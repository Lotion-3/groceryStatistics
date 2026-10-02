# Heavy Tails and Spatial Structure in Grocery Price Dispersion

The question: for identical products (matched by UPC), how are prices distributed across
stores and chains, how heavy-tailed are the deviations, and what geographic and latent
structure lies behind them?

**Status:** collection and analysis code complete for Modules A-D; no full snapshot has
been collected yet, so every result will be preliminary. See `docs/PROGRESS.md`.

## Layout

```
config/       items.csv (item list), sampling.yaml, store_sample.csv (drawn sample),
              items_resolved.csv / item_candidates.csv (UPC resolution, for review)
collectors/   thin wrappers that call the vendored collectors
  vendor/     basketBuddy collectors, copied verbatim (see VENDORED.md)
  snapshot.py run a snapshot; reparse.py rebuild the DB from raw; resolve_items.py
db/           schema.sql, init_db.py
sampling/     fetch_external.py, fetch_osm.py, build_frame.py, locate_target_stores.py, geo.py
data/         raw/ (gzipped responses, gitignored), processed/, external/ (gitignored)
analysis/     estimators.py, common.py, module_a … module_e
simulation/   SYNTHETIC-data checks of the estimators and of Module B (clearly labelled)
figures/ tables/  outputs
docs/         REPO_NOTES, SAMPLING, DECISIONS, LIMITATIONS, PROGRESS
tests/        pytest suite; fixtures are trimmed live responses
```

## Setup

```
py -3.12 -m venv C:\Users\<you>\.venvs\groceryStatistics      # keep the venv out of OneDrive
C:\Users\<you>\.venvs\groceryStatistics\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # CENSUS_API_KEY needed for the ACS covariates; Kroger keys optional
python db/init_db.py --load-items
python -m sampling.fetch_external && python -m sampling.fetch_osm && python -m sampling.build_frame
pytest
```

## Reproducing the analysis from raw data (no network)

```
python -m collectors.reparse        # data/raw/**  ->  data/grocery.sqlite
python run_all.py                   # analysis modules -> figures/, tables/
python run_all.py --sim             # also re-run the estimator simulations
```

The raw archive (`data/raw/`) is the source of truth. Each file is a gzipped JSON envelope
`{"meta": {chain, store, item, query, time, ...}, "body": "<verbatim response>"}`. Every
observation row records the raw file it came from.

## Collecting data (generates retailer traffic; owner approval required)

```
python -m sampling.locate_target_stores           # true Target store addresses (~1,900 requests)
python -m collectors.resolve_items --fetch-upc    # one product page per item per chain
.\scripts\run_snapshot_parallel.ps1 -Notes "snapshot 1"   # one process per chain; resume with -SnapshotId N
```

Then list the snapshot id under `main_snapshots` in `config/analysis.yaml` so the analysis
uses it.

Kroger (official Kroger Public API, `collectors/kroger.py`) is an optional chain:
`--chains kroger`. The certification host covers only ~10 of the 58 items, so it is off by
default. With production credentials, set `KROGER_BASE_URL=https://api.kroger.com/v1`.

The first run of a chain mints a session with a local headless browser (CloakBrowser), which
can take a minute. Walmart needs one browser launch per store to set it as the pickup store.

## Data collection and terms of use

- **Who is responsible.** Prices are collected from the public websites of Walmart, Target
  and Trader Joe's, and from Instacart's storefront for Costco. The project owner is
  responsible for confirming they are permitted to collect and use this data for research.
- **Tooling.** The project uses the owner's existing basketBuddy collection code, unchanged except that its
  database hook is disabled. That code obtains a normal browser session (cookies) and replays search
  requests over HTTP. No new mechanisms for getting past access controls were written for
  this project.
- **Rate limits.** Collection is deliberately slow: one request at a time per site, at
  least 2 seconds apart (5 seconds for Target and Walmart after both pushed back on day 2),
  with backoff on errors. Chains run in parallel only because they are different sites.
- **Blocks.** If a site serves a block or captcha, or fails 6 times in a row, collection
  for that chain stops for the run and the event is logged. It is never retried around,
  and sessions are not re-created to get past a block.
- **Kroger** is accessed only through its official, credentialed developer API, within its
  published daily limits.
- **Secrets.** Session cookies are stored only locally, in gitignored files, and are never
  committed.
- **Raw data.** Raw responses stay in the local archive, which is not published. Shared test
  fixtures are trimmed, and anything that identifies the collecting machine is removed.

## Sources of public reference data

- U.S. Census Bureau, 2024 ZCTA Gazetteer.
- USDA ERS, 2020 Rural-Urban Commuting Area codes (ZIP).
- U.S. Census Bureau, American Community Survey 2019-2023 5-year estimates by ZCTA (Census API).
- OpenStreetMap contributors (ODbL), store locations by brand via Overpass.
