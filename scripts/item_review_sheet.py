"""Build config/item_review.csv: one row per item, to speed up the owner's
review of which product (and UPC) each item is at each chain.

Evidence combined (no network):
  * Walmart / Target best candidates and runners-up (collectors.resolve_items:
    config/items_resolved.csv, config/item_candidates.csv). Walmart's best has a
    UPC from its product page; Target's has none while Target is blocked.
  * Meijer and Kroger search results already in the database: these carry a
    UPC for EVERY product, so the best name+size match there gives an
    independent proposed UPC.
  * Agreement: Walmart's chosen UPC equal to Meijer's or Kroger's proposed UPC
    is strong evidence both picked the same product.

Columns `confirmed_*` are left blank for the owner to fill; copy the confirmed
values into config/items.csv (walmart_id, target_tcin, upc). Nothing is
written into items.csv automatically (DECISIONS #14).

Usage:  python -m scripts.item_review_sheet
"""
from __future__ import annotations

import sqlite3
import sys

import pandas as pd

from collectors.resolve_items import score, size_match
from db.init_db import DEFAULT_DB
from collectors.common import ROOT


# Store/private-label brands: never the same UPC as a national brand, so they
# are not proposed for cross-chain (national-brand) items.
STORE_BRANDS = ("meijer", "great value", "market pantry", "good & gather", "kroger", "simple truth",
                "kirkland", "member's mark", "equate", "up&up", "up & up", "mainstays", "marketside",
                "freshness guaranteed", "private selection", "true goodness", "boogie")


def best_with_upc(obs: pd.DataFrame, item: dict, chain: str) -> dict:
    """Highest-scoring product with a UPC for this item at this chain
    (store brands excluded for cross-chain items)."""
    g = obs[(obs["chain"] == chain) & (obs["item_id"] == item["item_id"]) & obs["upc"].notna()]
    if item.get("cross_chain") == "1":
        low = g["product_name"].str.lower()
        g = g[~low.apply(lambda n: any(b in n for b in STORE_BRANDS))]
    g = g.drop_duplicates("upc")
    if g.empty:
        return {}
    sc = g["product_name"].map(lambda n: score(item, n))
    r = g.loc[sc.idxmax()]
    return {f"{chain}_name": r["product_name"], f"{chain}_upc": r["upc"], f"{chain}_score": float(sc.max()),
            f"{chain}_size_match": int(size_match(item, r["product_name"]))}


def main() -> int:
    items = pd.read_csv(ROOT / "config" / "items.csv", dtype=str, keep_default_na=False)
    res = pd.read_csv(ROOT / "config" / "items_resolved.csv", dtype=str)
    cand = pd.read_csv(ROOT / "config" / "item_candidates.csv", dtype=str)
    con = sqlite3.connect(DEFAULT_DB)
    obs = pd.read_sql_query("""SELECT s.chain, o.item_id, o.product_name, o.upc FROM observations o
                               JOIN stores s USING (store_pk) WHERE s.chain IN ('meijer', 'kroger')""", con)
    con.close()

    rows = []
    for it in items.to_dict("records"):
        row = {"item_id": it["item_id"], "name": it["name"], "size": f"{it['size_value']} {it['size_unit']}".strip(),
               "cross_chain": it["cross_chain"]}
        for ch, idcol in (("walmart", "walmart_id"), ("target", "target_tcin")):
            b = res[(res["item_id"] == it["item_id"]) & (res["chain"] == ch)]
            if not b.empty:
                b = b.iloc[0]
                row.update({f"{ch}_best_id": b["chain_product_id"], f"{ch}_best_name": b["product_name"],
                            f"{ch}_best_score": b["score"], f"{ch}_best_upc": b.get("upc")})
            alts = cand[(cand["item_id"] == it["item_id"]) & (cand["chain"] == ch)]
            row[f"{ch}_alternatives"] = " | ".join(f"{a.chain_product_id}: {a.product_name[:60]}"
                                                   for a in alts.iloc[1:3].itertuples())
        row.update(best_with_upc(obs, it, "meijer"))
        row.update(best_with_upc(obs, it, "kroger"))
        wu = row.get("walmart_best_upc")
        agree = [c for c in ("meijer", "kroger") if wu and row.get(f"{c}_upc") == wu]
        row["walmart_upc_agrees_with"] = ",".join(agree)
        # Simple triage for the owner (not a decision):
        if agree:
            # Same product at two chains -- check it is the intended VARIANT
            # (e.g. both may have picked Rao's Creamy Marinara).
            row["triage"] = "UPC agrees across chains: confirm the variant"
        elif row.get("meijer_upc") and float(row.get("meijer_score") or 0) >= 1.5:
            row["triage"] = "check Walmart pick: Meijer proposes a different UPC"
        else:
            row["triage"] = "check by hand"
        row.update({"confirmed_upc": "", "confirmed_walmart_id": "", "confirmed_target_tcin": ""})
        rows.append(row)
    out = pd.DataFrame(rows)
    path = ROOT / "config" / "item_review.csv"
    out.to_csv(path, index=False)
    print(f"wrote {path.relative_to(ROOT)} ({len(out)} items)")
    print(out["triage"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
