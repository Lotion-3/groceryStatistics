"""Module B: hierarchical Bayesian spatial model of prices (Rao).

Data: log regular price of the products each chain carries widely (seen at
>= 80% of the chain's stores, at most 40 per chain: Module A's basket rule),
store-specific rows only, retailer-direct chains only (Instacart-sourced
Costco and the Kroger certification feed are analysed elsewhere).

Models (y = log regular price of product j at store s):
  M0  y = a_j + g_chain + u_s + e,         e ~ Normal(0, sigma)
  M1  same, e ~ Student-t(nu, 0, sigma)     (heavy-tailed residuals, cf. Module A)
  M2  M1 + f(location_s),  f ~ GP(0, Matern-3/2) via the Hilbert-space
      approximation (HSGP) on projected coordinates (km)
  a_j   product effects ~ N(mean log price, 2)       (absorbs each product's price level)
  g     chain effects, sum-to-zero; IDENTIFIED ONLY THROUGH PRODUCTS MATCHED BY
        UPC ACROSS CHAINS. Without >= 3 matched UPCs the chain term is omitted
        (it would be confounded with the product effects) and this is reported.
  u_s   store effects ~ N(0, sigma_u[chain])        (non-spatial store pricing)

Reported:
  * convergence: R-hat, bulk/tail ESS, divergences, per model
  * posterior predictive checks: SD of store-mean residual level, and the
    1% / 99% quantiles of within-product deviations, observed vs replicated
  * model comparison: PSIS-LOO (ELPD) with Pareto-k diagnostics
  * spatial share in M2: var_s(f) / (var_s(f) + sigma_u^2) across stores, per
    chain, i.e. how much of store-level pricing is a smooth geographic surface
  * a map of the posterior mean of f

Pointwise LOO leaves out one price, not one store; the store effect absorbs
most of that price's store-level information, so the LOO difference mostly
measures residual fit (t vs normal) and only partly the spatial term. The
spatial share is the more direct answer to "is there geographic structure".

PRELIMINARY, cross-sectional; associations only. Seeds fixed.
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, FIG, MUTED, SEED, TAB, add_deviations, attach_upcs, caption,
                             load_observations, main_snapshots, product_panel, sample_size_note, style)

DRAWS, TUNE, CHAINS = 1000, 1000, 4
BASKET_COVERAGE, BASKET_MAX = 0.80, 40
HSGP_M = (20, 20)       # basis functions per dimension
HSGP_C = 1.5            # boundary factor
MIN_SHARED_UPCS = 3


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def model_data(dev: pd.DataFrame) -> pd.DataFrame:
    """Rows for the model: widely carried products per chain, direct source only."""
    d = dev[(dev["source"] == "direct") & dev["regular_price"].gt(0) & dev["lat"].notna()].copy()
    keep = []
    for chain, g in d.groupby("chain"):
        n = g["store_pk"].nunique()
        cov = g.groupby("chain_product_id")["store_pk"].nunique().sort_values(ascending=False)
        keep += [(chain, p) for p in cov[cov >= BASKET_COVERAGE * n].index[:BASKET_MAX]]
    d = d[pd.MultiIndex.from_frame(d[["chain", "chain_product_id"]]).isin(keep)]
    d = attach_upcs(d)
    # A product is a UPC when one is confirmed (so it can be shared across
    # chains), otherwise the chain's own product id.
    d["product"] = np.where(d["upc"].notna(), "upc:" + d["upc"].astype(str),
                            d["chain"] + ":" + d["chain_product_id"].astype(str))
    d["y"] = np.log(d["regular_price"])
    return d.reset_index(drop=True)


def project_km(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Equirectangular projection to km around the sample's mean latitude.
    Distortion is small at the scale that matters for the GP (hundreds of km)."""
    lat0 = np.deg2rad(np.mean(lat))
    return np.column_stack([6371.0 * np.deg2rad(lon) * np.cos(lat0), 6371.0 * np.deg2rad(lat)])


