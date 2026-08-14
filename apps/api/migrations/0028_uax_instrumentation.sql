-- 0028_uax_instrumentation.sql — U-AX self-improvement instrumentation.
--
-- RECORD ONLY (documentary mirror). The API applies every statement below
-- additively and idempotently at runtime via lazy DDL (ADR-TR-1, "no migration
-- runner"):
--   * app.repositories.application_status_event.ensure_application_status_event_table
--   * app.db.ensure_application_submission_snapshot_columns
--   * app.repositories.agent_run.ensure_agent_run_link_columns
--   * app.repositories.agent_run.ensure_agent_run_policy_columns
--   * app.services.offers.ensure_offer_application_id_column
-- The Prisma-managed tables ("Application", "AgentRun", "ApplicationStatusEvent")
-- are ALSO declared in packages/db/src/schema.prisma so a Prisma push never
-- drops them. "Offer" is a lazily-created table with no Prisma model (0025).
--
-- WHY: the product could state a conversion rate (0 interviews / 202 submitted,
-- live-verified 2026-08-13) but could not attribute it to anything. There was
-- no status-transition history (only a current-snapshot "Application"."status"),
-- no record of what was actually submitted at the moment of submission, no link
-- from an AgentRun to the job/application it acted on, and no link from an offer
-- back to the application that produced it. Without those four facts a
-- self-improvement loop cannot honestly claim — or disprove — improvement.
--
-- ADDITIVE AND NON-DESTRUCTIVE: no existing column, type or row is altered.
--
-- BACKFILL POLICY (deliberate, and asymmetric — see each block):
--   * "ApplicationStatusEvent" gets ONE reconstructed genesis row per existing
--     application: toStatus = its real current status, fromStatus = NULL (the
--     prior status genuinely was never observed and is NOT guessed), at = its
--     own updatedAt, source = 'backfill:current-status' so the provenance is on
--     the row itself.
--   * The snapshot columns get NO backfill. Those measurements were never taken
--     at those submissions; reconstructing them today would score a historical
--     submission against today's résumé and today's engine, i.e. a fabricated
--     number wearing a historical timestamp. NULL means "not measured".

-- 1. Status-transition history -------------------------------------------
CREATE TABLE IF NOT EXISTS "ApplicationStatusEvent" (
    "id"            text PRIMARY KEY,
    "seq"           bigserial   NOT NULL,
    "applicationId" text        NOT NULL
        REFERENCES "Application"("id") ON DELETE CASCADE,
    "fromStatus"    text,
    "toStatus"      text        NOT NULL,
    "at"            timestamptz NOT NULL DEFAULT now(),
    "source"        text        NOT NULL
);

CREATE INDEX IF NOT EXISTS "idx_appstatusevent_app_at"
    ON "ApplicationStatusEvent" ("applicationId", "at", "seq");

-- Genesis backfill (runs once, inside the same locked transaction as the
-- CREATE in the lazy-DDL path).
INSERT INTO "ApplicationStatusEvent"
    ("id", "applicationId", "fromStatus", "toStatus", "at", "source")
SELECT md5(random()::text || clock_timestamp()::text),
       "id", NULL, "status"::text, COALESCE("updatedAt", "createdAt"),
       'backfill:current-status'
FROM "Application";

-- 2. Submit-time snapshots ------------------------------------------------
ALTER TABLE "Application"
    ADD COLUMN IF NOT EXISTS "atsScoreAtSubmission" double precision;
ALTER TABLE "Application"
    ADD COLUMN IF NOT EXISTS "tailoredResumeVersionId" text;
ALTER TABLE "Application"
    ADD COLUMN IF NOT EXISTS "dimensionScoresAtSubmission" jsonb;
ALTER TABLE "Application"
    ADD COLUMN IF NOT EXISTS "policyTierAtSubmission" text;

-- 3. AgentRun -> job/application links + per-run rigor policy -------------
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "applicationId" text;
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "jobId" text;
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "policyTier" text;
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "metricSnapshot" jsonb;

CREATE INDEX IF NOT EXISTS "AgentRun_jobId_idx" ON "AgentRun" ("jobId");

-- 4. Offer -> originating application -------------------------------------
ALTER TABLE "Offer" ADD COLUMN IF NOT EXISTS "applicationId" text;
