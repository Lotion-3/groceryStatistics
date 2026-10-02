# Store sampling

**Status (2026-10-01): PROVISIONAL.** `config/store_sample.csv` was drawn from a frame whose
locations are known to be wrong for about 25% of stores (see "Known problem" below). It must
be redrawn after the locate pass, before snapshot 1.

## Frame

- **Target:** all 1,893 stores in Target's store sitemap, via the directory vendored from
  basketBuddy (`collectors/vendor/target_store_directory.json`). One store had no ZCTA
  within 25 km (store 2371, slug "anchorage-ne", geocoded to coastal California) and is
  ineligible. That leaves 1,892 eligible stores.
- **Walmart and Costco:** no store directory exists in basketBuddy, and building one would
  mean extra retailer traffic. Instead, both are **anchored to each sampled Target store's
  ZIP**:
  - Walmart: the store Walmart itself assigns to that ZIP (the first node of its
    nearby-store query, radius 50 miles).
  - Costco: the location Instacart assigns to that ZIP.
  - The result is a geographically paired sample: each anchor gives up to one store per
    chain, which suits the cross-chain comparison.
  - Distinct Target anchors can map to the same Walmart or Costco, so the per-chain counts
    are at most 250. Costco is deduplicated by Instacart location.
- **Trader Joe's:** one national web price, so it has no frame.

## Covariates attached to each store

| Field | Source |
|---|---|
| ZIP | Target: the ZIP in the address Target reports for the store (after the locate pass). Walmart: the ZIP in its scoped store address. Costco: the anchor ZIP. Before the locate pass, the frame uses the ZCTA nearest the slug geocode |
| lat, lon | Walmart: OpenStreetMap feature with `ref` = store number when present (`osm_ref`), else the ZIP's ZCTA internal point (`zip_centroid`). Target: ZCTA internal point of its reported ZIP. Costco: anchor ZIP centroid (`anchor_zip`). See `stores.coord_quality` |
| state | USDA ERS 2020 RUCA ZIP file |
| region | Census region of the state (Northeast, Midwest, South, West; DC counted as South) |
| urbanicity | 2020 primary RUCA code of the ZIP. 1 = urban (metropolitan core); 2–3 = suburban (metropolitan high/low commuting); 4–10 = rural (micropolitan, small town and rural) |

## Draw

- Strata: region × urbanicity (12 strata).
- Allocation: proportional to the stratum sizes in the eligible frame, rounded by the
  largest-remainder method so the total is exactly `n_target`.
- Within each stratum: simple random sampling without replacement, using
  `numpy.random.default_rng(seed)`. Strata are visited in sorted order and stores sorted
  by `store_id`, so the draw is reproducible.
- `n_target = 250` and `seed = 20261001` (`config/sampling.yaml`).

Reproduce with:

```
python -m sampling.fetch_external     # Census ZCTA gazetteer 2024, USDA RUCA 2020 (ZIP)
python -m sampling.build_frame        # -> data/processed/target_frame.csv, config/store_sample.csv
```

## Known problem and fix

Checking the directory against OpenStreetMap showed the slug geocodes were badly wrong for
about 25% of stores where a store number could be matched: 41 of 161 were more than 50 km
off, often in the wrong state. Example: store 1763 "frisco" was placed in San Francisco
instead of Frisco TX. The provisional draw therefore stratified some stores into the wrong
region or urbanicity class.

Every Target search response includes the searched store's mailing address
(`fulfillment.store_options[0].store.mailing_address`). Two fixes follow:

1. **Locate pass:** `sampling/locate_target_stores.py`.
   - One minimal search (`count=1`) per directory store records the true address. That is
     about 1,900 requests, roughly 1–1.5 h at 2 s spacing, and **needs owner approval**.
   - `build_frame.py` then uses the true ZIPs automatically, and the sample is redrawn with
     the same seed.
2. **During any snapshot**, each Target store's location is overwritten with the reported
   address on its first search, so collected data never uses the bad coordinates.

## Allocation of the provisional sample (seed 20261001, n = 250)

| region | rural | suburban | urban |
|---|---|---|---|
| Midwest | 10 | 3 | 47 |
| Northeast | 5 | 2 | 38 |
| South | 8 | 4 | 67 |
| West | 5 | 3 | 58 |

The suburban cells are tiny. The slug geocodes sit at city centres, which pushes stores
into the "urban" class. Expect this to shift after the locate pass.
