-- 0030_agent_directive.sql — B1b: AgentDirective (ADR-AGI-2 P1).
--
-- RECORD ONLY (documentary mirror). The API applies every statement below
-- additively and idempotently at runtime via lazy DDL (ADR-TR-1, "no
-- migration runner"):
--   * app.repositories.agent_directive.ensure_agent_directive_table
--   * advisory lock 7420260816
--
-- NOT mirrored in packages/db/src/schema.prisma (a documented DEVIATION from
-- the blueprint's §2.0 claim that every lazy-DDL table gets a Prisma mirror):
-- verified against the CURRENT tree that "Offer", "BackgroundJob",
-- "AnswerBank" and "UsageQuota" — every other no-FK-to-User, audit-row-style
-- lazy-DDL table — are ALSO absent from schema.prisma. The real, live
-- convention on this branch is that a table with no `user User @relation`
-- (the TRUNCATE-safety design every one of these tables shares) never enters
-- Prisma's schema at all; only tables that DO carry that relation (User,
-- Job, Application, AgentRun, ...) get Prisma-managed columns. This file
-- follows that verified precedent rather than the blueprint's stale one.
--
-- WHY: ADR-AGI-2 ("Directed Improvement") makes the Supervisor an
-- improvement DIRECTOR — it reads the metrics surface, diagnoses per-agent
-- performance, and issues bounded, whitelisted, ratcheted AgentDirective
-- rows that amend an agent's rigor policy for a window. See
-- ORCH-B1-BLUEPRINT-2026-08-14.md §2.2/§6 for the whitelist and ratchet
-- arithmetic, and ADR-AGI-2 itself
-- (uat/reports/evidence/market-perf/u-agi/ADR-AGI-2-DIRECTED-IMPROVEMENT.md)
-- for the guardrails this schema encodes structurally:
--
--   * IMMUTABLE HISTORY — no UPDATE of "directive"/"rationale"/"metricsCited"
--     is ever issued by the repository; a directive is superseded, never
--     edited or deleted.
--   * ONE ACTIVE DIRECTIVE PER (user, agent) — a DB fact via the partial
--     unique index below, not a convention.
--   * HONESTY GATES / SPEND CAPS / APPROVAL GATES ARE NOT REPRESENTABLE HERE
--     — "directive" carries only whitelisted numeric/enum knobs (§6.1); the
--     schema makes credential material and gate thresholds structurally
--     unrepresentable rather than merely filtered at write time.
--
-- ADDITIVE AND NON-DESTRUCTIVE: no existing table, column or row is altered.
--
-- No FK to "User" (matches BackgroundJob/Offer/UsageQuota) so the shared
-- test-suite's TRUNCATE "User" never trips, and a deleted user's directive
-- history is never silently made un-queryable.
--
-- BACKFILL POLICY: NONE, and none is correct. A new table has no history to
-- invent — no pre-existing AgentRun was ever governed by a directive.

CREATE TABLE IF NOT EXISTS "AgentDirective" (
    "id"             text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"         text        NOT NULL,
    "agentKey"       text        NOT NULL,   -- a _RUNNABLE_BACKENDS member; validated in Python, never a FK
    "directive"      jsonb       NOT NULL,   -- ONLY whitelisted keys survive the writer (§6)
    "clamped"        jsonb,                  -- {field: {requested, applied, reason}} for every value the kernel altered
    "rejectedKeys"   jsonb,                  -- un-whitelisted keys the issuer attempted, recorded loudly
    "rationale"      text        NOT NULL,   -- human-readable, cites the metrics that caused it
    "metricsCited"   jsonb       NOT NULL,   -- the metric snapshot the decision was made on
    "issuedBy"       text        NOT NULL DEFAULT 'supervisor-rules',  -- 'supervisor-rules' | 'supervisor-llm' (P2) | 'operator'
    "status"         text        NOT NULL DEFAULT 'active',            -- 'active' | 'superseded' | 'expired'
    "supersededById" text,                   -- set on the OLD row when a new one replaces it
    "outcome"        jsonb,                  -- P1 writes adherence + observed deltas; P2 scores efficacy
    "issuedAt"       timestamptz NOT NULL DEFAULT now(),
    "expiresAt"      timestamptz,            -- NULL = until superseded
    "createdAt"      timestamptz NOT NULL DEFAULT now(),
    "updatedAt"      timestamptz NOT NULL DEFAULT now()
);

-- The invariant that makes "one active directive per (user, agent)" a DB fact
-- rather than a convention. Partial, so superseded history is unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS "AgentDirective_active_key"
    ON "AgentDirective" ("userId", "agentKey") WHERE "status" = 'active';

CREATE INDEX IF NOT EXISTS "AgentDirective_user_agent_issued_idx"
    ON "AgentDirective" ("userId", "agentKey", "issuedAt" DESC);

CREATE INDEX IF NOT EXISTS "AgentDirective_status_expires_idx"
    ON "AgentDirective" ("status", "expiresAt");
