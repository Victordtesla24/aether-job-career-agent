# Aether Billing & Subscription Architecture

**Status:** ✅ **AS-BUILT** — this design was approved (`BILLING-ARCH-APPROVAL.md`, ratified per `ADR-P6-PRICING`)
and **implemented, tested (mocked Stripe), and deployed to production in Phase 6**. The live payment
round-trip is **pending operator Stripe keys** (see `docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md`, H-01/H-02/H-03,
which supersedes the Phase-6 checklist for current status); all code, schema, quota/spend-cap enforcement,
and `/pricing` are live. This document is the architecture reference for what shipped — the `§0.1`
"green-field / tables ABSENT" schema facts below describe the *pre-build* state observed at design time
(probe-15) and are annotated inline where the built system now differs.
**Author:** `billing-arch` sub-agent (Phase 6 Aether run).
**Date:** 2026-07-16 (design); implemented + deployed same run.
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`.
**Production:** https://5cb5f0620.abacusai.cloud (health `0.2.0`).

> **[PHASE-7 UPDATE, 2026-07-17]** Two changes since this document's Phase-6 authorship:
> (1) the runtime-reality claim in the paragraph immediately below (Anthropic OAuth "PROHIBITED") is
> **corrected** — see the inline annotation there; (2) quota reserve/refund now has an async variant
> (reserve-at-enqueue instead of reserve-before-run) for background generation jobs — see new **§4.4**.
> Both are `GAP-P7-DEF-A` / `GAP-P7-ASYNC-001`, `docs/delivery/PHASE7-GAP-ANALYSIS.md`.

## 0. Epistemic legend & inputs

All non-trivial claims carry a tag. No inference is presented as observation.

| Tag | Meaning |
|-----|---------|
| `[VERIFIED-WITH-SOURCE]` | From a live-fetched, dated research artifact under `uat/reports/evidence/phase6/`. |
| `[VERIFIED-FROM-PROBE]` | Observed directly in the probe-15 schema dump / code inventory / live probe. |
| `[INFERRED-FROM-PROMPT]` | Taken from the swarm prompt §14.x; market-cross-checked where noted. |
| `[DESIGN-DECISION]` | A choice made by this design; adjustable by orchestrator/human. Not verified. |
| `[ASSUMED-PENDING-PROBE]` | Not yet verified; explicitly flagged as an assumption. |

**Source artifacts consumed (all read in full):**
- `uat/reports/evidence/phase6/probe-15-schema.json` — 23 tables / 227 columns `[VERIFIED-FROM-PROBE]`.
- `uat/reports/evidence/phase6/anthropic-pricing-verified.md` — per-MTok USD rates `[VERIFIED-WITH-SOURCE]`.
- `uat/reports/evidence/phase6/stripe-au-fees-verified.md` — AU Stripe fees `[VERIFIED-WITH-SOURCE]`.
- `uat/reports/evidence/phase6/competitor-pricing-verified.md` — competitor band + FX 1 USD = 1.43 AUD `[VERIFIED-WITH-SOURCE]`.
- `uat/reports/evidence/phase6/RESEARCH-REVIEW-fable5.md` — fable-5 rulings 3b/3c/3d (binding).
- Code inventory: `probe-04-routes.json`, `inventory-backend.json`, `probe-08-agent-runs.json`, `probe-03-llm-mode.json`, `probe-19-webhook.json`, `probe-17-admin-cred.json`, and direct reads of `apps/api/app/routers/agents.py`, `apps/api/app/repositories/user_provider_credential.py`, `apps/api/app/db.py`, `apps/api/app/main.py`, `apps/api/app/rate_limit.py`.

**Runtime reality honored throughout `[VERIFIED-FROM-PROBE probe-03]`:** production LLM provider is **OpenRouter** (`AETHER_LLM_MODE=auto`; reasoning `deepseek/deepseek-v4-pro`, fast `deepseek/deepseek-v4-flash`, structured `qwen/qwen3-coder-next`) — **not** Anthropic — for the deepseek/qwen routing tiers a plan's `modelTier` maps to. ~~Anthropic third-party subscription OAuth is PROHIBITED~~ **[PHASE-7 CORRECTION, `[VERIFIED-WITH-SOURCE]` `docs/delivery/PHASE7-GAP-ANALYSIS.md` ADR-P7-01, `GAP-P7-DEF-A`]:** this Phase-6 blanket claim is **superseded for one narrow mechanism**. The Anthropic provider-credential endpoints (`PUT /api/agents/providers/anthropic/credential` and the per-user `PUT /api/agents/user/providers/anthropic/credential`) now accept **two** credential formats, auto-detected from the secret prefix: a Claude Console API key (`sk-ant-api…` → `x-api-key` header) **or** a pasted Claude Code OAuth token (`sk-ant-oat01-…`, the output of running `claude setup-token` on the operator's own machine → `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20`). ADR-P7-01's ruling: pasting one's own pre-generated setup-token is a *different mechanism* from the in-app interactive "Connect with Anthropic" OAuth-consent flow that ADR-P6-OAUTH found ToS-prohibited — **that interactive flow remained removed/unsupported through Phase 7**; only the paste-a-token path was permitted then. **[MODELS-LIVE AS-BUILT CORRECTION, `[VERIFIED-WITH-SOURCE]` `docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md` `ADR-ML-1`/`ADR-ML-2`/`ADR-ML-2a`, binding, operator-mandated, 2026-07-22]:** ADR-P6-OAUTH's removal is now **reversed for a compliant re-authoring** of that flow — the in-app **"Connect with Anthropic (subscription)"** OAuth flow is shipped and live: the operator clicks the button, **Anthropic's own** authorize page (`https://claude.com/cai/oauth/authorize`) opens in a new tab, the operator approves and pastes back a one-time `code#state`, and the server exchanges it server-side via PKCE (`https://platform.claude.com/v1/oauth/token`) — never a third-party-hosted consent page, no client secret registered outside Anthropic's own public CLI client id. The exchanged token is stored in the same deployment-wide `ProviderCredential('anthropic')` seam as the manual `oauth_token` paste (billing/routing via `resolve_provider` is unchanged), auto-refreshes ahead of expiry, and marks the credential `needs_reauth` (with an honest "Renew now" UI affordance) on refresh failure rather than silently reusing a stale token. The manual paste-a-token path described above remains available as a fallback. See `apps/api/app/services/anthropic_oauth.py` and `docs/subscription/model-catalog.md` §7 for full mechanics. An `oauth_token`-mode credential (however obtained) is stored encrypted and, on save, atomically synced to the repo-root `.env` as `CLAUDE_CODE_OAUTH_TOKEN` (0600 permissions, value never logged, `apps/api/app/services/env_file_writer.py`) so the async worker process can also read it. Quota exhaustion never silently falls through to a different credential (GATE-06, `[VERIFIED-WITH-SOURCE]` `uat/reports/evidence/phase7/step10-cluster1-gates.json`). Per-user spend is still tracked in **USD** from `AgentRun.costUsd` regardless of which Anthropic credential mode (if any) is active — Anthropic calls are a defect-fix/operator capability, not the default production billing/routing path, which remains OpenRouter as described above.

