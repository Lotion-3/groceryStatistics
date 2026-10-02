# Design decisions

Wherever the spec left a choice open, the simplest defensible option was taken. Each one is
recorded here with its reason.

| # | Date | Decision | Why |
|---|---|---|---|
| 1 | 2026-10-01 | Vendor (copy) the basketBuddy collectors unchanged into `collectors/vendor/`, with SHA-256 sums | Self-contained and reproducible; the research data provably comes from the same code as the app. Owner's choice |
| 2 | 2026-10-01 | Replace `session_store.py` with a no-op stub; do not copy `db.py` | The original reads and writes the production Supabase project. This project must never touch it |
| 3 | 2026-10-01 | Do not copy any session or cookie file; sessions are re-minted locally into gitignored files | Live auth cookies are secrets. Owner's choice |
| 4 | 2026-10-01 | Local SQLite (`data/grocery.sqlite`) with portable SQL | No need for a server; spec allows it; keeps production untouched |
| 5 | 2026-10-01 | Extra columns beyond the spec: `observations.chain_product_id`, `search_rank`, `priced_store_id`, `source`, `extra` (JSON); `stores.ruca`, `anchor_zip`, `coord_quality`, `address`; `items.search_term`, `walmart_id`, `target_tcin`, `costco_ic_id`, `tj_sku`; `collection_failures.raw_path` | Needed to identify products without UPCs, to audit store specificity and coordinates, and to keep chain-specific promo text without inventing columns per chain |
| 6 | 2026-10-01 | Wrappers bypass `price_all_*` and `find_best_purchase` and call the low-level fetch functions | Those functions reduce results to the single cheapest product and merge promo with regular price |
| 7 | 2026-10-01 | Pacing: 1 request at a time per domain, ≥ 2 s + jitter between requests, 2 retries with exponential backoff on transport errors only, **stop the chain for the run on the first WAF block** | Spec ground rule 2 and "do not escalate". The upstream code rotates proxies and IPs on blocks; we never do |
| 8 | 2026-10-01 | Walmart and Costco stores are anchored to the sampled Target stores' ZIPs | No Walmart or Costco directory exists; building one would add traffic. Pairing also helps the cross-chain comparison |
| 9 | 2026-10-01 | Costco location id = Instacart `retailerLocationId`; coordinates = anchor ZIP centroid | Instacart returns no address; the item ids carry the location id, so store specificity can be checked per row |
| 10 | 2026-10-01 | Never use the vendored Costco "expanding metro" fallback | It substitutes a different city's warehouse |
| 11 | 2026-10-01 | Store specificity per row: Target `price.location_id == store`; Walmart any `fulfillmentSummary.storeId == scoped store`; Costco item location prefix == shop location; Trader Joe's never | These are the retailers' own statements of where a price applies (verified live). Target prices about 10% of items at location 3991; Walmart returns many marketplace and fulfilment-centre listings |
| 12 | 2026-10-01 | `is_promo = 1` iff the retailer reports a regular or "was" price strictly above the current price; multi-buy deals and clip coupons stay in `extra` and do not change `price` | Spec rule; multi-buy prices are conditional on quantity, so they are not a shelf price |
| 13 | 2026-10-01 | Every returned product is stored against the item query that returned it; which product "is" the item is decided at analysis time via owner-confirmed ids and UPCs | Keeps the raw evidence; matching can be redone |
| 14 | 2026-10-01 | UPCs come only from retailer product pages (`resolve_items.py`); never typed in by hand. Candidates are ranked by a transparent heuristic and **reviewed by the owner** | Spec "never fabricate"; the heuristic got Cheerios wrong (different size) in the smoke test |
| 15 | 2026-10-01 | `items.csv`: `cross_chain = 1` means *intended* cross-chain; actual matching requires equal UPCs at both chains | UPCs are unknown until resolution |
| 16 | 2026-10-01 | Urbanicity from the 2020 ZIP-level RUCA primary code: 1 urban, 2–3 suburban, 4–10 rural | Standard public classification, available for every ZIP, with no extra data pulls |
| 17 | 2026-10-01 | Target frame locations come from the store address Target reports (locate pass); the slug geocodes are used only as a provisional fallback | The slug geocodes are wrong for ~25% of stores |
| 18 | 2026-10-01 | Walmart coordinates from OpenStreetMap features whose `ref` is the store number | Verified on both smoke-test stores; ~3,900 Walmart features carry `ref` |
| 19 | 2026-10-01 | Hill estimator: report k = 5% of n as primary, with the stability-rule k (on k ≤ 15% n) and k = 10% as sensitivity | Simulation: on \|t₃\| data the stability rule over-reaches into the body (95% CI coverage 0.22–0.78) while k = 5% covers 0.84–0.92; all are fine on exact Pareto data |
| 20 | 2026-10-01 | GPD threshold at the 90% quantile of \|d\|, reported on the shape scale ξ | Comparable across chains; ξ ≤ 0 (no power tail) is possible and must not be forced into an α |
| 21 | 2026-10-01 | The database can be rebuilt entirely from `data/raw/` (`collectors/reparse.py`); failures are mirrored to `data/raw/snapN/_failures.jsonl` | Spec: "parsing can be redone"; reproducibility from raw data |
| 22 | 2026-10-01 | The smoke-test failure row for Trader Joe's was restored by hand into `_failures.jsonl` (marked as such) after the DB was rebuilt during a schema change | The event happened and was seen in the console; missingness is data |
| 23 | 2026-10-01 | Python venv lives outside OneDrive (`C:\Users\laksh\.venvs\groceryStatistics`) | Avoids OneDrive syncing tens of thousands of package files |
