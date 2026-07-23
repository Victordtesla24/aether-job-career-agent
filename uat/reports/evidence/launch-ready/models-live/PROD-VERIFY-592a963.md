# PROD-VERIFY — W-A ledger close (deploy 592a963), 2026-07-24 (Australia/Melbourne)

Deployed commit: `592a963` (main). Batched deploy per DEPLOYMENT-RUNBOOK §5:
push → pull (up to date) → pip install (no new deps) → pnpm install --frozen-lockfile
→ `pnpm build` in apps/web (✓ Compiled successfully) → IMMEDIATE stop/start of
aether-api, aether-web, aether-worker (§0.3 rule) → all three `active`.

## Phase-5 verification
- Health (vhost): `curl -s -H 'Host: 5cb5f0620.vm.internal' http://localhost/api/health` → `{"status":"ok","version":"0.2.0"}`
- Health (public): `https://5cb5f0620.abacusai.cloud/api/health` → `{"status":"ok","version":"0.2.0"}`
- `AETHER_LLM_MODE=auto` (unchanged; value read from .env by grep, not printed beyond mode key).
- .next assets: 5/5 HTML-referenced `/_next/static/*` chunks on /dashboard/jobs → HTTP 200 on public URL (incl. rebuilt `app/dashboard/jobs/page-ebb7a0ebdd42ebef.js`).

## API prod-verify (Bearer token via POST /api/auth/login, admin test account; token masked)
| # | Request (public URL) | Expected | Observed |
|---|---|---|---|
| 1 | `GET /api/jobs?source=linkedin` | 422 honest | **422** — "Source 'linkedin' is currently unavailable: no live discovery implementation (fixture-only legacy adapter). Historical rows are retained — pass include_stale=true …" |
| 2 | `GET /api/jobs?source=bogusboard` | 422 known-set | **422** — "Unknown source 'bogusboard'. Known sources: adzuna, ashby, greenhouse, indeed, lever, linkedin, remoteok, remotive, seek, wellfound, workable" |
| 3 | `GET /api/jobs?source=seek` | 422 gated | **422** — "…compliance-gated (ADR-P6-SEEK): ToS-prohibited scraping; enable only via AETHER_ENABLE_SEEK…" |
| 4 | `GET /api/jobs?source=greenhouse` | 200 | **200** — 17 rows |
| 5 | `GET /api/jobs?source=seek&include_stale=true` | 200 (history reachable) | **200** — 0 rows (no seek history for this user; endpoint honest, not rejected) |
| 6 | `GET /api/agents/scout/sources/availability` | 200 rows | **200** — 11 rows: 8 available (reason null); indeed/linkedin unavailable "no live…"; seek unavailable "compliance-gated…AETHER_ENABLE_SEEK" |
| 7 | same, unauthenticated | 401 | **401** |

## FE smoke (live browser, admin login via UI)
/dashboard/jobs renders normally (job cards, sync status, filter bar). Source
dropdown options read via DOM after render — now BACKEND-driven (hardcoded
NO_LIVE_MODE_SOURCES deleted from the shipped bundle):

```
all        disabled=false  "All sources"
greenhouse disabled=false  "Greenhouse"
lever      disabled=false  "Lever"
remotive   disabled=false  "Remotive"
remoteok   disabled=false  "RemoteOK"
seek       disabled=true   "Seek.com.au (unavailable)"
linkedin   disabled=true   "LinkedIn AU (unavailable)"
indeed     disabled=true   "Indeed AU (unavailable)"
```

## Regression
- Full pytest (flock, serialized): **1131 passed, 0 failed** (baseline 1118 + 13 new) — 27m51s.
- Full vitest: **559 passed, 0 failed / 81 files** (baseline 556 + 3 new).
- `tsc --noEmit`: clean.
- Targeted Playwright `e2e/jobs.spec.ts` against the live deployment (LOGIN_EMAIL=admin): **4/4 passed**. (Full Playwright not re-run this pass; documented baseline remains 51P/28F pre-existing.)
