#!/usr/bin/env bash
# ops_alert.sh — operator alert email for a failed prod systemd unit (D-ALERT).
#
# Invoked as `ExecStart=.../ops_alert.sh %i` by deploy/aether-alert@.service,
# itself fired via `OnFailure=aether-alert@%n.service` from the drop-ins in
# deploy/systemd-dropins/ (see docs/delivery/OPS-ALERTING.md for the install
# + test-fire recipe — nothing here is wired into systemd by this ticket).
#
# Sends via the SAME Resend-style HTTPS API the app already uses for
# transactional email (apps/api/app/services/email_sender.py::_send_via_api)
# — no new provider, no new credential. Reads its two keys, AETHER_EMAIL_API_KEY
# and AETHER_EMAIL_FROM, out of the repo-root .env with a single-key grep
# (the extraction idiom scripts/run-tests.sh uses for DATABASE_URL_TEST /
# scripts/env-audit.sh's get_val) rather than sourcing the whole file — a
# wholesale `source .env` would pull unrelated production secrets (e.g.
# DATABASE_URL) into this process's environment for no reason.
#
# Contract: this script must NEVER crash-loop the alert@ unit. Every failure
# mode (missing keys, no log file, network error, non-2xx response) is
# logged to stderr and the script still exits 0 — see the final `exit 0`.
# Deliberately not `set -e`: a single missing/failing step (e.g. the log file
# not existing) must degrade the alert body, not abort the send.
set -uo pipefail

UNIT="${1:-unknown}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ALERT_TO="sarkar.vikram@gmail.com"

# Single-key extraction, no wholesale `source` — same convention as
# scripts/run-tests.sh (DATABASE_URL_TEST) / scripts/env-audit.sh (get_val).
get_env_val() {
  local key="$1" val
  val="$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "$val"
}

api_key=""
email_from=""
if [[ -f "$ENV_FILE" ]]; then
  api_key="$(get_env_val AETHER_EMAIL_API_KEY)"
  email_from="$(get_env_val AETHER_EMAIL_FROM)"
fi

# Per-unit log file this repo's systemd drop-ins already write to (see
# deploy/aether-*.service.d/logging.conf): "aether-api.service" -> "api.log".
short="${UNIT#aether-}"
short="${short%.service}"
LOG_FILE="/var/log/aether/${short}.log"

timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
if [[ -f "$LOG_FILE" ]]; then
  log_excerpt="$(tail -n 40 "$LOG_FILE" 2>/dev/null)"
  [[ -z "$log_excerpt" ]] && log_excerpt="(log file exists but is empty)"
else
  log_excerpt="No log file at $LOG_FILE — this unit has no file-based log sink (or hasn't logged yet). Check with: journalctl -u \"$UNIT\" -n 40 --no-pager"
fi

subject="[Aether ALERT] unit $UNIT failed on prod VM"
body="Unit: $UNIT
Failed/alerted at: $timestamp UTC

--- last 40 lines of $LOG_FILE ---
$log_excerpt"

if [[ -z "$api_key" || -z "$email_from" ]]; then
  echo "ops_alert.sh: AETHER_EMAIL_API_KEY / AETHER_EMAIL_FROM not configured in $ENV_FILE — cannot send alert for unit '$UNIT'. See docs/delivery/OPS-ALERTING.md." >&2
  exit 0
fi

# Build the JSON payload with python3 (stdlib json — correct escaping of the
# log excerpt's newlines/quotes, avoids hand-rolled JSON string building).
# The API key never enters this payload or argv here; it goes into the curl
# request only via the header config file below.
json_payload="$(python3 - "$email_from" "$ALERT_TO" "$subject" "$body" <<'PY'
import json
import sys

from_addr, to_addr, subject, body = sys.argv[1:5]
print(json.dumps({"from": from_addr, "to": [to_addr], "subject": subject, "text": body}))
PY
)" || {
  echo "ops_alert.sh: failed to build JSON payload for unit '$UNIT' alert." >&2
  exit 0
}

# Pass the Authorization header via a curl config file rather than -H on the
# command line: -H "...$api_key" would put the key in this process's argv,
# readable by any local user via `ps`/`/proc`. The config file is created
# 0600 in a private per-invocation temp dir and removed immediately after.
# Never echo the key anywhere (stdout, stderr, or the request body/subject).
curl_tmp_dir="$(mktemp -d)" || curl_tmp_dir=""
send_ok=0
if [[ -n "$curl_tmp_dir" ]]; then
  curl_cfg="$curl_tmp_dir/curl.cfg"
  (
    umask 077
    printf 'header = "Authorization: Bearer %s"\n' "$api_key" > "$curl_cfg"
  )
  http_status="$(curl -s -o /dev/null -w '%{http_code}' \
    -K "$curl_cfg" \
    -X POST "https://api.resend.com/emails" \
    -H "Content-Type: application/json" \
    --max-time 10 \
    -d "$json_payload" 2>/dev/null)" || http_status="000"
  rm -rf "$curl_tmp_dir"
  [[ "$http_status" == 2* ]] && send_ok=1
  if [[ "$send_ok" -ne 1 ]]; then
    echo "ops_alert.sh: alert send for unit '$UNIT' failed (HTTP ${http_status:-unknown}). API key not printed." >&2
  fi
else
  echo "ops_alert.sh: could not create a temp dir for the curl config; alert for unit '$UNIT' NOT sent." >&2
fi

exit 0
