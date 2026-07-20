# TESTING-OUTCOME-REPORT — offer-comparison

**Screen ID:** offer-comparison
**Screen name:** Offer Comparison
**Route:** `/dashboard/offers`
**Wireframe ref:** `design/screens/offer-comparison.html`
**Backing endpoints (per BRIEF.json):** `GET /workspaces/offers`, `GET /offers` (both live-verified during this session; both mounted, both GET-only, both return the same real-data payload)
**Environment:** Production — `https://5cb5f0620.abacusai.cloud`
**Repo / commit SHA (repo state at time of testing):** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Tester:** screen-tester agent role, model Claude Sonnet 5 (Claude Agent SDK)
**Session window (UTC):** 2026-07-17T16:13:00Z – 2026-07-17T16:29:30Z (two scripted Playwright passes — `run1` ~16:16Z, `run2` ~16:24–16:26Z — plus 8 targeted investigative Playwright sessions ~16:17Z–16:29Z, plus one manual-checks pass repeated twice ~16:28–16:29Z)
**Account used:** admin/admin123 (TEMP Pro entitlement, per brief), 0 pre-existing offers on this account

---

## 1. My own expectation of the screen (formed BEFORE looking at behavior)

From the wireframe (`offer-comparison.html`) and product sense: this is a "weighted decision analysis" tool for comparing job offers. I expected:
- An **Add Offer** flow that durably saves a real offer to the user's account (name, base/bonus/equity, location) — since offers are exactly the kind of high-stakes, infrequent data a user would type once and expect to keep.
- A **side-by-side comparison grid** of offer cards with a computed "Fit score" and a "Top pick" designation.
- A **Priority Weights** panel that is either informational-only (fine) or, if presented as adjustable ("weighted decision analysis"), actually feeds into the Fit score.
- A **Negotiation Coach** giving a real, offer-derived suggested counter figure and market commentary — or, if not AI-backed, at least internally consistent (no impossible numbers).
- Honest empty/loading states, and — given the brief's explicit warning that this screen has only 1 real backend endpoint — a real risk that "Add Offer" might be a client-side-only mock. I went in specifically looking for that.

## 2. What it actually does (summary)

