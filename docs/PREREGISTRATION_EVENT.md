# Pre-registration: the Kroger promotion expiry of 2026-10-06

Written 2026-10-04, about 01:45 Eastern, **before any data from the event was collected**.
The commit containing this file, `config/prereg_kroger_zones.csv`,
`config/kroger_panel.csv`, `config/kroger_event_probe.csv` and
`analysis/module_h_event.py` fixes the predictions, the zones, the stores and the
analysis code. Anything decided after the data arrive is labelled *post hoc* in the
write-up. DECISIONS #51.

## The event

Kroger's API gives each price a scheduled `expirationDate`. In snapshot 2 (Oct 2–4):
- **9,326 promotions** at 113 Kroger-family stores (375 products) are scheduled to expire
  at **2026-10-07T03:59:59Z**: Tuesday Oct 6, 11:59 pm Eastern.
- This is the same instant at stores in every time zone (checked in CA, WA, CO, AZ, TX, IL,
  OH, GA and VA).
- Regular prices carry the placeholder expiry 9999-12-31.
- At the 60 panel stores, 4,721 of 34,785 store-products have a promotion ending at the
  event.

**Prior evidence used to write the predictions** (snapshot 2 only):
- **Promotion lengths** are whole weeks: 7, 14, 28 or 56 days most often.
- **Expiry days:** 80% of promotions end on a Tuesday night.
- **Start days:** 89% of promotions and 54% of regular prices start on a Wednesday.
- **Timing of last week's changes.** Prices that took effect on Wednesday Sep 30 did not
  start at midnight:
  - about 27% of promotions and 39% of regular prices started Tuesday about 22:00 Eastern;
  - most of the rest started 04:00–10:00 Eastern on Wednesday.
- **Zones and timing:**
  - same-banner store pairs in the same price zone share a price start *date* for 0.87 of
    their shared products, against 0.62 across zones (Module G);
  - given the same date, they share the start *minute* 27% of the time vs 8.6%.

## Data (scripts/run_kroger_event.ps1)

Kroger production API, 60 panel stores (`config/kroger_panel.csv`, chosen on 2026-10-04
before the event was known), all 58 items. Times are Eastern.

| Pass | Start | Role |
|---|---|---|
| control | Mon Oct 5 10:00 | baseline; Mon→Tue has no scheduled expiry |
| before | Tue Oct 6 11:00 | state just before the event |
| probe pre | Tue Oct 6 22:30 | 204 store-item queries at 12 stores, all with a promotion ending at the event |
| probe post | Wed Oct 7 00:15 | same queries, just after the expiry |
| probe early | Wed Oct 7 05:00 | same queries, during the usual morning batch |
| after | Wed Oct 7 10:00 | state after the event |
| late | Thu Oct 8 10:00 | one day later |

## Definitions (fixed in advance)

- **Unit:** a store-product, i.e. a (store, Kroger product id) pair observed in both passes
  being compared.
- **Scheduled:** in the *before* pass, the store-product shows a promotion
  (promo < regular) whose `expirationDate` is 2026-10-07T03:59:59Z.
- **Changed** between two passes: the shelf price (promo if present, else regular)
  differs, or the price's `effectiveDate` differs. The **price-change** outcome uses the
  shelf price only.
- **Old promotion gone:** the after-pass record does not show the same promo price with the
  same `effectiveDate`.
- **Renewed:** an old promotion is gone and a promotion is present again with a new
  `effectiveDate`.
- **Zones:** frozen in `config/prereg_kroger_zones.csv`: the Dirichlet-process zones
  fitted to snapshot-2 regular prices only (Module E method). Zone tests use **same-banner
  store pairs only**; zone labels are permuted within banner (4,999 permutations,
  one-sided).

## Predictions

**H1 Enforcement.** Of the scheduled units seen in the before and after passes, at least
95% have the old promotion gone in *after*.

**H2 Predictiveness.** Price-change rate before→after:
- scheduled units: at least 0.80;
- units with no promotion or a promotion expiring later: at most 0.15.

**H3 Event vs control.** The share of all units whose shelf price changes is at least
3 times higher before→after than control→before.

**H4 Expiry at the instant.**
- In the *probe post* pass (00:15 Eastern), at least 90% of probed scheduled promotions
  are gone. The scheduled expiry is enforced at the instant, not in the morning batch.
- In *probe pre*, at least 90% are still present.

**H5 Two batches.**
- Among new prices that appear for scheduled units by the *after* pass, at least 15%
  have an `effectiveDate` before the expiry instant (pushed Tuesday evening).
- At least 50% have one between 04:00 and 11:00 Eastern on Wednesday.

**H6 Zones change together.** Among same-banner pairs where both stores changed the same
product before→after:
- (a) the new `effectiveDate` agrees to the minute more often within a zone than across
  zones;
- (b) the new shelf price is identical more often within a zone than across zones.

Each is a one-sided permutation test, at α = 0.05 per test.

