# API-level claim evidence — agent-monitor screen tester

All calls made with the canonical admin/admin123 bearer token, production API
base `https://5cb5f0620.abacusai.cloud/api`. Timestamps UTC. Token used was
never logged beyond its first 8 chars (`eyJhbGci`).

## CLM-006 — garbage Anthropic credential prefix → 422 naming both formats

Timestamp: 2026-07-17T15:19:05Z (approx)

```
$ curl -X PUT .../agents/user/providers/anthropic/credential \
  -d '{"authMode":"api_key","secret":"garbage-not-a-real-prefix-12345"}'
HTTP 422
{"detail":"Anthropic credential not recognized. Console API keys start with
'sk-ant-api'. Claude Code OAuth tokens start with 'sk-ant-oat01-'. Check which
credential you are pasting."}
```
Verified non-destructive: `GET /agents/user/providers` before and after the
422 was unchanged (empty `[]` both times).

## CLM-005 — dual credential format auto-detection

Timestamp: 2026-07-17T15:19:08Z–15:19:16Z. Before-state: empty (`[]`).

1. PUT `sk-ant-api03-MV-agent-monitor-test-fake-...` with `authMode:"api_key"`
   → HTTP 200, stored row `authMode:"api_key"`, `secretHint:"…0000"`,
   `lastVerifyStatus:"failed"` (honest — fake key, real verify attempted).
2. PUT `sk-ant-oat01-MV-agent-monitor-test-fake-...` with `authMode:"oauth_token"`
   → HTTP 200, stored row `authMode:"oauth_token"` (prefix correctly re-detected
   and overwrote the mode), `lastVerifyStatus:"failed"`.
3. DELETE credential → row cleared, `GET` after confirms restored to `[]`
   (matches before-state — no residual test data left on the shared account).

## CLM-010 — genuine oat01 round-trip + billingAudit.authMode=oauth_token

Timestamp: 2026-07-17T15:19:20Z (verify call, read-only, did not touch the
stored secret):

```
$ curl -X POST .../agents/providers/anthropic/verify
HTTP 200
{"ok":true,"status":"ok","detail":"anthropic responded HTTP 200."}
```

Cross-checked against `GET /agents/runs` (read live in this session,
2026-07-17T15:20:xx Z): run id `c4b50bcdae68b33ab9f220fb7`, agent `tailor`,
status `completed`, `output.billingAudit = {"authMode":"oauth_token",
"provider":"anthropic","quotaPath":"metered_api","credentialSource":"database"}`.
Full dump: `agents-runs-full-dump.json`.

## CLM-011 / CLM-079 — removed OAuth-consent start route → 404

Timestamp: 2026-07-17T15:20:0xZ. All four combinations return 404:
```
GET  /api/agents/auth/anthropic/start   (unauth) -> 404 {"detail":"Not Found"}
POST /api/agents/auth/anthropic/start   (unauth) -> 404 {"detail":"Not Found"}
GET  /api/agents/auth/anthropic/start   (auth)   -> 404 {"detail":"Not Found"}
POST /api/agents/auth/anthropic/start   (auth)   -> 404 {"detail":"Not Found"}
```

## CLM-036 — Gmail multi-account select_account prompt

Timestamp: 2026-07-17T15:27:55Z.
```
GET /api/emails/oauth/status -> 200 {"configured":true,"connected":true,"accountCount":1}
POST /api/emails/accounts/connect -> 200
  authUrl ends with "...&access_type=offline&include_granted_scopes=true&prompt=select_account"
```

## CLM-039 — per-agent config PUT persists (sampled: orchestration/supervisor)

