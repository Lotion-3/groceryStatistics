"""Simple session policy (DECISIONS #44), on temporary files only."""
import pytest

from collectors import session_stash as SS
from collectors.common import ChainBlocked


@pytest.fixture
def stash(tmp_path, monkeypatch):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    monkeypatch.setattr(SS, "STASH", tmp_path / "sessions")
    monkeypatch.setattr(SS, "FILES", {"target": [vendor / ".target_http_session.json"]})
    net = {"ip": "1.1.1.1"}
    monkeypatch.setattr(SS, "public_ip", lambda refresh=False: net["ip"])
    return vendor / ".target_http_session.json", net


def test_each_run_starts_fresh(stash):
    live, _ = stash
    live.write_text("old-cookie")
    assert SS.start_fresh("target") == "fresh" and not live.exists()


def test_every_successful_session_is_archived_per_network(stash):
    live, net = stash
    for cookie in ("A", "B"):
        live.write_text(cookie)
        SS.save("target")
    net["ip"] = "2.2.2.2"
    live.write_text("C")
    SS.save("target")
    nets = SS.summary()["target"]["networks"]
    assert nets["1_1_1_1"]["archived_sessions"] == 2 and nets["2_2_2_2"]["archived_sessions"] == 1


def test_pause_blocks_fresh_sessions_and_spares(stash):
    SS.record_block("target", "explicit:px-captcha marker")
    with pytest.raises(ChainBlocked, match="cooldown"):
        SS.start_fresh("target")
    with pytest.raises(ChainBlocked, match="cooldown"):
        SS.make_spare("target")


def test_pause_escalates_and_resets_after_a_clean_run(stash, monkeypatch):
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(SS.time, "time", lambda: clock["t"])
    SS.record_block("target", "explicit:a")
    assert SS.cooldown_left_hours("target") == pytest.approx(3.0)        # 1st block: 3 h
    clock["t"] += 3.5 * 3600
    assert SS.cooldown_left_hours("target") == 0.0
    SS.record_block("target", "explicit:b")                              # 2nd in a row: 6 h
    assert SS.cooldown_left_hours("target") == pytest.approx(6.0)
    clock["t"] += 7 * 3600
    SS.mark_clean("target")                                              # clean run resets
    SS.record_block("target", "explicit:c")
    assert SS.cooldown_left_hours("target") == pytest.approx(3.0)


def test_clean_run_does_not_cut_an_active_pause(stash, monkeypatch):
    SS.record_block("target", "explicit:a")
    SS.mark_clean("target")
    assert SS.cooldown_left_hours("target") > 2.9
