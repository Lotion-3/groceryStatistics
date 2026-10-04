"""Kroger daily panel (Plan Q4): the same Kroger stores and items, once a day.

Purpose. Snapshot 2 is one cross-section. A short daily panel shows which
prices CHANGE from day to day, and lets us test whether stores in the same
inferred pricing zone (Module E) change prices together -- independent,
dynamic evidence for the zones.

Source: Kroger's official production API only (KROGER_BASE_URL must point at
api.kroger.com), paced at >= 9 s per request (collectors/common.py), within
the published 10,000 calls/day: about 60 stores x 58 items = ~3,500 calls/day.

Steps
  select   choose the panel from Kroger stores already collected in snapshot 2:
           proportional across banners (largest remainder), and within a
           banner in farthest-point order so the panel is spread out.
           Writes config/kroger_panel.csv. No network.
  run      one panel day: a new snapshot (notes "kroger panel <date>") with
           every panel store x every item. Resumable with --snapshot-id.
           NEEDS THE OWNER'S GO-AHEAD (retailer API traffic).

  python -m scripts.kroger_panel select [--n 60]
  python -m scripts.kroger_panel run [--snapshot-id N]
Afterwards add the panel snapshot ids to `panel_snapshots` in config/analysis.yaml.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from collectors.common import ROOT
from db.init_db import DEFAULT_DB

PANEL = ROOT / "config" / "kroger_panel.csv"
SEED = 20261004


def _banner(name: str) -> str:
    return (name or "").split()[0].upper() if name else ""


def select(n: int = 60, snapshot: int = 2) -> pd.DataFrame:
    from sampling.visit_order import maximin_order
    con = sqlite3.connect(DEFAULT_DB)
    st = pd.read_sql_query(
        """SELECT DISTINCT s.store_pk, s.store_id, s.name, s.lat, s.lon, s.zip, s.state
           FROM stores s JOIN observations o USING (store_pk)
           WHERE s.chain = 'kroger' AND o.snapshot_id = ? AND s.lat IS NOT NULL""", con, params=(snapshot,))
    con.close()
    st = st[~st["state"].isin(["HI", "AK"]) & ~st["name"].str.lower().str.contains("spoke")].copy()
    st["banner"] = st["name"].map(_banner)
    sizes = st["banner"].value_counts()
    n = min(n, len(st))
    exact = sizes / sizes.sum() * n
    alloc = np.floor(exact).astype(int)
    for b in (exact - alloc).sort_values(ascending=False).index[: n - alloc.sum()]:
        alloc[b] += 1
    rng = np.random.default_rng(SEED)
    parts = []
    for b, k in alloc.items():
        g = st[st["banner"] == b].reset_index(drop=True)
        order = maximin_order(g["lat"].to_numpy(float), g["lon"].to_numpy(float), rng)
        parts.append(g.iloc[order[:k]])
    panel = pd.concat(parts, ignore_index=True)
    panel.to_csv(PANEL, index=False)
    return panel


def run_day(snapshot_id: int | None = None) -> int:
    from collectors import kroger as K
    from collectors.common import start_snapshot, end_snapshot
    from collectors.snapshot import Run, read_csv
    from db.init_db import connect, load_items
    if not K.PRODUCTION:
        raise SystemExit("KROGER_BASE_URL must point at the production API (api.kroger.com) for the panel")
    con = connect(DEFAULT_DB)
    load_items(con)
    snap = snapshot_id or start_snapshot(con, f"kroger panel {datetime.now(timezone.utc).date()}")
    items = read_csv(ROOT / "config" / "items.csv")
    panel = read_csv(PANEL)
    r = Run(con, snap, [K.CHAIN])
    if not r.session_ready(K.CHAIN):
        return snap
    sess = K.Session()
    try:
        for i, p in enumerate(panel, 1):
            row = con.execute("SELECT * FROM stores WHERE store_pk = ?", (int(p["store_pk"]),)).fetchone()
            cols = [c[1] for c in con.execute("PRAGMA table_info(stores)")]
            store = dict(zip(cols, row))
            print(f"[{i}/{len(panel)}] Kroger {store['store_id']} {store.get('name')}", flush=True)
            loc = store["store_id"]
            r._query_items(K.CHAIN, store, store["store_pk"], items, lambda it: K.search_item(it, loc, sess))
            if K.CHAIN not in r.active:
                break
    finally:
        end_snapshot(con, snap)
    return snap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["select", "run"])
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--snapshot-id", type=int, default=None)
    a = ap.parse_args(argv)
    if a.step == "select":
        p = select(a.n)
        print(f"wrote {PANEL.relative_to(ROOT)}: {len(p)} stores")
        print(p["banner"].value_counts().to_string())
    else:
        print("panel snapshot:", run_day(a.snapshot_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
