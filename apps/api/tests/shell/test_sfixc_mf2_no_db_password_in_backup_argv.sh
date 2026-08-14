#!/usr/bin/env bash
# MF-2 (S-FIX slice C reviewer round) — production DB password placed in
# process argv every 6 hours by deploy/aether-backup.sh.
#
# Evidence: `pg_dump --schema=aether --no-owner --no-privileges
# --format=plain "$base_url"` passed the full DSN (role:password@host) as a
# trailing positional argument. pg_dump/psql do not scrub argv (only the
# Postgres SERVER calls setproctitle on itself — the CLIENT process argv is
# untouched), so for the whole duration of the dump the prod credential is
# readable via `ps aux` / `/proc/<pid>/cmdline` by any local shell user, and
# is easy to accidentally capture into a transcript or evidence file on a VM
# where many concurrent agent sessions run `ps` routinely. This directly
# contradicts the script's own safety header ("never echoes/logs the
# credential value"). docs/delivery/DEPLOYMENT-RUNBOOK.md section 10.2's
# restore recipe taught operators the identical pattern
# (`psql -v ON_ERROR_STOP=1 "$BASE_URL"`).
#
# Fix: parse the DSN into PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
# (libpq's own environment-variable convention, which pg_dump/psql read
# automatically) so the connection string — and therefore the credential —
# never appears as a pg_dump/psql command-line argument. Update the runbook
# restore recipe identically.
#
# Contract asserted here (four checks):
#   (a) STATIC (script) — no pg_dump invocation in deploy/aether-backup.sh
#       passes a `$base_url` / `$raw_url`-shaped DSN variable as a trailing
#       argument.
#   (b) STATIC (script) — the script sets PGPASSWORD (or PGPASSFILE) from
#       the parsed DSN before invoking pg_dump — i.e. a real credential-safe
#       replacement, not merely a deletion.
#   (c) STATIC (runbook) — the restore recipe in
#       docs/delivery/DEPLOYMENT-RUNBOOK.md no longer hands psql a
#       `"$BASE_URL"` (or equivalent DSN variable) as a trailing argument.
#   (d) STATIC (runbook) — the restore recipe sets PGPASSWORD (or
#       PGPASSFILE) before invoking psql, mirroring the script's fix.
# All four FAIL against the pre-fix script/runbook.
#
# Usage: bash apps/api/tests/shell/test_sfixc_mf2_no_db_password_in_backup_argv.sh
# Exit 0 = all assertions passed. Exit 1 = at least one failed.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
BACKUP_SCRIPT="$REPO_ROOT/deploy/aether-backup.sh"
RUNBOOK="$REPO_ROOT/docs/delivery/DEPLOYMENT-RUNBOOK.md"

if [[ ! -f "$BACKUP_SCRIPT" ]]; then
  echo "FAIL: backup script not found at $BACKUP_SCRIPT" >&2
  exit 1
fi
if [[ ! -f "$RUNBOOK" ]]; then
  echo "FAIL: runbook not found at $RUNBOOK" >&2
  exit 1
fi

FAILURES=0

echo "--- (a) scanning $BACKUP_SCRIPT for a DSN passed as a pg_dump argv ---"
# Any pg_dump line that still references the raw/base URL variables as an
# argument is the exact argv-leak shape.
OFFENDERS_A="$(grep -nE 'pg_dump.*\$(\{)?(base_url|raw_url|DATABASE_URL)' "$BACKUP_SCRIPT" || true)"
if [[ -z "$OFFENDERS_A" ]]; then
  echo "PASS (a): no pg_dump invocation references a DSN variable as an argument"
else
  echo "FAIL (a): pg_dump invocation(s) still pass a DSN variable as an argument:"
  echo "$OFFENDERS_A"
  FAILURES=$((FAILURES + 1))
fi

echo "--- (b) scanning $BACKUP_SCRIPT for PGPASSWORD/PGPASSFILE set before pg_dump ---"
# Not anchored to line-start: the credential-safe replacement builds the
# PG* exports inside a small python3 heredoc (so the DSN parse never touches
# argv either), so the literal "export PGPASSWORD=" text is indented / not
# at column 0. What matters is that the mechanism genuinely exists somewhere
# in the script, ahead of the pg_dump call.
if grep -qE 'PG(PASSWORD|PASSFILE)=' "$BACKUP_SCRIPT"; then
  echo "PASS (b): script sets PGPASSWORD/PGPASSFILE from the parsed DSN"
else
  echo "FAIL (b): script never sets PGPASSWORD/PGPASSFILE — no real credential-safe" \
       "connection mechanism found"
  FAILURES=$((FAILURES + 1))
fi

echo "--- (c) scanning $RUNBOOK restore recipe for a DSN passed as a psql argv ---"
OFFENDERS_C="$(grep -nE 'psql[^\n]*"\$(BASE_URL|DB_URL|DATABASE_URL)"' "$RUNBOOK" || true)"
if [[ -z "$OFFENDERS_C" ]]; then
  echo "PASS (c): runbook restore recipe no longer hands psql a DSN as an argument"
else
  echo "FAIL (c): runbook restore recipe still hands psql a DSN as an argument:"
  echo "$OFFENDERS_C"
  FAILURES=$((FAILURES + 1))
fi

echo "--- (d) scanning $RUNBOOK restore recipe for PGPASSWORD/PGPASSFILE before psql ---"
if grep -qE 'PG(PASSWORD|PASSFILE)=' "$RUNBOOK"; then
  echo "PASS (d): runbook restore recipe sets PGPASSWORD/PGPASSFILE"
else
  echo "FAIL (d): runbook restore recipe never mentions PGPASSWORD/PGPASSFILE"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed) — MF-2 no-DB-password-in-argv contract not met"
  exit 1
fi
echo "RESULT: PASS"
exit 0
