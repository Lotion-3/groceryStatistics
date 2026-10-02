"""SIMULATION ONLY -- synthetic data with a known tail index.

Checks that the Hill and GPD estimators in analysis/estimators.py recover a
known alpha, and how wide / how well-calibrated their intervals are at the
sample sizes we actually have (a few hundred stores per chain). Nothing
here touches real price data.

Designs:
  * Pareto(alpha) with alpha in {2, 3, 4}            exact power tail
  * |Student-t(df)| with df = 3                      alpha = df, but only asymptotically
Sample sizes n in {250, 500, 1000}; R replications each.

Outputs:
  tables/simulation_tail_estimators.csv
  figures/simulation_hill_plot.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.estimators import gpd_fit, hill_gamma, hill_path, stable_k  # noqa: E402

SEED = 20261001


def draw(design: str, alpha: float, n: int, rng) -> np.ndarray:
    if design == "pareto":
        return rng.pareto(alpha, n) + 1.0          # P(X > x) = x^-alpha, x >= 1
    if design == "abs_t":
        return np.abs(rng.standard_t(alpha, n))
    raise ValueError(design)


def one_rep(design, alpha, n, rng) -> dict:
    x = draw(design, alpha, n, rng)
    out = {}
    # Hill: stability rule on k <= 15% n, plus fixed fractions as sensitivity.
    k_rule = stable_k(hill_path(x))
    for name, k in (("rule", k_rule), ("k5", max(10, int(0.05 * n))), ("k10", int(0.10 * n))):
        a = 1.0 / hill_gamma(x, k)
        out[f"alpha_hill_{name}"] = a
        out[f"cover_hill_{name}"] = int(abs(a - alpha) <= 1.96 * a / np.sqrt(k))
    out["k_rule"] = k_rule
    # GPD above the 90% quantile; compare on the shape scale xi = 1/alpha.
    try:
        out["xi_gpd"] = gpd_fit(x, np.quantile(x, 0.9)).xi
    except ValueError:
        out["xi_gpd"] = np.nan
    return out


def main(R: int = 300) -> int:
    rng = np.random.default_rng(SEED)
    rows = []
    for design, alphas in (("pareto", (2.0, 3.0, 4.0)), ("abs_t", (3.0,))):
        for alpha in alphas:
            for n in (250, 500, 1000):
                reps = pd.DataFrame([one_rep(design, alpha, n, rng) for _ in range(R)])
                row = {"design": design, "true_alpha": alpha, "n": n, "R": R,
                       "median_k_rule": reps.k_rule.median()}
                for name in ("rule", "k5", "k10"):
                    a = reps[f"alpha_hill_{name}"]
                    row[f"hill_{name}_median"] = a.median()
                    row[f"hill_{name}_rmse"] = np.sqrt(np.mean((a - alpha) ** 2))
                    row[f"hill_{name}_cover95"] = reps[f"cover_hill_{name}"].mean()
                row["gpd_xi_median"] = reps.xi_gpd.median()
                row["gpd_xi_true"] = 1 / alpha
                row["gpd_xi_rmse"] = np.sqrt(np.nanmean((reps.xi_gpd - 1 / alpha) ** 2))
                rows.append(row)
    out = pd.DataFrame(rows).round(3)
    (ROOT / "tables").mkdir(exist_ok=True)
    out.to_csv(ROOT / "tables" / "simulation_tail_estimators.csv", index=False)
    print("SIMULATED DATA -- estimator validation (not real prices)")
    print(out.to_string(index=False))

    # Example Hill plot for one Pareto(3) sample of n = 500.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = draw("pareto", 3.0, 500, np.random.default_rng(SEED))
    p = hill_path(x)
    k = stable_k(p)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.fill_between(p["k"], p["lo"], p["hi"], alpha=0.2, label="asymptotic 95% band")
    ax.plot(p["k"], p["alpha"], lw=1.2, label="Hill estimate")
    ax.axhline(3.0, ls="--", c="k", lw=0.8, label="true alpha = 3")
    ax.axvline(k, ls=":", c="gray", lw=0.8, label=f"stability-rule k = {k}")
    ax.set(xlabel="k (number of upper order statistics)", ylabel="alpha",
           title="SIMULATED Pareto(3), n = 500: Hill plot", ylim=(0, 7))
    ax.legend(fontsize=7)
    fig.tight_layout()
    (ROOT / "figures").mkdir(exist_ok=True)
    fig.savefig(ROOT / "figures" / "simulation_hill_plot.png", dpi=150)
    return 0


if __name__ == "__main__":
    sys.exit(main())
