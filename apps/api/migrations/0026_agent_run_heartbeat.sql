-- 0026_agent_run_heartbeat.sql — CRITICAL-1 abandoned-AgentRun watchdog.
--
-- RECORD ONLY (documentary mirror). The API applies this additively and
-- idempotently at runtime via
-- ``app.repositories.agent_run.ensure_heartbeat_column`` — the same lazy-DDL
-- pattern 0020 uses for "AgentRun"."billingAuditJson" — so a deploy that has
-- not re-run Prisma still gets a working watchdog. The column is also declared
-- in packages/db/src/schema.prisma so a Prisma push never drops it.
--
-- WHY: production had ONE "tailor" AgentRun stuck at status='running' since
-- 2026-07-26 03:41:20 UTC — 192.6 hours (8 days) — with no process attached
-- (aether-worker was restarted 2026-08-03 00:17, which would have killed any
-- real job). Nothing ever reconciled a 'running' AgentRun row, so it survived
-- every restart and the dashboard kept presenting it as an ACTIVE run.
--
-- An executing run now stamps "heartbeatAt" every
-- AETHER_AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS (default 30s) from
-- app.services.agent_run_watchdog.agent_run_heartbeat, wired into the single
-- execution seam (routers.agents._execute_reserved_run) shared by the sync HTTP
-- path and the ARQ worker. The watchdog reconciles a run ONLY when that
-- liveness evidence is missing:
--   * heartbeatAt stale by > AETHER_AGENT_RUN_HEARTBEAT_STALE_SECONDS (300s
--     default = 10 missed stamps), regardless of total age; or
--   * heartbeatAt NULL (never stamped) AND older than
--     AETHER_AGENT_RUN_MAX_SECONDS (1800s default).
-- A genuinely live run keeps stamping and is therefore never reaped.
--
-- The 1800s default is derived from real observed durations, not guessed.
-- Across 3,984 completed production runs on 2026-08-03 the longest run ever
-- completed was 403.4s (fitScorer) and the worst per-agent p95 was 289.7s
-- (tailor); ARQ's own hard ceilings are job_timeout=600s and the board-sweep
-- func timeout=900s. 1800s is therefore 4.5x the longest completed run and 2x
-- ARQ's largest hard timeout.
--
-- Additive and non-destructive: no existing column or row is altered.

ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "heartbeatAt" timestamp;

CREATE INDEX IF NOT EXISTS "AgentRun_status_heartbeatAt_idx"
    ON "AgentRun" ("status", "heartbeatAt");
