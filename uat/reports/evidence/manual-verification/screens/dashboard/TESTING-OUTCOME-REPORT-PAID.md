# Testing Outcome Report — `dashboard` — PAID-PLAN RE-TEST (Stage 1)

**Screen id:** dashboard
**Screen name:** Dashboard (hub)
**Route(s):** `/dashboard`, `/dashboard/[...slug]` (catch-all)
**Wireframe:** `design/screens/dashboard.html`
**Production:** `https://5cb5f0620.abacusai.cloud`
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Test account:** `admin` / `admin123` — **TEMP Pro entitlement** (`active_paid:true`, `plan.id:"pro"`, `plan.status:"active"`) confirmed live via `GET /billing/entitlement` at session start
**Session window (UTC):** 2026-07-17T16:52:45Z (session start) → 2026-07-17T17:04:01Z (ground-truth cross-check complete)
**Tester:** screen-tester agent (Claude Sonnet 5), MANUAL-VERIFICATION Stage-1 Paid Content Re-Test

## 0. Context / relationship to the prior free-plan pass

The earlier free-plan pass (`screens/dashboard/TESTING-OUTCOME-REPORT.md`, findings `MV-dashboard-001..003`) could only observe the `SubscriptionGate` paywall — the entire wireframed hub was unreachable and `MV-dashboard-003` was filed as a **coverage-gap**, explicitly recommending a paid-tier re-test. This report is that re-test. Per instruction, **the 3 existing findings are not re-filed**; new findings continue the sequence from `MV-dashboard-004`. Where this pass produces evidence directly relevant to the free-plan findings (e.g. resolving the open question in `MV-dashboard-001`), it is reported as **claim/cross-reference evidence**, not as a re-filed or self-closed finding — closure authority rests with the orchestrator/qa-adversary.

