"""Resolve each item in config/items.csv to a concrete product per chain.

For each item and chain, the search results already saved in data/raw/ (from
the latest snapshot that has them) are scored against the item's name and
size. The top candidates go to config/item_candidates.csv. For Walmart and
Target the single best candidate's product page is fetched once to read its
UPC (search results carry no UPC on either chain).

Output: config/item_candidates.csv (top 3 per item x chain, for review) and
        config/items_resolved.csv (best candidate per item x chain + UPC).
Nothing is written back into config/items.csv automatically: the owner
reviews items_resolved.csv and copies confirmed IDs/UPCs (see README).

Usage:
  python -m collectors.resolve_items [--items a,b,c] [--fetch-upc] [--chains walmart,target]

--fetch-upc generates retailer traffic (one product page per item per chain).
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
from pathlib import Path

from collectors import parsers
from collectors.common import RAW_DIR, ROOT, ChainBlocked, TransientError, save_raw, with_backoff

_STOP = {"the", "and", "of", "with", "for", "a", "oz", "fl", "ct", "count", "pack", "pk", "lb",
         "size", "family", "original", "classic"}


def tokens(s: str) -> set[str]:
    s = (s or "").lower().replace("'", "")
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in _STOP and not t.isdigit()}


_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*-?\s*(fl\.?\s*oz|oz|ounce|lb|lbs|pound|ct|count|pk|pack|l|liter)\b",
                      re.IGNORECASE)


def sizes_in(name: str) -> list[tuple[float, str]]:
    out = []
    for v, u in _SIZE_RE.findall(name or ""):
        u = u.lower().replace(".", "").replace(" ", "")
        u = {"ounce": "oz", "lbs": "lb", "pound": "lb", "count": "ct", "pack": "pk", "liter": "l"}.get(u, u)
        out.append((float(v), u))
    return out


def size_match(item: dict, name: str) -> bool:
    if not item.get("size_value"):
        return False
    want = float(item["size_value"])
    unit = (item.get("size_unit") or "").replace(" ", "").lower()
    for v, u in sizes_in(name):
        if u == unit and abs(v - want) < 0.051:
            return True
        # 12 pk of 12 fl oz cans stated as 144 fl oz in items.csv
        if unit == "floz" and u == "pk" and abs(v * 12 - want) < 0.5:
            return True
    return False


# Words that mark a different variant of the same brand (a flavour, diet
# version, format). Present in a product name but absent from the item name
# -> probably the wrong product.
VARIANT_WORDS = {
    "multi", "grain", "honey", "nut", "cherry", "vanilla", "zero", "diet", "sugar", "free",
    "caffeine", "lime", "lemon", "orange", "grape", "chocolate", "cinnamon", "frosted", "apple",
    "berry", "strawberry", "blueberry", "peanut", "almond", "protein", "thin", "angel", "whole",
    "wheat", "gluten", "organic", "mini", "minis", "bites", "light", "lite", "reduced", "low",
    "sodium", "spicy", "hot", "bbq", "ranch", "sour", "cream", "cheddar", "jalapeno", "decaf",
    "dark", "medium", "mild", "bold", "k", "cups", "pods", "instant", "squeeze", "crunchy",
    "chunky", "natural", "unsalted", "bottle", "bottles", "glass", "mexico", "mexican",
}
_MULTIPACK_RE = re.compile(r"\(\s*\d+\s*pack\s*\)|\bpack of \d+|\b\d+\s*-\s*count\b|\b[2-9]\s*-?\s*ct\b|\bvariety\b",
                           re.IGNORECASE)


def score(item: dict, name: str) -> float:
    """Heuristic match score (higher is better). Only used to RANK candidates
    for the owner's review; nothing is accepted automatically."""
    item_toks = tokens(item["name"]) | tokens(item["search_term"])
    got = tokens(name)
    s = len(item_toks & got) / max(1, len(item_toks))
    s += 1.0 if s >= 0.5 and size_match(item, name) else 0.0
    s -= 0.5 * len((got & VARIANT_WORDS) - item_toks)
    if _MULTIPACK_RE.search(name or "") and not re.search(r"pack|ct|count", item["search_term"], re.I):
        s -= 0.5
    return round(s, 3)


def latest_raw(chain: str, item_id: str) -> list[Path]:
    snaps = sorted((p for p in RAW_DIR.glob("snap*") if p.name[4:].isdigit()),
                   key=lambda p: int(p.name[4:]), reverse=True)
    for s in snaps:
        files = sorted((s / chain).glob(f"*/{item_id}__search__*.json.gz"))
        if files:
            return files
    return []


