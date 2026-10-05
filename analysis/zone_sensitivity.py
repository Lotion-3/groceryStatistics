"""Robustness of the Dirichlet-process zones (Module E, Plan Q2).

The zone model treats products as independent within a zone, so its posterior
over the number of zones is probably overconfident. Two checks that do not
rely on that posterior:

  1. Prior sensitivity. Refit with gamma (strength of the pull toward the
     chain-wide price pattern) in GAMMAS; report the number of zones and the
     adjusted Rand index (ARI) of each partition with the gamma = 1 partition.
  2. Split-half replication. Split the chain's products at random into two
     disjoint halves and fit each half separately. If the zones are real, two
     independent sets of products recover the same zones: report the ARI
     between halves (and with the full-data partition), over N_SPLITS splits.

Contiguous US; regular prices; products seen at >= 10 stores. Slow (many
fits): run with `python -m analysis.zone_sensitivity`.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import SEED, TAB, load_observations, main_snapshots, product_panel
from analysis.module_e_architecture import chain_matrix
from analysis.zone_model import adjusted_rand, fit_zones

CHAINS = ("aldi", "walmart", "costco", "kroger", "meijer")
GAMMAS = (0.5, 1.0, 5.0)
N_SPLITS = 2
SWEEPS = dict(n_sweeps=300, burn=100, thin=4)


def run(snaps: list[int] | None = None, chains=CHAINS) -> str:
    """Writes tables/zone_sensitivity_{prior,split_half}_<chain>.csv after each
    chain (so a long run keeps what it finished)."""
    snaps = snaps or main_snapshots()[:1]
    obs = load_observations(snapshot_id=snaps)
    p = product_panel(obs, min_stores=10)
    p = p[p["chain"].isin(CHAINS) & ~p["state"].isin(["HI", "AK"]) & p["lat"].notna()].copy()
    p["cents"] = p["regular_price"].round(2)
    rng = np.random.default_rng(SEED)
    prior_rows, split_rows = [], []
    for chain in chains:
        st, M = chain_matrix(p, chain)
        if len(st) < 15:
            continue
        A = M.to_numpy(float)
        fits = {g: fit_zones(A, gamma=g, seed=SEED, **SWEEPS) for g in GAMMAS}
        ref = fits[1.0]["partition"]
        for g, r in fits.items():
            z = r["partition"]
            prior_rows.append({"chain": chain, "stores": len(st), "gamma": g,
                               "zones_ge2": int((np.bincount(z) >= 2).sum()),
                               "zones_post_mean": float(r["k_ge2"].mean()),
                               "ari_vs_gamma1": adjusted_rand(ref, z), "start_agreement_ari": r["start_agreement_ari"]})
        for k in range(N_SPLITS):
            perm = rng.permutation(A.shape[1])
            h1, h2 = perm[: len(perm) // 2], perm[len(perm) // 2:]
            z1 = fit_zones(A[:, h1], seed=SEED + k, **SWEEPS)["partition"]
            z2 = fit_zones(A[:, h2], seed=SEED + 100 + k, **SWEEPS)["partition"]
            split_rows.append({"chain": chain, "stores": len(st), "split": k, "products_per_half": len(h1),
                               "zones_half1": int((np.bincount(z1) >= 2).sum()),
                               "zones_half2": int((np.bincount(z2) >= 2).sum()),
                               "ari_half1_vs_half2": adjusted_rand(z1, z2),
                               "ari_half1_vs_full": adjusted_rand(z1, ref), "ari_half2_vs_full": adjusted_rand(z2, ref)})
        TAB.mkdir(exist_ok=True)
        pd.DataFrame([r for r in prior_rows if r["chain"] == chain]).to_csv(
            TAB / f"zone_sensitivity_prior_{chain}.csv", index=False)
        pd.DataFrame([r for r in split_rows if r["chain"] == chain]).to_csv(
            TAB / f"zone_sensitivity_split_half_{chain}.csv", index=False)
        print(f"  {chain}: done", flush=True)
    TAB.mkdir(exist_ok=True)
    pr, sp = pd.DataFrame(prior_rows), pd.DataFrame(split_rows)
    pr.to_csv(TAB / "zone_sensitivity_prior.csv", index=False)
    sp.to_csv(TAB / "zone_sensitivity_split_half.csv", index=False)
    summ = sp.groupby("chain")["ari_half1_vs_half2"].agg(["mean", "min"]).round(2).to_dict("index")
    return f"Zone sensitivity: wrote 2 tables. Split-half ARI by chain: {summ}"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default=",".join(CHAINS))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        from pathlib import Path
        TAB = Path(a.out)
    print(run(chains=tuple(a.chains.split(","))))
    sys.exit(0)
