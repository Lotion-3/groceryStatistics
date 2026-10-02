# Notes on the basketBuddy price engine

These notes describe the parts of the owner's basketBuddy repo (`backend/`, commit
`9310f751`, read 2026-10-01) that this project reuses. They are written so that
basketBuddy never needs to be opened again: the collectors are vendored into
`collectors/vendor/` (see `VENDORED.md` there), and everything learned about them is
recorded here. Line numbers refer to the vendored copies.

## 1. Overall architecture

- **App flow:** FastAPI `server.py`. It geocodes the user, finds stores with Google Places
  inside an OpenRouteService isochrone, prices a basket at up to 10 stores in parallel,
  then runs a route optimiser.
- **Every collector has the same shape.**
  - Input: `price_all_<chain>(ingredients, lat, lon)` with
    `ingredients = {name: {"qty": float, "unit": str}}`.
  - Output: `(display_name, store_id, prices)` with `prices = {ingredient: result}`.
  - Exceptions: Trader Joe's returns a 2-tuple; Costco returns a 4-tuple with
    `meta = {is_estimate, distance_km, store}`.
- **Catalog:** `kroger_search_map.py` holds **199** canonical ingredients. Each has one
  primary search term and five fallbacks; `get_all_terms` returns at most 6.
- **Database:**
  - Supabase. Relevant tables: `stores`, `ingredients`, `prices` (with `week_number`),
    `chain_sessions`, `chain_session_pool`, `chain_block_events`.
  - **Nothing writes to `prices`.** `stores` is only seeded with 17 Indianapolis stores.
    No price history exists anywhere.
  - `schema.sql` begins with `DROP TABLE … CASCADE`. **Never run it against production.**
- **Concurrency:** one shared thread pool (`PRICING_MAX_THREADS=24`), a 75 s request budget,
  and per-chain single-flight locks.

## 2. Where "cheapest only" happens

Every US collector does the same three steps:

1. Converts raw results into a "Kroger-shaped" product dict:
   `{description, brand, items:[{itemId, soldBy, size, price:{regular, promo}}]}`.
2. Calls `kroger_pricing.find_best_purchase()`.
3. Stops at the **first search term** that yields anything (`_price_one`).

`find_best_purchase` (`kroger_pricing.py:674-909`) then discards information at several
points:

| Where | What it does |
|---|---|
| lines 746-751 | Keyword relevance filter |
| line 795 | Computes the cost of the cheapest whole-package combination covering the requested quantity |
| lines 817-821 | Sorts by **total cost** and returns `paired[0]`. Total cost, not unit price, so the requested quantity changes which product wins |
| lines 324-330 | `_effective_price = min(regular, promo)`: promo and regular are merged |
| line 382 vs. 881-908 | Product id is stored internally as `PricedProduct.upc` but **dropped from the returned dict** |

Return keys: `units_to_buy, total_qty, unit, overage, overage_pct, total_cost,
unit_price_str, description, brand, size_str, sold_by, notes`.

**Consequence:** this project never calls `price_all_*` or `find_best_purchase`. The
wrappers in `collectors/` call the lower-level fetch functions and keep every product
and the raw response.

## 3. Collector reference

### Walmart (`walmart_pricing.py`)

**Search**
- `GET https://www.walmart.com/search?q={q}&affinityOverride=default&ps=40` returns HTML.
- Products are in `<script id="__NEXT_DATA__">`. `_find_items` takes the first dict whose
  `itemStacks[].items[]` is non-empty.
- Request: curl_cffi with `impersonate="chrome"`, the session's cookies and UA, and the
  headers at lines 674-679.

**Session** (`_ensure_http_session`, ~line 1043). Sources are tried in this order:
1. Cookie pool file `.minted_walmart_cookies.json`.
2. Supabase pool (stubbed out here).
3. Disk cache `.walmart_http_session.json`.
4. A CloakBrowser mint (stealth Chromium via Playwright): visit the homepage, wait for the
   PerimeterX `_px3` cookie, run a search, then harvest cookies and UA.