**Headline result: the hub is real.** Every widget I could cross-check against the production Postgres DB (sanctioned read-only access per `.env` `DATABASE_URL`, matching the runbook's DB) or against a second, independent API call matched exactly — no `Math.random()`, no hardcoded numbers, no fixture fingerprints found anywhere on this screen. Given the brief's explicit warning about a systemic hardcoded-UI-data pattern elsewhere in the app, this is a materially positive, evidence-backed finding for this specific screen. New defects found are about **stale cross-widget sync, an empty-state gap, a wireframe section substitution, and a slow-network race** — not fabrication.

## 1. Element inventory (paid-plan hub content)

| # | Element | Wireframe id | Tested | Result |
|---|---|---|---|---|
| 1 | Stat cards ×4 (Active Applications / Interview Rate / Offers / AI Confidence) | `stats-row-p7q8r9` | Yes | Live, DB-verified exact match (§3) |
| 2 | Stat-card info tooltips ×4 | — | Yes | Hover reveals real explanatory copy |
| 3 | Agent Activity feed + 5 filter pills (All/Discovered/Tailored/Submitted/Waiting) | `agent-feed-s1t2u3` | Yes | Live, real `AgentRun` rows incl. honest `Failed` states |
| 4 | Agent Activity "View all" link | — | Yes | → `/dashboard/agents`, confirmed by click |
| 5 | Inline feed "Approve" button (cover-letter drafted item) | — | Yes | **Defect — MV-dashboard-009** |
| 6 | Today's Opportunities — 3 job cards | `opportunities-v4w5x6` | Yes | Live, DB-verified top-3-by-fitScore |
| 7 | "Tailor & Apply" (card 1) | `btn-apply-1-b1c2d3` | Yes | → `/dashboard/resume?job=<id>`, confirmed by click |
| 8 | "Review Match" (cards 2,3) | `btn-apply-2/3` | Yes | → `/dashboard/jobs`, confirmed by click |
| 9 | External posting links (↗) | — | Yes | Correct `target=_blank`, real `sourceUrl` per job |
| 10 | "Browse all jobs" link | — | Yes | → `/dashboard/jobs`, confirmed by click |
| 11 | Application Funnel (5 stages) | `funnel-q7r8s9` | Yes | Live, DB-verified exact match (§3) |
| 12 | Story Bank quick access + "Open" | `story-bank-quick-db10` | Yes | Live, DB-verified count (26); → `/dashboard/stories` |
| 13 | Recruiter CRM summary + "Open" | `crm-summary-db11` | Yes | Live, honest zero-state (0/0/0); → `/dashboard/networking` |
| 14 | Needs Approval widget (count badge + 3 cards + "+N more") | `approvals-t1u2v3` | Yes (read + nav only) | Live count (4) matches DB; Approve/Reject **not exercised** — shared prod data, see §6 |
| 15 | "+N more waiting — review all" link | — | Yes | → `/dashboard/approvals`, confirmed by click |
| 16 | Market Intelligence section | `market-intel-mi01` | Yes | **Wireframe section replaced wholesale — MV-dashboard-004** |
| 17 | ↳ Trend Indicators ×3 | — | Yes | Live (small sample → "no change") |
| 18 | ↳ Jobs by Source donut | — | Yes | Live, DB-verified (44 jobs, 5 sources) |
| 19 | ↳ Top Skills in Demand | — | Yes | **Empty-state gap — MV-dashboard-005** |
| 20 | ↳ Job Probability Score ring + factors | — | Yes | Live, formula-verified from funnel/fit data |
| 21 | ↳ Weekly Activity heatmap | — | Yes | Live, matches sparse `Application` history |
| 22 | ↳ Employer Hiring Activity | — | Yes | Live, matches `Application`×`Job` join |
| 23 | ↳ Recruiter Activity sparkline | — | Yes | Live, 200 total / 16.7 avg = 200÷12 exactly |
| 24 | ↳ Market vs. You | — | Yes | Live, honest "Market data: not connected" |
| 25 | Sidebar nav (13 items) | `nav-primary-d4e5f6` | Yes | All present + correct hrefs (carried from free pass, unaffected by plan) |
| 26 | Sidebar "Agents Active/Idle" widget | — | Yes | Live (`8 agents ready · none running`) |
| 27 | "Manage Agents" button | `btn-manage-agents-9a8b7c` | Yes | → `/dashboard/agents`, confirmed by click |
| 28 | Topbar greeting + subtitle | `topbar-g7h8i9` | Yes | Live (time-of-day + real name + real last-run) |
| 29 | Topbar search box | — | Yes | Live index (jobs/applications/agents); XSS-safe (escaped, no raw `<script>` in DOM) |
| 30 | Notification bell | `btn-notif-j1k2l3` | Yes | → `/dashboard/approvals`, confirmed by click; badge reflects live pending count |
| 31 | User chip (avatar/name/role) | — | Yes | Live from `/workspaces/settings`; **no plan-tier text — MV-dashboard-006** |
| 32 | `[...slug]` catch-all (unmapped route) | — | Yes | **Now renders correctly under paid state** — resolves `MV-dashboard-001`'s open question (§7) |
| 33 | Unauthenticated `/dashboard` access | — | Yes | Clean redirect → `/login`, unaffected by plan |
| 34 | Throttled reload | — | Yes | **Transient misleading state — MV-dashboard-008** |
| 35 | Back/forward navigation | — | Yes | Correct in both directions, twice |

## 2. Findings (new — continuing from `MV-dashboard-004`)

Full rows also in `findings-paid.json`.

### MV-dashboard-004 — MEDIUM — visual
**Summary:** The wireframe's "Market Intelligence" section (`market-intel-mi01`: AU/US Demand Heatmap by Role, Remote Work Index, Hot Sectors, Salary Trends by role, "Best Time to Apply", and an AI "Where to Focus" recommendation with an "Explore matching roles" CTA) is not present anywhere on `/dashboard`. In its place, the shipped screen renders the entirely different `MarketPulse` component (shared with the Analytics screen: Trend Indicators, Jobs-by-Source donut, Top Skills, Job Probability Score, Weekly Activity heatmap, Employer Hiring Activity, Recruiter Activity, Market-vs-You). This was invisible to the free-plan pass (masked by the paywall) — it is new information from this pass.
**Reproduction:** 1) Login as admin/admin123 (paid). 2) Load `/dashboard`, scroll to the bottom section. 3) Compare its `data-testid` panels and headings against `design/screens/dashboard.html`'s `market-intel-mi01` block.
**Expected:** The wireframed Demand-Heatmap-by-Role / Remote-Work-Index / Hot-Sectors / Salary-Trends / Best-Time-to-Apply / Where-to-Focus widget set, incl. the "Explore matching roles" CTA.
**Observed:** A different, fully-functional, DB-driven "Real-Time Market Pulse" widget set with no equivalent AI-recommendation CTA anywhere on this screen.
**Evidence:** `test-artifacts/paid/p1-01-dashboard-loaded-full.png`, `p2-01-dashboard-loaded.png`, `p1-results.json` (step `market-pulse-content`)
**Claim refs:** none directly; contextual to `CLM-024`/`CLM-062` screen scope
**Status:** OPEN

