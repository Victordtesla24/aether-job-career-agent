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
# THROTTLE (D-ALERT-2). The Resend quota is shared with the application's own
# transactional mail (password reset, welcome), so a crash-looping unit must
# never be able to spend it. On 2026-10-13 a unit restarting every ~6 s sent
# 215 alert emails in four hours and the application's welcome email was
# rejected with daily_quota_exceeded. Two limits now apply to every call:
#   * per unit: at most one email per AETHER_ALERT_MIN_INTERVAL_SECS (default
#     3600). Failures inside the interval are only counted; the next email
#     states how many were suppressed and when (the "N suppressed since" line).
#   * global: at most AETHER_ALERT_DAILY_CAP emails per UTC day (default 10)
#     across all units; the last permitted email says so.
# A send that fails (network, HTTP 4xx/5xx) is retried no sooner than
# AETHER_ALERT_RETRY_AFTER_FAILURE_SECS (default 600) and does not count against
# the daily cap. State lives in AETHER_ALERT_STATE_DIR (default
# /var/lib/aether-alert); if that is not writable the script falls back to a
# private directory under ${TMPDIR:-/tmp}. A flock serialises concurrent calls.
# AETHER_ALERT_NOW (epoch seconds) overrides the clock and exists for tests only.
#
# Contract: this script must NEVER crash-loop the alert@ unit. Every failure
# mode (missing keys, no state dir, no log file, network error, non-2xx
# response, corrupt state, an unexpected shell error) is logged to stderr and
# the script still exits 0 — the EXIT trap below guarantees it. Deliberately
# not `set -e`: a single missing/failing step (e.g. the log file not existing)
# must degrade the alert body, not abort the send.
set -uo pipefail
trap 'exit 0' EXIT

UNIT="${1:-unknown}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
ALERT_TO="sarkar.vikram@gmail.com"

uint_or_default() { # value default -> value when it is a non-negative integer, else default
  if [[ "${1:-}" =~ ^[0-9]{1,12}$ ]]; then printf '%s' "$((10#$1))"; else printf '%s' "$2"; fi
}
MIN_INTERVAL="$(uint_or_default "${AETHER_ALERT_MIN_INTERVAL_SECS:-}" 3600)"
DAILY_CAP="$(uint_or_default "${AETHER_ALERT_DAILY_CAP:-}" 10)"
RETRY_AFTER_FAILURE="$(uint_or_default "${AETHER_ALERT_RETRY_AFTER_FAILURE_SECS:-}" 600)"
NOW="$(uint_or_default "${AETHER_ALERT_NOW:-}" "$(date +%s)")"
iso() { date -u -d "@$1" +"%Y-%m-%dT%H:%M:%SZ"; }

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

timestamp="$(iso "$NOW")"
subject="[Aether ALERT] unit $UNIT failed on prod VM"

if [[ -z "$api_key" || -z "$email_from" ]]; then
  echo "ops_alert.sh: AETHER_EMAIL_API_KEY / AETHER_EMAIL_FROM not configured in $ENV_FILE — cannot send alert for unit '$UNIT'. See docs/delivery/OPS-ALERTING.md." >&2
  exit 0
fi

# ---------------------------------------------------------------- state + lock
pick_state_dir() { # first writable, self-owned, non-symlink directory of the candidates
  local d
  for d in "${AETHER_ALERT_STATE_DIR:-/var/lib/aether-alert}" "${TMPDIR:-/tmp}/aether-alert-$(id -u)"; do
    mkdir -p "$d" 2>/dev/null || continue
    if [[ -d "$d" && ! -L "$d" && -O "$d" && -w "$d" ]]; then
      chmod 700 "$d" 2>/dev/null
      printf '%s' "$d"
      return 0
    fi
  done
  return 1
}

STATE_DIR="$(pick_state_dir)" || STATE_DIR=""
unit_key="$(printf '%s' "$UNIT" | tr -c 'A-Za-z0-9_.@-' '_')"
UNIT_STATE="$STATE_DIR/unit-${unit_key}.state"
DAY_STATE="$STATE_DIR/day-$(date -u -d "@$NOW" +%F).count"

next_allowed=0 suppressed=0 first_suppressed=0 last_suppressed=0 sent_today=0

load_state() {
  local line kv
  if [[ -r "$UNIT_STATE" ]]; then
    read -r line <"$UNIT_STATE" || line=""
    for kv in $line; do
      case "$kv" in
        next_allowed=*)     next_allowed="$(uint_or_default "${kv#*=}" 0)" ;;
        suppressed=*)       suppressed="$(uint_or_default "${kv#*=}" 0)" ;;
        first_suppressed=*) first_suppressed="$(uint_or_default "${kv#*=}" 0)" ;;
        last_suppressed=*)  last_suppressed="$(uint_or_default "${kv#*=}" 0)" ;;
      esac
    done
  fi
  if [[ -r "$DAY_STATE" ]]; then
    read -r line <"$DAY_STATE" || line=""
    sent_today="$(uint_or_default "$line" 0)"
  fi
}

write_file_atomic() { # path content
  local tmp="$1.$$"
  if printf '%s\n' "$2" >"$tmp" 2>/dev/null; then
    mv -f "$tmp" "$1" 2>/dev/null || rm -f "$tmp" 2>/dev/null
  else
    rm -f "$tmp" 2>/dev/null
  fi
}

