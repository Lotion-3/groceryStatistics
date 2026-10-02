"""Download OpenStreetMap store locations for the four chains (public data,
no retailer traffic) via the Overpass API.

Uses:
  * accurate coordinates for Walmart / Costco stores reached by ZIP anchoring
    (match on OSM `ref` = store number where present, else nearest same-brand
    feature to the store's ZIP centroid);
  * "distance to nearest competitor" covariates for Module C;
  * a cross-check of the slug-geocoded Target directory (which proved wrong
    for ~25% of stores; see docs/REPO_NOTES.md).

Brands are selected by Wikidata id, which OSM's name-suggestion index applies
consistently. Output: data/external/osm_<chain>.json (raw Overpass JSON) and
data/processed/osm_stores.csv (chain, osm_id, ref, lat, lon, city, state, postcode).

OSM data (c) OpenStreetMap contributors, ODbL.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
URL = "https://overpass-api.de/api/interpreter"
UA = "groceryStatistics-research/0.1 (academic project)"
BRANDS = {"target": "Q1046951", "walmart": "Q483551", "costco": "Q715583", "trader_joes": "Q688825"}


def fetch(chain: str, qid: str) -> list[dict]:
    path = ROOT / "data" / "external" / f"osm_{chain}.json"
    if not path.exists():
        q = (f'[out:json][timeout:180];nwr["brand:wikidata"="{qid}"]["shop"](17,-180,72,-60);'
             "out center tags;")
        for attempt in range(4):
            r = requests.post(URL, data={"data": q}, headers={"User-Agent": UA}, timeout=240)
            if r.status_code not in (429, 504):
                break
            time.sleep(60 * (attempt + 1))   # public instance asks clients to back off
        r.raise_for_status()
        path.write_bytes(r.content)
        time.sleep(5)  # be polite to the public Overpass instance
    return json.loads(path.read_text(encoding="utf-8"))["elements"]


def main() -> int:
    rows = []
    for chain, qid in BRANDS.items():
        els = fetch(chain, qid)
        for e in els:
            t = e.get("tags", {})
            c = e.get("center", {})
            rows.append({"chain": chain, "osm_id": f"{e['type']}/{e['id']}", "ref": t.get("ref"),
                         "shop": t.get("shop"), "name": t.get("name"), "branch": t.get("branch"),
                         "lat": e.get("lat", c.get("lat")), "lon": e.get("lon", c.get("lon")),
                         "city": t.get("addr:city"), "state": t.get("addr:state"),
                         "postcode": (t.get("addr:postcode") or "")[:5] or None})
        print(f"{chain}: {len(els)} OSM features, {sum(1 for e in els if e.get('tags', {}).get('ref'))} with ref")
    out = ROOT / "data" / "processed" / "osm_stores.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
