# Production verification — 2026-08-04T11:10Z

**Target:** https://5cb5f0620.abacusai.cloud · **Deployed:** `98e7e5b` (API restarted 10:57:08Z, web rebuilt +
restarted 10:58:04Z) · **Verifier:** orchestrator, first-hand. Every row below was observed this run.

`origin/main` == local HEAD; no code commit exists after the deploy (docs only).

## Results

| # | Check | Observed | Expected |
|---|---|---|---|
| 1 | `admin` / `admin123` | **401** | 401 |
| 1 | `admin` / `admin1234` | **401** | 401 |
| 2 | `GET /agents/providers` (non-admin) | **403** | 403 |
| 2 | `PUT` / `DELETE .../anthropic/credential` | **403** | 403 |
| 2 | `POST .../anthropic/verify` | **403** | 403 |
| 2 | `POST .../anthropic/oauth/start` and `/exchange` | **403** | 403 |
| 2 | `GET /agents/providers` (anonymous) | **401** | 401, never 403 |
| 2 | `GET /agents/user/providers` (non-admin) | **200** | 200 — must not break |
| 2 | `GET /admin/users` (non-admin) | **403** | 403 |
| 3 | `POST /agents/pipeline/run {}` | **422** + *"Your profile has no target role and no location…"* | 422, no fabricated search |
| 3 | `POST /agents/scout/run {}` | **422** | 422 |
| 3 | hardcoded persona in served JS | **absent from all 11 chunks** | absent |
| 3 | `discovery-target-prompt` in served chunk | **present** | present |
| 4 | `market_demand` in `/analytics/market-pulse` | **absent** | absent |
| 4 | offer-likelihood claim | **absent** | absent |
| 5 | `/`, `/login`, `/signup`, `/dashboard/*`, `/api/health` | **200** (`/`→307) | 200 |
| 5 | chunk integrity | **4/4 on disk, 200 over HTTP** | no clobber |
| 6 | **F-03 upload at EXHAUSTED quota (5/5)** | **201**, `storyExtractionRequested=false`, `storyExtraction=null`, agent runs **6 → 6** | upload free, no run consumed |
| 7 | `ats_engine.py` on disk == HEAD, mtime 10:37 < restart 10:57 | **the R-01-fixed engine is the running engine** | live |
| 8 | 5xx + tracebacks since restart | **0** | 0 |
| 8 | discovery cron | **11:05 scout persisted 34 · 11:08 fit-scorer scored 37** | healthy |

## Method notes

- **Served chunks were fetched over HTTP**, not read from `.next`. `.next`'s mtime landed *after* the restart
  (Next writes cache post-start), so on-disk freshness would not have proven what a browser receives.
- **F-03 was verified against an exhausted quota deliberately.** A 5/5 account is the sharpest possible test:
  if upload still dispatched the metered `storyExtractor`, it would have been refused. A 201 with an unchanged
  run count is positive proof the silent spend is gone, not merely absent from a log.
- **The OpenAPI probe proved nothing and was discarded**, not reported as a failure: production serves
  `openapi.json` with 0 paths (docs disabled), so `extract_stories` being missing there was an artifact of the
  probe, not evidence about the fix.
- **The ATS engine was verified by identity, not behaviour, in production**: the file is byte-identical to
  HEAD and its mtime precedes the restart, so the process loaded it. Its *behaviour* was verified directly
  against the fixed module (fabrication reproduction: `keyword_match` 100.0 → 28.57, all 9 stack terms scored).

## Test data created by this verification

One `Resume` row for `aether-uat-1785805899201@mailinator.com` (id `cb2aba1a9ec4787b28d460d22`), 11:10Z.
That account is already inside the approved purge scope, so this adds no new cleanup debt — but the purge
census **must be re-taken after this timestamp**, not reused from 02:07Z.

## Verdict

**All seven fixes deployed today are verified live in production.** No 5xx, no regression in the credential
gate, the per-user store intact, and the discovery pipeline running normally.

