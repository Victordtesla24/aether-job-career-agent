"""S-4 completion round — the two reviewer items on the spend-cap slice.

R-1 (mid-job cap crossing). The per-iteration pre-check runs ONCE before both
dispatches of a ``full``-mode job. When the tailor call itself pushes
``spendUsedUsd`` to the cap, the follow-up coverLetter dispatch is correctly
blocked by ``_record_run``'s own gate — but that raise happens BEFORE
``runs.start()``, so no AgentRun row exists, and the sweep's generic
``except HTTPException`` 429 branch collapsed the event into
``reason='quota-exhausted'`` logged at INFO. Money-safe, but it broke the
"honest WARNING log plus a failed boardSweep AgentRun stating the numbers"
contract that ``_spend_cap_breach``'s docstring, the S-4 spec and the commit
message all promise. These tests pin the mid-job crossing, which the original
S-4 suite never covered (it only starts a stretch already at the cap).

R-2 (period rollover on the read path). ``UsageQuotaRepository.get_or_create``
is the sole read behind both S-4 gates, and unlike ``reserve`` it did not roll
an expired period over — so a user whose period had lapsed while at the cap
stayed blocked against last period's numbers. Defensive today (every user the
sweep can spend on is a paying subscriber whose period the Stripe renewal
webhook resets), a live bug the moment the ``skip_quota`` surface widens.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

import pytest
from fastapi import HTTPException

from app.db import get_connection
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _record_run
from app.workers import board_sweep


@pytest.fixture(autouse=True)
def _priced_model_env(monkeypatch):
    """Pin a PRICED model so realized spend is deterministic and non-zero."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _seed_job(user_id: str, *, fit: float) -> str:
    job_id = _uid()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Job" ("id","userId","title","company","description",'
                '"source","sourceUrl","status","fitScore","createdAt","updatedAt") '
                'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
                (job_id, user_id, "Engineer", "Acme", "Build.", "greenhouse",
                 f"https://example.com/job/{job_id}", "screening", fit),
            )
        conn.commit()
    return job_id


def _set_spend_at_cap(user_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendUsedUsd" = "spendCapUsd" '
                'WHERE "userId" = %s',
                (user_id,),
            )
        conn.commit()


