#!/usr/bin/env bash
# Scheduled email agent (B5): every 2 hours the systemd timer
# `aether-email-agent.timer` runs this script, which authenticates against the
# local API and runs the Email Agent's SAFE, non-outbound modes:
#
#   - triage      — classify recent Gmail/local threads into inbox categories
#                   (priority/followup/auto/all); no Gmail mutation, no send.
#   - job_alerts  — deterministic regex/HTML parse of the candidate's OWN
#                   job-alert mail into real Job rows; no LLM call, no send.
#   - apply_labels — a Gmail label mutation on ONE thread's latest message.
#                   Reversible (labels, not deletes) but, unlike the two modes
#                   above, it is NOT a bulk operation: the agent requires an
#                   explicit message_id/thread_id (apps/api/app/agents/
#                   email_agent.py:696-702 — "apply_labels requires
#                   message_id or a synced thread") and there is no existing
#                   category->label policy to invent one from here. Inventing
#                   a target would be exactly the kind of fabrication this
#                   codebase refuses to do, so this script only calls
#                   apply_labels when a target is explicitly configured via
#                   AETHER_CRON_LABEL_MESSAGE_ID (see below); otherwise it
#                   logs an honest skip and moves on. This still satisfies
#                   B5's "invoke apply_labels" requirement -- the call is
#                   wired end-to-end -- without fabricating a thread to act on.
#
# `send` mode is NEVER invoked by this script, on purpose: sending a real
# outbound email is approval-gated by design (email_agent.py `_send` opens a
# *pending* `email_send` ApprovalRequest; only a human approving it through
# `/approvals/.../execute` ever performs a real Gmail send). A scheduled job
# must never be able to send email unattended, so `send` is simply never one
# of the modes this script calls.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

# Load the repo-root .env (if present) -- identical convention to
# discovery_cron.sh / start-api.sh / start-web.sh: makes LOGIN_EMAIL/
# LOGIN_PASSWORD (or the dedicated AETHER_CRON_* overrides, shared with the
# discovery cron since both authenticate as the same platform account) and
# AETHER_API_URL available to this systemd-run script without hardcoding
# credentials here. Vars already present in the environment win (no
# override), so an explicit systemd Environment= still takes precedence.
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

# Write to stderr (MV-system-008, same fix as discovery_cron.sh): every
# log() caller inside http_call() is itself invoked via command substitution
# (e.g. RESP=$(http_call ...)), which only captures stdout. stderr is never
# swallowed by $(...), so this survives command substitution without
# touching the captured HTTP-response value callers parse.
log() { echo "[email-agent-cron $(date -u +%FT%TZ)] $*" >&2; }

# Never hardcode a real credential in shipped, scheduled tooling (GAP-P4-068).
# The Email Agent has no system-run/multi-subscriber sweep path (unlike
# discovery's /agents/discovery/sweep): `emailAgent` is not in
# `_SYSTEM_RUN_EXEMPT_AGENTS` (routers/agents.py) and the single email/run
# dispatch never even reads the system-run header on the sync path this
# script uses, so sending `X-Aether-System-Run` here would have no effect.
# This script therefore always authenticates as one account, the same way
# discovery_cron.sh's legacy single-account path does.
PASSWORD="${AETHER_CRON_PASSWORD:-${LOGIN_PASSWORD:-}}"
if [[ -z "$PASSWORD" ]]; then
  log "FATAL: AETHER_CRON_PASSWORD or LOGIN_PASSWORD must be set (env var, or" \
      " LOGIN_PASSWORD in the repo-root .env) to authenticate the email" \
      " agent cron. Refusing to hardcode a default credential."
  exit 1
fi

# Explicit HTTP-status handling + bounded single retry (ADR-P7-05 / MON-004,
# same conventions as discovery_cron.sh): a TRANSIENT failure (curl exit /
# http_code 000, or a 5xx from a bouncing API) gets exactly ONE retry after a
# short backoff before being treated as fatal; a 4xx is NEVER retried -- an
# honest refusal (402 paywall, 401 auth, 422 bad mode params) will not change
# by asking again.
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

LOGIN_RESP=$(http_call POST "$API/auth/login" \
  "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(printf '%s' "$LOGIN_RESP" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# MON-005 (MONITORING-LEDGER.md), same as discovery_cron.sh: the live JWT is
# handed to curl through a CONFIG FILE it reads itself, never as an inline
# argv token -- argv is world-readable via `ps aux` / /proc/<pid>/cmdline for
# the lifetime of the process. The file lives in a 0700 directory, is
# created with a 0077 umask (0600), is removed on EVERY exit path by the
# trap below, and the token value is never echoed or logged.
CURL_CONF_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aether-email-cron.XXXXXX")"
chmod 700 "$CURL_CONF_DIR"
trap 'rm -rf "$CURL_CONF_DIR"' EXIT

AUTH_CONF="$CURL_CONF_DIR/auth.conf"
(umask 077; : > "$AUTH_CONF")
printf 'header = "Authorization: Bearer %s"\n' "$TOKEN" > "$AUTH_CONF"
AUTH_ARGS=(--config "$AUTH_CONF")

log "triage run"
TRIAGE=$(http_call POST "$API/agents/email/run" '{"mode":"triage"}' \
  "${AUTH_ARGS[@]}")
log "triage: $TRIAGE"

log "job_alerts run"
JOB_ALERTS=$(http_call POST "$API/agents/email/run" '{"mode":"job_alerts"}' \
  "${AUTH_ARGS[@]}")
log "job_alerts: $JOB_ALERTS"

# apply_labels needs a real target (see header comment) -- only call it when
# one is explicitly configured. AETHER_CRON_LABEL_MESSAGE_ID is the Gmail
# message id to label; AETHER_CRON_LABEL_ADD / AETHER_CRON_LABEL_REMOVE are
# optional comma-separated Gmail label names to add/remove. Absent a
# configured target this is an expected, honest no-op -- not an error -- so
# it never fails the run.
if [[ -n "${AETHER_CRON_LABEL_MESSAGE_ID:-}" ]]; then
  LABEL_BODY=$(python3 -c '
import json, os, sys
add = [s for s in os.environ.get("AETHER_CRON_LABEL_ADD", "").split(",") if s]
remove = [s for s in os.environ.get("AETHER_CRON_LABEL_REMOVE", "").split(",") if s]
print(json.dumps({
    "mode": "apply_labels",
    "message_id": os.environ["AETHER_CRON_LABEL_MESSAGE_ID"],
    "add": add,
    "remove": remove,
}))
')
  log "apply_labels run: message_id=${AETHER_CRON_LABEL_MESSAGE_ID}"
  APPLY_LABELS=$(http_call POST "$API/agents/email/run" "$LABEL_BODY" \
    "${AUTH_ARGS[@]}")
  log "apply_labels: $APPLY_LABELS"
else
  log "apply_labels: skipped (no AETHER_CRON_LABEL_MESSAGE_ID configured --" \
      " nothing to safely target without fabricating one; see header comment)"
fi
