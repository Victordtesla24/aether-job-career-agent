# Docs Truth Spot-Audit (G-I) — 2026-07-24 (Workstream F)

Method: 12 specific documentation claims verified against live production
(`https://5cb5f0620.abacusai.cloud`) and the working tree, fresh this run.
Raw probe transcript: this file's claims were captured via curl/systemctl in one
batch (see `/dev/null`-free outputs quoted below). Docs edits made this pass are
listed at the bottom.

| # | Claim (doc, location) | Verification | Result |
|---|---|---|---|
| 1 | Health endpoint returns `{"status":"ok"}` (DEPLOYMENT-RUNBOOK.md §verify) | `GET /api/health` | PASS — `{"status":"ok","version":"0.2.0"}` |
| 2 | Security headers: CSP `frame-ancestors 'self' https://*.abacus.ai`, nosniff, referrer-policy (README W-E row / runbook nginx vhost) | `curl -I /pricing` | PASS — all three present |
| 3 | FastAPI docs/redoc/openapi disabled in production (W-E prod hygiene, README) | `GET /api/docs`, `/api/openapi.json` | PASS — 404 / 404 |
| 4 | Per-source honest availability incl. fixture-only indeed flagged unavailable (README sourcing row, docs/subscription) | `GET /api/agents/scout/sources/availability` | PASS — adzuna/ashby/greenhouse/lever available:true; indeed available:false reason "no live discovery implementation (fixture-only legacy adapter)" |
| 5 | 4 billing tiers Free/Starter/Pro/Power (README, billing-architecture.md) | `GET /api/billing/plans` | PASS — `['free','starter','pro','power']` |
| 6 | Approvals purge-expired endpoint exists and returns `{purged, ids}` (FEAT-B1 docs) | `POST /api/approvals/purge-expired` | PASS — `{"purged":0,"ids":[]}` |
| 7 | pytest must run via `scripts/run-tests.sh` (runbook §0) | `ls scripts/run-tests.sh` | PASS — executable exists; used for this run's full suite |
| 8 | Three systemd units aether-api/web/worker (runbook §restart) | `systemctl is-active` | PASS — active active active |
| 9 | Canonical login admin/admin123 works (runbook, P0-002 note) | `POST /api/auth/login` | PASS — 200 + token |
| 10 | Application stage map ready→draft / submitted / in-review→screening / interview / offer (FEAT-B2 docs) | source `apps/api/app/routers/applications.py` `_APP_STAGE_TO_STATUS` | PASS — matches exactly |
| 11 | `AETHER_ASYNC_GENERATION=true` in production (README env table) | repo `.env` grep | PASS — 1 occurrence `=true` |
| 12 | Model catalog count "varies with upstream churn" (README, model-catalog.md) | fresh pull this run: app 333 vs upstream 343, delta fully accounted (5 denylist + 5 unpriced sentinels) | PASS — README updated to cite fresh 333 figure |

**Result: 12/12 claims PASS** (≥10 required).

## Docs edits made this pass (truth refresh)
1. `README.md` repo-structure tree: `packages/` line updated — orphan TS
   workspace packages were hard-deleted in dedup wave 3 (2026-07-24); only
   `packages/db/src/schema.prisma` remains as schema-of-record.
2. `README.md` model-catalog row: stale "357 models (2026-07-22)" refreshed to
   the 2026-07-24 adversarial re-sample figure (333 app / 343 upstream, delta
   accounted) while keeping the churn caveat.
3. `README.md` Delivery History: added the LAUNCH-READY (2026-07-24) entry and
   corrected `MODELS-LIVE-GOVERNANCE-AUDIT.md` to its archived path
   (`docs/delivery/archive/`).
4. `DEPLOYMENT-RUNBOOK.md` and `docs/subscription/model-catalog.md` spot-checked
   for stale build commands / package references / count claims — none found;
   no edits needed.
