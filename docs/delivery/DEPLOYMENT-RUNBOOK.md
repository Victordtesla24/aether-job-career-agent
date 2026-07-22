# Aether Job & Career Agent — Production Deployment Runbook

**Last Updated:** 2026-07-22 (MODELS-LIVE `ML-runbook-001` — corrected the `pnpm` path/provenance
claim in the Web Service section; see `docs/delivery/MODELS-LIVE-GAPS.json`); prior update
2026-07-18 (MV-system-003 — safe test-suite invocation)  
**Production URL:** https://5cb5f0620.abacusai.cloud  
**Repository:** https://github.com/Victordtesla24/aether-job-career-agent  
**Evidence Tag:** [VERIFIED-WITH-SOURCE]

---

## 0. CRITICAL SAFETY — Running the Backend Test Suite

> ### ⚠️ WARNING — read before running `pytest` anywhere near this repo
>
> On 2026-07-18 a deploy step ran `set -a && source ../../.env && set +a && pytest`
> before the test suite. Sourcing the repo-root `.env` put the **PRODUCTION**
> `DATABASE_URL` (schema=`aether`) into the pytest process's environment. The
> suite's per-test table-cleanup fixture (`apps/api/tests/conftest.py`,
> `_truncate_tables()`) then ran `TRUNCATE TABLE ... CASCADE` against the
> **production** `aether` schema, wiping all real `User`/`Application`/`Job`/
> `StoryEntry`/`Resume`/`CoverLetter`/`Subscription`/`ApprovalRequest` data.
> Full incident writeup: `docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`.
>
> **NEVER** run the backend test suite by `source`-ing the repo-root `.env`
> (or any file that sets `DATABASE_URL` to the production DSN) into the same
> shell/process that then invokes `pytest`. `DATABASE_URL` and
> `DATABASE_URL_TEST` point at the **same** Postgres host+database and differ
> **only** by a `?schema=` query param — psycopg2 does not honour that param
> on its own (it needs `search_path` pinned via connection `options=`), so
> there is no forgiving margin here: getting `DATABASE_URL` wrong means
> truncating production.

### SAFE invocation (required)

Use **`scripts/run-tests.sh`** — it resolves `DATABASE_URL_TEST` (from an
already-exported var, or by grepping *only* that one line out of the
repo-root `.env`, never sourcing the whole file), exports it as **both**
`DATABASE_URL` and `DATABASE_URL_TEST` for the pytest child process, and
**refuses to run at all** if the resolved DSN's `schema=` param is not
literally `aether_test`:

```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
scripts/run-tests.sh                          # full suite
scripts/run-tests.sh tests/test_auth.py -q    # one file
```

Equivalent manual invocation (if you must run pytest directly — still never
`source ../../.env`):

```bash
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
DATABASE_URL="$DATABASE_URL_TEST" AETHER_ASYNC_GENERATION=false python3 -m pytest
```

### Defense in depth (already in place, do not rely on this alone)

`apps/api/tests/conftest.py` additionally enforces a fail-closed,
session-start guard (MV-system-003): before any fixture or test runs, it
opens the exact connection the truncation fixture will use — built **only**
from `DATABASE_URL_TEST`, with `search_path` pinned via `options=`, never
trusting `DATABASE_URL` — and verifies live via `SELECT current_schema()`
that it resolves to `aether_test`. Anything else aborts the whole pytest
session (`pytest.exit(..., returncode=2)`) before any destructive SQL runs.
Regression test: `apps/api/tests/test_mv_system_003_prod_truncate_guard.py`.
The escape hatch `AETHER_ALLOW_PROD_TRUNCATE=1` exists only for a
consciously-overridden local schema name and **must never be set in CI or
any deploy script.**

### 0.1 Concurrent pytest discipline — `flock` (shared `aether_test` schema)

Multiple agents/sessions on this VM can run the backend suite against the
**same** shared `aether_test` schema at the same time. A concurrent
`TRUNCATE` from one run against tables another run is mid-assertion on
produces non-deterministic, environment-caused failures that are easy to
mistake for real regressions ("Aether shared test-DB flakiness" — see
project memory). All sanctioned sub-agent charters (`.claude/agents/tester.md`,
`fixer-medium.md`, `fixer-hard.md`) run pytest wrapped in
`flock /tmp/aether-pytest.lock` for exactly this reason:

```bash
flock /tmp/aether-pytest.lock scripts/run-tests.sh
```

