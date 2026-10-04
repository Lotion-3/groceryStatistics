"""Rule-based item review (DECISIONS #48: the owner delegated the review).

For each cross-chain item, decide which product (and UPC) the item is at each
chain, from evidence already collected -- no network. Every decision records
its evidence; anything uncertain is left blank (a missing match costs a
little data, a wrong match would contaminate cross-chain results).

Rules
  1. Canonical UPC. Among the item's products at Kroger (production API) and
     Meijer -- both report a UPC for every product -- take the best
     national-brand match: name-token score >= 1.5 AND size match, store
     brands excluded, ties broken by the number of stores carrying it.
       * both chains' best agree           -> evidence "kroger+meijer"
       * only one chain has a match        -> that chain
       * they disagree                     -> the higher score; flagged
  2. Walmart. walmart_id is set only if the UPC on Walmart's product page for
     its best candidate equals the canonical UPC ("upc").
  3. Target. Product pages were unavailable, so no UPC: target_tcin is set
     only for a strong name match with a size match (score >= 1.75) among
     the products Target returned, labelled "name+size" (weaker evidence).
  4. Perishables (cross_chain = 0) are within-chain only: not reviewed.

Outputs: config/item_review_auto.csv (all evidence) and the confirmed values
written into config/items.csv (upc, walmart_id, target_tcin).

Usage: python -m scripts.auto_item_review [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from analysis.common import ROOT, load_observations
from collectors.resolve_items import score, size_match
from scripts.item_review_sheet import STORE_BRANDS


import re

from collectors.resolve_items import tokens

# Words marking a different variant/format. A candidate containing one that the
# item's own name/search term does not contain is rejected (stricter than the
# ranking heuristic in collectors/resolve_items.py).
VARIANT = {"max", "zero", "diet", "creamy", "mascarpone", "roasted", "garlic", "herbs", "herb", "homestyle",
           "extra", "toasty", "variety", "sport", "odor", "defense", "oxi", "febreze", "smooth", "silky",
           "calming", "gravy", "turkey", "lamb", "salmon", "seafood", "fish", "thin", "thick", "light", "lite",
           "sensitive", "pm", "nighttime", "mini", "minis", "reduced", "sodium", "spicy", "flavored",
           "cinnamon", "vanilla", "chocolate", "strawberry", "unsalted", "organic", "decaf", "dark", "bold",
           "blend", "wash", "plus", "advanced", "ultra", "gain", "pine", "scented", "lavender",
           "whitening", "gluten", "multi", "grain", "wild", "cherry", "salt", "added", "italian", "harvest",
           "vapor", "bath", "soothing", "liver", "dinner", "itchy", "kids", "protein", "keto"}
_PACK = re.compile(r"\b\d+\s*(?:pk|pack|count pack)\b|\bpack of \d+|\(\s*\d+\s*pack\s*\)|/\s*\d+\s*pk|\b\d+x\d+|\b[2-9]\s*count\b", re.IGNORECASE)
KROGER_BANNER_BRANDS = ("harris teeter", "ralphs", "fred meyer", "king soopers", "smith's", "fry's", "mariano's",
                        "dillons", "home chef", "heritage farm", "kroger")


def _brand_token(item: dict) -> str:
    """First word of the item name, normalised (e.g. "kelloggs", "raos")."""
    w = re.findall(r"[a-z0-9]+", item["name"].lower().replace("'", ""))
    return w[0] if w else ""


def _acceptable(item: dict, name: str) -> bool:
    if _brand_token(item) not in re.findall(r"[a-z0-9]+", (name or "").lower().replace("'", "").replace("’", "")):
        return False                                          # a different brand (e.g. Mom's Best vs Kellogg's)
    allowed = tokens(item["name"]) | tokens(item["search_term"])
    if (tokens(name) & VARIANT) - allowed:
        return False
    is_pack_item = bool(re.search(r"pack|pk|\bct\b|count", item["search_term"], re.I))
    if _PACK.search(name or "") and not is_pack_item:
        return False
    low = (name or "").lower()
    return not any(b in low for b in STORE_BRANDS + KROGER_BANNER_BRANDS)


def _best(g: pd.DataFrame, item: dict, with_size_col: bool) -> dict:
    """Best national-brand product for an item among one chain's products."""
    if g.empty:
        return {}
    d = g.groupby(["upc", "product_name", "pack_size"], dropna=False)["store_pk"].nunique().reset_index(name="stores")
    d = d[d["product_name"].map(lambda n: _acceptable(item, n))]
    if d.empty:
        return {}
    text = d["product_name"] + (" " + d["pack_size"].fillna("") if with_size_col else "")
    d["score"] = text.map(lambda t: score(item, t))
    d["size_ok"] = text.map(lambda t: size_match(item, t))
    d = d[(d["score"] >= 1.5) & d["size_ok"]]
    if d.empty:
        return {}
    r = d.sort_values(["score", "stores"], ascending=False).iloc[0]
    return {"upc": r["upc"], "name": r["product_name"], "score": float(r["score"]), "stores": int(r["stores"])}


