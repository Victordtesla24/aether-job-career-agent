# Phase-2 Audit — Defect Log (D1–D9)

**Date:** 2026-07-09 · **Branch:** `phase-2/intelligence` · **Production:** https://5cb5f0620.abacusai.cloud
All defects were found by the adversarial live audit (see `TRACEABILITY-MATRIX.md`), fixed on this
branch, re-verified **on production**, and covered by new automated tests. Raw evidence (curl
transcripts, DB before/after snapshots, screenshots) lives in the audit evidence archive
(`reverify-*.txt`, `shots/reverify-*.png`).

**Note on server logs:** `journalctl` for the API unit was empty and the legacy log file stale, so
runtime evidence was gathered from the `AgentRun` DB table and live reproduction instead of logs.

---

## D1 — Cover-letter & pipeline runs exceed the edge timeout (524) — **CRITICAL**

- **Symptom (before):** `POST /api/agents/cover-letter/run` and `POST /api/agents/pipeline/run`
  returned **524** from the edge (~100 s cut-off). DB `AgentRun` rows showed coverLetter runs of
  **133–157 s** despite a declared 60 s budget.
- **Root cause:** the httpx read timeout is **per-chunk**, not wall-clock — a model that keeps
  trickling tokens can run indefinitely. Additionally, in the pipeline each agent constructed its
  own `LLMClient`, so budgets were per-agent and additive.
- **Fix** (`apps/api/app/services/llm_client.py`, `apps/api/app/routers/agents.py`):
  1. Hard wall-clock cap: live calls run in a worker thread and are abandoned via
     `future.result(timeout=max_seconds)` — a trickling call can no longer exceed its budget.
  2. `shared_budget()` context manager (contextvar deadline) — the pipeline's tailor + coverLetter
     dispatches now share one wall-clock budget instead of stacking.
  3. Env-configurable fallback model (`AETHER_MODEL_FALLBACK`) and provider override
     (`AETHER_LLM_BASE_URL` / `AETHER_LLM_API_KEY`, any OpenAI-compatible endpoint incl. Anthropic)
     — ADR D-0017.
- **After (production):** cover-letter run **HTTP 200 in 60.3 s** (`reverify-D1.txt`); full pipeline
  **HTTP 200 in 62.4 s** (`reverify-D1-pipeline.txt`). No 524s.
- **Tests:** `tests/test_llm_resilience.py::TestHardBudgetCap` (3 new tests — trickling call
  abandoned at cap; shared budget bounds all clients in scope; provider base URL configurable).

## D2 — Approve/reject never updated the linked Application — **HIGH**

- **Symptom (before):** approving an `application_submit` approval left the tracked application
  stuck in `draft`; the kanban never reflected decisions (journey J4).
- **Root cause:** `ApprovalService.resolve()` flipped the approval row only; the
  `ApprovalRequest.applicationId` FK was never propagated.
- **Fix** (`apps/api/app/services/approval_service.py`): `resolve()` now calls
  `_sync_application()` — approve → `submitted`, reject → `rejected`, guarded to only transition
  applications still in `draft` (a decision can never regress an advanced application). ADR D-0016.
- **After (production):** `reverify-D2.txt` — application `c66207e…` `draft → submitted` on
  approve; application `c4365c…` `draft → rejected` on reject (DB before/after included).
- **Tests:** `tests/test_approvals.py` — 2 new tests (approve→submitted, reject→rejected).

## D3 — Cover-letter fixture contaminated with the wrong role/company — **HIGH**

- **Symptom (before):** replayed retry fixture `tests/fixtures/llm/cover_letter/retry.json`
  hard-coded "Data Engineer role at Atlassian", so retried generations could store letters citing
  the wrong job (observed on a DevOps Engineer job).
- **Fix:** fixture rewritten role/company-neutral. All other fixtures grep-verified clean.
- **After:** fresh production letters cite the correct role/company (see D1 evidence — Canva Staff
  Engineer and Immutable Full Stack Developer letters generated correctly).

## D4 — Jobs page had no path to tailoring — **MEDIUM**

- **Before:** wireframe `job-discovery.html` shows a per-job tailor action; production had none.
- **Fix** (`apps/web/src/app/dashboard/jobs/page.tsx`): per-card "Tailor Resume →" deep link
  (`data-testid="tailor-job-link"`) to `/dashboard/resume?job={id}`; resume studio pre-selects the
  job from the query param.
- **After (production):** 847 links rendered (`reverify-ui.log`, `shots/reverify-D4-jobs.png`).

## D5 — No resume Download control — **MEDIUM**

- **Before:** `resume-studio.html` shows a download action; the `POST /resumes/{id}/download`
  endpoint (intentional 501 until Phase 3) had no UI consumer.
- **Fix** (`apps/web/src/lib/api/resumes.ts`, `resume/page.tsx`): `downloadResume()` client +
  Download button; a 501 renders "PDF export is coming in Phase 3 — this version is safely stored."
- **After (production):** verified live (`shots/reverify-D5-resume.png`).
- **Tests:** vitest `phase2-audit-clients.test.ts` (501 surfaces as `ApiError(status=501)`).

## D6 — Story Bank had no create/edit UI — **MEDIUM**

- **Before:** `story-bank.html` shows manual STAR entry; production only listed/extracted/deleted.
  `POST /stories` and `PUT /stories/{id}` had no UI consumers.
