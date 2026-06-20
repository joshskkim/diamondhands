#!/usr/bin/env bash
# Nightly Postgres backup: pg_dump from the running container → gzipped file, with retention.
# We self-host Postgres, so we own backups. Point DIAMOND_BACKUP_DIR at a volume that is
# itself backed up offsite (e.g. rclone to object storage) for real durability.
set -uo pipefail

DIR="${DIAMOND_DIR:-/opt/diamond}"
BACKUP_DIR="${DIAMOND_BACKUP_DIR:-/opt/diamond/backups}"
RETAIN_DAYS="${DIAMOND_BACKUP_RETAIN_DAYS:-14}"
mkdir -p "$BACKUP_DIR"

ts=$(date +%Y%m%d-%H%M%S)
out="$BACKUP_DIR/diamond-$ts.sql.gz"

cd "$DIR" || { echo "cannot cd to $DIR"; exit 1; }
docker compose -f compose.prod.yml exec -T postgres pg_dump -U diamond diamond | gzip > "$out"
rc=$?

if [ "$rc" -eq 0 ] && [ -s "$out" ]; then
  echo "[$(date -Is)] backup ok: $out ($(du -h "$out" | cut -f1))"
  find "$BACKUP_DIR" -name 'diamond-*.sql.gz' -mtime +"$RETAIN_DAYS" -delete

  # Offsite copy (best-effort): mirror the dump to an rclone remote if one is configured,
  # e.g. DIAMOND_B2_REMOTE=diamond-b2:diamond-backups. A failure here is logged but does
  # NOT fail the local backup. Old remote dumps are pruned to the same retention window.
  if [ -n "${DIAMOND_B2_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
    if rclone copy "$out" "$DIAMOND_B2_REMOTE"; then
      echo "[$(date -Is)] offsite copy ok: $DIAMOND_B2_REMOTE"
      rclone delete --min-age "${RETAIN_DAYS}d" "$DIAMOND_B2_REMOTE" 2>/dev/null || true
    else
      echo "[$(date -Is)] offsite copy FAILED: $DIAMOND_B2_REMOTE"
    fi
  fi
else
  echo "[$(date -Is)] backup FAILED (exit $rc)"
  rm -f "$out"
fi
exit "$rc"
