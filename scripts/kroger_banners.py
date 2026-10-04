"""Kroger-family banner sample (owner-approved, 2026-10-04; DECISIONS #49).

Snapshot 2 reached Kroger stores only near the sampled Target locations, so
several banners have 1-3 stores and some none. This adds a sample designed
for banners: up to PER_BANNER stores per banner, spread out within each
banner, priced for all items in snapshot 2 (the existing cross-section).

Source: Kroger's official production API only (KROGER_BASE_URL must point at
api.kroger.com), one request at a time at >= 9 s (collectors/common.py), so at
most ~9,600 calls/day -- under the 10,000/day Products limit. Locations calls
(~600) are within their own 1,600/day limit.

Steps (each resumable):
  enumerate  list every Kroger-family store: Locations queries on a ~1 degree
             grid of points that have ZCTAs (radius 50 mi, up to 200 results;
             cells hitting the cap are flagged). -> data/processed/kroger_store_universe.csv
  select     up to PER_BANNER stores per banner (contiguous US), farthest-point
             order within banner; stores already priced in snapshot 2 count
             toward the quota first. -> config/kroger_banner_sample.csv
  run        price every item at the selected stores in snapshot 2 (pairs already
             collected are skipped).

  python -m scripts.kroger_banners enumerate|select|run
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import numpy as np
import pandas as pd

from collectors.common import ROOT, TransientError, save_raw, with_backoff
from db.init_db import DEFAULT_DB

UNIVERSE = ROOT / "data" / "processed" / "kroger_store_universe.csv"
SAMPLE = ROOT / "config" / "kroger_banner_sample.csv"
PER_BANNER = 12
SEED = 20261004
NON_STORE = ("fuel", "distribution", "lab", "picking", "spoke", "pharmacy only", "vitacost")  # vitacost: online-only


def grid_points(step: float = 1.0) -> pd.DataFrame:
    """Centres of ~1 degree cells of the contiguous US that contain ZCTAs. A 50-mile
    radius reaches a 1 degree cell's corners (~44 mi from the centre)."""
    from sampling.geo import _tables
    zt, _ = _tables()
    zt = zt[(zt["zlat"].between(24, 50)) & (zt["zlon"] > -125) & (zt["zlon"] < -66)]   # contiguous US
    cells = (zt.assign(clat=(zt["zlat"] // step) * step + step / 2, clon=(zt["zlon"] // step) * step + step / 2)
             .groupby(["clat", "clon"]).size().reset_index(name="zctas"))
    return cells


def enumerate_stores() -> pd.DataFrame:
    from collectors import kroger as K
    if not K.PRODUCTION:
        raise SystemExit("KROGER_BASE_URL must point at the production API")
    sess = K.Session()
    done = set()
    rows = []
    if UNIVERSE.exists():
        prev = pd.read_csv(UNIVERSE, dtype=str)
        rows = prev.to_dict("records")
        done = set(prev["_cell"])
    cells = grid_points()
    for i, c in enumerate(cells.itertuples(), 1):
        key = f"{c.clat:.2f},{c.clon:.2f}"
        if key in done:
            continue
        try:     # a 5xx on one cell is retried (backoff), then logged and skipped; never fatal
            r = with_backoff(K._get, "/locations",
                             {"filter.latLong.near": key, "filter.radiusInMiles": 50, "filter.limit": 200}, sess)
        except TransientError as e:
            print(f"  cell {key}: {e} after retries; skipped (rerun enumerate to retry)", flush=True)
            continue
        if r.status_code != 200:
            print(f"  cell {key}: http {r.status_code}", flush=True)
            continue
        data = r.json().get("data") or []
        save_raw("kroger_universe", "kroger", f"cell_{key.replace(',', '_')}", "_locations", r.text,
                 {"cell": key}, kind="locations")
        for s in data:
            a, g = s.get("address") or {}, s.get("geolocation") or {}
            rows.append({"_cell": key, "_capped": int(len(data) >= 200), "location_id": s.get("locationId"),
                         "banner": s.get("chain"), "name": s.get("name"), "zip": (a.get("zipCode") or "")[:5],
                         "state": a.get("state"), "city": a.get("city"),
                         "lat": g.get("latitude"), "lon": g.get("longitude")})
        if not data:
            rows.append({"_cell": key, "_capped": 0})
        if i % 5 == 0:
            pd.DataFrame(rows).to_csv(UNIVERSE, index=False)
            print(f"  {i}/{len(cells)} cells", flush=True)
    u = pd.DataFrame(rows)
    u.to_csv(UNIVERSE, index=False)
    return u


def select() -> pd.DataFrame:
    from sampling.visit_order import maximin_order
    u = pd.read_csv(UNIVERSE, dtype={"location_id": str, "zip": str}).dropna(subset=["location_id", "lat"])
    u = u.drop_duplicates("location_id")
    u = u[~u["name"].fillna("").str.lower().str.contains("|".join(NON_STORE))]
    u = u[~u["state"].isin(["AK", "HI"])].copy()
    con = sqlite3.connect(DEFAULT_DB)
    have = set(pd.read_sql_query("""SELECT DISTINCT s.store_id FROM stores s JOIN observations o USING (store_pk)
                                    WHERE s.chain='kroger' AND o.snapshot_id = 2""", con)["store_id"])
    con.close()
    rng = np.random.default_rng(SEED)
    parts = []
    for banner, g in u.groupby("banner"):
        g = g.reset_index(drop=True)
        g["already"] = g["location_id"].isin(have)
        rest = g[~g["already"]].reset_index(drop=True)
        k = max(0, PER_BANNER - int(g["already"].sum()))
        order = maximin_order(rest["lat"].to_numpy(float), rest["lon"].to_numpy(float), rng) if len(rest) else []
        parts.append(pd.concat([g[g["already"]], rest.iloc[list(order)[:k]]]))
    s = pd.concat(parts, ignore_index=True)
    s.to_csv(SAMPLE, index=False)
    return s


def run(snapshot_id: int = 2) -> None:
    from collectors import kroger as K
    from collectors.common import upsert_store
    from collectors.snapshot import Run, read_csv
    from db.init_db import connect, load_items
    from sampling.geo import zip_info
    if not K.PRODUCTION:
        raise SystemExit("KROGER_BASE_URL must point at the production API")
    con = connect(DEFAULT_DB)
    load_items(con)
    items = read_csv(ROOT / "config" / "items.csv")
    sample = pd.read_csv(SAMPLE, dtype={"location_id": str, "zip": str})
    r = Run(con, snapshot_id, [K.CHAIN])
    if not r.session_ready(K.CHAIN):
        return
    sess = K.Session()
    for i, s in enumerate(sample.itertuples(), 1):
        z = zip_info(s.zip)
        store = {"chain": "kroger", "store_id": str(s.location_id), "name": f"{s.banner} {s.name}",
                 "lat": float(s.lat), "lon": float(s.lon), "zip": s.zip, "state": z["state"] or s.state,
                 "region": z["region"], "urbanicity": z["urbanicity"], "ruca": z["ruca"], "source": K.SOURCE,
                 "anchor_zip": None, "coord_quality": "api_geolocation",
                 "address": f"{s.city}, {s.state} {s.zip}"}
        store_pk = upsert_store(con, store)
        print(f"[{i}/{len(sample)}] {s.banner} {s.location_id} {s.city} {s.state}", flush=True)
        loc = str(s.location_id)
        r._query_items(K.CHAIN, store, store_pk, items, lambda it: K.search_item(it, loc, sess))
        if K.CHAIN not in r.active:
            break


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["enumerate", "select", "run"])
    a = ap.parse_args(argv)
    if a.step == "enumerate":
        u = enumerate_stores()
        v = u.dropna(subset=["location_id"]).drop_duplicates("location_id")
        print(f"{len(v)} Kroger-family locations; capped cells: {u.loc[u['_capped'] == 1, '_cell'].nunique()}")
        print(v["banner"].value_counts().to_string())
    elif a.step == "select":
        s = select()
        print(f"{len(s)} stores selected ({int(s['already'].sum())} already in snapshot 2)")
        print(s.groupby("banner").agg(stores=("location_id", "size"), already=("already", "sum")).to_string())
    else:
        run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
