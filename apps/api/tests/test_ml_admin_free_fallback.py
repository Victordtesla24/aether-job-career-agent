"""ADMIN-ONLY free-model rescue on an OpenRouter HTTP 402 (insufficient credits).

Operator mandate (MODELS-LIVE, evidence:
``uat/reports/evidence/free-model-fallback/PROBE-REPORT.json``): when an
OpenRouter call fails with HTTP **402 — insufficient credits** and the run
belongs to the ADMIN account (``User.isAdmin = true``), the model chain must
continue with live-verified FREE OpenRouter models so the owner's pipeline
keeps producing. For EVERY other user the behaviour must stay byte-for-byte
what it is today (an honest ``LLMUnavailableError`` → HTTP 503).

Live facts these tests encode (all verified 2026-07-29 by the probe, see the
report above):
- a paid model on the app's own key returns HTTP 402 with body
  ``{"error":{"message":"Insufficient credits. ...","code":402,...}}``;
- free (``:free``) models return HTTP 200 on that SAME zero-credit key —
  OpenRouter's credit gate is per-model-price, not account-wide;
- ``openai/gpt-oss-20b:free`` (the old hardcoded ``FALLBACK_MODEL``) produced
  garbled multilingual output at realistic prompt lengths, so the verified
  working ids are the two nemotron ones asserted below.

Seams: these tests mock at ``httpx.post`` — the SAME seam
``test_llm_resilience.py::TestActiveCredentialSource`` uses — so the whole real
path runs (``_auto`` → ``_model_chain`` → ``_call_live`` → status classification).
Nothing about prompts, JSON validation or the downstream quality gates is
stubbed out.
"""
from __future__ import annotations

import pytest

from app.services.llm_client import (
    LLMClient,
    LLMUnavailableError,
    user_credential_context,
    user_model_context,
)

_PAID_PRIMARY = "deepseek/deepseek-v4-pro"
_PAID_FALLBACK = "deepseek/deepseek-v4-flash"
_FREE_A = "nvidia/nemotron-3-super-120b-a12b:free"
_FREE_B = "nvidia/nemotron-3-ultra-550b-a55b:free"

#: Verbatim body OpenRouter returned for a paid model on the app's own key
#: (probe artifact ``paid-model-claude-sonnet-5-response.json``, 2026-07-29).
_LIVE_402_BODY = (
    '{"error":{"message":"Insufficient credits. Add more using '
    'https://openrouter.ai/settings/credits","code":402,"metadata":'
    '{"limit_source":"openrouter_credits"}}}'
)


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _ok(content: str) -> _Resp:
    payload = {"choices": [{"message": {"content": content}}]}
    return _Resp(200, content, payload)


def _402() -> _Resp:
    return _Resp(402, _LIVE_402_BODY, {"error": {"code": 402}})


