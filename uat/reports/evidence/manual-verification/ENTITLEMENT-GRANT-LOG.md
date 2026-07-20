# Temporary Entitlement Grant Log (MANUAL-VERIFICATION run) — CRASH-PROOF REVERT RECORD

**ADR-MV-01 — orchestrator (fable-5) decision, 2026-07-17.**

## Why
The whole `/dashboard/*` tree is gated by `SubscriptionGate` (apps/web/src/app/dashboard/layout.tsx:27; condition `requiresSubscription && !active_paid`), and every metered agent run is gated by `_require_active_subscription` (apps/api/app/routers/agents.py:539-571 → 402). The canonical test account admin/admin123 is FREE (`Subscription.planId='free'`), so ~17 dashboard screens + all agent-run flows are unreachable for testing. The PAID-user experience is the run's core mandate ("real users will pay real Australian dollars"). Per §3.2.5 + §9, a temporary DB entitlement (NOT real Stripe) is granted to test paid content, then reverted byte-for-byte before exit. This mirrors the Phase-7 precedent.

The free-tier paywall itself remains a real finding set (MV-pricing-001 BLOCKER, MV-analytics-001 BLOCKER, MV-dashboard-003, MV-agents-001, etc.) — the grant is for COVERAGE of paid behavior, it does not close those findings.

## Source-of-truth (scout packet ENTITLEMENT-DECISION-PACKET.json, live DB @ 2026-07-17T11:45Z)
- User: admin@aether.local · id `cc29a76e324fbf19f438eb8be` · isAdmin=false
- Subscription row id `6f3839c0-7cc0-4c8f-885f-009a11105c01`: planId=`free`, status=`active`, updatedAt=`2026-07-17T11:26:01.52178+00:00`, stripe*=null, currentPeriod*=null
- UsageQuota row id `0df03084-76d2-484b-a35a-9dc67dfeeaaf`: planId=`free`, runsAllowed=5, runsUsed=3, spendCapUsd=1.0, spendUsedUsd=0.058292, updatedAt=`2026-07-17T11:26:01.683608+00:00`, periodStart=2026-07-01, periodEnd=2026-08-01

## GRANT SQL (single transaction)
```sql
BEGIN;
UPDATE "Subscription" SET "planId"='pro', "updatedAt"=now() WHERE "userId"='cc29a76e324fbf19f438eb8be';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cc29a76e324fbf19f438eb8be';
COMMIT;
```
Grant applied at: 2026-07-17T15:36:09.089223Z · confirmed GET /api/billing/entitlement → active_paid:true, plan.id=pro

## REVERT SQL (byte-for-byte restore of pre-run state — run BEFORE exit gates)
```sql
BEGIN;
UPDATE "Subscription" SET "planId"='free', "status"='active', "updatedAt"='2026-07-17T11:26:01.52178+00:00'
  WHERE "userId"='cc29a76e324fbf19f438eb8be';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "spendCapUsd"=1.0, "runsUsed"=3, "spendUsedUsd"=0.058292,
  "updatedAt"='2026-07-17T11:26:01.683608+00:00'
  WHERE "userId"='cc29a76e324fbf19f438eb8be';
COMMIT;
```
Note on counters: revert resets runsUsed→3 and spendUsedUsd→0.058292 to remove ORCHESTRATOR-TEST-INDUCED usage (test cleanup, not data fabrication — restores the exact pre-run state). Any AgentRun rows created during paid testing are prefixed/attributable test data → enumerate + delete at cleanup (TEST-DATA-CLEANUP-LEDGER.md). Revert applied at: __PENDING__ · post-revert verify: GET /api/billing/entitlement → active_paid:false, /dashboard shows paywall again.

## Governance
Cross-referenced in docs/delivery/MANUAL-VERIFICATION-GOVERNANCE-AUDIT.md (ADR-MV-01). Grant is reversible test-fixture setup, NOT a code change and NOT a schema change. Orchestrator authorizes; a sub-agent applies. MUST be reverted before G-04/G-05/G-11.

---

## ADVERSARIAL STAGE-3 GRANT (qa-adversary, cluster E-JFE) — 2026-07-18

**Account:** `mv-qa-ej2-adv18@example.com` · userId `c88fc72d11082ac709fd6a801` (fresh signup; prior disposable `mv-qa-ej-2026-cebe` password unrecoverable, so a new one was created per brief).

**BEFORE-state (captured live 2026-07-18, single-row reads):**
- Subscription id `4a2fdcd9-24e1-47d1-b13a-1d6c3fc85f3a`: planId=`free`, status=`active`, billingInterval=NULL, stripe*=NULL, currentPeriod*=NULL, createdAt=`2026-07-18T17:16:19.712328+00:00`, updatedAt=`2026-07-18T17:16:19.712328+00:00`
- UsageQuota id `b7bb0dbd-d67e-4bfd-85e9-bb23c5bdb0d2`: planId=`free`, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, periodStart=2026-07-01, periodEnd=2026-08-01, updatedAt=`2026-07-18T17:16:19.712328+00:00`

