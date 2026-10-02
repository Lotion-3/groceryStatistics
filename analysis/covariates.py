"""Store-level covariates for Module C (and B), joined by the store's ZIP.

Sources (public, downloaded by sampling/fetch_external.py; vintages in SAMPLING.md):
  * ACS 2023 5-year by ZCTA: income, population, age, housing, poverty,
    education, transit commuting, households without a vehicle
  * Census 2024 ZCTA gazetteer: land area -> population density
  * USDA RUCA 2020 (already on the stores table): urbanicity class
  * OpenStreetMap store layers (data/processed/osm_stores.csv): distance to the
    nearest store of each OTHER chain, and the number of other-chain stores
    within 10 km (a crude local-competition measure)

ZIP codes are matched to ZCTAs of the same number. The two mostly coincide,
but not always (PO-box ZIPs have no ZCTA); unmatched stores get NaN and are
dropped by the models, and the count is reported.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.common import ROOT
from analysis.estimators import haversine_km

EXT = ROOT / "data" / "external"
COMPETITORS = ("walmart", "target", "costco", "trader_joes")

# Columns fed to the models, with plain-language labels for tables and figures.
LABELS = {
    "log_income": "log median household income",
    "log_density": "log population density (per sq mi)",
    "median_age": "median age",
    "log_home_value": "log median home value",
    "log_rent": "log median gross rent",
    "poverty_rate": "poverty rate",
    "college_share": "share with bachelor's or higher",
    "transit_share": "share commuting by transit",
    "no_vehicle_share": "share of households with no vehicle",
    "suburban": "RUCA suburban (vs urban)",
    "rural": "RUCA rural (vs urban)",
    "log_km_walmart": "log km to nearest Walmart",
    "log_km_target": "log km to nearest Target",
    "log_km_costco": "log km to nearest Costco",
    "log_km_trader_joes": "log km to nearest Trader Joe's",
    "rivals_10km": "other-chain stores within 10 km",
}


def acs_by_zcta() -> pd.DataFrame:
    a = pd.read_csv(EXT / "acs2023_5yr_zcta.csv", dtype={"zcta": str})
    num = a.columns.drop("zcta")
    a[num] = a[num].apply(pd.to_numeric, errors="coerce")
    a[num] = a[num].where(a[num] >= 0)          # ACS uses large negative codes for "not available"
    g = pd.read_csv(EXT / "2024_Gaz_zcta_national.txt", sep="\t", dtype={"GEOID": str})
    g.columns = [c.strip() for c in g.columns]
    a = a.merge(g[["GEOID", "ALAND_SQMI"]].rename(columns={"GEOID": "zcta"}), on="zcta", how="left")

    out = pd.DataFrame({"zcta": a["zcta"]})
    out["log_income"] = np.log(a["median_hh_income"])
    out["log_density"] = np.log1p(a["population"] / a["ALAND_SQMI"].where(a["ALAND_SQMI"] > 0))
    out["median_age"] = a["median_age"]
    out["log_home_value"] = np.log(a["median_home_value"])
    out["log_rent"] = np.log(a["median_gross_rent"])
    out["poverty_rate"] = a["poverty_count"] / a["poverty_universe"]
    out["college_share"] = (a[["edu_bachelors", "edu_masters", "edu_professional", "edu_doctorate"]].sum(axis=1)
                            / a["edu_universe"])
    out["transit_share"] = a["commute_transit"] / a["commute_universe"]
    out["no_vehicle_share"] = (a["hh_owner_no_vehicle"] + a["hh_renter_no_vehicle"]) / a["hh_universe"]
    return out.replace([np.inf, -np.inf], np.nan)


def competition(stores: pd.DataFrame, radius_km: float = 10.0) -> pd.DataFrame:
    """Distance (km) from each store to the nearest OSM store of every other
    chain, and the count of other-chain OSM stores within radius_km."""
    osm = pd.read_csv(ROOT / "data" / "processed" / "osm_stores.csv").dropna(subset=["lat", "lon"])
    rows = []
    for s in stores.itertuples():
        r = {"store_pk": s.store_pk}
        rivals = 0
        for c in COMPETITORS:
            if c == s.chain:
                continue          # own chain: the store's own OSM point would be its "nearest"
            o = osm[osm["chain"] == c]
            d = haversine_km(s.lat, s.lon, o["lat"].to_numpy(), o["lon"].to_numpy())
            r[f"log_km_{c}"] = np.log1p(d.min())
            rivals += int((d <= radius_km).sum())
        r["rivals_10km"] = rivals
        rows.append(r)
    return pd.DataFrame(rows)


def store_covariates(stores: pd.DataFrame) -> pd.DataFrame:
    """stores needs: store_pk, chain, zip, lat, lon, urbanicity, state, region.
    Returns one row per store with the LABELS columns (own-chain distance NaN)."""
    s = stores.copy()
    s["zcta"] = s["zip"].astype(str).str[:5].str.zfill(5)
    out = s.merge(acs_by_zcta(), on="zcta", how="left")
    out["suburban"] = (out["urbanicity"] == "suburban").astype(float)
    out["rural"] = (out["urbanicity"] == "rural").astype(float)
    out = out.merge(competition(s.dropna(subset=["lat", "lon"])), on="store_pk", how="left")
    return out