### MV-dashboard-005 — LOW — coverage-gap
**Summary:** The "Top Skills in Demand" panel (inside Market Pulse) renders its header only, with a completely blank body, whenever `GET /analytics/market-pulse` returns `topSkills: []` — no "no skills detected yet" fallback copy, unlike every sibling widget on this screen (Story Bank, CRM, Approvals, Agent Feed all show explicit empty-state copy). Root cause confirmed via DB: all 44 of this user's `Job` rows have an empty `requirements` array, so the server-side skill-lexicon match (`apps/api/app/routers/analytics.py:399-415`) has nothing to match — an upstream job-ingestion gap, not a frontend bug, but the panel gives no honest signal of why it's empty.
**Reproduction:** 1) Login as admin/admin123. 2) Load `/dashboard`, scroll to Market Pulse → "Top Skills in Demand". 3) Observe the header with no bars/rows/message beneath it. 4) Confirm via `GET /analytics/market-pulse` that `topSkills` is `[]`.
**Expected:** Either populated skill bars or explicit "No skills data yet" messaging, consistent with sibling widgets.
**Observed:** Blank void beneath the header.
**Evidence:** `test-artifacts/paid/p1-01-dashboard-loaded-full.png` (Top Skills panel is visibly empty), `test-artifacts/paid/ground-truth-cross-check.txt` (topSkills:[] + Job.requirements len=0 for all 44 rows), `p2-results.json` step `top-skills-reverify`
**Status:** OPEN

### MV-dashboard-006 — MEDIUM — coverage-gap
**Summary:** No plan-tier or quota/usage indicator is displayed anywhere on the dashboard hub — not in the topbar user chip (shows name + target role only, no "Pro plan" text), not in the sidebar. This is despite (a) `design/screens/dashboard.html`'s topbar explicitly showing "Pro plan" under the user's name, and (b) a real, populated quota system existing server-side (`GET /billing/subscription` → `quota.runsUsed/runsAllowed/spendUsedUsd/spendCapUsd`) that is surfaced on the Agent Settings panel and admin screens but never on the primary hub a user lands on after login. A paying Pro user gets zero at-a-glance confirmation of their plan or usage from this screen.
**Reproduction:** 1) Login as admin/admin123 with confirmed `active_paid:true`. 2) Inspect the topbar user chip and the sidebar bottom panel — both fully rendered. 3) Search rendered text for any plan/tier/quota/usage string.
**Expected:** Some visible confirmation of plan tier (wireframe) and/or usage, consistent with the brief's explicit ask ("quota/usage display — should show Pro now").
**Observed:** Absent. `topbarText`/`sidebarText` regex-checked for `/pro plan|plan:|quota|usage/i` → no match, twice (session 1 visual read + session 2 automated regex check).
**Evidence:** `test-artifacts/paid/p1-01-dashboard-loaded-top.png`, `p2-results.json` step `plan-quota-indicator-check` (`mentionsPlanOrQuota:false`)
**Status:** OPEN