**GRANT SQL (single-row, explicit WHERE on my userId; run under `PGOPTIONS=-c search_path=aether`):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c88fc72d11082ac709fd6a801';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c88fc72d11082ac709fd6a801';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at Stage-3 exit cleanup, NOT now; Pro stays through Stage 3):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-18T17:16:19.712328+00:00' WHERE "userId"='c88fc72d11082ac709fd6a801';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-18T17:16:19.712328+00:00' WHERE "userId"='c88fc72d11082ac709fd6a801';
```
Note: runsUsed/spendUsedUsd will accrue during paid testing; revert resets them to the pre-run 0/0 (orchestrator-test-induced usage removal, not fabrication). Any AgentRun/ApprovalRequest/InterviewSchedule rows created during testing are test data → enumerate + delete at cleanup. Revert applied at: __PENDING (Stage-3 exit)__.

**GRANT APPLIED:** 2026-07-18T~17:22Z (2× `UPDATE 1`). Confirmed live: GET /api/billing/entitlement → active_paid:true, plan.id=pro. Pro REMAINS active through Stage-3 (per brief; exit cleanup reverts using the REVERT SQL above).

**Test data created during adversarial Stage-3 (userId c88fc72d11082ac709fd6a801) — enumerate+delete at exit cleanup:**
- User account `mv-qa-ej2-adv18@example.com`
- Job: 42 rows (via real scout discovery + Sync-All re-run)
- Application: 1 (`c1eee7b59d57f564258be797c`)
- Resume: 10 versions (1 base + 1 tailored + 8 ingested variants for pagination test)
- InterviewSchedule: 2 (`c97fda39556d086b9455bf2b9` completed, `c301d140dd4055bdeaf61b93f` cancelled)
- ApprovalRequest: 8 (1 real resume_tailor `cc102bff35ab57946b2581393` approved via modal, 6 synthetic payload-test approvals, 1 execute-FSM `c15514f6e611e9b9ca5f95759`)
- AgentRun: 8 (scout/fitScorer/tailor; only 1 metered run consumed — runsUsed=1)
- NOTE: system-shared `ProviderCredential(anthropic)` lastVerifiedAt was refreshed by a live "Test connection" verify (honest live 401 result recorded — NO revert needed; it reflects true state).

---

## ADVERSARIAL STAGE-3 GRANT — SWEEP A (qa-adversary, data-consistency/UI-honesty/offers/job-discovery) — 2026-07-18

**Pro account:** `mv-qa-final-a-pro18@example.com` · userId `cb2b03a9bebcab4b7617d1c3c` (fresh disposable signup).
**2nd FREE account (paywall-leak check, NO grant):** `mv-qa-final-a-free18@example.com` · userId `cc623625e6be90fc99b3fa4f4`.

**BEFORE-state (captured live 2026-07-18T22:46Z, single-row reads):**
- Subscription id `31efccf5-7c84-4db5-affa-dc6d9bd2fa8f`: planId=`free`, status=`active`, billingInterval=NULL, stripe*=NULL, currentPeriod*=NULL, cancelAtPeriodEnd=false, createdAt=`2026-07-18 22:46:53.663406+00`, updatedAt=`2026-07-18 22:46:53.663406+00`
- UsageQuota id `693f58a7-e837-415f-bcf1-94ce2d233468`: planId=`free`, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, periodStart=2026-07-01 00:00:00+00, periodEnd=2026-08-01 00:00:00+00, updatedAt=`2026-07-18 22:46:53.663406+00`

**GRANT SQL (single-row, explicit WHERE on my userId; run under `PGOPTIONS=-c search_path=aether`):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cb2b03a9bebcab4b7617d1c3c';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cb2b03a9bebcab4b7617d1c3c';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at Stage-3 exit cleanup; Pro stays through this sweep):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-18 22:46:53.663406+00' WHERE "userId"='cb2b03a9bebcab4b7617d1c3c';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-18 22:46:53.663406+00' WHERE "userId"='cb2b03a9bebcab4b7617d1c3c';
```
Note: runsUsed/spendUsedUsd may accrue during paid testing; revert resets them to the pre-run 0/0. Test rows (Application/Offer/Story/InterviewSchedule) created during testing are test data → enumerate + delete at cleanup. Revert applied at: __PENDING (Stage-3 exit)__.

**GRANT APPLIED:** 2026-07-18T22:47Z (2× `UPDATE 1`). Confirmed live: GET /api/billing/entitlement → active_paid:true, plan.id=pro (evidence adversarial/final-A/api/00-pro-entitlement.json). FREE account confirmed active_paid:false (00-free-entitlement.json). Pro REMAINS active through this sweep; exit cleanup reverts using the REVERT SQL above.

**Test data created during SWEEP A — enumerate + delete at exit cleanup (NOT reverted now; Pro left active per brief):**
- User accounts: `mv-qa-final-a-pro18@example.com` (`cb2b03a9bebcab4b7617d1c3c`, Pro/granted), `mv-qa-final-a-free18@example.com` (`cc623625e6be90fc99b3fa4f4`, Free/paywall-leak check), `mv-qa-final-a-rl-1784415107@example.com` (`ccd254e547d3bee5f239f23c6`, register-rate-limit live probe).
- On Pro account `cb2b03a9bebcab4b7617d1c3c`: Application=10 (2 draft, 3 submitted, 3 interview, 1 offer, 1 rejected — pathological distribution w/ empty screening bucket for the negative-dropoff repro); Job=12 (AU-located, one retitled 'Senior Platform Engineer' with a rich JD for the tailor test); Resume=1 (`c22769663b1d79a8653a6071b`, identity 'ADVERSARY TESTPERSON'); StoryEntry=1 (191-char long-title Leadership story); ApprovalRequest=3 (pending, linked to 3 applications for the needs-approval filter test); AgentRun=2 (tailor no-op runs, BOTH refunded — runsUsed=0, spendUsedUsd=0). Offer table=0 (2 manual offers created then deleted during the delete/ownership test).
- Counters check at end of sweep: runsUsed=0, spendUsedUsd=0 (no metered run consumed — every tailor run was a fabrication-guard no-op and refunded). REVERT SQL above restores updatedAt only; no counter reset needed.


---

## ADVERSARIAL STAGE-3 GRANT (qa-adversary, SWEEP B — agents/security/injection/approvals) — 2026-07-18

**Account:** `mv-qa-final-b-8f2a@example.com` · userId `cee0c8f5076a48a3f166dee94` (fresh disposable signup created 2026-07-18T22:46:16Z for SWEEP B). Prod HEAD @bdf6ef9; aether-api restarted 22:39:19Z (running deployed code).

