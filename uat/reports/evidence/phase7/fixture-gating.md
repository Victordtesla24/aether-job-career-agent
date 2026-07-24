# Phase 5A — Fixture Gating: Production Guard Verification & Remediation

**Date**: 2026-07-24
**Branch**: `phase5/fixture-gating`
**Status**: PASS (with remediation applied)

---

## 1. Production Environment Confirmed

| Env Var | Value | Verified |
|---|---|---|
| `AETHER_ENV` | `production` | ✅ (Phase 0) |
| `AETHER_LLM_MODE` | `auto` | ✅ (Phase 0) |
| `AETHER_DISCOVERY_FIXTURE_DIR` | (not set) | ✅ (this audit) |

---

## 2. §REC-04 Fail-Fast Guard — VERIFIED CORRECT

**Location**: `apps/api/app/main.py` lines 93–118

**Logic**:
1. Reads `AETHER_LLM_MODE` (defaults to `replay`)
2. If mode != `replay` → early return (pass)
3. If `AETHER_ENV == "production"` → `raise RuntimeError("§REC-04: ...")`
4. Otherwise → print warning to stderr only

**Call site**: `create_app()` line 180 — called BEFORE any routers/DB wired.

**Verdict**: ✅ The guard is intact, correctly placed, and **cannot be bypassed**. The production `.env` has `AETHER_LLM_MODE=auto`, so the guard's condition (`mode != "replay"`) triggers the early return. Even if someone changed `AETHER_LLM_MODE` to `replay` on a production deploy, the guard would crash the API at startup with a clear `§REC-04` error message.

**Test coverage**: `apps/api/tests/test_gap_e1_llm_mode.py` (4 hermetic tests):
- `test_replay_mode_in_production_raises` ✅
- `test_non_replay_modes_in_production_do_not_raise` (parametrized: auto/live/record) ✅
- `test_replay_mode_in_development_warns_but_does_not_raise` ✅
- `test_replay_mode_with_no_aether_env_set_warns_but_does_not_raise` ✅

---

## 3. LLM Client Mode Routing — VERIFIED SAFE

**Location**: `apps/api/app/services/llm_client.py`

| Mode | Behavior | Fixture Risk |
|---|---|---|
| `replay` | `_replay()` — reads from `tests/fixtures/llm/` | ⚠️ Blocked by §REC-04 |
| `auto` | `_auto()` — live calls only; on failure → `LLMUnavailableError` (503) | ✅ No fixture fallback |
| `live` | `_call_live()` — live call, raises on error | ✅ No fixture path |
| `record` | `_call_live()` + `_record()` on success | ✅ Records only on success |

**Key design decisions that prevent fixture leakage in `auto` mode:**
- `_auto()` NEVER serves a recorded fixture on failure — it raises `LLMUnavailableError` (line 1524)
- On a live SUCCESS response in `auto` mode, recording a fixture is harmless and retained (line 1513-1514)
- `QuotaExhaustedError` is NOT caught in `_auto()` — propagates to router as honest 429
- The fixture default directory is `apps/api/tests/fixtures/llm/` (inside tests/ — NOT on production filesystem path)

---

## 4. Discovery Adapter Fixture Paths — GAP FOUND & FIXED

**Location**: `apps/api/app/services/discovery/base_adapter.py` lines 92–100

**Finding**: `_resolve_payload()` reads `AETHER_DISCOVERY_FIXTURE_DIR` with NO environment gate. If this env var is set in production, ALL job-board discovery adapters serve canned HTTP fixtures (`apps/api/tests/fixtures/http/<source>/jobs.json`) instead of making live calls.

**Risk**: The deploy-process defect that caused the prod-DB-wipe incident (`docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`) involved sourcing the production `.env` into a test-suite invocation. `tests/conftest.py` line 60 sets `AETHER_DISCOVERY_FIXTURE_DIR`. If this leaked into a production shell, discovery would silently serve stale fixture data as live job listings.

