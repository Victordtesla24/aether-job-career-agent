#!/usr/bin/env bash
# Deploy an environment from origin/main, smoke-test it, and (for production)
# roll back automatically if the smoke test fails.
#
#   deploy_env.sh <dev|test|prod> [--rollback-on-failure]
set -euo pipefail

ENV="${1:?usage: deploy_env.sh <dev|test|prod> [--rollback-on-failure]}"
ROLLBACK=""
PINNED_REF="origin/main"
for arg in "${@:2}"; do
  case "$arg" in
    --rollback-on-failure) ROLLBACK="--rollback-on-failure" ;;
    "" ) ;;
    * ) PINNED_REF="$arg" ;;     # a commit SHA from CI: deploy exactly what was verified
  esac
done

case "$ENV" in
  dev)  REPO=/root/dev/aether-job-career-agent; EXPORTS=/root/dev/.agent/staging/env.export.sh
        UNITS="aether-dev-api aether-dev-web";   API=8100; WEB=3100 ;;
  test) REPO=/root/test/app;                    EXPORTS=/root/test/env.export.sh
        UNITS="aether-test-api aether-test-web"; API=8300; WEB=3300 ;;
  prod) REPO=/root/prod/app;                    EXPORTS=/root/prod/env.export.sh
        UNITS="aether-prod-api aether-prod-web aether-prod-worker"; API=8000; WEB=3200 ;;
  *) echo "unknown environment '$ENV'" >&2; exit 2 ;;
esac

GUARD=/root/dev/aether-job-career-agent/scripts/integrity/runtime_env_guard.sh
cd "$REPO"

PREV=$(git rev-parse HEAD)
echo "[$ENV] current commit: $PREV ; deploying ref: $PINNED_REF"

smoke() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://127.0.0.1:$API/health") || code=000
  [ "$code" = "200" ] || { echo "[$ENV] API health = $code"; return 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "http://127.0.0.1:$WEB/") || code=000
  [ "$code" = "200" ] || { echo "[$ENV] web = $code"; return 1; }
  return 0
}

build_and_restart() {
  git fetch --all --prune -q
  git reset --hard -q "${1:-origin/main}"
  echo "[$ENV] deploying $(git rev-parse --short HEAD): $(git log -1 --format=%s | cut -c1-60)"
  # .env is environment-local and untracked; it must survive every deploy.
  test -f .env || { echo "[$ENV] .env missing — refusing to deploy"; exit 1; }
  "$GUARD" "$REPO/.env"
  corepack prepare pnpm@11.9.0 --activate >/dev/null 2>&1
  pnpm install --frozen-lockfile
  ( set +u; . "$EXPORTS"; set -u; pnpm build )
  # shellcheck disable=SC2086
  systemctl restart $UNITS
  sleep 18
}

build_and_restart "$PINNED_REF"

if smoke; then
  echo "[$ENV] smoke test PASSED"
  exit 0
fi

echo "[$ENV] smoke test FAILED"
if [ "$ROLLBACK" = "--rollback-on-failure" ]; then
  echo "[$ENV] rolling back to $PREV"
  build_and_restart "$PREV"
  if smoke; then
    echo "[$ENV] ROLLED BACK successfully to $PREV — production is serving the previous good commit"
    # The deploy failed; the pipeline must say so even though the rollback worked.
    exit 1
  fi
  echo "[$ENV] ROLLBACK ALSO FAILED — escalating"
  exit 1
fi
exit 1
