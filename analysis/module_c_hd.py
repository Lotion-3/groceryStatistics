"""Module C: high-dimensional structure (Song).

Part 1. What predicts a store's price level?
  Response: the store price index = mean of d_reg over the store's products
  (Module A), one value per store, within chain.
  Predictors (analysis/covariates.py): ACS neighbourhood variables, RUCA
  class, competitor distances, all standardised, PLUS their squares and
  pairwise interactions, PLUS state dummies. With ~250 stores this gives
  p ~ 100-150 predictors, a regime where OLS overfits and shrinkage matters.
  Models compared:
    mean        predict the training mean (baseline)
    ols_main    OLS on the main effects only (no squares/interactions/states)
    ols_full    minimum-norm least squares on everything (shows overfitting)
    lasso       LassoCV (inner 5-fold CV for the penalty)
    enet        ElasticNetCV (l1_ratio in {0.2, 0.5, 0.8})
    horseshoe   regularised horseshoe prior (Piironen & Vehtari 2017), PyMC
                with the NumPyro NUTS sampler; prediction = posterior mean
  Out-of-sample error from repeated K-fold CV BLOCKED BY STATE: every store
  of a held-out state is predicted by a model that never saw that state,
  which respects spatial dependence (neighbouring stores share unobserved
  local conditions). Selection: how often lasso / elastic net keep each
  predictor across folds; for the horseshoe, the 90% posterior interval.

Part 2. Low-rank structure of the store x product matrix of d_reg.
  EM-PCA (iterative SVD imputation) handles missing cells. The rank is chosen
  by hiding 10% of the observed cells and predicting them (repeated 5 times);
  rank 0 = product means only. Leading factors are interpreted through their
  product loadings (which categories load together) and through correlations
  of store scores with the covariates.

Cross-sectional associations only: nothing here is causal. PRELIMINARY.
"""
from __future__ import annotations

import itertools
import sys
import warnings

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, FIG, GRID, MUTED, SEED, TAB, add_deviations, caption,
                             load_observations, main_snapshots, product_panel, sample_size_note, style)
from analysis.covariates import LABELS, store_covariates

K_FOLDS = 5
N_REPEATS = 2
MIN_STORES_CHAIN = 60     # fit the regression only for chains with this many stores
HORSESHOE = True          # set False for a quick run (skips the slowest model)
MAX_RANK = 8


# ---------------------------------------------------------------------------
# Design matrix
# ---------------------------------------------------------------------------

