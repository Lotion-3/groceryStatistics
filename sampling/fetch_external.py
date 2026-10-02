"""Download the public reference files used to build the store frame.

  * Census 2024 ZCTA Gazetteer (ZCTA internal-point lat/lon)
  * USDA ERS 2020 Rural-Urban Commuting Area codes by ZIP (state + RUCA)

Files land in data/external/ (gitignored); SHA-256 sums are printed so a
reproduction can confirm it used the same vintages (recorded in SAMPLING.md).
"""
from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external"

ZCTA_URL = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_zcta_national.zip"
RUCA_URL = "https://www.ers.usda.gov/media/5444/2020-rural-urban-commuting-area-codes-zip-codes.csv?v=18641"


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
    print(f"{gaz.name} sha256={_sha(gaz.read_bytes())}")
    print(f"{ruca.name} sha256={_sha(ruca.read_bytes())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
