"""Get the true address of every Target store in the directory.

The vendored directory's coordinates are slug geocodes and are wrong for
~25% of stores (docs/REPO_NOTES.md). Every Target search response names the
searched store's mailing address, so one minimal search per store (count=1)
recovers it. Output feeds sampling/build_frame.py.

  data/processed/target_store_locations.csv
      store_id, name, address_line1, city, state, postal_code, located_at

Resumable (skips stores already in the CSV). Raw responses are not kept (the
address is the only datum used, and it is saved verbatim).

THIS GENERATES RETAILER TRAFFIC: ~1,900 requests at the project pace
(GS_MIN_INTERVAL_SECONDS, default 2 s) = about 1-1.5 hours. Owner approval
required before running without --limit.

Usage:  python -m sampling.locate_target_stores [--limit 10]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

from collectors import parsers
from collectors.common import ROOT, ChainBlocked, TransientError, utcnow, with_backoff

OUT = ROOT / "data" / "processed" / "target_store_locations.csv"
COLS = ["store_id", "name", "address_line1", "city", "state", "postal_code", "located_at"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)
    from collectors import target as T

    stores = json.loads((ROOT / "collectors" / "vendor" / "target_store_directory.json").read_text())
    done = set()
    if OUT.exists():
        with OUT.open(newline="", encoding="utf-8") as f:
            done = {r["store_id"] for r in csv.DictReader(f)}
    todo = [s for s in stores if s["store_id"] not in done]
    if a.limit:
        todo = todo[: a.limit]
    print(f"{len(done)} located already; locating {len(todo)}")
    new = not OUT.exists()
    sess = T.session()
    with OUT.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        if new:
            w.writeheader()
        for i, s in enumerate(todo, 1):
            try:
                body = with_backoff(T.search, "milk", s["store_id"], sess, num_results=1)
            except ChainBlocked as e:
                print(f"BLOCKED at store {s['store_id']} ({e}); stopping. Re-run later to resume.")
                return 1
            except TransientError as e:
                print(f"  store {s['store_id']}: {e}")
                continue
            loc = parsers.target_store_location(body)
            if loc and loc["store_id"] == s["store_id"]:
                w.writerow({**{k: loc.get(k) for k in COLS[:-1]}, "located_at": utcnow()})
                f.flush()
            else:
                print(f"  store {s['store_id']}: no address in response")
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
