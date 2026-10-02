"""Parser tests on saved (trimmed) live responses from the 2026-10-01 smoke test."""
import json
from pathlib import Path

import pytest

from collectors import parsers as P

FIX = Path(__file__).parent / "fixtures"


def body(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))["body"]


# --- helpers ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("$8.27", 8.27), ("4.97", 4.97), (5.29, 5.29), ("", None), (None, None), (0, None), ("$1,234.50", 1234.5)])
def test_money(raw, expected):
    assert P.money(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("27.6 ¢/oz", (0.276, "oz")), ("$0.29/ounce", (0.29, "oz")), ("17.2 ¢/fl oz", (0.172, "fl oz")),
    ("$1.23/lb", (1.23, "lb")), ("", (None, None)), (None, (None, None))])
def test_unit_price(raw, expected):
    assert P.unit_price(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("076808280081", "076808280081"),          # valid UPC-A
    ("0076808280081", "076808280081"),         # EAN-13 with leading zero
    ("00049000028904", "049000028904"),        # GTIN-14
    ("076808280082", None),                    # bad check digit
    ("1076808280081", None),                   # EAN-13 not starting with 0
    ("12345", None), (None, None)])
def test_normalize_upc(raw, expected):
    assert P.normalize_upc(raw) == expected


def test_promo_rule():
    assert P._promo_fields(7.0, 8.99) == {"price": 7.0, "regular_price": 8.99, "promo_price": 7.0, "is_promo": 1}
    assert P._promo_fields(5.29, 5.29)["is_promo"] == 0
    assert P._promo_fields(5.29, None) == {"price": 5.29, "regular_price": 5.29, "promo_price": None, "is_promo": 0}
    # a "was" price below the current price is not a promotion
    assert P._promo_fields(5.29, 4.00)["is_promo"] == 0


# --- Walmart -----------------------------------------------------------------

def test_walmart_search():
    rows = P.parse_walmart(json.dumps(body("walmart_search_cheerios.json")))
    assert rows, "expected products"
    assert all(r["chain_product_id"] and r["product_name"] for r in rows)
    assert all(r["price"] and r["price"] > 0 for r in rows)
    types = {r["extra"]["fulfillment_type"] for r in rows}
    assert {"STORE", "MARKETPLACE"} <= types
    # store-fulfilled items carry the scoped store id; marketplace items do not
    for r in rows:
        if r["extra"]["fulfillment_type"] == "MARKETPLACE":
            assert r["priced_store_id"] is None and r["extra"]["third_party_seller"] == 1
    assert any(r["priced_store_id"] == "2098" for r in rows)
    # at least one markdown with a WAS price
    promo = [r for r in rows if r["is_promo"]]
    assert promo and all(r["regular_price"] > r["price"] == r["promo_price"] for r in promo)
    # unit prices parsed in dollars
    assert any(r["unit_price"] and r["unit_price"] < 1 and r["unit_price_unit"] == "oz" for r in rows)


def test_walmart_skips_ad_tiles():
    items = [{"__typename": "AdPlaceholder", "name": None}, {"name": "x", "usItemId": None}]
    assert P.parse_walmart(json.dumps({"itemStacks": [{"items": items}]})) == []


def test_walmart_legacy_flat_price_fields():
    rows = P.parse_walmart(json.dumps(
        [dict(it, usItemId=str(i)) for i, it in enumerate(body_legacy())]))
    assert rows[0]["price"] == 8.27 and rows[0]["unit_price"] == pytest.approx(0.172)


def body_legacy():
    return json.loads((FIX / "walmart_search_items_milk_legacy.json").read_text(encoding="utf-8"))


def test_walmart_product_page_upc():
    assert P.parse_walmart_product_page_upc(body("walmart_product_page_snippet.json")) == "076808280081"


# --- Target ------------------------------------------------------------------

def test_target_search():
    rows = P.parse_target(json.dumps(body("target_search_cheerios.json")))
    assert len(rows) == 3
    r0 = rows[0]
    assert r0["chain_product_id"] == "81875238" and r0["brand"] == "Cheerios"
    assert r0["price"] == 5.29 and r0["is_promo"] == 0 and r0["priced_store_id"] == "1058"
    assert r0["unit_price"] == pytest.approx(0.29) and r0["unit_price_unit"] == "oz"
    assert r0["in_stock"] == 1
    assert r0["extra"]["promotions"] == ["Buy 2 for $9 breakfast cereal"]
    # an item priced at another location (not store-specific for 1058)
    assert rows[1]["priced_store_id"] != "1058"
    # a sale item
    sale = rows[2]
    assert sale["is_promo"] == 1 and sale["regular_price"] > sale["price"]
    assert sale["extra"]["price_type"] == "sale"


