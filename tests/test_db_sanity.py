"""Schema and data sanity checks (spec section 9).

The data checks run against data/grocery.sqlite when it exists (skipped on a
fresh clone with no collected data).
"""
import sqlite3

import pytest

from collectors.common import insert_observations, upsert_store
from collectors.parsers import upc_check_ok
from db.init_db import DEFAULT_DB, connect, load_items


@pytest.fixture
def mem_db(tmp_path):
    con = connect(tmp_path / "t.sqlite")
    load_items(con)
    return con


def test_items_csv_loads(mem_db):
    n = mem_db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    assert 40 <= n <= 70
    # UPCs are never typed in by hand: any present must be valid
    for (upc,) in mem_db.execute("SELECT upc FROM items WHERE upc IS NOT NULL"):
        assert upc_check_ok(upc)


def test_no_duplicate_rows(mem_db):
    mem_db.execute("INSERT INTO snapshots (snapshot_id, started_at) VALUES (1, 'x')")
    pk = upsert_store(mem_db, {"chain": "target", "store_id": "1", "source": "direct"})
    row = {"snapshot_id": 1, "store_pk": pk, "item_id": "cer_cheerios_18", "observed_at": "x",
           "price": 1.0, "store_specific": 1, "raw_path": "r", "chain_product_id": "p", "source": "direct"}
    assert insert_observations(mem_db, [row]) == 1
    assert insert_observations(mem_db, [row]) == 0     # re-run of a resumed snapshot


def test_upsert_store_is_idempotent(mem_db):
    a = upsert_store(mem_db, {"chain": "walmart", "store_id": "2098", "source": "direct", "zip": "43219"})
    b = upsert_store(mem_db, {"chain": "walmart", "store_id": "2098", "source": "direct", "name": "X"})
    assert a == b
    assert mem_db.execute("SELECT zip, name FROM stores WHERE store_pk=?", (a,)).fetchone() == ("43219", "X")


@pytest.mark.skipif(not DEFAULT_DB.exists(), reason="no collected data")
def test_collected_data_sanity():
    con = sqlite3.connect(DEFAULT_DB)
    assert con.execute("SELECT COUNT(*) FROM observations WHERE price IS NOT NULL AND price <= 0").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM observations WHERE is_promo=1 AND NOT (regular_price > price)"
                       ).fetchone()[0] == 0
    bad = [u for (u,) in con.execute("SELECT DISTINCT upc FROM observations WHERE upc IS NOT NULL")
           if not upc_check_ok(u)]
    assert not bad
    dup = con.execute("""SELECT COUNT(*) FROM (SELECT snapshot_id, store_pk, item_id, chain_product_id, COUNT(*) c
                         FROM observations GROUP BY 1,2,3,4 HAVING c > 1)""").fetchone()[0]
    assert dup == 0
    # every row points at a raw file that exists
    from collectors.common import ROOT
    missing = [p for (p,) in con.execute("SELECT DISTINCT raw_path FROM observations") if not (ROOT / p).exists()]
    assert not missing
