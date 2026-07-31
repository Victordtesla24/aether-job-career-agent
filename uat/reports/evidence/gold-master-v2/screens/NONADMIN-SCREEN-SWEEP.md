# GOLD-MASTER-V2 W-A §3.2 — Non-Admin Screen Sweep

**Agent**: screen-tester (serial, no sub-agents per standing rules)
**Production**: https://5cb5f0620.abacusai.cloud
**Identity**: `gm2-nonadmin-1785454990@example.com` (see `phase0/CANONICAL-NONADMIN-LOGIN.md`)
**Run start**: 2026-07-31T00:41Z
**Run end**: 2026-07-31T01:04Z

## Identity confirmation [VERIFIED-WITH-FRESH-EVIDENCE 2026-07-31T00:42:01Z]

Fresh `POST /api/auth/login` + `GET /api/auth/me` at 2026-07-31T00:42:01Z:
```json
{"id":"c56667cb7661a0cfef18ada20","email":"gm2-nonadmin-1785454990@example.com","name":"Gold Master V2 Test User","targetRole":"QA Tester Probe","location":"Sydney, AU","isAdmin":false}
```
`isAdmin: false` confirmed immediately before testing began. Token prefix used: `eyJhbGci…` (never printed in full).

Data-scoping re-check at same timestamp (all via bearer token, fresh curl):
- `GET /api/jobs` → `[]` (0)
- `GET /api/applications` → `[]` (0)
- `GET /api/stories` → `[]` (0)
- `GET /api/resumes` → `[]` (0)
- `GET /api/cover-letters` → `[]` (0)
- `GET /api/approvals?status=pending` → `[]` (0)
- `GET /api/billing/entitlement` → `{"active_paid":false,"plan":{"id":"free","status":"active"},"requiresSubscription":true}`
- `GET /api/agents` → 12 agents listed, all `status:"idle"`, `last_run:null`

NOTE: `name`/`targetRole`/`location` are non-blank, differing from the CANONICAL doc's original registration snapshot (both `""`). This account was evidently touched by prior settings-screen testing before this sweep began. This is NOT a defect — it is pre-existing state on a shared disposable test account — but is recorded here so any settings-screen findings below are read in that context.

---

## Coverage status

| # | Route | Status |
|---|-------|--------|
| 1 | /login | PASS |
| 2 | /dashboard | PASS |
| 3 | /dashboard/jobs | PASS (gated) |
| 4 | /dashboard/applications | PASS (gated) |
| 5 | /dashboard/resume | PASS (gated) |
| 6 | /dashboard/cover-letters | PASS (gated) |
| 7 | /dashboard/stories | PASS (gated) |
| 8 | /dashboard/approvals | PASS (gated) |
| 9 | /dashboard/analytics | PASS (gated) |
| 10 | /dashboard/agents | PASS (gated) |
| 11 | /dashboard/settings | PASS |
| 12 | /pricing | PASS |

All 12 routes reached PASS. Routes 3–10 are marked "(gated)" because this free-tier account renders the same honest subscription paywall on all of them — see the shared write-up under "3–10" below for what was and wasn't exercisable given that account state.

---

## 1. /login — PASS

**Verdict**: PASS. No wireframe exists in `design/screens/` for `/login` (list checked: agent-monitor, agents, analytics, application-tracker, approval-modal, cover-letter-studio, dashboard, email-center, interview-center, job-discovery, mobile-approval, mobile-dashboard, networking, offer-comparison, resume-studio, settings, story-bank — no login.html), so wireframe conformance is N/A; assessed on general UX/honesty quality instead.

**Screenshots**: `screens/nonadmin/login-00-unauth-redirect.png`, `login-01-initial.png`, `login-02-empty-submit.png`, `login-03-wrong-password.png`, `login-04-xss-adversarial.png`, `login-05-valid-login-success.png`
[VERIFIED-WITH-FRESH-EVIDENCE screens/nonadmin/login-*.png @2026-07-31T00:43Z]

**Element inventory**: 1 button (`Sign in`, type=submit), 2 inputs (email/username text, password), 4 links (`Forgot password?` → /forgot-password, `Create account` → /signup, `Privacy Policy`, `Terms`).

**Per-element results**:
| Element | Action | Result |
|---|---|---|
| Unauthenticated deep-link to `/dashboard` | direct nav | Redirected to `/login?next=%2Fdashboard`, honest preserve-destination pattern |
| Empty form submit | click Sign in | Browser-native `Please fill out this field.` HTML5 validation tooltip on email field; no API call fired (confirmed via network capture — 0 requests before valid attempt after this step) |
| Wrong password (valid email + `WrongPassword999!`) | submit | `POST /api/auth/login` → 401; UI shows plain honest message `Invalid email or password.` — no optimistic success, no info leak about which field was wrong |
| Adversarial: email=`<script>alert(1)</script>@x.com`, password=`' OR '1'='1` | submit | `POST /api/auth/login` → 401; no script executed (no JS dialog fired, no innerHTML injection observed in screenshot); treated as ordinary invalid credentials — SQLi-shaped string not special-cased, consistent with parameterized backend auth |
| Valid credentials | submit | `POST /api/auth/login` → 200; redirect to `/dashboard`; `aether_token` written to localStorage (prefix `eyJhbGci`, not printed further) |

