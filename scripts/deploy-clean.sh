#!/usr/bin/env bash
#
# deploy-clean.sh — clean rebuild + redeploy for the Aether production host.
#
# QA-2026-08-13 root cause for C-01/C-02/C-04/C-05/C-09/H-06/H-09: production
# was serving PRERENDERED HTML FROM AN OLD NEXT.JS BUILD. /dashboard/applications
# returned HTML referencing buildId zxfjB5xmQ2rLtJyu5ucRK whose JS chunk
# (page-8c44bf636b237c2c.js) 404s, while other pages served buildId
# 8W33u_S2TNVgzcoxG-aW8 — a half-updated .next directory plus
# `x-nextjs-cache: HIT` / `s-maxage=31536000` kept the broken HTML pinned.
# The only durable fix is a CLEAN rebuild (rm -rf .next) followed by a restart
# of every service, then verifying that the HTML each page serves references
# chunks that actually exist.
#
# Run ON THE PRODUCTION HOST as the deploy user:
#   sudo bash scripts/deploy-clean.sh
#
set -euo pipefail

REPO_DIR="${AETHER_REPO_DIR:-/home/ubuntu/github_repos/aether-job-career-agent}"
BASE_URL="${AETHER_BASE_URL:-https://5cb5f0620.abacusai.cloud}"
SERVICES=(aether-api aether-web aether-worker)

log() { printf '\n[deploy-clean] %s\n' "$*"; }

cd "$REPO_DIR"

log "1/7 Pulling latest main..."
git fetch origin && git rev-parse --abbrev-ref HEAD

log "2/7 Stopping web service (api/worker keep serving)..."
systemctl stop aether-web || true

log "3/7 Removing stale build output (.next) — THE stale-build fix..."
rm -rf apps/web/.next

log "4/7 Installing deps + building web (clean)..."
corepack enable >/dev/null 2>&1 || true
pnpm install --frozen-lockfile
(cd apps/web && pnpm build)

if [[ ! -f apps/web/.next/BUILD_ID ]]; then
  echo "FATAL: apps/web/.next/BUILD_ID missing — build did not complete. Aborting before restart." >&2
  exit 1
fi
log "Built BUILD_ID: $(cat apps/web/.next/BUILD_ID)"

log "5/7 Restarting services: ${SERVICES[*]}"
for svc in "${SERVICES[@]}"; do
  systemctl restart "$svc"
done
sleep 5
for svc in "${SERVICES[@]}"; do
  systemctl is-active --quiet "$svc" || { echo "FATAL: $svc failed to start"; journalctl -u "$svc" -n 50 --no-pager; exit 1; }
done

log "6/7 API health check..."
curl -fsS -m 20 "$BASE_URL/api/health" | head -c 400; echo

log "7/7 Stale-build verification: every dashboard page must reference JS chunks that return 200..."
BUILD_ID="$(cat apps/web/.next/BUILD_ID)"
FAIL=0
for path in /dashboard /dashboard/applications /dashboard/stories /dashboard/interviews /dashboard/agents /dashboard/analytics /dashboard/settings /admin /admin/health; do
  html="$(curl -fsS -m 30 "$BASE_URL$path" || true)"
  if [[ -z "$html" ]]; then echo "  FAIL $path: empty response"; FAIL=1; continue; fi
  if ! grep -q "$BUILD_ID" <<<"$html"; then
    echo "  FAIL $path: served HTML does not reference current BUILD_ID $BUILD_ID (stale cache?)"; FAIL=1; continue
  fi
  # Verify a sample of referenced chunks resolve (the QA blank-page signature
  # was a referenced page chunk returning 404).
  chunks="$(grep -o '/_next/static/[^"]*\.js' <<<"$html" | sort -u | head -5)"
  for c in $chunks; do
    code="$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$BASE_URL$c")"
    if [[ "$code" != "200" ]]; then echo "  FAIL $path: chunk $c → HTTP $code"; FAIL=1; fi
  done
  echo "  OK   $path"
done

if [[ "$FAIL" == "1" ]]; then
  echo "Stale-build verification FAILED — check CDN/proxy cache (x-nextjs-cache) and purge if needed." >&2
  exit 1
fi
log "Deploy complete and verified."
