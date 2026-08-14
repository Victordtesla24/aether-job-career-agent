#!/usr/bin/env bash
# Aether pull-based auto-deploy.
#
# Runs on a 5-minute timer (aether-autodeploy.timer). Polls origin/main; if
# this checkout is already at the tip, it's a silent no-op (exit 0). If
# origin/main moved, it runs the EXACT manual recipe from
# docs/delivery/DEPLOYMENT-RUNBOOK.md §5 ("Complete Deploy Recipe" +
# "Pre-Deployment Checks") under the same /tmp/aether-deploy.lock every
# other deploy actor on this VM uses.
#
# Safety contract: NEVER stash/reset/clean/force anything. On any failure —
# including a blocked pull or a health check that never comes healthy within
# its deadline — log loudly to /var/log/aether/deploy.log and exit non-zero.
# No retry loop ACROSS TICKS: the next timer tick is the only retry, and
# (see runbook §5.1) it only re-attempts once origin/main advances again,
# since HEAD already moved past the failure point on a mid-recipe failure.
# Operators must watch the log. (The 3 health checks below DO poll with a
# bounded retry+deadline WITHIN a single tick — see wait_healthy — because a
# real service takes longer to warm up than any single fixed-delay guess;
# that in-tick polling is not the "no retry" this paragraph refers to.)
#
# Benign lock contention (another deploy actor already holds the lock) is
# NOT a failure — it is expected on a VM where manual/agent deploys share
# this same lock file — so it logs an INFO line and exits 0, not FAILURE.
set -euo pipefail

REPO_DIR="/home/ubuntu/github_repos/aether-job-career-agent"
API_DIR="$REPO_DIR/apps/api"
WEB_DIR="$REPO_DIR/apps/web"
ENV_FILE="$REPO_DIR/.env"
LOG_FILE="/var/log/aether/deploy.log"
LOCK_FILE="/tmp/aether-deploy.lock"
NGINX_HOST="5cb5f0620.vm.internal"
# deploy/5cb5f0620.conf sets `proxy_set_header Host $http_x_original_host;` on
# BOTH the / and /api/ locations — nginx does not restore the original public
# Host itself, it relies on this header. Without it, Next.js (location /)
# receives an empty Host and answers 400; the nginx-fronted health checks
# below must send it to reach the app the same way real traffic does.
NGINX_ORIGINAL_HOST="5cb5f0620.abacusai.cloud"

# Untracked files a live concurrent agent may legitimately leave in this
# shared production checkout without it being a hazard to pull over (see
# FOREIGN-WIP-MOVED.md). Any OTHER untracked or modified file aborts the
# deploy loudly rather than pulling over it.
KNOWN_FOREIGN_UNTRACKED=(
    "FOREIGN-WIP-MOVED.md"
    "apps/api/tests/fixtures/llm/cover_letter/quality.json"
    "apps/api/tests/fixtures/llm/cover_letter/retry3.json"
    "apps/api/tests/test_blocker010_board_sweep_abort_recovery.py"
)

