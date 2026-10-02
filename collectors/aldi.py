"""ALDI wrapper around the vendored aldi/aldi_pricing module.

ALDI's US site (www.aldi.us) is an Instacart white-label storefront: the same
persisted GraphQL operations as the Costco path (DefaultShop,
SearchResultsPlacements, Items), but on ALDI's own domain, so it has its own
pacing budget. The vendored code notes that its prices are ALDI's in-store
prices (no delivery markup); rows are still tagged source='aldi_ic' so they
can be analysed separately.

Reused unchanged: session handling (_get_session: disk cache, then a normal
CloakBrowser visit to obtain the anonymous session cookie) and the GraphQL
helper (_gql) with its 401/403 handling.

Store = the shop DefaultShop assigns to the anchor ZIP/coordinates. Item ids
look like items_<locationId>-<productId>, so the existing Instacart parser
and the per-row store-specificity check (location prefix == shop's location)
apply unchanged.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Optional

from collectors.common import PACER, VENDOR, ChainBlocked, TransientError

import sys
if str(VENDOR / "aldi") not in sys.path:
    sys.path.insert(0, str(VENDOR / "aldi"))
import aldi_pricing as ap  # vendored

DOMAIN = "www.aldi.us"
CHAIN = "aldi"
SOURCE = "aldi_ic"


def session():
    """(requests.Session, zone_id)."""
    try:
        s, zone, _shop = ap._get_session()
        return s, zone
    except Exception as e:
        raise ChainBlocked(f"session:{repr(e)[:160]}")


def _gql(op: str, variables: dict, sess) -> dict:
    data = ap._gql(op, variables, sess)
    if not data:
        # The vendored helper returns {} on any failure and clears its session
        # cache on 401/403; distinguish the two for the failure log.
        if not ap._mem_cache:
            raise ChainBlocked(f"explicit:{op} 401/403 (session invalidated)")
        raise TransientError(f"soft:{op} returned no data")
    return data


def find_shop(zip_code: str, lat: float, lon: float, sess) -> tuple[Optional[dict], str]:
    """(shop dict or None, raw JSON text) for the ALDI DefaultShop serving the ZIP."""
    data = PACER.call(DOMAIN, _gql, "DefaultShop", {
        "postalCode": zip_code, "coordinates": {"latitude": lat, "longitude": lon}, "addressId": None,
    }, sess)
    return (data.get("defaultShop") or None), json.dumps(data)


def search(term: str, shop_id: str, zone_id: str, zip_code: str, sess) -> str:
    """Raw JSON text {"search_ids": ..., "items": ...}: every item, unfiltered."""
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
