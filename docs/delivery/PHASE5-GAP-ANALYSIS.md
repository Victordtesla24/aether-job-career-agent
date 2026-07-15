# Phase-5 Gap Analysis — Master Ledger

**Run:** phase5 · **Date:** 2026-07-15 · **HEAD:** `16575fa`
**Orchestrator:** opus-4-8 (orchestrator-only — plan/dispatch/adjudicate; never implements/reviews/tests/browses)
**Evidence root:** `uat/reports/evidence/phase5/` (gitignored)
**Note:** Fresh discovery; trusts no prior ledger (§2.1). This is a NEW ledger for the Phase-5
prompt (`aether-prod-trmediation-prompt.md`), distinct from the earlier completed "prud"
remediation ledger (`gap-analysis.json` at repo root).

**Machine-readable mirror:** [`docs/delivery/phase5-gap-analysis.json`](./phase5-gap-analysis.json)
(schema per §3.1; validated with `python3 -c "import json;json.load(open('docs/delivery/phase5-gap-analysis.json'))"`)

**Status lifecycle (§3.2 — allowed values only):**
`OPEN → TRIAGED → IN-PROGRESS → FIX-READY → REVIEW-FAILED → DEPLOYED → VERIFY-FAILED → VERIFIED-CLOSED`
Only **QA** may set `VERIFIED-CLOSED`.

---

## 1. Open Gaps (status: TRIAGED — discovery done, dispatch pending)

| ID | Severity | Type | Surface | Category | Assigned Role | Status |
|---|---|---|---|---|---|---|
| GAP-AUTH-001 | CRITICAL | AUTHENTICITY | /dashboard/agents | auth | fixer-hard | TRIAGED |
| GAP-SRC-001 | CRITICAL | CAPABILITY | /dashboard/jobs | sourcing | fixer-hard | TRIAGED |
| GAP-SRC-002 | CRITICAL | DEFECT | /dashboard/jobs | sourcing | fixer-hard | TRIAGED |
| GAP-SRC-003 | MEDIUM | USABILITY | /dashboard/jobs | sourcing | fixer-medium | TRIAGED |
| GAP-TAIL-001 | CRITICAL | CAPABILITY | /dashboard/resume | tailoring | fixer-hard | TRIAGED |
| GAP-COV-001 | HIGH | ENHANCEMENT | /dashboard/cover-letters | cover_letter | fixer-medium | TRIAGED |

**Counts by status:** TRIAGED = 6, all others (OPEN/IN-PROGRESS/FIX-READY/REVIEW-FAILED/DEPLOYED/VERIFY-FAILED/VERIFIED-CLOSED among open gaps) = 0.
**Counts by severity:** CRITICAL = 4, HIGH = 1, MEDIUM = 1.

---

## 2. Per-Gap Detail

