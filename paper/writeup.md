# Heavy Tails and Spatial Structure in Retail Price Dispersion: A Preliminary Cross-Section

*DRAFT, written before data collection. Sections marked **[RESULTS PENDING]** are filled in
after snapshot 1. Every number will state its sample size, and every result is preliminary
and cross-sectional.*

## 1. Question

If a product is identical (same UPC), how much does its price vary across stores of the same
chain and across chains? How heavy are the tails of that variation, and what geographic or
latent structure lies behind it? Under the law of one price, identical goods sold by one
firm would cost the same everywhere. Deviations from it, and especially their extremes, say
something about how prices are set: zone pricing, local competition, store-level
discretion, and promotions.

We study four things:

1. the distribution and tail index of within-chain price deviations (Module A);
2. how much of a store's price level is a smooth geographic surface (Module B);
3. which neighbourhood characteristics predict store price levels, and whether a few
   latent factors describe the store × product price matrix (Module C);
4. what a shopper could save by splitting a basket across nearby stores (Module D).

## 2. Data

**Collection.** One cross-sectional snapshot [RESULTS PENDING: dates, start/end times] of
online, store-specific prices from up to six chains, grouped by how the prices are obtained:

- *Retailer websites:* Walmart, Target and Meijer.
- *Instacart storefronts:* Costco, and ALDI's own Instacart-built site.
- *Kroger's official developer API:* its test environment, for the 25 items its catalog
  carries.

Instacart and Kroger-test prices are analysed separately from retailer-website prices.
[RESULTS PENDING: final per-chain store counts. Target, Walmart and Meijer each blocked
collection partway through. Those chains have fewer stores, but because stores were
visited in random order, the stores they have are a random subsample.]

Collection reused the owner's existing price-lookup code. It was rate-limited to one
request per site at a time, at least 5 seconds apart for Walmart and Target. Every raw
response is archived, and the database can be rebuilt from that archive. When a site
blocked a request, collection for that chain stopped; blocks were never worked around.
Failures are logged with chain, store, item, time and reason.

**Stores.** We drew a stratified random sample of 250 Target stores from Target's full
directory of 1,893 stores. Strata are Census region × urbanicity class, where urbanicity is
the 2020 USDA RUCA code of the store's ZIP: urban, suburban or rural. Allocation is
proportional, the seed is fixed, and stores were visited in a seeded random order. Walmart
and Costco stores are those each retailer assigns to the sampled Target ZIPs. That gives
geographically paired stores, but it is not a random sample of those chains.

**Items.** 58 items: 37 national-brand packaged groceries, 15 national-brand non-grocery
items (household, personal care, over-the-counter medicine, baby, pet) and 6 perishables,
which are compared within chain only. Every product returned by each search is stored, not
just the cheapest. Products are identical within a chain by the chain's product id, and
across chains by a UPC read from each retailer's product page and confirmed by hand.

**Prices.**
- Main analysis: the regular (non-promotional) price. A row is a promotion if the retailer
  reports a regular price above the current one.
- Sensitivity analysis: the shelf price including markdowns.
- Only rows the retailer itself ties to the requested store are used.

**Coverage.** [RESULTS PENDING: table of intended vs collected store-item pairs by chain,
region and urbanicity; the share of rows that are store-specific; failure reasons. Any
chain below 60% coverage is flagged.]

## 3. Methods

**Deviation.** For product $j$ at store $s$ of chain $c$,
$d_{sj} = \log p_{sj} - \log \operatorname{median}_{s' \in c}\, p_{s'j}$. Only products
seen at 20 or more stores are used. For UPC-matched products, a cross-chain version uses
the median over all chains.

**Tails (Module A).** For $|d|$, and for the upper and lower tails separately, we report:
- the Hill estimator of the tail index $\alpha$ at $k = 5\%$ of the nonzero observations,
  with the stability-rule $k$ and $k = 10\%$ as sensitivity checks;
- a generalised Pareto fit above the 90% quantile, reported as the shape $\xi$. Here
  $\xi \le 0$ means no power-law tail.

Confidence intervals come from a **store-cluster bootstrap**, which resamples whole stores
because deviations within a store are correlated. The estimators were checked first on
simulated data:
- On exact Pareto data with $n = 250$, the $k = 5\%$ Hill interval covered at 94–97%.
- On $|t_3|$ data, whose tail is only asymptotically Pareto, coverage was 84–92%.
- A data-driven stability rule covered only 22–78% there, because it chose $k$ too deep
  into the body of the distribution.