### 0.1 Schema facts this design is reconciled against `[VERIFIED-FROM-PROBE probe-15]`

- **`User` primary key: column `id`, type `text`, NOT NULL, no default** (cuid-shaped, minted by app `new_id()`). All billing `userId` columns are therefore **`text`** — *not* uuid, *not* integer.
- **`AgentRun` spend column: `costUsd numeric` (nullable)** — this is the authoritative per-run USD cost already populated on completion. It is the spend-tracking source of truth. `AgentRun` also has `userId text`, `agentName text`, `status "AgentRunStatus"`, `createdAt timestamp`, `billingAuditJson jsonb`.
- **Billing tables ABSENT (at design time):** `Plan`, `Subscription`, `UsageQuota`, `StripeEvent`, `AdminAuditLog` reported `false` in probe-15. Green-field additive build. **[AS-BUILT: all five tables now EXIST in production** — created via additive lazy DDL `_ensure_billing_tables()` (advisory lock 7420240719) + backfill; deploy-verify.json confirms them live.**]**
- **No privilege/role column on `User` (at design time)** (`probe-17`: `isAdmin`/`role` absent). **[AS-BUILT: Cluster F shipped** — additive `isAdmin` (default false), `suspended`, `lastLoginAt` columns on `User` + the `AdminSetting` table + credential rotation now exist in production (`admin/admin123` demoted to `isAdmin=false`); admin panel Tier 1 is live, formal closure pending the operator's own admin credential.**]**
- **DB access is raw psycopg2** via `app.db.get_connection()` (short-lived connections, 25-conn cap), `new_id()`, `rows_to_dicts()`. No ORM at the API layer; Prisma owns the base schema only.

---

## 1. Pricing model

### 1.1 GST rule (applies to every AUD figure)

Prices are **GST-inclusive AUD**. For any inclusive total:

```
gst = round(total / 11, 2)      # 10% GST embedded in a GST-inclusive price
net = total - gst               # == round(total / 1.1, 2) to the cent
```

Margins in §1.4 are computed on **GST-exclusive net revenue = total / 1.1** `[per RESEARCH-REVIEW-fable5 §3b ruling]`.

### 1.2 Final tier table

Tier slugs and monthly AUD prices are `[INFERRED-FROM-PROMPT §14.1]`, **market-validated** against the verified competitor band A$19.99–A$71.43/mo, none agentic `[VERIFIED-WITH-SOURCE competitor-pricing]`; fable-5 §3d ruling: "§14.1 tiers (A$19/39/69 + Free) are market-valid; keep as-is." **[AS-BUILT per `ADR-P6-PRICING`:** the ratified/shipped figures are the prompt's §14.1 exact values — annual **A$179 / A$359 / A$649** (≈9.4× monthly, ~2 months free) and run quotas **30 / 100 / 300** — NOT the design's originally-proposed 10× annual (A$190/390/690) or 50/200/600 quotas, which were rejected. The tables and DDL below reflect the shipped values.**]** Model-tier mapping is `[DESIGN-DECISION]` (see §1.3).

| Plan | Monthly (incl. GST) | Monthly GST `round(t/11,2)` | Monthly net `t−gst` | Annual (incl. GST) | Annual GST | Annual net | Metered runs/mo | Model tier (app routing) |
|------|--------------------:|----------------------------:|--------------------:|-------------------:|-----------:|-----------:|----------------:|--------------------------|
| **Free**    | A$0.00  | A$0.00 | A$0.00  | —        | —      | —        | 5   | `light` |
| **Starter** | A$19.00 | A$1.73 | A$17.27 | A$179.00 | A$16.27 | A$162.73 | 30  | `standard` |
| **Pro**     | A$39.00 | A$3.55 | A$35.45 | A$359.00 | A$32.64 | A$326.36 | 100 | `advanced` |
| **Power**   | A$69.00 | A$6.27 | A$62.73 | A$649.00 | A$59.00 | A$590.00 | 300 | `premium` |

GST arithmetic (shown so it is auditable): `19/11=1.7273→1.73`, `39/11=3.5455→3.55`, `69/11=6.2727→6.27`; annual `179/11=16.27`, `359/11=32.64`, `649/11=59.00`. Every `net` equals `total/1.1` to the cent.

**"Metered runs"** = agent runs that actually invoke the LLM and therefore incur COGS. Per `probe-08` + `apps/api/app/routers/agents.py::_LLM_TIER_BY_BACKEND` `[VERIFIED-FROM-PROBE]`, those are **`tailor`, `coverLetter`, `storyExtractor`, `emailAgent`**. Deterministic agents (`scout`, `fitScorer`, `matcher`, `supervisor`) make **zero LLM calls / zero spend** and are therefore **not** counted against a plan's run quota (charging for a $0 deterministic run would be dishonest). This is the metering rule the quota middleware (§4) enforces.

### 1.3 Model-tier mapping (plan → app routing → COGS ceiling)

The plan's `modelTier` selects the app's OpenRouter routing tier at runtime `[VERIFIED-FROM-PROBE probe-03]`. Because **no verified OpenRouter price artifact exists**, COGS is costed **conservatively against Anthropic's published per-MTok rates** `[VERIFIED-WITH-SOURCE anthropic-pricing]` as an **upper bound** — real deepseek COGS is materially lower (probe-08 shows real completed runs at ~$0.0005–$0.0009 each), so every margin below is a **floor**.

| Plan model tier | OpenRouter route (runtime, probe-03) | COGS ceiling model (verified rate) | Per-MTok in/out USD |
|-----------------|--------------------------------------|------------------------------------|---------------------|
| `light`    | `deepseek-v4-flash` | Claude Haiku 4.5           | $1 / $5 |
| `standard` | `deepseek-v4-flash`/`-pro` | Claude Sonnet 5 (intro)   | $2 / $10 |
| `advanced` | `deepseek-v4-pro`   | Claude Opus 4.x            | $5 / $25 |
| `premium`  | `deepseek-v4-pro`   | Claude Opus 4.x            | $5 / $25 |

Intro Sonnet-5 pricing holds through 2026-08-31, then $3/$15 `[VERIFIED-WITH-SOURCE]`; Starter COGS ceiling rises ~50% after that date but stays far inside margin (§1.4). Free tier is **Haiku-only** `[VERIFIED-WITH-SOURCE §3b]`.

### 1.4 Unit economics / margin (monthly, per paying user)

Inputs, all cited:
- **Net revenue (ex-GST)** = monthly total / 1.1 `[GST rule §1.1]`.
- **Stripe fee** = domestic card **1.7% + A$0.30** on the GST-inclusive charge `[VERIFIED-WITH-SOURCE stripe-au-fees; fable-5 §3c: use 1.7%]`. Stripe fees are themselves GST-inclusive; the small input-tax-credit on the fee is *ignored* here (conservative).
- **LLM COGS** = verified per-user monthly cost at the plan's COGS-ceiling model and a representative usage tier `[VERIFIED-WITH-SOURCE anthropic-pricing cost model, 70:30 in:out]`, converted at **1 USD = 1.43 AUD** `[VERIFIED-WITH-SOURCE competitor-pricing / RBA 2026-07-16]`. Usage-tier→plan assignment is `[DESIGN-DECISION]`.

| Plan | Net rev ex-GST (A$) | Stripe fee (A$) | COGS ceiling (USD → A$) | Usage tier used | Contribution (A$) | Margin on net |
|------|--------------------:|----------------:|-------------------------|-----------------|------------------:|--------------:|
| **Free**    | 0.00  | 0.00 (no charge) | Haiku Light $0.11 → A$0.16 | 50K tok/mo | **−0.16** | loss-leader (5-run cap) |
| **Starter** | 17.27 | 0.62 (`19×1.7%+0.30`) | Sonnet5-intro Avg $0.88 → A$1.26 | 200K tok/mo | **15.39** | **89.1 %** |
| **Pro**     | 35.45 | 0.96 (`39×1.7%+0.30`) | Opus Avg $2.20 → A$3.15 | 200K tok/mo | **31.34** | **88.4 %** |
| **Power**   | 62.73 | 1.47 (`69×1.7%+0.30`) | Opus Heavy $6.60 → A$9.44 | 600K tok/mo | **51.82** | **82.6 %** |

Annual (Stripe fee charged once on the annual total; COGS ×12), recomputed on the ratified annual prices A$179/359/649: Starter **≈A$144 (≈88.6 %)**, Pro **≈A$282 (≈86.4 %)**, Power **≈A$465 (≈78.9 %)**. *(Illustrative unit economics; exact COGS varies with live token usage.)*

**Sensitivity notes:**
- *International card* (3.5% + A$0.30 `[VERIFIED-WITH-SOURCE]`) worst case: Power fee A$2.72 → contribution A$50.57 (80.6 %). Margins stay >80 %.
- *Real COGS on OpenRouter* is ~1–2 orders of magnitude below the Anthropic ceiling (probe-08), so realized margins approach the Stripe-fee-only ceiling (~93–97 %).
- Free tier is a bounded funnel cost: capped at 5 metered runs and a **USD safety spend cap** (§2), max exposure ≈ A$0.16–A$1.9/user/mo.

### 1.5 Stripe Tax recommendation — **DO NOT enable at launch** `[DESIGN-DECISION, grounded in VERIFIED figures]`

Stripe Tax (Complete) starts at **A$140/month on a 1-year contract** `[VERIFIED-WITH-SOURCE stripe-au-fees; fable-5 §3c flagged this]`. For an **AU-only, single-rate (10% GST), GST-inclusive** product the GST computation is trivial and fully deterministic: `gst = round(total/11, 2)`. **The GST math is identical whether Stripe Tax is on or off** — Stripe Tax buys automated multi-jurisdiction determination + filing, which this launch does not need.

Break-even: A$140/mo ÷ A$15.39 Starter contribution ≈ **9.1 paying Starter subs** (or ~2.7 Power subs) consumed **every month** purely to fund Stripe Tax. At launch volume that is pure margin destruction.

**Launch approach:** present GST-inclusive prices; compute the GST line ourselves (`round(total/11,2)`) for the tax invoice/receipt; register Stripe Prices with `tax_behavior='inclusive'`; optionally attach a **manual Stripe Tax Rate (10% GST, inclusive)** — a *free* feature — so the Stripe invoice shows a GST line without the paid product. Checkout carries a config flag `STRIPE_AUTOMATIC_TAX` (default **false**). **Revisit Stripe Tax only when** (a) selling into a second tax jurisdiction (US sales tax / EU VAT), or (b) manual filing becomes burdensome. Note: Stripe's `automatic_tax[enabled]=true` *requires* the paid Stripe Tax product, which is exactly why the flag defaults false.

---

## 2. DDL — additive, idempotent, lazy (ADR-TR-1)

**Delivery mechanism `[VERIFIED-FROM-PROBE inventory-backend + user_provider_credential.py]`:** there is **no migration runner** in this repo. Schema ships as **lazy idempotent DDL inside a repository module** — `apps/api/app/repositories/billing.py` exposing `_ensure_billing_tables()` — guarded by a **transaction-scoped advisory lock** so concurrent first-hit callers cannot race on Postgres's `pg_type` index. Every read/write path calls `_ensure_billing_tables()` before touching a billing table (mirrors `_ensure_user_agent_tables`). The `.sql` file is **documentation only**.

- **Advisory lock id:** `7420240719` `[DESIGN-DECISION — next free]`. Used ids observed in code: 711 AgentConfig, 712 User, 713 CareerProfile, 714 OutreachTask, 715 GoogleCredential, 716 EmailThread/ProviderCredential, 717 UserProviderCredential, 718 GmailAccount. Billing takes **719**.
- **No FK to `User`** on any billing table — mirrors `AgentConfig`/`GmailAccount`/`UserProviderCredential` so the shared test-suite's `TRUNCATE "User"` never trips over them. `userId` is `text`, matching `User.id`.
- **Additive only:** `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `CREATE UNIQUE INDEX IF NOT EXISTS`. **No DROP / no ALTER TYPE / no column rename** anywhere.
- Documentary mirror: `apps/api/migrations/0022_billing.sql` `[DESIGN-DECISION — next migration number after 0020/0021]`.

The DDL below is the authoritative definition executed by `_ensure_billing_tables()` (inside the advisory-lock txn, then `commit()`):

```sql
-- ============================ Plan (catalog) ============================
CREATE TABLE IF NOT EXISTS "Plan" (
    "id"                   text PRIMARY KEY,              -- stable slug: 'free'|'starter'|'pro'|'power'
    "name"                 text        NOT NULL,
    "priceAudMonthly"      numeric     NOT NULL DEFAULT 0,  -- GST-inclusive AUD
    "priceAudAnnual"       numeric,                          -- GST-inclusive AUD; NULL for Free
    "runsPerMonth"         integer     NOT NULL,             -- metered (LLM) agent runs / period
    "modelTier"            text        NOT NULL
        CHECK ("modelTier" IN ('light','standard','advanced','premium')),
    "spendCapUsdMonthly"   numeric     NOT NULL,             -- USD safety ceiling (admin-administered in USD)
    "stripeProductId"      text,                             -- filled by human after Stripe setup
    "stripePriceIdMonthly" text,
    "stripePriceIdAnnual"  text,
    "active"               boolean     NOT NULL DEFAULT true,
    "sortOrder"            integer     NOT NULL DEFAULT 0,
    "createdAt"            timestamptz NOT NULL DEFAULT now(),
    "updatedAt"            timestamptz NOT NULL DEFAULT now()
);

-- ========================= Subscription (per user) ======================
CREATE TABLE IF NOT EXISTS "Subscription" (
    "id"                   text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"               text        NOT NULL,             -- User.id (text); no FK by design
    "planId"               text        NOT NULL,             -- logical ref to Plan.id
    "status"               text        NOT NULL DEFAULT 'active'
        CHECK ("status" IN ('active','trialing','past_due','canceled',
                            'incomplete','incomplete_expired','unpaid','paused')),
    "billingInterval"      text        CHECK ("billingInterval" IN ('month','year')),  -- NULL for Free
    "stripeCustomerId"     text,
    "stripeSubscriptionId" text,
    "currentPeriodStart"   timestamptz,
    "currentPeriodEnd"     timestamptz,
    "cancelAtPeriodEnd"    boolean     NOT NULL DEFAULT false,
    "createdAt"            timestamptz NOT NULL DEFAULT now(),
    "updatedAt"            timestamptz NOT NULL DEFAULT now()
);
-- One current subscription row per user (Free by default; upgraded in place).
CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_userId_key"
    ON "Subscription" ("userId");
-- Fast reverse lookup from a Stripe webhook payload; unique when present.
CREATE UNIQUE INDEX IF NOT EXISTS "Subscription_stripeSubscriptionId_key"
    ON "Subscription" ("stripeSubscriptionId")
    WHERE "stripeSubscriptionId" IS NOT NULL;

-- ===================== UsageQuota (per user, rolling) ===================
CREATE TABLE IF NOT EXISTS "UsageQuota" (
    "id"            text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"        text        NOT NULL,
    "planId"        text        NOT NULL,
    "periodStart"   timestamptz NOT NULL,
    "periodEnd"     timestamptz NOT NULL,
    "runsAllowed"   integer     NOT NULL,
    "runsUsed"      integer     NOT NULL DEFAULT 0,
    "spendCapUsd"   numeric     NOT NULL,                    -- USD ceiling for the period
    "spendUsedUsd"  numeric     NOT NULL DEFAULT 0,          -- USD accumulated from AgentRun.costUsd
    "createdAt"     timestamptz NOT NULL DEFAULT now(),
    "updatedAt"     timestamptz NOT NULL DEFAULT now()
);
-- Exactly one live quota row per user (rolled over in-place each period, §4).
CREATE UNIQUE INDEX IF NOT EXISTS "UsageQuota_userId_key"
    ON "UsageQuota" ("userId");

-- ================ StripeEvent (transaction-safe idempotency) ============
CREATE TABLE IF NOT EXISTS "StripeEvent" (
    "id"          text PRIMARY KEY,                          -- Stripe event id 'evt_...' == idempotency key
    "type"        text        NOT NULL,
    "status"      text        NOT NULL DEFAULT 'processing'
        CHECK ("status" IN ('processing','processed','failed','ignored')),
    "payloadJson" jsonb,
    "receivedAt"  timestamptz NOT NULL DEFAULT now(),
    "processedAt" timestamptz
);

-- ===================== AdminAuditLog (Cluster F sink) ===================
CREATE TABLE IF NOT EXISTS "AdminAuditLog" (
    "id"          text PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "actorUserId" text        NOT NULL,                      -- admin User.id who performed the action
    "action"      text        NOT NULL,                      -- 'spendcap.update'|'plan.override'|'refund.issue'|'plan.edit'|...
    "targetType"  text,                                      -- 'user'|'subscription'|'plan'|'usagequota'
    "targetId"    text,
    "detailJson"  jsonb,                                     -- before/after, USD amounts, reason
    "createdAt"   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS "AdminAuditLog_actor_idx"  ON "AdminAuditLog" ("actorUserId");
CREATE INDEX IF NOT EXISTS "AdminAuditLog_target_idx" ON "AdminAuditLog" ("targetType","targetId");
```

### 2.1 Plan seeding (idempotent, in `_ensure_billing_tables()`)

Catalog rows seed after DDL. Price/quota columns are refreshed on conflict (so tuning the tier table redeploys cleanly); Stripe id columns use `COALESCE` so a human-populated id is never clobbered by a NULL seed:

```sql
INSERT INTO "Plan" ("id","name","priceAudMonthly","priceAudAnnual","runsPerMonth",
                    "modelTier","spendCapUsdMonthly","sortOrder")
VALUES
  ('free',    'Free',    0,   NULL, 5,   'light',    1.00, 0),
  ('starter', 'Starter', 19,  179,  30,  'standard', 5.00, 1),
  ('pro',     'Pro',     39,  359,  100, 'advanced', 15.00,2),
  ('power',   'Power',   69,  649,  300, 'premium',  40.00,3)
ON CONFLICT ("id") DO UPDATE SET
  "name"=EXCLUDED."name",
  "priceAudMonthly"=EXCLUDED."priceAudMonthly",
  "priceAudAnnual"=EXCLUDED."priceAudAnnual",
  "runsPerMonth"=EXCLUDED."runsPerMonth",
  "modelTier"=EXCLUDED."modelTier",
  "spendCapUsdMonthly"=EXCLUDED."spendCapUsdMonthly",
  "sortOrder"=EXCLUDED."sortOrder",
  "updatedAt"=now();
```

`spendCapUsdMonthly` values (Free $1, Starter $5, Pro $15, Power $40) are `[DESIGN-DECISION]` USD safety ceilings sized ~4–6× the representative COGS to absorb heavy months while capping runaway abuse; admin-adjustable in USD (§8).

### 2.2 Backfill — **GATE-34** (all existing users → Free) `[idempotent, WHERE NOT EXISTS]`

Runs inside `_ensure_billing_tables()` immediately after seeding, in the same advisory-locked txn. Fully idempotent and additive; safe to run on every worker start.

```sql
-- Free Subscription for every user lacking one
INSERT INTO "Subscription" ("id","userId","planId","status","billingInterval","createdAt","updatedAt")
SELECT gen_random_uuid()::text, u."id", 'free', 'active', NULL, now(), now()
FROM "User" u
WHERE NOT EXISTS (SELECT 1 FROM "Subscription" s WHERE s."userId" = u."id");

-- Initialized Free UsageQuota for every user lacking one
INSERT INTO "UsageQuota" ("id","userId","planId","periodStart","periodEnd",
                          "runsAllowed","runsUsed","spendCapUsd","spendUsedUsd","createdAt","updatedAt")
SELECT gen_random_uuid()::text, u."id", 'free',
       date_trunc('month', now()),
       date_trunc('month', now()) + interval '1 month',
       (SELECT "runsPerMonth"       FROM "Plan" WHERE "id"='free'),
       0,
       (SELECT "spendCapUsdMonthly" FROM "Plan" WHERE "id"='free'),
       0, now(), now()
FROM "User" u
WHERE NOT EXISTS (SELECT 1 FROM "UsageQuota" q WHERE q."userId" = u."id");
```

GATE-34 verification: after run, `SELECT count(*) FROM "User"` == `SELECT count(*) FROM "Subscription"` == `SELECT count(*) FROM "UsageQuota"`, and every `Subscription.planId='free'` for pre-existing users. See §6 for rollback-safety statement.

---

## 3. API spec

**Router:** `apps/api/app/routers/billing.py`, mounted `app.include_router(billing.router, prefix="/billing", tags=["billing"])` in `apps/api/app/main.py`. All current routers mount without an `/api` prefix and the platform ingress maps external `/api/*` → the API service (probe-19 hit `/api/billing/webhooks/stripe`), so the **external contract is `/api/billing/...`**. Auth uses the existing `CurrentUser` dependency (`from app.middleware.auth import CurrentUser`) `[VERIFIED-FROM-PROBE agents.py:20]`.

Rate limiting reuses `apps/api/app/rate_limit.py::SlidingWindowRateLimiter` on `app.state` (identifier-keyed, per-worker) `[VERIFIED-FROM-PROBE]`.

| # | Method & path (external) | Auth | Rate limit | Purpose |
|---|--------------------------|------|-----------|---------|
| 1 | `GET  /api/billing/plans` | none (public) | none / cacheable | Powers `/pricing` (H-025) |
| 2 | `POST /api/billing/checkout` | `CurrentUser` | **5 / hour / user** | Start Stripe Checkout |
| 3 | `POST /api/billing/webhooks/stripe` | **none** (Stripe-signed) | **none** (Stripe retries) | Ingest Stripe events |
| 4 | `GET  /api/billing/subscription` | `CurrentUser` | none | Current plan + live quota |
| 5 | `POST /api/billing/portal` | `CurrentUser` | 10 / hour / user | Stripe Billing Portal |

### 3.1 `GET /api/billing/plans` (public)

Returns active plans with the GST breakdown pre-computed server-side (frontend never does tax math).

```jsonc
// 200 OK
{ "currency": "AUD", "gstIncluded": true, "plans": [
  { "id":"starter","name":"Starter","modelTier":"standard","runsPerMonth":30,
    "monthly": { "total": 19.00, "gst": 1.73, "net": 17.27 },
    "annual":  { "total": 179.00,"gst": 16.27,"net": 162.73 },
    "features": ["30 tailored agent runs / month","Standard model tier","Cover letters","Priority email agent"] },
  /* ...pro, power; free has monthly.total 0 and annual: null ... */
]}
```

Computed as `gst = round(total/11, 2)`, `net = total − gst` from `Plan` rows. `features[]` is presentation copy `[DESIGN-DECISION]`.

### 3.2 `POST /api/billing/checkout` (auth; 5/hr/user)

```jsonc
// Request
{ "planId": "pro", "interval": "month" }   // interval ∈ {month, year}
```

Server flow:
1. Load `Plan`; reject Free / inactive / missing `stripePriceId*` with honest 400.
2. **Create-or-reuse Stripe Customer:** read `Subscription.stripeCustomerId` for the user; if absent, `stripe.Customer.create(email=<user email>, metadata={"user_id": user_id})` and persist it onto the `Subscription` row.
3. `stripe.checkout.Session.create(...)` with:
   - `mode="subscription"`, `customer=<customer_id>`, `client_reference_id=<user_id>`,
   - `line_items=[{ price: <plan.stripePriceId for interval>, quantity: 1 }]`,
   - `payment_method_types=["card","au_becs_debit"]`,
   - `automatic_tax={"enabled": <STRIPE_AUTOMATIC_TAX>}` (default false, §1.5),
   - `metadata={"user_id": user_id, "plan_id": planId, "interval": interval}`,
   - `subscription_data={"metadata": {"user_id": user_id, "plan_id": planId}}` (so subscription-scoped webhooks carry identity),
   - `success_url=f"{APP_BASE_URL}/dashboard/settings?checkout=success"`, `cancel_url=f"{APP_BASE_URL}/pricing?checkout=cancel"`.

```jsonc
// 200 OK
{ "checkoutUrl": "https://checkout.stripe.com/c/pay/cs_test_...", "sessionId": "cs_test_..." }
// 429 when >5/hr:  { "detail": "Too many checkout attempts, retry later" }
```

Idempotency: pass a Stripe `idempotency_key` derived from `(user_id, planId, interval, hour-bucket)` so a double-click never mints two sessions.

### 3.3 `POST /api/billing/webhooks/stripe` (public, Stripe-signed) — the critical handler

**Ordering is mandatory (a webhook handler without raw-body signature verification is a prohibited pattern):**

1. **RAW BODY FIRST** — `payload: bytes = await request.body()`. The handler signature takes **`request: Request` only**; it must **never** declare a Pydantic body model (that would consume/re-encode the body and invalidate the signature).
2. **SIGNATURE SECOND** — `sig = request.headers.get("stripe-signature")`; `event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)`. On `SignatureVerificationError` / missing header / bad payload → **return HTTP 400 and stop** (nothing parsed, nothing written).
3. **PARSE THIRD** — only now read `event["id"]`, `event["type"]`, `event["data"]["object"]`.
4. **Transaction-safe idempotency** — open **one** DB transaction:
   ```sql
   INSERT INTO "StripeEvent" ("id","type","status","payloadJson","receivedAt")
   VALUES (%s, %s, 'processing', %s, now())
   ON CONFLICT ("id") DO NOTHING
   RETURNING "id";
   ```
   - **No row returned** → event already seen → `COMMIT` (no-op) → **return 200** (idempotent replay).
   - **Row returned** → dispatch the type-specific handler **inside the same transaction** (all Subscription/UsageQuota writes happen here), then `UPDATE "StripeEvent" SET "status"='processed', "processedAt"=now() WHERE "id"=%s` → **`COMMIT`** → return 200.
   - **Handler raises** → **`ROLLBACK`** (the `StripeEvent` insert rolls back too, so the event is *not* recorded as processed) → return 5xx → **Stripe retries later**. This is the "insert-in-transaction" idempotency the charter requires: an event is marked processed **iff** its side effects committed atomically.

Handlers by `event["type"]` (§5 enumerates the event set):

| Event | Action (within the txn) |
|-------|-------------------------|
| `checkout.session.completed` | Resolve `user_id`/`plan_id` from `metadata`; upsert `Subscription` (planId, status `active`/`trialing`, stripeCustomerId, stripeSubscriptionId, interval, period); reset `UsageQuota` to the new plan's `runsAllowed`/`spendCapUsd`, `runsUsed=0`, `spendUsedUsd=0`, new period. |
| `customer.subscription.updated` | Sync `Subscription.status`, `currentPeriodStart/End`, `cancelAtPeriodEnd`, and (on plan change) `planId` + `UsageQuota` limits. |
| `customer.subscription.deleted` | Downgrade `Subscription` → `planId='free'`, `status='canceled'`, clear Stripe sub id; reset `UsageQuota` to Free limits. |
| `invoice.payment_failed` | Set `Subscription.status='past_due'` (retain access per Stripe dunning; access decision is policy). |
| `customer.subscription.trial_will_end` | No state change required; hook point for a reminder notification. |

### 3.4 `GET /api/billing/subscription` (auth)

```jsonc
// 200 OK
{ "plan": { "id":"pro","name":"Pro","modelTier":"advanced" },
  "status":"active","interval":"month",
  "currentPeriodEnd":"2026-08-16T00:00:00Z","cancelAtPeriodEnd":false,
  "quota": { "runsUsed":37,"runsAllowed":100,
             "spendUsedUsd":2.14,"spendCapUsd":15.00,
             "periodEnd":"2026-08-01T00:00:00Z" } }
