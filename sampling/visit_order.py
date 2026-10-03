"""Balanced-prefix visit order for the store sample (DECISIONS #40).

Collection can stop part-way (a chain blocks, a daily quota runs out, a run
is cut short). The runner visits stores in `visit_order`, so whatever is
collected is a PREFIX of that order. This module chooses the order so that
every prefix is itself a usable sample:

  1. Proportional across strata at every prefix length (systematic
     interleaving). In stratum h with n_h stores, the store ranked i gets the
     key (i + u_h) / n_h, with one uniform offset u_h per stratum; sorting all
     stores by key interleaves the strata so that the first k stores contain
     each stratum in proportion to its size, to within +-1 store, for every k.
  2. Spread out within a stratum (maximin / farthest-point order). The rank
     i inside a stratum comes from greedy farthest-point ordering: start at a
     random store, then repeatedly take the store farthest (great-circle)
     from all stores already taken. Early stores in a stratum are therefore
     far apart, and later ones fill in.

The SAMPLE itself (which 250 stores) is unchanged; only the order changes.
Seeds are fixed (config/sampling.yaml seed + 2).

  python -m sampling.visit_order            # rewrite visit_order in config/store_sample.csv
  python -m sampling.visit_order --check    # only compare prefixes with the current order
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from analysis.estimators import haversine_km
from sampling.build_frame import CFG, ROOT

SAMPLE = ROOT / "config" / "store_sample.csv"


def maximin_order(lat: np.ndarray, lon: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Indices in greedy farthest-point order, starting from a random point."""
    n = len(lat)
    if n == 0:
        return np.array([], int)
    D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    order = [int(rng.integers(n))]
    dmin = D[order[0]].copy()
    for _ in range(n - 1):
        dmin[order] = -1.0
        nxt = int(np.argmax(dmin))
        order.append(nxt)
        dmin = np.minimum(dmin, D[nxt])
    return np.array(order)


def balanced_order(sample: pd.DataFrame, seed: int) -> pd.Series:
    """Return the visit rank (1..n) for each row of `sample`."""
    rng = np.random.default_rng(seed)
    strata = CFG["strata"]
    key = pd.Series(np.nan, index=sample.index)
    for _, g in sorted(sample.groupby(strata), key=lambda t: t[0]):
        idx = g.index.to_numpy()
        rank = np.empty(len(idx))
        rank[maximin_order(g["lat"].to_numpy(float), g["lon"].to_numpy(float), rng)] = np.arange(len(idx))
        key[idx] = (rank + rng.random()) / len(idx)
    # tiny random tie-breaker, then rank
    key = key + rng.random(len(key)) * 1e-9
    return key.rank(method="first").astype(int)


def prefix_quality(sample: pd.DataFrame, order: pd.Series, fracs=(0.1, 0.25, 0.5)) -> pd.DataFrame:
    """For prefixes of the order: worst deviation of any stratum count from
    proportional, number of states covered, and median nearest-neighbour
    distance (km) among the prefix (larger = more spread out)."""
    strata = CFG["strata"]
    s = sample.assign(_o=order.values).sort_values("_o")
    n = len(s)
    share = s.groupby(strata).size() / n
    rows = []
    for f in fracs:
        k = max(1, int(round(f * n)))
        p = s.head(k)
        counts = p.groupby(strata).size().reindex(share.index, fill_value=0)
        dev = (counts - share * k).abs().max()
        lat, lon = p["lat"].to_numpy(float), p["lon"].to_numpy(float)
        D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
        np.fill_diagonal(D, np.inf)
        rows.append({"prefix_share": f, "stores": k, "max_stratum_dev": float(dev),
                     "strata_present": int((counts > 0).sum()), "strata_total": len(share),
                     "states": int(p["state"].nunique()), "median_nn_km": float(np.median(D.min(axis=1)))})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare only; do not rewrite the file")
    a = ap.parse_args(argv)
    sample = pd.read_csv(SAMPLE, dtype={"zip": str, "store_id": str})
    new = balanced_order(sample, CFG["seed"] + 2)
    pd.set_option("display.width", 200)
    if "visit_order" in sample:
        print("Current order (seeded random shuffle):")
        print(prefix_quality(sample, sample["visit_order"]).round(2).to_string(index=False))
    print("\nBalanced-prefix order:")
    print(prefix_quality(sample, new).round(2).to_string(index=False))
    if not a.check:
        sample["visit_order"] = new.values
        sample.sort_values("visit_order").to_csv(SAMPLE, index=False)
        print(f"\nwrote {SAMPLE.relative_to(ROOT)} in balanced-prefix order")
    return 0


if __name__ == "__main__":
    sys.exit(main())
