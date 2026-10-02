"""ZIP-level lookups from the public reference files (no network calls)."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

from sampling.build_frame import STATE_TO_REGION, load_ruca, load_zcta, ruca_to_class


@lru_cache(maxsize=1)
def _tables():
    z = load_zcta().set_index("zip")
    r = load_ruca().drop_duplicates("zip").set_index("zip")
    return z, r


def zip_info(zip_code: Optional[str]) -> dict:
    """{lat, lon, state, region, ruca, urbanicity} for a 5-digit ZIP (ZCTA
    internal point); missing fields are None."""
    out = {"lat": None, "lon": None, "state": None, "region": None, "ruca": None, "urbanicity": None}
    if not zip_code:
        return out
    z5 = str(zip_code).strip()[:5].zfill(5)
    zt, rt = _tables()
    if z5 in zt.index:
        out["lat"], out["lon"] = float(zt.at[z5, "zlat"]), float(zt.at[z5, "zlon"])
    if z5 in rt.index:
        out["state"] = rt.at[z5, "state"]
        ruca = rt.at[z5, "ruca"]
        out["ruca"] = None if ruca != ruca else int(ruca)
        out["urbanicity"] = ruca_to_class(ruca)
        out["region"] = STATE_TO_REGION.get(out["state"])
    return out


def zip_from_address(address: str) -> Optional[str]:
    """Last 5-digit group in 'line1, city, ST, 12345' style addresses."""
    m = re.findall(r"\b(\d{5})(?:-\d{4})?\b", address or "")
    return m[-1] if m else None


@lru_cache(maxsize=1)
def _osm():
    import pandas as pd
    from sampling.build_frame import ROOT
    p = ROOT / "data" / "processed" / "osm_stores.csv"
    if not p.exists():
        return None
    o = pd.read_csv(p, dtype={"ref": str, "postcode": str})
    # store features only (Walmart's garden centres / auto centres share the ref)
    o = o[o["shop"].isin(["supermarket", "department_store", "wholesale", "variety_store"])]
    return o.dropna(subset=["ref"]).drop_duplicates(["chain", "ref"]).set_index(["chain", "ref"])


def osm_coords(chain: str, ref: str) -> Optional[tuple[float, float]]:
    """(lat, lon) of the OSM feature whose `ref` is this store number, if any.
    Verified for Walmart (refs 2098, 5732 match Walmart's own store ids)."""
    o = _osm()
    if o is None or (chain, str(ref)) not in o.index:
        return None
    r = o.loc[(chain, str(ref))]
    return float(r["lat"]), float(r["lon"])
