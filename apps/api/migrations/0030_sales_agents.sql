-- 0030_sales_agents.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/repositories/sales_agents.py::ensure_sales_agent_schema()
-- run under transaction-scoped advisory lock 7420260812. This file exists so the
-- ADMIN-2.0 BE-2 growth schema is reviewable as plain SQL; it is never applied
-- by a tool.
--
-- Additive only: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- ADD COLUMN IF NOT EXISTS. No DROP, no rename, no ALTER TYPE, and NO backfill
-- UPDATE — "User"."referredBy" is nullable with no default, so every
-- pre-existing account reads correctly as "not referred", which is exactly what
-- it is.
--
-- NO FOREIGN KEYS, deliberately (the same rule the billing spine follows):
-- "SalesAgent" has no FK to "User" and "User"."referredBy" has no FK to
-- "SalesAgent", so the shared aether_test schema's TRUNCATE ... CASCADE can
-- never reach across them, and deleting an account can never silently erase the
-- attribution history an agent's commission is computed from.
--
-- ADMIN-2.0 BE-2: sales agents (referral codes), signup attribution, the
-- commission report and the executive metrics endpoint. Nothing in this slice
-- adds a money-moving path: the commission report is arithmetic over payment
-- records that already exist.

-- ============================ SalesAgent ================================
-- A human reseller/affiliate. NEVER hard-deleted: a code that has been handed
-- out lives on in links and in the attribution history of every account it
-- brought in, so "remove this agent" is "status='inactive'" (the code stops
-- attributing at signup) and nothing else. The admin surface exposes no delete
-- route at all — DELETE /admin/sales-agents/{id} is a 405 by construction.
CREATE TABLE IF NOT EXISTS "SalesAgent" (
    "id"            text PRIMARY KEY,
    "name"          text        NOT NULL,
    "email"         text,                              -- optional contact
    "referralCode"  text        NOT NULL,              -- canonical UPPERCASE form
    "commissionPct" numeric     NOT NULL DEFAULT 0,    -- 0..100, validated at the router
    "status"        text        NOT NULL DEFAULT 'active',  -- 'active' | 'inactive'
    "notes"         text,
    "createdAt"     timestamptz NOT NULL DEFAULT now(),
    "updatedAt"     timestamptz NOT NULL DEFAULT now(),
    "createdBy"     text                               -- admin User.id (no FK by design)
);

-- Codes are stored uppercase and matched uppercase, so '?ref=jane-2026' and
-- '?ref=JANE-2026' resolve to the same agent. The unique index is the authority
-- on collisions: the INSERT uses ON CONFLICT DO NOTHING + an explicit raise, so
-- a duplicate is an honest 409 rather than a silently-ignored write.
CREATE UNIQUE INDEX IF NOT EXISTS "SalesAgent_referralCode_key"
    ON "SalesAgent" ("referralCode");

-- ===================== User.referredBy (attribution) ====================
-- SalesAgent.id stamped at signup when ?ref=<code> matched an ACTIVE agent.
-- NULL = "not referred" — the value for every pre-existing row and for every
-- signup without a code. The stamp is written only when the column is still
-- NULL (first attribution wins), so a later link cannot re-assign an account
-- that has already been credited to somebody.
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "referredBy" text;
CREATE INDEX IF NOT EXISTS "User_referredBy_idx" ON "User" ("referredBy");

-- ===================== Where the commission money comes from ============
-- No new payment table is introduced. There is none in this repo and inventing
-- one would create a second, drifting source of truth about money. The
-- commission report reads the payment records that already exist: the
-- signature-verified Stripe webhook payloads the billing spine persists in
-- "StripeEvent" (0022_billing.sql) —
--   invoice.paid     -> data.object.amount_paid      (money in, MINOR units)
--   charge.refunded  -> data.object.amount_refunded  (money back, CUMULATIVE
--                                                     per charge, so reduced
--                                                     with MAX, never summed)
-- attributed to a user through "Subscription"."stripeCustomerId". A plan price
-- or a local Subscription row is a claim about what SHOULD be charged, never
-- evidence that anybody paid, and is not used as such.
