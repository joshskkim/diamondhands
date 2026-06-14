#!/usr/bin/env bash
# Run the k6 slate load test against the host-run API via the grafana/k6 image.
# Usage: ./run.sh <label>   e.g. ./run.sh before   /   ./run.sh after
set -euo pipefail

LABEL="${1:-run}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DIR/results"

docker run --rm -i \
  --add-host=host.docker.internal:host-gateway \
  -v "$DIR:/scripts" \
  -e LABEL="$LABEL" \
  -e BASE_URL="${BASE_URL:-http://host.docker.internal:8080}" \
  -e GAME_ID="${GAME_ID:-823368}" \
  grafana/k6 run /scripts/slate.js

echo "Summary written to $DIR/results/$LABEL.json"
