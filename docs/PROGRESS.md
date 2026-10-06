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

## Target 64-query test (DECISIONS #47; owner-approved)

**Session 1 (2026-10-03, 21:07–21:19)**
- Ran on a fresh session made at run start.
- **50 successful requests**, then HTTP 435 at store 607: six failures in a row, so the
  circuit breaker tripped. One item (Prego) was lost.
- This was a refusal after successes, not a counted block. A **session-replace** followed
  after a 5-minute wait. The **fresh replacement worked**: the rest of the budget went
  through with no further refusal.
- **Total 63 successful queries out of 64.** No counted block (`blocks.json` unchanged);
  `mints.json` shows one run-start session and one replacement.
- **Reading:** the refusal came at about the same volume as before (about 47–115 requests
  per session), and a fresh session continued cleanly. This is consistent with the owner's
  hypothesis. One confound remains: the 5-minute wait alone might also have been enough.
  One event; sessions 2–3 follow.

## Module G: price timing (2026-10-04)
- **New:** `analysis/module_g_timing.py`, also wired into `run_all.py`. It uses Kroger's
  `price_effective` field from snapshot 2. No new collection.
- **Weekday:** 89% of promotional prices and 54% of regular prices start on a Wednesday.
- **Renewal-theory spell durations from ages:**
  - regular prices: mean about 32 days;
  - promotions: mean about 18 days;
  - age-tail Hill α about 2.3.
- **Zone co-dating:** 0.87 same zone vs 0.62 different zone (same banner, 906 pairs),
  p = 0.0003. It holds with the price held fixed (0.88 vs 0.72).
- The numbers will move slightly while the banner run adds stores to snapshot 2. Rerun after
  it finishes.