Timestamp: 2026-07-17T15:27:30Z. Before/after/restore cycle:
```
GET  /agents/config/orchestration -> temperature: 0.7
PUT  /agents/config/orchestration {"temperature":0.71} -> 200, temperature: 0.71
GET  /agents/config/orchestration -> temperature: 0.71 (persisted)
PUT  /agents/config/orchestration {"temperature":0.7}  -> 200, temperature: 0.7 (restored)
GET  /agents/config/orchestration -> temperature: 0.7 (confirmed restored)
```
All 8 runtime-agent catalog keys enumerated and confirmed present in
`GET /agents/config`: orchestration(supervisor), jobDiscovery(scout),
jobMatching(matcher), atsOptimization(fitScorer), resumeTailoring(tailor),
coverLetter(coverLetter), storyExtraction(storyExtractor), emailAgent(emailAgent).
Only 1 of 8 individually round-tripped live (to avoid mutating shared config
used by concurrent testers); the other 7 share the identical generic
`PUT /agents/config/{agent_key}` handler (source: `apps/api/app/routers/agents.py:1574`).

## CLM-003 / CLM-014 / CLM-046 — async 202 envelope, pipeline no-524

Timestamp: 2026-07-17T15:21:01Z. Account is free-plan
(`GET /billing/entitlement` -> `{"active_paid":false,"plan":{"id":"free"},"requiresSubscription":true}`).
The subscription paywall fires FIRST (source: `_require_active_subscription`,
`apps/api/app/routers/agents.py:940-970`) — before the async/sync branch is
ever reached:
```
POST /agents/tailor/run   {"job_id":"ce2f682aeba72f9e9b07ff083"} -> HTTP 402
POST /agents/pipeline/run {}                                     -> HTTP 402 (0.22s, NOT a 524)
POST /agents/scout/run    {"query":...,"location":...}           -> HTTP 402
{"detail":{"error":"subscription_required","message":"An active subscription is
required to use Aether. Subscribe to unlock.","upgradeUrl":"/pricing"}}
```
`GET /agents/stats.taskCount` was 160 before and 160 after all three attempts
— confirms no AgentRun row is created for a paywall-blocked call (no phantom
run, no silent partial charge).
This means the specific "HTTP 202 {job_id,status:enqueued}" response shape
could NOT be observed live in this session on this account (the code path is
gated behind subscription entitlement this tester does not have, and the
brief explicitly instructed not to trigger real agent runs). Source code at
`apps/api/app/routers/agents.py:1216-1239` confirms the 202 envelope exists
and is returned when `async_generation_enabled()` is true — this is
[INFERRED], not live-observed.

## CLM-096 — deterministic agents unmetered

Read live from `GET /agents/runs` (2026-07-17T15:20:2xZ), all completed
scout/matcher/fitScorer/supervisor runs show `costUsd: 0.0` and
`output.billingAudit.quotaPath: "none"` — confirms these run on the unmetered
path. The atomic-reserve/refund mechanism for METERED agents (tailor/
coverLetter) could not be freshly triggered (same paywall block as above);
source-confirmed only (`apps/api/app/routers/agents.py:966-990`).

## CLM-088 — $0 spend cap requires admin

`GET /api/auth/me` (2026-07-17T15:27:5xZ) confirms `"isAdmin":false` for the
admin/admin123 account — matches `canonical-login.md`'s documented finding.
No admin credential is available to this tester to set another user's
spend-cap via `POST /admin/users/{id}/spend-cap`. HUMAN-GATED / UNVERIFIABLE-FROM-UI.

## Fixture-fingerprint check (protocol §3.2.5)

Grepped `apps/api/tests/fixtures/llm/tailor/default.json` for distinctive
canned phrases ("Orchestrated the transformation of core banking platforms",
"Facilitated strategy workshops for 40+ GMs", "ePAL implementation", "Azure ML
telemetry gap analysis") against the full `GET /agents/runs` dump — NONE of
the fixture strings appear in any live run output. Real run outputs contain
distinct, evidence-grounded bullet text (e.g. "Payday Super reform program",
"PI Planning (PIs 47–48)") not present in any test fixture — no fixture
leakage into production found.

## Safe / free endpoint checks

```
POST /agents/test-run {"agent_key":"resumeTailoring"} -> 200
  {"estTokens":4200,"estCost":0.006,"actualCost":null,"actualTokens":null,
   "creditsCharged":0.0}   (taskCount unchanged before/after: 160)
GET  /agents/jobs/nonexistent-job-id-mv-test -> 404 {"detail":"Job not found"}
```
