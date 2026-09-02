#!/usr/bin/env bash
# Deploy production from a verified ref, smoke-test it, and roll back
# automatically if the smoke test fails.
#
#   deploy_env.sh prod [--rollback-on-failure] [<sha>]
#
# The persistent dev/test environments were retired on 2026-09-03; the full
# test suite runs in CI against an isolated CI database instead.
set -euo pipefail

ENV="${1:?usage: deploy_env.sh prod [--rollback-on-failure] [<sha>]}"
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
  prod) REPO=/root/prod/app;                    EXPORTS=/root/prod/env.export.sh
        UNITS="aether-prod-api aether-prod-web aether-prod-worker"; API=8000; WEB=3200 ;;
  *) echo "unknown environment '$ENV' (only 'prod' exists since 2026-09-03)" >&2; exit 2 ;;
esac

if [ ! -e "$REPO/.git" ]; then
  echo "[$ENV] checkout missing: $REPO" >&2
  exit 1
fi

# The self-hosted runner is not the directory owner. Git 2.35+ refuses
# "dubious ownership" (exit 128) unless safe.directory is set. Do not write
# git config — export it for this process AND children (pnpm/turbo spawn
# their own git).
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0="$REPO"
git() { command git -c "safe.directory=$REPO" "$@"; }

GUARD=/root/dev/aether-job-career-agent/scripts/integrity/runtime_env_guard.sh

# The environment guardian sweeps this same checkout on a 15-minute timer: it
# deletes build artefacts and stashes dirty worktrees. Without a shared lock it
# can do that in the middle of a `git reset --hard` / `pnpm build`, which is how
# a deploy ends up shipping a half-deleted .next. Both sides take this lock.
# The deploy WAITS for it (a deploy must never be silently skipped); the
# guardian does not (its next cycle is 15 minutes away and costs nothing).
LOCKDIR=/var/lib/aether-orchestrator/locks
mkdir -p "$LOCKDIR"
exec 9>"$LOCKDIR/$ENV.lock"
if ! flock -w 900 9; then
  echo "[$ENV] environment lock still held after 900s - refusing to deploy" >&2
  exit 1
fi

cd "$REPO"

# Self-hosted runner checkout ownership differs from the unit runtime user;
# mark this environment's tree safe for this process only (no global git config).
git config --local --add safe.directory "$REPO" >/dev/null 2>&1 || true

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
  # Untracked source files survive reset --hard and are typechecked by
  # `next build`. Ignored paths (.env, .venv, node_modules, .next) stay.
  git clean -fd -e .env
  echo "[$ENV] deploying $(git rev-parse --short HEAD): $(git log -1 --format=%s | cut -c1-60)"
  # .env is environment-local and untracked; it must survive every deploy.
  test -f .env || { echo "[$ENV] .env missing — refusing to deploy"; exit 1; }
  "$GUARD" "$REPO/.env"
  corepack prepare pnpm@11.9.0 --activate >/dev/null 2>&1
  pnpm install --frozen-lockfile
  ( set +u; . "$EXPORTS"; set -u; pnpm build )
  # shellcheck disable=SC2086
  systemctl restart $UNITS
  sleep 8
}

wait_for_smoke() {
  # Sentence-transformer weights load after uvicorn binds. Prod 2026-08-18T20:25Z
  # returned health=000 at 18s, then rollback hit the same race. Wait until
  # both API and web answer 200, bounded.
  local waited=0
  local delay=5
  local budget=90
  while [ "$waited" -lt "$budget" ]; do
    if smoke; then
      echo "[$ENV] smoke test PASSED after ${waited}s"
      return 0
    fi
    sleep "$delay"
    waited=$((waited + delay))
  done
  echo "[$ENV] smoke test FAILED after ${waited}s"
  return 1
}

build_and_restart "$PINNED_REF"

if wait_for_smoke; then
  echo "[$ENV] smoke test PASSED"
  exit 0
fi

echo "[$ENV] smoke test FAILED"
if [ "$ROLLBACK" = "--rollback-on-failure" ]; then
  echo "[$ENV] rolling back to $PREV"
  build_and_restart "$PREV"
  if wait_for_smoke; then
    echo "[$ENV] ROLLED BACK successfully to $PREV — production is serving the previous good commit"
    # The deploy failed; the pipeline must say so even though the rollback worked.
    exit 1
  fi
  echo "[$ENV] ROLLBACK ALSO FAILED — escalating"
  exit 1
fi
exit 1
