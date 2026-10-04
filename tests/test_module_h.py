"""Module H (pre-registered event analysis) on synthetic passes with known answers."""
import numpy as np
import pandas as pd

from analysis.module_h_event import EXPIRY, analyse

BEFORE_EFF = pd.Timestamp("2026-09-30T10:00Z")


def _synthetic(seed=0, renew=0.4):
    rng = np.random.default_rng(seed)
    stores = np.arange(1, 25)                       # 2 banners x 3 zones x 4 stores
    banner = pd.Series(np.where(stores <= 12, "KROGER", "RALPHS"), index=stores)
    zones = pd.Series((stores - 1) // 4, index=stores)
    zone_time = {z: pd.Timestamp("2026-10-07T10:00Z") + pd.Timedelta(minutes=17 * z) for z in range(6)}
    rows_b, rows_a, rows_c = [], [], []
    for s in stores:
        for p in range(40):
            scheduled = p < 15
            reg = 3.0 + p * 0.1
            shelf = round(reg * 0.8, 2) if scheduled else reg
            exp = "2026-10-07T03:59:59.999Z" if scheduled else "9999-12-31T00:00:00Z"
            base = dict(store_pk=s, chain_product_id=f"P{p}", regular=reg, stock="HIGH")
            rows_c.append({**base, "shelf": shelf, "promo": scheduled, "eff": BEFORE_EFF, "exp_raw": exp, "scheduled": scheduled})
            rows_b.append({**base, "shelf": shelf, "promo": scheduled, "eff": BEFORE_EFF, "exp_raw": exp, "scheduled": scheduled})
            if scheduled:
                z = zones[s]
                renewed = rng.random() < renew
                new_shelf = round(reg * (0.75 if z % 2 else 0.7), 2) if renewed else reg
                exp_new = (zone_time[z].normalize() + pd.Timedelta(days=14, hours=3, minutes=59)).isoformat() if renewed else ""
                rows_a.append({**base, "shelf": new_shelf, "promo": renewed, "eff": zone_time[z], "exp_raw": exp_new, "scheduled": False})
            else:
                rows_a.append({**base, "shelf": shelf, "promo": False, "eff": BEFORE_EFF, "exp_raw": exp, "scheduled": False})
    df = lambda r: pd.DataFrame(r)
    return {"control": df(rows_c), "before": df(rows_b), "after": df(rows_a), "late": df(rows_a)}, zones, banner


def test_module_h_recovers_known_answers():
    passes, zones, banner = _synthetic()
    pred, zs, est = analyse(passes, zones, banner, n_perm=199)
    get = lambda h, word: pred[(pred.hypothesis == h) & pred.prediction.str.contains(word)].iloc[0]
    assert get("H1", "gone")["value"] == 1.0
    assert get("H2", "not scheduled")["value"] == 0.0
    # zone-synchronised effective minutes -> within-zone agreement 1, across 0, significant
    h6a = zs[zs.test == "H6a_same_effective_minute"].iloc[0]
    assert h6a.within_zone == 1.0 and h6a.across_zone == 0.0 and h6a.p_one_sided < 0.05
    # all new prices dated 10:00-11:25 UTC Wed = 06:00-07:25 ET -> morning share 1, before-expiry share 0
    assert get("H5", "before the expiry")["value"] == 0.0
    assert get("H5", "04:00-11:00")["value"] == 1.0
    ren = est[est.estimate.str.startswith("renewal share (")].iloc[0]
    assert abs(ren.value - 0.4) < 0.1 and ren.ci_lo < ren.value < ren.ci_hi
    assert np.isinf(get("H3", "control")["value"])  # control->before has no changes
    assert EXPIRY.hour == 3
    coh = est[est.estimate.str.startswith("new cohort: mean")].iloc[0]
    assert abs(coh.value - 14) < 0.7      # renewals planned to the expiry two weeks on
