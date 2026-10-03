"""Pure parsers: raw retailer response body -> one dict per returned product.

Every product in the response becomes a row (never only the cheapest). These
functions do no I/O, so they can be re-run over data/raw/ at any time (see
collectors/reparse.py) and are unit-tested against saved responses in
tests/fixtures/.

Row keys (the `observations` columns that come from the response; the
snapshot/store context is added by the caller):
    chain_product_id, product_name, brand, upc, price, regular_price,
    promo_price, is_promo, unit_price, unit_price_unit, pack_size, in_stock,
    priced_store_id, search_rank, extra (dict of chain-specific fields)

Promo rule (spec section 5): is_promo = 1 iff the retailer reports a regular /
"was" price strictly above the current price. `price` is always the price
shown now; `regular_price` falls back to `price` when no separate regular
price is reported; `promo_price` is set only when is_promo. Multi-buy deals
("Buy 2 for $9") and clip coupons do NOT change `price`; they are kept as
text in `extra` so they can be studied separately.

Paths marked VERIFIED were confirmed on live responses on 2026-10-01 (see
docs/REPO_NOTES.md, "Raw field paths"); the rest are tolerant fallbacks.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(r"\$?\s*(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)")


def money(v: Any) -> Optional[float]:
    """'$8.27' -> 8.27, 8.27 -> 8.27, '' / None / 0 -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    m = _MONEY_RE.search(str(v))
    if not m:
        return None
    x = float(m.group(1).replace(",", ""))
    return x if x > 0 else None


_UNIT_PRICE_RE = re.compile(
    r"(?P<sym>\$)?\s*(?P<val>\d+(?:\.\d+)?)\s*(?P<cents>¢)?\s*(?:/|per)\s*(?P<unit>[a-zA-Z .]+)")
_UNIT_ALIASES = {"ounce": "oz", "ounces": "oz", "fluid ounce": "fl oz", "fl. oz": "fl oz",
                 "fluid ounces": "fl oz", "pound": "lb", "lbs": "lb", "each": "ct",
                 "count": "ct", "ea": "ct", "ct.": "ct"}


def unit_price(s: Any) -> tuple[Optional[float], Optional[str]]:
    """'27.6 ¢/oz' -> (0.276, 'oz'); '$0.29/ounce' -> (0.29, 'oz')."""
    if not s or not isinstance(s, str):
        return None, None
    m = _UNIT_PRICE_RE.search(s.replace(" ", " "))
    if not m:
        return None, None
    val = float(m.group("val"))
    if m.group("cents") and not m.group("sym"):
        val /= 100.0
    unit = m.group("unit").strip().lower().rstrip(".")
    return round(val, 5), _UNIT_ALIASES.get(unit, unit)


def upc_check_ok(upc12: str) -> bool:
    """UPC-A check digit."""
    if not re.fullmatch(r"\d{12}", upc12 or ""):
        return False
    d = [int(c) for c in upc12]
    return (10 - (3 * sum(d[0:11:2]) + sum(d[1:11:2])) % 10) % 10 == d[11]


def normalize_upc(raw: Any) -> Optional[str]:
    """12-digit UPC-A from a UPC-A, an EAN-13 with a leading 0 or a GTIN-14
    with leading zeros; None if not valid (check digit verified)."""
    if raw is None:
        return None
    d = re.sub(r"\D", "", str(raw))
    if len(d) > 12:
        if set(d[: len(d) - 12]) != {"0"}:
            return None
        d = d[-12:]
    return d if len(d) == 12 and upc_check_ok(d) else None


def _get(d: Any, *path, default=None):
    for k in path:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int) and -len(d) <= k < len(d):
            d = d[k]
        else:
            return default
        if d is None:
            return default
    return d


def _promo_fields(price: Optional[float], regular: Optional[float]) -> dict:
    if regular is not None and price is not None and regular <= price + 1e-9:
        regular = None  # a "was" price not above the current price is not a promo
    is_promo = int(regular is not None and price is not None)
    return {
        "price": price,
        "regular_price": regular if regular is not None else price,
        "promo_price": price if is_promo else None,
        "is_promo": is_promo,
    }


# ---------------------------------------------------------------------------
# Walmart  (body = the search page's __NEXT_DATA__ JSON text)
# ---------------------------------------------------------------------------