**Store scoping** (added upstream 2026-09-29; `CODEBASE_REVIEW.md` is stale on this)
- `_scope_session_in_browser(postal, address)`, line ~1415, all done **in the browser**:
  1. Run the GraphQL `storeFinderNearbyNodesQuery` for the ZIP (radius 50).
  2. `_pick_node`: match on street line, otherwise `nodes[0]`.
  3. Call `setPickup(storeId, postalCode, accessPointId)`.
  4. Re-search and require `_items_store_id(items) == node.id`.
- Returns `{cookies, ua, store_id, store_name, store_address}`.
- Cost: **one browser launch per store (~30-60 s)**.
- The cached state file is `.walmart_store_session.json`.
- Overriding the `assortmentStoreId` cookie does nothing. `setPickup` over curl_cffi returns
  412.
- Persisted-query hashes and `x-o-platform-version` live in `walmart_store_graphql.json` and
  **go stale when Walmart deploys**. Re-capture them from walmart.com/store-finder.

**Fallback behaviour**
- An unscoped session prices at a store near wherever its cookie was minted.
- `price_all_walmart` returns `store_id == "national"` when scoping failed. It falls back
  silently.

**Block detection**
- HTTP status is useless: blocked pages return **200**.
- Explicit block = body contains `px-captcha`. Soft block = no `__NEXT_DATA__`.

**Limits and failure modes**
- Hard wall: more than 20 concurrent requests per cookie blocks everything, and repeated
  violations escalate to an IP block. Upstream default is 18; **we use 1**.
- Datacenter and GitHub-Actions IPs get captchas.
- Only 1/3 to 2/3 of minted cookies survive replay.
- Cookies have died within minutes, and one survived 41 days.

**Search results carry no UPC and no brand.** The UPC is in the product page
`https://www.walmart.com/ip/{usItemId}` (`"upc":"…"`).

### Target (`target_pricing.py`)

**Search**
- `GET https://cdui-orchestrations.target.com/cdui_orchestrations/v1/pages/slp?…`, built by
  `_slp_url(query, store_id, count)` (line 993).
- The public `key=9f36aeaf…` is overridable with `TARGET_API_KEY`.
- Production uses `count=24`, `offset=0`.
- Products are at `data_source_modules[].module_data.search_response.products`
  (`_extract_slp_products`).
- The URL includes `default_purchasability_filter=true`, which may hide unpurchasable or
  out-of-stock items.
- `plp_search_v2` and `nearby_stores_v1` are dead (403).

**Store selection:** the `store_id` URL parameter alone scopes pricing and fulfilment. **Any
store id can be queried directly.** No browser is needed per store.

**Session:** same pattern as Walmart (pool → disk `.target_http_session.json` → CloakBrowser
mint).
- Target is PerimeterX-protected, despite the class name `_ImpervaBlocked`.
- Block = HTTP 403 or `"captchaRelativeURL"` in the body.
- Upstream concurrency is 6. Pool cookies have survived 27 h or more.

**Store directory:** `target_store_directory.json` has 1,893 stores with fields
`{store_id, slug, lat, lon}`, built from Target's store sitemap.
- **The coordinates come from geocoding the URL slug with Nominatim and are wrong for
  roughly a quarter of stores.** In 41 of 161 stores with an OpenStreetMap store-number
  match, the slug geocode was more than 50 km off, often in another state ("frisco" placed
  in San Francisco, "pasadena" in CA for a Texas store, and so on).
- There is no ZIP, state or address in the file.

### Costco (via Instacart, `instacart_pricing.py`)

- The `costco/` probe scripts against costco.com's own APIs all returned 403 and never
  produced a collector. **Costco data exists only as Instacart storefront prices.**
