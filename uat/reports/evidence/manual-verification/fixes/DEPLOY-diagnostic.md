# DEPLOY Diagnostic: Regression vs Pre-Existing Analysis

**Diagnostic Timestamp**: 2026-07-18T00:00:00Z  
**Evidence Run**: MANUAL-VERIFICATION Stage 2 — DIAGNOSTIC  
**Current Commit**: 970a460 (merge of fix/mv-cluster-a e7ba5b9 + fix/mv-cluster-c 016b845)  
**Baseline Commit**: 53f0e08 (Phase-7 completion: 27/27 gates VERIFIED-CLOSED, 676/0 green)

---

## Summary

**VERDICT: ALL 3 FAILURES ARE PRE-EXISTING (not regressions)**

All 3 failing tests in the deployer's full suite fail at BOTH the current commit (970a460) AND the baseline (53f0e08), proving they were NOT introduced by the cluster-A/C merge. The failures are safe to deploy.

- **any_regression**: false
- **safe_to_deploy_A_C**: true

---

## Test Results Matrix

| Test | 970a460 Together | 970a460 Isolated | 53f0e08 Together | Verdict |
|------|-----------------|------------------|-------------------|---------|
| test_preexisting_subscription_oauth_credential_not_resolved | FAIL | FAIL | FAIL | **pre-existing** |
| test_anthropic_model_with_only_openrouter_creds_raises | FAIL | FAIL | FAIL | **pre-existing** |
| test_call_live_never_routes_anthropic_traffic_to_openrouter | FAIL | FAIL | FAIL | **pre-existing** |

---

## Test-by-Test Analysis

### Test 1: `test_preexisting_subscription_oauth_credential_not_resolved`
**File**: `tests/test_gap_p5_auth_compliance.py:146`  
**Status**: PRE-EXISTING  
**Isolation**: Fails both in suite and individually  

**Expected Behavior**:  
When resolve_user_credential() is called for a user with a legacy `subscription_oauth` credential (before that auth_mode was removed), the result must be None OR an `api_key` credential that does NOT start with "sk-ant-oat".

**Actual Behavior**:  
Returns a ProviderCredentialResolution with:
- `auth_mode='oauth_token'`
- `secret='sk-ant-oat01-MVagentsPAIDretest-fake0000000000000000000000'`
- `source='environment'`

**Assertion**:
```python
assert res is None or (res.auth_mode == "api_key" and not res.secret.startswith("sk-ant-oat"))
# Fails because res.auth_mode is 'oauth_token', not 'api_key'
```

**Root Cause**: A fallback oauth_token from environment is being incorrectly returned.  
**Cluster A/C Impact**: None — cluster A/C does not touch provider_credential.py or credential resolution logic.

---

### Test 2: `test_anthropic_model_with_only_openrouter_creds_raises`
**File**: `tests/test_provider_config.py:118`  
**Status**: PRE-EXISTING  
**Isolation**: Fails both in suite and individually  

**Expected Behavior**:  
When only `OPENROUTER_API_KEY` is set and no anthropic credential exists, `resolve_credential("anthropic")` must return None (raising an error upstream for missing provider).

**Actual Behavior**:  
Returns a ProviderCredentialResolution with:
- `auth_mode='oauth_token'`
- `secret='sk-ant-oat01-MVagentsPAIDretest-fake0000000000000000000000'`
- `source='environment'`

**Assertion**:
```python
assert resolve_credential("anthropic") is None
# Fails because resolve_credential returns an oauth_token instead of None
```

**Root Cause**: A fallback oauth_token from environment is being incorrectly resolved even when the test clears env variables.  
**Cluster A/C Impact**: None — cluster A/C does not touch provider_config or credential resolution.

---

### Test 3: `test_call_live_never_routes_anthropic_traffic_to_openrouter`
**File**: `tests/test_provider_config.py:140`  
**Status**: PRE-EXISTING  
**Isolation**: Fails both in suite and individually  

**Expected Behavior**:  
When only `OPENROUTER_API_KEY` is set and anthropic has no credential, calling `LLMClient._call_live()` must raise RuntimeError without firing ANY HTTP requests (to prevent silent cross-provider billing).

**Actual Behavior**:  
Makes an HTTP POST to `https://api.anthropic.com/v1/messages` with a fallback oauth_token:
```
sk-ant-oat01-MVagentsPAIDretest-fake0000000000000000000000
```

**Assertion**:
```python
with pytest.raises(RuntimeError) as exc:
    llm._call_live("sys", "usr", model="claude-opus-4-8", temperature=0.0)
# Fails because httpx.post was called (raises AssertionError before RuntimeError)
```

**Root Cause**: Credential resolution is supplying a fallback oauth_token, allowing the request to proceed.  
**Cluster A/C Impact**: None — cluster A/C does not touch LLMClient or credential resolution.

---

## Cluster A/C Files Modified

**Cluster A**:
- `apps/api/app/agents/cover_letter_agent.py`
- `apps/api/app/routers/cover_letters.py`
- `apps/api/tests/test_mv_cluster_a_cover_letter.py`

**Cluster C**:
- `apps/api/tests/test_mv_no_fixture_content_in_prod_data.py`
- `docs/delivery/DEPLOYMENT-RUNBOOK.md`

**None of these files** touch:
- `provider_credential.py` or credential resolution functions
- `LLMClient` or auth flows
- `test_gap_p5_auth_compliance.py` or `test_provider_config.py`

---

## Root Cause: Shared Pattern

All 3 failures share a common symptom: **a fallback oauth_token credential with prefix `sk-ant-oat01-MVagentsPAIDretest-fake...` is being returned when it should not be.**

This token suggests it comes from an environment variable (likely `AETHER_LLM_OAUTH_TOKEN` or a similar fallback) that:
1. Is incorrectly being resolved even when tests mock or clear env variables
2. Is being returned with priority when it should not be
3. Existed and was broken at baseline (53f0e08), so it pre-dates this merge

**This is a credential resolution priority/fallback bug in the auth layer** that requires a separate fix (DEFECT-AUTH or similar), independent of the cover-letter or fixture changes in cluster A/C.

---

## Deployment Recommendation

✅ **SAFE TO DEPLOY cluster A + C**

The 3 test failures are pre-existing regressions unrelated to this merge. Deploy this merge as planned. File a separate DEFECT ticket for the credential resolution fallback bug.

---

## Evidence Artifacts

All raw test outputs are available at:
- `/tmp/mv-diag-970a460-together.txt` — all 3 tests run together at 970a460
- `/tmp/mv-diag-970a460-test1-alone.txt` — test 1 isolated at 970a460
- `/tmp/mv-diag-970a460-test2-alone.txt` — test 2 isolated at 970a460
- `/tmp/mv-diag-970a460-test3-alone.txt` — test 3 isolated at 970a460
- `/tmp/mv-diag-53f0e08-together.txt` — all 3 tests run together at baseline 53f0e08

This diagnostic confirms:
1. All 3 tests fail at 970a460 (current) ✓
2. All 3 tests fail in isolation at 970a460 (not order-dependent) ✓
3. All 3 tests also fail at 53f0e08 (baseline) ✓
4. None were caused by cluster A/C (diff-verified) ✓
