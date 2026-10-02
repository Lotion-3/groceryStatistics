"""Coverage and missingness report (spec section 9). Runs first in run_all.py.

For each main snapshot and chain:
  * stores reached: stores with at least one observation or item-level failure
  * pair coverage: (store, item) pairs with >= 1 returned product, out of
    stores reached x items; and the same counting only store-specific rows
  * the share of returned rows that are tied to the queried store
  * failures by reason category (the text before the first ':')
Coverage is broken down by region and urbanicity of the store. Chains below
60% store-specific pair coverage are flagged (spec: consider dropping them
from the main analysis).

Missingness is data: these tables go into the write-up as they are.
"""
from __future__ import annotations

import sqlite3
import sys

import pandas as pd

from analysis.common import DB, ROOT, TAB, main_snapshots

FLAG_BELOW = 0.60


def _pairs(con, snaps: list[int]) -> pd.DataFrame:
    """One row per (snapshot, store, item) with any observation."""
    q = f"""
    SELECT o.snapshot_id, s.chain, o.store_pk, s.region, s.urbanicity, o.item_id,
           COUNT(*) AS rows, SUM(o.store_specific) AS spec_rows
    FROM observations o JOIN stores s USING (store_pk)
    WHERE o.snapshot_id IN ({','.join('?' * len(snaps))})
    GROUP BY o.snapshot_id, o.store_pk, o.item_id"""
    return pd.read_sql_query(q, con, params=snaps)


def coverage_tables(db=DB, snaps: list[int] | None = None) -> dict[str, pd.DataFrame]:
    snaps = snaps or main_snapshots(db)
    con = sqlite3.connect(db)
    # Intended items = the current config/items.csv (the items table also keeps
    # items dropped from the list, e.g. the 15 swapped out in DECISIONS #28).
    intended = set(pd.read_csv(ROOT / "config" / "items.csv", dtype=str)["item_id"])
    n_items = len(intended)
    pairs = _pairs(con, snaps)
    pairs = pairs[pairs["item_id"].isin(intended)]
    fails = pd.read_sql_query(
        f"""SELECT f.snapshot_id, f.chain, f.store_pk, f.item_id, f.reason, s.region, s.urbanicity
            FROM collection_failures f LEFT JOIN stores s USING (store_pk)
            WHERE f.snapshot_id IN ({','.join('?' * len(snaps))})""", con, params=snaps)
    con.close()

    # Stores reached = seen in observations or in an item-level failure.
    reached = pd.concat([pairs[["snapshot_id", "chain", "store_pk", "region", "urbanicity"]],
                         fails.dropna(subset=["store_pk"])[["snapshot_id", "chain", "store_pk",
                                                            "region", "urbanicity"]]]).drop_duplicates()

    def summarise(keys: list[str]) -> pd.DataFrame:
        st = reached.groupby(keys)["store_pk"].nunique().rename("stores_reached")
        got = pairs.groupby(keys).agg(pairs_any=("item_id", "size"),
                                      pairs_store_specific=("spec_rows", lambda s: int((s > 0).sum())),
                                      rows=("rows", "sum"), spec_rows=("spec_rows", "sum"))
        t = st.to_frame().join(got).fillna(0).reset_index()
        t["pairs_intended"] = t["stores_reached"] * n_items
        t["coverage_any"] = t["pairs_any"] / t["pairs_intended"]
        t["coverage_store_specific"] = t["pairs_store_specific"] / t["pairs_intended"]
        t["share_rows_store_specific"] = t["spec_rows"] / t["rows"].where(t["rows"] > 0)
        return t

    by_chain = summarise(["snapshot_id", "chain"])
    by_chain["flag_below_60pct"] = by_chain["coverage_store_specific"] < FLAG_BELOW
    by_region = summarise(["snapshot_id", "chain", "region", "urbanicity"])

    fails["reason_category"] = fails["reason"].str.split(":").str[0].str.slice(0, 60)
    by_reason = (fails.groupby(["snapshot_id", "chain", "reason_category"]).size()
                 .rename("n").reset_index().sort_values(["snapshot_id", "chain", "n"], ascending=[True, True, False]))
    return {"coverage_by_chain": by_chain, "coverage_by_region": by_region, "failures_by_reason": by_reason}


def run() -> str:
    snaps = main_snapshots()
    if not snaps:
        return "Coverage: no main snapshot configured in config/analysis.yaml yet."
    TAB.mkdir(exist_ok=True)
    tabs = coverage_tables(snaps=snaps)
    for name, t in tabs.items():
        t.to_csv(TAB / f"{name}.csv", index=False)
    c = tabs["coverage_by_chain"]
    lines = [f"  snap {r.snapshot_id} {r.chain:<8} stores={r.stores_reached:>4}  "
             f"pairs(any)={r.coverage_any:.0%}  pairs(store-specific)={r.coverage_store_specific:.0%}"
             + ("  <-- BELOW 60%" if r.flag_below_60pct else "") for r in c.itertuples()]
    return "Coverage: wrote tables/coverage_*.csv\n" + "\n".join(lines)


if __name__ == "__main__":
    print(run())
    sys.exit(0)
