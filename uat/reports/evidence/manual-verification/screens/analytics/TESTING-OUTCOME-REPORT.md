# TESTING-OUTCOME-REPORT — Analytics

- **Screen id:** analytics
- **Screen name:** Analytics
- **Route:** `/dashboard/analytics`
- **Wireframe:** `design/screens/analytics.html`
- **Backing endpoints (per matrix row):** `GET /analytics`, `GET /analytics/dashboard`, `GET /analytics/funnel`, `GET /analytics/agent-roi`, `GET /analytics/conversion`, `GET /analytics/ats-distribution`, `GET /analytics/market-pulse`
- **Agents wired to this screen:** none (`agents: []` in BRIEF.json)
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Repo commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Tester:** screen-tester agent role, model claude-sonnet-5 (Claude Agent SDK)
- **Session start (UTC):** 2026-07-17T15:15:22Z
- **Session end (UTC):** 2026-07-17T15:24:15Z
- **Credential used:** `admin` / `admin123` (canonical-login.md) — confirmed `isAdmin: false`, plan `free`, `active_paid: false`

## Executive summary

The assigned test account cannot see the Analytics screen at all. Navigating to `/dashboard/analytics` while authenticated as `admin`/`admin123` renders a full-screen "Subscribe to unlock Aether" paywall instead of any wireframe content (funnel, conversion, ATS histogram, agent ROI, or Real-Time Market Pulse). This is driven by `GET /billing/entitlement` returning `{"active_paid":false,...,"requiresSubscription":true}` for this account's `free` plan, and it is not analytics-specific — the same gate replaces the content of every `/dashboard/*` route (`/dashboard`, `/dashboard/settings`, `/dashboard/jobs`, `/dashboard/agents` all verified). See finding **MV-analytics-001 (BLOCKER)**.

This makes the bulk of the §3.2 protocol (visual conformance against the wireframe's own charts/tabs/filters, per-element interaction, form testing — n/a, no forms on this screen — and live UI↔backend wiring for the 7 mapped endpoints) untestable with the credential specified. Everything that *could* be tested in this state (unauthenticated redirect, the paywall's own two interactive elements, back/forward, throttled reload, console/network hygiene, and direct API cross-checks) was tested and is clean. Direct API calls (bypassing the UI) confirm the backend analytics endpoints return real, internally-consistent, non-fabricated data for this account (44 jobs found, 5 applications, 160 agent runs, $0.101 spend, etc.) — so the defect is specifically in the UI's blanket access gate, not in data fabrication.

## Element inventory

### A. Elements actually rendered at `/dashboard/analytics` for this credential (paywall state) — tested

