# TESTING OUTCOME REPORT — Interview Center

**Screen id:** `interview-center`
**Screen name:** Interview Center
**Route under test:** `/dashboard/interviews`
**Wireframe reference:** `design/screens/interview-center.html`
**Environment:** Production — `https://5cb5f0620.abacusai.cloud`
**Repo / commit SHA:** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Backing endpoints (matrix):** `GET/POST /interviews`, `GET/PATCH /interviews/{id}`, `POST /interviews/{id}/cancel`, `POST /interviews/{id}/complete`, `GET /workspaces/interviews/prep` (7 total; router also exposes an undocumented `DELETE /interviews/{id}`)
**Agents wired to this screen (per BRIEF.json):** none
**Session window (UTC):** 2026-07-17T16:13:37Z → 2026-07-17T16:19:44Z (two independent fresh-browser sessions + fresh-login API verification pass)
**Tester:** screen-tester agent (Claude Sonnet 5), manual-verification Stage 1

---

## 1. Own expectation of the screen (formed BEFORE testing production)

From the wireframe (`interview-center.html`) and product sense: Interview Center should be a per-interview workspace reached once an application has an interview scheduled. It should show a header with role/company/round/time, a 3-way tab bar (Prep / Live Assist / Debrief), a compliance & consent banner (dismissible), a Company & Role Brief panel, a Predicted Questions list mapped to Story Bank entries, a Live Assist panel with a mute toggle and real-time coaching metrics (filler words/min, pace, talk/listen ratio, coaching cue), and a Last Debrief snapshot (score, strengths/warnings, "View full debrief"). For an account with **no** interviews, an honest empty state should replace this with a clear "nothing scheduled yet" message and a path to get one started (e.g. link back to Applications). CRUD (schedule/edit/cancel/complete/delete an interview) should be reachable from the UI somewhere, even if this exact screen isn't the "create" surface.

---

## 2. What production ACTUALLY does

The `/dashboard/interviews` route renders a **fully static placeholder**: page title, one-line subtitle, and a centered empty-state card ("No interview scheduled." / "Once an application progresses to interview stage, your prep brief appears here." / "View Applications" button). It is not conditionally empty — it is *unconditionally* this content. It makes **zero** calls to any of the 7 documented backend endpoints, in every load tested, including a load performed *after* real `InterviewSchedule` rows were created for the account via direct API calls. Source inspection confirms why: `apps/web/src/app/dashboard/interviews/page.tsx` at the tested commit is a static component with no `useEffect`/fetch at all. Git history shows a fully wired version (tabs, live fetch of `GET /workspaces/interviews/prep`, mute toggle, debrief) existed and was deliberately reverted to this static placeholder in commit `0701b34` ("replace crashing Interview Center with stable placeholder"), while the backend (`apps/api/app/routers/interviews.py`, `apps/api/app/routers/workspaces.py::interview_prep`) was left fully implemented and functioning. The empty-state **copy** happens to be honest (it matches what the backend would say if it were asked — `GET /workspaces/interviews/prep` returns the same message when `Application.status != 'interview'`), but this is coincidental hardcoding, not live wiring: the copy never changes no matter what state the backend is actually in.

There is no UI path anywhere in the product (Interview Center itself, or the Applications screen) to create/schedule an interview. The backend CRUD is otherwise complete and correct when driven directly via API.

---

## 3. Element inventory

