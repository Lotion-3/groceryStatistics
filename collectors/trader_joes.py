"""Trader Joe's wrapper around the vendored trader_joes_pricing module.

Trader Joe's website exposes ONE national price per SKU (Magento GraphQL,
no store parameter). So these rows are a uniform-price reference series,
recorded against a single pseudo-store ('national', source='national',
store_specific=0). They cannot measure store-level dispersion.

Reused unchanged: the module's requests.Session (headers), endpoint and query.
"""
from __future__ import annotations

from collectors.common import PACER, ChainBlocked, TransientError  # sets sys.path for vendor

import trader_joes_pricing as tj  # vendored

DOMAIN = "www.traderjoes.com"
CHAIN = "trader_joes"


def _post(term: str, page_size: int) -> str:
    try:
        r = tj._session.post(tj._GQL_URL, json={
            "operationName": "SearchProducts",
            "variables": {"search": term, "pageSize": page_size, "currentPage": 1},
            "query": tj._PRODUCTS_QUERY,
        }, timeout=15)
    except Exception as e:
        raise TransientError(f"transport:{repr(e)[:120]}")
    if r.status_code in (403, 429):
        raise ChainBlocked(f"explicit:http {r.status_code}")
    if r.status_code != 200:
        raise TransientError(f"soft:http {r.status_code}")
    return r.text


def search(term: str, page_size: int = 20) -> str:
    return PACER.call(DOMAIN, _post, term, page_size)