| # | Element | Tested | Result |
|---|---|---|---|
| 1 | Route load (authenticated) | Yes | 200, renders shared dashboard shell + Paywall card |
| 2 | Sidebar nav (16 links incl. active "Analytics" highlight) | Visual only | Renders, "Analytics" correctly highlighted active; not exhaustively click-tested (shared shell, primary scope of Dashboard-shell tester) |
| 3 | Topbar greeting / search / notification bell / avatar menu | Visual only | Renders; not deep-tested (shared shell, out of this screen's primary scope) |
| 4 | Paywall heading "Subscribe to unlock Aether" + copy + 3 bullet benefits | Yes | Renders correctly, matches product copy, no lorem-ipsum/placeholder text |
| 5 | "View plans & subscribe" button | Yes (clicked) | Navigates to `/pricing`; pricing page renders 4 real tiers (Free $0 / Starter $19 / Pro $39 / Power $69, GST-inclusive) — button works correctly |
| 6 | "pricing" inline link | Yes (clicked) | Navigates to `/pricing` correctly |
| 7 | "Agents Idle" sidebar footer widget ("8 agents ready · none running", "Manage Agents" button) | Visual only | Renders; out of this screen's scope |

### B. Wireframe-specified elements (`design/screens/analytics.html`) — NOT reachable, HUMAN-GATED

| # | Wireframe element (`data-design-id`) | Status |
|---|---|---|
| 1 | Header range-label + "updated N min ago" freshness text (`topbar-an03`) | NOT TESTED — screen gated |
| 2 | Time-range pills 7d/30d/90d/All (`range-pills-an04`) — implemented in code as `data-testid="period-selector"` | NOT TESTED — screen gated |
| 3 | Export button (`btn-export-an05`) | NOT TESTED — screen gated (also appears absent from implementation per source read, see MV-analytics-002) |
| 4 | Application Funnel chart (`funnel-an07`) — implemented as `data-testid="funnel-chart"` | NOT TESTED — screen gated |
| 5 | Interview Conversion line chart (`conversion-an08`) — implemented differently as `data-testid="conversion-rates"` (stage % grid) | NOT TESTED — screen gated |
| 6 | Applications by Source donut (`sources-an09`) — implemented as `data-testid="sources-donut"` inside MarketPulse | NOT TESTED — screen gated |
| 7 | Top Skills in Demand (`skills-an10`) — `data-testid="top-skills"` | NOT TESTED — screen gated |
| 8 | ATS Score Distribution histogram (`ats-an11`) — `data-testid="ats-distribution"` | NOT TESTED — screen gated |
| 9 | Weekly Activity heatmap (`heatmap-an12`) — `data-testid="activity-heatmap"` | NOT TESTED — screen gated |
| 10 | Job Probability Score ring (`probability-an13`) — `data-testid="probability-score"` | NOT TESTED — screen gated |
| 11 | Employer Hiring Activity feed (`employer-activity-an14`) — `data-testid="employer-activity"` | NOT TESTED — screen gated |
| 12 | Recruiter Activity trend (`recruiter-trends-an15`) — `data-testid="recruiter-trends"` | NOT TESTED — screen gated |
| 13 | Market vs. Your Performance (`market-vs-you-an16`) — `data-testid="market-vs-you"` | NOT TESTED — screen gated |
| 14 | Trend Indicators tiles (`trend-indicators-an17`) — `data-testid="trend-indicators"` | NOT TESTED — screen gated |
| 15 | Dashboard-summary metric cards (`data-testid="dashboard-summary"`, not in wireframe but present in code — Applications/Interviews/Offers/Jobs Found/Avg Fit Score/Agent Runs/Agent Spend, each with `MetricTooltip`) | NOT TESTED — screen gated |
| 16 | Agent ROI cards (`data-testid="agent-roi"`) | NOT TESTED — screen gated |

## Findings

| id | severity | category | summary |
|---|---|---|---|
| MV-analytics-001 | BLOCKER | defect | Entire `/dashboard/analytics` content replaced by subscription paywall for the assigned free-plan test account; blanket `/dashboard/*` gate, not analytics-specific; backend data behind it is real and non-fabricated |
| MV-analytics-002 | MEDIUM | coverage-gap | Live wireframe-conformance testing blocked by MV-analytics-001; static source read suggests possible deviations (missing Export button, missing freshness label, Interview-Conversion line chart replaced by Stage-Conversion grid) requiring live confirmation |

Full finding rows: `findings.json` (this directory), schema per STAGE1-TESTER-PROTOCOL.md §4.1.

## Claim verdicts

| Claim | Verdict | Evidence / reasoning |
|---|---|---|
| **CLM-024** — 27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors/20 routes, 0 same-origin 5xx, pytest/vitest/E2E counts | **PARTIALLY-TRUE** | Within this screen's scope: confirmed 0 uncaught console errors, 0 page errors, 0 same-origin 5xx across all sessions on `/dashboard/analytics` (gated) and `/login` (unauth), verified twice. The 20-route sweep, pytest 676, and vitest 297 counts are outside a single-screen tester's reproducible scope and are UNVERIFIABLE-FROM-UI here. |
| **CLM-041** — ATS score shown with MetricTooltip + methodology + before/after (`GET /resumes/{id}/ats`) | **UNVERIFIABLE-FROM-UI** | This claim's cited endpoint (`/resumes/{id}/ats`) belongs to the Resume Studio screen, not Analytics; the Analytics screen does have its own ATS-distribution `MetricTooltip` (source-confirmed), but the entire screen is blocked by MV-analytics-001 so no live tooltip/before-after check was possible here. Flagged for the orchestrator to confirm correct screen mapping. |
| **CLM-045** — Analytics metrics UI matches user-scoped SQL recomputation with 0.0% delta (GATE-18) | **UNVERIFIABLE-FROM-UI** | No UI metrics ever render for this account (MV-analytics-001), so there is nothing to compare against a DB recomputation. Direct API calls (not UI) show internally consistent values (e.g. ATS-distribution bucket total 44 == jobsFound 44; conversion `found_to_applied` = 1/44 = 2.27% matches; source percentages sum to 100%), which is supportive but does not satisfy the claim's stated UI-vs-DB method. |
| **CLM-059** — Conversion UI: estimatedConversionLift + methodology + working MetricTooltip (data-testid trigger/popover, role=tooltip) + before/after ATS + 0 console errors | **UNVERIFIABLE-FROM-UI** | Blocked by MV-analytics-001; no conversion UI ever renders for this account. |
| **CLM-062** — Playwright sweep of 14 dashboard routes + /pricing + /admin **as a paid admin** showed 0 console errors/failed requests/page errors | **PARTIALLY-TRUE** | Confirmed 0 console errors / 0 uncaught page errors / 0 failed (non-aborted) requests on `/dashboard/analytics` (both gated-authenticated and unauthenticated) and on `/pricing`. The claim explicitly says "as a paid admin" — no paid account was provided to this tester (admin/admin123 is confirmed `free`/`active_paid:false`), so the "paid" condition itself is UNVERIFIABLE with the assigned credential; console/network hygiene held for the slice that was reachable. |
| **CLM-078** — Funnel/conversion-rate stage percentages render and re-fetch when the period filter changes | **UNVERIFIABLE-FROM-UI** | The period-selector pills never render for this account (MV-analytics-001), so no live click-driven re-fetch could be observed. Direct API calls confirm `GET /analytics/funnel?period=7d` and `?period=all` are both accepted and return period-scoped data (identical values here because this account's job/application rows all fall within the last 7 days — plausible given the account's known recent heavy test usage — not evidence of a broken filter, just not a UI-level observation). |

## UNSURE items

**UNSURE-001 — Is the blanket `/dashboard/*` subscription paywall intended to hide read-only Analytics for free-plan users, or is this over-broad gating?**

- Evidence for "intended monetization gate": Paywall copy explicitly frames the requirement ("Aether is in limited beta. An active subscription is required..."), and the pricing page confirms a real Free/$0 tier alongside paid tiers — gating premium visibility behind paid tiers is a legitimate product choice.
- Evidence for "possibly over-broad": (a) the paywall's own copy scopes the requirement to *running the AI agents* ("required to run the AI agents that power your job search — discovery, tailoring, cover letters, and the inbox agent"), not to viewing already-computed, already-paid-for-by-quota results; (b) the Free plan explicitly grants and this account has already partially used a monthly agent-run quota (`runsUsed:3, runsAllowed:5` — confirmed via `GET /billing/subscription`), so free-tier product usage is expected, yet 100% of the resulting analytics is unconditionally hidden; (c) Analytics itself runs no agents (`agents: []` in the matrix row) — it is a pure read of already-recorded `Job`/`Application`/`AgentRun` rows; (d) the tester brief explicitly expected this account to show "low/zero counts" in the UI, implying the brief's author assumed Analytics would be visible on a free account.
- Screenshots: `screens/analytics/test-artifacts/10-gated-analytics-fullpage.png`, `screens/analytics/test-artifacts/api-crosscheck-billing.json`.
- Escalating for orchestrator/product adjudication rather than guessing; this determines whether MV-analytics-001 should be fixed (loosen the gate for read-only screens) or closed as working-as-intended (and the tester brief/claim ledger updated to require a paid test account for Analytics coverage).

**UNSURE-002 — Possible (very likely coincidental) fixture/company-name overlap**

While cross-checking `market-pulse`'s `employerActivity` feed for fabrication, one company name ("Deputy") also appears in two unrelated pytest HTTP fixtures (`apps/api/tests/fixtures/http/lever/jobs.json`, `.../indeed/jobs.json`). Deputy is a real, well-known Sydney-headquartered SaaS company frequently posted on AU job boards, and the fixture's own description text is factually accurate for the real company, so this reads as coincidental realistic-fixture-data reuse rather than production serving test fixtures — no matching posting IDs, no other overlapping company names (Stripe/replit/InterEx Group do not appear in any fixture file), and the account's data is otherwise internally consistent with genuine discovery-agent activity. Not filed as a finding; noted for completeness given the zero-tolerance bar on fabricated content.

## Screenshot index

All paths relative to `screens/analytics/test-artifacts/`:

| File | Description |
|---|---|
| `01b-unauth-redirect-run2.png` | Unauthenticated `/dashboard/analytics` → clean redirect to `/login` (2nd/verification run) |
| `02-analytics-loaded-fullpage.png` | First authenticated load of `/dashboard/analytics` — paywall observed |
| `03-gate-scope.json` | Gate-scope sweep across `/dashboard`, `/dashboard/settings`, `/dashboard/analytics`, `/dashboard/jobs`, `/dashboard/agents` |
| `gatecheck-_dashboard*.png` | Full-page screenshots for each route in the gate-scope sweep |
| `10-gated-analytics-fullpage.png` | Full-page screenshot, dedicated deep-dive session (3rd independent run) |
| `10-gated-result.json` | Console/network capture + interactive-element results for the deep-dive session |
| `11-after-pricing-link.png` | Result of clicking the "pricing" inline link — real `/pricing` page with 4 real tiers |
| `12-after-subscribe-click.png` | Result of clicking "View plans & subscribe" |
| `13-throttled-reload.png` | Reload under emulated slow-3G (400 Kbps, 400ms latency) — gate still renders correctly, ~2s load, no hang |
| `api-crosscheck.log` | Direct `curl` responses for all 7 mapped analytics endpoints + `/analytics` root, used to confirm real/non-fabricated, internally-consistent data |
| `api-crosscheck-billing.json` | Direct `curl` responses for `/billing/subscription` and `/billing/entitlement` |
| `probe1_unauth.mjs`, `probe2_main.mjs`, `probe3_gate_scope.mjs`, `probe4_gated_screen.mjs` | Playwright scripts used for each probe (kept for reproducibility) |

## Console / network / server-log summary

- **Console errors (all sessions, all routes tested):** 0 uncaught errors, 0 `pageerror` events.
- **Failed requests:** 5 `net::ERR_ABORTED` entries during the deep-dive session, all caused by client-side navigation away from a route while its own in-flight requests (`/workspaces/settings`, `/billing/entitlement`, `/approvals?status=pending`, `/agents` ×2) were still pending — standard browser navigation-abort behavior, not server-side failures or unsurfaced errors. No entry with an actual non-2xx/3xx HTTP status.
- **Same-origin 5xx:** 0 observed in any session.
- **Analytics-endpoint calls fired by the browser during normal navigation:** 0 — confirmed via network capture that none of the 7 mapped endpoints are ever requested by the client while gated (expected: `AnalyticsPage`/`MarketPulse` never mount because `<SubscriptionGate>` substitutes `<Paywall/>` for `children`).
- **Direct API calls (curl, bypassing UI) to the 7 mapped endpoints:** all returned HTTP 200 with real, internally consistent data (see `api-crosscheck.log`).
- **Server logs:** not independently tailed by this tester (no `log-tailer` invoked for this single-screen run); network-level capture above is the evidence base for this report.

## NOT-TESTED list (HUMAN-GATED only)

All items below are HUMAN-GATED by MV-analytics-001 — the assigned `admin`/`admin123` credential is on the `free` plan (`active_paid:false`), and the protocol explicitly prohibits this tester from changing account-level plan/subscription settings without brief authorization (BRIEF.json does not authorize it):

1. Visual conformance of all 14 wireframe chart/panel sections vs. rendered DOM (§3.2 pt.1).
2. Click-testing of the 7d/30d/90d/All period pills and confirming they re-fire `/analytics/funnel`, `/analytics/conversion`, `/analytics/dashboard` with new `period` values and re-render (§3.2 pt.2, pt.4; relates to CLM-078).
3. MetricTooltip hover/click behavior, methodology text, and before/after value rendering across all metric cards (§3.2 pt.2; relates to CLM-041, CLM-059).
4. Export button existence/behavior (wireframe `btn-export-an05`) (§3.2 pt.2).
5. Live cross-check of displayed numbers against direct DB query per DEPLOYMENT-RUNBOOK.md-sanctioned access, i.e. true UI-vs-DB delta (§3.2 pt.4; relates to CLM-045) — API-vs-DB partially substitutes but is not equivalent to UI-vs-DB.
6. Empty-state honesty check for a genuinely fresh/zero-data account (this account has 44 jobs / 5 applications / 160 agent runs already, so even if the gate were open it would not be a "fresh" account for this specific check).
7. Forced-backend-error behavior for the analytics endpoints (§3.2 pt.6) — no reachable UI entry point to trigger one meaningfully while gated.

## Sign-off

Tested by: screen-tester agent (Claude Agent SDK, model `claude-sonnet-5`), MANUAL-VERIFICATION Stage 1, screen `analytics`. All findings above were reproduced in at least two independent fresh browser sessions (unauthenticated redirect: 2 runs; paywall-gate observation: 3 independent runs across `probe2`, `probe3`, `probe4`) before filing, per §3.2 point 9. No code changes, service restarts, or git writes were made. No account-level settings were modified.
