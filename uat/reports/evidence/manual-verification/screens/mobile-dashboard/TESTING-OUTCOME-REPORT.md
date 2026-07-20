# TESTING-OUTCOME-REPORT — mobile-dashboard

## Screen identity
- **Screen id:** mobile-dashboard
- **Screen name:** Mobile Dashboard (responsive variant of the Dashboard, tested at MOBILE viewport)
- **Route:** `/dashboard`
- **Viewport:** 390x844 (all captures)
- **Wireframe:** `design/screens/mobile-dashboard.html`
- **Backing endpoints (per BRIEF/matrix):** `GET /workspaces/career-data`, `GET /analytics`, `GET /applications`, `GET /jobs`, `GET /agents`
- **Agents wired to this screen:** none (`agents: []` in BRIEF.json)
- **Claim-ledger rows mapped to this screen:** none (`claim_rows: []` in BRIEF.json; independently re-verified by filtering the full `claims/claim-ledger.json` — no row's `screens[]` array contains `"mobile-dashboard"`)

## Environment
- **Production URL:** https://5cb5f0620.abacusai.cloud
- **Repo / commit SHA:** /home/ubuntu/github_repos/aether-job-career-agent @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Test account:** admin/admin123 (per canonical-login.md; confirmed `isAdmin:false`, `active_paid:false`, plan `free`, `requiresSubscription:true` via live `GET /api/billing/entitlement`)
- **Tool:** Playwright (chromium) driven via ad-hoc Node scripts, headless, viewport locked to 390x844 for all mobile captures (one 1440x900 capture used only for desktop-comparison context)
- **Session start (UTC):** 2026-07-17T15:15:40Z (first login, session 1)
- **Session end (UTC):** 2026-07-17T15:22:37Z (fresh-session re-verification + throttled reload pass complete)
- All timestamps below are from network/console logs captured in `test-artifacts/*.json`.

## Approach
I read `design/screens/mobile-dashboard.html` before touching production and formed my own expectation: a compact single-screen mobile dashboard — small top bar (avatar+greeting left, bell right, one line), a 2x2 stats grid, a "needs approval" banner with a Review Now CTA, a live Agent Activity feed, and a fixed bottom tab bar (Home/Jobs/Apps/Agents/Profile). I then tested the live route against that expectation, the 9-point §3.2 protocol, and general mobile-UX product sense (touch targets, overflow, clipping, sticky/fixed elements).

## Element inventory

| # | Element | Wireframe design-id | Present in prod? | Tested | Result |
|---|---|---|---|---|---|
| 1 | Top header (avatar/greeting/date) | m-topbar-md01 | Present, but is the **desktop** header component (not the wireframe's compact mobile header) | Yes | **Clipped at 390px** — see MV-mobile-dashboard-001 |
| 2 | Notification bell (badge dot) | m-notif-md02 | Present, `data-design-id="m-notif-md02"` matches wireframe | Yes — tapped | Navigates to `/dashboard/approvals`, no errors |
| 3 | Main content area | m-main-md03 | Replaced entirely by subscription-paywall card for this account tier | Yes (as far as reachable) | See MV-mobile-dashboard-003 (coverage gap) |
| 4 | 2x2 stats grid (Active/Intvw Rate/Offers/Confidence) | m-stats-md04 | **Absent** (paywall shown instead) | Not reachable this session | Coverage gap, see MV-mobile-dashboard-003 |
| 5 | "Needs approval" banner + Review Now | m-approval-md05 / btn-review-md06 | **Absent** | Not reachable this session | Coverage gap, see MV-mobile-dashboard-003 |
| 6 | Agent Activity feed | m-feed-md07 | **Absent** | Not reachable this session | Coverage gap, see MV-mobile-dashboard-003 |
| 7 | Paywall card: "View plans & subscribe" button | n/a (not in wireframe; account-tier-specific) | Present | Yes — tapped | Navigates to `/pricing`, pricing page renders cleanly at 390px, no overflow |
| 8 | Paywall card: inline "pricing" text link | n/a | Present | Yes — tapped (separately from the button, distinct DOM node) | Navigates to `/pricing`, works |
| 9 | Bottom tab bar container | m-tabbar-md08 | Present, `data-design-id="m-tabbar-md08"` matches wireframe, `position:fixed`, `lg:hidden` (mobile-only) | Yes | Conforms to wireframe structurally |
| 10 | Bottom tab: Home | (part of m-tabbar-md08) | Present, href=`/dashboard` | Yes — tapped | Active-state highlight correct, no errors |
| 11 | Bottom tab: Jobs | " | Present, href=`/dashboard/jobs` | Yes — tapped | Navigates correctly, active-state highlight correct |
| 12 | Bottom tab: Apps | " | Present, href=`/dashboard/applications` | Yes — tapped | Navigates correctly |
| 13 | Bottom tab: Agents | " | Present, href=`/dashboard/agents` | Yes — tapped | Navigates correctly |
| 14 | Bottom tab: Profile | " | Present, href=`/dashboard/settings` | Yes — tapped | Navigates, but destination is a dead end — see MV-mobile-dashboard-002 |
| 15 | Desktop left sidebar (13 items: Dashboard/Jobs/Resume Studio/Cover Letter Studio/Story Bank/Applications/Interview Center/Networking/Email Center/Agents/Analytics/Offers/Settings) | n/a in wireframe | Present in DOM but `display:none`-equivalent at mobile width (rect 0x0, `visible:false`) | Verified via DOM query | Correctly hidden at mobile breakpoint; **no hamburger/drawer or "more" affordance replaces it** — 8 of 13 desktop destinations (Resume Studio, Cover Letter Studio, Story Bank, Interview Center, Networking, Email Center, Analytics, Offers) have no mobile navigation path at all. Noted for context; not filed as a standalone finding because the wireframe itself only specifies the 5-item bottom nav, so this is not a deviation from the wireframe's own IA — flagged here as a product-sense observation only. |
| 16 | Desktop-only search box (`w-72 max-lg:hidden`) | n/a | Correctly hidden at mobile, no mobile equivalent inserted | Verified via DOM | Matches wireframe (no search box in mobile wireframe either) |
| 17 | Unauthenticated access to `/dashboard` | n/a | Redirects | Yes (x2, fresh sessions) | Clean redirect to `/login`, no flash of protected content, no console errors |

No `<form>` elements exist on `/dashboard` at mobile viewport (the only text `<input>` in the DOM is the desktop search box, `max-lg:hidden` — not rendered/reachable on mobile). Protocol point 3 (form valid/empty/boundary/XSS testing) is therefore **not applicable** to this screen at mobile viewport — confirmed by DOM enumeration, not assumed.

## Findings

| id | severity | category | summary |
|---|---|---|---|
| MV-mobile-dashboard-001 | HIGH | visual | Mobile header (greeting + last-agent-run subtitle) clipped at 390px — desktop header component reused unresponsively; text top clipped above viewport, subtitle overflows below header box |
| MV-mobile-dashboard-002 | HIGH | defect | Bottom-nav "Profile" tab leads to `/dashboard/settings`, which shows the generic paywall with no account-management UI, contradicting the paywall's own "manage your account" copy |
| MV-mobile-dashboard-003 | LOW | coverage-gap | Wireframe's stats grid / approval banner / activity feed untestable on mobile — account has no active subscription; frontend correctly gates before calling BRIEF-listed data endpoints (this is a coverage gap, not a defect — the entitlement-driven gating itself is confirmed working correctly) |

Full JSON rows: `findings.json` (schema per STAGE1-TESTER-PROTOCOL.md §4.1).

### MV-mobile-dashboard-001 detail (VERIFIED-WITH-FRESH-EVIDENCE, reproduced twice)
DOM measurement, session 1 (2026-07-17, `header-clip-detail.json`) and session 2 — an independent fresh browser context with no shared storage/cookies (`session2-fresh-verify-summary.json`) — both produced **identical** numbers:
- Header box: `top:0 bottom:64` (fixed 64px, Tailwind `h-16`)
- `<h1>` "Good afternoon, Administrator": rendered `top:-15 bottom:30 height:45` (wraps to 2 lines; ~15px of the first line renders above the header/viewport top and is not visible)
- `<p>` "Fri, 17 July · last agent run 3h ago": rendered `top:30 bottom:78 height:48` (wraps to 3 lines; bottom edge is 14px past the header's own bottom edge, bleeding into the page body)

Desktop viewport (1440x900, same account, same page — `06-desktop-comparison-1440.png`) renders the identical text on a single unclipped line, confirming the defect is specific to the mobile width.

### MV-mobile-dashboard-002 detail (VERIFIED-WITH-FRESH-EVIDENCE, reproduced twice)
HTML source confirms the paywall copy: `You can still browse <a href="/pricing">pricing</a> and manage your account.` — "manage your account" is plain text with zero corresponding link/button anywhere in the DOM. Direct navigation to `/dashboard/settings` (both via bottom-nav tap and via fresh `page.goto`, in two independent sessions) renders `data-testid="subscription-paywall"` with the same "Subscribe to unlock Aether" content — no settings form, no account fields.

### MV-mobile-dashboard-003 detail
`GET /api/billing/entitlement` (curled directly with the session token) returns `{"active_paid":false,"plan":{"id":"free","status":"active"},"requiresSubscription":true}`. Direct curls to `GET /api/workspaces/career-data`, `/api/analytics`, `/api/applications`, `/api/jobs`, `/api/agents` with the same bearer token all return HTTP 200 — the backend endpoints are live and working — but the captured network trace of the `/dashboard` page load (`session1-network.json`, `session2-network.json`) shows only `GET /api/agents`, `GET /api/approvals?status=pending`, `GET /api/billing/entitlement`, `GET /api/workspaces/settings` firing; the frontend never calls career-data/analytics/applications/jobs because it renders the paywall first. This is **correct, wiring-confirmed gating behavior** for this account tier, not a defect — filed as a coverage gap because it means I cannot confirm the wireframe's stats grid / approval banner / activity feed render correctly (card stacking, no overflow, no truncation) on a 390px screen. Requires a subscribed test account to close.

## UI↔backend wiring summary (protocol point 4)
- `GET /api/billing/entitlement` → drives the paywall render faithfully (confirmed: response `requiresSubscription:true` ⇒ UI shows paywall, not dashboard content). **Wiring CONFIRMED correct.**
- `GET /api/agents`, `GET /api/approvals?status=pending`, `GET /api/workspaces/settings` fire on every `/dashboard` load regardless of entitlement (used to populate header/notification state) — all returned HTTP 200 in both sessions.
- `GET /workspaces/career-data`, `GET /analytics`, `GET /applications`, `GET /jobs` (BRIEF-listed) — never fired in this session; backend confirmed reachable via direct curl (200 each) but frontend short-circuits before calling them. See MV-mobile-dashboard-003.
- No 4xx/5xx responses observed in any session. No `requestfailed` events in any session.

## AI-agent integration (protocol point 5)
Not applicable — `agents: []` in this screen's BRIEF; no agent-trigger UI is present on `/dashboard` itself (the "Agents" bottom-tab link only navigates to `/dashboard/agents`, which is out of this screen's scope).

## Error / edge states (protocol point 6)
- **Unauthenticated access:** `GET /dashboard` while logged out → clean redirect to `/login`, no flash of protected content, tested twice (session 1: `01-unauth-dashboard-redirect.png`; session 2 fresh context: `20-fresh-unauth-redirect.png`). **PASS.**
- **Throttled reload:** CDP-emulated ~500kbps/400ms-latency network, full reload of `/dashboard` while authenticated. Completed in 1.9s with no errors, no failed requests, no infinite spinner; mid-load screenshot (`30-throttled-midload.png`) shows partial-but-coherent content (not a blank flash or broken skeleton), final state (`31-throttled-finalload.png`) matches normal-speed load. **PASS**, though note the header-clip defect (MV-001) is present in both the throttled and normal-speed final renders.
- **Back/forward:** Chained `goBack`/`goForward` across Home→Jobs→back→Apps→back→Agents→back→Profile→back→bell→back→View-plans→back→Home→back→forward exercised without console errors or broken states; final `goForward` correctly landed back on `/dashboard`. One history-stack quirk observed: after many chained back-navigations the stack unwound further than expected (ended on `/login`) — this is standard behavior for a SPA where re-clicking a Link to the *already-current* route does not push a new history entry (confirmed not a defect, just documented for transparency; no data loss or broken UI resulted).

## Console / network / server-log hygiene (protocol point 7)
- Session 1 (initial login + full element sweep): **0** console errors, **0** `pageerror` events, **0** failed requests.
- Session 1b (bottom-nav + link sweep, 10 navigations): **0** console errors.
- Session 2 (fresh context, unauth redirect + login + settings dead-end re-check): **0** console errors, **0** failed requests, 11 API calls all 200.
- Session 3 (throttled reload): **0** console errors, **0** failed requests.
- No server 5xx observed in any captured network log across all 4 sessions.

## Claim verdicts
No claim-ledger rows are mapped to `mobile-dashboard` (verified by filtering `claims/claim-ledger.json` — 101 total claims, zero with `"mobile-dashboard"` in their `screens[]` array; the two closest matches, CLM-046 and CLM-077, are scoped to `agent-monitor`/`resume-studio`/`cover-letter-studio` and `approval-modal`/`mobile-approval` respectively, not this screen). **No claims to adjudicate for this screen.**

## UNSURE items
None requiring escalation beyond what is already captured as MV-mobile-dashboard-003 (a documented coverage gap with a clear, non-ambiguous cause — account entitlement — rather than genuine uncertainty about correct behavior).

## Screenshot index
All paths relative to `test-artifacts/`:
- `01-unauth-dashboard-redirect.png` — unauth `/dashboard` → `/login` redirect (session 1)
- `02-login-page-mobile.png` — login form at 390x844
- `03-post-login-dashboard-mobile.png`, `04-dashboard-mobile-loaded.png` — post-login dashboard, full page
- `05-viewport-only-top.png` — viewport-only (non-fullpage) capture at scroll=0, shows header clip in-viewport (not a fullPage-stitch artifact)
- `06-desktop-comparison-1440.png` — same account/route at 1440x900 for contrast (header not clipped)
- `07-header-zoom.png` — cropped 390x100 top-of-page detail
- `08-tap-jobs-tab.png` / `09-tap-apps-tab.png` / `10-tap-agents-tab.png` / `11-tap-profile-tab.png` — bottom-nav destinations
- `12-tap-notif-bell.png` — `/dashboard/approvals`
- `13-tap-view-plans.png` — `/pricing` via button
- `14-direct-settings-fresh.png` — direct nav to `/dashboard/settings`, paywall dead end
- `15-tap-inline-pricing-link.png` — `/pricing` via inline text link
- `20-fresh-unauth-redirect.png`, `21-fresh-dashboard-loaded.png`, `22-fresh-settings-deadend.png` — session 2 (fresh context) re-verification
- `30-throttled-midload.png`, `31-throttled-finalload.png` — session 3 throttled reload

## Supporting data files (test-artifacts/)
- `interactive-elements.json` — full DOM enumeration of buttons/links/inputs with visibility + bounding rects
- `header-info.json`, `header-clip-detail.json` — precise header/h1/p bounding-rect measurements
- `dashboard-full-html.html` — captured page HTML (design-id audit, paywall-copy citation)
- `dashboard-body-text.txt`, `settings-body-text.txt` — innerText dumps
- `session1-*.json`, `session1b-*.json`, `session2-*.json`, `session3-*.json` — console/network/failed-request logs per session

## NOT-TESTED (HUMAN-GATED only)
1. **Wireframe main-content mobile rendering** (2x2 stats grid card-stacking, approval-banner button behavior, Agent Activity feed truncation/overflow at 390px) — requires a test account with `active_paid:true`. Cannot be produced by the tester (no self-service upgrade path was in scope/permitted; account-tier changes are outside this screen's brief). See MV-mobile-dashboard-003.
2. **Account-management screen mobile rendering** — `/dashboard/settings` is paywalled for this account tier (see MV-mobile-dashboard-002); its actual settings-form UI at mobile width (if any exists behind the paywall) is untested for the same reason.
3. **Real AI-agent run from this screen** — out of scope: `agents: []` in BRIEF, no agent-trigger control exists on `/dashboard` itself.

## Tester sign-off
Tested by: screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage 1, screen `mobile-dashboard`.
All findings reproduced in at least 2 independent sessions (one with a completely fresh browser context / no shared storage) before filing, per §3.2 point 9. No fixture/mock data injected. No code changes made. Evidence timestamps are UTC, taken from live production capture during this run (2026-07-17).
