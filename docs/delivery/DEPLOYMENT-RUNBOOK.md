# Aether Job & Career Agent — Production Deployment Runbook

**Last Updated:** 2026-07-17 (Phase-7 Async Additions)  
**Production URL:** https://5cb5f0620.abacusai.cloud  
**Repository:** https://github.com/Victordtesla24/aether-job-career-agent  
**Evidence Tag:** [VERIFIED-WITH-SOURCE]

---

## 1. Systemd Unit Names and Service Definitions

The Aether production system runs on four primary services (including Redis and worker) plus a scheduled discovery job:

### Primary Services
```
[VERIFIED-WITH-SOURCE] aether-api.service       — FastAPI/Uvicorn backend server (port 8000)
[VERIFIED-WITH-SOURCE] aether-web.service       — Next.js frontend server (port 3000)
[VERIFIED-WITH-SOURCE] aether-worker.service    — ARQ async background job worker
[VERIFIED-WITH-SOURCE] redis-server.service     — Redis queue store (DB 3, loopback only)
```

### Scheduled Jobs
```
[VERIFIED-WITH-SOURCE] aether-discovery.service — Oneshot job runner (scout + fit-scorer)
[VERIFIED-WITH-SOURCE] aether-discovery.timer   — Scheduler for discovery (every 30 minutes)
```

**Verification Command:**
```bash
systemctl is-active aether-api aether-web aether-worker redis-server
```

**Output (2026-07-17):**
```
active
active
active
active
```

---

## 2. Working Directories and Entrypoints

### Common Working Directory
All services share the single working directory:
```
[VERIFIED-WITH-SOURCE] /home/ubuntu/github_repos/aether-job-career-agent
```

