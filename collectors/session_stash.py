"""Session handling per chain and network (public IP) (DECISIONS #44-47).

  * Every run starts with a FRESH session (stored session files are cleared;
    the collector makes one the normal way).
  * A BLOCK is counted only when a fresh session is refused on its FIRST
    request. Then the chain stops and pauses; the pause escalates with
    repeated blocks (GS_BLOCK_PAUSE_SCHEDULE, default 3,6,12,24 h) and a clean
    run resets it. Nothing is made, swapped or reused during a pause.
  * A session refused AFTER it had worked is treated as a session fault (the
    owner's basketBuddy testing: cookies sometimes fail at random, and a fresh
    one then works for weeks). After a short wait (GS_REPLACE_DELAY_S, default
    300 s) a fresh session replaces it -- at most GS_MAX_REPLACEMENTS_PER_RUN
    (2) per run and GS_MAX_FRESH_PER_DAY (8) fresh sessions per chain per day.
    Past either limit the chain stops for the run (not a block).
  * Request volume is governed independently of sessions: per-domain pacing,
    the 6-failure circuit breaker and the per-run budget.
  * Every session that completes at least one successful request is ARCHIVED
    in data/sessions/<chain>/<network>/<timestamp>/ (for the record).
  * If the machine changed networks mid-run, the chain stops without a pause.
  * Replacement applies to Target, Costco (Instacart) and ALDI, whose sessions
    can be replaced in place. Walmart (per-store browser scoping) and
    Meijer/Kroger (no cookie session) stop at a refusal.

Everything lives in data/sessions/ (gitignored). The production Supabase pool
is never read or written.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from collectors.common import ROOT, VENDOR, ChainBlocked

STASH = ROOT / "data" / "sessions"
REPLACE_DELAY_S = float(os.environ.get("GS_REPLACE_DELAY_S", "300"))
MAX_REPLACEMENTS_PER_RUN = int(os.environ.get("GS_MAX_REPLACEMENTS_PER_RUN", "2"))
MAX_FRESH_PER_DAY = int(os.environ.get("GS_MAX_FRESH_PER_DAY", "8"))
SWAPPABLE = ("target", "costco", "aldi")
# Pause after the 1st, 2nd, 3rd, ... block in a row (hours); last value repeats.
PAUSE_SCHEDULE = [float(x) for x in os.environ.get("GS_BLOCK_PAUSE_SCHEDULE", "3,6,12,24").split(",") if x.strip()]

# Where each vendored collector keeps its session (it reads these on start).
FILES = {
    "target": [VENDOR / ".target_http_session.json"],
    "walmart": [VENDOR / ".walmart_http_session.json", VENDOR / ".walmart_store_session.json"],
    "costco": [VENDOR / ".ic_session.json"],
    "aldi": [VENDOR / "aldi" / ".aldi_session.json"],
}

_ip_cache: dict = {}


def public_ip(refresh: bool = False) -> str:
    """This machine's public IP (cached per process unless refresh=True)."""
    if refresh or "ip" not in _ip_cache:
        import requests
        ip = ""
        for url in ("https://api.ipify.org", "https://checkip.amazonaws.com"):
            try:
                ip = requests.get(url, timeout=10).text.strip()
                if ip:
                    break
            except Exception:
                continue
        _ip_cache["ip"] = ip or "unknown"
    return _ip_cache["ip"]


def _dir(chain: str, ip: str) -> Path:
    return STASH / chain / ip.replace(":", "_").replace(".", "_")


def _blocks_path() -> Path:
    return STASH / "blocks.json"