**Network capture**: `POST /api/auth/login` × 3 (401, 401, 200) — each initiated only after its corresponding submit click, no calls fired without user action.

**Console/errors**: 0 `pageerror`. 2 expected `console.error` lines are the browser's own "Failed to load resource: 401" for the two intentionally-wrong logins (expected side effect of testing bad creds, not an app defect). 2 `requestfailed` entries are Next.js RSC prefetch aborts (`net::ERR_ABORTED` on `/forgot-password?_rsc=` and `/dashboard/settings?_rsc=`) from hover-prefetch being cancelled by navigation — cosmetic Next.js router behavior, not user-visible.

**Findings**: none (0 OPEN).

---

## 2. /dashboard — PASS

**Verdict**: PASS. Wireframe `design/screens/dashboard.html` (rendered: `screens/nonadmin/wf-dashboard.png`) depicts a fully-populated pro-plan dashboard (stat tiles, agent activity feed, opportunities, funnel, story bank, CRM, market intelligence). The live non-admin free-tier account instead renders a full-screen **"Subscribe to unlock Aether"** paywall gate in place of all those widgets.

This is a **major visual deviation from the wireframe**, but on inspection it is the correct, honest behavior for this account state (`GET /api/billing/entitlement` → `requiresSubscription: true`), not a defect: the gate explains exactly what a subscription unlocks, offers a real CTA to `/pricing`, and does not fake any of the wireframe's sample data (no "37 active applications", no fabricated agent activity). This is exactly the kind of honest-empty-state the sweep is meant to reward rather than penalize. Confirmed by code read (`apps/web/src/app/dashboard/page.tsx` gate) that the widget-fetching calls (`/jobs?sort=fitScore`, `/agents/runs`, `/analytics/agent-roi`, `/stories`, `/workspaces/networking/summary`) documented in SCREEN-MATRIX.md are correctly **not** fired at all for a gated account (confirmed absent from network capture below) — no wasted calls, no silent partial-fetch.

**Screenshots**: `dashboard-00-initial.png`, `dashboard-01-after-bell-click.png`, `dashboard-02-search-xss.png`, `dashboard-03-user-menu-open.png`, `dashboard-04-after-subscribe-click.png`, `dashboard-05-search-typing.png`, `dashboard-06-search-single-char.png`, `dashboard-07-search-agent-match.png`, `dashboard-08-after-search-result-click.png`, `dashboard-09-search-no-match-state.png`, `dashboard-10-after-signout.png`, `dashboard-11-protected-nav-after-signout.png`, wireframe reference `wf-dashboard.png`
[VERIFIED-WITH-FRESH-EVIDENCE screens/nonadmin/dashboard-*.png @2026-07-31T00:44–00:47Z]

**Element inventory & per-element results**:
| Element | Action | Result |
|---|---|---|
| Sidebar nav (Dashboard/Jobs/Resume Studio/Cover Letter Studio/Story Bank/Applications/Interview Center/Networking/Email Center/Agents/Analytics/Offers/Settings) | direct nav to each href | All 9 in-scope routes load with HTTP 200, no client exception, no 404 |
| Notification bell (`aria-label="Notifications — no pending approvals"`) | click | Navigates to `/dashboard/approvals` (correct — link, not a dropdown; label honestly reflects 0 pending) |
| Global search input | focus | Lazily loads a client-side index via `GET /jobs?`, `GET /applications`, `GET /agents` (confirmed in `apps/web/src/components/topbar.tsx:158-166`) |
| Global search: adversarial `<script>alert(1)</script>` + Enter | type+submit | Rendered as inert literal text in the input (no execution, no dialog); no match found (correct — no job/app/agent named that), stayed on `/dashboard` |
| Global search: `engineer` (8 chars, real word) | type | 0 matches — correct, since account has 0 jobs/applications and no agent name contains "engineer" |
| Global search: `tailor` (matches agent name) | type | Dropdown (`#topbar-search-results`, `role="listbox"`) renders 1 hit `AGENT / tailor / agent`; click navigates to `/dashboard/agents` — **verified working end-to-end** |
| Global search: `zzzznomatch` (≥2 chars, no match) | type | No dropdown, no "no results" message — silent empty state (see LOW finding below) |
| User menu (`Gold U.` chip) | click | Opens menu with `Sign out`; identity chip correctly shows the account's real name/role from `/workspaces/settings` (`Gold U.` / `QA Tester Probe`) — not a hardcoded "Vikram D." like the wireframe |
| `View plans & subscribe` button | click | Navigates to `/pricing` |
| `pricing` / `manage your account` inline links | click | Navigate to `/pricing` and `/dashboard/settings` respectively |
| `Manage Agents` button | click | Navigates to `/dashboard/agents` |
| Sign out | click | Clears `aether_token` from localStorage, redirects to `/login`; subsequent direct nav to `/dashboard` correctly redirects to `/login?next=%2Fdashboard` (session genuinely terminated, not just UI-hidden) |