```

### 3.5 `POST /api/billing/portal` (auth; 10/hr/user)

`stripe.billing_portal.Session.create(customer=<stripeCustomerId>, return_url=f"{APP_BASE_URL}/dashboard/settings")` → `{ "portalUrl": "https://billing.stripe.com/p/session/..." }`. If the user has no `stripeCustomerId` (Free, never paid) → honest **409** `{ "detail": "No billing account yet — subscribe first" }`.

---

## 4. Quota middleware spec

**Hook point `[VERIFIED-FROM-PROBE agents.py:450 `_record_run`, agents.py:588 `_dispatch`]`:** every agent run funnels through `_record_run(user_id, agent_name, params, fn)` — the single chokepoint that starts the `AgentRun` row, runs `fn()` under `user_credential_context`, and writes `costUsd`. The quota reserve/refund wraps this function. **Gate on metering:** apply quota **only when `agent_name in _LLM_TIER_BY_BACKEND`** (`tailor`, `coverLetter`, `storyExtractor`, `emailAgent`). Deterministic agents pass through unmetered.

Repository: `apps/api/app/repositories/billing.py::UsageQuotaRepository`.

### 4.1 Atomic reserve-before-run (single statement; handles period rollover)

```sql
-- reserve(user_id) -> row | none
UPDATE "UsageQuota" SET
  "periodStart"  = CASE WHEN now() >= "periodEnd" THEN date_trunc('month', now())                     ELSE "periodStart"  END,
  "periodEnd"    = CASE WHEN now() >= "periodEnd" THEN date_trunc('month', now()) + interval '1 month' ELSE "periodEnd"    END,
  "runsUsed"     = CASE WHEN now() >= "periodEnd" THEN 1 ELSE "runsUsed" + 1 END,
  "spendUsedUsd" = CASE WHEN now() >= "periodEnd" THEN 0 ELSE "spendUsedUsd" END,
  "updatedAt"    = now()
