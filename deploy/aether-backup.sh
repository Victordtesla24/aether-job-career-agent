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

ts="$(date -u +%Y%m%dT%H%M%SZ)"
dump_file="$BACKUP_DIR/aether-${ts}.sql.gz"
tmp_file="${dump_file}.partial"

echo "$LOG_PREFIX starting dump of schema=aether -> $dump_file"
pg_dump --schema=aether --no-owner --no-privileges --format=plain "$base_url" | gzip -9 > "$tmp_file"
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
token="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-abacus-vm-metadata-token-ttl-seconds: 300")"
user_data="$(curl -s -H "X-abacus-vm-metadata-token: $token" http://169.254.169.254/latest/user-data)"
bucket="$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['storage']['bucket_name'])" "$user_data")"
base_path="$(python3 -c "import sys,json; print(json.loads(sys.argv[1])['storage']['path'])" "$user_data")"

if [[ -z "$bucket" || -z "$base_path" ]]; then
  echo "$LOG_PREFIX WARNING: could not resolve storage bucket/path from IMDS; local dump kept, S3 mirror skipped." >&2
  exit 1
fi

s3_dest="s3://${bucket}/${base_path}aether-db-backups/$(basename "$dump_file")"
aws s3 cp "$dump_file" "$s3_dest" --only-show-errors
echo "$LOG_PREFIX uploaded to $s3_dest"
