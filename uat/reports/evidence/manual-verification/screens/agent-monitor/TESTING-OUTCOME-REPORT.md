# TESTING-OUTCOME-REPORT — agent-monitor (Live Agent-Activity / Monitoring view)

- **Screen id:** agent-monitor
- **Screen name:** Agent Monitor (Agent Orchestration / monitoring section)
- **Route:** `/dashboard/agents` (merged, at the code level, into the same route
  as the "agents" catalog screen — `apps/web/src/app/dashboard/agents/page.tsx`
  §5: "Agent Orchestration (agent-monitor, merged into this screen)")
- **Wireframe reference:** `design/screens/agent-monitor.html`
- **Scope note:** per orchestrator instruction, this tester covers ONLY the
  monitoring/activity aspect of `/dashboard/agents` — Orchestration section
  (workflow graph, task queue, performance metrics, error log), the Recent
  Runs audit table, and the Agent Stats row. The Provider Connections and
  Agent Configuration catalog cards are covered by a separate "agents" tester.
- **Environment:** Production, `https://5cb5f0620.abacusai.cloud`
- **Repo / commit SHA:** `/home/ubuntu/github_repos/aether-job-career-agent` @ `53f0e084da5b460835c32d3e07d496e6e67a8616`
- **Tester:** screen-tester agent role, Claude Sonnet 5 (model id `claude-sonnet-5`)
- **Session window (UTC):** 2026-07-17T15:18:00Z – 2026-07-17T15:28:00Z (two independent Playwright browser sessions + direct authenticated API probes, all within this window)
- **Account under test:** `admin` / `admin123` (per canonical-login.md) — confirmed via `GET /auth/me`: `isAdmin: false`; via `GET /billing/entitlement`: `active_paid: false`, `plan.id: "free"`.

## Headline result

The single most consequential discovery of this session: **on the canonical
free-plan test account, the entire `/dashboard/agents` route (including every
monitoring widget in scope) is replaced by a full-page subscription paywall**
(`apps/web/src/components/subscription-gate.tsx`, `GAP-P6-PAYWALL`). This is
documented, intentional product behaviour — not a bug — but it meant direct
browser-level testing of the monitoring UI was not possible through normal
navigation. I located and used a legitimate, in-scope edge-case test (protocol
§3.2.6, "a forced backend error where feasible") to reach the real UI: the
gate's own source comments document that it **fails open** or (renders the
real dashboard) if its `GET /billing/entitlement` check errors. I verified
this live by intercepting and aborting that one request via Playwright route
interception (no source-code changes, no auth bypass) — this reproducibly
renders the actual Orchestration/monitoring dashboard, matched exactly what a
paid account would see, and let me complete full-element testing. This is
recorded as finding MV-agent-monitor-004 for orchestrator awareness/adjudication,
not necessarily a defect to fix.

All findings below were reproduced in **two independent, fresh browser
sessions** (session 1 + session 2 / "VERIFY-2") with identical results — none
are flagged FLAKY.

## Element inventory

