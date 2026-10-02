"""Kroger wrapper: the official Kroger Public API (OAuth client credentials).

Environment: the CERTIFICATION host api-ce.kroger.com, the same one the
vendored basketBuddy client (vendor/kroger_async.py) uses; the owner checked
that its prices track live prices (docs/DECISIONS.md). Rows carry
source='kroger_ce' so they can be analysed with and without Kroger.

Why not call vendor/kroger_async.price_all_async: it runs up to 40 requests at
once and keeps only the cheapest product (DECISIONS #6). This wrapper sends one
request at a time through the project pacer and keeps the whole response.
Reused from the vendor client: the endpoint, the token request, and its rule
for skipping non-shoppable locations (fuel centres, labs).

Published limits: Products 10,000 calls/day, Locations 1,600/day.

Raw body saved per search: {"location_id": ..., "term": ..., "response": <API JSON>}
"""
from __future__ import annotations

import json
import re
import os
import time
from typing import Optional

import requests

from collectors.common import PACER, ChainBlocked, TransientError

BASE_URL = os.environ.get("KROGER_BASE_URL", "https://api-ce.kroger.com/v1")
DOMAIN = "api-ce.kroger.com"
CHAIN = "kroger"
SOURCE = "kroger_ce"
LIMIT = 50            # API maximum page size
# Same exclusion list as vendor/kroger_async._JUNK_LOCATION_TOKENS
_JUNK_LOCATION_TOKENS = ("distribution", "fuel", "lab", "picking")


class Session:
    """Holds a bearer token and refreshes it before it expires (~30 min)."""

    def __init__(self):
        self.cid = os.environ.get("KROGER_CLIENT_ID", "").strip()
        self.secret = os.environ.get("KROGER_CLIENT_SECRET", "").strip()
        if not (self.cid and self.secret):
            raise ChainBlocked("session:KROGER_CLIENT_ID / KROGER_CLIENT_SECRET not set")
        self.token: Optional[str] = None
        self.expires = 0.0

    def bearer(self) -> str:
        if not self.token or time.time() > self.expires - 60:
            # Not routed through PACER: bearer() is called from inside paced
            # calls (the lock is not re-entrant), and tokens are needed only
            # about every 30 minutes.
            try:
                r = requests.post(f"{BASE_URL}/connect/oauth2/token", auth=(self.cid, self.secret), timeout=30,
                                  data={"grant_type": "client_credentials", "scope": "product.compact"})
            except requests.RequestException as e:
                raise TransientError(f"transport:token {repr(e)[:120]}")
            if r.status_code in (400, 401, 403):
                raise ChainBlocked(f"session:token http {r.status_code}")
            if r.status_code != 200:
                raise TransientError(f"soft:token http {r.status_code}")
            d = r.json()
            self.token, self.expires = d["access_token"], time.time() + float(d.get("expires_in", 1800))
        return self.token


def _get(path: str, params: dict, sess: Session) -> requests.Response:
    def call():
        try:
            r = requests.get(f"{BASE_URL}{path}", params=params, timeout=30,
                             headers={"Authorization": f"Bearer {sess.bearer()}", "Accept": "application/json"})
        except requests.RequestException as e:
            raise TransientError(f"transport:{repr(e)[:120]}")
        if r.status_code == 401:            # token expired early: refresh once
            sess.token = None
            raise TransientError("soft:http 401 (token refreshed)")
        if r.status_code == 403:
            raise ChainBlocked("explicit:http 403")
        if r.status_code == 429:
            raise ChainBlocked("explicit:http 429 (daily rate limit reached)")
        if r.status_code >= 500:
            raise TransientError(f"soft:http {r.status_code}")
        return r
    return PACER.call(DOMAIN, call)


def _resolves(location_id: str, sess: Session) -> bool:
    """Same liveness probe as vendor/kroger_async._store_has_products: some
    location ids from /locations return 400 on /products."""
    r = _get("/products", {"filter.term": "milk", "filter.locationId": location_id, "filter.limit": 1}, sess)
    return r.status_code == 200 and bool(r.json().get("data"))


def nearest_store(lat: float, lon: float, sess: Session, radius_miles: int = 15,
                  max_probe: int = 3) -> tuple[Optional[dict], str]:
    """(store dict or None, raw /locations JSON text): the nearest shoppable
    Kroger-family store within radius_miles of (lat, lon) whose id resolves on
    /products (at most max_probe candidates are probed)."""
    r = _get("/locations", {"filter.latLong.near": f"{lat},{lon}", "filter.radiusInMiles": radius_miles,
                            "filter.limit": 10}, sess)
    if r.status_code != 200:
        raise TransientError(f"soft:locations http {r.status_code}")
    cands = [s for s in r.json().get("data") or []
             if s.get("locationId") and not any(t in (s.get("name") or "").lower() for t in _JUNK_LOCATION_TOKENS)]
    for s in cands[:max_probe]:
        if _resolves(s["locationId"], sess):
            return s, r.text
    return None, r.text


def search(term: str, location_id: str, sess: Session) -> str:
    """Raw envelope text for one product search priced at one store."""
    r = _get("/products", {"filter.term": term, "filter.locationId": location_id, "filter.limit": LIMIT}, sess)
    if r.status_code not in (200, 400, 404):
        raise TransientError(f"soft:products http {r.status_code}")
    # 400/404 (e.g. a term the API rejects) is an answer, not a failure of the
    # service: keep it as data (parses to no products -> logged as 'empty')
    # so it does not count toward the circuit breaker.
    try:
        payload = r.json()
    except ValueError:
        payload = {"non_json": r.text[:2000]}
    return json.dumps({"location_id": str(location_id), "term": term, "status": r.status_code,
                       "response": payload})


def short_term(name: str, n_words: int = 2) -> str:
    """Fallback query: the first words of the item name. The API's search is
    strict on long queries ("Cheerios 18 oz" -> unrelated products; "Cheerios"
    -> Cheerios). Measured on 58 items at one store (2026-10-02): 2-word terms
    matched slightly more items than 3-word or full terms."""
    words = re.sub(r"\(.*?\)", "", name).replace("&", " ").split()
    return " ".join(words[:n_words])


def search_item(item: dict, location_id: str, sess: Session) -> str:
    """Full search term first; if it returns no products, the short term.
    The returned envelope records which term produced it."""
    body = search(item["search_term"], location_id, sess)
    if json.loads(body)["response"].get("data"):
        return body
    return search(short_term(item["name"]), location_id, sess)
