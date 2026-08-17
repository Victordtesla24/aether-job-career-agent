"""Inbound interview invites must update Application.status so analytics move.

Live miss: an interview meeting invite from John Black never created an
InterviewSchedule and never promoted the matching submitted application, so
`interview_conversion_rate` (interviews / submitted) stayed stale.

The ingest path is evidence-grounded: it only promotes when a real submitted
or screening application matches the invite's company/role/contact. It never
invents an application.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from app.services.interview_ingest import ingest_interview_invite


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_submitted_application(conn, user_id: str, *, company: str, title: str) -> str:
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                user_id,
                title,
                company,
                "Build things.",
                "seek",
                f"https://example.com/job/{job_id}",
                91.0,
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-test"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"answers","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, "submitted", None),
        )
    conn.commit()
    return app_id


def test_interview_invite_promotes_matching_application(
    db_session, test_user_id
):
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()
    app_id = _seed_submitted_application(
        db_session, test_user_id, company="Stripe", title="Staff Engineer"
    )
    when = datetime.now(timezone.utc) + timedelta(days=2)
    result = ingest_interview_invite(
        test_user_id,
        subject="Invitation: Interview — Staff Engineer @ Stripe",
        sender_name="John Black",
        sender_email="john.black@stripe.com",
        body="Please join a Google Meet interview for Staff Engineer at Stripe.",
        scheduled_at=when,
        calendar_event_id="evt-john-black-1",
        meeting_link="https://meet.google.com/abc-defg-hij",
    )
    assert result.promoted is True
    assert result.application_id == app_id
    assert result.interview_id

    with db_session.cursor() as cur:
        cur.execute(
            'SELECT status FROM "Application" WHERE id = %s AND "userId" = %s',
            (app_id, test_user_id),
        )
        assert cur.fetchone()[0] == "interview"
        cur.execute(
            'SELECT "applicationId","contactName","calendarEventId" '
            'FROM "InterviewSchedule" WHERE id = %s AND "userId" = %s',
            (result.interview_id, test_user_id),
        )
        row = cur.fetchone()
    assert row[0] == app_id
    assert row[1] == "John Black"
    assert row[2] == "evt-john-black-1"


def test_interview_invite_is_idempotent_on_calendar_event_id(
    db_session, test_user_id
):
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()
    _seed_submitted_application(
        db_session, test_user_id, company="Stripe", title="Staff Engineer"
    )
    when = datetime.now(timezone.utc) + timedelta(days=2)
    kwargs = dict(
        subject="Invitation: Interview — Staff Engineer @ Stripe",
        sender_name="John Black",
        sender_email="john.black@stripe.com",
        body="Google Meet interview for Staff Engineer at Stripe.",
        scheduled_at=when,
        calendar_event_id="evt-dup-1",
    )
    first = ingest_interview_invite(test_user_id, **kwargs)
    second = ingest_interview_invite(test_user_id, **kwargs)
    assert first.interview_id == second.interview_id
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT count(*) FROM "InterviewSchedule" '
            'WHERE "userId" = %s AND "calendarEventId" = %s',
            (test_user_id, "evt-dup-1"),
        )
        assert cur.fetchone()[0] == 1


def test_unmatched_invite_does_not_invent_an_application(
    db_session, test_user_id
):
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()
    result = ingest_interview_invite(
        test_user_id,
        subject="Invitation: Interview with John Black",
        sender_name="John Black",
        sender_email="john.black@unknown-corp.example",
        body="Interview at a company we have no application for.",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
        calendar_event_id="evt-unmatched",
    )
    assert result.promoted is False
    assert result.application_id is None
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT count(*) FROM "InterviewSchedule" WHERE "userId" = %s',
            (test_user_id,),
        )
        assert cur.fetchone()[0] == 0


def test_ingest_inbound_for_user_promotes_from_calendar_list(
    db_session, test_user_id, monkeypatch
):
    """The Email Center path that lists Google Calendar events, not Gmail."""
    from app.routers.interviews import _ensure_interview_tables
    from app.services.interview_ingest import ingest_inbound_for_user

    _ensure_interview_tables()
    app_id = _seed_submitted_application(
        db_session, test_user_id, company="Stripe", title="Staff Engineer"
    )
    when = datetime.now(timezone.utc) + timedelta(days=1)
    monkeypatch.setattr(
        "app.services.calendar_service.GoogleCalendarService.list_events",
        lambda self, **_kwargs: [
            {
                "id": "evt-cal-jb",
                "summary": "Interview with John Black — Staff Engineer @ Stripe",
                "description": "Google Meet interview for Staff Engineer at Stripe.",
                "organizer": {
                    "email": "john.black@stripe.com",
                    "displayName": "John Black",
                },
                "start": {"dateTime": when.isoformat()},
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            }
        ],
    )
    ingest_inbound_for_user(test_user_id, [], force_calendar=True)
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT status FROM "Application" WHERE id = %s AND "userId" = %s',
            (app_id, test_user_id),
        )
        assert cur.fetchone()[0] == "interview"


def test_career_calendar_event_is_detected():
    from app.services.interview_ingest import is_career_calendar_event

    assert is_career_calendar_event(
        {
            "summary": "Interview with John Black",
            "description": "Staff Engineer screen",
            "organizer": {"email": "john.black@stripe.com", "displayName": "John Black"},
        }
    )
    assert not is_career_calendar_event(
        {
            "summary": "Hearing reminder for 25/32 Queens Road",
            "description": "Residential tenancies",
            "organizer": {"email": "renting@courts.vic.gov.au"},
        }
    )
