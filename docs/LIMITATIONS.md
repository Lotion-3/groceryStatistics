# Limitations (running list; becomes the write-up's limitations section)

- **Cross-sectional.** One or two snapshots a week apart. Nothing here identifies dynamics,
  price-setting mechanisms or causal effects of covariates.
- **Online prices.** Walmart and Target prices are what each retailer's website shows for a
  chosen store, not shelf-audited prices. Costco prices are Instacart storefront prices,
  which may include a markup over in-warehouse prices. Trader Joe's has a single national
  web price.
- **Store specificity is the retailer's own claim.** We keep only rows the response ties to
  the requested store. About 10% of Target items are priced at a non-store location.
  Walmart search results are dominated by marketplace and fulfilment-centre listings, of
  which only about 25% are store-specific.
- **Sampling.**
  - Target stores are a stratified random sample of Target's own directory.
  - Walmart and Costco stores are whichever store each retailer assigns to the sampled
    Target ZIPs. They are therefore not a random sample of those chains' stores, and they
    are concentrated where Target is (mostly urban).
  - The provisional sample was stratified on wrong locations for ~25% of stores (see
    SAMPLING.md) and must be redrawn.
- **Coordinates.** Target stores and Costco are at ZIP centroids, and Walmart is at the
  OpenStreetMap point where available. Spatial models therefore have ZIP-level resolution
  for most stores.
- **Product matching.** Search results carry no UPC. Cross-chain identity relies on one
  product-page lookup per item and owner review; Costco's multipacks rarely match
  national-brand UPCs.
- **Search scope.** Each query returns at most 24 (Target), 40 (Walmart) or 20 (Instacart)
  products, and Target applies a purchasability filter. Items missing from the first page
  are recorded as not found, not as unavailable.
- **Promotions.** Only markdowns (regular > current) are flagged. Multi-buy and coupon
  offers are recorded as text but not converted into prices.
- **Collection method and access.** Data were collected with the owner's existing tooling
  (browser-made sessions replayed over HTTP), rate-limited, plus Kroger's official API.
  - **Blocks** (a fresh session refused on its first request) stop the chain and pause it.
  - **Session faults** (a session refused after it had worked) are replaced by a fresh
    session, at most twice per run.
  - **Counts.** All refusals, replacements and blocks are logged and reported.
  - **Pushback.** Target and Walmart limited automated access at low volume (about 47–115
    requests per session), so those chains are partial.
  - **Trader Joe's** returned HTTP 403 on day 1 and was dropped.
- **Zone model.** Products are treated as independent within a zone, so the posterior
  certainty about the number of zones is overstated. Robustness is checked by prior
  sensitivity and split-half replication (`analysis/zone_sensitivity.py`). Zones are groups
  sharing most price levels, not necessarily identical lists.
- **Item matching.** 37 of 52 cross-chain items have a canonical UPC (Kroger/Meijer). Target
  products are matched by name and size only. 15 items have no confirmed cross-chain
  identity and are within-chain only.
- **Model misfit.** The two-part model under-predicts the most extreme departures, and the
  simple Normal reference model does not converge with Kroger and Walmart together (only 3
  shared UPCs identify the chain effect).
- **Snapshot window.** A full snapshot takes many hours, not "a few", so prices within
  one snapshot were not all observed at the same moment. `observed_at` is kept per row.
- **Item scope.** 37 packaged grocery items, 15 non-grocery national brands and 6
  perishables. These are hand-picked items that both chains stock, not a random sample
  of either chain's assortment.
- **Tail estimation at n ≈ 250 per chain** is noisy. Simulation shows RMSE of α̂ around
  0.7–1.1 at n = 250 even for well-behaved tails, and poor interval coverage when the tail
  is only asymptotically Pareto.
- **Spatial model.** In simulation (`simulation/validate_module_b.py`, one replication),
  pointwise PSIS-LOO hardly separated the spatial from the non-spatial model (ΔELPD 3 ± 1.8)
  even when the truth was strongly spatial. So LOO is not evidence for or against spatial
  structure here. We report the posterior spatial share instead, which was recovered within
  about 0.1 but tended to be slightly low.
- **Store coordinates are mostly ZIP centroids,** which blurs spatial structure below
  roughly the ZIP scale.
- **Kroger.** *(Superseded 2026-10-03, DECISIONS #39.)* The first credentials worked only
  on the certification host, whose catalogue was partial. Those rows are labelled
  `kroger_ce` and excluded. Kroger now comes from the production API: 121 stores in
  snapshot 2, plus a banner sample in progress.
- **Instacart prices may not be a clean control.** In partial data, Costco via Instacart
  had *more* dispersion than Walmart (73% vs 89% of prices exactly at the chain median).
  One explanation is a markup that varies by location. If so, within-chain deviations for
  Instacart-sourced chains (Costco, ALDI) mix retailer pricing with Instacart pricing. These
  chains are reported separately, and the write-up must not treat them as uniform-price
  benchmarks without checking.
- **Blocked chains have partial coverage.** In snapshot 2, Walmart (after 42 stores) and
  Meijer (after 3 stores; its store locator) were blocked and stopped. Target comes from
  short budgeted sessions (16 stores, 16 matched items); Target allows about 50 requests
  per session. Stores are visited in balanced-prefix order, so each partial chain is a
  stratified, spread-out subsample, but far smaller than planned.
- **Geographic outliers.** Hawaii (and Alaska) stores carry large real price premia, and
  they dominate the extreme tail. Tail results are reported with and without them.
- **Timing comes from the retailer's timestamps, for Kroger only.**
  - `effectiveDate` is when Kroger's system says the current price began. If an unchanged
    price is re-entered, the date may reset, which would make prices look younger and
    more synchronised.
  - The pre-registered event panel (Module H) checks timestamps against observed changes.
  - Store-local times use each store's state time zone; a few states span two zones.
- **Promotion-length estimates from one snapshot depend on assumptions.** Four
  estimators give 9–28 days. A simulation shows which assumption each needs, but one
  snapshot cannot tell which one holds. The event's new promotions are observed when they
  start.
- **Zones are frozen from snapshot-2 prices** for the pre-registered tests. Zones refitted
  on the larger banner sample are reported separately and are not used for the
  pre-registered predictions.
