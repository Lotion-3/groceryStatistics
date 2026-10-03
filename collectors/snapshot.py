"""Run one price snapshot: (sampled stores) x (items) for each chain.

For every store-item query the wrapper stores the raw response, parses EVERY
returned product into `observations`, and logs anything that goes wrong to
`collection_failures`. A chain is abandoned for the rest of the run on its
first WAF block (no escalation).

Store construction per sampled Target store (see docs/SAMPLING.md):
  target      the sampled store itself (store_id URL parameter). Its true
              address is read from the response and overwrites the
              (unreliable) slug-geocoded location.
  walmart     the store Walmart assigns to the sampled store's ZIP (browser
              scoping via the vendored code)
  costco      the Costco location Instacart assigns to that ZIP
              (source='instacart')
trader_joes is collected once per snapshot against a 'national' pseudo-store.

Store specificity (observations.store_specific):
  target   price.location_id == requested store id
  walmart  a fulfillmentSummary storeId == the scoped store id
  costco   item id's Instacart location == the shop's retailerLocationId
  tj       always 0 (one national web price)

Resumable: re-running with --snapshot-id N skips store-item pairs that
already have observations in snapshot N.

Usage:
  python -m collectors.snapshot --chains target,walmart,costco \
      [--limit-stores 2] [--limit-items 3] [--items a,b] [--snapshot-id N] [--notes ...]
  python -m collectors.snapshot --new-snapshot-only --notes "..."   # prints the new id

Parallel (one process per chain, one shared snapshot id): scripts/run_snapshot_parallel.ps1

THIS GENERATES RETAILER TRAFFIC. Full runs need the owner's go-ahead.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Callable, Optional

from collectors import parsers
from collectors.common import (ROOT, ChainBlocked, TransientError, end_snapshot, insert_observations,
                               log_failure, save_raw, start_snapshot, upsert_store, utcnow, with_backoff)
from db.init_db import DEFAULT_DB, connect, load_items
from sampling.geo import osm_coords, zip_from_address, zip_info

ALL_CHAINS = ("target", "walmart", "costco", "trader_joes", "kroger", "kroger_ce", "aldi", "meijer")
# Trader Joe's is dropped from the study (HTTP 403; national price only): DECISIONS #24.
DEFAULT_CHAINS = ("target", "walmart", "costco")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_rows(chain: str, body: str, ctx: dict, store_specific_fn: Callable[[dict], bool]) -> list[dict]:
    """Parse a raw body into full observation rows. Shared with reparse.py so a
    rebuild from data/raw/ produces exactly what the live run produced."""
    return [{**p, "snapshot_id": ctx["snapshot_id"], "store_pk": ctx["store_pk"],
             "item_id": ctx["item_id"], "observed_at": ctx["observed_at"], "currency": "USD",
             "raw_path": ctx["raw_path"], "source": ctx["source"],
             "store_specific": int(bool(store_specific_fn(p)))}
            for p in parsers.parse(chain, body)]


def specificity_rule(chain: str, store_id: str) -> Callable[[dict], bool]:
    store_id = str(store_id)
    if chain == "trader_joes":
        return lambda p: False
    return lambda p: p.get("priced_store_id") == store_id


class Run:
    def __init__(self, con, snapshot_id: int, chains: list[str]):
        self.con, self.snap = con, snapshot_id
        self.active = set(chains)
        self.sessions: dict = {}
        self.costco_done: set[str] = set()
        self.kroger_done: set[str] = set()
        self.aldi_done: set[str] = set()
        self.meijer_done: set[str] = set()

    # -- bookkeeping -------------------------------------------------------
    def done(self, store_pk: int, item_id: str) -> bool:
        return self.con.execute(
            "SELECT 1 FROM observations WHERE snapshot_id=? AND store_pk=? AND item_id=? LIMIT 1",
            (self.snap, store_pk, item_id)).fetchone() is not None

    def fail(self, chain, store_pk, item_id, reason, raw_path=None):
        log_failure(self.con, self.snap, chain, store_pk, item_id, reason, raw_path)

    def block(self, chain: str, store_pk, item_id, err: Exception):
        self.fail(chain, store_pk, item_id, f"BLOCKED (chain stopped for this run) {err}")
        self.active.discard(chain)

    def record(self, chain: str, store: dict, store_pk: int, item: dict, body: str, meta: dict) -> int:
        """Save the raw body (with full store/request context), parse, insert."""
        raw = save_raw(self.snap, chain, store["store_id"], item["item_id"], body,
                       {**meta, "store": store, "term": item["search_term"]})
        ctx = {"snapshot_id": self.snap, "store_pk": store_pk, "item_id": item["item_id"],
               "observed_at": utcnow(), "raw_path": raw, "source": store["source"]}
        try:
            rows = build_rows(chain, body, ctx, specificity_rule(chain, store["store_id"]))
        except Exception as e:
            self.fail(chain, store_pk, item["item_id"], f"parse:{repr(e)[:200]}", raw)
            return 0
        if not rows:
            self.fail(chain, store_pk, item["item_id"], "empty:no products in response", raw)
            return 0
        n = insert_observations(self.con, rows)
        spec = sum(r["store_specific"] for r in rows)
        print(f"  {chain} #{store['store_id']} {item['item_id']}: {n} rows ({spec} store-specific)", flush=True)
        return n

    def _query_items(self, chain: str, store: dict, store_pk: int, items: list[dict],
                     fetch: Callable[[dict], str], meta: Optional[dict] = None,
                     on_first_body: Optional[Callable[[str], None]] = None):
        for it in items:
            if chain not in self.active or self.done(store_pk, it["item_id"]):
                continue
            try:
                body = with_backoff(fetch, it)
            except ChainBlocked as e:
                return self.block(chain, store_pk, it["item_id"], e)
            except TransientError as e:
                self.fail(chain, store_pk, it["item_id"], str(e))
                continue
            if on_first_body:
                on_first_body(body)
                on_first_body = None
            self.record(chain, store, store_pk, it, body, meta or {})

    # -- chains --------------------------------------------------------------
    def target(self, srow: dict, items: list[dict]):
        from collectors import target as T
        store = {"chain": "target", "store_id": srow["store_id"], "name": f"Target {srow.get('slug', '')}",
                 "lat": float(srow["lat"]), "lon": float(srow["lon"]), "zip": srow["zip"],
                 "state": srow["state"], "region": srow["region"], "urbanicity": srow["urbanicity"],
                 "ruca": int(float(srow["ruca"])) if srow.get("ruca") else None,
                 "source": "direct", "coord_quality": "slug_geocode"}
        store_pk = upsert_store(self.con, store)
        if "tsess" not in self.sessions:
            self.sessions["tsess"] = T.session()

        def relocate(body: str):
            # Replace the slug-geocoded location with the address Target reports.
            loc = parsers.target_store_location(body)
            if loc and loc["store_id"] == str(srow["store_id"]):
                zc = loc["postal_code"][:5]
                z = zip_info(zc)
                store.update({"name": f"Target {loc['name']}", "zip": zc, "lat": z["lat"], "lon": z["lon"],
                              "state": z["state"], "region": z["region"], "urbanicity": z["urbanicity"],
                              "ruca": z["ruca"], "coord_quality": "zip_centroid",
                              "address": f"{loc['address_line1']}, {loc['city']}, {loc['state']} {loc['postal_code']}"})
                upsert_store(self.con, store)

        self._query_items("target", store, store_pk, items,
                          lambda it: T.search(it["search_term"], srow["store_id"], self.sessions["tsess"]),
                          on_first_body=relocate)

    def walmart(self, srow: dict, items: list[dict]):
        from collectors import walmart as W
        try:
            sess = W.scoped_session(srow["zip"])
        except ChainBlocked as e:
            # A failed scope is usually per-store ("no store near ZIP"); only
            # explicit WAF blocks stop the chain.
            self.fail("walmart", None, None, f"scope zip={srow['zip']}: {e}")
            if str(e).startswith("explicit"):
                self.active.discard("walmart")
            return
        wzip = zip_from_address(sess.get("store_address", "")) or srow["zip"]
        z = zip_info(wzip)
        store = {"chain": "walmart", "store_id": str(sess["store_id"]), "name": sess.get("store_name"),
                 "lat": z["lat"], "lon": z["lon"], "zip": wzip, "state": z["state"], "region": z["region"],
                 "urbanicity": z["urbanicity"], "ruca": z["ruca"], "source": "direct",
                 "anchor_zip": srow["zip"], "coord_quality": "zip_centroid",
                 "address": sess.get("store_address")}
        exact = osm_coords("walmart", store["store_id"])
        if exact:
            store.update(lat=exact[0], lon=exact[1], coord_quality="osm_ref")
        store_pk = upsert_store(self.con, store)
        self._query_items("walmart", store, store_pk, items,
                          lambda it: W.search(it["search_term"], sess))

    def costco(self, srow: dict, items: list[dict]):
        from collectors import costco_instacart as C
        if "csess" not in self.sessions:
            self.sessions["csess"] = C.session()
        sess, zone = self.sessions["csess"]
        z = zip_info(srow["zip"])
        try:
            shop, shop_raw = with_backoff(C.find_shop, srow["zip"], z["lat"] or float(srow["lat"]),
                                          z["lon"] or float(srow["lon"]), sess)
        except ChainBlocked as e:
            return self.block("costco", None, None, e)
        except TransientError as e:
            return self.fail("costco", None, None, f"shop lookup zip={srow['zip']}: {e}")
        save_raw(self.snap, "costco", f"zip{srow['zip']}", "_shop", shop_raw,
                 {"zip": srow["zip"]}, kind="shop")
        if not shop or not shop.get("retailerLocationId"):
            return self.fail("costco", None, None, f"no Instacart Costco shop for zip={srow['zip']}")
        loc_id, shop_id = str(shop["retailerLocationId"]), str(shop["id"])
        if loc_id in self.costco_done:
            return  # same warehouse already reached from another sampled ZIP
        self.costco_done.add(loc_id)
        # Instacart does not return the warehouse's address; the anchor ZIP's
        # centroid stands in for its location (coord_quality='anchor_zip').
        store = {"chain": "costco", "store_id": loc_id,
                 "name": f"Costco (Instacart location {loc_id}, shop {shop_id})",
                 "lat": z["lat"], "lon": z["lon"], "zip": srow["zip"], "state": z["state"],
                 "region": z["region"], "urbanicity": z["urbanicity"], "ruca": z["ruca"],
                 "source": "instacart", "anchor_zip": srow["zip"], "coord_quality": "anchor_zip"}
        store_pk = upsert_store(self.con, store)
        self._query_items("costco", store, store_pk, items,
                          lambda it: C.search(it["search_term"], shop_id, zone, srow["zip"], sess),
                          meta={"shop_id": shop_id, "zone_id": zone, "zip": srow["zip"]})

    def kroger(self, srow: dict, items: list[dict]):
        """Nearest Kroger-family store (official API) to the anchor; optional
        chain, not in DEFAULT_CHAINS (see DECISIONS: certification catalog
        covers ~10 of 58 items)."""
        from collectors import kroger as K
        chain = K.CHAIN          # "kroger" (production) or "kroger_ce" (test host), set by KROGER_BASE_URL
        if chain not in self.active:
            return self.fail(chain, None, None, f"KROGER_BASE_URL selects {chain}; run with --chains {chain}")
        if "ksess" not in self.sessions:
            self.sessions["ksess"] = K.Session()
        sess = self.sessions["ksess"]
        try:
            st, raw = with_backoff(K.nearest_store, float(srow["lat"]), float(srow["lon"]), sess)
        except ChainBlocked as e:
            return self.block(chain, None, None, e)
        except TransientError as e:
            return self.fail(chain, None, None, f"store lookup zip={srow['zip']}: {e}")
        save_raw(self.snap, chain, f"zip{srow['zip']}", "_locations", raw, {"zip": srow["zip"]}, kind="locations")
        if not st:
            return self.fail(chain, None, None, f"no Kroger-family store within 15 mi of zip={srow['zip']}")
        loc = str(st["locationId"])
        if loc in self.kroger_done:
            return
        self.kroger_done.add(loc)
        a, g = st.get("address") or {}, st.get("geolocation") or {}
        zc = (a.get("zipCode") or srow["zip"])[:5]
        z = zip_info(zc)
        store = {"chain": chain, "store_id": loc, "name": f"{st.get('chain')} {st.get('name')}",
                 "lat": g.get("latitude") or z["lat"], "lon": g.get("longitude") or z["lon"], "zip": zc,
                 "state": z["state"] or a.get("state"), "region": z["region"], "urbanicity": z["urbanicity"],
                 "ruca": z["ruca"], "source": K.SOURCE, "anchor_zip": srow["zip"],
                 "coord_quality": "api_geolocation" if g.get("latitude") else "zip_centroid",
                 "address": f"{a.get('addressLine1')}, {a.get('city')}, {a.get('state')} {a.get('zipCode')}"}
        store_pk = upsert_store(self.con, store)
        self._query_items(chain, store, store_pk, items, lambda it: K.search_item(it, loc, sess))

    kroger_ce = kroger      # same collector; the label follows KROGER_BASE_URL

    def aldi(self, srow: dict, items: list[dict]):
        """ALDI shop assigned to the anchor ZIP (Instacart white-label, own
        domain). Location = anchor ZIP centroid, as for Costco."""
        from collectors import aldi as AL
        if "asess" not in self.sessions:
            self.sessions["asess"] = AL.session()
        sess, zone = self.sessions["asess"]
        z = zip_info(srow["zip"])
        lat, lon = z["lat"] or float(srow["lat"]), z["lon"] or float(srow["lon"])
        try:
            shop, raw = with_backoff(AL.find_shop, srow["zip"], lat, lon, sess)
        except ChainBlocked as e:
            return self.block("aldi", None, None, e)
        except TransientError as e:
            return self.fail("aldi", None, None, f"shop lookup zip={srow['zip']}: {e}")
        save_raw(self.snap, "aldi", f"zip{srow['zip']}", "_shop", raw, {"zip": srow["zip"]}, kind="shop")
        if not shop or not shop.get("retailerLocationId"):
            return self.fail("aldi", None, None, f"no ALDI shop for zip={srow['zip']}")
        loc_id, shop_id = str(shop["retailerLocationId"]), str(shop["id"])
        if loc_id in self.aldi_done:
            return
        self.aldi_done.add(loc_id)
        store = {"chain": "aldi", "store_id": loc_id, "name": f"ALDI (location {loc_id}, shop {shop_id})",
                 "lat": lat, "lon": lon, "zip": srow["zip"], "state": z["state"], "region": z["region"],
                 "urbanicity": z["urbanicity"], "ruca": z["ruca"], "source": AL.SOURCE,
                 "anchor_zip": srow["zip"], "coord_quality": "anchor_zip"}
        store_pk = upsert_store(self.con, store)
        self._query_items("aldi", store, store_pk, items,
                          lambda it: AL.search(it["search_term"], shop_id, zone, srow["zip"], sess),
                          meta={"shop_id": shop_id, "zip": srow["zip"]})

    def meijer(self, srow: dict, items: list[dict]):
        """Nearest full Meijer within 50 km of the anchor (Midwest only), from
        Meijer's own locator; never the upstream default store 130."""
        from collectors import meijer as M
        z = zip_info(srow["zip"])
        lat, lon = z["lat"] or float(srow["lat"]), z["lon"] or float(srow["lon"])
        try:
            st, raw = with_backoff(M.nearest_store, srow["zip"], lat, lon)
        except ChainBlocked as e:
            return self.block("meijer", None, None, e)
        except TransientError as e:
            return self.fail("meijer", None, None, f"locator zip={srow['zip']}: {e}")
        save_raw(self.snap, "meijer", f"zip{srow['zip']}", "_locator", raw, {"zip": srow["zip"]}, kind="locator")
        if not st:
            return self.fail("meijer", None, None, f"no Meijer within {M.MAX_KM:.0f} km of zip={srow['zip']}")
        sid = str(st["name"])
        if sid in self.meijer_done:
            return
        self.meijer_done.add(sid)
        gp, a = st.get("geoPoint") or {}, st.get("address") or {}
        zc = str(a.get("postalCode") or srow["zip"])[:5]
        zz = zip_info(zc)
        store = {"chain": "meijer", "store_id": sid, "name": f"Meijer {st.get('displayName')}",
                 "lat": gp.get("latitude"), "lon": gp.get("longitude"), "zip": zc, "state": zz["state"],
                 "region": zz["region"], "urbanicity": zz["urbanicity"], "ruca": zz["ruca"], "source": M.SOURCE,
                 "anchor_zip": srow["zip"], "coord_quality": "locator_geopoint",
                 "address": f"{a.get('line1')}, {a.get('town')} {a.get('postalCode')}"}
        store_pk = upsert_store(self.con, store)
        self._query_items("meijer", store, store_pk, items, lambda it: M.search(it["search_term"], sid))

    def trader_joes(self, items: list[dict]):
        from collectors import trader_joes as TJ
        store = {"chain": "trader_joes", "store_id": "national",
                 "name": "Trader Joe's (national web price)", "source": "national"}
        store_pk = upsert_store(self.con, store)
        self._query_items("trader_joes", store, store_pk, items,
                          lambda it: TJ.search(it["search_term"]))


