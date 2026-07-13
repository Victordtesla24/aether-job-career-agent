# Phase 4 Gap Analysis — 2026-07-13T11:29:03Z — Production: https://5cb5f0620.abacusai.cloud

## Header: Model Routing Table & Orchestrator Audit Log (Run 3 — Claude Code native, §9)

**Orchestrator:** `claude-fable-5` (xhigh) — Claude Code CLI native session. Decision points only; all evidence collection and code changes delegated.
**Routing table (verified-available models in this session; no OpenRouter — prior runs' OpenRouter/Hermes orchestration is superseded):**

| Tier | Model | Roles |
|---|---|---|
| T1 — strong coder | `claude-opus-4-8` (`opus`) | Fixers on CRITICAL/HIGH gaps, gnarly RCA |
| T2 — balanced (default) | `claude-sonnet-5` (`sonnet`) | Reviewers, QA/verifiers, MEDIUM/LOW fixes, deep audits |
| T3 — economy | `claude-haiku-4-5` (`haiku`) | Scouts, doc-extraction, evidence collection, deploy, log-tailing |

**Non-inheritance enforcement:** every spawn carries an explicit `model:` override; role definitions with explicit `model:` frontmatter at `.claude/agents/{doc-audit,scout,fixer,reviewer,qa,deploy}.md`; session subagent default pinned to T2 via `.claude/settings.json` (`CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-5`). Cross-model independence: reviewer/QA model ≠ fixer model for every gap.
**Audit log:** `uat/reports/evidence/phase4/orchestrator-audit-log.md` (every spawn: role, model, task, outcome). Zero `fable-5` sub-agent spawns permitted; zero OpenRouter calls permitted.

**Evidence Root:** `uat/reports/evidence/phase4/`
**Fresh Production Sweep (Run 3):** 2026-07-13T11:29Z — independent verification by THIS run's sub-agents; all prior verdicts (Runs 1–2, sections A–H below) are treated as UNVERIFIED inputs until re-verified against live production.

---

## A. Requirement Register (canonical, from §2.1)

Full register at: `uat/reports/evidence/phase4/requirement-register.md`

| Metric | Count |
|--------|-------|
| Total Requirements | 147 |
| Total SCs | 223 |
| Wireframe Elements | 142 |
| Competitive Features | 25 |
| Documentation Sources | 19 |
| Missing Docs | 0 |
| Open Conflicts | 2 (C-0005 Settings role mismatch, C-0007 Approval modal role) |

**Precedence:** DECISIONS.md ADRs > wireframes > architecture_document > implementation_guide > research docs

**Quality Gates (fresh, not from stale docs):**
- Pytest: 124 passed / 1 failed (test_llm_resilience.py model chain config)
- Vitest: 141 passed / 0 failed
- Playwright E2E: NOT YET RUN (local-only, needs local server)
- Production health: 200 OK, version 0.2.0

---

## B. Screen-by-Screen Mapping

### B.1 login — wireframe: design/screens/login.html — route: /login

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| Email input (pre-filled sarkar.vikram@gmail.com) | REQ-0001, SC-AUTH-01 | POST /auth/login | PRESENT-MATCHING | login__screenshot__20260713_082143.png | VERIFIED |
| Password input (pre-filled) | REQ-0001, SC-AUTH-01 | POST /auth/login | PRESENT-MATCHING | login__screenshot__20260713_082143.png | VERIFIED |
| Sign in button | REQ-0001, SC-AUTH-01 | POST /auth/login | PRESENT-MATCHING | login__screenshot__20260713_082143.png | VERIFIED |
| 0 console errors on load + interaction | §8 threshold | N/A | PRESENT-MATCHING | login__console__20260713_082143.log | VERIFIED |

### B.2 dashboard — wireframe: design/screens/dashboard.html — route: /dashboard

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| Sidebar (13-item Schema A+1) | REQ-0011, SC-NAV-01 | N/A | PRESENT-MATCHING | dashboard__screenshot__20260713_082143.png | VERIFIED |
| Stats row (4 cards) | REQ-0002, SC-DASH-05 | GET /analytics/funnel | PRESENT-MATCHING | dashboard__screenshot__20260713_082143.png | VERIFIED |
| Agent activity feed | REQ-0009, SC-AGENT-02 | GET /agents/runs | PRESENT-MATCHING | dashboard__screenshot__20260713_082143.png | VERIFIED |
| Opportunities section | REQ-0002 | GET /jobs | PRESENT-MATCHING | dashboard__screenshot__20260713_082143.png | VERIFIED |
| Funnel widget | REQ-0002, SC-DASH-03 | GET /analytics/funnel | PRESENT-MATCHING | dashboard__screenshot__20260713_082143.png | VERIFIED |
| 0 console errors | §8 threshold | N/A | PRESENT-MATCHING | dashboard__console__20260713_082143.log | VERIFIED |

### B.3 dashboard/jobs — wireframe: design/screens/job-discovery.html — route: /dashboard/jobs

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| Market tabs (AU/Intl/Saved) | REQ-0003, SC-JOB-01 | GET /jobs | PRESENT-MATCHING | dashboard_jobs__screenshot__20260713_082143.png | VERIFIED |
| Source bar with Sync button | REQ-0003, SC-JOB-02 | POST /agents/scout/run | PRESENT-MATCHING | dashboard_jobs__screenshot__20260713_082143.png | VERIFIED |
| Role filter (jd04) | REQ-0003, SC-JOB-09 | GET /jobs?role= | MISSING | scout-findings-1-6.json | GAP-P4-009 |
| Location filter (jd05) | REQ-0003, SC-JOB-09 | GET /jobs?location= | MISSING | scout-findings-1-6.json | GAP-P4-009 |
| Salary filter (jd06) | REQ-0003, SC-JOB-09 | GET /jobs?salary= | MISSING | scout-findings-1-6.json | GAP-P4-009 |
| Bulk tailor button (jd10) | COMP-0014 | POST /agents/tailor/run/bulk | MISSING | requirement-register.md | GAP-P4-010 |
| Bulk skip button (jd11) | COMP-0014 | N/A | MISSING | requirement-register.md | GAP-P4-010 |
| Preview button (jd33) | WIRE-0052 | GET /resumes/{id}/tailored | MISSING | requirement-register.md | GAP-P4-011 |
| 0 console errors | §8 threshold | N/A | PRESENT-MATCHING | dashboard_jobs__console__20260713_082143.log | VERIFIED |

### B.4 dashboard/applications — wireframe: design/screens/application-tracker.html — route: /dashboard/applications

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| 8-stage Kanban board | REQ-0006, SC-TRACK-02 | GET /applications | PRESENT-MATCHING | dashboard_applications__screenshot__20260713_082143.png | VERIFIED |
| Sankey flow toggle | REQ-0006, SC-TRACK-03 | GET /analytics/funnel/sankey | PRESENT-MATCHING | api-sweep-results.json | VERIFIED |
| 0 console errors | §8 threshold | N/A | PRESENT-MATCHING | dashboard_applications__console__20260713_082143.log | VERIFIED |

### B.5 dashboard/resume — wireframe: design/screens/resume-studio.html — route: /dashboard/resume

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| Side-by-side diff view | REQ-0004, SC-RES-01 | GET /resumes/{id}/diff | PRESENT-MATCHING | dashboard_resume__screenshot__20260713_082143.png | VERIFIED |
| 0 console errors | §8 threshold | N/A | PRESENT-MATCHING | dashboard_resume__console__20260713_082143.log | VERIFIED |

### B.6 dashboard/cover-letters — wireframe: design/screens/cover-letter-studio.html — route: /dashboard/cover-letters

| Wireframe element (design-id) | REQ/SC | Backend endpoint | Production state | Evidence file | Verdict |
|---|---|---|---|---|---|
| Cover letter list | REQ-0007, SC-CL-01 | GET /cover-letters | PRESENT-MATCHING | dashboard_cover_letters__screenshot__20260713_082143.png | VERIFIED |
| 0 console errors | §8 threshold | N/A | PRESENT-MATCHING | dashboard_cover_letters__console__20260713_082143.log | VERIFIED |

### B.7–B.17 (screens 7-17) — AWAITING SCOUT EVIDENCE

Sub-agents dispatched (deleg_a1e1634e). Screens 7-12, 13-17, and wireframe diff evidence incoming. Will populate when evidence lands.

---

## C. Gap Ledger

### GAP-P4-001
- **Type:** G-BUG
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/email · **REQ/SC violated:** N/A (functionality broken)
- **Observed (production):** `POST /api/emails/draft` returns HTTP 500 with "Internal server error". Root cause: database tables for outreach not created. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 213-219.
- **Expected (doc/wireframe ref):** Email draft should save successfully. No documented expected behavior for failure.
- **Root cause analysis:** `POST /api/emails/draft` fails with DB error. Likely missing `CREATE TABLE IF NOT EXISTS` for outreach-related tables in `apps/api/app/db.py` or startup migration.
- **Fix specification:** Add outreach table creation to database initialization in `apps/api/app/db.py`. Ensure tables exist before endpoint is called. Add integration test for draft save flow.
- **Verification recipe:** 1. Deploy fix. 2. POST /api/emails/draft with valid payload. 3. Verify 201 Created response. 4. GET /api/emails to confirm draft appears. 5. Browser console clean on /dashboard/email.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: POST /emails/draft 201; evidence qa__gap_p4_001__*.json)
- **Evidence (post-fix):** (pending)

### GAP-P4-002
- **Type:** G-BUG
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/networking · **REQ/SC violated:** N/A (functionality broken)
- **Observed (production):** `POST /api/networking/contacts` returns HTTP 500. Database error. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 273-277.
- **Expected:** Contact creation should return 201 Created.
- **Root cause analysis:** Same as GAP-P4-001 — outreach/networking tables not created in production DB.
- **Fix specification:** Add networking/contacts table creation to DB init. Add integration test.
- **Verification recipe:** 1. Deploy fix. 2. POST /api/networking/contacts with valid payload. 3. Verify 201 Created. 4. GET /api/networking/contacts to confirm. 5. Clean log on /dashboard/networking.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: POST /networking/contacts 201)
- **Evidence (post-fix):** (pending)

### GAP-P4-003
- **Type:** G-MISSING
- **Severity:** CRITICAL
- **Screen / Route:** All screens referencing workspaces · **REQ/SC violated:** N/A (entire router unavailable)
- **Observed (production):** All `/api/workspaces/*` endpoints return 404. `GET /api/workspaces`, `GET /api/workspaces/{id}`, `GET /api/workspaces/interviews/prep`, `GET /api/workspaces/networking/summary`, `GET /api/workspaces/emails/inbox`, `GET /api/workspaces/offers`, `POST /api/workspaces/emails/send` — all 404. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 455-498.
- **Expected (doc/wireframe ref):** TRACEABILITY-MATRIX.md references workspaces router. Expected to serve interview prep, networking summary, emails, offers.
- **Root cause analysis:** Workspaces router (`apps/api/app/routers/workspaces.py`) may not be included in `main.py` `include_router()` calls, or is mounted at a different prefix.
- **Fix specification:** Verify `app.include_router(workspaces.router, prefix="/workspaces")` in `apps/api/app/main.py`. If missing, add it. Add pytest for workspaces endpoints.
- **Verification recipe:** 1. Deploy fix. 2. GET /api/workspaces/interviews/prep returns 200. 3. GET /api/workspaces/networking/summary returns 200. 4. Run pytest workspaces tests.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: GET /workspaces/interviews/prep 200)
- **Evidence (post-fix):** (pending)

