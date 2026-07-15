-- 0020_per_user_agent_creds.sql
--
-- DOCUMENTARY ARTIFACT ONLY (ADR-TR-1). This repository has NO migration
-- runner: the schema below is created in production by the LAZY IDEMPOTENT DDL
-- in app/repositories/user_provider_credential.py::_ensure_user_agent_tables
-- and app/routers/agents.py::_ensure_agents_tables (advisory-locked
-- CREATE TABLE / ALTER TABLE ... ADD COLUMN IF NOT EXISTS). This file mirrors
-- that DDL for review/record purposes and is never executed at deploy.
--
-- Covers GAP-D1 (per-user credentials + Anthropic subscription OAuth),
-- GAP-D3 (full per-agent config + billing audit + quota), GAP-E5 (per-user
-- live-call resolution), GAP-NEW-001 (verify-on-save). All additive and
-- backward compatible — no DROP, no destructive ALTER.

-- Per-user encrypted provider credentials (UNIQUE per user+provider).
CREATE TABLE IF NOT EXISTS "UserProviderCredential" (
    "id"                text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"            text NOT NULL,
    "provider"          text NOT NULL,
    "authMode"          text NOT NULL
        CHECK ("authMode" IN ('api_key', 'subscription_oauth')),
    "ciphertext"        text NOT NULL,
    "secretHint"        text,
    "baseUrl"           text,
    "oauthScopes"       text,
    "expiresAt"         timestamptz,
    "lastVerifiedAt"    timestamptz,
    "lastVerifyStatus"  text,
    "createdAt"         timestamptz NOT NULL DEFAULT now(),
    "updatedAt"         timestamptz NOT NULL DEFAULT now(),
    UNIQUE ("userId", "provider")
);

-- Short-lived PKCE state for the Anthropic OAuth authorize round-trip.
CREATE TABLE IF NOT EXISTS "AnthropicOAuthState" (
    "stateToken"   text PRIMARY KEY,
    "userId"       text NOT NULL,
    "codeVerifier" text NOT NULL,
    "createdAt"    timestamptz NOT NULL DEFAULT now(),
    "expiresAt"    timestamptz NOT NULL DEFAULT (now() + interval '10 minutes')
);

-- Encrypted subscription OAuth access/refresh tokens (one per user).
CREATE TABLE IF NOT EXISTS "AnthropicOAuthToken" (
    "userId"        text PRIMARY KEY,
    "ciphertext"    text NOT NULL,
    "refreshCipher" text,
    "secretHint"    text,
    "expiresAt"     timestamptz,
    "scopes"        text,
    "createdAt"     timestamptz NOT NULL DEFAULT now(),
    "updatedAt"     timestamptz NOT NULL DEFAULT now()
);

-- Per-user, per-provider quota-exhaustion cooldown (subscription 429s).
-- NB: carries an id + explicit UNIQUE(userId,provider) index so it coexists
-- with any pre-existing table of the same name owned by a sibling feature.
CREATE TABLE IF NOT EXISTS "AgentQuotaBlock" (
    "id"        text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"    text NOT NULL,
    "provider"  text NOT NULL,
    "expiresAt" timestamptz NOT NULL,
    "reason"    text,
    "createdAt" timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS "AgentQuotaBlock_user_provider_key"
    ON "AgentQuotaBlock" ("userId", "provider");

-- Additive AgentConfig columns for full per-agent configuration (GAP-D3).
ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "credentialRef" text;
ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "provider" text;
ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "authMode" text;
ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "temperature" double precision DEFAULT 0.7;
ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "thinkingEffort" text DEFAULT 'medium';

-- Billing-provenance audit for every run (GAP-D3).
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "billingAuditJson" jsonb;
