"""Module B: hierarchical Bayesian models of store pricing, with space (Rao).

Data: log regular price of the products each chain carries widely (seen at
>= 80% of the chain's stores, at most 40 per chain: Module A's basket rule),
store-specific rows only, from retailer websites and Kroger's official
production API (Instacart-sourced Costco/ALDI and the Kroger test host are
analysed elsewhere),
contiguous US only (Hawaii/Alaska stores are excluded and counted; their
premia are reported by Module A).

What the data look like. Most store-product prices equal the chain's LIST
price exactly (89% for Walmart in a partial run of snapshot 2), and departures
are mostly upward. Models with one continuous residual cannot fit a point mass
plus a skewed tail: a Student-t residual drove its scale and df to their
bounds and did not converge (R-hat ~3), and a latent two-component mixture
suffered label switching (R-hat ~4). Whether a price is at list is OBSERVED,
so we use a two-part ("hurdle") model instead (DECISIONS #38).

  list_j   the chain's modal price of product j (to the cent)
  z_sj     1 if store s charges exactly list_j
  dl_sj    log(price / list_j), defined when z_sj = 0

Models
  M0  reference: y = a_j + g_chain + u_s + e,  e ~ Normal(0, sigma)
      (store effects centred, zero-mean within chain; chain effect g only
      when >= 3 UPCs are shared across chains, else confounded with a_j)
  M1  two-part:
        part 1  z_sj ~ Bernoulli(pi_s),   logit pi_s = alpha_chain + w_s,  w_s ~ N(0, sigma_w)
        part 2  dl_sj | z_sj = 0 ~ Student-t(nu, m_s, sigma1),  m_s = mu_dev_chain + u_s,
                u_s ~ N(0, sigma_u)
  M2  M1 + f(location_s) added to m_s,  f ~ GP(0, Matern-3/2), Hilbert-space
      approximation (HSGP) on projected coordinates
  Part 1 answers how OFTEN a store departs from its chain's list price; part 2
  answers by HOW MUCH when it does; M2 asks whether the latter is spatially
  smooth. Cross-chain differences in list prices are Module A's cross-chain
  table, not part of this model.

Reported
  * convergence for every model: R-hat, bulk/tail ESS, divergences
  * posterior predictive checks (incl. the share of prices exactly at list,
    which M0 cannot reproduce by construction)
  * PSIS-LOO of M1 vs M2 (same likelihood). M0 is not in the LOO comparison:
    it is a continuous density for y, the two-part models include a point mass.
  * spatial share in M2: var_s(f) / (var_s(f) + sigma_u^2) across stores
  * spatial check on part 1: Moran's I of the posterior mean of w_s (do stores
    that often depart from list cluster geographically?)
  * a map of the posterior mean of f

Validated on simulated data with a known answer: simulation/validate_module_b.py.
PRELIMINARY, cross-sectional; associations only. Seeds fixed.
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, FIG, MUTED, SEED, TAB, add_deviations, attach_upcs, caption,
                             load_observations, main_snapshots, product_panel, sample_size_note, style)

DRAWS = int(os.environ.get("GS_MODB_DRAWS", "1000"))     # 2000 for the final run (ESS target 400)
TUNE = int(os.environ.get("GS_MODB_TUNE", "1000"))
CHAINS = 4
BASKET_COVERAGE, BASKET_MAX = 0.80, 40
HSGP_M = (20, 20)       # basis functions per dimension
HSGP_C = 1.5            # boundary factor
MIN_SHARED_UPCS = 3
AT_LIST_TOL = 0.0005    # |log(price/list)| below this = same price to the cent
NON_CONTIGUOUS = ("HI", "AK")   # fitted area: contiguous US (+ DC)
MODEL_SOURCES = ("direct", "kroger")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def model_data(dev: pd.DataFrame) -> pd.DataFrame:
    """Rows for the model: widely carried products per chain, direct source only,
    with the chain's list (modal) price, the at-list indicator z and dl."""
    # Retailer websites and Kroger's official production API (source "kroger");
    # Instacart storefronts and the Kroger test host are analysed separately.
    d = dev[dev["source"].isin(MODEL_SOURCES) & dev["regular_price"].gt(0) & dev["lat"].notna()].copy()
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
    cents = d["regular_price"].round(2)
    d["list_price"] = cents.groupby([d["chain"], d["product"]]).transform(lambda s: s.mode().min())
    d["log_list"] = np.log(d["list_price"])
    d["dl"] = d["y"] - d["log_list"]
    d["z"] = (d["dl"].abs() < AT_LIST_TOL).astype(int)
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
            "store_lat": st["lat"].to_numpy(float), "store_lon": st["lon"].to_numpy(float),
            "xy": (xy - xy.mean(0)) / 1000.0,          # thousands of km, centred
            "n_shared_upcs": int((shared >= 2).sum()),
            "prod_mean": d.groupby(prod_codes)["y"].mean().to_numpy()}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _spatial_field(pm, ix: dict):
    """Centred HSGP Matern-3/2 field over store locations (thousands of km)."""
    ell = pm.InverseGamma("ell", alpha=3.0, beta=1.0)     # length-scale (prior mean 0.5 = 500 km)
    eta = pm.HalfNormal("eta", 0.1)                       # spatial SD, log-price units
    gp = pm.gp.HSGP(m=list(HSGP_M), c=HSGP_C, cov_func=eta ** 2 * pm.gp.cov.Matern32(2, ls=ell))
    f_raw = gp.prior("f_raw", X=ix["xy"])
    # centred over stores: the field's mean is an intercept
    return pm.Deterministic("f", f_raw - f_raw.mean(), dims="store")


