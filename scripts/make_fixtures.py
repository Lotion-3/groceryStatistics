"""Turn a few raw smoke-test responses into small, committed test fixtures.

Fixtures are trimmed to the parts the parsers read, and anything that could
identify the collecting machine is dropped (Target's `page_context` blob
encodes the requester's approximate location; Walmart's __NEXT_DATA__ carries
session/page state). Each fixture keeps a pointer to its source raw file.

Usage:  python -m scripts.make_fixtures
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

from collectors.common import RAW_DIR, ROOT
from collectors.parsers import target_products, walmart_find_items

OUT = ROOT / "tests" / "fixtures"


def _env(chain: str, store: str, item: str) -> tuple[dict, Path]:
    p = sorted((RAW_DIR / "snap1" / chain / store).glob(f"{item}__search__*.json.gz"))[0]
    return json.load(gzip.open(p, "rt", encoding="utf-8")), p


def _write(name: str, body, source: Path, note: str) -> None:
    doc = {"_source": source.relative_to(ROOT).as_posix(), "_note": note, "body": body}
    (OUT / name).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print("wrote", name)


def walmart() -> None:
    env, src = _env("walmart", "2098", "cer_cheerios_18")
    items = walmart_find_items(json.loads(env["body"]))
    keep, seen = [], set()
    for it in items:   # one of each (fulfillmentType, has comparison price) combination
        pl = ((it.get("priceInfo") or {}).get("priceDetails") or {}).get("priceLines") or []
        key = (it.get("__typename"), it.get("fulfillmentType"), any(l["lineType"] == "COMPARISON" for l in pl))
        if key not in seen:
            seen.add(key)
            keep.append(it)
    _write("walmart_search_cheerios.json", {"itemStacks": [{"items": keep}]}, src,
           "Walmart search items (one per fulfillment-type/markdown combination), scoped store 2098.")


def target() -> None:
    env, src = _env("target", "1058", "cer_cheerios_18")
    data = json.loads(env["body"])
    prods = target_products(data)
    pick = [prods[0]] + [p for p in prods if str(p["price"].get("location_id")) != "1058"][:1]
    for st in ("1058",):
        pass
    sale_env, _ = _env("target", "1058", "sod_coke_12pk")
    sale = [p for p in target_products(json.loads(sale_env["body"]))
            if p["price"].get("formatted_current_price_type") == "sale"][:1]
    body = {"data_source_modules": [{"module_data": {"search_response": {"products": pick + sale}}}]}
    _write("target_search_cheerios.json", body, src,
           "Target slp products: a regular item, an item priced at another location, a sale item. "
           "page_context removed.")


def costco() -> None:
    env, src = _env("costco", "1809", "cer_cheerios_18")
    data = json.loads(env["body"])
    items = data["items"]["items"]
    sale = [i for i in items if (i["price"]["viewSection"].get("badge") or {}).get("offerLabelString")]
    body = {"search_ids": data["search_ids"][:3], "items": {"items": items[:2] + sale[:1]}}
    _write("instacart_costco_cheerios.json", body, src, "Instacart Items response for Costco, trimmed.")


def product_pages() -> None:
    for chain, rx in (("walmart", r'"upc"\s*:\s*"\d+"'), ("target", r'\\?"primary_barcode\\?"\s*:\s*\\?"\d+')):
        for p in sorted((RAW_DIR / "snapitems" / chain / "product_pages").glob("*.json.gz"))[:1]:
            body = json.load(gzip.open(p, "rt", encoding="utf-8"))["body"]
            m = re.search(rx, body)
            if m:
                snippet = body[max(0, m.start() - 120): m.end() + 60]
                _write(f"{chain}_product_page_snippet.json", snippet, p,
                       f"{chain} product page: only the text around the UPC field is kept.")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    walmart(); target(); costco(); product_pages()
    return 0


if __name__ == "__main__":
    sys.exit(main())
