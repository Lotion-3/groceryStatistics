"""Refusal rules (DECISIONS #43, #46), with fake fetches: no network.

A block counts only when a FRESH session is refused on its first request."""
import pytest

from collectors import session_stash as SS
from collectors import snapshot as S
from collectors.common import ChainBlocked
from db.init_db import connect, load_items


@pytest.fixture
def run(tmp_path, monkeypatch):
    con = connect(tmp_path / "t.sqlite")
    load_items(con)
    r = S.Run(con, 1, ["target"])
    recorded, blocks = [], []
    monkeypatch.setattr(r, "record", lambda chain, store, pk, it, body, meta: recorded.append(it["item_id"]) or 1)
    monkeypatch.setattr(r, "fail", lambda *a, **k: None)
    monkeypatch.setattr(SS, "ip_changed", lambda: False)
    monkeypatch.setattr(SS, "has_spare", lambda chain: True)
    monkeypatch.setattr(SS, "load_spare", lambda chain: {"cookies": "spare"})
    monkeypatch.setattr(SS, "record_block", lambda chain, msg: blocks.append(msg))
    monkeypatch.setattr(SS, "record_rest", lambda chain, msg: blocks.append("REST " + msg))
    return r, recorded, blocks


ITEMS = [{"item_id": f"i{k}", "search_term": "x"} for k in range(4)]
STORE = {"store_id": "1"}


def fetcher(script):
    """script: list of 'ok' / 'block' outcomes, one per request."""
    calls = iter(script)

    def fetch(it):
        if next(calls) == "block":
            raise ChainBlocked("explicit:px-captcha marker")
        return "{}"
    return fetch


def test_spare_rescues_a_bad_cookie(run):
    r, recorded, blocks = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "ok", "ok", "ok"]))
    assert recorded == ["i0", "i1", "i2", "i3"] and not blocks and "target" in r.active
    assert r.sessions["tsess"] == {"cookies": "spare"}


def test_two_sessions_in_a_row_is_an_ip_block(run):
    r, recorded, blocks = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "block"]))
    assert recorded == ["i0"] and len(blocks) == 1 and "target" not in r.active


def test_fresh_session_refused_on_first_request_is_a_block(run):
    r, recorded, blocks = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["block"]))
    assert recorded == [] and len(blocks) == 1 and not blocks[0].startswith("REST")
    assert "target" not in r.switched                 # no switch: it is a block


def test_spare_worked_then_refused_is_a_rest_not_a_block(run):
    r, recorded, blocks = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "ok", "block"]))
    assert recorded == ["i0", "i1"] and len(blocks) == 1 and blocks[0].startswith("REST")
    assert "target" not in r.active