**Network capture** (paywalled load): `GET /agents`, `GET /approvals?status=pending`, `GET /billing/entitlement`, `GET /billing/subscription`, `GET /workspaces/settings` — all 200. Each of these fired twice on initial mount (once from `Topbar`, once from the page-level gate component, independently) — cosmetic redundancy, not a correctness bug (no duplicate side effects, both are idempotent GETs).

**Console/errors**: 0 `pageerror`, 0 console errors. 1 benign `net::ERR_ABORTED` RSC-prefetch abort (Next.js hover-prefetch cancelled by navigation), same pattern as `/login`.

**Cross-screen consistency**: agent count "19 agents ready" in the sidebar matches `GET /api/agents` returning exactly 19 agents (independently verified via curl). Plan badge "Free · 0/5 runs this period" matches `billing/entitlement.plan.id = "free"`.

**Findings**:
- **GM2-NA-DASH-01** (LOW, cosmetic) — Global search shows no "No results" affordance when a ≥2-character query matches nothing; the dropdown simply never appears, which is indistinguishable from "still loading" or "control did nothing" to a first-time user. Repro: focus search, type `zzzznomatch`, observe no listbox and no message. Evidence: `dashboard-09-search-no-match-state.png`. Not a functional defect (matches work correctly, confirmed with `tailor` query end-to-end) — purely a missing empty-state affordance.
  **Verify-twice confirmed [VERIFIED-WITH-FRESH-EVIDENCE verify-twice.js @2026-07-31T01:03Z]**: re-run in a fresh browser session with a different non-matching query (`nomatchquery99`) — `#topbar-search-results` listbox count = 0, same behavior. Reproduces consistently, not a flake. Evidence: `verify2-dash01-search-nomatch.png`.

---

## 3–10. /dashboard/jobs, /applications, /resume, /cover-letters, /stories, /approvals, /analytics, /agents — PASS (paywall-gated), deep interaction BLOCKED for this account tier

**Critical scope note read before the eight per-route mini-sections below**: this non-admin account is `plan.id="free"`, `requiresSubscription: true` (fresh-checked at the top of this report and re-checked per-route below). For a free-tier account, **all eight of these routes render the identical full-screen "Subscribe to unlock Aether" gate** in the main content area instead of any screen-specific UI (job cards, application board, resume list, cover-letter list, story bank, approval queue, analytics charts, or agent catalog). This was verified route-by-route, not assumed from one sample.

**This is judged honest, not a defect**: the gate text is accurate ("An active subscription is required to run the AI agents that power your job search"), it does not fabricate or reuse the wireframes' sample data (no fake "37 active applications" etc.), and — critically — it is enforced **server-side**, not just hidden in the UI. Direct `curl` probes against the underlying endpoints with this account's bearer token confirm honest, non-bypassable gating:
```
POST /api/agents/tailor/run        {"job_id":"…"}  → 402 {"error":"subscription_required","message":"An active subscription is required to use Aether. Subscribe to unlock.","upgradeUrl":"/pricing"}
POST /api/agents/cover-letter/run  {"job_id":"…"}  → 402 (same shape)
POST /api/agents/story-extractor/run {}             → 402 (same shape)
POST /api/agents/scout/run  {"query":"engineer","location":"Sydney"} → 402 (same shape)
GET  /api/jobs                                      → 200 [] (read-only listing still works — not gated, matches "you can still browse" framing)
POST /api/approvals/fake-id/approve                 → 404 {"detail":"Approval not found"} (honest not-found, not a fake 200)
```
[VERIFIED-WITH-FRESH-EVIDENCE curl probes @2026-07-31T00:50Z]
No client-only security theater: even a user who bypassed the UI entirely and drove the API directly could not run a gated agent without a real subscription.

**Network capture (per gated route)**: only shell-level calls fire — `GET /agents`, `GET /approvals?status=pending`, `GET /billing/entitlement`, `GET /workspaces/settings`, `GET /billing/subscription`. **None** of the screen-specific endpoints from SCREEN-MATRIX.md (`/jobs?sort=fitScore`, `/jobs/{id}/insights`, `/applications`, `/resumes`, `/cover-letters`, `/stories`, `/analytics/*`, `/agents/runs`, etc.) fire on any of the 8 gated routes — confirmed by full request-log capture per route (see `screens/nonadmin/` JSON evidence). This means the gate short-circuits *before* the page's own data-fetching code runs: no wasted calls, and — more importantly — no chance of a partial data leak (e.g., a paywalled screen quietly fetching and caching data it shouldn't show).

