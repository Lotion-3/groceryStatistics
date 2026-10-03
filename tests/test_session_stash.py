"""Session stash rules (DECISIONS #42), on temporary files only."""
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


def test_session_follows_the_network(stash):
    live, net = stash
    assert SS.restore("target") == "fresh"            # nothing stored for 1.1.1.1
    live.write_text("cookie-A")                       # collector starts a session normally
    SS.save("target")
    net["ip"] = "2.2.2.2"                             # move to another building
    assert SS.restore("target") == "fresh" and not live.exists()
    live.write_text("cookie-B")
    SS.save("target")
    net["ip"] = "1.1.1.1"                             # back again: A comes back, B is kept
    assert SS.restore("target") == "stash" and live.read_text() == "cookie-A"
    net["ip"] = "2.2.2.2"
    assert SS.restore("target") == "stash" and live.read_text() == "cookie-B"
    assert SS.restore("target") == "current"


def test_cooldown_refuses_any_session_after_a_block(stash):
    live, net = stash
    live.write_text("cookie-A")
    SS.save("target")
    SS.record_block("target", "explicit:px-captcha marker")
    with pytest.raises(ChainBlocked, match="cooldown"):
        SS.restore("target")
    net["ip"] = "3.3.3.3"                             # a new network does not lift the cooldown
    with pytest.raises(ChainBlocked, match="cooldown"):
        SS.restore("target")


def test_one_session_per_network(stash):
    live, net = stash
    live.write_text("cookie-A")
    SS.save("target")
    live.write_text("cookie-A2")                      # a refreshed session on the same network
    SS.save("target")
    files = list((SS.STASH / "target").glob("*/*.json"))
    assert len(files) == 1 and files[0].read_text() == "cookie-A2"
