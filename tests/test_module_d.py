"""Module D optimiser checks on small random instances (test-only data)."""
import numpy as np

from analysis import module_d_basket as D


def _instance(seed, S=6, I=8, miss=0.2):
    rng = np.random.default_rng(seed)
    P = rng.uniform(1, 10, size=(S, I))
    P[rng.random(P.shape) < miss] = np.nan
    return P


def test_milp_matches_brute_force_and_greedy_never_beats_it():
    for seed in range(12):
        P = _instance(seed)
        for k in (1, 2, 3):
            opt, chosen = D.solve_exact(P, k)
            brute = D.solve_brute(P, k)
            if np.isnan(brute):
                assert np.isnan(opt)
                continue
            assert abs(opt - brute) < 1e-6
            assert len(chosen) <= k
            assert abs(D.basket_cost(P, chosen) - opt) < 1e-6
            g, _ = D.solve_greedy(P, k)
            assert np.isnan(g) or g >= opt - 1e-9


def test_infeasible_when_an_item_is_sold_nowhere():
    P = _instance(0)
    P[:, 3] = np.nan
    assert np.isnan(D.solve_exact(P, 3)[0])


def test_more_stores_never_cost_more():
    P = _instance(5, miss=0.0)
    c = [D.solve_exact(P, k)[0] for k in (1, 2, 3)]
    assert c[0] >= c[1] >= c[2]