### API Service (aether-api.service)
- **Unit File:** `/etc/systemd/system/aether-api.service`
- **Working Directory:** `/home/ubuntu/github_repos/aether-job-career-agent`
- **ExecStart:** `/home/ubuntu/github_repos/aether-job-career-agent/start-api.sh`
- **Actual Entrypoint:** `/opt/abacus-python/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **App Directory:** `./apps/api`
- **Start Script Details:**
  ```bash
  #!/bin/bash
  export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
  cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
  # Loads .env from repo root
  while IFS= read -r line || [ -n "$line" ]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      key="${line%%=*}"
      value="${line#*=}"
      value="${value#\"}" && value="${value%\"}"
      value="${value#\'}" && value="${value%\'}"
      export "$key"="$value"
  done < /home/ubuntu/github_repos/aether-job-career-agent/.env
  exec /opt/abacus-python/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```

### Web Service (aether-web.service)
- **Unit File:** `/etc/systemd/system/aether-web.service`
- **Working Directory:** `/home/ubuntu/github_repos/aether-job-career-agent`
- **ExecStart:** `/home/ubuntu/github_repos/aether-job-career-agent/start-web.sh`
- **Actual Entrypoint:** `pnpm start` (Next.js production server on port 3000)
- **App Directory:** `./apps/web`
- **Start Script Details:**
  ```bash
  #!/bin/bash
  export PATH="/opt/abacus-npm/bin:/usr/local/bin:/usr/bin:/bin"
  cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web
  # Loads .env from repo root
  while IFS= read -r line || [ -n "$line" ]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      key="${line%%=*}"
      value="${line#*=}"
      value="${value#\"}" && value="${value%\"}"
      value="${value#\'}" && value="${value%\'}"
      export "$key"="$value"
  done < /home/ubuntu/github_repos/aether-job-career-agent/.env
  export NODE_ENV=production
  exec pnpm start
  ```

### Worker Service (aether-worker.service)
- **Unit File:** `/etc/systemd/system/aether-worker.service`
- **Working Directory:** `/home/ubuntu/github_repos/aether-job-career-agent/apps/api`
- **ExecStart:** `/home/ubuntu/github_repos/aether-job-career-agent/start-worker.sh`
- **Actual Entrypoint:** `/opt/abacus-python/bin/arq app.workers.settings.WorkerSettings`
- **Start Script Details:**
  ```bash
  #!/bin/bash
  export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
  cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
  # Loads .env from repo root (same parser as start-api.sh)
  while IFS= read -r line || [ -n "$line" ]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      key="${line%%=*}"
      value="${line#*=}"
      value="${value#\"}" && value="${value%\"}"
      value="${value#\'}" && value="${value%\'}"
      export "$key"="$value"
  done < /home/ubuntu/github_repos/aether-job-career-agent/.env
  exec /opt/abacus-python/bin/arq app.workers.settings.WorkerSettings
  ```

### Discovery Service (aether-discovery.service / aether-discovery.timer)
- **Unit File:** `/etc/systemd/system/aether-discovery.service`
- **Timer File:** `/etc/systemd/system/aether-discovery.timer`
- **Working Directory:** `/home/ubuntu/github_repos/aether-job-career-agent`
- **ExecStart:** `/home/ubuntu/github_repos/aether-job-career-agent/scripts/discovery_cron.sh`
- **Schedule:** Every 30 minutes at :00 and :30 (OnCalendar=*:00/30)
- **Type:** oneshot (runs once then exits)
- **Note:** Sends `X-Aether-System-Run: <AETHER_SYSTEM_RUN_SECRET>` header to bypass paywall on scout/fitScorer calls

---

## 3. Safe Service Restart Commands

All restart operations must preserve service state and log continuity.

### Restart Individual Services

**Restart API only:**
```bash
[SAFE] sudo systemctl restart aether-api.service
```

**Restart Web only:**
```bash
[SAFE] sudo systemctl restart aether-web.service
```

**Restart Worker only:**
```bash
[SAFE] sudo systemctl restart aether-worker.service
```

**Note:** Web depends on API, so restarting web alone is safe. Worker depends on Redis and API, so can be restarted independently. Restarting API may affect in-flight async jobs (they will be retried).

### Restart All Services (Coordinated)

**Recommended: restart API, then Web, then Worker:**
```bash
sudo systemctl restart aether-api.service && sleep 2 && sudo systemctl restart aether-web.service && sleep 2 && sudo systemctl restart aether-worker.service
```

**Alternative: stop all, start all (use for full redeploy):**
```bash
sudo systemctl stop aether-api.service aether-web.service aether-worker.service && sleep 2 && sudo systemctl start aether-api.service aether-web.service aether-worker.service
```

### Stop/Start Without Restart

**Stop services gracefully:**
```bash
sudo systemctl stop aether-api.service aether-web.service
```

**Start services:**
```bash
sudo systemctl start aether-api.service aether-web.service
```

### Enable/Disable Auto-Start

**Enable all services to auto-start on boot:**
```bash
sudo systemctl enable aether-api.service aether-web.service aether-worker.service redis-server.service
```

**Verify services are enabled:**
```bash
systemctl is-enabled aether-api.service aether-web.service aether-worker.service redis-server.service
```

### Check Service Status

```bash
systemctl status aether-api.service
systemctl status aether-web.service
systemctl status aether-worker.service
systemctl status redis-server.service
systemctl status aether-discovery.timer
```

---

## 4. Actual Log Locations and Collection Methods

### Log Storage
All Aether logs are **file-based** (NOT journalctl) due to systemd override redirections.

**Log Directory:** `/var/log/aether/`

**Verification Command:**
```bash
ls -la /var/log/aether/
```

**Output (2026-07-17):**
```
-rw-r--r--  1 root root   2984571 Jul 17 11:35 api.log
-rw-r--r--  1 root root     54321 Jul 17 11:35 worker.log
-rw-r--r--  1 root root    106001 Jul 17 10:30 discovery.log
-rw-r--r--  1 root root     77646 Jul 15 14:23 web.log
```

### Individual Log Files

#### API Service Logs
- **Path:** `/var/log/aether/api.log`
- **Content:** Uvicorn startup messages, HTTP request logs, application errors
- **Redirect Method:** Systemd StandardOutput/StandardError append override
- **Override File:** `/etc/systemd/system/aether-api.service.d/10-logging.conf`
  ```
  [Service]
  StandardOutput=append:/var/log/aether/api.log
  StandardError=append:/var/log/aether/api.log
  ```

**Tail API logs (live):**
```bash
tail -f /var/log/aether/api.log
```

**View last 50 lines:**
```bash
tail -50 /var/log/aether/api.log
```

**Search for errors:**
```bash
grep -i "error\|exception\|traceback" /var/log/aether/api.log
```

#### Web Service Logs
- **Path:** `/var/log/aether/web.log`
- **Content:** Next.js build output, server startup, request logs
- **Redirect Method:** Systemd StandardOutput/StandardError append override
- **Override File:** `/etc/systemd/system/aether-web.service.d/10-logging.conf`
  ```
  [Service]
  StandardOutput=append:/var/log/aether/web.log
  StandardError=append:/var/log/aether/web.log
  ```

**Tail Web logs (live):**
```bash
tail -f /var/log/aether/web.log
```

#### Worker Service Logs
- **Path:** `/var/log/aether/worker.log`
- **Content:** ARQ background job execution, async generation results, retry/failure events
- **Redirect Method:** Systemd StandardOutput/StandardError append override
- **Override File:** `/etc/systemd/system/aether-worker.service` (lines 17-18)
  ```
  StandardOutput=append:/var/log/aether/worker.log
  StandardError=append:/var/log/aether/worker.log
  ```

**Tail Worker logs (live):**
```bash
tail -f /var/log/aether/worker.log
```

**Search for job completions:**
```bash
grep -i "job\|failed\|complete" /var/log/aether/worker.log
```

#### Discovery Service Logs
- **Path:** `/var/log/aether/discovery.log`
- **Content:** Scheduled job runner output, scout/fit-scorer results with X-Aether-System-Run header
- **Content:** oneshot service execution logs

**Tail Discovery logs:**
```bash
tail -f /var/log/aether/discovery.log
```

### Log Rotation
No rotation is currently configured. Log files grow indefinitely. To manage disk usage, manually archive or truncate logs:
```bash
# Archive current logs
sudo gzip /var/log/aether/*.log

# Truncate (keep file open by service)
sudo truncate -s 0 /var/log/aether/*.log
```

### Journalctl (NOT USED)
Journalctl is **not the authoritative source** for Aether logs. Service output is redirected to files. Journalctl may contain service metadata but not application logs:
```bash
journalctl -u aether-api.service -n 50 --no-pager
# Output: "No journal files were found" (verified 2026-07-16)
```

---

## 5. Deploy Procedure: From `git push main` to Production Updated

### Prerequisite
This VM is the production host itself. **There is no separate CI/CD deployment pipeline.** Code is deployed manually to this VM, built in-place, and services are restarted.

### Pre-Deployment Checks

**1. Verify gh CLI authentication:**
```bash
gh auth status
# Output should show: "✓ Logged in to github.com account Victordtesla24"
```

**2. Verify current git branch:**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
git status
# Expected: "On branch main" with "Your branch is up to date with 'origin/main'"
```

**3. Verify services are running:**
```bash
systemctl status aether-api.service aether-web.service
# Both should show "active (running)"
```

### Step-by-Step Deployment

#### Phase 1: Pull Latest Code
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
git fetch origin main
git log --oneline -5 origin/main   # View commits to be pulled
git pull origin main               # Pull latest commits
git log --oneline -1               # Verify new commit is local
```

**Expected Outcome:** Working tree matches origin/main HEAD

#### Phase 2: Install/Update Dependencies

**For Python (API):**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
pip install -r requirements.txt
```

**For Node.js (Web):**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
pnpm install --frozen-lockfile    # Use locked versions from pnpm-lock.yaml
```

**Expected Outcome:** No errors, dependencies installed to node_modules and Python site-packages

#### Phase 3: Build (if needed)

**For Next.js Web:**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web
pnpm build
```

**For FastAPI (no build required, pure Python)**

**Expected Outcome:** Web build succeeds with no errors, .next/ directory updated

#### Phase 4: Restart Services (Including Worker)

**Stop all services (API, Web, Worker):**
```bash
sudo systemctl stop aether-api.service aether-web.service aether-worker.service
```

**Start all services:**
```bash
sudo systemctl start aether-api.service aether-web.service aether-worker.service
```

**Alternative (using coordinated restart):**
```bash
sudo systemctl restart aether-api.service && sleep 2 && sudo systemctl restart aether-web.service && sleep 2 && sudo systemctl restart aether-worker.service
```

**Expected Outcome:** All three services enter "active (running)" state

#### Phase 5: Verify Deployment

**1. Check service status:**
```bash
systemctl status aether-api.service aether-web.service aether-worker.service redis-server.service
# All four must show: "active (running)"
```

**2. Check logs for startup errors (within 10 seconds of restart):**
```bash
tail -20 /var/log/aether/api.log     # Should show "Application startup complete"
tail -20 /var/log/aether/web.log     # Should show Next.js server ready message
tail -20 /var/log/aether/worker.log  # Should show ARQ worker startup messages
```

**3. Test API health endpoint:**
```bash
curl -s -H 'Host: 5cb5f0620.vm.internal' http://localhost/api/health || echo "API endpoint test"
```

**4. Test Web endpoint:**
```bash
curl -s -H 'Host: 5cb5f0620.vm.internal' http://localhost/ | head -20
```

**5. Check public URL (if accessible):**
```bash
curl -s https://5cb5f0620.abacusai.cloud/ | head -20
```

### Complete Deploy Recipe

Use this sequence for a full production deployment:

```bash
#!/bin/bash
set -e  # Exit on first error

REPO_DIR="/home/ubuntu/github_repos/aether-job-career-agent"
API_DIR="$REPO_DIR/apps/api"
WEB_DIR="$REPO_DIR/apps/web"

echo "[1/6] Verifying gh authentication..."
gh auth status || { echo "ERROR: Not authenticated to GitHub"; exit 1; }

echo "[2/6] Pulling latest code from origin/main..."
cd "$REPO_DIR"
git fetch origin main
git pull origin main
DEPLOYED_COMMIT=$(git log --oneline -1)
echo "Deployed commit: $DEPLOYED_COMMIT"

echo "[3/6] Installing Python dependencies..."
cd "$API_DIR"
pip install -r requirements.txt

echo "[4/6] Installing Node dependencies and building web..."
cd "$REPO_DIR"
pnpm install --frozen-lockfile
cd "$WEB_DIR"
pnpm build

echo "[5/6] Restarting services (API, Web, Worker)..."
sudo systemctl stop aether-api.service aether-web.service aether-worker.service
sleep 2
sudo systemctl start aether-api.service aether-web.service aether-worker.service
sleep 5

echo "[6/6] Verifying deployment..."
if systemctl is-active --quiet aether-api.service; then
    echo "✓ API service running"
else
    echo "✗ API service failed"; exit 1
fi

if systemctl is-active --quiet aether-web.service; then
    echo "✓ Web service running"
else
    echo "✗ Web service failed"; exit 1
fi

if systemctl is-active --quiet aether-worker.service; then
    echo "✓ Worker service running"
else
    echo "✗ Worker service failed"; exit 1
fi

if systemctl is-active --quiet redis-server.service; then
    echo "✓ Redis running"
else
    echo "✗ Redis failed"; exit 1
fi

echo ""
echo "=========================================="
echo "Deployment successful!"
echo "Commit: $DEPLOYED_COMMIT"
echo "URL: https://5cb5f0620.abacusai.cloud"
echo "=========================================="
```

### Deployment Timeline

| Phase | Operation | Duration | Notes |
|-------|-----------|----------|-------|
| 1 | git fetch + pull | ~5s | Depends on network, code size |
| 2 | pip install | ~30s | Python deps mostly cached |
| 3 | pnpm install | ~20s | Node deps, incremental updates |
| 4 | pnpm build | ~60s | Next.js build, can vary |
| 5 | Service restart (API, Web, Worker) | ~5s | Graceful shutdown + startup |
| 6 | Verification (4 services) | ~10s | Health checks + log inspection |
| **Total** | **Full deploy** | **~2-2.5min** | **May vary based on changes** |

**Note:** Phase 5 now includes aether-worker restart. Async jobs in flight will be automatically retried by the worker after restart.

---

## 6. Rollback Procedure

### Prerequisite
You must know the **previous stable commit hash** to roll back to. Keep records of deployed commits in deployment logs.

### Step-by-Step Rollback

#### Phase 1: Identify Previous Stable Commit

**View recent commits:**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
git log --oneline -10
```

**Identify a known-good commit (e.g., 2-3 commits back):**
```bash
ROLLBACK_COMMIT="abc123d"  # Replace with actual commit hash
git log --oneline $ROLLBACK_COMMIT^..$ROLLBACK_COMMIT  # Verify commit details
```

#### Phase 2: Revert to Previous Commit

**Option A: Reset hard to previous commit (DESTRUCTIVE - loses all local changes)**
```bash
git fetch origin
git reset --hard $ROLLBACK_COMMIT
git log --oneline -1  # Verify you're at the target commit
```

**Option B: Revert via new commit (SAFE - preserves history)**
```bash
git revert HEAD --no-edit  # Creates a revert commit
git push origin main       # Only if you have push access and git is configured
```

**Option C: Checkout previous version without changing HEAD (temporary fix)**
```bash
git checkout $ROLLBACK_COMMIT -- apps/
# Warning: This leaves HEAD ahead but working directory at previous version
```

#### Phase 3: Rebuild

**Reinstall dependencies:**
```bash
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
pip install -r requirements.txt

cd /home/ubuntu/github_repos/aether-job-career-agent
pnpm install --frozen-lockfile

cd /home/ubuntu/github_repos/aether-job-career-agent/apps/web
pnpm build
```

#### Phase 4: Restart Services (Including Worker)

```bash
sudo systemctl stop aether-api.service aether-web.service aether-worker.service
sleep 2
sudo systemctl start aether-api.service aether-web.service aether-worker.service
sleep 5
```

#### Phase 5: Verify Rollback

```bash
systemctl status aether-api.service aether-web.service aether-worker.service redis-server.service
tail -20 /var/log/aether/api.log
tail -20 /var/log/aether/web.log
tail -20 /var/log/aether/worker.log
```

### Complete Rollback Recipe

```bash
#!/bin/bash
set -e

REPO_DIR="/home/ubuntu/github_repos/aether-job-career-agent"
API_DIR="$REPO_DIR/apps/api"
WEB_DIR="$REPO_DIR/apps/web"

# Accept rollback commit as argument
if [ -z "$1" ]; then
    echo "Usage: $0 <commit-hash>"
    echo ""
    echo "Recent commits:"
    cd "$REPO_DIR" && git log --oneline -5
    exit 1
fi

ROLLBACK_COMMIT="$1"

echo "[1/5] Verifying commit exists..."
cd "$REPO_DIR"
git rev-parse $ROLLBACK_COMMIT || { echo "ERROR: Commit $ROLLBACK_COMMIT not found"; exit 1; }

echo "[2/5] Rolling back to $ROLLBACK_COMMIT..."
git reset --hard $ROLLBACK_COMMIT
echo "Rollback commit: $(git log --oneline -1)"

echo "[3/5] Rebuilding dependencies..."
cd "$API_DIR"
pip install -r requirements.txt
cd "$REPO_DIR"
pnpm install --frozen-lockfile
cd "$WEB_DIR"
pnpm build

echo "[4/5] Restarting services..."
sudo systemctl stop aether-api.service aether-web.service aether-worker.service
sleep 2
sudo systemctl start aether-api.service aether-web.service aether-worker.service
sleep 5

echo "[5/5] Verifying rollback..."
if systemctl is-active --quiet aether-api.service && systemctl is-active --quiet aether-web.service && systemctl is-active --quiet aether-worker.service && systemctl is-active --quiet redis-server.service; then
    echo "✓ Rollback successful"
    echo "Active commit: $(cd $REPO_DIR && git log --oneline -1)"
else
    echo "✗ Rollback verification failed"; exit 1
fi
```

**Usage:**
```bash
bash rollback.sh 6b4c642    # Rollback to commit 6b4c642
bash rollback.sh HEAD~2     # Rollback to 2 commits ago
```

---

## 7. Environment Variable Storage

### Location
All environment variables are stored in a **single .env file** at the repository root:
```
[VERIFIED-WITH-SOURCE] /home/ubuntu/github_repos/aether-job-career-agent/.env
```

### How Variables Are Loaded

Both start-api.sh and start-web.sh load variables from .env using the same safe parsing logic:

```bash
while IFS= read -r line || [ -n "$line" ]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    # Remove surrounding quotes if present
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
    export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env
```

**Key Features:**
- Comments (lines starting with #) are skipped
- Values can contain '=' characters (e.g., base64 padding)
- Surrounding quotes are stripped
- Variables are exported to service environment

### Environment Variables (Names Only)

The following environment variables must be defined in .env:

**LLM & API Configuration:**
- `AETHER_LLM_MODE`
- `AETHER_MODEL_FALLBACK`
- `AETHER_MODEL_FAST`
- `AETHER_MODEL_HEAVY`
- `AETHER_MODEL_LIGHT`
- `AETHER_MODEL_REASONING`
- `AETHER_MODEL_STRUCTURED`
- `ABACUS_API_KEY`

**Database:**
- `DATABASE_URL` (PostgreSQL connection string for production)
- `DATABASE_URL_TEST` (PostgreSQL connection string for tests)

**External APIs:**
- `FIRECRAWL_API_KEY`
- `FIRECRAWL_API_URL`
- `FIRECRAWL_BASE_URL`
- `OPENROUTER_API_KEY`
- `OPENROUTER_BASE_URL`

**Google OAuth:**
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI`

**Authentication:**
- `NEXTAUTH_SECRET`
- `NEXTAUTH_URL`

**Application URLs:**
- `NEXT_PUBLIC_API_BASE_URL`
- `PRODUCTION_URL`

**Node.js:**
- `NODE_ENV` (set to "production" by start-web.sh)

**Credentials (used by test/demo automation):**
- `LOGIN_EMAIL`
- `LOGIN_PASSWORD`

**Job Board Base URLs:**
- `INDEED_BASE_URL`
- `LINKEDIN_BASE_URL`
- `SEEK_BASE_URL`

**Encryption Key:**
- `AETHER_CREDENTIAL_KEY` (Fernet key for encrypting stored credentials)

**Phase-7 Async & Redis:**
- `AETHER_REDIS_URL` (Redis connection string with DB 3; format: redis://:password@127.0.0.1:6379/3)
- `AETHER_REDIS_PASSWORD` (Redis requirepass value, 48 hex chars from openssl rand -hex 24)
- `AETHER_ASYNC_GENERATION` (Boolean: true to enable async background jobs, false for sync; currently true)
- `AETHER_LLM_WORKER_BUDGET_SECONDS` (Budget for tailor/general LLM calls; typically 300)
- `AETHER_LLM_WORKER_COVER_BUDGET_SECONDS` (Budget for cover letter generation; typically 300)
- `AETHER_LLM_WORKER_PIPELINE_BUDGET_SECONDS` (Budget for pipeline/job recommendations; typically 480)
- `AETHER_JOB_STALE_SECONDS` (Watchdog timeout for in-flight jobs; default 900)

**Discovery & System:**
- `AETHER_SYSTEM_RUN_SECRET` (64-char hex secret sent as X-Aether-System-Run header for discovery bypass)
- `AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS` (Comma-separated domains bypassing paywall; currently aether.local)
- `CLAUDE_CODE_OAUTH_TOKEN` (Claude Code API token for agent integration)

### .env File Format

```
# Comment lines are ignored
VARIABLE_NAME=value
QUOTED_VALUE="value with spaces"
BASE64_VALUE=aGVsbG8gd29ybGQ=
SPECIAL_CHARS_IN_VALUE=key1=value1&key2=value2
```

### Secrets Management

**NEVER:**
- Commit .env to git (add to .gitignore)
- Print secret values in logs or output
- Share .env files via email or chat
- Use default/example values in production

**Safe Practices:**
- Store .env in a secure location (e.g., secret management tool)
- Restrict read access: `chmod 600 .env`
- Audit access to the production host
- Rotate secrets regularly (especially API keys)

**Updating .env:**
1. Edit `/home/ubuntu/github_repos/aether-job-career-agent/.env`
2. Restart affected services:
   ```bash
   sudo systemctl restart aether-api.service aether-web.service
   ```

---

## 7.1. Redis Configuration and Async Queue Storage

### Redis Service and Configuration

Redis stores the async job queue (using ARQ — Async Request Queue). The instance is provisioned for Aether only, bound to loopback, and uses logical DB 3 with a password-protected requirepass.

**Service Unit:** `/etc/systemd/system/redis-server.service` (OS-provided)  
**Configuration File:** `/etc/redis/redis.conf.d/aether.conf` (drop-in, included by main config)  
**Port:** `6379` (loopback-only, no remote access)  
**Logical DB:** `3` (isolated from other Redis uses on the VM)  
**Max Memory:** `256mb` with `noeviction` policy (queue entries are never silently dropped)  
**Persistence:** RDB snapshots only (appendonly=no); Postgres is the authoritative source

### Verification

**Check Redis is running:**
```bash
systemctl status redis-server.service
```

**Test Redis connectivity (requires password from .env):**
```bash
PASS=$(grep "^AETHER_REDIS_PASSWORD=" /home/ubuntu/github_repos/aether-job-career-agent/.env | cut -d= -f2)
redis-cli -a "$PASS" -n 3 ping
# Expected output: PONG
```

**View queued jobs:**
```bash
PASS=$(grep "^AETHER_REDIS_PASSWORD=" /home/ubuntu/github_repos/aether-job-career-agent/.env | cut -d= -f2)
redis-cli -a "$PASS" -n 3 DBSIZE  # Returns number of keys (jobs)
redis-cli -a "$PASS" -n 3 KEYS '*'  # Lists all job keys
```

### Restart Redis

Redis does not require restarts during normal deployments. If Redis must be restarted (e.g., after configuration changes):

```bash
sudo systemctl restart redis-server.service
# All in-flight async jobs will be retried after Redis comes back online
```

### Rollback Strategy (Async)

If an async job deployment is problematic:

1. **Instant fallback:** Set `AETHER_ASYNC_GENERATION=false` in `.env` and restart aether-api
2. **Endpoints revert:** All new requests immediately return sync 200 responses (no longer enqueue)
3. **In-flight jobs:** Still processed by the worker; can safely coexist with disabled async
4. **Data safety:** The additive `BackgroundJob` table remains (harmless if async is disabled later)

---

## 8. Nginx Configuration and Routing

### Nginx Config File
```
[VERIFIED-WITH-SOURCE] /etc/nginx/conf.d/5cb5f0620.conf
```

### Complete Nginx Server Block

```nginx
server {
    listen 80;
    server_name 5cb5f0620.vm.internal;

    # Next.js web app (port 3000)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $http_x_original_host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # FastAPI backend API (port 8000)
    # Proxied through /api/ path
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_x_original_host;
        proxy_http_version 1.1;
        proxy_connect_timeout 10s;
        proxy_send_timeout 30s;
        proxy_read_timeout 180s;
        add_header Access-Control-Allow-Origin "https://5cb5f0620.abacusai.cloud" always;
    }
}
```

### Routing Details

| Request Path | Backend | Port | Notes |
|--------------|---------|------|-------|
| `/` (root) | Next.js Web | 3000 | Front-end, HTML/JS |
| `/api/*` | FastAPI API | 8000 | Backend, REST API |

### Public URL Mapping

- **Public URL:** `https://5cb5f0620.abacusai.cloud`
- **Internal Server Name:** `5cb5f0620.vm.internal` (nginx virtual host)
- **HTTP Port:** 80 (Envoy forwards HTTPS → HTTP)
- **Original Host Header:** Preserved in `X-Original-Host` for backend services

### Nginx Operations

**Test configuration:**
```bash
sudo nginx -t
# Output: "nginx: configuration file /etc/nginx/nginx.conf test is successful"
```

**Reload configuration (no downtime):**
```bash
sudo systemctl reload nginx
```

**Restart nginx:**
```bash
sudo systemctl restart nginx
```

**Check nginx status:**
```bash
systemctl status nginx
```

**View nginx logs:**
```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Modifying Nginx Config

To change routing (e.g., add a new location block):

1. Edit `/etc/nginx/conf.d/5cb5f0620.conf`
2. Test syntax: `sudo nginx -t`
3. Reload: `sudo systemctl reload nginx`
4. Verify: `curl -s -H 'Host: 5cb5f0620.vm.internal' http://localhost/`

---

## 9. GitHub CLI Authentication Status

### Authentication Verification

**Command:**
```bash
gh auth status
```

**Output (2026-07-16):**
```
github.com
  ✓ Logged in to github.com account Victordtesla24 (/home/ubuntu/.config/gh/hosts.yml)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'
```

### Permissions

The authenticated token (`Victordtesla24`) has the following scopes:
- ✓ `gist` — Manage gists
- ✓ `read:org` — Read organization membership
- ✓ `repo` — Full control of private and public repositories (includes PR read/write)
- ✓ `workflow` — Manage GitHub Actions workflows

### Verified Capabilities

**List PRs on aether repo:**
```bash
gh pr list --repo Victordtesla24/aether-job-career-agent --limit 3
```

**Output (2026-07-16):**
```
12  feat(monitor): live Agent Monitor at /dashboard/agents/monitor  swarm/AGT-MONITOR/monitor     OPEN
11  feat(approval): headless global approval-modal controller + API  swarm/AGT-APPROVE/approval-modal  OPEN
10  fix(mobile): 44px touch targets on mobile dashboard & approval   swarm/AGT-MOBILE/touch-targets    OPEN
```

### Useful gh Commands for Deployment

**List open PRs:**
```bash
gh pr list --repo Victordtesla24/aether-job-career-agent --state open
```

**List merged PRs:**
```bash
gh pr list --repo Victordtesla24/aether-job-career-agent --state merged --limit 5
```

**Check PR status:**
```bash
gh pr view <PR_NUMBER> --repo Victordtesla24/aether-job-career-agent
```

**Close a PR:**
```bash
gh pr close <PR_NUMBER> --repo Victordtesla24/aether-job-career-agent
```

---

## Quick Reference

### Service Control

| Task | Command |
|------|---------|
| Check all services | `systemctl is-active aether-api aether-web aether-worker redis-server` |
| Check status (detailed) | `systemctl status aether-api.service aether-web.service aether-worker.service redis-server.service` |
| Restart API | `sudo systemctl restart aether-api.service` |
| Restart Web | `sudo systemctl restart aether-web.service` |
| Restart Worker | `sudo systemctl restart aether-worker.service` |
| Restart all | `sudo systemctl restart aether-api.service aether-web.service aether-worker.service` |
| View logs (all) | `tail -f /var/log/aether/{api,web,worker,discovery}.log` |
| View worker logs | `tail -f /var/log/aether/worker.log` |

### Deployment

| Task | Command |
|------|---------|
| Deploy | `cd /repo && git pull origin main && pnpm install && pnpm --dir apps/web build && sudo systemctl restart aether-api.service aether-web.service` |
| Verify | `curl -s -H 'Host: 5cb5f0620.vm.internal' http://localhost/` |

### Rollback

| Task | Command |
|------|---------|
| Identify commit | `git log --oneline -10` |
| Rollback (full) | `git reset --hard <COMMIT> && pnpm install && pnpm --dir apps/web build && sudo systemctl restart aether-api.service aether-web.service aether-worker.service` |
| Disable async (instant) | `sed -i 's/AETHER_ASYNC_GENERATION=.*/AETHER_ASYNC_GENERATION=false/' .env && sudo systemctl restart aether-api.service` |

