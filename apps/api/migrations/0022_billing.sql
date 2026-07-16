-- 0022_billing.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in
--   apps/api/app/repositories/billing.py::_ensure_billing_tables()
-- run under transaction-scoped advisory lock 7420240719. This file exists so the
-- billing spine schema is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
-- CREATE UNIQUE INDEX IF NOT EXISTS. No DROP / no ALTER TYPE / no rename.
-- No FK to "User" (shared-test-DB TRUNCATE safety); userId columns are text.
--
-- Ratified tiers (ADR-P6-PRICING; NOT the design's proposals):
--   Free    A$0    / —      / 5   runs / spend cap USD $1
--   Starter A$19   / A$179  / 30  runs / spend cap USD $5
--   Pro     A$39   / A$359  / 100 runs / spend cap USD $15
--   Power   A$69   / A$649  / 300 runs / spend cap USD $40
-- GST (GST-inclusive): gst = round(total/11, 2); net = total - gst.

-- ============================ Plan (catalog) ============================
CREATE TABLE IF NOT EXISTS "Plan" (
    "id"                   text PRIMARY KEY,              -- 'free'|'starter'|'pro'|'power'
    "name"                 text        NOT NULL,
    "priceAudMonthly"      numeric     NOT NULL DEFAULT 0,  -- GST-inclusive AUD
    "priceAudAnnual"       numeric,                          -- GST-inclusive AUD; NULL for Free
    "runsPerMonth"         integer     NOT NULL,             -- metered (LLM) runs / period
    "modelTier"            text        NOT NULL
        CHECK ("modelTier" IN ('light','standard','advanced','premium')),
    "spendCapUsdMonthly"   numeric     NOT NULL,             -- USD safety ceiling (admin, USD)
    "stripeProductId"      text,                             -- filled by human after Stripe setup
    "stripePriceIdMonthly" text,
    "stripePriceIdAnnual"  text,
    "active"               boolean     NOT NULL DEFAULT true,
    "sortOrder"            integer     NOT NULL DEFAULT 0,
    "createdAt"            timestamptz NOT NULL DEFAULT now(),
    "updatedAt"            timestamptz NOT NULL DEFAULT now()
);

-- ========================= Subscription (per user) ======================
CREATE TABLE IF NOT EXISTS "Subscription" (
    "id"                   text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"               text        NOT NULL,             -- User.id (text); no FK by design
    "planId"               text        NOT NULL,             -- logical ref to Plan.id
    "status"               text        NOT NULL DEFAULT 'active'
        CHECK ("status" IN ('active','trialing','past_due','canceled',
                            'incomplete','incomplete_expired','unpaid','paused')),
    "billingInterval"      text        CHECK ("billingInterval" IN ('month','year')),  -- NULL for Free
    "stripeCustomerId"     text,
    "stripeSubscriptionId" text,
    "currentPeriodStart"   timestamptz,
    "currentPeriodEnd"     timestamptz,
    "cancelAtPeriodEnd"    boolean     NOT NULL DEFAULT false,
    "createdAt"            timestamptz NOT NULL DEFAULT now(),
    "updatedAt"            timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_userId_key"
    ON "Subscription" ("userId");
CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_stripeSubscriptionId_key"
    ON "Subscription" ("stripeSubscriptionId")
    WHERE "stripeSubscriptionId" IS NOT NULL;

-- ===================== UsageQuota (per user, rolling) ===================
CREATE TABLE IF NOT EXISTS "UsageQuota" (
    "id"            text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"        text        NOT NULL,
    "planId"        text        NOT NULL,
    "periodStart"   timestamptz NOT NULL,
    "periodEnd"     timestamptz NOT NULL,
    "runsAllowed"   integer     NOT NULL,
    "runsUsed"      integer     NOT NULL DEFAULT 0,
    "spendCapUsd"   numeric     NOT NULL,                    -- USD ceiling for the period
    "spendUsedUsd"  numeric     NOT NULL DEFAULT 0,          -- USD from AgentRun.costUsd
    "createdAt"     timestamptz NOT NULL DEFAULT now(),
    "updatedAt"     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS "UsageQuota_userId_key"
    ON "UsageQuota" ("userId");

-- ================ StripeEvent (transaction-safe idempotency) ============
CREATE TABLE IF NOT EXISTS "StripeEvent" (
    "id"          text PRIMARY KEY,                          -- Stripe event id == idempotency key
    "type"        text        NOT NULL,
    "status"      text        NOT NULL DEFAULT 'processing'
        CHECK ("status" IN ('processing','processed','failed','ignored')),
    "payloadJson" jsonb,
    "receivedAt"  timestamptz NOT NULL DEFAULT now(),
    "processedAt" timestamptz
);

-- ===================== AdminAuditLog (Cluster F sink) ===================
CREATE TABLE IF NOT EXISTS "AdminAuditLog" (
    "id"          text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "actorUserId" text        NOT NULL,
    "action"      text        NOT NULL,
    "targetType"  text,
    "targetId"    text,
    "detailJson"  jsonb,
    "createdAt"   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "AdminAuditLog_actor_idx"  ON "AdminAuditLog" ("actorUserId");
CREATE INDEX IF NOT EXISTS "AdminAuditLog_target_idx" ON "AdminAuditLog" ("targetType","targetId");

-- ============================ Plan seed (idempotent) ====================
INSERT INTO "Plan" ("id","name","priceAudMonthly","priceAudAnnual","runsPerMonth",
                    "modelTier","spendCapUsdMonthly","sortOrder")
VALUES
  ('free',    'Free',    0,   NULL, 5,   'light',    1.00, 0),
  ('starter', 'Starter', 19,  179,  30,  'standard', 5.00, 1),
  ('pro',     'Pro',     39,  359,  100, 'advanced', 15.00,2),
  ('power',   'Power',   69,  649,  300, 'premium',  40.00,3)
ON CONFLICT ("id") DO UPDATE SET
  "name"=EXCLUDED."name",
  "priceAudMonthly"=EXCLUDED."priceAudMonthly",
  "priceAudAnnual"=EXCLUDED."priceAudAnnual",
  "runsPerMonth"=EXCLUDED."runsPerMonth",
  "modelTier"=EXCLUDED."modelTier",
  "spendCapUsdMonthly"=EXCLUDED."spendCapUsdMonthly",
  "sortOrder"=EXCLUDED."sortOrder",
  "updatedAt"=now();

-- ==================== GATE-34 backfill (idempotent) =====================
INSERT INTO "Subscription" ("userId","planId","status","billingInterval","createdAt","updatedAt")
SELECT u."id", 'free', 'active', NULL, now(), now()
FROM "User" u
WHERE NOT EXISTS (SELECT 1 FROM "Subscription" s WHERE s."userId" = u."id");

INSERT INTO "UsageQuota" ("userId","planId","periodStart","periodEnd",
                          "runsAllowed","runsUsed","spendCapUsd","spendUsedUsd","createdAt","updatedAt")
SELECT u."id", 'free',
       date_trunc('month', now()),
       date_trunc('month', now()) + interval '1 month',
       (SELECT "runsPerMonth"       FROM "Plan" WHERE "id"='free'),
       0,
       (SELECT "spendCapUsdMonthly" FROM "Plan" WHERE "id"='free'),
       0, now(), now()
FROM "User" u
WHERE NOT EXISTS (SELECT 1 FROM "UsageQuota" q WHERE q."userId" = u."id");
