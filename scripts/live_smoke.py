"""Tiny, rate-limited live test of all four wrappers (owner-approved scope:
about 2 stores x 3 items per chain, ~40 requests total).

It runs a normal snapshot (tagged 'smoke test' in snapshots.notes) and prints
a coverage summary. Raw responses land in data/raw/snap<N>/ as usual;
scripts/make_fixtures.py turns a few of them into small test fixtures.

Usage:  python -m scripts.live_smoke [--chains target,trader_joes] [--stores 2] [--items ...]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from collectors.common import ROOT
from collectors.snapshot import ALL_CHAINS, read_csv, run
from db.init_db import DEFAULT_DB, connect

DEFAULT_ITEMS = "cer_cheerios_18,pas_barilla_spaghetti_16,sod_coke_12pk"


def coverage(snapshot_id: int) -> pd.DataFrame:
    con = connect(DEFAULT_DB)
    q = """
    SELECT s.chain, s.store_id, COUNT(DISTINCT o.item_id) AS items_with_rows,
           COUNT(*) AS rows, SUM(o.store_specific) AS store_specific_rows,
           SUM(o.is_promo) AS promo_rows, SUM(o.upc IS NOT NULL) AS rows_with_upc
    FROM observations o JOIN stores s USING (store_pk)
    WHERE o.snapshot_id = ? GROUP BY s.chain, s.store_id ORDER BY s.chain"""
    return pd.read_sql_query(q, con, params=(snapshot_id,))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chains", default=",".join(ALL_CHAINS))
    ap.add_argument("--stores", type=int, default=2)
    ap.add_argument("--items", default=DEFAULT_ITEMS)
    ap.add_argument("--snapshot-id", type=int, default=None)
    a = ap.parse_args(argv)

    stores = read_csv(ROOT / "config" / "store_sample.csv")
    # Two stores from different regions, chosen deterministically.
    picked, seen = [], set()
    for s in stores:
        if s["region"] not in seen and s["urbanicity"] == "urban":
            picked.append(s)
            seen.add(s["region"])
        if len(picked) == a.stores:
            break
    keep = set(a.items.split(","))
    items = [i for i in read_csv(ROOT / "config" / "items.csv") if i["item_id"] in keep]
    snap = run([c for c in a.chains.split(",") if c], picked, items,
               snapshot_id=a.snapshot_id, notes="smoke test (scripts/live_smoke.py)")

    con = connect(DEFAULT_DB)
    print("\nCoverage:")
    print(coverage(snap).to_string(index=False))
    print("\nFailures:")
    print(pd.read_sql_query("SELECT chain, store_pk, item_id, reason FROM collection_failures "
                            "WHERE snapshot_id=?", con, params=(snap,)).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