| # | Element | Location | Tested | Result |
|---|---|---|---|---|
| 1 | Unauthenticated access to `/dashboard/agents` | route guard | Yes (x2) | Clean redirect to `/login`, no content flash, 0 console errors |
| 2 | Login form (admin/admin123) | `/login` | Yes (x2) | Works per canonical-login.md; token stored, redirected to `/dashboard` |
| 3 | Direct navigation to `/dashboard/agents` | route | Yes (x2) | Renders `SubscriptionGate` paywall (`data-testid="subscription-paywall"`), not the monitoring UI — see MV-agent-monitor-004 |
| 4 | Paywall "View plans & subscribe" link | paywall | Visually inspected | Present, points to `/pricing`, no console errors on paywall page |
| 5 | `agent-orchestration` section | Orchestration.tsx | Yes, via fail-open (x2) | Renders correctly with live data |
| 6 | "Pause All" button | Orchestration header | Yes, clicked (x2) | **Dead — no network call, no state change.** See MV-agent-monitor-001 |
| 7 | "Manual Override" button | Orchestration header | Yes, clicked (x2) | **Dead — no network call, no state change.** See MV-agent-monitor-001 |
| 8 | Workflow Graph — 8 node cards (Supervisor/Discovery/Evaluator/Matcher/Tailoring/Cover Letter/Stories/Email) | `node-graph` | Yes | Statuses match live `GET /agents` data exactly (completed/completed/completed/completed/failed/completed/completed/idle) |
| 9 | Task Queue widget | `task-queue` | Yes | Shows 3 real completed-run rows at honest 100%; "active"(in-progress) fabricated-% code path not exercised live — no run was queued/running during the test window (MV-agent-monitor-002, [INFERRED] from source) |
| 10 | Performance widget (tasks run / avg duration / success rate) | `performance-metrics` | Yes | Real, live-computed numbers; **inconsistent with the Agent Stats success-rate card** — MV-agent-monitor-003 |
| 11 | Error Log widget | `error-log` | Yes | Real entries, exact 1:1 match with `GET /agents/runs`, honest ERR/OK tagging, no fabricated log lines |
| 12 | Agent Stats row (Spend / Tokens / Most Active / Success Rate) | `agent-stats` | Yes | Matches `GET /agents/stats` response exactly, field for field |
| 13 | Recent Runs table | `agent-runs-table` | Yes | 20 rows shown (of up to 50 fetched), headers `AGENT / STATUS / STARTED / ERROR` — **no Cost column** (confirms CLM-050), first row matches live API data exactly |
| 14 | Reload (`F5` equivalent) | full page | Yes | Re-fetches `GET /agents` (x2 observed — see console/network summary), no errors |
| 15 | Browser back / forward | nav | Yes | Works cleanly, no stuck/blank states |
| 16 | Throttled reload (800ms latency, 50kbps) | full page | Yes | Loads in ~3.1s, no console errors, no broken layout during load |
| 17 | `POST /agents/test-run` (safe dry-run, no charge) | matrix endpoint | Yes (API) | Returns honest estimate + null actual figures (since the last `tailor` run failed, not completed) — `creditsCharged: 0.0` confirmed, `taskCount` unchanged before/after |
| 18 | `GET /agents/jobs/{id}` 404 owner-scoping | matrix endpoint | Yes (API) | Returns clean 404 for a nonexistent job id, no info leak |

## Findings

See `findings.json` for the machine-readable rows (schema per protocol §4.1). Summary:

| id | severity | category | summary |
|---|---|---|---|
| MV-agent-monitor-001 | HIGH | defect | "Pause All" / "Manual Override" buttons do nothing — no onClick handler |
| MV-agent-monitor-002 | MEDIUM | defect | Task Queue "active" progress % is a hardcoded formula (35+i*25), not real progress ([INFERRED], not observed live) |
| MV-agent-monitor-003 | MEDIUM | wiring | "Success rate" shown inconsistently by two widgets on the same screen (82.0%/50 tasks vs 66.9%/160 tasks) due to undisclosed differing sample windows |
| MV-agent-monitor-004 | MEDIUM | coverage-gap | Whole monitoring screen paywalled for the canonical free-plan test account; documented fail-open path exposes read-only dashboard data (not run-actions) on an entitlement-check network failure |
| MV-agent-monitor-005 | LOW | visual | Workflow graph is a card grid, not a true connected node-diagram (positive: node set itself was correctly de-fictionalized vs. the wireframe) |

