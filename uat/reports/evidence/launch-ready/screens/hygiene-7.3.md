# W-E §7.3 — Performance & hygiene floor (production)

Audited: 2026-07-24 (AEST) · prod `https://5cb5f0620.abacusai.cloud`

## Lighthouse (authenticated, headless Chrome via remote-debug port, 5 heaviest routes)

Threshold: performance / accessibility / best-practices ≥ 90 each.

### Pre-fix (baseline, this sweep's findings)

| Route | Perf | A11y | Best-practices | Notes |
|---|---|---|---|---|
| /dashboard | 98 | 100 | 100 | PASS |
| /dashboard/jobs | 82 ✗ | 100 | 100 | LCP 4.0s, CLS 0.114 |
| /dashboard/agents | 84 ✗ | 100 | 100 | LCP 4.0s, TBT 160ms |
| /dashboard/analytics | 64 ✗ | 96 | 100 | CLS 0.668 (summary grid inserted post-fetch), LCP 4.0s |
| /dashboard/applications | 86 ✗ | 100 | 100 | LCP 3.9s |

### Post-fix (re-measured after the W-E quality wave deploy)

_See table appended below after deploy._

## API p95 snapshot (timed curl, n=20 per endpoint, authenticated)

| Endpoint | p50 (ms) | p95 (ms) | max (ms) | codes |
|---|---|---|---|---|
| /auth/me | 220 | 238 | 255 | 200 |
| /jobs | 263 | 288 | 296 | 200 |
| /applications | 233 | 249 | 259 | 200 |
| /resumes | 298 | 375 | 418 | 200 |
| /stories | 238 | 248 | 249 | 200 |
| /agents | 231 | 251 | 257 | 200 |
| /agents/runs | 240 | 265 | 279 | 200 |
| /analytics/market-pulse | 323 | 358 | 361 | 200 |
| /workspaces/career-data | 226 | 245 | 245 | 200 |
| /approvals | 222 | 241 | 249 | 200 |

Verdict: **PASS** — all endpoints p95 ≤ 375 ms, zero non-200s across 200 timed calls.
(Latency includes public TLS round-trip through Cloudflare + envoy.)

## Security headers & debug surfaces

| Check | Pre-fix | Post-fix action |
|---|---|---|
| `Content-Security-Policy: frame-ancestors 'self' https://*.abacus.ai` | **MISSING** ✗ | Added in tracked nginx vhost `deploy/5cb5f0620.conf` (symlinked to /etc/nginx/conf.d), plus `X-Content-Type-Options: nosniff`, `Referrer-Policy` |
| Conflicting `X-Frame-Options` | absent ✓ | still absent (by design) |
| Source maps (`/_next/static/chunks/*.js.map`) | 404 ✓ | n/a |
| `GET /api/docs` | **200** ✗ (interactive Swagger UI public) | `create_app()` now disables `/docs`, `/redoc`, `/openapi.json` when `AETHER_ENV=production` (test: `apps/api/tests/test_we_prod_docs_disabled.py`) |
| `GET /api/redoc` / `GET /api/openapi.json` | **200** ✗ | same fix |

Raw data: p95 script `/tmp/p95.py` output archived at
`s3://abacusai-apps-e154d00a983f92d71946ca64-us-west-2/49362/launch-ready-evidence/we-screens/` (`p95-results.json`),
Lighthouse JSON reports at the same S3 prefix (`lh/`).
