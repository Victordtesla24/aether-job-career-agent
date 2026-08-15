# PROD-PRISTINE-WIPE-MANIFEST — 2026-08-15

**Status: REVIEWED MANIFEST — READ-ONLY. Nothing in this document has been executed.**
**Author role:** migrator sub-agent (Phase 6 Aether run), operating strictly read-only per the operator's
brief. Zero `INSERT`/`UPDATE`/`DELETE`/DDL was issued against production while authoring this file — every
number below comes from `SELECT`/`\d` only.
**Executor:** none yet. This manifest requires operator sign-off on the flags in §0.2, then execution by a
`janitor`-class agent (never the author), per the binding precedent in `ADR-PROD-TESTDATA-PURGE.md` §8.1 C8.
**Operator ruling this manifest implements:** reset the app to the exact state a brand-new subscriber sees.
TRUE PRISTINE — wipe ALL product data including Story Bank + the evidence corpus; owner keeps LOGIN ONLY;
billing/financial audit rows survive; quota resets to a fresh-subscriber state.

Claim tags: **[VERIFIED-WITH-SOURCE]** = read directly against production DB or repository source this
session, reproduced below. **[INFERRED-FROM-PROMPT]** = a reading of the operator's scope decisions applied
to a fact pattern the operator did not enumerate explicitly. **[ASSUMED-PENDING-PROBE]** = stated but not
independently confirmed this session.

---

## 0.1 Operational note — mid-task worktree churn (read before anything else)

While this manifest was being authored, a **concurrent process removed 8 git worktrees** from
`/home/ubuntu/github_repos/`, including `aether-wt-orch-exec` — the directory this task named as the write
target (`aether-wt-orch-exec/docs/delivery/...`). `git worktree list` in the canonical repo no longer shows
it registered either. **[VERIFIED-WITH-SOURCE]**

- No work was lost: the worktree's branch, `orch/exec-20260814`, is safely pushed to
  `origin/orch/exec-20260814` and was re-fetched and diffed clean during this session (e.g.
  `apps/api/app/repositories/agent_directive.py`, `AgentDirective` table def, recovered via
  `git show origin/orch/exec-20260814:...`).
- **This manifest was written to the canonical repo instead:**
  `/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md`
  — same file the ADR-PROD-TESTDATA-PURGE precedent lives in, and the same repo the backup script
  (`deploy/aether-backup.sh`) hardcodes as `REPO_ROOT`.
- I took no corrective action on the worktree churn itself (out of scope for a read-only manifest task) and
  did not touch git state beyond `fetch`/`show`/`diff` (no writes, no branch checkout, no commit).
- **Escalate to the orchestrator:** confirm whether the worktree removal was intentional (end-of-run cleanup)
  before relying on any other in-flight worktree path in later steps of this run.

---

## 0.2 Flags requiring explicit operator sign-off before execution

These are the only open questions. Everything else in this manifest is a direct, unambiguous application of
the operator's four scope decisions.

| # | Flag | What I found | Recommendation |
|---|---|---|---|
| **F1** | **`abhikadam28@gmail.com`** (`c4dc7f26c8b6adea37c5a6c75`) — real (non-test) free-tier signup, 2026-08-03 | `ADR-PROD-TESTDATA-PURGE.md` explicitly named this account "the real free user" and structurally **protected** it from deletion. This task's operator scope decision (2) only addresses the **owner**'s account; it does not say whether *other real* accounts survive a TRUE PRISTINE reset. **[VERIFIED-WITH-SOURCE]** this account's product-data footprint is **zero** — `Job`/`AgentRun`/`Application`/`Resume`/`StoryEntry`/`GmailAccount` all return 0 rows for this `userId`. | Because the footprint is zero, the choice is low-stakes either way. Default manifest below treats it as **DELETE-ENTIRELY** (consistent with "brand-new subscriber = only the owner's login survives"), but the SQL is a single literal to add back to the survivor list if the operator instead wants it treated like the owner (KEEP LOGIN ONLY). **Do not execute past this flag without an explicit operator choice.** |
| **F2** | **`ProviderCredential`** (operator-scoped LLM credentials, 4 rows: `anthropic` oauth_token, `openai`/`groq`/`gemini` api_key) | Global table, no `userId` column — confirmed `provider` is the sole key. Deleting the `anthropic` row disconnects the **system-default Anthropic subscription** every agent run falls back to. **[VERIFIED-WITH-SOURCE]** | **KEEP** (not touched by the DELETE plan below) — this is deployment config, not user product data. **OPERATOR-DECISION**, not authored by me: if the operator wants a fully blank credential slate too, add `DELETE FROM "ProviderCredential"` as an explicit extra step; the app will run with no configured provider until re-added (§6, cross-session impacts). |
| **F3** | **Sales-agent tables** (`SalesCampaign` 5, `SalesLead` 2, `SalesOutreachLog` 18, `SalesSuppressionList` 2) | Not covered by any of the operator's four scope points. These are the owner's own outbound growth-agent operational data (leads/campaigns/suppression list), **not** subscriber-facing product data — a brand-new subscriber's product experience is unaffected by whether these rows exist. One row is a real inbound lead (`eyecycreator@pb05.wixemails.com`, unsubscribed + suppressed) with genuine consent/suppression obligations attached. `SalesCampaign`'s 5 rows are **not** auto-reseeded by the app (`_ensure_sales_tables()` creates the tables but does not seed rows — confirmed by reading `apps/api/app/repositories/sales.py` in full), so wiping them requires a manual reseed to restore the 5 campaign templates. **[VERIFIED-WITH-SOURCE]** | **KEEP by default** (business-ops data, analogous to `AdminAuditLog`, not "product data" a subscriber sees). **OPERATOR-DECISION**: if the operator wants the sales-agent surface reset too (its 2 leads are themselves recent test-period artifacts — the suppressions are dated during this same UAT window), that is a separate, additive DELETE block, given at the end of §3. |
| **F4** | **Orphaned `Subscription`/`UsageQuota` pair**, `userId = cac00bd20be02a849c53eda71` | This `userId` has **no** matching `User` row (0 rows), and 0 rows anywhere else I checked (`AgentRun`, `Job`, `AdminAuditLog.actorUserId`). `Subscription`/`UsageQuota` carry no FK to `User` (confirmed against `pg_constraint` — same 17-tables-with-no-FK gap `ADR-PROD-TESTDATA-PURGE.md` §3.2/§6.1 already documented once), so a prior User deletion left this pair behind. **[VERIFIED-WITH-SOURCE]** | **DELETE** — it belongs to nobody, "KEEP billing rows" cannot mean "keep a billing row with no owner." Included in the main plan below (§3, step D2). |
| **F5** | **Stripe live customer** `cus_V3y74AxRiKjfQc` attached to `c4f6928b582aa401f50f888c2` (a test persona being deleted below) | Same Stripe-side gap the prior ADR flagged for 2 other test identities (§9 there): the local `Subscription` row is the only pointer to this Stripe customer object. Deleting the local row is in-scope for this VM; the Stripe-side object is not — **[VERIFIED-WITH-SOURCE]** `stripeSubscriptionId` is NULL (customer object only, no live subscription, no charge). | **OPERATOR-DEFERRED**, exactly per the prior ADR's precedent: recommend the operator delete or tag this customer in the Stripe **live** dashboard after the DB-side wipe. Not actionable from this VM. |

