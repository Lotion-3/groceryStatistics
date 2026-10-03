"""Session handling per chain and network (public IP) -- the simple policy
(DECISIONS #44, the owner's rules):

  * Every run starts with a FRESH session: stored session files are cleared so
    the collector starts one the normal way. A fresh SPARE is also made at the
    start of the run, before anything has been refused.
  * The first session is used for as long as it works. If it is refused (an
    explicit challenge, or a 6-failure streak), the runner switches ONCE to the
    spare. If the spare's first request also fails, two sessions in a row have
    been refused: stop and pause the chain (GS_BLOCK_COOLDOWN_HOURS, default
    12) -- no session is made, swapped or reused during the pause.
  * No session is ever created after a refusal (the owner's rule).
  * Every session that completes at least one successful request is ARCHIVED
    in data/sessions/<chain>/<network>/<timestamp>/ (kept for the record; not
    reused).
  * If the machine changed networks mid-run, the chain stops without a pause.
  * The spare applies to Target, Costco (Instacart) and ALDI, whose sessions
    can be swapped in place. Walmart (per-store browser scoping) and
    Meijer/Kroger (no cookie session) stop at the first refusal.

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
        raise ChainBlocked(f"cooldown: blocked {COOLDOWN_HOURS:.0f} h ago or less; {left:.1f} h left")
    if chain not in FILES:
        return "n/a"
    for f in FILES[chain]:
        if f.exists():
            f.unlink()
    return "fresh"


# ---------------------------------------------------------------------------
# Spare session (DECISIONS #43): one per chain per network, made in advance.
# Owner's rule from basketBuddy testing: a genuine block hits the IP, not the
# cookie, so one failing session can be bad luck. On a challenge the runner
# may switch ONCE to this network's spare; if that also fails (two sessions
# in a row), it is the IP: stop and cool down. Spares are only ever created
# before any block (never during a cooldown), and only for chains whose
# session can be swapped in place: Target, Costco (Instacart), ALDI.
# ---------------------------------------------------------------------------

SPARE_CHAINS = ("target", "costco", "aldi")


def _spare_dir(chain: str, ip: Optional[str] = None) -> Path:
    return _dir(chain, ip or public_ip()) / "spare"


def has_spare(chain: str) -> bool:
    d = _spare_dir(chain)
    return chain in SPARE_CHAINS and any((d / f.name).exists() for f in FILES[chain])


def make_spare(chain: str) -> str:
    """Make a FRESH spare for this run through the collector's normal session
    start (replacing any unused spare). Called at run start only, before any
    refusal; refused during a pause."""
    if chain not in SPARE_CHAINS:
        return "n/a"
    if cooldown_left_hours(chain) > 0:
        raise ChainBlocked("cooldown: no spare session is created after a block")
    d = _spare_dir(chain)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    if chain == "target":
        import target_pricing as tp
        sess = tp._warm_http_session()
        (d / FILES["target"][0].name).write_text(
            json.dumps({"cookies": sess["cookies"], "ua": sess["ua"], "saved_at": now}), encoding="utf-8")
    elif chain == "costco":
        import instacart_pricing as ic
        cookies, qp, zone = ic._bootstrap("costco")
        (d / FILES["costco"][0].name).write_text(json.dumps(
            {"cookies": cookies, "qp": qp, "zone_id": zone, "expires_at": now + ic.SESSION_TTL}), encoding="utf-8")
    elif chain == "aldi":
        from collectors import aldi  # noqa: F401  (puts vendor/aldi on sys.path)
        import aldi_pricing as ap
        cookies, qp, zone, shop = ap._bootstrap()
        ttl = ap.SESSION_TTL if ap.SESSION_TTL != float("inf") else 30 * 24 * 3600
        (d / FILES["aldi"][0].name).write_text(json.dumps(
            {"cookies": cookies, "qp": qp, "zone_id": zone, "shop_id": shop, "expires_at": now + ttl}),
            encoding="utf-8")
    return "created"


def load_spare(chain: str):
    """Put this network's spare in place as the primary session and load it
    into the collector's memory WITHOUT any fallback that would create a new
    session. The spare is consumed (it becomes the primary). Returns the
    session object the wrapper uses, or None if there is no spare."""
    if not has_spare(chain):
        return None
    d = _spare_dir(chain)
    for f in FILES[chain]:
        if (d / f.name).exists():
            shutil.copy2(d / f.name, f)
            (d / f.name).unlink()
    if chain == "target":
        import target_pricing as tp
        sess = tp._load_http_session()          # disk only: no validation, no warm-up
        tp._http_session = sess
        return sess
    data = json.loads(FILES[chain][0].read_text(encoding="utf-8"))
    if chain == "costco":
        import instacart_pricing as ic
        ic._mem_cache, ic._session = data, None  # non-empty cache: _get_session builds, never bootstraps
        return ic._get_session("costco")
    from collectors import aldi  # noqa: F401
    import aldi_pricing as ap
    ap._mem_cache, ap._session = data, None
    s, zone, _shop = ap._get_session()
    return s, zone


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
                nets[net.name] = {"archived_sessions": sum(1 for e in net.glob("*") if (e / "meta.json").exists()),
                                  "spare_ready": any((net / "spare" / f.name).exists() for f in FILES[chain])}
        out[chain] = {"networks": nets, "cooldown_h_left": round(cooldown_left_hours(chain), 1)}
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