@pytest.fixture()
def openrouter_env(monkeypatch):
    """Env exactly like production: paid primary + PAID fallback, OpenRouter key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _PAID_PRIMARY)
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", _PAID_FALLBACK)
    monkeypatch.setenv("AETHER_ADMIN_FREE_FALLBACK_MODELS", f"{_FREE_A},{_FREE_B}")
    return None


def _install_transport(monkeypatch, responder):
    """Route every live call through ``responder(model_id)`` and record models."""
    import httpx

    seen: list[str] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        model = kwargs["json"]["model"]
        seen.append(model)
        return responder(model)

    monkeypatch.setattr(httpx, "post", _post)
    return seen


def _set_is_admin(user_id: str, value: bool) -> None:
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "isAdmin" = %s WHERE "id" = %s', (value, user_id)
            )
        conn.commit()


def _clear_admin_cache() -> None:
    from app.services import llm_client

    getattr(llm_client, "_admin_flag_cache", {}).clear()


# ---------------------------------------------------------------------------
# (a) classification
# ---------------------------------------------------------------------------


def test_openrouter_402_is_classified_as_insufficient_credits_error(
    monkeypatch, openrouter_env, tmp_path
):
    """FAILS NOW: llm_client.py:1681-1682 turns EVERY >=400 into a generic
    ``RuntimeError``, so a 402 is indistinguishable from a 404/500 and the
    admin rescue below has nothing to key off."""
    from app.services.llm_client import InsufficientCreditsError

    _install_transport(monkeypatch, lambda model: _402())
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with pytest.raises(InsufficientCreditsError) as excinfo:
        llm._call_live("sys", "usr", model=_PAID_PRIMARY, temperature=0.0)

    # Taxonomy: still a RuntimeError, so every existing `except Exception` /
    # `except RuntimeError` handler keeps catching it unchanged.
    assert isinstance(excinfo.value, RuntimeError)
    # Message keeps the current shape AND the provider body snippet.
    assert "LLM provider HTTP 402" in str(excinfo.value)
    assert "Insufficient credits" in str(excinfo.value)


def test_non_402_http_errors_stay_plain_runtime_errors(
    monkeypatch, openrouter_env, tmp_path
):
    """Contrast pin: only 402 is reclassified. A 404/429/500 must keep raising a
    plain ``RuntimeError`` so no other failure mode can trigger the free chain."""
    from app.services.llm_client import InsufficientCreditsError

    _install_transport(
        monkeypatch, lambda model: _Resp(404, '{"error":"No endpoints found"}')
    )
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        llm._call_live("sys", "usr", model=_PAID_PRIMARY, temperature=0.0)
    assert not isinstance(excinfo.value, InsufficientCreditsError)


def test_anthropic_402_is_not_reclassified(monkeypatch, tmp_path):
    """Billing separation: the rescue chain is OpenRouter-only, so a 402 from the
    DIRECT Anthropic transport must stay a plain ``RuntimeError`` (it can never
    pull an OpenRouter free model into an Anthropic-billed run)."""
    from app.services.llm_client import InsufficientCreditsError

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    _install_transport(monkeypatch, lambda model: _Resp(402, "payment required"))
    llm = LLMClient(mode="live", fixture_dir=tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        llm._call_live("sys", "usr", model="claude-sonnet-4-5", temperature=0.0)
    assert not isinstance(excinfo.value, InsufficientCreditsError)


# ---------------------------------------------------------------------------
# (b) admin rescue
# ---------------------------------------------------------------------------


def test_admin_402_continues_chain_into_first_free_model(
    monkeypatch, openrouter_env, tmp_path, caplog, client, auth_headers, test_user_id
):
    """FAILS NOW: today the chain is [paid primary, paid fallback]; both 402 and
    ``_auto`` raises ``LLMUnavailableError`` (→ 503). For the ADMIN account the
    chain must continue into the verified free models and return the first
    free model's real content."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    def _responder(model: str) -> _Resp:
        if model.endswith(":free"):
            return _ok("free model produced this")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with caplog.at_level("INFO"), user_credential_context(test_user_id, "coverLetter"):
        out = llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)

    assert out == "free model produced this"
    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK, _FREE_A], seen
    # Greppable marker for prod verification — the substitution is LOGGED,
    # never silent.
    assert any("admin-free-fallback" in rec.getMessage() for rec in caplog.records)
    marker = next(r for r in caplog.records if "admin-free-fallback" in r.getMessage())
    assert _FREE_A in marker.getMessage()
    assert "cover_letter" in marker.getMessage()
    assert test_user_id in marker.getMessage()


