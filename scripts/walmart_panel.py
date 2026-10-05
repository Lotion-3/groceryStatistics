"""Walmart repeat-visit panel (owner-approved 2026-10-04; DECISIONS #52, experiments T2/T3).

The same 10 Walmart stores and the 17 items with an owner-confirmed Walmart
product id, visited three times a day (08:00, 14:00, 20:00 Eastern) from Mon
Oct 5 to Thu Oct 8, around the Kroger promotion expiry. Each visit is its own
snapshot ("walmart panel <time>").

What it measures (no new endpoints; the same search the snapshots use):
  * T2 intraday repricing: does a store's price for a product change within a
    day (vs between days)?
  * T3 persistence of Walmart's local departures (prices off the national list).
  * Side signals kept by the parser in `extra` (DECISIONS #51 notes): earliest
    pickup/delivery slot from the store (lead time = slot - observation time),
    "Only N left" / "Low stock", "N+ bought since yesterday".

Traffic: about 170 searches per visit at >= 5 s (about 15 min), 11 visits in total.
Each store needs a store-scoped session (the collector's normal scoping flow; cached
for up to 6 h). A block stops the visit and the chain's pause policy applies
(collectors/session_stash.py).

  python -m scripts.walmart_panel select      # choose the stores (no network)
  python -m scripts.walmart_panel visit       # one visit (retailer traffic)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from collectors.common import ROOT
from db.init_db import DEFAULT_DB

PANEL = ROOT / "config" / "walmart_panel.csv"
N_STORES = 10
SEED = 20261004


def select(n: int = N_STORES) -> pd.DataFrame:
    from sampling.visit_order import maximin_order
    con = sqlite3.connect(DEFAULT_DB)
    st = pd.read_sql_query("""SELECT DISTINCT s.store_pk, s.store_id, s.name, s.lat, s.lon, s.zip, s.state,
                                     s.anchor_zip
                              FROM stores s JOIN observations o USING (store_pk)
                              WHERE s.chain = 'walmart' AND o.snapshot_id = 2 AND s.anchor_zip IS NOT NULL
                                AND s.lat IS NOT NULL""", con)
    con.close()
    st = st[~st["state"].isin(["HI", "AK"])].reset_index(drop=True)
    order = maximin_order(st["lat"].to_numpy(float), st["lon"].to_numpy(float), np.random.default_rng(SEED))
    panel = st.iloc[list(order)[:n]]
    panel.to_csv(PANEL, index=False)
    return panel


def visit() -> int:
    from collectors.common import end_snapshot, start_snapshot
    from collectors.snapshot import Run, read_csv
    from db.init_db import connect, load_items
    con = connect(DEFAULT_DB)
    load_items(con)
    items = [it for it in read_csv(ROOT / "config" / "items.csv") if it.get("walmart_id")]
    panel = pd.read_csv(PANEL, dtype={"anchor_zip": str, "zip": str, "store_id": str})
    snap = start_snapshot(con, f"walmart panel {datetime.now(timezone.utc).isoformat(timespec='minutes')}")
    print(f"snapshot {snap}: {len(panel)} stores x {len(items)} items", flush=True)
    r = Run(con, snap, ["walmart"])
    try:
        for i, p in enumerate(panel.itertuples(), 1):
            print(f"[{i}/{len(panel)}] Walmart {p.store_id} (anchor {p.anchor_zip})", flush=True)
            r.walmart({"zip": p.anchor_zip, "lat": p.lat, "lon": p.lon}, items)
            if "walmart" not in r.active:
                print("walmart stopped for this visit", flush=True)
                break
    finally:
        end_snapshot(con, snap)
    return snap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["select", "visit"])
    ap.add_argument("--n", type=int, default=N_STORES)
    a = ap.parse_args(argv)
    if a.step == "select":
        p = select(a.n)
        print(p[["store_id", "name", "state", "anchor_zip"]].to_string(index=False))
    else:
        print("panel snapshot:", visit())
    return 0


if __name__ == "__main__":
    sys.exit(main())
