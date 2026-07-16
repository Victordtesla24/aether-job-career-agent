# PHASE 6 — RE-RUN EXECUTION SUMMARY

**Prompt:** `/home/ubuntu/aether-subscription-prompt.md` (re-executed, maximum-accuracy, non-interactive)
**Run:** PHASE6-RERUN · **Date:** 2026-07-16 · **Orchestrator:** `claude-fable-5 (xhigh)` — decision points only
**Start HEAD:** `987709e` (== origin/main == production build; health ok, v0.2.0, subscription paywall live)
**Nature:** fresh independent re-audit + 34-gate re-verification per §3 ("trust no prior claim — begin with fresh evidence"). The build was delivered in the first run; this run re-derives evidence, confirms the §4.4 gap families still hold on production, and catches any regression introduced since (doc refresh, beta release, **subscription paywall**).

---

## Outcome

**RE-VERIFICATION COMPLETE — 0 regressions, 0 new gaps, 0 code fixes required.** This was a pure verification pass: PHASE-0 discovery and the live 34-gate re-check both reproduce the first run's verified-closed state. No source file was modified; only the re-run ledger, evidence, and this summary were added.

| Gate class | Count | Notes |
|---|---:|---|
| PASS / VERIFIED-CLOSED | 26 | incl. 7 agent-dependent gates re-verified **live on production** |
| CONDITIONALLY-CLOSED | 1 | GATE-04 Anthropic OAuth — ToS-prohibited, API-key-only design (ADR-P6-OAUTH) |
| BLOCKED / HUMAN-GATED | 7 | Stripe (13/14/15/16/33), admin-credential (17), Gmail 2nd consent (05) |
| **Total** | **34** | 0 OPEN · 0 RE-VERIFYING |

Regression suites (fresh): **backend 627 pytest passed / 0 failed** (690 s, under shared-DB lock) · **frontend 296 vitest passed / 0 failed** (44 files).

---

## PHASE-0 — fresh discovery (no regressions)

Two independent agents re-derived evidence into `uat/reports/evidence/phase6-rerun/`:

- **Probes (evidence agent):** health ok · LLM `mode=auto` · 32 jobs / 5 sources / 0 dup · billing + admin tables + `User.isAdmin/suspended` present · 8 runtime agents · rate-limit 429-after-5 · webhook rejects unsigned (400) · **paywall ACTIVE (402 `subscription_required`)**. Two WARNs adjudicated as non-issues: `admin/admin123` `isAdmin=false` is *correct* (GATE-31); 4 zero-token runs are deterministic agents (legitimate).
- **Inventory (scout):** every §4.4 family PRESENT / unchanged — billing `RATIFIED_PLANS` exact at `billing.py:42-47` + transaction-safe webhook; admin 10 routes + rotation demotes `admin@aether.local` + spend-cap-before-LLM; sourcing Seek `_COMPLIANCE_GATED` + Adzuna + 6 ATS live; quality `_verify_entailment` + batch cap + `_replay_with_default` **gone** (AUTH-002 holds) + cover budget decoupled; auth PUT-config + `anthropic_oauth.py` **absent** + `GmailAccount` multi-inbox; paywall `_require_active_subscription` first line of `_record_run` + `resumes.py` re-raises 402. **0 prohibited patterns. Repo clean (only `main`, 0 open PRs).**

**Verdict:** no regressions across any §4.4 family.

---

## Live 34-gate re-verification

### Agent-dependent journeys (re-verified on production under a temporary paid subscription, reverted byte-for-byte)

Because the paywall (`AETHER_REQUIRE_PAID_SUBSCRIPTION=true`) gates agent runs behind an active paid subscription, the independent `qa` agent granted the admin account a temporary `pro` subscription in the DB, executed every journey as a subscriber, then restored the account to its exact recorded pre-test state (pattern from `qa-paywall-verify.json`).

