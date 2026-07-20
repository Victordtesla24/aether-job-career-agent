# TESTING OUTCOME REPORT — mobile-approval

**Screen ID:** mobile-approval
**Screen name:** Mobile Approval (responsive variant of approval-modal, tested strictly at mobile viewport)
**Route under test:** `/dashboard/approvals`
**Wireframe reference:** `design/screens/mobile-approval.html`
**Viewport used for ALL captures:** 390 x 844 (iPhone-class mobile), `isMobile: true`, `hasTouch: true`
**Production URL:** https://5cb5f0620.abacusai.cloud
**Repo commit SHA (matches BRIEF.json / canonical-login.md):** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Tester:** screen-tester agent role, model claude-sonnet-5 (Claude Agent SDK)
**Session start (UTC):** 2026-07-17T16:12:49Z
**Session end (UTC):** 2026-07-17T16:29:38Z
**Account used:** admin / admin123 (shared production account, TEMP Pro entitlement) — a concurrently-tested account; only `MV-mobile-approval-`-prefixed rows were created/touched by this tester.

---

## 0. Scope note vs. approval-modal tester

Per orchestrator instructions, a separate tester ("approval-modal") covers the DESKTOP approval experience. This report covers ONLY the mobile rendering of the same route/component (`ApprovalModal.tsx` mobile footer branch + the shared queue list page), tested exclusively at 390x844.

## 1. Own expectation of the screen (formed BEFORE probing production)

Reading `design/screens/mobile-approval.html` before touching production: the wireframe depicts a **dedicated, single-focus, full-screen mobile review card** — header with a back-chevron and an "Approval / 1 of 2 pending" position counter, one action card (agent, job, confidence), an "AI reasoning" list, a "trust this agent" checkbox, and a sticky bottom footer with three tap targets: **Approve & Submit** (primary), **Edit**, **Reject**. No swipe-gesture code exists in the wireframe markup — interaction is tap-based buttons only, so "swipe" affordances were not an expectation drawn from the wireframe itself.

My expectation: at 390px width, tapping "Review" on a pending approval should open a focused, distraction-free single-item review surface matching this wireframe, with the three actions reachable by thumb without horizontal scrolling, and the approve/reject decision should visibly and persistently update the underlying queue.

## 2. What production actually implements

Production's `/dashboard/approvals` is **one shared responsive React component** for both desktop and mobile (`apps/web/src/app/dashboard/approvals/page.tsx` + `apps/web/src/components/approvals/ApprovalModal.tsx`), not a dedicated mobile-only page. At <640px the modal's footer switches to the wireframe's stacked "Approve & Submit / Edit / Reject" button group (`data-testid="modal-approve-btn-mobile"` etc., explicitly comments-referenced to `mobile-approval.html`), and the queue itself is a scrollable card list (not a single-focus swipe view) with inline Review/Approve/Reject buttons per card. This is a defensible design consolidation (one component, two breakpoints) but is a real deviation from the wireframe's dedicated single-item flow — see Finding 001.

---

## 3. Element inventory

