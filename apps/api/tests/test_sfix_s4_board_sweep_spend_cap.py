"""S-4 — the board-sweep autopilot must respect the per-user USD spend cap.

``board_sweep._run_agent`` dispatches with ``skip_quota=True``. That flag used
to disable BOTH the run-count quota AND the USD spend cap (``_record_run`` set
``quota_repo = None``), so sweep-driven tailor/coverLetter runs made real,
uncapped LLM calls that ``spendUsedUsd`` never even recorded — an autopilot
designed to run "continuously until the board is empty" with no dollar ceiling.

The exemption is legitimate for the RUN COUNT (automated infrastructure must not
eat a subscriber's paid run allowance) and illegitimate for the DOLLARS (they
are the user's). These tests pin that split.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import get_connection
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _record_run


@pytest.fixture(autouse=True)
def _priced_model_env(monkeypatch):
    """Pin a PRICED model so realized spend is deterministic and non-zero.

    Mirrors ``test_gap_p6_billing._model_env``: the repo's default tier model is
    an OpenRouter ``:free`` id priced at $0, which would make "spend recorded"
    unfalsifiable.
    """
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


def _set_spend(user_id: str, *, at_cap: bool) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendUsedUsd" = '
                + ('"spendCapUsd"' if at_cap else "0")
                + ' WHERE "userId" = %s',
                (user_id,),
            )
        conn.commit()


def test_sweep_run_at_spend_cap_makes_no_llm_call(client, auth_headers, test_user_id):
    """A user at their USD cap gets ZERO sweep LLM calls — an honest 429 first."""
    ensure_user_billing(test_user_id)
    _set_spend(test_user_id, at_cap=True)
    called: list[str] = []

    def _fn():
        called.append("llm")
        return _tailor_stub()

    with pytest.raises(HTTPException) as exc:
        _record_run(
            test_user_id,
            "tailor",
            {"job_id": "j"},
            _fn,
            system_run=True,
            skip_quota=True,
        )
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == "spend_cap_exceeded"
    assert called == [], "the sweep called the model despite the user being at cap"


def test_sweep_run_records_spend_without_consuming_run_quota(
    client, auth_headers, test_user_id
):
    """Sweep spend lands in ``spendUsedUsd``; the paid RUN allowance is untouched."""
    ensure_user_billing(test_user_id)
    _set_spend(test_user_id, at_cap=False)
    before = UsageQuotaRepository().get_by_user(test_user_id)

    out = _record_run(
        test_user_id,
        "tailor",
        {"job_id": "j"},
        _tailor_stub,
        system_run=True,
        skip_quota=True,
    )

    after = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(after["runsUsed"]) == int(before["runsUsed"]), "quota was consumed"
    assert float(after["spendUsedUsd"]) == pytest.approx(
        float(out["costUsd"]), abs=1e-9
    )
    assert float(after["spendUsedUsd"]) > 0, "sweep spend was not recorded"


def test_sweep_stretch_stops_at_cap_with_honest_log_and_agent_run(
    client, auth_headers, test_user_id, caplog, monkeypatch
):
    """The stretch stops BEFORE dispatching, says so, and records the stop."""
    import logging

    from app.repositories.agent_run import AgentRunRepository
    from app.workers import board_sweep

    ensure_user_billing(test_user_id)
    _set_spend(test_user_id, at_cap=True)

    dispatched: list[tuple[str, str]] = []

    def _explode(user_id, agent_key, params):  # pragma: no cover - must not run
        dispatched.append((user_id, agent_key))
        raise AssertionError("sweep dispatched an agent while at the spend cap")

    # Module-level seam the sweep dispatches through (monkeypatch restores it).
    monkeypatch.setattr(board_sweep, "_run_agent", _explode)
    with caplog.at_level(logging.WARNING, logger=board_sweep.logger.name):
        summary = board_sweep.sweep_user_stretch(test_user_id)

    assert dispatched == []
    assert summary["reason"] == "spend-cap-reached"
    assert summary["processed"] == 0
    assert summary["needs_continuation"] is False, "a capped user must not re-enqueue"
    assert any(
        "spend cap reached" in r.getMessage() for r in caplog.records
    ), "the stop was not logged honestly"

    runs = AgentRunRepository().list_recent(test_user_id, limit=10)
    stop_rows = [r for r in runs if r["agentName"] == "boardSweep"]
    assert stop_rows, "no AgentRun row recorded the spend-cap stop"
    assert stop_rows[0]["status"] == "failed"
    assert "spend cap" in (stop_rows[0]["error"] or "").lower()
