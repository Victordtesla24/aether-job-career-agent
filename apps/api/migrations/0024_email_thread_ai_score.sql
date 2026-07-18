-- 0024_email_thread_ai_score.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL is
-- the lazy idempotent DDL in:
--   apps/api/app/services/gmail_service.py::ensure_email_thread_ai_columns()
-- run under transaction-scoped advisory lock 7420240717. This file exists so the
-- schema change is reviewable as plain SQL; it is never applied by a tool.
--
-- Additive only: ADD COLUMN IF NOT EXISTS. No DROP / no ALTER TYPE / no rename,
-- so it is backward-compatible and survives TRUNCATE.
--
-- MV-email-center-001: `aiScore` persists the integer 0-100 triage score the
-- EmailAgent produces per thread, so the Email Command Center list surfaces the
-- REAL per-thread score instead of a hardcoded 0. It is nullable and stays NULL
-- until a thread is actually triaged — an un-triaged thread has NO score (never
-- a fabricated 0).

ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "aiScore" integer;