---

## 1. Full table census — `aether` schema, 41 tables

`SELECT count(*)` per table, as of **2026-08-15T02:10:49Z** [VERIFIED-WITH-SOURCE] (re-run twice, 5 minutes
apart, identical both times — production is quiescent for this schema right now, unlike the moving-target
census the prior ADR hit; still, **re-run this census immediately before executing**, per that ADR's C5
lesson).

| # | Table | Rows | Action |
|---|---|---:|---|
| 1 | `AdminAuditLog` | 747 | **KEEP** |
| 2 | `AdminSetting` | 3 | **KEEP** |
| 3 | `AgentConfig` | 23 | **WIPE** |
| 4 | `AgentProvider` | 2 | **WIPE** |
| 5 | `AgentQuotaBlock` | 0 | **WIPE** (assert-zero no-op) |
| 6 | `AgentRun` | 9,202 | **WIPE** |
| 7 | `AnswerBankItem` | 2 | **WIPE** |
| 8 | `AnswerBankUsage` | 0 | **WIPE** (assert-zero no-op) |
| 9 | `AnthropicOAuthState` | 1 | **WIPE** |
| 10 | `AnthropicOAuthToken` | 1 | **WIPE** |
| 11 | `Application` | 666 | **WIPE** |
| 12 | `ApplicationStatusEvent` | 672 | **WIPE** |
| 13 | `ApprovalRequest` | 660 | **WIPE** |
| 14 | `BackgroundJob` | 272 | **WIPE** |
| 15 | `CareerProfile` | 3 | **WIPE** |
| 16 | `Contact` | 0 | **WIPE** (assert-zero no-op) |
| 17 | `EmailThread` | 457 | **WIPE** |
| 18 | `EvidenceCorpusItem` | 390 | **WIPE** (the "377-item corpus" cited in the brief — current live count is 390; treating the live count as authoritative, see §1.1) |
| 19 | `GmailAccount` | 2 | **WIPE** |
| 20 | `GoogleCredential` | 0 | **WIPE** (assert-zero no-op) |
| 21 | `InterviewSchedule` | 0 | **WIPE** (assert-zero no-op) |
| 22 | `Job` | 10,221 | **WIPE** |
| 23 | `JobEmbedding` | 0 | **WIPE** (assert-zero no-op) |
| 24 | `JobSourceStatus` | 22 | **WIPE** |
| 25 | `Offer` | 0 | **WIPE** (assert-zero no-op) |
| 26 | `OutreachTask` | 0 | **WIPE** (assert-zero no-op) |
| 27 | `PasswordResetToken` | 5 | **WIPE** |
| 28 | `Plan` | 4 | **KEEP** (pure reference/config, no user data — pricing catalogue) |
| 29 | `ProviderCredential` | 4 | **F2 — OPERATOR-DECISION, default KEEP** |
| 30 | `Resume` | 503 | **WIPE** |
| 31 | `SalesCampaign` | 5 | **F3 — OPERATOR-DECISION, default KEEP** |
| 32 | `SalesLead` | 2 | **F3 — OPERATOR-DECISION, default KEEP** |
| 33 | `SalesOutreachLog` | 18 | **F3 — OPERATOR-DECISION, default KEEP** |
| 34 | `SalesSuppressionList` | 2 | **F3 — OPERATOR-DECISION, default KEEP** |
| 35 | `StoryEntry` | 79 | **WIPE** (Story Bank) |
| 36 | `StripeEvent` | 8 | **KEEP** |
| 37 | `Subscription` | 11 | **KEEP for survivors / DELETE for departing users** — see §2.3 |
| 38 | `UsageQuota` | 11 | **RESET for survivors / DELETE for departing users** — see §2.4 |
| 39 | `User` | 10 | **PER-ROW** — see §2.5 |
| 40 | `UserEntitlementOverride` | 2 | **WIPE** |
| 41 | `UserProviderCredential` | 0 | **WIPE** (assert-zero no-op) |

**Tables the brief names that do not exist in production** (checked directly against `pg_tables`, not
inferred): `RunPlan`, `AgentDirective`, any `Notification*` table, any `*Cache*`/market-cache table. All
return **0 rows from `pg_tables`** — these features have lazy-DDL definitions in the repo
(`run_plan.py` → `RunPlan`; the in-flight `agent_directive.py` on branch `origin/orch/exec-20260814` →
`AgentDirective`) but their `_ensure_*_tables()` has never fired against this production database, so the
tables have never been created. **Nothing to wipe — there is no row and no table.** [VERIFIED-WITH-SOURCE]

### 1.1 EvidenceCorpusItem count discrepancy

