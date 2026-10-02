"""Module A (CORE): dispersion and heavy tails of within-chain price deviations.

Status: SCAFFOLD. The data plumbing and estimators are in place; the full
module (per-category tails, GPD fits, basket VaR/ES, Hill plots per chain)
is Day-3 work once snapshot 1 exists. Run on too little data it reports
that and exits cleanly rather than producing misleading numbers.

Method (see docs/DECISIONS.md for the choices):
  * d_reg = log(regular price) - log(chain median of that product)
  * tails of |d|, and of d>0 / d<0 separately
  * Hill estimator, k = 5% of n (primary; best calibrated in simulation),
    sensitivity at the stability-rule k and k = 10%; bootstrap CIs
  * GPD above the 90% quantile, shape xi with bootstrap CI
  * exceedance clustering: join-count permutation test within 100 km
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import TAB, add_deviations, load_observations, product_panel, sample_size_note
from analysis.estimators import bootstrap_ci, hill_gamma

MIN_N = 200   # below this many nonzero |d| per chain, tail estimates are not reported


def tail_table(dev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for chain, g in dev.groupby("chain"):
        x = np.abs(g["d_reg"].to_numpy())
        x = x[x > 0]
        row = {"chain": chain, "n_prices": len(g), "n_nonzero": len(x), "stores": g["store_pk"].nunique()}
        if len(x) >= MIN_N:
            k = max(10, int(0.05 * len(x)))
            est, lo, hi = bootstrap_ci(x, lambda s: 1 / hill_gamma(s, k), B=500)
            row.update(k=k, alpha_hill=est, ci_lo=lo, ci_hi=hi)
        else:
            row.update(note=f"insufficient data (< {MIN_N} nonzero deviations)")
        rows.append(row)
    return pd.DataFrame(rows)


def run() -> str:
    obs = load_observations()
    if obs.empty:
        return "Module A: no store-specific observations yet."
    dev = add_deviations(product_panel(obs, min_stores=20))
    if dev.empty:
        return "Module A: no product is observed at >= 20 stores yet (need snapshot 1)."
    t = tail_table(dev)
    TAB.mkdir(exist_ok=True)
    t.to_csv(TAB / "module_a_tail_index_by_chain.csv", index=False)
    return f"Module A: wrote tables/module_a_tail_index_by_chain.csv. {sample_size_note(dev)}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