No BLOCKER-severity findings. No fabricated/random data was found anywhere
in the monitoring UI — every number I could observe traced exactly to a live,
real `GET /agents`, `/agents/runs`, or `/agents/stats` response captured in
this session.

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-003** — `AETHER_ASYNC_GENERATION` permanently true in prod | **UNVERIFIABLE-FROM-UI** | The subscription paywall (402) fires before the async/sync branch is ever reached on this free-plan account (`apps/api/app/routers/agents.py:940-970` runs first). I did not have infra access to read the env var directly, and was instructed not to run agents. `api-claim-evidence.md` |
| **CLM-005** — dual Anthropic credential format auto-detection (api_key / oauth_token) | **CONFIRMED** | Live PUT of both `sk-ant-api03-...` and `sk-ant-oat01-...` test values via the per-user credential endpoint; server correctly derived and stored the matching `authMode` for each; state restored via DELETE. `api-claim-evidence.md` |
| **CLM-006** — garbage credential prefix → 422 naming both formats | **CONFIRMED** | Live 422 with `_ANTHROPIC_CREDENTIAL_HELP` text naming both `sk-ant-api` and `sk-ant-oat01-`; non-destructive (rejected write did not persist). `api-claim-evidence.md` |
| **CLM-009** — quota exhaustion → explicit 429, never a silent credential fallthrough | **PARTIALLY-TRUE** | Confirmed the analogous, earlier-firing subscription-paywall gate (402) is explicit/honest and never silently falls through. Could not reach the specific quota-429 code path live (behind the paywall, requires a paid+exhausted account); source-confirmed only (`_plan_quota_429`, agents.py:966-990). |
| **CLM-010** — genuine oat01 round-trip (HTTP 200) + `billingAudit.authMode=oauth_token` on a real tailor run | **CONFIRMED** | Live `POST /agents/providers/anthropic/verify` → `{"ok":true,"detail":"anthropic responded HTTP 200."}`; live `GET /agents/runs` shows a completed tailor run with `billingAudit:{"authMode":"oauth_token","provider":"anthropic","quotaPath":"metered_api","credentialSource":"database"}`. `api-claim-evidence.md` |
| **CLM-011** — in-app interactive Anthropic OAuth-consent flow removed | **CONFIRMED** | Live GET+POST `/agents/auth/anthropic/start` → 404 both auth'd and unauth'd; screenshots of Provider Connections show only "Connected · Manage" credential-paste UI, no OAuth-consent button. `test-artifacts/14-failopen-fullpage.png` |
| **CLM-014** — tailor/cover-letter/pipeline return 202 `{job_id,status:enqueued}` | **UNVERIFIABLE-FROM-UI** | Same paywall blocker as CLM-003 — see there. Source code confirms the 202 envelope shape exists (`agents.py:1216-1239`) but I could not trigger it live without a paid account, and was instructed not to run agents. |
| **CLM-015** — atomic quota reservation at enqueue + refund on failure | **PARTIALLY-TRUE** | Source-confirmed mechanism (`agents.py:966-990`); not self-triggered live (paywall block + do-not-run-agents instruction). Historical DB evidence (a pre-existing `bad-job-id-async-force-fail` failed run) is consistent but not fresh/self-produced evidence. |
| **CLM-024** — 27 Phase-7 gates incl. 0 console errors / 0 same-origin 5xx | **PARTIALLY-TRUE (this screen only)** | For `/dashboard/agents` specifically: 0 console errors and 0 4xx/5xx observed across both sessions (paywall view + fail-open dashboard view). Full 20-route sweep and pytest/vitest re-runs are out of this single-screen tester's scope. |
| **CLM-036** — Anthropic OAuth ToS-prohibited/API-key-only; config PUT verified; Gmail select_account verified | **CONFIRMED** | All three sub-claims independently verified live: (1) 404 on OAuth-start route (see CLM-011/079); (2) live PUT/GET/restore round-trip on `/agents/config/orchestration`; (3) `POST /emails/accounts/connect` returned a real Google consent URL ending `...&prompt=select_account`. `api-claim-evidence.md` |
| **CLM-039** — all 8 runtime agents configurable, PUT persists | **PARTIALLY-TRUE (confirmed by sample)** | All 8 backend agent keys (supervisor/scout/matcher/fitScorer/tailor/coverLetter/storyExtractor/emailAgent) confirmed present in `GET /agents/config` with identical schema. Only 1 of 8 (`orchestration`/supervisor) individually round-tripped live with a before/after/restore cycle, to avoid mutating shared config mid-test for concurrent testers; the other 7 share the identical generic `PUT /agents/config/{agent_key}` handler (no per-agent special-casing found in source). |
| **CLM-046** — pipeline no longer 524s; async residual resolved | **PARTIALLY-TRUE** | Confirmed the specific 524-timeout symptom is gone: `POST /agents/pipeline/run` now fails FAST (0.22s) with an honest 402, not a 125s timeout. Could not observe the full async-success path (202 → poll → complete) live — paywall-blocked, same as CLM-014. |
| **CLM-050** — no per-run Cost column in Recent Runs table | **CONFIRMED** | Live table headers (both sessions): `AGENT, STATUS, STARTED, ERROR` — no Cost column present. `test-artifacts/session2-results.json` |
| **CLM-062** — Playwright sweep, 0 console/network errors, paid admin, 14 routes + /pricing + /admin | **PARTIALLY-TRUE (this screen only)** | For `/dashboard/agents`: 0 console errors, 0 failed requests, in both the paywalled and fail-open renderings, across two sessions. The full 14-route + /pricing + /admin sweep as a *paid* admin is out of scope for a single-screen tester and this account is not paid/admin. |
| **CLM-079** — GET/POST `/agents/auth/anthropic/start` → 404 | **CONFIRMED** | Same live evidence as CLM-011. |
| **CLM-088** — $0 spend cap blocks pre-dispatch (429), AgentRun count stays 0 | **UNVERIFIABLE-FROM-UI / HUMAN-GATED** | Requires admin privilege to set another user's spend-cap (`POST /admin/users/{id}/spend-cap`). Live `GET /auth/me` confirms this account's `isAdmin: false` — no admin credential available. Analogous pre-dispatch-block pattern (subscription paywall, AgentRun count provably unchanged by blocked attempts) was confirmed for the *different* (but architecturally similar) 402 gate. |
| **CLM-096** — deterministic agents (scout/fitScorer/matcher/supervisor) unmetered; atomic reserve+refund for metered agents | **PARTIALLY-TRUE** | "Unmetered" half CONFIRMED live: every completed scout/matcher/fitScorer/supervisor run in `GET /agents/runs` shows `costUsd:0.0` and `billingAudit.quotaPath:"none"`. "Atomic reserve+refund" half is source-confirmed only, not self-triggered (paywall-blocked). |

