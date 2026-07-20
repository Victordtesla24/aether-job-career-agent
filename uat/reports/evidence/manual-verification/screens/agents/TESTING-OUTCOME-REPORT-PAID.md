# TESTING-OUTCOME-REPORT — Agents (Agent Catalog) — PAID CONTENT RE-TEST

**Screen id:** `agents` | **Screen name:** Agent Catalog / Manage Agents | **Route:** `/dashboard/agents`
**Wireframe ref:** `design/screens/agents.html` (marked in `BRIEF.json` as a superseded design mock — "Duplicate of agent-monitor (design evolution)"; the live app has evolved beyond it, see Visual Conformance)
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Commit SHA:** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Production URL:** `https://5cb5f0620.abacusai.cloud`
**Environment:** production, admin/admin123, TEMPORARY Pro entitlement granted for this re-test (`GET /api/billing/entitlement` → `active_paid:true, plan.id:"pro"`)
**Session window (UTC):** 2026-07-17T16:52:48Z – 2026-07-17T17:00:50Z
**Tester:** screen-tester agent (Claude Agent SDK, Claude Fable 5 / claude-sonnet-5), MANUAL-VERIFICATION Stage 1, PAID re-test pass.

## Purpose of this pass
The prior free-plan pass (`TESTING-OUTCOME-REPORT.md`, findings `MV-agents-001`/`002`) could not render the catalog DOM at all — the account was Free-plan and the global SubscriptionGate replaced the whole page with a paywall. `MV-agents-001` documents that root cause and is **not re-filed here**. Admin now carries a TEMP Pro entitlement so the real catalog renders; this pass tests the **actual rendered UI**: every agent card, provider card, modal, and control, per protocol §3.2, with fresh evidence from 3 independent Playwright sessions plus direct API corroboration. New findings only, numbered from `MV-agents-003`.

## Element inventory

