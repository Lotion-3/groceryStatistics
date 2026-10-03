"""Local session stash: one stored session per chain per network (public IP).

Why per IP. Bot-protection services (Imperva, PerimeterX) can bind a session
to the IP it was created on. On a campus network the public IP changes from
building to building, so a perfectly good session can be challenged simply
because the machine moved. Keeping one session per (chain, IP) lets a run use
the session that belongs to the network it is on, as an ordinary browser
would.

Rules (DECISIONS #42; the owner's line: no new sessions after a block):
  * restore(chain) before a run: copy this IP's stored session into the place
    the vendored collector reads it from. If there is none, the vendored code
    creates one in the normal way, and save(chain) stores it after the first
    successful request.
  * Only ONE session per chain per IP is kept. Several sessions on the same
    IP would only be useful for rotating around a block, which we do not do.
  * After a block (record_block), the chain is in COOLDOWN for
    GS_BLOCK_COOLDOWN_HOURS (default 12): restore() refuses, so no session is
    created, swapped or reused for that chain until it ends.
  * ip_changed() lets the runner tell "the machine moved networks mid-run"
    (switch to this network's session once) from "the site refused us on the
    same network" (a block: stop and cool down).

Everything lives in data/sessions/ (gitignored). Nothing is read from or
written to the production Supabase pool.
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
COOLDOWN_HOURS = float(os.environ.get("GS_BLOCK_COOLDOWN_HOURS", "12"))

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
    STASH.mkdir(parents=True, exist_ok=True)
    b = _read_blocks()
    b[chain] = {"at": time.time(), "at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ip": public_ip(), "reason": reason[:300]}
    _blocks_path().write_text(json.dumps(b, indent=1), encoding="utf-8")


def cooldown_left_hours(chain: str) -> float:
    b = _read_blocks().get(chain)
    if not b:
        return 0.0
    return max(0.0, COOLDOWN_HOURS - (time.time() - float(b["at"])) / 3600.0)


def _active_path(chain: str) -> Path:
    return STASH / chain / "active.json"


def active_ip(chain: str) -> Optional[str]:
    """The IP the session currently in the vendored location belongs to."""
    try:
        return json.loads(_active_path(chain).read_text(encoding="utf-8"))["ip"]
    except Exception:
        return None


def save(chain: str) -> None:
    """Store the session now in use as THIS network's session for the chain."""
    if chain not in FILES:
        return
    ip = public_ip()
    d = _dir(chain, ip)
    d.mkdir(parents=True, exist_ok=True)
    for f in FILES[chain]:
        if f.exists():
            shutil.copy2(f, d / f.name)
    (STASH / chain).mkdir(parents=True, exist_ok=True)
    _active_path(chain).write_text(json.dumps({"ip": ip, "saved": time.time()}), encoding="utf-8")


def restore(chain: str) -> str:
    """Put this network's stored session in place before a run.
    Returns 'stash' (stored session restored), 'current' (the session in place
    already belongs to this IP) or 'fresh' (none for this IP; the vendored
    code will create one normally). Raises ChainBlocked during a cooldown."""
    left = cooldown_left_hours(chain)
    if left > 0:
        raise ChainBlocked(f"cooldown: blocked {COOLDOWN_HOURS:.0f} h ago or less; {left:.1f} h left")
    if chain not in FILES:
        return "n/a"
    ip = public_ip()
    if active_ip(chain) == ip:
        return "current"
    prev = active_ip(chain)
    if prev and any(f.exists() for f in FILES[chain]):
        # keep the session that belongs to the previous network
        d = _dir(chain, prev)
        d.mkdir(parents=True, exist_ok=True)
        for f in FILES[chain]:
            if f.exists():
                shutil.copy2(f, d / f.name)
    d = _dir(chain, ip)
    if d.exists() and any((d / f.name).exists() for f in FILES[chain]):
        for f in FILES[chain]:
            if (d / f.name).exists():
                shutil.copy2(d / f.name, f)
            elif f.exists():
                f.unlink()
        _active_path(chain).write_text(json.dumps({"ip": ip, "saved": time.time()}), encoding="utf-8")
        return "stash"
    for f in FILES[chain]:          # no session for this network: let the collector start one normally
        if f.exists():
            f.unlink()
    return "fresh"


def ip_changed() -> bool:
    """True if the public IP differs from the one this process started on."""
    before = public_ip()
    return public_ip(refresh=True) != before


def summary() -> dict:
    out = {}
    for chain in FILES:
        nets = sorted(p.name for p in (STASH / chain).glob("*") if p.is_dir())
        out[chain] = {"networks": nets, "active_ip": active_ip(chain),
                      "cooldown_h_left": round(cooldown_left_hours(chain), 1)}
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", action="store_true",
                    help="store the sessions currently in place as this network's sessions")
    a = ap.parse_args()
    if a.seed:
        for c in FILES:
            if any(f.exists() for f in FILES[c]):
                save(c)
    print(json.dumps(summary(), indent=1))