def indices(d: pd.DataFrame) -> dict:
    prod_codes, prods = pd.factorize(d["product"], sort=True)
    store_codes, stores = pd.factorize(d["store_pk"], sort=True)
    chain_codes, chains = pd.factorize(d["chain"], sort=True)
    st = d.drop_duplicates("store_pk").set_index("store_pk").loc[stores]
    xy = project_km(st["lat"].to_numpy(float), st["lon"].to_numpy(float))
    shared = d.groupby("product")["chain"].nunique()
    return {"prod": prod_codes, "products": prods, "store": store_codes, "stores": stores,
            "chain": chain_codes, "chains": list(chains), "store_chain": pd.factorize(st["chain"], sort=True)[0],
            "xy": (xy - xy.mean(0)) / 1000.0,          # thousands of km, centred
            "n_shared_upcs": int((shared >= 2).sum()),
            "prod_mean": d.groupby(prod_codes)["y"].mean().to_numpy()}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def build(d: pd.DataFrame, ix: dict, spatial: bool, student_t: bool):
    import pymc as pm
    y = d["y"].to_numpy()
    n_chain = len(ix["chains"])
    use_chain = n_chain > 1 and ix["n_shared_upcs"] >= MIN_SHARED_UPCS
    coords = {"product": ix["products"], "store": ix["stores"].astype(str), "retailer": ix["chains"]}
    with pm.Model(coords=coords) as m:
        a = pm.Normal("a", mu=ix["prod_mean"], sigma=2.0, dims="product")
        mu = a[ix["prod"]]
        if use_chain:
            g_raw = pm.Normal("g_raw", 0.0, 0.5, shape=n_chain - 1)
            g = pm.Deterministic("g", pm.math.concatenate([g_raw, [-g_raw.sum()]]), dims="retailer")
            mu = mu + g[ix["chain"]]
        # Store effects: CENTRED (each store has ~30-40 precise prices, so the
        # data dominate and a centred parametrisation samples well) and
        # constrained to mean zero within each chain. Without the constraint,
        # adding c to every store effect and subtracting c from every product
        # effect leaves the likelihood unchanged -- a ridge that stalls NUTS
        # (R-hat 1.11 in simulation/validate_module_b.py before this change).
        sigma_u = pm.HalfNormal("sigma_u", 0.1, dims="retailer")
        u_raw = pm.Normal("u_raw", 0.0, sigma_u[ix["store_chain"]], dims="store")
        ind = np.eye(n_chain)[ix["store_chain"]]                     # stores x chains
        chain_mean = pm.math.dot(ind.T, u_raw) / ind.sum(axis=0)
        u = pm.Deterministic("u", u_raw - pm.math.dot(ind, chain_mean), dims="store")
        store_eff = u
        if spatial:
            ell = pm.InverseGamma("ell", alpha=3.0, beta=1.0)     # length-scale, thousands of km (prior mean 0.5)
            eta = pm.HalfNormal("eta", 0.1)                       # spatial SD, log-price units
            cov = eta ** 2 * pm.gp.cov.Matern32(2, ls=ell)
            gp = pm.gp.HSGP(m=list(HSGP_M), c=HSGP_C, cov_func=cov)
            f_raw = gp.prior("f_raw", X=ix["xy"])
            # centred over stores for the same reason (the field's mean is an intercept)
            f = pm.Deterministic("f", f_raw - f_raw.mean(), dims="store")
            store_eff = store_eff + f
        mu = mu + store_eff[ix["store"]]
        sigma = pm.HalfNormal("sigma", 0.2)
        if student_t:
            nu = pm.Gamma("nu", alpha=2.0, beta=0.1)
            pm.StudentT("y", nu=nu, mu=mu, sigma=sigma, observed=y)
        else:
            pm.Normal("y", mu=mu, sigma=sigma, observed=y)
    return m, use_chain


def fit(model, seed: int = SEED):
    import pymc as pm
    with model, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        idata = pm.sample(DRAWS, tune=TUNE, chains=CHAINS, target_accept=0.95, nuts_sampler="numpyro",
                          random_seed=seed, progressbar=False, idata_kwargs={"log_likelihood": True})
        pm.sample_posterior_predictive(idata, extend_inferencedata=True, random_seed=seed, progressbar=False)
    return idata