| # | Element | Tested via | Result |
|---|---|---|---|
| 1 | Page load (authenticated, Pro) | LIVE-DOM ×3 sessions | Renders fully — no paywall (`data-testid=subscription-paywall` count: 0). 22 agent cards, 7 provider cards, quick-stats row, Agent Orchestration panel, Recent Runs table all mount and populate from real API data. |
| 2 | "Add Provider" button | LIVE-DOM | Opens `ProviderConfigModal` for the first unconfigured provider (OpenAI) — confirmed live, closed without saving. |
| 3 | "Test Run" button (header) | LIVE-DOM ×2 sessions | Opens modal; **majority of its own dropdown is broken** — see `MV-agents-003`. |
| 4 | "Run All" (pipeline) button | LIVE-DOM (presence/enabled only, NOT clicked) | Present, enabled, not busy. Not executed — full multi-agent pipeline run is quota-heavy and out of scope per brief ("do NOT run agents to exhaustion"); wiring already read in source (`runPipeline()` → `POST /agents/pipeline/run`) and its 402-honesty already confirmed by the free-plan pass. |
| 5 | 7 AI Provider Connection cards | LIVE-DOM | Anthropic, OpenRouter, OpenAI, Google Gemini, AWS Bedrock, Groq, **Abacus Subscription (fallback)** (7th card, a documented, intentional addition beyond the 6-card wireframe — GAP-P4-055). All render real per-provider state. |
| 6 | Provider card action button (Connected·Manage / Configure keys) | LIVE-DOM | Anthropic, OpenRouter, Abacus → "Connected · Manage"; OpenAI, Gemini, Bedrock → "Configure keys" (all unconfigured, honest). **Anthropic's "Connected" is misleading — see `MV-agents-004`.** |
| 7 | Provider Config modal — Anthropic (open/inspect/close) | LIVE-DOM ×2 sessions | Opens; shows 2 auth-mode radios (`authmode-api_key`, `authmode-oauth_token`); no "Connect with Anthropic" OAuth-consent button anywhere in the DOM (see CLM-011). |
| 8 | Provider Config modal — "Test connection" (Anthropic) | LIVE-DOM ×2 sessions, real round-trip | Confirmed genuine live call to `api.anthropic.com`; returned an honest `HTTP 401` failure both times (see `MV-agents-004`). |
| 9 | Provider Config modal — Bedrock (unconfigured) | LIVE-DOM | Opens; "Test connection" correctly `disabled` (no credential yet); single `api_key` mode only (no dual radio, correct per `authModeOptions()`). |
| 10 | Provider Config modal — Save credential / Remove | SOURCE + logic verified | **Not clicked** in this pass — `putProviderCredential`/`deleteProviderCredential` write to the **deployment-wide** route (`PUT/DELETE /agents/providers/{id}/credential`, not the per-user route), i.e. this modal's Save/Remove mutate a credential shared by all concurrent testers. Deliberately avoided per shared-environment rules; CLM-005/006 were instead re-verified via the non-destructive per-user route (see Claim verdicts). |
| 11 | Agent Configuration grid — 22 cards | LIVE-DOM ×3 | All 22 render: 9 Active (green), 1 Error (red — Cover Letter Agent), 12 Planned (grey, no Run/Toggle/Settings buttons at all). Legend counts (`9 Active · 0 Paused · 1 Error · 12 Planned`) match `GET /agents/catalog` `.counts` exactly. |
| 12 | Agent card info-tooltip (hover) | LIVE-DOM | Hovered `jobDiscovery`'s tooltip — real per-agent tip text renders on hover. |
| 13 | Agent card Settings toggle → `AgentSettingsPanel` | LIVE-DOM | Opened for `jobDiscovery`: Temperature (disabled, "Deterministic agent — no LLM sampling"), Thinking effort radios, Billing credential select ("Deployment default"), Save settings button. Closed without saving. |
| 14 | Agent card "Run" button (runnable agents) | LIVE-DOM (presence/enabled only, NOT clicked) | Present + enabled on all 9 runnable/active + 1 error card. **Deliberately not clicked** — brief: "Do NOT run agents to exhaustion (quota shared); a single config/detail interaction is fine" — the Test Run dry-run (item 15) was used instead to satisfy protocol §3.2.5 without spending quota. |
| 15 | Test Run modal — dropdown + Run Test | LIVE-DOM ×2 sessions, 5 different agents tried | 4/22 work correctly (resumeTailoring, coverLetter, emailAgent, storyExtraction — genuine dry-run, honest `creditsCharged:0.0`). **18/22 throw a raw Zod validation error — `MV-agents-003`.** |
| 16 | Planned-card gating (no Run/Toggle/Settings) | LIVE-DOM, spot-checked 4 cards (compliance, submission, salaryIntelligence, notification) | Confirmed: zero interactive buttons render on any Planned card — honest, matches source. |
| 17 | Orchestration Agent card (status Active, `runnable:false`) | LIVE-DOM | Toggle + Settings gear present, no Run button (by design — its function is exposed via the header's "Run All", not a duplicate per-card control). Not a defect. |
| 18 | Quick stats row (spend/tokens/most-active/success-rate) | LIVE-DOM + API | Real, live-changing numbers (`$0.12` spend, `81.1K` tokens, "Resume Tailoring" 126 tasks, `67.5%` success over last 200) — cross-referenced against `GET /agents/stats`, non-fabricated. |
| 19 | Agent Orchestration panel (workflow graph / task queue / error log) | LIVE-DOM | Real workflow-graph node statuses, real task queue entries, real error log with varied, non-repeating messages (see AI-agent integration section) — an app-only addition beyond the wireframe, not a bug. |
| 20 | Recent Runs table | LIVE-DOM | Real rows, real timestamps, real distinct error strings per row (not one canned message). |
| 21 | Unauthenticated access to `/dashboard/agents` | LIVE-DOM ×2 sessions | Clean client-side redirect to `/login`, zero content leak, reproduced twice. |
| 22 | Back/forward browser navigation | LIVE-DOM | `/dashboard/agents` → `/dashboard` → back → forward: clean, correct URL bar and content both directions, no stale DOM, no crash. |
| 23 | Throttled reload (CDP Slow-3G: 50KB/s down, 400ms latency) | LIVE-DOM | Resolved to an honest loading-skeleton state, then to the full correct page; zero console errors, zero failed requests. |
| 24 | Provider model `<select>` (e.g. OpenRouter) | LIVE-DOM (observed only, not changed) | Renders real per-provider model list (`openrouter`: 2 models; `openai`: 3; `bedrock`: 0 → shows disabled "Select region" placeholder). Not mutated — `PUT /agents/providers/{id}` (deployment-wide, same shared-state concern as item 10). |

## Findings
See `findings-paid.json` for the exact schema rows. Summary table:

| id | severity | category | summary |
|---|---|---|---|
| MV-agents-003 | HIGH | defect | Test Run modal throws a raw, truncated Zod validation error for 18/22 selectable agents (all 12 Planned + 6 real deterministic-Active agents) because `POST /agents/test-run` legitimately returns `null` for `model`/`estTokens`/etc. for non-LLM/unimplemented agents, but the frontend's `TestRunSchema` declares those fields non-nullable. Only the 4 true LLM-backed agents work. |
| MV-agents-004 | HIGH | defect | Anthropic provider card shows a permanent green "Connected · Manage" status even after a live "Test connection" round-trip proves the stored credential returns `HTTP 401` ("OAuth access token has expired"). `status` is derived purely from "a DB credential row exists", never demoted by a failed `lastVerifyStatus`. |

Neither finding is BLOCKER-severity: core money-path journeys (discovery → tailor → cover letter → apply, and the "Run" button on every runnable card) are unaffected; both defects are isolated to two secondary utility surfaces (the dry-run cost preview, and one provider's stale status badge).

## Claim verdicts
This screen's assigned claim rows (`CLM-005`, `CLM-006`, `CLM-011`) were already **CONFIRMED** by the earlier free-plan pass using fresh API evidence. Per protocol §3.2.8 ("never adjudicate from documents"), all three were **independently re-reproduced live in THIS session** (fresh curl transcript, non-destructive per-user route, state fully restored) plus, for CLM-011, fresh LIVE-DOM corroboration of the rendered modal that the paywall previously blocked:

| Claim | Verdict | Fresh evidence (this session) |
|---|---|---|
| **CLM-005** — `PUT /agents/user/providers/anthropic/credential` auto-detects/accepts both a Console API key (`sk-ant-api03-…`) and a Claude Code OAuth token (`sk-ant-oat01-…`), tagging the correct `authMode` | **CONFIRMED** | `api_key`-mode secret → `{"authMode":"api_key", "lastVerifyStatus":"failed", ...}` (fake secret, honestly fails verify — never fabricated "ok"); `oauth_token`-mode secret → `{"authMode":"oauth_token", ...}`. Both round-tripped with the matching mode declared. A mode/prefix MISMATCH (api_key mode + oauth-shaped secret) was correctly rejected: `422 "Credential prefix is a 'oauth_token' credential but you selected 'api_key'."` — evidence: `test-artifacts/paid/api-*` curl transcript (inline above), state restored to `[]` immediately after (confirmed via `GET /agents/user/providers`). |
| **CLM-006** — A garbage/unrecognized Anthropic credential prefix is rejected `422` naming both accepted formats | **CONFIRMED** | `garbage-not-a-real-prefix-MVagentsPAID` → `422 {"detail":"Anthropic credential not recognized. Console API keys start with 'sk-ant-api'. Claude Code OAuth tokens start with 'sk-ant-oat01-'. ..."}` — names both formats verbatim. |
| **CLM-011** — The interactive "Connect with Anthropic" OAuth-consent flow remains removed; only paste-token entry exists | **CONFIRMED** | Endpoint-removal half: `GET`/`POST /agents/auth/anthropic/start` and `GET /agents/auth/anthropic/callback` → `404` (all three, fresh this session). UI-absence half — **upgraded from SOURCE-only (free pass) to LIVE-DOM** this session: the rendered `ProviderConfigModal` for Anthropic was opened live and its full inner HTML inspected — zero occurrence of "Connect with Anthropic" or an OAuth-redirect button; only the two-radio paste-and-PUT selector (`authmode-api_key` / `authmode-oauth_token`) exists. Screenshot: `test-artifacts/paid/06-provider-config-anthropic.png`. |

## AI-agent integration (protocol §3.2.5)
Per the brief ("do NOT run agents to exhaustion... a single config/detail interaction is fine"), no agent was run to full completion via its own "Run" button this session. What was exercised instead, satisfying §3.2.5 without spending shared quota:
- **`POST /agents/test-run`** (the non-billing dry-run preview) was actually invoked 7 times across 2 sessions against 6 distinct agents. For a genuine LLM-backed agent (`storyExtraction`), it returned real, non-fabricated historical figures: `"Agent responded in 22.4s. Actual cost $0.001 · 523 tokens."` — these numbers come from the agent's own most recent completed `AgentRun` row (`actualCost`/`actualTokens`/`responseSeconds`), not a simulated/random figure, and `creditsCharged` was genuinely `0.0` every time (confirmed via network capture, no billing side-effect).
- **Fixture-fingerprint check:** `apps/api/tests/fixtures/` was grepped for the distinctive real error strings observed live in the Recent Runs table and Agent Orchestration error log ("Fabricated entities detected: ['AI-first']", "budget exhausted before any live attempt could complete", "LLM call exceeded hard budget of Xs") — **zero matches in the fixture corpus**; all three strings trace to real production code paths (`apps/api/app/agents/cover_letter_agent.py:373`, `apps/api/app/services/llm_client.py:1059`, `apps/api/app/services/llm_client.py:1170`), confirming this is genuine live agent activity from concurrent testers/production traffic, not canned fixture output being passed off as real.
- **Honest progress/error states:** the Recent Runs table shows a realistic mix of `completed` and `failed` rows for `coverLetter` with *distinct, varied* error messages per failure (budget exhaustion, timeout, malformed JSON, fabricated-entity rejection) — not a single repeated canned string, and not silently swallowed (every failed row has a populated, specific `error` field visible in the UI).
- **Quota decrement:** not directly re-measured this session (would require actually running an agent to completion, out of scope per brief); the free-plan pass already established the entitlement-gate-before-quota-work ordering is correct.
- **Audit fields:** `GET /agents/runs` rows carry real `startedAt`/`status`/`error` fields, rendered faithfully in the Recent Runs table (`api-runs-live.json`).

## Error / edge states (protocol §3.2.6)
- **Unauthenticated access:** clean redirect to `/login`, reproduced twice, zero content leak.
- **Forced backend error surfaced honestly:** the Anthropic "Test connection" round-trip is itself a real forced-error scenario (expired token) and the UI surfaced it via an honest error notice — no raw stack trace, no silent failure — though the *persistent* provider-card status is misleading (`MV-agents-004`).
- **Throttled reload:** Slow-3G CDP emulation — resolved to a correct loading-skeleton then full state, zero console errors, zero failed requests.
- **Back/forward:** clean, no crash, no stale content, both directions.

## Console / network / server-log summary
- **Console errors (uncaught):** **0** across all 3 sessions (`session1-console.json`, `session2-console.json`, `session3-console.json` — all empty arrays), including during the two Test-Run schema-validation failures (the ZodError is caught client-side, never an unhandled exception — good defensive coding, poor error-message quality).
- **Failed requests (`requestfailed`):** **0** across all 3 sessions.
- **Non-2xx API responses observed:** **0** in this pass's browser network capture (`session1-network.json`, `session2-network.json` — every `/api/agents*`, `/api/billing*`, `/api/auth*` call returned `200`). The two findings above are both **client-side contract/logic bugs on top of successful 200 responses**, not server errors — no forced-backend-error repro was needed this pass beyond the real Anthropic 401 (which is itself the correct, honest response for an expired credential, not a defect in the endpoint).
- **Server-side logs:** not independently tailed by this tester (no log-tailer agent dispatched for this pass); all evidence above is from HTTP response bodies and rendered DOM, which is sufficient to establish both findings' root cause via source citation.

## Visual conformance vs wireframe
Confirmed rendered (not just API-inferred, as the free pass had to do) — the two documented deviations from `design/screens/agents.html` are real, intentional, and positive:
1. **22 agent cards live vs 20 in the wireframe** — real backend-derived catalog; the extra cards (Job Matching, Skill Gap split out as their own cards) reflect real product surface.
2. **7 provider cards live vs 6 in the wireframe** — "Abacus Subscription (fallback)" card intentionally added to honestly surface a real serving credential path.
3. The wireframe's Test Run and Provider Config modals were fully client-side simulated mocks (`pcSimResult()`, hardcoded `actual = cost * 0.97`); the live app replaces every one of those simulated results with real `POST`/`PUT`/`DELETE` calls to the backend — a substantial, positive improvement over the mock, **except** for the Test Run schema bug documented in `MV-agents-003`, which is a regression introduced specifically because the real backend's honest null-shape wasn't matched by the frontend contract when the mock was replaced with a real call.
No other visual deviations found; layout, iconography, glass-panel styling, and copy match the wireframe's intent closely.

## UNSURE items
1. **Whether the Provider Config modal writing to the deployment-wide (not per-user) credential route is intentional architecture or a gap.** `ProviderConfigModal`'s Save/Remove call `PUT`/`DELETE /agents/providers/{id}/credential` (shared across the whole deployment), while a parallel, unused-by-this-screen `PUT`/`DELETE /agents/user/providers/{id}/credential` route exists and is what CLM-005/006 test. Two readings: (a) intentional — this is an org/admin-level settings screen where one shared credential pool is correct for a single-tenant deployment, and the per-user route serves a different (BYOK) persona/flow not surfaced on this screen; or (b) a gap — the per-user route was meant to be wired here and isn't. I did not click Save/Remove in the live modal to avoid mutating shared state for concurrent testers, so I could not observe which repository record actually changes. Escalating for an architecture-owner decision rather than guessing. Evidence: `apps/web/src/components/agents/api.ts:251-282` (`putProviderCredential`/`deleteProviderCredential` call sites) vs `apps/web/src/components/agents/ProviderConfigModal.tsx` (only ever calls those two, never the `user/providers` functions also exported from the same `api.ts`).

## NOT-TESTED (HUMAN-GATED)
- **Actually clicking "Save credential" / "Remove" in the Provider Config modal for any provider.** Reason: confirmed (see UNSURE item above) that this modal's Save/Remove mutate the **deployment-wide, shared-across-all-concurrent-testers** Anthropic/OpenRouter/etc. credential, not a per-user one. The shared-environment protocol explicitly prohibits changing account-/deployment-level state not assigned in the brief; CLM-005/006 were instead independently re-verified via the safe, per-user route.
- **Actually clicking "Run" on any real runnable agent card, or "Run All".** Reason: brief explicitly instructs "Do NOT run agents to exhaustion (quota shared); a single config/detail interaction is fine" — the non-billing Test Run dry-run (successfully exercised on 6 agents) was used instead to satisfy §3.2.5 without spending shared quota. Wiring of the real Run/Run-All calls was already confirmed correct (402-honesty under Free plan) by the earlier free-plan pass; under Pro entitlement the button is `enabled=true` and un-busy, consistent with expectation, but the actual multi-agent execution path itself was not re-run.
- **Toggling any agent's enable/disable switch, or changing any provider's active model.** Reason: both are shared, persisted, deployment-visible state (`PUT /agents/config/{key}` / `PUT /agents/providers/{id}`) that would affect concurrent testers' sessions; avoided per shared-environment rules, consistent with the free-plan pass's own restraint on the same controls.
- **Server-side log tailing.** Reason: no log-tailer agent was dispatched for this pass; all evidence is HTTP-response- and DOM-level.

## Screenshots index
All under `test-artifacts/paid/`:
- `01-agents-full-load.png` — full authenticated page load, Pro entitlement, no paywall.
- `02-tooltip-hover-jobDiscovery.png`, `03-agent-settings-panel-jobDiscovery.png` — tooltip + settings panel.
- `04-planned-cards-area.png`, `05-scroll-top.png` — planned-card gating spot check.
- `06-provider-config-anthropic.png`, `07-anthropic-verify-result.png` — Anthropic modal + live verify failure (session 1).
- `08-provider-config-bedrock.png` — unconfigured-provider modal state.
- `09-test-run-modal-default.png` → `12-test-run-storyExtraction-result.png` — Test Run modal sweep incl. the raw-JSON error (session 1).
- `13-full-page-final.png` — full page after all session-1 interactions, incl. the persistent Anthropic mismatch and the live Agent Orchestration / Recent Runs data.
- `s2-00-unauth.png` → `s2-10-throttled-final.png` — session 2 (fresh context): unauth redirect, Anthropic mismatch persisted + re-verified, Test Run raw-JSON error on 2 more agents, back/forward, throttled reload.
- `s3-01-add-provider-modal.png` — Add Provider → first-unconfigured-provider modal (session 3).

## Data hygiene confirmation
- Per-user Anthropic credential (`PUT`/`DELETE /agents/user/providers/anthropic/credential`): created 3 times this session (CLM-005a/b + CLM-006 probe), deleted after each; final state re-confirmed `[]` (empty) via `GET /agents/user/providers`.
- No deployment-wide credential was written by this tester — only read (`GET /agents/providers`) and live-verified (`POST /agents/providers/anthropic/verify`, a read-only round-trip that updates only `lastVerifiedAt`/`lastVerifyStatus` metadata on the *existing* real credential, never its secret value).
- No agent config (`enabled`, `model`) or provider default model was mutated.
- No agent was run to completion; no shared quota was spent (`creditsCharged:0.0` confirmed on every Test Run call).

## Sign-off
Tested by: screen-tester agent (Claude Agent SDK, Claude Fable 5 / claude-sonnet-5), MANUAL-VERIFICATION Stage 1, PAID-content re-test, screen `agents`.
Session window: 2026-07-17T16:52:48Z – 2026-07-17T17:00:50Z UTC, 3 independent Playwright sessions (fresh browser contexts) + direct API corroboration.
Both findings (`MV-agents-003`, `MV-agents-004`) were reproduced at least twice in independent sessions before filing, per protocol §3.2.9. Neither finding was self-closed; `status:"OPEN"` on both, pending orchestrator/fixer review. `MV-agents-001`/`002` from the free-plan pass are unchanged and not re-filed.
