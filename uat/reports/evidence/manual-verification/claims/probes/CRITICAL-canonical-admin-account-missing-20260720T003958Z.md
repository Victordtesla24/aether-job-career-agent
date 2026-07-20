# CRITICAL: canonical admin/admin123 login account is currently missing from production

**Probe timestamp (UTC):** 2026-07-20T00:39:58Z
**Discovered:** independently corroborated after an out-of-scope forked sub-agent (dispatched only to extract table rows from 7 TESTING-OUTCOME-REPORT.md files) self-reported this finding in its completion summary. Per this run's "trust but verify" discipline, that self-report was NOT taken at face value — it was independently re-derived below using this auditor's own authorized, safe, read-only methods before being accepted.

## Independent verification performed by this auditor

1. **Fresh canonical-login curl probe** (exact recipe from `uat/reports/evidence/manual-verification/canonical-login.md`):
   ```
   curl -s -X POST https://5cb5f0620.abacusai.cloud/api/auth/login \
     -H "Content-Type: application/json" -d '{"email":"admin","password":"admin123"}'
   ```
   Result: HTTP 401 `{"detail":"Invalid email or password"}` (2026-07-20T00:37:54Z).

2. **Read-only DB SELECT** (per DEPLOYMENT-RUNBOOK.md sanctioned access; `SELECT` only, no writes; connection string never echoed/logged; `options=-c search_path=aether` used per the runbook's own explicit warning about the `?schema=` query param not being honoured by psql/libpq on its own):
   - `SELECT count(*) FROM "User";` → **19**
   - `SELECT email, "isAdmin", "createdAt" FROM "User" WHERE email ILIKE '%admin%';` → **0 rows**
   - Full `SELECT email, "isAdmin", "createdAt" FROM "User" ORDER BY "createdAt";` → all 19 rows are disposable QA/test/fixture accounts (`fixture-user-*@example.com`, `mv-verify*@...`, `mv-vbatch*@...`, `mv-qa-*@...`), created between 2026-07-18T00:41:18Z and 2026-07-19T22:49:47Z, every single row `isAdmin=false`.

## Conclusion

The seeded `admin@aether.local` / `admin` / `admin123` account that every screen-tester in Stages 1-3 of this run used as the canonical test credential (per `canonical-login.md`) **no longer exists in the production database**. This is a genuine, currently-true, DB-confirmed fact, not a transient auth hiccup (the 401 body is the standard invalid-credential message, and the DB itself has zero matching rows).

**Likely relationship to other findings in this run:**
- The only 19 users present are exactly the disposable QA-run accounts that `uat/reports/evidence/manual-verification/TEST-DATA-CLEANUP-LEDGER.md` was tracking for eventual deletion — if that ledger's cleanup step ran against a table-wide `DELETE`/`TRUNCATE` or a mis-scoped filter instead of the intended per-account cleanup, it could explain the admin account's disappearance as collateral damage. This auditor did **not** run any DB write to test this hypothesis (out of scope, and DB writes are prohibited for this role) — recorded as a hypothesis only, not evidence.
- **CLM-019** (this ledger, REFUTED): the `aether-discovery.timer` cron has been failing at login for a *different* account (`sarkar.vikram@gmail.com`) since 2026-07-18T23:00:26Z. That account's absence was not separately re-checked here, but the same window/pattern (both a login-account casualty in the same post-2026-07-18-DB-wipe / cleanup timeframe) is suggestive of a shared root cause worth the orchestrator's attention.

## Impact

- This blocks any further live verification, gate closure, or qa-adversary re-probing that depends on `canonical-login.md`'s documented admin/admin123 recipe, until a new test account is seeded or the admin account is restored.
- It does **not** invalidate this run's own already-captured screen-tester evidence (Stages 1-3), which is timestamped and reflects what was genuinely true in production at the time each test ran — only the ability to *repeat* those tests right now.
- **Recommend the orchestrator treat this as a new, urgent, standalone finding** (distinct from any of the 101 CLM- claims) requiring operator/deployer attention before Gate G-08 (final state) or any further qa-adversary sweep can proceed. This auditor took no remediation action (out of scope: no DB writes, no re-seeding, no service restarts).

No secrets, passwords, or the database connection string were printed to any log, file, or terminal output in the course of this investigation.