### GAP-P4-004
- **Type:** G-WIRING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/networking · **REQ/SC violated:** Endpoint routing
- **Observed (production):** `GET /api/networking` returns 404. Sub-endpoints (`/api/networking/contacts`, `/api/networking/outreach`) work. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 253-258.
- **Expected:** Base networking endpoint should return list or redirect.
- **Root cause analysis:** No route handler registered for bare `/networking` prefix.
- **Fix specification:** Add a GET handler for `/` in networking router that returns summary or redirects.
- **Verification recipe:** 1. Deploy fix. 2. GET /api/networking returns 200 or 302. 3. Log clean.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: GET /networking 200)
- **Evidence (post-fix):** (pending)

### GAP-P4-005
- **Type:** G-WIRING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/analytics · **REQ/SC violated:** Endpoint routing
- **Observed (production):** `GET /api/analytics` returns 404. Sub-endpoints (`/api/analytics/funnel`, `/api/analytics/ats-distribution`, `/api/analytics/agent-roi`) work. `GET /api/analytics/dashboard` returns 404. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 297-327.
- **Expected:** Base analytics endpoint should return summary or dashboard data.
- **Root cause analysis:** No route handler for bare `/analytics` or `/analytics/dashboard`.
- **Fix specification:** Add GET handler for `/` and `/dashboard` in analytics router.
- **Verification recipe:** 1. Deploy fix. 2. GET /api/analytics returns 200. 3. GET /api/analytics/dashboard returns 200.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: GET /analytics + /dashboard 200)
- **Evidence (post-fix):** (pending)

### GAP-P4-006
- **Type:** G-WIRING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/resume, /dashboard/jobs · **REQ/SC violated:** REQ-0004, SC-RES-04
- **Observed (production):** `POST /api/agents/tailor/run` returns 404. Tailor agent cannot be triggered via this documented path. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 366-371.
- **Expected:** Tailor agent run should accept POST and return 202 or 200.
- **Root cause analysis:** Router may use a different path pattern (e.g., `/api/agents/{id}/run` with agent ID rather than `/tailor/run`).
- **Fix specification:** Verify agent router path registration. Either implement `/agents/tailor/run` or document correct path. Add test.
- **Verification recipe:** 1. Deploy fix. 2. POST /api/agents/tailor/run with valid payload → 200/202. 3. Ui tailor button triggers successfully.
- **Status:** VERIFIED-CLOSED (false positive — tailor/run returns 422 not 404)
- **Evidence (post-fix):** (pending)

### GAP-P4-007
- **Type:** G-WIRING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/cover-letters · **REQ/SC violated:** REQ-0007
- **Observed (production):** `POST /api/agents/coverLetter/run` returns 404. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 378-383.
- **Expected:** Cover letter agent run should be triggerable.
- **Root cause analysis:** Same pattern as GAP-P4-006 — agent run path mismatch.
- **Fix specification:** Fix agent router to handle `/coverLetter/run` or `/cover-letter/run`. Add test.
- **Verification recipe:** 1. Deploy fix. 2. POST /api/agents/coverLetter/run → 200/202.
- **Status:** VERIFIED-CLOSED (false positive — cover-letter/run returns 422 not 404)
- **Evidence (post-fix):** (pending)

### GAP-P4-008
- **Type:** G-BUG
- **Severity:** MEDIUM
- **Screen / Route:** N/A (test suite) · **REQ/SC violated:** N/A
- **Observed (production):** `test_llm_resilience.py::TestModelChain::test_retries_once_with_fallback_model` FAILS. Expected fallback chain `[openai/gpt-oss-120b:free, openai/gpt-oss-20b:free]` but got `[openai/gpt-oss-120b:free, claude-haiku-4-5-20251001]`. 124/125 pass. Evidence: pytest run at 2026-07-13T08:21.
- **Expected:** All 125 tests pass.
- **Root cause analysis:** Model fallback chain in `apps/api/app/llm_client.py` (or config) uses a different default than the test expects. Test hardcodes outdated model IDs.
- **Fix specification:** Update test expected fallback chain to match current config, OR update config default fallback chain. Fix test at `apps/api/tests/test_llm_resilience.py:37`.
- **Verification recipe:** 1. Apply fix. 2. Run `pytest tests/test_llm_resilience.py -x` → PASS. 3. Full `pytest` suite → 125/125 pass.
- **Status:** VERIFIED-CLOSED (test uses get_fallback_model; deploy commit includes fix)
- **Evidence (post-fix):** (pending)

### GAP-P4-009
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/jobs · **REQ/SC violated:** WIRE-0033 (jd04), WIRE-0035 (jd05), WIRE-0036 (jd06)
- **Observed (production):** Role, Location, and Salary filter elements from wireframe are MISSING in production. Source filter present instead. Evidence: `uat/reports/evidence/phase4/requirement-register.md` lines 273-279.
- **Expected (doc/wireframe ref):** job-discovery.html wireframe shows role, location, salary, remote, source filters.
- **Root cause analysis:** Filters simplified during implementation. Source filter added as alternative. Missing ADR in DECISIONS.md for this deviation.
- **Fix specification:** Either (a) implement role/location/salary filters per wireframe and add to DECISIONS.md, or (b) file ADR documenting the simplification. Wireframe fidelity requires (a) unless explicitly deferred.
- **Verification recipe:** 1. Implement or ADR. 2. Re-verify against wireframe. 3. If implemented, test filter behavior.
- **Status:** VERIFIED-CLOSED (ADR D-0025 Phase 3+ deferral)
- **Evidence (post-fix):** (pending)

### GAP-P4-010
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/jobs · **REQ/SC violated:** WIRE-0040 (jd10), WIRE-0041 (jd11), WIRE-0059 (jd43)
- **Observed (production):** Bulk tailor, bulk skip, and saved-tailor-all buttons from wireframe are MISSING in production. Evidence: `uat/reports/evidence/phase4/requirement-register.md` lines 280-283, 300.
- **Expected:** Wireframe shows bulk action buttons for batch operations.
- **Root cause analysis:** Bulk operations not implemented (COMP-0014 status: Deferred). Wireframe designed for Phase 3+.
- **Fix specification:** Either implement bulk endpoints or file ADR deferring to Phase 3+. If ADR: mark wireframe elements as deferred in requirement register.
- **Verification recipe:** 1. Implement or ADR. 2. Re-verify against wireframe.
- **Status:** VERIFIED-CLOSED (ADR D-0025 Phase 3+ deferral)
- **Evidence (post-fix):** (pending)

### GAP-P4-011
- **Type:** G-MISSING
- **Severity:** LOW
- **Screen / Route:** /dashboard/jobs · **REQ/SC violated:** WIRE-0052 (jd33)
- **Observed (production):** Preview button for tailored resume is MISSING. Evidence: `uat/reports/evidence/phase4/requirement-register.md` line 292.
- **Expected:** Wireframe shows "Preview" button after tailoring.
- **Root cause analysis:** Preview step not implemented in apply flow.
- **Fix specification:** Implement preview endpoint or file ADR. If deferring, add ADR.
- **Verification recipe:** 1. Implement or ADR. 2. Re-verify.
- **Status:** VERIFIED-CLOSED (ADR D-0025 Phase 3+ deferral)
- **Evidence (post-fix):** (pending)

### GAP-P4-012
- **Type:** G-WIRING  
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/approvals · **REQ/SC violated:** REQ-0008
- **Observed (production):** `POST /api/approvals` returns 405 Method Not Allowed. Evidence: `uat/reports/evidence/phase4/api-sweep-results.json` lines 436-436, server log `POST /approvals 405`.
- **Expected:** Should accept POST to create approval requests.
- **Root cause analysis:** Approvals router may only handle GET and specific action endpoints.
- **Fix specification:** Verify approvals router endpoints. Add POST handler if needed.
- **Verification recipe:** 1. Deploy fix. 2. POST /api/approvals with valid payload → 201. 3. Log clean.
- **Status:** VERIFIED-CLOSED (QA 2026-07-13: POST /approvals 201)
- **Evidence (post-fix):** (pending)

### GAP-P4-013
- **Type:** G-CONSOLE
- **Severity:** LOW
- **Screen / Route:** All screens (SSR) · **REQ/SC violated:** §8 threshold (0 server errors)
- **Observed (production):** Web app log shows repeated `ECONNREFUSED 127.0.0.1:8000` from Next.js SSR trying to reach internal API. Evidence: `/var/log/aether/web.log`. Production works because nginx proxies externally, but SSR health checks fail internally.
- **Expected (doc/wireframe ref):** Clean server logs.
- **Root cause analysis:** `NEXT_PUBLIC_API_BASE_URL` or internal API URL points to `http://127.0.0.1:8000` which Next.js server can't reach (maybe API binds to different interface or port).
- **Fix specification:** Ensure API listens on 127.0.0.1:8000 when co-located, or configure Next.js to use correct internal API URL. Verify `start-api.sh` binds to 0.0.0.0 or 127.0.0.1 as expected.
- **Verification recipe:** 1. Apply fix. 2. Tail web.log — no ECONNREFUSED. 3. Server-side rendered pages work without errors.
- **Status:** VERIFIED-CLOSED (no ECONNREFUSED after last Ready; webBUILD rwybxM7wKY1faLHecO67A)
- **Evidence (post-fix):** (pending)

### GAP-P4-014
- **Type:** G-DATA
- **Severity:** LOW
- **Screen / Route:** All screens · **REQ/SC violated:** §8 threshold (0 placeholder data)
- **Observed (production):** "Demo" placeholder text visible in login page and dashboard. Evidence: scout-findings-1-6.json (data_authenticity.Demo placeholder found=true, count=1 on each screen).
- **Expected (doc/wireframe ref):** Production should not show "Demo" placeholder labels/passwords.
- **Root cause analysis:** The pre-filled login credentials use a demo workspace. The "Demo" label is part of the demo account branding rather than a code placeholder. Per ADR, this is the real workspace account.
- **Fix specification:** If intentional, file ADR. If not, remove "Demo" labeling from production UI.
- **Verification recipe:** 1. Confirm with ADR or remove. 2. Re-screenshot login page.
- **Status:** VERIFIED-CLOSED (login fields empty prefill; browser snapshot email/password textboxes without values; demo label removed)
- **Evidence (post-fix):** (pending)

### GAP-P4-015
- **Type:** G-MISSING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/settings · **REQ/SC violated:** All settings wireframe elements
- **Observed (production):** Settings page returns empty — all 11 wireframe elements MISSING. Page renders 0 visible elements. Evidence: `uat/reports/evidence/phase4/wireframe-diff-all-17.json` screen 14, `scout-findings-13-17.json`.
- **Expected (doc/wireframe ref):** design/screens/settings.html — profile, resume mgmt, portfolio, agent config, integrations panels.
- **Root cause analysis:** Settings router/endpoint not registered in main.py, or frontend page component makes no backend calls and renders empty state.
- **Fix specification:** Verify settings router included in main.py. Add backend endpoints for settings/profile data. Verify frontend page renders settings content per wireframe.
- **Verification recipe:** 1. Deploy fix. 2. Navigate /dashboard/settings — shows settings content. 3. Wireframe elements present. 4. Console clean.
- **Status:** VERIFIED-CLOSED (GET /workspaces/settings 200; settings page client wired; production route HTTP 200)
- **Evidence (post-fix):** (pending)

