#!/usr/bin/env bash
# Post-deploy check that the public MCP endpoint is live AND secured.
#
#   scripts/verify-mcp.sh <domain-or-base-url> <api-key>
#
# Examples:
#   scripts/verify-mcp.sh diamondpicks.org "$MCP_KEY"     # -> https://diamondpicks.org/mcp
#   scripts/verify-mcp.sh http://localhost:8095 devkey    # local container
#
# Confirms (1) an unauthenticated request is rejected (auth is enforced — i.e. MCP_API_KEYS
# is set), and (2) an authenticated MCP `initialize` succeeds. Exits non-zero on any failure.
set -uo pipefail

ARG="${1:-}"; KEY="${2:-}"
if [ -z "$ARG" ] || [ -z "$KEY" ]; then
  echo "usage: $0 <domain-or-base-url> <api-key>" >&2
  exit 2
fi

# Accept either a bare domain or a full base URL.
case "$ARG" in
  http://*|https://*) BASE="$ARG" ;;
  *) BASE="https://$ARG" ;;
esac
URL="$BASE/mcp"

ACCEPT="application/json, text/event-stream"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify-mcp","version":"1.0"}}}'

fail=0

echo "Checking $URL"

# 1) Unauthenticated → must be rejected (proves auth is on and the route is live).
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST "$URL" \
  -H "Content-Type: application/json" -H "Accept: $ACCEPT" -d "$INIT")
if [ "$code" = "401" ]; then
  echo "OK   unauthenticated request rejected (401)"
else
  echo "FAIL unauthenticated request returned $code (expected 401 — is MCP_API_KEYS set?)"
  fail=1
fi

# 2) Authenticated initialize → must return a JSON-RPC result with server info.
body=$(curl -s --max-time 20 -X POST "$URL" \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -H "Accept: $ACCEPT" -d "$INIT")
if printf '%s' "$body" | grep -q '"result"' \
   && printf '%s' "$body" | grep -qE 'serverInfo|protocolVersion'; then
  echo "OK   authenticated initialize succeeded"
else
  echo "FAIL authenticated initialize did not return a result:"
  printf '%s\n' "$body" | head -c 400
  echo
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✓ MCP endpoint is live and secured."
else
  echo "✗ MCP verification failed."
fi
exit "$fail"
