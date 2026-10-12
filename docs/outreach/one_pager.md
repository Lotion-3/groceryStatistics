# How Retail Chains Price Across Space and Time

*One-page summary. Laksh Agarwal, Purdue. Preliminary results, October 2026.
Repository: [link]. Full write-up: `paper/writeup.md`.*

**Question.** For an identical product, how does a chain's price vary across its stores,
and how is its price list updated over time?

**Data.**
- Store-specific prices for 58 national-brand items: six US chains, 15–205 stores each
  (about 700 stores).
- Kroger's official API supplies, for every price, an effective and an expiration
  timestamp (109,362 dated price records at 191 stores).
- A pre-registered event panel follows a scheduled nationwide promotion expiry.
- All collection is rate-limited and every raw response is archived. Each method was
  validated on simulated data before use.

**Findings so far.**
1. **Prices are a point mass plus structured departures.** 91% of prices at ALDI and
   Walmart, and 65% at Kroger, sit *exactly* at the chain's list price.
2. **Four architectures.** We used a Dirichlet-process mixture that recovers pricing zones
   from prices alone, with split-half replication and prior sensitivity, plus a price-list
   variogram.
   - **ALDI:** a national list with regional zones.
   - **Walmart:** a gradient.
   - **Costco on Instacart:** about 18 regional zones.
   - **Kroger:** local zones nested in its operating divisions (95% purity; split-half
     ARI 0.90–0.98), although the model never sees banners or divisions.
   - **Meijer:** almost one list.
3. **Timestamps independently confirm the zones.** Same-zone Kroger stores start a price
   record in the same minute 4× as often as other same-banner stores (0.25 vs 0.06,
   permutation p < 0.001).
   - This holds for promotions, which are real price changes.
   - It holds beyond distance in a hierarchical binomial model of store pairs (odds
     ratio 1.6–1.75, simulation-validated).
   - Clustering stores on timing alone recovers the price zones.
4. **Microstructure.** Each zone is updated as a batch that walks its store list in
   store-number order (Spearman ρ = 1 in 13 of 21 zones). Updates happen overnight, almost
   never in the afternoon. A Walmart repeat-visit panel finds almost no repricing
   (3 changes in 11,725 store-product transitions over 9 visits).
5. **One snapshot, four answers.** Mean promotion length is 29.3, 18.4, 12.6 or 9.4 days,
   depending on which invariance is assumed: naive, renewal theory, length-bias
   correction, or Lynden-Bell's estimator for left-truncated data. A simulation explains
   the ordering.
6. **Pre-registered event.** 9,326 promotions were scheduled to expire at one instant
   nationwide (Tue Oct 6, 23:59 Eastern). Seven predictions were committed before any
   data, tested on 60 stores (34,177 store-products). **9 of 10 testable predictions
   hold.**
   - The expiry was enforced within 16 minutes, and the expiration date predicted which
     prices moved (90% of scheduled units vs 14% of others).
   - The event night had 46× the control night's change rate.
   - Same-zone stores chose the same new price (p = 0.0002).
   - **Failed:** zones did not significantly share the new effective minute (p = 0.06).
     A predicted "Tuesday-evening batch" turned out to be a single division's practice.
   - We observed the new promotion cohort directly: 42% of expiring promotions were
     renewed, with a planned mean length of 18.7 days.

**Honest limits.** Mostly cross-sectional; nothing causal. Kroger timestamps partly
reflect record re-entries (measured: 7.8% of regular-price records in 1–3 days). Walmart
and Target samples are small.

**Methods used.** Dirichlet-process mixtures (collapsed Gibbs, merge–split), Hilbert-space
Gaussian processes in a two-part Bayesian model (NUTS, PSIS-LOO), Hill and
generalised-Pareto tail estimation, renewal theory and left truncation, regularised
horseshoe vs lasso with state-blocked cross-validation, persistent homology, permutation
tests, and an integer program for basket arbitrage.
