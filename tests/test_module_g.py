"""Module G (price timing) estimators and zone-timing tests on synthetic data."""
import numpy as np
import pandas as pd

from analysis.module_g_timing import codating, timing_clusters
from simulation.validate_promo_lengths import BASE_P, LENGTHS, est_harmonic, est_lynden, simulate


def test_promo_length_estimators_unbiased_under_stationarity():
    rng = np.random.default_rng(1)
    a, L = simulate(rng, [5000.0] * 20, [BASE_P] * 20)
    true_mu = float(LENGTHS @ BASE_P)
    assert abs(est_harmonic(a, L) - true_mu) < 0.6
    assert abs(est_lynden(a, L) - true_mu) < 0.6
    assert L.mean() > true_mu + 5          # the naive mean is length-biased upward


def _timing_data(seed=0, n_products=40):
    """2 banners x 3 zones x 4 stores; stores in a zone share effective times,
    stores in different zones of the same banner do not."""
    rng = np.random.default_rng(seed)
    stores = np.arange(1, 25)
    zone = (stores - 1) // 4
    banner = np.where(stores <= 12, "KROGER", "RALPHS")
    base = pd.Timestamp("2026-09-30T10:00Z")
    rows = []
    for p in range(n_products):
        zone_time = {z: base - pd.Timedelta(days=int(rng.integers(0, 30)), minutes=int(rng.integers(0, 600)))
                     for z in range(6)}
        for s, z, b in zip(stores, zone, banner):
            t = zone_time[z] if rng.random() < 0.9 else base - pd.Timedelta(days=int(rng.integers(30, 90)))
            rows.append({"store_pk": s, "chain_product_id": f"P{p}", "eff": t, "banner": b})
    return pd.DataFrame(rows), pd.Series(zone, index=stores)


def test_codating_detects_zone_synchronisation():
    k, zones = _timing_data()
    rng = np.random.default_rng(2)
    for unit in ("date", "minute"):
        r = codating(k, zones, rng, n_perm=199, unit=unit)
        assert r["codated_share_same_zone"] > r["codated_share_diff_zone"] + 0.5
        assert r["p_value_one_sided"] <= 0.01


def test_codating_null_when_zones_are_random():
    k, zones = _timing_data()
    rng = np.random.default_rng(3)
    # zone labels unrelated to timing: no significant within-zone excess
    fake = pd.Series(rng.permutation(zones.to_numpy()), index=zones.index)
    r = codating(k, fake, rng, n_perm=199)
    assert r["p_value_one_sided"] > 0.01


def test_timing_clusters_recover_zones():
    k, zones = _timing_data()
    r = timing_clusters(k, zones, np.random.default_rng(4), n_perm=99)
    assert r["ari_timing_vs_price_zones"] > 0.9
    assert r["p_value_one_sided"] <= 0.02
