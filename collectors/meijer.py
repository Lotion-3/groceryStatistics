"""Meijer wrapper: the endpoints the vendored meijer_pricing module uses.

Store: Meijer's store locator (www.meijer.com/bin/meijer/store/search), which
the vendored code calls with curl_cffi's Chrome profile. We take the nearest
FULL store (pharmacy/clinic/express locations skipped, as upstream) to the
anchor's coordinates. Two upstream behaviours are deliberately NOT reused:
  * the silent fallback to store 130 when no store is found or the locator
    fails (that would mislabel prices): we log a failure instead;
  * walking a proxy pool when the locator is blocked: we stop the chain.

Prices: Constructor.io search (ac.cnstrc.com, Meijer's public site key) with
filters[availableInStores]=<store>. Verified 2026-10-02: the same products
return different prices at different stores (5 of 9 egg products, 2 of 37
Barilla products between stores 104 and 20), so the price is store-specific.
The response does not echo the store, so rows are tied to the requested store.

Raw body saved per search: {"store_id", "term", "status", "response": <API JSON>}
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import requests

from collectors.common import PACER, ChainBlocked, TransientError  # sets sys.path for vendor
from analysis.estimators import haversine_km

import meijer_pricing as mp  # vendored (constants only)

LOCATOR_DOMAIN = "www.meijer.com"
SEARCH_DOMAIN = "ac.cnstrc.com"
CHAIN = "meijer"
SOURCE = "direct"
NUM_RESULTS = 40
MAX_KM = 50.0


def locate(zip_code: str) -> tuple[list[dict], str]:
    """(store list, raw JSON text) from Meijer's store locator."""
    from curl_cffi import requests as cc

    def call():
        try:
            r = cc.get(mp._STORE_LOCATOR, params={"locationQuery": zip_code, "radius": "50"},
                       headers={**mp.HEADERS, "accept": "application/json",
                                "referer": "https://www.meijer.com/shopping/store-finder.html"},
                       impersonate="chrome", timeout=15)
        except Exception as e:
            raise TransientError(f"transport:{repr(e)[:120]}")
        if r.status_code in (403, 429):
            raise ChainBlocked(f"explicit:locator http {r.status_code}")
        if r.status_code != 200:
            raise TransientError(f"soft:locator http {r.status_code}")
        try:
            body = r.json()
        except ValueError:
            # Upstream notes the WAF answers with an HTML block page and HTTP 200.
            raise ChainBlocked("explicit:locator returned HTML (block page)")
        return body, r.text

    body, text = PACER.call(LOCATOR_DOMAIN, call)
    pts = (body.get("data") or {}).get("pointsOfService") or body.get("pointsOfService") or []
    return pts, text


def nearest_store(zip_code: str, lat: float, lon: float) -> tuple[Optional[dict], str]:
    """Nearest full Meijer store within MAX_KM of (lat, lon), or None."""
    pts, text = locate(zip_code)
    best = None
    for s in pts:
        dn = (s.get("displayName") or "").lower()
        if any(x in dn for x in ("pharmacy", "clinic", "express")):
            continue
        gp = s.get("geoPoint") or {}
        if not s.get("name") or gp.get("latitude") is None:
            continue
        d = float(haversine_km(lat, lon, gp["latitude"], gp["longitude"]))
        if d <= MAX_KM and (best is None or d < best[0]):
            best = (d, s)
    return (best[1] if best else None), text


def search(term: str, store_id: str) -> str:
    def call():
        try:
            r = requests.get(f"{mp.CNSTRC_BASE}/{requests.utils.quote(term)}", timeout=15, headers=mp.HEADERS,
                             params={"key": mp.CNSTRC_KEY, "c": "ciojs-client-2.68.1", "i": str(uuid.uuid4()),
                                     "s": "1", "filters[availableInStores]": str(store_id),
                                     "num_results_per_page": str(NUM_RESULTS)})
        except requests.RequestException as e:
            raise TransientError(f"transport:{repr(e)[:120]}")
        if r.status_code in (403, 429):
            raise ChainBlocked(f"explicit:search http {r.status_code}")
        if r.status_code != 200:
            raise TransientError(f"soft:search http {r.status_code}")
        return json.dumps({"store_id": str(store_id), "term": term, "status": r.status_code, "response": r.json()})
    return PACER.call(SEARCH_DOMAIN, call)
