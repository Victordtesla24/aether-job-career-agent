-- 0028_password_reset.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/services/password_reset.py::_ensure_password_reset_table()
--     (table + indexes, advisory lock 7420260806)
--   apps/api/app/db.py::ensure_password_reset_columns()
--     ("User"."passwordChangedAt", advisory lock 7420260805)
-- run under those transaction-scoped advisory locks. This file exists so the
-- schema is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: CREATE TABLE / INDEX IF NOT EXISTS, ADD COLUMN IF NOT EXISTS.
-- No DROP / no ALTER TYPE / no rename. No FK to "User" on
-- "PasswordResetToken" (shared-test-DB TRUNCATE safety, matching
-- Offer/AdminAuditLog/UsageQuota).
--
-- O-4 (day-one-blocker) — self-service password reset. Tokens are single-use
-- and hashed at rest (sha256); the raw value is never persisted, only handed
-- to the outbound email at issuance time. "User"."passwordChangedAt" is the
-- session-invalidation mechanism: a JWT whose iat predates it is rejected by
-- app.middleware.auth.get_current_user, forcing a fresh login with the new
-- password.

CREATE TABLE IF NOT EXISTS "PasswordResetToken" (
    "id"        text        PRIMARY KEY,          -- cuid-shaped (app.db.new_id)
    "userId"    text        NOT NULL,             -- owner; no FK (TRUNCATE safety)
    "tokenHash" text        NOT NULL,             -- sha256 hex of the raw token
    "expiresAt" timestamptz NOT NULL,              -- issuance + 1 hour
    "usedAt"    timestamptz,                       -- NULL until consumed
    "createdAt" timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS "idx_password_reset_token_hash"
    ON "PasswordResetToken" ("tokenHash");
CREATE INDEX IF NOT EXISTS "idx_password_reset_token_userId"
    ON "PasswordResetToken" ("userId");

ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "passwordChangedAt" timestamptz;
