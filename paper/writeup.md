# How Retailers Price Across Space and Time: National Lists, Pricing Zones and Overnight Batches

*Preliminary draft, 2026-10-06. Numbers come from snapshot 2 (one cross-section, Oct 2–5,
2026) and from the retailers' own price timestamps. Every result states its sample size.
Nothing here is causal. A pre-registered event study (§5.4) is in progress. Details of
data checks and methods are in the Appendix. A Kroger banner sample is being added to
snapshot 2 (121 → 192 so far, about 270 planned), so Kroger sample sizes differ between
sections. Each
result states its own n, and all Kroger numbers will be rerun once the sample is
complete.*

## Abstract

How does a retail chain's price for an identical product vary across its stores, and when
does it change? We collected store-specific prices for 58 national-brand items at six US
chains (up to 250 sampled locations; retailer websites, Instacart-built storefronts and
Kroger's official API).

Most prices sit **exactly** at the chain's list price (91% at ALDI and Walmart, 65% at
Kroger), so dispersion is a point mass plus structured departures. Using a price-list
variogram, a Dirichlet-process mixture that recovers pricing zones from prices alone, and
a two-part Bayesian spatial model, we find four architectures:
- **ALDI:** a national list with regional zones;
- **Walmart:** a slow gradient;
- **Costco on Instacart:** regional zones about 850 km across;
- **Kroger:** local zones nested in its operating divisions (95% purity), although the
  model never sees banners or divisions.

Meijer, in its Michigan core, has almost one list and one sale calendar.

Kroger's price-record timestamps independently confirm that zones are units of its pricing
system. Same-zone stores start a record on the same day for 90% of shared products (68%
across zones) and in the same minute for 25% (6%). The effect holds for promotions, holds
beyond distance in a hierarchical model, and stores clustered on timing alone recover the
zones. Each zone is updated as a batch that walks its store list in store-number order,
almost never in the afternoon. A pre-registered event study of a scheduled nationwide
promotion expiry is in progress. Every method was first checked on simulated data.

## 1. Question

Under the law of one price, a chain selling an identical product would charge the same
everywhere. DellaVigna and Gentzkow (2019, *QJE*), using Nielsen scanner data, found that
US chains price nearly uniformly across stores despite large differences in local
demographics. We ask a complementary question with public data: **how is a chain's price
list organised across space, and how is it updated over time?**

There are three candidate architectures: one national list, a few discrete zones, or a
continuous gradient. If zones exist, are they the units in which prices are actually
*changed*? The answer differs by chain, and the methods needed to see it are the
contribution.

## 2. Data

**Cross-section** (snapshot 2, Oct 2–5, 2026). Store-specific prices for 58 national-brand
items, collected three ways:
- retailer websites (Walmart, Target, Meijer);
- Instacart storefronts (Costco, and ALDI's own Instacart-built site), which may include
  platform pricing and are reported separately;
- Kroger's official API, covering its banners (Kroger, Ralphs, Harris Teeter, Fry's,
  King Soopers, Dillons and others).

The items are 37 groceries, 15 non-grocery items and 6 perishables; cross-chain matches use
UPCs confirmed from two retailers' catalogues (Appendix A). The core sample is 250
locations drawn from Target's 1,893 stores, stratified by Census region × RUCA urbanicity.
Each other chain contributes the store it assigns to, or has nearest to, each location.
Kroger and Meijer were then extended with samples designed for their footprints.

We use regular prices to the cent, and only rows the retailer ties to the requested store.

| Chain | Stores | Store-item coverage | Note |
|---|---|---|---|
| ALDI | 205 | 100% | Instacart-built site |
| Costco | 175 | 100% | Instacart |
| Kroger family | 192 | 96% | official API; banner sample in progress (about 270) |
| Meijer | 83 | 100% | Michigan core (its locator blocks automated use) |
| Walmart | 84 | 99% | all 250 anchors (extended Oct 6–7) |
| Target | 28 | 16 matched items | short budgeted sessions (ongoing) |

**Timestamps and panels.** Kroger's API gives every price an *effective* and a scheduled
*expiration* timestamp; Meijer gives a sale's end date. The pre-registered event panels
(Kroger, 60 stores × 7 passes; Meijer, 15 stores × 3) and a Walmart repeat-visit panel (10
stores × 3 visits a day) cover Oct 5–8.

