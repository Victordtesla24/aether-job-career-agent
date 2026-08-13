#!/usr/bin/env bash
# Aether pull-based auto-deploy.
#
# Runs on a 5-minute timer (aether-autodeploy.timer). Polls origin/main; if
# this checkout is already at the tip, it's a silent no-op (exit 0). If
# origin/main moved, it runs the EXACT manual recipe from
# docs/delivery/DEPLOYMENT-RUNBOOK.md §5 ("Complete Deploy Recipe") under
# the same /tmp/aether-deploy.lock every other deploy actor on this VM uses.
#
# Safety contract: NEVER stash/reset/clean/force anything. On any failure —
# including a blocked pull or a failed health check — log loudly to
# /var/log/aether/deploy.log and exit non-zero. No retry loop here: the next
# timer tick is the only retry, and (see runbook "Auto-deploy" section) it
# only re-attempts once origin/main advances again, since HEAD already moved
# past the failure point on a mid-recipe failure. Operators must watch the
# log.
set -euo pipefail

REPO_DIR="/home/ubuntu/github_repos/aether-job-career-agent"
API_DIR="$REPO_DIR/apps/api"
WEB_DIR="$REPO_DIR/apps/web"
LOG_FILE="/var/log/aether/deploy.log"
LOCK_FILE="/tmp/aether-deploy.lock"
NGINX_HOST="5cb5f0620.vm.internal"

log() { printf '%s [auto-deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$LOG_FILE"; }
fail() { log "FAILURE: $1"; exit 1; }

cd "$REPO_DIR"

# --- Step 0: anything to do? (cheap check, no lock needed yet) ----------
git fetch origin main --quiet || fail "git fetch origin main failed"
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse origin/main)
if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    exit 0   # already up to date — nothing to deploy
fi

# --- Step 1: serialize with every other deploy actor on this VM ---------
exec 200>"$LOCK_FILE" || fail "cannot open lock file $LOCK_FILE"
flock -n 200 || fail "another deploy holds $LOCK_FILE — skipping this tick, will retry next tick"

# --- Step 2: foreign-WIP preservation-protocol check ---------------------
# A shared production checkout can carry another live agent's uncommitted
# work (see FOREIGN-WIP-MOVED.md precedent). This script NEVER moves or
# discards it automatically — it refuses loudly and leaves everything
# exactly as found for a human/orchestrator to resolve.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    fail "foreign WIP detected in $REPO_DIR (uncommitted tracked-file changes) — refusing to pull; resolve per FOREIGN-WIP-MOVED.md precedent, then retry"
fi

log "deploying $LOCAL_HEAD -> $REMOTE_HEAD"

# --- Step 3: pull. --ff-only so a diverged/rewritten history (which the
#     dirty-tree check above cannot catch) also refuses loudly instead of
#     merging or rebasing. ------------------------------------------------
git pull --ff-only origin main || fail "git pull --ff-only failed (diverged history?) — no local state was changed"
NEW_HEAD=$(git rev-parse HEAD)
CHANGED=$(git diff --name-only "$LOCAL_HEAD" "$NEW_HEAD")

# --- Step 4: Python deps, only if requirements.txt changed ---------------
if echo "$CHANGED" | grep -q '^apps/api/requirements\.txt$'; then
    log "apps/api/requirements.txt changed — pip install"
    (cd "$API_DIR" && pip install -r requirements.txt) || fail "pip install -r requirements.txt failed"
fi

# --- Step 5: web build, only if apps/web changed (runbook §5 Phase 2+3) --
if echo "$CHANGED" | grep -q '^apps/web/'; then
    log "apps/web changed — installing web deps and building"
    (cd "$REPO_DIR" && pnpm install --frozen-lockfile) || fail "pnpm install --frozen-lockfile failed"
    (cd "$WEB_DIR" && env -u AETHER_API_PROXY -u NEXT_PUBLIC_API_BASE_URL pnpm build) || fail "pnpm build failed"
    "$REPO_DIR/scripts/verify-web-build.sh" || fail "web build pre-flight gate FAILED (§0.4) — refusing to restart aether-web"
fi

# --- Step 6: restart services (API, Web, Worker) --------------------------
sudo systemctl stop aether-api.service aether-web.service aether-worker.service || fail "service stop failed"
sleep 2
sudo systemctl start aether-api.service aether-web.service aether-worker.service || fail "service start failed"
sleep 5
for svc in aether-api aether-web aether-worker; do
    systemctl is-active --quiet "$svc.service" || fail "$svc.service is not active after restart"
done

# --- Step 7: the 3 exact health checks (runbook §5 Phase 5, items 3/3b/4) -
curl -sf -H "Host: $NGINX_HOST" http://localhost/api/health >/dev/null \
    || fail "health check 1/3 failed: GET /api/health via nginx"
curl -sf --max-time 10 http://127.0.0.1:3000/api/health >/dev/null \
    || fail "health check 2/3 failed: GET 127.0.0.1:3000/api/health (next /api rewrite, §0.4)"
curl -sf -H "Host: $NGINX_HOST" http://localhost/ >/dev/null \
    || fail "health check 3/3 failed: GET / via nginx"

log "deploy successful: $NEW_HEAD"
exit 0
