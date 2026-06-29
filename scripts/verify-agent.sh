#!/usr/bin/env bash
# Live end-to-end smoke for the Diamond Analyst agent.
#
# Verifies the full agentic path against a REAL Gemini key: auth-gated endpoint, the tool-use
# loop, trajectory persistence (agent_runs/agent_steps), and the human-in-the-loop write flow
# (propose -> signed token -> confirm -> user_preferences row).
#
# Usage (you supply the key; it never needs to be pasted anywhere shared):
#   1. Apply migrations so the agent tables exist (brings the local DB to V62):
#        docker run --rm --network host -v "$PWD/db/migrations:/flyway/sql" flyway/flyway:10 \
#          -url=jdbc:postgresql://localhost:5432/diamond -user=diamond -password=diamond \
#          -locations=filesystem:/flyway/sql -connectRetries=5 migrate
#   2. Start the API with the key (a fresh terminal):
#        AI_ENABLED=true GEMINI_API_KEY=AIza...yourkey \
#        JAVA_HOME=/opt/homebrew/opt/openjdk@21 mvn -f api/pom.xml spring-boot:run
#   3. Once it's up, run this script:
#        bash scripts/verify-agent.sh
set -euo pipefail

API="${DIAMOND_API_URL:-http://localhost:8080}"
JAR=$(mktemp -d)/cookies.txt
EMAIL="verify+$(date +%s)@local"
HANDLE="verify$(( RANDOM % 100000 ))"
PASS="verify-password-123"

say() { printf "\n\033[36m▶ %s\033[0m\n" "$1"; }
ok()  { printf "  \033[32m✓ %s\033[0m\n" "$1"; }
die() { printf "  \033[31m✗ %s\033[0m\n" "$1"; exit 1; }

say "0. API reachable + AI enabled?"
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/api/agent" \
  -H 'Content-Type: application/json' -d '{"question":"hi"}')
case "$code" in
  401) ok "endpoint requires auth (401 when signed out) — correct" ;;
  503) die "AI is disabled (503). Start the API with AI_ENABLED=true and GEMINI_API_KEY set." ;;
  *)   echo "  (got $code signed-out; continuing)" ;;
esac

say "1. Sign up a throwaway user"
curl -s -c "$JAR" -X POST "$API/api/auth/signup" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"handle\":\"$HANDLE\",\"password\":\"$PASS\"}" >/dev/null \
  && ok "signed up $HANDLE" || die "signup failed"

say "2. Ask the agent a grounded question (tool-use loop)"
OUT=$(mktemp)
curl -sN -b "$JAR" -X POST "$API/api/agent" -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"question":"How has the model been doing over the last 30 days?"}' > "$OUT" || true
grep -q '^event:status' "$OUT" && ok "tool-call status streamed" || echo "  (no status events — model may have answered directly)"
if grep -q '^event:answer' "$OUT"; then ok "got a grounded answer"; else die "no answer event (check the API log for a Gemini error)"; fi

say "3. Human-in-the-loop write: propose -> confirm"
OUT2=$(mktemp)
curl -sN -b "$JAR" -X POST "$API/api/agent" -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"question":"Set my bankroll to 100 units at quarter Kelly."}' > "$OUT2" || true
TOKEN=$(grep '^data:' "$OUT2" | sed 's/^data://' \
  | python3 -c 'import sys,json
for l in sys.stdin:
  try:
    d=json.loads(l)
    if "token" in d: print(d["token"]); break
  except Exception: pass' || true)
if [ -n "${TOKEN:-}" ]; then
  ok "agent proposed a write (confirm token issued)"
  RES=$(curl -s -b "$JAR" -X POST "$API/api/agent/confirm" -H 'Content-Type: application/json' \
    -d "{\"token\":\"$TOKEN\"}")
  echo "  confirm result: $RES"
  echo "$RES" | grep -qi "bankroll" && ok "write executed" || echo "  (unexpected confirm result)"
else
  echo "  (no confirm token — the model may have asked a follow-up instead; not a failure)"
fi

say "4. Trajectory + write persisted in Postgres"
docker exec diamond-postgres psql -U diamond -d diamond -t -c \
  "SELECT 'agent_runs='||count(*) FROM agent_runs; " 2>/dev/null | tr -d ' ' | grep -v '^$' | sed 's/^/  /'
docker exec diamond-postgres psql -U diamond -d diamond -t -c \
  "SELECT 'agent_steps='||count(*) FROM agent_steps;" 2>/dev/null | tr -d ' ' | grep -v '^$' | sed 's/^/  /'
docker exec diamond-postgres psql -U diamond -d diamond -t -c \
  "SELECT 'user_preferences rows='||count(*) FROM user_preferences;" 2>/dev/null | tr -d ' ' | grep -v '^$' | sed 's/^/  /'

printf "\n\033[32m✓ verification complete\033[0m — paste this output back to confirm.\n"
