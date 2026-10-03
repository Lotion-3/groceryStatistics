"""Module A (CORE): dispersion and heavy tails of price deviations.

Unit: one (chain, product, store) price in the primary snapshot, store-specific
rows only (see analysis/common.py). A "product" is the chain's own product id,
so within a chain identical products are compared exactly.

Deviation:   d = log(price at store) - log(median price of that product in the chain)
  d_reg    regular (non-promo) price: the main analysis
  d_shelf  shelf price incl. markdowns: promo-inclusive sensitivity
  d_cross  for UPC-matched products, relative to the median over all chains

Tails are estimated separately for |d|, the upper tail (d > 0: stores that
charge more) and the lower tail (d < 0, as -d). Zeros (store charges exactly
the median) are not tail observations and are excluded; their share is reported.

Estimators (choices in docs/DECISIONS.md #19-20, validated in simulation/):
  * Hill alpha at k = 5% of the nonzero n (primary), with sensitivity at the
    stability-rule k and k = 10%
  * GPD above the 90% quantile, shape xi (xi <= 0 means no power tail)
  * 95% CIs from a STORE-CLUSTER bootstrap (whole stores resampled), because
    prices from one store are not independent

Spatial clustering of extremes: per-store price index = mean d_reg over the
store's products; join-count test on "index above the chain's 90th percentile"
and Moran's I on the index, both with neighbours = stores within 100 km.

Basket tail risk: within each chain, a fixed basket of the products observed at
>= 80% of the chain's stores (at most 40, the most widely observed); cost per
store that carries all of them; VaR/ES (95%) of cost relative to the chain
median, plus the Hill index of the upper tail when n allows.

Everything is cross-sectional and PRELIMINARY; every output states n.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, FIG, MUTED, SEED, TAB, add_deviations, caption,
                             cross_chain_deviations, load_observations, main_snapshots,
                             product_panel, sample_size_note, style)
from analysis.estimators import (cluster_bootstrap_ci, exceedance_clustering_test, gpd_fit, hill_gamma,
                                 hill_path, mean_excess, morans_i, stable_k, var_es)

MIN_N = 200          # nonzero tail observations needed before a tail index is reported
MIN_STORES = 20      # a product must be seen at this many stores to define its median
B = 500              # bootstrap replicates
BASKET_COVERAGE = 0.80
BASKET_MAX = 40
BASKET_MIN = 5
RADIUS_KM = 100.0

TAILS = ("abs", "upper", "lower")


def tail_values(d: np.ndarray, tail: str) -> np.ndarray:
    """Positive magnitudes for one tail; exact zeros dropped."""
    d = np.asarray(d, float)
    if tail == "abs":
        x = np.abs(d)
    elif tail == "upper":
        x = d[d > 0]
    else:
        x = -d[d < 0]
    return x[x > 0]


def k_frac(n: int, frac: float) -> int:
    return max(10, int(frac * n))


def alpha_at(frac: float, tail: str):
    """Statistic for the bootstrap: Hill alpha at k = frac * n of the resample."""
    def stat(d):
        x = tail_values(d, tail)
        return 1.0 / hill_gamma(x, k_frac(len(x), frac))
    return stat


def xi_at_q90(tail: str):
    def stat(d):
        x = tail_values(d, tail)
        return gpd_fit(x, np.quantile(x, 0.90)).xi
    return stat


def tail_row(d: np.ndarray, stores: np.ndarray, tail: str, min_n: int = MIN_N) -> dict:
    """One line of the tail table for deviations d with their store ids."""
    x = tail_values(d, tail)
    row = {"tail": tail, "n_prices": len(d), "n_stores": len(np.unique(stores)),
           "share_zero": float(np.mean(np.asarray(d) == 0)) if len(d) else np.nan, "n_tail": len(x)}
    if len(x) < min_n:
        row["note"] = f"insufficient (< {min_n} nonzero tail observations)"
        return row
    k = k_frac(len(x), 0.05)
    a, lo, hi = cluster_bootstrap_ci(d, stores, alpha_at(0.05, tail), B=B, seed=SEED)
    path = hill_path(x)
    ks = stable_k(path)
    row.update(k=k, alpha_hill=a, alpha_ci_lo=lo, alpha_ci_hi=hi,
               k_stable=ks, alpha_stable_k=1.0 / hill_gamma(x, ks),
               k_10pct=k_frac(len(x), 0.10), alpha_k10=1.0 / hill_gamma(x, k_frac(len(x), 0.10)),
               gpd_threshold=float(np.quantile(x, 0.90)), gpd_n_exceed=int(np.sum(x > np.quantile(x, 0.90))))
    try:
        xi, xlo, xhi = cluster_bootstrap_ci(d, stores, xi_at_q90(tail), B=B, seed=SEED)
        row.update(gpd_xi=xi, xi_ci_lo=xlo, xi_ci_hi=xhi)
    except ValueError as e:
        # Prices sit on a discrete grid, so many |d| tie and few may lie
        # strictly above the 90% quantile.
        row["note"] = f"GPD not fitted: {e}"
    return row


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def dispersion_summary(dev: pd.DataFrame) -> pd.DataFrame:
    def summ(g):
        a = np.abs(g["d_reg"])
        return pd.Series({"n_prices": len(g), "n_stores": g["store_pk"].nunique(),
                          "n_products": g["chain_product_id"].nunique(),
                          "share_d_zero": float(np.mean(g["d_reg"] == 0)),
                          "sd_d": g["d_reg"].std(), "iqr_d": g["d_reg"].quantile(0.75) - g["d_reg"].quantile(0.25),
                          "q90_abs_d": a.quantile(0.90), "q99_abs_d": a.quantile(0.99), "max_abs_d": a.max(),
                          "share_promo": float(g["is_promo"].fillna(0).mean())})
    return dev.groupby(["chain", "source"]).apply(summ).reset_index()


def tail_table(dev: pd.DataFrame, min_n: int = MIN_N) -> pd.DataFrame:
    rows = []
    for (chain, source), g in dev.groupby(["chain", "source"]):
        for price_type, col in (("regular", "d_reg"), ("shelf", "d_shelf")):
            ok = g[col].notna()
            for tail in TAILS:
                r = tail_row(g.loc[ok, col].to_numpy(), g.loc[ok, "store_pk"].to_numpy(), tail, min_n)
                rows.append({"chain": chain, "source": source, "price_type": price_type, **r})
    return pd.DataFrame(rows)


def tail_by_category(dev: pd.DataFrame, min_n: int = MIN_N) -> pd.DataFrame:
    rows = []
    for (chain, cat), g in dev.groupby(["chain", "category"]):
        ok = g["d_reg"].notna()
        rows.append({"chain": chain, "category": cat, "products": g["chain_product_id"].nunique(),
                     **tail_row(g.loc[ok, "d_reg"].to_numpy(), g.loc[ok, "store_pk"].to_numpy(), "abs", min_n)})
    return pd.DataFrame(rows)


def tail_by_department(dev: pd.DataFrame, min_n: int = MIN_N) -> pd.DataFrame:
    """Grocery vs general merchandise (household, personal care, OTC, baby, pet)."""
    rows = []
    for (chain, dept), g in dev.groupby(["chain", "department"]):
        ok = g["d_reg"].notna()
        for tail in TAILS:
            rows.append({"chain": chain, "department": dept, "products": g["chain_product_id"].nunique(),
                         **tail_row(g.loc[ok, "d_reg"].to_numpy(), g.loc[ok, "store_pk"].to_numpy(), tail, min_n)})
    return pd.DataFrame(rows)


def cross_chain_table(panel: pd.DataFrame, min_n: int = MIN_N) -> pd.DataFrame:
    """Each chain's price level relative to the all-chain median for the same
    UPC, and the tail of |d_cross| pooled over chains."""
    m = cross_chain_deviations(panel)
    if m.empty:
        return pd.DataFrame([{"note": "no UPC observed at >= 2 chains (needs confirmed UPCs in config/items.csv)"}])
    rows = [{"chain": c, "n_prices": len(g), "n_upcs": g["upc"].nunique(), "n_stores": g["store_pk"].nunique(),
             "median_d_cross": g["d_cross"].median(), "mean_d_cross": g["d_cross"].mean(),
             "q10_d_cross": g["d_cross"].quantile(0.10), "q90_d_cross": g["d_cross"].quantile(0.90)}
            for c, g in m.groupby("chain")]
    pooled = tail_row(m["d_cross"].to_numpy(), m["store_pk"].to_numpy(), "abs", min_n)
    rows.append({"chain": "ALL (|d_cross| tail)", **pooled})
    return pd.DataFrame(rows)


def store_index(dev: pd.DataFrame) -> pd.DataFrame:
    """Per-store price index = mean d_reg over the store's products."""
    return (dev.groupby(["chain", "store_pk", "lat", "lon", "state", "region", "urbanicity"])
            .agg(index=("d_reg", "mean"), n_products=("d_reg", "size")).reset_index())


