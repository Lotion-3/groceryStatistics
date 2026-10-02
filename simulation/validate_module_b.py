"""SIMULATION ONLY -- synthetic prices with a known spatial structure.

Checks that Module B's models (analysis/module_b_bayes.py) recover what they
claim to measure before they are used on real prices:
  * the spatial share var_s(f) / (var_s(f) + sigma_u^2)
  * the GP length-scale and amplitude, the store-effect SD, the t degrees of freedom
  * that PSIS-LOO ranks M2 (t + spatial) > M1 (t) > M0 (normal) when the
    truth has heavy-tailed residuals and a spatial field

Design: 2 chains x 200 stores placed at REAL Target store locations (the
sampling frame, so the spatial geometry matches the study), 30 products per
chain with 10 shared across chains; a Matern-3/2 field (length-scale 500 km,
SD 0.05 log points), store effects SD 0.03, Student-t(4) residuals, scale 0.02.
These magnitudes are guesses at plausible values, not estimates.

Outputs: tables/simulation_module_b.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis import module_b_bayes as B  # noqa: E402

SEED = 20261002
TRUE = {"ell_1000km": 0.5, "eta": 0.05, "sigma_u": 0.03, "nu": 4.0, "sigma": 0.02}


def matern32(xy: np.ndarray, ell: float, eta: float) -> np.ndarray:
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
    r = np.sqrt(3) * d / ell
    return eta ** 2 * (1 + r) * np.exp(-r)


def simulate(n_stores: int = 200, n_prod: int = 30, n_shared: int = 10, seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    frame = pd.read_csv(ROOT / "data" / "processed" / "target_frame.csv").dropna(subset=["lat", "lon"])
    frame = frame[frame["lon"] > -130]                       # contiguous US + nearby
    locs = frame.sample(2 * n_stores, random_state=seed)[["lat", "lon"]].to_numpy()
    xy = B.project_km(locs[:, 0], locs[:, 1])
    xy = (xy - xy.mean(0)) / 1000.0
    K = matern32(xy, TRUE["ell_1000km"], TRUE["eta"]) + 1e-8 * np.eye(len(xy))
    f = np.linalg.cholesky(K) @ rng.normal(size=len(xy))
    u = TRUE["sigma_u"] * rng.normal(size=len(xy))
    rows = []
    shared = [f"upc:{k}" for k in range(n_shared)]
    base = {p: rng.uniform(np.log(2), np.log(15)) for p in shared}
    for c, chain in enumerate(("target", "walmart")):
        own = [f"{chain}:{k}" for k in range(n_prod - n_shared)]
        base.update({p: rng.uniform(np.log(2), np.log(15)) for p in own})
        g = 0.02 if chain == "target" else -0.02
        for s in range(c * n_stores, (c + 1) * n_stores):
            for p in shared + own:
                e = TRUE["sigma"] * rng.standard_t(TRUE["nu"])
                rows.append({"chain": chain, "store_pk": s, "lat": locs[s, 0], "lon": locs[s, 1], "product": p,
                             "y": base[p] + g + u[s] + f[s] + e})
    d = pd.DataFrame(rows)
    true_share = {chain: float(np.var(f[c * n_stores:(c + 1) * n_stores])
                               / (np.var(f[c * n_stores:(c + 1) * n_stores]) + TRUE["sigma_u"] ** 2))
                  for c, chain in enumerate(("target", "walmart"))}
    return d, true_share


def main() -> int:
    import arviz as az
    d, true_share = simulate()
    ix = B.indices(d)
    print(f"simulated {len(d):,} prices, {len(ix['stores'])} stores, {len(ix['products'])} products, "
          f"{ix['n_shared_upcs']} shared")
    fits = {}
    for name, (sp, t) in {"M0_normal": (False, False), "M1_student_t": (False, True),
                          "M2_t_spatial": (True, True)}.items():
        fits[name] = B.fit(B.build(d, ix, spatial=sp, student_t=t)[0], seed=SEED)
        print(name, B.diagnostics(name, fits[name]), flush=True)
    comp = az.compare(fits)                 # ArviZ >= 1: PSIS-LOO ELPD by default
    print(comp[["rank", "elpd", "elpd_diff", "dse"]])
    share = B.spatial_share(fits["M2_t_spatial"], ix)
    post = fits["M2_t_spatial"].posterior
    rows = [{"quantity": f"spatial_share_{r.chain}", "true": true_share[r.chain], "post_mean": r.spatial_share_mean,
             "q05": r.q05, "q95": r.q95} for r in share.itertuples()]
    for k, v in (("ell", "ell_1000km"), ("eta", "eta"), ("nu", "nu"), ("sigma", "sigma")):
        x = post[k].values.ravel()
        rows.append({"quantity": k, "true": TRUE[v], "post_mean": x.mean(),
                     "q05": np.quantile(x, 0.05), "q95": np.quantile(x, 0.95)})
    su = post["sigma_u"].values.reshape(-1, post["sigma_u"].shape[-1])
    for j, c in enumerate(ix["chains"]):
        rows.append({"quantity": f"sigma_u_{c}", "true": TRUE["sigma_u"], "post_mean": su[:, j].mean(),
                     "q05": np.quantile(su[:, j], 0.05), "q95": np.quantile(su[:, j], 0.95)})
    g = post["g"].values.reshape(-1, 2)
    for j, c in enumerate(ix["chains"]):
        rows.append({"quantity": f"chain_effect_{c}", "true": 0.02 if c == "target" else -0.02,
                     "post_mean": g[:, j].mean(), "q05": np.quantile(g[:, j], 0.05), "q95": np.quantile(g[:, j], 0.95)})
    out = pd.DataFrame(rows)
    out["covered_90"] = (out["q05"] <= out["true"]) & (out["true"] <= out["q95"])
    for name, r in comp.iterrows():
        out = pd.concat([out, pd.DataFrame([{"quantity": f"loo_rank_{name}", "true": np.nan,
                                             "post_mean": r["rank"], "q05": r["elpd"], "q95": r["elpd_diff"]}])])
    (ROOT / "tables").mkdir(exist_ok=True)
    out.to_csv(ROOT / "tables" / "simulation_module_b.csv", index=False)
    print(out.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