WHERE "userId" = %s
  AND ( now() >= "periodEnd"                                             -- fresh period always has budget
        OR ("runsUsed" < "runsAllowed" AND "spendUsedUsd" < "spendCapUsd") )
RETURNING "runsUsed","runsAllowed","spendUsedUsd","spendCapUsd","periodEnd";
```

- **Row returned** → run reserved (and period rolled over atomically if it had expired). Proceed.
- **No row** → either `runsUsed >= runsAllowed` (run cap) or `spendUsedUsd >= spendCapUsd` (USD spend cap) → raise **429** (§4.3). The `WHERE` makes the check-and-decrement a single atomic operation — no read-modify-write race across concurrent runs. `runsAllowed` comparison enforces the plan run quota; `spendCapUsd` comparison enforces the **USD** spend cap **before** spending.

### 4.2 Record spend on success; refund on failure/non-200

After `fn()` completes and `_record_run` computes `cost` (USD, into `AgentRun.costUsd`):

```sql
-- record_spend(user_id, cost_usd)  — on a completed (200) run
UPDATE "UsageQuota"
SET "spendUsedUsd" = "spendUsedUsd" + %s, "updatedAt" = now()
WHERE "userId" = %s;
```

On **any** failure path (the existing `except HTTPException / QuotaExhaustedError / LLMUnavailableError / Exception` branches that call `runs.finish(..., 'failed')`) → **refund the reserved run and record no spend**:

```sql
-- refund_run(user_id)  — reserved run did not produce billable output
UPDATE "UsageQuota"
SET "runsUsed" = GREATEST("runsUsed" - 1, 0), "updatedAt" = now()
WHERE "userId" = %s;
```

Insertion map inside `_record_run` (metered agents only):
- **Before** `run = runs.start(...)`: `quota.reserve(user_id)` → 429 if none. (Runs *after* the existing subscription-quota-block 429 check, so both gates apply.)
- **After** `runs.finish(run['id'], 'completed', cost_usd=cost)`: `quota.record_spend(user_id, cost)`.
- **In every `except ...` branch** (before re-raise): `quota.refund_run(user_id)`.

**Spend-cap semantics (honest, documented):** the cap is checked **pre-run** against accumulated spend. A single run whose actual cost pushes `spendUsedUsd` over `spendCapUsd` is allowed to finish (its cost cannot be known before it runs on OpenRouter), but the **next** reserve fails — the cap is a soft ceiling that halts the following run, not a mid-run kill. This is the correct guarantee given costs are only known post-hoc from `AgentRun.costUsd`. The `[DESIGN-DECISION]` USD caps (§2.1) are sized so one overshoot is immaterial.

### 4.3 429 response shape

```jsonc
// 429 Too Many Requests
{ "detail": { "code": "quota_exhausted",        // or "spend_cap_reached"
              "message": "You've used all 30 agent runs this period.",
              "runsUsed": 30, "runsAllowed": 30,
              "resetsAt": "2026-08-01T00:00:00Z" } }
