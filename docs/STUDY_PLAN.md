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
| Q4 | Dynamics: do stores in a zone change prices together? | effective/expiration timestamps (dates, minutes, timing-only clustering); **pre-registered promotion-expiry event** panel | G, H | timestamps done (strong); event Oct 5–8 |
| Q5 | Law of one price across chains | same-UPC spreads at paired anchors; basket MILP | A, D | needs the item review |
| Q6 | What predicts departures and zones? | horseshoe vs lasso vs elastic net, CV blocked by state; factor model | C | done: covariates weak (out-of-sample R² 0–0.19) |
| Q7 | Price timing: when do prices change, and how long do they last? | local time of day; renewal theory vs length-bias vs Lynden-Bell under left truncation (simulation-checked); a cohort observed when it starts | G, H | one-snapshot results done; cohort at the event |

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

## Zones (Dirichlet-process mixture; snapshot 2 partial; PRELIMINARY)

The model was checked on simulated price lists first (`tables/simulation_zone_model.csv`).
It recovers 3–6 zones exactly, even when zones differ on only 3% of products and stores
add their own noise. It finds one zone when there are none, and degrades gracefully when
zones differ on 1% of products (ARI 0.78).

| | ALDI (53 stores) | Walmart (41) | Costco/Instacart (101) |
|---|---|---|---|
| Distinct zones | 7 | 5 | 15 |
| Largest zone | 28 stores, 16 states | 17 stores, 9 states | 15 stores (Upper Midwest) |
| Notable zones | CA (9), AZ (4), TX (3), Mid-Atlantic (5) | CA (9), Mountain/Southwest (8) | NE corridor, Southeast, TX, several CA |
| Nearby stores (< 250 km) in the same zone | 78% vs 32% permuted (p = 0.001) | 78% vs 25% (p = 0.001) | 50% vs 7% (p = 0.001) |

Caveats:
- **The posterior number of zones is very concentrated.** The model treats products as
  independent within a zone, so this certainty is probably overstated.
- **Not every zone is contiguous.** One Walmart zone spans the Mountain West and the
  Northeast, which suggests market type as well as geography.

## Final snapshot-2 numbers (run_all, 2026-10-04 04:18; PRELIMINARY)

The tables above are from partial passes. The final pass covers ALDI 204, Walmart 41,
Costco 174, Kroger 121 and Target 16 stores (contiguous US). See `paper/writeup.md` §4.

| | ALDI | Walmart | Costco/Instacart | Kroger |
|---|---|---|---|---|
| Prices at list | 91% | 91% | 76% | 59% |
| Variogram range | no plateau | no plateau | ≈ 850 km | ≈ 240 km |
| Zones | 10 | 5 | 18 | 21; 94% banner purity |

Other results:
- **Module B (M2):** R-hat 1.007, minimum ESS 354. Spatial share: Kroger 0.99, Walmart 0.74.
  Length-scale about 93 km. LOO favours M2 by 20 ± 12 elpd.
- **Module C:** covariates weak; out-of-sample R² −0.03 (ALDI), 0.11 (Kroger), 0.19
  (Costco).
- **Module D:** splitting a basket saves a median of 0.05%.
- **Law of one price, gap vs Walmart:** Target +0.5% (16 stores), Meijer +5.6%, Kroger +9.8%.
- **Module G (timing):**
  - same start date within vs across zones 0.87 vs 0.66; same minute 0.16 vs 0.03;
  - timing-only clusters vs price zones: ARI 0.58 vs a 0.43 baseline, p = 0.001;
  - 2.5% of regular price starts fall between noon and 21:00 local.

## Next (updated 2026-10-04 night)

1. **Kroger event (Q4, Q7):** control pass Mon Oct 5, before Tue Oct 6, probes around the
   expiry at Tue 23:59 Eastern, after Wed Oct 7, late Thu Oct 8. Then run Module H,
   unchanged, and report all seven predictions.
2. Kroger banner sample: until Mon 09:30, resuming after the event. Then refit the zones
   (reported separately from the frozen pre-registered zones).
3. Owner decisions pending:
   - a Meijer store sample (about 5,000 searches);
   - a small Walmart repeat-visit panel (T2/T3; the parser now keeps slot and stock
     fields).
4. Final write-up around Q1–Q7, about Oct 9.
