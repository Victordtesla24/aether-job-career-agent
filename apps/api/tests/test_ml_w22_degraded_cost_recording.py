"""W-22 (MED) — degraded cover-letter completions must record the REAL model,
tokens and cost for the LLM calls that were actually made, never NULL.

Finding: uat/reports/evidence/prod-verify-3/PROD-VERIFY-3.json QA3-F-05. The
corrective drafting loop inside ``CoverLetterAgent.run()`` makes real,
successfully-served LLM calls on each retry — the fabrication/§10.2 guard
rejects the CONTENT of the final draft, not the call itself. But
``_execute_reserved_run``'s ``except (FabricationError, StructuralError)``
handler (apps/api/app/routers/agents.py) hardcoded ``cost_usd=0.0`` and never
recorded a model, discarding the real spend those calls incurred. The mirrored
async handler (apps/api/app/workers/tasks.py::run_agent_job) inherited the
same gap on its own BackgroundJob result, and never accrued that spend against
the USD spend cap either.

Root-cause seam: ``llm_client.get_last_served_model()`` DOES observe the
served id of the last successful call inside the corrective loop, but
``served_model_capture()``'s context manager resets that observation (via its
``finally``) the instant its ``with`` block unwinds — which happens BEFORE the
outer ``except (FabricationError, StructuralError)`` clause runs, since the
``with`` sits INSIDE that outer ``try``. By the time the guard-rejection
handler asks, the observation is already gone. The fix captures it INSIDE the
scope, the instant the exception is caught.
"""
from __future__ import annotations

import asyncio

import pytest

from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _price_for, _record_run

# ``bg_table`` must be imported at MODULE scope (not inside a test function) for
# pytest to register it as a usable fixture — mirrors
# test_ml_cover002_async_degrade.py's identical top-level import.
from test_gap_p7_async_001 import (  # noqa: E402,F401 pylint: disable=wrong-import-position
    _get_bg_job,
    _seed_bg_job,
    _set_paid_plan,
    bg_table,
)


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p4_002_guard_degrade).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")
    # The served model used below (a slash id) resolves to the OpenRouter
    # provider (resolve_provider's slash-id rule); a real live call needs a
    # resolvable credential, so provide the server-env fallback key.
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")


_SERVED_MODEL = "deepseek/deepseek-v4-pro"


