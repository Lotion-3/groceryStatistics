"""Module I: the Walmart repeat-visit panel (DECISIONS #52; experiments T2, T3).

Visits (snapshots "walmart panel <UTC time>", 10 stores, three a day) give, for
each store-product, a short price series. Units are store-specific rows only.

T2  Intraday repricing. For consecutive visits to the same store, the share of
    store-products whose shelf price changed, split into transitions within a
    store-local day vs across a night. Rates with store-cluster bootstrap CIs.
T3  Persistence of local departures. A product's list price is its modal price
    across Walmart stores in snapshot 2 (41 stores). Each store-product-visit is
    at list (0) or off list (1). The pooled 2-state transition matrix gives
    P(stay off list) per transition and the implied mean sojourn off list.
Slots  Earliest delivery/pickup slot from the store minus observation time
    (lead time, hours), decomposed into store and visit-time components.

PRELIMINARY; 10 stores, a few days; associations only.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

from analysis.common import DB, SEED, TAB, load_observations

_TZ = {**{s: -4 for s in "CT DE DC FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV".split()},
       **{s: -5 for s in "AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI".split()},
       **{s: -6 for s in "CO ID MT NM UT WY".split()}, **{s: -7 for s in "CA NV OR WA AZ".split()}}


def panel_snapshots() -> list[int]:
    con = sqlite3.connect(DB)
    ids = [r[0] for r in con.execute("""SELECT snapshot_id FROM snapshots WHERE notes LIKE 'walmart panel 20%'
                                        ORDER BY started_at""")]
    con.close()
    return ids


def tidy(obs: pd.DataFrame) -> pd.DataFrame:
    o = obs[(obs["chain"] == "walmart") & (obs["store_specific"] == 1)].dropna(subset=["price"]).copy()
    ex = o["extra"].map(lambda e: json.loads(e) if isinstance(e, str) else (e or {}))
    o["t"] = pd.to_datetime(o["observed_at"], utc=True, format="ISO8601")
    off = o["state"].map(_TZ).fillna(-5)
    o["local"] = o["t"] + pd.to_timedelta(off, unit="h")
    o["shelf"] = o["price"].round(2)
    for k in ("slot_delivery", "slot_pickup"):
        o[k] = pd.to_datetime(ex.map(lambda e: e.get(k)), utc=True, errors="coerce", format="ISO8601")
    o["low_stock"] = ex.map(lambda e: e.get("low_stock"))
    o = o.sort_values("t").drop_duplicates(["snapshot_id", "store_pk", "chain_product_id"], keep="last")
    return o[["snapshot_id", "store_pk", "state", "chain_product_id", "t", "local", "shelf", "slot_delivery",
              "slot_pickup", "low_stock"]]


def transitions(p: pd.DataFrame) -> pd.DataFrame:
    """Consecutive visits per store-product: changed?, same local day?"""
    p = p.sort_values(["store_pk", "chain_product_id", "t"])
    g = p.groupby(["store_pk", "chain_product_id"])
    out = p.assign(prev_shelf=g["shelf"].shift(), prev_local=g["local"].shift(), prev_snap=g["snapshot_id"].shift())
    out = out.dropna(subset=["prev_shelf"])
    out["changed"] = out["shelf"] != out["prev_shelf"]
    out["kind"] = np.where(out["local"].dt.date == out["prev_local"].dt.date, "intraday", "overnight")
    return out


def cluster_rate(x: pd.Series, clusters: pd.Series, rng, B: int = 1000) -> tuple[float, float, float]:
    x, c = x.astype(float).to_numpy(), clusters.to_numpy()
    u = np.unique(c)
    est = float(x.mean()) if len(x) else np.nan
    if len(u) < 2:
        return est, np.nan, np.nan
    idx = {k: np.flatnonzero(c == k) for k in u}
    bs = [x[np.concatenate([idx[k] for k in rng.choice(u, len(u))])].mean() for _ in range(B)]
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def list_prices() -> pd.Series:
    """Walmart list price per product: modal regular price across stores, snapshot 2."""
    o = load_observations(snapshot_id=[2])
    o = o[(o["chain"] == "walmart") & (o["store_specific"] == 1)].dropna(subset=["regular_price"])
    return o.assign(c=o["regular_price"].round(2)).groupby("chain_product_id")["c"].agg(lambda s: s.mode().iloc[0])


def analyse(p: pd.DataFrame, lp: pd.Series, seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    tr = transitions(p)
    t2 = []
    for kind, g in tr.groupby("kind"):
        est, lo, hi = cluster_rate(g["changed"], g["store_pk"], rng)
        t2.append({"transition": kind, "n": int(len(g)), "stores": int(g["store_pk"].nunique()),
                   "change_rate": est, "ci_lo": lo, "ci_hi": hi, "changes": int(g["changed"].sum())})
    q = p[p["chain_product_id"].isin(lp.index)].copy()
    q["off"] = (q["shelf"] != lp.reindex(q["chain_product_id"]).to_numpy()).astype(int)
    qt = transitions(q.assign(shelf=q["off"]))           # reuse: 'changed' = state switch
    qt["prev_off"] = qt["prev_shelf"].astype(int)
    m = pd.crosstab(qt["prev_off"], qt["shelf"].astype(int))
    p_stay_off = float(m.loc[1, 1] / m.loc[1].sum()) if 1 in m.index and m.loc[1].sum() else np.nan
    t3 = pd.DataFrame([{"units": int(q.groupby(["store_pk", "chain_product_id"]).ngroups),
                        "share_off_list": float(q["off"].mean()) if len(q) else np.nan,
                        "transitions": int(len(qt)), "p_stay_off": p_stay_off,
                        "p_off_to_on": 1 - p_stay_off if np.isfinite(p_stay_off) else np.nan,
                        "p_on_to_off": float(m.loc[0, 1] / m.loc[0].sum()) if 0 in m.index and 1 in m.columns else 0.0,
                        "mean_visits_off_list": 1 / (1 - p_stay_off) if np.isfinite(p_stay_off) and p_stay_off < 1 else np.inf}])
    sv = p.drop_duplicates(["snapshot_id", "store_pk"]).copy()
    for k in ("slot_delivery", "slot_pickup"):
        sv[k] = pd.to_datetime(sv[k], utc=True, errors="coerce")
    sv["lead_delivery_h"] = (sv["slot_delivery"] - sv["t"]).dt.total_seconds() / 3600
    sv["lead_pickup_h"] = (sv["slot_pickup"] - sv["t"]).dt.total_seconds() / 3600
    rows = []
    for col in ("lead_delivery_h", "lead_pickup_h"):
        d = sv.dropna(subset=[col])
        if len(d) < 4:
            continue
        tot = d[col].var()
        within_store = d.groupby("store_pk")[col].var().mean()
        rows.append({"lead": col, "store_visits": int(len(d)), "mean_h": float(d[col].mean()),
                     "median_h": float(d[col].median()), "share_var_between_stores": float(1 - within_store / tot) if tot else np.nan,
                     "by_local_hour": "; ".join(f"{h:02d}h {v:.1f}" for h, v in d.groupby(d["local"].dt.hour)[col].median().items())})
    return {"module_i_t2_change_rates": pd.DataFrame(t2), "module_i_t3_departure_persistence": t3,
            "module_i_slot_lead_times": pd.DataFrame(rows)}


def run() -> str:
    snaps = panel_snapshots()
    if len(snaps) < 2:
        return f"Module I: Walmart panel visits so far: {len(snaps)} (need >= 2)."
    p = tidy(load_observations(snapshot_id=snaps))
    tabs = analyse(p, list_prices())
    TAB.mkdir(exist_ok=True)
    for name, t in tabs.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    return f"Module I: {len(snaps)} Walmart panel visits, {p['store_pk'].nunique()} stores; wrote {len(tabs)} tables."


if __name__ == "__main__":
    print(run())
    sys.exit(0)
