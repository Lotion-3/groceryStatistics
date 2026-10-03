# Study plan (reformulated 2026-10-03)

**Working title:** *How retailers price across space: national lists, pricing zones and local
departures, measured from public store-level prices.*

## Why the plan changed

The original plan measured price dispersion as a continuous, possibly heavy-tailed spread.
The data show something sharper:
- Most store prices equal the chain's list price exactly (ALDI 92%, Walmart 91%).
- Departures are structured, and the structure differs by chain: discrete zones at ALDI, a
  distance gradient at Walmart, strongly local variation at Costco on Instacart.

The study therefore asks **how each chain's price list is organised across space**. Heavy
tails become one part of it (the tail of departures), and the extreme tail is largely
geography (Hawaii).

Related work: DellaVigna and Gentzkow, "Uniform Pricing in U.S. Retail Chains" (*QJE*
2019), found near-uniform pricing within chains using Nielsen scanner data. Our
contribution is from public data and is methodological: zone recovery, the price-list
variogram, a two-part spatial model, and topology on price-list dissimilarity, each checked
on simulated data.

## Data (what is realistically collectable by day 7)

| Source | Role |
|---|---|
| Kroger, official production API (≤ 10,000 calls/day) | backbone: legitimate, store-level, UPCs, promo prices; also the daily repeat panel (Q4) |
| ALDI (Instacart-built site) | clearest zone structure |
| Costco (Instacart) | local-pricing contrast (Instacart caveat) |
| Walmart, Target, Meijer | partial chains via budgeted sessions; the cross-chain panel |
| Optional: 4–5 Instacart chains (Safeway/Albertsons, Publix, H-E-B, Hy-Vee, Wegmans) | breadth for Q1–Q2: architecture across 8–10 chains |
| ACS 2023 5-year, RUCA, OpenStreetMap | covariates |

Every chain's stores are a prefix of the balanced visit order (DECISIONS #40), so whatever
is collected is a stratified, spread-out sample.

## Questions

| # | Question | Method | Module | Status |
|---|---|---|---|---|
| Q1 | Architecture: one list, zones or gradient? | point mass; **price-list variogram** with store-bootstrap bands | E | done (first pass) |
| Q2 | Can zones be recovered from prices alone? | **H0 persistence** of price-list dissimilarity; Dirichlet-process mixture over store price lists (simulation-checked) | E (+ new) | H0 done; DP model next |
| Q3 | Departures and extremes | two-part Bayesian model with spatial field; extreme values of departure size; Hawaii | B, A | built, validated |
| Q4 | Dynamics: do stores in a zone change prices together? | Kroger daily panel; within- vs across-zone synchronisation | new | needs the daily panel |
| Q5 | Law of one price across chains | same-UPC spreads at paired anchors; basket MILP | A, D | needs the item review |
| Q6 | What predicts departures and zones? | horseshoe vs lasso vs elastic net, CV blocked by state; factor model | C | built |

## First results (snapshot 2, partial; PRELIMINARY)

Contiguous US; regular prices; products seen at ≥ 10 stores.

| | ALDI (50 stores) | Walmart (41) | Costco/Instacart (99) |
|---|---|---|---|
| Share of prices at list | 92% | 91% | 76% |
| Departures upward | 29% (median −5.4%) | 76% (median +4.8%) | 52% (median +0.5%) |
| Price lists differ, stores < 50 km apart | 1.3% | 5.3% | 7.4% |
| … stores > 2,000 km apart | 17% | 21% | 36% |
| Variogram plateau | none within the US | none within the US | yes, range ≈ 880 km |
| Groups at 1% tolerance (H0) | 20; largest 23 stores | 41 (none) | 99 (none) |
| Nearby urban–rural vs same-type pairs | 6.0% vs 4.7% (p = 0.23) | 7.4% vs 5.4% (p = 0.03, exploratory) | 11.4% vs 14.3% (p = 0.92) |

Reading:
- **ALDI:** a national list with discrete regional zones.
- **Walmart:** a slow continuous gradient, with nearby urban and rural stores on different
  lists. The urban–rural result is a hypothesis to confirm.
- **Costco on Instacart:** highly local. This may reflect Instacart's pricing as much as
  Costco's.

## Next

1. Dirichlet-process mixture zone model with a simulation check (Q2).
2. Kroger: finish the pass, then the daily panel for Q4. That depends on the owner's go-ahead.
3. Item review, then the cross-chain panel (Q5).
4. Restructure the write-up around Q1–Q6.
