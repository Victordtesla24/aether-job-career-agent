# INCIDENT — Production DB wiped by test suite during Stage-2 deploy (2026-07-18)

**Severity:** SEV-1 (production data loss). **Status:** ACKNOWLEDGED by user — data was recoverable single-user test/demo data; user will re-signup as sarkar.vikram@gmail.com. Remediation of the ROOT CAUSE is mandatory before any further full-suite run.

## What happened
During the cluster-A/C merge+deploy, the deployer ran the full backend pytest suite. The suite's `conftest._truncate_tables()` executed `TRUNCATE TABLE ... CASCADE` against the PRODUCTION `aether` schema, wiping all real data (User/Application/Job/StoryEntry/Resume/CoverLetter/Subscription/ApprovalRequest → ~0). Confirmed live: `admin/admin123` → 401; only surviving `aether.User` rows were a conftest `fixture-user@example.com` (created 2026-07-18T00:41:18Z, inside the deploy window) and the qa-adversary's disposable account.

## Root cause (mine)
1. **Trigger (orchestrator error):** my deployer brief instructed `set -a && source ../../.env && set +a && pytest`. Sourcing the prod `.env` put the production `DATABASE_URL` (schema=aether) into the process environment.
2. **Latent defect (pre-existing, now MV-system-003):** `apps/api/tests/conftest.py` isolates tests by swapping `DATABASE_URL`→`DATABASE_URL_TEST` (`schema=aether_test`). But the `schema=` query param is a **Prisma-ism that psycopg2 ignores** — psycopg2 honors `search_path` via connection `options`, not `schema=`. `apps/api/app/db.py:46` sets `options=-csearch_path={schema}` for the APP, but `conftest._truncate_tables()` connects WITHOUT pinning search_path to `aether_test`, so under the sourced prod env its `current_schemas(false)` resolved to the role default and the TRUNCATE hit `aether` (prod). The `schema=aether_test` "safety" is therefore ineffective for the truncation path.

Net: sourcing prod `.env` + a truncation path that doesn't hard-pin the test schema = prod wipe. Either factor alone is dangerous; together they destroyed prod.

## Remediation (in progress — MV-system-003, HIGH)
1. **Hard conftest guard:** before any truncation, resolve the connection's effective database + search_path and ABORT the entire test session (pytest exit) if it targets the production `aether` schema or the prod DB host, unless an explicit `AETHER_ALLOW_PROD_TRUNCATE` override is set (never in CI/deploy). Fail closed.
2. **Pin truncation search_path:** `_truncate_tables()` must connect with `options=-csearch_path=aether_test` (not rely on `schema=`), so it can only ever truncate the test schema.
3. **Deploy runbook fix:** the authoritative full suite must run with the TEST database only — never `source` the prod `.env` into a pytest invocation. Document the safe invocation (`DATABASE_URL=$DATABASE_URL_TEST pytest`, or a dedicated `scripts/run-tests.sh` that refuses a prod DSN).
4. Regression test: a test proving the guard aborts when pointed at `aether`.

## Recovery
Single-user test data; user re-creates the account. Partial evidence exists (60 baseline screenshots, entitlement snapshots, 8-row Application backup, a few API-response captures) but is NOT a full DB and is not needed given user's decision. No platform PITR requested.

## Prevention verified before closure
No further full-suite pytest runs against any DSN whose host is the prod DB until guard #1+#2 land and are proven. Timeline of surviving rows + the deploy log are the evidence (`fixes/DEPLOY-*`, prod-verify-A-C/PRISTINE-STATE-AT-ARRIVAL.txt).
