# TESTING OUTCOME REPORT — mobile-dashboard (PAID CONTENT RE-TEST)

**Screen ID:** mobile-dashboard
**Screen Name:** Mobile Dashboard (Home hub)
**Route:** `/dashboard` at viewport 390x844
**Wireframe:** `design/screens/mobile-dashboard.html`
**Stage:** Stage 1 PAID re-test (free-plan pass previously filed MV-mobile-dashboard-001..003; this run does NOT re-file those — it cross-checks 001 and adds 004+)
**Environment:** Production — `https://5cb5f0620.abacusai.cloud`
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Test account:** admin/admin123, TEMP Pro entitlement (`GET /api/billing/entitlement` → `{"active_paid":true,"plan":{"id":"pro","status":"active"},"requiresSubscription":true}`)
**Session window (UTC):** 2026-07-17T16:50:18Z → 2026-07-17T17:01:00Z (session 1 + fresh session 2)
**Tester:** screen-tester subagent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1

---

## 1. Summary

With Pro entitlement, `/dashboard` at 390px now renders real, live, dynamically-fetched hub content instead of the free-tier paywall. The content is **not** the wireframe's purpose-built compact mobile hub — it is the entire desktop dashboard (11 widgets) reflowed into a single 390px column, ~6382px tall. Layout itself holds up well under that load: zero horizontal overflow, clean card stacking at every scroll depth, all touch targets ≥44px, zero console errors, zero failed/5xx requests across two independent sessions. The previously-filed header clip (MV-mobile-dashboard-001) reproduces byte-for-byte with content present, and this run identifies a concrete contributing cause (an unhidden desktop account-identity chip). Two new data-integrity/UX issues were found: a 3-way inconsistent "applications" count across widgets on the same page, and a silently-empty "Top Skills" widget with no empty-state messaging. All bottom-tab and in-page interactive elements were exercised and work correctly; numbers are confirmed real (dynamic, backend-driven, no fixture-fingerprint matches).

**Verdict inputs for orchestrator:** `responsive_ok: true` (no overflow/clipping-of-layout in the CSS-box sense, though the pre-existing header text-clip bug persists), `real_data: true`.

---

## 2. What this screen SHOULD do (tester's own view, formed from wireframe before observing production)

Per `design/screens/mobile-dashboard.html`: a compact, glanceable mobile home screen — avatar + "Good morning, {name}" + bell in a single-row header; a 2x2 stat grid (Active/Interview Rate/Offers/Confidence); one "N need your approval" banner with a "Review Now" CTA; a short 3-item "Agent Activity" feed; and a persistent 5-item bottom tab bar (Home/Jobs/Apps/Agents/Profile). The whole thing should fit in roughly one-to-two screen heights — a quick-glance dashboard, with deeper detail reachable via the other tabs.

---

## 3. Element inventory (found → tested → result)