The GET side is real: `/workspaces/offers` (and the parallel, apparently-unused `/offers`) derive the comparison payload from genuine `Application` rows with `status='offer'` joined to `Job` — **no hardcoded/fixture offers**, confirmed by reading `apps/api/app/routers/workspaces.py` and `apps/api/app/routers/offers.py`, and confirmed live (admin's account correctly shows the honest empty state because it has 0 such applications). Good news, no fabricated "sample offers" are shown as real.

The write side is **not real at all**: "Add Offer" is a client-only form that appends to in-memory React state and never calls any endpoint (there is no POST/PUT/DELETE route for offers anywhere in the API). This is the central finding, exactly the risk the brief flagged. See MV-offer-comparison-001.

Additionally: the Negotiation Coach's suggested counter is unconditionally `null` server-side and renders as a nonsensical "$0 base" in both the summary and the auto-generated draft email (MV-offer-comparison-002); the Add-Offer modal has a real, reproducible overlay-coverage gap that lets background controls remain clickable and can silently discard the in-progress form (MV-offer-comparison-003); and the "Priority Weights" panel is purely decorative with no scoring logic behind it (MV-offer-comparison-004).

Console/network hygiene was otherwise clean: **zero console errors, zero page errors, zero failed/non-2xx `/api/*` requests** across every session (138 total `/api/*` responses captured across the two scripted runs, all HTTP 200).

---

## 3. Element inventory

| Element | data-testid / selector | Tested | Result |
|---|---|---|---|
| Sidebar nav (13 items incl. "Offers" highlighted active) | `aside nav a` | Yes | Matches `NAV_ITEMS` contract, "Offers" correctly highlighted active on this route. Confirmed via 2 sessions. |
| Topbar: search input | `header input[aria-label="Search jobs, applications, agents..."]` | Yes (incidental, via overlay-gap probe) | Present, focusable in normal state. |
| Topbar: Notifications bell | `a[aria-label*="Notifications"]` | Yes | Present, navigates to `/dashboard/approvals`. Also the vector for MV-003 (see below). |
| Topbar: profile menu | `header` avatar area | Present, not deep-tested (out of scope for this screen) | Not a defect for this screen. |
| Header "Add Offer" button | `[data-testid="add-offer"]` | Yes | Opens modal. Works both sessions. |
| Empty state | `[data-testid="offers-empty-state"]` | Yes | Renders correctly and honestly when 0 offers exist (real account state, not a toggle). |
| Empty-state "Add Offer" button | `[data-testid="empty-add-offer"]` | Yes | Opens the same modal. Works both sessions. |
| Add-Offer modal: Company field (required) | `input[name="company"]` | Yes | Validated (required, max 60 chars, XSS-safe, unicode-safe). |
| Add-Offer modal: Role field (optional) | `input[name="role"]` | Yes | Accepts unicode freely, defaults to "—" if blank. |
| Add-Offer modal: Base field (required, >0) | `input[name="base"]` | Yes | Validated (required, must parse as non-negative number >0). |
| Add-Offer modal: Bonus field (optional, ≥0) | `input[name="bonus"]` | Yes | Defaults to 0. |
| Add-Offer modal: Equity field (optional, ≥0) | `input[name="equity"]` | Yes | Defaults to 0. |
| Add-Offer modal: Location field (required) | `input[name="location"]` | Yes | Validated (required). |
| Add-Offer modal: live Total-comp preview | `[data-testid="add-offer-total"]` | Yes | Recomputes live as fields change. Correct arithmetic in all cases tested. |
| Add-Offer modal: Cancel button | `button:has-text("Cancel")` | Yes | Closes modal, discards draft (draft not added to grid). Confirmed both sessions. |
| Add-Offer modal: ✕ close button | `button[aria-label="Close"]` | Yes | Closes modal, discards draft. Confirmed both sessions. |
| Add-Offer modal: Escape key | keyboard | Yes | Closes modal. Confirmed both sessions. |
| Add-Offer modal: backdrop click (safe region) | mouse click at e.g. (1000,400) | Yes | Closes modal correctly in the majority of the backdrop. |
| Add-Offer modal: backdrop coverage (top ~24px strip) | `document.elementFromPoint` + real click | Yes | **Defect** — does not close/does not cover; see MV-003. |
| Add-Offer modal: Submit / "Add offer" button | `[data-testid="add-offer-submit"]` | Yes | Validates, and on success appends a **client-only, non-persistent** card; see MV-001. |
| Add-Offer modal: Tab/Shift+Tab focus trap | keyboard, 9 focusable nodes | Yes | Holds correctly, no escape in either direction (GAP-P4-057 regression check: still fixed). Confirmed twice. |
| Offer card (grid) | `[data-testid="offer-card"]` | Yes | Renders Company, Total comp, Base/Bonus/Equity/Location, Fit score. "New" badge for session-added offers; "Top pick" badge reserved for `topPick:true` (only ever true for index 0 of real backend offers — not reachable live on this account, see NOT-TESTED). |
| Priority Weights panel | `[data-testid="priority-weights"]` | Yes | Renders correctly (bars, %, running total 100% badge). **Purely decorative / non-interactive** — see MV-004. |
| Negotiation Coach panel | `[data-testid="negotiation-coach"]` | Yes | Renders; insight text is generic boilerplate; suggested counter is always "$0 base" — see MV-002. |
| "Draft counter email" toggle button | `[data-testid="draft-counter-btn"]` | Yes | Toggles a pre-filled draft email visible/hidden correctly; content contains the "$0 base" defect from MV-002. |
| Skeleton loading state | `[data-testid="offers-skeleton"]` | Attempted (throttled reload) | Not caught in either throttled-reload attempt — page loaded too quickly even at 50kbps/800ms-latency emulation to catch the skeleton frame; not conclusively tested either way (see NOT-TESTED). |
| Error state | `[data-testid="offers-error"]` | Not triggered | No forced-error mechanism available from the UI alone; endpoint never failed during testing (see NOT-TESTED). |
| Wireframe's "Preview empty state" toggle button | n/a (design-time only) | N/A | Present only in the wireframe file itself as an explicit design-review affordance (`toggleOfEmpty()`, commented "toggle in header to preview" in the wireframe's own `<script>`). The shipped product correctly does **not** carry this over — it instead drives the empty state from real data, which is the correct behavior. Not filed as a finding. |

---

## 4. Findings