| Gate | Result | Live evidence |
|---|---|---|
| GATE-07 sourcing | PASS | `POST /agents/scout/run` 202 with honest per-source status (Wellfound 403 *surfaced*, not swallowed); `GET /jobs` → 32 jobs, 3 sources ≥5 (greenhouse 16 / ashby 7 / lever 5), max age 28 d, 0 dup, 0 Seek |
| GATE-08 cards live | PASS | 10/10 sampled cards HTTP 200, 0 expiry markers, 100% title-token match, 0 Seek |
| GATE-09 tailoring | VERIFIED-CLOSED | 4 live runs content-only + ATS non-regression + **zero fabrication**; run 1 entailment guard *actively rejected all 7 proposed candidates* (guard working, not passthrough). Lift-when-evidence-supports proven deterministically by STRICT-lift unit tests (`test_gap_p6_tailoring_ats.py:120/122`, `tail4`/`tail5`/`authenticity`/`p5_tailoring`) in the green suite, on byte-identical code to the first-run live lift proof (30.81 → 32.97). *(see residual 1)* |
| GATE-10 conversion UI | PASS | Playwright live run: `estimatedConversionLift` + methodology text + working `MetricTooltip` (`data-testid` trigger/popover, `role=tooltip`, hover-revealed, illustrative-estimate disclaimer) in real DOM; before/after ATS shown; 0 console errors |
| GATE-11 cover format | PASS | Live run, business format confirmed via rendered PDF (sender block / date / recipient / salutation / 3 paras / CTA / sign-off) |
| GATE-12 zero-fab + PDF | PASS | Every factual claim traced to source evidence (ANZ WebSocket/$5M, ATO COBOL, independent-consulting story with "simulated" qualifier preserved) — zero hallucinated facts; valid single-page PDF (200) |
| GATE-03 console | PASS | Playwright swept 14 dashboard routes + `/pricing` + `/admin` as paid admin — 0 console errors / 0 failed requests / 0 page errors |

**Cleanup verified:** Subscription + UsageQuota restored byte-for-byte to recorded pre-test state (`runsUsed=1`, the true prior value — deviation from the literal "0" instruction flagged explicitly rather than silently altered); 4 QA-created resume versions + 1 cover-letter (+ cascaded approval request) deleted; 8 pre-existing resumes / 4 cover letters / 3 stories untouched. Final checks: `entitlement.active_paid=false`, `POST /agents/scout/run` → 402 again, dashboard shows the paywall again. **Production left exactly as before.**

### Structural / security gates (fresh PHASE-0 evidence)

GATE-01 health, GATE-02 auto-mode (honest 503, no fixture), GATE-06 agent config, GATE-18 analytics parity, GATE-23 prohibited-patterns (0), GATE-27 governance (0 fable sub-agents), GATE-29 prod-serves-build, GATE-31 admin-no-privilege, GATE-32 rate-limit, GATE-34 backfill — all re-confirmed PASS on fresh probes/inventory.

### Human-gated (never closed by inference — §2)

- **Stripe** (GATE-13/14/15/16/33): full code + tests + prod flow present; live card round-trip needs operator keys/webhook-secret/Price-IDs/ABN.
- **Admin credential** (GATE-17): functionality live-verified (spend-cap 429-before-LLM via temp admin); formal closure needs operator `AETHER_ADMIN_EMAIL` + bcrypt hash. Demo `admin/admin123` has **zero** admin privilege in production (correct).
- **Gmail 2nd consent** (GATE-05): multi-inbox code present; second live OAuth consent is a human action.
- **Anthropic OAuth** (GATE-04): CONDITIONALLY-CLOSED — ToS-prohibited, API-key-only by design (ADR-P6-OAUTH).

See `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md` for the operator checklist.

---

## Honest residuals (documented, not gate failures)

1. **Tailoring guard is conservative** — on the 4 sampled live JDs the tailor produced 0 net bullet changes (run 1: 7 candidates proposed, all rejected by the entailment guard) because the baselines already covered the JD keywords / evidence didn't entail new gaps. Lift-when-supported is proven by STRICT-lift unit tests + the first-run live proof on unchanged code. This is correct anti-fabrication behavior, not a regression.
2. **One genuine transient 503** — a UI-driven tailor hit "LLM call exceeded hard budget of 38.7 s"; immediate retry succeeded. Real reliability signal (async generation tracked as `BACKLOG-P6-02`), **not** a fixture — consistent with the first run's ~20% honest-503 residual.
3. **GATE-03 `/admin` redirect** — redirects cleanly because no DB user has `isAdmin=true` (pre-existing GATE-31 state, left untouched).

---

## Governance

0 orchestrator-model (fable) sub-agent spawns; all dispatches haiku/sonnet/opus; author ≠ reviewer ≠ QA; only `qa` set VERIFIED-CLOSED against fresh live evidence. Binding ADRs carried unchanged: ADR-P6-SEEK, ADR-P6-OAUTH, ADR-TR-1, ADR-P6-STRIPE-MOCK, ADR-P6-PRICING (30/100/300 runs; A$179/359/649 annual).

**Ledger:** `docs/delivery/phase6-rerun-gap-analysis.json` · **Evidence:** `uat/reports/evidence/phase6-rerun/`