**H7 Settling.** The change rate after→late is at most the control→before rate.

## Estimated without a directional prediction

- The **renewal share** (renewed / scheduled), with a store-cluster bootstrap CI, by banner.
- **Discount depth** of renewals vs the expired promotions.
- **Stock levels:** the share LOW or TEMPORARILY_OUT_OF_STOCK, for scheduled vs other units,
  in before vs after.
- **Change-rate heterogeneity** across banners and zones: a hierarchical logistic model
  with banner and zone effects.

## Reporting

All seven predictions are reported whether they hold or not, with n and preliminary
labels. Missed passes (API errors, hard stops) are reported. Units not observed in both
passes of a comparison are dropped and counted.

## Addendum 1 (2026-10-04, about 02:10 Eastern; after commit af68714, before any event data)

**Added estimand: the promotion cohort observed when it starts.**

New promotions in the *after* pass are those with `effectiveDate` between 2026-10-06
22:00 and 2026-10-07 12:00 Eastern. Their planned lengths (expiration − effective) are
observed in full when they start: no truncation and no length bias. We will report:
- their mean length and length distribution, with a store-cluster bootstrap CI;
- a comparison with the three one-snapshot estimators from snapshot 2 (ages-only 18.4,
  harmonic 12.7, Lynden-Bell 9.4 days).

No directional prediction. The simulation (`simulation/validate_promo_lengths.py`)
expects the cohort mean to lie between the Lynden-Bell and ages-only values if cohorts
differ in length mix. That cohort is a single week, so it describes this week's mix, not
the long-run mean.

## Addendum 2 (2026-10-04, about 02:05 Eastern; before any event data): bug fix

A dry run of `module_h_event.py` on real snapshot-2 rows (every pass set to snapshot 2,
so nothing changes) showed a bug: when both the control and the event change rates were
0, H3's ratio was infinite and counted as holding. The ratio is now undefined (not
holding) in that case. No prediction, definition or threshold changed.

## Addendum 3 (2026-10-05, about 16:55 Eastern; before any event data): control pass rerun

The scheduled control pass (Mon Oct 5 10:00) collected nothing. PowerShell's
Start-Process split the multi-word `--note "kroger event control"` into separate
arguments, and the script rejected them, so it failed at start (logged in
`kroger_event_control_pass.log.err`). Every later pass would have failed the same way.

**Fix:** `scripts/kroger_panel.py` accepts a multi-word `--note`. The running pipeline
starts Python afresh for each pass, so the before, probe, after and late passes pick up
the fix.

**Deviation:** the control pass was rerun at 16:51 Mon Oct 5 (snapshot 6), with a hard
stop at Tue Oct 6 10:45 (`scripts/run_kroger_control_rerun.ps1`).
- The control→before comparison (H3, H7) still spans an interval with no scheduled
  expiry. It is about 18 h long instead of 25 h; H3 compares change *rates* per
  transition, not per hour.
- If the rerun is cut short, H3 and H7 use the store-products observed in both passes,
  as defined.

No prediction, definition or threshold changed.

**Also noted:** the laptop entered Modern Standby with the network off from 01:36 to
09:34 on Oct 5, which froze the collectors. A pass delayed by standby still runs, and
probe windows that are missed are reported as missed.

## Addendum 4 (2026-10-05, about 19:20 Eastern; before any Meijer event data): Meijer arm

The owner approved Meijer event passes (DECISIONS #53). The 15 Meijer stores are the
first 15 rows of `config/meijer_sample.csv` (farthest-point order). Each pass prices all
items through Constructor.io search: control Mon Oct 5 19:30, before Tue Oct 6 18:00,
after Wed Oct 7 12:00.

Snapshot 2 shows that Meijer reports, per store price, the date a sale price is good
through. 99.7% of store pairs share that date for a given product, and 4,936
store-products end their sale on 2026-10-06.

**Definitions.**
- *Scheduled:* in *before*, a sale price (good-through date before 2090) with
  good-through date 2026-10-06.
- *Changed:* the shelf price differs, to the cent.
- *Unit:* a (store, product) pair seen in both passes being compared.

**Predictions** (same thresholds as the Kroger arm):
- **M1** At least 80% of scheduled units change price before→after.
- **M2** The change rate before→after is at most 0.15 for units not scheduled.
- **M3** The share of all units whose price changes is at least 3 times higher
  before→after than control→before.
- **M4** One calendar: among products with a scheduled unit at 2 or more stores, at least
  90% have the same new (after) price at every store observed. Meijer is near-uniform:
  97% of prices at list.

Analysis: `analysis/module_h_event.py`, function `meijer_event`, written after this
addendum and before the data.

## Addendum 5 (2026-10-05, evening; before the before/after passes): reporting only

`module_h_event.py` gained reporting functions: per-transition change rates, a markdown
predictions table, and the event figure. They were tested on synthetic data. No
definition, prediction, threshold or test changed.
