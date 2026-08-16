#!/bin/bash
# =============================================================================
# run-e2e-companion-stack.sh — isolated API+web pair for env-override e2e specs
# =============================================================================
# Eleven Playwright specs (ml-admin-002-mobile-overflow, ml-agents-refix,
# ml-fe-polish, wg-admin-login-path) were authored against an ISOLATED local
# API+web pair on the aether_test schema — they sign up throwaway users and
# POST real mutations, so they must NEVER hit the production API through the
# read-only :3100 e2e server (which proxies /api → prod :8000 / prod DB).
#
# This script provides that pair (MP-035, docs/delivery/ORCH-DELTA-2026-08-15b.md
# §10.1):
#   • uvicorn API on :8300 — DATABASE_URL swapped to DATABASE_URL_TEST
#     (aether_test schema), env mirroring apps/api/tests/conftest.py
#   • next start on :3110 — serving a build BAKED with
#     AETHER_API_PROXY=http://127.0.0.1:8300 into apps/web/.next-companion
#     (rewrites are baked into routes-manifest at BUILD time; setting the env
#     only at `next start` has no effect — DEPLOYMENT-RUNBOOK §0.5)
#
# Usage:  scripts/run-e2e-companion-stack.sh build|start|seed|stop|status
#   build  — produce the companion web build (only needed when src changes)
#   start  — start API :8300 + web :3110 (builds first if missing), health-check
#   seed   — create the fixture users the specs expect (idempotent)
#   stop   — tear both processes down
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT=8300
WEB_PORT=3110
DIST_DIR=".next-companion"
API_PID_FILE=/tmp/aether-e2e-companion-api.pid
WEB_PID_FILE=/tmp/aether-e2e-companion-web.pid
API_LOG=/tmp/aether-e2e-companion-api.log
WEB_LOG=/tmp/aether-e2e-companion-web.log
PY=/opt/abacus-python/bin/python3

# Fixture users (must match the specs' documented defaults — see
# wg-admin-login-path.spec.ts:38-40 and ml-admin-002-mobile-overflow.spec.ts:33-34).
# Test-schema-only fixture identities, not real credentials.
ADMIN_ML_EMAIL="ml-admin-002-local@example.com"
ADMIN_ML_PASSWORD="MlAdmin002Test1"
ADMIN_WG_EMAIL="wg-admin-68075c7601@example.com"
USER_WG_EMAIL="wg-user-519a113ab2@example.com"
WG_PASSWORD="WgE2eTest1"

# --- shared: load repo .env exactly like start-api.sh (first-'=' split, strip quotes)
load_env() {
  while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    export "$key"="$value"
  done < "$REPO_ROOT/.env"
}

# --- test-mode overrides mirroring apps/api/tests/conftest.py --------------
apply_test_overrides() {
  [ -n "${DATABASE_URL_TEST:-}" ] || { echo "FATAL: DATABASE_URL_TEST not set in .env" >&2; exit 1; }
  case "$DATABASE_URL_TEST" in
    *schema=*) : ;;
    *) echo "FATAL: DATABASE_URL_TEST has no ?schema= param — refusing (prod-truncation guard convention)" >&2; exit 1 ;;
  esac
  export DATABASE_URL="$DATABASE_URL_TEST"
  # AETHER_ENV=production + replay trips §REC-04 fail-fast in app.main — this
  # stack is a test harness, so mark it as such.
  export AETHER_ENV=test
  # Never seed/rotate the real owner admin in the test schema.
  unset AETHER_ADMIN_EMAIL AETHER_ADMIN_PASSWORD_HASH || true
  export AETHER_LLM_MODE=replay
  export AETHER_REQUIRE_PAID_SUBSCRIPTION=false
  export AETHER_ASYNC_GENERATION=false
  export AETHER_DISCOVERY_FIXTURE_DIR="$REPO_ROOT/apps/api/tests/fixtures/http"
  # Deterministic Fernet key — same published TEST key conftest.py falls back
  # to (apps/api/tests/conftest.py). Test-schema data only; not a credential.
  export AETHER_CREDENTIAL_KEY="htOwdaXn8QwZE8LSvZF1oCdgVBisuJnJHrgxBGvVrEU="
  export AETHER_MODEL_PRICE_CACHE_FILE=/tmp/aether-companion-price-cache.json
  # Keep the sales agent + email agent inert in the companion (no timers run
  # here anyway, but belt-and-braces).
  export AETHER_SALES_AGENT_ENABLED=false
}

port_busy() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }

cmd_build() {
  echo "[companion] building web with AETHER_API_PROXY=http://127.0.0.1:${API_PORT} → apps/web/${DIST_DIR}"
  ( cd "$REPO_ROOT" \
    && env -u NEXT_PUBLIC_API_BASE_URL \
         AETHER_API_PROXY="http://127.0.0.1:${API_PORT}" \
         AETHER_WEB_DIST_DIR="$DIST_DIR" \
         pnpm --dir apps/web build )
  echo "[companion] build done: $(cat "$REPO_ROOT/apps/web/$DIST_DIR/BUILD_ID")"
}

