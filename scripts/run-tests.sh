#!/usr/bin/env bash
# Safe entrypoint for the backend pytest suite (MV-system-003).
#
# INCIDENT (2026-07-18, docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md):
# a deploy step ran `source ../../.env && pytest`, which put the PRODUCTION
# DATABASE_URL (schema=aether) into the pytest process environment. The
# suite's table-truncation fixture then wiped the production database.
#
# This script is the ONLY sanctioned way to run the backend test suite:
#   * It reads DATABASE_URL_TEST from the repo-root .env (or an already
#     exported DATABASE_URL_TEST) and exports it as BOTH DATABASE_URL and
#     DATABASE_URL_TEST for the pytest child process.
#   * It REFUSES to run at all (exit 1) if the resolved DSN's `schema=`
#     query param is not literally `aether_test` — this catches the exact
#     misconfiguration that caused the incident before pytest even starts,
#     independent of the in-process guard in apps/api/tests/conftest.py
#     (belt and suspenders — either layer alone stops the wipe).
#   * It NEVER sources the repo-root .env wholesale into the environment,
#     so a production DATABASE_URL in .env can never leak into the test
#     process via this script.
#
# Usage:
#   scripts/run-tests.sh [pytest args...]
#
# Examples:
#   scripts/run-tests.sh                          # run the whole suite
#   scripts/run-tests.sh tests/test_auth.py -q    # run one file
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
API_DIR="$REPO_ROOT/apps/api"
ENV_FILE="$REPO_ROOT/.env"

# Resolve DATABASE_URL_TEST WITHOUT sourcing the whole .env file (which would
# also export the production DATABASE_URL into this shell).
resolved_test_url="${DATABASE_URL_TEST:-}"
if [[ -z "$resolved_test_url" && -f "$ENV_FILE" ]]; then
  resolved_test_url="$(grep -E '^DATABASE_URL_TEST=' "$ENV_FILE" | tail -1 | cut -d= -f2- || true)"
  # Strip surrounding quotes, same convention as the other .env parsers in
  # this repo (start-api.sh / conftest.py's _load_root_env).
  resolved_test_url="${resolved_test_url%\"}"; resolved_test_url="${resolved_test_url#\"}"
  resolved_test_url="${resolved_test_url%\'}"; resolved_test_url="${resolved_test_url#\'}"
fi

if [[ -z "$resolved_test_url" ]]; then
  echo "REFUSING TO RUN: DATABASE_URL_TEST is not set (checked env and $ENV_FILE)." >&2
  echo "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md." >&2
  exit 1
fi

case "$resolved_test_url" in
  *"schema=aether_test"*) ;;
  *)
    echo "REFUSING TO RUN: DATABASE_URL_TEST does not carry '?schema=aether_test'." >&2
    echo "Resolved DSN's schema param must be exactly 'aether_test' — refusing" >&2
    echo "to risk running the destructive test suite against any other schema." >&2
    echo "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md." >&2
    exit 1
    ;;
esac

echo "[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed."

export DATABASE_URL="$resolved_test_url"
export DATABASE_URL_TEST="$resolved_test_url"

cd "$API_DIR"
exec python3 -m pytest "$@"
