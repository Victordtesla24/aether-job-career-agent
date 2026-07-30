"""Wave-4A — Compliance Agent (ADR-AG-1 honest scope).

HONEST SCOPE: the Compliance Agent does NOT re-verify artifacts with an LLM
("careful reasoning about truthfulness and evidence verification" was the
overpromising card copy — no such second-opinion verifier exists). It SURFACES
the verdicts the fabrication / entailment guards ALREADY recorded on the user's
own ``tailor`` / ``coverLetter`` AgentRun rows, as a per-artifact compliance
report. Deterministic, unmetered, read-only.

Fail-before: ``app.agents.compliance_agent`` does not exist and
``POST /agents/compliance/run`` 404s (``compliance`` is a planned card with
``backend: None``).
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_run(
    conn,
    user_id: str,
    agent_name: str,
    *,
    status: str = "completed",
    output: dict | None = None,
    input_: dict | None = None,
    error: str | None = None,
    created_at: str | None = None,
) -> str:
    """Insert a real AgentRun audit row — the ONLY input the compliance report
    reads. Mirrors exactly what ``AgentRunRepository.start/finish`` writes.

    ``created_at`` is explicit where ordering is asserted: ``AgentRun.createdAt``
    is millisecond-precision, so back-to-back inserts can share a timestamp.
    """
    run_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "AgentRun" ("id","userId","agentName","status","input",'
            '"output","error","startedAt","completedAt","createdAt") '
            'VALUES (%s,%s,%s,%s::"AgentRunStatus",%s,%s,%s,NOW(),NOW(),'
            "COALESCE(%s::timestamp, NOW()))",
            (
                run_id,
                user_id,
                agent_name,
                status,
                json.dumps(input_ or {}),
                json.dumps(output or {}),
                error,
                created_at,
            ),
        )
    conn.commit()
    return run_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _run(client, headers, params: dict | None = None):
    return client.post("/agents/compliance/run", json=params or {}, headers=headers)


# ---------------------------------------------------------------------------
# Real aggregation over real guard verdicts
# ---------------------------------------------------------------------------


def test_compliance_surfaces_real_guard_verdicts_per_artifact(
    client, auth_headers, user_id, db_session
):
    """Every recorded guard verdict becomes one artifact row with the REAL
    rejected/flagged items — clean, partially-flagged and fully-withheld."""
    clean_tailor = _seed_run(
        db_session, user_id, "tailor",
        input_={"job_id": "job-clean"},
        output={"resume_id": "res-1", "changes": 4, "rejected": []},
        created_at="2026-06-01 09:00:00",
    )
    flagged_tailor = _seed_run(
        db_session, user_id, "tailor",
        input_={"job_id": "job-part"},
        output={
            "resume_id": "res-2",
            "changes": 2,
            "rejected": ["Kubernetes at NAB", "led 40 engineers"],
        },
        created_at="2026-06-02 09:00:00",
    )
    withheld_tailor = _seed_run(
        db_session, user_id, "tailor",
        input_={"job_id": "job-none"},
        output={
            "resume_id": None,
            "changes": 0,
            "rejected": ["invented AWS certification"],
            "noChangesApplied": True,
        },
        created_at="2026-06-03 09:00:00",
    )
    clean_cover = _seed_run(
        db_session, user_id, "coverLetter",
        input_={"job_id": "job-cover-ok"},
        output={"cover_letter_id": "cl-1", "flagged": []},
        created_at="2026-06-04 09:00:00",
    )
    withheld_cover = _seed_run(
        db_session, user_id, "coverLetter",
        input_={"job_id": "job-cover-bad"},
        output={
            "cover_letter_id": None,
            "coverLetterUnavailable": True,
            "reason": "['Deloitte', '99%']",
        },
        created_at="2026-06-05 09:00:00",
    )

    resp = _run(client, auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["checked"] == 5
    assert body["clean"] == 2
    assert body["flagged"] == 1
    assert body["withheld"] == 2

    by_run = {a["runId"]: a for a in body["artifacts"]}
    assert set(by_run) == {
        clean_tailor, flagged_tailor, withheld_tailor, clean_cover, withheld_cover,
    }

    assert by_run[clean_tailor]["verdict"] == "clean"
    assert by_run[clean_tailor]["artifact"] == "resume"
    assert by_run[clean_tailor]["jobId"] == "job-clean"
    assert by_run[clean_tailor]["rejected"] == []

    part = by_run[flagged_tailor]
    assert part["verdict"] == "flagged"
    assert part["rejected"] == ["Kubernetes at NAB", "led 40 engineers"]
    assert part["changesApplied"] == 2

    gone = by_run[withheld_tailor]
    assert gone["verdict"] == "withheld"
    assert gone["rejected"] == ["invented AWS certification"]
    assert gone["changesApplied"] == 0

    assert by_run[clean_cover]["verdict"] == "clean"
    assert by_run[clean_cover]["artifact"] == "coverLetter"

    bad_cover = by_run[withheld_cover]
    assert bad_cover["verdict"] == "withheld"
    assert bad_cover["artifact"] == "coverLetter"
    assert "Deloitte" in bad_cover["detail"]

    # Newest-first ordering so the report reads like an audit log.
    assert [a["runId"] for a in body["artifacts"]][0] == withheld_cover


def test_compliance_counts_flagged_cover_letter_that_still_shipped(
    client, auth_headers, user_id, db_session
):
    """A letter the guard flagged but that still produced an artifact is
    ``flagged`` — never silently reported as clean."""
    _seed_run(
        db_session, user_id, "coverLetter",
        input_={"job_id": "j1"},
        output={"cover_letter_id": "cl-9", "flagged": ["Optiver"]},
    )
    body = _run(client, auth_headers).json()
    assert body["flagged"] == 1 and body["clean"] == 0
    art = body["artifacts"][0]
    assert art["verdict"] == "flagged"
    assert art["flagged"] == ["Optiver"]


# ---------------------------------------------------------------------------
# Honest empty / degraded states — never fabricated
# ---------------------------------------------------------------------------


def test_compliance_honest_empty_state_when_nothing_was_generated(
    client, auth_headers
):
    body = _run(client, auth_headers).json()
    assert body["checked"] == 0
    assert body["clean"] == body["flagged"] == body["withheld"] == 0
    assert body["artifacts"] == []
    assert "no tailoring or cover-letter runs" in body["message"].lower()


def test_compliance_excludes_failed_and_in_flight_runs_honestly(
    client, auth_headers, user_id, db_session
):
    """A failed / still-running generation recorded NO guard verdict, so it must
    not be scored as clean — it is reported as an honest exclusion count."""
    _seed_run(
        db_session, user_id, "tailor", status="failed",
        error="Job not found", output={},
    )
    _seed_run(db_session, user_id, "coverLetter", status="running", output={})
    body = _run(client, auth_headers).json()
    assert body["checked"] == 0
    assert body["clean"] == 0
    assert body["skippedNoVerdict"] == 2
    assert "no guard verdict" in body["message"].lower()


def test_compliance_ignores_non_guarded_agents(
    client, auth_headers, user_id, db_session
):
    """scout / fitScorer / matcher runs have no fabrication guard at all — they
    must never appear in a compliance report."""
    _seed_run(db_session, user_id, "scout", output={"persisted": 12})
    _seed_run(db_session, user_id, "fitScorer", output={"scored": 12})
    _seed_run(db_session, user_id, "matcher", output={"matched": 12})
    body = _run(client, auth_headers).json()
    assert body["checked"] == 0
    assert body["artifacts"] == []
    assert body["skippedNoVerdict"] == 0


def test_compliance_is_scoped_to_the_caller(client, auth_headers, user_id, db_session):
    other = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "User" ("id","email","name","passwordHash","updatedAt") '
            "VALUES (%s,%s,'Other','x',NOW())",
            (other, f"other-{other[:8]}@example.com"),
        )
    db_session.commit()
    _seed_run(
        db_session, other, "tailor",
        output={"resume_id": "r", "changes": 1, "rejected": ["leak"]},
    )
    body = _run(client, auth_headers).json()
    assert body["checked"] == 0
    assert body["artifacts"] == []


# ---------------------------------------------------------------------------
# Contract: deterministic, unmetered, audited
# ---------------------------------------------------------------------------


def test_compliance_run_is_audited_unmetered_and_zero_cost(
    client, auth_headers, user_id, db_session
):
    _seed_run(
        db_session, user_id, "tailor",
        output={"resume_id": "r", "changes": 3, "rejected": []},
    )
    body = _run(client, auth_headers).json()
    # Deterministic agent: no model, no tokens, no spend (never fabricated).
    assert body["model"] is None
    assert body["tokensIn"] == 0 and body["tokensOut"] == 0
    assert body["costUsd"] == 0.0
    assert body["approvalRequired"] is False
    assert body["run_id"]

    runs = client.get("/agents/runs", headers=auth_headers).json()
    row = next(r for r in runs if r["agentName"] == "compliance")
    assert row["status"] == "completed"
    assert float(row["costUsd"] or 0) == 0.0


def test_compliance_backend_is_not_metered():
    """``compliance`` must NOT be in the metered tier map — it makes no LLM
    call, so it must never reserve plan quota."""
    from app.routers.agents import _DETERMINISTIC_BACKENDS, _LLM_TIER_BY_BACKEND

    assert "compliance" not in _LLM_TIER_BY_BACKEND
    assert "compliance" in _DETERMINISTIC_BACKENDS