- **GraphQL:** `GET https://www.instacart.com/graphql` with persisted-query hashes
  (lines 123-127, which break when Instacart redeploys).
  - `ShopCollectionScoped{retailerSlug, postalCode, coordinates}` returns the shop serving
    that ZIP.
  - `SearchResultsPlacements` returns item ids, regex-scraped as `items_\d+-\d+`, up to 20.
  - `Items{ids, shopId, zoneId, postalCode}` returns the item details.
- **Session:** cookies + `x-ic-qp` + `zoneId`, from `.ic_session.json`, else a CloakBrowser
  bootstrap of `instacart.com/store/costco/storefront`.
- **Errors are silent:** `_gql` returns `{}` on any failure and invalidates the session on
  401/403.
- **Store choice:**
  - `find_nearest_store` uses Instacart's first shop for the ZIP, which is not necessarily
    the nearest warehouse.
  - Instacart returns **no shop address**, only `id` and `retailerLocationId`.
  - `price_all_costco` walks about 80 hard-coded metro ZIPs when no local shop exists
    (`is_estimate=True`). **That substitutes a different city's warehouse, and this project
    never uses it.**
- Instacart prices can differ from in-warehouse prices. Treat them as storefront prices and
  tag `source='instacart'`.

### Trader Joe's (`trader_joes_pricing.py`)

- `POST https://www.traderjoes.com/api/graphql` (Magento `SearchProducts`). Fields:
  `sku, name, price_range.minimum_price.regular_price.value`.
- No cookies or location parameter: **one national web price per SKU.** It cannot measure
  store dispersion.
- Akamai rate limit: the upstream throttle is 0.35 s between requests, 4 workers.
- **On 2026-10-01 this endpoint returned HTTP 403 to our first request.** Per the ground
  rules we logged it and did not retry around it.

### Others (vendored for completeness; no wrappers)

| Chain | Mechanism | Store selection | Fields of note |
|---|---|---|---|
| ALDI | Instacart white-label `aldi.us/graphql`; needs `__Host-instacart_sid` cookie | `DefaultShop{postalCode}` | regular and sale both present in raw, merged by `min()` |
| Meijer | Constructor.io `ac.cnstrc.com/search` (public key) | silently falls back to store 130 | `data.ean` is a GTIN |
| Kroger family | official API `api-ce.kroger.com` (certification env, i.e. "test server") | `/locations` near lat/lon | `price.regular` / `price.promo`; UPC in raw |
| King Soopers | Instacart slug `king-soopers` | n/a | n/a |
| IGA (Australia) | `igashop.com.au` storefront API | n/a | n/a |

## 4. Raw field paths (VERIFIED on live responses, 2026-10-01 smoke test)

**Walmart search item** (`__NEXT_DATA__ … itemStacks[].items[]`):

| Field | Meaning |
|---|---|
| `usItemId` | product id; missing on `AdPlaceholder` tiles |
| `name` | product name |
| `priceInfo.priceDetails.priceLines[]` with lineType `CURRENT_PRICE`/`PRICE` | normal price |
| lineTypes `DISCOUNTED_PRICE`/`PRICE` + `COMPARISON`/`WAS_PRICE` | a markdown |
| lineType `UNIT_PRICE`/`UNIT_PRICE` | e.g. `"27.6 ¢/oz"` |
| lineType `SHIPPING`/`PRICE` | shipping charge |
| flat `priceInfo.linePrice`, `wasPrice`, `unitPrice` | **empty strings since ~2026-07** |
| `fulfillmentType` | `STORE` \| `FC` (fulfilment centre) \| `MARKETPLACE` (third-party seller) |
| `sellerName` | seller |
| `fulfillmentSummary[].storeId` | **may list several entries; the store id can appear only in a later one; `"0"` = not store-fulfilled** |
| `availabilityStatusV2.value` | e.g. `IN_STOCK` |
| `brand`, `upc` | `null` in search results |

