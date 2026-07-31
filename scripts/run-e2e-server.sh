#!/usr/bin/env bash
# Dedicated e2e web-server launcher for Playwright (apps/web/playwright.config.ts
# `webServer.command`). Closes the ROOT CAUSE of BUILD-RISK-001 (see
# docs/delivery/DEPLOYMENT-RUNBOOK.md §0.4/§0.5).
#
# THE HAZARD THIS REPLACES:
# the old `webServer.command` was:
#     pnpm run build && pnpm exec next start -p 3000
# which (a) ran a full `next build` DIRECTLY into `apps/web/.next` — the
# exact directory the live `aether-web.service` serves from, with no
# separate build output / worktree / staging copy on this VM — and
# (b) started on port 3000, the SAME port production listens on, so
# `reuseExistingServer: !CI` could silently attach Playwright's "chromium"
# project (and every LOGIN_EMAIL/LOGIN_PASSWORD-authenticated action it
# performs) to the RUNNING PRODUCTION SERVER instead of a throwaway one.
#
# THE FIX:
#   1. This script never runs `pnpm build`. It only verifies — via
#      scripts/verify-web-build.sh, called (not duplicated) — that a valid,
#      unpoisoned production build ALREADY exists in apps/web/.next before
#      doing anything else. That single call also re-uses the existing
#      AETHER_API_PROXY guard (verify-web-build.sh Check 0), so a polluted
#      shell can no longer bake a dead upstream into a build reachable from
#      an e2e run either. A caller must build first
#      (`pnpm --dir apps/web build`, from a clean shell) — this script
#      refuses to build on your behalf, which is the whole point: `next
#      start` never writes to `.next/`, so once this gate passes, nothing
#      this script does can ever overwrite the build aether-web.service
#      serves.
#   2. It starts `next start` on a DEDICATED e2e port (default 3100) that
#      is never 3000, and hard-refuses to start on 3000 under any
#      configuration, so `reuseExistingServer` can only ever reuse a
#      previous e2e run of this same script — never the live service.
#
# Usage (invoked by playwright.config.ts; can also be run standalone):
#   scripts/run-e2e-server.sh                  # port 3100
#   AETHER_E2E_PORT=3101 scripts/run-e2e-server.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_DIR="${REPO_DIR}/apps/web"

E2E_PORT="${AETHER_E2E_PORT:-3100}"

# Hard-refuse the production port under any configuration — this is the
# structural guarantee that makes `reuseExistingServer` safe outside CI.
if [[ "${E2E_PORT}" == "3000" ]]; then
    echo "[e2e-server] REFUSING to start on port 3000." >&2
    echo "[e2e-server] Port 3000 is the production aether-web.service port —" >&2
    echo "[e2e-server] Playwright must never be able to attach to it. Set" >&2
    echo "[e2e-server] AETHER_E2E_PORT to a non-production port instead." >&2
    exit 1
fi

echo "[e2e-server] verifying an existing, unpoisoned build exists in ${WEB_DIR}/.next"
echo "[e2e-server] (via scripts/verify-web-build.sh; this script does NOT build)..."
if ! "${SCRIPT_DIR}/verify-web-build.sh"; then
    echo "" >&2
    echo "==============================================================" >&2
    echo "[e2e-server] FAIL: no valid, unpoisoned production build found." >&2
    echo "==============================================================" >&2
    echo "This script deliberately never runs 'pnpm build' — doing so from" >&2
    echo "here would reproduce BUILD-RISK-001 (rebuilding directly into the" >&2
    echo "live apps/web/.next). Build first, from a clean shell:" >&2
    echo "    cd ${WEB_DIR}" >&2
    echo "    env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build" >&2
    echo "then re-run the e2e suite. See docs/delivery/DEPLOYMENT-RUNBOOK.md" >&2
    echo "\"Running the e2e suite\" for the full recipe." >&2
    exit 1
fi

echo "[e2e-server] build verified OK — starting 'next start' on 127.0.0.1:${E2E_PORT}"
echo "[e2e-server] (read-only against ${WEB_DIR}/.next; next start never writes to it)"
cd "${WEB_DIR}"
exec pnpm exec next start -p "${E2E_PORT}"