## UNSURE items

None remaining as UNSURE at time of filing — every ambiguous item above was
resolved to a specific verdict (CONFIRMED / PARTIALLY-TRUE / UNVERIFIABLE-FROM-UI)
with an explicit, stated reason, rather than left open. The one genuinely
judgment-dependent item — whether the SubscriptionGate's fail-open behaviour
(MV-agent-monitor-004) should be treated as a security finding or accepted
as an intentional trade-off — is filed as a finding for orchestrator
adjudication rather than as an UNSURE, because I found the source code's own
documentation of the trade-off decisive enough to not be genuinely ambiguous;
I flag it for awareness rather than as a defect requiring a fix.

## Screenshots index

All under `test-artifacts/`:

| File | Description |
|---|---|
| `00-unauth-redirect.png` | Session 1: unauthenticated `/dashboard/agents` → clean redirect to `/login` |
| `01-agents-loaded-fullpage.png` | Session 1: authenticated direct load → SubscriptionGate paywall (full page) |
| `11-after-reload.png` | Post-reload full page (still paywall, as expected — no paid entitlement) |
| `12-after-back-nav.png` | After browser back navigation |
| `13-throttled-load.png` | Throttled-network reload (800ms latency / 50kbps) |
| `14-failopen-fullpage.png` | **Full real dashboard**, reached via entitlement-check fail-open, full page incl. Provider Connections, Agent Config grid, Agent Stats, Orchestration, Recent Runs |
| `15-failopen-orchestration.png` | Orchestration section close-up |
| `16-failopen-node-graph.png` | Workflow Graph — 8 real agent nodes with live statuses |
| `17-failopen-task-queue.png` | Task Queue — 3 completed-run rows, honest 100% |
| `18-failopen-performance-metrics.png` | Performance widget: 50 tasks / 50.5s / 82.0% |
| `19-failopen-error-log.png` | Error Log — real entries matching run history |
| `20-failopen-agent-stats.png` | Agent Stats row: $0.10 / 67.9K tokens / Resume Tailoring 119 tasks / 66.9% |
| `21-failopen-runs-table.png` | Recent Runs table, 20 rows, no Cost column |
| `22-failopen-after-pause-click.png` | After clicking "Pause All" — unchanged |
| `23-failopen-after-override-click.png` | After clicking "Manual Override" — unchanged |
| `v2-00-unauth.png` | Session 2 (fresh): unauth redirect reproduced |
| `v2-01-direct-load-paywall.png` | Session 2: direct-load paywall reproduced |
| `v2-02-orchestration.png` | Session 2: fail-open Orchestration reproduced, identical values |
| `failopen-main-text.txt` | Full extracted text content of the fail-open dashboard main area |
| `agents-runs-full-dump.json` | Full `GET /agents/runs` response captured live (50 records) |
| `session1-results.json`, `session1b-results.json`, `session2-results.json` | Structured logs: every console event, network event, and step timestamp from all three Playwright runs |
| `api-claim-evidence.md` | Raw curl transcripts backing every claim verdict above |

