"""Flag Instacart "fallback" shops (DECISIONS #50) -> config/excluded_stores.csv.

Instacart storefronts (Costco, ALDI) return no store address, so a store's
location is approximated by the anchor ZIP that reached it. For ZIPs with no
nearby store, a storefront can return a far-away default shop: e.g. ALDI
location 5884 was returned for 37 ZIPs from Washington to Hawaii to Texas.
Rule: an Instacart location reached from anchor ZIPs more than MAX_SPREAD_KM
apart is a fallback, not a local store, and is excluded from analysis (its
attached location is not where its prices apply). Reads only saved raw shop
responses; no network.

  python -m scripts.flag_fallback_shops
"""
from __future__ import annotations

import glob
import gzip
import json
import re
import sys

import numpy as np
import pandas as pd

from analysis.estimators import haversine_km
from collectors.common import ROOT
from sampling.geo import zip_info

MAX_SPREAD_KM = 300.0
OUT = ROOT / "config" / "excluded_stores.csv"


def main() -> int:
    rows = []
    for chain in ("costco", "aldi"):
        for f in glob.glob(str(ROOT / "data" / "raw" / "snap*" / chain / "zip*" / "_shop__*.json.gz")):
            env = json.load(gzip.open(f, "rt", encoding="utf-8"))
            m = re.search(r'"retailerLocationId"\s*:\s*"(\d+)"', env["body"])
            if m:
                zi = zip_info(env["meta"].get("zip"))
                rows.append({"chain": chain, "store_id": m.group(1), "zip": env["meta"].get("zip"),
                             "lat": zi["lat"], "lon": zi["lon"]})
    d = pd.DataFrame(rows).dropna()
    out = []
    for (chain, sid), g in d.groupby(["chain", "store_id"]):
        if len(g) < 2:
            continue
        D = haversine_km(g.lat.values[:, None], g.lon.values[:, None], g.lat.values[None, :], g.lon.values[None, :])
        if D.max() > MAX_SPREAD_KM:
            out.append({"chain": chain, "store_id": sid, "reason": f"fallback shop: returned for {g['zip'].nunique()} "
                        f"anchor ZIPs up to {D.max():.0f} km apart ({', '.join(sorted(g['zip'].unique())[:6])}...)"})
    pd.DataFrame(out, columns=["chain", "store_id", "reason"]).to_csv(OUT, index=False)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out)} stores")
    for r in out:
        print(" ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