**Remediation applied**: Added `_guard_production_discovery_fixtures()` in `apps/api/app/main.py` (new function, lines ~119-152), called from `create_app()` at line 181. The guard:

1. Reads `AETHER_DISCOVERY_FIXTURE_DIR`
2. If not set → early return (pass)
3. If `AETHER_ENV == "production"` → `raise RuntimeError("§REC-05: ...")`
4. Otherwise → print warning to stderr

**Design**: Pure env-var check — no file I/O, no imports — safe to call early in `create_app()` before settings/DB wired. Mirrors the proven `_guard_production_replay_mode()` pattern exactly.

---

## 5. Fixture File Inventory

All fixture files live under `apps/api/tests/fixtures/`:

| Directory | Contents | Production Risk |
|---|---|---|
| `fixtures/llm/cover_letter/` | `default.json`, `retry.json`, `retry2.json` | Gated by §REC-04 |
| `fixtures/llm/tailor/` | `default.json` | Gated by §REC-04 |
| `fixtures/llm/tailor_entailment/` | `default.json` | Gated by §REC-04 |
| `fixtures/llm/story_extractor/` | `default.json` | Gated by §REC-04 |
| `fixtures/llm/email_*/` | Various `.json` | Gated by §REC-04 |
| `fixtures/llm/cover_letter_refine/` | `default.json`, `retry.json` | Gated by §REC-04 |
| `fixtures/http/<source>/` | `jobs.json` (11 sources) | Gated by §REC-05 (NEW) |
| `fixtures/github_fixture.py` | Synthetic sample data | Test-only import |
| `fixtures/portfolio_fixture.py` | Synthetic sample HTML | Test-only import |

**No production code imports `github_fixture` or `portfolio_fixture`** — these are exclusively test imports.

---

## 6. API Endpoint Check

| Endpoint | Response | Notes |
|---|---|---|
| `GET /api/health` | `{"status":"ok","version":"0.2.0"}` 200 | ✅ Healthy |
| `GET /api/jobs` | `{"detail":"Not authenticated"}` 401 | ✅ Auth gate working |
| `GET /api/applications` | `{"detail":"Not authenticated"}` 401 | ✅ Auth gate working |
| `GET /api/resumes` | `{"detail":"Not authenticated"}` 401 | ✅ Auth gate working |
| `GET /docs` | (not tested live; code gate confirmed) | ✅ Disabled in prod |

No fixture content was observable in unauthenticated API responses (as expected — auth is required for data endpoints).

---

## 7. Prod-DB-Wipe Incident Context

The 2026-07-18 prod-DB-wipe incident (documented in `docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`) was caused by:
- A deploy-process defect that sourced the production `.env` into a test-suite invocation
- The test suite's `conftest.py` then ran `TRUNCATE ... CASCADE` against what it thought was the test schema — but was actually the production `aether` schema

**Post-incident guards now in place:**
1. `conftest.py` has a `_run_prod_truncate_guard()` fail-closed check (MV-system-003) — verified by `test_mv_system_003_prod_truncate_guard.py`
2. `§REC-04`: startup crash if `AETHER_LLM_MODE=replay` in production (this audit)
3. `§REC-05` (NEW): startup crash if `AETHER_DISCOVERY_FIXTURE_DIR` is set in production
4. `_auto()` mode in `llm_client.py` NEVER falls back to fixtures on failure

---

## 8. Conclusion

| Check | Status |
|---|---|
| §REC-04 guard verified correct | ✅ PASS |
| LLM client mode routing safe | ✅ PASS |
| Discovery fixture gate | 🔧 FIXED (added §REC-05) |
| No fixture files importable from production code | ✅ PASS |
| Production `.env` clean | ✅ PASS |
| API endpoints respond correctly | ✅ PASS |

**Risk of fixture data appearing in production**: MITIGATED. Two independent fail-fast guards at startup prevent the API from even starting if fixture-serving environment variables are present in production. The `auto` LLM mode never falls back to fixtures. No production code paths import or load fixture files.
