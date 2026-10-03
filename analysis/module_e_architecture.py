"""Module E: pricing architecture (replaces the optional topology stub).

How does each chain organise its price list across space -- one national list,
discrete zones, or a continuous gradient? (Plan: docs/STUDY_PLAN.md, Q1-Q2.)

For every pair of stores of a chain, the price-list DISSIMILARITY is the
fraction of the products both stores carry (>= MIN_SHARED) that are priced
differently, to the cent (regular prices). From it:

  1. Point mass. Share of store prices exactly at the chain's modal ("list")
     price, and the direction of departures.
  2. Price-list variogram. Mean dissimilarity by distance band, with 95% bands
     from a STORE bootstrap (whole stores resampled, since pairs sharing a
     store are dependent). A fitted curve
         gamma(h) = nugget + (sill - nugget) * (1 - exp(-h / range))
     summarises it: nugget = how different nearby stores already are (local
     departures), sill = the long-distance level, range = the distance over
     which lists diverge (km).
  3. Zones by persistent homology (dimension 0). Grow a tolerance t from 0 and
     link stores whose dissimilarity is <= t; the number of connected groups
     at each t is the H0 barcode of the single-linkage filtration. A chain
     with a national list plus a few regional zones shows a few long bars; a
     gradient shows bars dying gradually.
  4. Urban vs rural. Among stores < NEAR_KM apart: do mixed urban/non-urban
     pairs differ more than same-type pairs? Permutation test (urbanicity
     labels permuted across the chain's stores; 4,999 permutations).

Contiguous US only (Hawaii/Alaska premia are Module A's). PRELIMINARY,
cross-sectional, website prices; every output states n.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, FIG, MUTED, SEED, TAB, caption, load_observations, main_snapshots,
                             product_panel, style)
from analysis.estimators import haversine_km

MIN_STORES = 15          # chains with fewer stores are skipped
MIN_SHARED = 20          # products two stores must share for a dissimilarity
NEAR_KM = 300.0
BINS_KM = [0, 50, 100, 250, 500, 1000, 2000, 6000]
THRESHOLDS = (0.0, 0.01, 0.02, 0.05, 0.10)
B = 300
CHAINS = ("aldi", "walmart", "costco", "kroger", "meijer", "target")     # kroger_ce (test host) excluded
EXTRA_COLORS = {"aldi": "#8a5cf6", "kroger": "#e87ba4", "meijer": "#008300"}


NAMES = {"aldi": "ALDI", "walmart": "Walmart", "costco": "Costco", "kroger": "Kroger", "meijer": "Meijer",
         "target": "Target"}


def name(chain: str) -> str:
    return NAMES.get(chain, chain)


def color(chain: str) -> str:
    return CHAIN_COLORS.get(chain) or EXTRA_COLORS.get(chain, MUTED)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def chain_matrix(p: pd.DataFrame, chain: str):
    """(stores table, price matrix stores x products in cents, NaN = not carried)."""
    g = p[p["chain"] == chain]
    M = g.pivot_table(index="store_pk", columns="chain_product_id", values="cents", aggfunc="first")
    st = (g.drop_duplicates("store_pk").set_index("store_pk")
          .loc[M.index, ["lat", "lon", "state", "region", "urbanicity"]])
    return st, M


def dissimilarity(M: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(F, C): fraction of shared products priced differently, and the number
    shared, for every store pair. F is NaN where fewer than MIN_SHARED shared."""
    A = M.to_numpy(float)
    ok = ~np.isnan(A)
    n = len(A)
    F = np.full((n, n), np.nan)
    C = np.zeros((n, n), int)
    for i in range(n):
        both = ok[i] & ok
        C[i] = both.sum(1)
        diff = ((A[i] != A) & both).sum(1)
        F[i] = np.where(C[i] >= MIN_SHARED, diff / np.maximum(C[i], 1), np.nan)
    np.fill_diagonal(F, np.nan)
    return F, C


# ---------------------------------------------------------------------------
# 1. Point mass
# ---------------------------------------------------------------------------