```

This is distinct from the existing subscription-provider `AgentQuotaBlock` 429 (`_quota_429`, provider-cooldown) — that stays as-is; the plan-quota 429 is the new billing gate.

### 4.4 Async variant — reserve-at-enqueue / refund-on-failure `[PHASE-7 ADDITION, VERIFIED-WITH-SOURCE, GAP-P7-ASYNC-001]`

Behind the `AETHER_ASYNC_GENERATION` flag (default `false`; `true` in production since Phase 7 — `docs/delivery/PHASE7-GAP-ANALYSIS.md`), metered single-agent runs (`tailor`, `coverLetter`) no longer reserve quota *inside* a synchronous HTTP request. Instead:

- **Reserve at enqueue, not at execution.** `POST /api/agents/{tailor,cover-letters}/run` calls the same `UsageQuotaRepository.reserve(user_id)` single-statement atomic reserve as §4.1, but does it **before** the job is handed to the queue, not before the LLM call runs. On success it creates a `BackgroundJob` row (`apps/api/app/repositories/background_jobs.py`) with `quotaReserved=true` and returns **HTTP 202** `{"job_id", "status":"enqueued"}` — the same paywall-then-cooldown-then-reserve ordering as the sync path, so a request that would 429 synchronously still 429s synchronously (never queued to fail later).
- **Enqueue failure compensates immediately.** If the ARQ push itself fails (queue/Redis unavailable), the reservation is refunded via `quota.refund_run(user_id)`, the `BackgroundJob` and `AgentRun` rows are marked `failed`, and the endpoint raises an honest **503** — never a silent 202 for a job that was never actually queued.
- **Worker failure refunds after the fact.** The ARQ worker process (`aether-worker.service`, `apps/api/app/workers/tasks.py`) runs the real `_pipeline_core`/agent call outside the request/response cycle. If the worker itself dies or the job raises, the `BackgroundJob` transitions to `failed` and `quota.refund_run(user_id)` fires from the worker side, stamping `BackgroundJob.quotaRefundedAt` — net effect on `UsageQuota.runsUsed` is zero for a job that never produced billable output (`[VERIFIED-WITH-SOURCE]` `uat/reports/evidence/phase7/journey-j3-quota-refund.json`: enqueue reserved → worker `LookupError` → refunded, `runsUsed` net-unchanged).
- **Stale-job watchdog also refunds.** `GET /api/agents/jobs/{job_id}` (owner-scoped polling) applies a lazy staleness check (`AETHER_JOB_STALE_SECONDS`, default 900s enqueued / 720s processing) — a poll of a job stuck past that window is atomically marked `failed` **and refunded**, so a caller polling a dead worker always reaches a terminal state with correct quota accounting, not an indefinite `processing` with quota silently burned.
- **Pipeline composite is the one exception.** `_enqueue_pipeline` does **not** reserve at enqueue (its metered footprint is data-dependent across sub-steps); the per-step atomic reserve/refund from §4.1/§4.2 still applies *inside* the worker's `_pipeline_core` once it runs.
- **Record-spend on success is unchanged** — the worker calls the same `record_spend(user_id, cost_usd)` as §4.2 once the job completes.

Live-verified: 20/20-run soak with 0 HTTP 503s, 0 fixture-fallback matches, and a forced-failure run showing correct net-zero quota (`uat/reports/evidence/phase7/journey-j3-soak-20.json`, `journey-j3-quota-refund.json`). This closes the Phase-6 residual `BACKLOG-P6-02` (~20% honest-503 rate from synchronous generation under the ~100s HTTP edge) — `docs/delivery/EXECUTION-REPORT.md` §10.

---

## 5. Stripe integration plan

### 5.1 Products / Prices to create (test mode) `[human task]`

One **Product** per paid tier; two recurring **Prices** each, `currency='aud'`, `tax_behavior='inclusive'` (GST-inclusive, §1.5). Free has **no** Stripe product.

| Product | Price (monthly) | Price (annual) |
|---------|-----------------|----------------|
| Aether Starter | A$19.00 / month recurring | A$179.00 / year recurring |
| Aether Pro | A$39.00 / month recurring | A$359.00 / year recurring |
| Aether Power | A$69.00 / month recurring | A$649.00 / year recurring |

Resulting price IDs are written to `Plan.stripePriceIdMonthly/Annual` (via env or a one-time admin write; the seed uses `COALESCE` so ids survive redeploys).

### 5.2 Webhook events to subscribe (Stripe dashboard endpoint → `/api/billing/webhooks/stripe`)

`checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `customer.subscription.trial_will_end`. All handled idempotently (§3.3).

