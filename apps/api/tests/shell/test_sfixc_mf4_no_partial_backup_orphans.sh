#!/usr/bin/env bash
# MF-4 (S-FIX slice C reviewer round) — a dump that dies mid-stream leaves an
# unreclaimable aether-<ts>.sql.gz.partial in deploy/aether-backup.sh.
#
# Evidence: `set -euo pipefail` means a failed pg_dump | gzip pipeline aborts
# the script BEFORE the `mv "$tmp_file" "$dump_file"` line ever runs, leaving
# the ".partial" file behind. The rotation glob a few lines later
# (`"$BACKUP_DIR"/aether-*.sql.gz`) does not match a ".partial" suffix, so
# rotation can never reclaim it — every failed run permanently adds ~9MB+ to
# a directory that is otherwise capped at KEEP=14, on a VM with documented
# disk-pressure sensitivity (and a full disk is itself a backup-failure
# mode).
#
# Fix (either is acceptable, per the finding): sweep stale ".partial" files
# at the top of the run, or `trap` cleanup of the current run's tmp file on
# EXIT so a mid-stream failure can never leave an orphan.
#
# Contract asserted here:
#   (a) STATIC — the script contains an EXIT trap that removes "$tmp_file",
#       OR a startup sweep that removes "$BACKUP_DIR"/*.partial before the
#       new dump begins. Either satisfies the finding.
#   (b) DYNAMIC — the *actual cleanup logic* is exercised: extract only the
#       relevant tmp_file/trap lines from the real script (never sourcing
#       the whole side-effecting script — same technique as
#       test_discovery_cron_logging.sh) and prove that when the "pg_dump |
#       gzip" pipeline fails mid-stream (set -euo pipefail triggers the EXIT
#       trap before any `mv`), no ".partial" file survives in a scratch
#       BACKUP_DIR.
# Both FAIL against the pre-fix script (dynamic check leaves a .partial file
# behind; static check finds neither mechanism).
#
# Usage: bash apps/api/tests/shell/test_sfixc_mf4_no_partial_backup_orphans.sh
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

echo "--- (a) scanning $BACKUP_SCRIPT for a trap-based or startup-sweep cleanup mechanism ---"
HAS_TRAP="$(grep -cE "trap[[:space:]]+.*rm[[:space:]]+-f.*tmp_file" "$BACKUP_SCRIPT" || true)"
HAS_SWEEP="$(grep -cE 'rm[[:space:]]+-f[[:space:]]+--[[:space:]]+"\$BACKUP_DIR"/\*\.partial' "$BACKUP_SCRIPT" || true)"
if [[ "${HAS_TRAP:-0}" -gt 0 || "${HAS_SWEEP:-0}" -gt 0 ]]; then
  echo "PASS (a): found a trap-based EXIT cleanup of \$tmp_file and/or a startup .partial sweep"
else
  echo "FAIL (a): no trap-based cleanup of \$tmp_file and no startup .partial sweep found"
  FAILURES=$((FAILURES + 1))
fi

echo "--- (b) dynamically proving a mid-stream pg_dump failure leaves no .partial orphan ---"
TMP_DIR="$(mktemp -d)"
SCRATCH_BACKUP_DIR="$TMP_DIR/backups"
mkdir -p "$SCRATCH_BACKUP_DIR"
FAKE_BIN="$TMP_DIR/bin"
mkdir -p "$FAKE_BIN"
cleanup_tmp() { rm -rf "$TMP_DIR"; }
trap cleanup_tmp EXIT

# A pg_dump stand-in that always fails partway through emitting output —
# exactly the "dies mid-stream" failure mode the finding describes.
cat > "$FAKE_BIN/pg_dump" <<'EOF'
#!/usr/bin/env bash
echo "partial dump content before the crash"
exit 1
EOF
chmod +x "$FAKE_BIN/pg_dump"

# Extract ONLY the tmp_file/dump_file/BACKUP_DIR variable wiring plus the
# dump+rename block from the real script (never sourcing the whole
# side-effecting script — same discipline as
# test_discovery_cron_logging.sh's extract_func).
DRIVER="$TMP_DIR/driver.sh"
{
  echo '#!/usr/bin/env bash'
  echo 'set -euo pipefail'
  echo "BACKUP_DIR=\"$SCRATCH_BACKUP_DIR\""
  echo "PATH=\"$FAKE_BIN:\$PATH\""
  # The excerpt below references LOG_PREFIX and base_url, which the real
  # script defines earlier (outside this excerpt). Predefine them here with
  # harmless placeholder values so `set -u` in the excerpt doesn't abort on
  # an unrelated unbound-variable error before ever reaching pg_dump — that
  # would falsely "pass" this test without exercising the real failure mode.
  echo 'LOG_PREFIX="[test]"'
  echo 'base_url="postgresql://scratch-not-real/db"'
  # Pull every line from "ts=" through the "mv" line inclusive, plus any
  # trap line that appears anywhere above it in the real script (so the
  # driver exercises the exact fix, not a re-implementation of it).
  grep -E "trap[[:space:]]+.*rm[[:space:]]+-f.*tmp_file" "$BACKUP_SCRIPT" || true
  awk '/^ts="\$\(date -u/,/^mv "\$tmp_file" "\$dump_file"$/' "$BACKUP_SCRIPT"
} > "$DRIVER"
chmod +x "$DRIVER"

echo "--- extracted driver ($DRIVER) ---"
cat "$DRIVER"
echo "---"

# Run it; it is expected to fail (pg_dump exits 1) — that failure is the
# point of this test.
bash "$DRIVER" >/dev/null 2>"$TMP_DIR/driver.stderr" || true

echo "--- scratch BACKUP_DIR contents after the simulated mid-stream failure ---"
ls -la "$SCRATCH_BACKUP_DIR"
echo "---"

ORPHANS="$(find "$SCRATCH_BACKUP_DIR" -name '*.partial' 2>/dev/null || true)"
if [[ -z "$ORPHANS" ]]; then
  echo "PASS (b): no .partial orphan survived the simulated mid-stream pg_dump failure"
else
  echo "FAIL (b): .partial orphan(s) survived the simulated failure:"
  echo "$ORPHANS"
  FAILURES=$((FAILURES + 1))
fi

if [[ "$FAILURES" -gt 0 ]]; then
  echo "RESULT: FAIL ($FAILURES assertion(s) failed) — MF-4 no-partial-orphans contract not met"
  exit 1
fi
echo "RESULT: PASS"
exit 0
