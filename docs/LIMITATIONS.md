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
  (browser-minted sessions replayed over HTTP), rate-limited, without escalating past
  blocks. Chains that block are dropped for that run, and that missingness is logged.
  Trader Joe's returned HTTP 403 on day 1 and was dropped. Target soft-blocked (HTTP 435)
  on day 2 at a 2 s pace, so Target is now collected at ≥ 5 s per request, and a
  circuit breaker stops any chain after 6 consecutive failures.
- **Snapshot window.** A full snapshot takes many hours, not "a few", so prices within
  one snapshot were not all observed at the same moment. `observed_at` is kept per row.
- **Item scope.** 37 packaged grocery items, 15 non-grocery national brands and 6
  perishables. These are hand-picked items that both chains stock, not a random sample
  of either chain's assortment.
- **Tail estimation at n ≈ 250 per chain** is noisy. Simulation shows RMSE of α̂ around
  0.7–1.1 at n = 250 even for well-behaved tails, and poor interval coverage when the tail
  is only asymptotically Pareto.