### 5.3 Payment methods

- `card` — instant confirmation.
- `au_becs_debit` — **must be enabled in the Stripe dashboard**; BECS is **asynchronous** (funds clear over days). The subscription starts `incomplete`/`processing` and flips `active` on the confirming webhook — so subscription state is **webhook-driven, never assumed at checkout return**. The UI must reflect "pending bank debit" until the webhook confirms.

### 5.4 Env vars needed

| Var | Purpose | Source |
|-----|---------|--------|
| `STRIPE_SECRET_KEY` | Server SDK auth (test: `sk_test_...`) | Human / Stripe dashboard |
| `STRIPE_WEBHOOK_SECRET` | `construct_event` signature (`whsec_...`) | Human / Stripe webhook config |
| `STRIPE_PRICE_STARTER_MONTH` / `_YEAR` | Checkout line item | After price creation |
| `STRIPE_PRICE_PRO_MONTH` / `_YEAR` | Checkout line item | After price creation |
| `STRIPE_PRICE_POWER_MONTH` / `_YEAR` | Checkout line item | After price creation |
| `APP_BASE_URL` | success/cancel/return URLs | Known: `https://5cb5f0620.abacusai.cloud` |
| `STRIPE_AUTOMATIC_TAX` | Toggle Stripe Tax (default `false`, §1.5) | `[DESIGN-DECISION]` |
| `STRIPE_PUBLISHABLE_KEY` | (optional) frontend redirect | Human |

