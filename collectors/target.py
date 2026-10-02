"""Target wrapper around the vendored target_pricing module.

Reused unchanged: session sourcing/minting (_ensure_http_session), the
cdui_orchestrations `slp` URL builder (_slp_url) and the HTTP replay with its
block detection (_redsky_get_http).

Target scopes price by the `store_id` URL parameter alone, so any store in the
1,893-store directory can be queried directly without a browser per store.
"""
from __future__ import annotations

from collectors.common import PACER, ChainBlocked, TransientError  # sets sys.path for vendor

import target_pricing as tp  # vendored

DOMAIN = "cdui-orchestrations.target.com"
CHAIN = "target"
NUM_RESULTS = 24  # same page size the production app uses


def session() -> dict:
    try:
        return tp._ensure_http_session()
    except Exception as e:
        raise ChainBlocked(f"session:{repr(e)[:160]}")


def _get(url: str, sess: dict) -> str:
    try:
        return tp._redsky_get_http(url, sess)
    except tp._ImpervaBlocked as e:
        if e.category == "explicit":
            raise ChainBlocked(f"explicit:{e}")
        raise TransientError(f"{e.category}:{e}")


def search(term: str, store_id: str, sess: dict, num_results: int = NUM_RESULTS) -> str:
    """Raw slp JSON text for one search at one store."""
    url = tp._slp_url(term, str(store_id), num_results)
    return PACER.call(DOMAIN, _get, url, sess)


def _get_page(url: str, sess: dict) -> str:
    from curl_cffi import requests as _ccffi
    headers = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "accept-language": "en-US,en;q=0.9", "referer": "https://www.target.com/",
               "user-agent": sess["ua"]}
    try:
        resp = _ccffi.get(url, headers=headers, cookies=sess["cookies"],
                          impersonate=tp._IMPERSONATE, timeout=30)
    except Exception as e:
        raise TransientError(f"transport:{repr(e)[:120]}")
    if resp.status_code == 403 or "captchaRelativeURL" in resp.text or "px-captcha" in resp.text:
        raise ChainBlocked(f"explicit:product page http {resp.status_code}")
    if resp.status_code != 200:
        raise TransientError(f"soft:product page http {resp.status_code}")
    return resp.text


def product_page(tcin: str, sess: dict) -> str:
    """Raw HTML of a product page (used once per item to read its UPC)."""
    return PACER.call("www.target.com", _get_page, f"https://www.target.com/p/-/A-{tcin}", sess)