def diagnostics(name: str, idata) -> dict:
    import arviz as az
    vars_ = [v for v in ("a", "g", "sigma_u", "u", "sigma", "nu", "ell", "eta") if v in idata.posterior]
    s = az.summary(idata, var_names=vars_, kind="diagnostics")
    return {"model": name, "rhat_max": float(s["r_hat"].max()), "ess_bulk_min": float(s["ess_bulk"].min()),
            "ess_tail_min": float(s["ess_tail"].min()), "divergences": int(idata.sample_stats["diverging"].sum()),
            "share_rhat_gt_1.01": float((s["r_hat"] > 1.01).mean())}


# ---------------------------------------------------------------------------
# Posterior predictive checks
# ---------------------------------------------------------------------------

def _ppc_stats(y: np.ndarray, d: pd.DataFrame) -> dict:
    """Statistics a pricing model should reproduce: dispersion of store price
    levels, and the tails of within-product deviations."""
    dev = y - pd.Series(y).groupby(d["product"].to_numpy()).transform("median").to_numpy()
    store_level = pd.Series(dev).groupby(d["store_pk"].to_numpy()).mean()
    return {"sd_store_level": float(store_level.std()), "q01_dev": float(np.quantile(dev, 0.01)),
            "q99_dev": float(np.quantile(dev, 0.99)), "share_abs_dev_gt_0.1": float(np.mean(np.abs(dev) > 0.1))}


def ppc_table(name: str, idata, d: pd.DataFrame, n_rep: int = 200) -> list[dict]:
    obs = _ppc_stats(d["y"].to_numpy(), d)
    yrep = idata.posterior_predictive["y"].stack(s=("chain", "draw")).values   # (n_obs, n_samples)
    rng = np.random.default_rng(SEED)
    picks = rng.choice(yrep.shape[1], size=min(n_rep, yrep.shape[1]), replace=False)
    reps = pd.DataFrame([_ppc_stats(yrep[:, k], d) for k in picks])
    return [{"model": name, "statistic": k, "observed": v, "rep_q05": reps[k].quantile(0.05),
             "rep_median": reps[k].median(), "rep_q95": reps[k].quantile(0.95),
             "ppp": float(np.mean(reps[k] >= v))} for k, v in obs.items()]


