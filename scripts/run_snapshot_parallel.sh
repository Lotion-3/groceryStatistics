#!/usr/bin/env sh
# POSIX twin of run_snapshot_parallel.ps1: one background process per chain,
# one shared snapshot id. THIS GENERATES RETAILER TRAFFIC (owner approval).
#   scripts/run_snapshot_parallel.sh "snapshot 1 (main)" [snapshot_id] [extra args...]
set -e
cd "$(dirname "$0")/.."
PY=${PY:-python}
NOTES=${1:-}
SNAP=${2:-}
shift 2 2>/dev/null || shift $#
export PYTHONUNBUFFERED=1
[ -z "$SNAP" ] && SNAP=$($PY -m collectors.snapshot --new-snapshot-only --notes "$NOTES" | tail -1)
mkdir -p data/raw/logs
echo "Snapshot $SNAP"
for c in ${CHAINS:-target walmart costco}; do
  nohup $PY -m collectors.snapshot --snapshot-id "$SNAP" --chains "$c" "$@" \
      > "data/raw/logs/snap${SNAP}_$c.log" 2>&1 &
  echo "  $c -> pid $!"
done