# Manual vetoes after reading every row (2026-10-03). A vetoed field is left
# blank; each veto states why. Applied after the rules.
VETO = {
    "pas_raos_marinara_24": {"target_tcin": "Target pick is a bundle (marinara + Alfredo)"},
    "hh_tide_original_92": {"target_tcin": "Target pick is Tide + Downy, a different variant"},
    "pc_head_shoulders_classic_12_5": {"target_tcin": "Target pick is 2-in-1 with tea tree oil"},
    "otc_tylenol_es_100": {"target_tcin": "Target pick is 'Easy to Swallow' caplets, likely a different product"},
    "baby_johnsons_shampoo_13_6": {"target_tcin": "Target name does not clearly match the Kroger/Meijer UPC product"},
    "pet_friskies_pate_mixed_grill_5_5": {"upc": "Meijer name does not state the Mixed Grill flavour",
                                          "target_tcin": "Target name is ambiguous about the flavour"},
    "pc_colgate_cavity_6": {"upc": "Kroger pick is 'Mint Flavor'; item is the Regular flavour"},
}


def review() -> pd.DataFrame:
    items = pd.read_csv(ROOT / "config" / "items.csv", dtype=str, keep_default_na=False)
    resolved = pd.read_csv(ROOT / "config" / "items_resolved.csv", dtype=str)
    obs = load_observations(store_specific_only=False)
    rows = []
    for it in items.to_dict("records"):
        row = {"item_id": it["item_id"], "name": it["name"], "size": f"{it['size_value']} {it['size_unit']}"}
        if it["cross_chain"] != "1":
            rows.append({**row, "decision": "perishable: within-chain only"})
            continue
        kb = _best(obs[(obs.chain == "kroger") & (obs.item_id == it["item_id"]) & obs.upc.notna()], it, True)
        mb = _best(obs[(obs.chain == "meijer") & (obs.item_id == it["item_id"]) & obs.upc.notna()], it, False)
        row.update({"kroger_upc": kb.get("upc"), "kroger_name": kb.get("name"), "kroger_score": kb.get("score"),
                    "meijer_upc": mb.get("upc"), "meijer_name": mb.get("name"), "meijer_score": mb.get("score")})
        if kb and mb and kb["upc"] == mb["upc"]:
            canon, ev = kb["upc"], "kroger+meijer"
        elif kb and mb:
            canon, ev = (kb["upc"], "kroger (disagrees with meijer)") if kb["score"] >= mb["score"] \
                else (mb["upc"], "meijer (disagrees with kroger)")
        elif kb or mb:
            canon, ev = (kb or mb)["upc"], "kroger" if kb else "meijer"
        else:
            canon, ev = None, "none"
        row.update({"upc": canon, "upc_evidence": ev})

        w = resolved[(resolved.item_id == it["item_id"]) & (resolved.chain == "walmart")]
        w_upc = w["upc"].iloc[0] if len(w) else None
        row.update({"walmart_best_id": w["chain_product_id"].iloc[0] if len(w) else None,
                    "walmart_best_name": w["product_name"].iloc[0] if len(w) else None, "walmart_page_upc": w_upc})
        row["walmart_id"] = row["walmart_best_id"] if canon and w_upc == canon else None
        row["walmart_evidence"] = "upc" if row["walmart_id"] else ("no canonical UPC" if not canon else
                                                                   "walmart pick has a different UPC")

        t = obs[(obs.chain == "target") & (obs.item_id == it["item_id"])]
        t = t.drop_duplicates("chain_product_id")
        if len(t):
            t = t.assign(score=t["product_name"].map(lambda n: score(it, n)),
                         size_ok=t["product_name"].map(lambda n: size_match(it, n)))
            t = t[(t["score"] >= 1.75) & t["size_ok"] & t["product_name"].map(lambda n: _acceptable(it, n))]
            t = t.sort_values("score", ascending=False)
        if len(t):
            row.update({"target_tcin": t["chain_product_id"].iloc[0], "target_name": t["product_name"].iloc[0],
                        "target_evidence": "name+size"})
        else:
            row.update({"target_tcin": None, "target_name": None, "target_evidence": "no strong name+size match"})
        notes = []
        for field, why in VETO.get(it["item_id"], {}).items():
            row[field] = None
            if field == "upc":                       # no canonical UPC -> Walmart cannot be confirmed either
                row["walmart_id"], row["walmart_evidence"] = None, "no canonical UPC (vetoed)"
            notes.append(f"{field}: {why}")
        row["manual_veto"] = "; ".join(notes)
        row["decision"] = "reviewed"
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    r = review()
    r.to_csv(ROOT / "config" / "item_review_auto.csv", index=False)
    x = r[r["decision"] == "reviewed"]
    print(f"{len(x)} cross-chain items: canonical UPC for {x['upc'].notna().sum()}; "
          f"Walmart confirmed by UPC {x['walmart_id'].notna().sum()}; Target by name+size {x['target_tcin'].notna().sum()}")
    print(x["upc_evidence"].value_counts().to_string())
    if not a.dry_run:
        items = pd.read_csv(ROOT / "config" / "items.csv", dtype=str, keep_default_na=False)
        m = r.set_index("item_id")
        for col in ("upc", "walmart_id", "target_tcin"):
            items[col] = items["item_id"].map(m[col]).fillna("").astype(str).replace({"None": "", "nan": ""})
        items.to_csv(ROOT / "config" / "items.csv", index=False)
        print("wrote config/items.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