### MV-dashboard-007 — LOW — visual
**Summary:** Two agent types that actively run in production (`emailAgent`, `storyExtractor`) are not registered in the Agent Activity feed's display-name/tile/badge maps (`apps/web/src/components/dashboard/feed.ts` — `AGENT_NAMES`, `AGENT_TILES`, `runBadge`'s `byAgent`, `describeRun`'s `switch`). They fall back to a generic robot icon and copy like `"emailAgent agent run completed"` instead of dedicated, readable copy the way `scout`/`tailor`/`coverLetter`/`submission`/`supervisor` get.
**Reproduction:** 1) Login as admin/admin123. 2) Load `/dashboard`, read the Agent Activity feed. 3) Locate entries for `emailAgent` (present in this account's real run history).
**Expected:** A friendly display name/icon/description consistent with the other 5 agents.
**Observed:** Generic `"emailAgent agent"` / `"run completed"` fallback copy.
**Evidence:** `test-artifacts/paid/p1-01-dashboard-loaded-top.png` (visible "emailAgent agent run completed" rows), `p2-results.json` step `agent-feed-reverify` (`feedItemMentionsGenericAgent:true`)
**Status:** OPEN

### MV-dashboard-008 — LOW — performance
**Summary:** On a throttled connection, the four stat cards render as soon as the (small, fast) `GET /analytics/funnel` response resolves, without gating on the much larger `GET /jobs?sort=fitScore` response the "AI Confidence" card also depends on. Under 50kbps/400ms-latency throttling this produces a **misleading transient state**: "AI CONFIDENCE — no scored jobs yet" (implying zero data) for ~15–20 seconds, self-correcting to the real "38% avg match quality" once the jobs payload finishes downloading. No data is lost and the UI does self-heal, but the interim state reads as "you have no scored jobs" rather than "still loading," which is not honest for that window.
**Reproduction:** 1) Login as admin/admin123. 2) Open CDP `Network.emulateNetworkConditions` (50kbps down/up, 400ms latency) or DevTools "Slow 3G". 3) Reload `/dashboard`. 4) Watch the "AI Confidence" card for ~20s.
**Expected:** Either a shared loading gate across all 4 stat cards, or a card-level skeleton/spinner instead of the zero-state copy while its dependency is still in flight.
**Observed:** "no scored jobs yet" shown for 15–20s, then self-corrects to "38% avg match quality" with no further interaction. Reproduced twice (inline in session 2 + a dedicated 30s-polling follow-up run).
**Evidence:** `test-artifacts/paid/p2-03-throttled-mid-load.png`, `p2-04-throttled-final.png`, `p2-05-throttle-followup-final.png`, `p2-results.json` step `throttled-reload`, raw poll timeline in `throttle_followup.js` console output (self-corrects at elapsed 19595ms)
**Status:** OPEN

### MV-dashboard-009 — HIGH — wiring
**Summary:** The Agent Activity feed's inline "Approve" button for a `coverLetter` run's "drafted a cover letter — awaiting your approval" entry is driven by a field cached at generation time (`AgentRun.output.approval_status`) that is **never updated** once the linked `ApprovalRequest` is resolved through another surface (e.g. the `/dashboard/approvals` page, or the Needs Approval widget on a different session). Confirmed live: `ApprovalRequest c3df4494103f796021d8aae69` has `status:"approved"`, `resolvedAt:"2026-07-17 16:34:47"` — yet its originating `AgentRun`'s `output.approval_status` still reads `"pending"`, so the dashboard feed keeps showing an active "Approve" button for it indefinitely (confirmed still present 45+ minutes after resolution, across two fresh sessions). Clicking it correctly fails closed (backend returns `409 Approval already approved — terminal state`, no double-mutation), but the failure is surfaced to the paying user as a raw, unpolished string: `"Couldn't approve — POST /approvals/c3df4494103f796021d8aae69/approve failed (409): {"detail":"Approval already approved — terminal state"}"` — i.e. the literal HTTP method, endpoint path, record id, status code, and a raw JSON blob are concatenated straight into the user-facing toast, rather than a clean "this was already handled" message.
**Reproduction:** 1) Login as admin/admin123. 2) In the Agent Activity feed, find a `coverLetter` "drafted a cover letter — awaiting your approval" entry with a visible "Approve" button. 3) Click it. 4) Read the toast.
**Expected:** Either the button should not render once the underlying approval is resolved (fresh-check or hide-after-resolve), or at minimum the failure should surface a clean, non-technical message.
**Observed:** Button remains, click 409s, raw REST/JSON leaks into the toast. Reproduced identically in two independent fresh browser sessions (zero state mutation risk — the target approval was already in a terminal state before I touched it, confirmed via DB read first).
**Evidence:** `test-artifacts/paid/p3-00-before-stale-approve-click.png`, `p3-01-after-stale-approve-click.png`, `test-artifacts/paid/ground-truth-cross-check.txt` (DB `status:"approved"` vs API `output.approval_status:"pending"`), `stale_approval_check.js` console output (both runs)
**Status:** OPEN

