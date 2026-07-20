# MV-agents — curl evidence transcript

Production base: `https://5cb5f0620.abacusai.cloud/api`
Account: `admin` / `admin123` (Free plan, `active_paid: false`)
All commands run live against production during this test session (session 1: ~2026-07-17T15:16:57Z–15:20Z UTC; verify-2 fresh session: ~2026-07-17T15:26:00Z–15:27Z UTC).
Secrets below are test-only fake values, prefixed `MV-agents-`/`MVAGENTS` where the field allowed it; the last-4 hint `secretHint` is the only fragment ever returned by the server (never a full secret).

## Login (canonical, session 1)
```
POST /auth/login {"email":"admin","password":"admin123"} -> 200, access_token (JWT, prefix eyJhbGciOiJI...)
```

## Catalog / registry ground truth (GET /agents/catalog) — session 1, 2026-07-17T15:17:0xZ
Full response saved: `api-agents-catalog.json`. Summary:
```
counts: {'total': 22, 'active': 9, 'paused': 0, 'error': 1, 'planned': 12}
```
22 catalog cards total. 10 are backend-mapped (jobDiscovery/scout, resumeTailoring/tailor, coverLetter/coverLetter,
atsOptimization/fitScorer, matchScoring/fitScorer, jobMatching/matcher, skillGap/fitScorer, emailAgent/emailAgent,
storyExtraction/storyExtractor, orchestration/supervisor) → 9 show "active", 1 (resumeTailoring/tailor) shows "error"
(its last run at 11:24:47Z genuinely failed — matches `GET /agents` raw registry `tailor: status=failed`). The other
12 catalog cards (compliance, submission, salaryIntelligence, interviewPrep, companyResearch, recruiterOutreach,
marketTrends, scheduling, sentimentAnalysis, reference, learningFeedback, notification) have `backend: null` and are
honestly labelled `"status": "planned"`, `"model": "—"`, `"runnable": false`.

