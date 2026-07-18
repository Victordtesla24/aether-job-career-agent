-- 0025_offers.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/services/offers.py::_ensure_offers_table()
-- run under the transaction-scoped advisory lock 7420240724. This file exists so
-- the Offer schema is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: CREATE TABLE / INDEX IF NOT EXISTS. No DROP / no ALTER TYPE /
-- no rename. No FK to "User" (shared-test-DB TRUNCATE safety, matching
-- AdminAuditLog / UsageQuota / BackgroundJob).
--
-- MV-offer-comparison-001 — persist user-entered offers so "Add Offer" is a real
-- backend write instead of ephemeral client state. The Offer Comparison payload
-- (GET /workspaces/offers, GET /offers) UNIONs these manual rows with the
-- derived Application(status='offer') offers. Manual offers carry no fitScore
-- (shown as "Pending") and are never the "Top pick".

CREATE TABLE IF NOT EXISTS "Offer" (
    "id"        text        PRIMARY KEY,          -- cuid-shaped (app.db.new_id)
    "userId"    text        NOT NULL,             -- owner; every read/write is scoped to it
    "company"   text        NOT NULL,
    "role"      text,
    "base"      integer     NOT NULL,             -- annual base (>0, enforced at the API)
    "bonus"     integer     NOT NULL DEFAULT 0,
    "equity"    integer     NOT NULL DEFAULT 0,
    "location"  text        NOT NULL,
    "currency"  text        NOT NULL DEFAULT 'AUD', -- user-selected ISO code (no fabricated default)
    "createdAt" timestamptz NOT NULL DEFAULT now(),
    "updatedAt" timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "idx_offer_userId" ON "Offer" ("userId");
