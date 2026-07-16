#!/usr/bin/env bash
# Guardrail: assert the host clock is on the expected timezone (ET). Ubuntu/Debian cron fires jobs
# in the HOST's local time and IGNORES the CRON_TZ line, so if the box TZ ever drifts off
# America/New_York every evening ingester job silently shifts ~4-5h and late West-Coast games go
# unprojected all day (see the TIMEZONE note in deploy/crontab.example). Cheap daily check; loud on
# mismatch. Exit 0 = OK, exit 1 = drifted.
set -uo pipefail

DIR="${DIAMOND_DIR:-/opt/diamond}"
EXPECT_TZ="${DIAMOND_EXPECT_TZ:-America/New_York}"

# Region name when systemd is present; the abbreviation is the fallback signal otherwise.
actual_tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
abbr="$(date +%Z)"

ok=0
if [ -n "$actual_tz" ]; then
  [ "$actual_tz" = "$EXPECT_TZ" ] && ok=1
else
  case "$abbr" in EST|EDT) ok=1 ;; esac   # no timedatectl — accept the ET abbreviations
fi

if [ "$ok" = 1 ]; then
  echo "[$(date -Is)] timezone OK: ${actual_tz:-$abbr}"
  exit 0
fi

msg="Diamond box TIMEZONE DRIFT: host is '${actual_tz:-$abbr}', expected '$EXPECT_TZ' (ET). Cron fires in host time, so evening ingester jobs are shifting ~4-5h and late games may go unprojected. Fix: sudo timedatectl set-timezone $EXPECT_TZ && sudo systemctl restart cron"
echo "[$(date -Is)] $msg" >&2

# Best-effort visible alert: post to the Discord webhook if one is set in .env (same channel as the
# daily briefing). No webhook → cron's MAILTO delivers the stderr line above. msg is quote-free by
# construction; strip any double-quote defensively so the inline JSON stays valid.
webhook="$(grep -E '^DISCORD_WEBHOOK_URL=' "$DIR/.env" 2>/dev/null | head -n1 | cut -d= -f2-)"
webhook="${webhook%\"}"; webhook="${webhook#\"}"
if [ -n "$webhook" ] && command -v curl >/dev/null 2>&1; then
  safe_msg="${msg//\"/}"
  curl -fsS -X POST -H 'Content-Type: application/json' \
    -d "{\"content\": \"⚠️ $safe_msg\"}" "$webhook" >/dev/null 2>&1 \
    || echo "[$(date -Is)] timezone alert: Discord post failed" >&2
fi
exit 1
