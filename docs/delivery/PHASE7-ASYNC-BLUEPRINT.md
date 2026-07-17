# PHASE-7 — Async Background Generation Blueprint (GAP-P7-ASYNC-001)

**Author:** arch (claude-opus-4)
**Date:** 2026-07-17
**Ruling:** ADR-P7-03 (async stack defers to arch blueprint against OBSERVED infra)
**Spec:** §16 `/home/ubuntu/aether-subscription-prompt.md` + Journey J3 (§12) + §19
**Status:** DRAFT — requires explicit fable-5 approval before ANY implementation. arch writes no production fix code.
**Production:** https://5cb5f0620.abacusai.cloud
**Evidence root:** `uat/reports/evidence/phase7/`

Epistemic tags on every claim: `[VERIFIED-WITH-SOURCE: file:line]`, `[INFERRED]`, `[ASSUMED-PENDING-PROBE]`. Zero untagged assertions.

---

## 0. Observed reality (the ground the design stands on)

| Fact | Evidence |
|---|---|
| Redis NOT installed; no `redis-server` unit, no `redis-cli`/`redis-server` binary | `[VERIFIED-WITH-SOURCE: uat/reports/evidence/phase7/probe-async-redis-status.txt]` + `step2-infra-check.txt §2` |
| `arq` and `redis` python packages NOT in venv | `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §7]` (`/opt/abacus-python/bin/pip show arq redis` → not found) |
| API venv is `/opt/abacus-python` (Python 3.12.3) — NOT `apps/api/venv` | `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §2 + §7]` |
| aether-api launched by `start-api.sh` wrapper that parses **repo-root** `.env` then `exec /opt/abacus-python/bin/python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §2]` |
| `.env` lives at repo root `/home/ubuntu/github_repos/aether-job-career-agent/.env`, perms `-rw-------` (600) | `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §8]` |
| Logs are FILE-based at `/var/log/aether/{api,web,discovery}.log` (NOT journalctl, NOT /tmp) | `[VERIFIED-WITH-SOURCE: step2-infra-check.txt "Log Section"]` |
| DB access is **synchronous psycopg2**, short-lived connections (hosted PG caps 25 conns, kills idle txns); schema Prisma-managed | `[VERIFIED-WITH-SOURCE: apps/api/app/db.py:19-52]` |
| Run HTTP handlers are **sync `def`** (FastAPI runs them in its anyio threadpool) | `[VERIFIED-WITH-SOURCE: apps/api/app/routers/agents.py:835 run_tailor, :850 run_cover_letter, :927 run_pipeline]` |
| `pipeline/run` does NOT complete within 150s (honest timeout) | `[VERIFIED-WITH-SOURCE: uat/reports/evidence/phase7/probe-p7-11a-pipeline-latency.json]` |
| VM: 2 vCPU, 7957 MB RAM, ~2540 MB available, 0 swap, 32 GB free disk | `[VERIFIED-WITH-SOURCE: live probe 2026-07-17 — `free -m` / `nproc` / `df -h`]` |
| `redis-server` installable via apt, candidate `5:7.0.15-1ubuntu0.24.04.4` (noble) | `[VERIFIED-WITH-SOURCE: live probe 2026-07-17 — `apt-cache policy redis-server`]` |

**Deviations from the §16 draft that these facts force** (all recorded in §11):
1. venv path `/opt/abacus-python`, not `apps/api/venv`.
2. logs `/var/log/aether/worker.log`, not `/tmp/aether-worker.log`.
3. env loading via a `start-worker.sh` wrapper against **repo-root** `.env`, not `EnvironmentFile=apps/api/.env`.
4. Ubuntu unit name is `redis-server.service`, not `redis.service`.
5. Status route is NOT `/api/jobs/{id}` (route collision — §3).

---

## 1. Queue technology decision (§16.1)

### 1.1 Fit analysis against OBSERVED async patterns

The §16 draft reasons "if the API is fully async, ARQ fits." **The API is NOT fully async.** The data layer is synchronous psycopg2 with open-use-close connections `[VERIFIED-WITH-SOURCE: apps/api/app/db.py:44-52]`, and every run handler is a plain `def` that FastAPI already dispatches on its threadpool `[VERIFIED-WITH-SOURCE: apps/api/app/routers/agents.py:835,850,927]`. The LLM budget mechanism is a sync `ContextVar` deadline consumed inside sync client loops `[VERIFIED-WITH-SOURCE: apps/api/app/services/llm_client.py:88-105,768-778]`.

Consequence: an ARQ task body (`async def`) that called the existing service code **directly** would block ARQ's single event loop for the whole 60–300s LLM generation, serializing all jobs. This is not a blocker — it dictates one rule: **every task body offloads the blocking service call to a thread via `asyncio.to_thread(...)`**, mirroring exactly what FastAPI already does for the sync `def` handlers. `asyncio.to_thread` copies the current `contextvars.Context`, so the `shared_budget` ContextVar and per-user credential context propagate correctly. `[INFERRED from db.py sync model + llm_client ContextVar usage + asyncio.to_thread semantics]`

