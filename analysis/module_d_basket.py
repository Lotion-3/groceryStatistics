"""Module D: cheapest way to buy a fixed basket, visiting at most k stores (Lee, Song).

Setting. For each sampled anchor location (a sampled Target store), the
candidate stores are all sampled Target and Walmart stores within RADIUS_KM.
A shopper must buy one unit of every basket item; item i at store s costs
p_is (regular shelf price; promo prices as a sensitivity). Which <= k stores
should they visit, and what do they save versus the best single store?

Exact solution: a small integer program (PuLP with the HiGHS solver)
    min  sum_is p_is x_is
    s.t. sum_s x_is = 1           every item bought once, where it is sold
         x_is <= y_s              only at visited stores
         sum_s y_s <= k           at most k stores
         x, y binary
Heuristic: greedy (best single store, then repeatedly add the store that
lowers the basket cost most). Reported: the greedy-vs-optimal gap.

Cross-chain decomposition: the optimum when all visited stores must belong to
ONE chain, versus the unrestricted optimum. The difference is the part of the
saving that exists only because the two chains price differently (a
law-of-one-price violation a shopper can exploit).

Item identity: the owner-confirmed product ids (items.walmart_id /
items.target_tcin). Until those are filled in, the best automatic candidate
from config/items_resolved.csv is used and every output is marked
PROVISIONAL. Costco is excluded (its pack sizes rarely match).

Not modelled: travel cost and time (k caps the number of visits instead),
taxes, availability beyond what the search returned. PRELIMINARY.
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
import pandas as pd

from analysis.common import (CHAIN_COLORS, DB, FIG, MUTED, ROOT, TAB, caption, load_observations,
                             main_snapshots, style)
from analysis.estimators import haversine_km

RADIUS_KM = 25.0
KS = (1, 2, 3)
CHAINS = ("target", "walmart")
MIN_BASKET_COVERAGE = 0.80     # an item enters the basket if priced at >= 80% of each chain's stores


# ---------------------------------------------------------------------------
# Item prices per store
# ---------------------------------------------------------------------------

def item_product_ids(db=DB) -> tuple[pd.DataFrame, bool]:
    """(item_id, chain, chain_product_id) and whether it is provisional."""
    import sqlite3
    con = sqlite3.connect(db)
    it = pd.read_sql_query("SELECT item_id, walmart_id, target_tcin FROM items", con)
    con.close()
    confirmed = pd.concat([
        it.dropna(subset=["walmart_id"]).assign(chain="walmart", chain_product_id=lambda d: d["walmart_id"]),
        it.dropna(subset=["target_tcin"]).assign(chain="target", chain_product_id=lambda d: d["target_tcin"]),
    ])[["item_id", "chain", "chain_product_id"]]
    if not confirmed.empty:
        return confirmed, False
    res = ROOT / "config" / "items_resolved.csv"
    if not res.exists():
        return confirmed, True
    r = pd.read_csv(res, dtype=str)
    r = r[r["chain"].isin(CHAINS)]
    return r[["item_id", "chain", "chain_product_id"]], True


def price_matrix(obs: pd.DataFrame, ids: pd.DataFrame, col: str = "regular_price") -> pd.DataFrame:
    """Stores x items of the identified product's price (store-specific rows)."""
    o = obs[obs["chain"].isin(CHAINS)].merge(ids, on=["item_id", "chain", "chain_product_id"])
    o = o.dropna(subset=[col])
    return o.pivot_table(index="store_pk", columns="item_id", values=col, aggfunc="min")


def basket_items(P: pd.DataFrame, stores: pd.DataFrame) -> list[str]:
    """Items priced at >= MIN_BASKET_COVERAGE of the stores of EACH chain."""
    ch = stores.set_index("store_pk").loc[P.index, "chain"]
    cov = P.notna().groupby(ch.values).mean()
    ok = (cov.reindex(list(CHAINS)) >= MIN_BASKET_COVERAGE).all(axis=0)
    return list(ok[ok].index)


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------

