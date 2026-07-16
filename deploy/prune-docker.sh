#!/usr/bin/env bash
# Standalone Docker image + build-cache prune (cron safety net). The deploy already prunes on every
# push to main, but a box that fills up BETWEEN deploys — log/cache/backup growth, or a quiet stretch
# with no merges — has no other cleanup and can hit 100%, which crash-loops Postgres on a checkpoint
# it can't write (the 2026-07-04 outage). This closes that gap. `until=168h` keeps the last few days
# of images so a recent one is still around for a quick rollback — mirrors the deploy's prune.
set -uo pipefail

disk() { df -h / | awk 'NR==2{print $4" free ("$5" used)"}'; }

echo "[$(date -Is)] prune: disk before → $(disk)"
docker image prune -af --filter "until=168h"
docker builder prune -f --filter "until=168h"
rc=$?
echo "[$(date -Is)] prune: disk after  → $(disk)"
exit "$rc"
