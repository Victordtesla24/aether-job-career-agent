# Temporary Entitlement Grant Ledger — PROD-VERIFY batch-2 (qa-adversary)

Follows ADR-MV-01 pattern (see ../../ENTITLEMENT-GRANT-LOG.md). A temporary DB-only Pro
entitlement (NOT real Stripe) granted to a DISPOSABLE qa-adversary account solely to exercise
paid agent runs (cover-letter injection defense). Reverted byte-for-byte before finishing.

## Disposable account (grantee)
- PRO account: `mv-vbatch2-pro-20260718T045405Z@example.com` · userId `cb0159b14ae4852ad0f401f84`
  - display name updated free→"Jordan Ellis" (avoids signer/company token collision in test letters)
- FREE account (control, NO grant): `mv-vbatch2-free-20260718T045405Z@example.com` · userId `c57b9fb5fce9f882ba35b8a22`

## Pre-grant state (byte-for-byte capture @ 2026-07-18T04:54Z)
- Subscription id `00bd29d3-a7df-460f-9980-071f8560dc94`: planId=free, status=active, billingInterval=null,
  stripe*=null, currentPeriod*=null, cancelAtPeriodEnd=false,
  createdAt=updatedAt=`2026-07-18T04:54:20.70961+00:00`
- UsageQuota id `7df8b9be-e221-4147-8cc8-67cccf21ac39`: planId=free, periodStart=2026-07-01, periodEnd=2026-08-01,
  runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0,
  createdAt=updatedAt=`2026-07-18T04:54:20.70961+00:00`
- (full JSON: pro-subscription-before.json / pro-usagequota-before.json)

## GRANT (applied 2026-07-18T04:54:55Z)
```sql
BEGIN;
UPDATE aether."Subscription" SET "planId"='pro', "updatedAt"=now() WHERE "userId"='cb0159b14ae4852ad0f401f84';
UPDATE aether."UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cb0159b14ae4852ad0f401f84';
COMMIT;
```
Confirmed: GET /api/billing/entitlement → {"active_paid":true,"plan":{"id":"pro","status":"active"}} (pro-entitlement-after-grant.json)

## REVERT (byte-for-byte; run BEFORE finishing)
```sql
BEGIN;
UPDATE aether."Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL,
  "stripeCustomerId"=NULL, "stripeSubscriptionId"=NULL, "currentPeriodStart"=NULL, "currentPeriodEnd"=NULL,
  "cancelAtPeriodEnd"=false, "updatedAt"='2026-07-18T04:54:20.70961+00:00'
  WHERE "userId"='cb0159b14ae4852ad0f401f84';
UPDATE aether."UsageQuota" SET "planId"='free', "runsAllowed"=5, "spendCapUsd"=1.0,
  "runsUsed"=0, "spendUsedUsd"=0, "periodStart"='2026-07-01T00:00:00+00:00', "periodEnd"='2026-08-01T00:00:00+00:00',
  "updatedAt"='2026-07-18T04:54:20.70961+00:00'
  WHERE "userId"='cb0159b14ae4852ad0f401f84';
COMMIT;
```
Note: account is DISPOSABLE (residual acceptable) but reverted anyway. runsUsed/spendUsedUsd reset to the
pre-run 0/0 to remove adversary-test-induced usage. Revert applied at: 2026-07-18T05:15:04Z · post-revert entitlement GET → active_paid:false, plan.id=free (pro-entitlement-after-revert.json); Subscription+UsageQuota byte-for-byte match pre-grant (pro-*-after-revert.json)