def clustering_table(idx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for chain, g in idx.dropna(subset=["lat", "lon", "index"]).groupby("chain"):
        if len(g) < 30:
            rows.append({"chain": chain, "n_stores": len(g), "note": "insufficient (< 30 stores)"})
            continue
        exceed = (g["index"] > g["index"].quantile(0.90)).astype(int).to_numpy()
        jc = exceedance_clustering_test(g["lat"], g["lon"], exceed, RADIUS_KM, n_perm=4999, seed=SEED)
        mi = morans_i(g["lat"], g["lon"], g["index"], RADIUS_KM, n_perm=4999, seed=SEED)
        rows.append({"chain": chain, "n_stores": len(g), "radius_km": RADIUS_KM,
                     "joincount_T": jc["T"], "joincount_T_perm_mean": jc["T_perm_mean"], "joincount_p": jc["p_value"],
                     "n_exceed": jc["n_exceed"], "morans_I": mi["I"], "morans_E_I": mi.get("E_I"),
                     "morans_p": mi["p_value"], "neighbour_pairs": mi["n_neighbour_pairs"]})
    return pd.DataFrame(rows)


def basket_costs(dev: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(per-store basket cost, basket definition) within each chain."""
    costs, defs = [], []
    for chain, g in dev.groupby("chain"):
        n_st = g["store_pk"].nunique()
        cov = g.groupby("chain_product_id")["store_pk"].nunique().sort_values(ascending=False)
        basket = cov[cov >= BASKET_COVERAGE * n_st].index[:BASKET_MAX]
        if len(basket) < BASKET_MIN:
            continue          # too few widely carried products for a meaningful basket
        names = g.drop_duplicates("chain_product_id").set_index("chain_product_id")["product_name"]
        defs += [{"chain": chain, "chain_product_id": p, "product_name": names.get(p), "stores": int(cov[p])}
                 for p in basket]
        w = g[g["chain_product_id"].isin(basket)].pivot_table(index="store_pk", columns="chain_product_id",
                                                              values="regular_price", aggfunc="first")
        full = w.dropna()
        c = full.sum(axis=1)
        costs.append(pd.DataFrame({"chain": chain, "store_pk": c.index, "basket_cost": c.values,
                                   "n_items": len(basket), "stores_with_all_items": len(full),
                                   "stores_total": n_st}))
    if not costs:
        return pd.DataFrame(), pd.DataFrame(defs)
    bc = pd.concat(costs, ignore_index=True)
    bc["rel_cost"] = bc["basket_cost"] / bc.groupby("chain")["basket_cost"].transform("median") - 1
    return bc, pd.DataFrame(defs)


def basket_risk(bc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(SEED)
    for chain, g in bc.groupby("chain"):
        r = g["rel_cost"].to_numpy()
        v, es = var_es(r, 0.95)
        boot = np.array([var_es(rng.choice(r, len(r)), 0.95) for _ in range(B)])
        row = {"chain": chain, "n_stores": len(r), "basket_items": int(g["n_items"].iloc[0]),
               "stores_total": int(g["stores_total"].iloc[0]), "median_cost": g["basket_cost"].median(),
               "VaR95_rel": v, "VaR95_ci_lo": np.quantile(boot[:, 0], 0.025), "VaR95_ci_hi": np.quantile(boot[:, 0], 0.975),
               "ES95_rel": es, "ES95_ci_lo": np.quantile(boot[:, 1], 0.025), "ES95_ci_hi": np.quantile(boot[:, 1], 0.975),
               "max_rel": r.max(), "min_rel": r.min()}
        up = np.log1p(r)
        up = up[up > 0]
        if len(up) >= 100:
            k = k_frac(len(up), 0.05)
            row.update(hill_k=k, alpha_hill_upper=1.0 / hill_gamma(up, k))
        else:
            row["hill_note"] = f"tail index not reported ({len(up)} stores above the median; need >= 100)"
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def figures(dev: pd.DataFrame, bc: pd.DataFrame, note: str, min_n: int = MIN_N) -> list[str]:
    plt = style()
    FIG.mkdir(exist_ok=True)
    out = []
    chains = [c for c in CHAIN_COLORS if c in set(dev["chain"])]
    xs = {c: tail_values(dev.loc[dev["chain"] == c, "d_reg"].dropna(), "abs") for c in chains}
    tailed = [c for c in chains if len(xs[c]) >= min_n]

    # A1: Hill plots of |d_reg| by chain, with the asymptotic 95% band and the primary k.
    if tailed:
        fig, axes = plt.subplots(1, len(tailed), figsize=(3.3 * len(tailed), 2.8), sharey=True, squeeze=False)
        for ax, c in zip(axes[0], tailed):
            p = hill_path(xs[c])
            col = CHAIN_COLORS[c]
            ax.fill_between(p["k"], p["lo"], p["hi"], color=col, alpha=0.18, linewidth=0)
            ax.plot(p["k"], p["alpha"], color=col)
            k5 = k_frac(len(xs[c]), 0.05)
            ax.axvline(k5, color=MUTED, linewidth=0.8, linestyle="--")
            ax.text(k5, ax.get_ylim()[1] if ax.get_ylim()[1] < 50 else 10, " k = 5%", color=MUTED, fontsize=7, va="top")
            ax.set_title(f"{c.capitalize()} (n = {len(xs[c]):,} nonzero |d|)")
            ax.set_xlabel("k (upper order statistics)")
        axes[0][0].set_ylabel("Hill estimate of α")
        fig.suptitle("Hill plots of |d|, regular prices", x=0.01, ha="left", fontsize=10)
        caption(fig, note + " Band: asymptotic 95% interval; reported CIs use a store-cluster bootstrap.")
        fig.savefig(FIG / "fig_a1_hill_plots.png")
        plt.close(fig)
        out.append("fig_a1_hill_plots.png")

    # A2: log-log empirical survival function of |d| by chain.
    if any(len(xs[c]) for c in chains):
        fig, ax = plt.subplots(figsize=(4.6, 3.3))
        for c in chains:
            x = np.sort(xs[c])
            if len(x) == 0:
                continue
            surv = 1.0 - np.arange(len(x)) / len(x)
            ax.loglog(x, surv, color=CHAIN_COLORS[c], linewidth=1.5, label=f"{c.capitalize()} (n = {len(x):,})")
            ax.annotate(c.capitalize(), (x[-1], surv[-1]), color=MUTED, fontsize=7,
                        xytext=(3, 0), textcoords="offset points", va="center")
        from matplotlib.ticker import NullFormatter
        ax.xaxis.set_minor_formatter(NullFormatter())   # minor labels collide on short log ranges
        ax.set_xlabel("|d| = |log price − log chain median|")
        ax.set_ylabel("P(|d| > x), nonzero |d|")
        ax.set_title("Empirical survival of price deviations (log-log)", loc="left")
        ax.legend(loc="lower left", fontsize=7)
        caption(fig, note + " A straight line in the tail suggests a power law with slope −α.")
        fig.savefig(FIG / "fig_a2_survival_loglog.png")
        plt.close(fig)
        out.append("fig_a2_survival_loglog.png")

    # A3: mean excess plots (roughly linear above a threshold where the GPD fits).
    if tailed:
        fig, ax = plt.subplots(figsize=(4.6, 3.3))
        for c in tailed:
            x = xs[c]
            us = np.quantile(x, np.linspace(0.5, 0.97, 40))
            ax.plot(us, mean_excess(x, us), color=CHAIN_COLORS[c], marker="o", markersize=3,
                    label=c.capitalize())
            ax.axvline(np.quantile(x, 0.9), color=CHAIN_COLORS[c], linewidth=0.8, linestyle=":")
        ax.set_xlabel("threshold u (|d|)")
        ax.set_ylabel("mean excess E[|d| − u | |d| > u]")
        ax.set_title("Mean excess of |d|; dotted = GPD threshold (90% quantile)", loc="left")
        ax.legend(fontsize=7)
        caption(fig, note)
        fig.savefig(FIG / "fig_a3_mean_excess.png")
        plt.close(fig)
        out.append("fig_a3_mean_excess.png")

    # A4: distribution of basket cost relative to the chain median.
    if not bc.empty:
        bchains = [c for c in chains if c in set(bc["chain"])]
        fig, axes = plt.subplots(1, len(bchains), figsize=(3.3 * len(bchains), 2.6), squeeze=False)
        for ax, c in zip(axes[0], bchains):
            g = bc[bc["chain"] == c]
            r = 100 * g["rel_cost"]
            ax.hist(r, bins=30, color=CHAIN_COLORS[c], edgecolor="white", linewidth=0.6)
            v, _ = var_es(g["rel_cost"].to_numpy(), 0.95)
            ax.axvline(100 * v, color=MUTED, linestyle="--", linewidth=0.8)
            ax.text(100 * v, ax.get_ylim()[1], " VaR95", color=MUTED, fontsize=7, va="top")
            ax.set_title(f"{c.capitalize()}: {int(g['n_items'].iloc[0])} items, {len(g)} stores")
            ax.set_xlabel("basket cost vs chain median (%)")
        axes[0][0].set_ylabel("stores")
        caption(fig, note)
        fig.savefig(FIG / "fig_a4_basket_cost.png")
        plt.close(fig)
        out.append("fig_a4_basket_cost.png")
    return out


# ---------------------------------------------------------------------------

def run(snaps: list[int] | None = None, min_stores: int = MIN_STORES, min_n: int = MIN_N) -> str:
    snaps = snaps or main_snapshots()[:1]
    if not snaps:
        return "Module A: no main snapshot configured in config/analysis.yaml yet."
    obs = load_observations(snapshot_id=snaps)
    if obs.empty:
        return "Module A: no store-specific observations in the configured snapshot."
    panel = product_panel(obs, min_stores=min_stores)
    dev = add_deviations(panel)
    if dev.empty:
        return f"Module A: no product is observed at >= {min_stores} stores."
    note = sample_size_note(dev)
    TAB.mkdir(exist_ok=True)
    bc, bdef = basket_costs(dev)
    idx = store_index(dev)
    tables = {
        "module_a_dispersion_summary": dispersion_summary(dev),
        "module_a_tail_index_by_chain": tail_table(dev, min_n),
        "module_a_tail_index_by_category": tail_by_category(dev, min_n),
        "module_a_tail_index_by_department": tail_by_department(dev, min_n),
        # Sensitivity: Hawaii and Alaska carry large real price premia
        # (shipping); in a partial run of snapshot 2 the largest Walmart
        # deviations were all one Honolulu store (milk $6.28 vs median $2.97).
        "module_a_tail_index_excl_HI_AK": tail_table(dev[~dev["state"].isin(["HI", "AK"])], min_n),
        "module_a_cross_chain": cross_chain_table(panel, min_n),
        "module_a_store_index": idx,
        "module_a_spatial_clustering": clustering_table(idx),
        "module_a_basket_definition": bdef,
        "module_a_basket_risk": basket_risk(bc) if not bc.empty else pd.DataFrame(),
    }
    for name, t in tables.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    figs = figures(dev, bc, note, min_n)
    (TAB / "module_a_sample_size.txt").write_text(note + "\n", encoding="utf-8")
    return f"Module A: wrote {len(tables)} tables and {len(figs)} figures. {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