We report the share of deviations that are exactly zero, since much of a chain's pricing
is uniform. We test whether extreme stores cluster geographically using a join-count
permutation test and Moran's I, with neighbours within 100 km. Basket risk is the cost of
a fixed basket per store, relative to the chain median, summarised by its 95% value at
risk and expected shortfall.

**Spatial model (Module B).** Three models for $y = \log p$:
- M0: product effects, chain effects (identified only through UPCs shared across chains),
  store effects with chain-specific scale, and Normal residuals.
- M1: as M0, with Student-$t$ residuals.
- M2: as M1, plus a Matérn-3/2 Gaussian-process field over store locations, fitted with a
  Hilbert-space approximation.

Inference is by NUTS (PyMC with NumPyro; 4 chains × 1,000 draws). We report R-hat, ESS,
posterior predictive checks, PSIS-LOO and, for M2, the **spatial share**
$\operatorname{var}_s f / (\operatorname{var}_s f + \sigma_u^2)$.

A simulation at real Target locations checked the method:
- M2 recovered the field's scale, the residual df and the chain effects.
- It slightly under-estimated the spatial share (0.54 vs 0.62 for one chain, 0.60 vs 0.64
  for the other).
- Pointwise LOO barely separated M2 from M1 (ΔELPD 3 ± 1.8) even though the truth was
  strongly spatial. We therefore treat LOO as a check on the residual model, not as
  evidence about spatial structure.

**Shrinkage and factors (Module C).**
- *Response:* each store's price index (its mean $d$).
- *Predictors:* ACS 2023 5-year ZCTA variables (income, density, age, housing costs,
  poverty, education, transit, car ownership), RUCA class, and distances to competing
  chains from OpenStreetMap. We add their squares, pairwise interactions and state
  dummies, which gives about 100–150 predictors for about 250 stores.
- *Models:* OLS, lasso, elastic net and a regularised horseshoe prior.
- *Evaluation:* out-of-sample error by repeated 5-fold cross-validation with **whole
  states held out**, so a model is always judged on states it has not seen.
- *Factor model:* the store × product matrix of $d$ is fitted by EM-PCA, with the rank
  chosen by predicting 10% of cells held out at random.

**Basket optimisation (Module D).** For each sampled location we take Target and Walmart
stores within 25 km and ask: what is the cheapest way to buy a fixed basket while visiting
at most $k \in \{1, 2, 3\}$ stores? We solve this exactly as an integer program (HiGHS) and
compare it with a greedy heuristic. The saving that exists only because the chains price
differently is the gap between the best same-chain plan and the unrestricted optimum.
Travel cost is not modelled.

## 4. Results [RESULTS PENDING]

Planned figures, at most 5:
1. Survival function of $|d|$ (log-log) by chain, with Hill estimates and 95% CIs. Table:
   tail index by chain, department, and regular vs shelf price.
2. Hill plots with the chosen $k$ marked.
3. Posterior mean of the spatial surface (M2) and the spatial share by chain.
4. Out-of-sample RMSE by model, and horseshoe coefficients with 90% intervals.
5. Distribution of basket savings from visiting 2 or 3 stores.

## 5. Limitations

- **Cross-sectional.** One snapshot (two if the repeat is collected). Nothing here is causal
  or dynamic.
- **Online prices.** These are the prices each website shows for a selected store, not
  shelf audits. Costco prices are Instacart storefront prices.
- **Sampling.** Target is a stratified random sample. Walmart and Costco are the stores
  those retailers assign to the Target ZIPs, so they over-represent where Target operates.
  Items are hand-picked, nationally distributed brands, not a random sample of either
  chain's range.
- **Collection.** A full snapshot takes many hours, so prices within it were not observed
  at the same moment. Chains that blocked collection were stopped, not worked around, and
  their coverage is reported as is. Kroger's official test environment covered too few
  items to include.
- **Location.** Most store coordinates are ZIP centroids, which blurs spatial structure
  below the ZIP scale. ZIPs are matched to ZCTAs.
- **Tails at this sample size.** With a few hundred stores per chain, tail indices are
  imprecise. Intervals are wide, and the estimates are best read as an order of magnitude.
- **Promotions.** Only markdowns are flagged; multi-buy and coupon offers are not converted
  into prices.
