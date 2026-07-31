# Baseline Suite Run — Phase 0 Step 6 (GOLD-MASTER-V2)

**Run window:** 2026-07-30 22:47Z – 23:55Z UTC
**Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`, branch `main`, commit `297946d7dea3d01207586a4c9ef4a8e8bb91f6ef`
**Evidence root:** `uat/reports/evidence/gold-master-v2/phase0/`, raw logs in `logs/`
**Purpose:** establish the 0-regression reference line for GOLD-MASTER-V2. All numbers below are [VERIFIED] against logs captured in this run unless tagged otherwise.

## Summary

| Suite | Command | Exit | Passed | Failed | Skipped | Total | Duration | Authoritative log |
|---|---|---|---|---|---|---|---|---|
| Backend pytest | `scripts/run-tests.sh -q` (via `flock /tmp/aether-pytest.lock`) | **0** | **1885** | **0** | **0** | 1885 | 2134.28s (35m 34s) | `logs/pytest-baseline-FINAL-1885-passed.log` |
| Frontend vitest | `pnpm --dir apps/web test` (= `vitest run`) | **0** | **626** | **0** | **0** | 626 (87 files) | 168s | `logs/vitest-baseline.log` |
| Playwright e2e | `pnpm exec playwright test --reporter=list` (see credential caveat, §3) | **1** | **40** | **12** | **0** | 52 | 275s (4.6m) | `logs/playwright-baseline.log` |

**Skipped-test count: 0 across all three suites.** No skip-inflation observed anywhere in this baseline.

**Bottom line: pytest and vitest are a clean 0-regression baseline (2511/2511 passing, 0 skipped). Playwright has 12 real failures out of 52 — see §3c for root-causing; 9 of the 12 are pre-existing test-harness/environment issues (hardcoded wrong ports, one missing fixture path) unrelated to application code, 1 is a stale fixture-data assumption, and 1 (mobile approvals-page layout) is the one failure that plausibly reflects the live application and merits a follow-up look.**

---

## 0. Evidence-integrity note: concurrent duplicate task dispatch [VERIFIED]

Before reading §1, note that **this exact Phase 0 Step 6 task was independently dispatched to at least three concurrent Tester-role processes** sharing this VM and this session's scratchpad UUID (`/tmp/claude-2000/.../0651e783-3ef0-4bfa-a33d-267c8becdc79/`), all targeting the same evidence paths. This was discovered mid-run via `ps aux`/`lsof` process forensics (not asserted from memory) and is recorded here because it materially affected how the pytest number below was obtained, and because a stray/inflated skip or failure count from a **half-finished** competing run would otherwise be indistinguishable from a real regression.

Sequence of events (all timestamps UTC, 2026-07-30):
1. **22:50** — this session starts `scripts/run-tests.sh -q --durations=15` in a `nohup`-detached background script (`run_pytest_bg.sh`), writing to `logs/pytest-baseline.log`.
2. **22:52** — a second, independent process (PID 253390/253411) starts an equivalent `flock ... -c "scripts/run-tests.sh -q"` invocation targeting the **same** `logs/pytest-baseline.log` path. Bash's `>` redirection truncates the target file at shell-fork time — *before* `flock` actually acquires the lock — so this second process's mere startup silently NUL-corrupted the first ~144 bytes of this run's in-progress log (verified via `od -c`). `flock` itself correctly serialized the two processes' actual pytest/DB execution (only one `python3 -m pytest` process was ever alive at a time), so DB-level correctness was never at risk — only the shared log file's header bytes. This second process died on its own (most likely its own Bash tool's default timeout) by 22:58Z, before ever acquiring the lock.
3. **22:58** — this session finds a `BASELINE-SUITES.md` already on disk, authored by that concurrent session, documenting the same collision from its own vantage point and correctly declining to report a pytest number (its own queued invocation never got the lock in its observation window).
4. **~23:07** — *this session's own* first pytest invocation (PID 251805, holding the lock, at 42% / ~792 of 1885 tests, no failures observed in the dot-stream) **disappeared without a trace** — no exit code, no summary, the entire process tree (251801/251804/251805) gone from `ps aux`. `dmesg`/`journalctl -k` show no OOM-kill evidence and the box had 1.4Gi free / 4.6Gi available at the time, so this was most likely an external `kill`/`pkill` by another concurrent session doing its own cleanup of what looked like an orphaned process — not a code-triggered crash (pytest never printed a traceback or summary; a clean crash would have left one). This session's own partial log was preserved as `logs/pytest-baseline-MINE-safe-snapshot.log` for the record, but is **not used** for any number in this report.
5. **23:06–23:17** — a third concurrent process took the freed lock, wrote to a properly unique, collision-proof filename (`pytest-baseline-clean-<timestamp>.log`) this time, but was itself killed at 19% (its wrapping Bash tool call was not detached and hit a timeout), and its quarantined remnant is filed under `logs/quarantine-collided/pytest-baseline-clean-20260730T230650Z-INCOMPLETE-toolcap.log`.
6. **23:17:14** — the same (or another) concurrent session retried once more, this time running for the full duration uninterrupted: `logs/pytest-baseline-clean-20260730T231714Z.log`. This is the run that finished cleanly.
7. **23:22** — this session, unaware yet whether attempt #6 would also die, queued a properly `nohup`-detached hedge attempt (`run_pytest_bg_v2.sh` → `logs/pytest-baseline-TESTER-v2-final.log`) behind the held lock, as a self-healing fallback.
8. **23:54:32** — attempt #6 finished: **`1885 passed, 74 warnings in 2134.28s (0:35:34)`, `EXIT_CODE=0`, zero `failed`/`skipped` in the summary line.** Immediately copied to a permanent, unambiguous filename: `logs/pytest-baseline-FINAL-1885-passed.log`.
9. **23:55** — this session's own hedge (step 7) had just acquired the freed lock and begun a redundant re-run; it was deliberately `SIGTERM`'d by this session (exit 143, logged honestly in `pytest-baseline-TESTER-v2-final.log`) to release the lock promptly for the next queued waiter (a fourth concurrent process running a single targeted test, `test_blocker001_admin_overpermission.py`, unrelated to this task) rather than let a pointless duplicate run monopolize the shared DB for another 35 minutes.

**Conclusion: `logs/pytest-baseline-FINAL-1885-passed.log` (= `pytest-baseline-clean-20260730T231714Z.log`) is the one and only run of this suite in this window that ran start-to-finish, uninterrupted, to its own natural summary line. Its numbers are used below.** No pytest run in this window — by this session or any concurrent one — produced a single failure or a single skip.

---

## 1. Backend pytest — `scripts/run-tests.sh`

**Command:** `scripts/run-tests.sh -q`, wrapped in `flock /tmp/aether-pytest.lock -c "..."` per the Tester role charter. Never sourced the repo-root `.env`.

**Safety proof** — the resolved `DATABASE_URL_TEST`'s schema param, checked directly against the raw `.env` (never sourced) [VERIFIED]:
```
DATABASE_URL_TEST=postgresql://role_fdc4e11da:***@db-fdc4e11da.db005.hosteddb.reai.io:5432/fdc4e11da?schema=aether_test&connect_timeout=15
```
`schema=aether_test`, exactly as `scripts/run-tests.sh` requires (it refuses to run — exit 1 — on any other value); confirmed printed by the script itself at the top of `pytest-baseline-FINAL-1885-passed.log`: `[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed.`

**Collection:** `python3 -m pytest tests/ --collect-only -q` → **1885 tests collected** [VERIFIED].

**Result** [VERIFIED, `logs/pytest-baseline-FINAL-1885-passed.log`, final lines]:
```
1885 passed, 74 warnings in 2134.28s (0:35:34)
EXIT_CODE=0
```
**1885/1885 passed. 0 failed. 0 skipped (`grep -i skip` on the full log returns nothing). Exit code 0.** The 74 warnings are all non-fatal `DeprecationWarning`s (e.g. `HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT` rename in Starlette/FastAPI, a `swigvarlink`/`SwigPyObject` `__module__` warning from a native dependency) — console noise, not test failures.

**Skip-inflation check:** 3 files under `apps/api/tests/` contain `pytest.mark.skip`/`pytest.skip(` calls (conditional skips in `test_mv_no_fixture_content_in_prod_data.py`, `test_agents_screen.py`), but none fired in this run — the suite's own summary line has no `skipped` count at all, confirming 0.

**How this number was obtained:** see §0 — this was not this session's own invocation; it is the one fully-uninterrupted run among several concurrent/duplicate attempts in this window (including two by this session, both non-terminating for reasons documented in §0), copied to `logs/pytest-baseline-FINAL-1885-passed.log` the moment it completed.

---

## 2. Frontend vitest — `pnpm --dir apps/web test`

**Command discovered:** `apps/web/package.json` → `"test": "vitest run"`; confirmed against `.github/workflows/ci.yml`'s `web` job (`pnpm --dir apps/web test`).

**Result** [VERIFIED, `logs/vitest-baseline.log`]:
```
 Test Files  87 passed (87)
      Tests  626 passed (626)
   Start at  22:50:52
   Duration  166.31s (transform 4.06s, setup 0ms, collect 31.50s, tests 14.16s, environment 79.64s, prepare 15.94s)
EXIT_CODE=0
DURATION_SECONDS=168
```
**626/626 passed. 0 failed. 0 skipped. Exit code 0.** Clean. (Benign React `act(...)` console warnings from `Topbar` appear in the log — these are console noise, not failures; every listed suite line is `✓`.) This was this session's own single, uncontested, uninterrupted invocation — no concurrency caveat applies here.

---

## 3. Playwright e2e — `pnpm exec playwright test`

**Config:** `apps/web/playwright.config.ts` — `testDir: ./e2e`, `baseURL: http://127.0.0.1:3000`, `webServer.url: http://127.0.0.1:3000/dashboard`, `reuseExistingServer: !process.env.CI`. `CI` was unset in this shell, and the production `aether-web.service`/`aether-api.service` systemd units were already live on ports 3000/8000 (`curl` 200 on both, confirmed before running), so Playwright **reused the live production instance** rather than building/starting a separate copy — this is how the suite is designed to run (no CI job exists for it; several specs' own doc-comments describe themselves as "non-destructive / state-restoring against live data", e.g. `launch-b1-approvals-remove.spec.ts`, `launch-b2-move-stage.spec.ts`). Run to completion per the task's "run it if it can run against local or prod" instruction, without modifying any production source code.

**Discovered scope:** 52 tests across 22 spec files. Two additional spec files (`baseline-sweep-authed.spec.ts`, `baseline-sweep-standalone.spec.ts`) contribute 0 dynamically-generated tests each — both gracefully no-op (`fs.existsSync` guard) because their `SCREEN-MATRIX.json` fixture was evicted to S3 in an earlier cleanup (per their own source comment: `// SCREEN-MATRIX.json was evicted to S3 in the launch-ready cleanup`), self-reporting `Preparing to capture 0 authenticated routes` rather than crashing. Expected, not a suite defect.

### 3a. Attempt 1 — blocked at auth (repo `.env` credential is stale)

`e2e/auth.setup.ts` resolves `LOGIN_EMAIL`/`LOGIN_PASSWORD` from `process.env` or the repo-root `.env`. The repo `.env` carries `LOGIN_EMAIL=sarkar.vikram@gmail.com` / `LOGIN_PASSWORD=AetherDemo1…`. Submitting these against the live `/login` form produced the in-page alert **"Invalid email or password."** (captured verbatim in the DOM snapshot at timeout) — the real production account's current password does not match what's recorded in the repo's `.env`. `waitForURL("**/dashboard")` timed out at 20s, which cascaded through Playwright's `setup`→`chromium` project dependency: **1 failed, 51 "did not run"**. Full trace: `logs/playwright-baseline-attempt1-stale-cred.log`.

**This is a credential/environment drift finding, not a code regression** — recorded honestly rather than silently worked around.

### 3b. Attempt 2 — orchestrator-provided test login (`admin` / `admin123`)

The task context supplied a second credential (`Test login: admin / admin123`). A scoped `--project=setup` check confirmed it authenticates (1 passed in 1.4s). Notably, a later assertion inside the full run (`gap_p7_def_b.spec.ts`, failure #2 below) shows `admin` resolves to the **same underlying account** as `sarkar.vikram@gmail.com` (its stored settings email) — `admin` is a username alias for the real account, not a separate sandboxed demo user. The full 52-test suite was then run with `LOGIN_EMAIL=admin LOGIN_PASSWORD=admin123` exported for that invocation only (never written to the repo `.env`).

**Result** [VERIFIED, `logs/playwright-baseline.log`]: **40 passed, 12 failed, 0 skipped, exit code 1, 275s (4.6m).**

### 3c. The 12 failures, root-caused

| # | Spec : test | Root cause | Category |
|---|---|---|---|
| 1 | `baseline-manual-verification.spec.ts` › baseline capture sweep | `ENOENT` reading `uat/reports/evidence/manual-verification/screens/SCREEN-MATRIX.json` — does not exist there (a `SCREEN-MATRIX.json` **does** exist, but under `uat/reports/evidence/gold-master-v2/phase0/`, a different evidence tree from an earlier Phase-0 step). Unlike its sibling `baseline-sweep-*.spec.ts` files, this spec lacks the `fs.existsSync` guard. | Missing fixture / stale path reference — pre-existing, unrelated to this run. |
| 2 | `gap_p7_def_b.spec.ts` › settings_save_with_existing_aether_local_email_succeeds | `expect.soft(emailValue.endsWith("@aether.local"))` failed — the live account's stored settings email is `sarkar.vikram@gmail.com`, not the `@aether.local` demo address the spec assumes. | Stale test assumption about seeded fixture data vs. real production account state. |
| 3–4 | `ml-admin-002-mobile-overflow.spec.ts` › `/admin/settings`, `/admin/users` @ 390px | `net::ERR_CONNECTION_REFUSED` at `http://127.0.0.1:3010/login` — spec hardcodes port **3010**, not the live 3000 the rest of the suite/deployment uses. | Hardcoded wrong port in the spec itself — test/environment drift, not a product defect. |
| 5–6 | `ml-agents-refix.spec.ts` › ML-agents-002, ML-agents-005 | `net::ERR_CONNECTION_REFUSED` at `http://127.0.0.1:3012/signup` — hardcodes port **3012**. | Same class as above. |
| 7–11 | `ml-fe-polish.spec.ts` › ML-settings-001 (×2), ML-resume-002, ML-agents-006 (×2) | `net::ERR_CONNECTION_REFUSED` at `http://127.0.0.1:3091/signup` — hardcodes port **3091**. | Same class as above. |
| 12 | `mobile-regression.spec.ts` › rg-mob-appr: approvals page loads at mobile viewport | 30s test timeout; the spec's own internal assertion `expect(result.status).toBe("PASS")` received `"FAIL"` on the live `/dashboard/approvals` route at 390×844. | **The one failure NOT explained by test-harness config drift** — candidate real issue/flake. Its sibling test (`rg-mob-appr: verify mobile approval card layout and interactions`) passed immediately after, so this needs a repeat run to distinguish a genuine mobile-approvals issue from a one-off timeout, rather than being treated as confirmed. |

**Net read:** 9 of 12 failures (#1, #3–11) are pre-existing test-authoring/environment issues (hardcoded ports never updated to match the live deployment topology, one missing-fixture path) orthogonal to application health. 1 (#2) is a stale fixture-data assumption. 1 (#12) is the sole failure plausibly reflecting the live application, flagged for follow-up — **not fixed here**, per this task's read-only/discovery mandate.

---

## 4. Artifacts

- `logs/pytest-baseline-FINAL-1885-passed.log` — **authoritative pytest result** (1885 passed, 0 failed, 0 skipped).
- `logs/pytest-baseline-clean-20260730T231714Z.log` — identical content, original filename from the run that produced it.
- `logs/pytest-baseline.log`, `logs/pytest-baseline-MINE-safe-snapshot.log`, `logs/quarantine-collided/*` — forensic remnants of the concurrent-dispatch collision described in §0; not used for any reported number.
- `logs/pytest-baseline-TESTER-v2-final.log` — this session's own hedge attempt, deliberately terminated (`EXIT_CODE=143`) once the authoritative result was in hand, to free the shared lock for other queued work.
- `logs/vitest-baseline.log`
- `logs/playwright-baseline-attempt1-stale-cred.log` — blocked-at-auth attempt (stale `.env` credential).
- `logs/playwright-baseline.log` — completed run (`admin`/`admin123` credential), 40 passed / 12 failed.
- `logs/run_pytest_bg.sh`, `run_pytest_bg_v2.sh`, `run_playwright_bg.sh`, `guard_snapshot.sh` — exact wrapper scripts used, kept for reproducibility.
