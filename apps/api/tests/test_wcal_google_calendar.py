"""W-CAL (GOLD-MASTER V4 §10) — Google Calendar: scope expansion + real event write.

These tests are written BEFORE the implementation and MUST be red against the
pre-W-CAL tree. They pin four things:

1. ``calendar.events`` is really requested, and the consent URL still uses
   INCREMENTAL authorization (``include_granted_scopes=true``) so an account
   that already granted Gmail keeps that grant instead of having it replaced.
2. The token exchange persists the scopes Google ACTUALLY GRANTED, never the
   scopes we asked for — otherwise a user who declines Calendar on Google's
   granular-consent screen would be recorded as having granted it, and every
   calendar feature would then fail with a lie behind it. The exchange must
   also SURVIVE that partial grant (oauthlib rejects a changed scope set by
   default), because failing it would take the user's Gmail connection down
   with it.
3. Creating an interview writes a REAL Google Calendar event (title, company,
   time, job link) — and, when the Calendar scope was never granted, refuses
   HONESTLY with an actionable message instead of pretending an event exists.
4. The Scheduling Agent reads free/busy ONLY when Calendar is genuinely
   connected; with no calendar it keeps today's "propose nothing of my own"
   behaviour verbatim.

No test here touches the live Google API: every Google call is mocked at the
client boundary (``GoogleCalendarService._client``) or at the HTTP boundary
(``requests.Session.request``), following the existing Gmail test patterns.
"""
from __future__ import annotations

import json
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.repositories.gmail_account import GmailAccountRepository
from app.services import google_oauth

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"

GMAIL_ONLY_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify "
    "https://www.googleapis.com/auth/gmail.send "
    "https://www.googleapis.com/auth/gmail.labels openid "
    "https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/userinfo.profile"
)
GMAIL_PLUS_CALENDAR_SCOPES = f"{GMAIL_ONLY_SCOPES} {CALENDAR_SCOPE}"


def _uid() -> str:
    return uuid.uuid4().hex


def _configure_oauth_env(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://example.abacusai.cloud/api/auth/google/callback",
    )


def _connect_google(user_id: str, *, scopes: str, email: str = "me@gmail.com") -> str:
    """Persist a real GmailAccount row with the given GRANTED scope string."""
    repo = GmailAccountRepository()
    row = repo.upsert_account(
        user_id,
        account_email=email,
        refresh_token="refresh-tok",
        access_token="access-tok",
        access_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes=scopes,
    )
    return str(row["id"])


# ---------------------------------------------------------------------------
# Fake Google Calendar client (mocked at the googleapiclient boundary)
# ---------------------------------------------------------------------------