class _Resp:
    """Minimal httpx.Response stand-in (status_code / text / json())."""

    def __init__(self, status_code: int, text: str, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        return self._payload


def _install_transport(monkeypatch, served_model: str) -> None:
    """Every live call succeeds and echoes ``served_model`` as the provider's
    own ``model`` field — the exact shape ``_publish_served_model`` reads
    (mirrors test_ml_w14_served_model_billing.py's ``_install_transport``)."""
    import httpx

    def _post(url, **kwargs):  # noqa: ANN001 — httpx.post signature
        return _Resp(
            200,
            "content",
            {"choices": [{"message": {"content": "content"}}], "model": served_model},
        )

    monkeypatch.setattr(httpx, "post", _post)


def _guard_errors():
    from app.agents.cover_letter_agent import FabricationError, StructuralError

    return FabricationError, StructuralError


def _latest_cover_run(user_id: str) -> dict:
    runs = [
        r
        for r in AgentRunRepository().list_recent(user_id)
        if r["agentName"] == "coverLetter"
    ]
    assert runs, "no coverLetter AgentRun was recorded"
    return runs[0]


def _run_with_a_real_call_then_rejection(
    monkeypatch, tmp_path, user_id: str, exc: Exception, served_model: str = _SERVED_MODEL
):
    """A coverLetter run whose callable makes ONE real, successfully-served LLM
    call (mirroring the corrective loop's earlier retries) and then raises —
    simulating the guard rejecting the FINAL draft's content after the model
    itself already responded successfully at least once."""
    from app.services.llm_client import LLMClient

    _install_transport(monkeypatch, served_model)

    def _fn():
        llm = LLMClient(mode="live", fixture_dir=tmp_path)
        llm._call_live("sys", "usr", model=served_model, temperature=0.0)
        raise exc

    return _record_run(user_id, "coverLetter", {"job_id": "j"}, _fn)


class TestDegradedRunAfterARealCallRecordsRealCost:
    def test_fabrication_rejection_after_a_served_call_records_real_model_and_cost(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)

        with pytest.raises(FabricationError):
            _run_with_a_real_call_then_rejection(
                monkeypatch, tmp_path, test_user_id, FabricationError(["Acme Corp"]),
            )

        run = _latest_cover_run(test_user_id)
        assert run["status"] == "completed"
        output = run["output"] or {}
        assert output.get("coverLetterUnavailable") is True
        assert output.get("model") == _SERVED_MODEL, (
            "a real LLM call served this run before the guard rejected the "
            f"draft's content — got model={output.get('model')!r}"
        )
        assert output.get("tokensIn", 0) > 0
        assert output.get("tokensOut", 0) > 0
        assert float(output.get("costUsd") or 0) > 0, (
            "real cost was incurred for the served call — must not be zeroed"
        )
        assert float(run["costUsd"] or 0) > 0, (
            "the AgentRun row's own costUsd column must also be non-zero"
        )
        price_in, price_out = _price_for(_SERVED_MODEL)
        expected = round(
            output["tokensIn"] / 1000 * price_in + output["tokensOut"] / 1000 * price_out,
            6,
        )
        assert output["costUsd"] == pytest.approx(expected)

    def test_structural_rejection_after_a_served_call_also_records_real_cost(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        _, StructuralError = _guard_errors()
        ensure_user_billing(test_user_id)

        with pytest.raises(StructuralError):
            _run_with_a_real_call_then_rejection(
                monkeypatch, tmp_path, test_user_id,
                StructuralError(["missing closing"]),
            )

        run = _latest_cover_run(test_user_id)
        output = run["output"] or {}
        assert output.get("model") == _SERVED_MODEL
        assert float(output.get("costUsd") or 0) > 0

    def test_guard_rejection_still_refunds_the_run_count_reservation(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        """The realized USD cost is now recorded, but the RUN-COUNT
        reservation is still refunded — two separate ledgers. A degrade is
        never billed against the user's run allowance."""
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)

        before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
        with pytest.raises(FabricationError):
            _run_with_a_real_call_then_rejection(
                monkeypatch, tmp_path, test_user_id, FabricationError(["term"]),
            )
        after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
        assert after == before == 0

    def test_guard_rejection_cost_is_included_in_the_spend_cap(
        self, client, auth_headers, test_user_id, monkeypatch, tmp_path,
    ):
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)
        quotas = UsageQuotaRepository()
        before = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)

        with pytest.raises(FabricationError):
            _run_with_a_real_call_then_rejection(
                monkeypatch, tmp_path, test_user_id, FabricationError(["term"]),
            )

        after = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)
        assert after > before, (
            "a real LLM cost was incurred even though no letter shipped — the "
            "USD spend cap must see it (QA3-F-05)"
        )


class TestGenuinelyFailedBeforeAnyCallStillRecordsZero:
    """PIN — must pass BEFORE and AFTER this fix (mirrors
    test_gap_p4_002_guard_degrade.py's existing, unchanged assertion)."""

    def test_guard_rejection_with_no_served_call_still_records_zero(
        self, client, auth_headers, test_user_id,
    ):
        FabricationError, _ = _guard_errors()
        ensure_user_billing(test_user_id)

        def _raise():
            raise FabricationError(["term"])

        with pytest.raises(FabricationError):
            _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _raise)

        run = _latest_cover_run(test_user_id)
        output = run["output"] or {}
        assert output.get("model") is None
        assert float(output.get("costUsd") or 0) == 0.0
        assert float(run["costUsd"] or 0) == 0.0

    def test_llm_unavailable_on_first_draft_still_records_zero(
        self, client, auth_headers, test_user_id,
    ):
        """The OTHER genuinely-zero-cost degrade shape (cover _draft()
        resilience — an LLM failure on the very first draft, no exception
        raised, ``cover_letter_unavailable`` returned in the output instead).
        Untouched by this fix; still records honest zero."""
        ensure_user_billing(test_user_id)

        def _fn():
            return {
                "cover_letter_id": None,
                "coverLetterUnavailable": True,
                "message": "The cover letter couldn't be generated because the "
                "writing model was temporarily unavailable.",
            }

        out = _record_run(test_user_id, "coverLetter", {"job_id": "j"}, _fn)
        assert out["model"] is None
        assert out["costUsd"] == 0.0


