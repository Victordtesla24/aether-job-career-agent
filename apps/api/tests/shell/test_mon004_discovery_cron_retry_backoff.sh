#!/usr/bin/env bash
# MON-004 (MONITORING-LEDGER.md) — discovery-cron restart race.
#
# Evidence: discovery.log shows 7 historical occurrences of "discovery-cron
# FATAL POST fit-scorer/run" during service restarts (transient HTTP 000/5xx
# while the API process is bouncing) that self-heal on the NEXT cron cycle 30
# minutes later. TRIAGED fix: retry-once-with-backoff in
# scripts/discovery_cron.sh so a restart-window blip does not have to wait a
# full cycle.
#
# CURRENT CODE (pre-fix): http_call() has ZERO retry logic — any non-2xx
# status (or a curl transport failure surfacing as "000") hits the FATAL
# branch (log + exit 1) on the FIRST attempt. This harness proves that by
# driving http_call() (extracted from the real script, same technique as
# test_discovery_cron_logging.sh) against a stubbed `curl` on PATH that fails
# N times before succeeding, and counting how many times curl was actually
# invoked.
#
# Fix contract asserted here:
#   (a) a transient failure (000 or 5xx) on attempt 1, followed by success on
#       attempt 2, must result in an OVERALL SUCCESS (no FATAL) — i.e. one
#       retry happens and its result is used.
#   (b) a transient failure that persists past the retry must still FATAL —
#       and curl must be invoked EXACTLY TWICE (one retry, not zero, not
#       unbounded hammering).
# Both (a) and (b) FAIL against the pre-fix script: curl is invoked exactly
# ONCE in every case and the FATAL branch fires on the very first transient
# failure.
#
# Usage: bash apps/api/tests/shell/test_mon004_discovery_cron_retry_backoff.sh
# Exit 0 = all assertions passed. Exit 1 = at least one failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
CRON_SCRIPT="$REPO_ROOT/scripts/discovery_cron.sh"

if [[ ! -f "$CRON_SCRIPT" ]]; then
  echo "FAIL: cron script not found at $CRON_SCRIPT" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
BIN_DIR="$TMP_DIR/bin"
mkdir -p "$BIN_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

# --- extract log() and http_call() from the real script (brace-depth aware,
#     mirrors test_discovery_cron_logging.sh) --------------------------------
extract_func() {
  local name="$1" file="$2"
  awk -v fn="$name" '
    $0 ~ "^" fn "\\(\\) \\{" { found = 1 }
    found {
      print
      opens = gsub(/\{/, "{")
      closes = gsub(/\}/, "}")
      depth += opens - closes
      if (depth == 0) { exit }
    }
  ' "$file"
}

LOG_FN="$(extract_func log "$CRON_SCRIPT")"
HTTP_CALL_FN="$(extract_func http_call "$CRON_SCRIPT")"

if [[ -z "$LOG_FN" ]]; then
  echo "FAIL: could not extract log() from $CRON_SCRIPT" >&2
  exit 1
fi
if [[ -z "$HTTP_CALL_FN" ]]; then
  echo "FAIL: could not extract http_call() from $CRON_SCRIPT" >&2
  exit 1
fi

eval "$LOG_FN"
eval "$HTTP_CALL_FN"

FAILURES=0

# --- stub curl: fails MON004_FAIL_COUNT times (mode 000 or 503) then
#     succeeds; records one call-count line and one call per invocation ------
write_curl_stub() {
  local fail_count="$1" fail_mode="$2"
  cat > "$BIN_DIR/curl" <<STUB
#!/usr/bin/env bash
COUNTER_FILE="$TMP_DIR/call_count"
count=0
[[ -f "\$COUNTER_FILE" ]] && count=\$(cat "\$COUNTER_FILE")
count=\$((count + 1))
echo "\$count" > "\$COUNTER_FILE"
date +%s.%N >> "$TMP_DIR/call_times"

if (( count <= $fail_count )); then
  if [[ "$fail_mode" == "000" ]]; then
    printf '\n000'
    exit 7
  else
    printf '{"error":"upstream unavailable"}\n503'
    exit 0
  fi
fi
printf '{"ok":true,"attempt":%d}\n200' "\$count"
exit 0
STUB
  chmod +x "$BIN_DIR/curl"
}