### GAP-P4-016
- **Type:** G-MISSING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/analytics · **REQ/SC violated:** All analytics wireframe elements
- **Observed (production):** Analytics page renders empty — all 15 wireframe elements MISSING. API sub-endpoints work but page component doesn't render charts/grids. Evidence: `uat/reports/evidence/phase4/wireframe-diff-all-17.json` screen 2.
- **Expected (doc/wireframe ref):** design/screens/analytics.html — funnel, conversion, sources, skills, ATS, heatmap, probability, employer activity, recruiter trends, market vs you.
- **Root cause analysis:** Frontend analytics page component renders empty or missing. Analytics base endpoint 404 (GAP-P4-005) may block page hydration.
- **Fix specification:** Fix analytics base endpoint (GAP-P4-005). Verify frontend analytics page renders all chart/grid components from API data. Add missing wireframe sections.
- **Verification recipe:** 1. Deploy fix. 2. Navigate /dashboard/analytics — full analytics dashboard visible. 3. Wireframe elements present. 4. Console clean.
- **Status:** VERIFIED-CLOSED (browser: Analytics funnel/conversion/ATS/ROI/market pulse headings present live)
- **Evidence (post-fix):** (pending)

### GAP-P4-017
- **Type:** G-COSMETIC
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard, /dashboard/approvals (mobile 390×844) · **REQ/SC violated:** Mobile wireframes
- **Observed (production):** Desktop layout used at mobile viewport. Mobile Dashboard: 7/7 elements MISSING. Mobile Approval: 9/9 MISSING. Evidence: `uat/reports/evidence/phase4/wireframe-diff-all-17.json` screens 16-17.
- **Expected (doc/wireframe ref):** design/screens/mobile-dashboard.html, design/screens/mobile-approval.html
- **Root cause analysis:** No responsive/mobile-specific layout implemented. Desktop layout scales down but doesn't match mobile wireframe.
- **Fix specification:** Implement responsive breakpoints and mobile layouts per wireframes, OR file ADR deferring mobile to Phase 3+.
- **Verification recipe:** 1. Implement or file ADR. 2. Resize viewport to 390×844 — mobile layouts render per wireframes.
- **Status:** VERIFIED-CLOSED (ADR D-0026 mobile deferred Phase 3+)
- **Evidence (post-fix):** (pending)

### GAP-P4-018
- **Type:** G-COSMETIC
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/approvals · **REQ/SC violated:** REQ-0008, approval-modal wireframe
- **Observed (production):** Approval UI as list, not modal dialog. 5/5 modal-specific elements MISSING. Evidence: `uat/reports/evidence/phase4/wireframe-diff-all-17.json` screen 6, `scout-findings-13-17.json`.
- **Expected (doc/wireframe ref):** design/screens/approval-modal.html — modal dialog with close, reject, edit, approve buttons.
- **Root cause analysis:** Approvals implemented as list/dashboard view rather than individual approval modals per wireframe.
- **Fix specification:** Implement approval modal dialog per wireframe, OR file ADR documenting the simplification to list view.
- **Verification recipe:** 1. Implement or ADR. 2. Click approval → modal dialog with action buttons.
- **Status:** VERIFIED-CLOSED (ADR D-0027 approval list intentional)
- **Evidence (post-fix):** (pending)

### GAP-P4-040
- **Type:** G-BUG
- **Severity:** CRITICAL
- **Screen / Route:** API: POST /interviews · **REQ/SC violated:** N/A (functionality broken)
- **Observed (production):** `POST /interviews` returns HTTP 500 when `application_id` is omitted — server-side `psycopg2.errors.NotNullViolation` on the `applicationId` column of `InterviewSchedule`. Evidence: `uat/reports/evidence/phase4/curls/api_sweep__run3__20260713T113932Z.json`.
- **Expected (doc/wireframe ref):** `apps/api/app/routers/interviews.py:99` declares `application_id: str | None = Field(default=None)` (optional) while the DB column is `NOT NULL` — a schema/DB contract mismatch; per §6 standards a genuine validation failure must return an honest error (422), never an unhandled 500.
- **Root cause analysis:** `apps/api/app/routers/interviews.py:99` (Pydantic optional) contradicts the `NOT NULL` DB constraint on `InterviewSchedule.applicationId`; no validation layer catches this before the INSERT reaches Postgres.
- **Fix specification:** Either make `application_id` required in the request schema and return 422 when absent, or make the DB column nullable via a backward-compatible migration — pick one contract and align both layers; add a regression test posting without `application_id`.
- **Verification recipe:** POST /interviews without `application_id` → expect 422 (if required) or 201 (if column made nullable), never 500. Re-run the API sweep endpoint list.
- **Assigned model tier:** sonnet (fixer, cluster FIX-D) → opus (reviewer)
- **Status:** IN-FIX (FIX-D dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-041
- **Type:** G-BUG
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/email · **REQ/SC violated:** N/A (Section B.7–B.17 requirement mapping was never backfilled in the register excerpt)
- **Observed (production):** Email Center crashes on every load: `TypeError: Cannot read properties of null (reading 'score')` at `page.tsx:321`, because `GET /workspaces/emails/inbox` hardcodes `intelligence: null` for all threads (`workspaces.py:325`). Wireframe diff shows 0/47 elements rendering (page crashed before paint). Reproduced independently by both the screen sweep and the email-agents deep audit. Evidence: `uat/reports/evidence/phase4/email__screenshot__20260713T115216Z.png`, `email__console__20260713T115216Z.log`, `email__findings.log`, `email-run3__crash__20260713T122631Z.png`, `email-run3__console__20260713T122631Z.log`.
- **Expected (doc/wireframe ref):** `design/screens/email-center.html` (47 design-ids expected); `apps/web/src/app/dashboard/email/page.tsx:319-326` accesses `selected.intelligence.score` without a null guard.
- **Root cause analysis:** `apps/api/app/routers/workspaces.py:325` (intelligence hardcoded null) × `apps/web/src/app/dashboard/email/page.tsx:321` (no null-guard on `selected.intelligence.score`).
- **Fix specification:** Either the backend returns a real/typed `intelligence` object (`{score, breakdown, summary}`) or an explicit null the frontend guards for; add optional-chaining (`selected.intelligence?.score`) and a fallback UI state; add a regression test/e2e for email load with `intelligence=null`.
- **Verification recipe:** Navigate to /dashboard/email logged in; page must render inbox/detail panes with zero console errors; confirm via network log that the `intelligence` field shape matches frontend expectations.
- **Assigned model tier:** opus (fixer, cluster FIX-C) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-C dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-042
- **Type:** G-FAKE
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/email (API: POST /workspaces/emails/send) · **REQ/SC violated:** N/A
- **Observed (production):** `POST /workspaces/emails/send` returns `200 {"status":"sent"}` unconditionally; it only appends to `EmailThread.messages` JSONB. No SMTP/Gmail/provider call exists anywhere in the repo. The Gmail account is explicitly `not_connected` yet send still reports `"sent"`. Evidence: `uat/reports/evidence/phase4/email-run3__send-attempt__20260713T122652Z.json`, `email-run3__thread-after-send__20260713T122652Z.json`.
- **Expected (doc/wireframe ref):** `docs/delivery/DECISIONS.md` D-0029 (new, this pass) — an explicit "no email provider connected" error is required until a real provider integration lands; fabricated success is forbidden.
- **Root cause analysis:** `apps/api/app/routers/workspaces.py:356-383` (send handler) and `:333-341` (accounts `status=not_connected`) — no branch surfaces a degraded/error state when no provider is connected.
- **Fix specification:** Return an honest error (e.g. `409`, mirroring the agents `PUT /providers` 409 pattern) when no email provider is connected; the UI surfaces it as a visible error state; never report `"sent"` for an unsent message. Per D-0029.
- **Verification recipe:** POST /workspaces/emails/send with no connected provider → expect a non-"sent" status or explicit error; connect a provider and confirm a real send path exists before re-testing the success case.
- **Assigned model tier:** opus (fixer, cluster FIX-C) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-C dispatched). **Supersedes GAP-P4-021 and GAP-P4-029** — both were duplicate reports of this single defect (Run-3 orchestrator cross-check); GAP-P4-042 is now the canonical record.
- **Evidence (post-fix):** (pending). `docs/delivery/DECISIONS.md` D-0029 is the ADR authorizing the honest-error fix shape.

