# Progress log

## Day 1: 2026-10-01

**Done**
- Read basketBuddy and wrote `docs/REPO_NOTES.md`. Vendored the collectors with checksums,
  stubbed out Supabase, copied no secrets.
- Wrote the schema and SQLite DB, and `config/items.csv` (52 packaged national-brand items
  and 6 perishables, UPCs blank until resolved).
- Built the sampling frame and a provisional seeded sample of 250 Target stores, using the
  Census ZCTA gazetteer and USDA RUCA files. Downloaded OSM store layers for all four
  chains.
- Wrote wrappers for Walmart, Target, Costco (Instacart) and Trader Joe's. They keep every
  product plus the raw response, pace requests, and stop on a block.
- Ran the tiny live smoke test (owner-approved): 2 anchor ZIPs (Columbus OH, Binghamton NY)
  × 3 items. Results per chain:

  | Chain | Products per query | Rows tied to the store | Notes |
  |---|---|---|---|
  | Target | 24 | 90% | Prices differ between the two stores for 12 of 72 shared products |
  | Walmart | ~50 | ~25% | The rest are marketplace and fulfilment-centre listings |
  | Costco (Instacart) | 20 | 100% | |
  | Trader Joe's | — | — | HTTP 403. Logged, not retried |

- Resolved UPCs for the 3 test items with 6 product-page fetches. Barilla spaghetti and the
  Coke 12-pack match across Walmart and Target. For Cheerios, Walmart's top candidate was
  a different size, so it is flagged for review.
- Wrote parsers verified against the live responses, a reparse tool that rebuilds the DB
  from raw data, and 39 passing tests (parsers, DB sanity, estimators).
- Ran the tail-estimator simulation, which changed the Hill k choice (DECISIONS #19).

**Found**
- Basketbuddy's Target directory coordinates are wrong for ~25% of stores. Fix: the locate
  pass, plus overwriting each store's location during collection.

**Blocked / needs owner**
1. Approve the **Target locate pass**: about 1,900 requests, 1–1.5 h. After it, re-run
   `build_frame` to redraw the sample.
2. Approve **full item resolution**: about 52 items × 2 chains ≈ 110 product pages, plus
   1–2 searches per item at one store if not already on disk. Then review
   `config/items_resolved.csv` and copy the confirmed `walmart_id` / `target_tcin` / `upc`
   values into `config/items.csv`.
3. Decide on **Trader Joe's**: drop it, or retry once on another day. It only gives a
   national price in any case.
4. Approve **snapshot 1**. Estimated time:

   | Chain | Requests | Time |
   |---|---|---|
   | Target | 250 × 58 ≈ 14,500 | ~8 h at 2 s |
   | Walmart | 250 browser scopes + 14,500 searches | longer still |
   | Costco | fewer (dedup by warehouse) | n/a |

   This is more than "a few hours". Choose among: run the chains in parallel (separate
   domains, each still at ≤ 1 req / 2 s), reduce items to ~40, reduce stores to ~150 per
   chain, or accept a longer window.

**Next**
- After approvals: locate pass, redraw, item resolution and review, then snapshot 1 in the
  background with logging. Then a coverage and missingness report, and Module A.

## Day 2: 2026-10-01/02 (evening)

**Owner decisions:** approve the locate pass and item resolution; snapshot 1 at full scope
(250 × 58) with chains in parallel; drop Trader Joe's; swap 15 grocery items for
non-grocery national brands; after the Target block, pause and resume at ≥ 5 s
(DECISIONS #24–28).

**Done**
- Parallel snapshot runner: SQLite WAL + busy timeout, `--new-snapshot-only`, `ended_at`
  only moves forward, `scripts/run_snapshot_parallel.{ps1,sh}`. Tested with concurrent
  writers.
- **Circuit breaker** in the pacer (6 consecutive failures to one domain → chain stops)
  and a per-domain pace (Target ≥ 5 s). Tested.
- Item-resolution searches at one store (Columbus OH, in snapshot 1). Costco: all 58
  items, no failures. Walmart: 55 items, then a px-captcha stopped it automatically
  (3 left). Walmart is now also paced at ≥ 5 s (#29).
- `config/items.csv`: 15 grocery items replaced by household, personal care, OTC, baby
  and pet items (still 58).
- `analysis/coverage.py` (first step of `run_all.py`), `config/analysis.yaml`
  (main-snapshot list).
- Module A implemented in full (tails by chain, category and department; promo
  sensitivity; cross-chain; store-cluster bootstrap CIs; join-count and Moran's I; basket
  VaR/ES; 4 figures). Checked end to end on the smoke snapshot with lowered thresholds;
  the outputs are not kept.
- `sampling/fetch_external.py` can fetch ACS 2023 5-year by ZCTA, but it needs
  `CENSUS_API_KEY`.

**Blocked**
- **Target soft block (HTTP 435)** after ~115 locate-pass requests at 2 s. Stopped after
  10 refused requests. Locate pass is at 115 / 1,893. Resume is scheduled for ~04:13
  local, in this order: Target resolution searches → product-page UPCs → locate pass.
- **Census API key** needed for the Module C covariates (free; put it in `.env` as
  `CENSUS_API_KEY`).

**Next**
- Owner review of `config/items_resolved.csv`, then copy the confirmed IDs into
  `items.csv`.
- Locate pass → redraw the sample → snapshot 1 (Target at 5 s ≈ 20 h for 250 stores; may
  need ~150 stores).