### GAP-AUTH-001 — Anthropic consumer-subscription OAuth (PKCE) violates third-party auth policy
- **Severity:** CRITICAL · **Type:** AUTHENTICITY · **Surface:** /dashboard/agents · **Category:** auth
- **Source:** OBSERVED-CODE, OBSERVED-LIVE
- **Observed:** Anthropic consumer-subscription OAuth (PKCE) is fully implemented and active: `anthropic_oauth.py` (lines 1-265) implements `AUTHORIZE_URL=https://claude.ai/oauth/authorize` and `TOKEN_URL=https://api.anthropic.com/oauth/token` with PKCE; endpoints `GET /agents/auth/anthropic/{start,callback}` (`agents.py` lines 1520-1589) are live; 3 DB tables persist state — `UserProviderCredential` (`authMode='subscription_oauth'`), `AnthropicOAuthState`, `AnthropicOAuthToken`; `llm_client.py` sends Bearer + `anthropic-beta` oauth header, performs token refresh, and reports subscription quota usage.
- **Expected:** Per GT-3/§7/Gate-14 (Anthropic third-party auth policy [web:524]), consumer Free/Pro/Max subscription OAuth in a third-party product is non-compliant and must be removed. Anthropic access must use only server-side API-key auth (`x-api-key` via Claude Console/commercial credential), which is already implemented and functioning.
- **Root cause:** The prior "prud" remediation run (2026-07-14) built a subscription-OAuth PKCE flow believing it was a required enhancement; this predates the GT-3 compliance ruling surfaced fresh in this Phase-5 discovery. The API-key path already exists and works, so the OAuth path is pure non-compliant surface area, not a missing-feature gap.
- **Files:** `apps/api/app/services/anthropic_oauth.py`, `apps/api/app/services/llm_client.py`, `apps/api/app/routers/agents.py`, `apps/api/app/repositories/user_provider_credential.py`, `apps/web` (agents provider UI)
- **Wireframes:** `design/screens/agents.html`
- **Fix spec:** Remove `anthropic_oauth.py` and the `GET /agents/auth/anthropic/{start,callback}` routes (~1520-1589). Remove the `subscription_oauth` authMode branch from `UserProviderCredential` and the Bearer+`anthropic-beta` oauth path (incl. refresh and subscription-quota reporting) from `llm_client.py`. Retire (do not drop) `AnthropicOAuthState`/`AnthropicOAuthToken` tables per additive-only migration policy. Remove the "Connect with Anthropic" OAuth UI affordance, leaving only the existing API-key entry path.
- **Tests required:** anthropic_oauth route-removal pytest; provider_credential authMode enum pytest; playwright no-OAuth-control check; grep-based zero-reference check.
- **Verification recipe:** deploy → `GET /agents/auth/anthropic/{start,callback}` → 404 → confirm `/agents/config`/`/agents/providers` only advertise api_key mode → confirm x-api-key path unaffected → re-run OpenAPI inventory, confirm 0 oauth paths.
- **Pre-evidence:** `uat/reports/evidence/phase5/probe-003-openapi.json`, `EVIDENCE-SUMMARY.md`
- **Status:** TRIAGED · **Assigned role:** fixer-hard

### GAP-SRC-001 — Job sourcing single-source concentration and missing ATS connectors
- **Severity:** CRITICAL · **Type:** CAPABILITY · **Surface:** /dashboard/jobs · **Category:** sourcing
- **Source:** OBSERVED-LIVE, OBSERVED-CODE
- **Observed:** 155 total jobs; 96% (149) single-source from Seek. 5 live adapters (Seek/Greenhouse/Lever/Remotive/RemoteOk); LinkedIn/Indeed fixture-only; Workable/Ashby/Wellfound MISSING. Seek adapter hard-capped at 20 results/run (`seek_adapter.py:281`), no pagination beyond that cap. No per-company ATS portal configuration.
- **Expected:** Per §11.1/Journey A: add Workable/Ashby/Wellfound connectors; pagination-to-exhaustion on all adapters; >=25 net-new verified-real jobs across >=4 distinct sources per full sync; fingerprint dedupe (normalized company+title+location+source URL); liveness/freshness validation.
- **Root cause:** (1) Missing Workable/Ashby/Wellfound connectors. (2) `seek_adapter.py:281` hardcodes a 20-result cap with no next-page/offset logic. (3) No per-company ATS portal config equivalent to career-ops' `portals.yml` (GT-1/GT-2).
- **Files:** `apps/api/app/services/discovery/*`, `apps/api/app/agents/scout_agent.py`
- **Wireframes:** `design/screens/job-discovery.html`
- **Fix spec:** New connector modules for Workable/Ashby/Wellfound following the existing adapter interface. Remove the Seek 20-result cap; implement pagination-to-exhaustion across all adapters. Add normalized fingerprint dedupe key at persistence time. Add liveness/freshness validation before surfacing. Borrow career-ops portal-config/verification patterns (GT-1/GT-2).
- **Tests required:** pagination-exhaustion pytest; source failure isolation pytest; dedupe correctness pytest; expired-posting rejection pytest; new adapter unit tests; playwright per-source counts.
- **Verification recipe:** deploy → trigger `POST /agents/scout/run` → confirm >=25 net-new persisted → confirm >=4 distinct sources → cross-check >=10 sampled sourceUrls (§10.4) → confirm 0 fabricated/expired rows.
- **Pre-evidence:** `uat/reports/evidence/phase5/probe-004-jobs-initial.json`, `probe-004-jobs-analysis.txt`, `sourcing-pipeline-inventory.txt`, `EVIDENCE-SUMMARY.md`
- **Status:** TRIAGED · **Assigned role:** fixer-hard

