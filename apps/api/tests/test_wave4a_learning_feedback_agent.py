"""Wave-4A — Learning / Feedback Agent (ADR-AG-1 honest scope).

HONEST SCOPE: nothing in this product adapts or retrains from outcomes. The card
copy that promised "learns from application outcomes to refine future tailoring"
overpromised. What ships is a READ-ONLY outcomes report — application statuses
cross-referenced with fit score, whether the résumé was tailored for that job,
and whether a cover letter was attached — reported as OBSERVED ASSOCIATION with
an explicit sample threshold, and writing nothing. Deterministic, unmetered.

Fail-before: ``app.agents.learning_feedback_agent`` does not exist and
``POST /agents/learningFeedback/run`` 404s.
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_application(
    conn,
    user_id: str,
    *,
    status: str,
    fit_score: float | None = 80.0,
    tailored: bool = False,
    cover_letter: str | None = None,
) -> tuple[str, str]:
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'applied'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Program Manager", "Acme", "Deliver.", "seek",
             f"https://example.com/job/{job_id}", fit_score),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,1,%s,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "s"}), "hash",
             job_id if tailored else None),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, status, cover_letter),
        )
    conn.commit()
    return app_id, job_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _run(client, headers, params: dict | None = None):
    return client.post(
        "/agents/learningFeedback/run", json=params or {}, headers=headers
    )


def _seed_twelve(db_session, user_id: str) -> None:
    """12 applications: 6 tailored (4 advanced / 2 rejected) and 6 untailored
    (1 advanced / 5 rejected). Fit scores differ by outcome."""
    for _ in range(3):
        _seed_application(
            db_session, user_id, status="interview", fit_score=90.0,
            tailored=True, cover_letter="Dear team,",
        )
    _seed_application(
        db_session, user_id, status="offer", fit_score=94.0, tailored=True,
        cover_letter="Dear team,",
    )
    for _ in range(2):
        _seed_application(
            db_session, user_id, status="rejected", fit_score=70.0, tailored=True
        )
    _seed_application(
        db_session, user_id, status="interview", fit_score=88.0, tailored=False
    )
    for _ in range(5):
        _seed_application(
            db_session, user_id, status="rejected", fit_score=60.0, tailored=False
        )


# ---------------------------------------------------------------------------
# Real outcome aggregation
# ---------------------------------------------------------------------------


def test_reports_real_outcomes_by_status_and_tailoring(
    client, auth_headers, user_id, db_session
):
    _seed_twelve(db_session, user_id)
    resp = _run(client, auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["applications"] == 12
    assert body["byStatus"] == {"interview": 4, "offer": 1, "rejected": 7}
    assert body["outcomes"] == {"advanced": 5, "rejected": 7, "pending": 0}
    assert body["insufficientData"] is False

    assert body["tailored"]["applications"] == 6
    assert body["tailored"]["advanced"] == 4
    assert body["tailored"]["rejected"] == 2
    assert body["tailored"]["advanceRate"] == 0.667

    assert body["untailored"]["applications"] == 6
    assert body["untailored"]["advanced"] == 1
    assert body["untailored"]["rejected"] == 5
    assert body["untailored"]["advanceRate"] == 0.167

    # Real fit-score spread per outcome bucket, computed from the seeded scores.
    advanced = body["fitScoreByOutcome"]["advanced"]
    assert advanced["scored"] == 5
    assert advanced["mean"] == 90.4
    assert advanced["median"] == 90.0
    rejected = body["fitScoreByOutcome"]["rejected"]
    assert rejected["scored"] == 7
    assert rejected["median"] == 60.0

    assert body["coverLetter"]["withLetter"]["applications"] == 4
    assert body["coverLetter"]["withoutLetter"]["applications"] == 8

    # Association only — never a causal or self-improving claim.
    assert "association" in body["caveat"].lower()
    assert "never" in body["caveat"].lower()


def test_pending_applications_are_never_scored_as_outcomes(
    client, auth_headers, user_id, db_session
):
    for status in ("draft", "submitted", "screening", "withdrawn"):
        _seed_application(db_session, user_id, status=status)
    body = _run(client, auth_headers).json()
    assert body["applications"] == 4
    assert body["outcomes"] == {"advanced": 0, "rejected": 0, "pending": 4}
    assert body["tailored"]["advanceRate"] is None
    assert body["untailored"]["advanceRate"] is None


def test_fit_score_absent_is_reported_not_defaulted(
    client, auth_headers, user_id, db_session
):
    _seed_application(db_session, user_id, status="offer", fit_score=None)
    body = _run(client, auth_headers).json()
    bucket = body["fitScoreByOutcome"]["advanced"]
    assert bucket["scored"] == 0
    assert bucket["mean"] is None and bucket["median"] is None
    assert body["fitScoreDisclosed"] == 0


# ---------------------------------------------------------------------------
# Sample-threshold honesty
# ---------------------------------------------------------------------------


def test_small_sample_reports_counts_but_withholds_rates(
    client, auth_headers, user_id, db_session
):
    _seed_application(db_session, user_id, status="interview", tailored=True)
    _seed_application(db_session, user_id, status="rejected", tailored=False)
    body = _run(client, auth_headers).json()
    assert body["applications"] == 2
    assert body["insufficientData"] is True
    assert body["minSample"] >= 5
    # Raw counts are still honest and present…
    assert body["outcomes"] == {"advanced": 1, "rejected": 1, "pending": 0}
    # …but no rate is claimed off a 1-application bucket.
    assert body["tailored"]["advanceRate"] is None
    assert body["untailored"]["advanceRate"] is None
    assert "not enough" in body["message"].lower()


def test_empty_state_is_honest(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["applications"] == 0
    assert body["byStatus"] == {}
    assert body["insufficientData"] is True
    assert body["fitScoreByOutcome"]["advanced"]["mean"] is None
    assert "no applications" in body["message"].lower()


def test_is_scoped_to_the_caller(client, auth_headers, user_id, db_session):
    other = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "User" ("id","email","name","passwordHash","updatedAt") '
            "VALUES (%s,%s,'Other','x',NOW())",
            (other, f"other-{other[:8]}@example.com"),
        )
    db_session.commit()
    _seed_twelve(db_session, other)
    body = _run(client, auth_headers).json()
    assert body["applications"] == 0


# ---------------------------------------------------------------------------
# Contract: read-only, unmetered, audited
# ---------------------------------------------------------------------------


def test_run_writes_nothing_but_the_audit_row(
    client, auth_headers, user_id, db_session
):
    _seed_twelve(db_session, user_id)

    def _snapshot() -> tuple:
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT (SELECT count(*) FROM "Application" WHERE "userId"=%s),'
                '(SELECT count(*) FROM "Resume" WHERE "userId"=%s),'
                '(SELECT count(*) FROM "Job" WHERE "userId"=%s),'
                '(SELECT max("updatedAt") FROM "Application" WHERE "userId"=%s)',
                (user_id, user_id, user_id, user_id),
            )
            row = cur.fetchone()
        db_session.commit()
        return row

    before = _snapshot()
    assert _run(client, auth_headers).status_code == 200
    assert _snapshot() == before


def test_run_is_audited_unmetered_and_zero_cost(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["model"] is None
    assert body["costUsd"] == 0.0
    runs = client.get("/agents/runs", headers=auth_headers).json()
    row = next(r for r in runs if r["agentName"] == "learningFeedback")
    assert row["status"] == "completed"


def test_backend_is_not_metered():
    from app.routers.agents import _DETERMINISTIC_BACKENDS, _LLM_TIER_BY_BACKEND

    assert "learningFeedback" not in _LLM_TIER_BY_BACKEND
    assert "learningFeedback" in _DETERMINISTIC_BACKENDS