log() { printf '%s [auto-deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG_FILE"; }
fail() { log "FAILURE: $1"; exit 1; }

# --- health-check retry/deadline poll ---------------------------------------
# The first real deploy (canary d4287c1, 2026-08-13) proved a fixed `sleep 5`
# followed by a single one-shot `curl -sf` races real service startup: the
# API answered 200 in 2ms just 13s later, but the one-shot check had already
# logged a false FAILURE 5s after restart, leaving the systemd unit in
# 'failed' state after a deploy that actually succeeded (see
# uat/reports/evidence/market-perf/u-cd/04-DEFECT-healthcheck-race-realdeploy.txt).
# wait_healthy polls every HEALTH_POLL_INTERVAL seconds until the given
# command succeeds (HTTP 200 for these curl checks) or HEALTH_POLL_DEADLINE
# seconds have elapsed since the first attempt. It is generous on purpose:
# aether-api alone can take up to ~90s to stop and restart under load, and
# warmup adds more on top of that. Only deadline exhaustion is a FAILURE;
# every attempt in between is silent, and success logs the attempt count and
# elapsed time so operators can see how close to the deadline a real deploy
# is running.
HEALTH_POLL_INTERVAL=3
HEALTH_POLL_DEADLINE=90

wait_healthy() {
    # $1 = human-readable label for log lines; "$@" (after shift) = the
    # command to retry, e.g. `curl -sf ... url`.
    local label="$1"
    shift
    local start_ts elapsed attempt=0
    start_ts=$(date +%s)
    while true; do
        attempt=$((attempt + 1))
        if "$@" >/dev/null 2>&1; then
            elapsed=$(( $(date +%s) - start_ts ))
            log "$label: healthy after ${elapsed}s (attempt $attempt)"
            return 0
        fi
        elapsed=$(( $(date +%s) - start_ts ))
        if [ "$elapsed" -ge "$HEALTH_POLL_DEADLINE" ]; then
            fail "$label: still failing after ${elapsed}s / $attempt attempts (${HEALTH_POLL_DEADLINE}s deadline exceeded)"
        fi
        sleep "$HEALTH_POLL_INTERVAL"
    done
}

cd "$REPO_DIR"

# --- Step 0: branch guard ---------------------------------------------------
# The production checkout is shared with manual/agent deploy actors. If one
# of them ever leaves it on a branch other than main (documented shared-tree
# hazard — see aether-shared-tree-git-hazard notes), `git pull --ff-only
# origin main` below would silently fast-forward THAT branch's ref to
# origin/main and deploy from it. Refuse loudly instead.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
    fail "checkout is on branch '$CURRENT_BRANCH', not 'main' — refusing to deploy from a non-main checkout (shared-tree hazard); resolve manually"
fi

# --- Step 1: anything to do? (cheap check, no lock needed yet) -------------
git fetch origin main --quiet || fail "git fetch origin main failed"
if [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ]; then
    exit 0   # already up to date — nothing to deploy
fi

# --- Step 2: serialize with every other deploy actor on this VM ------------
exec 200>"$LOCK_FILE" || fail "cannot open lock file $LOCK_FILE"
if ! flock -n 200; then
    # Routine, not exceptional: every manual/agent deploy on this VM takes
    # this same lock. Do NOT treat this as a FAILURE — that trains operators
    # to ignore real failures. The next timer tick (5 min) is the retry.
    log "INFO: lock held by another deploy actor — skipping this tick (benign contention)"
    exit 0
fi

# --- Step 3: re-read HEADs now that we hold the lock (fixes a TOCTOU) ------
# Steps 0-1 ran before the lock was acquired. If a manual deploy took the
# lock, pulled, and released it in that window, HEAD has already moved to
# what we think of as REMOTE_HEAD — re-check under the lock so this tick is
# actually idempotent (a silent no-op) rather than merely serialized (which
# would still stop/restart all three services for nothing).
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse origin/main)
if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    exit 0   # someone else already deployed this exact commit while we waited
fi

# --- Step 4: foreign-WIP preservation-protocol check ------------------------
# A shared production checkout can carry another live agent's uncommitted
# work (see FOREIGN-WIP-MOVED.md precedent). This script NEVER moves or
# discards it automatically — it refuses loudly and leaves everything
# exactly as found for a human/orchestrator to resolve. Covers BOTH tracked
# modifications and untracked files (an untracked file outside the
# documented known-foreign set is just as much a hazard: `git pull
# --ff-only` can fail or, worse, silently interleave with it).
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    fail "foreign WIP detected in $REPO_DIR (uncommitted tracked-file changes) — refusing to pull; resolve per FOREIGN-WIP-MOVED.md precedent, then retry"
fi

UNEXPECTED_UNTRACKED=""
while IFS= read -r f; do
    [ -z "$f" ] && continue
    is_known=0
    for known in "${KNOWN_FOREIGN_UNTRACKED[@]}"; do
        if [ "$f" = "$known" ]; then
            is_known=1
            break
        fi
    done
    if [ "$is_known" -eq 0 ]; then
        UNEXPECTED_UNTRACKED="${UNEXPECTED_UNTRACKED}${f}, "
    fi
done < <(git status --porcelain --untracked-files=all | awk '/^\?\? /{print substr($0, 4)}')

if [ -n "$UNEXPECTED_UNTRACKED" ]; then
    fail "unexpected untracked file(s) in $REPO_DIR outside the documented known-foreign set (${KNOWN_FOREIGN_UNTRACKED[*]}): ${UNEXPECTED_UNTRACKED%, } — refusing to pull; resolve per FOREIGN-WIP-MOVED.md precedent, then retry"
