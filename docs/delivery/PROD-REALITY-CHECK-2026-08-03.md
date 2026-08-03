# Production reality check — 2026-08-03 ~11:30Z

Orchestrator-gathered, first-hand. Every line below is [VERIFIED] unless tagged otherwise.

## Healthy

| Signal | Evidence |
|---|---|
| API 5xx, last 24h | **0** (`journalctl -u aether-api --since "24 hours ago"` grepped on the quoted-request field, not a bare timestamp — see ORCH-CORR-010) |
| Agent runs, last 10h | **0 failed / ~110 completed**, sustained hourly |
| Job sourcing | discovery timer `*:00/30`, persisting 18–26 new jobs per cycle, 8 sources `ok` |
| Job corpus | 2,241 rows, **2,225 seen in the last 7 days** |
| Authenticated API surface | `/jobs` `/applications` `/analytics/conversion` `/resumes` `/stories` `/interviews` `/billing/subscription` all **200** |
| G-C (interview conversion) | **already live** — `interview_conversion_rate` present in `.next/static/chunks` and `.next/server/app/dashboard/analytics/page.js`; built 10:23Z, web restarted 10:33Z |
| Dummy/test data | none. All 4 "test"-matching Job rows are real employer postings (Canonical ×2, PEXA, Skilled Jobs Australia) |

## Corrected reading — do not repeat the raw aggregate

`AgentRun` over 48h is 665 failed / 434 completed, which reads as a 60% failure rate.
It is not. The failures are a **burst confined to 08-02 23:00 → 08-03 01:00** (20, 60, 11),
and **660 of the 665 are the `tailor` agent** — the hot-loop against an upstream returning
HTTP 402, fixed by commit 0b6102d. Every hour since 08-03 02:00 shows **zero** failures.
Quoting the 48h aggregate as current health would be false.

## Open

1. **No account holds admin.** `SELECT count(*) FROM "User" WHERE "isAdmin"` = **0**;
   `/admin/users` returns 403 "Admin privileges required". Cause: the §14.7 startup rotation
   revoked isAdmin from the `AETHER_ADMIN_EMAIL` row because the configured
   `AETHER_ADMIN_PASSWORD_HASH` hashes a password on the 14-entry weak denylist. The only fix
   is setting a strong hash — **exactly the rotation the user placed on hold**. USER-GATED.
2. **First real external user.** `abhikadam28@gmail.com`, signed up 2026-08-03, free plan,
   quota row 5 runs / $1.00 cap, **0 used, zero AgentRun rows**. Under audit.
3. `LOGIN_PASSWORD` in `.env` is **stale** — it fails auth. The owner's working credential is
   `AETHER_CRON_PASSWORD`. Both are listed for the same rotation; note the drift before rotating.
4. Two accounts total; owner on `pro` (66/100 runs, $0.80/$15.00 spend).