This is **in addition to**, not a replacement for, the `DATABASE_URL_TEST`
discipline in §0 above — `flock` only serializes concurrent runs against the
one shared schema; it does nothing to stop a wrong-DSN run from reaching
production. A gate/deploy suite run that matters (i.e. one whose count is
about to authorize a restart, per §0.2 below) should hold the lock for its
whole duration so a second concurrent run cannot interleave truncations
into it.

### 0.2 ADDENDUM (2026-07-20, MANUAL-VERIFICATION exit, `docs/delivery/MANUAL-VERIFICATION-GOVERNANCE-AUDIT.md` entries 12–13) — gate-before-restart + self-matching liveness checks

Two governance incidents during the MANUAL-VERIFICATION run exposed gaps in
this runbook's implicit deploy discipline that are now made explicit:

1. **Never restart a production service based on a partial or assumed test
   count.** A deployer restarted `aether-api`/`aether-web` **before** the
   full serialized backend gate (§0 above) had actually finished and
   reported its final `N passed / M failed` line — the first suite run had
   been `SIGTERM`'d and the second was still executing. **Rule: a deploy
   restart is authorized only after the gate's own completed summary line
   (`N passed, ... in ...s`) is read from the actual suite output — never
   before, and never from a guess about how long it "should" take.** If a
   gate run is killed or interrupted, it must be re-run from scratch to
   completion before any restart tied to it proceeds.
2. **Process-liveness checks must not self-match.** A separate incident: an
   orchestrator checked whether a long-running gate suite was "still
   running" using `pgrep -f <pattern>` — but the checking shell's own
   command line contained the same pattern, so the check matched itself and
   reported "STILL RUNNING" for ~30 minutes after the real suite process had
   already died (a false positive that delayed detecting the dead gate).
   **Rule: liveness checks must use self-excluding patterns** (e.g.
   `pgrep -f "[p]ytest"`, which bracket-escapes one character so the pattern
   no longer matches its own invocation) **or check `/proc/<pid>` /
   `ps -p <pid>` directly against a captured PID** — never a bare
   `pgrep -f <substring>` whose substring could appear in the checking
   command itself. Prefer file-based completion detection (the suite writing
   its own "done" marker/output file) over process-liveness polling
   entirely when practical.

### 0.3 ADDENDUM (2026-07-21, full incident: `docs/delivery/INCIDENT-2026-07-21-web-build-clobber.md`) — `pnpm build` in `apps/web` MUST be immediately followed by a web restart when working in the live-serving tree

**Symptom:** every screen in production began throwing the browser's
`Application error: a client-side exception has occurred` — site-wide, not
one screen.

**Root cause:** a fixer agent, following its own task's instruction to "run
`pnpm build`; must pass at the end" as a verification step, ran `pnpm build`
directly inside `/home/ubuntu/github_repos/aether-job-career-agent/apps/web`
— which is simultaneously the exact directory `aether-web.service`'s
already-running `next-server` process serves from (§2 above: there is no
separate build/worktree/staging copy on this VM; the fixer's own task
explicitly said to work "DIRECTLY in the main working tree… NO worktree").
`next build` **deletes and regenerates** `.next/static/` with brand-new
content-hashed chunk/CSS filenames on every run. The already-running
`next-server` process had the OLD build's HTML/manifests already loaded and
kept telling every browser to fetch the OLD (now on-disk-deleted) chunk
filenames — a guaranteed client-side chunk-load/hydration failure on
literally every route, because every route shares the same JS runtime
bootstrap. The fixer's task explicitly said "do not restart services —
orchestrator handles that," so the build ran, verified itself green
(vitest + `pnpm build` both passed), and stopped there — leaving the
already-running server pointed at assets that no longer existed on disk
until some later, unscheduled restart happened. In this incident a SECOND,
independent `pnpm build` (from a concurrent parallel agent/session working
the same shared tree) raced in immediately after the first restart and
would have reproduced the exact same outage again within seconds had it not
also been followed by its own restart.

