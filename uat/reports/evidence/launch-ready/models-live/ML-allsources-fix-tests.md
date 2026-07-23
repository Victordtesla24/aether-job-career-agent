# RED→GREEN evidence — rows ML-audit-allsources-deadcode-001, ML-audit-seek-fe-hardcode-001 (backend half), ML-prodverify-low1-allsources

Date: 2026-07-24 (Australia/Melbourne). Runner: `flock /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_source_availability.py -q`

## Test file
`apps/api/tests/test_source_availability.py` — 13 tests written FIRST, encoding the design:
- `all_sources()` hard-deleted (zero-caller dead code; fresh reference trace 2026-07-24: only its own definition, a coincidentally-named test method `test_adapter_registry_knows_all_sources` that calls `get_adapter_class` only, and docs/ledger mentions — zero live callers across apps/packages/scripts/ci/.claude).
- New `source_availability()` primitive: `{source, available, reason}` rows, computed at CALL time (`build_live_registry()`), so `AETHER_ENABLE_SEEK` flips availability without re-import.
- New endpoint `GET /agents/scout/sources/availability` (auth required).
- `GET /jobs?source=X` honest validation: unknown → 422 with known set; known-but-unavailable → 422 with reason + `include_stale` hint; `include_stale=true` keeps history reachable (GAP-P6-DATA-001); available sources and env-enabled seek → 200.

## RED (before implementation, 2026-07-24)
```
11 failed, 2 passed
```
(The 2 passes were pre-satisfied auth/behaviour assertions; all availability/validation tests failed as expected against the unmodified code.)

## GREEN (after implementation, 2026-07-24)
```
13 passed, 6 warnings in 13.44s
```

## Implementation commits
See ledger rows' fixCommits (filled at commit time).