The brief cites "the 377-item evidence corpus." The live count is **390**. I did not attempt to reconcile
the 13-row gap (it is 8 days' worth of drift on an actively-running system, same class of drift the prior
ADR observed hour-to-hour) — the WIPE action is identical regardless of the exact number, and the
verification step in §4 checks for **0**, not for a specific historical count. Re-verify the count
immediately before execution per §5.4's re-census requirement below.

---

## 2. Per-table classification and rationale

### 2.1 WIPE — product data (28 tables + assert-zero no-ops)

`Job`, `Resume`, `Application`, `ApplicationStatusEvent`, `ApprovalRequest`, `AgentRun`, `BackgroundJob`,
`StoryEntry`, `EvidenceCorpusItem`, `AnswerBankItem`, `AnswerBankUsage`, `EmailThread`, `Contact`,
`OutreachTask`, `Offer`, `InterviewSchedule`, `JobSourceStatus`, `AgentProvider`, `AgentConfig`,
`CareerProfile`, `GmailAccount`, `GoogleCredential`, `UserProviderCredential`, `AgentQuotaBlock`,
`AnthropicOAuthState`, `AnthropicOAuthToken`, `PasswordResetToken`, `JobEmbedding`, `UserEntitlementOverride`.

All 29 are per-user product/session data with `userId` (or, for `ApplicationStatusEvent`/`JobEmbedding`,
one hop from `userId` via `applicationId`/`jobId`). None carries financial-integrity or audit value. A
brand-new subscriber has zero rows in every one of these tables.

- **`AgentConfig` — explicitly called out.** WIPE is correct because an **absent** `AgentConfig` row reads as
  **enabled** — confirmed directly from the code's own doc comment
  (`apps/api/app/routers/agents.py:2059-2062`, `_agent_paused_by_user`): *"an absent row means enabled... the
  permanent guard at the reserve point owns the closed-world check."* A brand-new subscriber has no
  `AgentConfig` rows and every agent card defaults to enabled — wiping this table reproduces that state
  exactly, it does not disable anything. [VERIFIED-WITH-SOURCE]
- **`UserProviderCredential` (user-scoped)** vs **`ProviderCredential` (operator-scoped, F2)** — confirmed by
  column inspection: `UserProviderCredential` has a `userId` column, `ProviderCredential` does not (its PK is
  bare `provider`). The WIPE here is `UserProviderCredential` only (currently 0 rows). `ProviderCredential`
  is F2, addressed separately.
- **`UserEntitlementOverride` — including the owner's own row.** Two rows exist: one is the owner's own
  self-granted `kind=unlimited` override (`setBy` = owner, created 2026-08-14T22:26Z); the other is the same
  grant extended to test persona `sfixa-verify` (`cfefb94bff93aada257fb202e`, `setBy` = owner). "Quota
  counters reset to a fresh-subscriber state" (scope decision 3) means **no** override — a fresh subscriber
  has none. Wiping this table also wipes the owner's own admin-granted unlimited entitlement; it is
  self-service to re-grant via the admin panel post-wipe if the operator wants it back, and I call this out
  explicitly rather than silently keeping it, since a stale `unlimited` grant is exactly the kind of thing
  that would make a "pristine" claim false. [VERIFIED-WITH-SOURCE]

### 2.2 KEEP — audit/financial/config (5 tables, unconditionally, no predicate)

`AdminAuditLog` (747), `StripeEvent` (8), `Plan` (4), `AdminSetting` (3), plus F2's `ProviderCredential` (4,
pending operator sign-off, default KEEP).

- `AdminAuditLog`/`StripeEvent` — financial/audit integrity, matches `ADR-PROD-TESTDATA-PURGE.md` §4.2/§4.4
  verbatim (StripeEvent = webhook idempotency ledger; deleting a `processed` row invites Stripe redelivery
  to be reprocessed as new, i.e. double-billing).
- `Plan` — pricing catalogue, 4 rows (`free`/`starter`/`pro`/`power`), no user data, referenced by
  `Subscription.planId`/`UsageQuota.planId` as a lookup, not owned by any user.
- `AdminSetting` — 3 rows, checked content directly: `signup_enabled=true`, `email_verification_enabled=false`,
  `salesAgent.lastDigestDate="2026-08-15"`. Pure global feature-flag config, no PII, no per-user state.
  [VERIFIED-WITH-SOURCE]

### 2.3 `Subscription` — KEEP for survivors, DELETE for departing users

`Subscription` has **no** FK to `User` (confirmed against `pg_constraint` — it is one of the 17 tables the
prior ADR already flagged as orphan-risk). "KEEP billing/financial audit rows... (Subscription)" (scope
decision 3) is read as **KEEP the rows belonging to users who still exist after this wipe** — not "keep every
`Subscription` row regardless of whether its owner survives," which would manufacture new orphans identical
to the pre-existing one in F4. This reading is directly supported by `ADR-PROD-TESTDATA-PURGE.md` §4.1: that
ADR **approved deleting** `Subscription`/`UsageQuota` for departing test users on the grounds that free-tier,
no-Stripe-money rows "carry no financial-integrity value; the authoritative money record lives in Stripe, not
here." The same reasoning applies here (checked fresh: 9 of the 10 departing rows have `stripeSubscriptionId`
IS NULL and no real subscription; the tenth — F5 — has a Stripe **customer** object only, no subscription,
handled as an operator-deferred item, not a reason to keep the local row). [VERIFIED-WITH-SOURCE]

**Owner's row is untouched** (`planId='pro'`, real Stripe customer `cus_UvLRWZMJc6iGX2`, no subscription id —
a manually comped Pro, not a paid Stripe subscription). Not reset, not deleted — this is exactly what "KEEP"
means for the surviving account.

### 2.4 `UsageQuota` — RESET for survivors, DELETE for departing users

**What a fresh subscriber's `UsageQuota` row looks like — read directly from the repository code, not
guessed:** `apps/api/app/repositories/billing.py`, `ensure_user_billing()` (the function every new signup
runs through) inserts exactly:

```sql
INSERT INTO "UsageQuota" ("userId","planId","periodStart","periodEnd",
                         "runsAllowed","runsUsed","spendCapUsd","spendUsedUsd","createdAt","updatedAt")
VALUES (%s, 'free', date_trunc('month', now()), date_trunc('month', now()) + interval '1 month',
        <Plan.runsPerMonth for that plan>, 0, <Plan.spendCapUsdMonthly for that plan>, 0, now(), now())
```

and the same shape is what `UsageQuotaRepository._roll_expired_period()` writes every month for an existing
user (minus `planId`/`runsAllowed`/`spendCapUsd`, which that path assumes are already correct — mine cannot
make that assumption, because the owner's current row carries entitlement-override-inflated values, not the
plan's raw numbers). [VERIFIED-WITH-SOURCE]

**Owner's row today:** `planId=pro, runsAllowed=100000, runsUsed=108, spendCapUsd=10000.0,
spendUsedUsd=4.665536` — the 100,000/`$`10,000 figures are the effect of the `unlimited`
`UserEntitlementOverride` being wiped in §2.1, not the Pro plan's real numbers (`Plan.pro = 100 runs /
$15.00`). **RESET** for the owner means: reset to the *current Subscription plan's* real numbers (Pro:
100/$15), zero usage, fresh period — matching what a Pro subscriber looks like on day one, not what a Free
subscriber looks like (the owner's Subscription/planId is being **kept**, so the quota row must agree with
it).

```sql
UPDATE "UsageQuota" SET
  "planId"       = 'pro',
  "periodStart"  = date_trunc('month', now()),
  "periodEnd"    = date_trunc('month', now()) + interval '1 month',
  "runsAllowed"  = (SELECT "runsPerMonth"       FROM "Plan" WHERE id = 'pro'),
  "runsUsed"     = 0,
  "spendCapUsd"  = (SELECT "spendCapUsdMonthly" FROM "Plan" WHERE id = 'pro'),
  "spendUsedUsd" = 0,
  "updatedAt"    = now()
WHERE "userId" = 'c6c8d0163d973a8048e7e33b8';
```

If F1 resolves to KEEP `abhikadam28@gmail.com`, add the identical shape with `'free'` substituted for
`'pro'` (their current `Subscription.planId`) and their `userId`.

Departing users' `UsageQuota` rows (including the F4 orphan) are **DELETEd**, not reset — there is no
"fresh-subscriber state" for a subscriber who no longer has an account.

### 2.5 `User` — per-row disposition (all 10 rows enumerated)

Live columns confirmed directly (`schema.prisma` is stale/incomplete — it only carries the Phase-1 columns;
the additive columns below were added by lazy DDL in `apps/api/app/db.py` and only show up via `\d "User"` /
`information_schema.columns`, not the Prisma file): `id, email, name, image, passwordHash, createdAt,
updatedAt, targetRole, location, agentConfig(jsonb), username, isAdmin, suspended, lastLoginAt,
passwordChangedAt`. [VERIFIED-WITH-SOURCE]

| id | email | isAdmin | createdAt | Disposition |
|---|---|---|---|---|
| `c6c8d0163d973a8048e7e33b8` | sarkar.vikram@gmail.com | **true** | 2026-07-20 | **KEEP ROW, clear profile columns** — see below |
| `c4dc7f26c8b6adea37c5a6c75` | abhikadam28@gmail.com | false | 2026-08-03 | **F1 — OPERATOR-DECISION** (default: DELETE-ENTIRELY) |
| `c4f6928b582aa401f50f888c2` | melbvicduque+aethertest@gmail.com | false | 2026-08-13 | DELETE-ENTIRELY (test persona — Gmail plus-alias `+aethertest`; carries F5 Stripe-deferred item) |
| `cb4c47f230b952c9760308a5f` | sready-j2-1786667086738@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |
| `cfefb94bff93aada257fb202e` | sfixa-verify-1786677852@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona; holds the second `UserEntitlementOverride` row) |
| `c5120629cebd44754002ea24a` | sfixd-verify-1786678388@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |
| `c443caf7fb6a9e88faa291a0d` | orch-dedup-1786707553229@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |
| `c68c0e63194cec28b59ae9984` | orch-dedup-1786707570509@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |
| `c2b1c63eeb6542885600defd5` | qa-adminfull-1786735975@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |
| `c7809f0cca5ee67b596ba6e69` | qa-adminfull-1786735991@example.com | false | 2026-08-14 | DELETE-ENTIRELY (test persona) |

**`admin@aether.local`** (the seed demo account named in the brief) is **NOT PRESENT** — 0 rows match that
email right now. [VERIFIED-WITH-SOURCE] There is nothing to KEEP or delete for it. This is consistent with,
not contradictory to, "the boot rotation recreates/manages it anyway": I read `apply_admin_rotation()`
(`apps/api/app/repositories/admin.py`) in full — it only ever **demotes** (`isAdmin=false`) an *existing*
seed row on every boot; it never *creates* one. Since `AETHER_ADMIN_EMAIL=sarkar.vikram@gmail.com`
[VERIFIED-WITH-SOURCE, `.env`], the rotation's grant step (`INSERT ... ON CONFLICT (email) DO UPDATE SET
isAdmin=true`) targets the **owner's own row**, not the seed row — meaning the rotation will re-assert
`isAdmin=true` and re-stamp `passwordHash` from `AETHER_ADMIN_PASSWORD_HASH` on the owner's account on the
very next API restart, **regardless of what this manifest does to that row**. This is exactly why `username`
and `isAdmin` are correctly excluded from the "clear profile columns" list below — the rotation would just
re-assert them, and nulling `username` mid-transaction only to have it partially reconciled by the next boot
adds risk for no benefit.

**Owner row — exact column disposition:**

| Column | Action | Why |
|---|---|---|
| `id`, `email`, `passwordHash`, `createdAt` | **KEEP unchanged** | scope decision (2): "email+passwordHash+account row survives" |
| `username`, `isAdmin` | **KEEP unchanged** | explicit instruction + rotation would re-assert them anyway (above) |
| `suspended` | **KEEP unchanged** (`false`) | account-state flag, not a profile field; owner must stay unsuspended |
| `lastLoginAt`, `passwordChangedAt` | **KEEP unchanged** | login/security metadata, not "profile," not named in scope decision (2) |
| `name`, `image` | **CLEAR → NULL** | profile fields |
| `targetRole`, `location` | **CLEAR → NULL** | profile fields ("baseline resume" itself is the `Resume` table, wiped in full in §2.1 — these two are the free-text career-target/location fields on `User` itself) |
| `agentConfig` (jsonb column on `User`, distinct from the `AgentConfig` **table**) | **CLEAR → NULL** | this is the literal "agent configs...wiped" item from scope decision (2) |
| `updatedAt` | set to `now()` by the UPDATE | standard |

```sql
UPDATE "User" SET
  "name" = NULL, "image" = NULL, "targetRole" = NULL, "location" = NULL,
  "agentConfig" = NULL, "updatedAt" = now()
WHERE "id" = 'c6c8d0163d973a8048e7e33b8';
```

---

## 3. FK/dependency order and exact DELETE statements

### 3.1 The one binding ordering constraint

Of 17 live FK constraints (`pg_constraint`, re-enumerated fresh — this schema has grown since the prior ADR's
16-FK count, gaining `ApplicationStatusEvent` and `JobEmbedding`), only **one** is `RESTRICT`:

```
Application_resumeId_fkey | Application.resumeId -> Resume(id) | ON DELETE RESTRICT
```

Everything else is `CASCADE`, `SET NULL`, or **no FK at all** (soft reference / independent `userId`
column). Because this is an **unconditional full-table wipe** (not filtered by `userId` the way the prior
test-data purge was), cascade/SET NULL ordering is cosmetic — the end state is identical regardless of
order, since every row disappears either way. The RESTRICT constraint is the only one that can actually
**abort a statement**: `Resume` cannot be cleared while any `Application` row still points at it. **Explicit
per-table deletes are used throughout anyway** (never relying on cascade), per `ADR-TR-1` and the binding
precedent in `ADR-PROD-TESTDATA-PURGE.md` C3 (cascade-reliance previously produced 40 silently orphaned
rows on this exact schema).

### 3.2 Full statement list, in order, single transaction

```sql
BEGIN;

-- Pre-flight baseline (delta guards, never literals — see §4.3)
CREATE TEMP TABLE _wipe_baseline AS
SELECT
  (SELECT count(*) FROM "AdminAuditLog")      AS n_audit,
  (SELECT count(*) FROM "StripeEvent")        AS n_stripe,
  (SELECT count(*) FROM "Plan")               AS n_plan,
  (SELECT count(*) FROM "AdminSetting")       AS n_adminsetting,
  (SELECT count(*) FROM "ProviderCredential") AS n_provcred,
  (SELECT "isAdmin" FROM "User" WHERE id = 'c6c8d0163d973a8048e7e33b8') AS owner_was_admin;

-- ===== WIPE: product data, children-before-parents, RESTRICT-safe order =====
DELETE FROM "ApplicationStatusEvent";
DELETE FROM "AnswerBankUsage";
DELETE FROM "ApprovalRequest";
DELETE FROM "EmailThread";
DELETE FROM "BackgroundJob";
DELETE FROM "OutreachTask";
DELETE FROM "Offer";
DELETE FROM "InterviewSchedule";
DELETE FROM "Application";              -- MUST precede Resume (RESTRICT)
DELETE FROM "AnswerBankItem";
DELETE FROM "EvidenceCorpusItem";
DELETE FROM "Contact";
DELETE FROM "Resume";
DELETE FROM "JobEmbedding";
DELETE FROM "Job";
DELETE FROM "StoryEntry";
DELETE FROM "AgentRun";
DELETE FROM "JobSourceStatus";
DELETE FROM "AgentProvider";
DELETE FROM "AgentConfig";
DELETE FROM "CareerProfile";
DELETE FROM "GmailAccount";
DELETE FROM "GoogleCredential";
DELETE FROM "UserProviderCredential";
DELETE FROM "AgentQuotaBlock";
DELETE FROM "AnthropicOAuthState";
DELETE FROM "AnthropicOAuthToken";
DELETE FROM "PasswordResetToken";
DELETE FROM "UserEntitlementOverride";

-- ===== D2 (F4): pre-existing orphaned billing pair, owner-less =====
DELETE FROM "Subscription" WHERE "userId" = 'cac00bd20be02a849c53eda71';
DELETE FROM "UsageQuota"   WHERE "userId" = 'cac00bd20be02a849c53eda71';

-- ===== Departing users' billing rows (identity predicate only, C2-style) =====
-- Survivor set: owner only, by default. Add 'c4dc7f26c8b6adea37c5a6c75' to this
-- list (both places) iff F1 resolves to KEEP abhikadam28@gmail.com.
DELETE FROM "Subscription" WHERE "userId" NOT IN ('c6c8d0163d973a8048e7e33b8');
DELETE FROM "UsageQuota"   WHERE "userId" NOT IN ('c6c8d0163d973a8048e7e33b8');

-- ===== User: delete every row except the owner (add abhikadam28's id per F1 if kept) =====
DELETE FROM "User" WHERE "id" NOT IN ('c6c8d0163d973a8048e7e33b8');

-- ===== RESET: owner's UsageQuota to a fresh-Pro-subscriber state =====
UPDATE "UsageQuota" SET
  "planId" = 'pro',
  "periodStart" = date_trunc('month', now()),
  "periodEnd"   = date_trunc('month', now()) + interval '1 month',
  "runsAllowed" = (SELECT "runsPerMonth" FROM "Plan" WHERE id = 'pro'),
  "runsUsed" = 0,
  "spendCapUsd" = (SELECT "spendCapUsdMonthly" FROM "Plan" WHERE id = 'pro'),
  "spendUsedUsd" = 0,
  "updatedAt" = now()
WHERE "userId" = 'c6c8d0163d973a8048e7e33b8';

-- ===== PER-ROW: owner profile columns cleared, login preserved =====
UPDATE "User" SET
  "name" = NULL, "image" = NULL, "targetRole" = NULL, "location" = NULL,
  "agentConfig" = NULL, "updatedAt" = now()
WHERE "id" = 'c6c8d0163d973a8048e7e33b8';

-- ===== Post-flight guards (deltas, not literals — see §4.3) =====
DO $$
DECLARE
  b RECORD;
  n_owner_now int;
BEGIN
  SELECT * INTO b FROM _wipe_baseline;
  IF (SELECT count(*) FROM "AdminAuditLog") <> b.n_audit THEN
    RAISE EXCEPTION 'GUARD FAILED: AdminAuditLog row count changed (was %)', b.n_audit;
  END IF;
  IF (SELECT count(*) FROM "StripeEvent") <> b.n_stripe THEN
    RAISE EXCEPTION 'GUARD FAILED: StripeEvent row count changed (was %)', b.n_stripe;
  END IF;
  IF (SELECT count(*) FROM "Plan") <> b.n_plan THEN
    RAISE EXCEPTION 'GUARD FAILED: Plan row count changed (was %)', b.n_plan;
  END IF;
  IF (SELECT count(*) FROM "AdminSetting") <> b.n_adminsetting THEN
    RAISE EXCEPTION 'GUARD FAILED: AdminSetting row count changed (was %)', b.n_adminsetting;
  END IF;
  IF (SELECT count(*) FROM "ProviderCredential") <> b.n_provcred THEN
    RAISE EXCEPTION 'GUARD FAILED: ProviderCredential row count changed (was %)', b.n_provcred;
  END IF;
  SELECT count(*) INTO n_owner_now FROM "User" WHERE id = 'c6c8d0163d973a8048e7e33b8' AND "isAdmin" = b.owner_was_admin;
  IF n_owner_now <> 1 THEN
    RAISE EXCEPTION 'GUARD FAILED: owner row missing or isAdmin changed unexpectedly';
  END IF;
END $$;

COMMIT;
```

### 3.3 Additive block — only if F3 resolves to WIPE the sales-agent tables

Not part of the default plan (F3 default is KEEP). If the operator elects to wipe:

```sql
DELETE FROM "SalesOutreachLog";
DELETE FROM "SalesLead";
DELETE FROM "SalesSuppressionList";
DELETE FROM "SalesCampaign";   -- NOT auto-reseeded; the 5 template rows must be manually recreated afterward
```

### 3.4 Additive block — only if F2 resolves to wipe the operator credential slot

Not part of the default plan (F2 default is KEEP). If the operator elects to wipe:

```sql
DELETE FROM "ProviderCredential";  -- disconnects the Anthropic subscription default; every agent falls
                                    -- back to "not configured" until an operator re-adds a credential
```

---

## 4. Verification section

### 4.1 WIPE tables — expected `count(*) = 0` after commit

```sql
SELECT
  (SELECT count(*) FROM "AgentConfig")            AS "AgentConfig",
  (SELECT count(*) FROM "AgentProvider")           AS "AgentProvider",
  (SELECT count(*) FROM "AgentQuotaBlock")         AS "AgentQuotaBlock",
  (SELECT count(*) FROM "AgentRun")                AS "AgentRun",
  (SELECT count(*) FROM "AnswerBankItem")          AS "AnswerBankItem",
  (SELECT count(*) FROM "AnswerBankUsage")         AS "AnswerBankUsage",
  (SELECT count(*) FROM "AnthropicOAuthState")     AS "AnthropicOAuthState",
  (SELECT count(*) FROM "AnthropicOAuthToken")     AS "AnthropicOAuthToken",
  (SELECT count(*) FROM "Application")             AS "Application",
  (SELECT count(*) FROM "ApplicationStatusEvent")  AS "ApplicationStatusEvent",
  (SELECT count(*) FROM "ApprovalRequest")         AS "ApprovalRequest",
  (SELECT count(*) FROM "BackgroundJob")           AS "BackgroundJob",
  (SELECT count(*) FROM "CareerProfile")           AS "CareerProfile",
  (SELECT count(*) FROM "Contact")                 AS "Contact",
  (SELECT count(*) FROM "EmailThread")             AS "EmailThread",
  (SELECT count(*) FROM "EvidenceCorpusItem")      AS "EvidenceCorpusItem",
  (SELECT count(*) FROM "GmailAccount")            AS "GmailAccount",
  (SELECT count(*) FROM "GoogleCredential")        AS "GoogleCredential",
  (SELECT count(*) FROM "InterviewSchedule")       AS "InterviewSchedule",
  (SELECT count(*) FROM "Job")                     AS "Job",
  (SELECT count(*) FROM "JobEmbedding")            AS "JobEmbedding",
  (SELECT count(*) FROM "JobSourceStatus")         AS "JobSourceStatus",
  (SELECT count(*) FROM "Offer")                   AS "Offer",
  (SELECT count(*) FROM "OutreachTask")            AS "OutreachTask",
  (SELECT count(*) FROM "PasswordResetToken")      AS "PasswordResetToken",
  (SELECT count(*) FROM "Resume")                  AS "Resume",
  (SELECT count(*) FROM "StoryEntry")               AS "StoryEntry",
  (SELECT count(*) FROM "UserEntitlementOverride") AS "UserEntitlementOverride",
  (SELECT count(*) FROM "UserProviderCredential")  AS "UserProviderCredential";
-- every column above MUST read 0
```

### 4.2 KEEP tables — expected unchanged counts

| Table | Expected count | Basis |
|---|---:|---|
| `AdminAuditLog` | 747 (or higher — this table only ever grows) | must not shrink |
| `StripeEvent` | 8 exactly | must not change |
| `Plan` | 4 exactly | must not change |
| `AdminSetting` | 3 exactly | must not change |
| `ProviderCredential` | 4 exactly (pending F2) | must not change unless F2 → wipe |
| `SalesCampaign` | 5 exactly (pending F3) | must not change unless F3 → wipe |
| `SalesLead` | 2 exactly (pending F3) | must not change unless F3 → wipe |
| `SalesOutreachLog` | 18 exactly (pending F3) | must not change unless F3 → wipe |
| `SalesSuppressionList` | 2 exactly (pending F3) | must not change unless F3 → wipe |

### 4.3 RESET table — `UsageQuota`

```sql
SELECT "userId","planId","periodStart","periodEnd","runsAllowed","runsUsed","spendCapUsd","spendUsedUsd"
FROM "UsageQuota";
```
Expected: **exactly 1 row** (owner only, by default) — `userId='c6c8d0163d973a8048e7e33b8', planId='pro',
periodStart = first of current month, periodEnd = first of next month, runsAllowed=100, runsUsed=0,
spendCapUsd=15.0, spendUsedUsd=0`. (2 rows if F1 → keep abhikadam28, with the `free` plan's 5/1.0 numbers for
that row.)

### 4.4 PER-ROW — `User`, expected surviving rows

```sql
SELECT id, email, "isAdmin", "name", "image", "targetRole", "location", "agentConfig", username, suspended
FROM "User";
```
Expected: **exactly 1 row** by default —
`id=c6c8d0163d973a8048e7e33b8, email=sarkar.vikram@gmail.com, isAdmin=true, name=NULL, image=NULL,
targetRole=NULL, location=NULL, agentConfig=NULL, username='Vikram', suspended=false`.
(2 rows if F1 → keep abhikadam28, unmodified except by the general User DELETE not touching it.)

### 4.5 Guard failure behavior

The `DO $$ ... $$` block in §3.2 raises and aborts the whole transaction (nothing commits) if any KEEP
table's count moved, or if the owner row is missing or its `isAdmin` value changed. This mirrors
`ADR-PROD-TESTDATA-PURGE.md` §7.5's corrected C12 pattern (deltas captured inside the same transaction, never
a literal typed into a document) — that ADR's own postmortem on why a *literal* guard is itself a defect on
a live system.

---

## 5. Backup precondition

### 5.1 The real mechanism (proven, not aspirational)

`deploy/aether-backup.sh` + `deploy/aether-backup.service` + `deploy/aether-backup.timer`, documented in
`docs/delivery/DEPLOYMENT-RUNBOOK.md` §10. **[VERIFIED-WITH-SOURCE]**

- Installed and enabled: `systemctl status aether-backup.timer` → `Loaded: ... enabled`.
- `pg_dump`/`psql` on this VM are now **17.11** (Ubuntu PGDG repo), matching the production server's
  **17.9/17.11** — the version-mismatch failure the prior ADR hit (client 16.14 vs server 17.9, 0-byte dump)
  is **fixed** on this host; confirmed fresh this session (`pg_dump --version` → 17.11). Unlike the prior
  ADR, `pg_dump` is **usable here now** — no need for the JSONL-fallback mechanism that ADR had to invent.
- Most recent local backup on disk: `aether-20260814T120001Z.sql.gz` (13,191,749 B), 2026-08-14T12:00:01Z —
  **~2h10m old** as of this manifest's census timestamp, inside the 6-hour RPO but not fresh enough to be
  "the" pre-wipe backup.
- **Proven restore machinery** (not just "a script exists"): `DEPLOYMENT-RUNBOOK.md` §10.3 records a real
  restore drill against a real dump on 2026-08-14, restoring into a scratch schema
  (`aether_restore_test`, never over production) and matching the live schema exactly (31/31 tables,
  `User` 4/4, `Application` 571/571, `Job` 8267/8267), with the live schema re-verified unchanged immediately
  after. Evidence: `uat/reports/evidence/market-perf/s-fix/O-2-restore-drill-summary.txt` and
  `O-2-restore-drill-output.log`.

### 5.2 Exact command for a fresh pre-wipe backup

```bash
/home/ubuntu/github_repos/aether-job-career-agent/deploy/aether-backup.sh
```

(Same command the timer runs — safe to invoke on demand; it never writes to production, only reads via
`pg_dump --schema=aether`.) This produces a new
`/home/ubuntu/aether-backups/db/aether-<TIMESTAMP>.sql.gz`, mirrored to
`s3://<bucket>/<path>aether-db-backups/aether-<TIMESTAMP>.sql.gz`.

### 5.3 How to verify the fresh backup before trusting it

```bash
# 1. Confirm the new file landed locally and in S3, non-trivial size
ls -la /home/ubuntu/aether-backups/db/aether-<TIMESTAMP>.sql.gz
aws s3 ls s3://<bucket>/<path>aether-db-backups/aether-<TIMESTAMP>.sql.gz

# 2. Restore into a scratch schema (never over production) — DEPLOYMENT-RUNBOOK.md §10.2, verbatim recipe
gunzip -c /home/ubuntu/aether-backups/db/aether-<TIMESTAMP>.sql.gz > /tmp/restore.sql
sed -e 's/aether\./aether_restore_test./g' \
    -e 's/^CREATE SCHEMA aether;$/CREATE SCHEMA aether_restore_test;/' \
    /tmp/restore.sql > /tmp/restore-remapped.sql
# (parse DATABASE_URL into PG* env vars per the runbook — credential never in argv)
psql -v ON_ERROR_STOP=1 -f /tmp/restore-remapped.sql

# 3. Row-count spot check against THIS manifest's §1 census (must match exactly, pre-wipe)
psql -t -c "SET search_path=aether_restore_test; SELECT count(*) FROM \"Job\";"      -- expect 10221
psql -t -c "SET search_path=aether_restore_test; SELECT count(*) FROM \"AgentRun\";" -- expect 9202
psql -t -c "SET search_path=aether_restore_test; SELECT count(*) FROM \"User\";"     -- expect 10

# 4. Clean up
psql -t -c "DROP SCHEMA aether_restore_test CASCADE;"
```

### 5.4 Binding preconditions before any DELETE runs

1. Fresh backup per §5.2, verified per §5.3 — **not** the 2h10m-old one already on disk.
2. **Re-run §1's census** immediately before executing. If any WIPE-table count has moved materially, or if
   any **new** `User` row appeared, treat it the same way `ADR-PROD-TESTDATA-PURGE.md`'s C5-A quiescence gate
   did: pause and get the drift re-approved rather than silently widening scope.
3. Resolve F1–F5 in §0.2 explicitly before the janitor is handed this file.
4. Executor is a `janitor`-class agent, never this authoring role (mirrors `ADR-PROD-TESTDATA-PURGE.md` C8).

---

## 6. Cross-session impacts

- **Sales-agent shadow tables (F3).** Addressed as its own flag in §0.2 — not covered by the operator's four
  scope decisions, defaulted to KEEP with an additive DELETE block in §3.3 if the operator wants them wiped
  too. If wiped, `SalesCampaign`'s 5 templates are **not** auto-reseeded (`_ensure_sales_tables()` only
  creates tables, never rows) and must be manually recreated to restore the Welcome / Free→paid nudge /
  Re-engagement / Demo-response / LinkedIn-draft campaigns.
- **`storyExtraction` re-key item is moot once `AgentConfig` is wiped.** `docs/delivery/SESSION-COORDINATION.md`
  (line 532) records a peer finding that the owner's `AgentConfig` row with `agentKey="storyExtraction"`
  never actually overrides the live `storyExtractor` backend dispatch (`agentKey` mismatch by one letter) —
  filed as "harmless today... flagged for the owner/next slice." Wiping `AgentConfig` in full (§2.1/§3.2)
  removes that orphaned/legacy row along with everything else — **no separate re-key fix is needed**, this
  wipe closes it as a side effect.
- **Discovery timer + board-sweep against an empty DB — fail-closed, not silently broken.** With
  `CareerProfile` wiped, `POST /agents/scout/run` and `POST /agents/pipeline/run` return **HTTP 422** naming
  the missing profile fields — confirmed directly from `docs/delivery/ADR-F02-USER-SCOPED-DISCOVERY.md`
  (§ citing the exact behavior: *"the scout never ran"* on an empty profile, refusal by name not
  substitution). `scripts/discovery_cron.sh` authenticates as the owner and will hit the same 422 until the
  owner re-completes their `CareerProfile`. This is the intended honest-empty-state behavior, not a defect
  introduced by the wipe.
- **Email agent with no Gmail connection — honest degradation, not a crash.** `GmailAccount` is wiped; any
  code path that needs Gmail (`apps/api/app/services/gmail_service.py`, `application_submission.py`,
  `approvals.py`) raises `GmailNotConnectedError`, surfaced to callers as **HTTP 409** ("no Gmail account
  connected, or an expired grant" — `apps/api/app/routers/approvals.py:546`), not a 500 or a silent no-op.
  Matches the "brand-new subscriber, nothing connected yet" state exactly.
- **Analytics on an empty DB.** Every dashboard/analytics surface that aggregates `Job`/`Application`/
  `AgentRun` will show honest zero/empty states post-wipe (0 jobs discovered, 0 applications, no run
  history) — consistent with a subscriber who has not run an agent yet. Not independently re-verified this
  session (this manifest is read-only and pre-execution); flagged **[ASSUMED-PENDING-PROBE]** for the QA
  pass that follows execution.
- **Pre-existing orphan pattern confirmed to recur.** F4 (an owner-less `Subscription`/`UsageQuota` pair) is
  the same class of defect `ADR-PROD-TESTDATA-PURGE.md` §6.1 already documented once ("production users
  *have* been deleted before... no execution record proving it followed §13.2"). This manifest cleans up the
  one instance found; it does not fix the underlying gap (17 tables with no FK to `User`) — that remains
  filed as future schema-hardening work, not something to bundle into this destructive operation.
- **Worktree churn (§0.1).** Recorded above; repeated here because it is a cross-session operational fact,
  not a data-wipe consequence — the orchestrator should confirm intent before other in-flight work assumes
  `aether-wt-orch-exec` still exists.

---

## Summary

- **Tables enumerated:** 41
- **WIPE:** 29 (`AgentConfig`, `AgentProvider`, `AgentQuotaBlock`, `AgentRun`, `AnswerBankItem`,
  `AnswerBankUsage`, `AnthropicOAuthState`, `AnthropicOAuthToken`, `Application`, `ApplicationStatusEvent`,
  `ApprovalRequest`, `BackgroundJob`, `CareerProfile`, `Contact`, `EmailThread`, `EvidenceCorpusItem`,
  `GmailAccount`, `GoogleCredential`, `InterviewSchedule`, `Job`, `JobEmbedding`, `JobSourceStatus`, `Offer`,
  `OutreachTask`, `PasswordResetToken`, `Resume`, `StoryEntry`, `UserEntitlementOverride`,
  `UserProviderCredential`)
- **KEEP:** 5 unconditional (`AdminAuditLog`, `StripeEvent`, `Plan`, `AdminSetting`) + 1 pending (F2
  `ProviderCredential`) + 4 pending (F3 `SalesCampaign`/`SalesLead`/`SalesOutreachLog`/`SalesSuppressionList`)
- **RESET:** 1 (`UsageQuota` — 1 surviving row by default)
- **Mixed KEEP-for-survivors/DELETE-for-departing:** 1 (`Subscription`)
- **PER-ROW:** 1 (`User` — 10 rows in, 1 survives by default with 5 columns cleared, 9 deleted)
- **Not present in production (nothing to wipe):** `RunPlan`, `AgentDirective`, any `Notification*`/cache
  table

**Operator-decision flags requiring sign-off before execution:** F1 (abhikadam28@gmail.com disposition), F2
(operator-scoped `ProviderCredential` — default KEEP), F3 (sales-agent tables — default KEEP), F4 (orphaned
billing pair — recommend DELETE, low-controversy), F5 (Stripe-side customer `cus_V3y74AxRiKjfQc` —
operator-deferred, Stripe dashboard action, not a DB action).

**Manifest path:**
`/home/ubuntu/github_repos/aether-job-career-agent/docs/delivery/PROD-PRISTINE-WIPE-MANIFEST-2026-08-15.md`

**Executed against production this session: nothing. Every statement above is proposed, not run.**