def build_normal(d: pd.DataFrame, ix: dict):
    """M0 (reference)."""
    import pymc as pm
    n_chain = len(ix["chains"])
    use_chain = n_chain > 1 and ix["n_shared_upcs"] >= MIN_SHARED_UPCS
    sc = ix["store_chain"]
    coords = {"product": ix["products"], "store": ix["stores"].astype(str), "retailer": ix["chains"]}
    with pm.Model(coords=coords) as m:
        a = pm.Normal("a", mu=ix["prod_mean"], sigma=2.0, dims="product")
        mu = a[ix["prod"]]
        if use_chain:
            g_raw = pm.Normal("g_raw", 0.0, 0.5, shape=n_chain - 1)
            g = pm.Deterministic("g", pm.math.concatenate([g_raw, [-g_raw.sum()]]), dims="retailer")
            mu = mu + g[ix["chain"]]
        # Store effects CENTRED and zero-mean within chain: otherwise adding c
        # to every store effect and subtracting c from every product effect
        # leaves the likelihood unchanged (a ridge that stalls NUTS).
        sigma_u = pm.HalfNormal("sigma_u", 0.1, dims="retailer")
        u_raw = pm.Normal("u_raw", 0.0, sigma_u[sc], dims="store")
        ind = np.eye(n_chain)[sc]                                      # stores x chains
        u = pm.Deterministic("u", u_raw - pm.math.dot(ind, pm.math.dot(ind.T, u_raw) / ind.sum(axis=0)),
                             dims="store")
        sigma = pm.HalfNormal("sigma", 0.2)
        pm.Normal("y", mu=mu + u[ix["store"]], sigma=sigma, observed=d["y"].to_numpy())
    return m, use_chain


