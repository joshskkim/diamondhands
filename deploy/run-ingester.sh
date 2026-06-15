#!/usr/bin/env bash
# Run an ingester subcommand as a one-shot job container (for host cron).
# Usage:
#   run-ingester.sh daily            # nightly full pipeline
#   run-ingester.sh daily --quick    # afternoon lineups/odds loop
#   run-ingester.sh smoke            # read-only connectivity check
set -uo pipefail

DIR="${DIAMOND_DIR:-/opt/diamond}"
LOG_DIR="${DIAMOND_LOG_DIR:-/var/log/diamond}"
mkdir -p "$LOG_DIR"

ts=$(date +%Y%m%d-%H%M%S)
log="$LOG_DIR/ingester-${1:-run}-$ts.log"

cd "$DIR" || { echo "cannot cd to $DIR"; exit 1; }
echo "[$(date -Is)] running: ingester $*" | tee -a "$log"
docker compose -f compose.prod.yml run --rm ingester "$@" >>"$log" 2>&1
rc=$?
echo "[$(date -Is)] finished (exit $rc)" | tee -a "$log"
exit $rc