Secrets are read from env only — **never** committed (prohibited-pattern compliance). Prices may live in env **or** `Plan` rows; `Plan` columns are the durable store.

---

## 6. Data migration — GATE-34 detail & rollback-safety

- **What runs:** the two `INSERT ... WHERE NOT EXISTS` backfills in §2.2, immediately after DDL + Plan seeding, inside the advisory-locked (`7420240719`) transaction in `_ensure_billing_tables()`. Idempotent — re-running inserts nothing for users already backfilled.
- **Result invariant (GATE-34 pass condition):** `count(User) == count(Subscription) == count(UsageQuota)`, all pre-existing users on `planId='free'`, every quota row initialized (`runsUsed=0`, `spendUsedUsd=0`, current month period, Free limits from `Plan`).
- **Rollback-safety statement:** **strictly additive.** No `DROP`, no `ALTER TYPE`, no column rename, no `UPDATE`/`DELETE` of any existing row in any existing table. New tables/indexes use `IF NOT EXISTS`; `AgentRun.billingAuditJson` already exists (added by the prior per-user-agent bundle) and is untouched here. Rolling back the release simply stops calling `_ensure_billing_tables()`; the additive tables sit inert and harmless (mirrors the `GmailAccount`/`GoogleCredential` additive-coexistence precedent). No `User`-row mutation means a prior release keeps functioning unchanged.