def test_admin_402_walks_to_the_second_free_model_when_the_first_fails(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """The free list is a CHAIN, not a single retry."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    def _responder(model: str) -> _Resp:
        if model == _FREE_B:
            return _ok("second free model produced this")
        if model == _FREE_A:
            return _Resp(429, "rate limited")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_credential_context(test_user_id, "coverLetter"):
        out = llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)

    assert out == "second free model produced this"
    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK, _FREE_A, _FREE_B], seen


def test_admin_free_chain_still_honours_the_json_validator(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """Design item 3: free attempts flow through the SAME ``_call_live`` path with
    the SAME validation — a free model returning garbage must NOT be accepted."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    def _responder(model: str) -> _Resp:
        if model.endswith(":free"):
            return _ok("not json at all <<<garbled>>>")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_credential_context(test_user_id, "storyExtractor"):
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("story_extractor", "sys", "usr", model=_PAID_PRIMARY)

    # Both free models were tried (each with its bounded same-model re-draft on
    # malformed content) and NONE of the garbage was returned to the caller.
    assert _FREE_A in seen and _FREE_B in seen, seen


# ---------------------------------------------------------------------------
# (c) non-admin — behaviour identical to today
# ---------------------------------------------------------------------------


def test_non_admin_402_behaviour_is_unchanged(
    monkeypatch, openrouter_env, tmp_path, caplog, client, auth_headers, test_user_id
):
    """PIN (passes BEFORE and AFTER): an ordinary user hitting a 402 gets exactly
    today's behaviour — the paid chain only, then ``LLMUnavailableError``
    carrying the 402 detail (routers map it to 503 + quota refund). No free
    model is ever attempted, and no rescue is logged."""
    _clear_admin_cache()

    def _responder(model: str) -> _Resp:
        if model.endswith(":free"):
            pytest.fail(f"free model {model} must NEVER be attempted for a non-admin")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with caplog.at_level("INFO"), user_credential_context(test_user_id, "coverLetter"):
        with pytest.raises(LLMUnavailableError) as excinfo:
            llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)

    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK], seen
    assert "LLM provider HTTP 402" in str(excinfo.value)
    assert "Insufficient credits" in str(excinfo.value)
    assert not any("admin-free-fallback" in r.getMessage() for r in caplog.records)


def test_no_user_context_402_behaviour_is_unchanged(
    monkeypatch, openrouter_env, tmp_path
):
    """PIN: background/CLI callers bind no user context at all — there is no
    identity to gate on, so the rescue must not engage."""

    def _responder(model: str) -> _Resp:
        if model.endswith(":free"):
            pytest.fail(f"free model {model} attempted with no user context")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with pytest.raises(LLMUnavailableError):
        llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)
    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK], seen


