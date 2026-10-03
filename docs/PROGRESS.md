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

## Night of Day 2 → Day 3 (2026-10-02, owner asleep)

**Done**
- **Census key works.** ACS 2023 5-year data for 33,772 ZCTAs downloaded.
  `fetch_external` now reads `.env` itself.
- **Kroger.** The official-API wrapper and parser are written and tested (UPC conversion
  verified against Target), and `--chains kroger` is wired in as an optional chain. The
  supplied credentials work only on the certification host (production returns 401).
  That catalog is a small test subset: **only 10 of 58 items** get a good priced match,
  even with short search terms. So Kroger is **off by default** (DECISIONS #30); production
  keys would enable it.
- **Module C** (shrinkage and factor model) implemented and unit-tested. The regularised
  horseshoe converges (0 divergences after raising `target_accept`).
- **Module B** (hierarchical spatial model) implemented and validated on simulated data
  (`simulation/validate_module_b.py`). The first version had an unidentified direction
  (R-hat 1.11); fixed (#32). All three models now converge.
- **Module D** (basket optimisation, MILP vs greedy) implemented and tested against brute
  force.
- The store sample is now written in a seeded random visit order (#31). Without it, a
  blocked run would have covered whole regions only.
- Installed NumPyro/JAX (PyMC sampler) and HiGHS (MILP solver), and added both to
  `requirements.txt` (#33).

**Scheduled / in progress**
- 04:13: resume Target and Walmart at 5 s per request (resolution searches → product-page
  UPCs → locate pass), stopping at the first block.
- **04:13 resume.**
  - Target probe (3 items) clean. Then Target 435 again after ~47 searches at 5 s; the
    circuit breaker stopped it after 6 failed attempts. Target is stopped for now.
  - Walmart finished its 3 remaining items.
  - `resolve_items` with Walmart product pages: UPCs for all 58 Walmart candidates, but
    many top picks are the wrong variant (see the summary in chat). Target has candidates
    for 53 items but **no UPCs** (its product pages are blocked).
  - Locate pass **skipped**. Sample redrawn: 14 stores at true addresses, 236 at checked
    directory coordinates (the approved fallback).
  - **Snapshot 2 started at 04:26 for Walmart + Costco** (`config/analysis.yaml` →
    `main_snapshots: [2]`). Target is pending.

**Needs the owner (morning)**
1. **Target scope.** It blocks after ~50–115 requests, so 250 × 58 (~14,500) is not
   feasible. Options: drop Target from snapshot 2 and keep it Walmart vs Costco; a small
   Target panel (e.g. 40 stores × 20 items ≈ 800 requests, spread over several days in
   short sessions); or wait days and re-test.
2. **Review `config/items_resolved.csv`** (and `item_candidates.csv`), then copy the
   confirmed `walmart_id` / `target_tcin` / `upc` into `config/items.csv`.
3. Kroger production keys, if you want Kroger.
- **~09:00: chains added to snapshot 2** (owner request).
  - ALDI and Meijer wrappers written, probed (2 stores × 2–3 items each) and tested.
  - Kroger: re-checked by exact UPC (19/58 in the catalog); added for its 25 carried
    items.
  - All three running alongside Walmart and Costco: `data/raw/logs/snap2_{aldi,meijer,kroger}.log`.

## Day 3 (2026-10-02, evening)

**Snapshot 2 status at 20:17**
- Walmart: **42 stores** (2,425 searches), then a px-captcha; stopped automatically.
- Meijer: 3 stores × 58 items, then its store locator returned a block page; stopped
  automatically.
- Costco: 86 of 250 anchors and running. ALDI: 21 anchors and running. Kroger: 73 anchors
  and running; 216 "empty" responses are items its test catalog lacks at that store.
- No chain has been retried after a block.

**Partial-data check** (outputs in the scratchpad only, not reported)
- Two bugs found and fixed:
  - Instacart product ids embed the store, so Costco/ALDI products never matched across
    stores.
  - Baskets with fewer than 5 items are now skipped.
- Walmart's extreme deviations are a real Honolulu premium (milk $6.28 vs a median of
  $2.97), so Module A now also reports tails without HI and AK.
- Early signal, to examine later: Costco via Instacart is *not* near-uniform (73% of prices
  at the chain median vs Walmart's 89%), which may mean location-varying markups.

**Item review aid:** `python -m scripts.item_review_sheet` → `config/item_review.csv`. It
compares Walmart's pick with a UPC proposed independently from Meijer/Kroger search results
(store brands excluded), flags agreement, and leaves `confirmed_*` columns for the owner.

## Day 3–4 (2026-10-03)

**Collection**
- Costco and ALDI: **finished**, all 250 anchors, no blocks (Costco 174 warehouses, ALDI 205
  stores).
- Kroger production API: running, 84+ stores so far, no blocks.
- Target: budgeted sessions (32 queries) on the new session code. The first session was
  clean (one fresh session, no refusals). More sessions are scheduled tonight.
- Walmart: 41 stores. Meijer: 3.

**Analysis**
- **Module E (pricing architecture):** point mass, price-list variogram, H0 persistence,
  an exploratory urban/rural test.
- **Dirichlet-process zone model** (`analysis/zone_model.py`): collapsed Gibbs plus
  merge–split. It was validated on simulation only after three fixes, each found by the
  check: an empirical-Bayes base measure, store-unique levels set aside, and merge–split
  moves.
- **Results (preliminary):**
  - ALDI: 10 zones, with one national zone of 79 stores in 27 states.
  - Walmart: 5 zones.
  - Costco: 18 regional zones.
  - Kroger: 17 zones, and **94% of stores sit in a zone dominated by their own banner**,
    although the model is never given banners.
- **Write-up restructured** around pricing architecture (`paper/writeup.md`); the plan is
  in `docs/STUDY_PLAN.md`.

**Pending**
- The session-replacement code (DECISIONS #47) is in the working tree but uncommitted. The
  owner will commit it when the public repo is created.
- A Target test with budget 64 needs the owner's go-ahead.
- Item review, for the cross-chain panel.
