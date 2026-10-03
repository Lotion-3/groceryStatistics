"""SIMULATION ONLY -- synthetic price lists with known zones.

Checks that the Dirichlet-process zone model (analysis/zone_model.py)
recovers zones before it is used on real prices, in settings shaped like the
real data:
  * S stores, J products; a national list; K true zones, each differing from
    the national list on a share `zone_diff` of products (a different price
    level for that product)
  * local noise: each store departs from its zone's price on a share
    `noise` of products (a store-specific level)
  * a share `missing` of store-product cells is not carried
Scenarios cover few/many zones, clean/noisy stores and a "gradient" case with
no zones at all (every store its own small departures), where the model
should NOT invent large zones.

Outputs: tables/simulation_zone_model.csv (adjusted Rand index of the point
partition, posterior mean number of zones with >= 2 stores, true number).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.zone_model import adjusted_rand, fit_zones  # noqa: E402

SEED = 20261003


def simulate(S, J, K, zone_diff, noise, missing, rng):
    base = rng.integers(0, 3, J).astype(float)
    zones = rng.integers(0, K, S) if K > 0 else np.arange(S)
    zone_lists = []
    for k in range(max(K, 1)):
        zl = base.copy()
        d = rng.random(J) < zone_diff if K > 1 else np.zeros(J, bool)
        zl[d] = 10 + k                      # zone-specific level
        zone_lists.append(zl)
    M = np.empty((S, J))
    for s in range(S):
        M[s] = zone_lists[zones[s] if K > 0 else 0]
        dev = rng.random(J) < noise
        M[s, dev] = 100 + s                 # store-specific level
    M[rng.random((S, J)) < missing] = np.nan
    return M, (zones if K > 0 else np.arange(S))


def main() -> int:
    rng = np.random.default_rng(SEED)
    scenarios = [
        ("3 zones, clean", 50, 300, 3, 0.10, 0.01, 0.2),
        ("3 zones, noisy stores", 50, 300, 3, 0.10, 0.05, 0.2),
        ("6 zones, noisy", 80, 300, 6, 0.08, 0.05, 0.3),
        ("1 national list + noise (no zones)", 50, 300, 1, 0.0, 0.05, 0.2),
        ("3 zones, subtle (3% of products), noisier", 50, 300, 3, 0.03, 0.08, 0.3),
        ("3 zones, very subtle (1% of products)", 50, 300, 3, 0.01, 0.05, 0.3),
    ]
    rows = []
    for name, S, J, K, zd, nz, miss in scenarios:
        M, truth = simulate(S, J, K, zd, nz, miss, rng)
        r = fit_zones(M, n_sweeps=600, burn=200, thin=4, gamma=1.0, seed=1)
        true_k = len(np.unique(truth)) if K > 1 else 1
        rows.append({"scenario": name, "stores": S, "products": J, "true_zones": true_k,
                     "post_mean_zones_ge2": float(r["k_ge2"].mean()),
                     "post_q05": float(np.quantile(r["k_ge2"], 0.05)), "post_q95": float(np.quantile(r["k_ge2"], 0.95)),
                     "point_zones": int(len(np.unique(r["partition"]))),
                     "ARI": adjusted_rand(truth if K > 1 else np.zeros(S, int), r["partition"]),
                     "start_agreement_ari": r["start_agreement_ari"]})
        print(rows[-1], flush=True)
    out = pd.DataFrame(rows)
    (ROOT / "tables").mkdir(exist_ok=True)
    out.to_csv(ROOT / "tables" / "simulation_zone_model.csv", index=False)
    print(out.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