**BEFORE-state (captured live 2026-07-18T~22:47Z, single-row reads under `PGOPTIONS=-c search_path=aether`, `?schema=` stripped from DSN via python urllib):**
- Subscription id `24ea8b31-4f56-49e4-860c-aadf9cb37a4f`: planId=`free`, status=`active`, billingInterval=NULL, createdAt=`2026-07-18 22:46:54.407297+00`, updatedAt=`2026-07-18 22:46:54.407297+00`
- UsageQuota id `75efc963-3358-4779-ae80-7318f7dafce9`: planId=`free`, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, periodStart=2026-07-01, periodEnd=2026-08-01, updatedAt=`2026-07-18 22:46:54.407297+00`

**GRANT SQL (single-row, explicit WHERE on my userId; run under `PGOPTIONS=-c search_path=aether`):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cee0c8f5076a48a3f166dee94';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cee0c8f5076a48a3f166dee94';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at Stage-3 exit cleanup, NOT now; Pro stays through this sweep per brief):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-18 22:46:54.407297+00' WHERE "userId"='cee0c8f5076a48a3f166dee94';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-18 22:46:54.407297+00' WHERE "userId"='cee0c8f5076a48a3f166dee94';
```
Note: runsUsed/spendUsedUsd accrue during paid testing; revert resets them to pre-run 0/0 (orchestrator-test-induced usage removal, not fabrication). Any AgentRun/ApprovalRequest rows created during testing are test data → enumerate + delete at cleanup. Revert applied at: __PENDING (Stage-3 exit)__.

**GRANT APPLIED:** 2026-07-18T~22:50Z (2× `UPDATE 1`). Confirmed live: GET /api/billing/entitlement → active_paid:true, plan.id=pro.

**Test data created during SWEEP B (enumerate + delete at Stage-3 exit cleanup):**
- User `mv-qa-final-b-8f2a@example.com` (userId `cee0c8f5076a48a3f166dee94`) — Pro-granted; revert per REVERT SQL above. Profile name+targetRole set to 'Administrator' (to reproduce MV-approval-modal-009 trigger; disposable account).
- User `mv-qa-final-b-victim-7c1@example.com` (userId `c87e7575be459ff9c2dd5ceef`) — cross-user isolation test; 1 Contact (`c22160a8dfc085162b37c8fb1`).
- Job: 6 (ids prefixed `mvqafb-`: inj-zebra, inj-followed, inj-salary, garbage, match, nomatch) — direct single-row INSERTs keyed to my userId for controlled JD/injection/keyword testing.
- Resume: 1 (`c690b0b41931cee5fa1e13f86` "Zorpwell Base v1").
- StoryEntry: 4 (grounded on Zorpwell resume).
- ApprovalRequest: 5 (2 executed: match `cce1638d71be7a57bb69e2303` seq, inj-salary `c644c09ab43f05d5c8b5e0704` concurrent).
- Application: 5 · AgentRun: 9 · Contacts/OutreachTasks: created+deleted during cascade test (already gone).
- runsUsed accrued to 6 (metered agent runs) — revert resets to pre-run 0 per REVERT SQL.


---

## ADVERSARIAL STAGE-3 FINAL-PII GRANT (qa-adversary, cross-account PII-leak re-verify) — 2026-07-19

**Purpose:** DEFINITIVE live prod re-verify of the cross-account PII-leak class (NF-final-B-001/002/005/006/007/008 + MV-cover-letter-studio-006 + MV-adv-A-001/002) on PROD @d313d23. Real LLM, no fixtures. TWO fresh disposable Pro accounts.

**Prod HEAD @d313d23** (committed 2026-07-19T22:16:17Z); aether-api ActiveEnterTimestamp 2026-07-19T22:41:05Z (running deployed code). aether-worker restarted 22:41:05Z.

**Accounts (fresh disposable, created 2026-07-19T22:49Z):**
- (A) DISTINCT-RÉSUMÉ: `mv-qa-pii-distinct-9f3k@example.com` · userId `c6c99121d1d2a26ae37543ddd`
- (B) NO-RÉSUMÉ: `mv-qa-pii-noresume-9f3k@example.com` · userId `c43d8b2f3cbda5c787c107417`

**BEFORE-state (captured live 2026-07-19T22:50Z, single-row reads under `PGOPTIONS`/`options=-c search_path=aether`, `?schema=` stripped from DSN via python urllib.urlsplit/parse_qsl — NOT sed; current_schema()==aether confirmed before every op):**
- (A) Subscription `c9f62e6a-7028-49f1-8318-c6f422ca3db2`: planId=free,status=active,billingInterval=NULL,updatedAt=`2026-07-19 22:50:08.450054+00`. UsageQuota `1c84684f-035c-4e2d-9eab-6bf59789d871`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-19 22:50:08.450054+00`
- (B) Subscription `9087f897-ab79-4c29-ab67-d1b0b1968530`: planId=free,status=active,billingInterval=NULL,updatedAt=`2026-07-19 22:50:18.761435+00`. UsageQuota `cec9ecee-6719-4ea7-97e2-9d7fd0cf7e04`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-19 22:50:18.761435+00`
- (Both free-plan rows were lazily created by the first GET /api/billing/entitlement call; no rows existed at signup.)

**GRANT SQL (single-row, explicit WHERE on each userId; run via psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c6c99121d1d2a26ae37543ddd';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c6c99121d1d2a26ae37543ddd';
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c43d8b2f3cbda5c787c107417';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c43d8b2f3cbda5c787c107417';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at exit cleanup; qa-adversary reverts at end of this FINAL stage):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-19 22:50:08.450054+00' WHERE "userId"='c6c99121d1d2a26ae37543ddd';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-19 22:50:08.450054+00' WHERE "userId"='c6c99121d1d2a26ae37543ddd';
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-19 22:50:18.761435+00' WHERE "userId"='c43d8b2f3cbda5c787c107417';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-19 22:50:18.761435+00' WHERE "userId"='c43d8b2f3cbda5c787c107417';
```
Note: runsUsed/spendUsedUsd accrue during paid testing on (A); revert resets to pre-run 0/0. Test rows (Resume/Job/CoverLetter/Application/AgentRun/BackgroundJob/EmailThread) created during testing are test data → enumerate + delete at cleanup. Revert applied at: **2026-07-19T23:20Z** (4x `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /api/billing/entitlement -> active_paid:false, plan.id=free for BOTH accounts. Byte-for-byte before-state restored (planId=free, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, updatedAt restored to signup timestamps).

**GRANT APPLIED:** 2026-07-19T22:51Z (4× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /api/billing/entitlement -> active_paid:true, plan.id=pro for BOTH accounts (evidence adversarial/final-PII/api/api_entitlement_A_distinct.json + _B_noresume.json).

**Test data created during FINAL-PII sweep (both accounts now reverted to free; rows left for cleanup ledger):**
- (A) `mv-qa-pii-distinct-9f3k@example.com` (`c6c99121d1d2a26ae37543ddd`): Resume=1 (PRIYA NATARAJAN base, id c1fae2c2...), Job=4 (2 streaming + Pastry-Chef mismatch + messy-JD), Application=9 (3 seeded + cover-letter auto-drafts), CoverLetter/refine drafts, AgentRun=11, BackgroundJob=8, EmailThread=2, StoryEntry=5. Metered runsUsed peaked at 7 (cover-letters/refines/emails/story-extraction) — reset to 0 by revert.
- (B) `mv-qa-pii-noresume-9f3k@example.com` (`c43d8b2f3cbda5c787c107417`): Resume=0 (NONE — the point of the account; refused tailor did NOT seed operator PDF), Job=1 (seed), Application=0, AgentRun=4 (all failed/refused: tailor/coverLetter/fitScorer/emailAgent), BackgroundJob=2 (failed refusals), EmailThread=1. runsUsed stayed 0 (no charge on any refusal).
- All DB ops: single-row WHERE-keyed via psycopg2 under search_path=aether, ?schema= stripped via python urllib; current_schema()==aether asserted before every op; NO pytest against prod; NO TRUNCATE/unqualified-DELETE.


---

## ADVERSARIAL FINAL-RESIDUALS GRANT (qa-adversary, CamelCase-filter + async-refusal re-verify) — 2026-07-20

**Purpose:** FINAL live prod re-verify of MV-cover-letter-studio-006 / NF-final-PII-001 (CamelCase keyword chips) + NF-final-PII-002 (async no-résumé honest refusal, single-agent AND pipeline) on PROD @084e04b (backend-only residuals deploy). Real LLM (AETHER_LLM_MODE=auto), async ON (AETHER_ASYNC_GENERATION=true). TWO fresh disposable accounts.

**Prod HEAD @084e04b** (committed 2026-07-20T00:36:59Z); aether-api + aether-worker ActiveEnterTimestamp 2026-07-20T00:59:08Z (running deployed code). DB host db-fdc4e11da.db005.hosteddb.reai.io / db fdc4e11da / schema aether.

**Accounts (fresh disposable, registered 2026-07-20T~01:12Z via POST /auth/register):**
- (R1) DISTINCT SYNTHETIC RÉSUMÉ: `mv-qa-resid-distinct-865c45@example.com` · userId `cf6bb0e8a91954a87e00c0ee0`
- (R2) NO RÉSUMÉ EVER: `mv-qa-resid-noresume-865c45@example.com` · userId `c1561fd2195e1801d85872755`

**BEFORE-state (captured live 2026-07-20T~01:12Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped from DSN via python urllib.urlsplit/parse_qsl — NOT sed; current_schema()==aether asserted before every op; free rows lazily created by the first GET /billing/entitlement):**
- (R1) Subscription `ae3385ec-14f7-4782-984d-1ecbf1042c0b`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,updatedAt=`2026-07-20 01:12:08.279581+00`. UsageQuota `d1b6acbc-eee5-4ca7-9424-f83ab5ea9047`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,periodStart=2026-07-01,periodEnd=2026-08-01,updatedAt=`2026-07-20 01:12:08.279581+00`
- (R2) Subscription `1fc5556d-b487-45d5-80fb-8c091b6b4753`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,updatedAt=`2026-07-20 01:12:08.714534+00`. UsageQuota `ef9adbfa-7a2e-4935-99bc-21e81af2f6c5`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,periodStart=2026-07-01,periodEnd=2026-08-01,updatedAt=`2026-07-20 01:12:08.714534+00`

**GRANT SQL (single-row, explicit WHERE on each userId; psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c1561fd2195e1801d85872755';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c1561fd2195e1801d85872755';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at this stage's exit cleanup; qa-adversary reverts at end):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 01:12:08.279581+00' WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 01:12:08.279581+00' WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 01:12:08.714534+00' WHERE "userId"='c1561fd2195e1801d85872755';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 01:12:08.714534+00' WHERE "userId"='c1561fd2195e1801d85872755';
```
Note: runsUsed/spendUsedUsd may accrue during paid testing on R1; revert resets to pre-run 0/0 (orchestrator-test-induced usage removal, not fabrication). R2 must stay 0/0 (every refusal must refund). Test rows (Resume/Job/Application/CoverLetter/AgentRun/BackgroundJob) created during testing are test data → enumerate + delete at cleanup. Revert applied at: **2026-07-20T03:05:45Z (orchestrator EMERGENCY revert):** applied byte-for-byte per this block after the qa agent died on the harness monthly spend limit with the revert PENDING (6x UPDATE, rowcount==1 each, current_schema()==aether asserted; AFTER-state verified free/5/0/1.0/0 for all rows). Governance entry 11.

**GRANT APPLIED:** 2026-07-20T~01:13Z (4× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement -> active_paid:true, plan.id=pro for BOTH accounts (evidence adversarial/final-residuals/api/00-entitlement-R1-granted.json + 00-entitlement-R2-granted.json).

---

## CLAIM-RESAMPLE GRANT (qa-adversary §6.4, CONFIRMED-claim re-proof) — 2026-07-20

**Purpose:** re-prove CONFIRMED claims that strictly require a PAID context (async 202 contract CLM-003/014, paid scout sourcing CLM-056/026/071/080/081/084/085, paid-UI CLM-050/075/078, settings-allowlist accept CLM-012/025). ONE disposable Pro account per brief. Prod HEAD @084e04b.

**Account:** `mv-qa-resample-ac3fb1@example.com` · userId `c90279607e7688144c3d73b4d` (fresh disposable signup 2026-07-20T01:23:01Z).

**BEFORE-state (captured live 2026-07-20T01:23:17Z, single-row reads under `options=-c search_path=aether`, `?schema=` stripped via python urllib; current_schema()==aether asserted; read-only session):**
- Subscription id `50c0dcdb-ac72-4eee-b4ae-71da2112c3a5`: planId=`free`, status=`active`, billingInterval=NULL, updatedAt=`2026-07-20 01:23:17.631758+00`
- UsageQuota id `143b1476-f62a-44db-8b5d-122a53716b4f`: planId=`free`, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, updatedAt=`2026-07-20 01:23:17.631758+00`

**GRANT SQL (single-row, explicit WHERE on my userId; rowcount asserted ==1 each; run under `search_path=aether`):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c90279607e7688144c3d73b4d';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c90279607e7688144c3d73b4d';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — run at end of this resample; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 01:23:17.631758+00' WHERE "userId"='c90279607e7688144c3d73b4d';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 01:23:17.631758+00' WHERE "userId"='c90279607e7688144c3d73b4d';
```
Note: runsUsed/spendUsedUsd accrue during paid probes; revert resets to pre-run 0/0 (orchestrator-test-induced usage removal). Test rows (Job/Resume/Application/AgentRun/BackgroundJob/StoryEntry/CoverLetter) created during probes are test data → deleted with the account at cleanup (registered in TEST-DATA-CLEANUP-LEDGER.md, matches `mv-qa-%@example.com` DELETE pattern). Revert applied at: **2026-07-20T03:05:45Z (orchestrator EMERGENCY revert):** applied byte-for-byte per this block after the qa agent died on the harness monthly spend limit with the revert PENDING (6x UPDATE, rowcount==1 each, current_schema()==aether asserted; AFTER-state verified free/5/0/1.0/0 for all rows). Governance entry 11.

---

## ADVERSARIAL FINAL-RESIDUALS RE-GRANT (qa-adversary, §7 dashboard sweep resume, R1 ONLY) — 2026-07-20

**Context:** The qa agent was killed by a harness spend limit at ~01:27Z with the §7 sweep unstarted; the orchestrator EMERGENCY-reverted BOTH R1+R2 grants to free at 03:05:45Z (Governance entry 11) per the block above. Resuming at ~03:07Z on PROD @e182571 (Merge fix/mv-system-008-cron-logging; aether-api/web/worker ActiveEnterTimestamp 2026-07-20T03:03:48Z). The §7 dashboard-route sweep needs paid access, so R1 is re-granted for the sweep only. **R2 stays FREE** (not re-granted).

**Account re-granted (R1 ONLY):** `mv-qa-resid-distinct-865c45@example.com` · userId `cf6bb0e8a91954a87e00c0ee0`.

**BEFORE-state (captured live 2026-07-20T~03:08Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped via python urllib — NOT sed; current_schema()==aether asserted; this is the byte-for-byte free state left by the 03:05:45Z emergency revert):**
- Subscription `ae3385ec-14f7-4782-984d-1ecbf1042c0b`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,updatedAt=`2026-07-20 01:12:08.279581+00`. UsageQuota `d1b6acbc-eee5-4ca7-9424-f83ab5ea9047`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,periodStart=2026-07-01,periodEnd=2026-08-01,updatedAt=`2026-07-20 01:12:08.279581+00`

**GRANT SQL (single-row, explicit WHERE on R1's userId; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
```

**REVERT SQL (byte-for-byte restore of the above BEFORE-state — qa-adversary applies this at end of THIS sweep, before finishing):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 01:12:08.279581+00' WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 01:12:08.279581+00' WHERE "userId"='cf6bb0e8a91954a87e00c0ee0';
```
Note: the §7 sweep is read-only navigation (no metered runs), so runsUsed/spendUsedUsd should stay 0; the revert resets them to 0 regardless. Revert applied at: **2026-07-20T~03:13Z** (qa-adversary, 2× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted). AFTER-state verified byte-for-byte: Subscription planId=free/status=active/billingInterval=NULL/updatedAt=2026-07-20 01:12:08.279581+00; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt=2026-07-20 01:12:08.279581+00. Confirmed live: GET /billing/entitlement -> active_paid:false, plan.id=free for R1 (and R2 remained free throughout). Evidence: adversarial/final-residuals/api/zz-post-revert-entitlement.json.

**RE-GRANT APPLIED:** 2026-07-20T~03:08Z (2× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement -> active_paid:true, plan.id=pro (evidence adversarial/final-residuals/api/00-entitlement-R1-regranted.json).

---

## CLAIM-RESAMPLE RE-GRANT (qa-adversary §6.4, resumed after spend-limit) — 2026-07-20T03:10Z

**Context:** the original CLAIM-RESAMPLE grant (above) was EMERGENCY-reverted by the orchestrator at 2026-07-20T03:05:45Z (byte-for-byte, verified free) after this agent hit the harness monthly spend limit mid-run. Resuming at ~03:10Z to complete the remaining PAID-context sampled claims (agent-generation quality CLM-082/058/091; paid-dashboard UI CLM-050/075/081/078). Same disposable account re-granted. **This time the agent applies AND reverts the grant itself before finishing.**

**Account:** `mv-qa-resample-ac3fb1@example.com` · userId `c90279607e7688144c3d73b4d`.

**FRESH BEFORE-state (captured live 2026-07-20T03:10:32Z, read-only, current_schema()==aether asserted) — identical to original signup state after the orchestrator's byte-for-byte revert:**
- Subscription id `50c0dcdb-ac72-4eee-b4ae-71da2112c3a5`: planId=`free`, status=`active`, billingInterval=NULL, updatedAt=`2026-07-20 01:23:17.631758+00`
- UsageQuota id `143b1476-f62a-44db-8b5d-122a53716b4f`: planId=`free`, runsAllowed=5, runsUsed=0, spendCapUsd=1.0, spendUsedUsd=0, updatedAt=`2026-07-20 01:23:17.631758+00`

**RE-GRANT SQL (single-row keyed; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c90279607e7688144c3d73b4d';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c90279607e7688144c3d73b4d';
```

**REVERT SQL (byte-for-byte; same as original block — restores signup timestamp):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 01:23:17.631758+00' WHERE "userId"='c90279607e7688144c3d73b4d';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 01:23:17.631758+00' WHERE "userId"='c90279607e7688144c3d73b4d';
```
Revert applied at: **2026-07-20T03:22:29Z (this qa-adversary agent, self-applied)** — 2× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted, run under `search_path=aether` (?schema= stripped via urllib). AFTER-state verified byte-for-byte: Subscription planId=free/status=active/billingInterval=NULL/updatedAt=`2026-07-20 01:23:17.631758+00`; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt=`2026-07-20 01:23:17.631758+00`. Confirmed live: `GET /api/billing/entitlement` → `active_paid:false`, plan.id=free. NOTE: this account's LOGIN email is now `resample@aether.local` (changed by the CLM-012/025 settings-allowlist accept probe, per CLM-013) — delete by userId `c90279607e7688144c3d73b4d` at cleanup (see TEST-DATA-CLEANUP-LEDGER.md; it no longer matches the `mv-qa-%@example.com` pattern).


---

## ADVERSARIAL FINAL-CLOSURE GRANT (qa-adversary, LAST closure re-verify: CamelCase chips + async no-résumé refusal surfacing + lead-chase) — 2026-07-20

**Purpose:** FINAL closure re-verify on PROD @main 7fbf4c3 (Merge fix/nf-final-resid; aether-api/web restarted 2026-07-20T06:12:01Z) of MV-cover-letter-studio-006 / NF-final-PII-001 / NF-final-resid-001 (CamelCase JD-keyword chips) + NF-final-resid-002 (Cover Letter Studio async no-résumé refusal surfacing), plus a lead-chase on the shared resolveRun() mechanism in agents/email pages. Real LLM (AETHER_LLM_MODE=auto), async ON (AETHER_ASYNC_GENERATION=true). TWO fresh disposable accounts.

**Accounts (fresh disposable, registered 2026-07-20T~06:22Z via POST /auth/register with browser UA):**
- (F1) DISTINCT SYNTHETIC RÉSUMÉ: `mv-qa-fr-69d1e2@example.com` · userId `c6b1aca1f10731e9866b7dd38` (name "Quill Adversarius")
- (F2) NO RÉSUMÉ EVER: `mv-qa-fr-69d1e2-nr@example.com` · userId `cd63b6832b67eb3aa3d9a58c2`

**BEFORE-state (captured live 2026-07-20T~06:22Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped via python urllib.urlsplit/parse_qsl — NOT sed; current_schema()==aether asserted before every op; free rows lazily created by the first GET /billing/entitlement):**
- (F1) Subscription `9c349b68-ef4f-4099-a035-131e7e869af7`: planId=free,status=active,billingInterval=NULL,updatedAt=`2026-07-20T06:22:48.796931+00:00`. UsageQuota `27e983dd-5aa2-4aa0-945c-11435918eb01`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-20T06:22:48.796931+00:00`
- (F2) Subscription `74280cbc-fa5c-438a-9d49-c05601196cf4`: planId=free,status=active,billingInterval=NULL,updatedAt=`2026-07-20T06:22:50.169300+00:00`. UsageQuota `e3642a8e-a1d5-43c9-87b0-28c5d3c781e1`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-20T06:22:50.169300+00:00`

**GRANT SQL (single-row, explicit WHERE on each userId; psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c6b1aca1f10731e9866b7dd38';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c6b1aca1f10731e9866b7dd38';
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cd63b6832b67eb3aa3d9a58c2';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cd63b6832b67eb3aa3d9a58c2';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — qa-adversary applies at end of THIS closure run, before finishing; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20T06:22:48.796931+00:00' WHERE "userId"='c6b1aca1f10731e9866b7dd38';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20T06:22:48.796931+00:00' WHERE "userId"='c6b1aca1f10731e9866b7dd38';
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20T06:22:50.169300+00:00' WHERE "userId"='cd63b6832b67eb3aa3d9a58c2';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20T06:22:50.169300+00:00' WHERE "userId"='cd63b6832b67eb3aa3d9a58c2';
```
Note: runsUsed/spendUsedUsd accrue during paid cover-letter testing on F1; revert resets to pre-run 0/0 (orchestrator-test-induced usage removal, not fabrication). F2 must stay 0/0 (every no-résumé refusal must refund). Test rows (Resume/Job/CoverLetter/Application/AgentRun/BackgroundJob) created during testing are test data → enumerate + delete at cleanup (registered in TEST-DATA-CLEANUP-LEDGER.md; both emails match the binding `mv-qa-%@example.com` DELETE pattern). Revert applied at: **2026-07-20T~06:46Z (this qa-adversary, self-applied)** — 4× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted, run under `search_path=aether` (?schema= stripped via urllib). AFTER-state verified byte-for-byte (evidence adversarial/final-closure/db/revert-applied.json): F1+F2 both Subscription planId=free/status=active/billingInterval=NULL/updatedAt restored to signup ts; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt restored (updatedAt equality asserted against before-state as datetimes — MATCH). Confirmed live: GET /billing/entitlement → active_paid:false, plan.id=free for BOTH (evidence api/zz-post-revert-entitlement-F1.json + -F2.json).

**GRANT APPLIED:** 2026-07-20T~06:23Z (4× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement → active_paid:true, plan.id=pro for BOTH accounts (evidence adversarial/final-closure/api/00-entitlement-F1-granted.json + 00-entitlement-F2-granted.json).

---

## FINAL-PASS GRANT (qa-adversary §6 loop-exit condensed pass) — 2026-07-20

**Purpose:** FINAL condensed adversarial pass on PROD @f491170 (Merge fix/nf-final-closure: unicode-aware JD keyword tokenizer + honest no-résumé refusal surfacing on the agents console/pipeline; api+web restarted 07:53Z). Verifies the three fresh fix surfaces + condensed §3.2 sweep. Real LLM, async path. TWO fresh disposable accounts.

**Accounts (fresh disposable, registered 2026-07-20T~08:41Z via POST /auth/register with browser UA):**
- (Z1) DISTINCT SYNTHETIC RÉSUMÉ: `mv-qa-final2-2a385f@example.com` · userId `c669c1cdb0ff1b2cd0a9b8bf9` (name "Vesper Adversaria-Final2")
- (Z2) NO RÉSUMÉ EVER: `mv-qa-final2-2a385f-nr@example.com` · userId `c472704ece8d0718539b47954`

**BEFORE-state (captured live 2026-07-20T~08:41Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped via python urllib.urlsplit/parse_qsl — NOT sed; current_schema()==aether asserted before every op; free rows lazily created by the first GET /billing/entitlement):**
- (Z1) Subscription `0dabad55-4ed0-41da-8055-9e764d67f7c4`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,updatedAt=`2026-07-20 08:41:44.884144+00`. UsageQuota `4ba89603-5ef7-47ef-85ff-dd63f0cdbbfe`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-20 08:41:44.884144+00`
- (Z2) Subscription `cb4c45c0-77b4-4db5-b236-6e36f4b365e6`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,updatedAt=`2026-07-20 08:41:45.295654+00`. UsageQuota `9b52211e-3c82-454a-a215-b08fd332386b`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,updatedAt=`2026-07-20 08:41:45.295654+00`

**GRANT SQL (single-row, explicit WHERE on each userId; psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c669c1cdb0ff1b2cd0a9b8bf9';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c669c1cdb0ff1b2cd0a9b8bf9';
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c472704ece8d0718539b47954';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c472704ece8d0718539b47954';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — qa-adversary applied at end of THIS pass, before finishing; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 08:41:44.884144+00' WHERE "userId"='c669c1cdb0ff1b2cd0a9b8bf9';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 08:41:44.884144+00' WHERE "userId"='c669c1cdb0ff1b2cd0a9b8bf9';
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 08:41:45.295654+00' WHERE "userId"='c472704ece8d0718539b47954';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 08:41:45.295654+00' WHERE "userId"='c472704ece8d0718539b47954';
```
Note: runsUsed/spendUsedUsd accrued during paid testing on Z1 (§3.2 sweep clicked Run All + Regenerate); revert resets to pre-run 0/0 (orchestrator-test-induced usage removal, not fabrication). Z2 stayed 0/0 (every no-résumé refusal refunded). Test rows (Resume/Job/Application(coverLetter)/AgentRun/BackgroundJob) are test data → deleted with the accounts at cleanup (registered in TEST-DATA-CLEANUP-LEDGER.md; both emails match the binding `mv-qa-%@example.com` DELETE pattern).

**GRANT APPLIED:** 2026-07-20T~08:42Z (4× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement → active_paid:true, plan.id=pro for BOTH (evidence adversarial/final-pass/api/00-entitlement-Z1-granted.json + 00-entitlement-Z2-granted.json).

**REVERT APPLIED:** 2026-07-20T~09:03Z (this qa-adversary, self-applied) — 4× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted, run under `search_path=aether` (?schema= stripped via urllib). AFTER-state verified byte-for-byte (evidence adversarial/final-pass/db/zz-revert-verify.json): both Z1+Z2 Subscription planId=free/status=active/billingInterval=NULL/updatedAt restored to signup ts; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt restored (byte_for_byte_match=True). Confirmed live: GET /billing/entitlement → active_paid:false, plan.id=free for BOTH.

---

## FINAL-PASS-001 CLOSURE GRANT (qa-adversary, focused NF-final-pass-001 closure re-verify) — 2026-07-20

**Purpose:** FOCUSED closure re-verify of NF-final-pass-001 (non-Latin-script / non-ASCII-capital CamelCase JD-keyword gluings) on PROD @main c158729 (Merge fix/nf-final-pass-001: unicode case-based CamelCase segmenter `_camel_humps`; aether-api restarted 2026-07-20T12:20:16Z, running deployed code). ONE disposable account, minimal synthetic résumé. Verify the 5 reported gluings + reverse-order variants produce NO artifact chips, controls preserved (München dropped; standalone Киев/İstanbul/Zürich NOT suppressed; legit tech present), plus one novel adversarial of my own design.

**Account (fresh disposable, registered 2026-07-20T12:26:02Z via POST /auth/register with browser UA):**
- `mv-qa-lastcheck-be068b@example.com` · userId `c644b4d74664667b71f26e438` (name "Verity Lastcheck")

**BEFORE-state (captured live 2026-07-20T12:26:23Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped via python urllib — NOT sed; current_schema()==aether asserted before every op; free rows lazily created by the first GET /billing/entitlement at 12:26:11Z). Evidence: adversarial/final-pass-001-closure/db/00-before-state.json:**
- Subscription `da2733ad-fe3f-4f21-9940-3bc648f2222c`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,currentPeriod*=NULL,cancelAtPeriodEnd=false,createdAt=`2026-07-20 12:26:11.939328+00`,updatedAt=`2026-07-20 12:26:11.939328+00`
- UsageQuota `761414d8-0c16-43c3-8daf-b4e8c3a609d1`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,periodStart=2026-07-01,periodEnd=2026-08-01,updatedAt=`2026-07-20 12:26:11.939328+00`

**GRANT SQL (single-row, explicit WHERE on my userId; psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='c644b4d74664667b71f26e438';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='c644b4d74664667b71f26e438';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — qa-adversary applies at end of THIS closure run, before finishing; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 12:26:11.939328+00' WHERE "userId"='c644b4d74664667b71f26e438';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 12:26:11.939328+00' WHERE "userId"='c644b4d74664667b71f26e438';
```
Note: the insights keyword-chip verification is a read of deployed-tokenizer output on crafted JDs; test rows (Resume/Job/CoverLetter/Application) created for this account are test data → deleted with the account at cleanup (registered in TEST-DATA-CLEANUP-LEDGER.md; email matches the binding `mv-qa-%@example.com` DELETE pattern). Revert applied at (FINAL-PASS-001 account c644b4d…): **2026-07-20T12:38Z (this qa-adversary, self-applied)** — 2× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted, run under `search_path=aether` (?schema= stripped via urllib). AFTER-state verified byte-for-byte (evidence adversarial/final-pass-001-closure/db/zz-revert-verify.json, byte_for_byte_match=True): Subscription planId=free/status=active/billingInterval=NULL/updatedAt restored to `2026-07-20 12:26:11.939328+00`; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt restored. runsUsed stayed 0 throughout (insights reads are unmetered; no Regenerate/Generate clicked). Confirmed live: GET /billing/entitlement → active_paid:false, plan.id=free (evidence api/zz-post-revert-entitlement.json).

**GRANT APPLIED:** 2026-07-20T12:26:~35Z (2× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement → active_paid:true, plan.id=pro (evidence adversarial/final-pass-001-closure/api/00-entitlement-granted.json).

---

## FINAL-PASS-002 CLOSURE GRANT (qa-adversary, focused NF-final-pass-002 closure re-verify) — 2026-07-20

**Purpose:** FOCUSED closure re-verify of NF-final-pass-002 (caseless-script proper-noun CamelCase JD-keyword gluings — the leak I discovered in the FINAL-PASS-001 closure run) on PROD @main 54c28e5 (Merge fix/nf-final-pass-002: single-label-segment gluings are artifacts, closing the len<2 early-return family; fix commit 9ceb92f; aether-api restarted 2026-07-20T13:33:04Z, gate 967/0 COMPLETED BEFORE restart). ONE fresh disposable account, minimal synthetic résumé. Distinct account from the FINAL-PASS-001 run (that one already reverted; left alone).

**Account (fresh disposable, registered 2026-07-20T13:38:03Z via POST /auth/register with browser UA):**
- `mv-qa-lastcheck2-ff967d@example.com` · userId `cc62794585997022a7897e2f0` (name "Verity Lastcheck Two")

**BEFORE-state (captured live 2026-07-20T13:38:17Z, single-row reads via psycopg2 under `options=-c search_path=aether`, `?schema=` stripped via python urllib — NOT sed; current_schema()==aether asserted before every op; free rows lazily created by the first GET /billing/entitlement at 13:38:16Z). Evidence: adversarial/final-pass-002-closure/db/00-before-state.json:**
- Subscription `f8b68ee7-69fc-41d4-b21f-907477bfcfa4`: planId=free,status=active,billingInterval=NULL,stripe*=NULL,currentPeriod*=NULL,cancelAtPeriodEnd=false,createdAt=`2026-07-20 13:38:16.965884+00`,updatedAt=`2026-07-20 13:38:16.965884+00`
- UsageQuota `0bfd7b8d-cd17-44ee-8571-74de7297df1a`: planId=free,runsAllowed=5,runsUsed=0,spendCapUsd=1.0,spendUsedUsd=0,periodStart=2026-07-01,periodEnd=2026-08-01,updatedAt=`2026-07-20 13:38:16.965884+00`

**GRANT SQL (single-row, explicit WHERE on my userId; psycopg2 under search_path=aether, autocommit off, rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='pro', "status"='active', "updatedAt"=now() WHERE "userId"='cc62794585997022a7897e2f0';
UPDATE "UsageQuota"   SET "planId"='pro', "runsAllowed"=100, "spendCapUsd"=15.0, "updatedAt"=now() WHERE "userId"='cc62794585997022a7897e2f0';
```

**REVERT SQL (byte-for-byte restore of BEFORE-state — qa-adversary applies at end of THIS closure run, before finishing; rowcount asserted ==1 each):**
```sql
UPDATE "Subscription" SET "planId"='free', "status"='active', "billingInterval"=NULL, "updatedAt"='2026-07-20 13:38:16.965884+00' WHERE "userId"='cc62794585997022a7897e2f0';
UPDATE "UsageQuota" SET "planId"='free', "runsAllowed"=5, "runsUsed"=0, "spendCapUsd"=1.0, "spendUsedUsd"=0, "updatedAt"='2026-07-20 13:38:16.965884+00' WHERE "userId"='cc62794585997022a7897e2f0';
```
Note: insights keyword-chip reads are unmetered; test rows (Resume/Job/CoverLetter/Application) are test data → deleted with the account at cleanup (registered in TEST-DATA-CLEANUP-LEDGER.md; email matches `mv-qa-%@example.com`). Revert applied at: **2026-07-20T13:44Z (this qa-adversary, self-applied)** — 2× `UPDATE 1`, rowcount asserted ==1 each, current_schema()==aether asserted, run under `search_path=aether` (?schema= stripped via urllib). AFTER-state verified byte-for-byte (evidence adversarial/final-pass-002-closure/db/zz-revert-verify.json, byte_for_byte_match=True): Subscription planId=free/status=active/billingInterval=NULL/updatedAt restored to `2026-07-20 13:38:16.965884+00`; UsageQuota planId=free/runsAllowed=5/runsUsed=0/spendCapUsd=1.0/spendUsedUsd=0/updatedAt restored. runsUsed stayed 0 throughout (insights reads unmetered). Confirmed live: GET /billing/entitlement → active_paid:false, plan.id=free (evidence api/zz-post-revert-entitlement.json).

**GRANT APPLIED:** 2026-07-20T13:38:~30Z (2× `UPDATE 1`, rowcount asserted ==1 each). Confirmed live: GET /billing/entitlement → active_paid:true, plan.id=pro (evidence adversarial/final-pass-002-closure/api/00-entitlement-granted.json).
