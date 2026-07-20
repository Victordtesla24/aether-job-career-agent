# TESTING-OUTCOME-REPORT-PAID — Analytics (Stage 1 paid-content re-test)

- **Screen id:** analytics
- **Screen name:** Analytics
- **Route:** `/dashboard/analytics`
- **Wireframe:** `design/screens/analytics.html`
- **Backing endpoints (per matrix row):** `GET /analytics`, `GET /analytics/dashboard`, `GET /analytics/funnel`, `GET /analytics/agent-roi`, `GET /analytics/conversion`, `GET /analytics/ats-distribution`, `GET /analytics/market-pulse`
- **Agents wired to this screen:** none (`agents: []` in BRIEF.json / matrix row) — §3.2 point 5 (run AI agents) does not apply to this screen
- **Environment:** Production — `https://5cb5f0620.abacusai.cloud`
- **Repo commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Tester:** screen-tester agent role, model `claude-sonnet-5` (Claude Agent SDK)
- **Session start (UTC):** 2026-07-17T16:49:25Z
- **Session end (UTC):** 2026-07-17T16:58:01Z
- **Credential used:** `admin` / `admin123` (canonical-login.md) — confirmed via `GET /billing/entitlement`: `active_paid: true`, `plan.id: "pro"`, `status: "active"`; `GET /billing/subscription`: `quota.runsUsed: 18, runsAllowed: 100`

## Executive summary

With the account's TEMP Pro entitlement active, `/dashboard/analytics` renders the real Analytics UI — no paywall. All 16 wireframe-mapped panels/sections are present and populated (or honestly empty where the account has no underlying data). **Every displayed number was cross-checked against the raw backend API response and, for the Dashboard-summary and Funnel figures, against a direct SQL recomputation on the production database — all matched with 0.0% delta.** No `Math.random()`, no hardcoded/fixture-fingerprint values, and no fabricated content were found anywhere on this screen; every panel is genuinely wired to `GET /analytics/*` and reflects this account's real `Job`/`Application`/`AgentRun` rows. This is a materially different (and better) result than the systemic hardcoded-UI-data pattern flagged elsewhere in this app (dashboard/email/agent-monitor) — Analytics is clean on that specific axis.

The 3 deviations speculated in the free-plan pass (MV-analytics-002, static source read) are **confirmed live**: no Export button exists, no header freshness ("updated N min ago") label exists, and the wireframe's Interview-Conversion line chart is replaced by a real, data-backed "Stage Conversion" percentage grid (see **MV-analytics-003**).

Three new, previously-unreported issues were found through live interaction and are the substantive findings of this paid pass:
1. **MV-analytics-004 (MEDIUM, wiring):** the 7d/30d/90d/All period selector only actually re-scopes the Funnel and Stage-Conversion panels — the Dashboard-summary cards, ATS Score Distribution, and Agent ROI panels are silently always all-time and never respond to the selector, with no visual disclaimer.
2. **MV-analytics-005 (MEDIUM, defect):** the Dashboard-summary "Applications" card (14) and the Funnel's "Applied" stage (7) show different numbers for what reads as the same concept, on the same screen — root-caused via direct SQL to a draft-vs-submitted definitional split with no UI disambiguation.
3. **MV-analytics-006 (LOW, coverage-gap):** "Top Skills in Demand" renders a blank panel (no empty-state message) when the account has no skill-lexicon matches, inconsistent with the honest-empty-state pattern used elsewhere on the same screen (e.g. "Market data: not connected").

A 4th low-severity visual finding (**MV-analytics-007**) notes the wireframe's "Applications by Source" (application channel) donut is implemented as "Jobs by Source" (job-discovery/ATS platform) — a different, but honestly-labeled and non-fabricated, data dimension.

Console/network hygiene was clean across every session (0 uncaught errors, 0 page errors, 0 same-origin 5xx on analytics endpoints, confirmed independently via server-side `/var/log/aether/api.log`). Unauthenticated access redirects cleanly to `/login`. Throttled (400 Kbps / 400 ms latency) reload completed in ~887 ms with no hang. Back/forward navigation works correctly. `MetricTooltip` popovers (hover, keyboard focus, Escape-to-close) work correctly and are populated with real methodology copy, not placeholder text.

## Element inventory