def build_two_part(d: pd.DataFrame, ix: dict, spatial: bool):
    """M1 / M2. Store effects NON-centred: each store has few departures, so
    the data say little about each w_s / u_s individually."""
    import pymc as pm
    sc = ix["store_chain"]
    dep = d["z"].to_numpy() == 0
    coords = {"store": ix["stores"].astype(str), "retailer": ix["chains"]}
    with pm.Model(coords=coords) as m:
        # Part 1: is the price at list?
        alpha = pm.Normal("alpha", 1.5, 1.5, dims="retailer")           # logit P(at list)
        sigma_w = pm.HalfNormal("sigma_w", 1.0, dims="retailer")
        w = pm.Deterministic("w", pm.Normal("w_z", 0.0, 1.0, dims="store") * sigma_w[sc], dims="store")
        logit_pi = alpha[sc] + w
        pm.Deterministic("pi_store", pm.math.sigmoid(logit_pi), dims="store")
        pm.Bernoulli("z", logit_p=logit_pi[ix["store"]], observed=d["z"].to_numpy())
        # Part 2: how far from list, when not at list?
        mu_dev = pm.Normal("mu_dev", 0.0, 0.2, dims="retailer")
        sigma_u = pm.HalfNormal("sigma_u", 0.1, dims="retailer")
        u = pm.Deterministic("u", pm.Normal("u_z", 0.0, 1.0, dims="store") * sigma_u[sc], dims="store")
        m_s = mu_dev[sc] + u + (_spatial_field(pm, ix) if spatial else 0.0)
        pm.Deterministic("m", m_s, dims="store")
        sigma1 = pm.HalfNormal("sigma1", 0.2)
        nu = pm.Deterministic("nu", 1.0 + pm.Gamma("nu_excess", alpha=2.0, beta=0.1))
        pm.StudentT("dl", nu=nu, mu=m_s[ix["store"][dep]], sigma=sigma1, observed=d["dl"].to_numpy()[dep])
    return m


def fit(model, seed: int = SEED, posterior_predictive: bool = False):
    import pymc as pm
    with model, warnings.catch_warnings():
        warnings.simplefilter("ignore")
        idata = pm.sample(DRAWS, tune=TUNE, chains=CHAINS, target_accept=0.95, nuts_sampler="numpyro",
                          random_seed=seed, progressbar=False, idata_kwargs={"log_likelihood": True})
        if posterior_predictive:
            pm.sample_posterior_predictive(idata, extend_inferencedata=True, random_seed=seed, progressbar=False)
    return idata


def diagnostics(name: str, idata) -> dict:
    import arviz as az
    vars_ = [v for v in ("a", "g", "sigma_u", "u", "sigma", "nu", "ell", "eta", "alpha", "sigma_w", "w",
                         "mu_dev", "sigma1") if v in idata.posterior]
    s = az.summary(idata, var_names=vars_, kind="diagnostics")
    return {"model": name, "rhat_max": float(s["r_hat"].max()), "ess_bulk_min": float(s["ess_bulk"].min()),
            "ess_tail_min": float(s["ess_tail"].min()), "divergences": int(idata.sample_stats["diverging"].sum()),
            "share_rhat_gt_1.01": float((s["r_hat"] > 1.01).mean())}


def pointwise_loglik(idata, d: pd.DataFrame) -> np.ndarray:
    """(chain, draw, n_rows) log-likelihood of each price under a two-part
    model: log p(z) plus, for prices off list, log p(dl | z = 0)."""
    ll = np.asarray(idata.log_likelihood["z"].values, float).copy()
    dep = np.flatnonzero(d["z"].to_numpy() == 0)
    ll[..., dep] += np.asarray(idata.log_likelihood["dl"].values, float)
    return ll


def loo_compare(fits: dict, d: pd.DataFrame) -> pd.DataFrame:
    """PSIS-LOO of the two-part models, on their combined pointwise likelihood."""
    import arviz as az
    wrapped = {}
    for name, idata in fits.items():
        ll = pointwise_loglik(idata, d)
        wrapped[name] = az.from_dict({"posterior": {"nu": np.asarray(idata.posterior["nu"].values)},
                                      "log_likelihood": {"y": ll},
                                      "observed_data": {"y": np.zeros(ll.shape[-1])}})
    comp = az.compare(wrapped)              # ArviZ >= 1: PSIS-LOO ELPD by default
    comp["share_pareto_k_gt_0.7"] = comp.index.map(
        {k: float((np.asarray(az.loo(v, pointwise=True).pareto_k) > 0.7).mean()) for k, v in wrapped.items()})
    return comp


# ---------------------------------------------------------------------------
# Posterior predictive checks
# ---------------------------------------------------------------------------

def _ppc_stats(y: np.ndarray, d: pd.DataFrame) -> dict:
    """Statistics a pricing model should reproduce: how many prices sit exactly
    at list, the dispersion of store price levels, and the deviation tails."""
    dl = y - d["log_list"].to_numpy()
    store_level = pd.Series(dl).groupby(d["store_pk"].to_numpy()).mean()
    return {"share_at_list": float(np.mean(np.abs(dl) < AT_LIST_TOL)), "sd_store_level": float(store_level.std()),
            "q01_dev": float(np.quantile(dl, 0.01)), "q99_dev": float(np.quantile(dl, 0.99)),
            "share_abs_dev_gt_0.1": float(np.mean(np.abs(dl) > 0.1))}


