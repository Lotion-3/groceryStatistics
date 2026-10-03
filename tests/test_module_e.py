"""Module E building blocks on synthetic price lists (test-only)."""
import numpy as np
import pandas as pd

from analysis import module_e_architecture as E


def test_two_zones_show_as_two_long_h0_bars():
    rng = np.random.default_rng(0)
    base = rng.uniform(1, 10, 60).round(2)
    zone_b = base.copy()
    zone_b[:30] = (zone_b[:30] * 1.05).round(2)            # zone B differs on half the products
    rows = [base] * 6 + [zone_b] * 5
    M = pd.DataFrame(rows)
    F, C = E.dissimilarity(M)
    assert np.nanmax(F[:6, :6]) == 0 and np.nanmin(F[:6, 6:]) > 0.4
    deaths = E.h0_barcode(F)
    assert E.components_at(deaths, len(M), 0.01) == 2
    assert E.components_at(deaths, len(M), 0.6) == 1


def test_pairs_with_too_few_shared_products_are_missing():
    M = pd.DataFrame([[1.0] * 25 + [np.nan] * 25, [np.nan] * 25 + [1.0] * 25, [1.0] * 50])
    F, C = E.dissimilarity(M)
    assert np.isnan(F[0, 1]) and F[0, 2] == 0 and C[0, 2] == 25


def test_zone_model_recovers_two_zones_and_merges_identical_lists():
    from analysis.zone_model import adjusted_rand, fit_zones
    rng = np.random.default_rng(1)
    base = rng.integers(0, 3, 120).astype(float)
    zone_b = base.copy()
    zone_b[:15] = 9                                   # zone B differs on 15 of 120 products
    truth = np.array([0] * 12 + [1] * 10)
    M = np.array([base if t == 0 else zone_b for t in truth], float)
    M[rng.random(M.shape) < 0.1] = np.nan
    r = fit_zones(M, n_sweeps=60, burn=20, thin=2, seed=0)
    assert adjusted_rand(truth, r["partition"]) == 1.0 and r["start_agreement_ari"] == 1.0
    same = np.array([base] * 15, float)               # one list everywhere -> one zone
    assert len(np.unique(fit_zones(same, n_sweeps=40, burn=10, thin=2, seed=0)["partition"])) == 1
