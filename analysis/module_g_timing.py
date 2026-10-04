"""Module G: price timing from one snapshot (Kroger effective dates).

Kroger's API reports, for each store price, the date it took effect. That
turns one cross-section into dated events.

1. Weekly calendar. Share of price start dates by weekday (regular vs promo,
   by banner): price changes as a periodic point process.

2. How long does a price last? (renewal theory / inspection paradox)
   A snapshot meets each price at a random point of its life, so long-lived
   prices are over-represented. If price spells form a stationary renewal
   process, the observed AGE A (time since the price started) has density
       f_A(a) = S(a) / mu,
   where S is the survival function of spell durations and mu their mean.
   Hence S(a) = f_A(a) / f_A(0) and mu = 1 / f_A(0): the duration
   distribution is recovered from ages alone. f_A is estimated by a histogram
   (weekly bins, since changes cluster weekly); mu from the first bin. The
   upper tail of the ages is the tail of the residual-life/age distribution,
   which for a power-law spell tail S(t) ~ t^-a has tail index a - 1.
   We report the Hill estimate of the age tail (store-cluster bootstrap).
   Caveats: stationarity; ages are right-truncated at the observation date;
   effective dates may reset when a price is re-entered unchanged.

3. Do stores in the same zone change prices on the same day? For each pair of
   stores (same banner) and each product both carry, a CO-DATED price = the
   same effective date. Co-dating rate (same zone) vs (different zone),
   zones from Module E (estimated from prices only, never from dates);
   permutation test shuffling zone labels within banner.

PRELIMINARY; one snapshot; Kroger only.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import numpy as np
import pandas as pd

from analysis.common import DB, FIG, INK, MUTED, ROOT, SEED, TAB, caption, load_observations, main_snapshots, style
from analysis.estimators import cluster_bootstrap_ci, hill_gamma


def kroger_dated(snaps: list[int]) -> pd.DataFrame:
    o = load_observations(snapshot_id=snaps)
    k = o[o["chain"] == "kroger"].copy()
    ex = k["extra"].map(lambda e: json.loads(e) if isinstance(e, str) else {})
    k["eff"] = pd.to_datetime(ex.map(lambda e: e.get("price_effective")), errors="coerce", utc=True)
    k["obs"] = pd.to_datetime(k["observed_at"], utc=True)
    k = k.dropna(subset=["eff", "price"])
    k["age_days"] = (k["obs"] - k["eff"]).dt.total_seconds() / 86400
    k = k[k["age_days"] >= 0]
    names = pd.read_sql_query("SELECT store_pk, name FROM stores", sqlite3.connect(DB)).set_index("store_pk")["name"]
    k["banner"] = names.reindex(k["store_pk"]).fillna("").str.split().str[0].str.upper().to_numpy()
    return k


def weekday_table(k: pd.DataFrame) -> pd.DataFrame:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    t = (k.assign(weekday=k["eff"].dt.day_name(), kind=np.where(k["is_promo"] == 1, "promo", "regular"))
         .groupby(["kind", "weekday"]).size().unstack(fill_value=0).reindex(columns=days, fill_value=0))
    return (t.div(t.sum(axis=1), axis=0)).reset_index()


def durations(k: pd.DataFrame, rng) -> tuple[pd.DataFrame, dict]:
    """Renewal-theory estimate of the spell-duration survival from ages."""
    out, summ = [], {}
    for kind, g in (("regular", k[k["is_promo"] == 0]), ("promo", k[k["is_promo"] == 1]), ("all", k)):
        a = g["age_days"].to_numpy()
        if len(a) < 200:
            continue
        edges = np.arange(0, 7 * 53, 7.0)                       # weekly bins up to a year
        dens, _ = np.histogram(a, bins=np.append(edges, np.inf))
        dens = dens[:-1] / (len(a) * 7.0)                     # drop the open-ended > 1 year bin
        f0 = dens[0]
        S = np.minimum.accumulate(np.minimum(dens / f0, 1.0))  # survival is non-increasing
        out.append(pd.DataFrame({"kind": kind, "age_lo_days": edges[:-1], "age_density": dens, "spell_survival_S": S}))
        x = a[a > 0]
        k_hill = max(10, int(0.05 * len(x)))
        est, lo, hi = cluster_bootstrap_ci(x, g.loc[g["age_days"] > 0, "store_pk"].to_numpy(),
                                           lambda v: 1 / hill_gamma(v[v > 0], max(10, int(0.05 * (v > 0).sum()))),
                                           B=300, seed=SEED)
        summ[kind] = {"prices": int(len(a)), "median_age_days": float(np.median(a)),
                      "mean_spell_days_renewal": float(1 / f0) if f0 > 0 else np.nan,
                      "S_4wk": float(S[4]), "S_13wk": float(S[13]), "S_26wk": float(S[26]),
                      "age_tail_alpha": est, "age_tail_ci_lo": lo, "age_tail_ci_hi": hi,
                      "implied_spell_tail_alpha": est + 1 if np.isfinite(est) else np.nan, "hill_k": k_hill}
    return pd.concat(out, ignore_index=True), summ


def codating(k: pd.DataFrame, zones: pd.Series, rng, n_perm: int = 2999, unit: str = "date") -> dict:
    """Same-zone vs different-zone share of shared products with the same
    effective date (unit="date") or the same effective minute (unit="minute")."""
    k = k[k["store_pk"].isin(zones.index)].copy()
    k["date"] = k["eff"].dt.date if unit == "date" else k["eff"].dt.floor("min")
    piv = k.pivot_table(index="store_pk", columns="chain_product_id", values="date", aggfunc="first")
    stores = piv.index.to_numpy()
    banner = k.drop_duplicates("store_pk").set_index("store_pk")["banner"].reindex(stores).to_numpy()
    A = piv.to_numpy()
    n = len(stores)
    rate = np.full((n, n), np.nan)
    for i in range(n):
        ok = pd.notna(A[i]) & pd.notna(A)
        both = ok.sum(1)
        same = ((A[i] == A) & ok).sum(1)
        rate[i] = np.where(both >= 20, same / np.maximum(both, 1), np.nan)
    iu = np.triu_indices(n, 1)
    r = rate[iu]
    same_banner = (banner[:, None] == banner[None, :])[iu]
    keep = ~np.isnan(r) & same_banner
    r, I, J = r[keep], iu[0][keep], iu[1][keep]
    z0 = zones.reindex(stores).to_numpy()

    def stat(z):
        s = z[I] == z[J]
        if s.sum() < 5 or (~s).sum() < 5:
            return np.nan, np.nan, np.nan
        return r[s].mean() - r[~s].mean(), r[s].mean(), r[~s].mean()
    obs, rs, rd = stat(z0)
    perm = []
    for _ in range(n_perm):
        z = z0.copy()
        for b in np.unique(banner):
            idx = np.flatnonzero(banner == b)
            z[idx] = rng.permutation(z[idx])
        perm.append(stat(z)[0])
    perm = np.array([p for p in perm if not np.isnan(p)])
    return {"unit": unit, "store_pairs_same_banner": int(len(r)), "codated_share_same_zone": rs, "codated_share_diff_zone": rd,
            "difference": obs, "p_value_one_sided": float((1 + (perm >= obs).sum()) / (1 + len(perm))),
            "n_perm": int(len(perm))}


def codating_by_price(k: pd.DataFrame, zones: pd.Series) -> pd.DataFrame:
    """Co-dating share by (same regular price?, same zone?) over same-banner
    store pairs x shared products. Zones come from prices, so same-zone pairs
    share more prices; holding the price fixed shows the date effect is not
    just a by-product of sharing the price."""
    k = k[k["store_pk"].isin(zones.index)].drop_duplicates(["store_pk", "chain_product_id"]).copy()
    k["date"] = k["eff"].dt.date
    k["cents"] = k["regular_price"].round(2)
    k = k[["store_pk", "chain_product_id", "banner", "date", "cents"]]
    m = k.merge(k, on="chain_product_id", suffixes=("_a", "_b"))
    m = m[(m["store_pk_a"] < m["store_pk_b"]) & (m["banner_a"] == m["banner_b"])]
    m = m.assign(same_price=(m["cents_a"] == m["cents_b"]).to_numpy(),
                 same_zone=zones.reindex(m["store_pk_a"]).to_numpy() == zones.reindex(m["store_pk_b"]).to_numpy(),
                 same_date=(m["date_a"] == m["date_b"]).to_numpy())
    return (m.groupby(["same_price", "same_zone"])["same_date"].agg(codated_share="mean", pairs_x_products="size")
            .reset_index())


# Eastern-time offset in October (daylight time); Arizona has no DST.
_TZ = {**{s: -4 for s in "CT DE DC FL GA IN KY ME MD MA MI NH NJ NY NC OH PA RI SC VT VA WV".split()},
       **{s: -5 for s in "AL AR IL IA KS LA MN MS MO NE ND OK SD TN TX WI".split()},
       **{s: -6 for s in "CO ID MT NM UT WY".split()}, **{s: -7 for s in "CA NV OR WA AZ".split()}}


def local_hour_table(k: pd.DataFrame) -> pd.DataFrame:
    """Share of price starts by local hour band (store's state time zone).
    Approximate: states split across zones get the majority zone."""
    st = pd.read_sql_query("SELECT store_pk, state FROM stores", sqlite3.connect(DB)).set_index("store_pk")["state"]
    off = st.reindex(k["store_pk"]).map(_TZ).to_numpy()
    k = k.assign(off=off).dropna(subset=["off"])
    lh = (k["eff"].dt.hour + k["eff"].dt.minute / 60 + k["off"]) % 24
    band = pd.cut(lh, [0, 3, 6, 8, 12, 17, 21, 24], right=False,
                  labels=["00-03", "03-06", "06-08", "08-12", "12-17", "17-21", "21-24"])
    kind = np.where(k["is_promo"] == 1, "promo", "regular")
    t = pd.crosstab(kind, band, normalize="index")
    t["n"] = pd.Series(kind).value_counts().reindex(t.index).to_numpy()
    return t.reset_index().rename(columns={"row_0": "kind"})


def kroger_expirations(snaps: list[int]) -> pd.DataFrame:
    """(store_id, product, effective, expiration, promo) for promotions, read from
    the raw responses (rows parsed before the parser kept price_expiration)."""
    import glob
    import gzip
    rows = []
    for sn in snaps:
        for f in glob.glob(str(ROOT / "data" / "raw" / f"snap{sn}" / "kroger" / "*" / "*.json.gz")):
            env = json.loads(gzip.open(f).read())
            b = env["body"]
            b = json.loads(b) if isinstance(b, str) else b
            r = b.get("response")
            r = json.loads(r) if isinstance(r, str) else r
            for p in (r or {}).get("data") or []:
                for it in p.get("items") or []:
                    pr = it.get("price") or {}
                    if pr.get("promo") and pr.get("regular") and pr["promo"] < pr["regular"]:
                        rows.append((str(b.get("location_id")), p.get("productId"),
                                     (pr.get("effectiveDate") or {}).get("value"),
                                     (pr.get("expirationDate") or {}).get("value"), pr["regular"], pr["promo"]))
    d = pd.DataFrame(rows, columns=["store_id", "product", "eff", "exp", "regular", "promo"])
    d = d.drop_duplicates(["store_id", "product"])
    for c in ("eff", "exp"):
        d[c] = pd.to_datetime(d[c], utc=True, format="ISO8601", errors="coerce")
    return d[d["exp"].dt.year < 2100].dropna(subset=["eff", "exp"])


def promo_lengths(snaps: list[int], rng, B: int = 500) -> tuple[pd.DataFrame, dict]:
    """Planned promotion lengths L = expiration - effective, two ways:
      * harmonic: a snapshot samples promotions in proportion to their length
        (inspection paradox), so with equal weekly cohorts mu = 1 / E[1/L];
      * Lynden-Bell product-limit: a promotion is seen only if L > its age a
        (left truncation); allows any cohort sizes but assumes the same length
        mix in every cohort. simulation/validate_promo_lengths.py compares them."""
    from simulation.validate_promo_lengths import est_lynden
    d = kroger_expirations(snaps)
    obs = pd.read_sql_query("""SELECT s.store_id, MIN(o.observed_at) AS t FROM observations o JOIN stores s USING (store_pk)
                               WHERE s.chain = 'kroger' AND o.snapshot_id IN (%s) GROUP BY s.store_id""" % ",".join("?" * len(snaps)),
                            sqlite3.connect(DB), params=snaps)
    d = d.merge(obs, on="store_id")
    d["L"] = (d["exp"] - d["eff"]).dt.total_seconds() / 86400
    d["age"] = (pd.to_datetime(d["t"], utc=True, format="ISO8601") - d["eff"]).dt.total_seconds() / 86400
    d = d[(d["L"] > 0.5) & (d["age"] >= 0)]
    L, stores = d["L"].to_numpy(), d["store_id"].to_numpy()
    A = d["age"].to_numpy()
    u = np.unique(stores)
    idx = {s: np.flatnonzero(stores == s) for s in u}
    bs, lb = [], []
    for _ in range(B):
        i = np.concatenate([idx[s] for s in rng.choice(u, len(u))])
        bs.append(1 / np.mean(1 / L[i]))
        if len(lb) < 200:
            lb.append(est_lynden(A[i], np.round(L[i], 2)))
    weeks = np.round(L / 7)
    tab = (pd.Series(np.where(np.abs(L - 7 * weeks) < 1, weeks.astype(int).astype(str) + " wk", "other"))
           .value_counts().rename_axis("planned_length").reset_index(name="promotions"))
    exp_et = d["exp"] - pd.Timedelta(hours=4)
    summ = {"promotions": int(len(L)), "stores": int(len(u)),
            "sampled_mean_days": float(L.mean()), "length_bias_corrected_mean_days": float(1 / np.mean(1 / L)),
            "corrected_ci_lo": float(np.percentile(bs, 2.5)), "corrected_ci_hi": float(np.percentile(bs, 97.5)),
            "lynden_bell_mean_days": float(est_lynden(A, np.round(L, 2))),
            "lynden_ci_lo": float(np.percentile(lb, 2.5)), "lynden_ci_hi": float(np.percentile(lb, 97.5)),
            "mean_age_over_length": float(np.mean(np.clip(A / L, 0, 1))),
            "share_whole_weeks": float((np.abs(L - 7 * weeks) < 1).mean()),
            "share_expiring_tuesday_et": float((exp_et.dt.day_name() == "Tuesday").mean())}
    return tab, summ


def stock_table(k: pd.DataFrame) -> pd.DataFrame:
    ex = k["extra"].map(lambda e: json.loads(e) if isinstance(e, str) else {})
    s = ex.map(lambda e: e.get("stock_level")).fillna("not reported")
    kind = np.where(k["is_promo"] == 1, "promo", "regular")
    t = pd.crosstab(kind, s, normalize="index")
    t["n"] = pd.Series(kind).value_counts().reindex(t.index).to_numpy()
    return t.reset_index().rename(columns={"row_0": "kind"})


def timing_clusters(k: pd.DataFrame, zones: pd.Series, rng, n_perm: int = 999) -> dict:
    """Two independent views of one structure: cluster stores by TIMING alone
    (share of shared products whose price began in the same minute; average
    linkage, as many clusters as price zones) and compare with the price-level
    zones by adjusted Rand index. Baseline: zone labels shuffled within banner,
    so agreement explained by banners alone is not counted."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    from analysis.zone_model import adjusted_rand
    k = k[k["store_pk"].isin(zones.index)].drop_duplicates(["store_pk", "chain_product_id"])
    piv = k.assign(m=k["eff"].dt.floor("min")).pivot_table(index="store_pk", columns="chain_product_id",
                                                           values="m", aggfunc="first")
    A, S = piv.to_numpy(), piv.index.to_numpy()
    R = np.zeros((len(S), len(S)))
    for i in range(len(S)):
        ok = pd.notna(A[i]) & pd.notna(A)
        both = ok.sum(1)
        R[i] = np.where(both >= 20, ((A[i] == A) & ok).sum(1) / np.maximum(both, 1), 0)
    np.fill_diagonal(R, 1)
    zp = zones.reindex(S).to_numpy()
    banner = k.drop_duplicates("store_pk").set_index("store_pk")["banner"].reindex(S).to_numpy()
    zt = fcluster(linkage(squareform(1 - (R + R.T) / 2, checks=False), "average"), len(np.unique(zp)), "maxclust")
    obs = adjusted_rand(zt, zp)
    perm = []
    for _ in range(n_perm):
        zz = zp.copy()
        for b in np.unique(banner):
            idx = np.flatnonzero(banner == b)
            zz[idx] = rng.permutation(zz[idx])
        perm.append(adjusted_rand(zt, zz))
    perm = np.array(perm)
    return {"stores": int(len(S)), "price_zones": int(len(np.unique(zp))), "banners": int(len(np.unique(banner))),
            "ari_timing_vs_price_zones": obs, "ari_timing_vs_banners": adjusted_rand(zt, banner),
            "ari_price_zones_vs_banners": adjusted_rand(zp, banner),
            "ari_within_banner_shuffle_mean": float(perm.mean()),
            "p_value_one_sided": float((1 + (perm >= obs).sum()) / (1 + n_perm)), "n_perm": n_perm}


def kroger_zones(snaps: list[int]) -> pd.Series:
    """Kroger zones from Module E's table, or refit the same way (prices only)."""
    zt = TAB / "module_e_store_zones.csv"
    if zt.exists():
        z = pd.read_csv(zt)
        z = z[z["chain"] == "kroger"]
        if len(z):
            return z.set_index("store_pk")["zone"]
    from analysis.common import product_panel
    from analysis.module_e_architecture import chain_matrix
    from analysis.zone_model import fit_zones
    p = product_panel(load_observations(snapshot_id=snaps), min_stores=10)
    p = p[(p["chain"] == "kroger") & ~p["state"].isin(["HI", "AK"]) & p["lat"].notna()].copy()
    p["cents"] = p["regular_price"].round(2)
    st, M = chain_matrix(p, "kroger")
    z = fit_zones(M.to_numpy(float), seed=SEED)["partition"]
    return pd.Series(z, index=st.index, name="zone")


def figures(wd: pd.DataFrame, dur: pd.DataFrame, note: str) -> list[str]:
    plt = style()
    out = []
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.0))
    days = [c for c in wd.columns if c != "kind"]
    x = np.arange(len(days))
    for j, (kind, color) in enumerate((("regular", "#2a78d6"), ("promo", "#eb6834"))):
        row = wd[wd["kind"] == kind]
        if len(row):
            axes[0].bar(x + (j - 0.5) * 0.38, row[days].to_numpy()[0], width=0.36, color=color, label=kind)
    axes[0].set_xticks(x, [d[:3] for d in days])
    axes[0].set_ylabel("share of price start dates")
    axes[0].set_title("When Kroger prices start (weekday)", loc="left")
    axes[0].legend(fontsize=7)
    for kind, color in (("regular", "#2a78d6"), ("promo", "#eb6834")):
        g = dur[dur["kind"] == kind]
        if len(g):
            axes[1].step(g["age_lo_days"], g["spell_survival_S"], where="post", color=color, label=kind)
    axes[1].set_yscale("log")
    axes[1].set_xlabel("days")
    axes[1].set_ylabel("P(price lasts longer than t)")
    axes[1].set_title("Price durations recovered from ages (renewal theory)", loc="left")
    axes[1].legend(fontsize=7)
    caption(fig, note)
    fig.savefig(FIG / "fig_g1_price_timing.png")
    plt.close(fig)
    out.append("fig_g1_price_timing.png")
    return out


