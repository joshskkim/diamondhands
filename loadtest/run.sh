#!/usr/bin/env bash
# Run a k6 load test against the host-run API via the grafana/k6 image.
# Usage: ./run.sh <label>                              e.g. ./run.sh before / ./run.sh after
#        SCRIPT=leaderboard-stress.js ./run.sh <label> to drive a different script
# The label names both the k6 summary and results/<label>.json.
set -euo pipefail

LABEL="${1:-run}"
SCRIPT="${SCRIPT:-slate.js}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/results"

docker run --rm -i \
  --add-host=host.docker.internal:host-gateway \
  -v "$DIR:/scripts" \
  -e LABEL="$LABEL" \
  -e BASE_URL="${BASE_URL:-http://host.docker.internal:8080}" \
  -e GAME_ID="${GAME_ID:-823368}" \
  grafana/k6 run "/scripts/$SCRIPT"

echo "Summary written to $DIR/results/$LABEL.json"