| # | Element | data-testid / selector | Tested | Result |
|---|---|---|---|---|
| 1 | Unauthenticated route guard | n/a | Yes | PASS — clean redirect to `/login`, no content flash |
| 2 | Login form (canonical) | `#login-identifier`, `#login-password`, submit | Yes | PASS |
| 3 | Filter tabs: Pending/Approved/Rejected/All | `role="group"` buttons | Yes (all 4) | PASS — correct counts per filter, ≥44px touch targets |
| 4 | Pending count badge | `data-testid="pending-count"` | Yes | PASS — live count, matches list length |
| 5 | Approval card | `data-testid="approval-card"` | Yes (multiple) | PASS |
| 6 | Card "Review"/"View" button | `data-testid="review-btn"` | Yes | PASS — opens modal, 44px height |
| 7 | Card inline "Approve" button | `data-testid="approve-btn"` | Yes | PASS — decides + persists; correctly absent on resolved cards |
| 8 | Card inline "Reject" button | `data-testid="reject-btn"` | Yes | PASS — decides + persists |
| 9 | Expired badge (card) | `data-testid="expired-badge"` | Yes | PASS — present on a genuinely >48h-old row; card approve/reject correctly disabled |
| 10 | Modal backdrop | `data-testid="approval-modal-backdrop"` | Yes | PASS — click-outside closes |
| 11 | Modal close (X) | `data-testid="modal-close-btn"` | Yes | PASS — closes, clears `?review=` param |
| 12 | Modal "why" block | `data-testid="modal-why"` | Yes | PASS — renders payload text verbatim |
| 13 | Modal AI reasoning list | `data-testid="modal-reasoning"` | Yes | PASS — check/warning icons per kind |
| 14 | Modal confidence | `data-testid="modal-confidence"` | Yes | PASS — 91%/77%/etc. match payload |
| 15 | Modal preview / generated letter | `data-testid="modal-preview"` | Yes | PASS — safely escaped, no HTML injection |
| 16 | Trust-agent checkbox | `data-testid="trust-agent-checkbox"` | Yes | PASS — toggles, value round-trips to `trust_agent` in payload |
| 17 | Edit toggle (mobile) | `data-testid="modal-edit-btn-mobile"` | Yes | PASS — shows/hides textarea, "Discard edits" label toggles back |
| 18 | Edit textarea | `data-testid="modal-edit-textarea"` | Yes | PASS — accepts 2000+ char / unicode / `<script>` payload safely |
| 19 | Approve & Submit (mobile footer) | `data-testid="modal-approve-btn-mobile"` | Yes | PASS — fires `POST /approvals/{id}/approve`, 200, persists |
| 20 | Reject (mobile footer) | `data-testid="modal-reject-btn-mobile"` | Yes | PASS — fires `POST /approvals/{id}/reject`, 200, persists |
| 21 | Expired-note banner (modal) | `data-testid="modal-expired-note"` | Yes | PASS — shown, all 3 mobile footer buttons disabled |
| 22 | Already-resolved banner (modal) | n/a (inline text) | Yes | PASS — "This request was already approved/rejected on …" |
| 23 | Deep link `?review=<valid-id>` | URL param | Yes | PASS — opens modal directly, read-only for resolved rows |
| 24 | Deep link `?review=<invalid-id>` | URL param | Yes | **FINDING** — see MV-mobile-approval-002 |
| 25 | Browser back/forward | n/a | Yes | PASS — standard history semantics, no dead-ends |
| 26 | Global topbar notification bell/badge | `a[aria-label*="Notifications"]` | Yes | PASS — `aria-label="Notifications — N pending approvals"`, live-matches pending count, coral dot badge, links to same route |
| 27 | Bottom mobile nav (Home/Jobs/Apps/Agents/Profile) | `<nav>` fixed | Yes | PASS — no overlap with last card at true scroll-bottom (viewport screenshot confirmed) |
| 28 | Horizontal overflow at 390px | n/a | Yes | PASS — `scrollWidth === clientWidth === 390` in every capture |
| 29 | Empty-state copy | `data-testid="approvals-empty-state"` | Not reproduced | COVERAGE-GAP — no filter naturally had 0 rows during the session (shared account always had ≥2 rows per status); code-reviewed only (`apps/web/src/app/dashboard/approvals/page.tsx` "Queue clear" text) — do not close this as tested |
| 30 | `POST /approvals/{id}/execute` | n/a | No UI trigger found | Confirmed via full-repo grep: no frontend call site exists; invoked only server-side (`apps/api/app/agents/email_agent.py`) after approval. Not reachable from this screen's UI — see NOT-TESTED. |
| 31 | Throttled reload (CDP 500kbps/800ms latency) | n/a | Yes | PASS — honest "Checking your subscription…" loading state, then loads correctly, no false error |

