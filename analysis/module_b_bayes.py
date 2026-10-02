"""Module B: hierarchical Bayesian spatial model (Rao).

Status: STUB -- not implemented yet.

Planned (Day 4): log(price) ~ item + chain + store random effect + spatial
effect. Start with an ICAR / BYM2 effect over 3-digit ZIP regions (PyMC),
compare against a non-spatial model by LOO; report R-hat, ESS, posterior
predictive checks. Optional: GP over lat/lon on a subsample; DP mixture of
store price profiles.
"""
from __future__ import annotations


def run() -> str:
    return "Module B: not implemented yet (stub)."


if __name__ == "__main__":
    print(run())