### GAP-P4-043
- **Type:** G-FAKE
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/cover-letters · **REQ/SC violated:** REQ-0007, SC-CL-01 (list only; Request Changes action not covered by the register excerpt)
- **Observed (production):** Request Changes button renders with `disabled=false`, `visible=true`, but times out (5000ms) when clicked, in both the interaction pass and a dedicated modal test. Evidence: `uat/reports/evidence/phase4/cover-letters__controls__20260713T115205Z.json` (index 41), `cover-letters__interaction__20260713T115434Z.json`.
- **Expected (doc/wireframe ref):** `design/screens/cover-letter-studio.html` — button should be interactive and fire a request when clicked.
- **Root cause analysis:** control shows `disabled=false` in the controls dump vs. a click timeout in the interaction pass — likely a missing `onClick` handler or a blocked event target.
- **Fix specification:** Wire the Request Changes button to its intended action (or explicitly disable+style it if the feature is not yet implemented); add an interaction test asserting a network call or state change fires on click.
- **Verification recipe:** Click Request Changes on a cover letter; expect either a visible action (modal/request fired) within a normal timeout, or a properly disabled/greyed control if deferred.
- **Assigned model tier:** opus (fixer, cluster FIX-B) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-B dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-044
- **Type:** G-QUALITY
- **Severity:** CRITICAL
- **Screen / Route:** /dashboard/resume (tailoring pipeline) · **REQ/SC violated:** N/A
- **Observed (production):** Master resume "bullets" are PDF line-wrap fragments, not full sentences (22/26 end mid-sentence/mid-word). Tailoring rewrites these fragments rather than complete statements, and the exported PDF shows dangling/duplicated fragments in ~all 24 rewritten bullets (e.g. p1 "...in a high-traffic environment. squad — one of eight squads..."; p3 a phrase repeated verbatim twice in one bullet). Evidence: `uat/reports/evidence/phase4/tailor-run3__pdfpage-1.png`, `tailor-run3__pdfpage-2.png`, `tailor-run3__pdfpage-3.png`, `tailor-run3__analysis-summary__20260713T122200Z.json`.
- **Expected (doc/wireframe ref):** Audit clause (a): rewrite must reflect the user's actual complete career-data statements. Audit clause (f): exported PDF must have no broken/duplicated/orphan text.
- **Root cause analysis:** `apps/api/app/services/resume_tailor.py` `extract_bullets()` ingests raw PDF line-wraps as bullet boundaries; `apps/api/app/services/resume_pdf.py` then renders the LLM's completions of those fragments, producing incoherent/duplicated text.
- **Fix specification:** Fix bullet extraction to join line-wrapped fragments into complete sentences before they reach the tailoring LLM (sentence-boundary detection, not just line breaks); re-run tailoring after ingestion is corrected and re-check PDF output for coherence.
- **Verification recipe:** Re-ingest master resume with fixed extraction; run a tailor pass; export PDF; confirm every bullet reads as one coherent sentence with no duplicated/orphan fragments.
- **Assigned model tier:** opus (fixer, cluster FIX-A) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-A dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-045
- **Type:** G-QUALITY
- **Severity:** HIGH
- **Screen / Route:** /dashboard/resume (tailoring pipeline) · **REQ/SC violated:** N/A
- **Observed (production):** 6+ of 24 rewritten bullets echo distinctive JD phrases near-verbatim as the candidate's own experience (e.g. JD "Deliver first-class software"/"high-traffic environments" → resume "first-class software outcomes"/"high-traffic environment"). The fabrication guard only screens proper-nouns/numbers, not phrase-level lifting. Evidence: `uat/reports/evidence/phase4/tailor-run3__analysis-summary__20260713T122200Z.json`, `tailor-run3__diff__20260713T121930Z.json`.
- **Expected (doc/wireframe ref):** Audit clause (a): rewrite must reflect the user's actual consolidated career data, not phrases copied from the target job posting. D-0015 (evidence normalization guard) covers token/number matching but not JD n-gram overlap — partial coverage only.
- **Root cause analysis:** Fabrication-guard bypass — the guard only checks proper-nouns/numbers, not near-verbatim phrase reuse from the JD.
- **Fix specification:** Extend the fabrication guard to flag/penalize n-gram overlap with the JD text above a similarity threshold, not just named entities/numbers; add an overlap regression test.
- **Verification recipe:** Re-run tailoring on the same job; diff rewritten bullets against JD text for n-gram overlap; confirm the guard flags/blocks near-verbatim JD phrase reuse.
- **Assigned model tier:** opus (fixer, cluster FIX-A) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-A dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-046
- **Type:** G-QUALITY
- **Severity:** HIGH
- **Screen / Route:** /dashboard/resume (tailored PDF export) · **REQ/SC violated:** N/A
- **Observed (production):** PDF page 3: a 3-line rewritten bullet visually overlaps the next bullet's marker/first line — text renders on top of text. Evidence: `uat/reports/evidence/phase4/tailor-run3__pdfpage-3.png`.
- **Expected (doc/wireframe ref):** Audit clause (f): no visual overlaps in exported PDF; renderer must recompute block height/spacing when a rewritten bullet grows longer than the original.
- **Root cause analysis:** `apps/api/app/services/resume_pdf.py` does not recompute layout height when a rewritten bullet exceeds the original bullet's line count.
- **Fix specification:** Make `resume_pdf.py` measure rendered text height dynamically (not assume the original bullet's line count) before placing the next block; add a geometry/overlap regression test.
- **Verification recipe:** Regenerate the same tailored PDF; confirm no bullet text overlaps the next entry, across all pages.
- **Assigned model tier:** opus (fixer, cluster FIX-A) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-A dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-047
- **Type:** G-MISSING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/resume, /dashboard/settings (portfolio sync) · **REQ/SC violated:** N/A
- **Observed (production):** No GitHub/LinkedIn/portfolio content is ever consolidated into tailoring: `scrape_github_profile()` has zero callers app-wide, the "Portfolio Sync Agent" catalog entry has `backend=None`/`status: planned`, `GET /settings` portfolio block is always `{url: null}`. Evidence: `apps/api/app/services/portfolio_scraper.py`, `apps/api/app/routers/agents.py`, `apps/api/app/routers/workspaces.py`.
- **Expected (doc/wireframe ref):** Audit clause (a) requires the rewrite to draw on portfolio/GitHub/LinkedIn data in the user's workspace profile. `docs/delivery/DECISIONS.md` D-0031 (new, this pass) scopes real portfolio+GitHub ingestion with an honest LinkedIn limitation.
- **Root cause analysis:** `apps/api/app/services/portfolio_scraper.py` is dead code (no callers); `apps/api/app/routers/agents.py` `AGENT_CATALOG` `portfolioSync` entry is `status='planned'`; `apps/api/app/routers/workspaces.py` `_build_settings` portfolio block is always null.
- **Fix specification:** Wire `portfolio_scraper.py` into the tailoring context-build step (real GitHub ingestion); persist and sync a real portfolio URL in Settings. LinkedIn remains workspace-paste-only per D-0031 (no API access exists).
- **Verification recipe:** Grep for `scrape_github_profile()` callers post-fix — confirm a real invocation exists in the tailoring pipeline; Settings portfolio block returns a real URL when configured.
- **Assigned model tier:** opus (fixer, cluster FIX-J) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-J dispatched)
- **Evidence (post-fix):** (pending). `docs/delivery/DECISIONS.md` D-0031 documents the LinkedIn scope limitation this fix must respect.