---

## 7. Human prerequisites (BLOCKED-ON-HUMAN)

Cluster D code (§8) is **buildable and unit-testable now with mocked Stripe**. The items below are needed only to **VERIFY live** and to be GST-compliant. Mapped to what each unblocks:

| # | Prerequisite (human, in Stripe/ATO) | Unblocks |
|---|-------------------------------------|----------|
| H1 | Stripe account + `STRIPE_SECRET_KEY` (test) | Live checkout/session creation; portal; all live-Stripe verify gates |
| H2 | Create 3 Products × 2 Prices (test) → 6 price IDs | `GET /plans` live values; `POST /checkout` verify |
| H3 | Register webhook endpoint → `STRIPE_WEBHOOK_SECRET` | `POST /webhooks/stripe` live signature verify; subscription lifecycle verify |
| H4 | Enable `card` + `au_becs_debit` methods in dashboard | BECS payment path verify |
| H5 | ABN / GST registration + business legal name for tax invoices; decide Stripe Tax on/off (recommend **off**, §1.5) | GST-compliant tax-invoice/receipt gate; `STRIPE_AUTOMATIC_TAX` value |
| H6 | Confirm `APP_BASE_URL` (already `https://5cb5f0620.abacusai.cloud`) | Checkout/portal redirects |
| H7 | Activate Stripe Billing Portal configuration | `POST /portal` verify |
| H8 | **Admin/privilege system** (H-021 deferred; no role column today, `probe-17`) | Cluster F admin endpoints that write `AdminAuditLog` / adjust USD spend caps |

**GATE-34 (backfill) requires none of the above** — it runs against the existing DB and is verifiable immediately after the billing repository ships.

---

## 8. Cluster D vs Cluster F split

### 8.1 Cluster D — billing backend (build + unit-test now with MOCKED Stripe)

Buildable and fully unit-testable **without** live Stripe creds:
- `apps/api/app/repositories/billing.py` — `_ensure_billing_tables()` (DDL + seed + GATE-34 backfill), `PlanRepository`, `SubscriptionRepository`, `UsageQuotaRepository` (`reserve`/`record_spend`/`refund_run`), `StripeEventRepository` (insert-in-txn idempotency).
- `apps/api/app/routers/billing.py` — the 5 endpoints (§3), with the Stripe SDK calls behind a thin `app/services/stripe_gateway.py` wrapper so tests inject a mock.
- Quota hook wired into `agents.py::_record_run` (§4).
- **Webhook signature + idempotency logic is unit-testable now:** generate a valid `stripe-signature` with a **test** `STRIPE_WEBHOOK_SECRET` and `stripe.Webhook.construct_event`; assert (a) bad signature → 400, (b) first event → processed + state written, (c) replayed event id → 200 no-op, (d) handler raise → rollback leaves `StripeEvent` absent (retry-safe). No network needed.
- **GATE-34 backfill** — testable now against the DB.

**Needs live human creds to VERIFY (not to build):** real Checkout redirect (H1/H2), real webhook delivery signature (H3), BECS mandate flow (H4), portal session (H7), and `automatic_tax` if ever enabled (H5). These are QA/verify gates, not build blockers.

### 8.2 Cluster F — admin spend/user views (consumes these tables)

Cluster F **reads**:
- `UsageQuota` — per-user run consumption (`runsUsed`/`runsAllowed`) and **USD** spend (`spendUsedUsd`/`spendCapUsd`).
- `Subscription` — per-user plan, status, interval, period, Stripe ids.
- `AgentRun.costUsd` — authoritative realized USD spend per run; admin spend view aggregates `SUM(costUsd)` per user/period and reconciles against `UsageQuota.spendUsedUsd`.
- `Plan` — catalog for plan-change UIs.

Cluster F **writes** `AdminAuditLog` on every privileged mutation — spend-cap change (**administered in USD**, per charter), plan override, refund issuance, plan-catalog edit — recording `actorUserId`, `action`, `targetType/Id`, and `detailJson` (before/after USD amounts, reason).

**Prerequisite:** Cluster F admin **authorization** depends on the privilege system (H8 / H-021), which does **not** exist today (`probe-17`: no `isAdmin`/`role` on `User`). The billing tables ship now so Cluster F can build against a stable schema; the admin **authz gate** is tracked separately and must land before any admin billing endpoint is exposed. No admin endpoint may self-approve its own gate.

---

## 9. Approval

This document is **DESIGN ONLY**; no implementation code was written. It requires **fable-5 approval** before any Cluster D or Cluster F code is authored. Open `[DESIGN-DECISION]` items for fable-5 to ratify or override: annual multiplier (10×), per-tier run quotas (5/50/200/600), USD spend caps (1/5/15/40), and Stripe-Tax-off-at-launch.
