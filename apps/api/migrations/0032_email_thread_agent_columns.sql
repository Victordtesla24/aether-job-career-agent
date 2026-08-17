-- 0032_email_thread_agent_columns.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/services/gmail_service.py::ensure_email_thread_agent_columns()
-- run under transaction-scoped advisory lock 7420260823. This file exists so the
-- schema change is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: ADD COLUMN IF NOT EXISTS. No DROP / no ALTER TYPE / no rename.
--
-- Email Agent ↔ Email Center: persist a review-only draft (`draftReply`) and
-- on-demand intelligence (`aiInsights`) so the UI can show recruiter replies
-- the human still has to approve. Nothing here implies a send.

ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "draftReply" text;
ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "draftReplyAt" timestamptz;
ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "aiInsights" jsonb;