| # | Element (wireframe `data-design-id` → live `data-testid`) | Tested | Result |
|---|---|---|---|
| 1 | Route load (authenticated, Pro) | Yes | 200, full real UI renders (no paywall) |
| 2 | Period selector 7d/30d/90d/All (`range-pills-an04` → `period-selector`) | Yes (clicked all 4) | Renders, active state highlights correctly, fires `GET /analytics/funnel?period=X` and `GET /analytics/conversion?period=X` on each click; does NOT re-scope dashboard-summary/ats-distribution/agent-roi — see MV-analytics-004 |
| 3 | Header freshness label (`topbar-an03`, "updated N min ago") | Yes | ABSENT — confirmed live, see MV-analytics-003 |
| 4 | Export button (`btn-export-an05`) | Yes | ABSENT — confirmed live, see MV-analytics-003 |
| 5 | Dashboard-summary metric cards (Applications/Interviews/Offers/Jobs Found/Avg Fit Score/Agent Runs/Agent Spend) (`data-testid=dashboard-summary`) | Yes | Renders; all 7 values traced 1:1 to `GET /analytics/dashboard` response AND to direct SQL recomputation (0.0% delta) |
| 6 | Application Funnel (`funnel-an07` → `funnel-chart`) | Yes | Renders 5 stages (Jobs Found/Applied/Screened/Interviewed/Offers); values traced 1:1 to `GET /analytics/funnel` and direct SQL |
| 7 | Interview Conversion line chart (`conversion-an08`) | Yes | NOT rendered — replaced by "Stage Conversion" 4-tile percentage grid (`conversion-rates`), real data from `GET /analytics/conversion`. See MV-analytics-003. |
| 8 | Applications by Source donut (`sources-an09` → `sources-donut`) | Yes | Renders as "Jobs by Source" (different metric than wireframe intends — ATS/discovery platform, not application channel); values trace to `GET /analytics/market-pulse.sources`. See MV-analytics-007. |
| 9 | Top Skills in Demand (`skills-an10` → `top-skills`) | Yes | Renders heading only; empty body, no empty-state message (account has 0 skill-lexicon matches). See MV-analytics-006. |
| 10 | ATS Score Distribution histogram (`ats-an11` → `ats-distribution`) | Yes | Renders 10 buckets (0-100, superset of wireframe's 60-100); bar heights + "44 scored jobs" total trace 1:1 to `GET /analytics/ats-distribution` and direct SQL |
| 11 | Weekly Activity heatmap (`heatmap-an12` → `activity-heatmap`) | Yes | Renders 35 cells (5×7), intensities trace to `GET /analytics/market-pulse.activityHeatmap` (mostly 0, one 1-count and one 4-count cell matching this account's real application dates — not `Math.random()`, unlike the wireframe's own decorative mockup script) |
| 12 | Agent ROI (not in wireframe by this name; `agent-roi`) | Yes | Renders Total spend/Agent runs/Avg duration; all 3 trace 1:1 to `GET /analytics/agent-roi` |
| 13 | Job Probability Score ring (`probability-an13` → `probability-score`) | Yes | Renders 44% + 4 factor bars (Application volume/Interview conversion/Market demand/Skill match); traces 1:1 to `GET /analytics/market-pulse.probability` |
| 14 | Employer Hiring Activity feed (`employer-activity-an14` → `employer-activity`) | Yes | Renders 5 real entries (harvey/Empire Life/Plenti/airwallex/Empire Life) with relative timestamps; traces 1:1 to `GET /analytics/market-pulse.employerActivity` (derived from this account's real `Application`/`Job` join, not the wireframe's fictional ANZ/ATO/Atlassian/Canva examples) |
| 15 | Recruiter Activity trend (`recruiter-trends-an15` → `recruiter-trends`) | Yes | Renders sparkline + "200 total" / "16.7 · no change"; traces 1:1 to `GET /analytics/market-pulse.recruiterTrends` |
| 16 | Market vs. Your Performance (`market-vs-you-an16` → `market-vs-you`) | Yes | Renders honestly: "Market data: not connected" for both comparisons (no fabricated market benchmark, unlike wireframe's static "1.9x market" claim) — real "you" figures (14, 0%) trace to API/DB |
| 17 | Trend Indicators tiles (`trend-indicators-an17` → `trend-indicators`) | Yes | Renders 3 tiles (velocity/spend/fit score), all "no change" (single-point series, correctly computed by `_pct_delta`, not fabricated) |
| 18 | `MetricTooltip` (i)-icon popovers (multiple instances across all panels) | Yes | Hover reveals popover with real methodology copy; mouse-away hides; keyboard focus reveals; Escape closes and returns focus — all confirmed working |
| 19 | Unauthenticated access to `/dashboard/analytics` | Yes | Clean redirect to `/login` |
| 20 | Throttled reload (400 Kbps / 400 ms latency) | Yes | Loads in ~887 ms, full UI renders, no hang, no partial/broken state |
| 21 | Browser back/forward through `/dashboard` ↔ `/dashboard/analytics` | Yes | Both directions work correctly, page re-renders fully each time |
| 22 | Forms | N/A | Analytics is a read-only screen with no forms; §3.2 point 3 (form testing) does not apply |
| 23 | Sidebar/topbar shared shell | Visual only | Out of this screen's scope (covered by the Dashboard-shell tester) |

## Findings (this pass — new rows only, MV-analytics-003+)

| id | severity | category | summary |
|---|---|---|---|
| MV-analytics-003 | MEDIUM | visual | Live-confirmed: Export button absent, freshness label absent, Interview-Conversion line chart replaced by real Stage-Conversion grid |
| MV-analytics-004 | MEDIUM | wiring | Period selector only re-scopes Funnel/Conversion; Dashboard-summary/ATS-distribution/Agent-ROI silently stay all-time |
| MV-analytics-005 | MEDIUM | defect | Dashboard-summary "Applications" (14) vs Funnel "Applied" (7) — same-screen inconsistency, root-caused via SQL to draft-inclusion difference, no UI disambiguation |
| MV-analytics-006 | LOW | coverage-gap | "Top Skills in Demand" renders blank with no empty-state message when data is empty |
| MV-analytics-007 | LOW | visual | "Applications by Source" (wireframe) implemented as "Jobs by Source" (different, honestly-labeled metric) |

Full finding rows with reproduction steps and evidence paths: `findings-paid.json` (this directory), schema per STAGE1-TESTER-PROTOCOL.md §4.1. (MV-analytics-001/002 from the free-plan pass are NOT re-filed here per instruction; MV-analytics-002's speculation is resolved/confirmed by MV-analytics-003 above.)

## Claim verdicts (re-adjudicated with paid-account, fresh evidence)

| Claim | Verdict | Evidence / reasoning |
|---|---|---|
| **CLM-024** — 27 Phase-7 gates VERIFIED-CLOSED incl. 0 console errors/20 routes, 0 same-origin 5xx, pytest/vitest counts | **PARTIALLY-TRUE** | Within this screen's scope (now including the real, un-gated UI): 0 uncaught console errors, 0 `pageerror` events, 0 same-origin 5xx across all 3 fresh sessions (main load, edge-case session, re-verification session) on `/dashboard/analytics` (authenticated Pro), `/login`, and unauthenticated `/dashboard/analytics`. Independently cross-checked against `/var/log/aether/api.log` for the session window — every `/analytics/*` request logged 200 OK; the only 5xx/traceback entries in the log during this window belonged to a different concurrent tester's session (`/agents/runs?limit=-5`, different source IP, unrelated endpoint). The 20-route sweep and pytest 676/vitest 297 suite counts remain outside a single-screen tester's reproducible scope → still UNVERIFIABLE-FROM-UI for that portion. |
| **CLM-041** — ATS score shown with MetricTooltip + methodology + before/after values (`GET /resumes/{id}/ats`) | **UNVERIFIABLE-FROM-UI (mismapped screen, partially resolved)** | The cited endpoint (`/resumes/{id}/ats`) genuinely belongs to Resume Studio, not Analytics — confirmed unresolvable from this screen. However, Analytics' OWN "ATS Score Distribution" panel DOES have a working `MetricTooltip` with real methodology copy ("How your scored jobs are spread across ATS/AI fit-score bands...") — confirmed live via hover/keyboard test. It does NOT show a per-item "before/after" comparison (it is a distribution histogram, not a single-score view), which is consistent with this being the wrong screen for the claim's stated method. Escalating the same UNSURE as the free pass: orchestrator should confirm intended claim-to-screen mapping (likely Resume Studio). |
| **CLM-045** — Analytics metrics UI matches a user-scoped SQL recomputation with 0.0% delta (GATE-18) | **CONFIRMED** | Ran a direct SQL recomputation against the production database for this exact user (`cc29a76e324fbf19f438eb8be`) reproducing the router's own queries: `total_applications=14, interviews=0, offers=0, jobs_found=44, avg_fit=38.8, agent_runs=200, agent_cost=0.1204` and funnel `jobs_found=44, applied=7, screened=0, interviewed=0, offers=0` — both sets match the UI-displayed values exactly (0.0% delta). Evidence: `test-artifacts/paid/db-groundtruth-sql-recompute.txt`. |
| **CLM-059** — Conversion UI: estimatedConversionLift + methodology + working MetricTooltip (data-testid trigger/popover, role=tooltip, hover-revealed, illustrative-estimate disclaimer) render; before/after ATS shown; 0 console errors | **PARTIALLY-TRUE** | The Stage-Conversion grid renders with real `MetricTooltip` popovers (`data-testid="metric-tooltip-trigger"`/`"metric-tooltip-popover"`, `role="tooltip"`, hover-revealed, confirmed open/close mechanics) and 0 console errors — confirmed live. No literal `estimatedConversionLift` field or "illustrative-estimate disclaimer" text was found anywhere on this screen (the conversion tooltips describe methodology, e.g. "Share of discovered jobs you went on to apply for", not a lift estimate or disclaimer). No before/after ATS value is shown on this screen (that concept lives on Resume Studio, consistent with CLM-041's mismapping). Confirmed working parts; refuted/absent parts noted. |
| **CLM-062** — Playwright sweep of 14 dashboard routes + /pricing + /admin as a paid admin showed 0 console errors/failed requests/page errors | **PARTIALLY-TRUE** | Confirmed 0 console errors / 0 uncaught page errors / 0 failed (non-aborted, non-5xx) requests on `/dashboard/analytics` as a genuinely paid (Pro) admin across 3 independent sessions — this specific screen now satisfies the "as a paid admin" condition that was UNVERIFIABLE in the free-plan pass. The full 14+2-route sweep remains outside this single-screen tester's scope. |
| **CLM-078** — Analytics funnel/conversion-rate stage percentages render and re-fetch when the period filter changes | **PARTIALLY-TRUE** | CONFIRMED for the Funnel and Stage-Conversion panels specifically: clicking each of 7d/30d/90d/all fires `GET /analytics/funnel?period=X` and `GET /analytics/conversion?period=X` and the panels re-render (values happened to be identical across periods in this run because 100% of this account's non-draft application activity falls within the last 7 days — confirmed via direct SQL, not a broken filter). REFUTED as a page-wide claim: the Dashboard-summary, ATS-distribution and Agent-ROI panels do NOT re-fetch or change with the period filter (see MV-analytics-004) — if the claim intends "the whole Analytics page" this is only true for 2 of 5 data panels. |

## UNSURE items

**UNSURE-003 — Is the "Jobs by Source" / "Applications by Source" naming divergence (MV-analytics-007) an accepted, documented product decision or an unaddressed wireframe drift?**

- Evidence for "accepted": the backend code carries an explicit, dated comment (`GAP-P4-058`) stating the label must honestly say "jobs sourced" rather than "applications" — this reads as a deliberate engineering decision to avoid fabricating an application-channel breakdown the system doesn't actually track per-application.
- Evidence for "still open": the wireframe (source of truth for what this screen is supposed to show) explicitly specifies application-channel data (LinkedIn/Seek/Indeed with an "applied" center label), so if a real application-channel breakdown is a product requirement, this substitution has not delivered it — it has honestly declined to fabricate it instead.
- Not blocking; filed as MV-analytics-007 (LOW) rather than escalated further, since the live behavior is honest and non-misleading in isolation. Flagging for orchestrator awareness in case product intent differs.

## Screenshot index

All paths relative to `screens/analytics/test-artifacts/paid/`:

| File | Description |
|---|---|
| `20-analytics-loaded-fullpage.png` | Full-page screenshot, first authenticated load, Pro account, period=all |
| `21-analytics-above-fold.png` | Above-the-fold viewport screenshot |
| `22-market-pulse-section.png` | Real-Time Market Pulse section, scrolled into view |
| `23-after-period-clicks.png` | State after cycling through 7d/30d/90d/all pills |
| `24-tooltip-hover.png` | Generic tooltip-hover probe (first pass) |
| `25-unauth-redirect.png` | Unauthenticated `/dashboard/analytics` → clean redirect to `/login` |
| `26-tooltip-open-proper.png` | Proper hover-triggered `MetricTooltip` popover open, showing real methodology text; also visually documents the 14-vs-7 "Applications" discrepancy (MV-analytics-005) |
| `27-back-nav.png` | Browser back-navigation result, `/dashboard` → back → `/dashboard/analytics`, funnel chart re-rendered |
| `28-throttled-reload.png` | Reload under emulated slow-3G (400 Kbps, 400 ms latency), full-page, ~887 ms load, no hang |
| `29-reverify-after-7d-click.png` | Fresh-session re-verification: page state after clicking '7d', confirming Dashboard-summary/ATS/Agent-ROI panels unchanged |
| `30-reverify-top-skills-empty.png` | Fresh-session re-verification: "Top Skills in Demand" blank panel with no empty-state message |
| `api-groundtruth.json` | Direct `curl` responses for all 7 mapped analytics endpoints + `/billing/entitlement` + `/billing/subscription`, used as ground truth for UI-vs-API comparison |
| `db-groundtruth-sql-recompute.txt` | Direct SQL recomputation against the production DB (dashboard summary, funnel, ATS buckets, Application status breakdown) — used to close CLM-045 and root-cause MV-analytics-005 |
| `probe1-main-result.json` | Full structured result of the main Playwright probe: console/network capture, element inventory, displayed-value extraction, period-click network log, tooltip test |
| `probe2-edges-result.json` | Structured result: unauth redirect, proper tooltip hover/focus/escape mechanics, back/forward nav, throttled reload |
| `probe3-reverify-result.json` | Structured result of the fresh-session re-verification run (§3.2 point 9) for the 3 new findings + Export/freshness re-confirmation |
| `probe1_main.mjs`, `probe2_edges.mjs`, `probe3_reverify.mjs` | Playwright scripts used for each probe (kept for reproducibility) |

## Console / network / server-log summary

- **Console errors (all 3 sessions, all routes tested):** 0 uncaught errors, 0 `pageerror` events.
- **Failed requests:** 0 non-aborted failed requests. (No `net::ERR_ABORTED` noise this run, unlike the free-plan pass's navigation-abort artifacts — this pass's probes did not navigate away mid-fetch.)
- **Same-origin 5xx (client-observed):** 0.
- **Same-origin 5xx (server-side, `/var/log/aether/api.log`, session window):** 0 for any `/analytics/*` request. All `/analytics/*` lines in the log for this window are `200 OK`. (Unrelated 500s for `GET /agents/runs?limit=-5` appear in the same log window from a different source IP — a concurrent tester's session on a different screen, not this tester's traffic; noted for completeness per the shared-environment protocol, not filed as an Analytics finding.)
- **Analytics-endpoint calls fired by the browser during normal navigation + interaction:** confirmed real, live, per-user-scoped `GET /analytics/funnel`, `/analytics/dashboard`, `/analytics/ats-distribution`, `/analytics/agent-roi`, `/analytics/conversion`, `/analytics/market-pulse` — all 200 OK, all values traced to real DB rows.
- **Unauthenticated API access:** `GET /analytics/funnel` with no token → `401 {"detail":"Not authenticated"}` (clean, no stack trace).
- **Invalid period param:** `GET /analytics/funnel?period=bogus` → `422 {"detail":"Invalid period 'bogus'. Valid: ['30d', '7d', '90d', 'all']"}` (honest validation, no raw traceback).
- **Direct DB recomputation:** performed for Dashboard-summary and Funnel figures; 0.0% delta vs UI (see `db-groundtruth-sql-recompute.txt`).

## NOT-TESTED list (HUMAN-GATED only)

1. **CLM-024's full 20-route sweep and pytest/vitest suite counts** — HUMAN-GATED: outside a single-screen tester's scope (would require running the full backend/frontend test suites and a multi-screen Playwright sweep, not sanctioned for a single-screen manual tester per STAGE1-TESTER-PROTOCOL.md).
2. **CLM-041/CLM-059's "before/after ATS value"** — HUMAN-GATED: this concept was confirmed to live on a different screen (Resume Studio, `GET /resumes/{id}/ats`), not reachable/testable from the Analytics screen; requires the Resume Studio screen-tester to adjudicate.
3. **Sidebar/topbar shared-shell deep interaction** (all 12 nav links, search, notification bell, avatar menu) — HUMAN-GATED: explicitly out of this screen's scope, owned by the Dashboard-shell tester, per the free-plan pass's same scoping decision.
4. **Forms** — N/A, not HUMAN-GATED: Analytics has no forms to test (read-only screen); §3.2 point 3 does not apply.
5. **AI-agent generation testing (§3.2 point 5)** — N/A, not HUMAN-GATED: `agents: []` for this screen's matrix row; no agents are wired to Analytics to run.

## Sign-off

Tested by: screen-tester agent (Claude Agent SDK, model `claude-sonnet-5`), MANUAL-VERIFICATION Stage 1 PAID re-test, screen `analytics`. All 5 new findings (MV-analytics-003..007) were reproduced in at least two independent fresh browser sessions (probe1 main session + probe3 fresh-login re-verification session, plus probe2 for the unauth/tooltip/back-forward/throttled findings) before filing, per §3.2 point 9. CLM-045 was additionally closed with gold-standard evidence (direct production-DB SQL recomputation, 0.0% delta). No code changes, service restarts, or git writes were made. No account-level settings were modified (Pro entitlement was pre-set by the orchestrator before this session began, per the brief). No data was created by this tester (Analytics is read-only).