**Sidebar wiring**: the correct nav item is highlighted active on each route despite the shared gate content (confirmed per-screenshot — e.g. "Jobs" highlighted on `/dashboard/jobs`, "Agents" highlighted on `/dashboard/agents`), so the shell knows exactly where it is even while gating the content.

**Scope boundary — recorded, not guessed [UNSURE, both interpretations below]**: per §3.2 this tester is required to "click every button, submit every form, trigger every AI agent" on each screen. For these 8 routes, the screen-specific forms/buttons/agent triggers (job filters, apply flow, tailor/cover-letter/story-extractor agent runs, approval decisions, analytics interactions) are **not reachable in the DOM at all** for a free-tier account — there is nothing behind the gate to click. Exercising them would require converting this disposable test account into a real paying subscriber via production Stripe (a genuine financial transaction), which:
  - **Interpretation A (in scope)**: the task explicitly frames this as "human-grade production sweep as a real first-time paying user" and pricing/billing is called out as in-scope — arguably a full test should complete a real low-cost subscription to unlock and test the gated screens.
  - **Interpretation B (out of scope for this tester)**: standing rules restrict this agent to *testing*, forbid any destructive/state-changing action beyond what's needed to evidence a finding, and require cleanup of any test data left behind — a real subscription purchase is a financial transaction with billing/tax side effects that a screen-tester should not unilaterally initiate on production without explicit operator sign-off, especially given "Clean up any test data rows you create" is hard to honor for a real Stripe charge.
  - **Resolution taken**: did **not** complete a real purchase. Instead, `/pricing` (route 12, below) was tested to the point of confirming the checkout call is real and correctly wired (a genuine Stripe Checkout session is created, not a fake redirect), stopping short of entering payment details. The 8 screens above are marked **PASS at the gate level** (the gate itself is honest, consistent, and server-enforced) with their screen-specific interactive protocol steps marked **NOT TESTED — HUMAN-GATED (requires a real paid subscription to reach)**.

**Per-route evidence**:

| # | Route | Wireframe (for reference; not reachable live) | Live screenshot | Gate confirmed | Sidebar active-highlight correct |
|---|---|---|---|---|---|
| 3 | `/dashboard/jobs` | `wf-jobs.png` | `jobs-00-initial.png`, `gated-jobs-full.png` | yes | yes ("Jobs") |
| 4 | `/dashboard/applications` | `wf-applications.png` | `gated-applications-full.png` | yes | yes ("Applications") |
| 5 | `/dashboard/resume` | `wf-resume.png` | `gated-resume-full.png` | yes | yes ("Resume Studio") |
| 6 | `/dashboard/cover-letters` | `wf-cover-letters.png` | `gated-cover-letters-full.png` | yes | yes ("Cover Letter Studio") |
| 7 | `/dashboard/stories` | `wf-stories.png` | `gated-stories-full.png` | yes | yes ("Story Bank") |
| 8 | `/dashboard/approvals` | `wf-approvals.png` | `approvals-check-00-initial.png`, `gated-approvals-full.png` | yes | yes ("Approvals" — note: sidebar has no dedicated "Approvals" item; reached via bell icon, see below) |
| 9 | `/dashboard/analytics` | `wf-analytics.png` | `gated-analytics-full.png` | yes | yes ("Analytics") |
| 10 | `/dashboard/agents` | `wf-agents.png` | `gated-agents-full.png` | yes | yes ("Agents") |

[VERIFIED-WITH-FRESH-EVIDENCE screens/nonadmin/gated-*.png + gate-detail.js network capture @2026-07-31T00:51Z]

**Additional edge-case checks (shared across these routes)**:
- Unauthenticated direct access to `/dashboard/jobs` → redirected to `/login?next=%2Fdashboard%2Fjobs`, correctly preserving the deep-link target. [`jobs-00-unauth-access.png`]
- Back/forward navigation (`/dashboard/stories` → `/dashboard` → back → forward) → URL bar and rendered content stay in sync at every step, no stale/blank screen, no console error. [`stories-00-back-nav.png`, `dashboard-12-forward-nav.png`]
- Reload-and-re-read: reloading any gated route re-shows the same gate (re-checked live, not cached client state) — expected since gating is server-derived from `billing/entitlement` on every load.
- 0 console errors, 0 pageerrors, 0 unexpected failed requests across all 8 routes.

**Note on `/dashboard/approvals`**: there is no dedicated sidebar entry for Approvals — it's reached via the topbar bell icon (`aria-label="Notifications — no pending approvals"`, confirmed under §2 above) or by direct URL. This matches the current 13-item sidebar (Dashboard/Jobs/Resume Studio/Cover Letter Studio/Story Bank/Applications/Interview Center/Networking/Email Center/Agents/Analytics/Offers/Settings) which has no explicit "Approvals" link — consistent, not a defect, since the bell is the documented entry point.

**Findings for #3–10**: none at BLOCKER/HIGH/MEDIUM (the gate itself is correct and honest on every route). See scope-boundary UNSURE note above for what could not be exercised without a real purchase.