### 1.2 Options considered

| Option | Verdict for THIS stack |
|---|---|
| FastAPI `BackgroundTasks` | REJECTED — same process/threadpool as the API; a stuck LLM call still consumes an API worker thread; no durable status, no retry, no cross-restart survival. `[INFERRED]` |
| **ARQ + Redis** | **CHOSEN** — async-native worker process (separate from aether-api), Redis-backed durable queue, built-in retries/`job_timeout`/health, cron support for the staleness sweep. Sync work is offloaded via `asyncio.to_thread`. `[INFERRED from stack fit]` |
| RQ (Redis Queue) | Strong runner-up — sync, fork-per-job, natively fits the sync codebase with zero to_thread ceremony. Rejected only on balance: fork-per-job is heavier on a 2 GB-free VM than one long-lived async worker, RQ has no first-class async story for a future SSE progress channel, and choosing it widens the deviation from §16. `[INFERRED]` If fable-5 prefers minimizing event-loop risk, RQ is an acceptable substitution with the same DDL/endpoint/quota design below. |
| Celery | REJECTED — heavier, sync-first, same Redis dependency but more moving parts than ARQ for a single-VM single-worker deployment. `[INFERRED]` |
| Plain asyncio/DB-polled worker | REJECTED — reimplements retries/timeouts/visibility ARQ gives for free. `[INFERRED]` |

**Decision: ARQ + Redis**, tasks offload blocking service calls with `asyncio.to_thread`, modest concurrency for a small VM. `[INFERRED]`

### 1.3 Redis provisioning plan for THIS host

`redis-server` is apt-installable (candidate 7.0.15) `[VERIFIED-WITH-SOURCE: live probe apt-cache policy]`. Provisioning (an **infra step for the deployer, not arch**):

```bash
sudo apt-get update && sudo apt-get install -y redis-server   # installs redis-server.service
```

Config — a drop-in `/etc/redis/redis.conf.d/aether.conf` (or edited `/etc/redis/redis.conf`) with:

```
bind 127.0.0.1 -::1          # localhost only — never exposed via nginx
protected-mode yes
port 6379                    # confirm free at provision time; else 6380
requirepass ${AETHER_REDIS_PASSWORD}   # see below — defense-in-depth
maxmemory 256mb              # small: queue holds tens of jobs; Postgres is source of truth
maxmemory-policy noeviction  # never silently drop queue entries
appendonly no                # RDB default snapshots suffice; Postgres BackgroundJob is authoritative
```

```bash
sudo systemctl enable --now redis-server
redis-cli -a "$AETHER_REDIS_PASSWORD" ping   # expect PONG
```

**Password decision — USE a password.** `[INFERRED]` Rationale: per the VM's global instructions this host is **shared across projects/sessions** (OpenClaw, Hermes, other user projects), so `127.0.0.1:6379` is *not* single-tenant. Loopback binding alone would let any co-resident localhost process read/inject aether jobs. A `requirepass` sourced from `.env` (`AETHER_REDIS_PASSWORD`, generated once via `openssl rand -hex 24`, written with an atomic 600 write — §9) closes that hole at negligible cost. We further isolate on **Redis logical DB 3** (`AETHER_REDIS_URL=redis://:<pass>@127.0.0.1:6379/3`) so an unrelated project on db 0 cannot collide. `[INFERRED]`

Memory cap 256 MB is safe: only ~2.5 GB is free `[VERIFIED-WITH-SOURCE: live probe free -m]`, and the queue never holds more than tens of small JSON payloads (result bodies live in Postgres, not Redis). `noeviction` guarantees an honest error rather than silent job loss if the cap were ever hit. `[INFERRED]`

Python deps: add `arq>=0.25` and `redis>=5` to `apps/api/requirements.txt` `[VERIFIED-WITH-SOURCE: apps/api/requirements.txt:2-3 shows the file exists/format]`; `arq` pulls the async `redis` client. Install with `/opt/abacus-python/bin/pip install -r apps/api/requirements.txt`. `[INFERRED]`

---

## 2. `BackgroundJob` DDL (§16.2 — additive only)

Naming convention **verified from a real table**: production tables are quoted PascalCase, columns quoted camelCase, `text` PK defaulting to `gen_random_uuid()::text`, `timestamptz` audit columns `[VERIFIED-WITH-SOURCE: apps/api/app/repositories/billing.py:145-157 "UsageQuota" DDL]`; Prisma models confirm the same camelCase field convention `[VERIFIED-WITH-SOURCE: packages/db/src/schema.prisma:272-289 AgentRun]`. The table follows the existing lazy-ensure idempotent pattern (advisory-lock-guarded `CREATE TABLE IF NOT EXISTS`) `[VERIFIED-WITH-SOURCE: apps/api/app/repositories/billing.py:73-90, apps/api/app/db.py:74-140]`.

