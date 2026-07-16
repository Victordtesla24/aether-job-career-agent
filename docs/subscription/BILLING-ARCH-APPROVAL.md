# PHASE 6 — fable-5 approval of the billing architecture (STEP 7 gate)

Reviewed & **APPROVED** 2026-07-16, with one binding ratification (ADR-P6-PRICING).
Source design: `docs/subscription/billing-architecture.md` (billing-arch, opus). Cluster D/F code may proceed.

## Approved as-is
- User PK = `id` (text/cuid); billing `userId` columns text, no FK — shared-test-DB-safe pattern. ✅
- Spend tracked in USD from `AgentRun.costUsd`. ✅
- Metered runs = `tailor`/`coverLetter`/`storyExtractor`/`emailAgent`; deterministic agents ($0) do not consume quota. ✅
- Quota chokepoint = `_record_run()` in `apps/api/app/routers/agents.py` (reserve-before-run there). ✅
- Lazy idempotent DDL in new `apps/api/app/repositories/billing.py::_ensure_billing_tables()`, advisory lock **7420240719**; doc mirror `apps/api/migrations/0022_billing.sql`. ✅ (ADR-TR-1)
- Transaction-safe webhook (raw-body FIRST → signature SECOND → parse THIRD → StripeEvent insert-in-txn idempotency). ✅
- Create-or-reuse Stripe Customer (NOT customer_email=); card + au_becs_debit; metadata user_id+plan_id. ✅
- **Stripe Tax OFF at launch** (A$140/mo floor ≈ 9.1 Starter subs; GST identical via round(total/11,2); tax_behavior=inclusive; `STRIPE_AUTOMATIC_TAX=false`). ✅
- Endpoints: GET /api/billing/plans (public), POST /api/billing/checkout (auth, 5/hr/user), POST /api/billing/webhooks/stripe (public), GET /api/billing/subscription (auth), POST /api/billing/portal (auth). ✅
- USD spend caps per tier: Free $1 / Starter $5 / Pro $15 / Power $40 (admin-adjustable). ✅
- GATE-34 backfill = idempotent INSERT…WHERE NOT EXISTS, all users → Free + initialized UsageQuota; additive, rollback-safe. ✅

## ADR-P6-PRICING (BINDING ratification — overrides the design's proposed quotas/annual)
The design proposed run quotas 50/200/600 and annual A$190/390/690. Per MAXIMUM PROMPT EXECUTION
ACCURACY, the prompt's §14.1 figures are explicit and the verified costs (Free user LLM cost
< A$1.32/mo; margins 82–89%) **confirm** rather than contradict them. Therefore the ratified tiers are
the prompt's §14.1 values EXACTLY:

| Tier | Monthly AUD (GST-inc) | Annual AUD (GST-inc) | Agent runs/mo | Model tier (app routing) |
|---|---|---|---|---|
| Free | A$0 | — | 5 | light (Haiku-equivalent) |
| Starter | A$19 | A$179 | 30 | light+standard (Haiku+Sonnet-equiv) |
| Pro | A$39 | A$359 | 100 | light+standard |
| Power | A$69 | A$649 | 300 | full model access |

GST per §14.2: gst=round(total/11,2), net=total-gst → A$19→1.73/17.27, A$39→3.55/35.45, A$69→6.27/62.73.
Annual GST is round(annual/11,2). "Model tier" maps to the app's own OpenRouter routing (Anthropic
model names are semantic; runtime provider is OpenRouter per probe-03; Anthropic OAuth prohibited per
ADR-P6-OAUTH). The Cluster D fixer MUST seed the `Plan` table with THESE quotas/prices, not the design's.

## Cluster D scope (build now, mocked Stripe — ADR-P6-STRIPE-MOCK)
Schema+backfill, /billing router (5 endpoints), quota reserve-before-run at `_record_run()`, /pricing page,
Plan seed with ratified tiers. Unit-test webhook signature+idempotency, GST math, quota reserve/refund,
checkout create-or-reuse with MOCKED stripe SDK. Live-verify gates (13/14/15/16/33) stay BLOCKED-ON-HUMAN.

## Cluster F dependency
Admin panel consumes UsageQuota (spend cap set/read in USD), AgentRun.costUsd (per-user spend),
AdminAuditLog, and the new isAdmin column. Sequence F after D's schema lands.
