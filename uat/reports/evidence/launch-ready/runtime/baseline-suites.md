# Baseline Test Suites — PHASE 0 Bootstrap

**Date:** 2026-07-23 (UTC) · **Commit at run time:** `03c0c50` (main) · **Run after** worktree purge (see `cleanup/worktree-purge.md`)

## Summary

| Suite | Command | Result | Duration | Exit |
|---|---|---|---|---|
| pytest (API) | `flock /tmp/aether-pytest.lock scripts/run-tests.sh` | **1118 passed, 0 failed, 0 skipped** (54 warnings) | 1650.55s (27:30) | 0 |
| vitest (web unit) | `cd apps/web && pnpm run test` | **556 passed, 0 failed, 0 skipped** (81 files) | 108.2s | 0 |
| Playwright (e2e) | `cd apps/web && LOGIN_EMAIL=admin LOGIN_PASSWORD=admin123 pnpm e2e` | **51 passed, 28 failed, 0 skipped** (79 tests + auth setup) | 11.7m | 1 |

## pytest — 1118 passed (started ~2026-07-23T15:43Z)

- Ran under `flock` per runbook §6 (never `source .env`). Log: `/tmp/baseline-pytest.log`.
- Fully green and deterministic after the stale-worktree purge (the ML-env-001 nondeterminism source — stray /tmp worktrees — was removed first).

## vitest — 556 passed (started 2026-07-23T15:43:54Z)

- 81 test files, 556 tests, all passed. Log: `/tmp/baseline-vitest.log`.

## Playwright — two runs

### Run 1 (16:12:21Z) — FAILED at auth setup — stale `.env` credentials (ANOMALY)

- `pnpm e2e` with no env overrides: `[setup] auth.setup.ts` timed out on `waitForURL(/dashboard)`; page showed "Invalid email or password." 1 failed, 78 did not run. Log: `/tmp/baseline-playwright.log`.
- **Root cause (confirmed):** repo-root `.env` `LOGIN_EMAIL`/`LOGIN_PASSWORD` (the test/demo automation creds listed in runbook §7) are **stale** — a direct masked probe of `POST 127.0.0.1:8000/auth/login` with those values returns **401**. The login page itself works correctly.
- **Finding filed (not fixed here):** `.env` LOGIN_* values need rotation to a valid test credential. `e2e/env.ts` reads process env before `.env`, so suites can be run without editing production `.env`.

### Run 2 (16:16:07Z) — corrected creds via env override — 51 passed / 28 failed

- `LOGIN_EMAIL=admin LOGIN_PASSWORD=admin123 pnpm e2e`; auth setup passed; reused the live `next-server` on :3000 (`reuseExistingServer` — no in-tree build, per runbook §0.3 incident rule). Log: `/tmp/baseline-playwright2.log`.
- **51 passed** including: baseline-sweep-standalone (17 prod-route captures, all `errors=0 failed=0`), capture-authenticated-baselines (24/24 captures OK), cover-letters, dashboard, and others.
- **28 failed — all pre-existing baseline conditions, none introduced this phase:**

| Group | Count | Root cause (from log evidence) |
|---|---|---|
| `baseline-sweep-authed.spec.ts` | 17 | Spec hardcodes the production origin `https://5cb5f0620.abacusai.cloud` but the shared storageState (`e2e/.auth/user.json`) was captured on `http://127.0.0.1:3000` — domain mismatch → every route redirects to `/login?next=…`. |
| `ml-agents-refix.spec.ts` | 2 | `ERR_CONNECTION_REFUSED http://127.0.0.1:3012` — spec requires its own dedicated repro stack (ports 8012/3012, own `ml-agents-refix.playwright.config.ts`); not meant for the default `pnpm e2e` config. |
| `ml-fe-polish.spec.ts` | 5 | Same class: dedicated local repro stacks (8010/3010, 8012/3012) not running under default config. |
| `ml-admin-002-mobile-overflow.spec.ts` | 2 | Same class: dedicated repro stack (8010/3010) not running. |
| `gap_p7_def_b.spec.ts` | 1 | Data precondition: stored settings email is `sarkar.vikram@gmail.com`, spec expects an `@aether.local` address. |
| `baseline-manual-verification.spec.ts` | 1 | Aggregate sweep assertion `results.failed.length === 0`; sweep reported Captured 23 / Failed 12, 9299 console errors, 15274 failed requests across its route matrix (soft-fail accumulation). |

**Baseline interpretation:** pytest and vitest are fully green. The default Playwright invocation sweeps up specs that require dedicated repro stacks or prod-domain auth and is therefore red at baseline (51/79). These 28 failures + the stale LOGIN_* `.env` credentials are recorded as findings for later workstreams; nothing was modified to mask them.
