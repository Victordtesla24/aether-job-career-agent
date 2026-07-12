#!/usr/bin/env bash
# Scheduled job discovery (REQ-01 / SC-JOB-10): every 30 minutes the systemd
# timer `aether-discovery.timer` runs this script, which authenticates against
# the local API, kicks off a scout discovery run using the user's saved target
# role/location, then fit-scores whatever landed. Each run is recorded as an
# AgentRun row, so the schedule is verifiable in the Agents page run history.
set -euo pipefail

API="${AETHER_API_URL:-http://127.0.0.1:8000}"
EMAIL="${AETHER_CRON_EMAIL:-demo@aether.dev}"
PASSWORD="${AETHER_CRON_PASSWORD:-AetherDemo1}"

log() { echo "[discovery-cron $(date -u +%FT%TZ)] $*"; }

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
