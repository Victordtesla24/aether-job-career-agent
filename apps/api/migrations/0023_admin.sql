-- 0023_admin.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/db.py::ensure_admin_user_columns()               (User columns)
--   apps/api/app/repositories/admin.py::_ensure_admin_schema()    (AdminSetting + ip)
-- run under transaction-scoped advisory locks 7420240720 / 7420240721. This file
-- exists so the admin schema is reviewable as plain SQL; it is never applied by a
-- tool.
--
-- Additive only: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS. No DROP /
-- no ALTER TYPE / no rename. AdminAuditLog itself is created by the billing spine
-- (0022_billing.sql); this file only adds its "ip" column. No FK to "User"
-- (shared-test-DB TRUNCATE safety).
--
-- Cluster F — Admin Tier 1 (§15) + SEC-001 (§14.7 rotation). Per-user LLM spend
-- is SUM("AgentRun"."costUsd") in USD (LLM providers bill USD — never AUD).

-- ===================== User privilege / security columns ================
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "isAdmin"    boolean NOT NULL DEFAULT false; -- admin gate (GAP-P6-ADMIN-001)
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "suspended"  boolean NOT NULL DEFAULT false; -- 403 on auth routes when true (§15)
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "lastLoginAt" timestamptz;                    -- admin user list (§15)

-- ===================== AdminSetting (signup/email toggles) ==============
CREATE TABLE IF NOT EXISTS "AdminSetting" (
    "key"       text PRIMARY KEY,          -- 'signup_enabled' | 'email_verification_enabled'
    "value"     jsonb       NOT NULL,       -- JSON-encoded value (bool today)
    "updatedAt" timestamptz NOT NULL DEFAULT now()
);

-- ===================== AdminAuditLog.ip (append-only sink) ==============
-- AdminAuditLog is created in 0022_billing.sql; §15 additionally records the
-- request IP on every admin action.
ALTER TABLE "AdminAuditLog" ADD COLUMN IF NOT EXISTS "ip" text;
