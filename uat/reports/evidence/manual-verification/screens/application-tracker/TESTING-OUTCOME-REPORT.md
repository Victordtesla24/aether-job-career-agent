# TESTING-OUTCOME-REPORT — application-tracker

**Screen ID:** application-tracker
**Screen name:** Application Tracker
**Route:** `/dashboard/applications`
**Wireframe:** `design/screens/application-tracker.html`
**Production URL under test:** https://5cb5f0620.abacusai.cloud
**Repo / commit SHA:** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Backing endpoints (per BRIEF.json):** `GET /applications`, `GET /applications/{id}`, `POST /applications/{id}/submit`, `GET /applications/funnel/sankey`
**Agents wired to this screen:** none (`agents: []`)
**Tester:** screen-tester agent role, Claude Sonnet 5, MANUAL-VERIFICATION Stage 1

**Session 1 (primary pass) window (UTC):** 2026-07-17T15:57:50Z → 2026-07-17T15:58:57Z (+ setup/API probing 15:50:54Z–15:55:02Z)
**Session 2 (fresh, VERIFY-TWICE pass) window (UTC):** 2026-07-17T16:02:47Z → 2026-07-17T16:03:02Z (+ supplementary CLM-073 guard probe 16:03:52Z–16:03:58Z)

---

## 0. Scope note — what this screen actually is vs. the brief's assumption

Before testing, I read the wireframe, `apps/api/app/routers/applications.py`, `apps/web/src/app/dashboard/applications/page.tsx`, `tracker-api.ts`, and `tracker-lib.ts` to form my own expectation, per protocol.

The orchestrator brief described this as a "CRUD/kanban application tracker" with add/move/edit/delete affordances. **The live implementation does not match that description**, and I tested what actually exists rather than what was assumed:

- There is **no "add application" UI or endpoint** on this screen. Applications are created upstream, either by `POST /jobs/{id}/apply` (Job Discovery screen, sets status directly to `submitted`) or by the Cover Letter AI agent (Cover Letter Studio screen, creates a `draft` row with a generated letter). Neither endpoint is in this screen's matrix.
- There is **no drag-and-drop / manual stage-move** affordance. Cards move stage only as a side effect of backend status changes driven by other screens/agents (cover-letter generation, the approvals queue, "Mark as submitted").
- There is **no edit** affordance for an application's fields.
- There is **no delete** affordance for an application (no `DELETE /applications/{id}` exists in the router at all — deletion is not a capability of this system for applications).
- The **only** write action native to this screen is **"Mark as submitted"** (`POST /applications/{id}/submit`, draft→submitted, idempotent), which is exactly the fourth endpoint in the matrix.
- There are **no text-input forms anywhere on this screen** (verified by full source read of `page.tsx`) — §3.2 point 3 (form validation/XSS/boundary testing) is therefore **not applicable** to this screen; there is nothing to submit free text into.

This is filed transparently rather than silently reinterpreting the brief. Given the mismatch, my CRUD round-trip evidence below is adapted: "create" is exercised via the only real creation path available (`POST /jobs/{id}/apply`, zero AI cost) plus a best-effort, twice-attempted use of the Cover Letter agent to obtain a tester-owned `draft` row (both attempts failed honestly with 503 — see MV-application-tracker-003); "move/edit/delete" are recorded as **coverage gaps against the brief's assumption**, not defects of the screen (the screen behaves exactly as its source code and the wireframe's read-mostly design imply).

## 1. Element inventory

