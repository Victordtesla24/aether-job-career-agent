# CLM-047 / CLM-070 fresh probe: admin/admin123 seed account no longer exists

**Probe timestamp (UTC):** 2026-07-20T00:18Z - 00:33Z
**Method:** POST /auth/login (repeated), server-log cross-check (`/var/log/aether/api.log`, per DEPLOYMENT-RUNBOOK.md §4), read-only `SELECT` against production `aether.User` (per DEPLOYMENT-RUNBOOK.md §7 sanctioned DB access pattern -- `?schema=` stripped, `search_path` pinned via `SET search_path`, SELECT only, no writes)

## Findings

1. `POST /api/auth/login {"email":"admin","password":"admin123"}` -> **HTTP 401 `{"detail":"Invalid email or password"}`**, reproduced 3x across ~15 minutes (00:18Z, 00:20Z, 00:33Z). This is a clean credential-rejection message, not a 429 rate-limit response (ruling out CLM-048's rate-limiter as the cause).
2. `SELECT id, email, "isAdmin", suspended, "createdAt", "updatedAt" FROM "User" WHERE email ILIKE '%admin%'` -> **0 rows**.
3. `SELECT * FROM "User" WHERE id = 'cc29a76e324fbf19f438eb8be'` (the admin account's known id, per `canonical-login.md`) -> **0 rows**. The account was not renamed; it is gone.
4. `SELECT count(*) FROM "User"` -> **19** total users, all matching the disposable `mv-*@example.com` / `mv-*@mv-*-test.dev` test-account patterns logged in `TEST-DATA-CLEANUP-LEDGER.md`'s own DELETE list -- i.e. the ONE account that ledger's binding 2026-07-20 cleanup ruling explicitly says to **KEEP** ("admin / admin seed account ... KEEP the account itself") is gone, while the accounts that ruling says to DELETE are still present.
5. `SELECT min("createdAt"), max("createdAt") FROM "User"` -> oldest remaining row is 2026-07-18T00:41:18Z (i.e. from after the 2026-07-18 prod-DB-wipe incident), newest is 2026-07-19T22:49:47Z.
6. `/var/log/aether/api.log` shows a successful `POST /auth/login 200 OK` as recently as `2026-07-19T22:49:45Z` (from IP 208.122.8.11 -- most likely the qa-adversary FINAL-PII sweep's own test-account signups, not necessarily admin) and unbroken `401 Unauthorized` on every `/auth/login` attempt since, including the recurring `127.0.0.1` health/monitoring probe that fires every ~30 minutes.

## Interpretation

The admin/admin123 seed account (id `cc29a76e324fbf19f438eb8be`) has been **deleted outright** from production sometime very recently (narrowed to a window ending at this probe's timestamp; the exact deletion moment is not pinpointable from available logs, which do not record row-level DELETE statements). This directly contradicts `TEST-DATA-CLEANUP-LEDGER.md`'s own binding "KEEP admin" ruling and is a plausible root cause (or a closely-related symptom of the same underlying issue) for **CLM-019**'s independently-discovered discovery-cron failure (`aether-discovery.service` failing at its own login step with 401 since 2026-07-18T23:00Z, per `CLM-019-discovery-cron-FRESH-REFUTATION-20260720T001509Z.md`) -- both failures are "a seeded login credential this run depends on stopped working," on two different accounts, in the same ~36-hour window.

**This blocks further live re-verification via the canonical admin/admin123 recipe** for any claim not already closed with fresh evidence pre-dating this event (e.g. re-confirming CLM-010's live oat01 round-trip, CLM-042/060/061/083/093's post-fix cover-letter re-generation, or CLM-098's post-fix terms/privacy-policy re-read while authenticated).

**No destructive action was taken.** This probe performed SELECT-only queries; no INSERT/UPDATE/DELETE was issued against the `User` table or any other production table. Recreating the admin seed account (if that is the correct remediation) is a decision for the orchestrator/deployer, not this claim-auditor role.

## Recommendation

File a new HIGH-severity finding (suggested id `MV-system-004` or similar, next available in the `system` screen namespace) covering: (a) the admin seed account's unexplained deletion, contradicting the binding cleanup ledger's own "KEEP" ruling, and (b) its likely relationship to CLM-019's discovery-cron 401s. Root-cause via the deploy/cleanup-script history is out of this role's scope (no destructive/administrative DB access authorized).