## 3. Real-data verification (headline evidence)

Every widget's numbers were cross-checked against either a direct read-only production-DB query (via the same `DATABASE_URL` the API service itself uses, per `.env`) or a second, independent API call. All matched exactly — **zero discrepancies found**:

| UI value | Source | Ground truth | Match |
|---|---|---|---|
| Active Applications = 7 | `GET /analytics/funnel?period=all`.applied | DB: `Application` non-draft count for user = 6 submitted + 1 rejected = **7** | ✅ exact |
| Jobs Found = 44 | funnel.jobs_found | DB: `Job` count for user = **44** | ✅ exact |
| Interview Rate = 0% | `0 of 7 applied` | DB: 0 rows with status in (interview, offer) | ✅ exact |
| AI Confidence = 38% | client-computed avg `fitScore` over `GET /jobs?sort=fitScore` | API-independent recompute: avg(33 scored jobs) = 38.301 → round = **38** | ✅ exact |
| Today's Opportunities top-3 | `jobs.data.slice(0,3)` (sort=fitScore) | Independent `sort=fitScore` fetch: top 3 = Plenti 50.05, Brighte 45.6, Brighte 45.54 → UI shows 50%/46%/46% | ✅ exact |
| Story Bank = 26 | `GET /stories` | DB: `StoryEntry` count for user = **26** | ✅ exact |
| Recruiter CRM = 0/0/0 | `GET /workspaces/networking/summary`.crmSummary | Honest zero-state, not the wireframe's fake 5/2/1 | ✅ honest |
| Needs Approval = 4 | `GET /approvals?status=pending` | DB: `ApprovalRequest` pending count for user = **4** | ✅ exact |
| Jobs by Source donut (44, 5 sources) | `GET /analytics/market-pulse`.sources | Matches Job.source grouping | ✅ exact |
| Recruiter Activity "200 total / 16.7 avg" | market-pulse.recruiterTrends | 200 ÷ 12 weeks = 16.67 ≈ **16.7** | ✅ exact |
| Top Skills = empty | market-pulse.topSkills | DB: `Job.requirements` empty array for all 44 rows | ✅ honest (see MV-dashboard-005) |

