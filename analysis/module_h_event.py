"""Module H: the scheduled Kroger promotion expiry (pre-registered).

docs/PREREGISTRATION_EVENT.md fixes the predictions H1-H7, the definitions and
this code before the event (2026-10-07T03:59:59Z = Tue Oct 6, 11:59 pm
Eastern). Zones are frozen in config/prereg_kroger_zones.csv.

Passes (snapshots of the 60 panel stores; scripts/run_kroger_event.ps1):
control, before, probe_pre, probe_post, probe_early, after, late. Their ids come
from `event_snapshots` in config/analysis.yaml, else from the snapshot notes
("kroger event <pass>").

A unit is a (store, Kroger product) pair seen in both passes being compared.
PRELIMINARY; one event; associations only.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

from analysis.common import ANALYSIS_CFG, DB, ROOT, SEED, TAB, load_observations

EXPIRY = pd.Timestamp("2026-10-07T03:59:59Z")
EXPIRY_PREFIX = "2026-10-07T03:59:59"
PASSES = ("control", "before", "probe_pre", "probe_post", "probe_early", "after", "late")
N_PERM = 4999


# ---------------------------------------------------------------------------
# data

def event_snapshots() -> dict[str, int]:
    import yaml
    cfg = yaml.safe_load(ANALYSIS_CFG.read_text(encoding="utf-8")) or {}
    ids = {k: int(v) for k, v in (cfg.get("event_snapshots") or {}).items()}
    if len(ids) < len(PASSES):
        con = sqlite3.connect(DB)
        for sid, notes in con.execute("SELECT snapshot_id, notes FROM snapshots WHERE notes LIKE 'kroger event %'"):
            name = notes.split(" 20")[0].replace("kroger event ", "").replace(" ", "_")
            ids.setdefault(name, int(sid))
        con.close()
    return {k: v for k, v in ids.items() if k in PASSES}


def tidy(obs: pd.DataFrame) -> pd.DataFrame:
    """One row per (store, product): shelf/regular price, promo flag, effective
    and expiration times, stock level."""
    o = obs.dropna(subset=["price"]).copy()
    ex = o["extra"].map(lambda e: json.loads(e) if isinstance(e, str) else (e or {}))
    o["eff"] = pd.to_datetime(ex.map(lambda e: e.get("price_effective")), utc=True, errors="coerce", format="ISO8601")
    o["exp_raw"] = ex.map(lambda e: e.get("price_expiration") or "")
    o["stock"] = ex.map(lambda e: e.get("stock_level"))
    o["shelf"] = o["price"].round(2)
    o["regular"] = o["regular_price"].round(2)
    o["promo"] = o["is_promo"].fillna(0).astype(int) == 1
    o["scheduled"] = o["promo"] & o["exp_raw"].str.startswith(EXPIRY_PREFIX)
    cols = ["store_pk", "chain_product_id", "shelf", "regular", "promo", "eff", "exp_raw", "scheduled", "stock"]
    return o.sort_values("observed_at").drop_duplicates(["store_pk", "chain_product_id"], keep="last")[cols]


def pair(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    m = a.merge(b, on=["store_pk", "chain_product_id"], suffixes=("_a", "_b"))
    m["price_changed"] = m["shelf_a"] != m["shelf_b"]
    m["changed"] = m["price_changed"] | (m["eff_a"] != m["eff_b"])
    m["old_promo_gone"] = ~(m["promo_b"] & (m["shelf_a"] == m["shelf_b"]) & (m["eff_a"] == m["eff_b"]))
    return m


def rate(x: pd.Series) -> dict:
    x = x.dropna().astype(bool)
    return {"n": int(len(x)), "rate": float(x.mean()) if len(x) else np.nan}


# ---------------------------------------------------------------------------
# tests

def zone_sync(m: pd.DataFrame, zones: pd.Series, banner: pd.Series, rng, n_perm: int = N_PERM) -> pd.DataFrame:
    """H6: among same-banner store pairs where both changed the same product,
    agreement of the new effective minute (a) and new shelf price (b),
    within vs across frozen zones; zone labels permuted within banner."""
    ev = m[m["changed"] & m["store_pk"].isin(zones.index)]
    I, J, eff_same, price_same = [], [], [], []
    for _, g in ev.groupby("chain_product_id"):
        if len(g) < 2:
            continue
        s = g["store_pk"].to_numpy()
        t = g["eff_b"].dt.floor("min").to_numpy()
        p = g["shelf_b"].to_numpy()
        iu = np.triu_indices(len(s), 1)
        keep = banner.reindex(s[iu[0]]).to_numpy() == banner.reindex(s[iu[1]]).to_numpy()
        I.append(s[iu[0]][keep]); J.append(s[iu[1]][keep])
        eff_same.append((t[iu[0]] == t[iu[1]])[keep]); price_same.append((p[iu[0]] == p[iu[1]])[keep])
    if not I:
        return pd.DataFrame([{"note": "no same-banner pairs of changed units"}])
    I, J = np.concatenate(I), np.concatenate(J)
    stores = np.unique(np.concatenate([I, J]))
    pos = {s: k for k, s in enumerate(stores)}
    Ii, Jj = np.array([pos[x] for x in I]), np.array([pos[x] for x in J])
    z0 = zones.reindex(stores).to_numpy()
    bn = banner.reindex(stores).to_numpy()
    out = []
    for name, y in (("H6a_same_effective_minute", np.concatenate(eff_same)), ("H6b_same_new_price", np.concatenate(price_same))):
        y = y.astype(float)

        def stat(z):
            same = z[Ii] == z[Jj]
            if same.sum() == 0 or (~same).sum() == 0:
                return np.nan, np.nan, np.nan
            return y[same].mean() - y[~same].mean(), y[same].mean(), y[~same].mean()
        obs, ws, xs = stat(z0)
        perm = []
        for _ in range(n_perm):
            z = z0.copy()
            for b in np.unique(bn):
                idx = np.flatnonzero(bn == b)
                z[idx] = rng.permutation(z[idx])
            perm.append(stat(z)[0])
        perm = np.array([x for x in perm if not np.isnan(x)])
        p = float((1 + (perm >= obs).sum()) / (1 + len(perm))) if len(perm) and not np.isnan(obs) else np.nan
        out.append({"test": name, "pairs_x_products": int(len(y)), "within_zone": ws, "across_zone": xs,
                    "difference": obs, "p_one_sided": p, "n_perm": int(len(perm))})
    return pd.DataFrame(out)


def cluster_ci(x: pd.Series, clusters: pd.Series, rng, B: int = 1000) -> tuple[float, float]:
    x, c = x.astype(float).to_numpy(), clusters.to_numpy()
    u = np.unique(c)
    if len(u) < 2:
        return np.nan, np.nan
    idx = {k: np.flatnonzero(c == k) for k in u}
    bs = [x[np.concatenate([idx[k] for k in rng.choice(u, len(u))])].mean() for _ in range(B)]
    return tuple(np.percentile(bs, [2.5, 97.5]))


def analyse(passes: dict[str, pd.DataFrame], zones: pd.Series, banner: pd.Series, seed: int = SEED,
            n_perm: int = N_PERM) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(predictions table, zone-sync table, estimates table) from tidy passes."""
    rng = np.random.default_rng(seed)
    P = {k: v for k, v in passes.items() if v is not None and len(v)}
    rows, est = [], []

    def add(h, claim, value, n, holds, note=""):
        rows.append({"hypothesis": h, "prediction": claim, "value": value, "n": n,
                     "holds": holds if not (isinstance(value, float) and np.isnan(value)) else None, "note": note})

    ba = pair(P["before"], P["after"]) if {"before", "after"} <= P.keys() else None
    if ba is not None:
        sch = ba[ba["scheduled_a"]]
        r = rate(sch["old_promo_gone"]); add("H1", "old promotion gone in after >= 0.95", r["rate"], r["n"], r["rate"] >= 0.95)
        r1 = rate(sch["price_changed"])
        other = ba[~ba["scheduled_a"]]
        r0 = rate(other["price_changed"])
        add("H2", "price-change rate: scheduled >= 0.80", r1["rate"], r1["n"], r1["rate"] >= 0.80)
        add("H2", "price-change rate: not scheduled <= 0.15", r0["rate"], r0["n"], r0["rate"] <= 0.15)
        newp = sch[sch["changed"] & sch["eff_b"].notna()]
        et = newp["eff_b"] - pd.Timedelta(hours=4)
        early = rate(newp["eff_b"] < EXPIRY)
        morning = rate((et.dt.date == pd.Timestamp("2026-10-07").date()) & et.dt.hour.between(4, 10))
        add("H5", "new prices effective before the expiry >= 0.15", early["rate"], early["n"], early["rate"] >= 0.15)
        add("H5", "new prices effective Wed 04:00-11:00 ET >= 0.50", morning["rate"], morning["n"], morning["rate"] >= 0.50)
        gone = sch[sch["old_promo_gone"]]
        ren = gone["promo_b"]
        lo, hi = cluster_ci(ren, gone["store_pk"], rng)
        est.append({"estimate": "renewal share (promotion again, new effective date)", "value": float(ren.mean()) if len(ren) else np.nan,
                    "ci_lo": lo, "ci_hi": hi, "n": int(len(ren))})
        rn = gone[gone["promo_b"]]
        est.append({"estimate": "discount depth: expired promotions", "value": float((1 - sch["shelf_a"] / sch["regular_a"]).mean()),
                    "ci_lo": np.nan, "ci_hi": np.nan, "n": int(len(sch))})
        est.append({"estimate": "discount depth: renewals", "value": float((1 - rn["shelf_b"] / rn["regular_b"]).mean()) if len(rn) else np.nan,
                    "ci_lo": np.nan, "ci_hi": np.nan, "n": int(len(rn))})
        for lab, g in (("scheduled", sch), ("other", other)):
            for side in ("a", "b"):
                s = g[f"stock_{side}"].isin(["LOW", "TEMPORARILY_OUT_OF_STOCK"])
                est.append({"estimate": f"stock LOW/OUT share, {lab}, {'before' if side == 'a' else 'after'}",
                            "value": float(s.mean()) if len(s) else np.nan, "ci_lo": np.nan, "ci_hi": np.nan, "n": int(len(s))})
        g = ba.assign(banner=banner.reindex(ba["store_pk"]).to_numpy())
        for b, gb in g[g["scheduled_a"]].groupby("banner"):
            est.append({"estimate": f"renewal share, banner {b}", "value": float(gb.loc[gb["old_promo_gone"], "promo_b"].mean()),
                        "ci_lo": np.nan, "ci_hi": np.nan, "n": int(gb["old_promo_gone"].sum())})
    if "after" in P:                                   # Addendum 1: the new cohort, seen when it starts
        a = P["after"]
        exp = pd.to_datetime(a["exp_raw"].where(~a["exp_raw"].str.startswith("9999")), utc=True, errors="coerce", format="ISO8601")
        new = a[a["promo"] & a["eff"].between(pd.Timestamp("2026-10-07T02:00Z"), pd.Timestamp("2026-10-07T16:00Z")) & exp.notna()]
        L = (exp[new.index] - new["eff"]).dt.total_seconds() / 86400
        if len(L):
            lo, hi = cluster_ci(L, new["store_pk"], rng)
            est.append({"estimate": "new cohort: mean planned promotion length (days)", "value": float(L.mean()),
                        "ci_lo": lo, "ci_hi": hi, "n": int(len(L))})
            for w, share in (np.round(L / 7).value_counts(normalize=True).sort_index()).items():
                est.append({"estimate": f"new cohort: share {int(w)} wk", "value": float(share), "ci_lo": np.nan,
                            "ci_hi": np.nan, "n": int(len(L))})
    if ba is not None and "control" in P:
        cb = pair(P["control"], P["before"])
        rc, re_ = rate(cb["price_changed"]), rate(ba["price_changed"])
        if rc["rate"]:
            ratio = re_["rate"] / rc["rate"]
        else:                                   # no control changes: ratio infinite only if the event had some
            ratio = np.inf if re_["rate"] else np.nan
        add("H3", "change rate before->after >= 3 x control->before", float(ratio), re_["n"], ratio >= 3,
            f"event {re_['rate']:.4f} (n={re_['n']}), control {rc['rate']:.4f} (n={rc['n']})")
        if "late" in P:
            al = pair(P["after"], P["late"])
            rl = rate(al["price_changed"])
            add("H7", "change rate after->late <= control->before", rl["rate"], rl["n"], rl["rate"] <= rc["rate"],
                f"control {rc['rate']:.4f}")
    if "before" in P:
        sched_before = P["before"][P["before"]["scheduled"]]
        for probe, want_gone in (("probe_pre", False), ("probe_post", True)):
            if probe in P:
                m = pair(sched_before, P[probe])
                r = rate(m["old_promo_gone"] if want_gone else ~m["old_promo_gone"])
                add("H4", f"{probe}: scheduled promotions {'gone' if want_gone else 'still present'} >= 0.90",
                    r["rate"], r["n"], r["rate"] >= 0.90)
        if "probe_early" in P:
            m = pair(sched_before, P["probe_early"])
            r = rate(m["old_promo_gone"])
            est.append({"estimate": "probe_early: scheduled promotions gone", "value": r["rate"], "ci_lo": np.nan, "ci_hi": np.nan, "n": r["n"]})
    zs = zone_sync(ba, zones, banner, rng, n_perm) if ba is not None else pd.DataFrame()
    for _, z in zs.iterrows():
        if "test" in z and isinstance(z.get("test"), str):
            add(z["test"].split("_")[0], f"{z['test']}: within zone > across zone (one-sided p < 0.05)",
                float(z["difference"]), int(z["pairs_x_products"]), bool(z["p_one_sided"] < 0.05),
                f"within {z['within_zone']:.3f}, across {z['across_zone']:.3f}, p = {z['p_one_sided']:.4f}")
    return pd.DataFrame(rows), zs, pd.DataFrame(est)