| # | Element | Wireframe design-id | Found in prod? | Tested | Result |
|---|---|---|---|---|---|
| 1 | Header greeting + subtitle | m-topbar-md01 | Present (different markup — shared desktop topbar, not the wireframe's compact header) | Yes | Clips/overflows — reproduces MV-001 (see §6) |
| 2 | Header account-identity chip (avatar+name+role) | *(not in wireframe)* | Present, unconditionally (no responsive hide) | Yes | New finding MV-004 |
| 3 | Notification bell | m-notif-md02 | Present, matching design-id | Yes | Works — navigates to `/dashboard/approvals`, aria-label reflects live pending count |
| 4 | 2x2 stat grid (Active Applications / Interview Rate / Offers / AI Confidence) | m-stats-md04 | Present as 4 stacked full-width cards (not the wireframe's 2x2 grid — single column at this width) | Yes | Renders real dynamic values (7 / 0% / 0 / 38%), no overflow |
| 5 | Needs-approval banner + Review Now | m-approval-md05 / btn-review-md06 | Present, expanded into a full "Needs Approval" section (4 items + Approve/Reject per item + "review all" link) | Partially (navigational link tested; Approve/Reject buttons NOT clicked — see §9 NOT-TESTED) | "review all" → `/dashboard/approvals`, works |
| 6 | Agent Activity feed | m-feed-md07 | Present, with live-dot, "View all" link, and 5 filter pills (All/Discovered/Tailored/Submitted/Waiting) not in the wireframe | Yes | All 5 filters work and correctly filter/empty-state; "View all" → `/dashboard/agents` |
| 7 | Today's Opportunities cards + "Tailor & Apply" / "Review Match" | *(not in wireframe)* | Present | Yes | "Tailor & Apply" → `/dashboard/resume?job=<id>` (link); "Review Match" → `/dashboard/jobs` (link); "posting ↗" external links open new tab with `rel=noopener noreferrer` |
| 8 | Application Funnel widget | *(not in wireframe)* | Present | Yes (read) | Values render; see MV-005 for cross-widget inconsistency |
| 9 | Story Bank widget + "Open" | *(not in wireframe)* | Present | Yes | "Open" → `/dashboard/stories`, works |
| 10 | Recruiter CRM widget + "Open" | *(not in wireframe)* | Present | Yes | "Open" → `/dashboard/networking`, works |
| 11 | Real-Time Market Pulse (Trend Indicators, Jobs-by-Source donut, Top Skills, Job Probability Score, Weekly Activity heatmap, Employer Hiring Activity, Recruiter Activity chart, Market vs. Your Performance) | *(not in wireframe)* | Present | Yes (read) | All render without overflow; Top Skills renders empty with no empty-state copy — MV-006 |
| 12 | Bottom tab bar: Home | m-tabbar-md08 | Present | Yes | Active state correct, 56x56 target |
| 13 | Bottom tab bar: Jobs | m-tabbar-md08 | Present | Yes | → `/dashboard/jobs`, works |
| 14 | Bottom tab bar: Apps | m-tabbar-md08 | Present | Yes | → `/dashboard/applications`, works |
| 15 | Bottom tab bar: Agents | m-tabbar-md08 | Present | Yes | → `/dashboard/agents`, works |
| 16 | Bottom tab bar: Profile | m-tabbar-md08 | Present | Yes | → `/dashboard/settings`; under Pro entitlement this now renders a real Settings & Profile form (contrast with free-tier MV-002 dead-end paywall — see §6) |

---

## 4. Findings (this run — MV-mobile-dashboard-004 onward)

Full JSON: `findings-paid.json`. Summary table:

| ID | Severity | Category | Summary |
|---|---|---|---|
| MV-mobile-dashboard-004 | HIGH | visual | Desktop topbar's account-identity chip has no responsive hide class and renders at 390px, redundantly duplicating "Administrator" and directly contributing to the header clip bug |
| MV-mobile-dashboard-005 | HIGH | wiring | "Applications" count disagrees across three sources on the same page/session: 7 (funnel/stat card) vs 14 (market-pulse) vs 12 (raw `/api/applications` records) |
| MV-mobile-dashboard-006 | MEDIUM | defect | "Top Skills in Demand" widget renders a heading with zero content and no empty-state message, unlike sibling empty states on the same page |
| MV-mobile-dashboard-007 | MEDIUM | coverage-gap | Production serves the full desktop dashboard (11 widgets, 6382px scroll) rather than the wireframe's compact mobile hub — not broken, but a significant design-intent deviation |

Findings 001–003 (free-plan pass) are **not** re-filed here per instruction; see §6 for their cross-check status under paid content.

---

## 5. Claim verdicts

`uat/reports/evidence/manual-verification/screens/mobile-dashboard/BRIEF.json` → `"claim_rows": []`. Independently confirmed by filtering `claims/claim-ledger.json` for any row referencing `mobile-dashboard`: **zero matches**. No claim-ledger rows apply to this screen.

**Verdict: N/A — no claims assigned to mobile-dashboard.**

---

## 6. Cross-check of prior free-plan findings (not re-filed, status only)

- **MV-mobile-dashboard-001** (header clip, HIGH): **REPRODUCES IDENTICALLY** with real content present. Fresh measurement this run: `header height=64px`, `h1.top=-15` (clipped 15px above the header box), `p.bottom=78` (overflows 14px below the header). Matches the original free-tier measurement exactly. Reproduced on both `/dashboard` and `/dashboard/settings` (same shared layout header), and reproduced again in a fully independent fresh session 2. This run additionally identifies a concrete, previously-undocumented contributing cause — filed as new finding MV-mobile-dashboard-004.
- **MV-mobile-dashboard-002** (Profile→paywall dead-end, HIGH): **DOES NOT REPRODUCE under Pro entitlement.** Tapping "Profile" now leads to a fully-populated "Settings & Profile" page (Profile / Resume Management / Portfolio Sync / Notifications / Agent Configuration / Integrations / Privacy & Compliance tabs, all with real form fields and data — see `test-artifacts/paid/profile-settings-body-text.txt` and `p13-nav-profile.png`). This confirms MV-002 was specific to the free-plan paywall gating, not a mobile-navigation defect — useful for the orchestrator's severity/scope adjudication of MV-002, but the finding itself is left for the orchestrator to close/scope, not this report.
- **MV-mobile-dashboard-003** (coverage-gap: hub content unreachable on free plan): **RESOLVED BY THIS RUN.** The wireframed hub content (stats, approval banner, activity feed) is now reachable and has been fully tested (see §3, §4). It turns out to be structurally different from the wireframe (see MV-007) rather than a simple pixel-perfect match.

---

## 7. UI↔backend wiring (network capture)

All dashboard-page network calls captured (`test-artifacts/paid/session1-network.json`). Actual calls fired on `/dashboard` load:

```
POST /api/auth/login                          200
GET  /api/agents                               200
GET  /api/approvals?status=pending             200
GET  /api/billing/entitlement                  200
GET  /api/workspaces/settings                  200
GET  /api/analytics/funnel?period=7d           200
GET  /api/analytics/funnel?period=all          200
GET  /api/stories                              200
GET  /api/jobs?sort=fitScore                   200
GET  /api/agents/runs                          200
GET  /api/workspaces/networking/summary        200
GET  /api/analytics/market-pulse               200
```

Note: the SCREEN-MATRIX row for mobile-dashboard lists `GET /analytics`, `GET /applications`, `GET /workspaces/career-data` as backing endpoints; the actual page instead calls `GET /analytics/funnel`, `GET /analytics/market-pulse`, `GET /agents/runs`, `GET /stories`, `GET /workspaces/networking/summary`, `GET /approvals`. `GET /applications` and `GET /workspaces/career-data` were not called by this page (confirmed reachable directly and returning 200 when queried out-of-band — see `api-crosscheck.json`). This is a documentation/matrix drift, not a functional defect, and is noted for completeness rather than filed as a finding.

All responses drove the UI correctly (values displayed matched response bodies exactly, except for the cross-widget inconsistency documented in MV-005, which is a backend/data-model issue, not a UI-ignoring-the-response issue — the UI faithfully renders what each endpoint returns).

**Real-data confirmation:** wireframe placeholder values (Active 37 / Interview Rate 24% / Offers 3 / Confidence 91%) are completely different from live production values (7 / 0% / 0 / 38%); live values match independently-queried API responses; job/company names shown (Plenti, Brighte, Empire Life, EasyPark, harvey, airwallex) do **not** appear in any `apps/api/tests/fixtures/http/*/jobs.json` fixture file (verified via grep — zero matches); no fixture-fingerprint or lorem-ipsum/placeholder strings found in rendered body text. **real_data: true.**

---

## 8. AI-agent integration

SCREEN-MATRIX lists `"agents": []` for mobile-dashboard — no agents are directly owned by this screen. The dashboard does surface live agent-run history from other screens' agents (Cover Letter Agent, Scout Agent, Matcher Agent, Tailoring Agent, emailAgent) in its Activity feed, sourced from `GET /api/agents/runs`. This data is real and honest: multiple genuine "Cover Letter Agent run failed" entries with specific real error text (e.g., "LLM backend unavailable: budget exhausted before any live attempt could complete for 'cover_letter'", "Fabricated entities detected: ['AI-first']") are shown rather than being hidden or replaced with generic success filler — this is the correct, honest-error-surfacing behavior the protocol asks for. No agent execution was triggered from this screen (out of scope per the empty `agents` list; "Tailor & Apply" and "Review Match" were confirmed to be simple GET-navigational links, not agent-triggering actions, so clicking them did not consume quota or mutate data).

---

## 9. Error/edge states

- **Unauthenticated access:** `GET /dashboard` without a token → clean redirect to `/login` (confirmed, `p01-unauth-redirect.png`).
- **Throttled reload:** CDP-emulated 400kbps/400ms-latency reload completed in 3875ms; an honest loading state ("Checking your subscription..." with skeleton header) was shown mid-load, no raw errors, no blank/broken flash (`p30-throttled-midload.png`, `p31-throttled-finalload.png`).
- **Back/forward:** Dashboard → Jobs → back → Dashboard (state intact, stats re-rendered) → forward → Jobs → back → Dashboard, all transitions clean, zero console errors, zero re-fetch storms observed.

---

## 10. Console / network / server-log hygiene

- **Console:** 0 errors, 0 warnings, 0 pageerrors across all 4 test scripts / both sessions (`session1-console.json`, `session1c-console.json`, `session1d-console.json`, `session2-console.json` — all empty arrays).
- **Network:** 0 failed requests, 0 non-2xx responses across the full session (`session1-failed-requests.json`, `session1d-failed-requests.json` — both empty; `session1-network.json` — 15/15 requests returned 200).
- **Server-side 5xx:** none observed during this session window (monitored via response-status hook on all `/api/` and `/auth/` calls).

---

## 11. Responsive/visual conformance detail

- **Horizontal overflow:** none. `document.documentElement.scrollWidth === document.body.scrollWidth === window.innerWidth === 390` at every scroll depth tested (`overflow-check.json`, `overflowCount: 0`).
- **Card stacking:** clean single-column stacking confirmed via 8 full-viewport screenshots spanning the entire 6382px scroll (`p06-scroll-01` through `p06-scroll-08`) — no overlapping elements, no truncated/clipped card boundaries.
- **Touch targets:** 38 interactive elements inventoried; 0 measured below the 44x44px minimum (`touch-targets.json`). Bottom tab-bar links measure 56x56px each.
- **Charts/SVGs at 390px:** donut chart (Jobs by Source), Job Probability Score ring, and sparklines all render within bounds (`chart-elements-info.json` — max SVG right-edge 357px, well within 390px).
- **Filter-pill row:** "All / Discovered / Tailored / Submitted / Waiting" wraps cleanly to two rows at 390px rather than requiring horizontal scroll (`filter-pills-info.json`: scrollWidth===clientWidth, not scrollable, no overflow).
- **False-positive avoided:** an initial `fullPage:true` screenshot appeared to show the fixed bottom nav bar overlapping mid-page content on `/dashboard/settings`. This was verified to be a Playwright full-page-screenshot capture artifact (fixed-position elements anchor to the real viewport during CDP's expanded-viewport capture, not the virtual full-page height) — NOT a real bug. Confirmed via a genuine scrolled viewport-only screenshot (`p21-settings-fullname-viewport-real.png`) showing the nav correctly fixed at the bottom of the real viewport with no overlap. Documented here for transparency per the "verify twice, never guess" mandate; not filed as a finding.

---

## 12. Screenshots index

All under `test-artifacts/paid/` unless noted.

| File | Description |
|---|---|
| p01-unauth-redirect.png | Unauthenticated `/dashboard` → redirected to `/login` |
| p02-login-page.png | Login form at 390x844 |
| p03-post-login-dashboard.png | Immediately post-login |
| p04-dashboard-full.png | Full-page screenshot, entire hub (6404px) |
| p04b-dashboard-viewport.png | Above-the-fold viewport only |
| p05-header-zoom.png / p07-header-zoom-authed.png | Header clip close-up |
| p06-scroll-01..08-*.png | Full scroll sweep, 800px increments, viewport screenshots |
| p10–p13-nav-*.png | Bottom-tab navigation to Jobs/Apps/Agents/Profile |
| p14-tap-bell.png | Notification bell → `/dashboard/approvals` |
| p15-filter-*.png | Agent Activity filter pills (All/Discovered/Tailored/Submitted/Waiting) |
| p16-view-all.png | "View all" → `/dashboard/agents` |
| p17-browse-all-jobs.png | "Browse all jobs" → `/dashboard/jobs` |
| p18-story-bank-open.png / p19-recruiter-crm-open.png | Story Bank / Recruiter CRM "Open" links |
| p20-review-all-approvals.png | "+1 more waiting — review all" → `/dashboard/approvals` |
| p21-settings-fullname-viewport-real.png | Real scrolled viewport proving the fixed-nav overlap was a screenshot artifact |
| p30-throttled-midload.png / p31-throttled-finalload.png | Throttled-network reload |
| p32-back-nav.png / p33-forward-nav.png | Browser back/forward |
| s2-01/02/03-*.png | Fresh session 2 re-verification screenshots |

---

## 13. NOT-TESTED (HUMAN-GATED reasons only)

- **"Approve" / "Reject" buttons on Needs Approval items (4 items, real buttons, confirmed enabled via DOM inspection in `check-approve-reject.js` output).** NOT clicked. Reason: these are live mutations against shared production account data (pending cover-letter approvals) that this tester did not create — other MANUAL-VERIFICATION testers running concurrently against the same admin/admin123 account may depend on this state for their own in-flight tests (e.g., an agents-screen or approvals-screen tester). Per the STAGE1 protocol's shared-environment rule ("NEVER delete/modify data you did not create"), clicking Approve/Reject would irreversibly resolve another tester's test fixture. Confirmed via DOM that both buttons are real, enabled `<button type="button">` elements wired into the page (not dead/disabled) — full functional testing of the approve/reject mutation flow itself is the responsibility of a dedicated approvals-screen tester.
- **Full end-to-end "Tailor & Apply" agent generation flow** (beyond confirming the CTA is a correct navigational link to `/dashboard/resume?job=<id>`). Reason: SCREEN-MATRIX lists `"agents": []` for mobile-dashboard — deep agent execution belongs to the job-discovery/resume-studio screen's test scope, and triggering a real tailoring generation from this screen would consume Pro-tier LLM quota shared across concurrent testers for a screen where it isn't the assigned scope.
- **Deep functional testing of destination screens reached via the bottom tab bar** (Jobs, Applications, Agents, Settings) beyond confirming correct navigation/URL and absence of an immediate paywall/dead-end. Reason: each of those is a separately-assigned screen with its own tester in this MANUAL-VERIFICATION run; testing them fully here would duplicate/conflict with that screen's dedicated report.

---

## 14. Sign-off

Tested by: screen-tester subagent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1 PAID re-test, mobile-dashboard.
Every finding in this report was reproduced in two independent sessions (session 1 + fresh session 2, `session2-verify-summary.json`) before filing, per the protocol's VERIFY TWICE requirement. No FLAKY items to report — everything reproduced cleanly on first re-check.