def _expire_period(user_id: str) -> None:
    """Age the quota row's period out, at the cap and out of runs — exactly the
    state ``reserve``'s CASE-WHEN rollover exists to clear."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET '
                '  "periodStart" = now() - interval \'2 months\','
                '  "periodEnd"   = now() - interval \'1 day\','
                '  "spendUsedUsd" = "spendCapUsd",'
                '  "runsUsed" = "runsAllowed" '
                'WHERE "userId" = %s',
                (user_id,),
            )
        conn.commit()


# --------------------------------------------------------------------------
# R-1: the cap is crossed BETWEEN the tailor and coverLetter calls of one job
# --------------------------------------------------------------------------


def test_midjob_cap_crossing_stops_with_warning_and_agent_run(
    client, auth_headers, test_user_id, caplog, monkeypatch
):
    """Tailor crosses the cap; the blocked coverLetter must be recorded honestly.

    The coverLetter dispatch goes through the REAL ``_record_run`` gate (with a
    model function that must never be called), so this exercises the actual
    429 the sweep sees in production rather than a hand-rolled stand-in.
    """
    ensure_user_billing(test_user_id)
    first = _seed_job(test_user_id, fit=90.0)
    second = _seed_job(test_user_id, fit=10.0)
    calls: list[tuple[str, str]] = []

    def _must_not_call_model():  # pragma: no cover - the gate must raise first
        raise AssertionError("an LLM call was made after the cap was crossed")

    def _fake_run_agent(uid, agent_key, params):
        calls.append((agent_key, params["job_id"]))
        if agent_key == "tailor":
            # The tailor's own realized spend lands the user exactly on the cap.
            _set_spend_at_cap(uid)
            return {"resume_id": "r1", "changes": [], "rejected": []}
        return _record_run(
            uid, agent_key, params, _must_not_call_model,
            system_run=True, skip_quota=True,
        )

    monkeypatch.setattr(board_sweep, "_run_agent", _fake_run_agent)
    with caplog.at_level(logging.INFO, logger=board_sweep.logger.name):
        summary = board_sweep.sweep_user_stretch(
            test_user_id, deadline=time.monotonic() + 3600.0
        )

    # The blocked cover letter is a spend-cap stop, not a generic plan-quota 429.
    assert summary["reason"] == "spend-cap-reached", summary
    assert float(summary["spendUsedUsd"]) == pytest.approx(
        float(summary["spendCapUsd"])
    )
    # ...and the stretch stops: the second job is never attempted.
    assert calls == [("tailor", first), ("coverLetter", first)]
    assert second not in [job_id for _, job_id in calls]

    warnings = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    ]
    assert any("spend cap reached" in m for m in warnings), (
        f"the stop was not logged at WARNING; records={caplog.records!r}"
    )

    from app.repositories.agent_run import AgentRunRepository

    stops = [
        r for r in AgentRunRepository().list_recent(test_user_id, limit=20)
        if r["agentName"] == "boardSweep"
    ]
    assert stops, "no AgentRun row recorded the mid-job spend-cap stop"
    assert stops[0]["status"] == "failed"
    assert "spend cap" in (stops[0]["error"] or "").lower()
    output = stops[0]["output"]
    output = json.loads(output) if isinstance(output, str) else output
    assert output["reason"] == "spend_cap_exceeded"
    assert float(output["spendUsedUsd"]) >= float(output["spendCapUsd"]) > 0


def test_midjob_plain_quota_429_still_reports_quota_exhausted(
    client, auth_headers, test_user_id, monkeypatch
):
    """A NON-spend-cap 429 keeps its existing honest reason (no over-branching)."""
    ensure_user_billing(test_user_id)
    _seed_job(test_user_id, fit=90.0)

    def _fake_run_agent(uid, agent_key, params):
        raise HTTPException(429, detail={"code": "quota_exceeded", "message": "x"})

    monkeypatch.setattr(board_sweep, "_run_agent", _fake_run_agent)
    summary = board_sweep.sweep_user_stretch(
        test_user_id, deadline=time.monotonic() + 3600.0
    )
    assert summary["reason"] == "quota-exhausted"


# --------------------------------------------------------------------------
# R-2: the S-4 read path must roll an expired period over, exactly as reserve does
# --------------------------------------------------------------------------


def test_get_or_create_rolls_an_expired_period_like_reserve(
    client, auth_headers, test_user_id
):
    ensure_user_billing(test_user_id)
    _expire_period(test_user_id)

    rolled = UsageQuotaRepository().get_or_create(test_user_id)

    assert rolled is not None
    assert float(rolled["spendUsedUsd"]) == 0.0, "spend was not rolled over"
    assert int(rolled["runsUsed"]) == 0, "run count was not rolled over"
    persisted = UsageQuotaRepository().get_by_user(test_user_id)
    assert float(persisted["spendUsedUsd"]) == 0.0, "the rollover was not persisted"
    assert persisted["periodEnd"] > persisted["periodStart"]
    assert persisted["periodEnd"].timestamp() > time.time()


def test_get_or_create_leaves_a_live_period_untouched(
    client, auth_headers, test_user_id
):
    ensure_user_billing(test_user_id)
    _set_spend_at_cap(test_user_id)
    before = UsageQuotaRepository().get_by_user(test_user_id)

    after = UsageQuotaRepository().get_or_create(test_user_id)

    assert float(after["spendUsedUsd"]) == float(before["spendUsedUsd"]) > 0
    assert after["periodStart"] == before["periodStart"]
    assert after["periodEnd"] == before["periodEnd"]


def test_s4_gate_does_not_block_on_a_lapsed_period(
    client, auth_headers, test_user_id
):
    """The S-4 spend gate reads through ``get_or_create``: a user whose period
    lapsed while at the cap must start the new period unblocked."""
    ensure_user_billing(test_user_id)
    _expire_period(test_user_id)
    called: list[str] = []

    def _fn():
        called.append("llm")
        return {"resume_id": "r1", "changes": [], "rejected": []}

    _record_run(
        test_user_id, "tailor", {"job_id": "j"}, _fn,
        system_run=True, skip_quota=True,
    )
    assert called == ["llm"], "a lapsed period still blocked the run at last cap"