**Fix applied:** `sudo systemctl restart aether-web.service` (marked `[SAFE]`
in §3) — twice, once per each of the two builds that landed. Verified via
curl against the real public HTTPS URL (never `localhost` with a fake
`Host:` header — that only exercises envoy's real ingress path) that (a)
every key page returns HTTP 200 with real body content and zero occurrences
of "Application error"/"client-side exception" in the rendered HTML, and
(b) every `_next/static/*` asset REFERENCED in that HTML also independently
resolves HTTP 200 (not 400/404) — the second check is the one that actually
catches this failure mode; the first alone would not, since Next's
server-rendered HTML looks completely normal even when its own linked
assets 404 a moment later.

**Rule — binding on every fixer/deployer/orchestrator process, not just this
one:** `pnpm build` must **never** be run inside this VM's live
`apps/web` directory without an `aether-web.service` restart immediately
following it in the SAME task/session, before that task is considered done
— regardless of whether the individual task's own instructions say "don't
restart, orchestrator handles that." A fixer task that runs `pnpm build`
directly in the shared production tree (as opposed to an isolated worktree)
has, by that action alone, already put a stale-vs-disk mismatch one restart
away from going live; "the orchestrator restarts later" is not safe unless
the restart is guaranteed to happen before ANY other process (including a
concurrent fixer) reads or serves from that same `.next` directory in the
interim. If a task's own charter forbids restarting, it must instead forbid
running `pnpm build` in the shared tree at all (verify via `tsc --noEmit` +
`next lint` + vitest only, and defer the actual `pnpm build` + restart to
whichever agent owns the deploy step, back-to-back, with no other build in
between).

Neither of these changes the deploy recipe's commands in §5 — they are
process rules for *when* those commands are run, not new commands.

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
- **`pnpm` provenance (CORRECTED, `ML-runbook-001`, 2026-07-22):** `pnpm` is **system-installed at
  `/usr/bin/pnpm`** (a corepack symlink), **not** an `/opt/abacus-npm/bin` npm global — `pnpm` has
  no binary under `/opt/abacus-npm/bin/` at all (that directory only holds `abacusai`/`claude`/
  `codex`/`openclaw`). The `PATH` below lists `/opt/abacus-npm/bin` first for other npm-global
  tooling, but `/usr/bin` is also on it, so shell lookup falls through and correctly resolves
  `pnpm` to `/usr/bin/pnpm` — this has always worked; only the implied provenance was wrong.
  `[VERIFIED-WITH-FRESH-EVIDENCE: which pnpm → /usr/bin/pnpm; ls /opt/abacus-npm/bin/pnpm → No such
  file or directory; env PATH="/opt/abacus-npm/bin:/usr/local/bin:/usr/bin:/bin" which pnpm →
  /usr/bin/pnpm; this task, 2026-07-22]`.
- **App Directory:** `./apps/web`
- **Start Script Details:**
  ```bash
  #!/bin/bash
  # pnpm resolves to the system-installed /usr/bin/pnpm (corepack) via PATH
  # fallthrough — NOT from /opt/abacus-npm/bin, which has no pnpm binary.
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
- **Content:** Uvicorn startup messages, HTTP request logs, application errors — every line now carries an `ISO-8601 UTC` timestamp prefix (`2026-07-18T18:17:05Z INFO: ...`), fixed under MV-system-001 (see below)
- **Redirect Method:** Systemd StandardOutput/StandardError append override
- **Override File:** `/etc/systemd/system/aether-api.service.d/logging.conf` (corrected filename — was previously misdocumented here as `10-logging.conf`; verified against the live file 2026-07-18)
  ```
  [Service]
  StandardOutput=append:/var/log/aether/api.log
  StandardError=append:/var/log/aether/api.log
  ```
- **Now tracked in git:** `deploy/aether-api.service` + `deploy/aether-api.service.d/logging.conf` (previously host-only, untracked)

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
- **Content:** Next.js build output, server startup, request logs — every line now carries an `ISO-8601 UTC` timestamp prefix, fixed under MV-system-001 (see below)
- **Redirect Method:** Systemd StandardOutput/StandardError append override
- **Override File:** `/etc/systemd/system/aether-web.service.d/logging.conf` (corrected filename — was previously misdocumented here as `10-logging.conf`; verified against the live file 2026-07-18)
  ```
  [Service]
  StandardOutput=append:/var/log/aether/web.log
  StandardError=append:/var/log/aether/web.log
  ```
- **Now tracked in git:** `deploy/aether-web.service` + `deploy/aether-web.service.d/logging.conf` (previously host-only, untracked)

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

### MV-system-001 — Timestamped Logs Fix (2026-07-18)

**Finding:** journald was empty for every `aether-*` unit (confirmed above)
*and* `api.log`/`web.log` lines carried no timestamp at all, so a 5xx/
traceback found in either file could not be scoped to a test/incident time
window (`uat/reports/evidence/manual-verification/screens/baseline-server-logs.md`).

**Decision:** keep the file-based sink (do **not** switch
`StandardOutput`/`StandardError` to `journal`) rather than adopting journald.
Switching sinks is a bigger, restart-requiring infra change that would leave
every log-tailing/grep command in this runbook silently pointed at a file
journald no longer writes to. Instead, both surfaces now emit an ISO-8601 UTC
timestamp on every line, so the existing file-based tooling (`tail`, `grep`,
`awk`) can scope by time exactly like `journalctl --since`/`--until` would:

- **API (uvicorn):** `apps/api/logging_config.json` extends uvicorn's own
  default `logging.config.dictConfig` (formatters `default`/`access` plus a
  `root` handler so any app-module `logging.getLogger(__name__)` call also
  gets timestamped) with `%(asctime)sZ` (`datefmt: "%Y-%m-%dT%H:%M:%S"`).
  Wired in via `start-api.sh`'s `uvicorn ... --log-config logging_config.json`.
- **Web (Next.js):** `next start` has no built-in log-format hook, so
  `start-web.sh` now pipes its stdout/stderr through `gawk` (pre-installed,
  no new dependency) to prefix `strftime("%Y-%m-%dT%H:%M:%SZ", ..., utc=1)`
  on every line. `set -o pipefail` was added so the pipeline's exit status
  still reflects `pnpm start`/`next`'s real exit code (not gawk's), preserving
  `Restart=on-failure`.
- **Newly tracked in git** (previously host-only): `deploy/aether-api.service`,
  `deploy/aether-api.service.d/logging.conf`, `deploy/aether-web.service`,
  `deploy/aether-web.service.d/logging.conf` — the `[Unit]`/`[Service]`/
  `[Install]` directives are functionally identical to the live
  `/etc/systemd/system/...` units as of 2026-07-18 (no functional change);
  each tracked `.service` file additionally carries a descriptive header
  comment block not present in the live file. Verified via `diff` isolating
  the added comment lines as the only difference, plus `systemd-analyze
  verify`.
- **Worker (`aether-worker.service`) is unaffected** — `arq`'s own default
  logging config already prefixes `HH:MM:SS` timestamps (confirmed in the
  original finding's reproduction), so `worker.log` was never part of this
  gap.

**Needs a deploy to take effect:** `start-api.sh`/`start-web.sh` are read by
their respective processes only at process start, so the ISO-8601 prefix
appears only after the next `sudo systemctl restart aether-api.service` /
`aether-web.service` (normal deploy restart — see §5). No new systemd units
need to be installed/symlinked for this fix alone since `ExecStart` already
points directly at the tracked `start-api.sh`/`start-web.sh`; the newly
tracked `deploy/aether-{api,web}.service*` files are a documentation/version-
control hygiene addition, not a required action.

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

**4. Verify `AETHER_LLM_MODE` is NOT `replay` or `record`:**
```bash
grep -E '^AETHER_LLM_MODE=' /home/ubuntu/github_repos/aether-job-career-agent/.env
# Expected: AETHER_LLM_MODE=auto  (or =live)
# MUST NOT be =replay or =record
```

**Why this check exists (MV-application-tracker-001, BLOCKER, 2026-07-17):** in `replay`
mode the LLM client (`apps/api/app/services/llm_client.py`, `_replay()`) serves
canned content straight out of `apps/api/tests/fixtures/llm/**` instead of a live
model response, and `record` mode persists whatever the live call returns for
later replay. Neither mode carries any signal to the end user that the content
is fixture/test data, not a real generation. A prior incident (RCA:
`uat/reports/evidence/manual-verification/fixes/MV-application-tracker-001/RCA.json`,
verdict `stale-seed-data`) found 8 production `Application.coverLetter` rows
containing fixture-derived text, fabricated achievements repeated verbatim
across unrelated jobs, reachable by real users. The RCA confirmed production
was already running `AETHER_LLM_MODE=auto` (which never serves fixtures — see
`_auto()` in the same file) and that the leaked rows were stale seed/test data
rather than a live code defect, but the exposure mechanism (a non-`auto`/`live`
mode reaching production) is exactly what this check guards against. Do not
deploy — and if already deployed, treat as a rollback-now incident — if this
check shows `replay` or `record`. A permanent regression guard for the
specific leaked content also exists at
`apps/api/tests/test_mv_no_fixture_content_in_prod_data.py`.

**5. If running the backend test suite as part of pre-deploy validation:**
**NEVER** `source ../../.env` (or the repo-root `.env`) into the shell that
invokes `pytest` — use `scripts/run-tests.sh` exclusively. See **§0 CRITICAL
SAFETY** above (MV-system-003) — this is how production got wiped on
2026-07-18.

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
