"""Rebuild the database from data/raw/ alone (no network).

Every raw envelope (written by collectors.common.save_raw) carries its chain,
store and item context, so `observations` and `stores` can be regenerated
from scratch with the current parsers. Use this after changing a parser, or
to reproduce the analysis dataset from the raw archive.

Usage:  python -m collectors.reparse [--db data/grocery_rebuilt.sqlite] [--snapshots 1,2]

Smoke-test envelopes from before 2026-10-02 lack the embedded store record;
for those the store is reconstructed from what the envelope does hold (the
Target response's own store address, the Walmart scoping cache, the Costco
shop lookup), as noted in docs/DECISIONS.md.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from collectors import parsers
from collectors.common import RAW_DIR, ROOT, insert_observations, upsert_store
from collectors.snapshot import build_rows, specificity_rule
from db.init_db import connect, load_items
from sampling.geo import osm_coords, zip_from_address, zip_info

SOURCE = {"target": "direct", "walmart": "direct", "costco": "instacart", "trader_joes": "national",
          "kroger": "kroger_ce"}


def _legacy_store(chain: str, env: dict, path: Path) -> dict:
    """Best-effort store record for envelopes written before meta['store'] existed."""
    meta, sid = env["meta"], str(env["meta"]["store_id"])
    store = {"chain": chain, "store_id": sid, "source": SOURCE[chain]}
    if chain == "target":
        loc = parsers.target_store_location(env["body"])
        if loc:
            z = zip_info(loc["postal_code"][:5])
            store.update(name=f"Target {loc['name']}", zip=loc["postal_code"][:5], lat=z["lat"], lon=z["lon"],
                         state=z["state"], region=z["region"], urbanicity=z["urbanicity"], ruca=z["ruca"],
                         coord_quality="zip_centroid",
                         address=f"{loc['address_line1']}, {loc['city']}, {loc['state']} {loc['postal_code']}")
    elif chain == "walmart":
        try:
            st = json.loads((ROOT / "collectors" / "vendor" / ".walmart_store_session.json").read_text())
            s = st["sessions"].get(sid) or {}
            wzip = zip_from_address(s.get("store_address", ""))
            anchor = next((k.split("|")[0] for k, v in st["locations"].items() if v == sid), None)
            z = zip_info(wzip)
            store.update(name=s.get("store_name"), zip=wzip, lat=z["lat"], lon=z["lon"], state=z["state"],
                         region=z["region"], urbanicity=z["urbanicity"], ruca=z["ruca"],
                         anchor_zip=anchor, coord_quality="zip_centroid", address=s.get("store_address"))
            exact = osm_coords("walmart", sid)
            if exact:
                store.update(lat=exact[0], lon=exact[1], coord_quality="osm_ref")
        except Exception:
            pass
    elif chain == "costco":
        # Legacy smoke files were keyed by Instacart shop id; find the shop file
        # whose response names this shop to recover its retailerLocationId.
        for shop_file in path.parents[1].glob("zip*/_shop__*.json.gz"):
            senv = json.load(gzip.open(shop_file, "rt", encoding="utf-8"))
            shops = (json.loads(senv["body"]).get("shopCollection") or {}).get("shops") or []
            if shops and str(shops[0].get("id")) == sid:
                zc = shop_file.parent.name.removeprefix("zip")
                z = zip_info(zc)
                loc_id = str(shops[0].get("retailerLocationId"))
                store.update(store_id=loc_id, name=f"Costco (Instacart location {loc_id}, shop {sid})",
                             zip=zc, lat=z["lat"], lon=z["lon"], state=z["state"], region=z["region"],
                             urbanicity=z["urbanicity"], ruca=z["ruca"], anchor_zip=zc,
                             coord_quality="anchor_zip")
                break
    elif chain == "trader_joes":
        store.update(name="Trader Joe's (national web price)")
    return store


def rebuild(db_path: Path, snapshots: list[int] | None = None) -> dict:
    if db_path.exists():
        db_path.unlink()
    con = connect(db_path)
    load_items(con)
    stats = defaultdict(int)
    for snap_dir in sorted(p for p in RAW_DIR.glob("snap*") if p.name[4:].isdigit()):
        snap = int(snap_dir.name.removeprefix("snap"))
        if snapshots and snap not in snapshots:
            continue
        files = sorted(p for p in snap_dir.rglob("*.json.gz") if "__search__" in p.name)
        envs = [(p, json.load(gzip.open(p, "rt", encoding="utf-8"))) for p in files]
        times = [e["meta"]["saved_at"] for _, e in envs]
        con.execute("INSERT INTO snapshots (snapshot_id, started_at, ended_at, notes) VALUES (?,?,?,?)",
                    (snap, min(times), max(times), "rebuilt from data/raw by collectors.reparse"))
        for p, env in envs:
            chain = env["meta"]["chain"]
            store = env["meta"].get("store") or _legacy_store(chain, env, p)
            store_pk = upsert_store(con, store)
            ctx = {"snapshot_id": snap, "store_pk": store_pk, "item_id": env["meta"]["item_id"],
                   "observed_at": env["meta"]["saved_at"], "source": store["source"],
                   "raw_path": p.relative_to(ROOT).as_posix()}
            rows = build_rows(chain, env["body"], ctx, specificity_rule(chain, store["store_id"]))
            stats[f"{chain}_rows"] += insert_observations(con, rows)
            stats[f"{chain}_files"] += 1
        flog = snap_dir / "_failures.jsonl"
        if flog.exists():
            for line in flog.read_text(encoding="utf-8").splitlines():
                f = json.loads(line)
                pk = con.execute("SELECT store_pk FROM stores WHERE chain=? AND store_id=?",
                                 (f["chain"], f.get("store_id"))).fetchone()
                con.execute("INSERT INTO collection_failures (snapshot_id, chain, store_pk, item_id, "
                            "occurred_at, reason, raw_path) VALUES (?,?,?,?,?,?,?)",
                            (snap, f["chain"], pk[0] if pk else None, f.get("item_id"),
                             f["occurred_at"], f["reason"], f.get("raw_path")))
                stats["failures"] += 1
    con.commit()
    return dict(stats)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data" / "grocery.sqlite"))
    ap.add_argument("--snapshots", default="")
    a = ap.parse_args(argv)
    snaps = [int(s) for s in a.snapshots.split(",") if s] or None
    print(rebuild(Path(a.db), snaps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