## Raw 8-agent backend registry (GET /agents) — matches screens/agents-registry.json ground truth exactly
Full response saved: `api-agents-raw-list.json`. 8 entries: supervisor/scout/matcher/fitScorer/tailor/coverLetter/
storyExtractor/emailAgent — statuses completed×5, failed×1 (tailor), idle×1 (emailAgent, though the catalog view
separately shows emailAgent "active" because it has enabled=true and no *failed* run — this is a legitimate design
choice: "active" in the catalog means "implemented and enabled", not "currently mid-run"; live/mid-run state is the
agent-monitor tester's Orchestration-panel scope, not duplicated here).

## Providers — deployment-wide (GET /agents/providers) — 7 real provider cards (wireframe shows only 6)
Full response saved: `api-agents-providers-deployment-wide.json`. anthropic=connected(database, real oauth_token
credential, hint …eAAA — THIS WAS NEVER TOUCHED BY ANY TEST BELOW), openrouter=connected(environment),
openai/gemini/bedrock/groq=unconfigured(none), abacus=connected(environment, standby fallback). The 7th card
("Abacus Subscription (fallback)") is a deliberate, source-documented addition (GAP-P4-055) not present in the
static wireframe — an honesty improvement (surfaces the real last-resort credential path), not a defect.

## CLM-006 — garbage-prefix Anthropic credential -> 422 naming both formats
Session 1:
```
PUT /agents/user/providers/anthropic/credential {"authMode":"api_key","secret":"garbage-not-a-real-prefix-123"}
-> 422 {"detail":"Anthropic credential not recognized. Console API keys start with 'sk-ant-api'. Claude Code OAuth
        tokens start with 'sk-ant-oat01-'. Check which credential you are pasting."}
PUT /agents/providers/anthropic/credential (deployment-wide, same garbage secret) -> identical 422 (validation runs
        before any write, so this was safe to probe on the deployment-wide route too — no state changed).
```
Verify-2 (fresh login, fresh token, 2026-07-17T15:26:0xZ):
```
PUT /agents/user/providers/anthropic/credential {"authMode":"api_key","secret":"totally-not-anthropic-format"}
-> 422, identical message.
```
**Verdict: CONFIRMED, reproduced twice in independent sessions.**

## CLM-005 — both credential formats accepted, correct authMode auto-detected, correct header used
Session 1 (state before: `GET /agents/user/providers` -> `[]`, i.e. admin had no per-user Anthropic credential):
```
PUT .../user/providers/anthropic/credential {"authMode":"api_key","secret":"sk-ant-api03-MVAGENTSTEST00...(70 chars)"}
-> 200 {"authMode":"api_key","secretHint":"…0000","lastVerifyStatus":"failed", ...}   (saved as api-clm005-put-apikey-response.json)

PUT .../user/providers/anthropic/credential {"authMode":"oauth_token","secret":"sk-ant-oat01-MVAGENTSTEST00...(70 chars)"}
-> 200 {"authMode":"oauth_token","secretHint":"…0000","lastVerifyStatus":"failed", ...} (saved as api-clm005-put-oauth-response.json)
```
Both auto-detected correctly from the secret prefix (no client-declared authMode override needed/possible — the
server derives it authoritatively per `_detect_anthropic_auth_mode`).

**Live proof of the CORRECT auth header per mode** — `POST /agents/user/providers/anthropic/verify` was called once
per mode (a genuine round-trip to api.anthropic.com with the fake secret); Anthropic's own error text differs
distinctly by which header carried the credential:
```
oauth_token mode -> {"ok":false,"detail":"anthropic returned HTTP 401: {...\"message\":\"Invalid bearer token\"...}"}
   (Anthropic's own wording for a bad "Authorization: Bearer ..." + anthropic-beta:oauth-2025-04-20 header — proves
    the oauth_token path used Bearer, not x-api-key.)
api_key mode     -> {"ok":false,"detail":"anthropic returned HTTP 401: {...\"message\":\"API key is invalid.\"...}"}
   (Anthropic's own wording for a bad "x-api-key" header — proves the api_key path used x-api-key, not Bearer.)
```
This matches the source-code contract at `apps/api/app/services/llm_client.py:705-721` verbatim (comment: "x-api-key
returns 401 for an oat token; Bearer+beta returns 200").

Cleanup: `DELETE /agents/user/providers/anthropic/credential` -> 200, confirmed `GET .../user/providers` -> `[]` again
(state restored to pre-test empty array — no residual test credential left on the shared admin account).

Verify-2 (fresh login, fresh token): identical PUT/PUT/DELETE sequence repeated -> identical 200/200/200 results,
state confirmed empty afterward. **Verdict: CONFIRMED, reproduced twice in independent sessions. Deployment-wide
Anthropic credential (`…eAAA`) confirmed UNCHANGED after all tests (`api-agents-providers-deployment-wide.json`
re-checked post-test).**

## CLM-011 — interactive OAuth-consent flow removed; only paste-token entry exists
```
GET  /agents/auth/anthropic/start     -> 404 {"detail":"Not Found"}
POST /agents/auth/anthropic/start     -> 404 {"detail":"Not Found"}
GET  /agents/auth/anthropic/callback  -> 404 {"detail":"Not Found"}
```
Reproduced identically in verify-2 fresh session. Source review of `apps/web/src/components/agents/
ProviderConfigModal.tsx` (full file read) confirms no "Connect with Anthropic" / OAuth-redirect button exists
anywhere in the credential UI — only a two-radio "Authentication mode" selector (API key / Claude Code OAuth Token)
that both submit via paste-and-PUT, never a redirect flow. (This UI-absence half is source-verified; it could not
be re-confirmed on the live rendered DOM because the SubscriptionGate paywall blocks this account from ever
mounting the Agents page — see coverage-gap discussion below.)
**Verdict: CONFIRMED for the endpoint-removal half (live, twice); UI-absence half INFERRED from full source read
(not independently re-observable live under this account).**

## Free-plan "Run" behaviour (brief: "Do NOT actually run agents (free-plan 402...)")
```
POST /agents/scout/run {"query":"MV-agents-test","location":"Australia"} -> 402
  {"detail":{"error":"subscription_required","message":"An active subscription is required to use Aether.
   Subscribe to unlock.","upgradeUrl":"/pricing"}}
POST /agents/pipeline/run {} (the "Run All" button's endpoint) -> identical 402 subscription_required
```
Reproduced identically in verify-2 fresh session. This 402 is honest (no fake success, no partial execution) and
is the SAME root-cause paywall already filed as **MV-pricing-001 (BLOCKER)** by the pricing-screen tester — see
"Coverage gap" section of the report. Not re-filed here as a duplicate defect; cross-referenced only.

## POST /agents/test-run (dry-run cost preview — NOT subscription-gated, never charges)
```
{"agent_key":"resumeTailoring"} -> 200 {"model":"deepseek/deepseek-v4-pro","estTokens":4200,"estCost":0.006,
    "actualCost":null,"actualTokens":null,"responseSeconds":null,"creditsCharged":0.0}
    (actualCost/actualTokens correctly null because resumeTailoring's last run STATUS=failed, not completed —
     matches source: only a completed run's real figures are surfaced.)
{"agent_key":"compliance"}      -> 200 {"model":null,"estTokens":null,"estCost":null,"creditsCharged":0.0}
    (planned/no-backend agent — honestly returns nulls, not a fabricated estimate.)
{"agent_key":"bogus999"}        -> 404 {"detail":"Unknown agent 'bogus999'"}
{"agent_key": <missing>}        -> 422 (Field required)
```

## GET /agents/config/{key} and PUT /agents/config/{key} — form validation (protocol §3.2.3)
Target: `jobDiscovery` (a deterministic, free/no-LLM-cost catalog agent — chosen to minimise any shared-account
side effect). Before-state captured, all mutations restored afterward (`api-config-jobdiscovery-before.json`).
```
Before: {"enabled":true,"model":"deterministic","temperature":0.7,"thinkingEffort":"medium", ...}
PUT {"temperature": 3.5}   -> 422 "Input should be less than or equal to 2"
PUT {"temperature": -1}    -> 422 "Input should be greater than or equal to 0"
PUT {"thinkingEffort":"bogus"} -> 422 "String should match pattern '^(none|low|medium|high)$'"
PUT {"model":"<script>alert(1)</script>-éè中文-MV-agents-xsstest"} -> 200, persisted verbatim on GET re-read
    (round-trip confirmed; storage layer correctly does NOT sanitise — sanitisation is React's job at render time,
     and source review of AgentConfigGrid.tsx/AgentSettingsPanel.tsx confirms the model string is only ever
     rendered as a React text child, never via dangerouslySetInnerHTML, so this cannot execute as script in the
     browser — INFERRED from source, not independently re-observable live due to the paywall.)
RESTORE: PUT {"model":"deterministic"} -> 200, confirmed back to original.
PUT {} (empty body, no fields)  -> 200, no-op merge over existing (unchanged) — correct partial-update semantics.
GET /agents/config/notARealAgentKeyXYZ -> 404 "Unknown agent 'notARealAgentKeyXYZ'"
```

## Credential-field form validation (empty / whitespace / missing / unknown provider)
```
PUT .../anthropic/credential {"authMode":"api_key","secret":""}    -> 422 "String should have at least 1 character"
PUT .../anthropic/credential {"authMode":"api_key","secret":"   "} -> 422 (whitespace does not match either Anthropic
      prefix, so it correctly falls through to the same "not recognized" 422 as any other garbage string)
PUT .../anthropic/credential {"secret":"sk-ant-api03-x"} (authMode omitted) -> 422 "Field required"
PUT .../notarealprovider/credential {...}  -> 404 "Provider 'notarealprovider' does not support stored credentials."
PUT .../anthropic/credential {..., "baseUrl":"<script>alert(1)</script>"} -> 200, stored verbatim (baseUrl is never
      rendered anywhere in ProviderConfigModal.tsx per source review — no render-time XSS surface found; field also
      has no URL-format validation, a minor hardening gap, not currently exploitable). Cleaned up after (DELETE).
Final state re-confirmed empty: GET /agents/user/providers -> []
```

## Defect found: GET /agents/runs?limit=<negative> -> HTTP 500 (uncaught)
```
GET /agents/runs?limit=-5   -> HTTP 500, plain text body "Internal Server Error" (not JSON), content-length 21
                                (reproduced twice, identical, cf-ray a1ca44913c2cda91-PDX / a1ca4492bc63b876-PDX)
GET /agents/runs?limit=0    -> HTTP 200, []                         (correct)
GET /agents/runs?limit=abc  -> HTTP 422, structured Pydantic error   (correct)
GET /agents/runs?limit=99999-> HTTP 200, 160 rows (silently clamped to real row count, no crash)
```
Root cause (source, `apps/api/app/routers/agents.py:1123-1125` + `apps/api/app/repositories/agent_run.py:76-84`):
`list_runs(limit: int = 50)` passes `min(limit, 200)` straight into `... LIMIT %s` with NO lower bound — `min(-5,
200) == -5`, and `LIMIT -5` is invalid to PostgreSQL, raising an unhandled exception that FastAPI's default handler
turns into a bare-text 500 (not a JSON error, no `detail` field, would be surfaced to a UI caller as an unsurfaced/
uncaught failure if the frontend ever sent a negative limit — it currently does not, so this is not user-reachable
via the shipped UI, but it is a real, live, reproducible server defect on an endpoint in this screen's matrix).

## Unauthenticated access to the API layer
```
GET /agents/catalog (no Authorization header) -> 401 {"detail":"Not authenticated"}
GET /agents         (no Authorization header) -> 401 {"detail":"Not authenticated"}
GET /agents/catalog (garbage Bearer token)     -> 401 {"detail":"Could not validate credentials"}
```

## Subscription entitlement (root of the coverage gap — see report body)
```
GET /billing/entitlement -> 200 {"active_paid":false,"plan":{"id":"free","status":"active"},
                                  "requiresSubscription":true}
```
