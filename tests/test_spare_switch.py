"""Refusal rules (DECISIONS #46-47), with fake fetches and fake sessions: no
network. A block counts only when a FRESH session is refused on its first
request; a session refused after it had worked is replaced, within limits."""
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
    log = {"recorded": [], "blocks": [], "stops": [], "fresh": 0}
    mints = {"today": 0}

    def fresh(chain):
        log["fresh"] += 1
        return {"cookies": f"fresh-{log['fresh']}"}

    def fail(chain, store_pk, item_id, reason, raw_path=None):
        if reason.startswith("STOPPED"):
            log["stops"].append(reason)

    monkeypatch.setattr(r, "record", lambda chain, store, pk, it, body, meta: log["recorded"].append(it["item_id"]) or 1)
    monkeypatch.setattr(r, "fail", fail)
    monkeypatch.setattr(SS, "ip_changed", lambda: False)
    monkeypatch.setattr(SS, "fresh_session", fresh)
    monkeypatch.setattr(SS, "record_mint", lambda chain, why: None)
    monkeypatch.setattr(SS, "mints_today", lambda chain: mints["today"])
    monkeypatch.setattr(SS, "REPLACE_DELAY_S", 0)
    monkeypatch.setattr(SS, "record_block", lambda chain, msg: log["blocks"].append(msg))
    return r, log, mints


ITEMS = [{"item_id": f"i{k}", "search_term": "x"} for k in range(5)]
STORE = {"store_id": "1"}


def fetcher(script):
    calls = iter(script)

    def fetch(it):
        if next(calls) == "block":
            raise ChainBlocked("explicit:px-captcha marker")
        return "{}"
    return fetch


def test_fresh_session_refused_on_first_request_is_a_block(run):
    r, log, _ = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["block"]))
    assert log["recorded"] == [] and len(log["blocks"]) == 1 and log["fresh"] == 0


def test_session_that_worked_is_replaced_and_collection_continues(run):
    r, log, _ = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "ok", "ok", "ok", "ok"]))
    assert log["recorded"] == ["i0", "i1", "i2", "i3", "i4"] and not log["blocks"] and not log["stops"]
    assert r.sessions["tsess"] == {"cookies": "fresh-1"} and r.replacements["target"] == 1


def test_replacement_refused_on_first_request_is_a_block(run):
    r, log, _ = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "block"]))
    assert log["recorded"] == ["i0"] and len(log["blocks"]) == 1 and "target" not in r.active


def test_per_run_limit_stops_without_a_block(run):
    r, log, _ = run
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block", "ok", "block", "ok", "block"]))
    assert log["recorded"] == ["i0", "i1", "i2"] and not log["blocks"] and len(log["stops"]) == 1
    assert r.replacements["target"] == SS.MAX_REPLACEMENTS_PER_RUN and "target" not in r.active


def test_daily_limit_stops_without_a_block(run):
    r, log, mints = run
    mints["today"] = SS.MAX_FRESH_PER_DAY
    r._query_items("target", STORE, 1, ITEMS, fetcher(["ok", "block"]))
    assert log["recorded"] == ["i0"] and not log["blocks"] and len(log["stops"]) == 1 and log["fresh"] == 0
