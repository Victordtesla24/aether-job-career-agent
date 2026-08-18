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


def test_gmail_trail_uses_parsed_time_and_onsite_not_email_stamp(
    db_session, test_user_id
):
    """John/Adan trail: face-to-face tomorrow 10am, not the Gmail receivedAt."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app.routers.interviews import _ensure_interview_tables
    from app.services.interview_ingest import ingest_inbound_for_user

    _ensure_interview_tables()
    app_id = _seed_submitted_application(
        db_session,
        test_user_id,
        company="Next Business Energy",
        title="Project Manager — Retail Systems Transformation",
    )
    melbourne = ZoneInfo("Australia/Melbourne")
    john_at = dt(2026, 8, 6, 14, 0, tzinfo=melbourne)
    adan_at = dt(2026, 8, 18, 16, 0, tzinfo=melbourne)
    thread = {
        "id": "et-nbe-1",
        "subject": "Next Business Energy — Project Manager interview",
        "gmailThreadId": "gmail-nbe-1",
        "lastMessageAt": adan_at,
        "messages": [
            {
                "from": "John Black",
                "fromEmail": "john.black@robertwalters.com.au",
                "createdAt": john_at,
                "body": (
                    "I've spoken with Adan Micallef, Group Technical Lead at "
                    "Next Business Energy. Initial phone interview tomorrow at "
                    "10:00am. The role is Project Manager — Retail Systems "
                    "Transformation. When did you finish with the ATO?"
                ),
            },
            {
                "from": "Adan Micallef",
                "fromEmail": "adan@nextbusinessenergy.com.au",
                "createdAt": adan_at,
                "body": (
                    "Confirming we will meet face to face tomorrow morning at "
                    "10:00am at our Docklands office instead of a phone call."
                ),
            },
        ],
    }
    ingest_inbound_for_user(test_user_id, [thread], force_calendar=False)
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT status FROM "Application" WHERE id = %s AND "userId" = %s',
            (app_id, test_user_id),
        )
        assert cur.fetchone()[0] == "interview"
        cur.execute(
            'SELECT "type","scheduledAt","location","contactName","contactEmail"'
            ' FROM "InterviewSchedule" WHERE "userId" = %s AND "applicationId" = %s',
            (test_user_id, app_id),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "onsite"
    local = row[1].astimezone(melbourne)
    assert local.date().isoformat() == "2026-08-19"
    assert local.hour == 10
    assert row[2] and "docklands" in row[2].lower()
    assert row[3] and "adan" in row[3].lower()
    assert row[4] == "adan@nextbusinessenergy.com.au"


def test_ingest_updates_existing_row_when_trail_changes_format(
    db_session, test_user_id
):
    """A later message that moves phone → onsite must update the same row."""
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app.routers.interviews import _ensure_interview_tables
    from app.services.interview_ingest import ingest_inbound_for_user

    _ensure_interview_tables()
    app_id = _seed_submitted_application(
        db_session,
        test_user_id,
        company="Next Business Energy",
        title="Project Manager",
    )
    melbourne = ZoneInfo("Australia/Melbourne")
    first = {
        "id": "et-nbe-upd",
        "subject": "Phone interview — Next Business Energy",
        "gmailThreadId": "gmail-nbe-upd",
        "lastMessageAt": dt(2026, 8, 6, 14, 0, tzinfo=melbourne),
        "messages": [
            {
                "from": "John Black",
                "fromEmail": "john.black@robertwalters.com.au",
                "createdAt": dt(2026, 8, 6, 14, 0, tzinfo=melbourne),
                "body": (
                    "Phone interview tomorrow at 10:00am with Adan at "
                    "Next Business Energy for the Project Manager role."
                ),
            }
        ],
    }
    ingest_inbound_for_user(test_user_id, [first], force_calendar=False)
    first["messages"].append(
        {
            "from": "Adan Micallef",
            "fromEmail": "adan@nextbusinessenergy.com.au",
            "createdAt": dt(2026, 8, 18, 16, 0, tzinfo=melbourne),
            "body": (
                "We will meet face to face tomorrow morning at 10:00am at our "
                "Docklands office instead of a phone call."
            ),
        }
    )
    first["lastMessageAt"] = dt(2026, 8, 18, 16, 0, tzinfo=melbourne)
    ingest_inbound_for_user(test_user_id, [first], force_calendar=False)
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT count(*), min("type"), max("type") FROM "InterviewSchedule"'
            ' WHERE "userId" = %s AND "applicationId" = %s',
            (test_user_id, app_id),
        )
        count, min_type, max_type = cur.fetchone()
        cur.execute(
            'SELECT "scheduledAt","location" FROM "InterviewSchedule"'
            ' WHERE "userId" = %s AND "applicationId" = %s',
            (test_user_id, app_id),
        )
        when, location = cur.fetchone()
    assert count == 1
    assert min_type == max_type == "onsite"
    local = when.astimezone(melbourne)
    assert local.date().isoformat() == "2026-08-19"
    assert location and "docklands" in location.lower()


def test_evidenced_invite_creates_job_and_application_when_none_exist(
    db_session, test_user_id
):
    """Outside-app apply: company+title in the trail are enough to open a row."""
    import json as json_lib
    import uuid
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app.routers.interviews import _ensure_interview_tables
    from app.services.interview_ingest import ingest_inbound_for_user

    _ensure_interview_tables()
    resume_id = uuid.uuid4().hex
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, test_user_id, json_lib.dumps({"summary": "PM"}), "hash-nbe"),
        )
    db_session.commit()
    melbourne = ZoneInfo("Australia/Melbourne")
    thread = {
        "id": "et-nbe-new",
        "subject": "Interview — Project Manager at Next Business Energy",
        "gmailThreadId": "gmail-nbe-new",
        "lastMessageAt": dt(2026, 8, 18, 16, 0, tzinfo=melbourne),
        "messages": [
            {
                "from": "Adan Micallef",
                "fromEmail": "adan@nextbusinessenergy.com.au",
                "createdAt": dt(2026, 8, 18, 16, 0, tzinfo=melbourne),
                "body": (
                    "Face to face interview tomorrow at 10:00am at our Docklands "
                    "office. The role is Project Manager — Retail Systems "
                    "Transformation at Next Business Energy."
                ),
            }
        ],
    }
    ingest_inbound_for_user(test_user_id, [thread], force_calendar=False)
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT j.company, j.title, a.status FROM "Application" a '
            'JOIN "Job" j ON j.id = a."jobId" '
            'WHERE a."userId" = %s',
            (test_user_id,),
        )
        row = cur.fetchone()
        cur.execute(
            'SELECT "type" FROM "InterviewSchedule" WHERE "userId" = %s',
            (test_user_id,),
        )
        itype = cur.fetchone()
    assert row is not None
    assert row[0] == "Next Business Energy"
    assert "project manager" in row[1].lower()
    assert row[2] == "interview"
    assert itype[0] == "onsite"


def test_at_sign_confirmation_creates_next_business_energy_not_nab(
    db_session, test_user_id
):
    """The production confirmation uses '@ Next Business Energy', not 'at'."""
    import json as json_lib
    import uuid
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    from app.routers.interviews import _ensure_interview_tables
    from app.services.interview_ingest import ingest_inbound_for_user

    _ensure_interview_tables()
    resume_id = uuid.uuid4().hex
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, test_user_id, json_lib.dumps({"summary": "PM"}), "hash-at"),
        )
    db_session.commit()
    melbourne = ZoneInfo("Australia/Melbourne")
    thread = {
        "id": "et-nbe-at",
        "subject": "Interview: Adan & Vikram (Project Manager @ Next Business Energy",
        "gmailThreadId": "1a01283b30f89f5d",
        "lastMessageAt": dt(2026, 8, 18, 11, 36, tzinfo=melbourne),
        "messages": [
            {
                "from": "John Black",
                "fromEmail": "john.black@robertwalters.com.au",
                "createdAt": dt(2026, 8, 18, 11, 36, tzinfo=melbourne),
                "body": (
                    "This email confirms your in-person interview for the "
                    "Project Manager position with Next Business Energy.\n"
                    "This will be Wednesday 19th August at 10:00am.\n"
                    "The location will be in Docklands.\n"
                    "Project Manager | Retail Systems Transformation at NAB\n"
                    "sarkar.vikram@gmail.com\n"
                ),
            }
        ],
    }
    ingest_inbound_for_user(test_user_id, [thread], force_calendar=False)
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT j.company, j.title FROM "Application" a '
            'JOIN "Job" j ON j.id = a."jobId" '
            'WHERE a."userId" = %s',
            (test_user_id,),
        )
        row = cur.fetchone()
        cur.execute(
            'SELECT "contactEmail" FROM "InterviewSchedule" WHERE "userId" = %s',
            (test_user_id,),
        )
        contact = cur.fetchone()
    assert row is not None
    assert row[0] == "Next Business Energy"
    assert "nab" not in row[0].lower()
    assert "project manager" in row[1].lower()
    assert contact[0] == "john.black@robertwalters.com.au"


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
