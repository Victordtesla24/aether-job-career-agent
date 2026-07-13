#!/usr/bin/env bash
# Scheduled job discovery (REQ-01 / SC-JOB-10): every 30 minutes the systemd
# timer `aether-discovery.timer` runs this script, which authenticates against
# the local API, kicks off a scout discovery run using the user's saved target
# role/location, then fit-scores whatever landed. Each run is recorded as an
# AgentRun row, so the schedule is verifiable in the Agents page run history.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

# Load the repo-root .env (if present), same convention as start-api.sh /
# start-web.sh / apps/api/scripts/seed_demo.py: makes LOGIN_EMAIL/
# LOGIN_PASSWORD available to this systemd-run script without hardcoding
# credentials here. Vars already present in the environment win (no
# override), so an explicit AETHER_CRON_* systemd Environment= still takes
# precedence over .env.
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" =~ ^# ]] && continue
    [[ -n "${!key:-}" ]] && continue
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    export "$key"="$value"
  done < "$ENV_FILE"
fi

API="${AETHER_API_URL:-http://127.0.0.1:8000}"
EMAIL="${AETHER_CRON_EMAIL:-sarkar.vikram@gmail.com}"

log() { echo "[discovery-cron $(date -u +%FT%TZ)] $*"; }

# Never hardcode a real credential in shipped, scheduled tooling (GAP-P4-068).
# Resolve the cron's login password from the environment only: dedicated
# override first, falling back to LOGIN_PASSWORD (the same repo .env var the
# login flow and uat tooling already use, now loaded above). Refuse to run
# rather than default to a demo password, mirroring
# apps/api/scripts/seed_demo.py's _demo_password() pattern.
PASSWORD="${AETHER_CRON_PASSWORD:-${LOGIN_PASSWORD:-}}"
if [[ -z "$PASSWORD" ]]; then
  log "FATAL: AETHER_CRON_PASSWORD or LOGIN_PASSWORD must be set (env var, or" \
      " LOGIN_PASSWORD in the repo-root .env) to authenticate the discovery" \
      " cron. Refusing to hardcode a default credential."
  exit 1
fi

TOKEN=$(curl -sf -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

ME=$(curl -sf -H "Authorization: Bearer $TOKEN" "$API/auth/me")
QUERY=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("targetRole") or "Senior Technical Program Manager")')
LOCATION=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("location") or "Melbourne, AU")')

log "scout run: query='$QUERY' location='$LOCATION'"
SCOUT=$(curl -sf -X POST "$API/agents/scout/run" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"query\":\"$QUERY\",\"location\":\"$LOCATION\"}")
log "scout: $SCOUT"

SCORER=$(curl -sf -X POST "$API/agents/fit-scorer/run" \
  -H "Authorization: Bearer $TOKEN")
log "fit-scorer: $SCORER"
