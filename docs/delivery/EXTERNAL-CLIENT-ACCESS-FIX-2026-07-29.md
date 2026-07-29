# External-Client Access Fix — 2026-07-29

**Trigger:** External business clients report they cannot log in / use the app at
https://5cb5f0620.abacusai.cloud (test credential admin/admin123).

**Method:** swarm-orchestration SOP — evidence agent (browser repro) → orchestrator triage →
fixer (sonnet, test-first) → adversarial reviewer (opus, PASS) → deploy (runbook §0.3 atomic
build+restart, under lock) → independent QA closure (opus, external Playwright).

## Findings ledger

| ID | Sev | Finding | RCA | Status |
|----|-----|---------|-----|--------|
| DEF-EXT-001 | BLOCKER | /dashboard/jobs fully blank for external clients (ChunkLoadError: stale chunk `page-b25c5379…` → HTTP 400 HTML body; all page API calls ERR_ABORTED). /dashboard/resumes served HTML referencing 3 deleted assets (layout chunk + CSS → 404). | Web rebuilt 2026-07-26 23:57 with NO `aether-web` restart (recurrence of INCIDENT-2026-07-21-web-build-clobber; runbook §0.3 mandates build→immediate-restart). Running next-server (up since 19:47) served old-build pages from memory, 404'd new on-disk chunks. Prior UAT never caught external-only symptoms because it runs on-VM. | **VERIFIED-CLOSED** (QA 2026-07-29 ~01:20Z, external Playwright): 14/14 screens render, 0 console errors, jobs screen 7 real cards + interaction round-trips 200, mobile usable, server logs clean. POST-FIX-VERDICT.json. |
| DEF-EXT-002 | HIGH (latent) | `apps/web/src/lib/api/jobs.ts` baked `http://127.0.0.1:8000` into browser bundle (module-load `process.env.NEXT_PUBLIC_API_BASE_URL ?? loopback`; env unset at build). | Module bypassed the window-aware `apiBaseUrl()` in client.ts. Reviewer F1: at HEAD all prod call sites passed explicit baseUrl, so latent footgun (shipped ≠ reached); still removed. | **VERIFIED-CLOSED** @ commit 5f0af49 (branch fix/remove-fabricated-origination-activity, pushed). Test-first: apps/web/src/__tests__/jobs/job-api-base-url.test.ts (fail-before/pass-after). vitest 583/583. QA: 0 localhost calls in ~139 browser requests; 0 matches in built bundles. |
| OBS-EXT-003 | INFO | admin/admin123 resolves to the OWNER's personal account (sarkar.vikram@gmail.com, username=admin) — business clients see real personal job-search data. | Deliberate seed (2026-07-14 auth work) but data-exposure tradeoff. | FLAGGED to owner; credential left unchanged (it is what clients were given). Owner to decide on a sanitized demo account. |
| OBS-EXT-004 | NOTE | Repo tree is on branch `fix/remove-fabricated-origination-activity` (2 commits ahead of origin/main) with ~15 uncommitted WIP files from another session; the 4 WIP API files (db.py, story.py, agents.py, dedup.py) were edited AFTER the running aether-api started → the healthy prod API runs pre-WIP code. aether-api deliberately NOT restarted (would activate untested WIP). A VM reboot would activate that WIP untested. | In-flight parallel session. | FLAGGED. Web rebuild necessarily included the web-side WIP (already partially live since the 23:57 build); vitest 583/583 green on this tree. |

## Evidence
- Pre-fix external repro: `uat/reports/evidence/client-login-repro/` (REPRO-VERDICT.json — login WORKS desktop+mobile; jobs blank ×3).
- Reviewer artifact: `uat/reports/evidence/models-live/DEF-EXT-002-jobs-base-url-review.json` (PASS).
- Post-fix QA: `uat/reports/evidence/client-login-repro/post-fix/POST-FIX-VERDICT.json`.
- Post-fix gate sweep (orchestrator, 2026-07-29 ~01:05Z): 12/12 routes chunks=200, localhost refs 0.

## Deploy record
- Commit 5f0af49 on `fix/remove-fabricated-origination-activity` (fix + test only; other WIP untouched, uncommitted).
- `pnpm build` (apps/web) → `sudo systemctl restart aether-web.service` immediately after, under `flock /tmp/aether-pytest.lock`. Web healthy (200) post-restart. aether-api/worker untouched.

## Residual findings (QA 2026-07-29, pre-existing, OPEN — human/follow-up gated)

| ID | Sev | Finding | Remediation |
|----|-----|---------|-------------|
| QA-RES-002 | HIGH (business) | ENTIRE LLM pipeline degraded: OpenRouter account has insufficient credits (HTTP 402, limit_source=openrouter_credits). 1713+ failed cover_letter calls (anthropic/claude-sonnet-5) plus tailor/tailor_entailment failures across deepseek/qwen models. Board-sweep autopilot degrades gracefully (covers 0) but produces nothing. NOTE: `.env` has NO direct Anthropic key (AETHER_LLM_API_KEY absent) — OpenRouter is the ONLY live LLM path; no config flip can route around it. | Operator choice: (a) top up credits at openrouter.ai/settings/credits, (b) provide a direct Anthropic API key for .env (bare claude-* models then route direct per resolve_provider), or (c) authorize wiring the Abacus VM LLM endpoint (billing via Abacus subscription — needs explicit approval). |
| QA-RES-001 | MEDIUM | /dashboard/email shows skeletons ~11–12s (inbox API 11.9s; server logs show per-request Gmail credential refresh "401 → Attempt 1/2" twice per load — credential cache miss). Renders fully by ~t=12s. | API-side fix (cache refreshed Gmail credentials) — requires aether-api deploy, which is blocked on OBS-EXT-004 (untested WIP would activate on restart). Bundle into the follow-up run that reconciles the WIP branch. |