class TestAsyncWorkerMirrorsTheSameFix:
    """The async single-agent worker (``manage_quota=False``) records its own
    spend on the BackgroundJob result via the SAME computed usage, carried on
    the exception as ``degradedUsage``."""

    def test_async_guard_rejection_after_served_call_records_cost_on_background_job(
        self, client, auth_headers, test_user_id, bg_table, monkeypatch, tmp_path,  # noqa: F811
    ):
        from app.agents.cover_letter_agent import FabricationError
        from app.services.llm_client import LLMClient
        from app.workers.tasks import run_agent_job

        _install_transport(monkeypatch, _SERVED_MODEL)
        _set_paid_plan(test_user_id)
        UsageQuotaRepository().reserve(test_user_id)
        run = AgentRunRepository().start(
            test_user_id, "coverLetter", {"job_id": "job-1"}
        )
        job_id = _seed_bg_job(
            test_user_id, "coverLetter", status="enqueued", run_id=run["id"],
            params={"job_id": "job-1"}, quota_reserved=True,
        )

        def _stubbed_run(self, *args, **kwargs):
            llm = LLMClient(mode="live", fixture_dir=tmp_path)
            llm._call_live("sys", "usr", model=_SERVED_MODEL, temperature=0.0)
            raise FabricationError(["Acme Corp"])

        monkeypatch.setattr(
            "app.agents.cover_letter_agent.CoverLetterAgent.run",
            _stubbed_run,
            raising=True,
        )

        quotas = UsageQuotaRepository()
        before = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)
        asyncio.run(run_agent_job({}, job_id))
        after = float((quotas.get_by_user(test_user_id) or {}).get("spendUsedUsd") or 0.0)

        row = _get_bg_job(job_id)
        assert row["status"] == "completed"
        result = row["result"] or {}
        assert result.get("coverLetterUnavailable") is True
        assert result.get("model") == _SERVED_MODEL, (
            f"expected the served model on the BackgroundJob result, got {result!r}"
        )
        assert float(result.get("costUsd") or 0) > 0
        assert after > before, (
            "the async single-agent worker must also accrue the realized "
            "spend against the USD cap for a degraded run"
        )

    def test_async_guard_rejection_with_no_served_call_still_records_zero(
        self, client, auth_headers, test_user_id, bg_table, monkeypatch,  # noqa: F811
    ):
        """PIN for the async path: a guard rejection with no LLM call at all
        (no ``degradedUsage`` on the exception) still records zero, never
        crashes on a missing attribute."""
        from app.agents.cover_letter_agent import FabricationError
        from app.workers.tasks import run_agent_job

        _set_paid_plan(test_user_id)
        UsageQuotaRepository().reserve(test_user_id)
        run = AgentRunRepository().start(
            test_user_id, "coverLetter", {"job_id": "job-1"}
        )
        job_id = _seed_bg_job(
            test_user_id, "coverLetter", status="enqueued", run_id=run["id"],
            params={"job_id": "job-1"}, quota_reserved=True,
        )

        def _stubbed_run(self, *args, **kwargs):
            raise FabricationError(["term"])

        monkeypatch.setattr(
            "app.agents.cover_letter_agent.CoverLetterAgent.run",
            _stubbed_run,
            raising=True,
        )
        asyncio.run(run_agent_job({}, job_id))

        row = _get_bg_job(job_id)
        result = row["result"] or {}
        assert result.get("model") is None
        assert float(result.get("costUsd") or 0) == 0.0
