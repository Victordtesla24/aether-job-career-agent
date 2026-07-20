#!/usr/bin/env bash
# MV-system-008 regression test: scripts/discovery_cron.sh's http_call()
# FATAL branch must survive command substitution.
#
# Bug: http_call()'s FATAL branch calls log(), and log() historically wrote
# to the function's own stdout (fd 1) via a plain `echo`. Every real caller
# in the script captures http_call's stdout through command substitution
# (e.g. `LOGIN_RESP=$(http_call POST ...)`), so the FATAL diagnostic line
# was silently captured into the caller's response variable instead of
# reaching the process's real stdout/stderr -- which is exactly what
# systemd's StandardOutput=append:/var/log/aether/discovery.log /
# StandardError=append:/var/log/aether/discovery.log drop-in
# (aether-discovery.service.d/logging.conf) redirects to the log file. That
# is how a 48-hour total outage produced zero new bytes in discovery.log.
#
# This test extracts ONLY the log()/http_call() function definitions from
# the real script (sourcing the whole script would immediately run its
# side-effecting body -- password checks, real HTTP calls, etc.), then
# drives http_call() against an unreachable endpoint exactly the way every
# real caller does: `VAR=$(http_call ...)`. It asserts:
#   (a) a FATAL line lands in a log file that stands in for
#       /var/log/aether/discovery.log (fed via a stderr redirect on the
#       command substitution, mirroring systemd's StandardError=append:
#       directive on the whole process).
#   (b) the captured command-substitution stdout value does NOT contain the
#       FATAL diagnostic (i.e. response-parsing in real callers stays
#       unpolluted).
#
# Usage: bash apps/api/tests/shell/test_discovery_cron_logging.sh
# Exit 0 = both assertions passed. Exit 1 = at least one failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
CRON_SCRIPT="$REPO_ROOT/scripts/discovery_cron.sh"

if [[ ! -f "$CRON_SCRIPT" ]]; then
  echo "FAIL: cron script not found at $CRON_SCRIPT" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
LOG_FILE="$TMP_DIR/discovery.log"
: > "$LOG_FILE"
trap 'rm -rf "$TMP_DIR"' EXIT

# --- extract log() and http_call() from the real script (brace-depth aware,
#     so it works whether a function body is a one-liner or multi-line) ----
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

# --- drive http_call() against an unreachable endpoint, exactly as every
#     real caller in discovery_cron.sh does: VAR=$(http_call ...). Redirect
#     the subshell's stderr to LOG_FILE, standing in for systemd's
#     StandardError=append:/var/log/aether/discovery.log on the real
#     process. -----------------------------------------------------------
CAPTURED_STDOUT="$(http_call GET "http://127.0.0.1:1/mv-system-008-unreachable" "" 2>>"$LOG_FILE")"
RC=$?

echo "--- http_call exit code: $RC ---"
echo "--- captured stdout (what a real caller's \$(...) would receive) ---"
printf '%s\n' "$CAPTURED_STDOUT"
echo "--- log file contents ($LOG_FILE) ---"
cat "$LOG_FILE"
echo "---"

# Assertion (a): a FATAL line must land in the log file.
if grep -q "FATAL" "$LOG_FILE"; then
  echo "PASS (a): FATAL line landed in the log file"
else
  echo "FAIL (a): no FATAL line found in the log file -- diagnostics are being swallowed"
  FAILURES=$((FAILURES + 1))
fi

# Assertion (b): the captured stdout value must NOT contain the FATAL line
# (i.e. it must not corrupt what a real caller parses as the HTTP response).
if [[ "$CAPTURED_STDOUT" == *"FATAL"* ]]; then
  echo "FAIL (b): captured stdout is polluted with the FATAL diagnostic (response-parsing would break)"
  FAILURES=$((FAILURES + 1))
else
  echo "PASS (b): captured stdout is clean -- no FATAL contamination"
fi

# Sanity: http_call must still signal failure via a non-zero exit.
if [[ "$RC" -eq 0 ]]; then
  echo "FAIL (sanity): http_call against an unreachable endpoint should exit non-zero"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed)"
  exit 1
fi
echo "RESULT: PASS"
exit 0
