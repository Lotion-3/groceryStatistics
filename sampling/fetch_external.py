"""Download the public reference files used to build the store frame.

  * Census 2024 ZCTA Gazetteer (ZCTA internal-point lat/lon)
  * USDA ERS 2020 Rural-Urban Commuting Area codes by ZIP (state + RUCA)
  * ACS 2023 5-year estimates by ZCTA (Module C covariates), one Census API
    request for all ZCTAs. The API requires a free key: set CENSUS_API_KEY
    (https://api.census.gov/data/key_signup.html); without it this step is
    skipped and Module C reports that its covariates are missing.

Files land in data/external/ (gitignored); SHA-256 sums are printed so a
reproduction can confirm it used the same vintages (recorded in SAMPLING.md).
"""
from __future__ import annotations

import hashlib
import os
import io
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external"

ZCTA_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
RUCA_URL = "https://www.ers.usda.gov/media/5444/2020-rural-urban-commuting-area-codes-zip-codes.csv?v=18641"

# ACS 2023 5-year, table variables used as Module C covariates (see module_c_hd.py).
ACS_VARS = {
    "B19013_001E": "median_hh_income",
    "B01003_001E": "population",
    "B01002_001E": "median_age",
    "B25077_001E": "median_home_value",
    "B25064_001E": "median_gross_rent",
    "B17001_001E": "poverty_universe",
    "B17001_002E": "poverty_count",
    "B15003_001E": "edu_universe",
    "B15003_022E": "edu_bachelors",
    "B15003_023E": "edu_masters",
    "B15003_024E": "edu_professional",
    "B15003_025E": "edu_doctorate",
    "B08301_001E": "commute_universe",
    "B08301_010E": "commute_transit",
    "B25044_001E": "hh_universe",
    "B25044_003E": "hh_owner_no_vehicle",
    "B25044_010E": "hh_renter_no_vehicle",
}
ACS_URL = ("https://api.census.gov/data/2023/acs/acs5?get=" + ",".join(ACS_VARS)
           + "&for=zip%20code%20tabulation%20area:*")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gaz = OUT / "2024_Gaz_zcta_national.txt"
    if not gaz.exists():
        r = requests.get(ZCTA_URL, timeout=60)
        r.raise_for_status()
        print(f"zcta zip sha256={_sha(r.content)}")
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(OUT)
    ruca = OUT / "ruca2020_zip.csv"
    if not ruca.exists():
        r = requests.get(RUCA_URL, timeout=60)
        r.raise_for_status()
        ruca.write_bytes(r.content)
    acs = OUT / "acs2023_5yr_zcta.csv"
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not acs.exists() and not key:
        print("SKIP ACS: set CENSUS_API_KEY (free: https://api.census.gov/data/key_signup.html)")
    elif not acs.exists():
        import csv
        r = requests.get(ACS_URL + "&key=" + key, timeout=120)
        r.raise_for_status()
        rows = r.json()
        with acs.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["zcta"] + [ACS_VARS[v] for v in rows[0][:-1]])
            for row in rows[1:]:
                w.writerow([row[-1]] + row[:-1])
    print(f"{gaz.name} sha256={_sha(gaz.read_bytes())}")
    if acs.exists():
        print(f"{acs.name} sha256={_sha(acs.read_bytes())}")
    print(f"{ruca.name} sha256={_sha(ruca.read_bytes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
