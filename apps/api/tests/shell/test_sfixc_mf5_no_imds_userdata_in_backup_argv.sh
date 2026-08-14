#!/usr/bin/env bash
# MF-5 (S-FIX slice C, round-2 re-review `MF-REREVIEW-slice-C-20260814T031443Z.md`)
# — the whole IMDSv2 user-data JSON (which carries `abacus_api_key` and a
# hosted-DB `database_url`/`role_password`) is handed to python3 as
# `sys.argv[1]` twice per 6-hourly backup run in deploy/aether-backup.sh.
#
# Evidence (round-2 review): $user_data is the full IMDS user-data document;
# passing it as sys.argv[1] puts every secret it contains into
# /proc/<pid>/cmdline and `ps aux` for the lifetime of each python3 call —
# the exact defect class MF-2 was raised (and fixed) for, in the same new
# file, with a larger payload (LLM-billing API key + DB credential vs one DB
# credential).
#
# Contract asserted here (static only — MF-2's test already proves the
# env-var-handoff *pattern* works dynamically for this script):
#   (a) no python3 invocation in the script receives `$user_data` (or a
#       renamed alias of it) via sys.argv — i.e. no "python3 -c ... "
#       followed by a trailing `"$user_data"`-shaped argument.
#   (b) the bucket/base_path extraction instead feeds the IMDS user-data
#       JSON to python3 via an exported environment variable (mirroring the
#       AETHER_BACKUP_DSN technique already used at :69-70 for MF-2), and
#       that variable is unset again afterwards so it does not linger in
#       this shell's exported environment for child processes started later.
# Both FAIL against the pre-fix script (sys.argv[1] carries $user_data at
# two call sites; no env-var handoff exists for it).
#
# Usage: bash apps/api/tests/shell/test_sfixc_mf5_no_imds_userdata_in_backup_argv.sh
# Exit 0 = both assertions passed. Exit 1 = at least one failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
BACKUP_SCRIPT="$REPO_ROOT/deploy/aether-backup.sh"

if [[ ! -f "$BACKUP_SCRIPT" ]]; then
  echo "FAIL: backup script not found at $BACKUP_SCRIPT" >&2
  exit 1
fi

FAILURES=0

echo "--- (a) scanning $BACKUP_SCRIPT for IMDS user-data passed as python3 argv ---"
# The leak shape: a python3 -c invocation whose trailing argument is a
# variable holding the raw IMDS user-data response (commonly named
# user_data / userdata / ud_json_raw etc. — match the broad "user.?data"
# family so a bare rename doesn't defeat the check).
OFFENDERS_A="$(grep -nE 'python3 -c.*"\$\{?[Uu]ser_?[Dd]ata\}?"' "$BACKUP_SCRIPT" || true)"
if [[ -z "$OFFENDERS_A" ]]; then
  echo "PASS (a): no python3 invocation receives the IMDS user-data blob as an argv argument"
else
  echo "FAIL (a): python3 invocation(s) still receive IMDS user-data via argv:"
  echo "$OFFENDERS_A"
  FAILURES=$((FAILURES + 1))
fi

echo "--- (b) scanning $BACKUP_SCRIPT for env-var handoff of the IMDS user-data blob ---"
# Real fix must export the JSON into the environment (os.environ[...] read
# inside the heredoc/python3 -c body) rather than deleting the bucket/path
# resolution outright.
if grep -qE "os\.environ\[.[A-Za-z_]+.\]" "$BACKUP_SCRIPT" && \
   grep -qE '^\s*export [A-Za-z_]+_(JSON|USER_DATA|UD)(=|$)' "$BACKUP_SCRIPT"; then
  echo "PASS (b): script exports IMDS user-data via an environment variable read inside python3 (os.environ), not argv"
else
  echo "FAIL (b): no env-var handoff of the IMDS user-data blob found (bucket/path resolution may be broken, or the argv leak was only half-fixed)"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed) — MF-5 no-IMDS-userdata-in-argv contract not met"
  exit 1
fi
echo "RESULT: PASS"
exit 0
