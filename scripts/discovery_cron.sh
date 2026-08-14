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

# Write to stderr (MV-system-008): every log() caller inside http_call() is
# itself invoked via command substitution (e.g. LOGIN_RESP=$(http_call ...)),
# which only captures stdout. A plain stdout echo here was captured into the
# caller's response variable instead of reaching the process's real
# stdout/stderr, so FATAL diagnostics never reached /var/log/aether/
# discovery.log (the systemd drop-in's StandardError=append: target) --
# hiding a 48h+ total outage. stderr is never swallowed by $(...), so this
# survives command substitution without touching the captured HTTP-response
# value callers parse.
log() { echo "[discovery-cron $(date -u +%FT%TZ)] $*" >&2; }

# Never hardcode a real credential in shipped, scheduled tooling (GAP-P4-068).
# Resolve the cron's login password from the environment only: dedicated
# override first, falling back to LOGIN_PASSWORD (the same repo .env var the
# login flow and uat tooling already use, now loaded above). Refuse to run
# rather than default to a demo password, mirroring
# apps/api/scripts/seed_demo.py's _demo_password() pattern.
#
# S-FIX-A / S-1: the password is required only by the LEGACY single-account
# fallback below, which is the only path that logs in as a user. The
# multi-subscriber sweep authenticates with the system-run secret alone, so the
# refusal moved down to the fallback branch — demanding one account's password
# before a sweep that never uses it would block discovery for EVERY subscriber
# on a deployment that has no cron account configured.
PASSWORD="${AETHER_CRON_PASSWORD:-${LOGIN_PASSWORD:-}}"

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
#
# MON-004 (MONITORING-LEDGER.md): a TRANSIENT failure gets exactly ONE retry,
# after a short backoff, before it is treated as fatal. The observed failure is
# a restart race -- the systemd timer fires while the API process is bouncing,
# so the call dies with a curl transport error (http_code 000) or a 5xx from a
# half-started worker, and the whole discovery cycle was lost until the next
# tick 30 minutes later (7 occurrences in discovery.log). One retry covers a
# service bounce; the retry is BOUNDED at one so a genuinely-down API is still
# reported loudly and promptly instead of being hammered. A 4xx is NEVER
# retried: an honest refusal (402 paywall, 401 auth) will not change by asking
# again, and re-asking would burn a real, already-answered request.
http_call() {
  local method="$1" url="$2" data="$3"; shift 3
  local backoff="${AETHER_CRON_RETRY_BACKOFF_SECONDS:-5}"
  local attempt resp status body curl_rc code
  for attempt in 1 2; do
    curl_rc=0
    if [[ -n "$data" ]]; then
      resp=$(curl -sS -w '\n%{http_code}' -X "$method" "$url" \
        -H 'Content-Type: application/json' -d "$data" "$@") || curl_rc=$?
    else
      resp=$(curl -sS -w '\n%{http_code}' -X "$method" "$url" "$@") || curl_rc=$?
    fi
    status="${resp##*$'\n'}"
    body="${resp%$'\n'"$status"}"
    # A curl that never reached the server writes http_code 000; anything that
    # is not a 3-digit code means curl itself produced no status line, which is
    # the same "no HTTP answer" condition and is reported as such.
    [[ "$status" =~ ^[0-9]{3}$ ]] || status="000"
    code=$((10#$status))
    if (( code >= 200 && code < 300 )); then
      printf '%s' "$body"
      return 0
    fi
    if (( attempt == 1 )) && (( code == 0 || code >= 500 )); then
      log "TRANSIENT: $method $url -> HTTP $status (curl exit $curl_rc);" \
          "retrying once in ${backoff}s"
      sleep "$backoff"
      continue
    fi
    log "FATAL: $method $url -> HTTP $status (curl exit $curl_rc): ${body:0:300}"
    exit 1
  done
}

# S-FIX-A / S-1: EVERY entitled subscriber, not just this one account.
#
# The single-account flow below (login as EMAIL -> scout + fit-scorer for that
# one user) served exactly one customer: every other paying subscriber got zero
# automatic discovery and had to click Sync themselves. The server-side sweep
# (POST /agents/discovery/sweep) iterates every entitled subscriber with a
# usable search target, spacing the runs, and covers THIS account too — so the
# owner's discovery keeps happening on the same 30-minute cadence, through the
# same _dispatch/system_run path, with the same AgentRun audit rows.
#
# It needs no user password: the sweep is authenticated by the system-run
# secret alone (the platform has no password for its subscribers). When
# AETHER_SYSTEM_RUN_SECRET is UNSET the sweep is unreachable by design, so we
# fall through to the legacy single-account path below unchanged rather than
# silently discovering for nobody.
if [[ -n "${AETHER_SYSTEM_RUN_SECRET:-}" ]]; then
  SWEEP_CONF_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aether-discovery-sweep.XXXXXX")"
  chmod 700 "$SWEEP_CONF_DIR"
  trap 'rm -rf "$SWEEP_CONF_DIR"' EXIT
  SWEEP_CONF="$SWEEP_CONF_DIR/sweep.conf"
  # MON-005: secret travels in a 0600 config file curl reads itself, never argv.
  (umask 077; : > "$SWEEP_CONF")
  printf 'header = "X-Aether-System-Run: %s"\n' "$AETHER_SYSTEM_RUN_SECRET" \
    > "$SWEEP_CONF"
  log "discovery sweep: all entitled subscribers"
  SWEEP=$(http_call POST "$API/agents/discovery/sweep" "" --config "$SWEEP_CONF")
  # Log a compact per-user summary (never the whole payload): who ran, what
  # landed, who failed, and how much of the shared Adzuna day-budget went.
  printf '%s' "$SWEEP" | python3 -c '
import json, sys
data = json.load(sys.stdin)
budget = data.get("adzunaBudget") or {}
print("swept=%s errors=%s adzuna_used=%s/%s" % (
    data.get("sweptUsers"),
    sum(1 for r in data.get("users", []) if r.get("status") == "error"),
    budget.get("used"), budget.get("budget")))
for row in data.get("users", []):
    print("  %s %s persisted=%s updated=%s scored=%s %s" % (
        row.get("status"), row.get("email") or row.get("userId"),
        row.get("persisted"), row.get("updated"), row.get("scored"),
        row.get("error") or ""))
' >&2
  exit 0
fi

log "AETHER_SYSTEM_RUN_SECRET unset: falling back to the single-account" \
    " discovery path for $EMAIL (other subscribers get NO scheduled" \
    " discovery until the secret is configured)."

# Never hardcode a real credential in shipped, scheduled tooling (GAP-P4-068):
# the legacy path refuses to run rather than defaulting to a demo password.
if [[ -z "$PASSWORD" ]]; then
  log "FATAL: AETHER_CRON_PASSWORD or LOGIN_PASSWORD must be set (env var, or" \
      " LOGIN_PASSWORD in the repo-root .env) to authenticate the legacy" \
      " single-account discovery cron. Refusing to hardcode a default" \
      " credential. Set AETHER_SYSTEM_RUN_SECRET to use the multi-subscriber" \
      " sweep instead, which needs no user password."
  exit 1
fi

LOGIN_RESP=$(http_call POST "$API/auth/login" \
  "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(printf '%s' "$LOGIN_RESP" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# MON-005 (MONITORING-LEDGER.md): the live JWT is handed to curl through a
# CONFIG FILE it reads itself, never as an inline authorization-header argv
# token. Command-line arguments are world-readable via `ps aux` /
# /proc/<pid>/cmdline for the lifetime of the process, so every 30-minute tick
# briefly exposed a valid access token (and the system-run secret) to any local
# shell user. The file lives in a 0700 directory, is created with a 0077 umask
# (0600), is removed on EVERY exit path by the trap below, and the token value
# is never echoed or logged.
CURL_CONF_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aether-discovery-curl.XXXXXX")"
chmod 700 "$CURL_CONF_DIR"
trap 'rm -rf "$CURL_CONF_DIR"' EXIT

AUTH_CONF="$CURL_CONF_DIR/auth.conf"
(umask 077; : > "$AUTH_CONF")
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > "$AUTH_CONF"
AUTH_ARGS=(--config "$AUTH_CONF")

ME=$(http_call GET "$API/auth/me" "" "${AUTH_ARGS[@]}")
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
#
# MON-005: carried in a SECOND config file (same 0600 private dir) rather than
# argv, for the same reason as the bearer token above. It stays a separate file
# from AUTH_CONF so the system-run header still reaches ONLY the two agent
# calls it is scoped to -- /auth/me above must not send it.
AGENT_ARGS=("${AUTH_ARGS[@]}")
if [[ -n "${AETHER_SYSTEM_RUN_SECRET:-}" ]]; then
  AGENT_CONF="$CURL_CONF_DIR/agent.conf"
  (umask 077; : > "$AGENT_CONF")
  {
    printf 'header = "Authorization: Bearer %s"\n' "$TOKEN"
    printf 'header = "X-Aether-System-Run: %s"\n' "$AETHER_SYSTEM_RUN_SECRET"
  } > "$AGENT_CONF"
  AGENT_ARGS=(--config "$AGENT_CONF")
fi

log "scout run: query='$QUERY' location='$LOCATION'"
SCOUT=$(http_call POST "$API/agents/scout/run" \
  "{\"query\":\"$QUERY\",\"location\":\"$LOCATION\"}" \
  "${AGENT_ARGS[@]}")
log "scout: $SCOUT"

SCORER=$(http_call POST "$API/agents/fit-scorer/run" "" "${AGENT_ARGS[@]}")
log "fit-scorer: $SCORER"
