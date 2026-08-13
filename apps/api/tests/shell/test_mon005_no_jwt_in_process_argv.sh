#!/usr/bin/env bash
# MON-005 (MONITORING-LEDGER.md) — live JWT bearer token visible in process
# argv.
#
# Evidence: observed 2026-08-13 sweep of systemd/ps surface — discovery-cron's
# curl invocations pass the bearer token literally as a `-H "Authorization:
# Bearer <token>"` command-line argument, which is visible to ANY local shell
# user via `ps aux` / `/proc/<pid>/cmdline` for the (short) lifetime of the
# curl process. TRIAGED fix: pass the header via a FILE curl reads itself
# (`-H @<file>` or `--config <file>`) so the secret never appears in argv.
#
# Contract asserted here (two checks):
#   (a) STATIC — scripts/discovery_cron.sh must not contain a curl invocation
#       that inlines "Authorization: Bearer" directly as a `-H` argument
#       (the exact literal-argv leak).
#   (b) STATIC — the script must actually USE a file-based header mechanism
#       (`-H @<path>` / `--config <path>` / `-K <path>`) somewhere — i.e. the
#       fix must be a real replacement, not merely deleting the header.
# Both FAIL against the pre-fix script: it has three inline
# `-H "Authorization: Bearer $TOKEN"` call sites (the /auth/me, scout and
# fit-scorer calls) and zero file-based header usage anywhere.
#
# Usage: bash apps/api/tests/shell/test_mon005_no_jwt_in_process_argv.sh
# Exit 0 = both assertions passed. Exit 1 = at least one failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
CRON_SCRIPT="$REPO_ROOT/scripts/discovery_cron.sh"

if [[ ! -f "$CRON_SCRIPT" ]]; then
  echo "FAIL: cron script not found at $CRON_SCRIPT" >&2
  exit 1
fi

FAILURES=0

echo "--- scanning $CRON_SCRIPT for inline Authorization-header argv leaks ---"

# (a) Any line that hands curl a `-H` argument literally containing
# "Authorization: Bearer" is the exact argv-leak shape (a live token
# interpolated straight into the process's command line).
OFFENDERS="$(grep -nE -- '-H[[:space:]]+["'"'"'][^"'"'"']*Authorization:[[:space:]]*Bearer' "$CRON_SCRIPT" || true)"

if [[ -z "$OFFENDERS" ]]; then
  echo "PASS (a): no inline '-H \"Authorization: Bearer ...\"' argv leak found"
else
  echo "FAIL (a): inline Authorization-header argv leak(s) found:"
  echo "$OFFENDERS"
  FAILURES=$((FAILURES + 1))
fi

# (b) A real fix reads the header from a file curl is pointed at, never the
# secret value itself as a literal argv token.
if grep -qE -- '-H[[:space:]]+@|--header[[:space:]]+@|--config[[:space:]]|-K[[:space:]]' "$CRON_SCRIPT"; then
  echo "PASS (b): a file-based curl header mechanism (-H @file / --config) is present"
else
  echo "FAIL (b): no file-based curl header mechanism found — the Authorization" \
       "header must be supplied via a file curl reads (-H @file or --config)," \
       "not as a literal argv value"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed) — MON-005 no-JWT-in-argv contract not met"
  exit 1
fi
echo "RESULT: PASS"
exit 0
