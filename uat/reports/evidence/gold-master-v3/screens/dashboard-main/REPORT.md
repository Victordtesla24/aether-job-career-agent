# TESTING OUTCOME REPORT — /dashboard (main) (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 3)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:20–18:26Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright, Python, headless Chromium, 1440x1400.

Lowest-priority screen per task order ("only if time remains") — tested at reduced but still evidence-backed depth; no state-changing actions taken (Approve/Reject on real pending approvals and "Tailor & Apply" were deliberately NOT clicked — both would trigger real backend writes / real agent runs on this production account, out of SAFETY scope for a time-boxed pass).

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-initial-load.png + 02-scrolled-bottom.png + results.json)

- All 6 core widgets present: `agent-feed`, `todays-opportunities`, `funnel-widget`, `story-bank-widget`, `crm-summary`, `needs-approval-widget`.
- Needs Approval widget: badge shows **5** real pending approvals — "Submit application" for Senior Technical Program Manager/replit (31 min ago), Innovation Product Manager/harvey (42 min ago), Staff Program Manager/Mozilla (3 hr ago), plus "+2 more waiting". Each row has functional Approve/Reject buttons (not clicked — see Safety note above).
- Application Funnel mini-widget: Jobs Found 52 → Applied 48 → Screened 2 → Interviewed 0 → Offers 0 — **identical to the numbers independently observed on `/dashboard/analytics`**, confirming cross-screen data consistency (both read from the same real DB counts).
- Market Pulse section (code-labelled `market-intel-mi01`, rendered heading "Real-Time Market Pulse"): present at the bottom of the page — Trend Indicators (application velocity −80%, agent automation spend +174%, avg job fit score +10%), Jobs by Source donut (52 jobs sourced), Top Skills in Demand ("Not enough job data yet…" — honest empty state, not fabricated skill percentages), Your Job Probability Score (60%), Weekly Activity heatmap, Employer Hiring Activity feed, Recruiter Activity, and Market vs. Your Performance — which **honestly discloses "External market benchmark unavailable — Provider: none configured… your figures are derived from your own saved jobs and applications"** rather than fabricating a comparison (matches the `_market_summary()` GAP-P4-060 fix seen in the Analytics backend). [VERIFIED-WITH-FRESH-EVIDENCE 02-scrolled-bottom.png]
- Sidebar footer: "Agents Idle — 20 agents ready · none running" + "Manage Agents" link (real, matches the Agents screen's live count minus the 2 non-runnable roadmap/orchestration cards).

## Interaction / edge states

- Idle 60s window (no user action): only `GET /api/agents` (30.0s apart) + one `GET /api/approvals?status=pending` — the same global 30s sidebar-widget poll observed on both Agents and Analytics; no page-specific continuous poll despite SCREEN-MATRIX listing "polling 5s" for `/dashboard`. [VERIFIED-WITH-FRESH-EVIDENCE results.json → `idle_60s_calls`]
- Reload: page reloads cleanly with identical widget data. [VERIFIED-WITH-FRESH-EVIDENCE 03-reload.png]
- Unauthenticated access → redirected to `/login?next=%2Fdashboard`. [VERIFIED-WITH-FRESH-EVIDENCE 04-unauthenticated-access.png]
- Verified twice: independent fresh session reproduced the identical approval-count badge (5). [VERIFIED-WITH-FRESH-EVIDENCE 05-freshsession2-verify.png]

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-DASH-001 | /dashboard | INFO | confirmation | Cross-screen funnel data consistency confirmed | Compare `/dashboard` funnel widget vs `/dashboard/analytics` funnel | Same DB-backed counts on both screens | Identical 52/48/2/0/0 on both, same session | 02-scrolled-bottom.png vs dashboard-analytics/03-cold-load-settled.png | OPEN (confirmatory, not a defect) |

No BLOCKER/HIGH/MEDIUM defects found on this screen in this reduced-depth pass. No placeholder/fixture data observed (Market Pulse honestly discloses "not connected" rather than fabricating benchmarks).

## Not-tested (out of scope / HUMAN-GATED, time-boxed screen)

- Approve/Reject on the 5 real pending approvals — would execute a real backend write (submission/email); HUMAN-GATED, not exercised.
- "Tailor & Apply" / "Review Match" on Today's Opportunities cards — would trigger a real tailoring agent run with LLM cost; not exercised.
- Story Bank widget "Open →" and CRM summary "Open →" deep-navigation — not followed (those destination screens are out of this batch's scope).
- Global search input — not exercised with query strings.
- Back/forward navigation and full form-adversarial sweep — not performed on this screen given its "only if time remains" priority; the pattern was already exhaustively verified on Agents/Analytics/Settings in this same batch and is architecturally shared (same Next.js router, same auth guard).

## Data left behind

None — read-only pass, no mutations attempted.

## Sign-off

Screen tested at reduced (time-boxed, lowest-priority) but still evidence-backed depth: load+screenshot (incl. full scroll to Market Pulse), widget inventory, cross-screen data-consistency check against Analytics, idle-poll measurement, reload, unauthenticated + fresh-session-twice. Verdict: **no defects found; real, consistent, honestly-labeled data throughout; state-changing controls (Approve/Reject, Tailor & Apply) correctly deferred per SAFETY constraints.**