**Real AI-agent audit trail confirmed** (bonus evidence for protocol §3.2.5, even though the matrix's only listed agent for this screen is `supervisor`): the feed's cover-letter entries carry real per-run audit fields read via `GET /agents/runs` — `model:"deepseek/deepseek-v4-pro"`, `costUsd` (e.g. 0.00151, 0.00146, 0.00144), `tokensIn/tokensOut`, `duration_ms` (28–79s), and genuinely distinct, job-specific generated text (not a fixture string — cross-referenced against the test-suite fixture strings pattern, no match). Several runs also show an honest **fabrication guard**: `"Cover Letter Agent run failed · Fabricated entities detected: ['AI-first']"` — the system caught and blocked a hallucinated claim rather than shipping it, which is a strong positive signal, not a defect. Numerous other runs fail honestly with `"LLM backend unavailable: budget exhausted..."` rather than silently returning filler content.

## 4. Claim verdicts (this pass)

| Claim | Verdict (this pass) | Evidence |
|---|---|---|
| **CLM-024** — 0 console errors/0 5xx across 20 routes (GATE-16/17), 676 pytest, 297 vitest, Playwright E2E green | **PARTIALLY-TRUE (screen-scoped, reconfirmed under paid state)** | 0 console errors, 0 page errors, 0 failed requests not `ERR_ABORTED`-by-navigation, 0 server 5xx across 3 independent sessions today (`test-artifacts/paid/p1-console-events.json`, `p2-console-events.json`, `p1-server-5xx.json`, `p2-server-5xx.json` — all empty). Still only speaks to the dashboard family; the other 17 routes and the suite counts are out of single-screen scope. |
| **CLM-062** — Playwright sweep of 14 dashboard routes + `/pricing` + `/admin` **as a paid admin**, 0 console/failed/page errors (GATE-03) | **PARTIALLY-TRUE — materially strengthened vs. the free-plan pass** | This is the first pass actually run **as a paid admin** (the free-plan pass could only note this was untestable under its assigned credentials). Under confirmed `active_paid:true`, zero console/page/5xx errors observed across `/dashboard` plus incidental transits of `/dashboard/jobs`, `/dashboard/resume`, `/dashboard/agents`, `/dashboard/stories`, `/dashboard/networking`, `/dashboard/approvals`. Still not the full systematic 14-route + `/pricing` + `/admin` sweep (multi-screen/orchestrator scope) — those routes' owning screen-testers should confirm independently. |
| **CLM-063** — post-cleanup restored: `active_paid=false`, `POST /agents/scout/run` → 402, paywall shows again | **NOT RE-TESTED THIS PASS (state intentionally different)** | This pass runs under an orchestrator-provisioned **TEMP Pro** grant (`active_paid:true`) specifically to test the paid hub — the free-plan pass's `CONFIRMED` verdict for the *post-cleanup free* state stands as of its own snapshot and is not contradicted or re-tested here. |
| **CLM-086** — root `/` redirects (HTTP 307) to `/dashboard` | **CONFIRMED (reconfirmed)** | `curl -I https://5cb5f0620.abacusai.cloud/` → `HTTP/2 307`, `location: /dashboard`, re-run at session start of this pass. |
| **CLM-087** — unmapped `/dashboard/<unknown>` returns a generic placeholder (HTTP 200), not a 404, via the `[...slug]` catch-all | **CONFIRMED under paid conditions — resolves the free-plan pass's open question** | Navigated to `/dashboard/nonexistent-mv-dashboard-paid-check` as the paid admin: HTTP 200, and — unmasked by `SubscriptionGate` — the catch-all's **own** dedicated "Section not found / unknown route / `<path>` does not map to a known section... Back to Dashboard" UI renders correctly, with a working "Back to Dashboard" button. This directly answers interpretation (a) vs (b) raised in the free-plan pass's `MV-dashboard-001`: the catch-all's own placeholder **does exist and work correctly** — it was purely masked by `SubscriptionGate` for free-plan users, not broken. I am not re-filing or closing `MV-dashboard-001` myself (per instruction and per protocol, only the orchestrator/qa-adversary may adjudicate/close another tester's finding) but flag this as directly relevant fresh evidence for that adjudication. |

## 5. Console / network / server-log summary

- **Console errors (all sessions):** 0
- **Page errors (`pageerror`):** 0
- **Server 5xx:** 0
- **Failed requests:** All `net::ERR_ABORTED` entries were `GET /jobs/{id}/insights` calls on `/dashboard/jobs` (a different screen, out of scope) aborted by my own script navigating away mid-request during back/forward testing — benign test-harness artifact, not a production defect, and no such failures occurred on `/dashboard` itself.
- **Total `/api/*` requests observed:** 135 (session 1) + additional in session 2/follow-ups, all 200/201/204 except the documented 409 in MV-dashboard-009 (which is the correct, intended response).
- Raw logs: `test-artifacts/paid/p1-console-events.json`, `p1-page-errors.json`, `p1-network-failures.json`, `p1-server-5xx.json`, `p1-api-requests.json`, and the `p2-*` equivalents.

## 6. Shared-environment note — approvals not exercised destructively

Per the protocol's shared-environment rules ("NEVER delete/modify data you did not create... do not test concurrent-tab scenarios against another tester's flows"), I confirmed via direct DB read that **all 4 currently-pending `ApprovalRequest` rows** (Empire Life, EasyPark, replit, InterEx Group cover letters) and the majority of resolved ones carry payload fields (`instructions: "MV-coverletter-..."`, etc.) or timing clearly belonging to other concurrent screen-testers (cover-letter-studio, approval-modal, mobile-approval screens). I deliberately **did not** click Approve/Reject on any of these live items — doing so would resolve another tester's in-flight test data. I did verify the widget's display, count, and navigation are correctly live-wired (§1, §3) without mutating anything. The one mutating click I did make (MV-dashboard-009) targeted an approval already independently confirmed via DB read to be in a **terminal, already-resolved state** — clicking it could not and did not change any state (verified: backend returned 409, no-op).

## 7. UNSURE items

None outstanding from this pass. (The one ambiguity carried in from the free-plan pass — CLM-087 / MV-dashboard-001 — was resolved with fresh evidence in §4 above, not left as UNSURE.)

## 8. Screenshot index

All under `test-artifacts/paid/`:
- `p1-01-dashboard-loaded-top.png` / `-full.png` — initial paid-plan load, visual conformance baseline
- `p1-02-agent-feed-filtered.png` — feed filter state
- `p1-03-tailor-apply-nav.png` — Tailor & Apply navigation target
- `p1-04-needs-approval.png` — Needs Approval widget close-up
- `p1-05-approvals-page.png` — "review all" navigation target
- `p1-06-market-pulse.png` — full Market Pulse section
- `p1-07-search-results.png` — topbar search wired to live index
- `p1-08-search-xss-probe.png` — XSS probe, safely escaped
- `p1-09-after-bell-click.png` — notification bell navigation
- `p1-10-after-reload.png` — persistence-after-reload check
- `p2-00-unauth-redirect.png` — unauth access, fresh session
- `p2-01-dashboard-loaded.png` — reverify-twice full load
- `p2-02-catchall-paid.png` — catch-all placeholder under paid state (CLM-087)
- `p2-03/04-throttled-*.png`, `p2-05-throttle-followup-final.png` — MV-dashboard-008 evidence
- `p3-00/01-*-stale-approve-click.png` — MV-dashboard-009 evidence
- `p4-01-tooltip-hover.png` — stat-card tooltip check

## 9. NOT-TESTED list (reasons only — none are "ran out of ideas")

- **Actually approving/rejecting a live pending approval end-to-end** (does the queue count decrement, does the linked Application status flip) — protocol-gated: all currently-pending approval items belong to other concurrent testers' active test flows (confirmed via DB payload inspection, §6); exercising this destructively would corrupt their evidence. This is a genuine coverage gap for this pass, not laziness — a dedicated tester creating and resolving their own `MV-dashboard-`-prefixed approval end-to-end would close it.
- **Full systematic 14-route + `/pricing` + `/admin` Playwright sweep for CLM-062** — architecturally out of a single-screen tester's remit; requires the orchestrator's cross-screen aggregation.
- **Backend pytest (676) / frontend vitest (297) full suite re-runs for CLM-024** — out of scope for a single-screen manual UI tester.
- **`/admin` route** — out of matrix scope for the `dashboard` screen-tester.

## 10. Sign-off

Tested by: screen-tester agent (role: MANUAL-VERIFICATION Stage-1 paid-content re-tester), model: Claude Sonnet 5 (claude-sonnet-5), via Playwright against production only. All findings reproduced in ≥2 independent fresh browser sessions before filing (§2 each cites both). No code changes, no service restarts, no destructive mutations of other testers' data. No secrets logged beyond an 8-character token prefix.