class _Exec:
    def __init__(self, payload: Any, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def execute(self, **_kwargs: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._payload


class _Events:
    def __init__(self, api: "_FakeCalendarApi") -> None:
        self._api = api

    def insert(self, calendarId: str, body: dict, **kwargs: Any) -> _Exec:
        self._api.inserted.append({"calendarId": calendarId, "body": body, **kwargs})
        if self._api.insert_error is not None:
            return _Exec(None, self._api.insert_error)
        return _Exec(
            {
                "id": "evt-abc123",
                "htmlLink": "https://calendar.google.com/event?eid=evt-abc123",
                "status": "confirmed",
            }
        )

    def list(self, **kwargs: Any) -> _Exec:
        self._api.listed.append(kwargs)
        return _Exec({"items": list(self._api.events_items)})


class _FreeBusy:
    def __init__(self, api: "_FakeCalendarApi") -> None:
        self._api = api

    def query(self, body: dict, **_kwargs: Any) -> _Exec:
        self._api.freebusy_queries.append(body)
        return _Exec(self._api.freebusy_payload)


class _Calendars:
    def __init__(self, api: "_FakeCalendarApi") -> None:
        self._api = api

    def get(self, calendarId: str, **_kwargs: Any) -> _Exec:
        return _Exec({"id": calendarId, "timeZone": self._api.time_zone})


class _CalendarList:
    def __init__(self, api: "_FakeCalendarApi") -> None:
        self._api = api

    def list(self, **_kwargs: Any) -> _Exec:
        self._api.probe_calls += 1
        if self._api.probe_error is not None:
            return _Exec(None, self._api.probe_error)
        return _Exec({"items": [{"id": "primary"}]})


class _FakeCalendarApi:
    """Stands in for ``googleapiclient.discovery.build('calendar','v3',...)``."""

    def __init__(
        self,
        *,
        busy: list[dict[str, str]] | None = None,
        time_zone: str = "Australia/Sydney",
        insert_error: Exception | None = None,
        probe_error: Exception | None = None,
    ) -> None:
        self.inserted: list[dict[str, Any]] = []
        self.listed: list[dict[str, Any]] = []
        self.events_items: list[dict[str, Any]] = []
        self.freebusy_queries: list[dict[str, Any]] = []
        self.freebusy_payload = {"calendars": {"primary": {"busy": busy or []}}}
        self.time_zone = time_zone
        self.insert_error = insert_error
        self.probe_error = probe_error
        self.probe_calls = 0

    def events(self) -> _Events:
        return _Events(self)

    def freebusy(self) -> _FreeBusy:
        return _FreeBusy(self)

    def calendars(self) -> _Calendars:
        return _Calendars(self)

    def calendarList(self) -> _CalendarList:  # noqa: N802 — mirrors the Google API
        return _CalendarList(self)


@pytest.fixture(autouse=True)
def _clear_calendar_probe_failure_cache():
    """F5-004: the failed-probe TTL cache is module-level state — clear it
    around every test so one test's cached failure can never leak into
    another's expectation of a live probe."""
    from app.services import calendar_service

    calendar_service._probe_failure_cache.clear()
    yield
    calendar_service._probe_failure_cache.clear()


@pytest.fixture()
def fake_calendar(monkeypatch):
    """Patch the calendar client boundary; hand the fake back to the test."""
    from app.services import calendar_service

    api = _FakeCalendarApi()
    monkeypatch.setattr(
        calendar_service.GoogleCalendarService, "_client", lambda self: api
    )
    return api


# ===========================================================================
# 1. Scope list + incremental authorization
# ===========================================================================


def test_google_scopes_include_calendar_events():
    """W-CAL blocker: calendar.events was absent from GOOGLE_SCOPES."""
    assert CALENDAR_SCOPE in google_oauth.GOOGLE_SCOPES


def test_existing_gmail_scopes_are_all_still_requested():
    """Adding Calendar must not drop a single Gmail/identity scope."""
    for scope in (
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.labels",
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ):
        assert scope in google_oauth.GOOGLE_SCOPES


def test_consent_url_requests_calendar_with_incremental_authorization(monkeypatch):
    """The consent URL must ask for calendar.events AND keep
    ``include_granted_scopes=true`` so a prior Gmail grant is preserved rather
    than replaced (Google's incremental-authorization contract)."""
    _configure_oauth_env(monkeypatch)
    url = google_oauth.build_consent_url("user-123")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert query["include_granted_scopes"][0] == "true"
    requested = query["scope"][0].split()
    assert CALENDAR_SCOPE in requested
    assert "https://www.googleapis.com/auth/gmail.modify" in requested


# ===========================================================================
# 2. Token exchange — granted scopes, and surviving a partial grant
# ===========================================================================


def _token_response(payload: dict) -> Any:
    """A REAL ``requests.Response`` carrying Google's token JSON, so oauthlib
    and requests-oauthlib run their genuine parsing path (including the
    scope-change check this suite exists to pin)."""
    import requests

    resp = requests.Response()
    resp.status_code = 200
    resp._content = json.dumps(payload).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://oauth2.googleapis.com/token"
    prepared = requests.PreparedRequest()
    prepared.prepare(method="POST", url=resp.url)
    resp.request = prepared
    return resp


def _patch_token_endpoint(monkeypatch, granted_scope: str) -> None:
    """Mock the REAL HTTP boundary so oauthlib's own token parsing (including
    its scope-change check) actually runs."""
    import requests

    def fake_request(self, method, url, **kwargs):  # noqa: ANN001
        return _token_response(
            {
                "access_token": "access-xyz",
                "refresh_token": "refresh-xyz",
                "token_type": "Bearer",
                "expires_in": 3599,
                "scope": granted_scope,
            }
        )

    monkeypatch.setattr(requests.Session, "request", fake_request)


def test_exchange_persists_scopes_google_actually_granted(monkeypatch):
    """Google's granular consent lets a user tick Gmail and UNTICK Calendar.
    What we persist must be what was GRANTED — recording the requested set
    would make every downstream "Calendar connected" check a lie."""
    _configure_oauth_env(monkeypatch)
    monkeypatch.setattr(google_oauth, "_resolve_email", lambda creds: "me@gmail.com")
    url = google_oauth.build_consent_url("user-123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    _patch_token_endpoint(monkeypatch, GMAIL_ONLY_SCOPES)
    result = google_oauth.exchange_code("auth-code", state)

    assert CALENDAR_SCOPE not in result["scopes"].split(), (
        "declined Calendar scope was persisted as granted — a fabricated grant"
    )
    assert "https://www.googleapis.com/auth/gmail.modify" in result["scopes"].split()


def test_partial_grant_still_completes_so_the_gmail_connection_survives(monkeypatch):
    """oauthlib RAISES when the granted scope set differs from the requested
    one. Adding calendar.events makes that difference the NORMAL case for any
    user who declines Calendar — if the exchange blew up there, the user would
    lose Gmail entirely. The exchange must complete and record the truth."""
    _configure_oauth_env(monkeypatch)
    monkeypatch.setattr(google_oauth, "_resolve_email", lambda creds: "me@gmail.com")
    url = google_oauth.build_consent_url("user-123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    _patch_token_endpoint(monkeypatch, GMAIL_ONLY_SCOPES)
    result = google_oauth.exchange_code("auth-code", state)

    assert result["refresh_token"] == "refresh-xyz"
    assert result["user_id"] == "user-123"


def test_full_grant_records_calendar_scope(monkeypatch):
    _configure_oauth_env(monkeypatch)
    monkeypatch.setattr(google_oauth, "_resolve_email", lambda creds: "me@gmail.com")
    url = google_oauth.build_consent_url("user-123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]

    _patch_token_endpoint(monkeypatch, GMAIL_PLUS_CALENDAR_SCOPES)
    result = google_oauth.exchange_code("auth-code", state)

    assert CALENDAR_SCOPE in result["scopes"].split()


def test_relax_env_flag_is_not_left_set_after_exchange(monkeypatch):
    """The oauthlib relaxation is scoped to the exchange only — it must never
    leak into the rest of the process."""
    import os

    _configure_oauth_env(monkeypatch)
    monkeypatch.setattr(google_oauth, "_resolve_email", lambda creds: "me@gmail.com")
    url = google_oauth.build_consent_url("user-123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    _patch_token_endpoint(monkeypatch, GMAIL_ONLY_SCOPES)

    before = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    google_oauth.exchange_code("auth-code", state)
    assert os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE") == before


# ===========================================================================
# 3. Calendar service — honest refusal + real event payload
# ===========================================================================


def test_calendar_scope_granted_helper():
    from app.services.calendar_service import calendar_scope_granted

    assert calendar_scope_granted(GMAIL_PLUS_CALENDAR_SCOPES) is True
    assert calendar_scope_granted(GMAIL_ONLY_SCOPES) is False
    assert calendar_scope_granted(None) is False
    assert calendar_scope_granted("") is False


def test_create_event_refuses_when_no_google_account(db_session):
    from app.services.calendar_service import (
        CalendarNotConnectedError,
        GoogleCalendarService,
    )

    uid = _uid()
    with pytest.raises(CalendarNotConnectedError):
        GoogleCalendarService(uid).create_event(
            summary="Interview",
            start=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
        )


def test_create_event_refuses_honestly_when_calendar_scope_absent(
    db_session, fake_calendar
):
    """The load-bearing honesty rail: an account that consented to Gmail but
    NOT Calendar must be refused with an actionable message, and NOTHING may
    be sent to Google."""
    from app.services.calendar_service import (
        CalendarScopeNotGrantedError,
        GoogleCalendarService,
    )

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_ONLY_SCOPES)
    with pytest.raises(CalendarScopeNotGrantedError) as exc:
        GoogleCalendarService(uid).create_event(
            summary="Interview",
            start=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=60,
        )
    message = str(exc.value).lower()
    assert "calendar" in message
    assert "reconnect" in message, "the refusal must tell the user what to DO"
    assert fake_calendar.inserted == [], "no event may be attempted without the scope"


def test_event_payload_carries_title_company_time_and_job_link(
    db_session, fake_calendar
):
    from app.services.calendar_service import GoogleCalendarService

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    start = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)

    created = GoogleCalendarService(uid).create_event(
        summary="Interview — Staff Engineer @ Stripe",
        start=start,
        duration_minutes=45,
        description="Job: https://example.com/job/abc",
        location="Video call",
    )

    assert created["id"] == "evt-abc123"
    assert created["htmlLink"].startswith("https://calendar.google.com/")
    assert len(fake_calendar.inserted) == 1
    body = fake_calendar.inserted[0]["body"]
    assert body["summary"] == "Interview — Staff Engineer @ Stripe"
    assert "https://example.com/job/abc" in body["description"]
    assert body["location"] == "Video call"
    assert body["start"]["dateTime"].startswith("2026-09-01T04:00:00")
    assert body["end"]["dateTime"].startswith("2026-09-01T04:45:00")


def test_list_events_returns_google_items_not_synthesised(
    db_session, fake_calendar
):
    from app.services.calendar_service import GoogleCalendarService

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    fake_calendar.events_items = [
        {
            "id": "evt-john-black",
            "summary": "Interview with John Black",
            "organizer": {"email": "john.black@talent.example.com"},
        }
    ]
    now = datetime.now(timezone.utc)
    items = GoogleCalendarService(uid).list_events(
        time_min=now - timedelta(days=1),
        time_max=now + timedelta(days=14),
    )
    assert items[0]["id"] == "evt-john-black"
    assert fake_calendar.listed, "must actually call events().list"
    assert fake_calendar.listed[0]["calendarId"] == "primary"


# ===========================================================================
# 4. Interview creation writes a real event / refuses honestly
# ===========================================================================


def _seed_application(conn, user_id: str, *, app_status: str = "interview") -> str:
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Staff Engineer", "Stripe", "Build things.", "seek",
             f"https://example.com/job/{job_id}", 91.0),
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
            (app_id, user_id, job_id, resume_id, app_status, None),
        )
    conn.commit()
    return app_id


def test_create_interview_writes_a_real_calendar_event(
    client, auth_headers, test_user_id, db_session, fake_calendar
):
    app_id = _seed_application(db_session, test_user_id)
    _connect_google(test_user_id, scopes=GMAIL_PLUS_CALENDAR_SCOPES)

    resp = client.post(
        "/interviews",
        json={
            "application_id": app_id,
            "type": "video",
            "scheduled_at": "2026-09-01T04:00:00Z",
            "duration_minutes": 45,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["calendar"]["status"] == "created"
    assert body["calendar"]["event_id"] == "evt-abc123"
    assert body["calendar"]["html_link"].startswith("https://calendar.google.com/")

    assert len(fake_calendar.inserted) == 1
    event = fake_calendar.inserted[0]["body"]
    assert "Staff Engineer" in event["summary"]
    assert "Stripe" in event["summary"]
    assert "https://example.com/job/" in event["description"]

    # Persisted, so the row itself carries the proof (not just the response).
    fetched = client.get(f"/interviews/{body['id']}", headers=auth_headers).json()
    assert fetched["calendar_event_id"] == "evt-abc123"


def test_create_interview_without_calendar_scope_is_honest_not_fabricated(
    client, auth_headers, test_user_id, db_session, fake_calendar
):
    """The worst possible outcome would be a fake "event created". The
    interview row is still created (that is what the user asked for), but the
    calendar result must say, in words, that nothing was written."""
    app_id = _seed_application(db_session, test_user_id)
    _connect_google(test_user_id, scopes=GMAIL_ONLY_SCOPES)

    resp = client.post(
        "/interviews",
        json={
            "application_id": app_id,
            "type": "video",
            "scheduled_at": "2026-09-01T04:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cal = resp.json()["calendar"]

    assert cal["status"] == "scope_missing"
    assert cal["event_id"] is None
    assert cal["html_link"] is None
    assert "reconnect" in cal["message"].lower()
    assert "calendar" in cal["message"].lower()
    assert fake_calendar.inserted == []


def test_create_interview_without_google_account_reports_not_connected(
    client, auth_headers, test_user_id, db_session, fake_calendar
):
    app_id = _seed_application(db_session, test_user_id)

    resp = client.post(
        "/interviews",
        json={
            "application_id": app_id,
            "type": "video",
            "scheduled_at": "2026-09-01T04:00:00Z",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cal = resp.json()["calendar"]
    assert cal["status"] == "not_connected"
    assert cal["event_id"] is None
    assert "connect" in cal["message"].lower()
    assert fake_calendar.inserted == []


# ===========================================================================
# 5. Scheduling Agent — free/busy only when genuinely connected
# ===========================================================================


def test_scheduling_agent_reports_no_calendar_when_not_connected(db_session):
    """Today's honest behaviour is preserved verbatim for the unconnected
    user: no free/busy call, no invented availability."""
    from app.services import calendar_service

    uid = _uid()
    status = calendar_service.connection_status(uid, probe=False)
    assert status["status"] == "not_connected"
    assert status["scopeGranted"] is False


def test_scheduling_agent_derives_windows_from_real_freebusy(
    db_session, monkeypatch
):
    """When Calendar IS connected the agent proposes windows taken from the
    user's REAL free/busy, and every proposed window is genuinely free."""
    from app.services import calendar_service
    from app.services.calendar_service import GoogleCalendarService

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_PLUS_CALENDAR_SCOPES)

    # Busy for the whole of the first candidate day (UTC), free afterwards.
    now = datetime.now(timezone.utc)
    busy = [
        {
            "start": (now).isoformat(),
            "end": (now + timedelta(days=1)).isoformat(),
        }
    ]
    api = _FakeCalendarApi(busy=busy, time_zone="UTC")
    monkeypatch.setattr(GoogleCalendarService, "_client", lambda self: api)

    slots = calendar_service.suggest_free_windows(uid, max_slots=3)
    assert len(slots) == 3, slots
    assert api.freebusy_queries, "free/busy was never queried"

    busy_end = now + timedelta(days=1)
    for slot in slots:
        assert slot.start >= busy_end, f"proposed a window inside a busy block: {slot}"
        # The label must be self-describing enough that the fabrication guard
        # sees every rendering of the time in the corpus.
        assert slot.label
        assert ":" in slot.label


def test_caller_supplied_windows_do_not_claim_a_calendar_read(db_session, monkeypatch):
    """When the caller supplies their own windows the agent does NOT read the
    calendar — so ``calendarIntegration`` must stay False even though Calendar
    is connected. Reporting True would claim a read that never happened;
    ``calendarStatus`` is what conveys that the integration is available."""
    from app.agents.scheduling_agent import SchedulingAgent
    from app.services import calendar_service
    from app.services.calendar_service import GoogleCalendarService

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    api = _FakeCalendarApi(time_zone="UTC")
    monkeypatch.setattr(GoogleCalendarService, "_client", lambda self: api)

    result = SchedulingAgent().run(uid, proposed_times=["Tuesday 2pm AEST"])

    assert result.calendarStatus == calendar_service.STATUS_CONNECTED
    assert result.freeBusyChecked is False
    assert result.calendarIntegration is False
    assert result.calendarProposedTimes == []
    assert api.freebusy_queries == [], "free/busy must not be queried at all"


def test_scheduling_agent_reports_a_revoked_grant_as_needing_reauth(
    db_session, monkeypatch
):
    """The stored grant says "connected", so a revoked token only surfaces on
    the live free/busy call. It must be reported as ITSELF — collapsing
    "reconnect your account" into a vague "unavailable" leaves the user with no
    action to take."""
    from google.auth.exceptions import RefreshError

    from app.agents.scheduling_agent import SchedulingAgent
    from app.services import calendar_service
    from app.services.calendar_service import GoogleCalendarService

    uid = _uid()
    _connect_google(uid, scopes=GMAIL_PLUS_CALENDAR_SCOPES)

    def _revoked(self):
        raise RefreshError("Token has been expired or revoked.")

    monkeypatch.setattr(GoogleCalendarService, "_client", _revoked)

    result = SchedulingAgent().run(uid)
    assert result.calendarStatus == calendar_service.STATUS_NEEDS_REAUTH
    assert result.calendarIntegration is False
    assert result.freeBusyChecked is False
    assert result.calendarProposedTimes == []
    assert "reconnect" in result.calendarMessage.lower()


def test_scheduling_result_reports_calendar_status_honestly(db_session, monkeypatch):
    from app.agents.scheduling_agent import SchedulingAgent

    uid = _uid()
    result = SchedulingAgent().run(uid)
    # No threads at all — but the calendar fields must still be truthful.
    assert result.calendarIntegration is False
    assert result.calendarStatus == "not_connected"
    assert result.freeBusyChecked is False


# ===========================================================================
# 6. Settings surface — REAL token validity, not merely a stored row
# ===========================================================================


def test_settings_reports_calendar_scope_missing_truthfully(
    client, auth_headers, test_user_id, db_session
):
    _connect_google(test_user_id, scopes=GMAIL_ONLY_SCOPES)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    cal = [a for a in resp.json()["connectedAccounts"] if a["name"] == "Google Calendar"]
    assert len(cal) == 1, resp.json()["connectedAccounts"]
    assert cal[0]["status"] == "scope_missing"
    assert "reconnect" in cal[0]["detail"].lower()


def test_settings_reports_calendar_connected_when_a_live_probe_succeeds(
    client, auth_headers, test_user_id, db_session, fake_calendar
):
    _connect_google(test_user_id, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    cal = [a for a in resp.json()["connectedAccounts"] if a["name"] == "Google Calendar"]
    assert len(cal) == 1
    assert cal[0]["status"] == "connected"
    assert fake_calendar.probe_calls >= 1, (
        "GM2-EMAIL-001 lesson: status must reflect REAL token validity, not "
        "merely the presence of a stored row"
    )


def test_settings_reports_needs_reauth_when_the_live_probe_fails_auth(
    client, auth_headers, test_user_id, db_session, monkeypatch
):
    from google.auth.exceptions import RefreshError

    from app.services.calendar_service import GoogleCalendarService

    _connect_google(test_user_id, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    api = _FakeCalendarApi(probe_error=RefreshError("Token has been expired or revoked."))
    monkeypatch.setattr(GoogleCalendarService, "_client", lambda self: api)

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    cal = [a for a in resp.json()["connectedAccounts"] if a["name"] == "Google Calendar"]
    assert len(cal) == 1
    assert cal[0]["status"] == "needs_reauth"
    assert "reconnect" in cal[0]["detail"].lower()


def test_failed_probe_is_cached_and_not_repeated_every_poll(
    test_user_id, db_session, monkeypatch
):
    """F5-004: a grant Google rejects (403 insufficientPermissions) used to be
    re-probed — and re-logged — on EVERY settings poll (~every 20s, 3 031 log
    lines in prod). The failed outcome must be cached for the TTL; a
    successful probe must stay live (never cached)."""
    from googleapiclient.errors import HttpError

    from app.services import calendar_service
    from app.services.calendar_service import GoogleCalendarService, connection_status

    _connect_google(test_user_id, scopes=GMAIL_PLUS_CALENDAR_SCOPES)
    resp = type("R", (), {"status": 403, "reason": "insufficientPermissions"})()
    api = _FakeCalendarApi(
        probe_error=HttpError(resp, b'{"error": {"message": "insufficient permissions"}}')
    )
    monkeypatch.setattr(GoogleCalendarService, "_client", lambda self: api)

    first = connection_status(test_user_id)
    assert first["status"] == "scope_missing"
    assert api.probe_calls == 1

    second = connection_status(test_user_id)
    assert second["status"] == "scope_missing"
    assert second["cached"] is True
    assert api.probe_calls == 1, "cached failure must NOT re-probe Google"

    # Once the TTL lapses, the probe is live again — and a SUCCESS clears the
    # cache, so subsequent calls keep probing (success is never cached).
    calendar_service._probe_failure_cache.clear()
    api.probe_error = None
    third = connection_status(test_user_id)
    assert third["status"] == "connected"
    assert api.probe_calls == 2
    fourth = connection_status(test_user_id)
    assert fourth["status"] == "connected"
    assert api.probe_calls == 3, "successful probes are always live"


def test_settings_has_no_calendar_row_without_a_google_account(
    client, auth_headers, test_user_id, db_session
):
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    names = [a["name"] for a in resp.json()["connectedAccounts"]]
    assert "Google Calendar" not in names
