#!/bin/bash
# =============================================================================
# run-e2e-full.sh — the ONE command that runs the complete 82-test e2e suite
# =============================================================================
# Orchestrates both server tiers the suite needs:
#   1. The main read-only web server on :3100 — started by Playwright itself
#      (playwright.config.ts webServer → scripts/run-e2e-server.sh), serving
#      the ALREADY-BUILT apps/web/.next (build first; this never builds).
#   2. The isolated companion API+web pair (:8300/:3110, aether_test schema)
#      that the env-override specs (ml-*, wg-*) mutate freely — see
#      scripts/run-e2e-companion-stack.sh (MP-035).
#
# Usage (from the repo root, or a detached e2e worktree at the same sha):
#   scripts/run-e2e-full.sh [extra playwright args...]
#
# Prereqs: apps/web/.next built at the sha under test
#   (env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm --dir apps/web build)
#   and repo .env providing LOGIN_EMAIL/LOGIN_PASSWORD + DATABASE_URL_TEST.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPANION="${SCRIPT_DIR}/run-e2e-companion-stack.sh"

cleanup() { "$COMPANION" stop || true; }
trap cleanup EXIT

"$COMPANION" start
"$COMPANION" seed

cd "${REPO_ROOT}/apps/web"
# The fixture identities below are the specs' own documented defaults
# (test-schema throwaway users, not credentials) — exported explicitly so a
# polluted shell can never repoint these specs at another host.
env \
  E2E_BASE_URL="http://127.0.0.1:3110" \
  E2E_ADMIN_EMAIL="ml-admin-002-local@example.com" \
  E2E_ADMIN_PASSWORD="MlAdmin002Test1" \
  WG_E2E_BASE_URL="http://127.0.0.1:3110" \
  WG_E2E_ADMIN_EMAIL="wg-admin-68075c7601@example.com" \
  WG_E2E_USER_EMAIL="wg-user-519a113ab2@example.com" \
  WG_E2E_PASSWORD="WgE2eTest1" \
  ./node_modules/.bin/playwright test "$@"