def test_target_store_location():
    loc = P.target_store_location(json.dumps(body("target_search_cheerios.json")))
    assert loc["store_id"] == "1058" and loc["postal_code"].startswith("43212") and loc["city"] == "Columbus"


def test_target_product_page_upc():
    assert P.parse_target_product_page_upc(body("target_product_page_snippet.json")) == "049000028904"


# --- Costco via Instacart ------------------------------------------------------

def test_instacart_items():
    rows = P.parse_instacart(json.dumps(body("instacart_costco_cheerios.json")))
    assert len(rows) == 3
    assert all(r["upc"] is None and r["price"] > 0 for r in rows)
    assert rows[0]["priced_store_id"] == "7035"           # retailerLocationId from the item id
    assert rows[0]["brand"] == "general mills"
    assert rows[-1]["extra"]["offer_label"]                # the sale badge was kept as text


# --- Trader Joe's (synthetic shape; live endpoint returned 403) -------------------

def test_trader_joes_shape():
    raw = {"data": {"products": {"items": [
        {"sku": "123", "name": "Joe's O's Cereal 15 oz",
         "price_range": {"minimum_price": {"regular_price": {"value": 2.99, "currency": "USD"}}}}],
        "total_count": 1}}}
    rows = P.parse_trader_joes(json.dumps(raw))
    assert rows[0]["price"] == 2.99 and rows[0]["pack_size"] == "15 oz" and rows[0]["is_promo"] == 0


# --- Kroger (Public API, certification env; fixtures are live responses) ---

def test_kroger_upc_conversion():
    from collectors.parsers import kroger_upc
    # Barilla Spaghetti 16 oz: Kroger id vs the UPC on Target's product page
    assert kroger_upc("0007680828008") == "076808280081"
    assert kroger_upc("123") is None


def test_kroger_priced_row_is_store_specific():
    from collectors.parsers import parse_kroger
    rows = parse_kroger((FIX / "kroger_search_coke_promo.json").read_text(encoding="utf-8"))
    priced = [r for r in rows if r["price"] is not None]
    assert priced and all(r["priced_store_id"] == "01600942" for r in priced)
    assert all(r["upc"] and len(r["upc"]) == 12 for r in rows)
    # promo equal to regular is not a promotion
    assert all(r["is_promo"] == 0 for r in priced if r["price"] == r["regular_price"])


def test_kroger_unpriced_rows_kept_but_not_store_specific():
    from collectors.parsers import parse_kroger
    rows = parse_kroger((FIX / "kroger_search_bread_unpriced.json").read_text(encoding="utf-8"))
    assert rows and all(r["price"] is None and r["priced_store_id"] is None for r in rows)


# --- Meijer (Constructor.io) and ALDI (Instacart white-label); live probes 2026-10-02 ---

def test_meijer_multibuy_is_not_a_promotion():
    rows = P.parse_meijer((FIX / "meijer_search_pas_barilla_spaghetti_16.json").read_text(encoding="utf-8"))
    b = next(r for r in rows if r["upc"] == "076808280081")      # same UPC as Target / Kroger
    assert b["extra"]["multibuy"] and b["is_promo"] == 0 and b["price"] == b["regular_price"] == 1.89
    assert all(r["priced_store_id"] == "104" for r in rows)


def test_meijer_straight_sale_is_a_promotion():
    rows = P.parse_meijer((FIX / "meijer_search_sod_coke_12pk.json").read_text(encoding="utf-8"))
    sale = [r for r in rows if r["is_promo"]]
    assert sale and all(r["price"] < r["regular_price"] for r in sale)


def test_meijer_upc_without_check_digit():
    assert P.upc_from_no_check(7680828008) == "076808280081"
    assert P.upc_from_no_check(4900001278) == "049000012781"


def test_aldi_rows_tied_to_shop_location():
    rows = P.parse("aldi", (FIX / "aldi_search_eggs.json").read_text(encoding="utf-8"))
    assert rows and all(r["priced_store_id"] == "178404" for r in rows)
    assert all(r["price"] > 0 for r in rows)