```sql
-- ADDITIVE ONLY. No DROP, no destructive ALTER. Runs in the aether schema.
CREATE TABLE IF NOT EXISTS "BackgroundJob" (
    "id"              text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"          text        NOT NULL,
    "agentKey"        text        NOT NULL,          -- 'tailor' | 'coverLetter' | 'pipeline'
    "runId"           text,                          -- linked AgentRun.id (null for pipeline: it spawns many)
    "params"          jsonb,
    "status"          text        NOT NULL DEFAULT 'enqueued', -- enqueued|processing|completed|failed
    "arqJobId"        text,
    "result"          jsonb,                         -- output payload GET returns; only on completed
    "error"           text,                          -- honest failure message; never fixture content
    "attempts"        integer     NOT NULL DEFAULT 0,
    "quotaReserved"   boolean     NOT NULL DEFAULT false, -- single-agent enqueue reserved 1 plan run
    "quotaReservedAt" timestamptz,
    "quotaRefundedAt" timestamptz,
    "startedAt"       timestamptz,                   -- worker pickup time (watchdog staleness anchor)
    "finishedAt"      timestamptz,
    "createdAt"       timestamptz NOT NULL DEFAULT now(),
    "updatedAt"       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "BackgroundJob_userId_createdAt_idx"
    ON "BackgroundJob" ("userId", "createdAt" DESC);   -- user activity list + auth-scoped polling
CREATE INDEX IF NOT EXISTS "BackgroundJob_status_idx"
    ON "BackgroundJob" ("status");                      -- watchdog sweep of stuck enqueued/processing
```

No FK constraint — matches `"UsageQuota"` which stores `userId text` without a FK `[VERIFIED-WITH-SOURCE: billing.py:145-157]`; avoids ACCESS-EXCLUSIVE lock risk and keeps the migration fully additive/non-blocking. Applied by the `migrator` agent (`CREATE ... IF NOT EXISTS` only) AND lazily ensured by a new `BackgroundJobRepository._ensure_table()` on first use, exactly like `_ensure_billing_tables()` `[VERIFIED-WITH-SOURCE: billing.py:73]`.

---

## 3. Endpoint contract changes (§16.2)

### 3.1 Route-collision check — RESOLVED

`GET /api/jobs/{id}` as drafted in §16.2/J3 **collides**: the job-listings router is mounted at prefix `/jobs` `[VERIFIED-WITH-SOURCE: apps/api/app/main.py:140]` and already owns `GET /jobs/{id}` for a job *posting* id `[VERIFIED-WITH-SOURCE: apps/api/app/routers/jobs.py:5, :26]`. A background-job id at that path would be routed into the postings handler.

**Chosen status route: `GET /api/agents/jobs/{job_id}`** `[INFERRED]`. It lives in the agents router (prefix `/agents` `[VERIFIED-WITH-SOURCE: main.py:141]`), which already owns every run endpoint and the `CurrentUser` auth dependency. The agents router has **no** `GET` catch-all — its dynamic GETs are literal-prefixed (`/runs/{run_id}`) `[VERIFIED-WITH-SOURCE: agents.py:780]` and its only catch-all is `POST /{name}/run` — so `GET /agents/jobs/{job_id}` cannot be shadowed. Deviation from §16.2 recorded in §11. (`/api/background-jobs/{id}` via a new router is an equally-valid alternative; `/api/agents/jobs/{id}` is preferred for cohesion + minimal new surface.)

### 3.2 Enqueue endpoints → 202

`POST /api/agents/tailor/run`, `/cover-letter/run`, `/pipeline/run` return **202** `{"job_id": "<BackgroundJob.id>", "status": "enqueued"}` when async is enabled. Enqueue ordering (all synchronous, in the sync `def` handler — no event loop involved):

1. **Paywall FIRST** — `_require_active_subscription(user_id)` → honest 402 before any row/reserve/enqueue `[VERIFIED-WITH-SOURCE: agents.py:488-512, invoked first in _record_run at :528]`. Preserves the "paywall check still FIRST at enqueue" mandate.
2. Subscription-provider cooldown block check → 429 if blocked `[VERIFIED-WITH-SOURCE: agents.py:533-539]`.
3. **Quota reserve AT ENQUEUE (atomic)** — for single-agent runs (`tailor`, `coverLetter`, both metered `[VERIFIED-WITH-SOURCE: agents.py:634-639 _LLM_TIER_BY_BACKEND]`): `UsageQuotaRepository().reserve(user_id)` (single conditional UPDATE, atomic) `[VERIFIED-WITH-SOURCE: apps/api/app/repositories/billing.py:454-489]`; `None` → `_plan_quota_429("quota_exceeded", ...)` `[VERIFIED-WITH-SOURCE: agents.py:551-553]`; spend-cap breach → `refund_run` + `_plan_quota_429("spend_cap_exceeded")` `[VERIFIED-WITH-SOURCE: agents.py:554-556, billing.py:502-514]`. Set `quotaReserved=true`, `quotaReservedAt=now()`.
4. Create the `AgentRun` audit row (`runs.start`, status queued) `[VERIFIED-WITH-SOURCE: agents.py:558]` and the `BackgroundJob` row (`status='enqueued'`, `runId`, `quotaReserved`).
5. Enqueue to ARQ (`await pool.enqueue_job('run_agent_job', job_id)`); store `arqJobId`. **If enqueue raises (Redis down): compensate — `refund_run` (if reserved), mark BackgroundJob `failed` (honest error "generation queue temporarily unavailable"), return 503.** Never a 200/202 with no queued work; never silent sync fallthrough. `[INFERRED]`
6. Return 202.

