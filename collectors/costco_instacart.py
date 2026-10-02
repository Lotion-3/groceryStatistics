"""Costco (via Instacart) wrapper around the vendored instacart_pricing module.

There is no working direct Costco collector (the basketBuddy costco/ probes
were all HTTP 403), so Costco prices come only from the Instacart storefront.
These rows are tagged source='instacart' and analysed separately (spec
section 4): Instacart storefront prices can differ from shelf prices.

Reused unchanged: the shared Instacart session (_get_session), the
persisted-query GraphQL helper (_gql) and its block handling.

Store = the Costco shop Instacart assigns to a ZIP code (ShopCollectionScoped,
first shop). We never use the vendored "expanding metro" fallback, which
substitutes a different city's warehouse.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from collectors.common import PACER, ChainBlocked, TransientError  # sets sys.path for vendor

import instacart_pricing as ic  # vendored

DOMAIN = "www.instacart.com"
CHAIN = "costco"
SLUG = "costco"


def session():
    """(requests.Session, zone_id) shared Instacart session."""
    try:
        return ic._get_session(SLUG)
    except Exception as e:
        raise ChainBlocked(f"session:{repr(e)[:160]}")


def _gql(op: str, variables: dict, sess) -> dict:
    data = ic._gql(op, variables, sess, SLUG)
    if not data:
        # The vendored helper returns {} on any failure and clears its session
        # cache on 401/403. Distinguish the two cases for the failure log.
        if not ic._mem_cache:
            raise ChainBlocked(f"explicit:{op} 401/403 (session invalidated)")
        raise TransientError(f"soft:{op} returned no data")
    return data


def find_shop(zip_code: str, lat: float, lon: float, sess) -> tuple[Optional[dict], str]:
    """Return (shop dict or None, raw JSON text) for the Costco serving zip_code."""
    data = PACER.call(DOMAIN, _gql, "ShopCollectionScoped", {
        "retailerSlug": SLUG,
        "postalCode": zip_code,
        "coordinates": {"latitude": lat, "longitude": lon},
        "addressId": None,
        "allowCanonicalFallback": False,
    }, sess)
    shops = (data.get("shopCollection") or {}).get("shops") or []
    return (shops[0] if shops else None), json.dumps(data)


def search(term: str, shop_id: str, zone_id: str, zip_code: str, sess) -> str:
    """Raw JSON text {"search": ..., "items": ...} for one query at one shop.
    Mirrors vendored _search_and_fetch but keeps every item, unfiltered."""
    placements = PACER.call(DOMAIN, _gql, "SearchResultsPlacements", {
        "action": None, "query": term, "pageViewId": str(uuid.uuid4()),
        "elevatedProductId": None, "searchSource": "search", "filters": [],
        "disableReformulation": False, "disableLlm": False, "forceInspiration": False,
        "orderBy": "bestMatch", "clusterId": None, "includeDebugInfo": False,
        "clusteringStrategy": None,
        "contentManagementSearchParams": {"itemGridColumnCount": 6},
        "shopId": shop_id, "postalCode": zip_code, "zoneId": zone_id or None, "first": 20,
    }, sess)
    ids = list(dict.fromkeys(re.findall(r"items_\d+-\d+", json.dumps(placements))))[:20]
    items = {}
    if ids:
        items = PACER.call(DOMAIN, _gql, "Items", {
            "ids": ids, "shopId": shop_id, "zoneId": zone_id or None, "postalCode": zip_code,
        }, sess)
    return json.dumps({"search_ids": ids, "items": items})
