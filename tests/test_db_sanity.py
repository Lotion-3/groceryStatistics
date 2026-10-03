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


def test_parallel_chain_writers(tmp_path):
    """Per-chain snapshot processes share one SQLite file (WAL + busy timeout)."""
    import threading
    from collectors.common import end_snapshot, start_snapshot
    path = tmp_path / "p.sqlite"
    con0 = connect(path)
    load_items(con0)
    snap = start_snapshot(con0)
    errors = []

    def writer(chain):
        try:
            con = connect(path)
            pk = upsert_store(con, {"chain": chain, "store_id": "1", "source": "direct"})
            for i in range(200):
                insert_observations(con, [{"snapshot_id": snap, "store_pk": pk, "item_id": "cer_cheerios_18",
                                           "observed_at": "x", "price": 1.0, "store_specific": 1,
                                           "raw_path": "r", "chain_product_id": f"p{i}", "source": "direct"}])
            end_snapshot(con, snap)
        except Exception as e:   # pragma: no cover - the assertion reports it
            errors.append(e)

    ts = [threading.Thread(target=writer, args=(c,)) for c in ("target", "walmart", "costco")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert con0.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 600
    assert con0.execute("SELECT journal_mode FROM pragma_journal_mode").fetchone()[0] == "wal"


def test_end_snapshot_never_moves_back(tmp_path):
    from collectors.common import end_snapshot, start_snapshot
    con = connect(tmp_path / "e.sqlite")
    snap = start_snapshot(con)
    con.execute("UPDATE snapshots SET ended_at='2999-01-01T00:00:00+00:00' WHERE snapshot_id=?", (snap,))
    end_snapshot(con, snap)
    assert con.execute("SELECT ended_at FROM snapshots").fetchone()[0].startswith("2999")


def test_pacer_circuit_breaker_stops_after_soft_streak():
    from collectors.common import ChainBlocked, DomainPacer, TransientError
    p = DomainPacer(min_interval=0, max_failures=3)
    calls = []

    def refused():
        calls.append(1)
        raise TransientError("soft:http 435")

    for _ in range(2):
        with pytest.raises(TransientError):
            p.call("x.com", refused)
    with pytest.raises(ChainBlocked):
        p.call("x.com", refused)
    with pytest.raises(ChainBlocked):     # tripped: nothing more is sent
        p.call("x.com", refused)
    assert len(calls) == 3
    assert p.call("y.com", lambda: "ok") == "ok"   # other domains unaffected


def test_pacer_success_resets_streak():
    from collectors.common import DomainPacer, TransientError
    p = DomainPacer(min_interval=0, max_failures=2)

    def bad():
        raise TransientError("soft")
    with pytest.raises(TransientError):
        p.call("x.com", bad)
    p.call("x.com", lambda: 1)
    with pytest.raises(TransientError):
        p.call("x.com", bad)


def test_balanced_visit_order_keeps_every_prefix_proportional():
    import numpy as np
    import pandas as pd
    from sampling.visit_order import balanced_order, prefix_quality
    rng = np.random.default_rng(0)
    n = 200
    sample = pd.DataFrame({"region": rng.choice(["Midwest", "South", "West", "Northeast"], n, p=[.2, .4, .3, .1]),
                           "urbanicity": rng.choice(["urban", "suburban", "rural"], n, p=[.7, .1, .2]),
                           "lat": rng.uniform(25, 48, n), "lon": rng.uniform(-123, -70, n),
                           "state": rng.choice([f"S{i}" for i in range(40)], n)})
    order = balanced_order(sample, seed=1)
    assert sorted(order) == list(range(1, n + 1))
    q = prefix_quality(sample, order, fracs=(0.1, 0.25, 0.5, 0.75))
    assert (q["max_stratum_dev"] <= 1.0).all()
