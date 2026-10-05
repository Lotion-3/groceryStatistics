"""Module I (Walmart panel) on synthetic visits with known change rates."""
import numpy as np
import pandas as pd

from analysis.module_i_walmart_panel import analyse


def _panel(seed=0):
    rng = np.random.default_rng(seed)
    visits = [pd.Timestamp("2026-10-05T12:00Z") + pd.Timedelta(hours=6 * k) for k in range(8)]
    rows = []
    for s in range(1, 11):
        for p in range(30):
            price = 3.0 + p
            for v, t in enumerate(visits):
                local = t - pd.Timedelta(hours=5)
                if v and local.date() != (visits[v - 1] - pd.Timedelta(hours=5)).date() and rng.random() < 0.3:
                    price = round(price + 0.1, 2)                 # changes only across nights
                rows.append({"snapshot_id": 100 + v, "store_pk": s, "state": "TX", "chain_product_id": f"P{p}",
                             "t": t, "local": local, "shelf": price,
                             "slot_delivery": t + pd.Timedelta(hours=2 + s % 3), "slot_pickup": pd.NaT,
                             "low_stock": 0})
    return pd.DataFrame(rows)


def test_module_i_separates_intraday_and_overnight():
    p = _panel()
    lp = pd.Series({f"P{j}": 3.0 + j for j in range(30)})
    tabs = analyse(p, lp)
    t2 = tabs["module_i_t2_change_rates"].set_index("transition")
    assert t2.loc["intraday", "change_rate"] == 0.0
    assert 0.2 < t2.loc["overnight", "change_rate"] < 0.4
    t3 = tabs["module_i_t3_departure_persistence"].iloc[0]
    assert t3["p_stay_off"] == 1.0                            # once off list (price raised), it stays off
    sl = tabs["module_i_slot_lead_times"].set_index("lead").loc["lead_delivery_h"]
    assert sl["share_var_between_stores"] > 0.99              # lead time set by store only