save_state() {
  [[ -n "$STATE_DIR" ]] || return 0
  write_file_atomic "$UNIT_STATE" "next_allowed=$next_allowed suppressed=$suppressed first_suppressed=$first_suppressed last_suppressed=$last_suppressed"
  write_file_atomic "$DAY_STATE" "$sent_today"
}

if [[ -n "$STATE_DIR" ]]; then
  # Serialise concurrent alerts (two units failing together) so the counters stay exact.
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$STATE_DIR/lock" && flock -w 30 9 || echo "ops_alert.sh: could not take the state lock within 30 s; continuing without it." >&2
  fi
  find "$STATE_DIR" -maxdepth 1 -name 'day-*.count' -mtime +3 -delete 2>/dev/null
  find "$STATE_DIR" -maxdepth 1 -name 'unit-*.state' -mtime +30 -delete 2>/dev/null
  load_state
else
  echo "ops_alert.sh: no writable state directory (AETHER_ALERT_STATE_DIR, ${TMPDIR:-/tmp}); throttle state unavailable, sending this alert unthrottled." >&2
fi

suppress() { # reason
  suppressed=$((suppressed + 1))
  [[ "$first_suppressed" -eq 0 ]] && first_suppressed="$NOW"
  last_suppressed="$NOW"
  save_state
  echo "ops_alert.sh: alert for unit '$UNIT' suppressed ($1); $suppressed suppressed since the last email." >&2
  exit 0
}

if [[ -n "$STATE_DIR" ]]; then
  if [[ "$NOW" -lt "$next_allowed" ]]; then
    suppress "next email for this unit allowed at $(iso "$next_allowed")"
  fi
  if [[ "$sent_today" -ge "$DAILY_CAP" ]]; then
    suppress "daily cap of $DAILY_CAP alert emails reached for $(date -u -d "@$NOW" +%F) UTC"
  fi
fi

# ---------------------------------------------------------------- compose + send
if [[ -f "$LOG_FILE" ]]; then
  log_excerpt="$(tail -n 40 "$LOG_FILE" 2>/dev/null)"
  [[ -z "$log_excerpt" ]] && log_excerpt="(log file exists but is empty)"
else
  log_excerpt="No log file at $LOG_FILE — this unit has no file-based log sink (or hasn't logged yet). Check with: journalctl -u \"$UNIT\" -n 40 --no-pager"
fi

throttle_note=""
if [[ "$suppressed" -gt 0 ]]; then
  throttle_note="$suppressed further alert(s) for this unit were suppressed since the last email (first at $(iso "$first_suppressed"), last at $(iso "$last_suppressed")); at most one email per $((MIN_INTERVAL / 60)) min is sent per unit."
fi
if [[ -n "$STATE_DIR" && $((sent_today + 1)) -ge "$DAILY_CAP" ]]; then
  throttle_note="${throttle_note:+$throttle_note }This is the last alert email allowed today ($DAILY_CAP per UTC day across all units); further alerts are suppressed until 00:00 UTC."
fi
if [[ -n "$throttle_note" ]]; then
  log_excerpt="[throttle] $throttle_note
$log_excerpt"
fi

# Build the JSON payload with python3 (stdlib json — correct escaping of the
# log excerpt's newlines/quotes, avoids hand-rolled JSON string building).
# HTML chrome comes from email_branding (same renderer as Brand-tab
# ops_alert). If that import fails, the alert still goes out as plain text.
# The API key never enters this payload or argv here; it goes into the curl
# request only via the header config file below.
json_payload="$(PYTHONPATH="$REPO_ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}" python3 - \
  "$email_from" "$ALERT_TO" "$subject" "$UNIT" "$timestamp" "$LOG_FILE" "$log_excerpt" <<'PY'
import json
import sys

from_addr, to_addr, subject, unit, timestamp, log_path, log_excerpt = sys.argv[1:8]
text = (
    f"Unit: {unit}\n"
    f"Failed/alerted at: {timestamp} UTC\n\n"
    f"--- last 40 lines of {log_path} ---\n"
    f"{log_excerpt}"
)
payload = {"from": from_addr, "to": [to_addr], "subject": subject, "text": text}
try:
    from app.services.email_branding import build_ops_alert_bodies

    html, text = build_ops_alert_bodies(
        unit=unit,
        timestamp=timestamp,
        log_excerpt=log_excerpt,
        log_path=log_path,
    )
    payload["text"] = text
    payload["html"] = html
except Exception as exc:  # noqa: BLE001 — an alert must still send
    print(
        f"ops_alert.sh: gilt template unavailable ({type(exc).__name__}); "
        "sending plain text. API key not printed.",
        file=sys.stderr,
    )
print(json.dumps(payload))
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

# ---------------------------------------------------------------- record the outcome
if [[ "$send_ok" -eq 1 ]]; then
  sent_today=$((sent_today + 1))
  next_allowed=$((NOW + MIN_INTERVAL))
  suppressed=0 first_suppressed=0 last_suppressed=0
else
  next_allowed=$((NOW + RETRY_AFTER_FAILURE))
fi
save_state

exit 0
