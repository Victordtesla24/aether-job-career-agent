"""MON-019 — transport parameter safety when a provider REJECTS ``temperature``.

RCA (evidence: ``uat/reports/evidence/market-perf/mon-019/``). The reported
"regression since the 2026-08-13T21:04:17Z U1X deploy" is NOT one: all 65
``"`temperature` is deprecated for this model."`` HTTP 400s live at
``/var/log/aether/api.log`` lines 3817-14774, i.e. BEFORE the first
ISO-timestamped line (42076 = 2026-07-18T22:39:20Z) in a file created
2026-07-11; ZERO occurrences follow the deploy's restart marker (line 629210).
They date to the pre-provider-split transport (commit ee59bc5, 2026-07-13),
which posted ONE body — ``{model, temperature, messages}`` — to
``{AETHER_LLM_BASE_URL}/chat/completions`` for EVERY model id, including the
gateway's ``claude-fable-5``. The 2026-07-14 split (``resolve_provider``) sent
bare ``claude-*`` to the native Anthropic Messages API, whose builder omits
``temperature``/``top_p`` outright — which is why the signature stopped.

What the RCA leaves LIVE is the other half of that transport. The OpenRouter /
OpenAI-compatible body still carries ``temperature`` unconditionally, and users
pick their own model from the live catalog (ADR-ML-4 notes 50+ Anthropic-served
entries that use native params instead of ``temperature``). A user-CHOSEN model
gets a single-model chain (ADR-ML-3, no substitution), so one parameter-shape
400 spends the whole run — the exact production failure above, reachable
through a different door.

The fix is a bounded, honest re-send of the SAME model with only the rejected
parameter dropped, plus a warning log — the pattern already used for the
free-chain ``reasoning`` rejection. NOT a model substitution, NOT a silent
fallback: the model, prompt, credential and every downstream guard are
unchanged, and a 400 that does not explicitly name the parameter is still spent
on the first request exactly as today.
"""
from __future__ import annotations

import copy

import pytest

from app.services.llm_client import (
    LLMClient,
    LLMUnavailableError,
    build_anthropic_request,
    user_model_context,
)

#: The user's deliberately chosen OpenRouter model for these tests.
#:
#: MODEL-SUB-QUOTA (OWNER DIRECTIVE 2026-08-17): this was
#: ``anthropic/claude-fable-5``. A Claude id in ANY spelling is now served by
#: the operator's Anthropic subscription over the native Messages API, whose
#: builder omits ``temperature`` outright — so a Claude id can no longer reach
#: the OpenAI-compatible body this file is about. The scenario is unchanged:
#: ADR-ML-4 notes 50+ OpenRouter-served entries that use native params instead
#: of ``temperature``, and one of those is what a user picks here.
_CHOSEN = "mistralai/mistral-large-3"
_FALLBACK = "deepseek/deepseek-v4-flash"