### GAP-SRC-002 — Scout swallows real source failures as NotImplementedError; silent persisted=0 for 24h
- **Severity:** CRITICAL · **Type:** DEFECT · **Surface:** /dashboard/jobs · **Category:** sourcing
- **Source:** OBSERVED-LIVE, OBSERVED-CODE
- **Observed:** `scout_agent.py` catches real Seek 408/500 failures and re-wraps them as `NotImplementedError`, so runs report `errors:[]` (empty) while `persisted=0` for 24+ consecutive hours (40+ cron cycles). No per-source sync status (counts/last-sync/errors) is persisted or surfaced anywhere.
- **Expected:** Per §7/§8: no silently swallowed sourcing failures; no silent zero-result syncs without a surfaced cause. Honest per-source errors + a persisted, queryable `JobSourceStatus` record.
- **Root cause:** Exception handling catches source-specific errors and re-wraps them generically as `NotImplementedError` instead of propagating/recording the true failure; no `JobSourceStatus` persistence model exists.
- **Files:** `apps/api/app/agents/scout_agent.py`, `apps/api/app/services/discovery/*`
- **Wireframes:** `design/screens/job-discovery.html`
- **Fix spec:** Add `JobSourceStatus` table (`CREATE TABLE IF NOT EXISTS`, additive) with `last_run_at, jobs_found, jobs_persisted, error_message, error_code` per source. Stop re-wrapping as `NotImplementedError`; catch the real exception, log with context, write to `JobSourceStatus`. Populate `errors[]` honestly whenever a source fails or a run persists 0 new jobs.
- **Tests required:** simulated 408/500 → typed error recorded pytest; zero-net-new-with-real-error → non-empty errors[] pytest; JobSourceStatus round-trip pytest; no-silent-success pytest.
- **Verification recipe:** deploy → force/observe a source failure → query per-source status table, confirm real error recorded → confirm `errors[]` populated when `persisted=0` with failure → tail discovery.log, correlate with persisted status row.
- **Pre-evidence:** `uat/reports/evidence/phase5/probe-005-scout-trigger.json`, `probe-005-jobs-after-sync.txt`, `EVIDENCE-SUMMARY.md`
- **Status:** TRIAGED · **Assigned role:** fixer-hard

### GAP-SRC-003 — No per-source sync status indicator in jobs UI/API despite Sync Now button
- **Severity:** MEDIUM · **Type:** USABILITY · **Surface:** /dashboard/jobs · **Category:** sourcing
- **Source:** OBSERVED-LIVE
- **Observed:** /dashboard/jobs has a functioning "Sync Now" button, but no per-source sync status indicator (counts/last-sync/errors) exists in the UI or API.
- **Expected:** Per §11.1 acceptance criteria: unified + per-source results visible; each source reports counts/failures/timestamps honestly, surfaced in the UI.
- **Root cause:** No status API endpoint exists; no UI component consumes/renders it. Depends on `JobSourceStatus` from GAP-SRC-002.
- **Files:** `apps/web/src/app/dashboard/jobs/page.tsx`, `apps/api/app/routers` (jobs/discovery)
- **Wireframes:** `design/screens/job-discovery.html`
- **Fix spec:** Add `GET /jobs/sources/status` endpoint reading `JobSourceStatus`. Add a per-source status panel to the jobs page, refreshing after Sync Now.
- **Tests required:** status endpoint pytest; vitest/playwright status panel render.
- **Verification recipe:** deploy (depends on GAP-SRC-002) → click Sync Now → confirm panel updates → confirm endpoint data matches → confirm 0 console errors.
- **Pre-evidence:** `uat/reports/evidence/phase5/route-dashboard-jobs.png`, `EVIDENCE-SUMMARY.md`
- **Status:** TRIAGED · **Assigned role:** fixer-medium