## 4. Findings

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-mobile-approval-001 | MEDIUM | visual | Wireframe's single-focus "1 of 2 pending" step-through-queue pattern (back-chevron, position counter, implied auto-advance) is not implemented; production always returns to the full list after a decision with no position indicator. |
| MV-mobile-approval-002 | MEDIUM | wiring | Invalid/stale `?review=<id>` deep-link error message is race-conditioned between two competing `setError` calls; silently absent in 5/7 fresh-session repro attempts. |

Full JSON: `findings.json` (same directory).

## 5. Claim verdicts

| Claim ID | Claim | Verdict | Evidence |
|---|---|---|---|
| CLM-077 | "Approval requests show a 48-hour expiry badge, with actions disabled once expired" | **CONFIRMED** | Live data existed with a genuine >48h-old pending row (`Cover letter for Business Analyst @ InterEx Group`, created 2026-07-15T02:58:09, i.e. >48h before this session). Confirmed at all 3 layers: (1) card-level `expired-badge` visible + inline Approve/Reject `disabled=true`, forced click fires zero network request; (2) modal-level `modal-expired-note` text "This request is older than 48h and has expired — re-run the agent to get a fresh one. Actions are disabled." + all mobile footer buttons `disabled=true`; (3) backend defense-in-depth — direct `POST /api/approvals/{id}/approve` on the same expired id returns `409 {"detail":"Approval expired (> 48h old); re-run the agent"}`. Screenshots: `test-artifacts/17-all-filter-expiry-check.png`, `test-artifacts/25-expired-modal-view.png`. Reproduced twice (Session 1 evaluation + independent `expired_check.mjs` run, both against the same live expired row, plus a fresh direct-curl confirmation). |

No other claim-ledger rows were mapped to `mobile-approval` in `BRIEF.json`/`claim-ledger.json` (CLM-046 maps to agent-monitor/resume-studio/cover-letter-studio only, not this screen).

## 6. UNSURE items

None. Every ambiguity encountered (the full-page-screenshot backdrop bleed-through, the deep-link race) was resolved with additional targeted probes (viewport-only screenshots, DOM `getComputedStyle`/`getBoundingClientRect` checks, repeated fresh sessions) rather than left as a guess.

**Methodology note (not a finding):** early full-page (`fullPage: true`) screenshots of the open modal appear to show page content "bleeding through" behind the modal backdrop (e.g. `06-modal-open-mobile.png`). This is a Playwright full-page-screenshot capture artifact for `position: fixed` elements (it captures the full document flow beyond the viewport regardless of `body{overflow:hidden}`, which real users cannot scroll into) — confirmed NOT a real defect via a matched viewport-only screenshot (`06b-modal-viewport-only.png`) and `document.body` computed-style/scrollHeight checks. Recorded here for the record since several screenshots in the index below still show this stitching artifact.

## 7. Screenshots index

All paths relative to `uat/reports/evidence/manual-verification/screens/mobile-approval/test-artifacts/`.

| File | What it shows |
|---|---|
| `00-FINAL-approvals-list-mobile-clean.png` | Clean final full-page mobile queue list |
| `01-unauth-redirect.png` | Unauthenticated access → redirected to `/login` |
| `02-login-form.png` | Canonical login form, mobile viewport |
| `03-approvals-list-mobile.png` | Authenticated queue list, mobile, pending filter |
| `04-filter-{pending,approved,rejected,all}.png` | Each filter tab result |
| `05-target-card-visible.png` | Our `MV-mobile-approval-` approve-target card in list |
| `06-modal-open-mobile.png` / `06b-modal-viewport-only.png` | Modal open (full-page vs true-viewport, see methodology note) |
| `07-edit-mode-mobile.png` | Edit textarea open, mobile footer |
| `08-after-close.png` | Modal closed via X |
| `09-after-approve.png` | Immediately after Approve & Submit |
| `10-approved-filter-after-reload.png` | Persistence proof — approved filter after reload |
| `11-reject-card-visible.png` / `12-after-inline-reject.png` | Inline-card reject flow |
| `13-rejected-filter-after-reload.png` | Persistence proof — rejected filter after reload |
| `14-after-browser-back.png` | Browser back navigation |
| `15-deeplink-review.png` | Valid `?review=<resolved-id>` deep link, read-only view |
| `16*-deeplink-invalid*.png` | Invalid deep-link repro attempts (finding 002) |
| `17-all-filter-expiry-check.png` | CLM-077 evidence — expired badge in "all" filter |
| `18-20` | Edit + XSS/unicode/2000-char boundary content flow |
| `21-edited-preview-after-reload.png` | Edited content persisted + safely rendered after reload |
| `22-23-throttled-*.png` | CDP-throttled reload (500kbps/800ms latency) |
| `24-scrolled-to-bottom-viewport.png` | Bottom-nav overlap check (no overlap) |
| `25-expired-modal-view.png` | CLM-077 modal-level evidence |
| `26-28` | Session 2 (fresh browser) repeat of core approve/reject + persistence |
| `29-notification-badge-topbar.png` | Global topbar notification bell/badge, live pending count |
| `session1-*.{json,txt}`, `session2-*.{json,txt}` | Console/network/log dumps per session |