**Do requests reach the intended stores?**
- For every chain, the retailer's own attribution gives as many distinct pricing
  locations as stores requested.
- No two stores more than 1,000 km apart share a price list.
- Dissimilarity rises with distance in every chain.
- One Instacart fallback shop was found and excluded (Appendix A).

Collection is rate-limited (one request at a time per site, ≥ 5 s apart; 9 s for Kroger).
Every raw response is archived, and every failure is logged.

## 3. Methods

**Point mass and variogram.** The list price $\ell_j$ is the chain's modal price for product
$j$; departures are $\log(p_{sj}/\ell_j)$. For a pair of stores, the dissimilarity
$\delta_{st}$ is the share of shared products (at least 20) priced differently. Its mean by
distance band, with store-bootstrap bands, gives a price-list variogram, fitted with an
exponential nugget–sill–range model. When there is no plateau, we report none.

**Zones.** Each store's list is coded as which observed price level it charges for each
product, under a Dirichlet-process mixture:
- $z_s \sim \mathrm{CRP}(\alpha)$;
- $c_{sj} \mid z_s = k \sim \mathrm{Cat}(\theta_{kj})$;
- $\theta_{kj} \sim \mathrm{Dir}(\gamma g_j)$, where $g_j$ is the chain-wide level frequency (an
  empirical-Bayes base measure).

Levels charged by a single store are set aside. Inference: collapsed Gibbs (Neal 2000),
merge–split moves (Dahl 2005) and Escobar–West (1995) updates for $\alpha$, from two starts
compared by adjusted Rand index (ARI; Hubert and Arabie 1985). Zones are judged by
**split-half replication** (disjoint halves of the products) and **prior sensitivity**
($\gamma$ from 0.5 to 5), not by the posterior alone.

**Two-part spatial model.**
- Whether a price is at list: Bernoulli with store effects.
- Off-list departures: $t_\nu(\mu_c + u_s + f(x_s), \sigma)$, with $f$ a Matérn-3/2 Gaussian
  process (Hilbert-space approximation; Solin and Särkkä 2020).
- NUTS (Hoffman and Gelman 2014); spatial share $\operatorname{var} f / (\operatorname{var} f + \sigma_u^2)$; PSIS-LOO
  (Vehtari et al. 2017); posterior predictive checks.

**Timing.** For each store-product, the effective timestamp gives when the current price
record began.
- *Co-timing:* we compare same-zone and different-zone store pairs (same banner) on how
  many shared products began on the same day or minute. Zone labels are permuted within
  banner, so banners alone earn no credit.
- *Dyadic binomial model:* adds distance and store effects.
- *Timing-only clustering:* compared with the price zones by ARI.
- *Event study:* the scheduled expiry is pre-registered (§5.4).

**Simulation checks** (Appendix B), all run before the real results: tail-estimator
coverage 84–97%; exact zone recovery at a 3% product difference and one zone when there
are none; 13 of 16 two-part-model parameters inside their 90% intervals; the
promotion-length estimators (§5.3); the dyadic co-timing model (unbiased, 90% intervals
covering 80–90% in 10 replicates per scenario, and it removes the spurious zone effect
that distance alone creates in a naive comparison).

## 4. Results: space

| | ALDI (204) | Walmart (83) | Costco (174) | Kroger (191) |
|---|---|---|---|---|
| Prices at list | 91% | 92% | 76% | 65% |
| Departures upward (median) | 19% (−7.9%) | 75% (+4.9%) | 50% (+0.3%) | 66% (+4.5%) |
| $\delta$: stores < 50 km apart → > 2,000 km apart | 6.5% → 20% | 5.0% → 17% | 8.9% → 36% | 20% → 63% |
| Variogram range | no plateau | no plateau | ≈ 850 km | no plateau* |
| Zones | 10; largest 79 stores, 27 states | 12 (not robust) | 18 regional | 28, division-aligned |
| Nearby stores in the same zone vs permuted | 50% vs 20% | 59% vs 10% | 50% vs 6% | 48% vs 5% |
| Split-half replication (ARI) | 0.52–0.54 | 0.09–0.41 | 0.96 | 0.90–0.98* |

