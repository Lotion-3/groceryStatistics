"""Module F: do stores in the same pricing zone change prices together? (Plan Q4)

Data: the Kroger daily panel (scripts/kroger_panel.py) -- the same ~60 stores
and items on consecutive days -- with snapshot 2 as day 0. Panel snapshot ids
are listed under `panel_snapshots` in config/analysis.yaml. Zones come from
Module E (tables/module_e_store_zones.csv), estimated from snapshot 2 alone, so
the test is out-of-sample in time.

Events. For each store, product and pair of consecutive days, a CHANGE is a
different regular price (list changes) or a different shelf price (promotions
starting or ending), to the cent.

Synchronisation. For a pair of stores and a product-day transition where at
least one of the two changed, the pair CO-CHANGES if both changed to the same
new price. Per pair: co-change rate = co-changes / transitions where either
changed. Compared:
  * same zone vs different zone, among pairs of the SAME banner (zones are
    nested in banners, so this separates zone from banner);
  * permutation test: zone labels shuffled across stores within banner
    (4,999 permutations); one-sided p for "same-zone pairs co-change more".

PRELIMINARY; a few days of data; associations only.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from analysis.common import ANALYSIS_CFG, FIG, SEED, TAB, caption, load_observations, main_snapshots, style


def panel_snapshots() -> list[int]:
    import yaml
    cfg = yaml.safe_load(ANALYSIS_CFG.read_text(encoding="utf-8")) or {}
    return [int(s) for s in (cfg.get("panel_snapshots") or [])]


def price_panel(obs: pd.DataFrame, col: str) -> pd.DataFrame:
    """(store, product) x day matrix of prices in cents (day = snapshot order)."""
    p = obs.dropna(subset=[col]).assign(cents=lambda d: d[col].round(2))
    return p.pivot_table(index=["store_pk", "chain_product_id"], columns="snapshot_id", values="cents", aggfunc="min")


def change_events(P: pd.DataFrame) -> pd.DataFrame:
    """Long table of (store, product, day t -> t+1, changed, new price)."""
    days = list(P.columns)
    rows = []
    for a, b in zip(days[:-1], days[1:]):
        both = P[[a, b]].dropna()
        rows.append(pd.DataFrame({"store_pk": both.index.get_level_values(0),
                                  "product": both.index.get_level_values(1), "transition": f"{a}->{b}",
                                  "changed": (both[a] != both[b]).to_numpy(), "new": both[b].to_numpy()}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def pair_cochange(ev: pd.DataFrame) -> pd.DataFrame:
    """Per store pair: transitions where either changed, and co-changes."""
    out = {}
    for (prod, tr), g in ev.groupby(["product", "transition"]):
        if not g["changed"].any() or len(g) < 2:
            continue
        s = g["store_pk"].to_numpy()
        c = g["changed"].to_numpy()
        new = g["new"].to_numpy()
        for i in range(len(s)):
            for j in range(i + 1, len(s)):
                if c[i] or c[j]:
                    key = (min(s[i], s[j]), max(s[i], s[j]))
                    e, co = out.get(key, (0, 0))
                    out[key] = (e + 1, co + int(c[i] and c[j] and new[i] == new[j]))
    return pd.DataFrame([{"store_a": a, "store_b": b, "either": e, "co": co} for (a, b), (e, co) in out.items()])


def zone_test(pairs: pd.DataFrame, zones: pd.Series, banner: pd.Series, rng, n_perm: int = 4999) -> dict:
    """Same-zone vs different-zone co-change rate among same-banner pairs."""
    pairs = pairs[pairs["store_a"].isin(zones.index) & pairs["store_b"].isin(zones.index)].copy()
    pairs = pairs[banner.loc[pairs["store_a"]].to_numpy() == banner.loc[pairs["store_b"]].to_numpy()]
    pairs = pairs[pairs["either"] >= 3]
    if pairs.empty:
        return {"note": "no same-banner pairs with enough change events"}

    def stat(z):
        same = z.loc[pairs["store_a"]].to_numpy() == z.loc[pairs["store_b"]].to_numpy()
        if same.sum() < 3 or (~same).sum() < 3:
            return np.nan, np.nan, np.nan
        rate = pairs["co"] / pairs["either"]
        return rate[same].mean() - rate[~same].mean(), rate[same].mean(), rate[~same].mean()

    obs, r_same, r_diff = stat(zones)
    if np.isnan(obs):
        return {"pairs": len(pairs), "note": "too few same-zone or different-zone pairs"}
    perm = []
    for _ in range(n_perm):
        z = zones.copy()
        for b in banner.unique():           # shuffle zone labels within banner
            idx = banner.index[banner == b].intersection(z.index)
            z.loc[idx] = rng.permutation(z.loc[idx].to_numpy())
        perm.append(stat(z)[0])
    perm = np.array([x for x in perm if not np.isnan(x)])
    return {"pairs": len(pairs), "rate_same_zone": r_same, "rate_diff_zone": r_diff, "difference": obs,
            "p_value_one_sided": float((1 + (perm >= obs).sum()) / (1 + len(perm))), "n_perm": len(perm)}


def run() -> str:
    panel = panel_snapshots()
    if len(panel) < 1:
        return "Module F: no panel snapshots configured (panel_snapshots in config/analysis.yaml)."
    base = main_snapshots()[:1]
    zt = TAB / "module_e_store_zones.csv"
    if not zt.exists():
        return "Module F: run Module E first (needs tables/module_e_store_zones.csv)."
    obs = load_observations(snapshot_id=base + panel)
    obs = obs[obs["chain"] == "kroger"]
    zones_df = pd.read_csv(zt)
    zones_df = zones_df[zones_df["chain"] == "kroger"].set_index("store_pk")["zone"]
    import sqlite3
    from analysis.common import DB
    names = pd.read_sql_query("SELECT store_pk, name FROM stores", sqlite3.connect(DB)).set_index("store_pk")["name"]
    rng = np.random.default_rng(SEED)
    rows, rates = [], []
    for col, label in (("regular_price", "regular"), ("price", "shelf")):
        P = price_panel(obs, col)
        P = P.loc[P.index.get_level_values(0).isin(zones_df.index)]
        ev = change_events(P)
        if ev.empty:
            continue
        rates.append(ev.groupby("transition")["changed"].agg(["mean", "size"]).reset_index().assign(price=label))
        pairs = pair_cochange(ev)
        stores = zones_df.index.intersection(P.index.get_level_values(0).unique())
        banner = names.reindex(stores).fillna("").str.split().str[0].str.upper()
        rows.append({"price": label, "stores": len(stores), "change_rate": float(ev["changed"].mean()),
                     **zone_test(pairs, zones_df.loc[stores], banner, rng)})
    TAB.mkdir(exist_ok=True)
    res = pd.DataFrame(rows)
    res.to_csv(TAB / "module_f_zone_synchronisation.csv", index=False)
    if rates:
        pd.concat(rates).to_csv(TAB / "module_f_change_rates.csv", index=False)
    return f"Module F: {len(panel)} panel day(s); wrote 2 tables."


if __name__ == "__main__":
    print(run())
    sys.exit(0)