def _summarise_reps(name: str, obs: dict, reps: pd.DataFrame) -> list[dict]:
    return [{"model": name, "statistic": k, "observed": v, "rep_q05": reps[k].quantile(0.05),
             "rep_median": reps[k].median(), "rep_q95": reps[k].quantile(0.95),
             "ppp": float(np.mean(reps[k] >= v))} for k, v in obs.items()]


def ppc_normal(name: str, idata, d: pd.DataFrame, n_rep: int = 200) -> list[dict]:
    yrep = idata.posterior_predictive["y"].stack(s=("chain", "draw")).values      # (n, S)
    picks = np.random.default_rng(SEED).choice(yrep.shape[1], size=min(n_rep, yrep.shape[1]), replace=False)
    return _summarise_reps(name, _ppc_stats(d["y"].to_numpy(), d),
                           pd.DataFrame([_ppc_stats(yrep[:, k], d) for k in picks]))


def ppc_two_part(name: str, idata, d: pd.DataFrame, ix: dict, n_rep: int = 200) -> list[dict]:
    """Replicate whole datasets from posterior draws: z ~ Bernoulli(pi_s),
    dl ~ t(nu, m_s, sigma1); y_rep = log list + (1 - z) * dl."""
    post = idata.posterior
    pi = post["pi_store"].stack(s=("chain", "draw")).values           # (stores, S)
    m = post["m"].stack(s=("chain", "draw")).values
    nu = post["nu"].stack(s=("chain", "draw")).values
    s1 = post["sigma1"].stack(s=("chain", "draw")).values
    rng = np.random.default_rng(SEED)
    st, loglist = ix["store"], d["log_list"].to_numpy()
    reps = []
    for k in rng.choice(pi.shape[1], size=min(n_rep, pi.shape[1]), replace=False):
        z = rng.random(len(st)) < pi[st, k]
        dl = m[st, k] + s1[k] * rng.standard_t(nu[k], size=len(st))
        reps.append(_ppc_stats(loglist + np.where(z, 0.0, dl), d))
    return _summarise_reps(name, _ppc_stats(d["y"].to_numpy(), d), pd.DataFrame(reps))


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