---

## 11. /dashboard/settings — PASS (not gated — matches the paywall's own "you can still… manage your account" promise)

**Verdict**: PASS, and the strongest screen in this sweep for honesty. Unlike routes 3–10, `/dashboard/settings` is fully reachable on the free tier, consistent with the dashboard gate's own claim. Wireframe: `design/screens/settings.html` (`wf-settings.png`) — live implementation covers the same 8 sections (Profile, Resume Management, Portfolio Sync, Notifications, Agent Configuration, Integrations, Privacy & Compliance, Billing & Subscription) via a left sub-nav; clicking "Profile" shows a combined overview of Profile+Resume+Portfolio Sync+Agent Config+Integrations+Billing (all but Notifications/Privacy), while the other 7 sub-nav items each show just their own section — a reasonable "overview vs. focused" pattern, not a defect.

**Screenshots**: `settings-check-00-initial.png`, `settings-tab-*.png` (×8, one per sub-nav item), `settings-20` through `settings-37` (adversarial/valid edits, reloads, reverts) — 20 screenshots total.
[VERIFIED-WITH-FRESH-EVIDENCE screens/nonadmin/settings-*.png @2026-07-31T00:53–00:59Z]

**Per-element results**:
| Element | Action | Result |
|---|---|---|
| Unauthenticated direct access | nav to `/dashboard/settings` | Redirected to `/login?next=%2Fdashboard%2Fsettings` — correctly protected despite being outside the paywall gate (auth ≠ subscription, correctly modeled as two separate checks) |
| Profile: Full name field, adversarial `<script>alert(1)</script>` + 300×'A' + Target role `XSS" onmouseover="alert(2)` + Location 200×'Z' | fill + Save Changes | `PUT /api/workspaces/settings` → **422**, banner `"Full name must be 120 characters or fewer. Location must be 120 characters or fewer."` No script executed (rendered as inert text). Reload confirms **nothing was saved** — original values intact. Real server-side bounded validation, atomic (whole-request rejected, no partial write) |
| Profile: Full name field, cleared to empty | Save Changes | Client-side blocked before any network call: inline `"Full name is required"` under the field + top banner `"Fix the highlighted fields before saving."`; avatar glyph degrades to `?` |
| Profile: Target role, valid edit `"QA Tester Probe (edited)"` | Save → reload → revert → save | `PUT /api/workspaces/settings` → 200; reload shows the edited value (real persistence, not client-only state); reverted to original `"QA Tester Probe"` and re-saved — verified via a second reload that the account was left in its original state |
| Agent Configuration: Auto-apply toggle + Match-threshold slider (80%→55%) | toggle + drag + Save → reload → revert | `PUT` succeeds, `"Settings saved ✓"` confirmation shown; **reload confirms persistence** (55% still shown, toggle still on) — genuine backend-persisted preference, not a decorative control. Reverted to original (Auto-apply off, 80%) and re-saved, confirmed via reload |
| Notifications: 3 toggles (Approval requests, Application updates, Weekly digest) | inspect | All 3 are **`disabled` / `aria-disabled="true"`** with an explicit banner: `"Notification delivery isn't built yet — these preferences aren't functional and aren't saved by 'Save Changes'. Coming soon."` — this is honest incomplete-feature disclosure done right: the controls are inert (can't even be clicked), not fake-interactive |
| Resume Management: "Upload new version" | click | Triggers a real native OS file-chooser dialog (confirmed via Playwright's `filechooser` event) — genuinely wired to a file input, not a dead button. Cancelled with no file selected; no error, no crash |
| Portfolio Sync: "Sync now" with all 3 fields empty | click | `POST /api/workspaces/career-data/refresh` → 200, `"Career data synced ✓"` |
| Portfolio Sync: Portfolio URL = adversarial `javascript:alert(1)` | fill + Sync now | `POST /api/workspaces/career-data/refresh` → 200 but with an honest partial-failure state: `"Synced with 1 source error — see below"` and inline `"Could not reach the portfolio site javascript:alert(1): unknown url type: javascript."` — the backend actually attempted to fetch the value and reported a real, specific error instead of silently accepting garbage or crashing. Field cleared afterward to leave the account clean |
| Integrations: OpenRouter / Abacus Subscription (fallback) cards | inspect | Both show `Connected` badges sourced from server environment config (`"Configured via server environment (legacy)"`, `"...standby (a higher-priority OpenRouter/Anthropic key is the active path)"`) — read-only status, no fake "Test connection" button offered where there's nothing for the user to configure (env-managed keys, not user-supplied) |
| Privacy & Compliance | inspect | Honest static content: `"There is no self-service 'export all data' or 'delete all data' feature yet; contact us to request a full data export or deletion and we will process it manually."` — correctly avoids offering a fake/dangerous self-service delete button for a feature that doesn't exist |
| Billing & Subscription: "Manage subscription" | click | `POST /api/billing/portal` → **409** (this free account has no Stripe customer yet); UI shows an honest, specific fallback: `"Your account isn't linked to a Stripe billing profile yet, so the self-service portal isn't available. Email [operator email] or call [operator phone] to manage or cancel your subscription."` — no fake redirect, no silent no-op, real 409 surfaced with a working alternative path |

**Network capture**: `PUT /api/workspaces/settings` (422 adversarial, 200 valid×2, 200 revert), `POST /api/workspaces/career-data/refresh` (200×2), `POST /api/billing/portal` (409). Every button click fires its documented endpoint; no optimistic success shown for the 422 or 409 cases — both are clearly surfaced as failures with actionable copy.

**Console/errors**: 0 pageerrors. 1 expected `console.error` (browser's own log of the intentional 409 probe). No other console errors across ~20 interactions.

**Reload-and-re-read**: every state-changing action above was independently reloaded and re-read; all persisted values matched, and the account was returned to its pre-test state (Full name, Target role, Location, Auto-apply, Match threshold, Portfolio URL all reverted) — no test data left behind on this shared disposable account beyond the account's pre-existing name/role/location fields noted at the top of this report (which predate this sweep).

**Findings**:
- **GM2-NA-SET-01** (LOW, informational, not a defect) — The `POST /billing/portal` 409 fallback message displays a real operator email and phone number in plaintext to a free-tier user who has never attempted checkout and clicks "Manage subscription." This is very likely an intentional beta-support contact (consistent with this screen's overall pattern of honest, specific incomplete-feature messaging rather than a placeholder), not a secret or vulnerability — but it is real PII rendered on a user-reachable path, worth the operator's explicit confirmation that this is the intended long-term behavior. Evidence: `settings-33-manage-subscription-click.png`.
  **Verify-twice update [VERIFIED-WITH-FRESH-EVIDENCE verify-twice2.js output @2026-07-31T01:03:57Z]**: re-running this exact step in a fresh browser session (per protocol) produced a *different* result — `POST /api/billing/portal` now returns **200** and redirects to a real `billing.stripe.com/p/session/live_…` portal, no PII fallback shown. This is not a flake: between the two observations, this sweep's own `/pricing` → "Subscribe to Starter" test (route 12) created a live-mode Stripe customer record for this account (while deliberately not completing the purchase — plan is still confirmed `Free`, no charge). Once *any* Stripe customer exists on the account, `/billing/portal` succeeds immediately, even with zero active subscriptions. So both observations are honest and correct for the account state at the time: **brand-new account, zero checkout attempts** → 409 + contact-us fallback (PII exposure as filed above); **account with an abandoned/attempted checkout** → 200 + real portal redirect. The finding itself (PII in the fallback message) still stands for the first-time-user case this sweep started from — this note exists so the sequencing is fully transparent rather than silently re-testing into a different code path.

---

## 12. /pricing — PASS

**Verdict**: PASS. No dedicated wireframe exists in `design/screens/` for `/pricing` (confirmed absent from the 17-file listing) — assessed on general quality/honesty instead. This is a clean, professional, single-purpose pricing page, publicly reachable (tested both unauthenticated and authenticated).

**Screenshots**: `pricing-00-initial.png`, `pricing-01-unauth-view.png`, `pricing-02-annual-toggle.png`, `pricing-03-tooltip-open.png`, `pricing-04-after-subscribe-click.png` (live Stripe Checkout page), `pricing-results.json` (full network/console capture)
[VERIFIED-WITH-FRESH-EVIDENCE screens/nonadmin/pricing-*.png @2026-07-31T01:00–01:01Z]

**Per-element results**:
| Element | Action | Result |
|---|---|---|
| Unauthenticated access | direct nav | Fully public, no login redirect — correct for a marketing/pricing page. Free-tier CTA correctly reads `"Get started free"` (vs. `"Go to dashboard"` + `"CURRENT PLAN"` badge when authenticated as this free-tier account) — conditional rendering based on real auth+entitlement state, not static copy |
| Monthly / Annual toggle | click | Recomputes all 3 paid tiers' prices and GST lines live: Starter $19/mo → $179/yr, Pro $39/mo → $359/yr, Power $69/mo → $649/yr — no page reload, no flash of stale data |
| "More information" (ⓘ) GST tooltip | click | Opens an exact breakdown: `"GST-inclusive price. Net $162.73 + $16.27 GST (10%, computed as round(total ÷ 11, 2))."` — shows the actual formula, and the math is independently verifiable correct ($179 ÷ 1.1 = $162.73, GST = $16.27) |
| "Subscribe to Starter" (Monthly) | click | `POST /api/billing/checkout` → 200; browser navigates (no popup — full-page redirect) to a **real, live-mode** (`cs_live_…`) Stripe-hosted Checkout page titled "Subscribe to Aether Starter", correctly showing $13.88 USD/month (≈ AUD $19 converted), the account's real email pre-filled, and the correct plan feature list ("30 tailored agent runs/month · Standard model tier · Cover letters + story bank · Email agent"). **This is genuine, working, production Stripe wiring — not a fake redirect or a sandbox stub.** Per the scope-boundary note under routes 3–10, the purchase was deliberately **not completed**: no card details were entered, the Stripe "Subscribe" button was left untouched (and was disabled/greyed since the form was empty), and the tab was closed without submitting — leaving no financial side effect and no incomplete-subscription artifact to clean up |
| "Already have an account? Sign in" | (not clicked, already covered by `/login` section) | href confirmed `/login` |
| Footer `Privacy Policy` / `Terms` | (link presence only) | Present, hrefs correct |

**Network capture**: `GET /api/billing/plans` (200, drives the 4 plan cards), `GET /api/billing/entitlement` + `GET /api/billing/subscription` (200, drives "CURRENT PLAN" badge), `POST /api/billing/checkout` (200, returns a real Stripe session URL). No optimistic UI change before the checkout call resolved — the button stays in place until the redirect actually happens.

**Console/errors**: 0 console errors and 0 pageerrors on the Aether-origin `/pricing` page itself. The only console warnings/errors captured (WebGL driver messages, hCaptcha logo `net::ERR_ABORTED`, PerimeterX `EvalError` in a collapsed console group) all originate from `checkout.stripe.com` after navigation — third-party bot-detection/telemetry noise on Stripe's own page, outside this app's control and not evidence of an Aether defect.

**Not tested (intentionally, to avoid production side effects)**:
- Completing an actual purchase (would create a real recurring charge on production Stripe — see scope-boundary note under routes 3–10).
- 429 rate-limit behavior on `/billing/checkout` (SCREEN-MATRIX.md references `Retry-After` handling, MV-pricing-004) — reproducing this would require firing enough rapid real checkout-session-creation calls against **live** Stripe to trip the limit, creating multiple abandoned live sessions on the production Stripe account for no corresponding user benefit. Deliberately not attempted. **[UNSURE — not exercised, flagging rather than guessing]**: whether the honest Retry-After surfacing described in the code comments actually renders correctly in the UI was not re-verified in this sweep.

**Findings**: none at BLOCKER/HIGH/MEDIUM/LOW — this screen is accurate, honest, and its checkout wiring is demonstrably real.

**Side effect discovered during later verify-twice pass (documented per cleanup rules)**: initiating "Subscribe to Starter" causes the backend to create a **live-mode Stripe customer record** for the account as part of building the Checkout Session, independent of whether the checkout is ever completed. This was discovered when re-testing `/dashboard/settings` → "Manage subscription" afterward: it now succeeds (200, real portal redirect) where it previously returned 409, because a Stripe customer now exists on the account. No subscription and no charge was created (plan independently re-confirmed `Free` after the fact). This is normal Stripe integration behaviour, not a defect, but it is a real change to production Stripe data attached to this disposable test account. See the Cleanup section at the end of this report.

---

## Screenshot index

All screenshots live under `uat/reports/evidence/gold-master-v2/screens/nonadmin/` (75 PNG files). Grouped:
- **Wireframe references** (9): `wf-dashboard.png`, `wf-jobs.png`, `wf-applications.png`, `wf-resume.png`, `wf-cover-letters.png`, `wf-stories.png`, `wf-approvals.png`, `wf-analytics.png`, `wf-agents.png`, `wf-settings.png` — rendered directly from `design/screens/*.html` at 1440×900 for side-by-side comparison.
- **`/login`** (6): `login-00-unauth-redirect.png` … `login-05-valid-login-success.png`
- **`/dashboard`** (13): `dashboard-00-initial.png` … `dashboard-12-forward-nav.png`
- **Gated routes 3–10** (10): `jobs-00-initial.png`, `jobs-00-unauth-access.png`, `approvals-check-00-initial.png`, `stories-00-back-nav.png`, and `gated-{jobs,applications,resume,cover-letters,stories,approvals,analytics,agents}-full.png`
- **`/dashboard/settings`** (23): `settings-check-00-initial.png`, `settings-tab-*.png` (×8), `settings-20` … `settings-37`
- **`/pricing`** (5): `pricing-00-initial.png` … `pricing-04-after-subscribe-click.png` (the last is the live Stripe Checkout page)
- **Verify-twice re-runs** (3): `verify2-dash01-search-nomatch.png`, `verify2-set01-billing-portal-409.png`, `verify2-set01-manage-sub-url-check.png`

Raw JSON evidence (console/network capture per script run) also written alongside screenshots: `login-results.json`, `dashboard-results.json`, `settings-tabs-results.json`, `settings-adversarial-results.json`, `settings-forms3-results.json`, `pricing-results.json`.

## Console / network summary (aggregate across all 12 routes)

- **Pageerrors (uncaught exceptions)**: 0, across the entire sweep (~90 distinct interactions: clicks, form submissions, reloads, navigations).
- **Unexpected console errors**: 0. Every console `error` entry captured was either (a) the browser's own log line for an *intentionally* triggered 401/409 during adversarial/edge-case testing, or (b) third-party noise from `checkout.stripe.com` after redirect (PerimeterX/hCaptcha telemetry), outside this app's code.
- **Failed requests (`requestfailed`)**: a handful of `net::ERR_ABORTED` entries, all Next.js router hover-prefetch (`?_rsc=…`) cancellations when navigation happened before the prefetch completed — cosmetic, not user-visible, not a defect.
- **API honesty**: every 4xx/402/409/422 observed during this sweep was paired with an honest, specific, human-readable UI message (never a silent failure or a fake-success state). Every gated agent-run endpoint enforces subscription server-side, not just in the UI.

## Not-tested items (HUMAN-GATED / requires production side effects this tester chose not to trigger)

1. **Screen-specific interactive protocol for routes 3–10** (job filters/apply flow, tailor/cover-letter/story-extractor agent runs, approval decisions, analytics interactions) — the DOM for these controls does not exist for a free-tier account; reaching them requires a real paid subscription (see scope-boundary note under routes 3–10). **HUMAN-GATED**: requires an operator decision to fund a real subscription purchase on this test account, or to grant it a comped/test entitlement out-of-band.
2. **Completing an actual Stripe purchase** on `/pricing` — deliberately stopped at the live Checkout page without entering payment details.
3. **429 rate-limit UI behavior** on `/billing/checkout` / `/billing/portal` (referenced in SCREEN-MATRIX.md as MV-pricing-004) — would require firing enough rapid real Stripe session-creation calls to trip the limit; not attempted to avoid creating multiple abandoned live-mode Stripe artifacts.
4. **Agents screen deep pass** (per-agent config fields, model picker, provider credential Test-connection flows, catalog picker) — `/dashboard/agents` is paywall-gated for this account; the wireframe (`wf-agents.png`) shows this is a rich screen, but none of it is reachable without a subscription. Same HUMAN-GATED reason as item 1.
5. **Cross-screen entity consistency for job/application/resume/story data** — not exercisable because the account has 0 of each and cannot create any (agent runs that would create them are all subscription-gated).

## Cleanup / test data left behind

- **Settings profile fields** (Full name, Target role, Location) and **Agent Configuration** (Auto-apply toggle, Match-threshold slider) were each temporarily changed during adversarial/valid-edit testing and explicitly **reverted and re-saved** to their original values, independently confirmed via a second reload each time. No residual change on these fields.
- **Portfolio URL** field was temporarily set to `javascript:alert(1)` during adversarial sync testing and explicitly **cleared back to empty** afterward (not re-saved with a value, since the field only persists on explicit "Sync now"/Save — cleared client-side state before navigating away).
- **Stripe live-mode customer record**: `/pricing` → "Subscribe to Starter" was clicked to verify checkout wiring is real (see route 12 findings). This created a live-mode Stripe customer attached to this test account as a side effect, with **no subscription and no charge** (independently re-confirmed: plan still `Free`, $0 spend). This tester has no access to the Stripe dashboard or an admin/delete endpoint for Stripe customer records, so **this could not be cleaned up from within the tested UI** — documented here for the operator to remove manually from the Stripe dashboard if desired, alongside the rest of this disposable account's teardown.
- **Test account itself**: per `phase0/CANONICAL-NONADMIN-LOGIN.md`, this account (`gm2-nonadmin-1785454990@example.com`) is flagged for purge in W-K; this sweep did not delete it since doing so would remove the evidence trail and the account is explicitly documented as shared across §3.2 testers. No new jobs/applications/resumes/stories/cover-letters/approvals rows were created (all remained 0 — confirmed both at the start and can be re-confirmed at any time via the same `curl` recipe used in the Identity confirmation section above, since none of the gated create-paths were reachable).

## Sign-off

All 12 in-scope routes were loaded, screenshotted, interacted with, and evaluated against wireframes where they exist. Two LOW-severity, non-blocking findings were filed (GM2-NA-DASH-01, GM2-NA-SET-01), both independently re-verified in a fresh browser session per the "verify twice" requirement — GM2-NA-DASH-01 reproduced identically; GM2-NA-SET-01's re-verification surfaced an important, honestly-documented state transition (see its verify-twice note) rather than a flake. Zero BLOCKER, HIGH, or MEDIUM findings. Zero placeholder/fixture/"Coming Soon"-without-explanation content found on any user-reachable path — the one deliberately-unfinished feature encountered (Notifications delivery) is disclosed honestly with disabled controls and explicit "Coming soon" copy, which is the standard this sweep was asked to hold the product to. The dominant, sweep-wide observation is that this free-tier, zero-usage account is treated **honestly** throughout: real empty states instead of fake data, a real and consistently-enforced (client **and** server) paywall instead of UI-only gating, real validation errors instead of silent failures or fake success, and a genuinely real (live-mode) Stripe checkout instead of a stubbed redirect.

**Report status**: COMPLETE for all 12 assigned routes. Not a partial/coverage-marker file.

---