def walmart_find_items(o: Any) -> list[dict]:
    """Same walk as vendored walmart_pricing._find_items: the first dict whose
    itemStacks[] carry items, concatenated across stacks."""
    if isinstance(o, dict):
        if isinstance(o.get("itemStacks"), list):
            items = [it for st in o["itemStacks"] if isinstance(st, dict)
                     for it in (st.get("items") or [])]
            if items:
                return items
        for v in o.values():
            r = walmart_find_items(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = walmart_find_items(v)
            if r:
                return r
    return []


def _walmart_line(pi: dict, line_type: str, key: str) -> Optional[str]:
    for line in _get(pi, "priceDetails", "priceLines", default=[]) or []:
        if line.get("lineType") == line_type:
            for v in line.get("values") or []:
                if v.get("key") == key:
                    return v.get("value")
    return None


def parse_walmart_item(it: dict, rank: int) -> Optional[dict]:
    if not isinstance(it, dict) or not it.get("name"):
        return None
    pid = it.get("usItemId")          # ad tiles (AdPlaceholder) have none
    if not pid:
        return None
    pi = it.get("priceInfo") or {}
    # VERIFIED: priceInfo.priceDetails.priceLines[] lineTypes seen:
    #   CURRENT_PRICE/PRICE      normal price
    #   DISCOUNTED_PRICE/PRICE + COMPARISON/WAS_PRICE   a markdown
    #   UNIT_PRICE/UNIT_PRICE    e.g. "27.6 ¢/oz"
    #   SHIPPING/PRICE, OPTIONS_RANGE, OPTIONS
    # The flat legacy fields (linePrice, wasPrice, unitPrice) have been empty
    # strings since ~2026-07; kept only as fallbacks for older captures.
    price = (money(_walmart_line(pi, "CURRENT_PRICE", "PRICE"))
             or money(_walmart_line(pi, "DISCOUNTED_PRICE", "PRICE"))
             or money(pi.get("linePrice")) or money(pi.get("linePriceDisplay"))
             or money(pi.get("itemPrice")))
    regular = money(_walmart_line(pi, "COMPARISON", "WAS_PRICE")) or money(pi.get("wasPrice"))
    up, upu = unit_price(_walmart_line(pi, "UNIT_PRICE", "UNIT_PRICE") or pi.get("unitPrice"))
    avail = it.get("availabilityStatusV2")
    avail_val = (avail.get("value") if isinstance(avail, dict) else avail) or it.get("availabilityStatus")
    in_stock = int(avail_val.upper() == "IN_STOCK") if isinstance(avail_val, str) else None
    # VERIFIED: fulfillmentSummary[] may hold several entries (delivery,
    # pickup); the store id can appear only in a later one. "0" means not
    # store-fulfilled (marketplace seller or fulfilment centre).
    sids = [str(fs.get("storeId")) for fs in it.get("fulfillmentSummary") or []
            if fs.get("storeId") and str(fs.get("storeId")) != "0"]
    priced_at = max(sorted(set(sids)), key=sids.count) if sids else None
    return {
        "chain_product_id": str(pid),
        "product_name": it.get("name"),
        "brand": it.get("brand") or None,      # not populated in search results
        "upc": normalize_upc(it.get("upc")),   # not populated in search results
        **_promo_fields(price, regular),
        "unit_price": up, "unit_price_unit": upu,
        "pack_size": None,
        "in_stock": in_stock,
        "priced_store_id": priced_at,
        "search_rank": rank,
        "extra": {
            "fulfillment_type": it.get("fulfillmentType"),   # STORE | FC | MARKETPLACE
            "seller_name": it.get("sellerName"),
            "third_party_seller": int(bool(it.get("hasSellerBadge"))
                                      or it.get("fulfillmentType") == "MARKETPLACE"),
            "sold_by_weight": int(bool(pi.get("finalCostByWeight"))),
            "shipping_price": money(_walmart_line(pi, "SHIPPING", "PRICE")),
            "sponsored": int(bool(it.get("isSponsoredFlag"))),
        },
    }


def parse_walmart(body: str) -> list[dict]:
    data = json.loads(body) if isinstance(body, str) else body
    items = data if isinstance(data, list) else walmart_find_items(data)
    rows = [parse_walmart_item(it, i) for i, it in enumerate(items)]
    return [r for r in rows if r]


_WALMART_UPC_RES = (
    re.compile(r'"upc"\s*:\s*"(\d{8,14})"'),
    re.compile(r'"gtin13"\s*:\s*"(\d{8,14})"'),
    re.compile(r'"gtin"\s*:\s*"(\d{8,14})"'),
)


def parse_walmart_product_page_upc(body: str) -> Optional[str]:
    """UPC from a walmart.com/ip/<usItemId> page (HTML incl. __NEXT_DATA__)."""
    for rx in _WALMART_UPC_RES:
        for m in rx.finditer(body or ""):
            u = normalize_upc(m.group(1))
            if u:
                return u
    return None


# ---------------------------------------------------------------------------
# Target  (body = cdui_orchestrations slp JSON)
# ---------------------------------------------------------------------------

def target_products(data: dict) -> list[dict]:
    """Same extraction as vendored target_pricing._extract_slp_products."""
    for mod in data.get("data_source_modules") or []:
        products = _get(mod, "module_data", "search_response", "products")
        if products:
            return products
    return []


def parse_target_product(p: dict, rank: int) -> Optional[dict]:
    item = p.get("item") or {}
    tcin = p.get("tcin") or item.get("tcin")
    title = _get(item, "product_description", "title")
    if not tcin or not title:
        return None
    # VERIFIED: price.{current_retail, reg_retail, formatted_current_price_type
    # ('reg' | 'sale' | ...), formatted_unit_price + _suffix, location_id}.
    # location_id is the store the price is set at; it is NOT always the
    # requested store (~10% of products came back priced at location 3991,
    # apparently an online/default location), so priced_store_id carries it
    # and the caller decides store specificity.
    pr = p.get("price") or {}
    price = money(pr.get("current_retail")) or money(pr.get("current_retail_min")) \
        or money(pr.get("formatted_current_price"))
    regular = money(pr.get("reg_retail")) or money(pr.get("reg_retail_min"))
    unit_str = (f"{pr.get('formatted_unit_price')}{pr.get('formatted_unit_price_suffix') or ''}"
                if pr.get("formatted_unit_price") else None)
    up, upu = unit_price(unit_str)
    so = _get(p, "fulfillment", "store_options", 0) or {}
    status = _get(so, "in_store_only", "availability_status") or _get(so, "order_pickup", "availability_status")
    in_stock = int(status.upper() in ("IN_STOCK", "LIMITED_STOCK")) if isinstance(status, str) else None
    return {
        "chain_product_id": str(tcin),
        "product_name": html.unescape(title),
        "brand": _get(item, "primary_brand", "name"),
        "upc": normalize_upc(_get(item, "primary_barcode")),   # absent from slp search results
        **_promo_fields(price, regular),
        "unit_price": up, "unit_price_unit": upu,
        "pack_size": None,
        "in_stock": in_stock,
        "priced_store_id": str(pr["location_id"]) if pr.get("location_id") is not None else None,
        "search_rank": rank,
        "extra": {
            "price_type": pr.get("formatted_current_price_type"),
            "promotions": [x.get("plp_message") for x in p.get("promotions") or []] or None,
            "dpci": item.get("dpci"),
            "fulfillment_store_id": so.get("location_id"),
            "pickup_status": _get(so, "order_pickup", "availability_status"),
        },
    }


def parse_target(body: str) -> list[dict]:
    data = json.loads(body) if isinstance(body, str) else body
    rows = [parse_target_product(p, i) for i, p in enumerate(target_products(data))]
    return [r for r in rows if r]


def target_store_location(body: str) -> Optional[dict]:
    """The store Target says it searched (VERIFIED: fulfillment.store_options[0]):
    {store_id, name, address_line1, city, state, postal_code}."""
    data = json.loads(body) if isinstance(body, str) else body
    for p in target_products(data):
        so = _get(p, "fulfillment", "store_options", 0) or {}
        st = so.get("store") or {}
        addr = st.get("mailing_address") or {}
        if addr.get("postal_code"):
            return {"store_id": str(so.get("location_id")), "name": st.get("location_name"),
                    "address_line1": addr.get("address_line1"), "city": addr.get("city"),
                    "state": addr.get("state"), "postal_code": addr.get("postal_code")}
    return None


_TARGET_UPC_RE = re.compile(r'\\?"primary_barcode\\?"\s*:\s*\\?"(\d{8,14})')


def parse_target_product_page_upc(body: str) -> Optional[str]:
    """UPC from a target.com/p/-/A-<tcin> page (embedded JSON, possibly escaped)."""
    for m in _TARGET_UPC_RE.finditer(body or ""):
        u = normalize_upc(m.group(1))
        if u:
            return u
    return None


# ---------------------------------------------------------------------------
# Costco via Instacart  (body = {"search_ids": [...], "items": <Items data>},
# written by collectors/costco_instacart.search)
# ---------------------------------------------------------------------------

def parse_instacart_item(it: dict, rank: int) -> Optional[dict]:
    if not it.get("id") or not it.get("name"):
        return None
    # VERIFIED: price.viewSection.{priceValueString, priceString,
    # fullPriceString (struck-through regular price; null when not on sale),
    # badge.offerLabelString (e.g. "$6 off; limit 6")},
    # price.viewSection.itemCard.pricingUnitString (e.g. "2 ct").
    vs = _get(it, "price", "viewSection") or {}
    card = vs.get("itemCard") or {}
    price = money(vs.get("priceValueString")) or money(vs.get("priceString")) or money(card.get("priceString"))
    regular = money(vs.get("fullPriceString")) or money(card.get("fullPriceString")) \
        or money(card.get("plainFullPriceString"))
    up, upu = unit_price(card.get("pricePerUnitString"))
    avail = it.get("availability") or {}
    in_stock = int(avail["available"]) if isinstance(avail.get("available"), bool) else None
    m = re.match(r"items_(\d+)-", str(it["id"]))
    return {
        "chain_product_id": str(it["id"]),
        "product_name": it.get("name"),
        "brand": it.get("brandName") or None,
        "upc": None,                       # Instacart does not expose UPCs
        **_promo_fields(price, regular),
        "unit_price": up, "unit_price_unit": upu,
        "pack_size": card.get("pricingUnitString") or it.get("size"),
        "in_stock": in_stock,
        "priced_store_id": m.group(1) if m else None,   # Instacart retailerLocationId
        "search_rank": rank,
        "extra": {
            "offer_label": _get(vs, "badge", "offerLabelString"),
            "stock_level": avail.get("stockLevel"),
            "instacart_product_id": it.get("productId"),
            "size_field": it.get("size"),
        },
    }


def parse_instacart(body: str) -> list[dict]:
    data = json.loads(body) if isinstance(body, str) else body
    items = _get(data, "items", "items") or []
    rows = [parse_instacart_item(it, i) for i, it in enumerate(items)]
    return [r for r in rows if r]


# ---------------------------------------------------------------------------
# Trader Joe's  (body = Magento GraphQL SearchProducts response)
# NOTE: not yet verified live -- the endpoint returned HTTP 403 on 2026-10-01.
# ---------------------------------------------------------------------------

_TJ_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(fl\.?\s*oz|oz|ounce|lb|lbs|pound|gal|gallon|count|ct|pk|pack|each|liter|ml|g|kg)\b",
    re.IGNORECASE)


