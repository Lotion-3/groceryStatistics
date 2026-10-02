"""Fast sanity tests for analysis/estimators.py (SIMULATED data only).
The fuller calibration study is simulation/validate_tail_estimators.py."""
import numpy as np
import pytest

from analysis import estimators as E


def test_hill_recovers_pareto_alpha():
    x = np.random.default_rng(1).pareto(3.0, 20000) + 1
    assert 1 / E.hill_gamma(x, 1000) == pytest.approx(3.0, rel=0.1)


def test_hill_path_shapes():
    x = np.random.default_rng(2).pareto(2.0, 1000) + 1
    p = E.hill_path(x)
    assert p["k"][0] == 10 and p["k"][-1] < 150
    assert np.all(p["lo"] < p["alpha"]) and np.all(p["alpha"] < p["hi"])


def test_gpd_shape():
    x = np.random.default_rng(3).pareto(2.0, 20000) + 1
    fit = E.gpd_fit(x, np.quantile(x, 0.95))
    assert fit.xi == pytest.approx(0.5, abs=0.1)


def test_var_es():
    v, es = E.var_es(np.arange(1, 101), 0.95)
    assert v == pytest.approx(95.05) and es == pytest.approx(np.mean([96, 97, 98, 99, 100]))


def test_clustering_test_detects_cluster():
    rng = np.random.default_rng(4)
    lat = np.r_[rng.normal(40, 0.2, 20), rng.uniform(30, 48, 80)]
    lon = np.r_[rng.normal(-90, 0.2, 20), rng.uniform(-120, -75, 80)]
    exceed = np.r_[np.ones(20, int), np.zeros(80, int)]
    assert E.exceedance_clustering_test(lat, lon, exceed, 100, n_perm=499)["p_value"] < 0.01
    shuffled = rng.permutation(exceed)
    assert E.exceedance_clustering_test(lat, lon, shuffled, 100, n_perm=499)["p_value"] > 0.01


def test_cluster_bootstrap_wider_than_iid_for_clustered_data():
    from analysis.estimators import bootstrap_ci, cluster_bootstrap_ci
    rng = np.random.default_rng(1)
    store_effect = rng.normal(0, 1, 50)
    clusters = np.repeat(np.arange(50), 20)
    v = store_effect[clusters] + rng.normal(0, 0.1, len(clusters))
    _, lo_c, hi_c = cluster_bootstrap_ci(v, clusters, np.mean, B=400)
    _, lo_i, hi_i = bootstrap_ci(v, np.mean, B=400)
    assert (hi_c - lo_c) > 2 * (hi_i - lo_i)


def test_morans_i_detects_smooth_field():
    from analysis.estimators import morans_i
    rng = np.random.default_rng(2)
    lat, lon = rng.uniform(30, 45, 200), rng.uniform(-120, -75, 200)
    smooth = morans_i(lat, lon, lon + rng.normal(0, 1, 200), radius_km=300, n_perm=499)
    noise = morans_i(lat, lon, rng.normal(0, 1, 200), radius_km=300, n_perm=499)
    assert smooth["I"] > 0.5 and smooth["p_value"] < 0.01
    assert noise["p_value"] > 0.01