def solve_exact(P: np.ndarray, k: int) -> tuple[float, list[int]]:
    """MILP optimum for a (stores x items) price array with NaN = not sold.
    Returns (cost, chosen store indices); (nan, []) if infeasible."""
    import pulp
    S, I = P.shape
    avail = ~np.isnan(P)
    if not avail.any(axis=0).all():
        return np.nan, []
    prob = pulp.LpProblem("basket", pulp.LpMinimize)
    # PuLP >= 4: variables are created through the problem
    y = [prob.add_variable(f"y{s}", cat="Binary") for s in range(S)]
    x = {(i, s): prob.add_variable(f"x{i}_{s}", cat="Binary") for i in range(I) for s in range(S) if avail[s, i]}
    prob += pulp.lpSum(P[s, i] * v for (i, s), v in x.items())
    for i in range(I):
        prob += pulp.lpSum(x[i, s] for s in range(S) if avail[s, i]) == 1
    for (i, s), v in x.items():
        prob += v <= y[s]
    prob += pulp.lpSum(y) <= k
    stats = prob.solve(pulp.HiGHS(msg=False))      # HiGHS: open-source MILP solver (highspy)
    if stats.status != pulp.LpSolveStatus.Optimal:
        return np.nan, []
    return float(stats.objective), [s for s in range(S) if y[s].value() > 0.5]


def basket_cost(P: np.ndarray, stores: list[int]) -> float:
    """Cost of buying every item at its cheapest store among `stores`."""
    sub = P[stores]
    if np.isnan(sub).all(axis=0).any():
        return np.nan
    return float(np.nansum(np.nanmin(sub, axis=0)))


def solve_greedy(P: np.ndarray, k: int) -> tuple[float, list[int]]:
    """Best feasible single store, then add the store that lowers cost most."""
    S = P.shape[0]
    singles = [(basket_cost(P, [s]), s) for s in range(S)]
    singles = [t for t in singles if np.isfinite(t[0])]
    if not singles:
        return np.nan, []
    cost, s0 = min(singles)
    chosen = [s0]
    while len(chosen) < k:
        cands = [(basket_cost(P, chosen + [s]), s) for s in range(S) if s not in chosen]
        cands = [t for t in cands if np.isfinite(t[0])]
        if not cands:
            break
        c, s = min(cands)
        if c >= cost - 1e-9:
            break
        cost, chosen = c, chosen + [s]
    return cost, chosen


def solve_brute(P: np.ndarray, k: int) -> float:
    """Exhaustive check (used in tests on small instances)."""
    S = P.shape[0]
    costs = [basket_cost(P, list(c)) for r in range(1, k + 1) for c in itertools.combinations(range(S), r)]
    costs = [c for c in costs if np.isfinite(c)]
    return min(costs) if costs else np.nan


# ---------------------------------------------------------------------------

def anchors_table(P: pd.DataFrame, items: list[str], stores: pd.DataFrame, anchors: pd.DataFrame) -> pd.DataFrame:
    st = stores.set_index("store_pk").loc[P.index]
    lat, lon = st["lat"].to_numpy(float), st["lon"].to_numpy(float)
    chain = st["chain"].to_numpy()
    Pm = P[items].to_numpy(float)
    rows = []
    for a in anchors.itertuples():
        d = haversine_km(a.lat, a.lon, lat, lon)
        near = np.flatnonzero(d <= RADIUS_KM)
        if len(near) < 2:
            continue
        sub = Pm[near]
        row = {"anchor_store_pk": a.store_pk, "state": a.state, "region": a.region, "urbanicity": a.urbanicity,
               "n_candidates": len(near), "n_target": int((chain[near] == "target").sum()),
               "n_walmart": int((chain[near] == "walmart").sum()), "basket_items": len(items)}
        for k in KS:
            opt, chosen = solve_exact(sub, k)
            gr, _ = solve_greedy(sub, k)
            row[f"cost_k{k}"] = opt
            row[f"greedy_k{k}"] = gr
            row[f"chains_k{k}"] = "+".join(sorted(set(chain[near][chosen]))) if chosen else None
            # best when every visited store must be of one chain
            same = [solve_exact(sub[chain[near] == c], k)[0] for c in CHAINS if (chain[near] == c).any()]
            row[f"same_chain_k{k}"] = np.nanmin(same) if np.isfinite(same).any() else np.nan
        rows.append(row)
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    for k in KS[1:]:
        t[f"saving_pct_k{k}"] = 100 * (1 - t[f"cost_k{k}"] / t["cost_k1"])
        # share of the k-store saving that needs BOTH chains
        tot = t["cost_k1"] - t[f"cost_k{k}"]
        t[f"cross_chain_share_k{k}"] = (t[f"same_chain_k{k}"] - t[f"cost_k{k}"]) / tot.where(tot > 1e-9)
    for k in KS:
        t[f"greedy_gap_pct_k{k}"] = 100 * (t[f"greedy_k{k}"] / t[f"cost_k{k}"] - 1)
    return t