def run(chains: list[str], stores: list[dict], items: list[dict], db_path=DEFAULT_DB,
        snapshot_id: Optional[int] = None, notes: str = "") -> int:
    con = connect(db_path)
    load_items(con)
    snap = snapshot_id or start_snapshot(con, notes)
    print(f"Snapshot {snap}: {len(stores)} anchor stores x {len(items)} items, chains={chains}", flush=True)
    r = Run(con, snap, chains)
    try:
        if "trader_joes" in chains:
            r.trader_joes(items)
        for i, s in enumerate(stores, 1):
            print(f"[{i}/{len(stores)}] anchor Target #{s['store_id']} zip={s['zip']} {s['state']}", flush=True)
            for ch in ("target", "walmart", "costco", "kroger", "kroger_ce", "aldi", "meijer"):
                if ch in r.active:
                    try:
                        getattr(r, ch)(s, items)
                    except ChainBlocked as e:   # session-level block
                        r.block(ch, None, None, e)
    finally:
        end_snapshot(con, snap)
    return snap


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chains", default=",".join(DEFAULT_CHAINS))
    ap.add_argument("--stores", default=str(ROOT / "config" / "store_sample.csv"))
    ap.add_argument("--items-csv", default=str(ROOT / "config" / "items.csv"))
    ap.add_argument("--items", default="", help="comma-separated item_ids to restrict to")
    ap.add_argument("--limit-stores", type=int, default=0)
    ap.add_argument("--limit-items", type=int, default=0)
    ap.add_argument("--snapshot-id", type=int, default=None, help="resume this snapshot")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--notes", default="")
    ap.add_argument("--new-snapshot-only", action="store_true",
                    help="create a snapshot row, print its id and exit (for parallel per-chain runs)")
    a = ap.parse_args(argv)
    if a.new_snapshot_only:
        con = connect(a.db)
        load_items(con)
        print(start_snapshot(con, a.notes))
        return 0
    chains = [c.strip() for c in a.chains.split(",") if c.strip()]
    bad = set(chains) - set(ALL_CHAINS)
    if bad:
        ap.error(f"unknown chains {bad}")
    stores = read_csv(Path(a.stores))
    items = read_csv(Path(a.items_csv))
    if a.items:
        keep = set(a.items.split(","))
        items = [i for i in items if i["item_id"] in keep]
    if a.limit_stores:
        stores = stores[: a.limit_stores]
    if a.limit_items:
        items = items[: a.limit_items]
    snap = run(chains, stores, items, a.db, a.snapshot_id, a.notes)
    print(f"Done. snapshot_id={snap}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