**Pipeline is a deliberate exception to single-reserve-at-enqueue** `[INFERRED]`. `run_pipeline` runs supervisor→scout→fitScorer→matcher→tailor→coverLetter and its **metered footprint is data-dependent** (0, 1, or 2 metered runs, since it early-returns when no top job is found `[VERIFIED-WITH-SOURCE: agents.py:940-971]`). Reserving a fixed count at enqueue would misbill. Design: at enqueue the pipeline does **paywall FIRST only** (step 1) + BackgroundJob row; **per-metered-step atomic reserve/refund stays inside the worker's pipeline orchestration**, reusing the existing `_record_run` reserve+refund exactly as today `[VERIFIED-WITH-SOURCE: agents.py:551-556 reserve, :566/573/586/593 refund per failure path]`. Semantics preserved: every metered step is atomically reserved and refunded-on-failure; only the enqueue-time single-reserve differs, and only for the composite endpoint. Recorded as a spec deviation (§11).

### 3.3 Status polling endpoint

`GET /api/agents/jobs/{job_id}` (auth = `CurrentUser`, ownership-scoped by `userId`) returns:

```json
{ "job_id": "...", "status": "enqueued|processing|completed|failed",
  "result": { ... } | null, "error": "..." | null,
  "createdAt": "...", "startedAt": "..."|null, "finishedAt": "..."|null }
```

`404` if the job is not found or not owned by the caller (no cross-user leakage). Includes the **lazy staleness check** (§7): if `status in ('enqueued','processing')` and the age past `startedAt`/`createdAt` exceeds the timeout, the read atomically transitions the row to `failed` + refunds quota + returns `failed` — guaranteeing a terminal state even if the worker is dead. `[INFERRED]`

---

## 4. Worker module design (`apps/api/app/workers/`)

No logic duplication — the worker reuses the **exact** service code paths the sync endpoints use today. The one required refactor extracts the agent→callable mapping so both the sync path and the worker share it.

### 4.1 Refactor (fixer, under this blueprint) — split `_record_run` into reserve / execute

`_record_run` today does paywall → reserve → `runs.start` → `fn()` → `finish`/refund in one call `[VERIFIED-WITH-SOURCE: agents.py:515-627]`. Extract two helpers with **no behavior change** for the sync flag-OFF path:

- `_agent_callable(user_id, name, params) -> (canonical_name, fn)` — pure mapping, no side effects, lifted verbatim from the existing `_dispatch` body `[VERIFIED-WITH-SOURCE: agents.py:687-745]`. The exact service functions it binds: `TailoringAgent().run(user_id, job_id, resume_id)` `[VERIFIED-WITH-SOURCE: agents.py:719-724]`, `CoverLetterAgent().run(user_id, job_id)` `[VERIFIED-WITH-SOURCE: agents.py:727-731]`.
- `_execute_reserved_run(run_id, user_id, name, fn, quota_repo, audit)` — the `try/except` execution block (fn → finish → refund-on-any-failure → cost → record_spend) lifted verbatim from `agents.py:560-627`. Runs inside `user_credential_context` + honors `shared_budget` `[VERIFIED-WITH-SOURCE: agents.py:562-563, 965-967]`.
- Sync path (`_record_run`, flag OFF) = reserve + `_execute_reserved_run` — identical to today.
- Worker path (flag ON) = `_agent_callable` + `_execute_reserved_run` (quota already reserved at enqueue for single-agent).

### 4.2 `apps/api/app/workers/settings.py` — ARQ `WorkerSettings`

```
functions   = [run_agent_job]
cron_jobs   = [cron(sweep_stale_jobs, minute=set(range(0,60,5)))]  # every 5 min
redis_settings = RedisSettings.from_dsn(os.environ["AETHER_REDIS_URL"])
max_jobs    = 3          # 2 vCPU / ~2.5 GB free → modest concurrency [INFERRED from live probe]
job_timeout = 600        # > largest LLM budget so ARQ never kills mid-generation
keep_result = 300        # ARQ result TTL; Postgres BackgroundJob is authoritative anyway
max_tries   = 3          # applies only to transient (re-raised) errors — see 4.3
```

### 4.3 `apps/api/app/workers/tasks.py` — task function + honest error handling

