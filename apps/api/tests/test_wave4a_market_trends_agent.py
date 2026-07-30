"""Wave-4A — Market Trends Agent (ADR-AG-1 honest scope).

HONEST SCOPE: there is NO external market-data feed in this product. The agent
reports trends WITHIN the user's OWN discovery feed — keyword shifts between the
earlier and the more recent half of their own postings, the remote/onsite mix,
and postings-per-week by DISCOVERY date — and says "not enough data" below the
sample threshold instead of guessing. Deterministic, unmetered.

Fail-before: ``app.agents.market_trends_agent`` does not exist and
``POST /agents/marketTrends/run`` 404s.
"""
from __future__ import annotations

import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_job(
    conn,
    user_id: str,
    *,
    title: str,
    created_at: str,
    requirements: list[str] | None = None,
    remote: bool = False,
    company: str = "Acme",
    location: str = "Melbourne, Australia",
    posted_at: str | None = None,
) -> str:
    import json as _json

    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","location","remote",'
            '"description","requirements","source","sourceUrl","status","postedAt",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'
            "'discovered'::\"JobStatus\",%s,%s,NOW())",
            (
                job_id, user_id, title, company, location, remote,
                "Deliver outcomes.", _json.dumps(requirements or []), "seek",
                f"https://example.com/job/{job_id}", posted_at, created_at,
            ),
        )
    conn.commit()
    return job_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _run(client, headers, params: dict | None = None):
    return client.post("/agents/marketTrends/run", json=params or {}, headers=headers)


def _seed_eight(db_session, user_id: str) -> None:
    """4 EARLIER postings (week of 2026-06-01) + 4 RECENT ones (week of
    2026-06-15). Kubernetes only earlier; Terraform only recent."""
    for day, remote in zip(("01", "02", "03", "04"), (True, True, True, False)):
        _seed_job(
            db_session, user_id,
            title="Program Manager",
            requirements=["Kubernetes", "Delivery"],
            remote=remote,
            created_at=f"2026-06-{day} 09:00:00",
        )
    for day in ("15", "16", "17", "18"):
        _seed_job(
            db_session, user_id,
            title="Program Manager",
            requirements=["Terraform", "Delivery"],
            remote=False,
            created_at=f"2026-06-{day} 09:00:00",
        )


# ---------------------------------------------------------------------------
# Real trends over the user's own feed
# ---------------------------------------------------------------------------


