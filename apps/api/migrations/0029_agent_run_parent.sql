-- 0029_agent_run_parent.sql — B6: parentRunId causal traces.
--
-- RECORD ONLY (documentary mirror). The API applies every statement below
-- additively and idempotently at runtime via lazy DDL (ADR-TR-1, "no migration
-- runner"):
--   * app.repositories.agent_run.ensure_agent_run_parent_columns
-- The Prisma-managed table ("AgentRun") is ALSO declared in
-- packages/db/src/schema.prisma so a Prisma push never drops it.
--
-- WHY: the agents-console orchestration map drew stage-order edges only — an
-- explicit honesty-rule comment in both `orchestration-map-model.ts` and
-- `workflow-linkage.ts` said run-level causal traces "need a parent run id
-- the API does not record yet" and were deliberately not faked or stubbed
-- ahead of the data (ORCH-B1-BLUEPRINT-2026-08-14.md §4.4). This column is
-- that data: which AgentRun caused this one — e.g. every step
-- `_pipeline_core` dispatches now carries the pipeline's supervisor run's id.
--
-- ADDITIVE AND NON-DESTRUCTIVE: no existing column, type or row is altered.
--
-- BACKFILL POLICY: NONE, and none is correct. No historical run recorded a
-- cause (the column did not exist), so every pre-existing row's parentRunId
-- is NULL — the honest value. Inventing a parent for a historical run would
-- fabricate a causal fact nothing observed, which is exactly what this
-- column's consumer (the orchestration map's causal-edge layer) exists to
-- refuse to do.

ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "parentRunId" text;

CREATE INDEX IF NOT EXISTS "AgentRun_parentRunId_idx"
    ON "AgentRun" ("parentRunId") WHERE "parentRunId" IS NOT NULL;