All spatial-coherence p = 0.001. *Kroger, 191 stores (banner sample in progress). Its
variogram had a plateau at about 240 km on the first 121 stores; with distant divisions
added it keeps rising (local zones within a nationwide gradient). Robustness checks
on 191 stores: split-half ARI 0.90–0.98; γ = 0.5 vs 1 ARI 0.95.

![Figure 1](../figures/fig_e1_price_list_variogram.png)
*Figure 1. Price-list variogram: share of shared products priced differently, by distance
between stores. Bands are 95% store-bootstrap intervals.*

**Four architectures.**
- **ALDI** runs one national list over most of the country, with regional zones
  (California, the Mid-Atlantic, Texas, Arizona/Nevada) (Figure 2). Its departures are
  mostly markdowns.
- **Walmart** has no identical store lists. Dissimilarity rises slowly and steadily with
  distance (5% for nearby stores, 17% across the country), and departures are mostly
  upward. Doubling the sample to 83 stores did **not** make discrete zones appear: the zone
  map still does not replicate (split-half ARI 0.09–0.41). Walmart prices on a gradient,
  not in zones.
- **Costco on Instacart** forms about 18 regional zones on a scale of about 850 km. They
  replicate almost perfectly: split-half ARI 0.96, and ARI 0.99 across priors.