fi

# --- Step 5: pre-deployment checks (runbook §5) -----------------------------
# AETHER_LLM_MODE must never be replay/record in production (MV-application-
# tracker-001 BLOCKER: replay/record serve or persist fixture-derived
# content with no signal to the end user that it isn't a live generation —
# see runbook §5 check 4 for the full incident writeup). An unattended
# 5-minute-cadence deploy removes the human who otherwise runs this check
# manually, so it must be enforced here.
grep -qE '^AETHER_LLM_MODE=(auto|live)$' "$ENV_FILE" \
    || fail "AETHER_LLM_MODE in $ENV_FILE is not 'auto' or 'live' (or the file/line is missing) — refusing to deploy (MV-application-tracker-001 guard, runbook §5 check 4)"

log "deploying $LOCAL_HEAD -> $REMOTE_HEAD"

# --- Step 6: pull. --ff-only so a diverged/rewritten history (which the
#     dirty-tree check above cannot catch) also refuses loudly instead of
#     merging or rebasing. ------------------------------------------------
git pull --ff-only origin main || fail "git pull --ff-only failed (diverged history?) — no local state was changed"
NEW_HEAD=$(git rev-parse HEAD)
CHANGED=$(git diff --name-only "$LOCAL_HEAD" "$NEW_HEAD")

# --- Step 7: Python deps, only if requirements.txt changed ---------------
if grep -q '^apps/api/requirements\.txt$' <<<"$CHANGED"; then
    log "apps/api/requirements.txt changed — pip install"
    (cd "$API_DIR" && pip install -r requirements.txt) || fail "pip install -r requirements.txt failed"
fi

# --- Step 8: web build, only if apps/web changed (runbook §5 Phase 2+3) --
if grep -q '^apps/web/' <<<"$CHANGED"; then
    log "apps/web changed — installing web deps and building"
    (cd "$REPO_DIR" && pnpm install --frozen-lockfile) || fail "pnpm install --frozen-lockfile failed"
    (cd "$WEB_DIR" && env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build) || fail "pnpm build failed"
fi

# --- Step 9: web build gate — MANDATORY on EVERY deploy that restarts
#     aether-web (runbook §0.4 / §5 Phase 3b), not only when apps/web
#     changed: it validates the CURRENT on-disk build's baked-in /api/*
#     rewrite upstream, which a restart serves regardless of what this
#     particular commit touched. ------------------------------------------
"$REPO_DIR/scripts/verify-web-build.sh" || fail "web build pre-flight gate FAILED (§0.4) — refusing to restart aether-web"

# --- Step 10: restart services (API, Web, Worker) --------------------------
sudo systemctl stop aether-api.service aether-web.service aether-worker.service || fail "service stop failed"
sleep 2
sudo systemctl start aether-api.service aether-web.service aether-worker.service || fail "service start failed"
for svc in aether-api aether-web aether-worker; do
    systemctl is-active --quiet "$svc.service" || fail "$svc.service is not active after restart"
done

# --- Step 11: the 3 exact health checks (runbook §5 Phase 5, items 3/3b/4) -
# Each check polls with a retry+deadline (see wait_healthy above) instead of
# a single fixed-delay attempt — real service warmup time varies and a
# one-shot check raced it on the first real deploy (see the defect writeup
# referenced above wait_healthy's definition).
# The two nginx-fronted checks must send X-Original-Host: nginx proxies the
# real upstream Host from that header, not from the Host this curl sends
# (see NGINX_ORIGINAL_HOST comment above) — omitting it makes Next.js see an
# empty Host and return 400 on every real deploy (round-3 review blocker).
wait_healthy "health check 1/3 (GET /api/health via nginx)" \
    curl -sf -H "Host: $NGINX_HOST" -H "X-Original-Host: $NGINX_ORIGINAL_HOST" http://localhost/api/health
wait_healthy "health check 2/3 (GET 127.0.0.1:3000/api/health, next /api rewrite, §0.4)" \
    curl -sf --max-time 10 http://127.0.0.1:3000/api/health
wait_healthy "health check 3/3 (GET / via nginx)" \
    curl -sf -H "Host: $NGINX_HOST" -H "X-Original-Host: $NGINX_ORIGINAL_HOST" http://localhost/

log "deploy successful: $NEW_HEAD"
exit 0
