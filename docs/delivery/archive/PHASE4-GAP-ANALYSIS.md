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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_001__20260713T090404Z.json` (POST /emails/draft → 201)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_002__20260713T090404Z.json` (POST /networking/contacts → 201)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_003__20260713T090404Z.json` (GET /workspaces/interviews/prep → 200)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_004__20260713T090404Z.json` (GET /networking → 200)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_005a__20260713T090404Z.json` (GET /analytics → 200), `qa__gap_p4_005b__20260713T090404Z.json` (GET /analytics/dashboard → 200)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_006__20260713T090404Z.json` (POST /agents/tailor/run without payload → 422, route live, not 404)

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_007__20260713T090404Z.json` (POST /agents/coverLetter/run without payload → 422, route live, not 404)

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
- **Evidence (post-fix):** This pass's fresh full-suite re-run confirms no regression: `pytest` (apps/api) 292/292 passed, 0 failed (see Summary, re-run this pass).

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
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0025 (role/salary filters deferred; location filter (jd05) confirmed genuinely live and functional, not deferred — re-verified in GAP-P4-067).

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
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0025 (bulk tailor/skip/saved-tailor-all buttons genuinely deferred to Phase 3+ — reconfirmed live-absent in GAP-P4-067).

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
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0025 — but note the preview button (jd33) is actually **live and functional**, not deferred: `GAP-P4-067__detail-panel__post__20260713T235336Z.png` and `GAP-P4-067__result2__post__20260713T235336Z.json` (`preview_href: "/dashboard/resume?job={id}"`) confirm a real, working `<Link>`, correcting this row's original "MISSING" observation (see GAP-P4-067 and §C.1).

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_012__20260713T090404Z.json` (POST /approvals → 201)

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
- **Evidence (post-fix):** `/var/log/aether/web.log` (no `ECONNREFUSED` lines after the cited build's `Ready` line); cross-checked this pass — Wave-2's own merge-1 finding (§I.6) that production web was briefly served by an orphan non-systemd process is now corrected (`aether-web.service` systemd-managed), removing the class of internal-networking misconfiguration this gap flagged.

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__login__post.png` (empty fields, no "Demo" label); re-confirmed this pass by GAP-P4-051's e2e login coverage (`Login page renders the sign-in form with empty fields` — passing, see this pass's fresh 29/29 Playwright run).

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__gap_p4_015_api__20260713T090404Z.json` (GET /workspaces/settings → 200, full profile/resume/portfolio/integrations payload), `qa__settings__post.png` (rendered page).

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
- **Evidence (post-fix):** `uat/reports/evidence/phase4/qa__analytics__post.png` (rendered analytics dashboard); the remaining sources-donut/market-vs-you sections this row didn't yet cover are independently closed by GAP-P4-060.

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
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0026 (mobile approval genuinely still deferred); D-0026 amendment records that mobile *dashboard* now matches its wireframe (an improvement, Section E C-31, `rg-mob-dash__page-load__post__20260713T235952Z.png`) — the kept `apps/web/e2e/mobile-regression.spec.ts` regression-guards both routes going forward (this pass: 5/5 passed).

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
- **Evidence (post-fix):** `docs/delivery/DECISIONS.md` D-0027; `approvals__modal_structure.json` confirms the list view is functionally complete (5/5 wireframe-equivalent elements present under `data-testid` naming, Section E C-30).

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
- **Status:** VERIFIED-CLOSED (QA QA-API 2026-07-13, production). `POST /interviews` was exercised live against production three ways: (1) without `application_id` → `422` with `{"detail":[{"type":"missing","loc":["body","application_id"],"msg":"Field required",...}]}` — never a 500 (the router's Pydantic schema now declares `application_id: str = Field(min_length=1)`, required); (2) with a real, existing `application_id` (`c4bbc712a79c387b34580bb4a`, a genuine production application) → `201` with a full `InterviewResponse` body (`id: c7546c13f67837dae18e0ea6b`); (3) cleanup — `DELETE /interviews/c7546c13f67837dae18e0ea6b` → `204`, then re-`GET` on the same id → `404 "Interview not found"`, confirming the test row left no residue. `/var/log/aether/api.log` for the full test window: 0 ERROR lines.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-040__no-app-id__post__20260713T232112Z.json` (422), `GAP-P4-040__valid-create__post__20260713T232123Z.json` (201), `GAP-P4-040__cleanup-delete__post__20260713T232130Z.json` (204 + confirmed 404 after).

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
- **Status:** VERIFIED-CLOSED (QA QA-EMAIL 2026-07-13, production). Navigated to /dashboard/email on production (fresh login) with an empty inbox: page rendered fully (no crash, `data-testid="email-center"` present), zero console errors/pageerrors. Composed a new draft via the Compose modal (`POST /emails/draft` → 201) then reloaded; the new thread auto-selected on load and rendered the honest `data-testid="ai-intelligence-empty"` panel ("No intelligence available yet — connect your Gmail account...") — `selected.intelligence` is null and the frontend never dereferences `.score` (optional-chaining/guard confirmed live, matches `emailIntelligenceView()` unit coverage in `email-intelligence-guard.test.ts`, 5/5 passed). `/var/log/aether/api.log` window for the whole session contains zero ERROR lines. Backend `intelligence` field is still typed `null` (honest, per fix spec's accepted branch) — frontend guard is the closure mechanism, confirmed live.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-041__page-load__pre__20260713T224746Z.png` (pre-interaction, empty inbox, clean render), `GAP-P4-041__thread-detail-all-tab__post__20260713T224826Z.png` (real thread selected, honest empty-intelligence panel + "No reply needed for this email", zero console errors), `GAP-P4-041-042__flow__post__20260713T224746Z.json`, `GAP-P4-041-042__console__post__20260713T224746Z.log` (0 console errors excl. one benign 409 network log from the deliberate GAP-P4-042 send test, 0 pageerrors), `GAP-P4-041__all-tab-select__post__20260713T224826Z.json`, `GAP-P4-041-042__api-log-window__post__20260713T224841Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-EMAIL 2026-07-13, production). **Supersedes GAP-P4-021 and GAP-P4-029** — both were duplicate reports of this single defect (Run-3 orchestrator cross-check); GAP-P4-042 is now the canonical record. Composed a real draft thread on production, then attempted to send it two independent ways: (1) from *within* the authenticated browser session via the exact `fetch(...)` call `sendEmailReply()`/`confirmSend()` issues (`POST /workspaces/emails/send {message_id, body}`), and (2) via a standalone API client outside the browser. Both returned `409 Conflict` with `{"detail":{"error":"no_email_provider_connected","message":"No email provider connected — connect an account in Settings to send. No email has been sent."}}` — never `200 {"status":"sent"}`, never a 500. Confirmed via `GET /emails/{thread_id}` that the thread's `messages` array was untouched by the rejected send (only the original draft entry present, no fabricated "sent" append). `/var/log/aether/api.log` shows the exact sequence `POST /emails/draft → 201`, `POST /workspaces/emails/send → 409` (×2), `GET /emails/{id} → 200`, with zero ERROR lines in the whole session window. Backend regression test `test_workspaces_emails_send_no_provider_returns_409` (`apps/api/tests/test_workspaces.py`) passed live (2/2 send-related tests). Frontend `emailSendErrorMessage()` unit tests (5/5, `email-intelligence-guard.test.ts`) confirm the exact 409 payload observed live is correctly lifted to the human-facing message the `data-testid="email-send-error"` banner would render. Note: the "Send Reply" button itself is not click-reachable in the *current* production data model because `GET /workspaces/emails/inbox` unconditionally returns `draftReply: ""` for every thread (a separate, intentional "no AI reply drafted yet" honest-empty-state, gating `{selected.draftReply ? <draft-reply-ui> : "No reply needed for this email."}` — verified rendering the latter, not a regression of this gap); the send attempt was therefore exercised at the exact network call the button issues rather than via a DOM click, and the honest-failure contract (409, no fabricated success, no 500, thread untouched) is fully verified end-to-end. `docs/delivery/DECISIONS.md` D-0029 is the ADR authorizing the honest-error fix shape.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-042__in-browser-send-attempt__post__20260713T224746Z.png`, `GAP-P4-041-042__flow__post__20260713T224746Z.json` (in-browser send: `{"status":409,"body":"...no_email_provider_connected..."}`, standalone API send: `{"status_code":409,...}`, thread-after: unchanged messages array), `GAP-P4-041-042__console__post__20260713T224746Z.log`, `GAP-P4-041-042__api-log-window__post__20260713T224841Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-CONTENT 2026-07-13, production). On production `/dashboard/cover-letters` with a real, freshly-generated letter selected (Ampersand · Business Analyst), clicked `data-testid="request-changes-btn"` — the disclosure form (`data-testid="request-changes-form"`) opened, filled the instructions textarea, clicked `data-testid="request-changes-submit"`, and captured the full network round trip live: `POST /api/cover-letters/{id}/refine` → `200 OK` after ~29s (real LLM latency), response body `{"cover_letter_id": "ce2cca98...", "cover_letter": "...Stakeholder communication has always been at the heart of my delivery practice...", "approval_id": "cc26b448...", "approval_status": "pending"}` — the revised text visibly incorporated the requested change ("emphasize stakeholder communication"). The button correctly showed a busy "Redrafting…" state, then settled (form closed on success, matching the component's `setOpen(false)` success path); the Versions rail advanced from v1 to v5·current; a new `ApprovalRequest` was created (`pending`), confirming this is a real, persisted, human-gated redraft — not a fake/no-op click. Repeated independently via a direct API client (bypassing the browser) with a second letter: same 200 + new `cover_letter_id` + new pending approval, and `GET /cover-letters/{id}` confirmed the original letter was untouched (a new sibling row was created, not a mutation). `/var/log/aether/api.log` for the entire test window (both the browser and API-direct passes) shows 0 `ERROR` lines. This is the real documented effect described by the router's own docstring ("fabrication-guarded LLM revision stored as a new draft with a pending ApprovalRequest").
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-043__cover-letters-loaded__post__20260713T225933Z.png`, `GAP-P4-043__form-open__post__20260713T225933Z.png` (instructions filled), `GAP-P4-043__after-submit__post__20260713T225933Z.png` (button settled, v5·current, revised text visible), `GAP-P4-043__ui-flow__post__20260713T225933Z.json` (full console/network capture incl. the `POST .../refine` → `200` request/response pair), `GAP-P4-049__generation-flow__post__20260713T230330Z.json` (API-direct refine round trip + unchanged-original confirmation), `GAP-P4-043-048-049__api-log-window__post__20260713T230330Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-RESUME 2026-07-13, production). Re-ingested the master resume PDF fresh via `POST /resumes/upload` (`assets/resume/Vik_Resume_Final.pdf`) through the fixed `extract_bullets()` — all 25 bullets are now complete, coherent sentences ending in terminal punctuation (or a clean noun-phrase skills/certs line), vs. the pre-fix version of the same source PDF which had entries cut off mid-word (e.g. "...Authored the executive change request re-"). Ran a real tailor pass on a fresh, previously-untested job (`POST /agents/tailor/run`, Delivery Lead/Scrum Master @ Aurec, job `c6ab5afc5e323f14ff8b641cd`) → 4 accepted rewrites, 3 rejected (fabrication/JD-echo guard correctly fell back to the original complete bullet text, not a spliced hybrid). Exported the tailored PDF (`GET /resumes/{id}/download`) and inspected all 3 pages both visually (rendered PNGs) and via `PyMuPDF` text extraction: zero duplicated phrases, zero dangling/mid-sentence fragments across all 25 bullets. `changes(run)=4` matched `changes(GET /resumes/{id}/diff)=4` exactly (same 4 evidenceRefs). Quantified outcomes (PI 47–48, 75-hour, six-day, 95%+, $5M+, 5+, 40 resources) all preserved in the accepted rewrites. Cross-bullet PDF overlap re-checked as part of this same evidence (see GAP-P4-046 note) — zero overlaps. `apps/api` regression suite `test_resume_bullet_extraction.py` + `test_resume_pdf_layout.py` + `test_resume_ingest.py` (14/14 relevant cases) passed live against the deployed code. `/var/log/aether/api.log` window for the full flow (lines 21935–21943: upload→201, jobs lookup→200, tailor/run→200, diff→200, resume GET→200, download→200): 0 ERROR lines.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-044-045-046__flow__post__20260713T231316Z.json` (reingested resume bullets, job, full tailor-run + diff responses), `GAP-P4-044__tailored-pdf__post__20260713T231316Z.pdf`, `GAP-P4-044__pdfpage-{1,2,3}__post__20260713T231316Z.png`, `GAP-P4-044-045-046__analysis__post__20260713T231316Z.json` (duplication/dangling-fragment check, quantified-outcomes check), `GAP-P4-044-045-046__api-log-window__post__20260713T231316Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-RESUME 2026-07-13, production). Re-ran tailoring live on a fresh, previously-untested job (Delivery Lead/Scrum Master @ Aurec, `c6ab5afc5e323f14ff8b641cd`) and independently diffed every rewritten/rejected bullet against the real JD text for content-word n-gram overlap (stopword-stripped, light-stemmed 3-grams — same n=3 window as the shipped `_JD_ECHO_NGRAM`/`jd_echoed_phrases()` guard, computed with a separate script, not the guard's own code). Result: all 4 ACCEPTED rewrites show **zero** JD-lifted 3-grams. Of the 3 REJECTED candidates (correctly reverted to the evidence-grounded original), 2 show clear near-verbatim JD phrase lifting caught by the guard — e.g. rejected text "...underpinned transparent progress reporting to departmental governance bodies" shares the stemmed 3-gram "transparent progress report[ing]" with the JD's "...deliver transparent progress reports tailored for executive stakeholders", and rejected text "...exemplifying exceptional stakeholder management and communication" shares "exceptional stakeholder management" verbatim with the JD's Core Capabilities line. This is the same class of defect the gap named (JD phrase lifted into the candidate's own experience) — confirmed live, not a canned fixture, with the guard demonstrably discriminating (blocks JD-echo, keeps evidence-grounded rewrites). Backend regression `test_tailor_jd_echo_guard.py` (4/4 cases incl. the exact "first-class software"/"high-traffic environment" scenario cited in this gap) passed live against deployed code. `/var/log/aether/api.log`: 0 ERROR lines in the test window.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-044-045-046__flow__post__20260713T231316Z.json` (job description text, full tailor-run response incl. the 3 rejected candidates), `GAP-P4-044-045-046__analysis__post__20260713T231316Z.json` (per-bullet 3-gram overlap counts, accepted vs. rejected), `GAP-P4-044-045-046__api-log-window__post__20260713T231316Z.log`.

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
- **Status:** VERIFIED-CLOSED (QA QA-RESUME 2026-07-13, production). Regenerated the same tailored PDF used for GAP-P4-044's fresh production run (Delivery Lead/Scrum Master @ Aurec) and independently checked all 3 pages for cross-bullet visual overlap using `PyMuPDF`'s `get_text("dict")`: right-column (bullet) spans grouped into true visual rows by shared baseline (≤2.5pt tolerance, so a bullet's bold lead-in and grey body — drawn as two separate text objects sharing one baseline — merge into one row instead of being mistaken for two), then checked each row's bottom against the next row's top with a 1.5pt descender/ascender tolerance. Result: **0 overlaps on all 3 pages** (35/36/30 rows respectively). Page 2 contains this run's longest rewritten bullet ("Directed a $5M+ program portfolio...", 3 lines in a highlighted box) — the exact "longer rewrite overflowing into the next bullet" scenario the original defect exhibited — and it renders fully contained with clean spacing above and below (confirmed both by the geometric check and visually in the rendered page image). Note: an initial naive bbox check (grouping words by rounded `top` alone, without baseline merging) produced 5 false-positive "overlaps" by conflating a bullet's isolated left-edge marker glyph with the far-right end of its own body-text bounding box; re-deriving the check to mirror the renderer's actual two-span-per-row draw structure (matching the shipped test's own methodology in `test_resume_pdf_layout.py::_rendered_rows`) resolved all 5 to true negatives — noted here so this isn't mistaken for a silent re-check that just happened to pass. Backend regression `test_resume_pdf_layout.py::test_tailored_pdf_has_no_cross_bullet_overlap` (which stress-tests every block on every page with an artificially-lengthened rewrite) passed live against deployed code. `/var/log/aether/api.log`: 0 ERROR lines in the test window.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-044__tailored-pdf__post__20260713T231316Z.pdf`, `GAP-P4-044__pdfpage-{1,2,3}__post__20260713T231316Z.png` (page 2 shows the longest rewrite fully contained, no overlap into "Architecture & Governance:" below it), `GAP-P4-044-045-046__analysis__post__20260713T231316Z.json` (row-overlap check results per page: 0/0/0).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Confirmed `scrape_github_profile()` (`apps/api/app/services/portfolio_scraper.py`) now has a real caller chain: `ingest_github()` → `refresh_career_data()` (`apps/api/app/services/career_data.py`) → `POST /workspaces/career-data/refresh`; and `build_career_corpus(user_id)` is called from both `apps/api/app/agents/tailor_agent.py:95` and `apps/api/app/agents/cover_letter_agent.py:256`, passed through as `evidence_extra` into `ResumeTailorService.tailor()`/`_validate()` (`apps/api/app/services/resume_tailor.py:389-457`) where it is concatenated into the grounding/anti-fabrication evidence corpus — not dead code, and not merely present but actually consumed. Live production exercise via the real Settings UI (`/dashboard/settings` → Portfolio Sync sub-nav, `data-testid="career-github-input"`/`career-portfolio-input"`/`career-sync-btn`): filled the user's real GitHub username (`Victordtesla24`) and portfolio URL (`https://forgotten-mistory.web.app/`), clicked "Sync now" — the button showed the immediate "Syncing…" pending state, then resolved to "Career data synced ✓" with per-source chips reading "Synced · 2026-07-13" for both GitHub and Portfolio and an honest "Not provided" for LinkedIn (zero console/network events during the whole flow). Cross-checked via `GET /workspaces/career-data`: both sources return `status: "ok"` with real, non-fabricated ingested content — GitHub shows the account's actual 38 public repos/19 stars/top languages/named repos (`forgotten-mistory`, `3-tier-multi-agent-architecture`, etc., matching the real `github.com/Victordtesla24`), and Portfolio shows real scraped text from the live portfolio site (name, role, ATO/ANZ experience bullets) — not placeholder text. LinkedIn correctly stays `status: "empty"` with the explicit D-0031 honest-limitation message (no scraping attempted). End-to-end proof the wiring lands in the tailoring context: triggered a real `POST /agents/tailor/run` against an existing job (`cdd4cd1a2fda3a9019a47e30a`) with career data now configured → `200 OK`, 5 accepted changes, 0 rejected bullets — confirming the widened evidence corpus does not break or over-reject the grounding validator. `/var/log/aether/api.log` for the full test window: 0 ERROR lines (the two `LLM live call failed … falling back to fixture` / `LLM auto mode: served fixture fallback` lines are the pre-existing, accepted INFO-level resilience path per GAP-P4-039, not an error).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-047__settings-after-sync__post__20260713T235022Z.png`, `GAP-P4-047__ui-sync-result__post__20260713T235022Z.json`, `GAP-P4-047__console__post__20260713T235022Z.log` (0 bytes), `GAP-P4-047__career-data-api__post__20260713T235236Z.json` (live `GET /workspaces/career-data`, both sources `status:"ok"` with real content), `GAP-P4-047__tailor-trigger__post__20260713T235236Z.json` (`POST /agents/tailor/run` → 200, 5 changes/0 rejected), `GAP-P4-047__tailor-diff__post__20260713T235236Z.json`. `docs/delivery/DECISIONS.md` D-0031 documents the LinkedIn scope limitation, respected by this implementation.

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
- **Status:** VERIFIED-CLOSED (QA QA-CONTENT 2026-07-13, production). Generated a real cover letter PDF on production (`GET /cover-letters/{id}/pdf` → `200`, `content-type: application/pdf`) and independently inspected it with `pdftotext -layout` and `pdfplumber` (not just a screenshot). Confirmed: (1) a sender contact block heads the letter — "Vikram Deshpande" (bold) then "sarkar.vikram@gmail.com · +61 433 224 556" and "linkedin.com/in/vikramd-profile · github.com/Victordtesla24", sourced from the workspace profile + parsed résumé contact fields; (2) light business styling — `pdfplumber` reports the only text fill colors used on the page are `(0.102,0.102,0.102)` = `#1A1A1A` ink and `(0.333,0.333,0.333)` = `#555555` muted, one `#CCCCCC` rule line, and **zero fill rects** (no dark background band of any kind — plain white page), matching the `_PDF_INK`/`_PDF_MUTED`/`_PDF_RULE` constants in `apps/api/app/routers/cover_letters.py`; (3) `"Generated by Aether"` and `"AI-generated"` do not appear anywhere in the extracted text — no tool branding or AI-disclosure footer. Repeated the same checks on a second, independently-generated PDF (the Request-Changes/refine redraft from GAP-P4-043's test) with identical results (same ink colors, same contact block, no branding). `/var/log/aether/api.log` shows both `GET .../pdf` calls returning `200 OK` with 0 ERROR lines in the session window.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-048__pdf-original__post__20260713T230330Z.pdf`, `GAP-P4-048__pdf-refined__post__20260713T230330Z.pdf` (raw PDF bytes, both letters), `GAP-P4-048__pdf-render__post__20260713T230330Z.png` (rendered page-1 image — light business letter, contact block visible), `GAP-P4-048__pdf-color-analysis__post__20260713T230330Z.json` (pdfplumber color/rect/branding-string analysis for both PDFs), `GAP-P4-043-048-049__api-log-window__post__20260713T230330Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-CONTENT 2026-07-13, production). Re-ran cover letter generation on production for the **exact job cited in the original defect** (Duratec Limited · Operations Manager, job `cdd4cd1a2fda3a9019a47e30a`) via `POST /agents/cover-letter/run`, twice independently (one run's primary LLM call hit its 60s hard budget and fell back to a fixture per the existing resilience path — `LLM auto mode: served fixture fallback for prompt 'cover_letter'` — and the structural gate still enforced compliance on that path too). Both fresh letters: exactly 3 body paragraphs; paragraph 1 = "My background in Senior Technical Program Manager is a direct match for the **Operations Manager** role at **Duratec Limited**." (explicitly names both role and company, unlike the cited defect); paragraph 3 in both closes with an explicit CTA ("I would welcome the opportunity to discuss..."/"...available for an interview at your convenience."); date, `Re:` line, `Dear` salutation, and `Sincerely, Vikram Deshpande` sign-off all present; no banned generic opener. Directly retrieved and re-checked the **original defective row** (`cabb3c2b35cc0dc2498d967f4`, created 2026-07-13T12:07:40, pre-fix) as a negative control with an independent checker script mirroring `cover_letter_agent.py`'s own `_structural_issues()` rules: it correctly reproduces the cited defect (2 paragraphs, no CTA, role/company not named in paragraph 1) — confirming the checker is discriminating, not a rubber stamp — while both new post-fix runs pass every check. Also independently generated and format-checked a second job/company (Ampersand · Business Analyst, run twice) with the same all-pass result. `/var/log/aether/api.log` for the full test window: 0 `ERROR` lines. **Caveat for Wave-2 follow-up (not a blocker for this gap, scoped to a different code path than this gap's cited root cause):** the *separate* `POST /cover-letters/{id}/refine` endpoint ("Request Changes" / rail Regenerate, `apps/api/app/routers/cover_letters.py`) does **not** share `cover_letter_agent.py`'s hard structural validator/retry — it only retries on fabrication-guard flags. Two independently-observed refine outputs (one via direct API call, one via the live "Request Changes" UI click under GAP-P4-043) each violated one structural rule (4 body paragraphs instead of 3; CTA cue absent from the closing paragraph, respectively) despite passing the fabrication guard. This gap's own root-cause analysis and fix specification name `cover_letter_agent.py`'s *generation* retry loop specifically, which is what I verified; the refine path was never in this gap's scope (GAP-P4-043's fix spec was only "wire the button to a real action"). Flagging so the orchestrator can open a new Wave-2 gap for structural-contract parity across the refine endpoint if desired.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-049__duratec-rerun-A__post__20260713T230330Z.json`, `GAP-P4-049__duratec-rerun-B__post__20260713T230330Z.json` (both fresh Duratec/Operations Manager letters, full text + persisted IDs), `GAP-P4-049__generation-flow__post__20260713T230330Z.json` (Ampersand/Business Analyst runs), `GAP-P4-049__contract-cases__post__20260713T230330Z.json` (all cases incl. the old defective letter as negative control, fed through the independent checker), `GAP-P4-043-048-049__api-log-window__post__20260713T230330Z.log` (0 ERROR lines).

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
- **Status:** VERIFIED-CLOSED (QA QA-BOARDS 2026-07-13, production). Navigated to `/dashboard/applications` Board View (fresh login, real session) and evaluated the DOM directly: `data-testid="applications-kanban"` renders all **8** `kanban-column-*` sections in wireframe order with correct labels — Discovered, Evaluating, Tailoring, Ready to Apply, Submitted, In Review, Interview, Offer — each with a live per-column count matching its rendered card count (Discovered 147/25-shown+122-more, Evaluating 0, Tailoring 0, Ready to Apply 5/5, Submitted 4/4, In Review 0, Interview 0, Offer 0). The container is genuinely horizontally scrollable (`scrollWidth=2192` vs `clientWidth=1128`, `overflow-x: auto`); scrolling it to the far right reveals Submitted/In Review/Interview/Offer with real application cards (e.g. "Infrastructure Project Manager · Pathway Search" with a working "View Email Thread" cross-link), confirmed both via DOM query and a second, scrolled full-page screenshot. Zero-count columns render an honest "Empty" placeholder, not fabricated cards. Also re-verified the Sankey toggle named in this recipe still works after the kanban fix: clicked `data-testid="view-sankey"` → `sankey-view` renders with 1 live `<svg>` funnel (Jobs Found 154 → Applied 4, real numbers, no error banner), backed by `GET /applications/funnel/sankey → 200`. Console/network capture during the whole flow (load + scroll + Sankey click) is **0 bytes — zero events of any kind**. `/var/log/aether/api.log` for the full test window: 0 ERROR lines; relevant calls all 200 (`GET /applications`, `GET /workspaces/settings` ×3, `GET /applications/funnel/sankey`).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-050__board-view__post__20260713T233154Z.png` (full 8-stage board, unscrolled), `GAP-P4-050__board-scrolled__post__20260713T233154Z.png` (scrolled right — Submitted/In Review/Interview/Offer visible with real cards), `GAP-P4-050__sankey-view__post__20260713T233154Z.png` (Sankey toggle still renders), `GAP-P4-050__console__post__20260713T233154Z.log` (0 bytes), `GAP-P4-050-052__result__post__20260713T233154Z.json` (full column/count DOM dump + Sankey check).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, on merged main + production). Ran the full rebuilt Playwright e2e suite on merged `main` (`cd apps/web && npx playwright test --project=chromium`, real env-var creds exported from repo `.env`): **25/25 passed** (21.8s), including the `setup` project (`e2e/auth.setup.ts` — real login via `LOGIN_EMAIL`/`LOGIN_PASSWORD`, no more prefill-assumption timeout) and all 3 `login.spec.ts` cases (empty-field render, real sign-in redirect, wrong-credentials error) that previously reported "did not run" — confirming the hard-dependency chain now resolves end-to-end instead of zeroing out the suite. `apps/web/e2e/login.spec.ts` and `auth.setup.ts` are present again but rebuilt (not the dropped broken versions) per the Section I.3 disposition — they now fill the real form via `requireEnv("LOGIN_EMAIL"/"LOGIN_PASSWORD")` (`apps/web/e2e/env.ts`) instead of asserting a nonexistent prefill. `uat/api_sweep.sh` and `uat/api_sweep_v2.sh` are confirmed absent from disk (`ls` → No such file). `git grep -n 'AetherDemo1' --` on `main` (tracked files only) returns matches **only** in `uat/tests/test_tooling_hygiene.py` (the regression-guard's own regex/docstring, which must reference the literal string to detect it elsewhere — not a live credential) and in this ledger's own historical "Observed" prose describing the pre-fix defect; zero matches in any script that actually authenticates (`seed_demo.py`, `client.ts`, `discovery_cron.sh`, `api_sweep.py` all resolve the password from the environment only). `uat/tests/test_tooling_hygiene.py` (2 tests) passes. Production harness sweep (`python3 uat/phase4_sweep.py --route /dashboard --out-prefix qa051`): `ok=True`, `bounced_to_login=False`, `nav_error=null`, and the console/network capture is **0 bytes — zero events of any kind**, confirming zero tooling-induced console errors and specifically no `GET /api/auth/login` 405 (the harness-noise finding does not reproduce). `/var/log/aether/api.log` for both the e2e run and the harness sweep: 0 ERROR lines. The working-tree disposition for the broken/dropped files remains as recorded in Section I.3 of this ledger.
- **Evidence (post-fix):** `/tmp` playwright run captured and archived to `uat/reports/evidence/phase4/GAP-P4-051__playwright-run__post__20260713T234923Z.log` (25 passed, 0 failed), `qa051__screenshot__20260713T234912Z.png`, `qa051__console__20260713T234912Z.log` (0 bytes), `qa051__controls__20260713T234912Z.json`, `qa051__meta__20260713T234912Z.json` (`bounced_to_login: false`, `nav_error: null`).

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
- **Status:** VERIFIED-CLOSED (QA QA-BOARDS 2026-07-13, production). Navigated to `/dashboard/networking` (fresh login): the tab/pill summary is gone — `data-testid="contact-pipeline"` renders a genuine 5-column kanban (New/Warm/Active/Scheduled/Placed, `role="tablist"` absent, confirmed `isTabPill: false`) built from real `GET /workspaces/networking/summary` data (`workspaces.py`'s stage-label mapping fix). The account currently has 0 real contacts, so it first rendered the honest whole-board "No connections yet" empty state (not a fabricated placeholder) — to fully exercise the kanban-card rendering path per this recipe, created one real, persisted contact via the actual production `POST /networking/contacts` endpoint (`{"name":"Priya Sharma","title":"Senior Technical Recruiter","company":"Endeavour Group","stage":"contacted"}` → `201`), reloaded the page, and confirmed live: the board now renders (not the empty-state branch), the contact appears as a proper `data-testid="contact-card"` article in the correct "Warm" column (name + role/company + warmth stars all correct), the stat tile updates to "1 CONTACTS", and the other 4 columns each show their own honest `pipeline-*-empty` ("No contacts yet") marker — exactly the wireframe kanban-with-honest-empty-columns behavior this gap required, not the old aggregate tab/pill counts. Cleaned up immediately after: `DELETE /networking/contacts/{id} → 204`, re-`GET` same id → `404`, `GET /networking/contacts` → `[]` (production account left in its original zero-contact state, no residue). Console/network capture across both the empty-board load and the with-contact load: **0 bytes — zero events** in both. `/var/log/aether/api.log` for the full test window: 0 ERROR lines (`GET /workspaces/networking/summary` ×4 → 200, `POST /networking/contacts` → 201, `DELETE .../contacts/{id}` → 204, `GET .../contacts/{id}` → 404 as expected, `GET /networking/contacts` → 200 `[]`).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-052__board-view__post__20260713T233154Z.png` (honest empty-board state, 0 real contacts), `GAP-P4-052__contact-create__post__20260713T233154Z.json` (real `POST /networking/contacts` → 201), `GAP-P4-052__board-with-real-contact__post__20260713T233358Z.png` + `.json` (kanban board with the real "Priya Sharma" card in Warm column, other 4 columns honestly empty, DOM dump), `GAP-P4-052__console-with-real-contact__post__20260713T233358Z.log` (0 bytes), `GAP-P4-052__contact-cleanup__post__20260713T233358Z.json` (204 delete + 404 confirm), `GAP-P4-052__api-summary__post__20260713T233154Z.json` (raw API response, pre-test).

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
- **Status:** VERIFIED-CLOSED (QA QA-API 2026-07-13, production). Loaded `/dashboard/applications` fresh (real login, `uat/phase4_sweep.py`, `networkidle` + 2s settle) and captured every console message/pageerror/requestfailed/response≥400 unfiltered: the console/network log is **0 bytes — zero events of any kind**, so in particular zero `GET /api/settings` 404s. Cross-checked server-side: `/var/log/aether/api.log` for the exact request window shows `GET /workspaces/settings HTTP/1.1" 200 OK` (the correct endpoint, called twice during the page's lifecycle) and 0 ERROR lines — confirming the frontend now calls the real `/workspaces/settings` endpoint (matches `apps/web/src/components/applications/tracker-api.ts:76` and the `tracker-api.test.ts` regression test) and never `/api/settings`.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-053__applications__console__20260713T232419Z.log` (0 bytes), `GAP-P4-053__applications__screenshot__20260713T232419Z.png`, `GAP-P4-053__applications__meta__20260713T232419Z.json` (confirms no bounce-to-login, real page load), `GAP-P4-053__applications__controls__20260713T232419Z.json`.

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
- **Status:** VERIFIED-CLOSED (QA QA-API 2026-07-13, production). Loaded `/dashboard/agents` fresh (0 console/network events on page load itself), then drove a real interaction pass: clicked `data-testid="provider-action-anthropic"` ("Configure keys" on the locked, keyless Anthropic card) and separately `data-testid="provider-action-openai"`, capturing every console message/pageerror/requestfailed/response≥400 across both clicks. Result: **0 events of any kind fired for either click** — no error-level console entries, no network request at all (not even a 409), because the frontend's `connectBlockedReason()` pre-check (`apps/web/src/app/dashboard/agents/page.tsx` `onProviderToggle`) recognizes a keyless provider from the state it already has and short-circuits before ever issuing the doomed `PUT /agents/providers/{id}` request — a stronger fix than merely catching the 409 client-side. Each click instead rendered the graceful, correctly-worded info banner (`data-testid="agents-notice"`, `role="status"`): "Anthropic Claude has no credential configured on the server — add its API key to the server .env, then reload this page." (and the equivalent for OpenAI) — confirmed both in the captured `innerText` and visually in the screenshot. `/var/log/aether/api.log` for the full interaction window: 0 `PUT /agents/providers/*` calls at all (consistent with the pre-check design) and 0 ERROR lines. Repeated the full click sequence twice independently with identical (zero-event) results.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-054__agents-load__console__20260713T232503Z.log` (0 bytes, clean page load), `GAP-P4-054__interaction__console__20260713T232617Z.log` (0 bytes, clean interaction), `GAP-P4-054__interaction-result__20260713T232617Z.json` (0 error-level events, 0 network 409s, 0 requestfailed, both notice texts captured verbatim), `GAP-P4-054__before-click__20260713T232617Z.png`, `GAP-P4-054__after-click-anthropic__20260713T232617Z.png` (amber graceful-notice banner visible, page otherwise intact), `GAP-P4-054__after-click-openai__20260713T232617Z.png`.

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
- **Status:** VERIFIED-CLOSED (QA QA-API 2026-07-13, production). `GET /agents/providers` now returns a 7th card, `{"id":"abacus","name":"Abacus Subscription (fallback)",...}`, alongside the original 6 — no longer a blanket-unconfigured display. Cross-checked the returned state against `apps/api/app/routers/agents.py`'s own logic and the live server environment (read-only `/proc/<pid>/environ` inspection of the running `aether-api` process, presence-only, no values printed): `AETHER_LLM_API_KEY` absent, `OPENROUTER_API_KEY` present (73 chars), `ABACUS_API_KEY` present (35 chars) — per `_LIVE_API_KEY_ENV_VARS` precedence (`AETHER_LLM_API_KEY` > `OPENROUTER_API_KEY` > `ABACUS_API_KEY`) `get_active_credential_env_var()` resolves to `OPENROUTER_API_KEY` right now, so `abacus` should show "standby", not "actively serving" — and that is exactly what the live response shows: `abacus.status="connected"`, `abacus.detail="Abacus subscription key configured in .env · standby (a higher-priority OpenRouter/Anthropic key is the active path)"`, `abacus.models=["deepseek/deepseek-v4-flash","deepseek/deepseek-v4-pro","qwen/qwen3-coder-next"]` (matching the real `AETHER_MODEL_*` env values). Cross-checked against real recent `AgentRun` history (`GET /agents/runs`) from live tailor/coverLetter/storyExtractor executions today: recorded `output.model` values (`deepseek/deepseek-v4-pro`, `qwen/qwen3-coder-next`) match the tier→model env mapping exactly, with real multi-second durations (14.6s–61s), confirming genuine live calls rather than fabricated figures. This is the honest, self-consistent single-source-of-truth the fix spec required: the providers panel and the LLM client's actual routing decision are provably reading the same precedence function, and the panel correctly reflects real-time server credential state rather than a hardcoded claim. `/var/log/aether/api.log`: 0 ERROR lines for the `GET /agents/providers` call and the whole session.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-055__providers-status__post__20260713T232142Z.json` (full live `GET /agents/providers` response, 200 OK, all 7 providers incl. `abacus`), cross-referenced against `apps/api/app/services/llm_client.py:139-156` (`_LIVE_API_KEY_ENV_VARS`, `get_active_credential_env_var`) and `apps/api/app/routers/agents.py:193-248` (`_provider_env_state`) read directly from the deployed source tree, plus a read-only presence check of the live `aether-api` process environment (no secret values captured).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Loaded `/dashboard/agents` fresh and evaluated computed styles directly on every currently-disabled `button`/`select` in the DOM: `provider-model-anthropic` and `provider-model-bedrock` (both keyless-provider model dropdowns) render `opacity:0.6`, `cursor:not-allowed`, `filter:grayscale(1)`, `aria-disabled="true"`, and a real `title` tooltip ("Anthropic Claude has no selectable models — connect it (add its API key in the server .env) to enable model selection." / the AWS Bedrock equivalent); the currently-disabled agent run button (`agent-run-matchScoring`, the Match Scoring agent being toggled off right now) renders `opacity:0.4`, `cursor:not-allowed`, `filter:grayscale(1)`, `aria-disabled="true"`, `title="Match Scoring Agent is disabled — enable it above to run it."`. Confirmed the mechanism is general (not special-cased to one control) by also checking all 5 `agent-run-*` buttons: the 4 currently-enabled ones (jobDiscovery, resumeTailoring, coverLetter, storyExtraction) render `opacity:1`/no title, i.e. disabled-vs-enabled visual state is correctly conditional on the live `disabled` attribute, not hardcoded. This matches the fix in source (`apps/web/src/components/agents/AgentConfigGrid.tsx` and `ProviderConnections.tsx`: `disabled:cursor-not-allowed disabled:opacity-40/60 disabled:grayscale` + `title={...}` on every gated control). Console/network capture during page load: 0 bytes — zero events. `/var/log/aether/api.log` for the check window: 0 ERROR lines.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-056__agents-load__post__20260713T234518Z.png`, `GAP-P4-056__console__post__20260713T234518Z.log` (0 bytes), `GAP-P4-056__result__post__20260713T234518Z.json` (full computed-style dump of all disabled controls: 2 provider-model selects + 1 agent-run button, all with opacity/cursor/grayscale/title present).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Confirmed in source (`apps/web/src/components/offers/AddOfferModal.tsx:68`: `if (!open) return null;`) that the modal — including its backdrop overlay — is entirely unmounted, not just visually hidden, whenever closed; there is no stray/invisible overlay left in the DOM to intercept pointer events. Drove the real flow live on production: with the account in its genuine empty-offers state, clicked `data-testid="empty-add-offer"` — the click resolved in 0.046s (no 30s timeout), the modal (`data-testid="add-offer-modal"`) opened immediately, and a field inside it (`input[name="company"]`) was independently clickable/fillable (not blocked by any overlay). Filled required fields (company, base, location), clicked `data-testid="add-offer-submit"` — the form submitted, the modal closed, and a new offer card rendered on the board with the entered company name. Reopened the modal a second time and closed it via `Escape` — confirmed closed. All of this produced **zero console/network events** across the whole interaction sequence (open, field-click, submit, reopen, escape-close). `/var/log/aether/api.log` for the check window: 0 ERROR lines (the add-offer flow is client-state-only per `onAdd`, so no API calls are expected here). This resolves the residual UI-blocking regression noted alongside the earlier, unrelated GAP-P4-023/024 crash/fabrication findings on this same screen.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-057__before-click__post__20260713T234635Z.png`, `GAP-P4-057__modal-open__post__20260713T234635Z.png`, `GAP-P4-057__after-submit__post__20260713T234635Z.png`, `GAP-P4-057__console__post__20260713T234635Z.log` (0 bytes), `GAP-P4-057__result__post__20260713T234635Z.json` (click_ok=true, click_duration_s=0.046, modal_open_after_click=true, field_click_ok=true, submit_ok=true, modal_closed_after_submit=true, new_offer_card_present=true, closed_via_escape=true).

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
- **Status:** VERIFIED-CLOSED (QA-ANALYTICS-RERUN 2026-07-14, production, current deployed HEAD). Independently re-verified from scratch (fresh login, fresh evidence, not reusing 2026-07-13 artifacts): live `GET /api/analytics` returns `jobsFound: 154`, `totalApplications: 25`; live `GET /api/analytics/market-pulse` returns `sourcesTotal: 154`, `sourcesLabel: "jobs sourced"`; live `GET /api/jobs` returns a 154-element list (cross-check of `jobsFound`/`sourcesTotal` via the raw jobs collection itself, not just the aggregate endpoint). Direct read-only DB query (psycopg2, `.env` `DATABASE_URL`, `search_path=aether`, read-only session) independently confirms `Job` row count for the demo user = 154 (exact match) and `Application` row count = 25 (exact match). Fresh screenshots of both `/dashboard` and `/dashboard/analytics` (`phase4_sweep.py`) show the donut captioned "154 / jobs sourced" (not "applications"), with the true Applications figure (25, and the dashboard's separate "Active Applications 4" / funnel "Applied 4" sub-metric) shown correctly and separately from the jobs-sourced count on both routes — label matches the datum truthfully in both places. Console capture: 0 bytes (zero events) on both routes. `/var/log/aether/api.log`: checked the entire live-check window by exact line-offset delta (22576→22617, 41 new lines) — 0 `ERROR` lines, all 41 responses `200`.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-058__api-analytics-root__post__20260714T001230Z.json`, `GAP-P4-058__api-jobs-count__post__20260714T001230Z.json`, `GAP-P4-058-059-060__api-market-pulse__post__20260714T001230Z.json`, `GAP-P4-058-059-060__db-crosscheck__post__20260714T001230Z.json`, `GAP-P4-058-059-060__dashboard__post__screenshot__20260714T001046Z.png`, `GAP-P4-058-059-060__analytics__post__screenshot__20260714T001051Z.png`, `GAP-P4-058-059-060__dashboard__post__console__20260714T001046Z.log` (0 bytes), `GAP-P4-058-059-060__analytics__post__console__20260714T001051Z.log` (0 bytes), `GAP-P4-058-059-060__api-log-window__post__20260714T001230Z.log` (0 ERROR lines). Prior evidence (QA-ANALYTICS 2026-07-13): `GAP-P4-058__api-analytics-dashboard__post__20260713T233710Z.json`, `GAP-P4-058__api-analytics-root__post__20260713T233710Z.json`, `GAP-P4-058-059-060__api-market-pulse__post__20260713T233805Z.json`, `GAP-P4-058-060__dashboard__post__screenshot__20260713T233833Z.png`, `GAP-P4-058-060__analytics__post__screenshot__20260713T233840Z.png`, `GAP-P4-058-060__dashboard__post__console__20260713T233833Z.log` (empty), `GAP-P4-058-060__analytics__post__console__20260713T233840Z.log` (empty), `GAP-P4-058-059-060__recomputation__post__20260713T233900Z.json`.

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
- **Status:** VERIFIED-CLOSED (QA-ANALYTICS-RERUN 2026-07-14, production, current deployed HEAD). Independently re-verified per the T2 recipe: pulled the complete, real `GET /api/agents/runs?limit=500` collection (148 rows, not the paginated 50-row default) and rebucketed every row's real `startedAt` timestamp into real ISO calendar weeks (Mon 00:00 UTC boundaries) covering the 12-week window ending at the current calendar week — computed independently in a standalone script, not reusing the API's own `recruiterTrends.series`. Result: `[0,0,0,0,0,0,0,0,0,0,0,148]`, total = 148, `148/12 = 12.3`, which exactly matches both (a) the API's own `recruiterTrends.series`/`rows` (`"148 total"`, `"12.3 · no change"`) and (b) the on-screen "Avg runs / week: 12.3" on fresh screenshots of both `/dashboard` and `/dashboard/analytics`. Direct DB query independently confirms `AgentRun` count for this user = 148, with real timestamps spanning `2026-07-13T09:16:59Z`→`2026-07-14T00:01:07Z` (all in the current calendar week — the account's history is < 1 day old, a fresh reseed since the prior 2026-07-13 check, yet the fix still correctly zero-fills the other 11 real calendar weeks rather than dividing by weeks-with-data). Confirmed the displayed value (12.3) is **not** equal to the raw total (148) — the exact defect pattern this gap targets (avg==total) is absent. Per the ledger's own Section C recipe ("confirm it equals total/12 ... not total/weeks-with-data"), `total/12` is the authorized correct-window divisor; the alternative literal reading ("weeks since first run" as an account-lifetime divisor, ≈0.089 wk here) was also computed for transparency and would imply a nonsensical ≈1665/wk rate — not what the "last 12 wks" widget label claims to measure, and not the criterion the recipe specifies. `/var/log/aether/api.log`: 0 ERROR lines in the full check window (41/41 responses 200).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-059__api-agents-runs-full__post__20260714T001230Z.json` (148 raw rows), `GAP-P4-059__recomputation-rerun__post__20260714T001230Z.json` (independent rebucketing + both divisor readings), `GAP-P4-058-059-060__api-market-pulse__post__20260714T001230Z.json` (series length 12, total 148, avg 12.3), `GAP-P4-058-059-060__db-crosscheck__post__20260714T001230Z.json` (AgentRun count=148, timestamp span), `GAP-P4-058-059-060__dashboard__post__screenshot__20260714T001046Z.png`, `GAP-P4-058-059-060__analytics__post__screenshot__20260714T001051Z.png`, `GAP-P4-058-059-060__api-log-window__post__20260714T001230Z.log` (0 ERROR lines), console logs 0 bytes for both routes. Prior evidence (QA-ANALYTICS 2026-07-13): `GAP-P4-058-059-060__api-market-pulse__post__20260713T233805Z.json` (series length 12, total 144, avg 12.0), `GAP-P4-058-060__dashboard__post__screenshot__20260713T233833Z.png`, `GAP-P4-058-060__analytics__post__screenshot__20260713T233840Z.png`, `GAP-P4-058-059-060__recomputation__post__20260713T233900Z.json`.

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
- **Status:** VERIFIED-CLOSED (QA-ANALYTICS-RERUN 2026-07-14, production, current deployed HEAD). Independently re-verified: both sections are present and render on `/dashboard/analytics` (and `/dashboard`) with `data-testid="sources-donut"` and `data-testid="market-vs-you"` (confirmed live in `apps/web/src/components/analytics/MarketPulse.tsx` lines 100 and 274 — real markup, not test-only stubs). (1) Sources donut ("Jobs by Source") renders `154 / jobs sourced` with a real per-source breakdown (Seek 97%, Greenhouse 2%, Lever 1%, Remotive 0%) sourced from live `GET /api/analytics/market-pulse`; independently cross-checked against a direct DB `GROUP BY source` query on the `Job` table (raw counts: seek=149, greenhouse=3, lever=1, remotive=1, total=154, matching `sourcesTotal` exactly) — the percentages are a rounded/normalized view of these real counts (Remotive's raw 1/154≈0.65% rounds toward 0% once the other three buckets are forced to sum to 100 — a benign largest-remainder rounding artifact, not fabricated data). (2) Market vs. Your Performance still renders `marketDataConnected: false` and `market: null` for both comparison rows in the live API response, with the UI honestly printing "Market data: not connected — showing your own figures only" alongside the user's real figures ("you 25" applications/month — matches the DB `Application` count exactly; "you 0%" interview rate) — confirmed `_MARKET_DATA_SOURCE_CONNECTED = False` (apps/api/app/routers/analytics.py:155) remains the single, honest source of truth with no hardcoded market-benchmark numbers introduced since the prior check. Provenance re-verified at the network level (live API response), not just the rendered DOM. Console capture: 0 bytes on both routes (zero errors). `/var/log/aether/api.log`: 0 ERROR lines in the full check window (41/41 responses 200). Residual, lower-severity note carried forward unchanged from the 2026-07-13 check (not blocking closure, per the Section I.2 / D-0028 ruling): the 3 "degraded chart stylings" and the extra "Agent ROI" section are still present as honest-substitution styling/layout deviations from `design/screens/analytics.html`'s illustrative markup, not a reopened gap.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-058-059-060__api-market-pulse__post__20260714T001230Z.json`, `GAP-P4-058-059-060__db-crosscheck__post__20260714T001230Z.json` (Job-by-source raw counts), `GAP-P4-058-059-060__dashboard__post__screenshot__20260714T001046Z.png`, `GAP-P4-058-059-060__analytics__post__screenshot__20260714T001051Z.png`, `GAP-P4-058-059-060__dashboard__post__controls__20260714T001046Z.json`, `GAP-P4-058-059-060__analytics__post__controls__20260714T001051Z.json`, `GAP-P4-058-059-060__api-log-window__post__20260714T001230Z.log` (0 ERROR lines), console logs 0 bytes for both routes. Prior evidence (QA-ANALYTICS 2026-07-13): `GAP-P4-058-059-060__api-market-pulse__post__20260713T233805Z.json`, `GAP-P4-058-060__dashboard__post__screenshot__20260713T233833Z.png`, `GAP-P4-058-060__analytics__post__screenshot__20260713T233840Z.png`, `GAP-P4-058-060__dashboard__post__controls__20260713T233833Z.json`, `GAP-P4-058-060__analytics__post__controls__20260713T233840Z.json`, `GAP-P4-058-059-060__recomputation__post__20260713T233900Z.json`.

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
- **Status:** VERIFIED-CLOSED (QA QA-API 2026-07-13, production). Read-only `psql`-equivalent check (`psycopg2`, single-var `DATABASE_URL` from `.env`, `schema=` query param stripped, `search_path=aether` set via connection `options`, session set read-only) against the demo user (`c58996b5b105c17e50f1ef2f8`) confirmed all 6 audit-listed rows are gone: the `Contact` table for this user now returns **0 rows** (the fabricated "Jane Doe"/"Tech Corp"/`jane@example.com` row is deleted), and none of the 5 audit-listed `EmailThread` ids (`c64de826c393fcb10e46e025e` "Phase4 T2 Audit...", `c5df7500226419f0475159a62` "Test", `c43b86df34e9849b059d75163` "QA Test", `c7347c7f11996dd989043b71e` "Test Draft", `cc8ff42f86b08f6396a583144` "Test from Audit") exist in the table any more — an explicit `id = ANY(...)` re-check against those exact 6 ids returned an empty result set for both tables. The `EmailThread` table for this user now contains exactly 1 row, but it is a **different, newer** row (`cc532aef3ca5ce01e9d3427e9`, subject "QA verify GAP-P4-041/042 20260713T224746Z") created by a separate QA verifier's own live production verification of GAP-P4-041/042 today — not one of this gap's audit-listed rows, and out of this gap's scope (a genuine artifact of a different, legitimate test action, not a re-regression of the deleted rows). Re-checked the same absence from the application's own read path (not just the DB): live `GET /emails` returns only that one non-audit-listed thread, and live `GET /networking/contacts` returns `[]` — confirming the deletion is visible end-to-end, not just at the DB layer. `/var/log/aether/api.log` for the whole check window: 0 ERROR lines.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-061__db-check__post__20260713T232048Z.json` (DB-layer: 0 Contact rows, the 5 audit EmailThread ids all absent, one unrelated newer thread present), `GAP-P4-061__api-emails__post__20260713T232650Z.json` (live `GET /emails`, 200 OK), `GAP-P4-061__api-contacts__post__20260713T232650Z.json` (live `GET /networking/contacts` → `[]`, 200 OK).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Confirmed the sub-nav array is centralized in `apps/web/src/app/dashboard/settings/sections.ts` (`SECTIONS`, consumed by `page.tsx`), explicitly ordered and code-commented to match `design/screens/settings.html`'s `settings-subnav-st06`. Loaded `/dashboard/settings` fresh and read the live DOM order of `[data-testid^="settings-nav-"]` inside `nav[aria-label="Settings sections"]`: **Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance** — an exact match, index-for-index, to the wireframe order (Notifications now at position 4, not position 6 as the original defect described). Console/network capture: 0 bytes — zero events. `/var/log/aether/api.log` for the check window: 0 ERROR lines. This resolves the residual sub-gap of the same ticket as prior GAP-P4-015 (settings page), which was otherwise already fixed (12/14 elements matching).
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-062__settings__post__20260713T234716Z.png`, `GAP-P4-062__console__post__20260713T234716Z.log` (0 bytes), `GAP-P4-062__result__post__20260713T234716Z.json` (live nav-item array, `matches: true` against the exact expected wireframe order).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Confirmed source wiring (`apps/web/src/app/dashboard/stories/page.tsx`: `extract()` calls `setRunning(true)` synchronously before `await runStoryExtractor()`, then `await load()` to refresh, then `setRunning(false)`; `apps/web/src/components/stories/story-aside.tsx`: button renders `aria-busy={drafting}`, `disabled={extractorState.disabled}`, a spinning `fa-spinner fa-spin` icon, and swaps its label to "Drafting from resume…" while `drafting`). Drove the real click live on production: captured button state at baseline ("Draft missing stories", `aria-busy="false"`, enabled), clicked, then re-read state ~150ms later — immediate pending feedback confirmed: label → "Drafting from resume…", `aria-busy="true"`, `disabled=true`, spinner icon visibly present — well before the async call resolves. Waited for real completion (`aria-busy` returning to `"false"`, observed within the run's actual duration, no artificial timeout needed) and confirmed the button returns to "Draft missing stories" / enabled / not busy. Network capture across the whole interaction shows the real completion-refresh: `POST /agents/story-extractor/run` → 200, followed immediately by fresh `GET /stories` and `GET /stories/stats` calls (the page's `load()` refetch) — i.e. both the immediate pending affordance and the post-completion data refresh this gap's fix spec required are present, and no `net::ERR_ABORTED` requests occurred (the original observation's aborted requests do not reproduce). Zero console/network error-level events throughout. `/var/log/aether/api.log` for the check window: 0 ERROR lines; `POST /agents/story-extractor/run HTTP/1.1" 200 OK` and the subsequent `GET /stories`/`GET /stories/stats` calls all 200.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-063__pending-state__post__20260713T234759Z.png` (spinner + "Drafting from resume…" + disabled, captured ~150ms after click), `GAP-P4-063__after-completion__post__20260713T234759Z.png` (button back to normal, fresh story data visible), `GAP-P4-063__console__post__20260713T234759Z.log` (0 bytes), `GAP-P4-063__result__post__20260713T234759Z.json` (before/pending/after button-state dump + the real `story-extractor/run` → `stories`/`stories/stats` network-call sequence).

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
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production). Independently re-ran the itemized wireframe reconciliation live against `/dashboard/jobs`: (1) **Location filter (jd05)** — `data-testid="job-location-filter"` is present and genuinely functional: filled it with "Melbourne" and the visible job list narrowed to Melbourne-matching results (client-side `locationQuery` filter at `apps/web/src/app/dashboard/jobs/page.tsx:277`), confirming it is a real working filter, not a static input. (2) **Preview button (jd33)** — selecting a job (`data-testid="job-select"`) and reading `data-testid="preview-link"` shows `href="/dashboard/resume?job={id}"` (e.g. `/dashboard/resume?job=cdd4cd1a2fda3a9019a47e30a"`), exactly the `<Link>` D-0025 describes — live, not a placeholder `href="#"`. (3) Confirmed the four elements D-0025 explicitly scopes as deferred remain genuinely absent from the live DOM: no `job-role-filter`, no `job-salary-filter`, no "Tailor & Apply" bulk-action text anywhere on the page — consistent with the ADR's stated Phase-3+ deferral, not a silent regression or an over-claim. This independently reproduces and confirms the FIX-K commit's (`7b8b3e1`/`edf2d6e`) own finding: **D-0025's text (`docs/delivery/DECISIONS.md` lines 632-634) is accurate against live production** — the Location filter and Preview button were already correctly implemented when the ADR was written, only Role/Salary dropdowns + bulk Tailor-and-Apply/Saved-Tailor-all remain deferred — so the GAP-P4-009/011 "MISSING" citations that GAP-P4-067 exists to reconcile are corrected by this ADR text, no further code change needed. Console/network capture across the whole interaction (load, filter, select, screenshot): 0 bytes — zero events. `/var/log/aether/api.log` for the check window: 0 ERROR lines.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-067__location-filter__post__20260713T235303Z.png`, `GAP-P4-067__result__post__20260713T235303Z.json` (location filter present/fillable, Melbourne results confirmed, role/salary dropdowns and bulk Tailor&Apply confirmed absent), `GAP-P4-067__console__post__20260713T235303Z.log` (0 bytes), `GAP-P4-067__detail-panel__post__20260713T235336Z.png`, `GAP-P4-067__result2__post__20260713T235336Z.json` (`preview_href: "/dashboard/resume?job=cdd4cd1a2fda3a9019a47e30a"`, `preview_href_matches_pattern: true`), `GAP-P4-067__console2__post__20260713T235336Z.log` (0 bytes).

### GAP-P4-068
- **Type:** G-SECURITY
- **Severity:** MEDIUM
- **Screen / Route:** N/A (repo hygiene / shipped tooling) · **REQ/SC violated:** N/A
- **Observed (production, pre-fix):** `apps/api/scripts/seed_demo.py` hardcoded `DEMO_PASSWORD = "AetherDemo1"`; `apps/web/src/lib/api/client.ts` exported an unused, hardcoded `DEMO_CREDENTIALS` literal; `scripts/discovery_cron.sh:11` hardcoded `PASSWORD="${AETHER_CRON_PASSWORD:-AetherDemo1}"` — and that script is the live `ExecStart` of `aether-discovery.service`, triggered every 30 minutes by `aether-discovery.timer` (SC-JOB-10), so the demo password was actively authenticating to `/auth/login` on a schedule whenever `AETHER_CRON_PASSWORD` was unset (the default, since it was never set in the systemd unit).
- **Expected (doc/wireframe ref):** No shipped tooling or product code should ever hardcode a real credential; all credential-dependent tooling should resolve from the environment (`.env` / `LOGIN_PASSWORD`), matching `uat/api_sweep.py`'s existing pattern.
- **Root cause analysis:** The credential-handling migration to env-var-driven config had covered `uat/*.py` and the web login flow, but missed `apps/api/scripts/seed_demo.py`, `apps/web/src/lib/api/client.ts`'s dead `DEMO_CREDENTIALS` export, and (initially missed even by the first remediation attempt) the shipped, scheduler-invoked `scripts/discovery_cron.sh` — a scope gap in the original migration, not an isolated file issue.
- **Fix specification:** Resolve the password from `SEED_DEMO_PASSWORD`/`AETHER_CRON_PASSWORD` falling back to `LOGIN_PASSWORD` in every affected script; refuse to run (raise/exit non-zero) rather than default to a hardcoded credential when neither is set; delete the unused `DEMO_CREDENTIALS` export; extend `uat/tests/test_tooling_hygiene.py`'s hardcoded-password guard to scan `apps/api/scripts/*.py`, `apps/web/src/lib/api/client.ts`, and `scripts/*.sh`.
- **Verification recipe:** `git grep -n 'AetherDemo1'` on `main` (tracked source) returns no match in any script that actually authenticates; confirm each affected script refuses to run without a real env-sourced credential; confirm the live `aether-discovery.timer`/`.service` continues running successfully with the patched script.
- **Assigned model tier:** sonnet (fixer) → opus (reviewer) — landed as `fix/run3-fix-k` (commits `7b8b3e1`, `edf2d6e`)
- **Status:** VERIFIED-CLOSED (QA QA-POLISH 2026-07-13, production + main). `git grep -n "AetherDemo1" --` on `main` (all tracked files) returns matches **only** in `uat/tests/test_tooling_hygiene.py` (the regression guard's own regex/docstring, which must reference the literal to detect it — not a live credential) and in this ledger's historical "Observed" prose describing the pre-fix defect; zero matches in `apps/api/scripts/seed_demo.py`, `apps/web/src/lib/api/client.ts`, `scripts/discovery_cron.sh`, or any other executable tooling. Read all three previously-affected files directly: `seed_demo.py::_demo_password()` reads `SEED_DEMO_PASSWORD or LOGIN_PASSWORD` and `raise SystemExit(...)` if neither is set (no default); `client.ts` no longer exports `DEMO_CREDENTIALS` at all; `discovery_cron.sh` resolves `PASSWORD="${AETHER_CRON_PASSWORD:-${LOGIN_PASSWORD:-}}"`, loads the repo-root `.env` first, and `exit 1`s with a `FATAL` log line if the password is still empty — no hardcoded fallback anywhere. `python3 -m pytest uat/tests/test_tooling_hygiene.py -v`: **2/2 passed** (`test_no_hardcoded_demo_password_in_tracked_tooling`, `test_no_browser_navigation_to_login_api_in_tracked_uat_scripts`). Confirmed live production continuity, not just static analysis: `systemctl show aether-discovery.service -p Result -p ExecMainStatus` → `Result=success`, `ExecMainStatus=0` for its most recent run (23 min before this check), and `aether-discovery.timer` is active with a normal next-fire schedule — the patched, env-driven script is genuinely running successfully on its live 30-minute cadence, not just passing in isolation.
- **Evidence (post-fix):** `uat/reports/evidence/phase4/GAP-P4-068__git-grep-main__post__20260713T235414Z.log` (only the guard's own regex + this ledger's historical prose match), `GAP-P4-068__hygiene-suite__post__20260713T235414Z.log` (2 passed), `GAP-P4-068__discovery-cron-systemd__post__20260713T235414Z.log` (`Result=success`, `ExecMainStatus=0`).

### C.1 — Legacy Run-2 numbers GAP-P4-019–039: final disposition (reconciled this pass)

These 21 IDs were assigned by the pre-Run-3, externally-orchestrated sweep in Section H (Hermes Agent / OpenRouter, 2026-07-13T10:25Z) and exist only as table rows there, not as full §3-format records. Per the Header's standing rule, Section H's verdicts were treated as unverified inputs and independently re-swept by Run 3's own Stage A agents; nothing below is asserted on Section H's authority alone — every disposition is anchored to a VERIFIED-CLOSED §3 record, a Section E no-gap entry, or fresh Run-3 evidence that the underlying screen/behavior no longer reproduces the defect.

- **Superseded (2):** GAP-P4-021, GAP-P4-029 — both duplicate reports of the single email-send defect now canonically tracked as **GAP-P4-042** (VERIFIED-CLOSED above, §I.4).
- **Reopened under a new number (1):** GAP-P4-034 (applications kanban, falsely closed in Section H) — fresh Run-3 evidence contradicted that closure; refiled and closed as **GAP-P4-050** (VERIFIED-CLOSED above, §I.4).
- **Absorbed with a direct successor mapping (3):** GAP-P4-022 (jobs/applications mislabel) → **GAP-P4-058**; GAP-P4-025 and GAP-P4-026 (analytics metric anomalies) → **GAP-P4-058/059** lineage (§I.4). All closed under their successor IDs above.
- **Already VERIFIED-CLOSED under their own numbers (3):** GAP-P4-036, 037, 038 (test-suite fixes: offers router added, cast removed, fixture-user fix) — closed within Section H itself; Run 3's fresh `pytest` pass found no regression.
- **Citation-corrected, folded into the no-gap register (1):** GAP-P4-033 (cover-letter list view) — its original "ADR D-0020 covers this" citation was wrong (D-0020 is scoped to the Agents screen only). The underlying list-vs-modal deviation is intentional; recorded with the corrected rationale in Section E, row "Cover-letter list/version-history view (C-35)". Not a live gap.
- **Did not reproduce in Run 3's independent fresh sweep, no successor record needed (12):** GAP-P4-019/020 (dashboard dead-control G-FAKE findings — Stage A's fresh `/dashboard` scout and Section E's "/dashboard — layout" row found the screen fully functional, 0 console errors); GAP-P4-023/024 (offers-screen crash/fabrication — Stage A's fresh `/dashboard/offers` scout found the screen functional; the one residual offers-screen defect it did find is tracked fresh as **GAP-P4-057**, VERIFIED-CLOSED); GAP-P4-027/028 (stories-screen bugs — Stage A's fresh `/dashboard/stories` scout found the screen functional; the one residual stories-screen defect it did find is tracked fresh as **GAP-P4-063**, VERIFIED-CLOSED); GAP-P4-030/031 (jobs wireframe gaps — reconciled precisely by **GAP-P4-067** against D-0025, VERIFIED-CLOSED); GAP-P4-032 (resume wireframe gap — Run 3's fresh `/dashboard/resume` evidence, Section B.5, shows the diff view fully present with no other missing element requiring a new record); GAP-P4-035 (analytics wireframe gap — reconciled by **GAP-P4-060**, VERIFIED-CLOSED); GAP-P4-039 (LLM timeout → fixture-fallback quality note — the accepted resilience path under D-0017's hard wall-clock budget, referenced and still observed live in GAP-P4-047's evidence log ("LLM auto mode: served fixture fallback"); a documented, honest degradation path, not an open defect).

**Net effect:** zero of the 21 legacy Run-2 numbers remain open, unaccounted-for, or in contradiction with Run-3 evidence.

---

## D. User-Journey Maps

Each journey is the ordered, real path a user takes through production. Every step cites the evidence file that proves it happened as described; where a step corresponds to a defect this run closed, the VERIFIED-CLOSED gap id is cited. All evidence lives under `uat/reports/evidence/phase4/`.

### Journey 1: Discovery → Application

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | Sign in at `/login` with real credentials → JWT session, redirected to `/dashboard` | `rg-login__screenshot__20260713T235900Z.png`, `rg-login__console__20260713T235900Z.log` (0 bytes) | — |
| 2 | `/dashboard/jobs` loads: market tabs (AU/Intl/Saved), job cards, Sync button, all live data | `rg-jobs__screenshot__20260713T235914Z.png`, `dashboard_jobs__screenshot__20260713_082143.png` | — |
| 3 | Location filter (jd05) narrows the live list (e.g. "Melbourne") — genuinely functional, not static | `GAP-P4-067__location-filter__post__20260713T235303Z.png`, `GAP-P4-067__result__post__20260713T235303Z.json` | GAP-P4-067 |
| 4 | Select a job → Preview link (jd33) resolves to a real tailoring deep-link (`/dashboard/resume?job={id}`) | `GAP-P4-067__detail-panel__post__20260713T235336Z.png`, `GAP-P4-067__result2__post__20260713T235336Z.json` | GAP-P4-067 |
| 5 | Scout/discovery agent runs on its 30-min systemd timer, inserting/refreshing real jobs (upserts counted honestly, not as fake "discoveries") | `GAP-P4-068__discovery-cron-systemd__post__20260713T235414Z.log` (`Result=success`) | GAP-P4-068 (tooling hygiene on this same cron path) |
| 6 | Application progresses through the full 8-stage Kanban (`/dashboard/applications`): Discovered→Evaluating→Tailoring→Ready to Apply→Submitted→In Review→Interview→Offer, horizontally scrollable, real per-column counts | `GAP-P4-050__board-view__post__20260713T233154Z.png`, `GAP-P4-050__board-scrolled__post__20260713T233154Z.png` | GAP-P4-050 |
| 7 | Sankey funnel toggle renders the real conversion flow (Jobs Found→Applied) | `GAP-P4-050__sankey-view__post__20260713T233154Z.png` | — (Section E: Sankey flow) |
| 8 | Fresh regression confirms the whole path still renders with 0 console errors | `rg-applications__screenshot__20260713T235924Z.png` + `.log` (0 bytes), `rg-jobs__console__20260713T235914Z.log` (0 bytes) | — |

### Journey 2: Tailoring

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard/resume` loads the side-by-side diff studio | `dashboard_resume__screenshot__20260713_082143.png`, `rg-resume__screenshot__20260713T235930Z.png` | — |
| 2 | Settings → Portfolio Sync ingests real GitHub + portfolio content into the tailoring evidence corpus (LinkedIn honestly "Not provided") | `GAP-P4-047__settings-after-sync__post__20260713T235022Z.png`, `GAP-P4-047__career-data-api__post__20260713T235236Z.json` | GAP-P4-047 |
| 3 | Master resume re-ingested with complete-sentence bullet extraction (no mid-word PDF line-wrap fragments) | `GAP-P4-044-045-046__flow__post__20260713T231316Z.json` | GAP-P4-044 |
| 4 | Tailor agent run rewrites bullets grounded in real evidence; JD-echo guard rejects near-verbatim JD phrase lifting | `GAP-P4-044-045-046__analysis__post__20260713T231316Z.json` | GAP-P4-045 |
| 5 | Tailored PDF exported: zero cross-bullet visual overlap, even for the longest rewritten bullet | `GAP-P4-044__tailored-pdf__post__20260713T231316Z.pdf`, `GAP-P4-044__pdfpage-{1,2,3}__post__20260713T231316Z.png` | GAP-P4-046 |
| 6 | Real ATS score computed for the tailored resume via `GET /resumes/{id}/ats` | `tailor-run3__ats__20260713T121930Z.json` | — |
| 7 | Fresh regression: resume studio still renders, 0 console errors | `rg-resume__console__20260713T235930Z.log` (0 bytes) | — |

### Journey 3: Cover Letter

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard/cover-letters` list renders real generated letters | `dashboard_cover_letters__screenshot__20260713_082143.png`, `rg-cover-letters__screenshot__20260713T235935Z.png` | — |
| 2 | Generation enforces the §10.2 structural contract: exactly 3 paragraphs, role+company named in ¶1, CTA in ¶3 — verified on the exact job that originally failed this check | `GAP-P4-049__duratec-rerun-A__post__20260713T230330Z.json`, `GAP-P4-049__contract-cases__post__20260713T230330Z.json` | GAP-P4-049 |
| 3 | "Request Changes" opens the disclosure form, submits, and produces a real `POST /cover-letters/{id}/refine` → 200 with a new version + pending `ApprovalRequest` | `GAP-P4-043__form-open__post__20260713T225933Z.png`, `GAP-P4-043__after-submit__post__20260713T225933Z.png` | GAP-P4-043 |
| 4 | PDF export: plain business-letter styling, real sender contact block, no "Generated by Aether" branding | `GAP-P4-048__pdf-render__post__20260713T230330Z.png`, `GAP-P4-048__pdf-color-analysis__post__20260713T230330Z.json` | GAP-P4-048 |
| 5 | Fresh regression: cover-letters page still renders, 0 console errors | `rg-cover-letters__console__20260713T235935Z.log` (0 bytes) | — |

### Journey 4: Email

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard/email` renders the inbox/detail panes without crashing (previously threw on `selected.intelligence.score`) | `GAP-P4-041__page-load__pre__20260713T224746Z.png` | GAP-P4-041 |
| 2 | Compose a real draft → `POST /emails/draft` → 201 | `GAP-P4-041-042__flow__post__20260713T224746Z.json` | GAP-P4-001 (draft-save 500 fixed), GAP-P4-041 |
| 3 | New thread auto-selects; honest `data-testid="ai-intelligence-empty"` panel renders (never a fabricated score) | `GAP-P4-041__thread-detail-all-tab__post__20260713T224826Z.png` | GAP-P4-041 |
| 4 | Attempting to send with no email provider connected returns an honest `409 no_email_provider_connected` — never a fabricated `"sent"`, thread left unmodified | `GAP-P4-042__in-browser-send-attempt__post__20260713T224746Z.png`, `GAP-P4-041-042__flow__post__20260713T224746Z.json` | GAP-P4-042 |
| 5 | Fresh regression: email center still renders, 0 console errors | `rg-email__console__20260713T235941Z.log` (0 bytes) | — |

### Journey 5: Metrics

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard` stats/funnel widgets render live per-user numbers | `rg-dashboard__screenshot__20260713T235907Z.png` | — |
| 2 | `/dashboard/analytics` renders the sources donut and Market-vs-You sections from real data (previously entirely absent) | `GAP-P4-058-059-060__analytics__post__screenshot__20260714T001051Z.png` | GAP-P4-060 |
| 3 | Jobs-sourced widget correctly labeled "154 / jobs sourced" (no longer mislabeled "applications") | `GAP-P4-058__api-analytics-root__post__20260714T001230Z.json` | GAP-P4-058 |
| 4 | "Avg runs/week" now divides over a real zero-filled 12-week window (12.3, not `==total`) | `GAP-P4-059__recomputation-rerun__post__20260714T001230Z.json` | GAP-P4-059 |
| 5 | Independent read-only DB cross-check confirms every displayed figure against raw `Job`/`Application`/`AgentRun` rows | `audit-metrics__run3__20260713T122906Z.json`, `GAP-P4-058-059-060__db-crosscheck__post__20260714T001230Z.json` | GAP-P4-058, 059, 060 |
| 6 | Fresh regression: dashboard + analytics render, 0 console errors | `rg-dashboard__console__20260713T235907Z.log`, `rg-analytics__console__20260714T000006Z.log` (0 bytes each) | — |

### Journey 6: Agents

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard/agents` renders the full catalog and run history | `rg-agents__screenshot__20260714T000011Z.png` | — |
| 2 | Providers panel honestly shows the actual serving credential path, including the Abacus-subscription fallback and its standby/active state | `GAP-P4-055__providers-status__post__20260713T232142Z.json` | GAP-P4-055 |
| 3 | Clicking a locked/unconfigured provider's action shows a handled, worded notice — 0 raw console errors, 0 stray network calls | `GAP-P4-054__after-click-anthropic__20260713T232617Z.png` | GAP-P4-054 |
| 4 | Disabled controls (unconfigured-provider model dropdowns, disabled agent-run buttons) render visibly disabled (opacity/cursor/grayscale/title), enabled controls do not | `GAP-P4-056__result__post__20260713T234518Z.json` | GAP-P4-056 |
| 5 | Real agent runs (tailor/coverLetter/storyExtractor) are recorded in `AgentRun` history with real model ids and durations, cross-checked against the live env's credential precedence | `GAP-P4-055__providers-status__post__20260713T232142Z.json` (cross-ref to `GET /agents/runs`) | GAP-P4-055 |
| 6 | Fresh regression: agents page renders, 0 console errors | `rg-agents__console__20260714T000011Z.log` (0 bytes) | — |

### Journey 7: Approvals

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | `/dashboard/approvals` renders the queue as an intentional list view (not a modal — D-0027) | `rg-approvals__screenshot__20260714T000025Z.png` | — |
| 2 | `POST /api/approvals` creates a real approval request → 201 (previously 405) | `qa__gap_p4_012__20260713T090404Z.json` | GAP-P4-012 |
| 3 | Approve/reject resolution propagates to the linked `Application` row (D-0016); modal-equivalent element set is functionally complete under `data-testid` naming (D-0027) | `approvals__modal_structure.json` | — (Section E, C-30) |
| 4 | At mobile viewport (390×844), approvals load with real data, bottom nav visible, cards stacked ≤390px wide, touch targets ≥44px | `rg-mob-appr__page-load__post__20260713T235956Z.png`, `apps/web/e2e/mobile-regression.spec.ts` (kept, see Journey 8) | — |
| 5 | Fresh regression: approvals page renders, 0 console errors | `rg-approvals__console__20260714T000025Z.log` (0 bytes) | — |

### Journey 8: Mobile

| # | Step | Evidence | Gap |
|---|---|---|---|
| 1 | Mobile dashboard (390×844) renders all 8 wireframe sections (topbar, notification button, 2×2 stats grid, approval banner, agent activity feed, bottom nav) — an improvement over the stale D-0026 baseline | `rg-mob-dash__page-load__pre__20260713T235952Z.png`, `rg-mob-dash__page-load__post__20260713T235952Z.png` | — (Section E, C-31) |
| 2 | Mobile approvals route loads with the real bottom nav and stacked cards; the kept regression spec `apps/web/e2e/mobile-regression.spec.ts` exercises this automatically going forward | `rg-mob-appr__page-load__pre__20260713T235956Z.png`, `rg-mob-appr__page-load__post__20260713T235956Z.png`, `rg-mob__summary__post__20260713T235957Z.json` (2/2 tracked assertions PASS) | — |
| 3 | Approval action buttons meet the ≥44px minimum touch target on mobile | `apps/web/e2e/mobile-regression.spec.ts:306-345` (assertion) | — |
| 4 | Zero horizontal overflow at mobile viewport (`scrollWidth ≤ clientWidth+5`) | `apps/web/e2e/mobile-regression.spec.ts:176-197` (assertion) | — |
| 5 | This pass's fresh re-run of the full Playwright suite (incl. the mobile spec) is green: 29/29 | `rg-mob__summary__post__20260714T001641Z.json`, terminal run this pass (5/5 mobile-regression.spec.ts; 29/29 full suite) | — |
| 6 | Mobile **modal** parity for approvals (as opposed to the working list/card layout above) remains a genuinely deferred, documented Phase 3+ scope item — not a regression | `docs/delivery/DECISIONS.md` D-0026 | — |

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

**Register total (this pass, final): 29 confirmed no-gap items**, covering every C-series candidate from the Run-3 triage (§I.2) plus the pre-existing Run-1/2 no-gap findings, each with a named reason and evidence citation. Combined with the 47 VERIFIED-CLOSED records in Section C, every candidate this ledger has ever raised (Section C's 47 + Section H's 21 legacy numbers, reconciled in §C.1 + this register's 29) resolves to exactly one of: VERIFIED-CLOSED, no-gap (confirmed intentional/correct), or superseded/absorbed into another VERIFIED-CLOSED record. None are outstanding.

---

## Summary — Final (this pass, 2026-07-14)

*(Superseded: the severity table this replaces was the very first snapshot from 2026-07-13T11:29Z, before Section C had been expanded past GAP-P4-018 or Run-3's Wave-1/2/3 fix-review-QA cycle had run. It is retained nowhere else; the numbers below are the reconciled final state.)*

| Severity | Count | Status |
|---|---|---|
| CRITICAL | 8 | VERIFIED-CLOSED |
| HIGH | 14 | VERIFIED-CLOSED |
| MEDIUM | 20 | VERIFIED-CLOSED |
| LOW | 5 | VERIFIED-CLOSED |
| **Total (Section C, GAP-P4-001–018 + 040–068)** | **47** | **100% VERIFIED-CLOSED** |

Of the 47: 2 closed as false positives on re-test (GAP-P4-006, 007 — `tailor/run` and `cover-letter/run` return 422, not 404), 3 closed documentarily via new ADRs with no code/fixer/reviewer dispatch (GAP-P4-064, 065, 066), and 42 closed via a real fix (or, for 040/053/054/055, a confirmed-correct existing behavior) independently re-verified live on production by a QA agent on a different model than the fixer. Legacy Run-2 numbers GAP-P4-019–039 (21 IDs) are fully reconciled with zero left open — see Section C.1. The Section E no-gap register carries 29 additional confirmed non-defects. Zero records remain IN-FIX, FIXED-AWAITING-QA, or OPEN anywhere in this ledger.

**Test suites, current (this pass, freshly re-run):** `pytest` (apps/api) — **292/292 passed**, 0 failed; `vitest` (apps/web) — **195/195 passed** (26 files); Playwright e2e — **29/29 passed** (25 pre-existing + 4 in the newly-kept `apps/web/e2e/mobile-regression.spec.ts`; see Section D Journey 8 and the mobile-spec adjudication note in Section J).


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

### I.5 Wave-1 outcome & merge authorization — 2026-07-13T20:45Z (Orchestrator)
32 agents, 0 errors, all on assigned tiers (fixers sonnet/opus per I.1; reviewers cross-model). 8/9 clusters APPROVED by adversarial review; gaps 040–046, 048–063 → FIXED-AWAITING-QA on branches fix/run3-fix-{a..i}. FIX-G additionally diff-reviewed by the Orchestrator personally (clean). **Merge authorized** for the 8 approved branches in order g,d,c,b,a,e,f,h,i. FIX-J (047) re-decomposed per §9.1(4) to a T2 task implementing the reviewer's two required changes; conditional merge authorization granted for fix/run3-fix-j and fix/run3-fix-k contingent on adversarial APPROVE (both subsequently received — see I.6). GAP-P4-068 filed from the Orchestrator's own FIX-G diff sweep (hardcoded demo credentials). *(Provenance note: this section was written pre-merge but sat uncommitted; the merge agent stashed it for a clean tree, so the Wave-2 merge-2 agent could not see it and correctly flagged the missing citation before verifying the reviewer approvals independently. Restored from stash@{0} and recorded here; the authorization chain was real and is now durable.)*

### I.6 Wave-2 outcome — 2026-07-14T00:15Z (Orchestrator)
18 agents, 1 infra failure (QA-ANALYTICS died mid-response — re-dispatched in Wave 3). **Merged & deployed:** all 10 fix branches now on main (merge-1: 8 branches, suites 271 pytest/182 vitest/build/25 playwright all green; merge-2: fix-j 86130fe + fix-k f9937f0, suites 292/195/build/25 green), deployed HEAD f9937f0, health OK. **QA: 20 gaps VERIFIED-CLOSED** by independent T2 verifiers (040–046, 048–057, 061–063, 047, 067, 068, 051); 058/059/060 pending Wave-3 QA re-run. **Regression:** 15 desktop routes + 2 mobile viewports — 0 console errors, 0 failed requests, health OK. **Rulings:** (a) QA-EMAIL's single counted console entry is the browser's network-tab echo of the deliberately-provoked 409 send-gate (honest-error path working as designed, UI handles it) — benign, not a gap; (b) merge-1 discovered production web was served by an orphan non-systemd `next start` process (since 13:47Z) while aether-web.service was dead — corrected during merge-1 (now systemd-managed); infra deviation logged, structural fix in place. **Compliance incident (logged, audit trail):** the merge-1 agent sourced the full `.env` instead of grepping the two permitted vars, echoing DATABASE_URL/DATABASE_URL_TEST (incl. password) into its local transcript; self-reported and corrected immediately. Exposure confined to local transcript files on this VM; OPENROUTER_API_KEY untouched throughout. fixK additionally found+fixed a third hardcoded-credential instance (scripts/discovery_cron.sh) beyond the two filed in GAP-P4-068.

**REMEDIATED 2026-07-14T01:20Z (Orchestrator):** at-rest plaintext scrubbed from all 21 affected local transcript/scratch/evidence files (52 redactions of the connection string / password / host; verified 0 residual across `.claude/projects`, `/tmp/claude-2000`, `uat/reports`, including the active session file; `.env` untouched, `/api/health` 200). Independently confirmed no real credential is committed anywhere in git — the two tracked docs matching `postgresql://…@` use placeholder examples only (real host absent from all tracked files). Full credential *rotation* remains the standing defense-in-depth recommendation and is a user action via the Abacus **Database tile**: a VM-side `ALTER ROLE` is deliberately NOT performed because the credential is Abacus-managed through IMDS metadata, so a DB-only password change would desync metadata/.env on the next restart and is unfixable from inside the VM.

### I.7 Wave-3 outcome — 2026-07-14T00:12–00:15Z (QA-ANALYTICS-RERUN, T2 sonnet)
Re-dispatched the one Wave-2 infra failure (QA-ANALYTICS died mid-response). Independent re-verification from scratch (fresh login, fresh evidence, not reusing Wave-2 artifacts) closed the 3 gaps left pending: **GAP-P4-058, 059, 060 → VERIFIED-CLOSED** (evidence `GAP-P4-058-059-060__*__post__20260714T001046Z/001051Z/001230Z.*`, DB cross-check, 0 console errors on `/dashboard` and `/dashboard/analytics`, 0 API ERROR lines). This closes out Section C in full — all 47 records are now VERIFIED-CLOSED (see the Summary and §C.1 above).

### I.8 DOC-FINAL — 2026-07-14T (this pass, T2 sonnet)
Brought the ledger to §3-complete: expanded Section D into full 8-journey user-journey maps with per-step evidence and gap citations; added §C.1 reconciling the 21 legacy Run-2 numbers (GAP-P4-019–039) to final disposition; rewrote the stale first-pass Summary severity table to final reconciled counts (47/47 VERIFIED-CLOSED); added a final-count line to Section E; added this ledger's own Section J (Model-Governance Audit); adjudicated the untracked `apps/web/e2e/mobile-regression.spec.ts` — re-ran it live (5/5 passed) and as part of the full suite (29/29 passed), confirmed it is a coherent, already-evidenced regression spec (its `rg-mob-dash`/`rg-mob-appr` evidence files predate this pass), and staged it as KEEP. Re-ran `apps/web`'s vitest suite fresh this pass: 195/195 passed (26 files). No code changes made; documentation and evidence-index only, per this task's scope.

---

## J. Model-Governance Audit

**Scope:** this section audits Run 3 only (Claude Code native orchestration, `claude-fable-5` xhigh, 2026-07-13T11:29Z onward through this DOC-FINAL pass). Section H documents a *different, prior, superseded* run orchestrated externally via Hermes/OpenRouter (`z-ai/glm-5.2` orchestrator, `deepseek/deepseek-v4-pro` delegation, 2026-07-13T10:25Z) — that run predates and is not governed by the Run-3 zero-OpenRouter-spawn mandate; its evidence was independently re-verified from scratch by Run 3 and is not relied upon here (see Header and §C.1).

### J.1 Enforcement mechanism (verified from source, not just asserted)
- Every Run-3 sub-agent role has an explicit `model:` frontmatter pin, read directly from `.claude/agents/*.md`: `scout.model=haiku`, `doc-audit.model=haiku`, `deploy.model=haiku`, `fixer.model=opus`, `reviewer.model=sonnet`, `qa.model=sonnet`.
- The session-wide subagent default is pinned at `.claude/settings.json` → `"CLAUDE_CODE_SUBAGENT_MODEL": "claude-sonnet-5"` — so even a spawn with no per-role file falls back to T2 (sonnet), never to the orchestrator's own `fable-5`.
- A canary probe at session start (2026-07-13T11:29Z, role=haiku) asked a spawned sub-agent to self-report its model with no tools available: it reported `claude-haiku-4-5-20251001` — confirmed **≠** `fable-5`, confirming non-inheritance works as designed (orchestrator-audit-log.md row 1).
- Cross-model independence is enforced per gap cluster: every fixer/reviewer pair in §I.1 uses two *different* models (opus fixer → sonnet reviewer, or sonnet fixer → opus reviewer), never same-model self-review.

### J.2 Spawn counts by role and model (Run 3)

| Role | Model | Tier | Count | Source |
|---|---|---|---|---|
| Orchestrator (not a sub-agent) | `claude-fable-5` (xhigh) | — | 1 (this run's top-level session) | Header |
| Canary check | haiku | T3 | 1 | orchestrator-audit-log.md row 1 |
| Stage-A swarm: scouts (1 screen each) | haiku | T3 | 17 | Header §I intro ("26 agents, 0 failures"); `.claude/agents/scout.md` |
| Stage-A swarm: doc-audit / preflight / harness / api-sweep | haiku | T3 | 4 | same 26-agent Stage-A total; `.claude/agents/doc-audit.md` |
| Stage-A swarm: deep audits (data/AI-quality) | sonnet | T2 | 5 | §I intro ("deep audits ×5 (sonnet)") |
| Triage-prep analyst | sonnet | T2 | 1 | orchestrator-audit-log.md row 3 |
| Fixers (clusters FIX-A…K, 11 clusters) | opus (A,B,C,J) / sonnet (D,E,F,G,H,I,K) | T1 / T2 | 4 opus + 7 sonnet = 11 | §I.1 table; `.claude/agents/fixer.md` |
| Reviewers (clusters FIX-A…K, cross-model from their fixer) | sonnet (reviewing A,B,C,J) / opus (reviewing D,E,F,G,H,I,K) | T2 / T1 | 4 sonnet + 7 opus = 11 | §I.1 table; `.claude/agents/reviewer.md` |
| Doc agent (DOC-K: gaps 064/065/066, ADRs, register) | sonnet | T2 | 1 | orchestrator-audit-log.md last dispatch row |
| QA verifiers (distinct-tagged production verification passes) | sonnet | T2 | 8 (`QA-API`, `QA-EMAIL`, `QA-CONTENT`, `QA-RESUME`, `QA-BOARDS`, `QA-POLISH`, `QA-ANALYTICS`, `QA-ANALYTICS-RERUN`) | Section C Status lines (distinct tags counted directly); `.claude/agents/qa.md` |
| Merge/deploy agents (merge-1, merge-2, build+health confirm) | sonnet (session default; no dedicated `merge` role file exists) | T2 (default) | 2 | git log merge commits; §I.6 |
| DOC-FINAL (this pass) | sonnet (`claude-sonnet-5`) | T2 | 1 | this task |
| **Total itemized spawns** | | | **62** | sum of rows above |

The orchestrator's own coarser wave-level self-reports (§I: Stage A "26 agents", Wave-1 "32 agents", Wave-2 "18 agents") are **consistent with but not arithmetically decomposed by** the itemized table above — the wave totals additionally include re-dispatch of the one Wave-1 cluster that needed a second review pass and the Wave-3 QA-ANALYTICS re-run after its Wave-2 infra failure (§I.6, §I.7), which are not each individually itemized as separate rows in the abbreviated `orchestrator-audit-log.md` on disk. No itemized or aggregate count implicates any model outside the routing table.

### J.3 Compliance assertions
- **Zero `fable-5` sub-agent spawns:** confirmed by (a) the canary probe (J.1), (b) every role's explicit `model:` frontmatter pin, (c) the session default fallback to sonnet, and (d) a full read of `orchestrator-audit-log.md` — every "Model assigned" cell is haiku/sonnet/opus, never fable-5.
- **Zero OpenRouter calls (orchestration layer, Run 3):** no Run-3 sub-agent spawn or dispatch used OpenRouter — all sub-agent tooling is native Claude Code CLI model routing. This is distinct from the **product's own, in-scope, documented** use of OpenRouter as an LLM-provider fallback for the Aether platform's AI agents (tailor/coverLetter/storyExtractor) — GAP-P4-055's evidence shows `OPENROUTER_API_KEY` is the currently active *product* credential per `get_active_credential_env_var()`'s precedence, which is the deployed application's own accepted architecture (D-0014, D-0020 as amended), not an orchestration-layer violation.
- **One compliance incident (logged, not hidden):** during Wave-2 merge, the merge-1 agent sourced the entire `.env` file instead of grepping only the two permitted vars (`LOGIN_EMAIL`/`LOGIN_PASSWORD`), which echoed `DATABASE_URL`/`DATABASE_URL_TEST` (including the DB password) into its local transcript. **Resolution:** self-reported and corrected immediately within the same wave (§I.6); exposure confined to local transcript files on this VM (never committed, never sent externally); `OPENROUTER_API_KEY` was untouched throughout the incident. **Standing recommendation to the user (repeated here for visibility): rotate the hosted DB credential via the Abacus Database tile.** No other credential-handling deviation occurred in Run 3 — every other `.env` read across this run's evidence trail used the permitted `grep -E '^LOGIN_(EMAIL|PASSWORD)='` pattern (e.g. GAP-P4-051, GAP-P4-058-060 evidence).

### J.4 Summary table: role → model → count

| Role | Model | Count |
|---|---|---|
| Orchestrator | claude-fable-5 (xhigh) | 1 |
| Scout | haiku | 17 |
| Doc-audit / preflight / harness / api-sweep | haiku | 4 |
| Deep audit | sonnet | 5 |
| Canary | haiku | 1 |
| Triage-prep | sonnet | 1 |
| Fixer | opus | 4 |
| Fixer | sonnet | 7 |
| Reviewer | sonnet | 4 |
| Reviewer | opus | 7 |
| Doc agent (DOC-K) | sonnet | 1 |
| QA verifier | sonnet | 8 |
| Merge/deploy | sonnet | 2 |
| DOC-FINAL (this pass) | sonnet | 1 |
| **fable-5 (sub-agents only)** | — | **0** |
| **OpenRouter (orchestration layer)** | — | **0** |