def test_reports_real_keyword_shifts_remote_mix_and_weekly_volume(
    client, auth_headers, user_id, db_session
):
    _seed_eight(db_session, user_id)
    resp = _run(client, auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["insufficientData"] is False
    assert body["postings"] == 8
    assert body["windowStart"].startswith("2026-06-01")
    assert body["windowEnd"].startswith("2026-06-18")

    assert body["remoteMix"] == {"remote": 3, "onsite": 5, "remoteShare": 0.375}

    assert body["postingsPerWeek"] == [
        {"weekStart": "2026-06-01", "postings": 4},
        {"weekStart": "2026-06-15", "postings": 4},
    ]
    # Real span includes the empty middle week — the mean is honest, and the
    # series never invents a bucket that has no postings.
    assert body["weeksSpanned"] == 3
    assert body["postingsPerWeekMean"] == 2.67

    assert body["keywordShiftsAvailable"] is True
    shifts = {s["keyword"]: s for s in body["keywordShifts"]}
    assert shifts["terraform"] == {
        "keyword": "terraform", "earlierCount": 0, "recentCount": 4, "delta": 4
    }
    assert shifts["kubernetes"] == {
        "keyword": "kubernetes", "earlierCount": 4, "recentCount": 0, "delta": -4
    }
    # Unchanged keywords are not "shifts" — they must not pad the list.
    assert "delivery" not in shifts

    # The series is by DISCOVERY date; the agent says so rather than implying
    # it knows when each role was actually posted.
    assert body["postedAtDisclosed"] == 0
    assert "discover" in body["basis"].lower()


def test_keyword_shifts_are_computed_over_titles_too(
    client, auth_headers, user_id, db_session
):
    for day in ("01", "02", "03"):
        _seed_job(
            db_session, user_id, title="Delivery Manager",
            created_at=f"2026-06-{day} 09:00:00",
        )
    for day in ("15", "16", "17"):
        _seed_job(
            db_session, user_id, title="Transformation Manager",
            created_at=f"2026-06-{day} 09:00:00",
        )
    body = _run(client, auth_headers).json()
    shifts = {s["keyword"]: s["delta"] for s in body["keywordShifts"]}
    assert shifts["transformation"] == 3
    assert shifts["delivery"] == -3


# ---------------------------------------------------------------------------
# Honest "not enough data" states
# ---------------------------------------------------------------------------


def test_below_the_sample_threshold_says_not_enough_data(
    client, auth_headers, user_id, db_session
):
    for day in ("01", "02"):
        _seed_job(
            db_session, user_id, title="Program Manager",
            created_at=f"2026-06-{day} 09:00:00",
        )
    body = _run(client, auth_headers).json()
    assert body["insufficientData"] is True
    assert body["postings"] == 2
    assert body["minPostings"] >= 3
    assert body["keywordShifts"] == []
    assert body["keywordShiftsAvailable"] is False
    assert body["postingsPerWeek"] == []
    assert body["remoteMix"] is None
    assert "not enough data" in body["message"].lower()


def test_empty_feed_is_honest_not_zeroed_trends(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["insufficientData"] is True
    assert body["postings"] == 0
    assert body["keywordShifts"] == []
    assert body["remoteMix"] is None
    assert body["windowStart"] is None and body["windowEnd"] is None
    assert "not enough data" in body["message"].lower()


def test_keyword_shifts_withheld_when_a_half_is_too_small(
    client, auth_headers, user_id, db_session
):
    """5 postings clears the overall threshold, but the earlier half holds only
    2 — not enough to call a "shift". Volume/remote mix still report."""
    for day in ("01", "02"):
        _seed_job(
            db_session, user_id, title="Program Manager", remote=True,
            requirements=["Kubernetes"], created_at=f"2026-06-{day} 09:00:00",
        )
    for day in ("15", "16", "17"):
        _seed_job(
            db_session, user_id, title="Program Manager",
            requirements=["Terraform"], created_at=f"2026-06-{day} 09:00:00",
        )
    body = _run(client, auth_headers).json()
    assert body["insufficientData"] is False
    assert body["postings"] == 5
    assert body["keywordShiftsAvailable"] is False
    assert body["keywordShifts"] == []
    assert body["remoteMix"] == {"remote": 2, "onsite": 3, "remoteShare": 0.4}
    assert "keyword" in body["message"].lower()


def test_is_scoped_to_the_caller(client, auth_headers, user_id, db_session):
    other = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "User" ("id","email","name","passwordHash","updatedAt") '
            "VALUES (%s,%s,'Other','x',NOW())",
            (other, f"other-{other[:8]}@example.com"),
        )
    db_session.commit()
    _seed_eight(db_session, other)
    body = _run(client, auth_headers).json()
    assert body["postings"] == 0
    assert body["insufficientData"] is True


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_run_is_audited_unmetered_and_zero_cost(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["model"] is None
    assert body["costUsd"] == 0.0
    runs = client.get("/agents/runs", headers=auth_headers).json()
    row = next(r for r in runs if r["agentName"] == "marketTrends")
    assert row["status"] == "completed"


def test_backend_is_not_metered():
    from app.routers.agents import _DETERMINISTIC_BACKENDS, _LLM_TIER_BY_BACKEND

    assert "marketTrends" not in _LLM_TIER_BY_BACKEND
    assert "marketTrends" in _DETERMINISTIC_BACKENDS
