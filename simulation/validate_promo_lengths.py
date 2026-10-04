"""How long do promotions last? Three one-snapshot estimators, simulated.

A snapshot sees the promotions active at one moment: each has an age a (since
its effective date) and, at Kroger, a planned length L (expiration - effective).
Promotions start in weekly cohorts (Wednesdays); lengths are whole weeks.

Estimators of the mean length mu:
  ages     renewal theory from ages alone: mu = 1 / f_A(0), with f_A(0) taken as
           the share of active promotions younger than a week, divided by 7.
           Assumes a stationary process: equal cohorts, same length mix.
  harmonic length-biased sampling: mu = 1 / mean(1/L). Assumes active promotions
           are sampled in proportion to length (equal cohorts).
  lynden   Lynden-Bell / Woodroofe product-limit estimator for left-truncated
           data: a promotion is seen only if L > a. Allows cohorts of any size,
           but assumes the same length distribution in every cohort.

Scenarios: (1) stationary; (2) cohort sizes vary week to week; (3) the length
mix varies between cohorts (a multi-week event in one week). Writes
tables/simulation_promo_lengths.csv.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import TAB

LENGTHS = np.array([7, 14, 21, 28, 56])
BASE_P = np.array([0.45, 0.30, 0.07, 0.12, 0.06])
WEEKS = 20                     # cohorts before the snapshot
OBS_AGE = 2.5                  # snapshot taken 2.5 days into the newest cohort's week
N_REP = 200


def simulate(rng, sizes, mixes):
    """Active promotions at the snapshot: arrays (age, L)."""
    ages, Ls = [], []
    for w in range(WEEKS):                       # w = 0 is the newest cohort
        n = rng.poisson(sizes[w])
        L = rng.choice(LENGTHS, size=n, p=mixes[w])
        a = OBS_AGE + 7 * w
        alive = L > a
        ages.append(np.full(alive.sum(), a)); Ls.append(L[alive])
    return np.concatenate(ages), np.concatenate(Ls).astype(float)


def est_ages(a, L):
    return 7 / np.mean(a < 7)


def est_harmonic(a, L):
    return 1 / np.mean(1 / L)


def est_lynden(a, L):
    S, prev, mean = 1.0, 0.0, 0.0
    for x in np.unique(L):
        mean += (x - prev) * S
        R = np.sum((a < x) & (L >= x))
        S *= 1 - np.sum(L == x) / R if R else 1
        prev = x
    return mean


def main() -> int:
    rng = np.random.default_rng(20261004)
    true_mu = float(LENGTHS @ BASE_P)
    flat = [1000.0] * WEEKS
    scen = {
        "stationary": (lambda: flat, lambda: [BASE_P] * WEEKS),
        "cohort sizes vary (x0.5-x2)": (lambda: list(1000 * np.exp(rng.uniform(np.log(0.5), np.log(2), WEEKS))),
                                        lambda: [BASE_P] * WEEKS),
        "length mix varies (multi-week event)": (lambda: flat,
                                                 lambda: [BASE_P if w != 1 else np.array([0.05, 0.6, 0.05, 0.25, 0.05])
                                                          for w in range(WEEKS)]),
    }
    rows = []
    for name, (sz, mx) in scen.items():
        res = {"ages": [], "harmonic": [], "lynden": []}
        for _ in range(N_REP):
            a, L = simulate(rng, sz(), mx())
            res["ages"].append(est_ages(a, L)); res["harmonic"].append(est_harmonic(a, L)); res["lynden"].append(est_lynden(a, L))
        for k, v in res.items():
            v = np.array(v)
            rows.append({"scenario": name, "estimator": k, "true_mean_days": true_mu, "mean_estimate": v.mean(),
                         "bias": v.mean() - true_mu, "sd": v.std(), "rmse": np.sqrt(np.mean((v - true_mu) ** 2))})
    t = pd.DataFrame(rows)
    TAB.mkdir(exist_ok=True)
    t.to_csv(TAB / "simulation_promo_lengths.csv", index=False)
    print(t.round(2).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
