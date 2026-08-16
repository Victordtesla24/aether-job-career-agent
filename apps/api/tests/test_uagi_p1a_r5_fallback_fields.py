"""U-AGI P1-A / R-5 — a served-model substitution must be VISIBLE, not just logged.

SYNTHESIS.md R-5: the substitution IS recorded server-side and correctly costed,
and is invisible in the FE (``grep -rn requestedModel apps/web/src`` → 0 hits).
In a 19-step plan narration, green steps that quietly ran on a rescue model are
exactly the "graceful fiction" DESIGN-PRINCIPLE.md forbids.

P1-A adds the three additive payload fields the FE (P1-B) renders as a chip:
``requestedModel`` (intent), ``servedModel`` (observation) and ``fallbackReason``
(the mechanism that engaged, published by the mechanism itself — never inferred).

PINs that must hold: no substitution → no ``requestedModel``/``fallbackReason``,
and nothing is fabricated when the client observed nothing. (Updated per
Architect decision audit wf_9a87f76f-eaa Track E (D5): ``servedModel`` — plus
``servedProvider`` — is now ALWAYS disclosed on a run that reached an LLM, so
the original "ordinary run grows no keys" pin narrowed to the two intent/reason
fields; see test_cli_d5_served_model_disclosure.py.)
"""
from __future__ import annotations

import pytest

_PRIMARY = "deepseek/deepseek-v4-pro"
_FALLBACK = "deepseek/deepseek-v4-flash"


class _Resp:
    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _ok(content: str, served_model: str) -> _Resp:
    return _Resp(
        200, content, {"choices": [{"message": {"content": content}}], "model": served_model}
    )


def _install_transport(monkeypatch, responder):
    import httpx

    seen: list[str] = []

    def _post(url, **kwargs):  # noqa: ANN001
        model = kwargs["json"]["model"]
        seen.append(model)
        return responder(model)

    monkeypatch.setattr(httpx, "post", _post)
    return seen


@pytest.fixture()
def openrouter_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _PRIMARY)
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", _FALLBACK)
    return None


# ---------------------------------------------------------------------------
# The client publishes WHY it moved off the primary — observation, not guess.
# ---------------------------------------------------------------------------


def test_no_fallback_reason_is_published_when_the_primary_serves(
    monkeypatch, openrouter_env, tmp_path
):
    from app.services.llm_client import (
        LLMClient,
        get_last_fallback_reason,
        served_model_capture,
    )

    _install_transport(monkeypatch, lambda m: _ok("hi", m))
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with served_model_capture():
        llm.complete("test_prompt", "sys", "usr", fixture_key="k")
        assert get_last_fallback_reason() is None


