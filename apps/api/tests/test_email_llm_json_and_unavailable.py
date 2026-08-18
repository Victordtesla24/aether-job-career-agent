"""Email Agent / Email Center — glm-5 JSON complete and honest 429 copy.

Production 2026-08-18 (prod-worker):

* ``POST /agents/email/run`` (mode=triage) on user-chosen ``z-ai/glm-5`` returned
  chain-of-thought in ``content``. ``complete_json`` ran ``json.loads`` on the
  whole string, failed with ``Expecting value: line 1 column 1``, same-model
  re-drafted identically, then surfaced the generic
  ``LLM_UNAVAILABLE_USER_MESSAGE`` ("The AI service is temporarily unavailable.
  Please try again in a moment.") — which is false: the provider answered.
* Minutes later ``claude-opus-4-8`` HTTP 429'd twice (RT-006 same-model retry)
  and the same generic sentence was shown.

ADR-ML-3 is unchanged: a user-chosen model stays a sole-model chain. These
tests lock the JSON-complete transport so that model can actually return JSON,
and lock honest user copy for 429 / unusable output. Ordinary prose
``.complete()`` must not pick up the JSON-only ``reasoning: {enabled: False}``
shaping (U1X-a pin).
"""
from __future__ import annotations

import copy
import json

import httpx
import pytest

from app.services.llm_client import (
    LLM_UNAVAILABLE_USER_MESSAGE,
    LLMClient,
    LLMUnavailableError,
    llm_failure_user_message,
)

_COT_THEN_JSON = (
    "The user wants recruiter triage. The first thread is a screening call "
    "request, so the score is high.\n"
    '{"items": [{"index": 0, "score": 88, "category": "priority"}]}'
)

_FENCED_IN_PROSE = (
    "Here is the triage result:\n"
    "```json\n"
    '{"items": [{"index": 0, "score": 88, "category": "priority"}]}\n'
    "```\n"
    "Hope that helps."
)

_TRUNCATED = '{"items": [{"index": 0, "score": 88, "category":'
_OPENROUTER_JSON_MODEL = "z-ai/glm-5"


class _Resp:
    def __init__(self, status_code: int, payload: dict, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> dict:
        return self._payload


def _ok(content: str) -> _Resp:
    return _Resp(200, {"choices": [{"message": {"content": content}}]}, content)


def _record_payloads(monkeypatch, responder):
    payloads: list[dict] = []

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        payloads.append(copy.deepcopy(kwargs["json"]))
        return responder(kwargs["json"])

    monkeypatch.setattr(httpx, "post", _post)
    return payloads


@pytest.fixture()
def openrouter_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.delenv("AETHER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ABACUS_API_KEY", raising=False)
    return None


class TestCompleteJsonExtractsUsableDocument:
    def test_cot_then_json_parses_the_object(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: _COT_THEN_JSON
        )
        parsed = llm.complete_json("email_triage", "s", "u")
        assert parsed["items"][0]["score"] == 88

    def test_prose_then_fenced_json_parses_the_object(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: _FENCED_IN_PROSE
        )
        parsed = llm.complete_json("email_triage", "s", "u")
        assert parsed["items"][0]["score"] == 88

    def test_empty_payload_still_raises(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", lambda self, *a, **k: "")
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("email_triage", "s", "u")

    def test_truncated_json_still_raises(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: _TRUNCATED
        )
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("email_triage", "s", "u")


class TestJsonCompleteDisablesReasoning:
    def test_json_complete_openrouter_body_disables_reasoning(
        self, monkeypatch, openrouter_env, tmp_path
    ):
        payloads = _record_payloads(
            monkeypatch,
            lambda _p: _ok('{"items":[{"index":0,"score":88,"category":"priority"}]}'),
        )
        parsed = LLMClient(mode="auto", fixture_dir=tmp_path).complete_json(
            "email_triage", "s", "u", model=_OPENROUTER_JSON_MODEL
        )
        assert parsed["items"][0]["score"] == 88
        assert payloads, "complete_json never reached OpenRouter"
        body = payloads[0]
        assert body.get("reasoning") == {"enabled": False}, body

    def test_ordinary_complete_does_not_add_reasoning(
        self, monkeypatch, openrouter_env, tmp_path
    ):
        payloads = _record_payloads(monkeypatch, lambda _p: _ok("plain prose"))
        text = LLMClient(mode="auto", fixture_dir=tmp_path).complete(
            "email_triage", "s", "u", model=_OPENROUTER_JSON_MODEL
        )
        assert text == "plain prose"
        assert payloads, "complete never reached OpenRouter"
        assert "reasoning" not in payloads[0], payloads[0]


class TestHonestUnavailableCopy:
    def test_429_is_not_generic_outage(self):
        from app.services.llm_client import LLM_RATE_LIMITED_USER_MESSAGE

        exc = LLMUnavailableError(
            "LLM backend unavailable: live call failed: LLM provider HTTP 429: "
            "rate limit for 'email_triage'"
        )
        msg = llm_failure_user_message(exc)
        assert msg == LLM_RATE_LIMITED_USER_MESSAGE
        assert "temporarily unavailable" not in msg.lower()
        assert "rate" in msg.lower() or "limit" in msg.lower()

    def test_unusable_json_is_not_generic_outage(self):
        from app.services.llm_client import LLM_UNUSABLE_OUTPUT_USER_MESSAGE

        inner = json.JSONDecodeError("Expecting value", "", 0)
        exc = LLMUnavailableError(
            "LLM backend unavailable: live call failed: Expecting value: "
            "line 1 column 1 (char 0) for 'email_triage'"
        )
        exc.__cause__ = inner
        msg = llm_failure_user_message(exc)
        assert msg == LLM_UNUSABLE_OUTPUT_USER_MESSAGE
        assert "temporarily unavailable" not in msg.lower()

    def test_malformed_json_phrase_is_not_generic_outage(self):
        from app.services.llm_client import LLM_UNUSABLE_OUTPUT_USER_MESSAGE

        exc = LLMUnavailableError(
            "LLM backend unavailable: live call for 'email_triage' returned "
            "malformed JSON"
        )
        msg = llm_failure_user_message(exc)
        assert msg == LLM_UNUSABLE_OUTPUT_USER_MESSAGE
        assert "temporarily unavailable" not in msg.lower()

    def test_generic_retryable_boom_keeps_existing_sentence(self):
        exc = LLMUnavailableError("boom")
        assert llm_failure_user_message(exc) == LLM_UNAVAILABLE_USER_MESSAGE