def figure_g2(hours: pd.DataFrame, lsum: dict, note: str) -> str:
    """(a) local hour of price starts; (b) mean promotion length by estimator."""
    plt = style()
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.0), gridspec_kw={"width_ratios": [1.15, 1]})
    fig.subplots_adjust(wspace=0.62)
    bands = [c for c in hours.columns if c not in ("kind", "n")]
    x = np.arange(len(bands))
    for j, (kind, color) in enumerate((("regular", "#2a78d6"), ("promo", "#eb6834"))):
        row = hours[hours["kind"] == kind]
        if len(row):
            axes[0].bar(x + (j - 0.5) * 0.38, row[bands].to_numpy(float)[0], width=0.36, color=color, label=kind)
    axes[0].set_xticks(x, bands)
    axes[0].set_xlabel("store local time")
    axes[0].set_ylabel("share of price starts")
    axes[0].set_title("Prices change overnight, not during the day", loc="left")
    axes[0].legend(fontsize=7)
    est = [("naive mean", lsum["sampled_mean_days"], None, None),
           ("ages (renewal)", lsum.get("ages_only_days", np.nan), None, None),
           ("1 / E[1/L]", lsum["length_bias_corrected_mean_days"], lsum["corrected_ci_lo"], lsum["corrected_ci_hi"]),
           ("Lynden-Bell", lsum["lynden_bell_mean_days"], lsum["lynden_ci_lo"], lsum["lynden_ci_hi"])]
    y = np.arange(len(est))[::-1]
    for yi, (lab, v, lo, hi) in zip(y, est):
        if lo is not None:
            axes[1].hlines(yi, lo, hi, color=INK, linewidth=2)
        axes[1].plot(v, yi, "o", color="#8b5cc7", markersize=7)
        axes[1].annotate(f"{v:.1f}", (v, yi), textcoords="offset points", xytext=(7, 4), fontsize=8, color=INK)
    axes[1].set_yticks(y, [e[0] for e in est])
    axes[1].set_xlabel("mean promotion length (days)")
    axes[1].set_title("One snapshot, four answers", loc="left")
    caption(fig, note)
    fig.savefig(FIG / "fig_g2_timing_lengths.png")
    plt.close(fig)
    return "fig_g2_timing_lengths.png"