# ---------------------------------------------------------------------------
# Meijer arm (pre-registration Addendum 4)

MEIJER_END = "2026-10-06"


def meijer_snapshots() -> dict[str, int]:
    con = sqlite3.connect(DB)
    ids = {}
    for sid, notes in con.execute("SELECT snapshot_id, notes FROM snapshots WHERE notes LIKE 'meijer event %'"):
        ids.setdefault(notes.split(" 20")[0].replace("meijer event ", "").strip(), int(sid))
    con.close()
    return ids


def meijer_tidy(obs: pd.DataFrame) -> pd.DataFrame:
    o = obs[(obs["chain"] == "meijer") & (obs["store_specific"] == 1)].dropna(subset=["price"]).copy()
    ex = o["extra"].map(lambda e: json.loads(e) if isinstance(e, str) else (e or {}))
    o["good_through"] = ex.map(lambda e: str(e.get("price_good_through") or "")[:10])
    o["shelf"] = o["price"].round(2)
    o["scheduled"] = o["good_through"] == MEIJER_END
    return o.sort_values("observed_at").drop_duplicates(["store_pk", "chain_product_id"], keep="last")[
        ["store_pk", "chain_product_id", "shelf", "good_through", "scheduled"]]


def meijer_event(passes: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Predictions M1-M4 (Addendum 4) from tidy Meijer passes."""
    rows = []

    def add(h, claim, value, n, holds, note=""):
        ok = None if (isinstance(value, float) and np.isnan(value)) else bool(holds)
        rows.append({"hypothesis": h, "prediction": claim, "value": value, "n": n, "holds": ok, "note": note})
    if not {"before", "after"} <= passes.keys():
        return pd.DataFrame([{"note": f"Meijer passes so far: {sorted(passes)}"}])
    ba = passes["before"].merge(passes["after"], on=["store_pk", "chain_product_id"], suffixes=("_a", "_b"))
    ba["changed"] = ba["shelf_a"] != ba["shelf_b"]
    sch, other = ba[ba["scheduled_a"]], ba[~ba["scheduled_a"]]
    r1 = float(sch["changed"].mean()) if len(sch) else np.nan
    r2 = float(other["changed"].mean()) if len(other) else np.nan
    add("M1", "change rate of scheduled units >= 0.80", r1, len(sch), r1 >= 0.80)
    add("M2", "change rate of other units <= 0.15", r2, len(other), r2 <= 0.15)
    if "control" in passes:
        cb = passes["control"].merge(passes["before"], on=["store_pk", "chain_product_id"], suffixes=("_a", "_b"))
        rc = float((cb["shelf_a"] != cb["shelf_b"]).mean()) if len(cb) else np.nan
        re_ = float(ba["changed"].mean())
        ratio = re_ / rc if rc else (np.inf if re_ else np.nan)
        add("M3", "change rate before->after >= 3 x control->before", ratio, len(ba), ratio >= 3,
            f"event {re_:.4f} (n={len(ba)}), control {rc:.4f} (n={len(cb)})")
    g = sch.groupby("chain_product_id")["shelf_b"].agg(["nunique", "size"])
    g = g[g["size"] >= 2]
    r4 = float((g["nunique"] == 1).mean()) if len(g) else np.nan
    add("M4", "products with one new price across stores >= 0.90", r4, len(g), r4 >= 0.90)
    return pd.DataFrame(rows)


def run() -> str:
    mids = meijer_snapshots()
    if mids:
        mobs = load_observations(snapshot_id=list(mids.values()))
        mp_ = {k: meijer_tidy(mobs[mobs["snapshot_id"] == sid]) for k, sid in mids.items()}
        TAB.mkdir(exist_ok=True)
        meijer_event(mp_).to_csv(TAB / "module_h_meijer_predictions.csv", index=False)
    ids = event_snapshots()
    if not {"before", "after"} <= ids.keys():
        return f"Module H: event passes not collected yet (have {sorted(ids)})."
    obs = load_observations(snapshot_id=list(ids.values()))
    obs = obs[obs["chain"] == "kroger"]
    passes = {k: tidy(obs[obs["snapshot_id"] == sid]) for k, sid in ids.items()}
    zones = pd.read_csv(ROOT / "config" / "prereg_kroger_zones.csv").set_index("store_pk")["zone"]
    names = pd.read_sql_query("SELECT store_pk, name FROM stores", sqlite3.connect(DB)).set_index("store_pk")["name"]
    banner = names.fillna("").str.split().str[0].str.upper()
    pred, zs, est = analyse(passes, zones, banner)
    TAB.mkdir(exist_ok=True)
    pred.to_csv(TAB / "module_h_predictions.csv", index=False)
    zs.to_csv(TAB / "module_h_zone_sync.csv", index=False)
    est.to_csv(TAB / "module_h_estimates.csv", index=False)
    held = int(pred["holds"].fillna(False).sum())
    return f"Module H: passes {ids}; {held}/{len(pred)} pre-registered predictions hold; wrote 3 tables."


if __name__ == "__main__":
    print(run())
    sys.exit(0)
