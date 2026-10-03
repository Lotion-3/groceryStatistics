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
