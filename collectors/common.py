"""Shared plumbing for the collection wrappers: pacing, raw-response storage,
failure logging and DB writes.

Design rules (spec section 3):
  * Reuse the vendored basketBuddy collectors; never add new evasion.
  * Be gentle: one request at a time per domain, a minimum interval between
    requests, exponential backoff on transport errors, and STOP a chain on the
    first WAF block instead of rotating identities to push through it.
  * Store every raw response (gzipped) and record its path.
  * Log every failure. Missingness is data.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "collectors" / "vendor"
RAW_DIR = ROOT / "data" / "raw"

# The vendored modules import each other as top-level modules (e.g.
# `from kroger_pricing import ...`), exactly as they did in basketBuddy/backend.
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

try:  # optional .env support; nothing in it is required
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

MIN_INTERVAL = float(os.environ.get("GS_MIN_INTERVAL_SECONDS", "2.0"))
MAX_RETRIES = int(os.environ.get("GS_MAX_RETRIES", "2"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Pacing
# ---------------------------------------------------------------------------

class DomainPacer:
    """Serialize requests per domain and keep at least `min_interval` seconds
    (plus a little jitter) between consecutive requests to the same domain."""

    def __init__(self, min_interval: float = MIN_INTERVAL):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock(self, domain: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(domain, threading.Lock())

    def call(self, domain: str, fn: Callable, *args, **kwargs):
        with self._lock(domain):
            wait = self._last.get(domain, 0) + self.min_interval + random.uniform(0, 0.5) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return fn(*args, **kwargs)
            finally:
                self._last[domain] = time.monotonic()


PACER = DomainPacer()


class ChainBlocked(Exception):
    """The retailer served a WAF/captcha response. Collection for that chain
    must stop for this run (we do not escalate past blocks)."""


class TransientError(Exception):
    """No usable response (timeout, connection reset, 5xx). Safe to retry a
    couple of times with backoff."""


def with_backoff(fn: Callable, *args, retries: int = MAX_RETRIES, base: float = 3.0, **kwargs):
    """Retry `fn` on TransientError with exponential backoff (3s, 6s, ...).
    ChainBlocked is never retried."""
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except TransientError:
            if attempt == retries:
                raise
            time.sleep(base * (2 ** attempt) + random.uniform(0, 1))


# ---------------------------------------------------------------------------
# Raw storage
# ---------------------------------------------------------------------------

def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(s))[:80]


def save_raw(snapshot_id: int | str, chain: str, store_id: str, item_id: str,
             payload: str | bytes, meta: Optional[dict] = None, kind: str = "search") -> str:
    """Write one raw response as gzipped JSON envelope; return its path
    relative to the repo root (what goes in observations.raw_path).

    Envelope: {"meta": {...request context...}, "body": "<raw response text>"}.
    The body is stored verbatim so parsing can be redone later."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    digest = hashlib.sha1(payload.encode("utf-8", errors="replace")).hexdigest()[:8]
    rel = Path("data/raw") / f"snap{snapshot_id}" / chain / _safe(store_id) / \
        f"{_safe(item_id)}__{kind}__{stamp}_{digest}.json.gz"
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    env = {"meta": {**(meta or {}), "saved_at": utcnow(), "chain": chain,
                    "store_id": store_id, "item_id": item_id, "kind": kind},
           "body": payload}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(env, f)
    return rel.as_posix()


def load_raw(rel_path: str | Path) -> dict:
    """Read an envelope written by save_raw: {"meta": ..., "body": str}."""
    p = Path(rel_path)
    if not p.is_absolute():
        p = ROOT / p
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def start_snapshot(con: sqlite3.Connection, notes: str = "") -> int:
    cur = con.execute("INSERT INTO snapshots (started_at, notes) VALUES (?, ?)", (utcnow(), notes))
    con.commit()
    return cur.lastrowid


def end_snapshot(con: sqlite3.Connection, snapshot_id: int) -> None:
    con.execute("UPDATE snapshots SET ended_at=? WHERE snapshot_id=?", (utcnow(), snapshot_id))
    con.commit()


def log_failure(con: sqlite3.Connection, snapshot_id: Optional[int], chain: str,
                store_pk: Optional[int], item_id: Optional[str], reason: str,
                raw_path: Optional[str] = None) -> None:
    con.execute(
        "INSERT INTO collection_failures (snapshot_id, chain, store_pk, item_id, occurred_at, reason, raw_path) "
        "VALUES (?,?,?,?,?,?,?)",
        (snapshot_id, chain, store_pk, item_id, utcnow(), reason[:500], raw_path),
    )
    con.commit()
    # Mirror into the raw archive so a rebuild from data/raw keeps the failure log.
    store_id = None
    if store_pk is not None:
        r = con.execute("SELECT store_id FROM stores WHERE store_pk=?", (store_pk,)).fetchone()
        store_id = r[0] if r else None
    log = RAW_DIR / f"snap{snapshot_id}" / "_failures.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"chain": chain, "store_id": store_id, "item_id": item_id,
                            "occurred_at": utcnow(), "reason": reason[:500], "raw_path": raw_path}) + "\n")
    print(f"  [fail] {chain} store_pk={store_pk} item={item_id}: {reason[:160]}", flush=True)


def upsert_store(con: sqlite3.Connection, row: dict) -> int:
    """Insert a store (or update it) and return its store_pk."""
    cols = ["chain", "store_id", "name", "lat", "lon", "zip", "state", "region",
            "urbanicity", "source", "ruca", "anchor_zip", "coord_quality", "address"]
    vals = [row.get(c) for c in cols]
    con.execute(
        f"INSERT INTO stores ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
        "ON CONFLICT(chain, store_id, source) DO UPDATE SET "
        + ",".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in cols[2:]),
        vals,
    )
    con.commit()
    return con.execute("SELECT store_pk FROM stores WHERE chain=? AND store_id=? AND source=?",
                       (row["chain"], row["store_id"], row["source"])).fetchone()[0]


OBS_COLS = ["snapshot_id", "store_pk", "item_id", "observed_at", "product_name", "brand", "upc",
            "price", "regular_price", "promo_price", "is_promo", "unit_price", "unit_price_unit",
            "pack_size", "in_stock", "currency", "store_specific", "raw_path", "chain_product_id",
            "search_rank", "priced_store_id", "source", "extra"]


def insert_observations(con: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert parsed rows. A repeated (snapshot, store, item, product) is
    ignored, so re-running a resumed snapshot never duplicates data."""
    n = 0
    for r in rows:
        cur = con.execute(
            f"INSERT OR IGNORE INTO observations ({','.join(OBS_COLS)}) "
            f"VALUES ({','.join('?' * len(OBS_COLS))})",
            [json.dumps(r[c]) if c == "extra" and isinstance(r.get(c), dict) else r.get(c)
             for c in OBS_COLS],
        )
        n += cur.rowcount
    con.commit()
    return n
