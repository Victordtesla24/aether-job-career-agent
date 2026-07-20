# TESTING-OUTCOME-REPORT — Screen: agents (Agent Catalog)

**Screen id:** agents
**Screen name:** Agents — Agent Catalog (AGENT CATALOG scope only; live-monitoring/Orchestration panel is tested separately by the "agent-monitor" tester on this same route)
**Route:** `/dashboard/agents`
**Wireframe:** `design/screens/agents.html` (20 agent cards / 6 provider cards mock — noted in BRIEF.json as "Duplicate of agent-monitor (design evolution)"; the live app's catalog has evolved past this static mock — see Visual Conformance below)
**Production:** `https://5cb5f0620.abacusai.cloud`
**Repo commit (canonical-login.md):** `53f0e084da5b460835c32d3e07d496e6e67a8616`
**Tester:** screen-tester agent role, model claude-sonnet-5 (Claude Fable 5)

## Environment / session timestamps (UTC)
- Session 1 (API probes + Playwright browser session 1): 2026-07-17T15:16:57Z – 2026-07-17T15:20:20Z
- Session 2 (Playwright browser session 2, fresh context, paywall edge/back-forward/throttle): 2026-07-17T15:23:49Z – 2026-07-17T15:24:11Z
- Verify-2 (fresh-login API re-verification pass, second independent session): 2026-07-17T15:26:00Z – 2026-07-17T15:27:35Z

## Executive summary
This screen's assigned test account (`admin`/`admin123`, canonical login) is on the **Free plan** (`GET /billing/entitlement` → `active_paid: false`, `requiresSubscription: true`). The app's global `SubscriptionGate` (`apps/web/src/components/subscription-gate.tsx`, wired in `apps/web/src/app/dashboard/layout.tsx`) replaces the ENTIRE routed content of every `/dashboard/*` page — including `/dashboard/agents` — with a "Subscribe to unlock Aether" paywall for any non-paying account. This is confirmed to be a global, pre-existing, intentional gate (GAP-P6-PAYWALL; already flagged as **MV-pricing-001, BLOCKER**, by the pricing-screen tester, because the `/pricing` page's own Free-tier card advertises "5 agent runs/month" that the same gate makes entirely unusable). It is **not** a new agents-screen-specific defect, but it **does** mean none of the Agent Catalog's cards, toggles, modals, or tooltips ever mount in the browser for this account, so protocol §3.2 points 1–3 (visual conformance, every interactive element, every form) could only be exercised at the API layer, not via live DOM interaction. This is logged as `MV-agents-001` (coverage-gap) and as an explicit NOT-TESTED list below, and cross-referenced to `MV-pricing-001` rather than duplicated as a new BLOCKER.

Despite the UI block, this screen's full backend surface (every endpoint in the assigned matrix, plus the credential-mode auto-detection and OAuth-removal claims) was exercised directly and extensively against production, with fresh evidence, reproduced twice in independent sessions. One new, independently-discovered, reproducible backend defect was found (`MV-agents-002`, `GET /agents/runs?limit=<negative>` → unhandled 500). All three assigned claims (CLM-005, CLM-006, CLM-011) are **CONFIRMED** with live evidence.

## Element inventory
Source: full read of `apps/web/src/app/dashboard/agents/page.tsx`, `AgentConfigGrid.tsx`, `ProviderConnections.tsx`, `ProviderConfigModal.tsx`, `AgentSettingsPanel.tsx`, `TestRunModal.tsx` (React source, current production build). Interaction column reflects what could be exercised: **API** = verified live via authenticated HTTP call against production; **SOURCE** = read in full, not independently renderable due to the paywall (§ Coverage gap); **LIVE-DOM** = clicked/observed in an actual rendered browser page.

| # | Element | Wireframe ref | Tested via | Result |
|---|---|---|---|---|
| 1 | "Add Provider" button | btn-add-provider-ag04 | SOURCE | Opens ProviderConfigModal for first unconfigured provider (or providers[0]) — logic read, not clickable live |
| 2 | "Test Run" button | btn-test-ag16 | API (`POST /agents/test-run`) | Confirmed: real dry-run cost preview, `creditsCharged: 0.0`, NOT subscription-gated, honest nulls for planned agents, 404 for unknown key |
| 3 | "Run All" button (pipeline) | btn-run-all-ag05 | API (`POST /agents/pipeline/run`) | Confirmed 402 `subscription_required` for the Free-plan account — honest, no fake success |
| 4 | 6 AI Provider Connection cards (wireframe) | providers-ag07 | API (`GET /agents/providers`) | Live app renders **7** provider cards, not 6 — legitimate documented addition ("Abacus Subscription (fallback)", GAP-P4-055); see Visual Conformance |
| 5 | Provider card action button (Connected·Manage / Re-authenticate / Configure keys) | btn-anthropic-ag08 etc. | SOURCE | `providerAction(status)` maps status→label/icon; opens `ProviderConfigModal` — not clickable live |
| 6 | Provider model `<select>` | (inline in provider card) | API (`GET /agents/providers`) | Model list `p.models` real per-provider (`openrouter`: 2 models; `openai`: 3; `bedrock`: `[]` -> disabled select) |
| 7 | Provider Config modal — auth-mode radios (Anthropic only: API key / Claude Code OAuth Token) | pcModes | API (`PUT .../credential`) + SOURCE | Both modes accepted server-side with correct auto-detected `authMode`; UI radios read in source, not clicked live |
| 8 | Provider Config modal — secret input + Show/Hide reveal | pcSecret / pcReveal | SOURCE | `type="password"` toggled to `"text"` client-side only; never round-trips the plaintext back from the server (`secretHint` only) |
| 9 | Provider Config modal — Save credential | (Save credential btn) | API (`PUT .../credential`) | Confirmed: both `sk-ant-api03-…` and `sk-ant-oat01-…` accepted, correct `authMode` stored, auto-verifies on save (`GAP-NEW-001`), honest `lastVerifyStatus:"failed"` for a fake secret (never fabricated `"ok"`) |
| 10 | Provider Config modal — Test connection | (Test connection btn) | API (`POST .../verify`) | Confirmed real round-trip to api.anthropic.com; distinct honest error text per auth mode ("Invalid bearer token" vs "API key is invalid.") proving the correct header is used per mode — see CLM-005 |
| 11 | Provider Config modal — Remove | (Remove btn) | API (`DELETE .../credential`) | Confirmed: removes credential, falls back to environment/none source |
| 12 | Provider Config modal — Cancel / Close (X) / Escape key | provider-config-cancel/close | SOURCE | Standard dialog dismiss handlers, read not clicked |
| 13 | 22 Agent Configuration cards (wireframe shows 20) | agent-grid-ag14 | API (`GET /agents/catalog`) | Live catalog has **22** cards; 10 backend-mapped (9 "active", 1 "error"), 12 honestly "planned" (`backend:null`, `model:"—"`, no Run/Toggle/Settings buttons per source) — see Claim/Ground-truth section |
| 14 | Agent card info-tooltip (recommendation) | has-tip | API (`GET /agents/catalog` `.tip` field) + SOURCE | Real per-agent tip text returned by API and rendered via `role="tooltip"`, hover/focus-shown; not hovered live |
| 15 | Agent card status dot + label (Active/Paused/Error/Planned) | (status dot) | API (`GET /agents/catalog` `.status`) | Confirmed 4-state honest derivation: active/paused/error/planned, matches raw registry `GET /agents` exactly for the 8 real backend names |
| 16 | Agent card enable/disable toggle | agent-toggle-{key} | API (`PUT /agents/config/{key}` `{enabled}`) | Not directly toggled live (paywalled), but PUT endpoint verified functional via other field mutations below; not exercised on `enabled` specifically to avoid disabling a shared agent for concurrent testers |
| 17 | Agent card "Run" button (runnable agents only) | agent-run-{key} | API (`POST /agents/{route}/run`) | Confirmed 402 for scout (deterministic, free); planned cards have no Run button at all per source (`agent.status === "planned" ? null : ...`) |
| 18 | Agent card Settings toggle (sliders icon) → AgentSettingsPanel | agent-settings-toggle-{key} | API (`GET/PUT /agents/config/{key}`) | Temperature (0-2, disabled for deterministic), Thinking effort (none/low/medium/high), Billing credential select — all validated live (see Forms below); not expanded live |
| 19 | Quick stats row (spend/tokens/most-active/success-rate) | quick-stats-ag15 | API (`GET /agents/stats`) | Real, non-fabricated aggregate: `spendUsd:0.1, tokensTotal:67857, mostActiveAgent:"Resume Tailoring"(119 tasks), successRate:66.9%, taskCount:160` — derived from real `AgentRun` rows, not hardcoded (source-confirmed) |
| 20 | Recent runs table | (below quick stats, app-only addition) | API (`GET /agents/runs`) | Real run rows with genuine, non-fixture LLM output content (see Agent-integration section) |
| 21 | Sidebar "Agents Idle / N agents ready" widget + "Manage Agents" button | (shared sidebar, not agents-screen-owned) | LIVE-DOM | Confirmed: "8 agents ready · none running" matches the raw 8-agent registry exactly; "Manage Agents" navigates to `/dashboard/agents` (still paywalled) |
| 22 | Unauthenticated access to `/dashboard/agents` | — | LIVE-DOM ×2 | Clean client-side redirect to `/login`, no leaked content, reproduced twice |
| 23 | The paywall itself: "View plans & subscribe" link, inline "pricing" link | — | LIVE-DOM | Both correctly `href="/pricing"`; clicked live, lands on a real, fully-rendered pricing page with 4 plan tiers |
| 24 | Back/forward browser navigation across `/dashboard` ↔ `/dashboard/agents` | — | LIVE-DOM | Clean, no crashes, no stale content, correct URL bar state both directions |
| 25 | Throttled reload (CDP Slow-3G emulation, 500kbps/400ms latency) | — | LIVE-DOM | Reload completed in 1.89s, resolved cleanly to the same honest paywall state, zero console errors, zero failed requests |
| 26 | Former OAuth-consent endpoints (`GET`/`POST /agents/auth/anthropic/start`, `GET /agents/auth/anthropic/callback`) | — | API ×2 sessions | Confirmed 404 on all three, twice — see CLM-011 |

## Findings
See `findings.json` for the exact schema rows. Summary table:

| id | severity | category | summary |
|---|---|---|---|
| MV-agents-001 | HIGH | coverage-gap | Entire Agent Catalog page content blocked by the global Free-plan SubscriptionGate for the assigned test account; blocks live DOM verification of every card/modal on this screen. Cross-ref MV-pricing-001 (BLOCKER, root cause, filed by pricing tester — not duplicated here). |
| MV-agents-002 | MEDIUM | defect | `GET /agents/runs?limit=<negative>` returns an unhandled bare-text HTTP 500 instead of a structured 422 validation error. Not reachable via the shipped UI (which never sends a negative limit). |

No BLOCKER-severity defect is filed by this tester for the Agents screen itself (the one true BLOCKER-class issue discovered during this session — the Free-tier paywall contradicting the `/pricing` page's own "5 agent runs/month" promise — is already owned and filed by the pricing-screen tester as MV-pricing-001; re-filing it here would be a duplicate).

## Claim verdicts

| Claim | Verdict | Evidence |
|---|---|---|
| **CLM-005** — `PUT /agents/providers/anthropic/credential` and `PUT /agents/user/providers/anthropic/credential` auto-detect and accept both a Console API key (`sk-ant-api03-…`, sent as `x-api-key`) and a Claude Code OAuth token (`sk-ant-oat01-…`, sent as `Authorization: Bearer` + `anthropic-beta: oauth-2025-04-20`) | **CONFIRMED** | Both formats PUT to the per-user endpoint, both returned 200 with correctly auto-detected `authMode` (`api_key` / `oauth_token` respectively, matching the pasted prefix with no client override needed). Live "Test connection" round-trip to api.anthropic.com then returned *distinctly worded* Anthropic-native errors per mode ("Invalid bearer token" for oauth_token vs "API key is invalid." for api_key) — direct proof the correct transport header is used per mode, matching the source contract at `llm_client.py:705-721` verbatim. Reproduced twice in independent login sessions. Deployment-wide real Anthropic credential (`…eAAA`) confirmed untouched throughout. Full transcript: `test-artifacts/curl-evidence-full-transcript.md`. |
| **CLM-006** — A mismatched/unrecognized Anthropic credential prefix is rejected with HTTP 422 naming both accepted formats | **CONFIRMED** | `garbage-not-a-real-prefix-123` (and a second garbage string in the fresh verify session) both PUT to the endpoint returned `422 {"detail":"Anthropic credential not recognized. Console API keys start with 'sk-ant-api'. Claude Code OAuth tokens start with 'sk-ant-oat01-'. ..."}` — names both formats verbatim. Also confirmed on the deployment-wide route (validation runs before any write, safe to probe). Reproduced twice. |
| **CLM-011** — The interactive "Connect with Anthropic" OAuth-consent flow remains removed; only paste-token entry exists | **CONFIRMED** | `GET`/`POST /agents/auth/anthropic/start` and `GET /agents/auth/anthropic/callback` all return `404 {"detail":"Not Found"}`, reproduced twice in independent sessions. Full read of `ProviderConfigModal.tsx` (the credential UI's entire source) confirms no OAuth-redirect/"Connect with Anthropic" button exists anywhere — only a two-mode paste-and-PUT radio selector. The endpoint-removal half is **live-verified**; the UI-absence half is **source-verified** only, since the SubscriptionGate paywall prevented independently re-observing the rendered modal DOM under this test account (see coverage gap). |

## AI-agent integration (protocol §3.2.5)
Per the brief, agents were **not** actually run to completion (Free-plan account; every `Run`/`Run All` call was expected to 402, and did). What was still verified with fresh evidence:
- `POST /agents/scout/run` (deterministic, free/no-LLM-cost agent) and `POST /agents/pipeline/run` ("Run All") both returned an honest `402 subscription_required` pointing at `/pricing` — no partial execution, no fake progress, no silent failure. Reproduced twice.
- `POST /agents/test-run` (the wireframe's non-billing "dry-run cost preview") is genuinely **not** subscription-gated and genuinely charges nothing (`creditsCharged: 0.0` on every response) — confirmed live for a real backend-mapped agent (resumeTailoring), a planned agent (compliance, correctly returns all-null estimate rather than a fabricated number), and an unknown key (404).
- Existing real `AgentRun` history (`GET /agents/runs`) was inspected for fixture fingerprints: the fixture corpus at `apps/api/tests/fixtures/llm/tailor/default.json` contains a fixed bullet set ("Agile Transformation & Program Management…Orchestrated the transformation of core banking platforms…"); the live production run record inspected has entirely different, distinct content ("Led end-to-end delivery for a cross-functional Agile squad — one of eight on the Payday Super reform program…") with real `costUsd`, `tokensIn/Out`, `duration_ms`, and a populated `billingAudit` block (`authMode`, `provider`, `quotaPath`, `credentialSource`) — **no fixture-fingerprint match found**, consistent with genuine (not canned) historical output.
- Audit fields: every inspected `AgentRun` row carries real `startedAt`/`completedAt`/`status`/`error`/`costUsd`/`billingAudit` — no synthetic placeholders observed.
- Quota decrement: not directly observable this session (every run attempt 402'd before reaching quota-reservation code, which is itself the honest, correct behavior per `_record_run`'s ordering — entitlement gate fires before any quota/audit work).

## Error / edge states (protocol §3.2.6)
- **Unauthenticated access:** clean client-side redirect `/dashboard/agents` → `/login`, zero content leak, reproduced twice (session 1 and session 2, independent browser contexts).
- **API-level unauthenticated/garbage-token access:** `401 {"detail":"Not authenticated"}` (no header) / `401 {"detail":"Could not validate credentials"}` (garbage JWT) — both honest, no stack trace.
- **Forced backend error:** `GET /agents/runs?limit=-5` → unhandled 500 (see MV-agents-002).
- **Throttled reload:** Slow-3G CDP emulation (500 kbps / 400 ms latency) — page resolved in 1.89 s to the same correct (paywalled) state, no hang, no partial/broken render, zero console errors.
- **Back/forward:** `/dashboard` → `/dashboard/agents` → back → forward, clean URL-bar and content state both directions, no stale DOM, no crash.

## Console / network / server-log summary
- **Console (both Playwright sessions, full page lifecycle incl. login, navigation, throttled reload, back/forward):** zero console errors, zero `pageerror` events, zero warnings captured (`test-artifacts/session1-console.json`, `session2-console.json` — both empty arrays).
- **Network (session 1 + session 2 combined):** all captured `/api/*` calls during browser sessions returned 2xx (`/api/auth/login` 200, `/api/agents` 200×~9 total across both sessions from the shared sidebar widget, `/api/billing/entitlement` 200, `/api/approvals?status=pending` 200, `/api/workspaces/settings` 200). Zero failed/aborted requests (`requestfailed` listener: empty in both sessions).
- **Direct API probing (curl, outside the browser, ~40 requests across session 1 + verify-2):** every response matched its documented/expected contract (200/401/402/404/422/200) with **one exception** — `GET /agents/runs?limit=-5` → 500 (MV-agents-002). No other 5xx observed anywhere in this session's traffic, including on the deployment-wide credential route probed for CLM-006 (422, not 500).
- **Server-side logs:** not independently tailed by this tester (no log-tailer agent was dispatched for this screen); all server-error evidence above is from the HTTP response itself (status code + body), which is sufficient to establish the defect but not to see the underlying stack trace.

## Visual conformance vs wireframe
The wireframe (`design/screens/agents.html`) is explicitly noted in `BRIEF.json` as a superseded design mock ("Duplicate of agent-monitor (design evolution)"). Two intentional, source-documented deviations were confirmed via live API data (not independently re-confirmed as *rendered* pixels, due to the paywall):
1. **22 agent cards live vs 20 in the wireframe** — the current catalog (`AGENT_CATALOG` in `agents.py`) is a real, backend-derived list, not the wireframe's static mock; the extra cards reflect real product surface, not a bug.
2. **7 provider cards live vs 6 in the wireframe** — an "Abacus Subscription (fallback)" card was deliberately added (GAP-P4-055) to honestly surface a real serving credential path that previously left runs appearing to "come from nowhere". A positive honesty fix, not a defect.

Both are noted here as observations, not filed as findings, since they are intentional and documented improvements over a stale wireframe rather than regressions.

## UNSURE items
1. **Whether the orchestrator intends a paid-tier test credential to be provisioned for catalog-screen testing.** The brief's language ("every agent card renders...", "Every card's buttons/links/config/detail modal open+work") reads as though live DOM interaction with the catalog was expected, but the only credential provided (admin/admin123, canonical login) is Free-plan and is paywalled out of ever seeing that DOM. Two interpretations: (a) this is already known/accepted — my MEMORY notes independently confirm "paywall now live" was a deliberate Phase-6 shipped feature, and the orchestrator's own root-cause finding already exists as MV-pricing-001 — in which case my source-code-level + API-level coverage (this report) is the intended substitute for direct DOM testing under a Free account; or (b) the orchestrator wants a genuinely paid test account provisioned so a fresh screen-tester pass can directly exercise every card/modal/toggle live. I did **not** attempt to grant myself a subscription (out of scope per the shared-environment rules — no plan changes without explicit brief authorization), and instead maximized API-layer + source-level coverage. Escalating for an orchestrator decision on whether (b) is warranted. Screenshots: `test-artifacts/02-agents-route-paywall-session1.png`, `04-agents-route-paywall-session2.png`.

## NOT-TESTED (HUMAN-GATED)
All items below are blocked by the same single root cause: the assigned admin/admin123 account is Free-plan, and the global SubscriptionGate never mounts the Agents page's own component tree for a Free-plan account (confirmed via network capture: `GET /agents/catalog`, `/agents/providers`, `/agents/config`, `/agents/stats` never fire on page load while gated). A paid-tier credential is required to close this gap; granting one is outside this tester's authorized scope (shared-environment rule: never change account-level plan/subscription state without explicit brief authorization).
- Live click-through of all 22 agent cards' Run/Settings-toggle/Enable-Disable buttons (exercised at the API layer instead — see Element Inventory rows 16-18).
- Live open/interact of the Provider Config modal (Anthropic auth-mode radio switch, Show/Hide reveal toggle, Save/Test/Remove/Cancel buttons) — exercised at the API layer instead (rows 7-12).
- Live open/interact of the Test Run modal (agent `<select>`, cost estimate refresh, "Run Test" dry-run button) — exercised at the API layer instead (`POST /agents/test-run`, row 2).
- Live hover/focus of the 22 agent-card recommendation tooltips and the provider cards' visual styling/colors against the wireframe pixel-for-pixel.
- Live verification that the XSS-payload model string (`<script>alert(1)</script>-éè中文-MV-agents-xsstest`, successfully PUT and persisted via the API — see curl transcript) renders inert in the actual DOM rather than executing; this is currently only source-verified (no `dangerouslySetInnerHTML` found in the rendering path) — INFERRED, not VERIFIED-WITH-FRESH-EVIDENCE at the DOM level.
- Real, cost-incurring agent execution end-to-end (explicitly out of scope per the brief for a Free-plan account; every attempt correctly and honestly 402'd instead).
- Server-side log tailing (no log-tailer agent dispatched for this screen; all server-error evidence is from HTTP response bodies only).

## Screenshot index
| # | File | Description |
|---|---|---|
| 1 | `test-artifacts/01-unauth-redirect-session1.png` | Unauthenticated `/dashboard/agents` → clean redirect to `/login` (session 1) |
| 2 | `test-artifacts/02-agents-route-paywall-session1.png` | Authenticated Free-plan `/dashboard/agents` → full-page SubscriptionGate paywall (session 1) |
| 3 | `test-artifacts/03-unauth-precise-session2.png` | Unauthenticated `/dashboard/agents` → clean redirect (session 2, precise/independent repro) |
| 4 | `test-artifacts/04-agents-route-paywall-session2.png` | Authenticated Free-plan `/dashboard/agents` → paywall (session 2, independent repro) |
| 5 | `test-artifacts/05-pricing-page-from-view-plans-link.png` | "View plans & subscribe" link on the agents-route paywall correctly navigates to a fully-rendered `/pricing` page |
| 6 | `test-artifacts/06-after-back-forward-nav.png` | State after `/dashboard` → `/dashboard/agents` → back → forward navigation cycle |
| 7 | `test-artifacts/07-throttled-reload.png` | Slow-3G throttled reload of `/dashboard/agents`, resolved cleanly |

## Additional evidence files
- `test-artifacts/curl-evidence-full-transcript.md` — full, timestamped curl transcript for every API-layer test in this report (catalog, providers, credentials, config CRUD, boundary/XSS/unicode form tests, the runs-limit defect, unauth, entitlement).
- `test-artifacts/api-agents-catalog.json`, `api-agents-raw-list.json`, `api-agents-providers-deployment-wide.json` — raw production API responses.
- `test-artifacts/api-clm005-put-apikey-response.json`, `api-clm005-put-oauth-response.json` — CLM-005 raw responses.
- `test-artifacts/api-config-jobdiscovery-before.json` — before-state for the restored `jobDiscovery` config mutation test.
- `test-artifacts/session1-console.json`, `session1-network.json`, `session1-failedrequests.json`, `session2-*` — raw Playwright event captures.
- `test-artifacts/script-session1-playwright.js`, `script-session2-playwright.js` — the exact Playwright scripts run against production (re-runnable for independent re-verification).

## Data hygiene confirmation
All test-created/mutated state was prefixed `MV-agents-` where the field allowed free text, and fully restored to its pre-test value before this report was filed:
- Per-user Anthropic credential (`PUT`/`DELETE /agents/user/providers/anthropic/credential`): created twice (once per session), deleted both times; final state re-confirmed `[]` (empty, matching the pre-test state).
- `jobDiscovery` agent config (`model` field): mutated to an XSS/unicode test string, then restored to `"deterministic"`; final state re-confirmed via GET.
- The **deployment-wide** Anthropic credential (the real, production-serving `…eAAA` credential) was never mutated — only read, both before and after all per-user tests, to confirm zero collateral impact on other concurrent testers or on live agent serving.
- No agent was actually run to completion (every attempt correctly 402'd before any execution/quota/cost was incurred).

## Sign-off
Tested by: screen-tester agent (Claude Agent SDK, Claude Fable 5 / claude-sonnet-5), MANUAL-VERIFICATION Stage 1, screen `agents`.
Session window: 2026-07-17T15:16:57Z – 2026-07-17T15:27:35Z UTC.
All findings and claim verdicts above were reproduced at least twice in independent sessions before filing, per protocol §3.2.9. No finding in this report was self-closed; `status: "OPEN"` on both filed findings pending orchestrator/fixer review.