## 8. Console / network / server-log summary

- **Uncaught JS exceptions:** 0 across both sessions.
- **Console errors:** Only the browser's own "Failed to load resource: 404" entries generated by our *intentional* invalid-approval-id probes (2 occurrences total across both sessions) — these are the expected client log of a deliberately-triggered, handled 404, not application crashes.
- **Network requests captured (Session 1):** 81 total; 80×200, 1×404 (intentional). **0×5xx.**
- **Server errors:** No 5xx responses observed from the API at any point in either session, across ~90+ authenticated requests (list/get/approve/reject/login/other dashboard widgets loaded on the same page).
- **Endpoints from SCREEN-MATRIX confirmed wired live:** `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject` — all fired with expected verbs/paths and drove UI state (verified via response-status assertions in Session 2 and full request/response capture in Session 1).
- **`POST /approvals/{id}/execute`** — not fired by any UI action on this screen; confirmed by full-repo grep to have no frontend call site (backend-internal, invoked by `apps/api/app/agents/email_agent.py` post-approval). See NOT-TESTED.

## 9. NOT-TESTED (with reasons)

| Item | Reason |
|---|---|
| `POST /approvals/{id}/execute` | No UI element on this screen (or anywhere in the frontend, confirmed by repo-wide grep) invokes this endpoint directly — it is a backend/agent-internal call triggered after approval, not user-facing. Cannot be exercised "as a user" from this screen; this is an architectural fact, not a coverage shortcut. |
| Empty-state rendering (`data-testid="approvals-empty-state"`) | The shared production account always had ≥2 rows in every status filter throughout this session (concurrent testers were actively creating/resolving approvals). Forcing an empty state would require deleting other testers' data, which is explicitly prohibited by the shared-environment rules. Code-reviewed only (not fresh-evidence-verified) — treat as unverified, not passed. |
| Native swipe gesture (left/right swipe to approve/reject) | The wireframe itself contains no swipe-gesture markup/library — only tap-target buttons (Approve & Submit / Edit / Reject). No swipe expectation exists to test against; brief's mention of "swipe/tap affordances" is satisfied by the tap-based buttons, which were fully tested. |

## 10. Sign-off

Tested by: screen-tester agent (Claude Agent SDK, model claude-sonnet-5), MANUAL-VERIFICATION Stage 1, screen `mobile-approval`, route `/dashboard/approvals`, mobile viewport 390x844 only.
All findings and the claim verdict above are [VERIFIED-WITH-FRESH-EVIDENCE] against production at commit `53f0e084da5b460835c32d3e07d496e6e67a8616`, session window 2026-07-17T16:12:49Z–16:29:38Z, with every finding reproduced in at least 2 independent fresh browser sessions per the VERIFY TWICE requirement (finding 002 was additionally corroborated across 7 total repro attempts to characterize its race-condition nature). No self-closure performed; both findings filed as OPEN for fixer/QA adjudication.