def spatial_share(idata, ix: dict) -> pd.DataFrame:
    """Posterior of var_s(f_s) / (var_s(f_s) + sigma_u^2) across each chain's stores."""
    post = idata.posterior
    f = post["f"].stack(s=("chain", "draw")).values               # (stores, S)
    su = post["sigma_u"].stack(s=("chain", "draw")).values        # (chains, S)
    rows = []
    for k, c in enumerate(ix["chains"]):
        m = ix["store_chain"] == k
        vf = f[m].var(axis=0)
        share = vf / (vf + su[k] ** 2)
        rows.append({"chain": c, "stores": int(m.sum()), "spatial_share_mean": float(share.mean()),
                     "q05": float(np.quantile(share, 0.05)), "q95": float(np.quantile(share, 0.95)),
                     "sd_f_mean": float(np.sqrt(vf).mean()), "sigma_u_mean": float(su[k].mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------

def figures(d: pd.DataFrame, ix: dict, idata_sp, ppc: pd.DataFrame, note: str) -> list[str]:
    plt = style()
    out = []
    if idata_sp is not None:
        from analysis.module_c_hd import _diverging_cmap
        st = d.drop_duplicates("store_pk").set_index("store_pk").loc[ix["stores"]]
        fm = idata_sp.posterior["f"].mean(("chain", "draw")).values
        fig, ax = plt.subplots(figsize=(5.6, 3.4))
        lim = np.max(np.abs(fm)) or 1
        sc = ax.scatter(st["lon"], st["lat"], c=100 * fm, cmap=_diverging_cmap(), vmin=-100 * lim, vmax=100 * lim,
                        s=16, edgecolors="white", linewidths=0.4)
        fig.colorbar(sc, ax=ax, shrink=0.85, label="spatial effect f (% price level)")
        ax.set_title("Posterior mean of the spatial price surface (M2)", loc="left")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_aspect(1.25)
        caption(fig, note + " Points are stores (all chains share one surface).")
        fig.savefig(FIG / "fig_b1_spatial_surface.png")
        plt.close(fig)
        out.append("fig_b1_spatial_surface.png")
    if not ppc.empty:
        stats = list(dict.fromkeys(ppc["statistic"]))
        models = list(dict.fromkeys(ppc["model"]))
        fig, axes = plt.subplots(1, len(stats), figsize=(2.6 * len(stats), 2.6), squeeze=False)
        for ax, stat in zip(axes[0], stats):
            t = ppc[ppc["statistic"] == stat].set_index("model").loc[models]
            yy = np.arange(len(models))
            ax.hlines(yy, t["rep_q05"], t["rep_q95"], color=MUTED, linewidth=3, label="replicated 90%")
            ax.axvline(t["observed"].iloc[0], color=CHAIN_COLORS["target"], linewidth=1.5, label="observed")
            ax.set_yticks(yy, models)
            ax.invert_yaxis()
            ax.set_title(stat, fontsize=8)
        axes[0][0].legend(fontsize=6, loc="lower left")
        caption(fig, note)
        fig.savefig(FIG / "fig_b2_ppc.png")
        plt.close(fig)
        out.append("fig_b2_ppc.png")
    return out


def run(snaps: list[int] | None = None) -> str:
    import arviz as az
    from analysis.module_a_tails import MIN_STORES
    snaps = snaps or main_snapshots()[:1]
    if not snaps:
        return "Module B: no main snapshot configured in config/analysis.yaml yet."
    obs = load_observations(snapshot_id=snaps)
    dev = add_deviations(product_panel(obs, min_stores=MIN_STORES))
    d = model_data(dev) if not dev.empty else pd.DataFrame()
    if d.empty or d["store_pk"].nunique() < 30:
        return "Module B: too few stores for the spatial model."
    ix = indices(d)
    note = sample_size_note(d)
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)

    specs = {"M0_normal": (False, False), "M1_student_t": (False, True), "M2_t_spatial": (True, True)}
    fits, diag, ppc, chain_note = {}, [], [], None
    for name, (sp, t) in specs.items():
        model, use_chain = build(d, ix, spatial=sp, student_t=t)
        chain_note = ("chain effect estimated" if use_chain else
                      f"chain effect omitted: {ix['n_shared_upcs']} UPCs shared across chains (< {MIN_SHARED_UPCS})")
        fits[name] = fit(model)
        diag.append(diagnostics(name, fits[name]))
        ppc += ppc_table(name, fits[name], d)

    comp = az.compare(dict(fits))          # ArviZ >= 1: PSIS-LOO ELPD by default
    loo_k = {k: float((np.asarray(az.loo(v, pointwise=True).pareto_k) > 0.7).mean()) for k, v in fits.items()}
    comp["share_pareto_k_gt_0.7"] = comp.index.map(loo_k)
    params = az.summary(fits["M2_t_spatial"], var_names=[v for v in ("g", "sigma_u", "sigma", "nu", "ell", "eta")
                                                          if v in fits["M2_t_spatial"].posterior], hdi_prob=0.9)
    tables = {
        "module_b_data_summary": pd.DataFrame([{"rows": len(d), "stores": len(ix["stores"]),
                                                "products": len(ix["products"]), "chains": ",".join(ix["chains"]),
                                                "shared_upcs": ix["n_shared_upcs"], "chain_term": chain_note}]),
        "module_b_convergence": pd.DataFrame(diag),
        "module_b_ppc": pd.DataFrame(ppc),
        "module_b_loo_compare": comp.reset_index(names="model"),
        "module_b_m2_parameters": params.reset_index(names="parameter"),
        "module_b_spatial_share": spatial_share(fits["M2_t_spatial"], ix),
    }
    for name, t in tables.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    figs = figures(d, ix, fits["M2_t_spatial"], tables["module_b_ppc"], note)
    return f"Module B: wrote {len(tables)} tables and {len(figs)} figures ({chain_note}). {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