Not verified here, and deliberately still open: R-03/R-04 (known ATS residuals shipped knowingly), the ≥85
ceiling re-measurement (in flight), and the full backend suite (in flight — G-N remains OPEN until it passes).

---

# CORRECTION — the deploy was INCOMPLETE when first declared (2026-08-04T12:02Z)

**I declared this deploy complete and verified while one of the four services was still running code from the
previous day.** `aether-worker` last started **2026-08-03 00:17:42 UTC** — **34 hours before** `f5d7139`,
`9780c92` and `f91cdf0`. `AETHER_ASYNC_GENERATION=true`, so **every `POST /agents/tailor/run` executes in that
worker**, not in the API I restarted. The tailoring path — the product's core journey — was still running the
old ATS engine, including the R-01 fabrication.

**Found by the GOV-021 re-measurement agent, empirically rather than by inference:** for one JD the worker
(11:05:13Z) emitted `a16z, accel, according, account, advisor, agents, ai-native, ai-powered, along, app,
applicable` — strictly alphabetical, the unmistakable ATS-KW-002 signature — while the freshly restarted API
(11:12:11Z) emitted an evidence-ranked set for the same input. Two different engines, live, at the same time.

**My error, precisely:** I built the deploy checklist around "which files would a restart newly ship" and
verified it against `aether-api` and `aether-web`. I never enumerated **which services execute which code
paths**. `aether-worker` and `aether-discovery` run from the same tree and were outside my check entirely. The
verification I ran was real, but it only ever exercised the API path, so it could not have caught this.

**Corrected:** `aether-worker` restarted **2026-08-04 12:01:38Z**, after all three ATS commits. All four units
now run post-fix code. No in-flight work was interrupted — the only running `AgentRun` was a scout job, which
executes in the API process, and every `BackgroundJob` was `completed`.

**Standing rule added:** a deploy is not complete until **every** unit that loads application code has been
restarted and its start time verified against the commit timestamps — `aether-api`, `aether-web`,
`aether-worker`, `aether-discovery`. "The API responds correctly" is not evidence about the worker.

---

# DEPLOY #2 — CRITICAL-3b + seed fix (2026-08-04T12:46Z)

**Shipped:** `90fd15d` (backend circuit honesty), `267a1a9` (the 503 banner's customer-visible half),
`19d4c65` (F-04 anti-over-correction guard now reaches its assertion).

**All FOUR units restarted this time**, per the rule added after the last deploy missed one:
`aether-api` 12:45:46Z · `aether-worker` 12:45:47Z · `aether-web` 12:46:41Z · `aether-discovery.timer` active.
Worker shutdown was clean — *24 jobs complete, 0 failed, 0 ongoing to cancel*.

| check | result |
|---|---|
| `admin`/`admin123` | **401** |
| F-01 provider routes (non-admin / anon) | **403 / 401** |
| per-user provider store | **200** |
| F-02 `pipeline/run {}` | **422** |
| F-04 `market_demand` | **0 occurrences** |
| 5xx since restart | **0** |
| new 503 branch in the SERVED chunk | **`paused —` present** |
| fallback copy | **still present — intended** |

## A verification of mine that was wrong, and how it was caught

I first grepped the served bundle for `insufficient_credits` / `failure_class`, found nothing, and nearly
recorded the web half as not deployed. **The grep was wrong, not the deploy.** The fix adds no new literal: it
calls `extractApiJsonDetail(err)` and renders the **backend's** message, so the only new marker is the template
`` `${context} paused — ${detail}` ``. That IS present in the served chunk.

The old *"wait a minute and press the button again"* copy is also still present, and that is **correct** — it
is now the fallback for a synthetic client-side error or a 503 carrying no JSON detail (a proxy/gateway page),
not the blanket override it used to be.

**Lesson, and it is the same one as R-01 and GOV-028:** grep for what the change actually introduces, not for
what you imagine it introduces. A negative result from a wrong probe looks identical to a failed deploy.
