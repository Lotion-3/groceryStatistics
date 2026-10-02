"""Build the Target sampling frame and draw the stratified store sample.

Steps (documented in docs/SAMPLING.md):
  1. Frame = all 1,893 stores in the vendored target_store_directory.json.
  2. Attach the nearest Census ZCTA (by internal point) -> ZIP.
  3. Attach state and primary RUCA code from the USDA 2020 ZIP RUCA file,
     map state -> Census region and RUCA -> urbanicity class.
  4. Draw n_target stores with a fixed seed, proportional allocation across
     region x urbanicity strata (largest-remainder rounding), simple random
     sampling within each stratum.

Outputs:
  data/processed/target_frame.csv   full frame with covariates (committed)
  config/store_sample.csv           the drawn Target sample (committed)

Usage:  python sampling/build_frame.py [--n 250] [--seed 20261001]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "config" / "sampling.yaml").read_text())

CENSUS_REGION = {
    "Northeast": ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"],
    "Midwest": ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "South": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN",
              "AR", "LA", "OK", "TX"],
    "West": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"],
}
STATE_TO_REGION = {s: r for r, ss in CENSUS_REGION.items() for s in ss}


def _unit_xyz(lat, lon):
    """Lat/lon (deg) -> 3-D unit vectors, so Euclidean nearest = great-circle nearest."""
    la, lo = np.radians(lat), np.radians(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


def load_zcta() -> pd.DataFrame:
    z = pd.read_csv(ROOT / CFG["external"]["zcta_gazetteer"], sep="\t", dtype={"GEOID": str})
    z.columns = [c.strip() for c in z.columns]
    return z.rename(columns={"GEOID": "zip", "INTPTLAT": "zlat", "INTPTLONG": "zlon",
                             "ALAND_SQMI": "zcta_land_sqmi"})[["zip", "zlat", "zlon", "zcta_land_sqmi"]]


def load_ruca() -> pd.DataFrame:
    r = pd.read_csv(ROOT / CFG["external"]["ruca_zip"], dtype={"ZIPCode": str})
    r = r.rename(columns={"ZIPCode": "zip", "State": "state", "PrimaryRUCA": "ruca"})
    r["ruca"] = pd.to_numeric(r["ruca"], errors="coerce")
    return r[["zip", "state", "ruca"]]


def ruca_to_class(ruca: float) -> str | None:
    if pd.isna(ruca):
        return None
    for cls, codes in CFG["urbanicity_from_ruca"].items():
        if int(ruca) in codes:
            return cls
    return None


LOCATIONS = ROOT / "data" / "processed" / "target_store_locations.csv"


def build_frame() -> pd.DataFrame:
    """Frame of all directory stores with ZIP, state, region, RUCA, urbanicity.

    Location source, best first:
      zip_centroid  ZIP from the store address Target itself reports
                    (sampling/locate_target_stores.py), located at that
                    ZIP's ZCTA internal point;
      slug_geocode  the vendored directory's slug geocode, snapped to the
                    nearest ZCTA. UNRELIABLE (~25% wrong; REPO_NOTES.md)."""
    stores = pd.DataFrame(json.loads(
        (ROOT / "collectors" / "vendor" / "target_store_directory.json").read_text()))
    zcta = load_zcta()
    tree = cKDTree(_unit_xyz(zcta["zlat"].to_numpy(), zcta["zlon"].to_numpy()))
    chord, idx = tree.query(_unit_xyz(stores["lat"].to_numpy(), stores["lon"].to_numpy()))
    stores["zip"] = zcta["zip"].to_numpy()[idx]
    stores["zcta_dist_km"] = 2 * 6371.0 * np.arcsin(np.clip(chord / 2, 0, 1))
    stores["coord_quality"] = "slug_geocode"

    if LOCATIONS.exists():
        loc = pd.read_csv(LOCATIONS, dtype=str)
        loc["true_zip"] = loc["postal_code"].str[:5]
        stores = stores.merge(loc[["store_id", "true_zip", "name", "address_line1", "city"]],
                              on="store_id", how="left")
        z = zcta.set_index("zip")
        has = stores["true_zip"].isin(z.index)
        stores.loc[has, "zip"] = stores.loc[has, "true_zip"]
        stores.loc[has, "lat"] = z.loc[stores.loc[has, "zip"], "zlat"].to_numpy()
        stores.loc[has, "lon"] = z.loc[stores.loc[has, "zip"], "zlon"].to_numpy()
        stores.loc[has, "zcta_dist_km"] = 0.0
        stores.loc[has, "coord_quality"] = "zip_centroid"
        stores = stores.drop(columns=["true_zip"])

    stores = stores.merge(load_ruca().drop_duplicates("zip"), on="zip", how="left")
    stores["region"] = stores["state"].map(STATE_TO_REGION)
    stores["urbanicity"] = stores["ruca"].map(ruca_to_class)
    stores["chain"] = "target"
    stores["eligible"] = (
        stores["region"].notna() & stores["urbanicity"].notna()
        & (stores["zcta_dist_km"] <= CFG["max_zcta_distance_km"])
    )
    return stores


def allocate(sizes: pd.Series, n: int) -> pd.Series:
    """Proportional allocation with largest-remainder rounding (sums to n)."""
    exact = sizes / sizes.sum() * n
    alloc = np.floor(exact).astype(int)
    short = n - alloc.sum()
    order = (exact - alloc).sort_values(ascending=False).index[:short]
    alloc.loc[order] += 1
    return np.minimum(alloc, sizes)


def draw_sample(frame: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    elig = frame[frame["eligible"]]
    strata = CFG["strata"]
    sizes = elig.groupby(strata).size()
    alloc = allocate(sizes, n)
    rng = np.random.default_rng(seed)
    parts = []
    # Iterate strata in sorted order so the draw is reproducible.
    for key in sorted(alloc.index):
        k = int(alloc.loc[key])
        if k == 0:
            continue
        grp = elig.set_index(strata).loc[[key]].reset_index().sort_values("store_id")
        take = rng.choice(len(grp), size=k, replace=False)
        parts.append(grp.iloc[np.sort(take)])
    return pd.concat(parts, ignore_index=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=CFG["n_target"])
    ap.add_argument("--seed", type=int, default=CFG["seed"])
    args = ap.parse_args(argv)

    frame = build_frame()
    out = ROOT / "data" / "processed"
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "target_frame.csv", index=False)

    sample = draw_sample(frame, args.n, args.seed)
    # Visit order: a seeded random permutation, so that a snapshot stopped
    # part-way (e.g. a chain blocked) has covered a random subsample of all
    # strata rather than whole regions in turn (DECISIONS #31).
    sample = sample.sample(frac=1.0, random_state=args.seed + 1).reset_index(drop=True)
    sample["visit_order"] = np.arange(1, len(sample) + 1)
    cols = ["chain", "store_id", "slug", "lat", "lon", "zip", "state", "region",
            "urbanicity", "ruca", "zcta_dist_km", "coord_quality", "visit_order"]
    sample[cols].to_csv(ROOT / "config" / "store_sample.csv", index=False)

    print(f"Frame: {len(frame)} Target stores; eligible {int(frame['eligible'].sum())} "
          f"(excluded: {int((~frame['eligible']).sum())})")
    print("Frame by stratum (eligible):")
    print(frame[frame["eligible"]].groupby(CFG["strata"]).size().unstack(fill_value=0))
    print(f"\nSample: {len(sample)} stores (seed {args.seed})")
    print(sample.groupby(CFG["strata"]).size().unstack(fill_value=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
