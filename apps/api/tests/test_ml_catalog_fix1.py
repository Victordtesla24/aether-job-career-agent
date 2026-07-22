"""MODELS-LIVE FIX-1 (§3.3) — failing tests for the catalog gaps found in the
Phase-0 current-state audit (uat/reports/evidence/models-live/catalog/
CURRENT-STATE.md, dispatch #10):

  * ML-catalog-001 (HIGH, §3.2.1/§3.2.3) — the model picker is
    PROVIDER-GLOBAL (PUT /agents/providers/{id} -> AgentProvider.model), not
    per-agent. §3 requires a picker per agent whose selection persists to
    THAT agent's AgentConfig.model and is used on that agent's next run.
    The backend READ side (`_user_model_override`) already prefers a
    per-agent AgentConfig.model over the provider default (see agents.py
    ~879-928) — this file PINS that contract with an explicit
    two-different-agents-two-different-models assertion so the FE fixer can
    build the per-agent UI against a backend guarantee, and separately pins
    the WRITE-side gap that made ML-catalog-001 possible in the first place:
    PUT /agents/config/{agent_key} accepts ANY string as `model` — no
    catalog-membership check, so an unknown id is never rejected (§3.1.3).
  * ML-catalog-002 (MED, §3.1.2) — no catalog freshness is exposed: the
    GET .../models response carries no timestamp, and an expired cache that
    fails to refresh raises a blocking error instead of serving last-good
    stale data.
  * ML-catalog-003 (MED, §3.1.2) — no manual-refresh path exists.

PINNED CONTRACT for the fixer (exact names — match these or these tests will
legitimately still fail after implementation):

  * `GET /agents/providers/{provider}/models` response gains two new keys
    alongside the existing `provider` / `models` / `count`:
      - `lastRefreshedAt`: str — ISO-8601 UTC timestamp of the wall-clock
        moment the returned catalog was actually fetched from upstream (NOT
        the moment of this particular request). For the static (anthropic)
        catalog this may be "now" every call — that's honest, it's not
        cached.
      - `stale`: bool — True only when serving an EXPIRED cache because the
        latest upstream refresh attempt failed (never true for a fresh
        fetch or a within-TTL cache hit).
  * On upstream failure with a WARM (even if TTL-expired) cache present, the
    endpoint MUST still return 200 with the last-good cached `models` list
    (never empty, never fabricated) and `stale: true` with `lastRefreshedAt`
    equal to the PRIOR successful fetch's timestamp — never a blocking 4xx/5xx
    that leaves the FE catalog empty.
  * `POST /agents/providers/{provider}/models/refresh` — new route. Forces a
    fresh upstream fetch bypassing the TTL cache and returns the SAME
    envelope shape as the GET endpoint (`provider`, `models`, `count`,
    `lastRefreshedAt`, `stale`) with `stale: false` and an updated
    `lastRefreshedAt` on success. On upstream failure it follows the same
    honest-stale-serve rule as the GET path (never worse than GET).
  * `PUT /agents/config/{agent_key}` — `model` must be validated against the
    union of every provider's catalog (`list_provider_models` per known
    provider, keyed by `resolve_provider(model)`); an id that matches no
    provider's catalog is rejected `422` with a `detail` naming the problem
    (mentions "model"); an id present in some provider's catalog is accepted
    (`200`).

Outbound OpenRouter HTTP is ALWAYS mocked here (via `monkeypatch.setattr
(httpx, "get", ...)` on the `httpx` module `llm_client.list_provider_models`
imports) — these tests never touch the network.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import pytest

from app.services import credential_vault as vault
from app.services import llm_client


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _clean_openrouter_cache():
    """Every test starts with NO cached OpenRouter catalog and leaves none
    behind — this cache is process-global module state shared across tests."""
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)
    yield
    llm_client._MODEL_CATALOG_CACHE.pop("openrouter", None)


# ---------------------------------------------------------------------------
# ML-catalog-002 — freshness field on the catalog response
# ---------------------------------------------------------------------------


def test_models_endpoint_includes_freshness_field(client, auth_headers, monkeypatch):
    """§3.1.2: GET /agents/providers/{provider}/models MUST expose
    `lastRefreshedAt` (ISO-8601 str) + `stale` (bool).

    FAILS NOW: the endpoint returns only {provider, models, count} — no
    freshness metadata at all. `list_provider_models()` returns a bare
    `list[dict]`; the router has no wall-clock fetch time to report even if
    it wanted to (the cache stores a `time.monotonic()` value, not a
    wall-clock timestamp — see llm_client.py `_MODEL_CATALOG_CACHE`).
    """
    monkeypatch.setattr(
        "app.services.llm_client.list_provider_models",
        lambda provider, user_id, **k: [
            {"id": "z/cheap", "name": "Z", "promptPerM": 0.1, "completionPerM": 0.2,
             "contextLength": 8000, "tier": "budget", "reasoning": False},
        ],
    )
    r = client.get("/agents/providers/openrouter/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "lastRefreshedAt" in body, (
        f"missing freshness field 'lastRefreshedAt' — got keys={sorted(body.keys())}"
    )
    # Must be a real, parseable ISO-8601 timestamp — not a placeholder string.
    datetime.fromisoformat(body["lastRefreshedAt"].replace("Z", "+00:00"))
    assert "stale" in body and isinstance(body["stale"], bool), (
        f"missing/wrong-typed 'stale' flag — got keys={sorted(body.keys())}"
    )


def test_anthropic_models_endpoint_also_includes_freshness_field(client, auth_headers):
    """The static (non-cached) anthropic catalog must ALSO carry the two new
    keys — a consistent envelope regardless of provider — so the FE doesn't
    need provider-specific branching to render the freshness note.
    FAILS NOW: same missing-keys gap as the openrouter case above.
    """
    r = client.get("/agents/providers/anthropic/models", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "lastRefreshedAt" in body
    assert body.get("stale") is False  # static list is never "stale"


# ---------------------------------------------------------------------------
# ML-catalog-002 — honest stale-serve on upstream failure with a warm cache
# ---------------------------------------------------------------------------


def test_models_endpoint_serves_stale_cache_on_upstream_failure(client, auth_headers, monkeypatch):
    """§3.1.2: when the TTL has expired and a fresh upstream fetch fails
    (network error / non-2xx), the endpoint MUST still return 200 with the
    last-good cached models AND stale=true + the PRIOR lastRefreshedAt —
    never an empty/fake list, never a blocking 4xx/5xx.

    FAILS NOW: `list_provider_models()` raises `ModelCatalogError` whenever
    the TTL has lapsed and the retry fails; it never looks at the still-
    present (merely expired) cache entry, so the router turns this into a
    blocking 400 instead of serving last-good stale data — asserted below by
    checking the CURRENT (wrong) status code is what today's code actually
    returns is not the point; the assertion pins the REQUIRED behaviour and
    fails loudly against current code.
    """
    prior_models = [
        {"id": "cached/model", "name": "Cached", "promptPerM": 1.0, "completionPerM": 2.0,
         "contextLength": 4096, "tier": "budget", "reasoning": False},
    ]
    # A warm cache from an earlier successful fetch, now EXPIRED.
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (
        time.monotonic() - llm_client._MODEL_CATALOG_TTL - 10,
        prior_models,
    )

    class _Cred:
        secret = "sk-test"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm_client, "resolve_user_credential", lambda *a, **k: _Cred())
    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: None)

    def _boom(*a, **k):
        raise RuntimeError("simulated upstream network failure")

    import httpx
    monkeypatch.setattr(httpx, "get", _boom)

    r = client.get("/agents/providers/openrouter/models", headers=auth_headers)
    assert r.status_code == 200, (
        "an upstream failure with a warm (even if expired) cache must serve "
        f"last-good data, not block the UI — got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert body["models"] == prior_models, "must serve the last-good cached models verbatim"
    assert body.get("stale") is True, "must flag the response as stale"
    assert "lastRefreshedAt" in body


def test_list_provider_models_never_raises_when_a_stale_cache_exists(monkeypatch):
    """Same contract, exercised directly at the `llm_client` boundary (no
    HTTP layer) so a future refactor of the router can't accidentally hide a
    regression here: with an expired-but-present cache entry, a failing
    upstream fetch must not raise `ModelCatalogError` — the caller always has
    a last-good list to fall back to.
    FAILS NOW: raises `ModelCatalogError`.
    """
    prior_models = [{"id": "cached/x", "name": "X", "promptPerM": 0.0, "completionPerM": 0.0,
                      "contextLength": 1000, "tier": "free", "reasoning": False}]
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (
        time.monotonic() - llm_client._MODEL_CATALOG_TTL - 5, prior_models,
    )

    class _Cred:
        secret = "sk-test"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm_client, "resolve_user_credential", lambda *a, **k: _Cred())
    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: None)

    def _boom(*a, **k):
        raise RuntimeError("simulated network failure")

    import httpx
    monkeypatch.setattr(httpx, "get", _boom)

    try:
        result = llm_client.list_provider_models("openrouter", user_id="u1")
    except llm_client.ModelCatalogError as exc:
        pytest.fail(
            "list_provider_models() raised ModelCatalogError instead of "
            f"serving the last-good stale cache: {exc}"
        )
    assert result == prior_models


# ---------------------------------------------------------------------------
# ML-catalog-003 — manual refresh endpoint
# ---------------------------------------------------------------------------


def test_manual_refresh_endpoint_forces_fresh_fetch(client, auth_headers, monkeypatch):
    """§3.1.2: POST /agents/providers/{provider}/models/refresh forces a
    fresh upstream fetch bypassing the TTL cache, and returns the SAME
    envelope shape as GET .../models with stale=false and an updated
    lastRefreshedAt on success.
    FAILS NOW: no such route exists (404).
    """
    old_models = [{"id": "stale/model", "name": "Old", "promptPerM": 1.0, "completionPerM": 2.0,
                   "contextLength": 4096, "tier": "budget", "reasoning": False}]
    # Cache is STILL FRESH (would normally be served as-is by GET) — the
    # manual refresh route must bypass it anyway.
    llm_client._MODEL_CATALOG_CACHE["openrouter"] = (time.monotonic(), old_models)

    class _Cred:
        secret = "sk-test"
        base_url = "https://openrouter.ai/api/v1"

    monkeypatch.setattr(llm_client, "resolve_user_credential", lambda *a, **k: _Cred())
    monkeypatch.setattr(llm_client, "resolve_credential", lambda *a, **k: None)

    class _Resp:
        status_code = 200

        def json(self):
            return {"data": [
                {"id": "fresh/model", "name": "Fresh",
                 "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                 "context_length": 8192},
            ]}

    calls = {"n": 0}

    def _fake_get(*a, **k):
        calls["n"] += 1
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", _fake_get)

    r = client.post("/agents/providers/openrouter/models/refresh", headers=auth_headers)
    assert r.status_code == 200, (
        f"expected the manual refresh route to exist and succeed, got "
        f"{r.status_code}: {r.text}"
    )
    body = r.json()
    assert calls["n"] >= 1, "must have actually hit the upstream, not served the fresh cache"
    assert body["models"][0]["id"] == "fresh/model", "must force a fresh fetch, not the cached list"
    assert body.get("stale") is False
    assert "lastRefreshedAt" in body


def test_manual_refresh_endpoint_rejects_unknown_provider(client, auth_headers):
    """The refresh route must not silently no-op for a provider with no live
    catalog (e.g. groq) — honest 400/404, matching the GET endpoint's
    existing behaviour for the same case.
    FAILS NOW: route doesn't exist at all (404 either way, but for the wrong
    reason — pinned here so the fixer's route exists AND still rejects
    groq/bedrock/etc honestly)."""
    r = client.post("/agents/providers/groq/models/refresh", headers=auth_headers)
    assert r.status_code in (400, 404), r.text


# ---------------------------------------------------------------------------
# ML-catalog-001 — per-agent (not provider-global) persistence contract
# ---------------------------------------------------------------------------


def test_per_agent_model_persists_independently_round_trip(client, auth_headers):
    """PINS THE PER-AGENT CONTRACT for the FE fixer: PUT
    /agents/config/{agent_key} with a valid model id persists to THAT
    agent's AgentConfig.model row, survives reload (a subsequent GET returns
    the same value), and `_user_model_override(user_id, backend)` resolves
    to it for THAT agent.

    THE KEY ASSERTION: two DIFFERENT agents can simultaneously hold two
    DIFFERENT models — proving the picker's persistence is per-agent, not
    provider-global (would fail if the write path silently fanned out to a
    shared/global row instead of `AgentConfig.model` keyed per agent).

    NOTE: the read-side (`_user_model_override`) already implements this
    correctly today per the ML-catalog Phase-0 code audit — this test is
    written to PIN the contract for FE work (§3.3 instruction), not because
    the backend read path is expected to fail. If it currently PASSES, that
    is the expected/correct outcome for this specific assertion; the write-
    side validation gap is pinned separately below
    (test_unknown_model_id_rejected_valid_model_accepted), which DOES fail
    now.
    """
    from app.routers.agents import _user_model_override

    put1 = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "deepseek/deepseek-chat"}, headers=auth_headers,
    )
    assert put1.status_code == 200, put1.text
    put2 = client.put(
        "/agents/config/coverLetter",
        json={"model": "anthropic/claude-opus"}, headers=auth_headers,
    )
    assert put2.status_code == 200, put2.text

    # Survives reload.
    get1 = client.get("/agents/config/resumeTailoring", headers=auth_headers)
    get2 = client.get("/agents/config/coverLetter", headers=auth_headers)
    assert get1.json()["model"] == "deepseek/deepseek-chat"
    assert get2.json()["model"] == "anthropic/claude-opus"

    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    tailor_override = _user_model_override(user_id, "tailor")
    cover_override = _user_model_override(user_id, "coverLetter")
    assert tailor_override == "deepseek/deepseek-chat"
    assert cover_override == "anthropic/claude-opus"
    # THE per-agent (not provider-global) assertion.
    assert tailor_override != cover_override, (
        "two different agents resolved to the SAME model — the override "
        "path is provider-global, not per-agent"
    )


def test_unknown_model_id_rejected_valid_model_accepted(client, auth_headers, monkeypatch):
    """§3.1.3: PUT /agents/config/{agent_key} with an unknown model id (not
    present in ANY provider's catalog) must be rejected with an honest 422
    naming the problem; a valid catalog id must be accepted (200).

    FAILS NOW: `AgentConfigUpdate.model` is a bare `str` with no
    catalog-membership validator (agents.py `update_agent_config` writes
    whatever string arrives straight to the DB) — the PUT below currently
    returns 200 for a nonsense id instead of 422.
    """
    monkeypatch.setattr(
        "app.services.llm_client.list_provider_models",
        lambda provider, user_id=None, **k: (
            [{"id": "real/model", "name": "Real", "promptPerM": 1.0, "completionPerM": 2.0,
              "contextLength": 4096, "tier": "budget", "reasoning": False}]
            if provider == "openrouter" else
            list(llm_client._STATIC_MODEL_CATALOG.get(provider, []))
        ),
    )

    bad = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "totally-not-a-real-model-id-xyz"}, headers=auth_headers,
    )
    assert bad.status_code == 422, (
        f"unknown model id must be rejected with 422, got {bad.status_code}: {bad.text}"
    )
    detail = str(bad.json().get("detail", "")).lower()
    assert "model" in detail, f"422 detail must name the problem, got: {detail!r}"

    good = client.put(
        "/agents/config/resumeTailoring",
        json={"model": "real/model"}, headers=auth_headers,
    )
    assert good.status_code == 200, good.text


def test_deterministic_sentinel_still_accepted(client, auth_headers):
    """Guard: the literal "deterministic" sentinel (used by non-LLM agents,
    e.g. jobDiscovery) must remain a valid, always-accepted `model` value —
    the new catalog-membership validation must not break the existing
    deterministic-agent config path."""
    r = client.put(
        "/agents/config/jobDiscovery",
        json={"model": "deterministic"}, headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["model"] == "deterministic"


# ---------------------------------------------------------------------------
# ML-catalog-006 (BLOCKER, §3.4.4) — no silent model substitution for a
# USER-CHOSEN model (ADR-ML-3, docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md).
#
# The FIX-1 diff review (5db6f43, reviewer finding B1) traced the real run
# path and found `_validate_agent_model`'s docstring claim — "a genuinely
# wrong id fails honestly at call time" — is FALSE: `get_model('REASONING')`
# (llm_client.py:378-390) returns the user's per-agent override verbatim;
# `LLMClient._auto()` (llm_client.py:1334-1411) builds a fallback chain via
# `_model_chain()` (llm_client.py:1413-1417) that ALWAYS appends the
# hardcoded `FALLBACK_MODEL` ("openai/gpt-oss-20b:free"), regardless of
# whether the primary model came from a deliberate user choice; when the
# primary 404s, the broad `except Exception` (llm_client.py:1391) silently
# retries the fallback and, on success, `_auto()` returns NORMALLY — no
# exception, no signal a DIFFERENT model actually served the request. This is
# the exact §3.4.4 BLOCKER: "never a silent fallback to a different model
# (silent model substitution = BLOCKER finding)."
#
# ADR-ML-3 RULING: when a run uses a USER-SELECTED model (`_user_model_override`
# returned a value), silent substitution to a DIFFERENT model is FORBIDDEN —
# on failure, surface an honest error + refund any reserved quota + NEVER run
# a different model and report success. The un-chosen SYSTEM-DEFAULT path may
# retain its resilience fallback (contrast guard below pins that boundary so
# the re-fix doesn't over-reach).
# ---------------------------------------------------------------------------


def test_user_chosen_model_failure_does_not_silently_substitute_fallback(
    client, auth_headers, monkeypatch, test_user_id, tmp_path
):
    """THE keystone ML-catalog-006 test — reproduces the diff review's B1
    finding end-to-end through the REAL run/quota path (`_record_run` ->
    `_execute_reserved_run` -> `user_model_context` -> `LLMClient._auto`).

    Setup: the user deliberately picks an OpenRouter model for `coverLetter`
    that will FAIL at call time (a stale/unavailable id — mocked as a 404).
    `LLMClient._call_live` is mocked so ONLY the user's chosen model fails;
    the hardcoded `FALLBACK_MODEL` "succeeds" if attempted — this is exactly
    what the reviewer's reproduction did (5db6f43 review, Item 2(b)).

    REQUIRED (ADR-ML-3): the run must surface an HONEST error (mapped to
    HTTP 503, matching the sibling `LLMUnavailableError` contract already
    pinned in `test_gap_p6_billing.py::test_honest_llm_failure_refunds_
    reserved_run_and_503`) — never a fake 200-equivalent success built from
    FALLBACK_MODEL's output — and the reserved plan-quota run must be
    refunded (runsUsed returns to its pre-run value).

    FAILS NOW: today's `_auto()` swallows the primary failure, silently
    serves the FALLBACK_MODEL's output, and `_record_run` returns a normal
    completed-run dict (no exception at all) — the `else: pytest.fail(...)`
    branch below fires and documents the actual silently-substituted output.
    """
    from fastapi import HTTPException

    from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
    from app.routers.agents import _record_run
    from app.services.llm_client import LLMClient, get_fallback_model, get_model

    # The user deliberately picks an OpenRouter id for coverLetter that will
    # fail live (mocked below) — a real per-agent override, not the seeded
    # "claude-sonnet-4" default (see `_RECOMMENDED_FOR_BACKEND`).
    put = client.put(
        "/agents/config/coverLetter",
        json={"model": "vendor/user-chosen-unavailable-model"}, headers=auth_headers,
    )
    assert put.status_code == 200, put.text

    fallback_id = get_fallback_model()
    calls: list[str | None] = []

    def _fake_call_live(self, system, user, *, model=None, temperature=0.0, max_seconds=None):
        calls.append(model)
        if model == "vendor/user-chosen-unavailable-model":
            raise RuntimeError("LLM provider HTTP 404: model not found")
        # Any OTHER model in the chain (i.e. the hardcoded FALLBACK_MODEL)
        # "succeeds" — this is the silent-substitution trap.
        return "content from a model the user never chose"

    monkeypatch.setattr(LLMClient, "_call_live", _fake_call_live)

    def _run_the_real_call_path() -> dict[str, Any]:
        # Mirrors the real cover-letter agent's call surface exactly
        # (apps/api/app/agents/cover_letter_agent.py:1121-1127):
        # `get_model('REASONING')` resolved from inside the bound
        # `user_model_context`, then passed explicitly to `.complete(...)`.
        resolved = get_model("REASONING")
        assert resolved == "vendor/user-chosen-unavailable-model"  # sanity: override IS bound
        content = LLMClient(mode="auto", fixture_dir=tmp_path).complete(
            "cover_letter", "sys", "usr", model=resolved, temperature=0.0,
        )
        return {"resolved_model_output": content}

    ensure_user_billing(test_user_id)
    quota_repo = UsageQuotaRepository()
    runs_used_before = int(quota_repo.get_by_user(test_user_id)["runsUsed"])

    try:
        result = _record_run(test_user_id, "coverLetter", {}, _run_the_real_call_path)
    except HTTPException as exc:
        assert exc.status_code == 503, (
            f"expected an honest 503 (matching the sibling LLMUnavailableError "
            f"contract), got {exc.status_code}: {exc.detail}"
        )
    else:
        pytest.fail(
            "SILENT MODEL SUBSTITUTION (§3.4.4 BLOCKER, ADR-ML-3): a run bound "
            "to the user's DELIBERATELY CHOSEN model "
            "('vendor/user-chosen-unavailable-model', which 404'd) returned a "
            f"normal completed-run result instead of an honest error: {result!r}. "
            f"Models actually attempted (in order): {calls!r} — the fallback "
            f"model ({fallback_id!r}) silently served the request with NO "
            "signal to the caller that a different model than the one the "
            "user picked actually ran. Required (ADR-ML-3): an honest "
            "error + refund, never a fake success on a substituted model."
        )

    # Reserved plan-quota run for this failed, user-chosen-model run must be
    # refunded — never billed for a run that (should have) failed honestly.
    runs_used_after = int(quota_repo.get_by_user(test_user_id)["runsUsed"])
    assert runs_used_after == runs_used_before, (
        f"reserved quota for the failed user-chosen-model run was not "
        f"refunded: runsUsed before={runs_used_before} after={runs_used_after}"
    )


def test_default_model_failure_may_still_fall_back_contrast_guard(
    client, auth_headers, monkeypatch, test_user_id, tmp_path
):
    """Contrast guard for ADR-ML-3 (§3.4.4): the strict no-substitution rule is
    scoped to a USER-CHOSEN model. A run on the unmodified SYSTEM-DEFAULT model
    (no per-agent override, no openrouter provider-default override — a fresh
    user who never picked anything) retains its EXISTING resilience — one
    fallback retry, matching `test_llm_resilience.py::TestModelChain` and
    `TestAutoModeFallback` — so the re-fix does not over-reach and regress
    users who never chose a model.

    This is a PIN, not one of the newly-required-behaviour tests: it is
    expected to PASS both BEFORE and AFTER the re-fix. If a re-fix makes this
    fail, the re-fix over-reached (broke default resilience) — see the diff
    review's explicit warning against that (Item 2, closing option (ii)).
    """
    from app.repositories.billing import ensure_user_billing
    from app.routers.agents import _record_run
    from app.services.llm_client import LLMClient, get_model

    monkeypatch.setenv("AETHER_MODEL_REASONING", "env/system-default-model")
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", "openai/gpt-oss-20b:free")

    calls: list[str | None] = []

    def _fake_call_live(self, system, user, *, model=None, temperature=0.0, max_seconds=None):
        calls.append(model)
        if model == "env/system-default-model":
            raise RuntimeError("simulated upstream 404 on the env-default model")
        return "fallback served this system-default run"

    monkeypatch.setattr(LLMClient, "_call_live", _fake_call_live)

    def _run_the_real_call_path() -> dict[str, Any]:
        resolved = get_model("REASONING")
        assert resolved == "env/system-default-model"  # sanity: NO override bound
        content = LLMClient(mode="auto", fixture_dir=tmp_path).complete(
            "cover_letter", "sys", "usr", model=resolved, temperature=0.0,
        )
        return {"resolved_model_output": content}

    ensure_user_billing(test_user_id)
    # No PUT to /agents/config/coverLetter and no openrouter provider default
    # -> `_user_model_override` resolves to None for this fresh user.
    out = _record_run(test_user_id, "coverLetter", {}, _run_the_real_call_path)
    assert out["resolved_model_output"] == "fallback served this system-default run"
    assert calls == ["env/system-default-model", "openai/gpt-oss-20b:free"], calls
