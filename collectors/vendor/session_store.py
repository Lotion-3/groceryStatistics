"""
STUB replacing basketBuddy's Supabase-backed session_store.py.

The original (kept for reference as session_store_supabase_original.py.txt)
reads/writes WAF session cookies and block events to the production Supabase
project. This research project must never touch that database, so every
function here is a no-op that reports "nothing stored". The vendored
collectors already treat that as a normal case and fall back to their local
disk session files or a fresh browser mint.

Block events that the original would have logged to Supabase are instead
appended to data/logs/block_events.jsonl so they are still recorded.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

_LOG = Path(__file__).resolve().parents[2] / "data" / "logs" / "block_events.jsonl"


def save(chain: str, session: dict, store_id: Optional[str] = None,
         extra: Optional[dict] = None) -> bool:
    return False


def load(chain: str, max_age_seconds: int = 20 * 60) -> Optional[dict]:
    return None


def save_to_pool(chain: str, session: dict, store_id: Optional[str] = None,
                 extra: Optional[dict] = None) -> bool:
    return False


def load_pool(chain: str, limit: int = 300) -> list[dict]:
    return []


def save_assets(chain: str, assets: dict) -> bool:
    return False


def load_assets(chain: str, max_age_seconds: int = 6 * 3600) -> Optional[dict]:
    return None


def log_block_event(chain: str, category: str, detail: str = "") -> bool:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "chain": chain,
                                "category": category, "detail": detail[:500]}) + "\n")
        return True
    except Exception:
        return False
