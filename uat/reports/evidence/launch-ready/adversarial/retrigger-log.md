# Adversarial Re-Trigger Log — Workstream F (2026-07-24)

Every finding closed during this launch-ready phase was re-triggered on
production (`https://5cb5f0620.abacusai.cloud`) via its original path plus at
least one variant path, fresh this run. Raw transcripts: `/tmp/wf-retrigger{1,2}.txt`
(session-transient), key outputs quoted inline.

## W-A ledger rows (all 5 closed this phase)

| ID | Original re-trigger | Variant | Verdict |
|---|---|---|---|
| ML-env-001 (shared-test-DB flakiness, environmental) | Fresh FULL pytest via `flock … scripts/run-tests.sh` this run | Stale worktrees already purged in W-D (0 remaining) | HOLDS — see fresh suite counts in G-H evidence |
| ML-adv-001 (monitor perl regex `/…/` delimiter broken) | Piped `HTTP/1.1" 500` line through the corrected `m{}` matcher → **MATCH** | Piped `ERROR` line → **MATCH**; broken `monitor-tail.sh` itself was deleted in cleanup; this run's G-G monitor uses grep -E (no delimiter issue) | HOLDS |
| ML-audit-allsources-deadcode-001 (zero-caller `all_sources()`) | `grep -rn all_sources apps/api/app` → only a comment recording the deletion; no callers, no definition | Prod `GET /api/jobs?source=linkedin` → **422** (was silent 200-with-0-jobs) | HOLDS |
| ML-audit-seek-fe-hardcode-001 (FE hardcoded seek availability) | `jobs/page.tsx` L382: availability now backend-derived (comment cites this finding); hardcode gone | Prod `GET /api/jobs?source=seek` → 422 with honest reason "compliance-gated (ADR-P6-SEEK)" | HOLDS |
| ML-prodverify-low1-allsources (source disclosure FE-only) | `GET /api/agents/scout/sources/availability` → 200, per-source `available`/`reason` incl. honest `indeed available:false "fixture-only legacy adapter"` | `source=linkedin` rejected 422 at API (no longer FE-only) | HOLDS |

## W-B features (both)

| Feature | Original re-trigger | Variant | Verdict |
|---|---|---|---|
| FEAT-B1 approvals remove/purge | `POST /api/approvals/purge-expired` → 200 `{"purged":0,"ids":[]}` (nothing expired — honest zero) | `DELETE /api/approvals/<nonexistent-id>` → **404** | HOLDS |
| FEAT-B2 stage moves | App `cf4c…` submitted→in-review→submitted round-trip 200/200, persisted; draft app `c59d…` ready→offer→ready 200/200 (legal per matrix), status verified `draft` after revert | `POST …/move {"stage":"bogus-stage"}` → **422** | HOLDS |

## W-E fixes (≥2 re-triggered)

| Fix | Re-trigger | Verdict |
|---|---|---|
| Security headers via tracked nginx vhost | `curl -I /pricing` → CSP `frame-ancestors 'self' https://*.abacus.ai`, `x-content-type-options: nosniff`, `referrer-policy: strict-origin-when-cross-origin` | HOLDS |
| Prod hygiene: FastAPI docs disabled | `GET /api/docs` → 404, `GET /api/openapi.json` → 404 | HOLDS |
| en-AU date formatting (central `format.ts`) | Covered by 4 locale vitest tests in this run's fresh vitest suite (G-H); headless route sweep of 16 routes showed 0 console errors | HOLDS |

## Condensed per-screen adversarial pass (>5 screens, data-variant probes)

Headless authed route sweep this run: **16 routes, 0 console errors, 0 5xx**
(`../runtime/final-route-sweep.json`). Data-variant API probes behind the key
screens, all fresh:

| Screen | Probe | Result |
|---|---|---|
| Approvals | `GET /api/approvals` | 200, real rows |
| Applications | `GET /api/applications` | 200, real rows |
| Analytics | `GET /api/analytics/funnel` | 200 `{jobs_found:45, applied:6, …}` |
| Agents | `GET /api/agents/config` | 200, 22 agent configs incl. honest `"model":"deterministic"` locks |
| Jobs | `GET /api/jobs?limit=5` + `?source=linkedin` (422) + `?source=seek` (422 honest reason) | 200 / honest rejections |
| Pricing (unauth) | `GET /api/billing/plans` | 200, 4 tiers |

Note: `GET /api/notifications` → 404; the FE does not call this path (0 console
errors across sweep) — checked, not user-reachable, not a finding.

**Findings from re-trigger pass: 0. All prior closures HOLD.**
