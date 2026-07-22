#!/usr/bin/env bash
# Overnight transcript backfill.
#
# Waits until secrets/roic_api has an API key (so you can start this, paste the
# key whenever, and go to bed), then pulls all available quarters for every
# ticker in scripts/universe_overnight.txt into inbox/. Progress is teed to a
# timestamped log under data/ (gitignored).
#
# Usage:  bash scripts/run_overnight.sh
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

KEY_FILE="$REPO_ROOT/secrets/roic_api"
UNIVERSE="$REPO_ROOT/scripts/universe_overnight.txt"
LOG_DIR="$REPO_ROOT/data"
LOG_FILE="$LOG_DIR/overnight-$(date +%Y%m%d-%H%M%S).log"
PYTHON="$REPO_ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

mkdir -p "$LOG_DIR"

# Wait for the key (poll every 30s, give up after ~10h).
waited=0
max_wait=$((10 * 3600))
while [ ! -s "$KEY_FILE" ]; do
  if [ "$waited" -ge "$max_wait" ]; then
    echo "[run_overnight] gave up waiting for a key in $KEY_FILE after ${max_wait}s." | tee -a "$LOG_FILE"
    exit 2
  fi
  if [ "$waited" -eq 0 ]; then
    echo "[run_overnight] waiting for an API key in secrets/roic_api ..." | tee -a "$LOG_FILE"
  fi
  sleep 30
  waited=$((waited + 30))
done

echo "[run_overnight] key found; starting backfill at $(date)" | tee -a "$LOG_FILE"
echo "[run_overnight] universe: $UNIVERSE   log: $LOG_FILE" | tee -a "$LOG_FILE"

"$PYTHON" scripts/fetch_transcripts.py \
  --tickers-file "$UNIVERSE" \
  --all \
  --no-fallback 2>&1 | tee -a "$LOG_FILE"

echo "[run_overnight] done at $(date)" | tee -a "$LOG_FILE"
