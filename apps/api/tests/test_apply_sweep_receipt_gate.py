"""The sweep never reopens the employer's page once siteSubmittedAt is set.

A row with ``siteSubmittedAt`` set and ``transmittedAt`` still NULL was
already submitted on the employer's site — Aether is only waiting on the
Gmail receipt. ``apply_sweep._attempt_transmission`` must route that row
through ``finish_pending_receipt`` (poll-only) and must NEVER call
``execute_site_application`` again, because that would click the employer's
Submit control a second time for the same attempt.
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id
from app.workers import apply_sweep

LIVE_URL = "https://jobs.ashbyhq.com/acme/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee/application"


@pytest.fixture()
def user_id(client, auth_headers) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" LIMIT 1')
            return cur.fetchone()[0]


def _seed_site_submitted_application(user_id: str) -> tuple[str, str, str]:
    """A draft application whose employer form was already submitted once,
    with no transmission yet — the exact row shape ``pending_transmissions``
    selects when a receipt is still outstanding.
    """
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Staff Engineer", "Acme", "Melbourne VIC", False,
                    "Build things.", json.dumps([]), "ashby", LIVE_URL, 90.0,
                ),
            )
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake."}), "hash", job_id),
            )
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter","createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (app_id, user_id, job_id, resume_id, "Dear Hiring Manager,"),
            )
        conn.commit()
    from app.db import ensure_application_site_submitted_column

    ensure_application_site_submitted_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "siteSubmittedAt" = NOW() WHERE "id" = %s',
                (app_id,),
            )
        conn.commit()
    return job_id, resume_id, app_id


def test_attempt_transmission_polls_receipt_and_never_resubmits_the_form(
    user_id, monkeypatch
):
    _job_id, _resume_id, app_id = _seed_site_submitted_application(user_id)
    approval_id = new_id()

    calls: dict[str, object] = {"finish": None, "execute_called": False}

    def _finish_spy(uid, aid, apid, **kwargs):
        calls["finish"] = (uid, aid, apid, kwargs)
        return {"transmitted": True}

    def _execute_forbidden(*_a, **_k):
        calls["execute_called"] = True
        raise AssertionError(
            "execute_site_application must not run for a row whose "
            "siteSubmittedAt is already set — the employer's Submit control "
            "was already clicked once for this attempt"
        )

    monkeypatch.setattr(
        "app.services.apply_executor.finish_pending_receipt", _finish_spy
    )
    monkeypatch.setattr(
        "app.services.apply_executor.execute_site_application", _execute_forbidden
    )

    apply_sweep._attempt_transmission(user_id, app_id, approval_id)

    assert calls["execute_called"] is False
    assert calls["finish"] is not None
    finished_user_id, finished_app_id, finished_approval_id, kwargs = calls["finish"]
    assert finished_user_id == user_id
    assert finished_app_id == app_id
    assert finished_approval_id == approval_id
    assert kwargs.get("company") == "Acme"
    assert kwargs.get("job_title") == "Staff Engineer"