def candidates(chain: str, item: dict) -> list[dict]:
    """Distinct products across all saved searches for this item, scored."""
    seen: dict[str, dict] = {}
    for f in latest_raw(chain, item["item_id"]):
        env = json.load(gzip.open(f, "rt", encoding="utf-8"))
        for p in parsers.parse(chain, env["body"]):
            extra = p.get("extra") or {}
            if chain == "walmart" and extra.get("third_party_seller"):
                continue   # marketplace listings are not Walmart's own price
            c = seen.setdefault(p["chain_product_id"], {
                "item_id": item["item_id"], "chain": chain, "chain_product_id": p["chain_product_id"],
                "product_name": p["product_name"], "score": score(item, p["product_name"]),
                "size_match": int(size_match(item, p["product_name"])), "n_stores": 0,
                "example_price": p["price"], "upc": p.get("upc")})
            c["n_stores"] += 1
    return sorted(seen.values(), key=lambda c: (-c["score"], -c["n_stores"], c["chain_product_id"]))


def fetch_upc(chain: str, product_id: str, sessions: dict) -> tuple[str | None, str | None]:
    """(upc, raw_path) from one product page fetch."""
    if chain == "walmart":
        from collectors import walmart as W
        sessions.setdefault("walmart", W.unscoped_session())
        body = with_backoff(W.product_page, product_id, sessions["walmart"])
        upc = parsers.parse_walmart_product_page_upc(body)
    elif chain == "target":
        from collectors import target as T
        sessions.setdefault("target", T.session())
        body = with_backoff(T.product_page, product_id, sessions["target"])
        upc = parsers.parse_target_product_page_upc(body)
    else:
        return None, None
    raw = save_raw("items", chain, "product_pages", product_id, body, {"product_id": product_id}, kind="pdp")
    return upc, raw


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--items", default="")
    ap.add_argument("--chains", default="walmart,target,costco,trader_joes")
    ap.add_argument("--fetch-upc", action="store_true")
    a = ap.parse_args(argv)
    with (ROOT / "config" / "items.csv").open(newline="", encoding="utf-8") as f:
        items = list(csv.DictReader(f))
    if a.items:
        keep = set(a.items.split(","))
        items = [i for i in items if i["item_id"] in keep]
    chains = a.chains.split(",")

    cand_rows, best_rows, sessions, blocked = [], [], {}, set()
    for it in items:
        for ch in chains:
            cs = candidates(ch, it)
            cand_rows += cs[:3]
            if not cs:
                continue
            best = dict(cs[0])
            best["upc_source"] = "search" if best.get("upc") else None
            if a.fetch_upc and ch in ("walmart", "target") and not best.get("upc") and ch not in blocked:
                try:
                    best["upc"], raw = fetch_upc(ch, best["chain_product_id"], sessions)
                    best["upc_source"] = f"product_page:{raw}" if best["upc"] else f"not_found:{raw}"
                except (ChainBlocked, TransientError) as e:
                    best["upc_source"] = f"error:{e}"
                    if isinstance(e, ChainBlocked):
                        blocked.add(ch)
            best_rows.append(best)
            print(f"{it['item_id']:<36} {ch:<12} {best['score']:.2f} {best['chain_product_id']:<22} "
                  f"upc={best.get('upc')}  {best['product_name'][:60]}", flush=True)

    # Cross-chain check: does Walmart's best UPC equal Target's?
    by_item: dict[str, dict] = {}
    for b in best_rows:
        by_item.setdefault(b["item_id"], {})[b["chain"]] = b.get("upc")
    for b in best_rows:
        u = by_item[b["item_id"]]
        b["upc_match_walmart_target"] = (int(bool(u.get("walmart")) and u.get("walmart") == u.get("target"))
                                         if b["chain"] in ("walmart", "target") else None)
        # Flag anything that is not an exact name+size hit, or a cross-chain UPC disagreement.
        b["needs_review"] = int(b["score"] < 1.5 or (b["chain"] in ("walmart", "target")
                                                     and not b["upc_match_walmart_target"]))

    for path, rows in ((ROOT / "config" / "item_candidates.csv", cand_rows),
                       (ROOT / "config" / "items_resolved.csv", best_rows)):
        if rows:
            cols = list(dict.fromkeys(k for r in rows for k in r))
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols)
                w.writeheader()
                w.writerows(rows)
            print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
