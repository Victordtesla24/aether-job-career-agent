"""ML-pipeline-001 (HIGH) — failing tests BEFORE fix (MODELS-LIVE §7 step 2).

RCA verified against CURRENT code (2026-07-22):
- ``LLMClient.complete_json`` (apps/api/app/services/llm_client.py:1343-1366)
  calls ``self.complete(...)`` (which for ``mode="auto"`` runs ``_auto()``,
  llm_client.py:1373-1456) and THEN does its own ``json.loads(...)`` on the
  returned text.
- ``_auto()``'s per-model retry loop (llm_client.py:1408-1452) only treats a
  RAISED EXCEPTION from ``_call_live`` as an attempt failure worth trying the
  next model in the chain (``except Exception as exc: ... continue``). A
  live call that returns HTTP 200 with a malformed/truncated JSON body is not
  an exception — ``_call_live`` returns the string successfully, so ``_auto``
  takes the ``return content`` path on the FIRST model and never even looks
  at the fallback model.
- Back in ``complete_json`` (llm_client.py:1352-1366), ``json.loads`` on that
  malformed text raises ``json.JSONDecodeError``, which is immediately turned
  into ``LLMUnavailableError`` with NO retry attempted at all — a single
  garbled JSON response hard-fails the call even though the model-fallback
  retry machinery exists one layer down and is simply never reached for this
  failure mode.

Target behaviour (not yet implemented): a malformed-JSON response should be
treated as a retryable failure, bounded (e.g. 1-2 extra attempts), so a
transient garbled response doesn't hard-fail the whole call when a
well-formed response would follow on retry. Only once every attempt is
malformed should an honest ``LLMUnavailableError`` be raised (never a raw
``json.JSONDecodeError`` escaping the client).
"""
from __future__ import annotations

import pytest

from app.services.llm_client import LLMClient, LLMUnavailableError


class TestCompleteJsonRetriesMalformedResponse:
    def test_retries_after_malformed_json_then_succeeds(self, tmp_path, monkeypatch):
        """First live attempt returns malformed JSON; a bounded retry that
        then returns valid JSON should still let the call succeed.

        FAILS TODAY: ``complete_json`` never retries a parse failure — it
        converts the very first malformed response straight into
        ``LLMUnavailableError`` and the second (valid) response is never
        requested, so this call raises instead of returning ``{"ok": True}``.
        """
        calls = {"n": 0}

        def _call_live(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return "{not valid json"  # malformed / truncated live response
            return '{"ok": true}'

        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", _call_live)

        result = llm.complete_json("demo_prompt", "sys", "usr")

        assert result == {"ok": True}
        assert calls["n"] >= 2, (
            "complete_json() must retry at least once after a malformed-JSON "
            f"response before giving up (observed {calls['n']} live attempt(s))"
        )

    def test_persistently_malformed_response_is_retried_then_honest_error(
        self, tmp_path, monkeypatch
    ):
        """Every attempt returns malformed JSON: the retry must actually be
        ATTEMPTED (more than one live call) before an honest
        ``LLMUnavailableError`` is raised — never a raw ``JSONDecodeError``,
        and never given up on after a single malformed response.

        FAILS TODAY: only ONE live call is ever made (no retry loop reached
        for a parse failure), so ``calls["n"]`` stays at 1.
        """
        calls = {"n": 0}

        def _call_live(self, *a, **k):
            calls["n"] += 1
            return "{never valid json"

        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", _call_live)

        with pytest.raises(LLMUnavailableError):
            llm.complete_json("demo_prompt", "sys", "usr")

        assert calls["n"] >= 2, (
            "a malformed JSON response must trigger at least one retry "
            f"attempt before giving up (observed {calls['n']} live attempt(s))"
        )
        # Bounded — a persistently-malformed backend must not be hammered
        # indefinitely.
        assert calls["n"] <= 4, (
            f"retry must be BOUNDED, observed {calls['n']} live attempts"
        )
