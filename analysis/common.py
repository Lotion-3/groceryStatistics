"""Shared data access for the analysis modules.

Unit of analysis: a (chain, product) observed at many stores in one snapshot.
Only store-specific rows are used for store-level analysis (spec section 5);
Instacart-sourced Costco rows are kept separate (source='instacart').

Deviation from the chain median (spec Module A):
    d = log(price) - log(median price of that product within the chain)
Main analysis uses the REGULAR price (regular_price; equals price when the
item is not on promotion); a promo-inclusive version uses the shelf price
(price) as a sensitivity check.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "grocery.sqlite"
FIG = ROOT / "figures"
TAB = ROOT / "tables"
SEED = 20261001
ANALYSIS_CFG = ROOT / "config" / "analysis.yaml"

# Non-grocery categories in config/items.csv (DECISIONS #28); everything else is grocery.
GENERAL_MERCH = {"household", "personal_care", "otc_health", "baby", "pet"}


def department(category: str) -> str:
    return "general_merchandise" if category in GENERAL_MERCH else "grocery"


def main_snapshots(db: Path = DB) -> list[int]:
    """Snapshot ids the analysis uses, from config/analysis.yaml (DECISIONS #26).
    Snapshot 1 (smoke test + item-resolution searches) is never included."""
    import yaml
    cfg = yaml.safe_load(ANALYSIS_CFG.read_text(encoding="utf-8")) or {}
    return [int(s) for s in (cfg.get("main_snapshots") or [])]


def load_observations(db: Path = DB, snapshot_id: int | list[int] | None = None,
                      store_specific_only: bool = True, include_test_sources: bool = False) -> pd.DataFrame:
    """Observations joined to stores and items. snapshot_id may be one id or a
    list (e.g. main_snapshots()); None loads every snapshot."""
    con = sqlite3.connect(db)
    q = """
    SELECT o.*, s.chain, s.store_id, s.lat, s.lon, s.zip, s.state, s.region, s.urbanicity,
           s.coord_quality, i.name AS item_name, i.category, i.cross_chain
    FROM observations o
    JOIN stores s USING (store_pk)
    JOIN items  i USING (item_id)
    """
    conds, params = [], []
    if snapshot_id is not None:
        ids = [snapshot_id] if isinstance(snapshot_id, int) else list(snapshot_id)
        conds.append(f"o.snapshot_id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    if store_specific_only:
        conds.append("o.store_specific = 1")
    # Not stores: e.g. a Kroger Delivery "spoke" (fulfilment hub) returned by the
    # Locations API in snapshot 2.
    conds.append("lower(coalesce(s.name, '')) NOT LIKE '%spoke%'")
    if not include_test_sources:
        conds.append("s.chain != 'kroger_ce'")    # Kroger's test host is not analysis data (DECISIONS #39)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    df = pd.read_sql_query(q, con, params=params)
    con.close()
    return df


_IC_ITEM = re.compile(r"^items_\d+-(\d+)$")


def product_key(chain_product_id: str) -> str:
    """Identifier of a product ACROSS stores. Instacart-style ids (Costco, ALDI)
    embed the store: items_<locationId>-<productId>; the same product at two
    stores shares only the productId part. Other chains' ids are already
    store-independent."""
    m = _IC_ITEM.match(str(chain_product_id))
    return m.group(1) if m else str(chain_product_id)


def product_panel(obs: pd.DataFrame, min_stores: int = 20) -> pd.DataFrame:
    """One row per (chain, product, store): the product's price at that store.

    A product may be returned by several item queries at one store; its price
    is identical across them, so duplicates are dropped. Products seen at
    fewer than `min_stores` stores are discarded (too few to define a median)."""
    cols = ["snapshot_id", "chain", "source", "chain_product_id", "store_pk", "store_id", "lat", "lon",
            "state", "region", "urbanicity", "product_name", "upc", "price", "regular_price",
            "is_promo", "category"]
    obs = obs.assign(chain_product_id=obs["chain_product_id"].map(product_key))
    p = obs[cols].drop_duplicates(["snapshot_id", "chain", "chain_product_id", "store_pk"]).copy()
    p["department"] = p["category"].map(department)
    n = p.groupby(["snapshot_id", "chain", "chain_product_id"])["store_pk"].transform("nunique")
    return p[n >= min_stores].copy()


def add_deviations(panel: pd.DataFrame) -> pd.DataFrame:
    """Add d_reg (regular price, main) and d_shelf (promo-inclusive) within chain."""
    out = panel.copy()
    g = ["snapshot_id", "chain", "chain_product_id"]
    for col, name in (("regular_price", "d_reg"), ("price", "d_shelf")):
        lp = np.log(out[col])
        out[name] = lp - lp.groupby([out[c] for c in g]).transform("median")
    return out


def attach_upcs(panel: pd.DataFrame, db: Path = DB) -> pd.DataFrame:
    """Search results carry no UPC, so cross-chain identity comes from the
    owner-confirmed IDs in the items table (walmart_id / target_tcin -> upc)."""
    con = sqlite3.connect(db)
    it = pd.read_sql_query("SELECT upc, walmart_id, target_tcin FROM items WHERE upc IS NOT NULL", con)
    con.close()
    m = pd.concat([
        it.dropna(subset=["walmart_id"]).assign(chain="walmart", chain_product_id=lambda d: d.walmart_id),
        it.dropna(subset=["target_tcin"]).assign(chain="target", chain_product_id=lambda d: d.target_tcin),
    ])[["chain", "chain_product_id", "upc"]].rename(columns={"upc": "upc_confirmed"})
    out = panel.merge(m, on=["chain", "chain_product_id"], how="left")
    out["upc"] = out["upc"].fillna(out.pop("upc_confirmed"))
    return out


def cross_chain_deviations(panel: pd.DataFrame) -> pd.DataFrame:
    """For UPC-matched products: d relative to the median over ALL chains'
    stores carrying that UPC (store-specific rows only)."""
    m = attach_upcs(panel).dropna(subset=["upc"]).copy()
    multi = m.groupby(["snapshot_id", "upc"])["chain"].transform("nunique") >= 2
    m = m[multi]
    lp = np.log(m["regular_price"])
    m["d_cross"] = lp - lp.groupby([m["snapshot_id"], m["upc"]]).transform("median")
    return m


def sample_size_note(df: pd.DataFrame) -> str:
    """The sample-size statement every figure and table must carry."""
    return (f"n = {len(df):,} store-product prices; {df['store_pk'].nunique():,} stores; "
            f"{df['chain_product_id'].nunique():,} products; snapshot(s) "
            f"{sorted(df['snapshot_id'].unique().tolist())}. PRELIMINARY, cross-sectional.")


# ---------------------------------------------------------------------------
# Figures: one look for every module
# ---------------------------------------------------------------------------

# Colour follows the chain, never its rank (validated categorical slots 1-3;
# every figure also has a legend and a matching table in tables/).
CHAIN_COLORS = {"target": "#2a78d6", "walmart": "#eb6834", "costco": "#1baf7a"}
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dc"


def style():
    """Matplotlib defaults: thin marks, recessive grid/axes, no top/right spines."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight",
        "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "lines.linewidth": 2, "legend.frameon": False,
    })
    return plt


def caption(fig, text: str):
    """Sample-size / PRELIMINARY footnote under a figure."""
    fig.text(0.0, -0.02, text, ha="left", va="top", fontsize=7, color=MUTED, wrap=True)
