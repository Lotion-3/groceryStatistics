"""Meijer footprint sample (owner-approved 2026-10-04; DECISIONS #52).

Snapshot 2 reached Meijer at only 3 stores: Meijer operates in six Midwest
states, so most of the 250 Target-based anchors had no Meijer within 50 km, and
those wasted locator lookups ended in a block page after 51 calls. This sample
is designed for Meijer's footprint instead:

  enumerate  Meijer's own store locator at ~30 metro ZIPs covering MI, OH, IN, IL,
             WI and KY (50-mile radius; one call returns up to ~25 stores), paced at
             >= 12 s (GS_DOMAIN_INTERVALS) and stopping at the first block page.
             -> data/processed/meijer_store_universe.csv
  select     up to N_STORES full stores (pharmacy/clinic/express skipped), farthest-
             point order so any prefix is spread out; the 3 snapshot-2 stores count
             first. -> config/meijer_sample.csv
  run        price all items at the selected stores in snapshot 2 via Meijer's
             Constructor.io search (store-filtered), resumable; ~58 searches/store.

  event      one event pass (owner-approved 2026-10-05; DECISIONS #53): the first
             N_EVENT stores of the sample (farthest-point order, so spread out) x all
             items, as a NEW snapshot "meijer event <pass> <time>". Passes: control
             (Mon night), before (Tue 18:00), after (Wed 12:00), around Meijer's
             sale ends of Oct 6 (the same night as the Kroger expiry).

  python -m scripts.meijer_sample enumerate|select|run
  python -m scripts.meijer_sample event --note meijer event before
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import numpy as np
import pandas as pd

os.environ.setdefault("GS_DOMAIN_INTERVALS", "www.meijer.com=12")
from collectors.common import ROOT, ChainBlocked, TransientError, save_raw, with_backoff  # noqa: E402
from db.init_db import DEFAULT_DB  # noqa: E402

UNIVERSE = ROOT / "data" / "processed" / "meijer_store_universe.csv"
SAMPLE = ROOT / "config" / "meijer_sample.csv"
N_STORES = 80
N_EVENT = 15
SEED = 20261004
# Metro ZIPs spanning Meijer's footprint (50-mile radius each).
ZIPS = ["48201", "48104", "48933", "49503", "49007", "48502", "48601", "49684", "49770", "48858",
        "49085", "43604", "43215", "45402", "45202", "44113", "44308", "46204", "46802", "46601",
        "47901", "47708", "47807", "60602", "61101", "61602", "61820", "62701", "53202", "53703",
        "54301", "40202", "40507", "42101"]
SKIP = ("pharmacy", "clinic", "express")


def enumerate_stores() -> pd.DataFrame:
    from collectors import meijer as M
    rows, done = [], set()
    if UNIVERSE.exists():
        prev = pd.read_csv(UNIVERSE, dtype=str)
        rows, done = prev.to_dict("records"), set(prev["_zip"])
    for i, z in enumerate(ZIPS, 1):
        if z in done:
            continue
        try:
            pts, raw = with_backoff(M.locate, z)
        except ChainBlocked as e:
            print(f"  zip {z}: BLOCKED ({e}); stopping enumeration (rerun later to resume)", flush=True)
            break
        except TransientError as e:
            print(f"  zip {z}: {e}; skipped", flush=True)
            continue
        save_raw("meijer_universe", "meijer", f"zip{z}", "_locator", raw, {"zip": z}, kind="locator")
        for s in pts:
            a, g = s.get("address") or {}, s.get("geoPoint") or {}
            rows.append({"_zip": z, "store_id": str(s.get("name")), "display_name": s.get("displayName"),
                         "line1": a.get("line1"), "town": a.get("town"), "zip": str(a.get("postalCode") or "")[:5],
                         "lat": g.get("latitude"), "lon": g.get("longitude")})
        if not pts:
            rows.append({"_zip": z})
        pd.DataFrame(rows).to_csv(UNIVERSE, index=False)
        print(f"  [{i}/{len(ZIPS)}] zip {z}: {len(pts)} locations", flush=True)
    return pd.DataFrame(rows)


def select(n: int = N_STORES) -> pd.DataFrame:
    from sampling.visit_order import maximin_order
    u = pd.read_csv(UNIVERSE, dtype={"store_id": str, "zip": str}).dropna(subset=["store_id", "lat"])
    u = u.drop_duplicates("store_id")
    u = u[~u["display_name"].fillna("").str.lower().str.contains("|".join(SKIP))].reset_index(drop=True)
    con = sqlite3.connect(DEFAULT_DB)
    have = set(pd.read_sql_query("""SELECT DISTINCT s.store_id FROM stores s JOIN observations o USING (store_pk)
                                    WHERE s.chain = 'meijer' AND o.snapshot_id = 2""", con)["store_id"])
    con.close()
    u["already"] = u["store_id"].isin(have)
    rest = u[~u["already"]].reset_index(drop=True)
    order = maximin_order(rest["lat"].to_numpy(float), rest["lon"].to_numpy(float), np.random.default_rng(SEED))
    s = pd.concat([u[u["already"]], rest.iloc[list(order)[: max(0, n - int(u["already"].sum()))]]], ignore_index=True)
    s.to_csv(SAMPLE, index=False)
    return s


def run(snapshot_id: int = 2, n_stores: int | None = None) -> None:
    from collectors import meijer as M
    from collectors.common import upsert_store
    from collectors.snapshot import Run, read_csv
    from db.init_db import connect, load_items
    from sampling.geo import zip_info
    con = connect(DEFAULT_DB)
    load_items(con)
    items = read_csv(ROOT / "config" / "items.csv")
    sample = pd.read_csv(SAMPLE, dtype={"store_id": str, "zip": str})
    if n_stores:
        sample = sample.head(n_stores)
    r = Run(con, snapshot_id, [M.CHAIN])
    if not r.session_ready(M.CHAIN):
        return
    for i, s in enumerate(sample.itertuples(), 1):
        z = zip_info(s.zip)
        store = {"chain": "meijer", "store_id": s.store_id, "name": f"Meijer {s.display_name}",
                 "lat": float(s.lat), "lon": float(s.lon), "zip": s.zip, "state": z["state"],
                 "region": z["region"], "urbanicity": z["urbanicity"], "ruca": z["ruca"], "source": M.SOURCE,
                 "anchor_zip": None, "coord_quality": "locator_geopoint",
                 "address": f"{s.line1}, {s.town} {s.zip}"}
        store_pk = upsert_store(con, store)
        print(f"[{i}/{len(sample)}] Meijer {s.store_id} {s.display_name} {z['state']}", flush=True)
        sid = s.store_id
        r._query_items(M.CHAIN, store, store_pk, items, lambda it: M.search(it["search_term"], sid))
        if M.CHAIN not in r.active:
            break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["enumerate", "select", "run", "event"])
    ap.add_argument("--n", type=int, default=N_STORES)
    ap.add_argument("--note", nargs="+", default=["meijer", "event"])
    a = ap.parse_args(argv)
    if a.step == "enumerate":
        u = enumerate_stores()
        v = u.dropna(subset=["store_id"]).drop_duplicates("store_id") if "store_id" in u else u
        print(f"{len(v)} Meijer locations listed")
    elif a.step == "select":
        s = select(a.n)
        print(f"{len(s)} stores selected ({int(s['already'].sum())} already in snapshot 2)")
    elif a.step == "event":
        from datetime import datetime, timezone
        from collectors.common import end_snapshot, start_snapshot
        from db.init_db import connect
        con = connect(DEFAULT_DB)
        snap = start_snapshot(con, f"{' '.join(a.note)} {datetime.now(timezone.utc).isoformat(timespec='minutes')}")
        print("event snapshot:", snap, flush=True)
        try:
            run(snapshot_id=snap, n_stores=N_EVENT)
        finally:
            end_snapshot(con, snap)
    else:
        run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
