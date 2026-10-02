"""Module C building blocks on synthetic data (test-only; never used as results)."""
import numpy as np
import pandas as pd

from analysis import module_c_hd as C


def _low_rank(n=120, m=40, r=2, noise=0.05, miss=0.3, seed=0):
    rng = np.random.default_rng(seed)
    Y = rng.normal(size=(n, r)) @ rng.normal(size=(r, m)) + noise * rng.normal(size=(n, m))
    Yobs = Y.copy()
    Yobs[rng.random(Y.shape) < miss] = np.nan
    return Y, Yobs


def test_em_pca_recovers_missing_cells():
    Y, Yobs = _low_rank()
    R = C.em_pca(Yobs, 2)[0]
    miss = np.isnan(Yobs)
    rel = np.mean((R[miss] - Y[miss]) ** 2) / np.var(Y)
    assert rel < 0.05


def test_rank_cv_picks_true_rank():
    _, Yobs = _low_rank(r=3)
    cv = C.rank_cv(Yobs, max_rank=6, repeats=2)
    assert int(cv.loc[cv["mean"].idxmin(), "rank"]) == 3


def test_state_folds_never_split_a_state():
    groups = np.repeat(np.array(list("ABCDEFGHIJ")), 7)
    seen = []
    for tr, te in C.state_folds(groups, 5, seed=1):
        assert not set(groups[tr]) & set(groups[te])
        seen.extend(te)
    assert sorted(seen) == list(range(len(groups)))


def test_shrinkage_beats_overfit_ols_on_sparse_truth():
    rng = np.random.default_rng(3)
    n, p = 150, 120
    X = pd.DataFrame(rng.normal(size=(n, p)), columns=[f"x{i}" for i in range(p)])
    y = 0.8 * X["x0"].to_numpy() - 0.5 * X["x1"].to_numpy() + 0.5 * rng.normal(size=n)
    groups = np.repeat(np.arange(15), 10)
    models = {k: C.MODELS[k] for k in ("mean", "ols_full", "lasso")}
    errs, sel = C.cv_compare(X, ["x0", "x1"], y, groups, models)
    rmse = errs.groupby("model")["mse"].mean()
    assert rmse["lasso"] < rmse["ols_full"] and rmse["lasso"] < rmse["mean"]
    f = sel.set_index("predictor")["selfreq_lasso"]
    assert f["x0"] == 1.0 and f["x1"] == 1.0
