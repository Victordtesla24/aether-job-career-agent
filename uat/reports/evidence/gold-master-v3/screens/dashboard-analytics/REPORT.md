# TESTING OUTCOME REPORT — /dashboard/analytics (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 3)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T18:05–18:14Z. Account: AETHER_CRON_EMAIL (non-admin). Playwright, Python, headless Chromium, 1440x1200.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 03-cold-load-settled.png + results.json)

- Header "Analytics" + 4-way period selector (7d/30d/90d/all, default "all" — wireframe said 30d default, actual default is "all").
- Dashboard summary card (7 tiles): Applications 49, Interviews 0, Offers 0, Jobs Found 52, Avg Fit Score 39.7%, Agent Runs 3667, Agent Spend $0.78.
- Application funnel (real 5-stage, NOT the wireframe's 847→412→156→23→4 fixture): Jobs Found 52 → Applied 48 → Screened 2 → Interviewed 0 → Offers 0.
- Stage conversion tiles: Found→Applied 92.31%, Applied→Screened 4.17%, Screened→Interview 0%, Interview→Offer 0%.
- ATS score distribution histogram: 10 buckets (0–90), "52 scored jobs" caption, labeled "(all time — not affected by the period selector)".
- Agent ROI panel: Total spend $0.78, Agent runs 3667, Avg duration 13.4s, same "(all time)" honesty label.
- Market Pulse section renders below (live-dot header) — present, screenshotted.
- **"Export" button from the wireframe is ABSENT in production** (`export_button_present: false`) — wireframe-vs-built gap, not independently a defect but worth flagging.

## Targeted verifications

1. **`interview_conversion_rate` display + real-computation check**: The backend genuinely computes it (`GET /analytics/conversion` → 200, body includes `"interview_conversion_rate": 0, "interview_conversion_healthy": false`), matching `analytics.py:220`'s real DISTINCT-jobId query — **not a placeholder**. However, **it is NEVER rendered anywhere in the Analytics page UI** — grepped the entire frontend (`apps/web/src/`) for `interview_conversion_rate`/`interviewConversionRate`: zero references outside the API layer. The UI only shows the four found→applied/applied→screened/screened→interview/interview→offer stage rates, not this specific named metric. Cross-checked against the funnel and dashboard-summary cards on the same load: Interviewed=0, Interviews=0 — internally consistent with `interview_conversion_rate=0`, so the underlying number is honest, just not surfaced. [VERIFIED-WITH-FRESH-EVIDENCE 03-cold-load-settled.png, results.json → `conversion_api_raw`]
2. **Placeholder funnel check (847→412→156→23→4)**: NOT present. Live funnel shows the account's real, much smaller numbers (52→48→2→0→0), confirmed on two independent fresh sessions (initial load + `08-freshsession2-verify.png`). No fixture/placeholder content found — no BLOCKER here.
3. **CLS on cold load**: Screenshots taken at t=0(commit)/300ms/800ms/settled show the reserved-space skeleton (`dashboard-summary-loading`, 7 pulsing `h-[92px]` tiles) holding its layout slot, so no dashboard-summary-card *insertion* shift was visually apparent between the pre- and post-load screenshots. A `PerformanceObserver` for `layout-shift` was injected before first paint and recorded **CLS = 0.0794** for this load (4 shift entries, largest single event 0.0698 at t≈779ms) — well below the historical 0.67 cited in the code comment, and below the "needs improvement" (0.1) threshold, i.e. the reserved-space fix is working, though a small residual shift (~0.08) still occurs and is not literally zero. [VERIFIED-WITH-FRESH-EVIDENCE 01/02/03 screenshots, results.json → `cls_value`, `cls_entries`]
4. **GMV4-analytics-001 / "Dashboard endpoint not yet deployed" degrade path**: Does **NOT** trigger in production. `GET /api/analytics/dashboard?period=<p>` returned **200** on every one of 5 loads observed (initial load + all 4 period-pill clicks), and the backend router (`apps/api/app/routers/analytics.py`) has a live `@router.get("/dashboard")` handler. The Dashboard Summary card rendered with real data on every load — the `catch { setDashboard(null) }` degrade branch in `apps/web/.../analytics/page.tsx:61` is dead code under current production conditions; the code comment is stale relative to the deployed backend, not a live defect. [VERIFIED-WITH-FRESH-EVIDENCE results.json → `dashboard_endpoint_calls`, `period_click_calls`]

## Interaction / forms / persistence

- All 4 period pills clicked; each correctly re-fires `funnel`, `conversion`, and `dashboard` with `?period=<x>`, while `ats-distribution` and `agent-roi` fire WITHOUT a period param — matching their explicit "(all time — not affected by the period selector)" UI labels. No mislabeled/silently-ignored selector found. [VERIFIED-WITH-FRESH-EVIDENCE 04-after-period-clicks.png, results.json → `period_click_calls`]
- Cross-check against `/dashboard/applications`: same account shows "50 pipeline items across 8 stages", Tailoring column has 2 items, consistent order-of-magnitude with the Analytics funnel's 48 applied / 2 screened (exact reconciliation not pursued further — different counting bases: applications-in-pipeline vs. submitted-and-scored — but no contradiction observed). [VERIFIED-WITH-FRESH-EVIDENCE 05-applications-crosscheck.png]
- Reload-and-re-read: after navigating away and back, all panels reload with identical figures (52/48/2/0/0 funnel unchanged). [VERIFIED-WITH-FRESH-EVIDENCE 06-reload-analytics.png]

## Error / edge states

- Unauthenticated access → redirected to `/login?next=%2Fdashboard%2Fanalytics`. [VERIFIED-WITH-FRESH-EVIDENCE 07-unauthenticated-access.png]
- Verified twice: independent fresh browser session reproduced identical funnel figures. [VERIFIED-WITH-FRESH-EVIDENCE 08-freshsession2-verify.png]
- Idle 60s window (no user action): only 2 `GET /api/agents` calls 30.0s apart + 1 `GET /api/approvals?status=pending` — same global sidebar 30s poll seen on the Agents screen (`sidebar.tsx:45`); the Analytics page itself has **no continuous idle poll** despite SCREEN-MATRIX listing "polling 5s" for this route — that 5s figure does not manifest at idle in this observation window. [VERIFIED-WITH-FRESH-EVIDENCE results.json → `idle_60s_calls`]

## Console / network / server-log summary

- console-log.json / pageerrors.json / requestfailed.json captured for the full session; no console errors, no failed requests, no 4xx/5xx observed on any analytics endpoint across 5 loads.

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-ANALYTICS-001 | /dashboard/analytics | MEDIUM | UI-gap | `interview_conversion_rate` computed honestly but never displayed | Load Analytics, inspect DOM + `GET /analytics/conversion` | G-J/G-GSC imply this named metric is user-visible | Backend returns it correctly; grep of entire frontend shows zero references — not rendered anywhere | results.json → conversion_api_raw; 03-cold-load-settled.png | OPEN |
| ML-ANALYTICS-002 | /dashboard/analytics | INFO | stale-comment | GMV4-analytics-001 "endpoint not yet deployed" comment is stale | Load Analytics 5x (initial + 4 period pills), inspect network | Comment implies a 404/degrade path exists | `GET /analytics/dashboard` returned 200 every time; degrade branch is dead code under current deploy | results.json → dashboard_endpoint_calls | OPEN (doc-debt, not a runtime defect) |
| ML-ANALYTICS-003 | /dashboard/analytics | LOW | wireframe-drift | "Export" button from wireframe absent in production | Load Analytics, search for Export control | analytics.html promises `btn-export-an05` | No Export button anywhere on the page | 03-cold-load-settled.png | OPEN |
| ML-ANALYTICS-004 | /dashboard/analytics | INFO | perf | Residual CLS ~0.08 on cold load | Cold-load with PerformanceObserver | Ideally 0 / "good" (<0.1) | 0.0794 measured, one shift of 0.0698 at ~779ms — much improved from 0.67 baseline but not fully eliminated | results.json → cls_entries | OPEN (minor) |

No BLOCKER or HIGH findings. No placeholder/fixture content found on this screen — the canonical 847→412→156→23→4 wireframe example is absent; live data is real and account-specific.

## Not-tested (out of scope / HUMAN-GATED)

- Full exhaustive reconciliation between Applications-tracker pipeline counts and Analytics funnel counts (different counting bases — flagged as an area needing a dedicated cross-screen audit, not pursued exhaustively here given time-box).
- Market Pulse sub-panel deep interaction (heatmap cell hover, sparkline tooltips) — screenshotted only, not individually clicked (low risk, cosmetic panel).

## Data left behind

None — this screen is entirely read-only (no forms submitted, no mutations made).

## Sign-off

Screen tested per §3.2 protocol: cold-load CLS measurement, wireframe conformance, all 4 period pills exercised with network capture, `interview_conversion_rate` real-vs-displayed check, GMV4-analytics-001 degrade-path live verification, idle-poll measurement, reload persistence, unauthenticated + fresh-session-twice. Verdict: **real DB-backed data throughout, no fixture content, GMV4-analytics-001's premised degrade path does NOT occur in production (stale comment, not a live defect); genuine gap is `interview_conversion_rate` being computed but not surfaced in the UI (ML-ANALYTICS-001).**