def parse_trader_joes(body: str) -> list[dict]:
    data = json.loads(body) if isinstance(body, str) else body
    items = _get(data, "data", "products", "items") or []
    rows = []
    for i, it in enumerate(items):
        if not it.get("sku") or not it.get("name"):
            continue
        price = money(_get(it, "price_range", "minimum_price", "regular_price", "value"))
        m = _TJ_SIZE_RE.search(it["name"])
        rows.append({
            "chain_product_id": str(it["sku"]),
            "product_name": it["name"],
            "brand": "Trader Joe's",
            "upc": None,
            **_promo_fields(price, None),
            "unit_price": None, "unit_price_unit": None,
            "pack_size": f"{m.group(1)} {m.group(2)}" if m else None,
            "in_stock": None,
            "priced_store_id": None,
            "search_rank": i,
            "extra": None,
        })
    return rows


# ---------------------------------------------------------------------------
# Kroger Public API  (body = {"location_id", "term", "status", "response": <API JSON>},
# written by collectors/kroger.search)
# ---------------------------------------------------------------------------

def kroger_upc(raw: Any) -> Optional[str]:
    """Kroger sends 13 digits WITHOUT the check digit ('0007680828008').
    UPC-A = the last 11 digits + the computed check digit ('076808280081').
    VERIFIED: equals Target's product-page UPC for Barilla Spaghetti 16 oz."""
    d = re.sub(r"\D", "", str(raw or ""))
    if len(d) != 13:
        return None
    body = [int(c) for c in d[-11:]]
    chk = (10 - (3 * sum(body[0::2]) + sum(body[1::2])) % 10) % 10
    return normalize_upc(d[-11:] + str(chk))