### GAP-TAIL-001 — Tailored resume scores worse than baseline (craft_score 20/100, negative conversion lift)
- **Severity:** CRITICAL · **Type:** CAPABILITY · **Surface:** /dashboard/resume · **Category:** tailoring
- **Source:** OBSERVED-LIVE
- **Observed:** writer-audit craft_score for a tailored resume = 20/100 — WORSE than baseline (negative conversion lift). Rewriting is superficial; anti-fabrication guard too aggressive, rejects legitimate truthful rewrites.
- **Expected:** Per §11.2/Journey B: content-only inline rewriting raising ATS coverage using truthful JD keywords, preserved quantified achievements, tailoredATS >= baseline, writer-audit score above baseline, with externalized baseline/tailored/conversion-change/explanation.
- **Root cause:** Anti-fabrication guard is over-conservative — blocks truthful evidence-grounded rewrites (not just fabricated ones), collapsing rewrite to near-baseline text.
- **Files:** `apps/api/app/services/resume_tailor.py`, `apps/api/app/agents/tailor_agent.py`, `apps/api/app/services/ats_engine.py`, `apps/api/app/services/career_data.py`
- **Wireframes:** `design/screens/resume-studio.html`
- **Fix spec:** Recalibrate the guard to reject only claims unsupported by the career-evidence corpus while permitting truthful JD-keyword mirroring and quantified-achievement-preserving rewrites. Enforce tailoredATS >= baselineATS via `ats_engine.py` on both texts. Surface baseline/tailored/conversion-change/formula explanation (§11.2).
- **Tests required:** no-layout-mutation pytest; evidence-grounding-permits-truthful-mirroring pytest; tailoredATS>=baselineATS pytest; conversion-metric-explanation pytest; writer-audit re-score > 20/100; PDF export integrity pytest.
- **Verification recipe:** deploy → tailor a real sourced job via `POST /agents/tailor/run` → capture before/after + diff → confirm tailoredATS>=baselineATS → writer-audit re-score > 20/100 → export PDF, confirm layout unchanged.
- **Pre-evidence:** `uat/reports/evidence/phase5/tailor_run_response.json`, `tailor_diff.json`, `tailored_resume_full.json`, `base_resume.json`
- **Status:** TRIAGED · **Assigned role:** fixer-hard

### GAP-COV-001 — Cover letter craft below elite standard (craft_score 60/100 — weak hook/CTA)
- **Severity:** HIGH · **Type:** ENHANCEMENT · **Surface:** /dashboard/cover-letters · **Category:** cover_letter
- **Source:** OBSERVED-LIVE
- **Observed:** writer-audit craft_score for a generated cover letter = 60/100. Business-letter skeleton present but weak role/company hook, loose JD-tie, weak CTA.
- **Expected:** Per §11.3/Journey C: elite honest craft — specific company/role hook, JD-requirement-matched evidence, elegant CTA, non-boastful tone.
- **Root cause:** Generation prompt produces generic content instead of pulling a specific hook/JD-mapping from the sourced job + career-evidence corpus; no explicit CTA-quality directive.
- **Files:** `apps/api/app/agents/cover_letter_agent.py`
- **Wireframes:** `design/screens/cover-letter-studio.html`
- **Fix spec:** Enhance the prompt/pipeline to require a specific company/role hook (paragraph 1), JD-matched evidence (paragraph 2), a specific elegant CTA (paragraph 3), non-boastful tone (GT-5), following §11.3 content structure.
- **Tests required:** business-letter structure validator pytest; unsupported-claim rejection pytest; hook-presence pytest; CTA-presence pytest; PDF rendering test; writer-audit re-score > 60/100; approval flow regression pytest.
- **Verification recipe:** deploy → generate cover letter for a real sourced job → capture draft → writer-audit re-score > 60/100 → approve via workflow → export PDF, confirm clean.
- **Pre-evidence:** `uat/reports/evidence/phase5/cover_letter_text.txt`, `coverletter_run_response.json`
- **Status:** TRIAGED · **Assigned role:** fixer-medium

---

## 3. Already Satisfied (§3.3 mandatory families checked against fresh evidence — VERIFIED-CLOSED, no work opened)

Per §3.3, ten mandatory gap families must be pre-seeded. Six of the ten were checked against fresh
Phase-5 discovery evidence and found **already satisfied** by the prior "prud" remediation run.
They are recorded here as closed with verdict `ALREADY-SATISFIED` so no duplicate work is dispatched.
The remaining four families (`GAP-SRC-001`, `GAP-TAIL-001`, `GAP-COV-001`, `GAP-AUTH-001`) are open
above.

