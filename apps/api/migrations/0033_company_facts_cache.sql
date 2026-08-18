-- 0033_company_facts_cache.sql — DOCUMENTATION MIRROR ONLY (ADR-TR-1).
--
-- There is NO migration runner in this repo. The authoritative, executed DDL
-- is the lazy idempotent DDL in:
--   apps/api/app/repositories/company_facts.py::CompanyFactsRepository._ensure_table()
-- run under transaction-scoped advisory lock 7420260818. This file exists so
-- the schema change is reviewable as plain SQL; it is never applied by a tool.
--
-- AUD-COV-3: TTL cache for the bounded, real company-facts fetch the cover
-- letter agent may cite in its opening sentence (app.services.company_facts).
-- Keyed by normalized company name only — no FK to "User" — so one fetched
-- fact about a real company is legitimately shared across every candidate
-- applying there, and the cache is additive (never truncated by the test
-- suite's per-test TRUNCATE, same as "JobSourceStatus").
--
-- Additive only: CREATE TABLE IF NOT EXISTS. No DROP / no ALTER TYPE.

CREATE TABLE IF NOT EXISTS "CompanyFactsCache" (
    "company"    text PRIMARY KEY,
    "facts"      text NOT NULL,
    "sourceUrl"  text,
    "fetchedAt"  timestamptz NOT NULL DEFAULT now()
);