def parse_kroger(body: str) -> list[dict]:
    env = json.loads(body) if isinstance(body, str) else body
    loc = str(env.get("location_id") or "")
    rows = []
    for i, p in enumerate(_get(env, "response", "data") or []):
        if not p.get("productId") or not p.get("description"):
            continue
        it = (p.get("items") or [{}])[0]
        pr = it.get("price") or {}
        # VERIFIED (certification env, 2026-10-02): items[].price = {regular,
        # promo, effectiveDate, expirationDate}; promo absent or 0 or equal to
        # regular when there is no promotion; many products carry no price.
        regular = money(pr.get("regular"))
        promo = money(pr.get("promo"))
        price = promo if (promo and regular and promo < regular) else regular
        stock = _get(it, "inventory", "stockLevel")
        rows.append({
            "chain_product_id": str(p["productId"]),
            "product_name": p.get("description"),
            "brand": p.get("brand") or None,
            "upc": kroger_upc(p.get("upc")),
            **_promo_fields(price, regular),
            "unit_price": None, "unit_price_unit": None,
            "pack_size": it.get("size"),
            "in_stock": None if stock is None else int(stock != "TEMPORARILY_OUT_OF_STOCK"),
            # A price is returned only when filter.locationId is given, so it
            # is that store's price.
            "priced_store_id": loc if price is not None else None,
            "search_rank": i,
            "extra": {"stock_level": stock, "price_effective": _get(pr, "effectiveDate", "value"),
                      "fulfillment": it.get("fulfillment"), "sold_by": it.get("soldBy"),
                      "term": env.get("term"), "http_status": env.get("status")},
        })
    return rows


