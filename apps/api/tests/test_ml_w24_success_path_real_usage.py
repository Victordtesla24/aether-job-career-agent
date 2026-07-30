"""W-24 (HIGH) — a genuinely SUCCESSFUL run must be costed off the REAL
accumulated LLM usage, not the tiny run-trigger params dict.

Finding: uat/reports/evidence/prod-verify-4/PROD-VERIFY-4.json QA4-F-01. W-22
fixed the guard-rejection DEGRADE branch to read real accumulated usage
(MF-1), but left the genuine-SUCCESS branch (apps/api/app/routers/agents.py,
the ``else:`` clause in ``_execute_reserved_run``'s costing tail) on the old
estimate: ``tokens_in = max(1, len(json.dumps(params, default=str)) // 4) +
400``. ``params`` is the tiny run-trigger dict (e.g. ``{"job_id": ...}``, ~50
chars) — NOT the real prompt sent to the LLM (job description + résumé +
career evidence, often 1000s of chars) — so tokensIn was a near-constant 414
regardless of the real prompt size.

Live A/B proof (same build/model/agent, 5 minutes apart): a 4-call DEGRADE
recorded tokensIn=26263/tokensOut=2042/$0.030347 (the W-22-fixed branch,
reading real accumulated usage); a 3-call SUCCESS recorded
tokensIn=414/tokensOut=524/$0.001462 (the untouched branch) — a ~16x
under-report on the revenue-generating path, with the perverse result that a
run producing NOTHING was costed more accurately than one that shipped a
letter.

Fix: read ``llm_client.get_accumulated_usage()`` (the same ContextVar W-22
added) on the success path too, captured inside the ``served_model_capture()``
scope alongside ``_served_model`` — falling back to the legacy params/output
estimate ONLY when nothing was accumulated (replay/fixture-mode tests, where
no live ``_call_live`` call is ever made, and deterministic agents, which
never reach this branch at all).
"""
from __future__ import annotations

import json

import pytest

from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _price_guarding_down_pricing, _record_run


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")


_SERVED_MODEL = "deepseek/deepseek-v4-pro"

#: Realistic cover-letter-sized prompt/response — real prompts run to
#: thousands of chars (job description + résumé + career evidence); the tiny
#: ``{"job_id": ...}`` params dict the old code measured is nowhere close.
_REAL_SYSTEM = "You are a truthful cover-letter writer." * 5  # 205 chars
_REAL_USER = "Target role: Staff Engineer at Acme.\nJob description:\n" + ("x" * 6000)
_REAL_LETTER = "Dear Hiring Manager,\n" + ("y" * 500)


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _install_transport(monkeypatch, served_model: str, n_calls: int, content: str) -> None:
    """Every one of the first ``n_calls`` live calls succeeds and echoes
    ``served_model`` + ``content`` — real usage accumulates across all of
    them (mirrors test_ml_w22_degraded_cost_recording.py's transport mock)."""
    import httpx

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        return _Resp(
            200, content,
            {"choices": [{"message": {"content": content}}], "model": served_model},
        )

    monkeypatch.setattr(httpx, "post", _post)


def _run_genuine_success_with_n_real_calls(
    monkeypatch, tmp_path, user_id: str, *, n: int, served_model: str = _SERVED_MODEL,
) -> dict:
    """A coverLetter run whose callable makes ``n`` REAL, successfully-served
    LLM calls (mirroring the corrective loop's draft + retries all succeeding
    on content too) and then returns a genuine successful result — no
    exception, a real ``cover_letter_id``."""
    from app.services.llm_client import LLMClient

    _install_transport(monkeypatch, served_model, n, _REAL_LETTER)

    def _fn():
        llm = LLMClient(mode="live", fixture_dir=tmp_path)
        for _ in range(n):
            llm._call_live(_REAL_SYSTEM, _REAL_USER, model=served_model, temperature=0.0)
        return {"cover_letter_id": "cl_1", "approval_status": "pending"}

    return _record_run(user_id, "coverLetter", {"job_id": "j"}, _fn)


