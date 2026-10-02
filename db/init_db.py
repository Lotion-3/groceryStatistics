"""Create (or open) the local SQLite database and apply db/schema.sql.

Usage:  python db/init_db.py [--db data/grocery.sqlite] [--load-items]

--load-items upserts config/items.csv into the `items` table.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "grocery.sqlite"
SCHEMA = ROOT / "db" / "schema.sql"
ITEMS_CSV = ROOT / "config" / "items.csv"


def connect(db_path: Path | str = DEFAULT_DB) -> sqlite3.Connection:
    """Open the database, creating it and its tables if needed."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # timeout + WAL: the per-chain snapshot processes write to one file at once
    # (scripts/run_snapshot_parallel.*); readers never block writers.
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 30000")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def load_items(con: sqlite3.Connection, csv_path: Path = ITEMS_CSV) -> int:
    """Upsert the item list. Blank cells become NULL (UPCs stay NULL until resolved)."""
    cols = ["item_id", "name", "upc", "category", "cross_chain", "size_value", "size_unit",
            "search_term", "walmart_id", "target_tcin", "costco_ic_id", "tj_sku"]
    n = 0
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = [(row.get(c) or "").strip() or None for c in cols]
            vals[4] = 1 if str(vals[4]).lower() in ("1", "true", "yes") else 0
            vals[5] = float(vals[5]) if vals[5] else None
            con.execute(
                f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                f"ON CONFLICT(item_id) DO UPDATE SET "
                + ",".join(f"{c}=excluded.{c}" for c in cols[1:]),
                vals,
            )
            n += 1
    con.commit()
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--load-items", action="store_true")
    args = ap.parse_args(argv)
    con = connect(args.db)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"DB ready at {args.db}: tables = {', '.join(tables)}")
    if args.load_items:
        print(f"Loaded {load_items(con)} items from {ITEMS_CSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