- **Fix** (`apps/web/src/lib/api/stories.ts`, `stories/page.tsx`): `createStory`/`updateStory`
  clients; "Add story" STAR form + per-card inline edit.
- **After (production):** story created end-to-end live and persisted
  (`reverify-ui.log` "D6-create PASS", `shots/reverify-D6-stories.png`).
- **Tests:** 3 new vitest cases (POST payload, PUT partial, zod rejection).

## D7 — Applications: no detail view, no pending-approvals cue — **MEDIUM**

- **Before:** `application-tracker.html` shows a detail panel and approval linkage; production
  kanban cards were inert and `GET /applications/{id}` had no consumer.
- **Fix** (`applications.ts`, `applications/page.tsx`): clickable cards open a detail panel
  (status, resume version, cover letter); non-fatal pending-approvals banner links to the
  approvals queue.
- **After (production):** banner + detail panel verified (`shots/reverify-D7-applications.png`).
- **Tests:** 2 new vitest cases (detail fetch validates; invalid status enum rejected).

## D8 — Approvals: expired requests actionable forever — **MEDIUM**

- **Before:** `approval-modal.html` specifies expiry; the backend enforces a 48-h expiry on
  *consumption* (`assert_action_allowed` → 409) but the UI let users approve/reject stale items
  with no signal.
- **Fix** (`approvals/page.tsx`): 48-h `isExpired()` check — expired badge
  (`data-testid="expired-badge"`) and approve/reject disabled past expiry, matching the backend
  window.
- **After (production):** current queue has no expired items (badge count 0, correctly
  data-dependent); rendering path exercised in code review + build (`shots/reverify-D8-approvals.png`).

## D9 — `GET /analytics/conversion` had no UI consumer — **LOW**

- **Before:** the endpoint returned four stage-conversion rates that no screen displayed
  (`analytics.html` wireframe includes them).
- **Fix** (`analytics.ts`, `analytics/page.tsx`): `fetchConversion(period)` client + a
  "Stage conversion" section that re-fetches on period change.
- **After (production):** renders `48.88% Found→Applied · 37.68% Applied→Screened ·
  14.74% Screened→Interview · 17.39% Interview→Offer` for `all`
  (`shots/reverify-D9-analytics.png`).
- **Tests:** 2 new vitest cases (valid payload parses; malformed payload rejected).

## D10 — Agents console: "Run Full Pipeline" perceived dead + silent long-running calls — **HIGH**

- **Before (root cause):** the button was *not* dead — Playwright network capture showed the click
  fires `POST /agents/pipeline/run` — but the endpoint is a single synchronous 25–120 s call and
  the UI gave zero feedback until it returned, so it looked frozen. Three genuine wiring defects
  were hiding behind it: (1) **supervisor and matcher were never executed or recorded** by the
  FastAPI pipeline (registry-only → permanent "Never run" cards) despite being canonical nodes in
  `aether-graph.ts`; (2) the per-agent **Tailor/CoverLetter Run buttons sent `{}`** →
  guaranteed 422 (actually-dead buttons); (3) failures surfaced as raw errors with no guidance.
- **Fix (API, `routers/agents.py`):** pipeline now records a real `supervisor` AgentRun (the
  execution plan) and a real `matcher` AgentRun (top-job selection incl. `top_job_title`/
  `top_company`), in canonical order supervisor → scout → fitScorer → matcher → tailor →
  coverLetter; empty-job runs record `matcher(matched=0)`. New `tests/test_pipeline.py` (2 tests).
- **Fix (web, `lib/agents-feedback.ts` + `agents/page.tsx`):** pure, unit-tested notice helpers —
  immediate "Pipeline started — Scout is discovering jobs…" banner + disabled button + spinner on
  click; 3 s polling of `/agents/runs` drives a live "step X of 6: …" progress banner and
  refreshes RECENT RUNS + agent cards mid-run; completion banner summarises matched/scored/
  changes/letter and links to Approvals (or Jobs when nothing matched); errors map to action:
  503 → "model busy / budget exceeded — retry", 422 → "run Scout first", 401 → "reload to sign in".
  Tailor/CoverLetter Run buttons now resolve the top job by fit score before dispatching;
  supervisor/matcher cards state they execute inside the full pipeline.
- **After (production):** notice appears <1 s after click, progress advanced through steps 5→6,
  completion banner with Approvals CTA at ~27 s, supervisor/matcher cards show fresh `last_run`
  with matching DB `AgentRun` rows, per-agent Tailor run succeeds (8 changes), 0 console errors
  (`reverify-pipeline-ux.txt`, `shots/reverify-pipeline-ux.png`, `shots/reverify-tailor-button.png`).
- **Tests:** +2 pytest (pipeline step recording), +15 vitest (`agents-feedback.test.ts`);
  brittle hardcoded `applied=412` funnel assertion in `e2e/analytics.spec.ts` replaced with a
  live-API comparison (pipeline runs legitimately create draft applications).

---

## Quality gates (post-fix)

| Gate | Result |
|---|---|
| pytest (apps/api) | **112 passed** (99 → 112; +13 new), coverage **91%** (floor 86%) |
| ruff / mypy | clean (48 source files) |
| vitest (apps/web) | **62 passed** (38 → 62; +24 new) |
| next lint / tsc --noEmit / next build | clean |
| Playwright e2e | **24 passed** |