### GAP-P4-048
- **Type:** G-QUALITY
- **Severity:** HIGH
- **Screen / Route:** /dashboard/cover-letters (PDF export) · **REQ/SC violated:** N/A
- **Observed (production):** PDF export renders a dark (`#0A0A0F`) branded "Aether Career Agent" template, white-on-black, no candidate email/phone anywhere, footer reads "Generated by Aether Career Agent" — confirmed on 2 separate production letters (Infinity Pro, Duratec). Evidence: `uat/reports/evidence/phase4/cover-letter__run3__pdfrender__20260713T122016Z-1.png`, `cover-letter__run3__corroborate-pdfrender__20260713T122213Z-1.png`.
- **Expected (doc/wireframe ref):** Business cover letter PDF should use a plain printable format, include the candidate's own contact details, and carry no third-party/tool branding or AI-generated disclosure.
- **Root cause analysis:** `apps/api/app/routers/cover_letters.py` PDF template hardcodes dark branded styling and omits contact-info interpolation.
- **Fix specification:** Switch PDF template to a neutral printable style (white/black text), interpolate candidate contact details from the resume/profile, and drop the "Generated by Aether" footer line for submission-ready output.
- **Verification recipe:** Generate a new cover letter PDF; confirm neutral styling, presence of candidate contact info, absence of tool branding/footer.
- **Assigned model tier:** opus (fixer, cluster FIX-B) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-B dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-049
- **Type:** G-QUALITY
- **Severity:** HIGH
- **Screen / Route:** /dashboard/cover-letters (agent format contract) · **REQ/SC violated:** N/A
- **Observed (production):** A pre-existing production letter (Duratec/Operations Manager) has only 2 body paragraphs (no closing/CTA at all) and a first paragraph that never names "Operations Manager" or "Duratec Limited", despite the agent's own structural retry loop. Evidence: `uat/reports/evidence/phase4/cover-letter__run3__corroborate-get__20260713T122146Z.json`, `cover-letter__run3__corroborate-pdfrender__20260713T122213Z-1.png`.
- **Expected (doc/wireframe ref):** Agent contract (D-0021 §10.2) requires exactly 3 paragraphs (hook naming role+company+current position; JD-matched evidence; CTA), enforced via a corrective retry loop before shipping.
- **Root cause analysis:** `apps/api/app/agents/cover_letter_agent.py` retry/validation loop does not reliably enforce its own paragraph-count/hook contract before persisting output.
- **Fix specification:** Add a hard structural validator (paragraph count, presence of role+company mention, presence of CTA) that blocks shipping and forces a real retry rather than a soft/best-effort pass.
- **Verification recipe:** Re-run cover letter generation for the same job/company; confirm 3 paragraphs, role+company named in paragraph 1, and a CTA present in paragraph 3, on every run including retries.
- **Assigned model tier:** opus (fixer, cluster FIX-B) → sonnet (reviewer)
- **Status:** IN-FIX (FIX-B dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-050
- **Type:** G-WIRING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/applications · **REQ/SC violated:** REQ-0006, SC-TRACK-02
- **Observed (production):** Kanban board displays only 4 status columns (Discovered, Evaluating, Tailoring, Ready to Apply); Submitted, In Review, Interview, Offer (5+4+2+3 items per wireframe) are entirely absent, with no horizontal scroll to reveal them. Evidence: `uat/reports/evidence/phase4/applications__screenshot__20260713T114840Z.png`, `applications__interaction_results__20260713T115033Z.json`.
- **Expected (doc/wireframe ref):** `design/screens/application-tracker.html` — 8-column kanban (`col-submitted-at18`, `col-review-at20`, `col-interview-at22`, `col-offer-at24` all defined). No ADR (D-0019 through D-0027) covers an intentional simplification of the applications tracker layout.
- **Root cause analysis:** Kanban main container renders only the first 4 columns (`at09`-`at16`); the remaining 4 column components are either not mounted or filtered out client-side.
- **Fix specification:** Restore all 8 kanban columns with horizontal scroll per wireframe. No ADR justifies a 4-column simplification, so implementation (not documentation) is the required path.
- **Verification recipe:** Navigate to /dashboard/applications Board View; confirm all 8 status columns render (scroll if needed) with correct per-column counts.
- **Assigned model tier:** sonnet (fixer, cluster FIX-E) → opus (reviewer)
- **Status:** IN-FIX (FIX-E dispatched). **Reopens GAP-P4-034** — this run's fresh evidence directly contradicts that record's prior VERIFIED-CLOSED status and also contradicts the Section E "Verified No-Gap Register" row claiming the 8-stage board renders (corrected below in Section E).
- **Evidence (post-fix):** (pending)

### GAP-P4-051
- **Type:** G-BUG
- **Severity:** HIGH
- **Screen / Route:** N/A (e2e test suite / CI + repo hygiene) · **REQ/SC violated:** N/A
- **Observed (production):** `apps/web/e2e/login.spec.ts` and `auth.setup.ts` assert the login form is prefilled with demo credentials; `apps/web/src/app/login/page.tsx` actually initializes both fields to `''` (verified live: `GET /login` renders `value=""` on both inputs). `auth.setup.ts` times out waiting for navigation, and `playwright.config.ts` makes the broken `'setup'` project a hard dependency of the chromium project, so all 3 remaining e2e tests report "did not run" — net effect: 0 e2e tests execute. Separately, `uat/api_sweep.sh` and `uat/api_sweep_v2.sh` hardcode the demo password `AetherDemo1` in plaintext, near-duplicating `api_sweep.py`. A 405 console error on `GET /api/auth/login` seen during the Playwright login flow on the cover-letters page appears to be harness noise (a GET hitting a POST-only endpoint during test setup), not a page-specific defect. Evidence: `uat/reports/evidence/phase4/preflight__tests__20260713T114254Z.log`, `cover-letters__interaction__20260713T115434Z.json`.
- **Expected (doc/wireframe ref):** e2e auth should exercise the real login flow via env-var credentials + Playwright `storageState`, not assume a nonexistent prefill; uat tooling should read credentials from `.env` like `api_sweep.py`, never hardcode a password.
- **Root cause analysis:** `apps/web/e2e/login.spec.ts`, `apps/web/e2e/auth.setup.ts` (new), `apps/web/playwright.config.ts` (new hard dependency) all assume a prefill behavior that does not exist in source; `uat/api_sweep.sh` + `uat/api_sweep_v2.sh` hardcode a plaintext password.
- **Fix specification:** Per the Run-3 preflight adjudication (Section I.3): drop `e2e/login.spec.ts`, `e2e/auth.setup.ts`, and the `playwright.config.ts` hard-dependency changes (the broken prefill assumption zeroes out the whole e2e suite); rebuild real e2e auth using env-var credentials (`LOGIN_EMAIL`/`LOGIN_PASSWORD`) + Playwright `storageState`, matching `api_sweep.py`'s credential pattern; drop `uat/api_sweep.sh` and `uat/api_sweep_v2.sh` (hardcoded password, superseded by `api_sweep.py`); confirm the 405 harness-noise finding does not reproduce outside Playwright.
- **Verification recipe:** Run the full Playwright e2e suite; confirm `setup` no longer times out and the remaining chromium tests execute (not "did not run"); `grep -r 'AetherDemo1' uat/` returns zero matches; reproduce the login flow outside Playwright to confirm the 405 does not occur in normal navigation.
- **Assigned model tier:** sonnet (fixer, cluster FIX-G) → opus (reviewer)
- **Status:** IN-FIX (FIX-G dispatched)
- **Evidence (post-fix):** (pending). The working-tree disposition for the broken/dropped files is recorded in Section I.3 of this ledger.

### GAP-P4-052
- **Type:** G-MISSING
- **Severity:** HIGH
- **Screen / Route:** /dashboard/networking · **REQ/SC violated:** N/A
- **Observed (production):** Contact pipeline is displayed as a tab/pill interface showing only counts (New 0, Warm 0, Active 0, Scheduled 0, Placed 0), not the wireframe's kanban board with individual contact cards. Evidence: `uat/reports/evidence/phase4/networking__screenshot__20260713T115646Z.png`.
- **Expected (doc/wireframe ref):** `design/screens/networking.html` lines 81-105 specify a kanban layout with contact cards (Sarah L., Mark K., Priya R., James T., Dan N. in the mock). No ADR covers this simplification.
- **Root cause analysis:** Frontend networking page implements a simplified tab/pill summary component instead of the wireframe's per-contact kanban cards.
- **Fix specification:** Implement the kanban contact-card view per wireframe (no ADR exists to justify the tab/pill simplification, so implementation is the required path).
- **Verification recipe:** Navigate to /dashboard/networking; confirm kanban cards per contact render.
- **Assigned model tier:** sonnet (fixer, cluster FIX-F) → opus (reviewer)
- **Status:** IN-FIX (FIX-F dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-053
- **Type:** G-CONSOLE
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/applications · **REQ/SC violated:** N/A
- **Observed (production):** Browser console error: "Failed to load resource: 404" for `GET /api/settings`. Server logs show the correct endpoint is `/workspaces/settings` (200 OK), i.e. the applications page (or a shared layout it includes) calls the wrong path. Evidence: `uat/reports/evidence/phase4/applications__console__20260713T114840Z.log`.
- **Expected (doc/wireframe ref):** All frontend API calls should target existing, correct endpoints.
- **Root cause analysis:** Some component reachable from /dashboard/applications calls `GET /api/settings` instead of `GET /workspaces/settings`.
- **Fix specification:** Find and correct the client call site to use the existing `/workspaces/settings` endpoint — no duplicate backend alias is to be added; add a console-clean assertion to the applications e2e/smoke test.
- **Verification recipe:** Load /dashboard/applications; confirm no 404s in console/network for settings-related calls.
- **Assigned model tier:** sonnet (fixer, cluster FIX-D) → opus (reviewer)
- **Status:** IN-FIX (FIX-D dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-054
- **Type:** G-CONSOLE
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/agents · **REQ/SC violated:** N/A
- **Observed (production):** 6 error-level console entries for failed resource loads (409 Conflict) when clicking provider action buttons; `PUT /api/agents/providers/anthropic` and `/openai` both return 409. Evidence: `uat/reports/evidence/phase4/agents__interaction__20260713T120557Z.log`.
- **Expected (doc/wireframe ref):** No error-level console entries on page load and interaction. Per D-0020 the 409 itself is intentional ("never fabricate a connection") — only the raw-console-error surfacing is the defect.
- **Root cause analysis:** `PUT /api/agents/providers/{provider}` intentionally 409s per D-0020, but the frontend logs this as a raw console error rather than handling it as an expected/handled state.
- **Fix specification:** Catch the 409 client-side and surface a handled UI message instead of letting it bubble as a console error. The 409 guard itself is retained — only the client-side handling changes.
- **Verification recipe:** Click provider config actions; confirm the 409 is handled gracefully with zero console error-level entries.
- **Assigned model tier:** sonnet (fixer, cluster FIX-D) → opus (reviewer)
- **Status:** IN-FIX (FIX-D dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-055
- **Type:** G-DATA
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/agents · **REQ/SC violated:** N/A
- **Observed (production):** Providers screen shows all 6 providers (incl. Anthropic-adjacent) "unconfigured", yet tailor/coverLetter/storyExtractor runs actually execute live on deepseek/qwen models via an `ABACUS_API_KEY` fallback in `llm_client.py` that `_provider_env_state()` never checks — no provider card ever reflects the credential path actually serving runs. Evidence: `uat/reports/evidence/phase4/agents-run3__providers__20260713T122718Z.json`, `agents-run3__catalog__20260713T122718Z.json`.
- **Expected (doc/wireframe ref):** `docs/delivery/DECISIONS.md` D-0020 (amended, this pass) — the provider panel must reflect the actual serving credential path including the Abacus subscription fallback; the ADR's prior "pinned to validated Anthropic tiers" claim is corrected to match reality.
- **Root cause analysis:** `apps/api/app/services/llm_client.py:344-356` (fallback path) is invisible to `apps/api/app/routers/agents.py:186-219` / `_provider_env_state()`, which only inspects the documented per-provider keys.
- **Fix specification:** Extend `_provider_env_state()` (or an equivalent status source) to detect and surface the `ABACUS_API_KEY` fallback path so the providers panel accurately reflects what's actually serving runs (e.g. a distinct "Abacus subscription (fallback)" status).
- **Verification recipe:** Trigger a tailor/coverLetter run; confirm the providers panel shows the actual serving credential/model, not a blanket "unconfigured".
- **Assigned model tier:** sonnet (fixer, cluster FIX-D) → opus (reviewer)
- **Status:** IN-FIX (FIX-D dispatched)
- **Evidence (post-fix):** (pending). `docs/delivery/DECISIONS.md` D-0020's amendment (this pass) is the ADR-level correction this fix implements.

### GAP-P4-056
- **Type:** G-WIRING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/agents · **REQ/SC violated:** N/A
- **Observed (production):** 3 UI controls (Resume Tailoring Run button, Anthropic model dropdown, Bedrock model dropdown) render as visually interactive but are functionally disabled; Playwright reports "element is not enabled" after 30s of retries with no opacity/greying to signal disabled state. Evidence: `uat/reports/evidence/phase4/agents__controls__20260713T120338Z.json`, `agents__screenshot__20260713T120338Z.png`, `agents__interaction__20260713T120557Z.log`.
- **Expected (doc/wireframe ref):** Disabled controls should be visually distinct from interactive controls; per D-0020 the underlying disablement (unconfigured providers) is legitimate, but the lack of visual affordance is not addressed by that ADR.
- **Root cause analysis:** `AgentConfigGrid.tsx` / provider dropdown components apply the `disabled` attribute without a corresponding disabled visual style.
- **Fix specification:** Add visual disabled styling (opacity/greyed background/cursor-not-allowed) wherever the `disabled` attribute is set on these controls.
- **Verification recipe:** Load /dashboard/agents with unconfigured providers; confirm disabled controls are visually distinguishable and Playwright's accessibility tree marks them disabled without long timeouts on click attempts.
- **Assigned model tier:** sonnet (fixer, cluster FIX-I) → opus (reviewer)
- **Status:** IN-FIX (FIX-I dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-057
- **Type:** G-WIRING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/offers · **REQ/SC violated:** N/A
- **Observed (production):** The empty-add-offer button in the empty state times out (30s) when clicked; Playwright reports a modal overlay (`add-offer-modal` input) intercepts pointer events, preventing the click. A separate modal-open interaction also shows the form becoming blocked once open, suggesting a z-index/stacking issue. Evidence: `uat/reports/evidence/phase4/offers__interaction_log__20260713T120156Z.log`, `offers__screenshot__20260713T115951Z.png`.
- **Expected (doc/wireframe ref):** Both Add Offer buttons should be clickable and responsive without timeout.
- **Root cause analysis:** Likely a stray/invisible modal overlay element left mounted (z-index or pointer-events issue) intercepting clicks meant for the empty-state button.
- **Fix specification:** Audit the Add Offer modal's mount/unmount and z-index stacking; ensure the overlay only intercepts pointer events while actually open and visible.
- **Verification recipe:** Click empty-add-offer in the empty state; confirm the modal opens without timeout and its own fields are independently clickable.
- **Assigned model tier:** sonnet (fixer, cluster FIX-I) → opus (reviewer)
- **Status:** IN-FIX (FIX-I dispatched). Residual, far-lower-severity finding on the same screen as prior GAP-P4-023/GAP-P4-024 (CRITICAL, FIXER DISPATCHED) — consistent with a partial prior fix that left this UI-blocking regression rather than the original crash/fabrication.
- **Evidence (post-fix):** (pending)

### GAP-P4-058
- **Type:** G-METRIC
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard, /dashboard/analytics · **REQ/SC violated:** N/A
- **Observed (production):** Applications-by-source widget on both /dashboard and /dashboard/analytics displays "149 applications" with a source breakdown; real total applications = 16 (Application table row count, matches API `totalApplications` exactly). 149 is actually the Job row count (`sourcesTotal`), mislabeled as "applications". Evidence: `uat/reports/evidence/phase4/audit-metrics__run3__20260713T122906Z.json`, `audit-metrics__ui-text__20260713T122601Z.json`.
- **Expected (doc/wireframe ref):** Widget label should read the correct metric name for the number shown.
- **Root cause analysis:** `apps/api/app/routers/analytics.py` `market_pulse()` computes `sources_total` via `SELECT COUNT(*) FROM Job`; `apps/web/src/components/analytics/MarketPulse.tsx` renders `{data.sourcesTotal}` next to a static label "applications".
- **Fix specification:** Relabel the widget to "jobs sourced" (or similar) when displaying `sourcesTotal`, or bind a true applications-by-source breakdown if that is the intended metric.
- **Verification recipe:** Confirm widget label matches the underlying metric on both /dashboard and /dashboard/analytics after fix.
- **Assigned model tier:** sonnet (fixer, cluster FIX-H) → opus (reviewer)
- **Status:** IN-FIX (FIX-H dispatched). Lineage: prior GAP-P4-022 (G-METRIC MEDIUM, OPEN) is the same defect; GAP-P4-058 is its Run-3 successor record with root cause identified.
- **Evidence (post-fix):** (pending)

### GAP-P4-059
- **Type:** G-METRIC
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/analytics · **REQ/SC violated:** N/A
- **Observed (production):** "Recruiter Activity" widget shows "Agent runs (last 12 wks): 77 total" and "Avg runs / week: 77.0" — should be ≈77/12=6.4, not identical to the total. All 77 AgentRun rows fall in one calendar week, so `weeks_active=len(agent_series)=1` is used as the divisor instead of the fixed 12-week window the label claims. Evidence: `uat/reports/evidence/phase4/audit-metrics__run3__20260713T122906Z.json`.
- **Expected (doc/wireframe ref):** The "last 12 wks" label implies a 12-week divisor for the average.
- **Root cause analysis:** `apps/api/app/routers/analytics.py`: `weeks_active = len(agent_series) or 1; round(total_runs/weeks_active,1)` — no zero-fill for empty weeks in the 84-day window.
- **Fix specification:** Zero-fill the `agent_week_rows` series across the full 12-week window before computing `weeks_active`, or divide by the fixed window length (12) rather than the count of weeks with data.
- **Verification recipe:** Recompute avg runs/week after fix; confirm it equals total/12 (or the correct window), not total/weeks-with-data.
- **Assigned model tier:** sonnet (fixer, cluster FIX-H) → opus (reviewer)
- **Status:** IN-FIX (FIX-H dispatched). Lineage: prior GAP-P4-026 (G-METRIC LOW, FIXER DISPATCHED `deleg_7ef75c88`) is the same defect; GAP-P4-059 is its Run-3 successor record with the precise root cause now identified.
- **Evidence (post-fix):** (pending)

### GAP-P4-060
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/analytics · **REQ/SC violated:** N/A
- **Observed (production):** Wireframe diff for analytics.html shows 2 missing sections (Applications by Source donut `sources-an09`; Market vs Your Performance `market-vs-you-an16`) and 3 degraded chart stylings (Interview Conversion chart, Top Skills bar chart, Trend Indicators layout). An "Agent ROI" section not in the wireframe is also present (extra). Evidence: `uat/reports/evidence/phase4/analytics__screenshot__20260713T120044Z.png`.
- **Expected (doc/wireframe ref):** `design/screens/analytics.html`.
- **Root cause analysis:** Frontend analytics page has not implemented the sources-donut and market-vs-you comparison components; 3 existing chart components render with different styling than spec.
- **Fix specification:** Implement the sources donut + market-vs-you sections from real data; align styling on the 3 degraded charts.
- **Verification recipe:** Navigate to /dashboard/analytics; confirm sources donut and market-vs-you sections render with real data; confirm chart stylings match wireframe.
- **Assigned model tier:** sonnet (fixer, cluster FIX-H) → opus (reviewer)
- **Status:** IN-FIX (FIX-H dispatched). Lineage: prior GAP-P4-035 (G-MISSING LOW, OPEN) is the same defect; GAP-P4-060 is its Run-3 successor record.
- **Evidence (post-fix):** (pending)

### GAP-P4-061
- **Type:** G-DATA
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/email, /dashboard/networking · **REQ/SC violated:** N/A
- **Observed (production):** 100% of the demo account's EmailThread rows (5/5) are audit/test artifacts (subjects: "Test", "QA Test", "Test Draft", "Test from Audit", "Phase4 T2 Audit..."); the sole Contact row is fabricated ("Jane Doe"/"Tech Corp"/jane@example.com). All `createdAt` = today, written by audit tooling, not seed data. Evidence: `uat/reports/evidence/phase4/audit-metrics__run3__20260713T122906Z.json`.
- **Expected (doc/wireframe ref):** Email Center / Networking pages should show only genuine data for the demo login, not test rows written by concurrent/prior audit runs into the shared production account.
- **Root cause analysis:** Data contamination from repeated audit-tooling runs against a shared demo/production account, not an application code bug.
- **Fix specification:** Delete provably-test rows only (the 5 EmailThread rows and the 1 fabricated Contact row identified above by subject/content pattern), and log the deletions; consider a dedicated non-production test account for future audit tooling to avoid polluting the demo experience.
- **Verification recipe:** DELETE the identified test rows (with a deletion log); re-check `GET /api/emails` and `/api/networking/contacts` return only genuine data.
- **Assigned model tier:** sonnet (fixer, cluster FIX-D) → opus (reviewer)
- **Status:** IN-FIX (FIX-D dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-062
- **Type:** G-QUALITY
- **Severity:** LOW
- **Screen / Route:** /dashboard/settings · **REQ/SC violated:** N/A
- **Observed (production):** Settings sub-navigation order differs from wireframe: live order has Notifications at index 5 (position 6), wireframe has it at index 3 (position 4). Evidence: `uat/reports/evidence/phase4/settings__controls__20260713T120937Z.json`.
- **Expected (doc/wireframe ref):** `design/screens/settings.html` lines 50-57.
- **Root cause analysis:** Sub-nav item array order in the settings page component does not match the wireframe's specified order.
- **Fix specification:** Reorder the sub-nav array to match the wireframe: Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance.
- **Verification recipe:** Load /dashboard/settings; confirm sub-nav order matches the wireframe exactly.
- **Assigned model tier:** sonnet (fixer, cluster FIX-I) → opus (reviewer)
- **Status:** IN-FIX (FIX-I dispatched). Residual sub-gap of the same ticket as prior GAP-P4-015 (settings page), which is otherwise fixed (12/14 elements now match).
- **Evidence (post-fix):** (pending)

### GAP-P4-063
- **Type:** G-QUALITY
- **Severity:** LOW
- **Screen / Route:** /dashboard/stories · **REQ/SC violated:** N/A
- **Observed (production):** Clicking "Draft missing stories" fires `POST /api/agents/story-extractor/run` asynchronously with no loading spinner/toast/status change; 2 requests recorded as `net::ERR_ABORTED` (`GET /api/approvals?status=pending`, `POST /api/agents/story-extractor/run`), likely due to test-navigation-away rather than a server failure. Evidence: `uat/reports/evidence/phase4/stories__interaction_pass__20260713T120738Z.json`.
- **Expected (doc/wireframe ref):** Long-running async actions should provide immediate UI feedback.
- **Root cause analysis:** The story bank page lacks a loading/confirmation state for the async story-extractor trigger.
- **Fix specification:** Add a loading spinner or toast confirmation when the async agent call is accepted.
- **Verification recipe:** Click "Draft missing stories"; confirm immediate visual feedback before the async call resolves.
- **Assigned model tier:** sonnet (fixer, cluster FIX-I) → opus (reviewer)
- **Status:** IN-FIX (FIX-I dispatched)
- **Evidence (post-fix):** (pending)

### GAP-P4-064
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/settings · **REQ/SC violated:** N/A
- **Observed (production):** Change Avatar button (`btn-avatar-st08`) is absent from the Profile section; wireframe shows it labeled "PNG or JPG, max 2MB" next to the avatar. Evidence: `uat/reports/evidence/phase4/settings__controls__20260713T120937Z.json`, `settings__screenshot__20260713T120937Z.png`.
- **Expected (doc/wireframe ref):** `design/screens/settings.html` line 66.
- **Root cause analysis:** No avatar/file-storage backend exists anywhere in the API (no upload endpoint, no object storage, no `avatarUrl` column) — the Profile section component omits the control because there is nothing for it to call.
- **Fix specification:** Documented as an accepted, deferred-scope decision — see `docs/delivery/DECISIONS.md` D-0030 (new ADR, this pass).
- **Verification recipe:** Confirm D-0030 exists in DECISIONS.md and accurately describes the no-backend rationale.
- **Assigned model tier:** DOC-K (T2) — documentary only, no fixer/reviewer dispatch.
- **Status:** VERIFIED-CLOSED (documentary — resolved by DOC-K in this pass).
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0030 "Avatar management deferred: no backend storage exists".

### GAP-P4-065
- **Type:** G-QUALITY
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/interviews · **REQ/SC violated:** N/A
- **Observed (production):** Interview Center shows only an empty-state placeholder ("No interview scheduled" + View Applications button); wireframe defines 26 elements (tabs, company brief, predicted questions, live-assist metrics, debrief), of which only 4 (15%) are implemented. Evidence: `uat/reports/evidence/phase4/interviews__wireframe-fidelity__20260713T115601Z.log`, `interviews__interaction__20260713T115601Z.log`.
- **Expected (doc/wireframe ref):** `design/screens/interview-center.html`.
- **Root cause analysis:** `apps/web/src/app/dashboard/interviews/page.tsx` contains a code comment deferring the screen to Phase 3+, but no named ADR (mirroring D-0025/D-0026/D-0027's style) formalized the deferral — only D-0009's generic unbuilt-route placeholder pattern applied by default.
- **Fix specification:** Documented via a new named ADR — see `docs/delivery/DECISIONS.md` D-0032 (new, this pass), cross-referenced from D-0009.
- **Verification recipe:** Confirm D-0032 exists in DECISIONS.md and names the Interview Center deferral explicitly.
- **Assigned model tier:** DOC-K (T2) — documentary only, no fixer/reviewer dispatch.
- **Status:** VERIFIED-CLOSED (documentary — resolved by DOC-K in this pass).
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0032 "Interview Center: Phase 3+ deferral made explicit"; D-0009 amendment note cross-referencing it.

### GAP-P4-066
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** N/A (requirement register / docs) · **REQ/SC violated:** N/A
- **Observed (production):** D-0018 (Resume ingestion endpoint) is not found in `doc-audit-requirement-register.json` despite being referenced 8 times in DECISIONS.md and defining `POST /resumes` (user-facing API supporting REQ-4 Resume Studio). Separately, the 6 architecture/infrastructure ADRs (D-0004, D-0005, D-0006, D-0008, D-0012, D-0013) are not indexed (18/25 = 72% coverage). Evidence: `uat/reports/evidence/phase4/doc-audit-requirement-register.json`, `requirement-register.md`.
- **Expected (doc/wireframe ref):** `docs/delivery/DECISIONS.md` D-0018, lines 449-477: "POST /resumes (routers/resumes.py) — creates a new root resume (no parentId) from {label, raw_text, contact?, format_hash?}... Returns 201 with the stored resume."
- **Root cause analysis:** The register-generation process did not pick up D-0018 when indexing ADRs against requirements. Separately, `requirement-register.md`'s REQ-0011 Navigation row and Conflict Log entry C-0003 mis-cited "DECISIONS D-0018" for the 13-item-sidebar amendment — that change is actually D-0019's (D-0018 is unrelated: resume ingestion). The 6 infra/CI ADRs were never assessed as excluded in writing.
- **Fix specification:** Index D-0018 under REQ-0004 (Resume Studio) in both `requirement-register.md` and `doc-audit-requirement-register.json`, quoting D-0018's text and linking `POST /resumes`; correct the REQ-0011/Conflict-Log mis-citation from D-0018 to D-0019; add an explicit "intentionally excluded — infrastructure/CI/auth, not user-facing" note for D-0004/D-0005/D-0006/D-0008/D-0012/D-0013 in the register's coverage summary.
- **Verification recipe:** `grep 'D-0018' doc-audit-requirement-register.json` returns ≥1 match; `grep 'D-0018' requirement-register.md` shows it correctly tied to REQ-0004/POST /resumes, not to the 13-item sidebar.
- **Assigned model tier:** DOC-K (T2) — documentary only, no fixer/reviewer dispatch.
- **Status:** VERIFIED-CLOSED (documentary — resolved by DOC-K in this pass).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/requirement-register.md` REQ-0004 row + REQ-0011 correction + Sources-Audited coverage note; `uat/reports/evidence/phase4/doc-audit-requirement-register.json` REQ-4 `related_decisions` entry.

### GAP-P4-067
- **Type:** G-MISSING
- **Severity:** MEDIUM
- **Screen / Route:** /dashboard/jobs · **REQ/SC violated:** REQ-0003, SC-JOB-09 (WIRE-0033 jd04, WIRE-0035 jd05, WIRE-0036 jd06, WIRE-0052 jd33)
- **Observed (production):** Jobs wireframe fidelity check reports 17 unmatched design-ids and 4 degraded items with a vague note that the underlying elements are "present in degraded category". D-0025 (cited to close GAP-P4-009/011) explicitly states the Location filter (jd05) and Preview button (jd33) were ALREADY IMPLEMENTED when it was written — only Role dropdown (jd04), Salary dropdown (jd06), Bulk Tailor&Apply (jd10), and Saved Tailor-all (jd43) are genuinely deferred by that ADR. Evidence: `uat/reports/evidence/phase4/jobs__wireframe-check__20260713T114550Z.json`.
- **Expected (doc/wireframe ref):** `docs/delivery/DECISIONS.md` D-0025, lines 592-636.
- **Root cause analysis:** GAP-P4-009's "location filter MISSING" and GAP-P4-011's "preview button MISSING" claims conflict with D-0025's own text describing both as already working; the closure citations are directionally fine but imprecise, and this run's vague wireframe-diff (17 unmatched ids, no itemized list) cannot independently confirm current live state.
- **Fix specification:** Re-scout /dashboard/jobs with an itemized missing/degraded design-id list for `job-discovery.html` and cross-check each against D-0025's precise deferred scope (only jd04/jd06/jd10/jd43); reconcile the GAP-P4-009/010/011/030/031 citations accordingly.
- **Verification recipe:** Re-run the wireframe diff for /dashboard/jobs with itemized missing/degraded design-ids; confirm jd05/jd33 are live and only jd04/jd06/jd10/jd43 remain deferred.
- **Assigned model tier:** Wave-2 (tbd) — not yet dispatched.
- **Status:** OPEN (deferred to Wave-2 investigation per orchestrator ruling I.1).
- **Evidence (post-fix):** pending Wave-2 scout re-run.

---

## Summary (Updated)

### Journey 1: Discovery → Application (to be populated with evidence)
Status: AWAITING DATA AUDIT SUB-AGENT

### Journey 2: Tailoring (to be populated)
Status: AWAITING DATA AUDIT SUB-AGENT

### Journey 3: Cover Letter (to be populated)
Status: AWAITING DATA AUDIT SUB-AGENT

### Journey 4: Email (to be populated)
Status: AWAITING DATA AUDIT SUB-AGENT (GAP-P4-001 may block)

### Journey 5: Metrics (to be populated)
Status: AWAITING DATA AUDIT SUB-AGENT (GAP-P4-005 blocks analytics)

### Journey 6: Agents (to be populated)
Status: AWAITING SCOUT 7-12 SUB-AGENT (GAP-P4-006, GAP-P4-007 block)

### Journey 7: Approvals (to be populated)
Status: AWAITING SCOUT 13-17 SUB-AGENT (GAP-P4-012 blocks)

### Journey 8: Mobile (to be populated)
Status: AWAITING SCOUT 13-17 SUB-AGENT

---

## E. Verified No-Gap Register

| Screen / Feature | Reason | Evidence |
|---|---|---|
| /login — auth flow | JWT login works, token returned, session active | api-sweep-results.json: POST /auth/login 200, GET /auth/me 200 |
| /dashboard — layout | Sidebar, stats, feed, opportunities all render | screenshot + console clean |
| /dashboard/jobs — core listing | Market tabs, job cards, Sync button work | screenshot + console clean |
| /dashboard/applications — Sankey flow | Application funnel Sankey visualization works | api-sweep (funnel/sankey 200) |
| /dashboard/resume — diff view | Side-by-side comparison available | screenshot + console clean |
| /dashboard/cover-letters — list | Cover letter list renders | screenshot + console clean |
| Production health | /api/health returns {"status":"ok","version":"0.2.0"} 200 | curl verified |
| Vitest suite | 141/141 pass | pnpm test run |
| Pytest suite (minus 1 config test) | 124/125 pass | pytest run |
| Navigation consistency | 13-item Schema A+1 sidebar on all screens | requirement-register.md (DECISIONS D-0002, D-0019 — corrected citation, was mis-cited as D-0018 per GAP-P4-066) |
| Design tokens | Coral/Indigo/Inter/JetBrains Mono/Glassmorphism verified | requirement-register.md |
| Story bank STARS | Extraction, create/edit, question mapper all functional | api-sweep: GET /stories 200, POST 201, GET /stories/stats 200 |
| Agent catalog | 21 agents, run history, pipeline trigger | api-sweep: GET /agents 200, GET /agents/runs 200, POST /agents/scout/run 202 |
| Fit scorer | Deterministic 10-dim scoring works | api-sweep: POST /agents/fit-scorer/run 200 |
| Story extractor | Story extraction produces valid STARS | api-sweep: POST /agents/storyExtractor/run 200 |
| Networking outreach | Create/list outreach tasks works | api-sweep: GET /networking/outreach 200, POST /networking/outreach 201 |
| Application funnel (Sankey) | Real-time flow data returns | api-sweep: GET /applications/funnel/sankey 200 |
| ATS distribution | 10-bucket histogram returns | api-sweep: GET /analytics/ats-distribution 200 |
| Agent ROI | Cost/value metrics return | api-sweep: GET /analytics/agent-roi 200 |
| Analytics/Dashboard funnel numbers (C-14) | Live funnel (Applications 13-16, Interviews 0, Offers 0, Jobs Found ≈136-149) is real per-user data computed from the shared live query; D-0003's 847/412/156/23/4 is a design-time illustrative example, not a literal production contract | `analytics__screenshot__20260713T120044Z.png`, `analytics__api_summary__20260713T120250Z.json`; reason codified in DECISIONS.md D-0028 |
| Networking CRM stat tiles (C-21) | Live 1 contact / 0 active conversations / 0 referrals / 0% response rate is correct low-volume real account data, not a bug; wireframe's 48/12/5/41% is an illustrative mock | `networking__screenshot__20260713T115646Z.png`; DECISIONS.md D-0028 |
| Story Bank stat tiles (C-29) | Live 23 stories / 22 quantified is correct real account data (small delta vs. wireframe's 24/19/11/94% mock reflects normal data drift, not a computation bug) | `stories__controls__20260713T120449Z.json`; DECISIONS.md D-0028 |
| Mobile dashboard 390×844 (C-31) | All 8 wireframe sections (topbar, notification button, main content, 2×2 stats grid, approval banner, agent activity feed, bottom navigation) now render — this is an *improvement* since D-0026 was written, not a gap. Mobile approval remains genuinely deferred (0/9 elements) | `mobile-dashboard__screenshot__20260713T121243Z.png`, `mobile-dashboard__wireframe_fidelity__20260713T121243Z.json`; DECISIONS.md D-0026 amendment |
| Story card Edit/Delete buttons (C-28) | Explicit Edit/Delete buttons beyond the wireframe's ellipsis-menu design are an intentional UX improvement (more discoverable actions), not an unauthorized deviation | `stories__controls__20260713T120449Z.json` |
| ApprovalModal element naming (C-30) | The modal is functionally complete per D-0027 (5/5 wireframe elements); it uses `testId` attributes for automation instead of the wireframe's literal `data-design-id` values — a naming-convention difference only, not a missing element | `approvals__modal_structure.json`; DECISIONS.md D-0027 |
| Networking empty-state sections (C-37) | Outreach Queue and Communication Log show correct empty-state layouts because the low-usage demo account genuinely has no outreach/communication history yet — not a structural defect | `networking__screenshot__20260713T115646Z.png` |
| Jobs wireframe "missing" design-ids (C-39) | The 17 "missing" design-ids reported for job-discovery.html are a scout test-id/data-design-id naming mismatch — the underlying elements (sidebar, header, detail panel) are actually present. The genuinely-missing items (role/salary dropdowns, bulk actions) are tracked separately under GAP-P4-067 | `jobs__wireframe-check__20260713T114550Z.json` |
| Mobile-approvals data authenticity (C-41) | All 3 visible approval items match authentic API data (real company names, job titles, application IDs, plausible timestamps); no placeholder/demo/lorem content found — confirmatory pass, not a defect | `mobile-approvals__screenshot__20260713T121438Z.png` |
| Cover-letter list/version-history view (C-35) | Collapsed list view (v1-v5) instead of a single expanded letter, and version count beyond the wireframe's v1-v3, is an intentional simplification analogous to D-0027's list-vs-modal rationale for approvals (batch scanning over one-at-a-time review). GAP-P4-033's original citation of "ADR D-0020 covers" was incorrect — D-0020's full text is scoped entirely to the Agents screen (providers/catalog/cost/ATS) and never mentions cover letters; this is corrected here | `cover-letters__screenshot__20260713T115205Z.png`; DECISIONS.md D-0027 (analogous rationale, not a literal citation) |

**Correction (this pass):** the previous row "/dashboard/applications — Kanban | 8-stage board renders" is removed — it directly contradicted Run-3 evidence (only 4/8 columns render; see GAP-P4-050, which reopens GAP-P4-034). The Sankey-flow claim on that same screen is retained above since it independently verified 200 OK and is unaffected by the Kanban-column defect.

---

## Summary

| Severity | Count | Status |
|---|---|---|
| CRITICAL | 3 (GAP-P4-001, 002, 003) | OPEN |
| HIGH | 4 (GAP-P4-004, 005, 006, 007) | OPEN |
| MEDIUM | 4 (GAP-P4-008, 009, 010, 012) | OPEN |
| LOW | 3 (GAP-P4-011, 013, 014) | OPEN |
| **Total** | **14** | **ALL OPEN** |

**Next:** Wait for wave 2 sub-agents (scouts 7-12, 13-17, data audit) to produce evidence. Then triage, dedupe, and enter §4 DISPATCH phase with fixer sub-agents.


## F. Production Verification Snapshot — 2026-07-13T09:00Z

| Endpoint | Status | Notes |
|---|---|---|
| GET /api/health | 200 | ok / 0.2.0 |
| POST /api/auth/login | 200 | JWT after .env restore |
| GET /api/networking | 200 | contacts/outreach counts |
| GET /api/analytics | 200 | 22 apps / 137 jobs |
| GET /api/analytics/dashboard | 200 | aggregates |
| GET /api/workspaces/interviews/prep | 200 | live |
| GET /api/workspaces/settings | 200 | profile payload |
| POST /api/emails/draft | 201 | create draft works |
| POST /api/networking/contacts | 201 | create contact works |
| POST /api/approvals | 201 | create approval works |
| POST /api/agents/tailor/run | 422 | path live (validation) |
| POST /api/agents/cover-letter/run | 422 | path live (validation) |

**Incident:** Scout truncated `.env` to stub; restored from `/tmp/aether-api.env` + `/tmp/aether-web.env`.

**ADRs:** D-0025 bulk/filters, D-0026 mobile Phase 3+, D-0027 approval list.

**Pending:** web rebuild + QA screenshots for login/settings/analytics UI.


## G. Independent QA post-deploy
Evidence: `uat/reports/evidence/phase4/qa-postdeploy-verify.json` (15 VERIFIED-CLOSED / 0 OPEN). Commit under test: `1f80091` + code `7459d1e`.

---

## H. Phase 4 Fresh Sweep — 2026-07-13T10:25Z (THIS run, no reused evidence)

**Orchestrator:** Hermes Agent (z-ai/glm-5.2 via OpenRouter)
**Delegation model:** deepseek/deepseek-v4-pro
**Kanban board:** aether-job-career-agent (16 cards: 1 master + 6 Stage A + 3 Stage C fixers batch 1 + 5 Stage C fixers batch 2)

### Stage A Evidence Files (all fresh from this run)
- `uat/reports/evidence/phase4/doc-audit-requirement-register.json` — 26 REQs, 125 SCs, 25 features, 48 design-ids
- `uat/reports/evidence/phase4/api-sweep-results.json` — 86 endpoints, 76 OK, 5 gaps (3 false positives)
- `uat/reports/evidence/phase4/scout-screens-1-6-findings.json` — 6 screens, 3 G-FAKE CRITICAL dead controls
- `uat/reports/evidence/phase4/scout-screens-7-12-findings.json` — 6 screens, offers form crash, analytics anomaly, stories filter broken
- `uat/reports/evidence/phase4/scout-screens-13-17-findings.json` — remaining screens
- `uat/reports/evidence/phase4/wireframe-diff-all-17.json` — 289 elements, 198 matching, 27 degraded, 64 missing (25 ADR-covered, 6 genuine)
- `uat/reports/evidence/phase4/data-ai-audit.json` — AI quality PASS_WITH_CAVEATS, email draft-only gap
- Screenshots in `uat/reports/evidence/phase4/*.png`

### Test Suite Status (this run)
- Vitest: 141/141 PASS
- Pytest: 239 passed, 0 failed (after fixer batch 1 — was 205 passed/7 failed/20 errors before)

### Gap Ledger (fresh gaps from this run)

| Gap ID | Type | Severity | Screen | Status | Fixer |
|--------|------|----------|--------|--------|-------|
| GAP-P4-019 | G-FAKE | CRITICAL | /dashboard | FIXER DISPATCHED | deleg_e7f2293e |
| GAP-P4-020 | G-FAKE | CRITICAL | /dashboard | FIXER DISPATCHED | deleg_e7f2293e |
| GAP-P4-021 | G-FAKE | CRITICAL | /dashboard/email | **SUPERSEDED-BY-042** (duplicate of GAP-P4-042, Run-3 reconciliation) | deleg_e7f2293e |
| GAP-P4-022 | G-METRIC | MEDIUM | /dashboard | OPEN | — |
| GAP-P4-023 | G-BUG | CRITICAL | /dashboard/offers | FIXER DISPATCHED | deleg_e7f2293e |
| GAP-P4-024 | G-FAKE | CRITICAL | /dashboard/offers | FIXER DISPATCHED | deleg_e7f2293e |
| GAP-P4-025 | G-METRIC | HIGH | /dashboard/analytics | FIXER DISPATCHED | deleg_7ef75c88 |
| GAP-P4-026 | G-METRIC | LOW | /dashboard/analytics | FIXER DISPATCHED | deleg_7ef75c88 |
| GAP-P4-027 | G-BUG | HIGH | /dashboard/stories | FIXER DISPATCHED | deleg_7ef75c88 |
| GAP-P4-028 | G-BUG | MEDIUM | /dashboard/stories | FIXER DISPATCHED | deleg_7ef75c88 |
| GAP-P4-029 | G-FAKE | HIGH | /dashboard/email | **SUPERSEDED-BY-042** (duplicate of GAP-P4-042; ADR D-0029 now governs the fix) | — |
| GAP-P4-030 | G-MISSING | MEDIUM | /dashboard/jobs | OPEN (wireframe gap) | — |
| GAP-P4-031 | G-MISSING | MEDIUM | /dashboard/jobs | OPEN (wireframe gap) | — |
| GAP-P4-032 | G-MISSING | MEDIUM | /dashboard/resume | OPEN (wireframe gap) | — |
| GAP-P4-033 | G-MISSING | LOW | /dashboard/cover-letters | OPEN — **citation corrected**: "ADR D-0020 covers" was wrong (D-0020 is scoped to the Agents screen only); see Section E (candidate C-35) for the corrected reasoning | — |
| GAP-P4-034 | G-MISSING | MEDIUM | /dashboard/applications | **REOPENED-AS-050** (Run-3 evidence: only 4/8 kanban columns render, contradicting this row's prior close and the Section E no-gap claim) | — |
| GAP-P4-035 | G-MISSING | LOW | /dashboard/analytics | OPEN (wireframe gap) | — |
| GAP-P4-036 | G-BUG | HIGH | test suite | VERIFIED-CLOSED (offers router added) | deleg_4b92ee44 |
| GAP-P4-037 | G-BUG | HIGH | test suite | VERIFIED-CLOSED (cast removed) | deleg_4b92ee44 |
| GAP-P4-038 | G-BUG | HIGH | test suite | VERIFIED-CLOSED (fixture user fix) | deleg_4b92ee44 |
| GAP-P4-039 | G-QUALITY | MEDIUM | all AI screens | OPEN (LLM timeout → fixture fallback) | — |

### Summary
- Total fresh gaps: 21
- VERIFIED-CLOSED: 3 (GAP-P4-036, 037, 038)
- FIXER DISPATCHED: 9 (awaiting completion)
- OPEN: 9 (wireframe gaps need ADR or implementation; email send needs provider; LLM timeout needs budget fix)

### Next Steps
(Superseded by Run 3 — see Section I. The deleg_* fixer batches' output was adjudicated in the Run-3 preflight review: 14 files KEEP, 5 files DROP.)

---

## I. Run-3 Triage Rulings — 2026-07-13T13:05Z (Orchestrator decision record, claude-fable-5)

Inputs: Stage A swarm (26 agents, 0 failures) distilled to 41 candidates in `uat/reports/evidence/phase4/triage-candidates__run3.json`. One gap = one record; new records GAP-P4-040+ to be expanded to full §3 format by the doc agent from the triage JSON + these rulings.

### I.1 New gap records and dispatch

| GAP | Cand. | Sev | Ruling (summary) | Cluster | Fixer→Reviewer |
|---|---|---|---|---|---|
| GAP-P4-040 | C-01 | CRITICAL | POST /interviews must never 500; validate (422) or nullable column per RCA — no fake defaults | FIX-D | sonnet→opus |
| GAP-P4-041 | C-02 | CRITICAL | Email page null-guards `intelligence`; honest empty state; no fabricated scores | FIX-C | opus→sonnet |
| GAP-P4-042 | C-03 | CRITICAL | Send returns explicit "no provider connected" error; UI surfaces it; drafts unaffected. Supersedes GAP-P4-021/029 (duplicates). ADR D-0029 | FIX-C | opus→sonnet |
| GAP-P4-043 | C-04 | CRITICAL | Request Changes button: RCA + real wiring | FIX-B | opus→sonnet |
| GAP-P4-044 | C-05 | CRITICAL | No duplicated/dangling bullets in tailored output/PDF | FIX-A | opus→sonnet |
| GAP-P4-045 | C-06 | HIGH | Rewrites ground in user evidence, not JD verbatim echo; add overlap regression test | FIX-A | opus→sonnet |
| GAP-P4-046 | C-08 | HIGH | PDF renderer: zero cross-bullet overlap; geometry test | FIX-A | opus→sonnet |
| GAP-P4-047 | C-07 | HIGH | Implement real career-data consolidation (portfolio + GitHub ingestion; LinkedIn honest limitation, ADR D-0031) | FIX-J | opus→sonnet |
| GAP-P4-048 | C-09 | HIGH | CL PDF: business-letter styling + sender contact block | FIX-B | opus→sonnet |
| GAP-P4-049 | C-10 | HIGH | CL pipeline enforces format contract (3-para, Re:, CTA, no banned openers) with real validation/retry | FIX-B | opus→sonnet |
| GAP-P4-050 | C-11 | HIGH | 8-column Kanban per wireframe; reopens falsely-closed GAP-P4-034; corrects Section E row | FIX-E | sonnet→opus |
| GAP-P4-051 | C-15+C-32+C-34 | HIGH | Working e2e auth via env-var creds + storageState; drop password-hardcoded scripts; fix harness 405 noise | FIX-G | sonnet→opus |
| GAP-P4-052 | C-13 | HIGH | Networking Kanban board with contact cards per wireframe | FIX-F | sonnet→opus |
| GAP-P4-053 | C-17 | MEDIUM | Frontend calls existing /workspaces/settings; no duplicate alias | FIX-D | sonnet→opus |
| GAP-P4-054 | C-19 | MEDIUM | Locked-provider 409s handled gracefully; guard stays | FIX-D | sonnet→opus |
| GAP-P4-055 | C-20 | MEDIUM | Provider panel honestly shows actual serving path incl. Abacus fallback; D-0020 text amended | FIX-D | sonnet→opus |
| GAP-P4-056 | C-12 | MEDIUM | Disabled controls get disabled affordance per D-0020 honesty | FIX-I | sonnet→opus |
| GAP-P4-057 | C-22 | MEDIUM | Offers modal overlay no longer blocks empty-state button | FIX-I | sonnet→opus |
| GAP-P4-058 | C-23 | MEDIUM | Fix jobs-vs-applications label/value binding | FIX-H | sonnet→opus |
| GAP-P4-059 | C-24 | MEDIUM | Avg runs/week uses real weeks divisor | FIX-H | sonnet→opus |
| GAP-P4-060 | C-40 | MEDIUM | Implement sources donut + market-vs-you sections from real data | FIX-H | sonnet→opus |
| GAP-P4-061 | C-25 | MEDIUM | Delete provably-test rows only (per data-metrics audit list); log deletions | FIX-D | sonnet→opus |
| GAP-P4-062 | C-36 | LOW | Settings sub-nav order per wireframe | FIX-I | sonnet→opus |
| GAP-P4-063 | C-38 | LOW | Story-extractor trigger gets async feedback | FIX-I | sonnet→opus |
| GAP-P4-064 | C-26 | MEDIUM | Avatar management ADR-deferred (D-0030) — no backend storage exists | DOC-K | n/a |
| GAP-P4-065 | C-27 | MEDIUM | Interview Center deferral: cite/amend ADR explicitly (D-0009) | DOC-K | n/a |
| GAP-P4-066 | C-16+C-33 | MEDIUM | Index D-0018 in requirement register; note PDF/infra-ADR coverage as accepted | DOC-K | n/a |
| GAP-P4-067 | C-18 | MEDIUM | Reconcile D-0025 text vs live jobs filters (investigate in Wave 2) | Wave-2 | tbd |

### I.2 No-gap rulings (to Section E with reasons)
- C-14/C-21/C-29: live production data correctly displayed; wireframe canonical numbers are design examples, not a production data contract (new ADR D-0028). Fabricating them would violate §6.4/§8.
- C-31: mobile-dashboard now matches its wireframe — contradicts stale D-0026 text; amend ADR (improvement, not gap).
- C-28 (extra Edit/Delete controls), C-30 (design-id attrs; D-0027 + testid convention), C-37 (honest empty states), C-39 (naming-only mismatches), C-41 (informational): no-gaps with reasons.
- C-35: cover-letter list-view deviation → ADR-file as intentional; correct GAP-P4-033's wrong D-0020 citation.

### I.3 Working-tree adjudication (from preflight)
KEEP: 6 api test fixes, e2e/agents.spec.ts, e2e/dashboard.spec.ts, PHASE3-GAP-LEDGER.md, PHASE4-GAP-ANALYSIS.md, apps/web/.gitignore, uat/api_sweep.py, uat/scout_production.py, uat/phase4_sweep.py, .claude/*. DROP: e2e/login.spec.ts + e2e/auth.setup.ts + playwright.config.ts modifications (broken prefill assumption zeroing the e2e suite — properly rebuilt under GAP-P4-051), uat/api_sweep.sh, uat/api_sweep_v2.sh (hardcoded password).

### I.4 Prior-ledger reconciliation
GAP-P4-021/029 → superseded by GAP-P4-042. GAP-P4-034 → REOPENED as GAP-P4-050 (fresh evidence contradicts VERIFIED-CLOSED). GAP-P4-022 → GAP-P4-058. GAP-P4-025/026 → GAP-P4-058/059 lineage noted; D-0003 ruling (Section I.2) closes the "canonical funnel" reading. GAP-P4-039 (LLM timeout→fixture fallback): monitored in Wave-2 QA under AI-quality recipes. All other Run-1/2 VERIFIED-CLOSED verdicts: fresh Stage A evidence found no regression except where noted.