```
async def run_agent_job(ctx, job_id):
    job = BackgroundJobRepository().mark_processing(job_id)   # status=processing, startedAt=now
    try:
        if job.agentKey == 'pipeline':
            # reuse run_pipeline orchestration (per-step reserve/refund inside)
            result = await asyncio.to_thread(_run_pipeline_body, job.userId, job.params)
        else:
            name, fn = _agent_callable(job.userId, job.agentKey, job.params)
            with_budget = _wrap_worker_budget(name, fn)          # §4.4
            result = await asyncio.to_thread(
                _execute_reserved_run, job.runId, job.userId, name, with_budget, ...)
        BackgroundJobRepository().mark_completed(job_id, result)  # status=completed, result=...
    except _TransientError as e:            # Redis/DB connectivity, LLMUnavailable transient
        raise                               # let ARQ retry (max_tries)
    except Exception as e:                  # permanent/business failure
        # NEVER fixture content. ALWAYS refund. NEVER re-raise (no retry with bad input).
        BackgroundJobRepository().mark_failed(job_id, error=_honest_message(e))
        # _execute_reserved_run already refunded the reserved run on its failure paths
        # (agents.py:566/573/586/593); for single-agent enqueue-reserved jobs the worker
        # additionally refunds if the exception escaped before _execute_reserved_run ran.
        logger.error("job %s failed: %s: %s", job_id, type(e).__name__, e)  # no token/secret
```

Key rules (all mandated by §16.2):
- **Never fixture content on failure** — `mark_failed` writes only an honest error string; `result` stays null. The existing `_record_run` already emits a clean 503 for `LLMUnavailableError` with no fixture fallback `[VERIFIED-WITH-SOURCE: agents.py:582-589]`; the worker preserves that (no fallback path exists).
- **Refund on failure** — reuses `quota_repo.refund_run(user_id)` `[VERIFIED-WITH-SOURCE: billing.py:502-514]`, already wired into every failure branch of `_execute_reserved_run` `[VERIFIED-WITH-SOURCE: agents.py:566,573,586,593]`.
- **No re-raise for permanent errors** — business/validation/LLM-permanent exceptions are swallowed after marking failed, so ARQ does not retry with the same bad input. Only a narrow `_TransientError` set (Redis/DB connection, transient upstream) is re-raised for ARQ retry. `[INFERRED]`
- **No secret logging** — the worker logs `type(e).__name__` + message only; credentials/tokens are never in the message path (the credential context resolves internally `[VERIFIED-WITH-SOURCE: agents.py:562]`). Matches the token-never-logged constraint.

### 4.4 LLM budget seconds in worker context (more generous than HTTP)

HTTP budgets are tuned to the ~100 s edge ceiling: `AETHER_LLM_BUDGET_SECONDS` default 180 but **65 s in production** `[VERIFIED-WITH-SOURCE: apps/api/app/services/llm_client.py:107-121, comment :131]`, cover default 88 s `[VERIFIED-WITH-SOURCE: llm_client.py:126-154]`, and the pipeline squeezes tailor+coverLetter into ONE `shared_budget()` to stay under the edge `[VERIFIED-WITH-SOURCE: agents.py:962-971]`. **The worker has no HTTP edge** — it should be more generous. Recommendation `[INFERRED]`: add worker-only env vars consumed by a `_wrap_worker_budget` that wraps execution in `shared_budget(seconds)` (the mechanism already accepts an explicit value `[VERIFIED-WITH-SOURCE: llm_client.py:88-105]`):
- `AETHER_LLM_WORKER_BUDGET_SECONDS` default **300** (tailor / single generation)
- `AETHER_LLM_WORKER_COVER_BUDGET_SECONDS` default **300** (cover letter)
- pipeline shared budget default **480** (both metered steps)

These MUST stay below `job_timeout=600` so ARQ never kills a job mid-budget. Because they are separate env vars, the worker's generosity never leaks into the HTTP request path. `[INFERRED]`

---

## 5. systemd `aether-worker.service`

Matches the observed aether-api convention: `/opt/abacus-python` venv, repo-root `.env` via a wrapper (`start-worker.sh` mirroring `start-api.sh` `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §2]`), file logs under `/var/log/aether/`, `Restart=always`, ordered after Redis.

`/etc/systemd/system/aether-worker.service`:
```ini
[Unit]
Description=Aether ARQ Worker (async background generation)
After=network-online.target redis-server.service aether-api.service
Wants=network-online.target
Requires=redis-server.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/github_repos/aether-job-career-agent/apps/api
ExecStart=/home/ubuntu/github_repos/aether-job-career-agent/start-worker.sh
Restart=always
RestartSec=5
StandardOutput=append:/var/log/aether/worker.log
StandardError=append:/var/log/aether/worker.log

[Install]
WantedBy=multi-user.target
```

`start-worker.sh` (reuses the EXACT `.env` parse block from `start-api.sh` — base64-padding/quote-safe — then execs arq):
```bash
#!/bin/bash
export PATH="/opt/abacus-python/bin:/usr/local/bin:/usr/bin:/bin"
cd /home/ubuntu/github_repos/aether-job-career-agent/apps/api
while IFS= read -r line || [ -n "$line" ]; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  key="${line%%=*}"; value="${line#*=}"
  value="${value#\"}"; value="${value%\"}"; value="${value#\'}"; value="${value%\'}"
  export "$key"="$value"
done < /home/ubuntu/github_repos/aether-job-career-agent/.env
exec /opt/abacus-python/bin/arq app.workers.settings.WorkerSettings
```

