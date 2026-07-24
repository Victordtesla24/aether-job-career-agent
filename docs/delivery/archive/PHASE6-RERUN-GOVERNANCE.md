# PHASE 6 — RE-RUN GOVERNANCE & PLAN

**Trigger:** user directive (2026-07-16) — re-execute `/home/ubuntu/aether-subscription-prompt.md` with
MAXIMUM PROMPT EXECUTION ACCURACY, no user interactivity, AFTER the doc-refresh + beta-release + paywall
tasks completed.
**Orchestrator:** `claude-fable-5 (xhigh)` — decision points only. **Start HEAD:** 987709e (origin==HEAD,
prod health ok v0.2.0, subscription paywall live).

## Nature of this run
This is a **fresh independent RE-AUDIT + 34-gate RE-VERIFICATION** of the same prompt, per §3 ("trust no
prior claim — begin with fresh evidence"). The build was delivered in the first run (23 gaps
VERIFIED-CLOSED, 6 BLOCKED-ON-HUMAN, 34 gates adjudicated — see `PHASE6-EXECUTION-SUMMARY.md`). The re-run
re-derives fresh evidence, confirms the §4.4 families still hold on production, catches any regression
introduced since (docs refresh, beta release, **subscription paywall**), and produces a fresh summary.

## Bootstrap (§17) status — carried from first run, re-confirmed
- STEP 1 governance roster: 14 `.claude/agents/*.md`, exact §0.2 models, no `inherit`/no `model: fable` — **re-confirmed clean**.
- STEP 2 infra: `docs/delivery/DEPLOYMENT-RUNBOOK.md` exists — current.
- STEP 3 research: 5 live artifacts under `uat/reports/evidence/phase6/` (Anthropic OAuth PROHIBITED, pricing, Stripe AU, competitors, Seek ToS) — dated 2026-07-16, still current; re-confirm only if a probe contradicts.
- STEP 7 billing-arch: `docs/subscription/billing-architecture.md` exists + corrected to shipped RATIFIED_PLANS.
- Fresh evidence root: `uat/reports/evidence/phase6-rerun/`.

## Binding carry-over ADRs (unchanged)
ADR-P6-SEEK (Seek scraping ToS-prohibited), ADR-P6-OAUTH (Anthropic OAuth prohibited → API-key only),
ADR-TR-1 (additive lazy DDL), ADR-P6-STRIPE-MOCK, ADR-P6-PRICING (ratified tiers 30/100/300, A$179/359/649).

## Paywall reconciliation (new since first run)
The user-added subscription paywall (`AETHER_REQUIRE_PAID_SUBSCRIPTION=true`) gates all agent runs behind an
active PAID subscription. The prompt's agent-dependent verification journeys (§12 Journeys 2/3/4 —
sourcing/tailoring/cover) therefore require a subscribed context: the re-run's gate-verify QA will **grant
the test account a temporary paid subscription in the DB, verify, then revert byte-for-byte** (the pattern
already proven in `qa-paywall-verify.json`) — never faking, always reverting. Journey 1 (subscription/
entitlement) is now directly satisfied by the live paywall.

## Loop
Fresh PHASE-0 (probes + inventory) → triage vs §4.4 → seed `phase6-rerun-gap-analysis.json` → re-verify the
34 §13 gates on live production (independent qa, paid-sub context where needed) → fix any regression
(fix→review→deploy→verify) → closeout `PHASE6-RERUN-EXECUTION-SUMMARY.md`. Human-gated gates
(Stripe 13/14/15/16/33, admin-credential 17, Gmail 05) remain BLOCKED-ON-HUMAN — never closed by inference.
Model governance: 0 fable sub-agent spawns (continues from first run).
