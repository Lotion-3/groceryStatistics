# How Retailers Price Across Space: National Lists, Pricing Zones and Local Departures

*Preliminary draft. All numbers come from snapshot 2 (October 2026), one cross-section,
with collection still finishing for some chains; they will be updated at the final run
(marked **[update]**). Every result states its sample size. Nothing here is causal or
dynamic.*

## Abstract

For identical products, how does a retail chain's price vary across its stores? We
collected store-specific online prices for about 60 nationally distributed items at up to
250 sampled locations for six US chains, from retailer websites, Instacart-built
storefronts and Kroger's official API. Most prices sit **exactly** at a chain's list price
(91% at ALDI and Walmart, 62% at Kroger), so dispersion is a point mass plus structured
departures, not a continuous spread. We describe each chain's *pricing architecture* with
four tools:
- a price-list variogram;
- the persistent homology of price-list dissimilarity;
- a Dirichlet-process mixture that recovers pricing zones from prices alone;
- a two-part Bayesian spatial model of departures.

The chains differ sharply:
- ALDI: a national list with a few regional zones.
- Walmart: a slow geographic gradient.
- Costco on Instacart: regional zones about 850 km across.
- Kroger: highly local zones that coincide with its banners. 94% of stores fall in
  banner-pure zones, although the model is never told the banners.

Each method is first checked on simulated data with a known answer.

## 1. Question

Under the law of one price, a chain selling an identical product would charge the same
everywhere. DellaVigna and Gentzkow (2019, *QJE*), using Nielsen scanner data, found that
US chains price nearly uniformly across stores despite large differences in local
demographics.

We ask a complementary question with public data: **how is a chain's price list organised
across space?** There are three candidate architectures: one national list, a few discrete
zones, or a continuous gradient. Where do departures from the list occur, and how large
are the extremes? The answer differs by chain, and the methods needed to see it are the
contribution.

## 2. Data

**Sources.** Snapshot 2 [update: dates]. Store-specific prices came from three routes:
- *Retailer websites:* Walmart, Target and Meijer.
- *Instacart storefronts:* Costco, and ALDI's own Instacart-built site.
- *Kroger's official Public API* (production), which covers its banners: Kroger, Ralphs,
  Fry's, Fred Meyer, Smith's, Harris Teeter, Mariano's and others.

Instacart prices may include platform pricing, so Instacart chains are always reported
separately.

**Stores.** We drew a stratified random sample of 250 locations from Target's directory of
1,893 stores. Strata are Census region × urbanicity, where urbanicity is the store ZIP's
2020 USDA RUCA class. For every other chain, the store is the one that chain assigns to,
or has nearest to, each sampled location.

Collection visits locations in a **balanced-prefix order**: systematic interleaving across
strata with farthest-point order within each stratum. A chain that stops part-way
therefore still has a stratified, geographically spread sample: at 25% of the list, every
stratum is within one store of proportional, and 38 states are present.

Store counts [update]:

| Chain | Stores | Source |
|---|---|---|
| ALDI | 205 | ALDI's Instacart-built site |
| Costco | 174 | Instacart |
| Kroger | 84 so far (target about 130) | official API |
| Walmart | 41 | stopped at a captcha |
| Meijer | 3 | stopped at a block |
| Target | short budgeted sessions | website |

**Items.** 58 items:
- 37 national-brand packaged groceries;
- 15 national-brand non-grocery items (household, personal care, over-the-counter, baby,
  pet);
- 6 perishables.

Every product returned by each search is stored, not only the best match. Within a chain,
a product is identified by the chain's own product id. Across chains, products are
matched by UPC:
- The canonical UPC comes from Kroger and Meijer, which report a UPC for every product.
  Both chains agree on it for 22 items, and 37 of 52 cross-chain items have one.
- Walmart products are confirmed by the UPC on their product page (17 items).
- Target products are matched by name and size only (21 items; weaker evidence).
- Variant, multipack and store-brand candidates are rejected by rule, and seven fields
  were vetoed by hand (all documented).

**Prices.**
- The main analysis uses regular (non-promotional) prices, to the cent, and only rows the
  retailer itself ties to the requested store.
- Promotions are flagged when the retailer reports a regular price above the current one.
  Multi-buy offers are recorded but not treated as prices.

**Collection practice.**
- One request at a time per site, at least 5 s apart for Walmart and Target, and 9 s for
  Kroger (within its published daily limit).
- Every raw response is archived, and the database can be rebuilt from the archive.
- Every failure is logged.
- A chain whose fresh session is refused on its first request is treated as blocked and
  paused (3 h, then longer on repeats).
- A session that fails after working is replaced at most twice per run.
- Target and Walmart limited automated access at low volume, so those chains are partial.

## 3. Methods