All findings below have fresh evidence from **this session** (production, 2026-07-17). Full detail — reproduction steps, expected/observed, evidence paths — is in `findings.json`. Every finding below was reproduced in at least 2 independent fresh browser sessions before filing (VERIFY TWICE), per §3.2.9.

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-offer-comparison-001 | BLOCKER | defect | "Add Offer" is entirely client-side and non-persistent — no backend write endpoint exists at all; added offers vanish on reload or any navigation, with zero warning. |
| MV-offer-comparison-002 | HIGH | defect | Negotiation Coach's suggested counter / drafted email always show "$0 base" — backend hardcodes `suggestedCounter: null` unconditionally. |
| MV-offer-comparison-003 | HIGH | defect | Add-Offer modal backdrop leaves a reproducible ~24px full-width strip at the top of the viewport uncovered; background Topbar controls (e.g. Notifications link) remain clickable and can silently navigate away, destroying the open modal and any unsaved draft. |
| MV-offer-comparison-004 | MEDIUM | defect | "Priority Weights" panel is purely decorative — no interactive control and no scoring logic anywhere consumes the weights, despite the screen's own subtitle promising "weighted decision analysis." |
| MV-offer-comparison-005 | LOW | coverage-gap | No way to edit/remove a single offer once added (matches wireframe, so not a build-vs-wireframe defect, but a product-completeness gap, compounded by MV-001). |
| MV-offer-comparison-006 | LOW | defect | Dollar figures shown with no currency code anywhere on screen; backend computes a currency-qualified `salaryRange` field that the frontend never renders. |

---

## 5. Claim verdicts

Per BRIEF.json, two claim-ledger rows map to this screen (both are multi-screen sweep claims covering offer-comparison among many other screens):

### CLM-024
> "All 27 core Phase-7 gates were VERIFIED-CLOSED including: 0 console errors across 20 routes (GATE-16), 0 same-origin 5xx (GATE-17), backend 676 pytest passed (GATE-19), frontend 297 vitest passed (GATE-20), Playwright E2E green (GATE-21)"

**Verdict: PARTIALLY-TRUE** (scoped to what this screen-tester can verify from the UI).
- The GATE-16/GATE-17 slice ("0 console errors", "0 same-origin 5xx") **is CONFIRMED for the offer-comparison screen specifically**: across 2 full scripted Playwright sessions plus 8 additional targeted investigative sessions on production, `console` events = 0, `pageerror` events = 0, and all 138 captured `/api/*` responses returned HTTP 200 (no 4xx/5xx). Evidence: `test-artifacts/run1__console.json`, `run1__pageerrors.json`, `run1__network.json`, `run2__console.json`, `run2__pageerrors.json`, `run2__network.json`.
- The pytest-676 / vitest-297 / "Playwright E2E green" portions are **UNVERIFIABLE-FROM-UI** — this screen-tester's brief and tooling is production UI/API probing only; re-running the full backend/frontend test suites is out of scope for a single-screen manual verification pass and was not attempted.
- This finding does not contradict the functional defects found (MV-001 through MV-006) — none of them produce console errors or 5xx responses; they are silent functional/business-logic failures, which is itself consistent with a "0 console errors" claim while the feature is still broken underneath.

### CLM-062
> "A Playwright sweep of 14 dashboard routes + /pricing + /admin as a paid admin showed 0 console errors / 0 failed requests / 0 page errors (GATE-03)"

**Verdict: PARTIALLY-TRUE** (scoped identically).
- For the offer-comparison route specifically: **CONFIRMED** — 0 console errors, 0 failed requests, 0 page errors across all sessions this run.
- Cannot attest to the other 15 routes in this claim's scope (out of this screen-tester's assignment).

---

## 6. UNSURE items

None. Every ambiguity encountered during testing was resolved by direct source-code cross-reference (the repo was available) and/or live reproduction, so nothing required escalation as UNSURE this run.

---

## 7. Screenshots index

All paths relative to `uat/reports/evidence/manual-verification/screens/offer-comparison/test-artifacts/`:

| # | File | What it shows |
|---|---|---|
| 1 | `run1__00-unauth-access.png`, `run2__00-unauth-access.png` | Unauthenticated access to `/dashboard/offers` cleanly redirects to `/login`. |
| 2 | `run1__01-load.png`, `run2__01-load.png` | Authenticated load, honest empty state (0 real offers on admin account). Matches wireframe layout/copy. |
| 3 | `run1__02-modal-open.png`, `run2__02-modal-open.png` | Add-Offer modal open, empty form. |
| 4 | `run1__03-empty-submit-errors.png`, `run2__03-empty-submit-errors.png` | Inline validation errors on empty submit (Company/Location/Base required). |
| 5 | `run1__04-after-xss-add.png`, `run2__04-after-xss-add.png` | `<script>` payload in Company field rendered as inert text (no XSS execution) — confirms safe. |
| 6 | `run1__05-after-unicode-add.png`, `run2__05-after-unicode-add.png` | Unicode/emoji company & role names render correctly. |
| 7 | `run1__06-after-valid-mv-offer-add.png`, `run2__06-after-valid-mv-offer-add.png` | 3-card grid, Priority Weights, Negotiation Coach all visible; "Suggested counter: $0 base" visible (MV-002). |
| 8 | `run1__07-draft-counter-email.png` | Drafted counter-offer email showing the "$0 base" text in full (MV-002). |
| 9 | `run1__08-after-reload.png`, `run2__08-after-reload.png` | After reload: all previously-added offers gone, empty state again (MV-001). |
| 10 | `run1__09-after-back-navigation.png`, `run2__09-after-back-navigation.png` | After navigating away and back (no hard reload): offer still gone (MV-001). |
| 11 | `run1__10/11-throttled-*.png`, `run2__10/11-throttled-*.png` | Throttled (50kbps/800ms latency) reload — page still loads correctly, no error state. |
| 12 | `run1__12-final-wireframe-compare.png`, `run2__12-final-wireframe-compare.png` | Final full-page screenshot for wireframe comparison. |
| 13 | `investigate-modal-overlay-gap-visual.png` | Full-page screenshot with modal open — visually confirms the topbar band is NOT dimmed (MV-003). |
| 14 | `investigate-after-bell-click-navigated-away.png` | Post-click state: navigated to `/dashboard/approvals`, modal and draft gone (MV-003). |

---

## 8. Console / network / server-log summary

- **Console errors:** 0 across all sessions (`run1__console.json` = `[]`, `run2__console.json` = `[]`).
- **Page errors (uncaught exceptions):** 0 across all sessions (`run1__pageerrors.json` = `[]`, `run2__pageerrors.json` = `[]`).
- **Network:** `run1` captured 64 `/api/*` responses, `run2` captured 74 — **100% HTTP 200**, 0 failed requests (`requestfailed` events = 0 in both runs). Full logs: `run1__network.json`, `run2__network.json`.
- **Server-side 5xx:** none observed at the network layer during this session (no log-tailer was dispatched alongside this screen-tester run; network-layer evidence above is the basis for the "0 same-origin 5xx" portion of the claim verdicts above).

---

## 9. NOT-TESTED (HUMAN-GATED / cross-screen-dependency reasons only)

- **Populated view with REAL (server-sourced) offer cards** — including the "Top pick" badge/green border treatment and a genuine non-null numeric Fit score derived from `Job.fitScore` — could not be exercised live, because the admin test account has **zero** `Application` rows with `status='offer'`, and there is no way to create one from the offer-comparison screen itself (an offer only becomes eligible for this view once its status is changed elsewhere, in the Application Tracker screen, which is a different tester's assigned scope). Per the shared-environment rules I did not create cross-screen data outside my assignment to force this state. All "populated" evidence in this report is therefore for **client-only, ephemeral, `fitScore: null` ("Pending")** offers added via the modal — verified thoroughly — not for genuine backend-sourced offers.
- **Skeleton loading state (`data-testid="offers-skeleton"`) under throttled network** — attempted twice (50kbps/800ms-latency CDP emulation) but the page consistently finished loading before a screenshot could catch the skeleton frame in either run; not conclusively confirmed present or absent under throttling. Not a HUMAN-GATED item in the strict sense, but genuinely inconclusive with the tooling available in this session (would need a slower emulated profile or a network-level pause to force-capture it).
- **Forced backend 5xx / error state (`data-testid="offers-error"`)** — no mechanism reachable from the UI/production environment to force the `/workspaces/offers` GET to fail (no test-only fault-injection endpoint documented in the runbook); not exercised. This is consistent with the "no service restarts / no code changes" prohibition in the tester protocol.
- **Full backend pytest (676) / frontend vitest (297) suite counts referenced in CLM-024** — out of scope for a single-screen production UI tester; would require running the actual test suites, which this brief does not assign to screen-testers.

---

## 10. Sign-off

Tested by: **screen-tester agent** (Claude Agent SDK, model: Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, screen `offer-comparison`.
All findings above were independently reproduced at least twice in fresh browser sessions before filing, per §3.2.9. No localhost testing was performed; all evidence is from production (`https://5cb5f0620.abacusai.cloud`). No code changes, service restarts, or destructive actions were taken. Test data created was limited to ephemeral (non-persisted) client-side offer entries prefixed `MV-offer-`; since MV-offer-comparison-001 confirms nothing is ever written server-side, there is no server-side test data to clean up (verified via direct GET /api/workspaces/offers showing `"offers": []` at session end).

Report generated: 2026-07-17T16:31:00Z