class TestSuccessPathRecordsRealAccumulatedUsage:
    def test_tokens_reflect_the_real_accumulated_prompt_not_the_tiny_params_dict(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        ensure_user_billing(test_user_id)

        out = _run_genuine_success_with_n_real_calls(
            monkeypatch, tmp_path, test_user_id, n=3,
        )

        expected_chars_in = 3 * (len(_REAL_SYSTEM) + len(_REAL_USER))
        expected_chars_out = 3 * len(_REAL_LETTER)
        assert out["tokensIn"] == max(1, expected_chars_in // 4), (
            f"tokensIn must reflect the REAL accumulated prompt size across all "
            f"3 calls, not a near-constant estimate off the tiny params dict — "
            f"got {out['tokensIn']!r}"
        )
        assert out["tokensOut"] == max(1, expected_chars_out // 4)
        # The old (wrong) measurement target: params={"job_id": "j"} is ~14
        # chars -> 14//4=3, +400 fixed offset = 403. The real prompt above is
        # >6000 chars per call; the fix must clear that old figure by orders
        # of magnitude, not sit near it.
        assert out["tokensIn"] > 403 * 10, (
            "tokensIn must be far larger than the old params-based estimate "
            f"(403) for a multi-thousand-char real prompt — got {out['tokensIn']!r}"
        )

    def test_cost_matches_real_usage_not_the_legacy_estimate(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        ensure_user_billing(test_user_id)

        out = _run_genuine_success_with_n_real_calls(
            monkeypatch, tmp_path, test_user_id, n=3,
        )
        # Priced via the SAME shared MF-2 rail production code applies (the
        # fixture's AETHER_MODEL_REASONING may resolve to a priced static-
        # catalog entry that differs from _SERVED_MODEL's own price, in which
        # case the down-pricing rail legitimately picks the intended model's
        # price — substitution/pricing behaviour has its own dedicated tests
        # elsewhere; this test is about tokensIn/tokensOut, not which price
        # wins).
        price_in, price_out = _price_guarding_down_pricing(
            _SERVED_MODEL, out.get("requestedModel")
        )
        expected_cost = round(
            out["tokensIn"] / 1000 * price_in + out["tokensOut"] / 1000 * price_out, 6,
        )
        assert out["costUsd"] == pytest.approx(expected_cost)
        # The old estimate for THIS SAME run's params ({"job_id": "j"}, tiny)
        # would have booked a near-constant 403 tokensIn regardless of the
        # real multi-thousand-char prompt above — the fix must clear that
        # old figure by a wide margin (live evidence: a comparable 3-call
        # run booked tokensIn=414 -> $0.001462 under the old code).
        legacy_tokens_in = max(1, len(json.dumps({"job_id": "j"}, default=str)) // 4) + 400
        legacy_cost = round(legacy_tokens_in / 1000 * price_in, 6)
        assert out["costUsd"] > legacy_cost * 5, (
            f"expected a cost far above the old params-based estimate "
            f"(${legacy_cost!r}) — got ${out['costUsd']!r}"
        )

    def test_agentrun_row_and_spend_cap_both_see_the_real_cost(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        ensure_user_billing(test_user_id)
        quotas = UsageQuotaRepository()
        before = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)

        out = _run_genuine_success_with_n_real_calls(
            monkeypatch, tmp_path, test_user_id, n=3,
        )

        runs = [
            r for r in AgentRunRepository().list_recent(test_user_id)
            if r["agentName"] == "coverLetter"
        ]
        assert runs
        # The AgentRun.costUsd DB column is DECIMAL(10,4) (packages/db/src/
        # schema.prisma) — coarser than the JSON output's 6dp float — so
        # compare at 4dp precision rather than exact/tight-relative equality.
        assert float(runs[0]["costUsd"] or 0) == pytest.approx(out["costUsd"], abs=5e-5)
        after = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)
        assert after - before == pytest.approx(out["costUsd"], abs=5e-5), (
            "the USD spend cap must accrue the CORRECTED (real-usage) cost, "
            "not the old under-reported estimate"
        )


class TestReplayModeFallbackAndDeterministicPinsUnchanged:
    """PINs — must pass BEFORE and AFTER this fix."""

    def test_replay_mode_success_falls_back_to_the_legacy_estimate(
        self, client, auth_headers, test_user_id,
    ):
        """No live _call_live means no accumulated usage — storyExtractor
        runs against committed fixtures in replay mode (the whole suite's
        default), so it must keep recording SOMETHING sane via the fallback,
        not a zero/crash from an empty accumulation."""
        res = client.post("/agents/story-extractor/run", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["tokensIn"] > 0
        assert body["tokensOut"] > 0
        assert body["costUsd"] > 0

    def test_deterministic_agent_still_records_zero_cost_and_null_model(
        self, client, auth_headers, test_user_id,
    ):
        """PIN (mirrors test_ml_w14's identical pin): a deterministic agent
        (no LLM tier at all) must be entirely unaffected by this fix — it
        never reaches the ``else:`` branch this fix touches."""
        out = _record_run(test_user_id, "scout", {}, lambda: {"jobs": 0})
        assert out["model"] is None
        assert out["costUsd"] == 0.0
        assert out["tokensIn"] == 0
        assert out["tokensOut"] == 0
