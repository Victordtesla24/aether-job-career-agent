-- 0021_multi_gmail_inbox.sql — multiple Gmail inboxes per user (GAP-D2)
--
-- ADDITIVE + ROLLBACK-SAFE. This migration is DOCUMENTARY: production applies the
-- same schema lazily and idempotently at runtime via
-- app.repositories.gmail_account.GmailAccountRepository._ensure_table
-- (ADR-TR-1 advisory-locked DDL). It is reproduced here as the durable record.
--
-- Design: a NEW ``GmailAccount`` table is the authoritative multi-account store.
-- The legacy single-account ``GoogleCredential`` table is left COMPLETELY
-- UNTOUCHED — its primary key and every column are preserved as-is — so a
-- rollback to the previous release (whose upsert does ``ON CONFLICT ("userId")``)
-- keeps working. Every statement below is purely additive (CREATE ... IF NOT
-- EXISTS / ADD COLUMN IF NOT EXISTS); there are deliberately no destructive or
-- type-changing statements anywhere in this file.

-- New multi-account Gmail store. One row per connected inbox; tokens are held as
-- Fernet ciphertext (accessTokenCipher / refreshTokenCipher) — see the app-level
-- backfill note below.
CREATE TABLE IF NOT EXISTS "GmailAccount" (
    "id"                 text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"             text NOT NULL,
    "accountEmail"       text,
    "accessTokenCipher"  text,
    "refreshTokenCipher" text,
    "tokenExpiry"        timestamptz,
    "scopes"             text,
    "isPrimary"          boolean NOT NULL DEFAULT false,
    "syncStatus"         text,
    "lastSyncedAt"       timestamptz,
    "createdAt"          timestamptz NOT NULL DEFAULT now(),
    "updatedAt"          timestamptz NOT NULL DEFAULT now()
);

-- One account row per (user, email); exactly one primary inbox per user.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gmailaccount_user_email
    ON "GmailAccount" ("userId", "accountEmail");
CREATE UNIQUE INDEX IF NOT EXISTS uq_gmailaccount_one_primary
    ON "GmailAccount" ("userId") WHERE "isPrimary";

-- Link every synced thread to the specific inbox it came from, so the unified
-- inbox can badge each thread and an ?account_id filter can narrow to one mailbox.
ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "gmailAccountId" text;
CREATE INDEX IF NOT EXISTS "idx_emailthread_account"
    ON "EmailThread" ("userId", "gmailAccountId");

-- Backfill: token ciphers CANNOT be produced in SQL (Fernet encryption runs in
-- the application), so the row copy from GoogleCredential is performed by the
-- application vault-encrypting backfill in
-- GmailAccountRepository._backfill_from_google_credential (idempotent,
-- WHERE-NOT-EXISTS on (userId, accountEmail), tokens encrypted, isPrimary=true
-- when the user has no primary yet). It is intentionally NOT duplicated here to
-- avoid inserting token-less shadow rows that would mask the encrypted copy.

-- Backfill existing threads to each user's primary connected inbox (pure SQL;
-- only affects rows not already linked).
UPDATE "EmailThread" et
   SET "gmailAccountId" = ga."id"
  FROM "GmailAccount" ga
 WHERE et."gmailAccountId" IS NULL
   AND ga."userId" = et."userId"
   AND ga."isPrimary";
