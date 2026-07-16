#!/usr/bin/env bash
# Preflight: verify the .env DB_PASSWORD still authenticates against the LIVE postgres volume.
#
# Why this exists (the 2026-07-02 outage): postgres bakes POSTGRES_PASSWORD into its data volume
# on FIRST init and ignores it forever after. So changing DB_PASSWORD in .env once the volume
# exists does NOT change the stored password — and the compose healthcheck is `pg_isready`, which
# only checks that the server accepts connections, NOT that a password is valid. The drift sails
# past the healthcheck, then flyway (-password=${DB_PASSWORD}) fails auth with a cryptic error and
# api/mcp never start (they depend_on flyway completing) — the whole app tier goes dark.
#
# Run this before `compose up -d` (the deploy does) or by hand before rotating the password.
# Exit 0 = match (or nothing to check yet); exit 1 = drift, with recovery steps printed.
set -euo pipefail

DIAMOND_DIR="${DIAMOND_DIR:-/opt/diamond}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.prod.yml}"
cd "$DIAMOND_DIR"

if [ ! -f .env ]; then
  echo "check-db-password: no .env in $DIAMOND_DIR — nothing to check."
  exit 0
fi

# Pull DB_PASSWORD out of .env (value may contain '='; strip optional surrounding quotes).
DB_PASSWORD="$(grep -E '^DB_PASSWORD=' .env | head -n1 | cut -d= -f2-)"
DB_PASSWORD="${DB_PASSWORD%\"}"; DB_PASSWORD="${DB_PASSWORD#\"}"
DB_PASSWORD="${DB_PASSWORD%\'}"; DB_PASSWORD="${DB_PASSWORD#\'}"
if [ -z "$DB_PASSWORD" ]; then
  echo "check-db-password: DB_PASSWORD is unset/empty in .env — nothing to check."
  exit 0
fi

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# No running postgres → no existing volume password to drift from (a fresh box initializes it
# from this same .env on first `up`), or the DB is simply down and we can't probe. Best-effort.
if [ -z "$(compose ps -q postgres 2>/dev/null)" ] || \
   [ -z "$(compose ps --status running -q postgres 2>/dev/null)" ]; then
  echo "check-db-password: postgres not running — skipping drift check."
  exit 0
fi

# Probe over the service name `postgres` (not 127.0.0.1). The postgres image's pg_hba trusts
# loopback (`host all all 127.0.0.1/32 trust`) AND the unix socket, so both give a false pass;
# only a non-loopback host hits the `host all all all scram-sha-256` rule and actually checks the
# password — the exact path flyway uses (jdbc:postgresql://postgres:5432). -w never prompts.
if compose exec -T \
     -e PGPASSWORD="$DB_PASSWORD" -e PGCONNECT_TIMEOUT=5 \
     postgres psql -h postgres -U diamond -d diamond -w -tAc 'select 1' >/dev/null 2>&1; then
  echo "check-db-password: ✓ DB_PASSWORD matches the live postgres volume."
  exit 0
fi

cat >&2 <<'EOF'
check-db-password: ✗ DB PASSWORD DRIFT

The DB_PASSWORD in .env does NOT authenticate against the live postgres volume. Postgres stores
the password in its data volume on first init and IGNORES POSTGRES_PASSWORD afterward, and the
pg_isready healthcheck doesn't check auth — so this would sail past `up -d` and then make flyway
fail with a cryptic auth error, blocking api/mcp (which depend_on flyway) and downing the app tier.

Fix ONE of:
  • Restore the previous DB_PASSWORD in .env (whatever the volume was initialized with), OR
  • Rotate the password on the LIVE volume (works over the socket even when TCP auth is broken),
    then set the SAME value in .env:
        docker compose -f compose.prod.yml exec -T postgres \
          psql -U diamond -d diamond -c "ALTER USER diamond WITH PASSWORD '<new-password>';"

See the "DB password" gotcha in docs/ops-cheatsheet.md.
EOF
exit 1
