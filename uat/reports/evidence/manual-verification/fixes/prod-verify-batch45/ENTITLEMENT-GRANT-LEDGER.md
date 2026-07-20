# Temporary Entitlement Grant Ledger — PROD-VERIFY batch45 (qa-adversary)

Run: MANUAL-VERIFICATION Stage-2 PROD-VERIFY SWEEP batch-4 + batch-5
Role: qa-adversary (opus) — DISTINCT from all fixers/reviewers
Deployed HEAD: ec20b91
Production: https://5cb5f0620.abacusai.cloud

## Why
The whole `/dashboard/*` tree (except `/dashboard/settings`) is gated by `SubscriptionGate`
(apps/web/src/components/subscription-gate.tsx:78 — `ent.requiresSubscription && !ent.active_paid`).
Story-bank (/dashboard/stories), dashboard hub (/dashboard, /dashboard/agents) and email-center
(/dashboard/email) are all behind the paywall. To exercise the fixes I grant a TEMPORARY DB Pro
entitlement to MY OWN disposable account (NOT a real Stripe subscription, NOT a real user).

## Disposable account (created THIS run via POST /api/auth/register)
- email: mv-vb45-pro-1784361227@example.com
- userId: c5dc9f214d581a28eb910671d
- created: 2026-07-18T07:53:49.361Z (register → 201)
- NO real user was touched. This is a throwaway MV-vb45 test account.

## Pre-grant (free) state — byte-for-byte snapshot @ 2026-07-18T07:54:02.271846Z
Subscription id `8703ad1f-59db-4594-90f0-6c92f373a7a2`: planId=free, status=active,
  billingInterval=NULL, updatedAt=2026-07-18T07:54:02.271846+00:00 (see grant-before-subscription.json)
UsageQuota id `38f2e7a7-57df-4e04-b101-f998c753ef26`: planId=free, runsAllowed=5, runsUsed=0,
  spendCapUsd=1.0, spendUsedUsd=0, updatedAt=2026-07-18T07:54:02.271846+00:00 (see grant-before-usagequota.json)
(Rows were lazily created by the app's first GET /api/billing/entitlement call.)

## GRANT SQL (applied @ 2026-07-18T07:54:55.538329Z, single transaction) — see grant-after-*.json
```sql
BEGIN;
UPDATE "Subscription" SET "planId"='pro', "updatedAt"=now() WHERE "userId"='c5dc9f214d581a28eb910671d';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c5dc9f214d581a28eb910671d';
COMMIT;
```
Confirmed: GET /api/billing/entitlement → {"active_paid":true,"plan":{"id":"pro","status":"active"}}

## REVERT SQL (byte-for-byte restore of pre-grant free state — run BEFORE exit)
```sql
BEGIN;
UPDATE "Subscription" SET "planId"='free', "status"='active',
  "updatedAt"='2026-07-18T07:54:02.271846+00:00'
  WHERE "userId"='c5dc9f214d581a28eb910671d';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "spendCapUsd"=1.0, "runsUsed"=0, "spendUsedUsd"=0,
  "updatedAt"='2026-07-18T07:54:02.271846+00:00'
  WHERE "userId"='c5dc9f214d581a28eb910671d';
COMMIT;
```
Note: WHERE clauses are strictly scoped to the disposable account's userId — NO other user row is ever touched.
Revert applied at: 2026-07-18T09:31:05Z (byte-for-byte EXACT; active_paid:false confirmed) — see grant-revert.txt
