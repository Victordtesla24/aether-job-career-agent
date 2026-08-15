-- 0029_admin2.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/db.py::ensure_user_lifecycle_columns()                (User columns)
--   apps/api/app/repositories/admin_billing.py::ensure_custom_price_columns()
-- run under transaction-scoped advisory locks 7420260810 / 7420260811. This file
-- exists so the ADMIN-2.0 schema is reviewable as plain SQL; it is never applied
-- by a tool.
--
-- Additive only: ADD COLUMN IF NOT EXISTS with safe defaults. No DROP, no
-- rename, no ALTER TYPE, no backfill UPDATE — every pre-existing row reads
-- correctly with the column's default (NULL = "not deleted" / "no custom
-- price"; false = "not an admin-generated credential").
--
-- ADMIN-2.0 BE-1: admin user CREATE/soft-DELETE, per-user custom pricing, the
-- local-vs-Stripe billing surface and the executive billing summary.

-- ===================== User lifecycle columns ===========================
-- Soft delete. A hard delete is NOT used: every child table (Job, Resume,
-- Application, AgentRun, Contact, EmailThread, StoryEntry) cascades from
-- "User"."id", so deleting the row would destroy the work the account produced
-- and orphan the billing/audit history that still references it. The delete
-- route stamps "deletedAt" AND sets "suspended" (the enforcement the auth
-- dependency already honours), so "deleted" genuinely revokes access.
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "deletedAt" timestamptz;

-- Set true when POST /admin/users creates an account with a generated temporary
-- password; cleared by UserRepository.set_password when the account's owner sets
-- a password of their own, so the flag is true for exactly as long as the
-- account is still on an admin-generated credential.
ALTER TABLE "User"
    ADD COLUMN IF NOT EXISTS "mustChangePassword" boolean NOT NULL DEFAULT false;

-- ===================== Subscription custom-price mirror =================
-- Stripe stays the source of truth for what a customer is actually charged.
-- These columns are the LOCAL MIRROR of an admin-negotiated amount, so the admin
-- surface and the billing summary can show it without a Stripe round trip per
-- row. NULL (every pre-existing row) means "no custom price" — the plan's
-- catalogue price applies, exactly as before ADMIN-2.0.
--
-- The write path (POST /admin/users/{id}/subscription/price) reprices the
-- EXISTING Stripe subscription in place with proration_behavior="none": no
-- second subscription (no double billing) and no immediate invoice (no surprise
-- charge) — the new amount applies from the next renewal.
ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "customPriceAud"      numeric;
ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "customPriceInterval" text;
ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "customPriceStripeId" text;
ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "customPriceSetAt"    timestamptz;
ALTER TABLE "Subscription" ADD COLUMN IF NOT EXISTS "customPriceSetBy"    text;