**3.1 Point mass and departures.** For each chain and product, the list price $\ell_j$ is
the modal price. We report:
- the share of store prices equal to $\ell_j$;
- for departures, their direction and size, $\log(p_{sj}/\ell_j)$.

**3.2 Price-list variogram.** For stores $s, t$ of a chain, the dissimilarity $\delta_{st}$
is the fraction of products both carry (at least 20) that they price differently. The
variogram is the mean of $\delta$ by distance band. Its 95% bands come from a
**store bootstrap**, because pairs sharing a store are dependent. We fit
$\gamma(h) = \text{nugget} + (\text{sill} - \text{nugget})(1 - e^{-h/r})$:
- the nugget measures local departures;
- the range $r$ is the scale over which price lists diverge;
- when the curve has no plateau within US distances, we report that rather than an
  unidentified range.

**3.3 Zones, two ways.**
- *Persistent homology.* Linking stores with $\delta_{st} \le t$ and growing $t$ gives the
  0-dimensional barcode of the single-linkage filtration. Long bars indicate discrete
  zones.
- *Dirichlet-process mixture.* Each store's price list is coded product by product as
  which of the product's observed price levels it charges. The model is
  $z_s \sim \mathrm{CRP}(\alpha)$ and
  $c_{sj} \mid z_s = k \sim \mathrm{Cat}(\theta_{kj})$, with
  $\theta_{kj} \sim \mathrm{Dir}(\gamma\, g_j)$, where $g_j$ is the chain-wide level
  frequency (an empirical-Bayes base measure).
  - Price levels charged by only one store say nothing about which stores belong
    together. They are set aside as local departures, and their share is reported.
  - Inference is collapsed Gibbs (Neal 2000) plus sequentially allocated merge–split
    moves (Dahl 2005), with Escobar–West updates for $\alpha$.
  - We run two chains from different starts and compare them (adjusted Rand index, ARI).
  - Zones with identical estimated lists are merged, because they are not identifiable.
  - Spatial coherence is tested by comparing how often nearby stores (< 250 km) share a
    zone against permuted zone labels.

**3.4 Two-part spatial model** (validated on simulated data with a known answer).
1. *Part 1:* $z_{sj} = 1\{p_{sj} = \ell_j\} \sim \mathrm{Bernoulli}(\pi_s)$, with store
   effects on the logit scale.
2. *Part 2:* for prices off list, $\log(p_{sj}/\ell_j) \sim t_\nu(m_s, \sigma_1)$, with
   $m_s = \mu + u_s$ in M1. M2 adds a Matérn-3/2 Gaussian-process field, fitted with a
   Hilbert-space approximation.

Inference is by NUTS (PyMC with NumPyro). We report R-hat, ESS, posterior predictive
checks, PSIS-LOO for M1 against M2, and the spatial share
$\operatorname{var}_s f / (\operatorname{var}_s f + \sigma_u^2)$. The model is fitted on
the contiguous US.

Two simpler models failed to converge on real data: a single Student-$t$ residual, and a
latent two-component mixture that label-switched. Those failures are what revealed the
point-mass structure.

**3.5 Extremes.** Hill and generalised-Pareto estimates of the departure tail are reported
with store-cluster bootstrap intervals, with and without Hawaii and Alaska. The estimators
were first calibrated on simulated data: at $n = 250$, the $k = 5\%$ Hill interval covered
the true value 84–97% of the time.

**3.6 Predictors and law of one price.**
- Store-level departures are regressed on 2023 ACS neighbourhood variables, RUCA class and
  competitor distances, with their squares and interactions (p ≈ 100–150). We compare OLS,
  lasso, elastic net and a regularised horseshoe by cross-validation with whole states held
  out.
- Same-UPC price gaps across chains at the same locations, and an exact integer program
  for the cheapest multi-store basket, use the matched-item panel.

**3.7 Validation summary.**

| Method | Check on simulated data |
|---|---|
| Hill / GPD tails | 95% interval coverage 84–97% (k = 5%) |
| Two-part spatial model | 13 of 16 parameters inside their 90% intervals; spatial share slightly underestimated |
| Zone model | exact recovery of 3–6 zones down to a 3% product difference; one zone when there are none; ARI 0.78 at a 1% difference |
| Zone model on real data | recovers Kroger's banner structure without being told it (94% purity) |

## 4. Results (preliminary)

| | ALDI (205) | Walmart (41) | Costco/Instacart (174) | Kroger (84) |
|---|---|---|---|---|
| Prices at list | 91% | 91% | 76% | 62% |
| Departures upward (median) | 19% (−7.9%) | 76% (+4.8%) | 50% (+0.3%) | 65% (+4.9%) |
| $\delta$, stores < 50 km apart → > 2,000 km apart | 6.5% → 20% | 5.3% → 21% | 8.9% → 36% | 22% → 64% |
| Variogram range | no plateau | no plateau | ≈ 850 km | ≈ 190 km |
| Zones (posterior) | 10; largest 79 stores in 27 states | 5 | 18 regional | 17, banner-aligned |
| Nearby stores in the same zone vs chance | 50% vs 20% | 78% vs 25% | 50% vs 6% | 49% vs 6% |