cmd_start() {
  if port_busy "$API_PORT" || port_busy "$WEB_PORT"; then
    echo "FATAL: port $API_PORT or $WEB_PORT already bound — run 'stop' first (never kill foreign processes)" >&2
    exit 1
  fi
  [ -f "$REPO_ROOT/apps/web/$DIST_DIR/BUILD_ID" ] || cmd_build

  load_env
  apply_test_overrides

  echo "[companion] starting API :$API_PORT (schema aether_test, replay mode)"
  pushd "$REPO_ROOT/apps/api" > /dev/null
  setsid "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" \
    < /dev/null >> "$API_LOG" 2>&1 &
  echo $! > "$API_PID_FILE"
  popd > /dev/null

  for _ in $(seq 1 30); do
    curl -fsS "http://127.0.0.1:${API_PORT}/health" > /dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS "http://127.0.0.1:${API_PORT}/health" > /dev/null \
    || { echo "FATAL: companion API failed health check — see $API_LOG" >&2; exit 1; }

  echo "[companion] starting web :$WEB_PORT (dist $DIST_DIR)"
  pushd "$REPO_ROOT/apps/web" > /dev/null
  setsid env AETHER_WEB_DIST_DIR="$DIST_DIR" \
    ./node_modules/.bin/next start -p "$WEB_PORT" \
    < /dev/null >> "$WEB_LOG" 2>&1 &
  echo $! > "$WEB_PID_FILE"
  popd > /dev/null

  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "http://127.0.0.1:${WEB_PORT}/pricing" 2>/dev/null && break
    sleep 1
  done
  curl -fsS -o /dev/null "http://127.0.0.1:${WEB_PORT}/pricing" \
    || { echo "FATAL: companion web failed health check — see $WEB_LOG" >&2; exit 1; }
  echo "[companion] up: API http://127.0.0.1:${API_PORT}  web http://127.0.0.1:${WEB_PORT}"
}

register_user() { # email password
  local code
  code=$(curl -s -o /tmp/aether-companion-register.out -w '%{http_code}' \
    -X POST "http://127.0.0.1:${API_PORT}/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\",\"name\":\"E2E Fixture\"}")
  case "$code" in
    201) echo "[companion] registered $1" ;;
    400|409) echo "[companion] $1 already exists (HTTP $code) — ok, idempotent" ;;
    *) echo "FATAL: register $1 → HTTP $code: $(cat /tmp/aether-companion-register.out)" >&2; exit 1 ;;
  esac
}

cmd_seed() {
  load_env
  [ -n "${DATABASE_URL_TEST:-}" ] || { echo "FATAL: DATABASE_URL_TEST not set" >&2; exit 1; }
  register_user "$ADMIN_ML_EMAIL" "$ADMIN_ML_PASSWORD"
  register_user "$ADMIN_WG_EMAIL" "$WG_PASSWORD"
  register_user "$USER_WG_EMAIL" "$WG_PASSWORD"
  # Promote the two admin fixtures — direct SQL in the aether_test schema only
  # (the register endpoint rightly has no way to mint admins).
  "$PY" - "$ADMIN_ML_EMAIL" "$ADMIN_WG_EMAIL" <<'PYEOF'
import os, sys
import psycopg2
url = os.environ["DATABASE_URL_TEST"]
assert "schema=" in url, "refusing: DATABASE_URL_TEST has no ?schema= param"
base, _, query = url.partition("?")
schema = [p.split("=", 1)[1] for p in query.split("&") if p.startswith("schema=")][0]
conn = psycopg2.connect(base)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(f'SET search_path TO "{schema}"')
    for email in sys.argv[1:]:
        cur.execute('UPDATE "User" SET "isAdmin" = true WHERE email = %s', (email,))
        print(f"[companion] promoted {email}: {cur.rowcount} row(s)")
        assert cur.rowcount == 1, f"expected exactly 1 row for {email}"
conn.close()
PYEOF
  echo "[companion] seed complete"
}

stop_one() { # pidfile label
  if [ -f "$1" ]; then
    local pid; pid=$(cat "$1")
    if kill -0 "$pid" 2>/dev/null; then
      kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      echo "[companion] stopped $2 (pid $pid)"
    fi
    rm -f "$1"
  fi
}

cmd_stop() {
  stop_one "$WEB_PID_FILE" web
  stop_one "$API_PID_FILE" api
  sleep 1
  port_busy "$API_PORT" && echo "WARN: :$API_PORT still bound" >&2 || true
  port_busy "$WEB_PORT" && echo "WARN: :$WEB_PORT still bound" >&2 || true
}

cmd_status() {
  for p in "$API_PORT" "$WEB_PORT"; do
    if port_busy "$p"; then echo ":$p LISTEN"; else echo ":$p free"; fi
  done
}

case "${1:-}" in
  build)  cmd_build ;;
  start)  cmd_start ;;
  seed)   cmd_seed ;;
  stop)   cmd_stop ;;
  status) cmd_status ;;
  *) echo "usage: $0 build|start|seed|stop|status" >&2; exit 2 ;;
esac