| # | Element | data-testid / selector | Tested | Result |
|---|---|---|---|---|
| 1 | View tab: Board View | `[data-testid="view-board"]` | Yes | Works — default view, highlights active |
| 2 | View tab: Sankey Flow | `[data-testid="view-sankey"]` | Yes | Works — shows loading skeleton (~0.3–1s) then live SVG matching backend data |
| 3 | View tab: Timeline | `[data-testid="view-timeline"]` | Yes | Works — flat list sorted by `updatedAt` desc, matches app data |
| 4 | Filter dropdown (button + menu) | `[data-testid="filter-btn"]` | Yes | Works — 4 options, each filters cards correctly, active state highlighted, closes on outside-click and Escape |
| 5 | Filter: All applications | menuitemradio | Yes | 34 cards (see §5 note on this count) |
| 6 | Filter: Match ≥ 85 | menuitemradio | Yes | 0 cards (no card currently ≥85 fit — honest, not fabricated) |
| 7 | Filter: Match < 85 | menuitemradio | Yes | 34 cards |
| 8 | Filter: Needs approval | menuitemradio | Yes | 5 cards — **see MV-application-tracker-002** (disagrees with approvals banner's "4") |
| 9 | Sort dropdown (button + menu) | `[data-testid="sort-btn"]` | Yes | Works — 3 options, each re-orders cards, closes on outside-click/Escape |
| 10 | Sort: Latest activity | menuitemradio | Yes | Works |
| 11 | Sort: Match score | menuitemradio | Yes | Works |
| 12 | Sort: Company A–Z | menuitemradio | Yes | Works |
| 13 | Kanban board, 8 columns | `[data-testid="kanban-column-*"]` | Yes | All 8 render (Discovered/Evaluating/Tailoring/Ready to Apply/Submitted/In Review/Interview/Offer); empty columns show "Empty" placeholder honestly |
| 14 | Application card (job-pipeline sourced, no linked Application) | `[data-testid="application-card"]` w/o `role=button` | Yes | Correctly **not** clickable (no detail exists to show) — clicking is a no-op, confirmed |
| 15 | Application card (linked to a real Application row) | `[data-testid="application-card"][role="button"]` | Yes | Clickable, opens detail panel; keyboard-accessible (Tab+Enter/Space) |
| 16 | Application detail panel | `[data-testid="application-detail-panel"]` | Yes | Opens/closes correctly, shows job title/company/status/resume version/updatedAt/cover letter |
| 17 | Detail panel close (×) | `[aria-label="Close application details"]` | Yes | Works |
| 18 | "Apply on company site ↗" link | `[data-testid="application-apply-link"]` | Yes | Present when `applyUrl` set and not a `demo.aether.dev` placeholder; `target="_blank" rel="noopener noreferrer"`, correct real `href` verified |
| 19 | "Mark as submitted" button | `[data-testid="mark-submitted-btn"]` | Partially | Renders correctly, correctly gated to `status===draft` only. Live click-through **not exercised** on tester-owned data — see MV-application-tracker-003 |
| 20 | Cover letter block in detail panel | — | Yes | Renders verbatim `coverLetter` text; **surfaced MV-application-tracker-001** (fixture-content match on 2 pre-existing rows) |
| 21 | "View Email Thread →" cross-link (Submitted/In Review cards) | text="View Email Thread" | Yes | Navigates to `/dashboard/email`; back-navigation returns cleanly |
| 22 | "View in CRM →" cross-link (Interview/Offer cards) | text="View in CRM" | Not testable | No card currently in Interview/Offer stage — see MV-application-tracker-004 |
| 23 | Closed strip (rejected/withdrawn) | `[data-testid="closed-strip"]` | Yes | Renders when ≥1 closed app exists; each button opens the same detail panel |
| 24 | Pending-approvals banner | `[data-testid="pending-approvals-banner"]` | Yes | Renders when count>0, correct pluralization, navigates to `/dashboard/approvals`; count cross-checked against backend — **see MV-application-tracker-002** |
| 25 | Auto-apply guardrail banner | `[data-testid="auto-apply-banner"]` | Yes | Renders dynamic threshold (80%, from live `workspaces/settings`, not the wireframe's static 85% — correct, expected dynamism) and live on/off state |
| 26 | Error banner + Retry button (list load failure) | — | Not exercised | Could not force a genuine backend failure without violating "no service restarts" — reviewed via source only (`onClick={() => void load()}`, re-fetches, honest) |
| 27 | Sankey Retry button (sankey load failure) | — | Not exercised | Same reasoning as #26 |
| 28 | Timeline items | `[data-testid="timeline-view"] li` | Yes | Clickable, opens same detail panel, correct `updatedAt` desc ordering |
| 29 | Notification bell / topbar | inherited dashboard shell | Not in scope | Shell chrome shared across all dashboard screens, not application-tracker-specific |

## 2. Findings

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-application-tracker-001 | BLOCKER | defect | Detail panel shows cover-letter content byte-identical to checked-in LLM test fixtures for 2 pre-existing applications (Deputy, Stripe) |
| MV-application-tracker-002 | MEDIUM | wiring | "Needs approval" filter count (5) disagrees with pending-approvals banner count (4) on the same screen |
| MV-application-tracker-003 | LOW | coverage-gap | "Mark as submitted" not click-tested end-to-end on tester-owned data (Cover Letter agent 503'd twice; scope/data-ownership constraints) |
| MV-application-tracker-004 | LOW | coverage-gap | In Review / Interview / Offer stages and "View in CRM" link untestable — no qualifying data in account |

Full JSON: `findings.json` (schema per §4.1).

## 3. Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-024** — "All 27 core Phase-7 gates VERIFIED-CLOSED including 0 console errors across 20 routes, 0 same-origin 5xx..." | **PARTIALLY-TRUE (scoped to this screen only)** | This tester can only speak to `/dashboard/applications`, one of the 20 routes named. On that route: 0 uncaught console errors, 0 page errors, 0 HTTP ≥400 responses across 2 independent fresh sessions (`session1-console-events.json`=`[]`, `session1-page-errors.json`=`[]`, network scan 79 requests/0 bad; `session2-console-events.json`=`[]`, `session2-page-errors.json`=`[]`, 27 requests/0 bad). The 2 `net::ERR_ABORTED` entries in session1 are benign browser-cancelled in-flight requests from a same-tab navigation away from the page, not surfaced errors. This tester cannot adjudicate the pytest/vitest counts or the other 19 routes — those are other screens'/testers' responsibility. **My slice: CONFIRMED. Overall claim: UNVERIFIABLE-FROM-UI** (out of single-screen scope). |
| **CLM-062** — "Playwright sweep of 14 dashboard routes + /pricing + /admin ... 0 console errors / 0 failed requests / 0 page errors (GATE-03)" | **PARTIALLY-TRUE (scoped to this screen only)** | Same reasoning and same evidence as CLM-024 — this screen's slice is clean across 2 fresh sessions; the aggregate 16-route claim is outside this tester's single-screen mandate. |
| **CLM-073** — "Approving or rejecting an approval request synchronizes the linked application's status (approve→submitted, reject→rejected), with a draft-only guard" | **CONFIRMED** | Reproduced with fresh, tester-controlled evidence: (a) **guard clause**, self-triggered twice on tester-owned non-draft data — created an `application_submit` approval against my own `submitted`-status application (`c96b71a0a873a64806f95bb93`), resolved it `rejected` → application status remained `submitted` (unchanged, guard held); created a second approval against the same application, resolved it `approved` → application status again remained `submitted` (guard held both directions). `api-evidence-05..08`. (b) **positive transitions**, observed via fresh, timestamped `GET` reads of live concurrent activity on the shared account (not self-triggered by this tester, so noted as observation rather than self-reproduction): application `ce8edc6e...` (openai) moved `draft`→`submitted` between two reads 3 minutes apart, coincident with its approval resolving to `approved`; application `c7812e33...` (Empire Life) was read already in `rejected` status with a resolved-`rejected` approval linked. Both are consistent with the claimed sync direction and the draft-only guard. Root-mechanism (approval.py `_sync_application`, single-transaction UPDATE gated on `status='draft'`) was also source-verified. |

## 4. UNSURE items

None requiring escalation as a genuine ambiguity — the one significant judgment call (MV-application-tracker-001's root cause: live bug vs. stale seed data) is filed as a finding with both hypotheses stated explicitly and evidence for each, rather than as an UNSURE, because the user-facing fact (fabricated content is live and visible today) is unambiguous regardless of root cause.

## 5. Data-integrity note (not filed as a finding — conformance-consistent with wireframe)

The subtitle "N active applications across 8 stages" counts **every card across all 8 columns**, including `Discovered`/`Evaluating`/`Tailoring` cards that are sourced directly from `Job.status` and have **no linked `Application` row at all** (not yet applied to). At test time this inflated the visible number substantially (34 total cards, of which only 10 are backed by a real `Application` row — 5 draft + 5 submitted; the other 24 are un-applied "discovered" jobs). I verified this is **not a defect**: it matches the wireframe's own explicit design (`application-tracker.html`'s mockup literally sums Discovered(12)+Evaluating(6)+Tailoring(3)+...+Offer(3) into its "N active applications" copy), i.e. "active applications" is the product's chosen (if debatable) terminology for "everything currently live in the pipeline," not "things I have formally applied to." Recorded here for the orchestrator's awareness, not as a bug.

## 6. Screenshot index

All paths relative to `test-artifacts/`.

**Session 1:**
`session1-01-unauth-access.png`, `session1-02-board-view-loaded.png`, `session1-03-view-sankey.png` (loading-skeleton state, expected), `session1-04-view-timeline.png`, `session1-05-view-board-again.png`, `session1-06-filter-menu-open.png`, `session1-07..10-filter-*.png` (4 filter options), `session1-11-sort-menu-open.png`, `session1-12..14-sort-*.png` (3 sort options), `session1-15-detail-panel-open.png`, `session1-16-detail-panel-via-keyboard.png`, `session1-17-detail-deputy-fixture-check.png` (MV-001 evidence), `session1-18-detail-stripe-fixture-check.png` (MV-001 evidence), `session1-19-closed-strip-detail.png`, `session1-20-crosslink-email-thread.png`, `session1-21-pending-approvals-banner-nav.png`, `session1-22-after-reload-airwallex-check.png`, `session1-23-sankey-recheck.png` (loaded state, real data), `session1-24-back-forward-nav.png`, `session1-25-throttled-reload.png`, `session1-26-mid-session-unauth.png`.

**Session 2 (fresh, verify-twice):**
`session2-01-unauth-access-repro.png`, `session2-02-board-view-loaded-repro.png` (wide viewport, shows my created `airwallex` card in the Submitted column), `session2-03-detail-deputy-fixture-check-repro.png`, `session2-04-detail-stripe-fixture-check-repro.png` (MV-001 re-confirmed byte-identical), `session2-05-needs-approval-filter-repro.png` (MV-002 re-confirmed, 5 vs banner's 4), `session2-06-sankey-loading-state-repro.png`, `session2-07-sankey-loaded-state-repro.png`, `session2-08-draft-detail-apply-link-check.png`.

**API/data evidence (not screenshots):** `api-evidence-01..11-*.json/.txt` — see file list in `test-artifacts/`.

## 7. Console / network / server-log summary

- **Console errors (both sessions):** 0
- **Uncaught page errors (both sessions):** 0
- **Failed/aborted requests:** 2 in session1 (`net::ERR_ABORTED` on `/workspaces/settings` and `/workspaces/emails/inbox`, both coincident with a same-tab navigation away from the page — benign browser cancellation, not a surfaced app error); 0 in session2.
- **HTTP ≥400 responses on this screen's own network traffic:** 0 across 79 (session1) + 27 (session2) `/api/` requests observed.
- **Server-side 5xx directly caused by this screen's endpoints:** 0. (The two 503s recorded in MV-application-tracker-003 came from `POST /agents/cover-letter/run`, which is **not** one of this screen's 4 endpoints — it is test-data-setup plumbing for another screen's agent, included here for full disclosure, not counted against application-tracker's own hygiene.)
- No server log-tailing was performed directly by this tester (no `log-tailer` agent invoked) — this section covers browser-observed network/console only, per the tools available to a screen-tester.

## 8. Data created/touched by this tester (audit trail)

All prefixed conceptually as this screen's MV test data, tracked by exact ID since no free-text field exists on this screen to embed an `MV-application-tracker-` string literal (job/company text is third-party-sourced, not tester-editable):

- **Created** `Application` `c96b71a0a873a64806f95bb93` (airwallex, "Implementation Manager - Spend") via `POST /jobs/c4c2b512ad476b76b98ef9596/apply` at 2026-07-17T15:50:54Z — status `submitted`. Verified round-trip: appears on tracker immediately, persists after reload, persists across a brand-new browser session (session2), appears correctly in the Submitted column and in Timeline view.
- **Created and resolved 2 `ApprovalRequest` rows** against the application above (`cc68a2c7...` rejected, `c538028f...` approved) purely to reproduce CLM-073's draft-only guard on tester-owned data with zero collision risk to concurrent testers. Both resolved cleanly; the linked application's status was correctly left unchanged (`submitted`) by the guard in both directions, as expected.
- **Attempted and failed twice** (honestly, 503) to create a tester-owned `draft` Application via `POST /agents/cover-letter/run` (jobs `c9424bbb...` harvey and `c4c2b512...` airwallex) — no Application rows resulted from these failed attempts.
- **Deletion:** Not applicable — no delete capability exists for `Application` rows anywhere in this system (confirmed via source read of `apps/api/app/routers/applications.py`, no `DELETE` route). Nothing to clean up; my one created application (`c96b71a0a873a64806f95bb93`, status `submitted`) is left in place as it cannot be removed and causes no harm to other testers (it is not referenced by any pending approval or other tester's in-flight work, confirmed).
- **Not touched:** all pre-existing applications/approvals belonging to concurrent testers' in-flight work (openai, replit, InterEx, EasyPark, Empire Life, and their approval requests) were read-only inspected, never mutated, per protocol's shared-environment rules.

## 9. NOT-TESTED list (reasons required)

| Item | Reason |
|---|---|
| Live click-through of "Mark as submitted" (draft→submitted transition, triggered by a real UI click on tester-owned data) | HUMAN/RESOURCE-GATED: the only legitimate creation path for a tester-owned `draft` row (Cover Letter AI agent) failed with 503 twice in this session (this tester's hard stop-after-two-failures rule applies); using a *pre-existing* draft not created by this tester was excluded by protocol (never modify data you didn't create), doubly so while a concurrent tester was actively exercising the same approval-queue data live during this session. See MV-application-tracker-003. |
| "View in CRM" cross-link, Interview-stage card badge (round/date), Offer-stage card badge (amount/deadline) | HUMAN/DATA-GATED: no application in the shared test account is currently in `interview` or `offer` status, and this screen has no endpoint capable of producing one — that lifecycle belongs to other screens/agents outside this screen's matrix. See MV-application-tracker-004. |
| Forced-backend-error / list-load Retry button, Sankey-load Retry button | HUMAN-GATED: protocol prohibits service restarts or backend fault injection; reviewed via source only (both wire a plain re-fetch on click, fail honestly with a visible red error banner, no raw stack traces observed anywhere in this session). |
| Root-causing MV-application-tracker-001 (whether the fixture-content match is a live, ongoing code defect vs. stale pre-existing test-seed data) | OUT-OF-SCREEN-SCOPE: requires inspecting `AETHER_LLM_MODE` in the production runbook/env and/or the Cover Letter agent's code path directly, which is cover-letter-studio's/infra's territory, not application-tracker's. Filed as a BLOCKER finding with both hypotheses stated for the orchestrator to route. |
| Pytest/vitest suite counts referenced in CLM-024 | OUT-OF-SCREEN-SCOPE: this tester's mandate is live UI/API testing of one screen, not re-running the backend/frontend test suites. |

## 10. Sign-off

Tested by: screen-tester agent role (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, application-tracker.
All findings above were reproduced in two independent, fresh browser sessions (`session1`, `session2`) before filing, per §3.2 point 9. No code changes, service restarts, or destructive git operations were performed. No secrets logged beyond 8-character token prefixes (`eyJhbGci`).

**Verdict on this screen:** functions correctly for what it actually is (a read-heavy pipeline board with one write action, "Mark as submitted"); solid wiring, honest empty/loading states, clean console/network hygiene, no XSS/injection surface (no forms exist). One BLOCKER-grade data-integrity issue (MV-001, fabricated/fixture cover-letter content reaching the user) and one MEDIUM UX/data-consistency issue (MV-002) require orchestrator attention; both are reproducible and evidenced twice.
