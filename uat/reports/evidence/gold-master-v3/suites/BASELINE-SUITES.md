# Zero-Regression Baseline Test Suite Summary

**Timestamp:** 2026-07-31T17:51:27Z
**Git HEAD SHA:** 6440325b363e2b9a684f54742ad02781babefe47

---

## Test Suites Executed

### 1. Backend Tests (pytest — apps/api)

**Command:**
```bash
flock /tmp/aether-pytest.lock scripts/run-tests.sh -p no:xdist --tb=short
```

**Exit Code:** 0

**Summary:**
36 failed, 2027 passed, 1 skipped, 9 errors in 2677.16s

**Duration:** 44:37 (2677.16 seconds)

**Notes:**
- Total tests collected: 2073
- Ran with `-p no:xdist` to avoid parallel execution conflicts with shared `aether_test` schema
- 36 genuine failures detected (not flakiness); multiple test files show failures/errors
- 1 skipped test
- 9 errors (likely test setup/infrastructure issues)

### 2. Frontend Tests (vitest — apps/web)

**Command:**
```bash
pnpm test
```

**Exit Code:** 0 ✓ PASS

**Summary:**
Test Files  96 passed (96), Tests  650 passed (650)

**Duration:** 3m52.828s

### 3. Linting (ESLint — apps/web)

**Command:**
```bash
pnpm lint
```

**Exit Code:** 0 ✓ PASS
**Duration:** 13.785s
**Result:** ✓ No ESLint warnings or errors

### 4. Type Checking (TypeScript — apps/web)

**Command:**
```bash
pnpm type-check
```

**Exit Code:** 0 ✓ PASS
**Duration:** 10.607s
**Result:** ✓ No TypeScript errors

### 5. Playwright E2E Tests

**Status:** NOT-RUN
**Reason:** Complex infrastructure dependency; E2E suite requires running local server with production-like environment setup, deferred to deployment verification phase.

---

## Baseline Counts (Machine-Readable)

```
pytest: passed=2027 failed=36 skipped=1 errors=9
vitest: passed=650 failed=0 skipped=0
playwright: NOT-RUN: Complex infrastructure dependency
```

---

## Genuine Failures vs Flakiness

Multiple test files show failures (F/E indicators observed):
- tests/test_networking.py: 4 failures, 1 error
- tests/test_offers_persist.py: 4 failures
- tests/test_pipeline.py: 2 failures
- tests/test_provider_config.py: 5 failures, 2 errors
- tests/test_resume_ingest.py: 1 failure, 1 error
- tests/test_resume_upload.py: 1 failure, 1 error
- tests/test_rt_004_application_card_dedup.py: 1 failure
- tests/test_rt_005_board_stage_sync.py: 6 failures
- tests/test_rt_007_board_sweep.py: 1 failure, 1 error
- tests/test_wave4a_catalog_wiring.py: 1 error, 1 failure
- tests/test_wave4b_interview_prep_agent.py: 5 failures
- tests/test_wave4c_notification_agent.py: 1 error, 2 failures (including final test)
- tests/test_wave4c_outreach_contact_agents.py: 2 failures
- tests/test_wave4c_thread_agents.py: 1 failure

**Note:** These are genuine failures, not DB schema contention flakiness. The errors span multiple, unrelated test files and test classes, indicating defects in code logic rather than concurrent execution conflicts.

---

## Summary

**Backend (pytest):** 2027/2073 passing (97.8%)
**Frontend (vitest):** 650/650 passing (100%)
**Lint:** ✓ PASS (0 errors)
**Type-check:** ✓ PASS (0 errors)

**BASELINE ESTABLISHED:** The repository contains genuine test failures that must be fixed before this can be considered the true regression baseline. Current state represents the pre-fix measurement point.

