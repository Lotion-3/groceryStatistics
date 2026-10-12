# How Retailers Price Across Space and Time

For identical products (matched by UPC), how does a chain's price vary across its stores,
and how is its price list organised across space: one national list, discrete pricing
zones, or a continuous gradient? Where do departures from the list occur, and how extreme
are they? And when do prices change: do stores in the same zone change prices together?

**Status:** preliminary. One cross-section (snapshot 2, October 2026) covering ALDI,
Costco (Instacart), Kroger (official API), Walmart, and partly Target and Meijer. Write-up:
`paper/writeup.md`. Pre-registered event study (Kroger promotion expiry, Oct 6, 2026):
`docs/PREREGISTRATION_EVENT.md`. Plan and first results: `docs/STUDY_PLAN.md`. Day-by-day log:
`docs/PROGRESS.md`. Every design choice: `docs/DECISIONS.md`.

## Key findings (preliminary; full write-up in [`paper/writeup.md`](paper/writeup.md))

- **Prices are a point mass plus structured departures.** 91% of prices at ALDI and
  Walmart, and 65% at Kroger, sit exactly at the chain's list price.
- **Four pricing architectures,** recovered from prices alone by a Dirichlet-process zone
  model, a price-list variogram and a two-part Bayesian spatial model:
  - ALDI: a national list with regional zones.
  - Walmart: a slow gradient.
  - Costco (Instacart): regional zones.
  - Kroger: local zones nested in its operating divisions (95% purity; split-half ARI
    0.90–0.98).
- **Timestamps independently confirm the zones.** Same-zone Kroger stores start a price
  record in the same minute 4× as often as other stores (0.25 vs 0.06, p < 0.001). Each
  zone is updated as an overnight batch that walks its store list in store-number order.
- **Pre-registered event** (nationwide Kroger promotion expiry, Oct 6, 2026; 60 stores,
  34,177 store-products): **9 of 10 predictions hold.** The expiry was enforced within 16
  minutes, and the event night had 46× the control night's change rate. Zones did not
  significantly share the new effective minute (p = 0.06).
- **Walmart barely moves:** 3 price changes in 11,725 store-product transitions over 9
  repeat visits.

Every number states its sample size, and every method was checked on simulated data
first (`simulation/`). Nothing is causal. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

## Layout

```
config/       items.csv (58 items, with confirmed UPCs / product ids), store_sample.csv
              (stratified sample in balanced visit order), sampling.yaml, analysis.yaml
              (which snapshots the analysis uses), item_review*.csv (matching evidence)
collectors/   thin wrappers around the vendored basketBuddy collectors: walmart, target,
              costco_instacart, aldi, meijer, kroger (official API); snapshot.py runs a
              snapshot, reparse.py rebuilds the DB from raw, session_stash.py handles sessions
  vendor/     basketBuddy collectors, copied verbatim (see VENDORED.md)
db/           schema.sql, init_db.py
sampling/     frame, stratified draw, balanced-prefix visit order, external reference data
analysis/     coverage; module_a (tails), module_b (two-part Bayesian spatial model),
              module_c (shrinkage regression + factor model), module_d (basket MILP),
              module_e (pricing architecture: variogram, H0 persistence, zones),
              module_f (daily-panel synchronisation), module_g (price timing from Kroger
              effective/expiration timestamps), module_h (pre-registered event analysis),
              module_i (Walmart repeat-visit panel),
              zone_model.py (Dirichlet-process mixture), zone_sensitivity.py
simulation/   SYNTHETIC-data checks of the tail estimators, Module B, the zone model and the
              promotion-length estimators
scripts/      parallel snapshot runner, item review tools, smoke test
figures/ tables/  outputs
docs/         STUDY_PLAN, DECISIONS, PROGRESS, LIMITATIONS, SAMPLING, REPO_NOTES
paper/        write-up
tests/        pytest suite (no network); fixtures are trimmed live responses
```

## Setup

```
py -3.12 -m venv C:\Users\<you>\.venvs\groceryStatistics      # keep the venv out of OneDrive
C:\Users\<you>\.venvs\groceryStatistics\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # CENSUS_API_KEY for ACS covariates; Kroger production keys (…_ID2/…_SECRET2)
python db/init_db.py --load-items
python -m sampling.fetch_external && python -m sampling.fetch_osm && python -m sampling.build_frame
python -m sampling.visit_order
pytest
```

## Reproducing the analysis from raw data (no network)