def summary(t: pd.DataFrame, provisional: bool) -> pd.DataFrame:
    rows = []
    for k in KS:
        r = {"k": k, "anchors": int(t[f"cost_k{k}"].notna().sum()), "median_cost": t[f"cost_k{k}"].median(),
             "greedy_optimal_share": float((t[f"greedy_gap_pct_k{k}"].abs() < 1e-6).mean()),
             "greedy_gap_pct_max": t[f"greedy_gap_pct_k{k}"].max(), "provisional_items": provisional}
        if k > 1:
            s = t[f"saving_pct_k{k}"]
            r.update(saving_pct_median=s.median(), saving_pct_q10=s.quantile(0.10), saving_pct_q90=s.quantile(0.90),
                     cross_chain_share_median=t[f"cross_chain_share_k{k}"].median(),
                     share_optimum_mixes_chains=float(t[f"chains_k{k}"].str.contains(r"\+", na=False).mean()))
        rows.append(r)
    return pd.DataFrame(rows)


def figures(t: pd.DataFrame, note: str) -> list[str]:
    plt = style()
    fig, ax = plt.subplots(figsize=(4.6, 3.0))
    data = [t[f"saving_pct_k{k}"].dropna() for k in KS[1:]]
    for j, (k, v) in enumerate(zip(KS[1:], data)):
        jitter = np.random.default_rng(j).uniform(-0.12, 0.12, len(v))
        ax.scatter(j + jitter, v, s=8, color=CHAIN_COLORS["target"] if k == 2 else CHAIN_COLORS["walmart"],
                   alpha=0.6, edgecolors="none")
        ax.hlines(v.median(), j - 0.25, j + 0.25, color="#1f1f1e", linewidth=2)
    ax.set_xticks(range(len(data)), [f"≤ {k} stores (n = {len(v)})" for k, v in zip(KS[1:], data)])
    ax.set_ylabel("saving vs best single store (%)")
    ax.set_title(f"Basket savings from visiting more stores (within {RADIUS_KM:.0f} km)", loc="left")
    caption(fig, note + " Bar = median. Travel cost not included.")
    fig.savefig(FIG / "fig_d1_basket_savings.png")
    plt.close(fig)
    return ["fig_d1_basket_savings.png"]


def run(snaps: list[int] | None = None) -> str:
    snaps = snaps or main_snapshots()[:1]
    if not snaps:
        return "Module D: no main snapshot configured in config/analysis.yaml yet."
    obs = load_observations(snapshot_id=snaps)
    ids, provisional = item_product_ids()
    if ids.empty:
        return "Module D: no item -> product ids (confirm items or run collectors.resolve_items)."
    P = price_matrix(obs, ids)
    stores = obs.drop_duplicates("store_pk")[["store_pk", "chain", "lat", "lon", "state", "region", "urbanicity"]]
    stores = stores[stores["store_pk"].isin(P.index) & stores["lat"].notna()]
    P = P.loc[stores["store_pk"]]
    items = basket_items(P, stores)
    if len(items) < 5:
        return f"Module D: only {len(items)} items priced widely at both chains; need >= 5."
    anchors = stores[stores["chain"] == "target"]
    t = anchors_table(P, items, stores, anchors)
    if t.empty:
        return "Module D: no anchor has >= 2 candidate stores within the radius."
    tag = " PROVISIONAL item matching (unconfirmed ids)." if provisional else ""
    note = (f"n = {len(t)} anchor locations, {len(P)} stores, basket of {len(items)} items; snapshot(s) {snaps}. "
            f"PRELIMINARY, cross-sectional.{tag}")
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    t.to_csv(TAB / "module_d_anchor_results.csv", index=False)
    summary(t, provisional).to_csv(TAB / "module_d_summary.csv", index=False)
    pd.DataFrame({"item_id": items}).to_csv(TAB / "module_d_basket_items.csv", index=False)
    figs = figures(t, note)
    return f"Module D: wrote 3 tables and {len(figs)} figure(s). {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