# ---------------------------------------------------------------------------
# Meijer  (body = {"store_id", "term", "status", "response": <Constructor.io JSON>},
# written by collectors/meijer.search)
# ---------------------------------------------------------------------------

def upc_from_no_check(raw: Any) -> Optional[str]:
    """UPC-A from a number given WITHOUT its check digit and with leading zeros
    dropped (Meijer's `ean`, e.g. 7680828008 -> 076808280081). A 12-digit value
    whose check digit is already valid is returned as is."""
    d = re.sub(r"\D", "", str(raw or ""))
    if not d or len(d) > 12:
        return None
    if len(d) == 12 and upc_check_ok(d):
        return d
    body = d.zfill(11)[-11:]
    n = [int(c) for c in body]
    chk = (10 - (3 * sum(n[0::2]) + sum(n[1::2])) % 10) % 10
    return normalize_upc(body + str(chk))


_MULTIBUY_RE = re.compile(r"\b(buy|for)\b.*\d", re.IGNORECASE)


def parse_meijer(body: str) -> list[dict]:
    env = json.loads(body) if isinstance(body, str) else body
    sid = str(env.get("store_id") or "")
    rows = []
    for i, x in enumerate(_get(env, "response", "response", "results") or []):
        d = x.get("data") or {}
        if not d.get("id") or not x.get("value"):
            continue
        # VERIFIED (2026-10-02): `price` is the regular price. With sale=True,
        # discountSalePriceValue is the sale price; for multi-buy offers
        # ("Buy 3 for $4.00") it is a per-unit price that only applies when
        # buying the multiple -- not a shelf price (DECISIONS #12), so it is
        # kept in `extra` and not treated as a promotion.
        regular = money(d.get("price"))
        text = d.get("discountSalePriceText") or ""
        multibuy = bool(_MULTIBUY_RE.search(text))
        sale = money(d.get("discountSalePriceValue")) if d.get("sale") and not multibuy else None
        price = sale if (sale is not None and regular is not None and sale < regular) else regular
        stock = d.get("stockLevelStatus")
        rows.append({
            "chain_product_id": str(d["id"]),
            "product_name": x.get("value"),
            "brand": None,
            "upc": upc_from_no_check(d.get("ean")),
            **_promo_fields(price, regular),
            "unit_price": None, "unit_price_unit": None,
            "pack_size": d.get("productUnit"),
            "in_stock": None if stock is None else int(str(stock).lower() == "instock"),
            "priced_store_id": sid if price is not None else None,
            "search_rank": i,
            "extra": {"sale_flag": d.get("sale"), "sale_text": text or None,
                      "sale_value": d.get("discountSalePriceValue"), "multibuy": multibuy,
                      "mperks": d.get("hasMPerks"), "price_good_through": d.get("priceGoodThrough"),
                      "price_by_weight": d.get("priceByWeight"), "term": env.get("term")},
        })
    return rows


PARSERS = {
    "meijer": parse_meijer,
    "aldi": parse_instacart,
    "kroger": parse_kroger,
    "kroger_ce": parse_kroger,
    "walmart": parse_walmart,
    "target": parse_target,
    "costco": parse_instacart,
    "trader_joes": parse_trader_joes,
}


def parse(chain: str, body: str) -> list[dict]:
    return PARSERS[chain](body)


def iter_rows(chain: str, bodies: Iterable[str]) -> Iterable[dict]:
    for b in bodies:
        yield from parse(chain, b)