def _read_blocks() -> dict:
    try:
        return json.loads(_blocks_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def record_block(chain: str, reason: str) -> None:
    """Record a block; the streak (blocks in a row without a clean run) sets
    the length of the pause."""
    STASH.mkdir(parents=True, exist_ok=True)
    b = _read_blocks()
    prev = b.get(chain) or {}
    streak = int(prev.get("streak", 0)) + 1
    b[chain] = {"at": time.time(), "at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ip": public_ip(), "reason": reason[:300], "streak": streak,
                "pause_hours": pause_hours(streak)}
    _blocks_path().write_text(json.dumps(b, indent=1), encoding="utf-8")


def mark_clean(chain: str) -> None:
    """A run with successful requests and no block: reset the streak (the
    next block gets the shortest pause). Past pauses already over are kept as
    history in the file."""
    b = _read_blocks()
    if chain in b and b[chain].get("streak"):
        if cooldown_left_hours(chain) == 0:
            b[chain]["streak"] = 0
            _blocks_path().write_text(json.dumps(b, indent=1), encoding="utf-8")


def pause_hours(streak: int) -> float:
    return PAUSE_SCHEDULE[min(max(streak, 1), len(PAUSE_SCHEDULE)) - 1]


def cooldown_left_hours(chain: str) -> float:
    """Hours left of the pause after a counted block (0 if none)."""
    b = _read_blocks().get(chain)
    if not b or not b.get("streak") or "at" not in b:
        return 0.0
    hours = float(b.get("pause_hours") or pause_hours(int(b["streak"])))
    return max(0.0, hours - (time.time() - float(b["at"])) / 3600.0)


def _mints_path() -> Path:
    return STASH / "mints.json"


def record_mint(chain: str, why: str) -> None:
    STASH.mkdir(parents=True, exist_ok=True)
    try:
        m = json.loads(_mints_path().read_text(encoding="utf-8"))
    except Exception:
        m = {}
    m.setdefault(chain, []).append({"at": time.time(), "ip": public_ip(), "why": why})
    _mints_path().write_text(json.dumps(m, indent=1), encoding="utf-8")


def mints_today(chain: str) -> int:
    """Fresh sessions made for this chain in the last 24 h."""
    try:
        m = json.loads(_mints_path().read_text(encoding="utf-8"))
    except Exception:
        return 0
    return sum(1 for e in m.get(chain, []) if time.time() - float(e["at"]) < 86400)

def save(chain: str) -> None:
    """Archive the session now in use (it has just had a successful request):
    a new timestamped entry under this network. Kept for the record."""
    if chain not in FILES or not any(f.exists() for f in FILES[chain]):
        return
    ip = public_ip()
    base = _dir(chain, ip) / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    entry, k = base, 1
    while entry.exists():                       # never overwrite an archived session
        entry, k = base.with_name(f"{base.name}_{k}"), k + 1
    entry.mkdir(parents=True)
    for f in FILES[chain]:
        if f.exists():
            shutil.copy2(f, entry / f.name)
    (entry / "meta.json").write_text(json.dumps({"chain": chain, "ip": ip, "archived": time.time()}),
                                     encoding="utf-8")

def start_fresh(chain: str) -> str:
    """Before a run: respect a pause, then clear the stored session files so
    the collector starts a FRESH session the normal way."""
    left = cooldown_left_hours(chain)
    if left > 0:
        raise ChainBlocked(f"cooldown: paused after a block; {left:.1f} h left")
    if chain not in FILES:
        return "n/a"
    for f in FILES[chain]:
        if f.exists():
            f.unlink()
    return "fresh"


# ---------------------------------------------------------------------------
# Replacing a session that failed after it had worked
# ---------------------------------------------------------------------------

def fresh_session(chain: str):
    """Make a new session through the collector's normal session start, put
    it where the collector reads it, and return the object the wrapper uses.
    Refused during a pause. The caller enforces the replacement limits."""
    left = cooldown_left_hours(chain)
    if left > 0:
        raise ChainBlocked(f"cooldown: paused after a block; {left:.1f} h left")
    if chain == "target":
        import target_pricing as tp
        sess = tp._warm_http_session()
        tp._save_http_session(sess)
        tp._http_session = sess
        return sess
    if chain == "costco":
        import instacart_pricing as ic
        cookies, qp, zone = ic._bootstrap("costco")
        ic._save_disk_session(cookies, qp, zone)
        ic._mem_cache, ic._session = {}, None
        return ic._get_session("costco")         # loads the session just saved
    if chain == "aldi":
        from collectors import aldi  # noqa: F401  (puts vendor/aldi on sys.path)
        import aldi_pricing as ap
        cookies, qp, zone, shop = ap._bootstrap()
        ap._save_disk_session(cookies, qp, zone, shop)
        ap._mem_cache, ap._session = {}, None
        s_, zone_, _shop = ap._get_session()
        return s_, zone_
    raise ValueError(f"sessions for {chain} cannot be replaced in place")


def ip_changed() -> bool:
    """True if the public IP differs from the one this process started on."""
    before = public_ip()
    return public_ip(refresh=True) != before


def summary() -> dict:
    out = {}
    for chain in FILES:
        nets = {}
        for net in (STASH / chain).glob("*"):
            if net.is_dir():
                nets[net.name] = {"archived_sessions": sum(1 for e in net.glob("*") if (e / "meta.json").exists())}
        out[chain] = {"networks": nets, "cooldown_h_left": round(cooldown_left_hours(chain), 1),
                      "fresh_sessions_last_24h": mints_today(chain)}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", action="store_true",
                    help="archive the sessions currently in place under this network")
    a = ap.parse_args()
    if a.seed:
        for c in FILES:
            if any(f.exists() for f in FILES[c]):
                save(c)
    print(json.dumps(summary(), indent=1))