def test_the_fallback_reason_names_the_failure_class_that_ended_the_primary(
    monkeypatch, openrouter_env, tmp_path
):
    from app.services.llm_client import (
        LLMClient,
        get_last_fallback_reason,
        get_last_served_model,
        served_model_capture,
    )

    def responder(model: str) -> _Resp:
        if model == _PRIMARY:
            return _Resp(503, "upstream down", {})
        return _ok("hi", model)

    _install_transport(monkeypatch, responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with served_model_capture():
        llm.complete("test_prompt", "sys", "usr", fixture_key="k")
        assert get_last_served_model() == _FALLBACK
        reason = get_last_fallback_reason()
        assert reason and _PRIMARY in reason
        assert "retryable" in reason or "503" in reason


def test_the_reason_scope_resets_between_runs(monkeypatch, openrouter_env, tmp_path):
    from app.services.llm_client import (
        LLMClient,
        get_last_fallback_reason,
        served_model_capture,
    )

    def responder(model: str) -> _Resp:
        if model == _PRIMARY:
            return _Resp(503, "down", {})
        return _ok("hi", model)

    _install_transport(monkeypatch, responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)
    with served_model_capture():
        llm.complete("test_prompt", "sys", "usr", fixture_key="k")
        assert get_last_fallback_reason() is not None
    with served_model_capture():
        assert get_last_fallback_reason() is None


# ---------------------------------------------------------------------------
# The run payload the FE already consumes carries the triple.
# ---------------------------------------------------------------------------


def _run_with_observation(monkeypatch, *, served, reason, intended):
    """Drive ``_execute_reserved_run``'s costing tail with a controlled
    observation, exactly as the live client would publish it."""
    from app.routers import agents as agents_mod

    monkeypatch.setattr(agents_mod, "get_last_served_model", lambda: served)
    monkeypatch.setattr(agents_mod, "get_last_fallback_reason", lambda: reason)
    monkeypatch.setattr(
        agents_mod, "_model_for_agent", lambda name, override=None: intended
    )
    return agents_mod


def test_a_substitution_records_all_three_fields_on_the_run_output(
    client, auth_headers, test_user_id, monkeypatch
):
    from app.routers import agents as agents_mod

    _run_with_observation(
        monkeypatch, served=_FALLBACK, reason="primary deepseek/x failed (retryable)",
        intended=_PRIMARY,
    )
    out = agents_mod._record_run(
        test_user_id, "storyExtractor", {}, lambda: {"stories": []}
    )
    assert out["requestedModel"] == _PRIMARY
    assert out["servedModel"] == _FALLBACK
    assert out["model"] == _FALLBACK
    assert out["fallbackReason"] == "primary deepseek/x failed (retryable)"


def test_an_ordinary_run_gains_only_the_d5_disclosure_keys(
    client, auth_headers, test_user_id, monkeypatch
):
    """PIN, updated per Architect decision audit wf_9a87f76f-eaa Track E (D5):
    no substitution still means no ``requestedModel`` and no ``fallbackReason``
    — but a run that reached an LLM now ALWAYS discloses ``servedModel`` (and
    its billing provider), matching the observation, even when it equals the
    intent. (Previously this pinned ``servedModel`` absent — the exact silence
    D5 flags: the run record never named the model that actually served.)"""
    from app.routers import agents as agents_mod

    _run_with_observation(
        monkeypatch, served=_PRIMARY, reason=None, intended=_PRIMARY
    )
    out = agents_mod._record_run(
        test_user_id, "storyExtractor", {}, lambda: {"stories": []}
    )
    assert "requestedModel" not in out
    assert "fallbackReason" not in out
    assert out["servedModel"] == _PRIMARY
    assert out["servedProvider"] == "openrouter"
    assert out["model"] == _PRIMARY


def test_nothing_is_fabricated_when_the_client_observed_nothing(
    client, auth_headers, test_user_id, monkeypatch
):
    from app.routers import agents as agents_mod

    _run_with_observation(monkeypatch, served=None, reason=None, intended=_PRIMARY)
    out = agents_mod._record_run(
        test_user_id, "storyExtractor", {}, lambda: {"stories": []}
    )
    assert "servedModel" not in out
    assert "servedProvider" not in out  # D5 keys are observation-gated too
    assert "fallbackReason" not in out


def test_a_substitution_with_no_published_reason_still_records_the_two_models(
    client, auth_headers, test_user_id, monkeypatch
):
    """Honest partial knowledge: the models are observed, the reason was not
    published — so no reason is invented."""
    from app.routers import agents as agents_mod

    _run_with_observation(
        monkeypatch, served=_FALLBACK, reason=None, intended=_PRIMARY
    )
    out = agents_mod._record_run(
        test_user_id, "storyExtractor", {}, lambda: {"stories": []}
    )
    assert out["requestedModel"] == _PRIMARY
    assert out["servedModel"] == _FALLBACK
    assert "fallbackReason" not in out


def test_the_fields_survive_onto_the_persisted_run_row(
    client, auth_headers, test_user_id, monkeypatch
):
    """The FE reads ``AgentRun.output`` through ``GET /agents/runs`` — the
    fields must be on the persisted row, not only the HTTP response."""
    from app.routers import agents as agents_mod

    _run_with_observation(
        monkeypatch, served=_FALLBACK, reason="out of credits", intended=_PRIMARY
    )
    agents_mod._record_run(test_user_id, "storyExtractor", {}, lambda: {"stories": []})

    runs = client.get("/agents/runs", headers=auth_headers).json()
    row = next(r for r in runs if r["agentName"] == "storyExtractor")
    assert row["output"]["servedModel"] == _FALLBACK
    assert row["output"]["requestedModel"] == _PRIMARY
    assert row["output"]["fallbackReason"] == "out of credits"