**Session 2 (2026-10-04, 00:28–00:40)**
- Ran on a fresh session made at run start. No pause was active (no `blocks.json`).
- **51 successful requests**, then HTTP 435 at anchor 12 (Target #2152, store_pk 624). Six
  failures in a row tripped the circuit breaker. One item was lost (Prego).
- This was a refusal after successes, not a counted block. A **session-replace** followed
  after the 5-minute wait. The **fresh replacement worked**: 12 more queries, no further
  refusal, then the planned budget stop at 64.
- **Total 63 successful queries out of 64** (anchors 1–12). No counted block
  (`blocks.json` still absent); `mints.json` shows one run-start session and one
  replacement.
- The vendored cookie loader logged a check of the Supabase pool and loaded 0 cookies.
  The production pool was not used.
- **Reading:** both sessions were refused after almost exactly the same number of
  successes (50 and 51). That looks like a fixed per-session request allowance at Target
  (about 50 requests) rather than random bad cookies. A fresh session continued cleanly
  both times. The 5-minute-wait confound is still there. Session 3 follows.

## Night of 2026-10-04: time hypotheses (owner: "plan 8 hours ... get started")
- **Kroger expiration times discovered.** Every promotion has a scheduled end; regular
  prices carry 9999-12-31. 9,326 promotions expire at the same instant nationwide:
  2026-10-07T03:59:59Z, which is **Tue Oct 6, 23:59 Eastern**. Earlier messages said
  "Tue Oct 7"; Oct 7 is the Wednesday.
- **Pre-registration** (`docs/PREREGISTRATION_EVENT.md`, committed af68714 at 01:38
  Eastern): predictions H1–H7, frozen zones, panel, probe list and Module H code. Module H
  is tested on synthetic data. Addendum 1 (about 02:10, uncommitted) adds the "cohort
  observed when it starts" length estimand.
- **Pipeline:** `scripts/run_kroger_event.ps1` (pid 44200) replaces `run_kroger_banners.ps1`
  (stopped while it was still waiting).
  - Banner sample until Mon 09:30.
  - Event passes: control Mon 10:00, before Tue 11:00, probes Tue 22:30 / Wed 00:15 /
    Wed 05:00, after Wed 10:00, late Thu 10:00.
  - The banner sample resumes after the late pass.
  - Log: `data/raw/logs/kroger_event.log`. DECISIONS #51.
- **Parser** keeps `price_expiration`. Snapshot-2 rows get it at the next reparse;
  Module G reads it from raw for now.
- **Module G extended:**
  - local time of day (2.5% of regular price starts between noon and 21:00 local);
  - same-minute zone test (0.14 vs 0.03, p = 0.0003);
  - promotion lengths: whole weeks, 80% ending on Tuesday;
  - three one-snapshot estimators of mean promotion length: ages 18.3, harmonic 12.7,
    Lynden-Bell 9.5 days;
  - stock levels;
  - figure `fig_g2`.
- **New simulation** `simulation/validate_promo_lengths.py`: the estimators agree under
  stationarity and split in the observed order when one cohort's length mix differs.
- **Module C** had finished its fits but crashed drawing figures (no colour for ALDI).
  Fixed `CHAIN_COLORS`, which now covers 6 chains and passes the palette validator. Figures
  rebuilt from the saved tables. Results are in the write-up: out-of-sample R² ≈ 0 for
  ALDI, 0.11 for Kroger, 0.19 for Costco.
- The write-up's timing section was rewritten, and Module C was added.
- **Not done (blocked by the permission classifier):** a commit of Module G, and deleting
  the empty stray file `data/grocery.db`, which a typo in a query created. Left for the
  owner.

**Session 3 (2026-10-04, 03:07–03:19)**
- Ran on a fresh session made at run start. No pause was active (no `blocks.json`).
- **51 successful requests**, then HTTP 435 at store_pk 639. Six failures in a row tripped
  the circuit breaker. One item was lost (Barilla).
- This was a refusal after successes, not a counted block. A **session-replace** followed
  after the 5-minute wait. The **fresh replacement worked**: 12 more queries, no further
  refusal, then the planned budget stop at 64.
- **Total 63 successful queries out of 64.** No counted block (`blocks.json` still
  absent); `mints.json` shows one run-start session and one replacement.

### Summary of the Target session tests (PRELIMINARY; one network, about 6 hours)

| Session | Gap | Successes before refusal | Replacement | Result |
|---|---|---|---|---|
| Oct 2 locate pass (old code) | 2 s | about 115 | none (stopped) | blocked; 12 h pause |
| Oct 2 resume (old code) | 5 s | about 47 | none (stopped) | stopped |
| Oct 3, 32-query budget | 5 s | none: 32 of 32 | not needed | clean |
| 64-query test, session 1 (Oct 3, 21:07) | 5 s | 50 | fresh, after 5 min: worked (13 queries) | 63 of 64 |
| 64-query test, session 2 (Oct 4, 00:28) | 5 s | 51 | fresh, after 5 min: worked (12 queries) | 63 of 64 |
| 64-query test, session 3 (Oct 4, 03:07) | 5 s | 51 | fresh, after 5 min: worked (12 queries) | 63 of 64 |

**Did refusals occur?** Yes. Every session that ran past about 50 requests was refused,
and the 32-query session stayed below that.

**Did a fresh session fix them?** Yes, 3 out of 3. Each replacement ran the rest of its
budget without a refusal.

**Counted blocks** (a fresh session refused on its first request): **zero** in all four
sessions under the current policy. `blocks.json` was never created. No pause was triggered.

**Reading.** The evidence supports the owner's hypothesis that a refusal after a run of
successes is tied to the *session*, not the IP, and a fresh session fixes it. The refusals
are not random "bad cookies", though: they arrive after **50, 51 and 51 successes**, at
three different times of day and at different stores. That points to a fixed allowance of
about 50 requests per Target session (at our 5 s gap), after which the session is
refused. The IP stayed in good standing throughout.

**Practical implication.** A Target run yields about 63 queries per run start plus one
replacement, with one item lost at the refusal. Retiring the session just before about
50 requests would avoid even that loss. That is a design change for the owner to decide;
we have not made it.

**Caveats:**
- n = 3 refusals, one network, one night.
- Every replacement came after the 5-minute wait, so a pause alone could also explain the
  rescue. This was not tested.
- Sessions were 2.5–3 h apart; shorter gaps were not tested.

**04:13 night check**
- **Snapshot-2 Kroger pass finished** (log ends with "Done.").
- **The banner steps had failed at 03:10.**
  - Store listing crashed after about 16 Locations calls on a single HTTP 500. The
    exception wasn't caught, and nothing was saved: progress was written every 25 cells.
  - The select step then failed (no store list), and the pipeline skipped the banner run.
    It was found waiting for Monday's control pass.
  - **Fix** (`scripts/kroger_banners.py`): each cell is retried with backoff
    (`with_backoff`), then logged and skipped if it still fails. Progress is saved every
    5 cells.
  - Pipeline restarted at 04:13 (pid 47108); listing is under way (904 cells, about
    2.3 h). The banner run follows until Mon 09:30, then the event schedule is unchanged.
  - Failed logs kept as `kroger_event_failed0310_*`. About 1 h of banner time was lost.
- `run_all.py` started detached at 04:15 (pid 21240; output in the scratchpad).
- **run_all (final snapshot 2), 04:18–05:16.**
  - The first attempt crashed in Module A: a bootstrap resample with tied top order
    statistics gave Hill gamma = 0. Fixed: alpha is undefined (NaN) for that resample,
    and the bootstrap drops it.
  - Second run: every module ran. Module F and Module H are waiting for panel data.
  - **Module B M2:** R-hat 1.007, no divergences, minimum bulk ESS 354 (below the 400
    target; consider more draws). M1 R-hat 1.028. M0 (reference) does not converge.
  - **Module B results:**
    - Kroger spatial share 0.99 (with 121 stores, its store effects are almost entirely
      regional; banner territories);
    - length-scale about 93 km;
    - nu ≈ 3.5;
    - Module B's chain term is omitted: only 2 UPCs are matched across chains inside
      Module B.
  - **Module E, Kroger:** 121 stores, 21 zones, 94% banner purity; within 100 km, 11%
    differ within a banner vs 77% across banners; variogram range about 240 km.
  - **Module D:** 88 locations, saving 0.05%.
  - **Target law-of-one-price gap** now +0.5% (16 stores; it was +3.2% at 4 stores).
  - The write-up and STUDY_PLAN numbers are updated.
- **Commit:** not attempted again. The permission classifier denied the last two commits
  tonight; tables, figures, paper and docs are left for the owner to commit.

**07:47 morning check (Kroger event pipeline, pid 47108)**
- **Store listing finished at 06:41:** 904 grid cells, none skipped.
- **Selection:** 271 stores across 21 banners, 121 already priced in snapshot 2. New
  banners include Bakers, City Market, Dillons, Gerbes, Jay C, Metro Market, Pay Less,
  Pick 'n Save, QFC and Ruler.
- **Banner run started at 06:41.** By 07:47, 5 new stores were priced (2,958 rows), for
  127 Kroger stores in snapshot 2.
- **Pacing:** median gap 10.4 s, minimum 9.9 s (≥ 9 s holds). No 401/403/429 responses
  and no blocks.
- **Expected finish:** about 150 new stores at about 10 min each is about 25 h, just
  before the Mon 09:30 hard stop. The run resumes after the event if it is cut.
- **Vitacost removed.** The selection included 2 "VITACOST" locations, which are Vitacost
  fulfilment warehouses (online only, not stores).
  - Removed from `config/kroger_banner_sample.csv`, and "vitacost" added to `NON_STORE`
    in `scripts/kroger_banners.py`.
  - The running process loaded the old list. Vitacost comes last alphabetically, so it
    is unlikely to be reached before the stop. If it is, add those store_pks to
    `config/excluded_stores.csv`.
- **run_all (04:18–05:16)** finished; it was reviewed and the write-up updated at the
  04:13 check (see above).

**Afternoon of 2026-10-04 ("keep working")**
- **Write-up restructured to fit 5–6 pages.** The main text is 2,738 words with 5
  figures and 3 tables. Data checks and method details moved to appendices. The previous
  version is backed up in the session scratchpad.
  - New framing: space *and* time. Results are split into §4 Space and §5 Time, and §5.4
    covers the pre-registered event.
  - Figures:
    1. variogram, now chains with ≥ 30 stores only;
    2. ALDI zones;
    3. **new** `fig_e4_kroger_banners_zones` (stores by banner, and banner × zone
       counts; almost block-diagonal);
    4. Module B spatial field;
    5. timing and promotion-length estimators.
- **Module E** draws the Kroger banner/zone figure (`kroger_banner_figure`) and uses real
  banner names (Harris Teeter, Pick 'n Save, ...).
- **Module B:** the colour bar no longer overlaps the title. Draws and tune are
  configurable (`GS_MODB_DRAWS`, `GS_MODB_TUNE`). A 2,000-draw / 1,500-tune rerun started
  15:23 (pid 16996) to reach ESS ≥ 400. The write-up has an [update] for its ESS, and the
  figure is redrawn from that run.
- **README** updated for Modules F–H, the event pipeline and the promotion-length
  simulation.
- **Kroger banner run:** sample row 53/271 at 15:27, no 401/403/429. On pace to finish
  before the Mon 09:30 stop.
- **Module B rerun** (2,000 draws, 1,500 tune; 15:27–15:39).
  - M2: R-hat 1.005, minimum bulk ESS 877, no divergences, so the ESS target is met.
  - It used **160 Kroger stores**, because the banner run is adding stores to snapshot 2.
  - Results: Kroger spatial share 0.996; Walmart 0.51 (0.35–0.68); length-scale about
    92 km; nu ≈ 2.2; Kroger mean departure +3.0%.
  - LOO now slightly favours M1 (30 ± 22), still not decisive.
  - The write-up states n per result and says all Kroger numbers are rerun after the
    banner sample. The figure has no overlap.
- **Kroger zone robustness** (split-half and prior) rerunning on the current Kroger set
  (pid 4340; output in the scratchpad).
- `docs/LIMITATIONS.md` updated: Kroger and Target entries corrected; timing, promotion
  length and frozen-zone caveats added.
- **Kroger zone robustness on 160 stores** (15:42):
  - split-half ARI 0.98 and 0.83 (mean 0.91);
  - prior: gamma 0.5 vs 1 gives ARI 0.92 (28 vs 25 zones); gamma 5 merges to 14;
  - start agreement 0.96–0.97.
  - Tables `zone_sensitivity_*_kroger.csv` and the combined files are updated; the
    write-up is updated.

**Evening of 2026-10-04 (owner: "I approve keep working")**
- **Meijer:**
  - The locator **blocked after 8 calls** at 12 s (Michigan listed: 122 locations).
    Stopped; no further locator use.
  - 80 stores selected, pricing run started 23:18 (pid 45732; log
    `data/raw/logs/meijer_sample_run.log`), about 2.6 h.
- **Walmart panel:**
  - 10 stores × 17 items; visits 08:00/14:00/20:00 ET, Mon–Thu (11 visits);
    scheduler pid 43912; log `data/raw/logs/walmart_panel.log`.
  - The smoke test passed (snapshot 3): store-specific rows carry slot, stock and
    demand fields.
  - The machine is now on the Purdue network (128.211.x).
- DECISIONS #52.

**Mon 2026-10-05, 09:43 check**
- **Laptop in Modern Standby, network disconnected, 01:36 to 09:34** (Kernel-Power
  events 506/507, "Adaptive Connected Standby"). Every background job froze for about 8 h.
  - **Kroger banner run:** stalled at sample row 116/271, then hard-stopped at 09:34 (09:30
    deadline). **192 Kroger stores** in snapshot 2 (121 before the banner sample). It
    resumes after the event. No Vitacost rows.
  - **Kroger control pass:** waiting for 10:00 (pipeline alive).
  - **Meijer sample:** at store 53/80 (55 Meijer stores, 64,335 store-specific rows, no
    blocks; failures are items not carried). Still running; the Meijer analysis waits
    for it to finish.
  - **Walmart panel:** the 08:00 visit started only at 09:34. Its 09:45 hard stop cuts it
    to the first store or two (snapshot 4, a partial visit). The 14:00 visit follows the
    schedule.
- **Risk for the event:** the probes on Tue 22:30 and Wed 00:15 Eastern need the laptop
  awake and online. **Owner action:** keep it plugged in, and set "sleep when plugged in"
  to Never (or `powercfg /change standby-timeout-ac 0`) until Thu Oct 8.

**Mon 2026-10-05, 16:50 check**
- **Control pass failed at 10:00:** Start-Process split the multi-word `--note`. Fixed in
  `scripts/kroger_panel.py` (`--note` takes several words). Rerun started 16:51
  (snapshot 6, pid 41136, hard stop Tue 10:45). Rows carry `price_effective` and
  `price_expiration`. Pre-registration Addendum 3.
- **Walmart panel:**
  - The 08:00 visit (snapshot 4) was partial: 4 stores, 903 store-specific rows, all
    with slot fields, no failures.
  - The 14:00 visit finished 15:53 (late, so probably standby again). The 20:00 visit
    is waiting.
- **Meijer:** store 69/80 at 16:49 (slowed by standby).
- The laptop's standby is the main risk to the event schedule.
- **Walmart panel 14:00 visit (snapshot 5):** 7 stores (1,366 store-specific rows), then a
  px-captcha after 105 successful requests. Logged as "STOPPED for this run (not a
  block)", with a 1 h rest under the policy. Like Target's per-session allowance, each
  visit reliably covers the first 6–7 stores in the fixed order; those form the effective
  panel.
- **Module I, first real run** (visits 4 and 5; PRELIMINARY):
  - 0 of 707 store-products changed price between the morning and afternoon visits
    (4 stores);
  - departures from the list price persisted (p_stay_off = 1, 694 transitions);
  - fixed the slot-lead variance decomposition (pooled within-store variance, stores
    seen ≥ 2 times; it was giving negative shares).
- **Meijer sample finished (about 16:50).**
  - 83 Meijer stores in snapshot 2 (71 pass the analysis filters); no blocks.
  - 97% of prices at list; variogram nugget 0.1%, sill 4.9%, range about 44 km.
  - Zones: 7, weakly coherent (24% vs 21%).
  - Sale ends: 99.7% of store pairs end the same date (one sale calendar). 83% of sales
    end on a Tuesday, and 6,953 store-products end on Oct 6–7, the same night as the
    Kroger expiry.
  - Added to the write-up's §4, §5 and abstract.
  - The Module E/G rerun also refit Kroger on 191 stores (banner sample partial). The
    write-up's Kroger figures stay at 121/160 until the final rerun after the banner
    sample.

**Mon 2026-10-05 evening, reproducibility:** `simulation.validate_tail_estimators`,
`validate_promo_lengths` and `validate_zone_model` were rerun from scratch. All three
reproduce the committed `tables/simulation_*.csv` exactly (no content diff). The Module B
simulation was not rerun because it is slow.
- The Module B simulation (`simulation.validate_module_b`) was also rerun (19:40–19:48). It
  reproduces `tables/simulation_module_b.csv` exactly (no content diff). Every simulation
  table now reproduces from scratch.
- **Walmart 20:00 visit (snapshot 8):** all 10 stores, no captcha. Module I after 3
  visits:
  - 0/1,844 intraday price changes (7 stores);
  - departures persist (1,804 transitions);
  - slot lead time is driven by time of day (evening 10–17 h), not by store.

  Added to the write-up §5.5.
- **Meijer control pass (snapshot 7)** finished at 20:11: 15 stores, 16,677 store-products,
  no blocks. 1,020 store-products have a sale ending 2026-10-06; these become "scheduled"
  units if still on sale in the Tue 18:00 before pass.
- **Kroger control pass check (20:26).** The 10:01 "control pass : finished" log line is
  the failed run; the rerun is **snapshot 6**, at 15/60 stores, about 14 min per store,
  expected to finish about 07:15 Tue (hard stop 10:45).
  - All 8,954 rows so far carry `price_effective` and `price_expiration`; no parser
    issue.
  - 8,871 store-products; **935 scheduled units** (promos expiring
    2026-10-07T03:59:59Z) of 1,704 promos.
  - `config/analysis.yaml`: `event_snapshots: {control: 6}`.

**Mon 2026-10-05, 23:43 night check**
- **Kroger control rerun (snapshot 6):** 30/60 stores (about 13 min per store, so about
  06:15 Tue, before the 10:45 stop). Pacing median 10.5 s, minimum 9.8 s (≥ 9 s holds).
  No 401/403/429 or blocks.
- **Meijer control (snapshot 7):** finished 20:11 (15 stores, 16,677 store-products, no
  blocks). Waiting for Tue 18:00.
- **Walmart:** the 20:00 visit (snapshot 8) reached all 10 stores; Module I updated. Next
  visit Tue 08:00.
- **Keep-awake** is running (pid 21456). The only standby since evening was 19:08–19:15,
  before the keep-awake started at 19:16. None since.
- Nothing broken; no changes.

**Tue 2026-10-06, 00:30–01:30 (owner: "8 hours uninterrupted")**
- **Push order follows store number:** Spearman ρ between a store's mean position in a
  zone update and its store number is 1 in 13 of 21 zones (≥ 0.95 in 16; mean 0.92).
  Location explains little.
- **Update batches** (same effective minute):
  - top 1% of batches hold 24% of prices, top 10% hold 66%;
  - Hill α 1.7 / 1.39 / 1.16 at k = 2 / 5 / 10%: heavy tail, not a clean power law.
- **Zones follow Kroger's operating divisions** (location-id prefix) more closely than
  banners. At 191 stores: purity 95% vs 89%, ARI 0.71 vs 0.51, zones inside one division
  89% vs inside one banner 82%. Food 4 Less with Foods Co, and Dillons with Baker's and
  Gerbes, share zones.
  - Module E's banner check now reports divisions.
  - Posterior co-clustering figure (`fig_e5`): 0.1% of pairs uncertain.
- **Within the same division:** same date 0.92 vs 0.87 (zone vs not), same minute 0.28 vs
  0.16 (p = 0.0005). Division sets the day; zone sets the batch.
- Tests added for push order and batch sizes; all pass.
- **Dyadic model validated** (`simulation/validate_dyadic_model.py`, 10 replicates per
  scenario, about 420 pairs each).
  - True b_zone 0: estimate −0.01, 90% coverage 0.8. The naive within/across difference
    shows a spurious +0.09 from distance.
  - True b_zone 0.5: estimate 0.52, coverage 0.9.
  - b_dist coverage 0.9.
  - Table `simulation_dyadic_model.csv`.
- **Write-up:** §5 rebuilt on 191 Kroger stores (one table for the zone-timing tests),
  plus tighter Data and Methods. Main text 3,320 words; the final cut comes after the
  event results.
- **Effective-date resets measured** (snapshot 2 vs control, 35 stores, 19,373 units).
  - 6.5% of records got a new effective date in 1–3 days, 93.5% of them with an
    identical price: re-entries. Regular 7.8% vs promo 0.3%.
  - Store-level batches (one minute per store); 58% are in multi-store zone batches.
  - Write-up reworded: timestamps describe update batches; regular "ages" are record
    ages (spells are longer); promotions are rarely affected.
  - Pre-registration Addendum 7: the H tests are unchanged, and Module H also reports
    reset rates per transition.
- **Zone co-timing holds for promotions** (real price changes; rarely reset). Same-banner
  pairs: same day 0.98 vs 0.92, same minute 0.17 vs 0.04 (p = 0.001). Regular: 0.88 vs
  0.64 and 0.27 vs 0.07. Zones push real promotion changes in the same batch. Added to
  Module G and the §5.2 table.
- Module G ran end-to-end (191 stores, about 8 min, no errors). Figures and captions now
  say "price records". All 85 tests pass.

**Tue 2026-10-06, 02:47 night check 2**
- **Kroger control rerun (snapshot 6):** 43/60, no 401/403/429, pacing median 10.4 s
  (minimum 9.8 s), about 13 min per store, so it should finish about 06:30 (hard stop
  10:45).
- All schedulers alive: Kroger event pipeline (47108, waiting for the 11:00 before pass),
  control rerun (41136), Walmart (43912, next 08:00), Meijer (39336, next 18:00),
  keep-awake (21456).
- No standby events since 19:15 Mon.

## End-of-night summary (Tue 2026-10-06, 05:43)

**Jobs**

| Job | Status |
|---|---|
| Kroger control rerun (snapshot 6) | 57/60 stores, no 401/403/429, pacing ≥ 9.8 s; finishes about 06:25 (hard stop 10:45) |
| Kroger event pipeline (pid 47108) | waiting for the before pass at Tue 11:00 |
| Meijer event scheduler (39336) | control done (snapshot 7); before Tue 18:00, after Wed 12:00 |
| Walmart panel (43912) | 3 visits Mon; next Tue 08:00 |
| Keep-awake (21456) | on until Oct 8 15:00; no standby since Mon 19:15 |

**Failures and fixes (Mon–Tue)**
- **Control pass failed at 10:00:** Start-Process split the multi-word `--note`. Fixed
  (`--note` takes several words); rerun as snapshot 6 (Addendum 3). Later passes use the
  fix.
- **Modern Standby froze every job** Mon 01:36–09:34. Fixed with the keep-awake helper.
- **Meijer locator blocked** after 8 calls; stopped, and it is not used.
- Walmart visits stop after about 105 requests (captcha, "not a block"), so the effective
  panel is 6–7 stores.
- **Bugs fixed:** Module I variance decomposition; zone-sensitivity partial reruns; the
  dyadic model's identifiability; text that the shell's newline escaping had mangled.

**Results that changed overnight**
- **Effective timestamps mark price records.** 7.8% of regular-price records (0.3% of
  promotions) re-entered with an identical price within 1–3 days. Write-up reworded;
  Addendum 7.
- **Zone co-timing holds for promotions** (real changes): same minute 0.17 vs 0.04.
- **Zones follow Kroger's operating divisions** (purity 95%, ARI 0.71 vs banner 0.51).
  Division sets the day; zone sets the batch.
- **Each zone batch walks its store list in store-number order** (ρ = 1 in 13/21 zones).
- **Dyadic hierarchical model:** zone odds ratio 1.59 (day) and 1.75 (minute) beyond
  distance and store; simulation-validated.
- **Meijer:** near-uniform list (97% at list), zones do not replicate, one sale calendar
  ending the same night as Kroger's.
- **Walmart panel day 1:** 0/1,844 intraday price changes; lead time follows the clock.
- **Kroger at 191 stores:** 65% at list, no variogram plateau (local zones within a
  nationwide gradient).
- **Update batches:** heavy-tailed sizes. Every simulation table reproduces exactly.

**Next (scheduled; no owner action needed unless something fails)**
- Tue 08:00 Walmart visit (first overnight comparison); check at 08:53.
- **Tue 11:00 Kroger before pass** (hard stop 22:15; about 45 of 60 stores expected).
- **Tue 18:00 Meijer before.**
- **Kroger probes Tue 22:30, Wed 00:15, Wed 05:00** around the 23:59 Eastern expiry.
- Wed 10:00 Kroger after; Wed 12:00 Meijer after; Thu 10:00 Kroger late. Then the banner
  sample resumes.
- **Thu after the late pass:** run Module H (and I), then `scripts/final_rerun.ps1`
  (run_all plus Kroger/Meijer zone robustness on the full Kroger sample), and cut the
  write-up to 5–6 pages with the event results.

**Owner**
- Keep the laptop plugged in, lid open, on the network until Thu.
- Commit your session-policy files when you create the public repo.
- Decide whether the write-up goes out before or after the event results (Thu).