All spatial-coherence p-values are 0.001.

**Four architectures.**
- **ALDI** runs one national list over most of the country, with regional zones (California,
  Mid-Atlantic, Texas, Arizona/Nevada). It departs mostly *downward*, to local markdowns.
- **Walmart** has no identical store lists. Instead, dissimilarity rises slowly with
  distance, with distinct West Coast and Mountain zones. Departures are mostly *upward*.
- **Costco on Instacart** forms about 18 regional zones on a scale of about 850 km.
- **Kroger** is the most local. Its zones follow its banners, and within a banner, its
  divisions:
  - Stores < 100 km apart differ on 8% of shared products within a banner and 78% across
    banners.
  - 94% of stores are in a zone dominated by their own banner, although the zone model
    never sees banner labels.

**Extremes.** The extreme upper tail is mostly geographic. One Honolulu Walmart charges
\$6.28 for milk against a chain median of \$2.97. Without Hawaii and Alaska, the
generalised-Pareto shape of Walmart's departures is about 0, meaning no power-law tail
[update].

**Urban and rural.** We find no urban–rural difference in price *levels* in any chain.
Nearby urban and rural Walmarts differ on more products than same-type pairs (7.4% vs
5.4%, p = 0.03, 41 stores). This hypothesis was suggested by the same data, so it is
exploratory.

**Spatial structure of departures (two-part model, M2).** The model uses Kroger (94
stores) and Walmart (41), contiguous US: 5,380 prices, 74% at list. It converges (R-hat
1.014, ESS 391).
- **Spatial share:** about **70%** of the store-level variation in departure size is a
  smooth geographic surface. Kroger 0.72 (90% interval 0.54–0.89); Walmart 0.70
  (0.40–0.99).
- **Scale agreement:** the field's length-scale (about 170 km) matches the Kroger variogram
  range (about 190 km), from a different method.
- **Departures:** they average +5.1% at Kroger and about 0 at Walmart. Stores' propensity
  to depart clusters in space (Moran's I = 0.46 and 2.08, p = 0.0002).
- **LOO:** PSIS-LOO does not separate M1 from M2, as the simulation predicted.
- **Misfit:** posterior predictive checks reproduce the share of prices at list, but the
  most extreme departures (99th percentile 0.37 observed vs about 0.29 replicated) are
  heavier than the model's $t_{
u pprox 1.9}$.
- **Reference model:** M0 does not converge (R-hat 1.46). It is misspecified, and with
  only 3 UPCs shared between chains its chain effect is barely identified.

**Basket arbitrage.** Basket of 12 items (about \$60) at 62 locations with 142 nearby
stores; the exact integer program and the greedy heuristic agree at every location.
Splitting the basket across 2–3 stores saves a median of **0.05%** (90th percentile
0.12%), although the cheapest split mixes chains 71% of the time. Cross-chain gaps are
level differences, not item-specific ones: one chain is cheapest on nearly every item, so
law-of-one-price violations leave almost no basket arbitrage.

**Law of one price.** Matches use confirmed product identities (§2). On identical UPCs in
the contiguous US, each chain's median regular price compared with Walmart's:

| Chain | Shared UPCs | Its stores | Gap vs Walmart (IQR) |
|---|---|---|---|
| Target | 11 | 4 | +3.2% (+0.9 to +6.2) |
| Meijer | 17 | 3 | +5.6% (+2.3 to +8.1) |
| Kroger | 15 | 93 | +9.8% (+6.2 to +18.0) |

[update: Target and Meijer store counts after more sessions; Module B spatial share and
Module C cross-validation comparison.]

## 5. Limitations

- **One cross-section.** There is no dynamics and nothing is causal. A second snapshot or
  Kroger daily panel would test whether stores in a zone change prices together.
- **Website prices**, not shelf audits. Instacart chains may carry platform pricing, so
  Costco's local structure may partly be Instacart's.
- **Partial chains.** Walmart and Target restricted automated access at low volume.
  Walmart (41 stores) and Target are small, though spread across strata by design.
- **Sampling.** Locations come from Target's footprint, which over-represents urban areas
  for the other chains. Items are hand-picked national brands.
- **Zone model assumptions.** Products are treated as independent within a zone, so
  posterior certainty about the number of zones is probably overstated. "Zones" are
  groups sharing most price levels, not necessarily identical lists.
- **Location.** Most coordinates are ZIP centroids.

## 6. Reproducibility

The raw archive rebuilds the database (`python -m collectors.reparse`), and
`python run_all.py` regenerates every table and figure. Simulation checks live in
`simulation/`, and design decisions are logged in `docs/DECISIONS.md`.