In the smoke test, 93 of 150 results per store were marketplace listings, and only about 25%
of rows were priced at the scoped store.

**Target slp product:**

| Field | Meaning |
|---|---|
| `tcin` | product id |
| `item.product_description.title` | title |
| `item.primary_brand.name` | brand |
| `item.dpci` | Target's department/class/item code |
| `price.current_retail`, `price.reg_retail` | current and regular price |
| `price.formatted_current_price_type` | `reg` \| `sale` |
| `price.formatted_unit_price` + `formatted_unit_price_suffix` | e.g. `$0.29` + `/ounce` |
| `price.location_id` | the store the price is set at; **about 10% of products came back priced at location `3991`, not the requested store** |
| `promotions[].plp_message` | e.g. "Buy 2 for $9 breakfast cereal" |
| `fulfillment.store_options[0].store.mailing_address{address_line1, city, state, postal_code}` | **the searched store's real address** |
| `fulfillment.store_options[0].in_store_only.availability_status` | in-store availability |
| `fulfillment.store_options[0].order_pickup.availability_status` | pickup availability |

Notes:
- **No UPC in search.** The product page `https://www.target.com/p/-/A-{tcin}` embeds
  `"primary_barcode":"…"`.
- The top-level `page_context` is base64 that encodes **the requester's own approximate
  location** (derived from IP). Strip it from anything shared.
- Real store-level variation exists: 12 of 72 shared products differed in price between the
  Columbus OH (1058) and Vestal NY (1056) stores.

**Instacart (Costco) item:**

| Field | Meaning |
|---|---|
| `id` = `items_<retailerLocationId>-<n>` | item id; the prefix is the store |
| `name`, `brandName` (lowercase), `size` | descriptive fields |
| `productId`, `legacyId` | other ids |
| `price.viewSection.priceValueString` | current price |
| `price.viewSection.fullPriceString` | struck-through regular price; null when not on sale |
| `price.viewSection.badge.offerLabelString` | e.g. `"$6 off; limit 6"` |
| `price.viewSection.itemCard.pricingUnitString` | e.g. `"2 ct"` |
| `availability.{available, stockLevel}` | stock |
| UPC | not exposed |

Costco listings are usually multipacks, so they rarely match a national-brand UPC.

**Instacart shop** (`ShopCollectionScoped`): `id`, `retailerLocationId`, `serviceType`. No
address or coordinates.

## 5. Conflicts with the project spec

| Spec says | Code / live behaviour | What we do |
|---|---|---|
| Trader Joe's is a store-level control | One national web price; and the endpoint returned 403 on day 1 | Collect once per snapshot as a `national` pseudo-store when reachable; it cannot enter store-level analysis |
| Costco is a direct-from-retailer collector | Only via Instacart; no shop address | Treat as `source='instacart'`, analyse within chain only, coordinates = anchor ZIP centroid |
| Walmart and Target "browser-assisted cookies plus fast requests" | True for sessions; Walmart **store scoping** also needs one browser launch per store | Budget ~1 min per Walmart store per snapshot |
| Match items by UPC | Neither Walmart nor Target search returns UPCs | One product-page fetch per item per chain at resolution time (`collectors/resolve_items.py`) |
| Use Target's 1,893-store directory as the frame | Directory coordinates are slug geocodes, ~25% badly wrong; no ZIP or state | Real address comes back in every Target search response and replaces the frame location; frame strata must be rebuilt from true addresses before the final draw (see SAMPLING.md) |
| Walmart falls back to a default store | Yes, silently; detectable per item via `fulfillmentSummary.storeId` | `store_specific` computed per row |
| Promo vs. regular price is not kept | True upstream (`min()` merge); but raw responses carry both for Walmart, Target, Instacart | Parsers keep both; `is_promo` from regular > current |
| Kroger is "test server only" | Confirmed: `api-ce.kroger.com` | Excluded |