def point_mass(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for chain, g in p.groupby("chain"):
        mode = g.groupby("chain_product_id")["cents"].transform(lambda s: s.mode().min())
        off = g["cents"] != mode
        dl = np.log(g.loc[off, "cents"] / mode[off])
        rows.append({"chain": chain, "stores": g["store_pk"].nunique(), "products": g["chain_product_id"].nunique(),
                     "prices": len(g), "share_at_list": float((~off).mean()),
                     "share_departures_up": float((dl > 0).mean()) if len(dl) else np.nan,
                     "median_departure_pct": float(100 * dl.median()) if len(dl) else np.nan})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Variogram
# ---------------------------------------------------------------------------

def _binned(F, D, idx=None):
    if idx is None:
        idx = np.arange(len(F))
    Fi, Di = F[np.ix_(idx, idx)], D[np.ix_(idx, idx)]
    same = idx[:, None] == idx[None, :]                 # bootstrap duplicates of one store
    iu = np.triu_indices(len(idx), 1)
    f, d, s = Fi[iu], Di[iu], same[iu]
    keep = ~np.isnan(f) & ~s
    f, d = f[keep], d[keep]
    out = []
    for lo, hi in zip(BINS_KM[:-1], BINS_KM[1:]):
        m = (d >= lo) & (d < hi)
        out.append((f[m].mean() if m.any() else np.nan, int(m.sum())))
    return out


def variogram(F: np.ndarray, D: np.ndarray, rng: np.random.Generator) -> pd.DataFrame:
    point = _binned(F, D)
    n = len(F)
    boots = np.array([[v for v, _ in _binned(F, D, rng.integers(0, n, n))] for _ in range(B)])
    rows = []
    for k, (lo, hi) in enumerate(zip(BINS_KM[:-1], BINS_KM[1:])):
        b = boots[:, k]
        b = b[~np.isnan(b)]
        rows.append({"bin_lo_km": lo, "bin_hi_km": hi, "mid_km": (lo + hi) / 2, "pairs": point[k][1],
                     "mean_dissimilarity": point[k][0],
                     "ci_lo": float(np.quantile(b, 0.025)) if len(b) > 20 else np.nan,
                     "ci_hi": float(np.quantile(b, 0.975)) if len(b) > 20 else np.nan})
    return pd.DataFrame(rows)


def fit_variogram(F: np.ndarray, D: np.ndarray) -> dict:
    """Least-squares fit of the exponential model to all pairs."""
    from scipy.optimize import curve_fit
    iu = np.triu_indices(len(F), 1)
    f, d = F[iu], D[iu]
    keep = ~np.isnan(f)
    f, d = f[keep], d[keep]
    if len(f) < 20:
        return {}

    def model(h, nugget, sill, rng_km):
        return nugget + (sill - nugget) * (1 - np.exp(-h / rng_km))
    try:
        (nug, sill, r), _ = curve_fit(model, d, f, p0=[f.min() + 0.01, f.max(), 500.0],
                                      bounds=([0, 0, 10], [1, 1, 20000]), maxfev=20000)
    except Exception:
        return {}
    # If the curve has no plateau within US distances the range is not
    # identified (the fit runs to its bounds): report that, not a number.
    plateau = r < 0.5 * d.max() and sill < 0.99
    return {"nugget": float(nug), "sill": float(sill) if plateau else np.nan,
            "range_km": float(r) if plateau else np.nan, "plateau_reached": bool(plateau),
            "note": "" if plateau else "no plateau within observed distances: dissimilarity keeps rising "
                                        "(gradient, not zones of a fixed size); sill/range not identified",
            "pairs_fitted": int(len(f))}


# ---------------------------------------------------------------------------
# 3. H0 barcode (single-linkage filtration)
# ---------------------------------------------------------------------------

def h0_barcode(F: np.ndarray) -> np.ndarray:
    """Death times of the H0 bars (all bars are born at 0): the merge heights
    of single-linkage clustering on the dissimilarity. Pairs without enough
    shared products get dissimilarity 1 (never linked before t = 1)."""
    from scipy.cluster.hierarchy import linkage
    from scipy.spatial.distance import squareform
    Dm = np.nan_to_num(F, nan=1.0)
    Dm = np.minimum(Dm, Dm.T)
    np.fill_diagonal(Dm, 0.0)
    if len(Dm) < 2:
        return np.array([])
    return np.sort(linkage(squareform(Dm, checks=False), method="single")[:, 2])


def components_at(deaths: np.ndarray, n: int, t: float) -> int:
    """Number of groups when stores with dissimilarity <= t are linked."""
    return int(n - np.sum(deaths <= t))


def zones_at(F: np.ndarray, t: float) -> np.ndarray:
    """Group label per store at tolerance t (connected components)."""
    from scipy.sparse.csgraph import connected_components
    adj = (np.nan_to_num(F, nan=1.0) <= t).astype(int)
    np.fill_diagonal(adj, 0)
    return connected_components(adj, directed=False)[1]


# ---------------------------------------------------------------------------
# 4. Urban vs rural
# ---------------------------------------------------------------------------

def urban_rural_test(F: np.ndarray, D: np.ndarray, urban: np.ndarray, rng: np.random.Generator,
                     n_perm: int = 4999) -> dict:
    iu = np.triu_indices(len(F), 1)
    near = (D[iu] < NEAR_KM) & ~np.isnan(F[iu])
    i, j = iu[0][near], iu[1][near]
    f = F[i, j]

    def stat(u):
        mixed = u[i] != u[j]
        if mixed.sum() < 3 or (~mixed).sum() < 3:
            return np.nan
        return f[mixed].mean() - f[~mixed].mean()
    obs = stat(urban)
    if np.isnan(obs):
        return {"pairs_near": int(near.sum()), "note": "too few mixed or same-type pairs"}
    perm = np.array([stat(rng.permutation(urban)) for _ in range(n_perm)])
    perm = perm[~np.isnan(perm)]
    mixed = urban[i] != urban[j]
    return {"note": "EXPLORATORY: hypothesis suggested by an earlier look at the same snapshot; "
                    "confirm on stores collected later or on snapshot 3",
            "pairs_near": int(near.sum()), "pairs_mixed": int(mixed.sum()), "pairs_same": int((~mixed).sum()),
            "mean_mixed": float(f[mixed].mean()), "mean_same": float(f[~mixed].mean()), "difference": float(obs),
            "p_value_one_sided": float((1 + np.sum(perm >= obs)) / (1 + len(perm))), "n_perm": int(len(perm))}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def figures(vg: pd.DataFrame, bars: dict, zones_map: dict, note: str) -> list[str]:
    plt = style()
    out = []
    if not vg.empty:
        fig, ax = plt.subplots(figsize=(5.4, 3.4))
        for chain, g in vg.groupby("chain"):
            g = g.dropna(subset=["mean_dissimilarity"])
            ax.fill_between(g["mid_km"], g["ci_lo"], g["ci_hi"], color=color(chain), alpha=0.15, linewidth=0)
            ax.plot(g["mid_km"], g["mean_dissimilarity"], marker="o", markersize=4, color=color(chain),
                    label=f"{name(chain)} ({int(g['stores'].iloc[0])} stores)")
        ax.set_xscale("log")
        ax.set_xlabel("distance between stores (km, log scale)")
        ax.set_ylabel("share of shared products priced differently")
        ax.set_title("Price-list variogram by chain", loc="left")
        ax.legend(fontsize=7)
        caption(fig, note + " Bands: 95% store-bootstrap intervals. Contiguous US.")
        fig.savefig(FIG / "fig_e1_price_list_variogram.png")
        plt.close(fig)
        out.append("fig_e1_price_list_variogram.png")
    if bars:
        fig, ax = plt.subplots(figsize=(5.4, 3.2))
        ts = np.linspace(0, 0.3, 301)
        for chain, (deaths, n) in bars.items():
            ax.step(ts, [components_at(deaths, n, t) / n for t in ts], where="post", color=color(chain),
                    label=f"{name(chain)} (n = {n})")
        ax.set_xlabel("tolerance t (share of shared products priced differently)")
        ax.set_ylabel("groups / stores")
        ax.set_title("H0 persistence: store groups as the tolerance grows", loc="left")
        ax.legend(fontsize=7)
        caption(fig, note + " A flat early drop to few groups = a shared national list or zones.")
        fig.savefig(FIG / "fig_e2_h0_components.png")
        plt.close(fig)
        out.append("fig_e2_h0_components.png")
    for chain, (st, lab) in zones_map.items():
        fig, ax = plt.subplots(figsize=(5.4, 3.2))
        sizes = pd.Series(lab).value_counts()
        big = sizes[sizes >= 2].index[:6]
        palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
        for k, z in enumerate(big):
            m = lab == z
            ax.scatter(st["lon"][m], st["lat"][m], s=22, color=palette[k], edgecolors="white", linewidths=0.4,
                       label=f"group {k + 1} ({m.sum()} stores)")
        m = ~np.isin(lab, big)
        ax.scatter(st["lon"][m], st["lat"][m], s=14, color=MUTED, alpha=0.6, label=f"singletons ({m.sum()})")
        ax.set_aspect(1.25)
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        ax.set_title(f"{name(chain)}: stores with near-identical price lists (t = 0.01)", loc="left")
        ax.legend(fontsize=6, loc="lower left")
        caption(fig, note)
        name = f"fig_e3_zones_{chain}.png"
        fig.savefig(FIG / name)
        plt.close(fig)
        out.append(name)
    return out


# ---------------------------------------------------------------------------

def run(snaps: list[int] | None = None) -> str:
    snaps = snaps or main_snapshots()[:1]
    if not snaps:
        return "Module E: no main snapshot configured in config/analysis.yaml yet."
    obs = load_observations(snapshot_id=snaps)
    p = product_panel(obs, min_stores=10)
    p = p[p["chain"].isin(CHAINS) & ~p["state"].isin(["HI", "AK"]) & p["lat"].notna()].copy()
    p["cents"] = p["regular_price"].round(2)
    if p.empty:
        return "Module E: no data."
    rng = np.random.default_rng(SEED)
    pm = point_mass(p)
    vg_rows, fits, h0, ur, bars, zmap = [], [], [], [], {}, {}
    for chain in CHAINS:
        st, M = chain_matrix(p, chain)
        if len(st) < MIN_STORES:
            continue
        F, C = dissimilarity(M)
        D = haversine_km(st["lat"].values[:, None], st["lon"].values[:, None],
                         st["lat"].values[None, :], st["lon"].values[None, :])
        vg = variogram(F, D, rng).assign(chain=chain, stores=len(st))
        vg_rows.append(vg)
        fits.append({"chain": chain, "stores": len(st), **fit_variogram(F, D)})
        deaths = h0_barcode(F)
        bars[chain] = (deaths, len(st))
        h0.append({"chain": chain, "stores": len(st),
                   **{f"groups_at_t{t:g}": components_at(deaths, len(st), t) for t in THRESHOLDS},
                   "largest_group_t0.01": int(pd.Series(zones_at(F, 0.01)).value_counts().iloc[0]),
                   "median_death": float(np.median(deaths)) if len(deaths) else np.nan})
        zmap[chain] = (st.reset_index(), zones_at(F, 0.01))
        ur.append({"chain": chain, **urban_rural_test(F, D, (st["urbanicity"] != "urban").to_numpy(), rng)})
    note = (f"Snapshot(s) {snaps}; {int(p['store_pk'].nunique())} stores, {len(p):,} store-product prices "
            f"(regular prices, products at >= 10 stores). PRELIMINARY, cross-sectional.")
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    tables = {"module_e_point_mass": pm,
              "module_e_variogram": pd.concat(vg_rows, ignore_index=True) if vg_rows else pd.DataFrame(),
              "module_e_variogram_fit": pd.DataFrame(fits), "module_e_h0_groups": pd.DataFrame(h0),
              "module_e_urban_rural": pd.DataFrame(ur)}
    for name, t in tables.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    figs = figures(tables["module_e_variogram"], bars, {c: v for c, v in zmap.items() if c in ("aldi", "walmart")},
                   note)
    return f"Module E: wrote {len(tables)} tables and {len(figs)} figures. {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