def part1_spatial_check(idata, ix: dict) -> pd.DataFrame:
    """Moran's I (100 km) of each store's posterior mean departure propensity w_s."""
    from analysis.estimators import morans_i
    w = idata.posterior["w"].mean(("chain", "draw")).values
    rows = []
    for k, c in enumerate(ix["chains"]):
        m = ix["store_chain"] == k
        r = morans_i(ix["store_lat"][m], ix["store_lon"][m], w[m], radius_km=100.0, n_perm=4999, seed=SEED)
        rows.append({"chain": c, "stores": int(m.sum()), "morans_I": r["I"], "E_I": r.get("E_I"),
                     "p_value": r["p_value"], "neighbour_pairs": r["n_neighbour_pairs"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------

def figures(d: pd.DataFrame, ix: dict, idata_sp, ppc: pd.DataFrame, note: str) -> list[str]:
    plt = style()
    out = []
    if idata_sp is not None:
        from analysis.module_c_hd import _diverging_cmap
        fm = idata_sp.posterior["f"].mean(("chain", "draw")).values
        fig, ax = plt.subplots(figsize=(6.4, 3.4))
        lim = np.max(np.abs(fm)) or 1
        sc = ax.scatter(ix["store_lon"], ix["store_lat"], c=100 * fm, cmap=_diverging_cmap(),
                        vmin=-100 * lim, vmax=100 * lim, s=16, edgecolors="white", linewidths=0.4)
        fig.colorbar(sc, ax=ax, shrink=0.8, pad=0.03, label="effect on departure size (%)")
        ax.set_title("Where off-list prices are higher (M2, mean of f)", loc="left")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_aspect(1.25)
        caption(fig, note + " Points are stores; f shifts the size of departures from list price.")
        fig.savefig(FIG / "fig_b1_spatial_surface.png")
        plt.close(fig)
        out.append("fig_b1_spatial_surface.png")
    if not ppc.empty:
        stats = list(dict.fromkeys(ppc["statistic"]))
        models = list(dict.fromkeys(ppc["model"]))
        fig, axes = plt.subplots(1, len(stats), figsize=(2.5 * len(stats), 2.6), squeeze=False)
        for ax, stat in zip(axes[0], stats):
            t = ppc[ppc["statistic"] == stat].set_index("model").loc[models]
            yy = np.arange(len(models))
            ax.hlines(yy, t["rep_q05"], t["rep_q95"], color=MUTED, linewidth=3, label="replicated 90%")
            ax.axvline(t["observed"].iloc[0], color=CHAIN_COLORS["target"], linewidth=1.5, label="observed")
            ax.set_yticks(yy, models if ax is axes[0][0] else [""] * len(models))
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
    # Contiguous US only (DECISIONS #38): a smooth surface should not bridge
    # the ocean to Hawaii/Alaska, and one Honolulu store (prices up to +130%
    # over list) made the non-spatial model bimodal (store effect vs heavy tail).
    n_excl = int(d.loc[d["state"].isin(NON_CONTIGUOUS), "store_pk"].nunique()) if not d.empty else 0
    if not d.empty:
        d = d[~d["state"].isin(NON_CONTIGUOUS)].reset_index(drop=True)
    if d.empty or d["store_pk"].nunique() < 30:
        return "Module B: too few stores for the spatial model."
    if (d["z"] == 0).sum() < 30:
        return "Module B: fewer than 30 prices off list; the departure model is not identified."
    ix = indices(d)
    note = sample_size_note(d)
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)

    m0, use_chain = build_normal(d, ix)
    chain_note = ("chain effect estimated (M0)" if use_chain else
                  f"chain effect omitted: {ix['n_shared_upcs']} UPCs shared across chains (< {MIN_SHARED_UPCS})")
    fits = {"M0_normal": fit(m0, posterior_predictive=True),
            "M1_two_part": fit(build_two_part(d, ix, spatial=False)),
            "M2_two_part_spatial": fit(build_two_part(d, ix, spatial=True))}
    diag = [diagnostics(k, v) for k, v in fits.items()]
    ppc = (ppc_normal("M0_normal", fits["M0_normal"], d)
           + ppc_two_part("M1_two_part", fits["M1_two_part"], d, ix)
           + ppc_two_part("M2_two_part_spatial", fits["M2_two_part_spatial"], d, ix))
    m2 = fits["M2_two_part_spatial"]
    params = az.summary(m2, var_names=["alpha", "sigma_w", "mu_dev", "sigma_u", "sigma1", "nu", "ell", "eta"],
                        ci_prob=0.9, ci_kind="eti")     # ArviZ >= 1: 90% equal-tailed interval
    tables = {
        "module_b_data_summary": pd.DataFrame([{
            "rows": len(d), "stores": len(ix["stores"]), "products": len(ix["products"]),
            "chains": ",".join(ix["chains"]), "share_at_list": float(d["z"].mean()),
            "rows_off_list": int((d["z"] == 0).sum()), "share_off_list_upward": float((d.loc[d.z == 0, "dl"] > 0).mean()),
            "shared_upcs": ix["n_shared_upcs"], "chain_term": chain_note,
            "excluded_HI_AK_stores": n_excl}]),
        "module_b_convergence": pd.DataFrame(diag),
        "module_b_ppc": pd.DataFrame(ppc),
        "module_b_loo_compare": loo_compare({k: fits[k] for k in ("M1_two_part", "M2_two_part_spatial")}, d)
                                 .reset_index(names="model"),
        "module_b_m2_parameters": params.reset_index(names="parameter"),
        "module_b_spatial_share": spatial_share(m2, ix),
        "module_b_part1_spatial_check": part1_spatial_check(m2, ix),
    }
    for name, t in tables.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    figs = figures(d, ix, m2, tables["module_b_ppc"], note)
    return f"Module B: wrote {len(tables)} tables and {len(figs)} figures ({chain_note}). {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