def run(snaps: list[int] | None = None) -> str:
    snaps = snaps or main_snapshots()[:1]
    k = kroger_dated(snaps)
    if len(k) < 500:
        return "Module G: too few dated Kroger prices."
    rng = np.random.default_rng(SEED)
    wd = weekday_table(k)
    dur, summ = durations(k, rng)
    zones = kroger_zones(snaps)
    res = codating(k, zones, rng)
    res_min = codating(k, zones, rng, unit="minute")
    by_price = codating_by_price(k, zones)
    hours = local_hour_table(k)
    tclus = timing_clusters(k, zones, rng)
    lengths, lsum = promo_lengths(snaps, rng)
    stock = stock_table(k)
    note = (f"n = {len(k):,} dated Kroger prices, {k['store_pk'].nunique()} stores; snapshot(s) {snaps}. "
            f"PRELIMINARY; renewal estimate assumes stationary price spells.")
    TAB.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    wd.to_csv(TAB / "module_g_weekday.csv", index=False)
    dur.to_csv(TAB / "module_g_duration_curve.csv", index=False)
    pd.DataFrame([{"kind": kk, **v} for kk, v in summ.items()]).to_csv(TAB / "module_g_durations.csv", index=False)
    pd.DataFrame([res, res_min]).to_csv(TAB / "module_g_zone_codating.csv", index=False)
    by_price.to_csv(TAB / "module_g_codating_by_price.csv", index=False)
    hours.to_csv(TAB / "module_g_local_hour.csv", index=False)
    lengths.to_csv(TAB / "module_g_promo_lengths.csv", index=False)
    pd.DataFrame([lsum]).to_csv(TAB / "module_g_promo_length_summary.csv", index=False)
    stock.to_csv(TAB / "module_g_stock.csv", index=False)
    pd.DataFrame([tclus]).to_csv(TAB / "module_g_timing_clusters.csv", index=False)
    lsum["ages_only_days"] = summ.get("promo", {}).get("mean_spell_days_renewal", np.nan)
    pd.DataFrame([lsum]).to_csv(TAB / "module_g_promo_length_summary.csv", index=False)
    figs = figures(wd, dur, note) + [figure_g2(hours, lsum, note)]
    return f"Module G: wrote 10 tables and {len(figs)} figure. {note}"


if __name__ == "__main__":
    print(run())
    sys.exit(0)
