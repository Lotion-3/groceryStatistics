"""Check the dyadic co-timing model (analysis.module_g_timing.dyadic_model) on
synthetic store pairs with a KNOWN zone effect.

Stores sit in zones (within banners) at random locations. Each same-banner pair
shares n products; the number co-timed is Binomial with
    logit p = a + b_zone * same_zone + b_dist * log1p(d / 100) + u_i + u_j + e_ij.
Distance is correlated with zone membership (zones are spatially clustered), so a
naive within/across comparison mixes zone and distance; the model must separate
them. Scenarios: b_zone = 0.5 (a real zone effect) and b_zone = 0 (distance only).
Reports estimates, 90% intervals and coverage. Writes tables/simulation_dyadic_model.csv.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import TAB
from analysis.module_g_timing import dyadic_model

TRUTH = {"a": 0.5, "b_dist": -0.5, "s_u": 0.35, "s_e": 0.35}


def simulate(rng, b_zone: float, n_banners: int = 4, zones_per_banner: int = 3, stores_per_zone: int = 5):
    rows, sid = [], 0
    stores = []
    for b in range(n_banners):
        centre = rng.uniform(0, 2000, 2)
        for z in range(zones_per_banner):
            zc = centre + rng.normal(0, 150, 2)
            for _ in range(stores_per_zone):
                stores.append({"id": sid, "banner": b, "zone": b * 10 + z, "xy": zc + rng.normal(0, 40, 2)})
                sid += 1
    u = rng.normal(0, TRUTH["s_u"], len(stores))
    for i in range(len(stores)):
        for j in range(i + 1, len(stores)):
            si, sj = stores[i], stores[j]
            if si["banner"] != sj["banner"]:
                continue
            d = float(np.linalg.norm(si["xy"] - sj["xy"]))
            same = int(si["zone"] == sj["zone"])
            eta = (TRUTH["a"] + b_zone * same + TRUTH["b_dist"] * np.log1p(d / 100) + u[i] + u[j]
                   + rng.normal(0, TRUTH["s_e"]))
            n = int(rng.integers(200, 600))
            rows.append({"i": si["id"], "j": sj["id"], "banner": f"B{si['banner']}", "n": n,
                         "y": int(rng.binomial(n, 1 / (1 + np.exp(-eta)))), "same_zone": same, "dist_km": d})
    return pd.DataFrame(rows)


def main() -> int:
    rng = np.random.default_rng(20261006)
    out = []
    for b_zone in (0.5, 0.0):
        for rep in range(10):
            pt = simulate(rng, b_zone)
            naive = pt.assign(r=pt["y"] / pt["n"]).groupby("same_zone")["r"].mean()
            r = dyadic_model(pt, seed=rep, draws=1000, tune=1000)
            out.append({"true_b_zone": b_zone, "rep": rep, "pairs": len(pt),
                        "naive_rate_diff": float(naive.get(1, np.nan) - naive.get(0, np.nan)),
                        "b_zone_mean": r["b_zone_mean"], "b_zone_lo90": r["b_zone_lo90"], "b_zone_hi90": r["b_zone_hi90"],
                        "covered": bool(r["b_zone_lo90"] <= b_zone <= r["b_zone_hi90"]),
                        "b_dist_mean": r["b_dist_mean"], "b_dist_covered": bool(r["b_dist_lo90"] <= TRUTH["b_dist"] <= r["b_dist_hi90"]),
                        "rhat_max": r["rhat_max"], "divergences": r["divergences"]})
            print(out[-1], flush=True)
    t = pd.DataFrame(out)
    TAB.mkdir(exist_ok=True)
    t.to_csv(TAB / "simulation_dyadic_model.csv", index=False)
    print(t.groupby("true_b_zone")[["b_zone_mean", "covered", "b_dist_covered", "naive_rate_diff"]].mean().round(3))
    return 0


if __name__ == "__main__":
    sys.exit(main())
