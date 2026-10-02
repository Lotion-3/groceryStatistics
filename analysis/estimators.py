"""Tail and risk estimators used by Module A.

Everything here is plain numpy/scipy so each step can be explained line by
line. Conventions: `x` is a 1-D array of positive magnitudes (e.g. |d|) and
the tail index alpha is defined by P(X > x) ~ C x^(-alpha); the extreme value
index is gamma = 1/alpha (xi in the GPD parameterisation).

Validated on simulated data with known alpha in
simulation/validate_tail_estimators.py before use on real prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from scipy import stats


# ---------------------------------------------------------------------------
# Hill estimator
# ---------------------------------------------------------------------------

def hill_gamma(x: np.ndarray, k: int) -> float:
    """Hill (1975) estimate of gamma = 1/alpha from the k largest observations:
        gamma_hat(k) = (1/k) sum_{i=1..k} log X_(i) - log X_(k+1),
    with X_(1) >= X_(2) >= ... the order statistics."""
    xs = np.sort(np.asarray(x, float))[::-1]
    xs = xs[xs > 0]
    if not 1 <= k < len(xs):
        raise ValueError(f"k must be in [1, n-1]; got k={k}, n={len(xs)}")
    return float(np.mean(np.log(xs[:k])) - np.log(xs[k]))


def hill_path(x: np.ndarray, ks: Optional[np.ndarray] = None, max_frac: float = 0.15) -> dict:
    """Hill estimates of alpha over a range of k (the data behind a Hill plot),
    with the asymptotic 95% interval alpha_hat * (1 +- 1.96/sqrt(k)).

    By default k runs from 10 to max_frac * n. Larger k reaches into the body
    of the distribution, where the power law does not hold and the Hill
    estimator is badly biased (see simulation/validate_tail_estimators.py:
    for |t_3| data, letting k reach 50% of n gave alpha_hat ~ 1.6 vs true 3)."""
    xs = np.sort(np.asarray(x, float))[::-1]
    xs = xs[xs > 0]
    n = len(xs)
    if ks is None:
        ks = np.arange(10, max(11, int(max_frac * n)))
    ks = np.asarray([k for k in ks if 1 <= k < n], int)
    logs = np.log(xs)
    csum = np.cumsum(logs)
    gamma = csum[ks - 1] / ks - logs[ks]
    alpha = 1.0 / gamma
    se = alpha / np.sqrt(ks)
    return {"k": ks, "alpha": alpha, "lo": alpha - 1.96 * se, "hi": alpha + 1.96 * se,
            "threshold": xs[ks]}


def stable_k(path: dict, window: int = 15) -> int:
    """Pick k from the flattest stretch of the Hill plot: the centre of the
    `window`-long run of consecutive k with the smallest standard deviation of
    alpha_hat. A simple, transparent threshold-stability rule; report results
    for neighbouring k too (sensitivity), never this k alone."""
    a = path["alpha"]
    if len(a) <= window:
        return int(path["k"][len(a) // 2])
    sds = np.array([np.std(a[i:i + window]) for i in range(len(a) - window)])
    i = int(np.argmin(sds))
    return int(path["k"][i + window // 2])


# ---------------------------------------------------------------------------
# Peaks over threshold (generalised Pareto)
# ---------------------------------------------------------------------------

@dataclass
class GPDFit:
    threshold: float
    n_exceed: int
    xi: float          # shape (= gamma = 1/alpha when xi > 0)
    sigma: float       # scale

    @property
    def alpha(self) -> float:
        return 1.0 / self.xi if self.xi > 0 else np.inf


def gpd_fit(x: np.ndarray, u: float) -> GPDFit:
    """Maximum-likelihood GPD fit to the exceedances X - u for X > u."""
    x = np.asarray(x, float)
    y = x[x > u] - u
    if len(y) < 10:
        raise ValueError(f"only {len(y)} exceedances above u={u:.4g}; need >= 10")
    xi, _, sigma = stats.genpareto.fit(y, floc=0)
    return GPDFit(threshold=float(u), n_exceed=int(len(y)), xi=float(xi), sigma=float(sigma))


def mean_excess(x: np.ndarray, us: np.ndarray) -> np.ndarray:
    """Mean residual life e(u) = E[X - u | X > u]; roughly linear in u above a
    threshold where the GPD fits (slope xi/(1-xi))."""
    x = np.asarray(x, float)
    return np.array([np.mean(x[x > u] - u) if np.any(x > u) else np.nan for u in us])


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap_ci(x: np.ndarray, stat: Callable[[np.ndarray], float], B: int = 1000,
                 level: float = 0.95, seed: int = 0) -> tuple[float, float, float]:
    """(estimate, lo, hi): nonparametric percentile bootstrap. Resamples whose
    statistic fails (e.g. too few exceedances) are dropped and counted."""
    rng = np.random.default_rng(seed)
    x = np.asarray(x, float)
    est = stat(x)
    reps = []
    for _ in range(B):
        try:
            reps.append(stat(rng.choice(x, size=len(x), replace=True)))
        except (ValueError, FloatingPointError, RuntimeError):
            continue
    reps = np.asarray([r for r in reps if np.isfinite(r)])
    if len(reps) < 0.5 * B:
        return est, np.nan, np.nan
    a = (1 - level) / 2
    return float(est), float(np.quantile(reps, a)), float(np.quantile(reps, 1 - a))


# ---------------------------------------------------------------------------
# Basket risk measures (across stores)
# ---------------------------------------------------------------------------

def var_es(costs: np.ndarray, q: float = 0.95) -> tuple[float, float]:
    """Empirical value at risk and expected shortfall of basket cost across
    stores at level q (upper tail: expensive stores). ES = mean cost of the
    stores at or above the q-quantile."""
    c = np.asarray(costs, float)
    v = float(np.quantile(c, q))
    return v, float(np.mean(c[c >= v]))


# ---------------------------------------------------------------------------
# Spatial clustering of extremes
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(h))


def exceedance_clustering_test(lat, lon, exceed, radius_km: float = 100.0,
                               n_perm: int = 9999, seed: int = 0) -> dict:
    """Permutation test: do stores with an extreme price (exceed=1) have more
    extreme neighbours within `radius_km` than random relabelling would give?

    Statistic T = number of ordered pairs (i, j), i != j, within radius_km
    with exceed_i = exceed_j = 1 (a join count). Labels are permuted over the
    fixed store locations; p-value = (1 + #{T_perm >= T_obs}) / (1 + n_perm)."""
    lat, lon, e = np.asarray(lat, float), np.asarray(lon, float), np.asarray(exceed, int)
    D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    W = (D <= radius_km).astype(float)
    np.fill_diagonal(W, 0)
    t_obs = float(e @ W @ e)
    rng = np.random.default_rng(seed)
    perm = np.array([(lambda p: p @ W @ p)(rng.permutation(e)) for _ in range(n_perm)])
    return {"T": t_obs, "T_perm_mean": float(perm.mean()), "p_value": float((1 + np.sum(perm >= t_obs)) / (1 + n_perm)),
            "n": int(len(e)), "n_exceed": int(e.sum()), "radius_km": radius_km, "n_perm": n_perm}
