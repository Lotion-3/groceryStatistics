"""Walmart wrapper around the vendored walmart_pricing module.

What is reused from the vendored module (unchanged):
  * session minting / cookie handling (_ensure_http_session, CloakBrowser warm)
  * store scoping (_scope_session_in_browser: nearby-stores GraphQL + setPickup,
    run inside the browser exactly as the production app does)
  * the search URL, headers, TLS impersonation and block markers

What this wrapper adds:
  * keeps the raw __NEXT_DATA__ payload instead of reducing it to the single
    cheapest product (vendored _fetch_items_http returns parsed items only)
  * per-domain pacing, and stops on the first WAF block (no IP rotation)

Store specificity: every search item carries fulfillmentSummary[0].storeId,
the store Walmart actually priced at. Rows are store_specific only when that
equals the store we scoped to (see collectors/snapshot.py).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from collectors.common import PACER, ChainBlocked, TransientError  # also sets sys.path for vendor

import walmart_pricing as wp  # vendored

DOMAIN = "www.walmart.com"
CHAIN = "walmart"
_PRODUCT_URL = "https://www.walmart.com/ip/{id}"


def _headers(session: dict) -> dict:
    # Identical to vendored walmart_pricing._fetch_items_http.
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": wp._WARM_URL,
        "user-agent": session["ua"],
    }


def _get(url: str, session: dict) -> str:
    from curl_cffi import requests as _ccffi
    try:
        resp = _ccffi.get(url, headers=_headers(session), cookies=session["cookies"],
                          impersonate=wp._IMPERSONATE, timeout=30)
    except Exception as e:
        raise TransientError(f"transport:{repr(e)[:120]}")
    if wp._has_explicit_block_marker(resp.text):
        raise ChainBlocked("explicit:px-captcha marker")
    if resp.status_code >= 500:
        raise TransientError(f"soft:http {resp.status_code}")
    if resp.status_code != 200:
        raise ChainBlocked(f"soft:http {resp.status_code}")
    return resp.text


def _next_data(html: str) -> str:
    m = wp._NEXT_DATA_RE.search(html)
    if not m:
        # Same interpretation as the vendored code: no data blob = likely challenge.
        raise ChainBlocked("soft:no __NEXT_DATA__")
    return m.group(1)


def search(term: str, session: dict) -> str:
    """Raw __NEXT_DATA__ JSON text for one search (up to 40 results)."""
    url = wp._SEARCH_URL.format(q=wp.requests_quote(term))
    return _next_data(PACER.call(DOMAIN, _get, url, session))


def product_page(us_item_id: str, session: dict) -> str:
    """Raw HTML of a product page (used once per item to read its UPC)."""
    return PACER.call(DOMAIN, _get, _PRODUCT_URL.format(id=us_item_id), session)


def unscoped_session() -> dict:
    """Any working session (not tied to a chosen store). Used only for item
    resolution, never for store-level observations."""
    try:
        return wp._ensure_http_session()
    except Exception as e:
        raise ChainBlocked(f"session:{repr(e)[:160]}")


def scoped_session(zip_code: str, max_age_s: float = 6 * 3600) -> dict:
    """A session whose searches are priced at the Walmart Walmart itself
    assigns to `zip_code` (its nearest store for that ZIP).

    Re-uses a cached scoped session from the vendored state file when it is
    recent; otherwise runs the vendored in-browser scoping flow (~30-60 s,
    one browser launch). Returns {cookies, ua, store_id, store_name,
    store_address, saved_at_epoch}."""
    with wp._store_lock:
        state = wp._load_store_state()
        key = wp._location_key(zip_code, "")
        sid = state["locations"].get(key)
        sess = state["sessions"].get(sid) if sid else None
        if sess and time.time() - float(sess.get("saved_at_epoch", 0)) < max_age_s:
            return sess
        try:
            sess = wp._scope_session_in_browser(zip_code, "")
        except Exception as e:
            cat = getattr(e, "category", "soft")
            raise ChainBlocked(f"{cat}:store scope near {zip_code}: {repr(e)[:160]}")
        state["locations"][key] = sess["store_id"]
        state["sessions"][sess["store_id"]] = sess
        wp._save_store_state()
        return sess


def items_priced_at(next_data_json: str) -> Optional[str]:
    """Store id the search was priced at (majority fulfillmentSummary storeId)."""
    try:
        return wp._items_store_id(wp._find_items(json.loads(next_data_json)))
    except Exception:
        return None