- **Kroger** is the most local at short range (Figure 3). Stores within 100 km differ on
  8% of shared products within a banner and 72% across banners. The zones replicate
  (split-half ARI 0.90–0.98).

  **They follow Kroger's operating divisions even more closely than its banners.** The
  location id starts with a 3-digit division number. At 191 stores (16 banners, 20
  divisions, 28 zones):

  | Zones compared with | Purity | ARI | Zones inside one group |
  |---|---|---|---|
  | division | 95% | 0.71 | 89% |
  | banner | 89% | 0.51 | 82% |

  The "Kroger" banner spans 9 divisions and is split along them, while banners that share
  a division share zones (Food 4 Less and Foods Co; Dillons, Baker's and Gerbes). Prices
  alone recover the organisational pricing units.
- **Meijer** (71 stores, its Michigan core) is the most uniform chain.
  - 97% of prices sit at list.
  - Nearby stores differ on 0.1% of products, rising to only 4.9%.
  - Its 7 zones barely beat chance in space and do not replicate (split-half ARI
    0.28–0.69).

![Figure 2](../figures/fig_e3_zones_aldi.png)
*Figure 2. ALDI's price-list zones (Dirichlet-process mixture): one national list plus
regional zones.*

![Figure 3](../figures/fig_e4_kroger_banners_zones.png)
*Figure 3. Kroger-family stores by banner (left), and banner × zone counts (right). The zone
model never sees banners, yet most zones fall inside one banner (and more inside one
division).*

**Departures and extremes** (M2, Figure 4). The model is fitted to Kroger (191 stores),
Meijer (71) and Walmart (41): 12,108 prices, 78% at list. It converges (4 × 2,000 draws,
R-hat ≤ 1.005, no divergences).
- **Spatial share of store-level departure size:** Kroger 0.93 (90% interval 0.89–0.96);
  Walmart 0.49 (0.32–0.65); Meijer 0.13 (0.06–0.23). Kroger's departures are regional,
  while Meijer's are store-specific. Length-scale about 120 km.
- **Fit:** PSIS-LOO favours the spatial model by 80 ± 16 elpd. Departures are very
  heavy-tailed ($t_{\nu \approx 1.3}$).
- **Extremes:** the upper tail is mostly geographic. A Honolulu Walmart charges \$6.28
  for milk against a chain median of \$2.97. Without Hawaii and Alaska, Walmart's
  generalised-Pareto shape is about 0 ($\hat\xi = -0.04$, 95% CI −0.40 to 0.14).

![Figure 4](../figures/fig_b1_spatial_surface.png)
*Figure 4. Posterior mean of the spatial field $f$ in the two-part model: where off-list
prices are higher.*

**What predicts price levels? Not demographics.** We tried about 130 neighbourhood,
urbanicity and competition predictors, with state-blocked cross-validation. Out-of-sample
R² with the best shrinkage model:
- ALDI: about 0 (184 stores);
- Kroger: 0.11 (108 stores);
- Costco: 0.19 (163 stores; horseshoe).

The only clear Kroger coefficient is North Carolina (+2.3%), which is in effect the Harris
Teeter banner. Price levels show no urban–rural difference in any chain. Location matters
through the retailer's zone design, not local demographics, consistent with DellaVigna and
Gentzkow.

**Across chains.** On identical UPCs, medians vs Walmart:
- Target +0.5% (10 UPCs, 16 stores);
- Meijer +5.6% (17 UPCs, 71 stores; the same as with 3 stores, as a uniform list implies);
- Kroger +9.7% (16 UPCs, 191 stores; IQR +5.4 to +16.6).

One chain is cheapest on nearly every item, so splitting a 12-item basket across 2–3
nearby stores saves a median of **0.05%**. The test covers 88 locations, and the exact
integer program and the greedy heuristic agree everywhere. Cross-chain gaps are level
differences, so the violations of the law of one price leave almost no basket arbitrage.

## 5. Results: time (Kroger, n = 109,362 dated price records, 191 stores)

*What a timestamp measures.* Kroger's effective timestamp marks when the current price
**record** began. Comparing the same store-products on Oct 2–4 and Oct 5 (60 stores), 7.8%
of regular-price records (0.9% of promotions) got a new timestamp with an **identical**
price.
These re-entries come in store-level batches. So:
- the co-timing below describes the pricing system's **update batches**;
- regular-price "ages" are record ages, and true spells are longer;
- promotions are rarely affected.

The event study (§5.4) observes actual price changes.

**5.1 When price records start.**
- **Weekly calendar.** 89% of promotions and 54% of regular prices start on a Wednesday,
  the start of Kroger's ad week. 78% of promotions end on a Tuesday night, and 90% run a
  whole number of weeks.
- **Time of day.** By store-local time, 66% of price starts fall 03:00–08:00 and 20% fall
  08:00–12:00. **Only 2.3% of regular prices and 0.4% of promotions** start between noon
  and 21:00.

Records start in overnight and morning batches. 99.6% of promotions, which rarely reset,
start outside noon–21:00. We see no sign of the demand-driven ("surge")
intraday repricing feared with electronic shelf labels (Figure 5a). The Walmart repeat
visits agree: 1 price change in 5,790 transitions (§5.5).

**5.2 Zones change prices together.** Zones were estimated from price *levels* only, so
timestamps are an independent test of whether they are real units. The table uses
same-banner store pairs (1,535); p-values come from permuting zone labels within banner.

| Statistic | Same zone | Different zone | Evidence |
|---|---|---|---|
| Share of shared products whose current price record began the same **day** | 0.90 | 0.68 | p = 0.0003 |
| ... the same **minute** | 0.25 | 0.06 | p = 0.0003 |
| Same day, products at the same price / at different prices | 0.91 / 0.72 | 0.76 / 0.51 | holds at fixed price |
| Promotions only (real price changes; rarely reset): same day / same minute | 0.98 / 0.17 | 0.92 / 0.04 | p = 0.001 each |
| Hierarchical binomial model, odds ratio for same zone, day / minute | 1.59 / 1.75 | 1 | 90% intervals 1.50–1.69 and 1.38–2.21 |
| Stores clustered by co-timing alone, agreement with price zones (ARI) | 0.70 | 0.60 (permuted) | p = 0.001 |

The model controls for log distance, store effects (pairs sharing a store are dependent)
and pair-level overdispersion. NUTS: R-hat ≤ 1.006, no divergences. The zone effect is not
a by-product of sharing a price, of being close, or of record re-entries (it holds for
promotions): **prices and timestamps identify the same pricing units.**

Two exploratory findings sharpen this:
- **Division sets the day, zone sets the batch.**
  - Within the same division (1,354 pairs), the same-day share is 0.92 vs 0.87, and the
    same-minute share is 0.28 vs 0.16 (both p = 0.0005).
  - A division shares a calendar, but each zone is pushed as its own batch.
- **Each batch walks the store list in store-number order.** For products repriced on one
  day at every store of a zone, the order in which stores receive them agrees across
  products in all 24 zones tested.
  - Kendall's W median 0.62, vs about 0.003 under the null; median spread 9 minutes.
  - A store's position correlates with its store number at Spearman 0.92 on average,
    and exactly 1 in 13 of 21 zones. Location explains little (median |ρ| ≤ 0.40).

**Meijer, by contrast, runs one sale calendar** (71 stores; Meijer reports when each
store's sale price ends).
- For a given product, 99.7% of store pairs end the sale on the same date, and zones add
  nothing.
- 83% of sales end on a Tuesday, and 6,953 store-products end on Oct 6–7: the same night
  as Kroger's mass expiry (§5.4).

**5.3 How long do promotions last? One snapshot, four answers.** A snapshot sees only
promotions still running, so long promotions are over-represented (the inspection
paradox). Each correction relies on a different invariance, and they disagree (Figure 5b):
- naive mean 29.3 days;
- renewal theory from ages 18.4;
- length-bias correction $1/\mathbb{E}[1/L]$: 12.6;
- Lynden-Bell's product-limit estimator for left-truncated data: 9.4.

A simulation shows they agree under stationarity, and split in exactly this order when
one week's cohort has a different length mix (Appendix B). One snapshot cannot separate
cohort size from cohort mix. The event below sees a whole cohort when it starts.

![Figure 5](../figures/fig_g2_timing_lengths.png)
*Figure 5. (a) Store-local time at which Kroger price records take effect. (b) Mean promotion
length from one snapshot under four estimators.*

**5.4 A pre-registered event (in progress).** 9,326 snapshot-2 promotions at 113 stores are
scheduled to expire at one instant nationwide: Tuesday Oct 6, 23:59 Eastern.

Before any event data existed, we committed (`docs/PREREGISTRATION_EVENT.md`, commit
abce80e) the frozen zones, the 60 panel stores, analysis code tested on synthetic data,
and seven predictions:
- the expiry is enforced, at the instant;
- the expiration date predicts which prices change;
- the event night has at least 3 times the control night's change rate;
- new prices arrive in two batches;
- zones switch together;
- prices then settle.

Meijer's sales end the same night, so a 15-store Meijer arm (M1–M4) was pre-registered
before its data. Later addenda (all before event data) record a control-pass rerun, the
reporting code, and exploratory additions.

[result: Module H predictions table (`tables/module_h_predictions.md`) and Figure 6.]

**5.5 Walmart repeat visits (in progress).** Walmart publishes no price dates, so we
revisit 10 stores (17 confirmed items) three times a day from Monday to Thursday. Each
visit reaches the same 6–7 stores before Walmart's per-session limit (about 105 requests).
- **First 6 visits** (Mon 08:00 to Tue 20:00; 10 stores; the Tue 14:00 visit failed at
  store scoping):
  - **1 of 3,632** store-product transitions within a day changed price, and **0 of
    2,158 overnight**;
  - all 5,631 transitions from an off-list price stayed off list;
  - delivery-slot lead time follows the clock, not the store: 3–5 h during the day,
    10–12 h in the evening (the next slot is the following morning). Store explains none
    of its variance.
- **Still to measure:** change rates across the Tuesday-night ad-week boundary, and the
  persistence of local departures over several days (a two-state Markov chain).

[result: Module I tables.]

## 6. Limitations

- **Mostly cross-sectional.** Nothing is causal. Timing comes from Kroger's reported
  timestamps, and an effective date can reset when an unchanged price is re-entered (7.8%
  of regular-price records in 1–3 days, measured). The event panel observes actual
  changes.
- **Website prices,** not shelf audits. Costco's local structure may partly be
  Instacart's.
- **Partial chains.** Walmart (41 stores) and Target (16) limited automated access at low
  volume; they are spread across strata by design, but small. Meijer (83) is a regional
  sample of its Michigan core.
- **Sampling.** Locations come from Target's footprint, which over-represents urban areas
  for the other chains. Items are hand-picked national brands.
- **Zone model.** Products are treated as independent within a zone, so posterior
  certainty about the number of zones is overstated. The replication checks address this.
- **Locations** are mostly ZIP centroids. Timestamp results are for Kroger (with Meijer
  sale ends); Walmart timing comes only from repeat visits.

## 7. Reproducibility

The raw archive rebuilds the database (`python -m collectors.reparse`), and
`python run_all.py` regenerates every table and figure. Simulation checks live in
`simulation/`, decisions are logged in `docs/DECISIONS.md`, and the event
pre-registration is in `docs/PREREGISTRATION_EVENT.md`.

## References

- Cox, D. R. (1962). *Renewal Theory*. Methuen.
- Dahl, D. B. (2005). Sequentially-allocated merge-split sampler for conjugate and
  nonconjugate Dirichlet process mixture models. Technical report, Texas A&M University.
- DellaVigna, S., and Gentzkow, M. (2019). Uniform pricing in U.S. retail chains.
  *Quarterly Journal of Economics* 134(4), 2011–2084.
- Edelsbrunner, H., and Harer, J. (2010). *Computational Topology: An Introduction*.
  American Mathematical Society.
- Escobar, M. D., and West, M. (1995). Bayesian density estimation and inference using
  mixtures. *Journal of the American Statistical Association* 90(430), 577–588.
- Hill, B. M. (1975). A simple general approach to inference about the tail of a
  distribution. *Annals of Statistics* 3(5), 1163–1174.
- Hoffman, M. D., and Gelman, A. (2014). The No-U-Turn sampler. *Journal of Machine
  Learning Research* 15, 1593–1623.
- Hubert, L., and Arabie, P. (1985). Comparing partitions. *Journal of Classification* 2,
  193–218.
- Lynden-Bell, D. (1971). A method of allowing for known observational selection in small
  samples applied to 3CR quasars. *Monthly Notices of the Royal Astronomical Society* 155,
  95–118.
- Neal, R. M. (2000). Markov chain sampling methods for Dirichlet process mixture models.
  *Journal of Computational and Graphical Statistics* 9(2), 249–265.
- Pickands, J. (1975). Statistical inference using extreme order statistics. *Annals of
  Statistics* 3(1), 119–131.
- Piironen, J., and Vehtari, A. (2017). Sparsity information and regularization in the
  horseshoe and other shrinkage priors. *Electronic Journal of Statistics* 11(2),
  5018–5051.
- Solin, A., and Särkkä, S. (2020). Hilbert space methods for reduced-rank Gaussian process
  regression. *Statistics and Computing* 30, 419–446.
- Vehtari, A., Gelman, A., and Gabry, J. (2017). Practical Bayesian model evaluation using
  leave-one-out cross-validation and WAIC. *Statistics and Computing* 27, 1413–1432.
- Woodroofe, M. (1985). Estimating a distribution function with truncated data. *Annals of
  Statistics* 13(1), 163–177.

---

## Appendix A. Data checks

**Item matching.**
- The canonical UPC comes from Kroger and Meijer, which report a UPC for every product.
  They agree on 22 items, and 37 of 52 cross-chain items have a canonical UPC.
- Walmart products are confirmed by the UPC on their product page (17 items).
- Target products are matched by name and size (21 items; weaker evidence).
- Variant, multipack and store-brand candidates are rejected by rule, and seven fields
  were vetoed by hand.

**Store attribution.** Distinct pricing locations equal stores requested: ALDI 205/205,
Costco 175/175, Kroger 108/108 at the check, Walmart 42/42.

**Locations.** For Target, Walmart, Kroger and Meijer, a store's location comes from the
retailer. Instacart returns no address, so the anchor ZIP stands in. Costco anchors lie a
median of 7 km from a real Costco (OpenStreetMap).

**Fallback shop.** One ALDI location was returned for 37 ZIPs from Washington to Hawaii, all
without a nearby ALDI. It was excluded by a documented rule (more than 300 km between
anchors).

**Promotions.** A price is a promotion when the retailer reports a regular price above
the current one. Multi-buy offers are recorded but not treated as prices.

**Session policy.** A fresh session refused on its first request counts as a block and
triggers a pause of 3 h, then longer on repeats. A session refused after it has worked is
replaced at most twice per run.

Target refused sessions after about 50 requests (three tests: 50, 51, 51). A fresh session
completed every run, and no test triggered a counted block.

## Appendix B. Methods detail and validation

**Variogram.** $\gamma(h) = \text{nugget} + (\text{sill} - \text{nugget})(1 - e^{-h/r})$.
Pairs sharing a store are dependent, so bands come from a store bootstrap.

**Zones.**
- H0 persistent homology (Edelsbrunner and Harer 2010) of the single-linkage filtration of $\delta$ gives a
  model-free view of the zones.
- In the Dirichlet-process model, zones with identical estimated lists are merged,
  because they are not identifiable.
- Spatial coherence compares how often stores < 250 km apart share a zone against
  permuted labels.

**Prior sensitivity of the zones.**
- Kroger (191 stores): $\gamma = 0.5$ vs 1 gives ARI 0.95; $\gamma = 5$ merges zones
  (27 → 17).
- ALDI: 7–11 zones across $\gamma$. With 91% of prices at list and 0.6% unique to one
  store, each store carries little information.
- Walmart: 4–6 zones.

**Two-part model history.** Two simpler models failed to converge on real data:
- a single Student-$t$ residual (R-hat about 3);
- a latent mixture that label-switched.

Those failures revealed the point mass. The reference normal model (M0) still does not
converge. With only 2 UPCs shared between chains, the chain effect is omitted.

**Tails.** Hill (1975) ($k = 5\%$, with stable-$k$ and $k = 10\%$ sensitivity) and
generalised-Pareto (Pickands 1975) estimates with store-cluster bootstrap intervals. At $n = 250$, the
$k = 5\%$ Hill interval covered the true value 84–97% of the time.

**Predictors.** We compare OLS, lasso, elastic net and a regularised horseshoe (Piironen and Vehtari 2017). Low-rank
factor structure in the store × product deviation matrix is supported for ALDI (rank 4),
Costco (3) and Kroger (8), but not for Walmart (cross-validation picks rank 0).

**Promotion-length estimators.**

| Estimator | Mean (days) | Assumes |
|---|---|---|
| Naive mean of planned lengths | 29.3 | nothing (length-biased) |
| Renewal theory from ages, $\mu = 1/f_A(0)$ (Cox 1962) | 18.4 | stationarity |
| Length-bias correction, $1/\mathbb{E}[1/L]$ | 12.6 (12.5–12.8) | equal weekly cohorts |
| Lynden-Bell (1971) product-limit, left-truncated at age (Woodroofe 1985) | 9.4 (9.2–9.7) | same length mix each week |

Intervals are 95% store bootstrap.

In a 200-replication simulation, the corrections agree under stationarity. When one
week's cohort has a different length mix, ages-only is biased up (+2.8 days on a
15.5-day truth), Lynden-Bell down (−0.7), and the harmonic mean stays close. In the data,
age / planned length (uniform under stationarity) has mean 0.58, and the most recent
weekly cohort is smaller than the one before.

**Posterior co-clustering** (Figure B1, `figures/fig_e5_kroger_psm.png`). Only 0.1% of
Kroger store pairs have a posterior same-zone probability between 0.1 and 0.9. The model
is confident (likely overconfident; products are treated as independent), which is why
replication, not the posterior, is our evidence for the zones.

**Update batches** (exploratory). Grouping Kroger's current prices by the minute they took
effect gives 10,068 batches (108,370 store-products).
- They are very uneven: median size 3, 99th percentile 141, maximum 985 (24 stores × 76
  products).
- The largest 1% of batches carry 24% of all prices, and the largest 10% carry 66%.
- The Hill tail index falls with $k$: 1.70 (95% bootstrap 1.46–1.92) at $k$ = 2%, 1.39
  (1.28–1.50) at 5%, 1.16 (1.09–1.23) at 10%. That is a heavy, infinite-variance tail
  that is not a clean power law.
- Caveats: only prices still in force are seen, and zones updated in the same minute
  merge into one batch.

**Timing details.**
- Regular-price *records* have a renewal-estimated mean of about 35 days, which is a
  lower bound for true price spells because records reset. The age tail has
  Hill $\hat\alpha \approx 2.3$ (2.2–2.4).
- Kroger reports stock levels for 81% of store-products: 61% HIGH, 12% LOW, 9% out of
  stock. These shares are the same for promotions and regular prices.
- Promotion-length simulation: `simulation/validate_promo_lengths.py` (stationary,
  varying cohort sizes, varying length mix).