def test_admin_with_empty_free_list_behaves_like_today(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """Kill switch: ``AETHER_ADMIN_FREE_FALLBACK_MODELS=`` (empty) disables the
    rescue entirely, even for the admin — back to exactly today's behaviour."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()
    monkeypatch.setenv("AETHER_ADMIN_FREE_FALLBACK_MODELS", "")

    seen = _install_transport(monkeypatch, lambda model: _402())
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_credential_context(test_user_id, "coverLetter"):
        with pytest.raises(LLMUnavailableError):
            llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)
    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK], seen


# ---------------------------------------------------------------------------
# (d) admin + every free model also failing → honest failure
# ---------------------------------------------------------------------------


def test_admin_402_with_all_free_models_failing_raises_honestly(
    monkeypatch, openrouter_env, tmp_path, client, auth_headers, test_user_id
):
    """FAILS NOW (the free models are never attempted at all). After the fix the
    UX is unchanged when the rescue cannot help: the honest
    ``LLMUnavailableError`` still surfaces the 402 detail — no fixture, no fake
    success, no silent degradation."""
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    seen = _install_transport(monkeypatch, lambda model: _402())
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_credential_context(test_user_id, "coverLetter"):
        with pytest.raises(LLMUnavailableError) as excinfo:
            llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)

    assert seen == [_PAID_PRIMARY, _PAID_FALLBACK, _FREE_A, _FREE_B], seen
    assert "LLM provider HTTP 402" in str(excinfo.value)
    assert "Insufficient credits" in str(excinfo.value)


# ---------------------------------------------------------------------------
# (e) isAdmin lookup is cached (TTL)
# ---------------------------------------------------------------------------


def test_is_admin_lookup_is_cached_within_ttl(
    monkeypatch, client, auth_headers, test_user_id
):
    """FAILS NOW: ``_user_is_admin`` does not exist. After the fix a second call
    inside the TTL must not re-query the DB (one LLM call per prompt would
    otherwise mean one extra DB round-trip per call)."""
    from app.services.llm_client import _user_is_admin

    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    import app.db as db_module

    real = db_module.get_connection
    calls = {"n": 0}

    def _counting_get_connection(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(db_module, "get_connection", _counting_get_connection)

    assert _user_is_admin(test_user_id) is True
    assert calls["n"] == 1
    assert _user_is_admin(test_user_id) is True
    assert calls["n"] == 1, "second lookup inside the TTL must be served from cache"


def test_is_admin_lookup_failure_degrades_to_non_admin(monkeypatch):
    """A DB outage must never grant the rescue (fail CLOSED) and never break a
    run — and a failed lookup must NOT be cached as a negative."""
    from app.services.llm_client import _user_is_admin

    _clear_admin_cache()
    import app.db as db_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(db_module, "get_connection", _boom)
    assert _user_is_admin("some-user-id") is False

    from app.services import llm_client

    assert "some-user-id" not in llm_client._admin_flag_cache


# ---------------------------------------------------------------------------
# configuration surface
# ---------------------------------------------------------------------------


def test_free_fallback_defaults_to_the_live_verified_models(monkeypatch):
    """Works out of the box: unset env → the two probe-verified nemotron ids
    (``openai/gpt-oss-20b:free`` is deliberately EXCLUDED — it returned garbled
    output at realistic prompt length, PROBE-REPORT part 1d)."""
    from app.services.llm_client import get_admin_free_fallback_models

    monkeypatch.delenv("AETHER_ADMIN_FREE_FALLBACK_MODELS", raising=False)
    assert get_admin_free_fallback_models() == [_FREE_A, _FREE_B]


def test_free_fallback_list_is_env_overridable(monkeypatch):
    from app.services.llm_client import get_admin_free_fallback_models

    monkeypatch.setenv(
        "AETHER_ADMIN_FREE_FALLBACK_MODELS", " vendor/a:free , ,vendor/b:free "
    )
    assert get_admin_free_fallback_models() == ["vendor/a:free", "vendor/b:free"]


def test_hardcoded_fallback_model_is_a_working_free_model():
    """The D-0014 ``FALLBACK_MODEL`` constant must not point at the broken
    ``openai/gpt-oss-20b:free`` any more (same mechanism, working model)."""
    from app.services.llm_client import FALLBACK_MODEL

    assert FALLBACK_MODEL == _FREE_A


# ---------------------------------------------------------------------------
# ADR-ML-3 interaction (documented behaviour — see the fixer report)
# ---------------------------------------------------------------------------


def test_admin_user_chosen_model_402_still_rescues_and_logs(
    monkeypatch, openrouter_env, tmp_path, caplog, client, auth_headers, test_user_id
):
    """ADR-ML-3 keeps the chain at [chosen model] alone so a user-chosen model is
    never SILENTLY substituted. A 402 is not a model failure — it is a billing
    impossibility that no model choice can satisfy — so for the ADMIN account the
    operator-mandated rescue still engages, and it is LOGGED (not silent).

    For any NON-admin user ADR-ML-3 is untouched (pinned by
    ``test_non_admin_402_behaviour_is_unchanged`` and by
    ``test_ml_catalog_fix1.py::test_user_chosen_model_failure_does_not_silently_
    substitute_fallback``, which uses a 404 — the non-402 path).
    """
    _set_is_admin(test_user_id, True)
    _clear_admin_cache()

    def _responder(model: str) -> _Resp:
        if model.endswith(":free"):
            return _ok("free rescue for the admin's chosen-model run")
        return _402()

    seen = _install_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with caplog.at_level("INFO"), user_credential_context(test_user_id, "coverLetter"):
        with user_model_context(_PAID_PRIMARY):
            out = llm.complete("cover_letter", "sys", "usr", model=_PAID_PRIMARY)

    assert out == "free rescue for the admin's chosen-model run"
    # No PAID substitute was attempted — only the chosen model, then free.
    assert seen == [_PAID_PRIMARY, _FREE_A], seen
    assert any("admin-free-fallback" in r.getMessage() for r in caplog.records)