def design(df: pd.DataFrame, chain: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    """(X, main-effect columns, all columns). Continuous predictors get squares
    and pairwise interactions; dummies (RUCA class, state) enter linearly."""
    dummies = ["suburban", "rural"]
    cont = [c for c in LABELS if c not in dummies and c != f"log_km_{chain}"
            and c in df and df[c].notna().mean() > 0.9]
    main = cont + [d for d in dummies if df[d].nunique() > 1]
    extra = {f"{c}^2": df[c] ** 2 for c in cont}
    extra.update({f"{a} x {b}": df[a] * df[b] for a, b in itertools.combinations(cont, 2)})
    states = pd.get_dummies(df["state"], prefix="state", dtype=float)
    X = pd.concat([df[main], pd.DataFrame(extra, index=df.index),
                   states.loc[:, states.sum() >= 3]], axis=1)       # states with >= 3 stores
    return X, main, list(X.columns)


def state_folds(groups: np.ndarray, k: int, seed: int):
    """K folds of whole states, states shuffled by `seed` (repeatable)."""
    rng = np.random.default_rng(seed)
    states = rng.permutation(np.unique(groups))
    fold_of = {s: i % k for i, s in enumerate(states)}
    f = np.array([fold_of[g] for g in groups])
    for i in range(k):
        yield np.flatnonzero(f != i), np.flatnonzero(f == i)


def _standardise(Xtr: np.ndarray, Xte: np.ndarray):
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    return (Xtr - mu) / sd, (Xte - mu) / sd


# ---------------------------------------------------------------------------
# Models: each takes standardised (Xtr, ytr, Xte) and returns (pred, coef)
# ---------------------------------------------------------------------------

def fit_mean(Xtr, ytr, Xte):
    return np.full(len(Xte), ytr.mean()), np.zeros(Xtr.shape[1])


def fit_ols(Xtr, ytr, Xte):
    """Minimum-norm least squares (pinv), so p > n does not fail."""
    A = np.column_stack([np.ones(len(Xtr)), Xtr])
    b = np.linalg.pinv(A) @ ytr
    return np.column_stack([np.ones(len(Xte)), Xte]) @ b, b[1:]


def fit_lasso(Xtr, ytr, Xte):
    from sklearn.linear_model import LassoCV
    m = LassoCV(cv=5, random_state=SEED, max_iter=20000).fit(Xtr, ytr)
    return m.predict(Xte), m.coef_


def fit_enet(Xtr, ytr, Xte):
    from sklearn.linear_model import ElasticNetCV
    m = ElasticNetCV(l1_ratio=[0.2, 0.5, 0.8], cv=5, random_state=SEED, max_iter=20000).fit(Xtr, ytr)
    return m.predict(Xte), m.coef_


def horseshoe_idata(Xtr: np.ndarray, ytr: np.ndarray, p0: int = 5, draws: int = 1000, seed: int = SEED,
                    tune: int = 1000, chains: int = 4):
    """Regularised horseshoe on standardised X and y (non-centred):
        beta_j = z_j * tau * lambda~_j,  lambda~_j^2 = c^2 lambda_j^2 / (c^2 + tau^2 lambda_j^2)
        z_j ~ N(0,1), lambda_j ~ C+(0,1), tau ~ C+(0, tau0), c^2 ~ InvGamma(2, 8)
    tau0 = p0/(p-p0)/sqrt(n) encodes a prior guess of ~p0 relevant predictors;
    the slab (c) keeps the few large coefficients from being unregularised."""
    import pymc as pm
    n, p = Xtr.shape
    ym, ys = ytr.mean(), ytr.std() or 1.0
    yz = (ytr - ym) / ys
    tau0 = p0 / max(p - p0, 1) / np.sqrt(n)
    with pm.Model() as model:
        tau = pm.HalfCauchy("tau", beta=tau0)
        lam = pm.HalfCauchy("lam", beta=1.0, shape=p)
        c2 = pm.InverseGamma("c2", alpha=2.0, beta=8.0)          # slab scale ~2 (sd units), df = 4
        lam_t = pm.math.sqrt(c2 * lam ** 2 / (c2 + tau ** 2 * lam ** 2))
        z = pm.Normal("z", 0.0, 1.0, shape=p)
        beta = pm.Deterministic("beta", z * tau * lam_t)
        a = pm.Normal("a", 0.0, 1.0)
        sigma = pm.HalfNormal("sigma", 1.0)
        pm.Normal("y", a + pm.math.dot(Xtr, beta), sigma, observed=yz)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            idata = pm.sample(draws, tune=tune, chains=chains, target_accept=0.99, nuts_sampler="numpyro",
                              random_seed=seed, progressbar=False)
    return idata, ym, ys


def fit_horseshoe(Xtr, ytr, Xte):
    # Inside cross-validation only the posterior mean is used for prediction,
    # so a lighter run suffices; the reported full-data fit keeps 4 x 1000.
    idata, ym, ys = horseshoe_idata(Xtr, ytr, draws=500, tune=500, chains=2)
    post = idata.posterior
    b = post["beta"].mean(("chain", "draw")).values
    a = float(post["a"].mean())
    return ym + ys * (a + Xte @ b), ys * b


MODELS = {"mean": fit_mean, "ols_main": fit_ols, "ols_full": fit_ols,
          "lasso": fit_lasso, "enet": fit_enet, "horseshoe": fit_horseshoe}


def cv_compare(X: pd.DataFrame, main: list[str], y: np.ndarray, groups: np.ndarray,
               models: dict = MODELS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-fold errors, selection frequencies)."""
    errs, sel = [], {m: np.zeros(X.shape[1]) for m in ("lasso", "enet")}
    n_fits = 0
    for r in range(N_REPEATS):
        for f, (tr, te) in enumerate(state_folds(groups, K_FOLDS, SEED + r)):
            for name, fn in models.items():
                cols = main if name == "ols_main" else list(X.columns)
                Xtr, Xte = _standardise(X.iloc[tr][cols].to_numpy(float), X.iloc[te][cols].to_numpy(float))
                pred, coef = fn(Xtr, y[tr], Xte)
                errs.append({"repeat": r, "fold": f, "model": name, "n_test": len(te),
                             "mse": float(np.mean((y[te] - pred) ** 2))})
                if name in sel:
                    sel[name] += np.abs(coef) > 1e-10
            n_fits += 1
    sel_df = pd.DataFrame({"predictor": X.columns, **{f"selfreq_{m}": v / n_fits for m, v in sel.items()}})
    return pd.DataFrame(errs), sel_df


def summarise_cv(errs: pd.DataFrame, y_var: float) -> pd.DataFrame:
    """RMSE per fold, then mean and SD over folds; out-of-sample R^2 vs the
    total variance of the index."""
    e = errs.assign(rmse=np.sqrt(errs["mse"]))
    s = e.groupby("model").agg(rmse_mean=("rmse", "mean"), rmse_sd=("rmse", "std"), mse_mean=("mse", "mean"),
                               folds=("rmse", "size")).reset_index()
    s["oos_r2"] = 1 - s["mse_mean"] / y_var
    order = list(MODELS)
    return s.sort_values("model", key=lambda c: c.map(order.index))


def full_fit_coefs(X: pd.DataFrame, main: list[str], y: np.ndarray) -> pd.DataFrame:
    """Coefficients (per SD of each predictor, in units of the index) from fits
    on all stores: OLS on main effects, lasso, elastic net, horseshoe with a 90% interval."""
    Xs, _ = _standardise(X.to_numpy(float), X.to_numpy(float))
    out = pd.DataFrame({"predictor": X.columns})
    out["label"] = out["predictor"].map(lambda c: LABELS.get(c, c))
    Xm, _ = _standardise(X[main].to_numpy(float), X[main].to_numpy(float))
    out["ols_main"] = out["predictor"].map(dict(zip(main, fit_ols(Xm, y, Xm)[1])))
    out["lasso"] = fit_lasso(Xs, y, Xs)[1]
    out["enet"] = fit_enet(Xs, y, Xs)[1]
    if HORSESHOE:
        import arviz as az
        idata, ym, ys = horseshoe_idata(Xs, y)
        b = idata.posterior["beta"] * ys
        out["hs_mean"] = b.mean(("chain", "draw")).values
        q = b.quantile([0.05, 0.95], dim=("chain", "draw")).values
        out["hs_q05"], out["hs_q95"] = q[0], q[1]
        out["hs_interval_excludes_0"] = (out["hs_q05"] > 0) | (out["hs_q95"] < 0)
        summ = az.summary(idata, var_names=["beta", "tau", "sigma"], kind="diagnostics")
        out.attrs["rhat_max"] = float(summ["r_hat"].max())
        out.attrs["ess_bulk_min"] = float(summ["ess_bulk"].min())
        out.attrs["divergences"] = int(idata.sample_stats["diverging"].sum())
    return out


# ---------------------------------------------------------------------------
# Part 2: factor model
# ---------------------------------------------------------------------------

def em_pca(Y: np.ndarray, rank: int, iters: int = 300, tol: float = 1e-7):
    """Rank-r reconstruction of a matrix with NaNs (rows = stores, cols =
    products). Start from column means; repeat: SVD of the column-centred
    filled matrix, rebuild with r components, refill ONLY the missing cells.
    Returns (reconstruction, U, s, Vt, column means)."""
    Y = np.asarray(Y, float)
    miss = np.isnan(Y)
    mu = np.nanmean(Y, axis=0)
    F = np.where(miss, mu, Y)
    U = s = Vt = None
    for _ in range(iters):
        mu = F.mean(axis=0)
        if rank == 0:
            R = np.broadcast_to(mu, F.shape).copy()
        else:
            U, s, Vt = np.linalg.svd(F - mu, full_matrices=False)
            R = mu + (U[:, :rank] * s[:rank]) @ Vt[:rank]
        newF = np.where(miss, R, Y)
        delta = np.sum((newF - F) ** 2) / max(np.sum(F ** 2), 1e-12)
        F = newF
        if delta < tol:
            break
    return R, U, s, Vt, mu


def rank_cv(Y: np.ndarray, max_rank: int = MAX_RANK, frac: float = 0.10, repeats: int = 5,
            seed: int = SEED) -> pd.DataFrame:
    """Held-out MSE by rank: hide `frac` of observed cells, fit, predict them."""
    rng = np.random.default_rng(seed)
    obs = np.argwhere(~np.isnan(Y))
    rows = []
    for rep in range(repeats):
        hide = obs[rng.random(len(obs)) < frac]
        Yt = Y.copy()
        Yt[hide[:, 0], hide[:, 1]] = np.nan
        truth = Y[hide[:, 0], hide[:, 1]]
        for r in range(0, max_rank + 1):
            R = em_pca(Yt, r)[0]
            rows.append({"repeat": rep, "rank": r, "mse": float(np.mean((R[hide[:, 0], hide[:, 1]] - truth) ** 2))})
    return pd.DataFrame(rows).groupby("rank")["mse"].agg(["mean", "std"]).reset_index()


def store_product_matrix(dev: pd.DataFrame, chain: str, min_cov: float = 0.5) -> pd.DataFrame:
    """Stores x products of d_reg for one chain, keeping products seen at >=
    min_cov of the stores and stores that carry >= min_cov of those products."""
    g = dev[dev["chain"] == chain]
    M = g.pivot_table(index="store_pk", columns="chain_product_id", values="d_reg", aggfunc="first")
    M = M.loc[:, M.notna().mean() >= min_cov]
    return M.loc[M.notna().mean(axis=1) >= min_cov]


def factor_analysis(dev: pd.DataFrame, cov: pd.DataFrame, chain: str):
    M = store_product_matrix(dev, chain)
    if M.shape[0] < 30 or M.shape[1] < 10:
        return None
    cv = rank_cv(M.to_numpy())
    best = int(cv.loc[cv["mean"].idxmin(), "rank"])
    # one-standard-error rule: the smallest rank within 1 SE of the best
    se_best = cv.loc[cv["rank"] == best, "std"].iloc[0] / np.sqrt(5)
    r1se = int(cv.loc[cv["mean"] <= cv["mean"].min() + se_best, "rank"].min())
    r = max(best, 2)    # always keep 2 components for interpretation; the chosen rank is reported
    R, U, s, Vt, mu = em_pca(M.to_numpy(), r)
    var_share = s ** 2 / np.sum(s ** 2)
    names = dev.drop_duplicates("chain_product_id").set_index("chain_product_id")
    load = pd.DataFrame({"chain": chain, "chain_product_id": M.columns,
                         "product_name": names.loc[M.columns, "product_name"].values,
                         "category": names.loc[M.columns, "category"].values})
    scores = pd.DataFrame({"chain": chain, "store_pk": M.index})
    for k in range(2):
        load[f"loading_{k + 1}"] = Vt[k]
        scores[f"score_{k + 1}"] = U[:, k] * s[k]
    # Interpretation: rank correlations of store scores with covariates.
    sc = scores.merge(cov, on="store_pk", how="left")
    corr = [{"chain": chain, "factor": k + 1, "covariate": c, "label": LABELS[c],
             "spearman": sc[f"score_{k + 1}"].corr(sc[c], method="spearman"), "n": int(sc[c].notna().sum())}
            for k in range(2) for c in LABELS if c in sc and sc[c].notna().sum() >= 20]
    summary = {"chain": chain, "stores": M.shape[0], "products": M.shape[1],
               "share_observed": float(M.notna().mean().mean()), "rank_cv_min": best, "rank_1se": r1se,
               "var_share_f1": float(var_share[0]), "var_share_f2": float(var_share[1]),
               # Two factors are always fitted for description; when CV prefers
               # rank 0 they do not predict held-out cells and must not be
               # interpreted as structure.
               "note": ("CV chose rank 0: factors descriptive only, not supported by held-out fit"
                        if best == 0 else "")}
    return summary, cv.assign(chain=chain), load, scores.merge(cov[["store_pk", "lat", "lon"]], on="store_pk"), \
        pd.DataFrame(corr)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def _diverging_cmap():
    from matplotlib.colors import LinearSegmentedColormap
    # two hues + neutral grey midpoint (never a hue at the midpoint)
    return LinearSegmentedColormap.from_list("bgo", ["#1c5cab", "#d9d8d2", "#c24a1c"])


def figures(cvsum: pd.DataFrame, coefs: dict, rank_tabs: pd.DataFrame, scores: pd.DataFrame, note: str) -> list[str]:
    plt = style()
    out = []
    chains = [c for c in CHAIN_COLORS if c in set(cvsum["chain"])]
    if chains:
        fig, axes = plt.subplots(1, len(chains), figsize=(3.6 * len(chains), 2.8), sharey=True, squeeze=False)
        for ax, c in zip(axes[0], chains):
            t = cvsum[cvsum["chain"] == c].reset_index(drop=True)
            ax.errorbar(t["rmse_mean"], range(len(t)), xerr=t["rmse_sd"], fmt="o", color=CHAIN_COLORS[c],
                        ecolor=MUTED, elinewidth=1, capsize=0, markersize=6)
            ax.set_yticks(range(len(t)), t["model"])
            ax.invert_yaxis()
            ax.set_title(f"{c.capitalize()}: out-of-sample RMSE")
            ax.set_xlabel("RMSE of store index (± 1 SD over folds)")
        caption(fig, note + f" CV: {K_FOLDS} folds of whole states x {N_REPEATS} repeats.")
        fig.savefig(FIG / "fig_c1_cv_rmse.png")
        plt.close(fig)
        out.append("fig_c1_cv_rmse.png")

    hs = {c: t for c, t in coefs.items() if "hs_mean" in t}
    if hs:
        fig, axes = plt.subplots(1, len(hs), figsize=(4.6 * len(hs), 4.2), squeeze=False)
        for ax, (c, t) in zip(axes[0], hs.items()):
            top = t.reindex(t["hs_mean"].abs().sort_values(ascending=False).index).head(12).iloc[::-1]
            y = np.arange(len(top))
            ax.axvline(0, color=GRID, linewidth=1)
            ax.hlines(y, top["hs_q05"], top["hs_q95"], color=CHAIN_COLORS[c], linewidth=2)
            ax.plot(top["hs_mean"], y, "o", color=CHAIN_COLORS[c], markersize=6, label="horseshoe mean, 90% interval")
            ax.plot(top["lasso"], y, "x", color=MUTED, markersize=6, label="lasso")
            ax.set_yticks(y, [str(l)[:38] for l in top["label"]], fontsize=7)
            ax.set_title(f"{c.capitalize()}: largest effects (per SD)")
            ax.set_xlabel("change in store index per SD of predictor")
            ax.legend(fontsize=7, loc="lower right")
        caption(fig, note)
        fig.savefig(FIG / "fig_c2_coefficients.png")
        plt.close(fig)
        out.append("fig_c2_coefficients.png")

    if not rank_tabs.empty:
        fig, ax = plt.subplots(figsize=(4.4, 3.0))
        for c, t in rank_tabs.groupby("chain"):
            ax.errorbar(t["rank"], t["mean"], yerr=t["std"], color=CHAIN_COLORS.get(c, MUTED), marker="o",
                        markersize=4, capsize=0, label=c.capitalize())
        ax.set_xlabel("rank (0 = product means only)")
        ax.set_ylabel("held-out MSE of d")
        ax.set_title("Choosing the number of factors (10% of cells held out)", loc="left")
        ax.legend(fontsize=7)
        caption(fig, note)
        fig.savefig(FIG / "fig_c3_factor_rank_cv.png")
        plt.close(fig)
        out.append("fig_c3_factor_rank_cv.png")

    if not scores.empty:
        sch = [c for c in CHAIN_COLORS if c in set(scores["chain"])]
        fig, axes = plt.subplots(1, len(sch), figsize=(4.6 * len(sch), 3.0), squeeze=False)
        for ax, c in zip(axes[0], sch):
            t = scores[scores["chain"] == c]
            lim = np.nanquantile(np.abs(t["score_1"]), 0.98) or 1
            sc = ax.scatter(t["lon"], t["lat"], c=t["score_1"], cmap=_diverging_cmap(), vmin=-lim, vmax=lim,
                            s=14, edgecolors="white", linewidths=0.4)
            ax.set_title(f"{c.capitalize()}: store scores on factor 1")
            ax.set_xlabel("longitude")
            ax.set_ylabel("latitude")
            ax.set_aspect(1.25)
            fig.colorbar(sc, ax=ax, shrink=0.8, label="factor 1 score")
        caption(fig, note + " Sign of a factor is arbitrary; read with the loadings table.")
        fig.savefig(FIG / "fig_c4_factor_map.png")
        plt.close(fig)
        out.append("fig_c4_factor_map.png")
    return out


# ---------------------------------------------------------------------------

def run(snaps: list[int] | None = None) -> str:
    from analysis.module_a_tails import MIN_STORES, store_index
    snaps = snaps or main_snapshots()[:1]
    if not snaps:
        return "Module C: no main snapshot configured in config/analysis.yaml yet."
    obs = load_observations(snapshot_id=snaps)
    dev = add_deviations(product_panel(obs, min_stores=MIN_STORES))
    if dev.empty:
        return "Module C: no products observed at enough stores."
    note = sample_size_note(dev)
    idx = store_index(dev)
    stores = obs.drop_duplicates("store_pk")[["store_pk", "chain", "zip", "lat", "lon", "urbanicity", "state", "region"]]
    cov = store_covariates(stores)
    data = idx.merge(cov.drop(columns=["chain", "lat", "lon", "state", "region", "urbanicity"]), on="store_pk")
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)

    cv_rows, sel_rows, coef_tabs, diag = [], [], {}, []
    # Kroger's test host (kroger_ce) is not a chain for analysis (DECISIONS #39).
    for chain, g in data[data["chain"] != "kroger_ce"].groupby("chain"):
        X, main, _ = design(g, chain)
        ok = X.notna().all(axis=1).to_numpy() & g["index"].notna().to_numpy()
        X, y, groups = X[ok], g["index"].to_numpy()[ok], g["state"].to_numpy()[ok]
        diag.append({"chain": chain, "stores": len(g), "stores_complete_covariates": int(ok.sum()),
                     "predictors_main": len(main), "predictors_full": X.shape[1], "states": len(np.unique(groups))})
        if ok.sum() < MIN_STORES_CHAIN or len(np.unique(groups)) < K_FOLDS:
            continue
        models = {k: v for k, v in MODELS.items() if HORSESHOE or k != "horseshoe"}
        errs, sel = cv_compare(X, main, y, groups, models)
        cv_rows.append(summarise_cv(errs, float(np.var(y))).assign(chain=chain, n_stores=len(y), p=X.shape[1]))
        coefs = full_fit_coefs(X, main, y).merge(sel, on="predictor")
        coefs.insert(0, "chain", chain)
        coef_tabs[chain] = coefs
        diag[-1].update({"horseshoe_rhat_max": coefs.attrs.get("rhat_max"),
                         "horseshoe_ess_bulk_min": coefs.attrs.get("ess_bulk_min"),
                         "horseshoe_divergences": coefs.attrs.get("divergences")})

    fac = [factor_analysis(dev, cov, c) for c in sorted(dev["chain"].unique())]
    fac = [f for f in fac if f]
    cvsum = pd.concat(cv_rows, ignore_index=True) if cv_rows else pd.DataFrame(columns=["chain"])
    tables = {
        "module_c_design_summary": pd.DataFrame(diag),
        "module_c_cv_rmse": cvsum,
        "module_c_coefficients": pd.concat(coef_tabs.values(), ignore_index=True) if coef_tabs else pd.DataFrame(),
        "module_c_factor_summary": pd.DataFrame([f[0] for f in fac]),
        "module_c_factor_rank_cv": pd.concat([f[1] for f in fac], ignore_index=True) if fac else pd.DataFrame(),
        "module_c_factor_loadings": pd.concat([f[2] for f in fac], ignore_index=True) if fac else pd.DataFrame(),
        "module_c_factor_scores": pd.concat([f[3] for f in fac], ignore_index=True) if fac else pd.DataFrame(),
        "module_c_factor_covariate_corr": pd.concat([f[4] for f in fac], ignore_index=True) if fac else pd.DataFrame(),
    }
    for name, t in tables.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    figs = figures(cvsum, coef_tabs, tables["module_c_factor_rank_cv"], tables["module_c_factor_scores"], note)
    return f"Module C: wrote {len(tables)} tables and {len(figs)} figures. {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
