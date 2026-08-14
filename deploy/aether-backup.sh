#!/usr/bin/env bash
# Aether production DB backup (O-2, S-FIX slice C).
#
# Context: docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md documents a
# SEV-1 total-data-loss event, and the incident record explicitly notes
# "No platform PITR requested". The guard added afterwards (conftest
# schema-pin + prod-DSN abort) only stops the ONE trigger that caused that
# incident (test-suite truncation) — it gives zero protection against a bad
# migration, a future deploy-script bug, or a DB-provider-side incident. This
# script is the actual backup/restore capability: a full logical dump of the
# `aether` schema every 6h (see aether-backup.timer), rotated locally and
# mirrored to durable object storage. RPO ~= 6h; see
# docs/delivery/DEPLOYMENT-RUNBOOK.md §10 for the restore recipe and honest
# posture notes (this is NOT provider-side PITR — it is scheduled logical
# backups, which is what is actually achievable from inside this VM).
#
# Safety:
#   * DATABASE_URL is read from the app's repo-root .env AT RUNTIME by
#     grepping the single variable — this script never `source`s the whole
#     .env (the exact mistake that caused the 2026-07-18 incident) and never
#     echoes/logs the credential value.
#   * The credential never reaches pg_dump's argv (MF-2, S-FIX slice C):
#     the DSN is parsed into PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE (the
#     libpq environment-variable convention pg_dump reads automatically) —
#     never passed as a connection-string argument, so it never appears in
#     `ps aux` / `/proc/<pid>/cmdline` output for the pg_dump process.
#   * pg_dump only ever reads (--schema=aether, no DDL/DML against prod);
#     nothing here can write to or truncate the production database.
#
# Usage: deploy/aether-backup.sh
# Logs:  stdout/stderr only (captured by systemd journal via
#        aether-backup.service; this script deliberately does not print any
#        part of the connection string).
set -euo pipefail

REPO_ROOT="/home/ubuntu/github_repos/aether-job-career-agent"
ENV_FILE="$REPO_ROOT/.env"
BACKUP_DIR="/home/ubuntu/aether-backups/db"
KEEP=14
LOG_PREFIX="[aether-backup]"

mkdir -p "$BACKUP_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "$LOG_PREFIX REFUSING TO RUN: $ENV_FILE not found." >&2
  exit 1
fi

# Resolve DATABASE_URL WITHOUT sourcing the whole .env (same discipline as
# scripts/run-tests.sh — see INCIDENT-PROD-DB-WIPE-2026-07-18.md).
raw_url="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | tail -1 | cut -d= -f2-)"
raw_url="${raw_url%\"}"; raw_url="${raw_url#\"}"
raw_url="${raw_url%\'}"; raw_url="${raw_url#\'}"
if [[ -z "$raw_url" ]]; then
  echo "$LOG_PREFIX REFUSING TO RUN: DATABASE_URL not set in $ENV_FILE." >&2
  exit 1
fi
# pg_dump/psql don't understand the `schema=` query param (it's a Prisma-ism
# — see INCIDENT-PROD-DB-WIPE-2026-07-18.md root cause #2); strip the query
# string and select the schema explicitly via --schema below instead.
base_url="${raw_url%%\?*}"

# Parse the DSN into PG* environment variables (MF-2, S-FIX slice C) so the
# credential is never handed to pg_dump as a connection-string ARGUMENT —
# only libpq client tools read PGPASSWORD from the environment; a value in
# argv is visible to any local user via `ps aux` / `/proc/<pid>/cmdline` for
# as long as the process runs. The DSN is passed to python3 via an exported
# env var (never argv) for the same reason.
export AETHER_BACKUP_DSN="$base_url"
pg_env="$(python3 - <<'PYEOF'
import os
from urllib.parse import urlparse, unquote

parsed = urlparse(os.environ["AETHER_BACKUP_DSN"])


def esc(value: str) -> str:
    return value.replace("'", "'\\''")


print(f"export PGHOST='{esc(parsed.hostname or '')}'")
print(f"export PGPORT='{esc(str(parsed.port or 5432))}'")
print(f"export PGUSER='{esc(unquote(parsed.username or ''))}'")
print(f"export PGPASSWORD='{esc(unquote(parsed.password or ''))}'")
print(f"export PGDATABASE='{esc(parsed.path.lstrip('/'))}'")
PYEOF
)"
unset AETHER_BACKUP_DSN
eval "$pg_env"
unset pg_env raw_url base_url

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dump_file="$BACKUP_DIR/aether-${ts}.sql.gz"
tmp_file="${dump_file}.partial"
# MF-4 (S-FIX slice C): a pg_dump|gzip pipeline that fails mid-stream aborts
# (set -euo pipefail) before the `mv` below ever runs, which would otherwise
# leave an orphaned ".partial" file that the rotation glob below (which only
# matches "aether-*.sql.gz") can never reclaim. Guarantee cleanup on any
# exit path (success leaves nothing to remove, since the file is renamed
# away before the trap fires).
trap 'rm -f -- "$tmp_file"' EXIT

echo "$LOG_PREFIX starting dump of schema=aether -> $dump_file"
pg_dump --schema=aether --no-owner --no-privileges --format=plain | gzip -9 > "$tmp_file"
mv "$tmp_file" "$dump_file"
echo "$LOG_PREFIX wrote $dump_file ($(du -h "$dump_file" | cut -f1))"

# Rotate local copies: keep only the newest $KEEP dumps.
mapfile -t old_dumps < <(ls -1t "$BACKUP_DIR"/aether-*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))")
for f in "${old_dumps[@]:-}"; do
  if [[ -n "$f" ]]; then
    rm -f -- "$f"
    echo "$LOG_PREFIX rotated out $f"
  fi
done

# Mirror to durable object storage (bucket/path from this VM's IMDSv2
# user-data at runtime — never hardcoded; AWS CLI auto-discovers credentials
# from the same metadata service).
#
# MF-5 (S-FIX slice C, round 2): the IMDS user-data document carries
# `abacus_api_key` and a hosted-DB `database_url`/`role_password` — the same
# argv-visibility hazard MF-2 fixed for the Postgres DSN, just with a larger
# payload. Feed it to python3 via an exported env var (never argv), same
# technique as AETHER_BACKUP_DSN above, and unset it immediately after.
token="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-abacus-vm-metadata-token-ttl-seconds: 300")"
AETHER_BACKUP_UD_JSON="$(curl -s -H "X-abacus-vm-metadata-token: $token" http://169.254.169.254/latest/user-data)"
export AETHER_BACKUP_UD_JSON
bucket="$(python3 -c "import os,json; print(json.loads(os.environ['AETHER_BACKUP_UD_JSON'])['storage']['bucket_name'])")"
base_path="$(python3 -c "import os,json; print(json.loads(os.environ['AETHER_BACKUP_UD_JSON'])['storage']['path'])")"
unset AETHER_BACKUP_UD_JSON token

if [[ -z "$bucket" || -z "$base_path" ]]; then
  echo "$LOG_PREFIX WARNING: could not resolve storage bucket/path from IMDS; local dump kept, S3 mirror skipped." >&2
  exit 1
fi

s3_dest="s3://${bucket}/${base_path}aether-db-backups/$(basename "$dump_file")"
aws s3 cp "$dump_file" "$s3_dest" --only-show-errors
echo "$LOG_PREFIX uploaded to $s3_dest"