| # | Element | data-design-id (wireframe) / selector | Present in prod? | Tested | Result |
|---|---|---|---|---|---|
| 1 | Sidebar nav "Interview Center" link | `nav-primary-ic02` | Yes (highlighted, active) | Yes | Works — active state correct, href `/dashboard/interviews` |
| 2 | Page header title "Interview Center" | `header-ic04` (repurposed) | Yes | Yes | Static text only, no role/company/round/time (no interview to show) |
| 3 | Page subtitle "Prep briefs · Live Assist · Debrief" | — | Yes | Yes | Static text, cosmetic only |
| 4 | Tab bar (Prep / Live Assist / Debrief) | `tabs-ic05`, `tab-prep-ic06`, `tab-live-ic07`, `tab-debrief-ic08` | **No** | N/A | Absent from DOM entirely — see MV-interview-center-002 |
| 5 | Compliance & consent banner + dismiss (X) | `compliance-banner-ic17`, `btn-dismiss-compliance-ic17b` | **No** | N/A | Absent — see MV-interview-center-002 |
| 6 | Company & Role Brief panel | `prep-main-ic09` | **No** | N/A | Absent — see MV-interview-center-002 |
| 7 | Predicted Questions list | `pq-card-ic10/11/12` | **No** | N/A | Absent — see MV-interview-center-002 |
| 8 | Live Assist panel + mute toggle | `live-assist-ic14`, `btn-mute-ic18` | **No** | N/A | Absent — see MV-interview-center-002 |
| 9 | Last Debrief snapshot + "View full debrief" | `debrief-snap-ic15`, `view-debrief-ic16` | **No** | N/A | Absent — see MV-interview-center-002 |
| 10 | Empty-state icon | — | Yes | Yes | Renders correctly (calendar-check icon) |
| 11 | Empty-state heading "No interview scheduled." | — | Yes | Yes | Renders, honest given no data exists |
| 12 | Empty-state subtext | — | Yes | Yes | Renders, honest copy |
| 13 | "View Applications" link/button | — | Yes | Yes | Click → navigates to `/dashboard/applications` (200); browser Back returns cleanly to `/dashboard/interviews`; Forward returns to `/dashboard/applications`. Works as designed. |
| 14 | Header search box (shared dashboard chrome) | — | Yes | Yes (spot check) | Accepts text input, no console error, no screen-specific behavior observed (out of this screen's functional scope) |
| 15 | Notification bell (shared chrome) | — | Yes | Yes (spot check) | Click does not throw, no console error |
| 16 | Profile / "Administrator" (shared chrome) | — | Yes | Yes (spot check) | Click navigates to `/dashboard/approvals`, no console error |
| 17 | Backend: `GET /interviews` | — | n/a (API) | Yes (direct) | 200, correct list scoped to user |
| 18 | Backend: `POST /interviews` | — | n/a (API) | Yes (direct) | 201 valid; 422 empty/invalid-type/boundary; no UI caller |
| 19 | Backend: `GET /interviews/{id}` | — | n/a (API) | Yes (direct) | 200 found / 404 after delete |
| 20 | Backend: `PATCH /interviews/{id}` | — | n/a (API) | Yes (direct) | 200, edits persist on reload |
| 21 | Backend: `POST /interviews/{id}/complete` | — | n/a (API) | Yes (direct) | 200, status → completed, persists |
| 22 | Backend: `POST /interviews/{id}/cancel` | — | n/a (API) | Yes (direct) | 200, status → cancelled, persists |
| 23 | Backend: `DELETE /interviews/{id}` (undocumented 7th) | — | n/a (API) | Yes (direct) | 204, row gone, subsequent GET → 404 |
| 24 | Backend: `GET /workspaces/interviews/prep` | — | n/a (API) | Yes (direct) | 200, correct empty/populated shapes; never called by UI |

---

## 4. Findings

| id | severity | category | summary |
|---|---|---|---|
| MV-interview-center-001 | BLOCKER | wiring | Screen never calls any of its 7 backend endpoints, even with real data present |
| MV-interview-center-002 | HIGH | visual | ~90% of wireframed components (tabs, brief, questions, live assist, debrief, compliance banner) absent from production DOM |
| MV-interview-center-003 | BLOCKER | coverage-gap | No UI control anywhere in the app can create/schedule an interview; full backend CRUD is unreachable by users |
| MV-interview-center-004 | MEDIUM | validation | `POST /interviews` accepts a nonexistent `application_id` with no referential check, creating orphaned rows (201 instead of 4xx) |

Full machine-readable rows: `findings.json` (same directory).

---

## 5. CRUD round-trip (via direct API — see §6 for why UI could not be used)

Performed twice, in two independently-authenticated sessions, prefixed `MV-interview-center-00N`:

**Session A** (interview `cf23fcdc8e6662852e2f0a0c0`):
1. `POST /interviews` → 201, appears in `GET /interviews` list. ✅
2. `PATCH /interviews/{id}` (notes edited to include `<script>alert(1)</script>` and unicode `üñîçøđé 😀`) → 200, `GET /interviews/{id}` re-read confirms the edit persisted verbatim (stored as literal text, not executed — API is JSON, no HTML render context on this screen so no XSS surface here). ✅
3. `POST /interviews/{id}/complete` → 200, `status: "completed"` persisted. ✅
4. `DELETE /interviews/{id}` (cleanup) → 204, subsequent `GET` → 404. ✅

**Session B** (interview `cdcfcc2cd6c11b0217f2c88ed`):
1. `POST /interviews` → 201. ✅
2. `POST /interviews/{id}/cancel` → 200, `status: "cancelled"` persisted, re-read confirms. ✅
3. `DELETE /interviews/{id}` → 204, re-read → 404, `GET /interviews` list confirms gone. ✅

**Verify-twice pass** (fresh login, interview `ceffff77bd8cd772a879bd88f`): create → appears in list → PATCH edit → re-GET confirms persisted → delete → re-GET 404 → list confirms empty. Identical behavior to Session A/B. ✅ Not flaky.

All account data created above was prefixed `MV-interview-center-` and fully deleted by end of session; final `GET /interviews` for the admin account returns `[]`. No other tester's data was read, modified, or deleted (only one shared `Application` id was *referenced* — never mutated — to satisfy the required `application_id` field).

**crud_roundtrip verdict: `true`** — the backend CRUD contract itself is fully correct and round-trips cleanly. It is simply unreachable from the UI (MV-interview-center-001, -003), which is reported as its own, more severe, defect rather than a CRUD failure.

---

## 6. UI↔backend wiring (network capture)

Two independent fresh-browser Playwright sessions captured all `/api/*` traffic while on `/dashboard/interviews`, both before and after real `InterviewSchedule` data existed for the account:

- Requests fired: `GET /agents` (×2), `GET /approvals?status=pending`, `GET /billing/entitlement`, `GET /workspaces/settings` — all shared dashboard-shell calls unrelated to this screen.
- Requests **never** fired, in either session, before or after data existed: `GET /interviews`, `GET /workspaces/interviews/prep`, or any other interviews-router call.
- Confirmed via server-side log (`/var/log/aether/api.log`) cross-reference: every `/interviews*` request logged during the test window came from my own `curl` API probes (timestamped, IP `208.122.8.11`), none from the browser sessions.

This is airtight confirmation of MV-interview-center-001: the disconnect is total, not intermittent.

---

## 7. AI-agent integration

BRIEF.json lists **no agents** wired to this screen (`"agents": []`), and this was independently confirmed: the screen fires no agent-related calls and has no agent-trigger UI. `GET /workspaces/interviews/prep` does read from `AgentRun` rows with `agentName ILIKE '%interview%'` to source live-assist/debrief signals, implying some *other* screen (Agents) is the actual trigger surface for interview-prep generation — testing that generation pipeline is out of scope for this screen and is noted under NOT-TESTED below.

---

## 8. Error & edge states

| Test | Result |
|---|---|
| Unauthenticated access to `/dashboard/interviews` | Clean redirect to `/login` (HTTP 200 on the login shell, final URL `/login`). Reproduced twice, identical. ✅ |
| Unauthenticated `GET /api/interviews` | 401 `{"detail":"Not authenticated"}`. Reproduced twice. ✅ |
| Browser back navigation (after `View Applications` click) | Returns cleanly to `/dashboard/interviews`, page re-renders correctly. ✅ |
| Browser forward navigation | Returns cleanly to `/dashboard/applications`. ✅ |
| Reload | Identical static content, no state loss (there is no state to lose). ✅ |
| Throttled reload (400ms latency, ~50kbps down / 20kbps up via CDP) | Page loads in 737ms wall-clock in this run, no spinner/skeleton needed since content is static; no errors, no truncated render. ✅ |
| POST /interviews with empty body | 422 with field-level Pydantic errors (`application_id`, `scheduled_at` required). Honest, no stack trace. ✅ |
| POST /interviews with invalid `type` | 422 `"Invalid type 'telepathic'. Valid: [...]"`. ✅ |
| POST /interviews with `duration_minutes` out of [15,480] bounds | 422 on both ends (10 → too low, 481 → too high). ✅ |
| POST /interviews with nonexistent `application_id` | **201 (should be rejected)** — see MV-interview-center-004. |
| Unicode + XSS-payload text in `notes` | Stored and returned verbatim as JSON string; no HTML render context on this screen (frontend never displays interview data at all, so no live XSS surface today — flagged as a latent risk if/when a UI is reconnected). |

---

## 9. Console / network / server-log hygiene

- **Console errors:** 0, in both fresh sessions, across load + all chrome interactions (search box, notification bell, profile link) + tab/back/forward/reload/throttled-reload. ✅
- **Console warnings:** 0. ✅
- **Failed requests (network-level):** 0. ✅
- **Server-side 5xx during test window:** 0. Grepped `/var/log/aether/api.log` for all `interviews`-related lines across the full test window — every request logged is one of my own probes, and every status code matches what curl reported (201/200/204/404/422/401), zero 5xx. ✅
- **`/var/log/aether/web.log`:** no `dashboard/interviews`-specific entries (Next.js server log doesn't do per-route access logging); no anomalies observed.

---

## 10. Claim verdicts

| Claim id | Claim (abridged) | Verdict | Evidence |
|---|---|---|---|
| CLM-024 | "27/27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors across 20 routes (GATE-16), 0 same-origin 5xx (GATE-17), pytest 676 / vitest 297 green, Playwright E2E green" | **PARTIALLY-TRUE** | The portion of this claim that is reproducible from a single-screen test — 0 console errors and 0 same-origin 5xx specifically on `/dashboard/interviews` — is **CONFIRMED** live, twice (`session1-results.json`, `session2-results.json`, `13-server-log-excerpt-interviews.txt`). The broader claim (all 20 routes, full pytest/vitest suite counts, full E2E suite) is **UNVERIFIABLE-FROM-UI** by a single-screen tester — I did not re-run the full backend/frontend test suites or sweep the other 19 routes; that is outside this brief's scope. No evidence contradicting the broader claim was found, but it was not independently reproduced end-to-end here. |
| CLM-062 | "Playwright sweep of 14 dashboard routes + /pricing + /admin as paid admin showed 0 console errors / 0 failed requests / 0 page errors (GATE-03)" | **PARTIALLY-TRUE** | Same reasoning: the `/dashboard/interviews` slice of this sweep is **CONFIRMED** (0 console errors, 0 failed requests, 0 page errors, reproduced twice as admin). The full 16-route sweep was not re-run by this tester; **UNVERIFIABLE-FROM-UI** for the remaining routes. |

Neither claim row makes any assertion about the Interview Center screen's *functional* completeness or UI↔backend wiring — both are narrowly about console/network hygiene and test-suite counts, so MV-interview-center-001/002/003/004 are **new findings**, not claim contradictions.

---

## 11. UNSURE items

None. Every observation in this report was directly reproduced with fresh evidence (network capture, screenshots, server-log cross-reference, or direct API round-trip) in at least two independent sessions; nothing required guessing.

---

## 12. Screenshots index

All paths relative to `uat/reports/evidence/manual-verification/screens/interview-center/test-artifacts/`:

| File | Description |
|---|---|
| `01-unauth-access.png` | Unauthenticated request to `/dashboard/interviews` → redirected to `/login` |
| `02-interview-center-loaded.png` | Authenticated load, full page — static empty state (primary visual-conformance evidence) |
| `02-page-html.html` | Full DOM dump at load, used to confirm absence of wireframed components |
| `03-after-view-applications-click.png` | After clicking "View Applications" → `/dashboard/applications` |
| `04-after-back.png` | Browser Back → returns to `/dashboard/interviews` |
| `05-after-forward.png` | Browser Forward → returns to `/dashboard/applications` |
| `06-reload.png` | Plain reload, identical static content |
| `07-throttled-reload.png` | CDP-throttled reload (400ms latency / ~50kbps down) |
| `08-after-data-exists-still-static.png` | Reload performed AFTER real InterviewSchedule rows exist for the account — page unchanged (key evidence for MV-interview-center-001) |
| `09-session2-unauth.png` | Fresh-session repeat of unauth redirect test |
| `10-session2-loaded.png` | Fresh-session repeat of authenticated load |
| `14-header-search-typed.png` | Shared header search box spot-check |
| `15-notification-bell-clicked.png` | Shared notification bell spot-check |
| `16-profile-clicked.png` | Shared profile-link spot-check |

JSON/log artifacts: `session1-results.json`, `session1b-results.json`, `session2-results.json`, `session3-chrome-results.json`, `11-api-crud-log-session1.txt`, `12-api-crud-log-verify2.txt`, `13-server-log-excerpt-interviews.txt`. Scripts used: `script-session1.mjs`, `script-session1b.mjs`, `script-session2.mjs`.

---

## 13. NOT-TESTED (HUMAN-GATED only)

- **Interview-prep AI-agent generation pipeline** (the `AgentRun` records with `agentName ILIKE '%interview%'` that `GET /workspaces/interviews/prep` reads from): triggering and evaluating this generation is owned by the **Agents** screen's tester per the screen matrix (BRIEF.json for this screen lists `"agents": []`); running it here would duplicate/conflict with that screen's dedicated test pass and its own quota/audit-field checks.
- **Moving a real `Application` to `status = 'interview'`** to observe the fully-populated (non-empty) `GET /workspaces/interviews/prep` response end-to-end in a live UI: no API endpoint exists to transition an application to `interview` status (only `POST /applications/{id}/submit` exists, `draft → submitted`); doing this would require either direct production-database mutation (prohibited — evidence root/protocol forbids DB writes outside the app's own APIs) or a full, uncontrolled recruiting-pipeline simulation outside this screen's brief. The populated-session JSON *shape* was nonetheless verified directly via `GET /workspaces/interviews/prep` source-code review and the documented empty-state shape was verified live.

---

## 14. Sign-off

Tested by: screen-tester agent (Claude Sonnet 5), Aether MANUAL-VERIFICATION Stage 1, screen `interview-center`.
Two independent fresh-browser sessions plus one independent fresh-login API verification pass performed; every finding above reproduced in at least two runs with matching results (no FLAKY items to report). Server-side log cross-reference performed directly on the production host (`/var/log/aether/api.log`) for the full test window, corroborating all client-observed network behavior with zero 5xx.

**crud_roundtrip: true** (backend-only; screen itself exposes none of it to users — see MV-interview-center-001/003).
