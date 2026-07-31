# TESTING OUTCOME REPORT — /dashboard/agents (GOLD-MASTER-V4, WORKSTREAM A §3.2, batch 3)

Tester: screen-tester agent. Production URL: https://5cb5f0620.abacusai.cloud
Timestamp window: 2026-07-31T17:59–18:05Z (see per-screenshot filenames / JSON timestamps for exact ts).
Account: AETHER_CRON_EMAIL (non-admin). Tooling: Playwright (Python, headless Chromium), 1440x1000 viewport.

## Element inventory (VERIFIED-WITH-FRESH-EVIDENCE, 01-initial-load.png + results.json)

- Header: "22 agents · 7 AI providers · configure models & connections" — count is internally consistent (22 cards rendered = 22 in header; no wireframe-style discrepancy).
- Topbar buttons: Add Provider, Test Run, Run All (Run All untested — would run the full pipeline, out of scope for a safe read-only probe).
- Provider Connections section: 7 cards — anthropic, openrouter, openai, gemini, bedrock, groq, abacus (wireframe promised 6; abacus/"Abacus Subscription (fallback)" is a real 7th, documented in code as the last-resort billing path).
- Agent Configuration grid: 22 cards, all status "Active" (0 Paused/Error/Planned at capture time — differs from wireframe's fictional Paused/Error examples). Full roster + model + Run/toggle presence in results.json → `inventory.agent_cards`. **Submission Agent card is present** (key `submission`, model `deterministic`, status Active, has Run button + toggle) — confirms the code-level catalog entry (`apps/api/app/routers/agents.py:201`) renders live.
- Recent runs table (`agent-runs-table`): columns **Agent | Status | Started | Error** only — no jobs_submitted / jobs_skipped / ats_avg_delta / duration columns. Shows up to 20 rows (code: `runs.slice(0, 20)`), not "last 10".
- Agent Orchestration panel: workflow graph (8 real nodes: Supervisor/Discovery/Evaluator/Matcher/Tailoring/Cover Letter/Stories/Email — not the wireframe's 6 fictional nodes), Task Queue, Performance (tasks run / avg duration / success rate), Error Log. "Pause All" and "Manual Override" buttons present but **disabled** (`aria-disabled`, tooltip "Not yet available") — confirmed via `pause_all_disabled: true` / `manual_override_disabled: true`.
- No approval-queue panel, no pending-approval badge, no "Approve All" CTA, and no ATS-delta chips anywhere on this screen (`approval_queue_panel_present: false`, `approve_all_cta_present: false`, `ats_delta_chip_present: false`) — that functionality lives on `/dashboard/approvals` per SCREEN-MATRIX, confirmed absent here specifically.
- Per-agent settings panel (gear icon → `agent-settings-<key>`): Temperature (disabled for deterministic agents), Thinking effort (None/Low/Medium/High), Billing credential (provider-scoped dropdown + "Bills to:" readout), Save settings. **No `submission_ats_threshold` or `submission_auto_approve` field exists anywhere in this panel** (confirmed on the Submission Agent card itself — 05-settings-panel-submission.png) — matches the backend `AgentConfigUpdate` model (`apps/api/app/routers/agents.py`), which has no such fields.
- Provider config modal (anthropic, 16-provider-config-modal-anthropic.png): has Test connection, Show/Hide secret reveal, and subscription-vs-API-key auth-mode controls (`modal_has_test_connection/show_hide/auth_mode_radio: true`).
- Test Run modal: 22-option agent select (one per catalog agent, each showing its assigned model), ran a real dry-run — network capture shows `POST /api/agents/test-run` → 200, matching the backend's documented "never invokes the live LLM, charges nothing" contract.

## Targeted verifications (G-SUB)

1. **Submission Agent card**: PRESENT. Status "Active", model "deterministic" (it's a DB read/write gate agent, not an LLM). Actions offered: Run, gear (settings), enable/disable toggle. [VERIFIED-WITH-FRESH-EVIDENCE 01-initial-load.png, results.json, 20260731]
2. **Approval queue panel / pending-count badge / "Approve All" CTA on this screen**: ABSENT on `/dashboard/agents` (lives on `/dashboard/approvals` instead, per SCREEN-MATRIX; not re-verified here as out of scope). [VERIFIED-WITH-FRESH-EVIDENCE 02-run-history-and-orchestration.png]
3. **Run history table**: PRESENT, 20 rows, columns Agent/Status/Started/Error — **does not** include jobs_submitted/jobs_skipped/ats_avg_delta/duration as §14.5.5 specifies. [VERIFIED-WITH-FRESH-EVIDENCE 02-run-history-and-orchestration.png, results.json]
4. **ATS delta chips**: ABSENT anywhere on this screen. [VERIFIED-WITH-FRESH-EVIDENCE 02-run-history-and-orchestration.png]
5. **Safe agent run triggered**: Match Scoring Agent (`matchScoring`, backend `fitScorer`) — chosen because it is a deterministic, read-only scorer over already-discovered jobs (no email, no submission, no real spend; backend docstring confirms "no LLM cost"). Network capture: `POST /api/agents/fit-scorer/run` → 200, completed in ~3.4s. **Mechanism confirmed: POLLING, not SSE.** No `EventSource`/SSE connection observed anywhere in the network log. While the run was in flight, the page polled `GET /agents/runs`, `GET /agents`, `GET /agents/stats`, `GET /agents/catalog` at the code-documented 3000ms cadence (`POLL_MS`), started by the click handler and stopped once the run resolved — this matches `apps/web/.../dashboard/agents/page.tsx` exactly. [VERIFIED-WITH-FRESH-EVIDENCE 08-run-triggered.png, 09-run-after-20s.png, results.json → `run_trigger_network_calls`]
6. **Idle-window polling (60s, no user action)**: only 2 `GET /api/agents` calls, 30.01s apart, plus one `GET /api/approvals?status=pending` — i.e. the page itself has **no continuous poll at idle** (its 3s interval only runs during an active trigger); the ~30s cadence is a *global sidebar widget* poll (`apps/web/src/components/sidebar.tsx:45`, `setInterval(load, 30_000)`), present on every dashboard route, not specific to this screen. **This 30s interval exceeds the §15.1 ≤20s idle-poll requirement** if that gate is meant to cover this global widget — flagged below as ML-AGENTS-003. [VERIFIED-WITH-FRESH-EVIDENCE 10-after-idle60.png, results.json → `idle_60s_network_calls`]
7. **Per-agent settings (thresholds/auto-approve)**: exposes Temperature / Thinking effort / Billing credential only — **no `submission_ats_threshold` or `submission_auto_approve` control exists** on the Submission Agent's settings panel or any other agent's. [VERIFIED-WITH-FRESH-EVIDENCE 05-settings-panel-submission.png]

## Interaction / forms / persistence

- Toggle test (jobDiscovery agent, chosen as low-risk — avoided submission/tailor/coverLetter/emailAgent): `true → false` on click, confirmed `false` on hard reload (persistence real, not optimistic-only), then restored to `true` and confirmed restored. [VERIFIED-WITH-FRESH-EVIDENCE 06/07 screenshots, results.json → `toggle_persistence_test`]
- Test Run modal: opened, 22 options enumerated, ran dry-run → 200, closed cleanly.
- Provider config modal (Anthropic): opened, clicked "Test connection" → `POST /agents/providers/anthropic/verify` → 200 (read-only verify, no credential mutated), closed without saving/removing anything.
- Reload-and-re-read: after the fit-scorer run, reloading the page shows the run recorded at the top of the Recent Runs table: `fitScorer | completed | 31/07/2026, 6:00:54 pm | —`. [VERIFIED-WITH-FRESH-EVIDENCE 11-reload-final.png, results.json]

## Error / edge states

- Unauthenticated access to `/dashboard/agents` → redirected to `/login?next=%2Fdashboard%2Fagents`. [VERIFIED-WITH-FRESH-EVIDENCE 12-unauthenticated-access.png]
- Back/forward nav (agents → analytics → back → forward): URLs transition correctly, no stuck/blank states. [VERIFIED-WITH-FRESH-EVIDENCE 14/15 screenshots]
- Verified twice: a second, fully independent browser session (fresh login) re-confirmed 22 agent cards and the Submission Agent card present. [VERIFIED-WITH-FRESH-EVIDENCE 13-freshsession2-verify.png]

## Console / network / server-log summary

- console-log.json / pageerrors.json / requestfailed.json: captured for the full session; no console errors or failed requests observed during the run above (files in this directory).
- All XHR/fetch calls observed returned 2xx; no silent-fail or optimistic-success-on-error pattern observed in this pass.

## Findings

| id | screen | severity | category | summary | reproduction | expected | observed | evidence | status |
|---|---|---|---|---|---|---|---|---|---|
| ML-AGENTS-001 | /dashboard/agents | MEDIUM | spec-conformance | Recent Runs table missing required columns | Load /dashboard/agents, inspect `agent-runs-table` headers | §14.5.5: jobs_submitted, jobs_skipped, ats_avg_delta, duration, status columns, last 10 rows | Only Agent/Status/Started/Error columns; shows up to 20 rows | 02-run-history-and-orchestration.png, results.json | OPEN |
| ML-AGENTS-002 | /dashboard/agents | MEDIUM | spec-conformance | No submission_ats_threshold / submission_auto_approve config exposed | Expand Submission Agent settings gear | §14.4.7: per-agent submission_ats_threshold + submission_auto_approve fields | Only Temperature/Thinking effort/Billing credential present; backend `AgentConfigUpdate` model has no such fields | 05-settings-panel-submission.png | OPEN |
| ML-AGENTS-003 | /dashboard/agents | LOW | performance/spec-conformance | Idle background poll interval is 30s, not ≤20s | Sit idle on any /dashboard/* route for 60s with network capture | §15.1: ≤20s polling interval | Global sidebar widget polls `GET /agents` every 30s (`sidebar.tsx:45`); page's own listeners are event-triggered only (no idle poll at all) | 10-after-idle60.png, results.json → idle_60s_network_calls | OPEN |
| ML-AGENTS-004 | /dashboard/agents | INFO | wireframe-drift | No approval queue panel / Approve All CTA / ATS-delta chips on this screen | Load /dashboard/agents | §14.5.2/§14.5.4/§14.5.6 implied on Agents screen | That functionality lives on /dashboard/approvals instead; Agents screen has none of it | 02-run-history-and-orchestration.png | OPEN (informational — confirms scope split, not necessarily a defect) |

No BLOCKER or HIGH findings on this screen. No placeholder/fixture content observed on any user-reachable element.

## Not-tested (out of scope / HUMAN-GATED)

- "Run All" pipeline button — would trigger tailor/coverLetter/email agents with real LLM cost and potential real side effects; not run per SAFETY constraints.
- Actually running the Submission Agent — would perform a real `POST /jobs/{id}/apply` write per its own docstring; not run per SAFETY constraints (HUMAN-GATED).
- Adding/removing/saving a real provider credential (all 7 providers) — mutating real billing credentials is out of scope for a read-only pass; only Test-connection (non-mutating) was exercised.
- OpenRouter live-catalog full picker (search/select/save/reload-persist across the 300+ model catalog) — spot-checked presence only (ModelPicker section rendered); full exhaustive picker sweep not performed in this pass (time-boxed).

## Data left behind

- One real agent run recorded: `fitScorer / completed / 2026-07-31 18:00:54` — a genuine, harmless read-only scoring run over the account's own already-discovered jobs. Not deleted (run history has no delete affordance visible; leaving it is the honest state per "document exactly what was left").
- jobDiscovery agent toggle: flipped off then back on; confirmed restored to original `enabled: true` state via reload.

## Sign-off

Screen tested per §3.2 protocol: load+screenshot, wireframe conformance, every visible control clicked/exercised, one safe agent run end-to-end with network capture, idle-poll measurement, reload persistence, unauthenticated + back/forward nav, verified twice in a fresh session. Verdict: **functional, real backend wiring confirmed (no fixture/placeholder data), polling-not-SSE confirmed, 2 real spec gaps (ML-AGENTS-001/002) + 1 minor timing gap (ML-AGENTS-003) filed as OPEN.**
