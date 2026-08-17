-- 0031_email_thread_last_message_at.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/services/gmail_service.py::ensure_email_thread_last_message_column()
-- run under transaction-scoped advisory lock 7420260822. This file exists so the
-- schema change is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: ADD COLUMN IF NOT EXISTS. No DROP / no ALTER TYPE / no rename.
--
-- Email Center recency: `lastMessageAt` is the Gmail message time (internalDate
-- / RFC2822 Date). Sorting by `updatedAt` previously put freshly-triaged old
-- personal mail above today's interview invites.

ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "lastMessageAt" timestamptz;
CREATE INDEX IF NOT EXISTS "idx_emailthread_last_message"
  ON "EmailThread" ("userId", "lastMessageAt" DESC);
