"""SIMULATION ONLY -- synthetic prices with a known structure.

Checks that Module B's models (analysis/module_b_bayes.py) recover what they
claim to measure before they are used on real prices.

Data-generating process (the hurdle model, DECISIONS #38), chosen to look like
the real data (most prices exactly at the chain's list price, departures
mostly upward):
  * 2 chains x 200 stores at REAL Target store locations (the sampling frame,
    so the spatial geometry matches the study); 30 products per chain, 10
    shared across chains (UPC-matched), chain effects +-0.02
  * store s charges the list price for a product with probability pi_s,
    logit pi_s = 2.0 + w_s, w_s ~ N(0, 0.5)   (about 87% at list)
  * otherwise log price = list + m_s + 0.03 * t_4,
    m_s = 0.05 + u_s + f_s,  u_s ~ N(0, 0.03),
    f ~ Matern-3/2 GP (length-scale 500 km, SD 0.05)
  * list-price prices carry 1-cent rounding noise (SD 0.001 in logs)
These magnitudes are guesses at plausible values, not estimates.

Checked: convergence of all three models; recovery of mu_dev, sigma_u, nu,
sigma1, alpha, sigma_w, eta, ell, the spatial share (two-part M2) and the
chain effects (M0); the LOO ranking of M1 vs M2.

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
TRUE = {"alpha": 2.0, "sigma_w": 0.5, "mu_dev": 0.05, "sigma_u": 0.03, "nu": 4.0, "sigma1": 0.03,
        "ell_1000km": 0.5, "eta": 0.05}


def matern32(xy: np.ndarray, ell: float, eta: float) -> np.ndarray:
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
    r = np.sqrt(3) * d / ell
    return eta ** 2 * (1 + r) * np.exp(-r)


def simulate(n_stores: int = 200, n_prod: int = 30, n_shared: int = 10, seed: int = SEED):
    rng = np.random.default_rng(seed)
    frame = pd.read_csv(ROOT / "data" / "processed" / "target_frame.csv").dropna(subset=["lat", "lon"])
    frame = frame[frame["lon"] > -130]                       # contiguous US
    locs = frame.sample(2 * n_stores, random_state=seed)[["lat", "lon"]].to_numpy()
    xy = B.project_km(locs[:, 0], locs[:, 1])
    xy = (xy - xy.mean(0)) / 1000.0
    K = matern32(xy, TRUE["ell_1000km"], TRUE["eta"]) + 1e-8 * np.eye(len(xy))
    f = np.linalg.cholesky(K) @ rng.normal(size=len(xy))
    f -= f.mean()
    u = TRUE["sigma_u"] * rng.normal(size=len(xy))
    w = TRUE["sigma_w"] * rng.normal(size=len(xy))
    pi = 1 / (1 + np.exp(-(TRUE["alpha"] + w)))
    m = TRUE["mu_dev"] + u + f
    shared = [f"upc:{k}" for k in range(n_shared)]
    base = {p: rng.uniform(np.log(2), np.log(15)) for p in shared}
    rows = []
    for c, chain in enumerate(("target", "walmart")):
        own = [f"{chain}:{k}" for k in range(n_prod - n_shared)]
        base.update({p: rng.uniform(np.log(2), np.log(15)) for p in own})
        g = 0.02 if chain == "target" else -0.02
        for s in range(c * n_stores, (c + 1) * n_stores):
            for p in shared + own:
                at_list = rng.random() < pi[s]
                dl = 0.0 if at_list else m[s] + TRUE["sigma1"] * rng.standard_t(TRUE["nu"])
                rows.append({"chain": chain, "store_pk": s, "lat": locs[s, 0], "lon": locs[s, 1],
                             "product": p, "log_list": base[p] + g, "y": base[p] + g + dl,
                             "dl": dl, "z": int(at_list)})
    d = pd.DataFrame(rows)
    true_share = {}
    for c, chain in enumerate(("target", "walmart")):
        vf = np.var(f[c * n_stores:(c + 1) * n_stores])
        true_share[chain] = float(vf / (vf + TRUE["sigma_u"] ** 2))
    return d, true_share


def main() -> int:
    import arviz as az
    d, true_share = simulate()
    ix = B.indices(d)
    print(f"simulated {len(d):,} prices, {len(ix['stores'])} stores, {len(ix['products'])} products, "
          f"{ix['n_shared_upcs']} shared; share at list price {d['z'].mean():.2f}")
    fits = {"M0_normal": B.fit(B.build_normal(d, ix)[0], seed=SEED),
            "M1_two_part": B.fit(B.build_two_part(d, ix, spatial=False), seed=SEED),
            "M2_two_part_spatial": B.fit(B.build_two_part(d, ix, spatial=True), seed=SEED)}
    for name, idata in fits.items():
        print(name, B.diagnostics(name, idata), flush=True)
    comp = B.loo_compare({k: fits[k] for k in ("M1_two_part", "M2_two_part_spatial")}, d)
    print(comp[["rank", "elpd", "elpd_diff", "dse"]])
    post = fits["M2_two_part_spatial"].posterior

    def q(x):
        x = np.asarray(x).ravel()
        return x.mean(), np.quantile(x, 0.05), np.quantile(x, 0.95)

    rows = []
    for r in B.spatial_share(fits["M2_two_part_spatial"], ix).itertuples():
        rows.append({"quantity": f"spatial_share_{r.chain}", "true": true_share[r.chain],
                     "post_mean": r.spatial_share_mean, "q05": r.q05, "q95": r.q95})
    for k, t in (("ell", "ell_1000km"), ("eta", "eta"), ("nu", "nu"), ("sigma1", "sigma1")):
        mn, lo, hi = q(post[k].values)
        rows.append({"quantity": k, "true": TRUE[t], "post_mean": mn, "q05": lo, "q95": hi})
    for k in ("alpha", "sigma_w", "mu_dev", "sigma_u"):
        v = post[k].values.reshape(-1, post[k].shape[-1])
        for j, c in enumerate(ix["chains"]):
            mn, lo, hi = q(v[:, j])
            rows.append({"quantity": f"{k}_{c}", "true": TRUE[k], "post_mean": mn, "q05": lo, "q95": hi})
    gv = fits["M0_normal"].posterior["g"].values.reshape(-1, 2)      # chain effects live in M0
    for j, c in enumerate(ix["chains"]):
        mn, lo, hi = q(gv[:, j])
        rows.append({"quantity": f"chain_effect_{c}", "true": 0.02 if c == "target" else -0.02,
                     "post_mean": mn, "q05": lo, "q95": hi})
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
