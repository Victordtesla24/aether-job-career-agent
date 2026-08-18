-- 0033_user_profile_avatar.sql — Settings → Profile photo (PNG/JPG, max 2MB).
--
-- RECORD ONLY (documentary mirror). The API applies this additively and
-- idempotently at runtime via ``app.db.ensure_user_avatar_columns`` — the same
-- lazy-DDL pattern 0027/0020/0023 use (ADR-TR-1: this repo has no migration
-- runner). The columns are also declared in packages/db/src/schema.prisma so a
-- Prisma push never drops them (losing ``avatarFile`` would destroy a user's
-- uploaded profile photo).
--
-- WHAT THIS ADDS (all additive, all nullable, no default, no backfill):
--   "avatarFile"          bytea — exact uploaded PNG/JPEG bytes
--   "avatarContentType"   text  — sniffed media type (image/png | image/jpeg)
--
-- Existing Prisma column ``image`` (text, nullable) stores the SHA-256 hex of
-- the bytes as a cache-busting revision — never a data URL or the raw bytes.

ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "avatarFile" bytea;
ALTER TABLE "User" ADD COLUMN IF NOT EXISTS "avatarContentType" text;