```
python -m collectors.reparse        # data/raw/**  ->  data/grocery.sqlite
python run_all.py                   # coverage + modules A-I -> figures/, tables/
python run_all.py --sim             # also re-run the estimator simulations
python simulation/validate_module_b.py       # two-part spatial model check
python simulation/validate_zone_model.py     # zone model check
python -m simulation.validate_promo_lengths  # one-snapshot promotion-length estimators
python -m analysis.zone_sensitivity          # zone prior sensitivity + split-half replication (slow)
python -m scripts.auto_item_review           # item matching decisions (writes config/items.csv)
```

The raw archive (`data/raw/`) is the source of truth. Each file is a gzipped JSON envelope
`{"meta": {chain, store, item, query, time, ...}, "body": "<verbatim response>"}`, and
every observation row records the raw file it came from.

## Collecting data (generates retailer traffic; owner approval required)

```
.\scripts\run_snapshot_parallel.ps1 -Notes "snapshot N" -Chains "costco,aldi"   # one process per chain
.\scripts\run_snapshot_parallel.ps1 -SnapshotId N -Chains "target" -ExtraArgs "--budget 32"
$env:KROGER_BASE_URL = "https://api.kroger.com/v1"; .\scripts\run_snapshot_parallel.ps1 -SnapshotId N -Chains "kroger"
```

Then list the snapshot under `main_snapshots` in `config/analysis.yaml`. Runs are
resumable (`-SnapshotId N`). Stores are visited in balanced-prefix order, so a partial run
still yields a stratified, geographically spread sample. `--budget N` stops a chain
cleanly after N queries.

Kroger banner sample and event panel (official API, one process, ≤ 10,000 calls/day):

```
Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File scripts\run_kroger_event.ps1" -WindowStyle Hidden
```

Log: `data/raw/logs/kroger_event.log`. Pass times and the definitions are in
`docs/PREREGISTRATION_EVENT.md`.

Other panels (each owner-approved, DECISIONS #52–53; one process per site):

```
python -m scripts.meijer_sample enumerate|select|run      # Meijer footprint sample (snapshot 2)
scripts\run_meijer_event.ps1                              # Meijer control/before/after passes
scripts\run_walmart_panel.ps1                             # Walmart: 10 stores x 17 items, 3 visits/day
scripts\keep_awake.ps1                                    # stop Windows idle sleep while collecting
scripts\final_rerun.ps1                                   # final analysis rerun (run_all + zone robustness)
```

## Data collection and terms of use

- **Who is responsible.** Prices come from the public websites of Walmart, Target and
  Meijer, from Instacart-built storefronts (Costco, ALDI), and from Kroger's official
  developer API. The project owner is responsible for confirming they are permitted to
  collect and use this data for research.
- **Tooling.** The project uses the owner's existing basketBuddy collection code, unchanged
  except that its database hook is disabled. That code obtains a normal browser session
  (cookies) and replays search requests over HTTP. Kroger is accessed only through its
  credentialed API, within its published daily limit.
- **Rate limits.** One request at a time per site:
  - Instacart: ≥ 2 s apart.
  - Walmart and Target: ≥ 5 s, after both pushed back at 2 s.
  - Kroger (official API): ≥ 9 s for the cross-section; 0.5–1 s for the event panel, kept
    under the published 10,000 calls/day with a daily guard (DECISIONS #56).

  Chains run in parallel only because they are different sites, and per-run query budgets
  keep sessions short.
- **Sessions and refusals** (`collectors/session_stash.py`, DECISIONS #44–47):
  - Every run starts with a fresh session.
  - A fresh session refused on its first request counts as a **block**: the chain stops
    and pauses for 3 h, rising to 6, 12 and 24 h on repeated blocks.
  - A session refused after it had worked is treated as a session fault. After 5 minutes
    it is replaced by a fresh session, at most twice per run and 8 times per chain per day.
  - No proxies or IP rotation are used.
  - Every session, refusal, replacement and block is logged, and the counts are reported.
- **Secrets.** Session cookies are stored only locally, in gitignored files, and are never
  committed. The production Supabase pool of the basketBuddy app is never used.
- **Raw data.** Raw responses stay in the local archive, which is not published. Shared
  test fixtures are trimmed. Only aggregate statistics are published.

## Sources of public reference data

- U.S. Census Bureau, 2024 ZCTA Gazetteer.
- USDA ERS, 2020 Rural-Urban Commuting Area codes (ZIP).
- U.S. Census Bureau, American Community Survey 2019–2023 5-year estimates by ZCTA (Census API).
- OpenStreetMap contributors (ODbL), store locations by brand via Overpass.