Why a wrapper, not `EnvironmentFile=` (deviation from the task's phrasing): the `.env` is at **repo root** (not `apps/api/.env`) and aether-api itself loads it via this exact bash parser, which handles base64 padding and quoted values that systemd's simpler `EnvironmentFile` parser can mangle — using the same parser guarantees the worker resolves identical credentials/budgets/DATABASE_URL with zero drift. `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §2 (start-api.sh body), §8 (.env at repo root, 600)]`

Ordering: `Requires=redis-server.service` + `After=redis-server.service` so Redis is up before the worker connects; `Restart=always`/`RestartSec=5` self-heals a crashed worker. `[INFERRED]`

---

## 6. Frontend polling spec (§16.2)

### 6.1 Components that change
Client layer: `apps/web/src/lib/api/agents.ts` (`runAgent`, `runPipeline`) `[VERIFIED-WITH-SOURCE: apps/web/src/lib/api/agents.ts:38-64]`, `apps/web/src/lib/api/resumes.ts` (`runTailorAgent`) `[VERIFIED-WITH-SOURCE: resumes.ts:107]`, `apps/web/src/lib/api/coverLetters.ts` (`runCoverLetterAgent`) `[VERIFIED-WITH-SOURCE: coverLetters.ts:29-37]`.
Call sites (page components): `dashboard/agents/page.tsx:166,194` (pipeline + generic run) `[VERIFIED-WITH-SOURCE]`, `dashboard/cover-letters/page.tsx:132,147` `[VERIFIED-WITH-SOURCE]`, `dashboard/resume/page.tsx:75` (button `data-testid="run-tailor-btn"` :152) `[VERIFIED-WITH-SOURCE]`, `dashboard/jobs/page.tsx:388` (inline `/agents/tailor/run`) `[VERIFIED-WITH-SOURCE]`.

Add one shared helper `pollJob(job_id)` (in `lib/api/agents.ts`) + a `useBackgroundJob` hook; each call site swaps its single `await run...()` for `enqueue → poll → render`.

### 6.2 202 handling / poll loop / terminal states
- Response detection: **response has `job_id` && `status==='enqueued'`** → enter polling; otherwise treat as a legacy synchronous result and render immediately (backward-compat — §6.3). `[INFERRED]`
- Show a "Processing…" state on the triggering surface, keep the run button disabled.
- Poll `GET /api/agents/jobs/{job_id}` **every 3 s** (§16.2 / J3 step 2).
- `processing` → keep spinner; `completed` → render `result`, stop; `failed` → show the honest `error` string (not a generic message, not fabricated output), stop.
- **Client cap: 10 min** (~200 polls). On cap: stop polling, honest copy — *"This is taking longer than expected. Your run is still processing in the background — it will appear in your Agents activity shortly."* (honest: the BackgroundJob persists and the worker may still finish; do not claim failure). `[INFERRED]`

### 6.3 Backward-compat during deploy
- Frontend ships the dual-shape handler (§6.2) BEFORE the flag flips; while `AETHER_ASYNC_GENERATION` is OFF the endpoints still return the legacy 200 body and the frontend renders it inline — no polling, no behavior change. `[INFERRED]`
- An in-flight synchronous request during an API restart resolves or errors normally (unchanged from today).
- An async job enqueued just before an aether-api restart is unaffected: the `BackgroundJob` row (Postgres) + the ARQ entry (Redis) + the worker (separate process) all survive an api restart; the client simply keeps polling `GET /api/agents/jobs/{id}` across the restart. `[INFERRED]`

---

## 7. Migration / rollout, rollback, failure modes, soak

### 7.1 Feature flag decision
`AETHER_ASYNC_GENERATION` — **code default OFF on first deploy; flipped ON in `.env` only after the production J3 soak passes.** `[INFERRED]` Justification: the async path introduces two brand-new hard dependencies (Redis + worker). Shipping default-ON couples all generation availability to them on day one; default-OFF lets us land table + worker + Redis + code with zero user-facing change, verify the worker drains a canary, then flip via a one-line atomic `.env` edit + `systemctl restart aether-api` (no redeploy). Changing the **code** default to ON is a follow-up PR once the async path has soaked in production for the phase.

### 7.2 Rollout order
1. `arq`,`redis` → `requirements.txt`; `pip install` into `/opt/abacus-python`.
2. Provision Redis (§1.3) — apt install, config, `AETHER_REDIS_PASSWORD`/`AETHER_REDIS_URL` written to `.env` (atomic, 600), `enable --now redis-server`, `ping` PONG.
3. Additive DDL (§2) via `migrator` (`CREATE ... IF NOT EXISTS`).
4. Deploy worker code + `start-worker.sh` + `aether-worker.service`; `enable --now aether-worker` (idle while flag OFF).
5. Deploy API code (enqueue path + `GET /agents/jobs/{id}` behind the flag, default OFF) + frontend dual-shape polling (dormant).
6. Verify: temporarily set flag ON, enqueue one tailor job → 202 → poll → completed with `tokensIn>0` + no fixture fingerprint; force a failure → quota refunded; confirm worker picks up in `/var/log/aether/worker.log`.
7. Run the **J3 20-run soak** (§7.5). On pass, flip `AETHER_ASYNC_GENERATION=true` in `.env` (atomic, 600) + `systemctl restart aether-api`. Monitor.

### 7.3 Rollback (instant, no redeploy)
Set `AETHER_ASYNC_GENERATION=false` in `.env` + `systemctl restart aether-api` → endpoints revert to the synchronous 200 path immediately. Worker + Redis may keep running idle; the additive `BackgroundJob` table is harmless and stays. `[INFERRED]`

### 7.4 Failure modes + watchdog
- **Redis down at enqueue** → compensate (refund + BackgroundJob failed) + honest 503; never a silent success (§3.2 step 5). Operator can flip the flag OFF if chronic.
- **Worker dead → jobs stuck `enqueued`** → dual watchdog: (a) **lazy on GET** — a poll of a job older than the staleness threshold atomically marks it `failed` + refunds, so a polling user always reaches a terminal state even with a dead worker; (b) **ARQ cron `sweep_stale_jobs`** every 5 min refunds/fails abandoned jobs nobody polls (bounds quota leakage). `systemd Restart=always` shrinks the dead-worker window. `[INFERRED]`
- **Worker crash mid-job** → ARQ re-queues only for re-raised transient errors; the lazy/cron watchdog covers a process that died before writing failure; quota is refunded exactly once (`refund_run` floors at 0 `[VERIFIED-WITH-SOURCE: billing.py:509-513]`).
- **DB down in worker** → transient → ARQ retry; watchdog backstops.
- Thresholds `[INFERRED]`: `enqueued` stale > 15 min; `processing` stale > 12 min (> `job_timeout`/… but < 15). Tunable via `AETHER_JOB_STALE_SECONDS`.

### 7.5 J3 soak plan (Journey J3, §12)
Script (evidence agent, production, temp QA subscription): POST `tailor/run` (and `pipeline/run`) **20×**, collect every 202, poll each `GET /api/agents/jobs/{id}` @3 s to a terminal state; assert **zero HTTP 503** across all enqueue+poll calls (GATE-11/12/13); assert each `completed` job has `tokensIn>0` + zero fixture fingerprints (reuse the fingerprint set from `probe-p7-04c`); one forced model failure → assert `UsageQuota.runsUsed` not net-incremented (refund). Evidence: `journey-j3-tailor-202.json`, `journey-j3-poll-sequence.json`, `journey-j3-soak-20-results.json`, `journey-j3-pipeline-202-fast.json`, `journey-j3-worker-logs.txt`, `journey-j3-quota-refund.json`. `[VERIFIED-WITH-SOURCE: §12 J3 steps 1-8]`

---

## 8. Test list (§16.3) mapped to files + Redis-free coverage

File: **`apps/api/tests/test_gap_p7_async_001.py`** (dir confirmed `[VERIFIED-WITH-SOURCE: apps/api/tests/conftest.py present]`). Paywall/quota toggled in tests via `AETHER_REQUIRE_PAID_SUBSCRIPTION` `[VERIFIED-WITH-SOURCE: apps/api/app/repositories/billing.py:312-323]`.

Unit-testable **without Redis** by injecting a `FakeArqPool` (records `enqueue_job` calls, returns a fake id) into the enqueue path, and by invoking the worker task function **directly** with a hand-built `ctx` dict + a stubbed LLM client (ARQ ships no in-memory broker, so we hand-roll the double):

| §16.3 test | File symbol | Redis? |
|---|---|---|
| tailor run → 202 not 200 | `test_tailor_run_returns_202_not_200` | No (FakeArqPool) |
| pipeline run → 202 not 200 | `test_pipeline_run_returns_202_not_200` | No |
| status transitions enqueued→completed | `test_job_status_polling_transitions` | No (call task fn directly) |
| quota reserved AT ENQUEUE (before completion) | `test_quota_reserved_at_enqueue_not_at_completion` | No |
| quota refunded on worker failure | `test_quota_refunded_on_worker_failure` | No |
| no fixture content in failed job result | `test_no_fixture_content_in_failed_job_result` | No |
| honest error body on failure | `test_honest_error_body_on_worker_failure` | No |
| worker does not re-raise permanent errors (no retry-with-bad-input) | `test_worker_does_not_reraise_permanent_error` | No |
| paywall 402 BEFORE enqueue (no row, no reserve) | `test_paywall_402_before_enqueue` | No |
| Redis-unavailable at enqueue → 503 + refund | `test_redis_unavailable_returns_503_and_refunds` | No (stub raises) |
| stale-job watchdog marks failed + refunds | `test_stale_job_watchdog_marks_failed_and_refunds` | No |
| 20 concurrent enqueues → all 202 (soak, mocked) | `test_20_concurrent_runs_zero_503` | No (FakeArqPool) |

The **real** 20-run zero-503 end-to-end (enqueue→Redis→worker→complete) is the **production J3 soak** (§7.5), run by `evidence`/`qa` against live Redis+worker — not a unit test. An optional CI integration test against a real local Redis is possible but not gate-blocking. `[INFERRED]`

---

## 9. Security constraints (§19)

- **No token/secret logging** — worker logs `type(e).__name__` + message only; credential resolution is internal to `user_credential_context` `[VERIFIED-WITH-SOURCE: agents.py:562]`; the existing billing audit already records only `credentialSource/authMode/provider`, never the token `[VERIFIED-WITH-SOURCE: agents.py:421-425]`.
- **Atomic `.env` writes, 600 perms** — `AETHER_REDIS_URL`, `AETHER_REDIS_PASSWORD`, `AETHER_ASYNC_GENERATION`, and the worker budget vars are added by writing a temp file then `os.replace()` (atomic) and `chmod 600`, preserving the existing `-rw-------` `.env` `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §8]`.
- **Redis not internet-exposed** — bound to `127.0.0.1` + `requirepass`; nginx proxies only `/` and `/api/` `[VERIFIED-WITH-SOURCE: step2-infra-check.txt §10]`, never Redis.
- **No fixture content in any production path** — worker failure writes only honest errors (§4.3); no fallback fixture branch exists `[VERIFIED-WITH-SOURCE: agents.py:582-589]`.
- **No silent credential-type fallthrough / no silent sync fallthrough** — Redis-down returns an honest 503, never a silent degrade (§3.2).
- **Additive-only DDL** — `CREATE TABLE/INDEX IF NOT EXISTS` only; no DROP/destructive ALTER (§2).

---

## 10. Files touched (for the fixer, post-approval — arch writes none)

- `apps/api/requirements.txt` (+arq, +redis)
- `apps/api/app/repositories/background_jobs.py` (NEW — `BackgroundJobRepository` + `_ensure_table`)
- `apps/api/app/workers/__init__.py`, `settings.py`, `tasks.py` (NEW)
- `apps/api/app/routers/agents.py` (refactor `_dispatch`→`_agent_callable`+`_execute_reserved_run`; 202 enqueue path; `GET /agents/jobs/{id}`; enqueue-flag)
- `apps/api/app/services/llm_client.py` (worker budget getters)
- `apps/web/src/lib/api/agents.ts` (+`pollJob`, dual-shape) + `resumes.ts`/`coverLetters.ts` + 4 page call sites (§6.1)
- `start-worker.sh` (NEW), `/etc/systemd/system/aether-worker.service` (NEW — deployer)
- Redis: apt package + `/etc/redis/redis.conf.d/aether.conf` (deployer)
- `.env` (+`AETHER_REDIS_URL`,`AETHER_REDIS_PASSWORD`,`AETHER_ASYNC_GENERATION`, worker budgets) + `.env.example`
- Migration: additive DDL via `migrator`
- Tests: `apps/api/tests/test_gap_p7_async_001.py`

---

## 11. Recorded deviations from §16 draft (with justification)

| # | §16 draft said | Blueprint uses | Why |
|---|---|---|---|
| D1 | venv `apps/api/venv/bin/arq` | `/opt/abacus-python/bin/arq` | Observed venv `[step2-infra-check.txt §7]` |
| D2 | logs `/tmp/aether-worker.log` | `/var/log/aether/worker.log` | Observed log convention `[§ Log Section]` |
| D3 | `EnvironmentFile=apps/api/.env` | `start-worker.sh` parsing **repo-root** `.env` | `.env` at repo root + api uses the same bash parser `[§2,§8]` |
| D4 | `redis.service` | `redis-server.service` | Ubuntu package unit name |
| D5 | `GET /api/jobs/{id}` | `GET /api/agents/jobs/{id}` | Collision with job-listings `GET /jobs/{id}` `[jobs.py:5, main.py:140]` |
| D6 | single reserve-at-enqueue (all endpoints) | single-agent: reserve at enqueue; **pipeline: paywall-at-enqueue + per-step reserve in worker** | Pipeline metered count is data-dependent `[agents.py:940-971]` |
| D7 | no password mentioned | Redis `requirepass` via `.env` + db 3 | VM is shared across projects/sessions (global instructions) |
| D8 | HTTP budgets reused | separate `AETHER_LLM_WORKER_BUDGET_SECONDS` (300/480) | Worker has no HTTP edge; HTTP budgets are edge-tuned (65 s prod) `[llm_client.py:107-154]` |

---

**APPROVAL GATE:** This blueprint requires explicit fable-5 approval (§19 STEP-6) before any TDD/implementation. arch writes no production fix code.