reset_counters() {
  rm -f "$TMP_DIR/call_count" "$TMP_DIR/call_times"
}

run_case() {
  local label="$1" fail_count="$2" fail_mode="$3"
  reset_counters
  write_curl_stub "$fail_count" "$fail_mode"
  LOG_FILE="$TMP_DIR/discovery-$label.log"
  : > "$LOG_FILE"
  local captured rc
  captured=$(PATH="$BIN_DIR:$PATH" http_call POST \
    "http://127.0.0.1:8000/agents/fit-scorer/run" "" \
    -H "Authorization: Bearer test-token" 2>>"$LOG_FILE")
  rc=$?
  local calls=0
  [[ -f "$TMP_DIR/call_count" ]] && calls=$(cat "$TMP_DIR/call_count")
  {
    echo "--- case=$label fail_count=$fail_count fail_mode=$fail_mode ---"
    echo "curl invocations: $calls"
    echo "http_call exit code: $rc"
    echo "captured: $captured"
    echo "log: $(cat "$LOG_FILE")"
  } >&2
  printf '%s\n' "$calls" "$rc" "$captured"
}

echo "=== Case A: one transient failure (503) then success — must SUCCEED with exactly 2 curl calls ==="
mapfile -t RESULT_A < <(run_case "transient-then-success" 1 503)
CALLS_A="${RESULT_A[0]}"; RC_A="${RESULT_A[1]}"; BODY_A="${RESULT_A[*]:2}"

if [[ "$CALLS_A" -eq 2 ]]; then
  echo "PASS (A.retry-count): curl invoked exactly twice (one retry)"
else
  echo "FAIL (A.retry-count): expected exactly 2 curl invocations, got $CALLS_A — no retry occurred"
  FAILURES=$((FAILURES + 1))
fi
if [[ "$RC_A" -eq 0 ]]; then
  echo "PASS (A.overall-success): http_call succeeded after the retry"
else
  echo "FAIL (A.overall-success): http_call exited $RC_A — a transient failure that recovers on retry must not FATAL"
  FAILURES=$((FAILURES + 1))
fi
if [[ "$BODY_A" == *'"ok":true'* ]]; then
  echo "PASS (A.body): the successful retry's body was returned to the caller"
else
  echo "FAIL (A.body): expected the retry's success body, got: $BODY_A"
  FAILURES=$((FAILURES + 1))
fi

echo "=== Case B: one transient failure (curl transport / HTTP 000) then success ==="
mapfile -t RESULT_B < <(run_case "000-then-success" 1 000)
CALLS_B="${RESULT_B[0]}"; RC_B="${RESULT_B[1]}"

if [[ "$CALLS_B" -eq 2 ]]; then
  echo "PASS (B.retry-count): curl invoked exactly twice"
else
  echo "FAIL (B.retry-count): expected exactly 2 curl invocations, got $CALLS_B"
  FAILURES=$((FAILURES + 1))
fi
if [[ "$RC_B" -eq 0 ]]; then
  echo "PASS (B.overall-success): http_call succeeded after retrying an HTTP-000 transient failure"
else
  echo "FAIL (B.overall-success): http_call exited $RC_B on a recoverable HTTP-000 blip"
  FAILURES=$((FAILURES + 1))
fi

echo "=== Case C: persistent transient failure (every attempt 503) — must FATAL after EXACTLY one retry (2 total attempts, never unbounded) ==="
mapfile -t RESULT_C < <(run_case "persistent-failure" 99 503)
CALLS_C="${RESULT_C[0]}"; RC_C="${RESULT_C[1]}"

if [[ "$CALLS_C" -eq 2 ]]; then
  echo "PASS (C.bounded-retry): curl invoked exactly twice — one bounded retry, not unbounded hammering"
else
  echo "FAIL (C.bounded-retry): expected exactly 2 curl invocations (1 initial + 1 retry), got $CALLS_C"
  FAILURES=$((FAILURES + 1))
fi
if [[ "$RC_C" -ne 0 ]]; then
  echo "PASS (C.eventual-fatal): http_call correctly FATALs once the retry also fails"
else
  echo "FAIL (C.eventual-fatal): http_call returned success ($RC_C) despite both attempts failing"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed) — MON-004 retry-with-backoff contract not met"
  exit 1
fi
echo "RESULT: PASS"
exit 0