#: Verbatim provider body from the production log (api.log:3817), the signature
#: MON-019 was filed on.
_LIVE_400_TEMPERATURE_BODY = (
    '{"error":{"code":"invalid_request_error","message":"`temperature` is '
    'deprecated for this model.","type":"invalid_request_error","param":null}}'
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
    return _Resp(200, content, {"choices": [{"message": {"content": content}}]})


_GOOD_CONTENT = '{"hook_reason": "x", "body": "a\\n\\nb"}'


@pytest.fixture()
def openrouter_env(monkeypatch):
    """Production-shaped env: an OpenRouter key and nothing cross-provider."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("AETHER_MODEL_REASONING", _CHOSEN)
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", _FALLBACK)
    return None


def _install_payload_transport(monkeypatch, responder):
    """Record every outgoing JSON body and answer via ``responder(payload)``."""
    import httpx

    payloads: list[dict] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        payload = kwargs["json"]
        payloads.append(copy.deepcopy(payload))
        return responder(payload)

    monkeypatch.setattr(httpx, "post", _post)
    return payloads


def test_temperature_rejection_is_resent_once_without_the_parameter(
    monkeypatch, openrouter_env, tmp_path, caplog
):
    """FAILS NOW: the 400 spends the user's chosen model and the run dies 503.

    The provider names the parameter explicitly, so the attempt is re-sent ONCE
    with just that key removed — same model, same prompt, same credential.
    """

    def _responder(payload: dict) -> _Resp:
        if "temperature" in payload:
            return _Resp(400, _LIVE_400_TEMPERATURE_BODY)
        return _ok(_GOOD_CONTENT)

    payloads = _install_payload_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with caplog.at_level("WARNING"):
        with user_model_context(_CHOSEN):
            out = llm.complete("cover_letter", "sys", "usr", model=_CHOSEN)

    assert out == _GOOD_CONTENT
    assert [p["model"] for p in payloads] == [_CHOSEN, _CHOSEN], payloads
    assert "temperature" in payloads[0]
    assert "temperature" not in payloads[1]
    # ONLY the rejected key is dropped: prompt and the U1X-a token bound stay.
    assert payloads[1]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]
    assert payloads[1]["max_tokens"] == payloads[0]["max_tokens"]
    # The recovery is LOUD — never a silent parameter change.
    assert any(
        "temperature" in r.getMessage() and _CHOSEN in r.getMessage()
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_temperature_resend_never_substitutes_the_model(
    monkeypatch, openrouter_env, tmp_path
):
    """ADR-ML-3 pin: the re-send is the SAME model — the fallback never runs."""

    def _responder(payload: dict) -> _Resp:
        if "temperature" in payload:
            return _Resp(400, _LIVE_400_TEMPERATURE_BODY)
        return _ok(_GOOD_CONTENT)

    payloads = _install_payload_transport(monkeypatch, _responder)
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_model_context(_CHOSEN):
        llm.complete("cover_letter", "sys", "usr", model=_CHOSEN)

    assert _FALLBACK not in [p["model"] for p in payloads], payloads


def test_a_400_that_does_not_name_the_parameter_is_never_resent(
    monkeypatch, openrouter_env, tmp_path
):
    """ZERO-REGRESSION PIN: a generic 400 keeps today's behaviour — one request
    for the model, then the chain moves on. No blind reshaping loop."""
    payloads = _install_payload_transport(
        monkeypatch, lambda payload: _Resp(400, '{"error":{"code":400}}')
    )
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with pytest.raises(LLMUnavailableError):
        llm.complete("cover_letter", "sys", "usr", model=_CHOSEN)

    assert [p["model"] for p in payloads] == [_CHOSEN, _FALLBACK], payloads


def test_temperature_resend_is_bounded_to_one_extra_request(
    monkeypatch, openrouter_env, tmp_path
):
    """A model that 400s on BOTH shapes is honestly spent: exactly two requests
    for that model, then an honest failure — never an unbounded retry."""
    payloads = _install_payload_transport(
        monkeypatch, lambda payload: _Resp(400, _LIVE_400_TEMPERATURE_BODY)
    )
    llm = LLMClient(mode="auto", fixture_dir=tmp_path)

    with user_model_context(_CHOSEN):
        with pytest.raises(LLMUnavailableError):
            llm.complete("cover_letter", "sys", "usr", model=_CHOSEN)

    assert [p["model"] for p in payloads] == [_CHOSEN, _CHOSEN], payloads


def test_anthropic_native_transport_never_sends_temperature():
    """RCA-(b) pin: the direct-Anthropic body carries no ``temperature`` —
    the structural reason the July signature stopped at the provider split."""
    req = build_anthropic_request(
        "claude-opus-4-8", "sys", "usr", auth_mode="api_key", secret="sk-ant-test",
    )
    assert "temperature" not in req["json"]
    assert "top_p" not in req["json"]