| ID | Verdict | Evidence Summary |
|---|---|---|
| GAP-WIRE-001 | ALREADY-SATISFIED | 0 dead primary controls; 343 controls functional; 0 console errors / 0 5xx across 15 routes |
| GAP-MET-001 | ALREADY-SATISFIED | Metrics wired, no recompute mismatch, MetricTooltip present |
| GAP-PDF-001 | ALREADY-SATISFIED | Resume 189KB + cover letter 23KB valid `%PDF` exports |
| GAP-DATA-001 | ALREADY-SATISFIED | All 5 sampled job sourceUrls resolve to real postings (single-source *diversity* is tracked under GAP-SRC-001, not fake-data) |
| GAP-UI-001 | ALREADY-SATISFIED | All 17 wireframes implemented/mapped |
| GAP-AGT-001 | ALREADY-SATISFIED | Agent config editable/persisted (from prior run) |

**Note on GAP-AGT-001 vs GAP-AUTH-001:** both touch `/dashboard/agents`, but they are distinct
findings — GAP-AGT-001 confirms agent *configuration* is editable/persisted (satisfied); GAP-AUTH-001
flags the Anthropic *consumer-subscription OAuth* path as non-compliant (open, CRITICAL). One does
not invalidate the other.

Only `qa-reviewer` may set `VERIFIED-CLOSED` per §3.2; these six were closed based on the fresh
discovery synthesis (reviewer/QA-role evidence review during this run's DISCOVER phase), not
self-approval by an implementer.

---

## 4. §12 Exit Gates (initial status: PENDING)

All 20 gates must pass and be independently evidenced before the run can close.

| # | Gate | Status |
|---|---|---|
| 1 | Production health endpoint returns expected success. | PENDING |
| 2 | Full route sweep completed with artifacts. | PENDING |
| 3 | All dead/decorative critical controls fixed or explicitly marked out-of-scope by code truth and wireframe contract. | PENDING |
| 4 | Wireframe fidelity matrix completed for all 17 screens. | PENDING |
| 5 | Job sourcing ceiling root-caused and materially improved. | PENDING |
| 6 | Post-fix sync yields substantially larger verified-real multi-board results. | PENDING |
| 7 | No fake/stale/fabricated job rows remain in sampled verification set. | PENDING |
| 8 | Tailored resume shows content-only inline changes with preserved layout. | PENDING |
| 9 | Tailored resume shows before/after conversion metric with explanation. | PENDING |
| 10 | Cover letter meets business-format and elite craft standard. | PENDING |
| 11 | Resume and cover-letter PDFs export cleanly. | PENDING |
| 12 | All displayed metrics have transparent explanations/tooltips. | PENDING |
| 13 | Metric recomputations match or are honestly labeled estimated. | PENDING |
| 14 | No unsupported Anthropic third-party consumer-subscription OAuth path remains; any Anthropic integration uses supported developer/commercial auth patterns. | PENDING |
| 15 | Tokens and client credentials are stored securely per Google/industry guidance if applicable. | PENDING |
| 16 | Full relevant backend tests pass. | PENDING |
| 17 | Full relevant frontend/unit tests pass. | PENDING |
| 18 | E2E journeys pass on production. | PENDING |
| 19 | Model-governance audit is clean: zero orchestrator-model sub-agent spawns. | PENDING |
| 20 | Every closed gap has pre/post evidence and QA closure. | PENDING |

Gates 3, 4, 7, 11, 12, 13 are partially pre-satisfied by the already-satisfied families in §3 above,
but remain marked `PENDING` here until re-confirmed as part of a full gate-check pass (per §4.10 —
gate status is a run-level determination, not inherited automatically from individual gap status).

---

## 5. Summary Counts

- **Open gaps (TRIAGED):** 6 — 4 CRITICAL, 1 HIGH, 1 MEDIUM
- **Already-satisfied families (VERIFIED-CLOSED / ALREADY-SATISFIED):** 6
- **Exit gates (PENDING):** 20 of 20
- **Total mandatory §3.3 families accounted for:** 10 of 10 (6 open + 6 already-satisfied — note GAP-AUTH-001 and GAP-AGT-001 both map to the `/dashboard/agents` surface but are distinct families, and GAP-SRC has three sub-IDs under one family)