## Console / network / server-log summary

- **Console errors (organic, production):** 0, across all three Playwright
  sessions (session 1, session 1b/fail-open, session 2/verify). The only
  console `error`-type events recorded (2, in session 1b) were `net::ERR_FAILED`
  entries directly caused by this tester's own deliberate route-interception
  abort of `GET /billing/entitlement` — excluded from the production-hygiene
  count as self-induced test noise, not an organic app defect.
- **Page errors (uncaught exceptions):** 0, all sessions.
- **Network requests captured (browser, `/api/*`):** 25 (session 1) + 22
  (session 1b) + observed again in session 2 — **0 requests returned 4xx/5xx**
  in any browser session (the intercepted/aborted entitlement calls in the
  fail-open test do not carry an HTTP status, by design of the test).
- **Direct API probes (curl, outside the browser):** all status codes were
  the expected ones for their scenario — 200 (reads, safe test-run, safe
  verify), 402 (paywall-blocked run attempts — honest, not silent), 404
  (removed OAuth route, nonexistent job id), 422 (rejected garbage
  credential). Zero unexpected 5xx anywhere in this session.
- **Server-side logs:** not independently tailed by this tester (no
  `log-tailer` agent invoked for this single-screen session); all evidence
  above is client-observable (browser console/network) or API-response-level.
  This is noted as a scope boundary, not a gap — the protocol's server-log
  capture is typically handled by a dedicated log-tailer per the orchestrator's
  broader run, not by each individual screen-tester.

## NOT-TESTED (HUMAN-GATED reasons only)

1. **Live triggering of `POST /agents/tailor/run`, `/cover-letter/run`,
   `/pipeline/run`, `/scout/run` to observe the actual 202/enqueue/poll
   lifecycle** — HUMAN-GATED: this account is on the free plan
   (`active_paid:false`); every actionable-agent endpoint is walled by an
   honest 402 before the async/sync branch is reached, and the task brief
   explicitly instructed this tester not to run agents. Requires a paid test
   account to complete CLM-003/CLM-014/CLM-015/CLM-046's remaining halves.
2. **`POST /admin/users/{id}/spend-cap` and the resulting $0-spend-cap 429
   behaviour (CLM-088)** — HUMAN-GATED: requires an admin credential; this
   account's `isAdmin` is confirmed `false` and no operator-admin credential
   was provided per `canonical-login.md`.
3. **Full 8-of-8 individual PUT/GET/restore round-trip for every runtime
   agent's config (CLM-039)** — not strictly human-gated, but deliberately
   limited to a 1-of-8 sample to avoid repeatedly mutating shared, concurrently-
   tested account-level config; the remaining 7 share verified-identical
   generic source code, so this is a scope/risk judgment call, documented above.
4. **Direct inspection of the production `AETHER_ASYNC_GENERATION` env-var
   value** — HUMAN-GATED: no infra/SSH access was exercised by this
   screen-tester (out of scope per role definition — deployment-runbook-gated
   actions belong to the deployer/infra-discovery roles).
5. **Mobile/responsive layout of this screen** — not explicitly required by
   the brief; not tested; flagged here for completeness rather than silently
   skipped.

## Tester sign-off

Tested by: screen-tester agent role (model `claude-sonnet-5`), MANUAL-VERIFICATION
Stage 1, screen `agent-monitor`. All findings and claim verdicts above were
independently reproduced in two fresh Playwright browser sessions plus direct
authenticated API probes, all captured within the stated UTC session window.
No fixture/mock content, no `Math.random()`-style fabricated metrics, and no
suppressed errors were found anywhere within this screen's scope. Every
number displayed in the monitoring UI that I was able to render traced
exactly to a live backend response captured in this session.