---

## Troubleshooting

### Service won't start
1. Check logs: `tail -100 /var/log/aether/{api,web}.log`
2. Check dependencies: `pip list` (API) or `pnpm ls` (Web)
3. Verify .env: `grep -c "=" /home/ubuntu/github_repos/aether-job-career-agent/.env`
4. Restart manually: `sudo systemctl restart aether-{service}.service`

### Web can't reach API
1. Check API is running: `systemctl is-active aether-api.service`
2. Check port: `lsof -i :8000` (should show uvicorn)
3. Check nginx: `sudo nginx -t` then `sudo systemctl reload nginx`
4. Check NEXT_PUBLIC_API_BASE_URL in .env

### High disk usage
1. Check log sizes: `du -sh /var/log/aether/*`
2. Archive: `sudo gzip /var/log/aether/*.log`
3. Truncate: `sudo truncate -s 0 /var/log/aether/*.log`

### Async jobs not processing
1. Check worker is running: `systemctl is-active aether-worker.service`
2. Check Redis is running: `systemctl is-active redis-server.service`
3. Check worker logs: `tail -100 /var/log/aether/worker.log`
4. Check AETHER_ASYNC_GENERATION=true in .env: `grep "AETHER_ASYNC_GENERATION" .env`
5. Restart worker: `sudo systemctl restart aether-worker.service`

### Redis connection errors
1. Check Redis is running: `systemctl status redis-server.service`
2. Test Redis: `redis-cli -a <PASSWORD> -n 3 ping` (should output PONG)
3. Check .env has AETHER_REDIS_URL and AETHER_REDIS_PASSWORD
4. Restart Redis: `sudo systemctl restart redis-server.service`

---

**Document Version:** 2.0 (Phase-7: Async/Redis/Worker)  
**Last Verified:** 2026-07-17 by infra-discovery agent  
**Next Review:** 2026-07-24
