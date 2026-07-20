# ADR-MV-02 — Free-tier paywall ⟷ marketing reconciliation (Cluster D)

**Status:** ACCEPTED (orchestrator claude-fable-5, 2026-07-17). Adjudicates BLOCKERs MV-pricing-001 + MV-analytics-001 and related coverage findings.

## Context (evidence, not optimism)
- **Pricing page (public)** advertises the Free tier as usable: "5 tailored agent runs / month", "Resume tailoring + ATS scoring", "No card required", "Get started free". (screens/pricing evidence.)
- **Data model** provisions every free user a `UsageQuota` row with `runsAllowed=5`, `spendCapUsd=1.0` (ENTITLEMENT-DECISION-PACKET.json — admin free row had runsAllowed=5, runsUsed=3).
- **Frontend gate** `SubscriptionGate` (apps/web/src/app/dashboard/layout.tsx:27) blocks the ENTIRE `/dashboard/*` tree for free users (`requiresSubscription && !active_paid`) — no allowlist.
- **Backend gate** `_require_active_subscription` (apps/api/app/routers/agents.py:539-571) 402s EVERY metered agent run for free users.
- **Ratified design** ADR-P6-PRICING / docs/subscription/billing-architecture.md: `AETHER_REQUIRE_PAID_SUBSCRIPTION=true`, free tier described as a "loss-leader with bounded cost ~A$0.16–1.9/user/mo" (which itself budgets for free-user LLM spend).

## The contradiction (the §0.5 violation)
The product **advertises free features** (marketing) and **provisions a free run quota** (data model) while **blocking free users from reaching or using any of it** (both gates). A prospective paying customer is shown "Get started free · 5 agent runs · no card required" and then can do nothing. That is misleading content reachable by users — a zero-tolerance §0.5 item — regardless of which layer is "wrong".

Two internally-conflicting ratified signals: `AETHER_REQUIRE_PAID_SUBSCRIPTION=true` (subscription-only) vs `runsAllowed=5` free provisioning + free marketing (freemium). Evidence does not unambiguously pick one; this is at root a business-model decision.

## Decision
Resolve the **user-facing dishonesty** with the least-destructive change that respects the ratified Phase-6 paywall, and escalate the deeper business-model choice to the product owner rather than unilaterally reversing a ratified architectural decision in production.

**D-fix (implement now):**
1. **Marketing honesty (MV-pricing-001, MV-analytics-001 user-facing half):** reconcile the pricing page + any "free" framing to the ACTUAL current behavior. The Free tier must NOT promise usable agent features while the gate blocks them. Options for the fixer to implement the honest copy: reframe "Free" as an explicit *preview/browse* tier (sign up, view pricing, see the product) with agent features clearly labeled "requires subscription", OR — if product confirms freemium — see D1 below. Remove "5 agent runs / month / no card required / get started free" as an unqualified promise. No unqualified claim of a capability the gate denies.
2. **Fail-open paywall bypass (MV-agent-monitor-004) — SECURITY, fix unconditionally:** `SubscriptionGate` must FAIL CLOSED when `GET /billing/entitlement` errors (currently fails open → free users bypass the paywall by forcing the entitlement call to error). This is a revenue/security defect independent of the business-model choice.
3. **Honest dashboard for free users:** whatever the copy says, a free user hitting `/dashboard/*` must land on an honest, non-dead state (the subscribe CTA is acceptable IF the marketing matches it). No dead-end that contradicts on-page copy (MV-mobile-dashboard-002).

**Escalated to product owner (BLOCKED-ON-HUMAN, documented — NOT silently decided):**
- **D1 (freemium — the alternative):** if the business intends the advertised freemium (which the provisioned `runsAllowed=5` + loss-leader design doc suggest), the correct fix is instead to HONOR the free tier: narrow `SubscriptionGate` to allow free users the read-only dashboard + let `_require_active_subscription` permit metered runs up to the free quota (then 402/upgrade). This REVERSES the ratified subscription-only gate and materially changes revenue, so it is the owner's call. Orchestrator RECOMMENDATION: the provisioned free quota + explicit loss-leader cost budgeting are strong evidence D1 was the original intent; if the owner confirms freemium, prefer D1 over D-fix#1's copy-restriction.

Rationale: both D-fix and D1 cure the §0.5 violation. D-fix is minimal, reversible, and does not unilaterally overturn a ratified monetization decision; it ships an honest product today. D1 is larger and reverses ratified architecture, so it is escalated with a recommendation rather than force-built. The security fail-open fix (#2) is unconditional.

## Consequences
- Immediate: pricing/free copy becomes honest; fail-open closed; no dead-ends. §0.5 violation cured.
- Deferred to owner: whether to deliver freemium (D1). Logged in MANUAL-VERIFICATION-BLOCKED-ON-HUMAN.md with the evidence + recommendation.
- Testing note: the temporary Pro entitlement (ADR-MV-01) remains for paid-screen coverage; reverted before exit. Free-plan paywall re-verified after revert.
