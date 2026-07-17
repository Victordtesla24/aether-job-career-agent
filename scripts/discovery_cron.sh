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
# LOGIN_PASSWORD (and now AETHER_SYSTEM_RUN_SECRET, GAP-P7-DISCOVERY-001)
# available to this systemd-run script without hardcoding credentials here.
# Vars already present in the environment win (no override), so an explicit
# AETHER_CRON_* systemd Environment= still takes precedence over .env.
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

# Explicit HTTP-status handling (ADR-P7-05 / GAP-P7-DISCOVERY-001): curl -sf
# alone treats ANY non-2xx response the same way -- a genuine network/API
# outage and an intentional, honest 402 from the subscription paywall both
# produce a silent exit 22 with zero diagnostic text (plain -s suppresses
# curl's own stderr too). That is exactly how this gap went undetected: the
# paywall correctly rejecting this account read as "the discovery service is
# broken" with no way to tell the two apart from the log. http_call captures
# the REAL status and a body excerpt so every failure is loud, legible, and
# honestly attributed in the discovery log -- never miscategorized as "curl
# broke" when the API actually just said no (or vice versa).
http_call() {
  local method="$1" url="$2" data="$3"; shift 3
  local resp status body
  if [[ -n "$data" ]]; then
    resp=$(curl -sS -w '\n%{http_code}' -X "$method" "$url" \
      -H 'Content-Type: application/json' -d "$data" "$@")
  else
    resp=$(curl -sS -w '\n%{http_code}' -X "$method" "$url" "$@")
  fi
  status="${resp##*$'\n'}"
  body="${resp%$'\n'"$status"}"
  if (( status < 200 || status >= 300 )); then
    log "FATAL: $method $url -> HTTP $status: ${body:0:300}"
    exit 1
  fi
  printf '%s' "$body"
}

LOGIN_RESP=$(http_call POST "$API/auth/login" \
  "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(printf '%s' "$LOGIN_RESP" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

ME=$(http_call GET "$API/auth/me" "" -H "Authorization: Bearer $TOKEN")
QUERY=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("targetRole") or "Senior Technical Program Manager")')
LOCATION=$(echo "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("location") or "Melbourne, AU")')

# System-run header (ADR-P7-05 / GAP-P7-DISCOVERY-001): identifies this
# request as the platform's OWN scheduled discovery automation so the API's
# scoped SYSTEM-RUN exemption can bypass ONLY the subscription-paywall check
# for the scout + fit-scorer calls below (see agents.py:_is_system_run /
# _SYSTEM_RUN_EXEMPT_AGENTS) -- never any other agent, and never any guard
# other than the paywall itself (quota/spend caps still apply). Secret comes
# from AETHER_SYSTEM_RUN_SECRET (repo-root .env, loaded above) and is never
# echoed/logged. Omitted entirely when unset, so a missing/misconfigured
# secret fails the SAME honest way an ordinary unpaid run would (402 -- now
# loud thanks to http_call above), never a silent bypass or a silent skip.
SYSTEM_RUN_ARGS=()
if [[ -n "${AETHER_SYSTEM_RUN_SECRET:-}" ]]; then
  SYSTEM_RUN_ARGS=(-H "X-Aether-System-Run: $AETHER_SYSTEM_RUN_SECRET")
fi

log "scout run: query='$QUERY' location='$LOCATION'"
SCOUT=$(http_call POST "$API/agents/scout/run" \
  "{\"query\":\"$QUERY\",\"location\":\"$LOCATION\"}" \
  -H "Authorization: Bearer $TOKEN" "${SYSTEM_RUN_ARGS[@]}")
log "scout: $SCOUT"

SCORER=$(http_call POST "$API/agents/fit-scorer/run" "" \
  -H "Authorization: Bearer $TOKEN" "${SYSTEM_RUN_ARGS[@]}")
log "fit-scorer: $SCORER"
