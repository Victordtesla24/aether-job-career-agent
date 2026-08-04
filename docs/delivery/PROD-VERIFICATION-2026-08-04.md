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
