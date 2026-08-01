"""Google Calendar service — real event writes + real free/busy (W-CAL).

ADR-CALENDAR-V4 supersedes ADR-AG-1's "no calendar read/write" restriction: that
restriction was architectural (there was no Calendar OAuth scope, so any
calendar claim would have been fabricated), not permanent. With
``calendar.events`` now requested under incremental authorization
(:mod:`app.services.google_oauth`), the honest capability exists — but ONLY for
an account that really granted it.

THE LOAD-BEARING RAIL: a calendar capability is claimed only when the stored
grant proves it. Three distinct, separately-reported refusals — never one vague
failure, never a silent success:

* :class:`CalendarNotConnectedError` — the user has no Google account linked.
* :class:`CalendarScopeNotGrantedError` — the account is linked (Gmail works)
  but ``calendar.events`` is absent from the GRANTED scopes. Google's granular
  consent screen makes this an ordinary user choice, not an error state, so it
  gets its own actionable message rather than being folded into "auth failed".
* :class:`CalendarAuthError` — the grant existed and has expired or been
  revoked; reconnecting is the fix.

Nothing here ever reports a created event it did not create. The event id and
``htmlLink`` returned are the ones Google itself handed back.

Credentials reuse the SAME multi-account ``GmailAccount`` store as
:mod:`app.services.gmail_service` (one Google grant, one row) including its
Fernet-encrypted tokens and its refresh-and-persist behaviour — a Calendar call
that refreshes the token benefits the next Gmail call and vice versa.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.repositories.gmail_account import GmailAccountRepository
from app.services.google_oauth import CALENDAR_EVENTS_SCOPE

logger = logging.getLogger(__name__)

#: Re-exported so callers do not have to reach into the OAuth module.
CALENDAR_SCOPE = CALENDAR_EVENTS_SCOPE

#: Conservative fallback expiry when a refresh response carries no ``expires_in``
#: — identical reasoning to gmail_service._FALLBACK_EXPIRY_MINUTES: persisting
#: NULL would make google-auth treat the token as "never expires" forever.
_FALLBACK_EXPIRY_MINUTES = 55

#: The single actionable sentence every scope refusal ends with. Kept in one
#: place so the API, the agent and the settings surface cannot drift apart.
RECONNECT_INSTRUCTION = (
    "Reconnect your Google account from Settings and tick the calendar "
    "permission to enable this."
)

NOT_CONNECTED_MESSAGE = (
    "Google Calendar is not connected — connect your Google account from "
    "Settings to have interviews written to your calendar. Nothing was added "
    "to any calendar."
)

SCOPE_MISSING_MESSAGE = (
    "Google Calendar access was not granted for this account — Gmail still "
    f"works, but no calendar event was created. {RECONNECT_INSTRUCTION}"
)

AUTH_EXPIRED_MESSAGE = (
    "Google Calendar authorization expired or was revoked, so no calendar "
    f"event was created. {RECONNECT_INSTRUCTION}"
)


class CalendarError(RuntimeError):
    """Any Calendar failure that is not specifically a grant problem."""


class CalendarNotConnectedError(CalendarError):
    """No Google account is linked to this user at all."""


class CalendarScopeNotGrantedError(CalendarError):
    """A Google account is linked but ``calendar.events`` was never granted."""


class CalendarAuthError(CalendarError):
    """The grant existed and has expired or been revoked."""


def calendar_scope_granted(scopes: Optional[str]) -> bool:
    """True only when ``calendar.events`` is in the GRANTED scope string.

    ``scopes`` is what the OAuth callback persisted from
    ``credentials.granted_scopes`` — Google's own answer to "what did the user
    actually agree to". Presence of a stored row proves nothing on its own.
    """
    if not scopes:
        return False
    return CALENDAR_SCOPE in scopes.split()


@dataclass(frozen=True)
class FreeWindow:
    """One genuinely-free window taken from the user's real free/busy."""

    start: datetime
    end: datetime
    #: Human label handed to the Scheduling Agent as availability. Deliberately
    #: multi-form (full weekday, 12-hour and short clock renderings, and the
    #: matching time-of-day word) so that whichever rendering the model chooses,
    #: the token is already present in the evidence corpus and the
    #: no-invented-availability rail does not false-positive on formatting.
    label: str


def _time_of_day(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def _format_window(start: datetime, end: datetime, tz_name: str) -> str:
    def _twelve(dt: datetime) -> str:
        return dt.strftime("%I:%M %p").lstrip("0")

    def _short(dt: datetime) -> str:
        minutes = dt.strftime(":%M") if dt.minute else ""
        return f"{dt.strftime('%I').lstrip('0')}{minutes}{dt.strftime('%p').lower()}"

    return (
        f"{start.strftime('%A')} {start.day} {start.strftime('%B')}, "
        f"{_time_of_day(start.hour)} — {_twelve(start)} to {_twelve(end)} "
        f"({_short(start)} to {_short(end)}), {tz_name}"
    )


class GoogleCalendarService:
    """Per-user Google Calendar client. Construct with the app ``user_id``."""

    def __init__(
        self,
        user_id: str,
        creds_repo: GmailAccountRepository | None = None,
        account_id: str | None = None,
    ) -> None:
        self._user_id = user_id
        self._creds_repo = creds_repo or GmailAccountRepository()
        self._account_id = account_id
        self._resolved_account_id: str | None = account_id
        self._row: dict[str, Any] | None = None
        self._service: Any = None

    # ------------------------------------------------------------------ auth
    def _account_row(self) -> dict[str, Any]:
        """The stored Google account this service will act as.

        With no explicit ``account_id``, prefer an account that really granted
        ``calendar.events`` — a user with two inboxes may have granted calendar
        on only one of them, and picking the primary blindly would refuse a
        capability the user does have. Falls back to the primary so the refusal
        below can still name a real account.
        """
        if self._row is not None:
            return self._row
        if self._account_id is not None:
            row = self._creds_repo.get(self._user_id, self._account_id)
        else:
            rows = self._creds_repo.list_accounts(self._user_id)
            row = next(
                (r for r in rows if calendar_scope_granted(r.get("scopes"))),
                rows[0] if rows else None,
            )
        if not row:
            raise CalendarNotConnectedError(NOT_CONNECTED_MESSAGE)
        self._row = row
        self._resolved_account_id = row.get("id")
        return row

    def require_calendar_account(self) -> dict[str, Any]:
        """The account row, or an honest refusal. Runs BEFORE any Google call so
        an ungranted scope never produces network traffic — and never produces
        a half-written event."""
        row = self._account_row()
        if not row.get("refreshToken"):
            # No usable refresh token: either Google never returned one or the
            # vault key rotated and the cipher no longer decrypts. Either way
            # the stored row cannot mint a call — reconnect is the honest fix.
            raise CalendarAuthError(AUTH_EXPIRED_MESSAGE)
        if not calendar_scope_granted(row.get("scopes")):
            raise CalendarScopeNotGrantedError(SCOPE_MISSING_MESSAGE)
        return row

    def _credentials(self) -> Any:
        row = self.require_calendar_account()
        from google.oauth2.credentials import Credentials

        # google-auth compares expiry against a NAIVE UTC "now", so a
        # timezone-aware stored expiry must be normalized or the comparison
        # raises TypeError (same handling as gmail_service._credentials).
        expiry = row.get("accessTokenExpiresAt")
        if expiry is not None and expiry.tzinfo is not None:
            expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)

        client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")

        creds = Credentials(
            token=row.get("accessToken"),
            refresh_token=row["refreshToken"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=(row.get("scopes") or "").split() or [CALENDAR_SCOPE],
            expiry=expiry,
        )
        if not creds.valid:
            if not client_id or not client_secret:
                detail = (
                    "Google Calendar is temporarily unavailable — server OAuth "
                    "configuration is missing."
                )
                logger.error(
                    "Calendar service misconfigured for user=%s account=%s: %s",
                    self._user_id,
                    self._resolved_account_id,
                    detail,
                )
                raise CalendarError(detail)

            from google.auth.exceptions import RefreshError, TransportError
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise CalendarAuthError(AUTH_EXPIRED_MESSAGE) from exc
            except TransportError as exc:
                # Transient network trouble talking to Google's token endpoint
                # — NOT a revoked grant. Telling the user to reconnect here
                # would be wrong.
                raise CalendarError(
                    f"Google Calendar is temporarily unreachable: {exc}"
                ) from exc

            new_expiry = creds.expiry
            if new_expiry is not None and new_expiry.tzinfo is None:
                new_expiry = new_expiry.replace(tzinfo=timezone.utc)
            elif new_expiry is None:
                new_expiry = datetime.now(timezone.utc) + timedelta(
                    minutes=_FALLBACK_EXPIRY_MINUTES
                )
                creds.expiry = new_expiry.replace(tzinfo=None)
            self._creds_repo.update_access_token(
                self._user_id,
                creds.token,
                new_expiry,
                account_id=self._resolved_account_id,
            )
        return creds

    def _client(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "calendar", "v3", credentials=self._credentials(), cache_discovery=False
            )
        return self._service

    # ----------------------------------------------------------------- write
    def create_event(
        self,
        *,
        summary: str,
        start: datetime,
        duration_minutes: int = 60,
        description: str | None = None,
        location: str | None = None,
        calendar_id: str = "primary",
    ) -> dict[str, Any]:
        """Create a REAL Google Calendar event and return Google's own reply.

        Raises one of the three honest refusals above rather than returning a
        made-up success. The returned ``id``/``htmlLink`` come straight from
        Google — this function never synthesises either.
        """
        self.require_calendar_account()
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=max(int(duration_minutes), 1))
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location

        created = self._execute(
            lambda: self._client()
            .events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        return {
            "id": created.get("id"),
            "htmlLink": created.get("htmlLink"),
            "status": created.get("status"),
        }

    # ------------------------------------------------------------------ read
    def primary_timezone(self) -> str:
        """The calendar's OWN timezone (real data, not a guess). Falls back to
        UTC only when Google does not tell us."""
        try:
            info = self._execute(
                lambda: self._client().calendars().get(calendarId="primary").execute()
            )
            return str(info.get("timeZone") or "UTC")
        except CalendarError:
            raise
        except Exception:  # noqa: BLE001 — a missing timezone is never fatal
            return "UTC"

    def busy_periods(
        self, time_min: datetime, time_max: datetime, calendar_id: str = "primary"
    ) -> list[tuple[datetime, datetime]]:
        """The user's REAL busy blocks in ``[time_min, time_max)``."""
        self.require_calendar_account()
        payload = self._execute(
            lambda: self._client()
            .freebusy()
            .query(
                body={
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "items": [{"id": calendar_id}],
                }
            )
            .execute()
        )
        calendars = (payload or {}).get("calendars") or {}
        entry = calendars.get(calendar_id) or {}
        periods: list[tuple[datetime, datetime]] = []
        for block in entry.get("busy") or []:
            start = _parse_google_ts(block.get("start"))
            end = _parse_google_ts(block.get("end"))
            if start and end:
                periods.append((start, end))
        periods.sort(key=lambda p: p[0])
        return periods

    def probe(self) -> None:
        """Cheapest possible LIVE validity check of the stored grant.

        GM2-EMAIL-001's lesson applied to Calendar: a stored row is not proof of
        a working grant. This makes one real API call so "connected" means the
        token was accepted by Google just now, not that a row exists.
        """
        self.require_calendar_account()
        self._execute(
            lambda: self._client().calendarList().list(maxResults=1).execute()
        )

    # --------------------------------------------------------------- plumbing
    @staticmethod
    def _execute(call: Any) -> Any:
        """Run a Google API call, mapping its failure taxonomy onto ours."""
        from google.auth.exceptions import GoogleAuthError, RefreshError

        try:
            return call()
        except CalendarError:
            raise
        except RefreshError as exc:
            raise CalendarAuthError(AUTH_EXPIRED_MESSAGE) from exc
        except Exception as exc:  # noqa: BLE001 — normalized below
            status_code = _http_status(exc)
            if status_code in (401,):
                raise CalendarAuthError(AUTH_EXPIRED_MESSAGE) from exc
            if status_code == 403 and _is_insufficient_scope(exc):
                raise CalendarScopeNotGrantedError(SCOPE_MISSING_MESSAGE) from exc
            if isinstance(exc, GoogleAuthError):
                raise CalendarError(
                    f"Google Calendar request failed: {exc}"
                ) from exc
            raise CalendarError(f"Google Calendar request failed: {exc}") from exc


def _http_status(exc: Exception) -> int | None:
    """The HTTP status behind a googleapiclient ``HttpError``, if any."""
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _is_insufficient_scope(exc: Exception) -> bool:
    text = str(exc).lower()
    return "insufficient" in text and ("scope" in text or "permission" in text)


def _parse_google_ts(value: Any) -> datetime | None:
    """Parse an RFC-3339 timestamp from the Calendar API into aware UTC."""
    if not value:
        return None
    raw = str(value)
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Connection status — the settings surface's single source of truth
# ---------------------------------------------------------------------------

#: Every status this module can report. There is deliberately no value that
#: means "probably fine".
STATUS_NOT_CONNECTED = "not_connected"
STATUS_SCOPE_MISSING = "scope_missing"
STATUS_NEEDS_REAUTH = "needs_reauth"
STATUS_UNAVAILABLE = "unavailable"
STATUS_CONNECTED = "connected"


def connection_status(
    user_id: str, account_id: str | None = None, probe: bool = True
) -> dict[str, Any]:
    """Truthful Calendar connection state for ``user_id``.

    GM2-EMAIL-001 established that a connection status must reflect REAL token
    validity, not merely a stored row. So:

    * no Google account            -> ``not_connected`` (no network call)
    * account without the scope    -> ``scope_missing``  (no network call — the
      stored GRANTED scopes already settle it, and probing would be pointless)
    * account with the scope       -> a LIVE probe decides ``connected`` /
      ``needs_reauth`` / ``unavailable``

    ``probe=False`` returns the stored-grant view only and is used where a
    network round-trip would be inappropriate (e.g. inside an agent run that
    is about to make its own calendar calls anyway).
    """
    service = GoogleCalendarService(user_id, account_id=account_id)
    try:
        row = service._account_row()
    except CalendarNotConnectedError:
        return {
            "status": STATUS_NOT_CONNECTED,
            "scopeGranted": False,
            "accountEmail": None,
            "probed": False,
            "message": NOT_CONNECTED_MESSAGE,
        }

    account_email = row.get("accountEmail")
    scope_ok = calendar_scope_granted(row.get("scopes"))
    base: dict[str, Any] = {
        "scopeGranted": scope_ok,
        "accountEmail": account_email,
        "probed": False,
    }
    if not scope_ok:
        return {**base, "status": STATUS_SCOPE_MISSING, "message": SCOPE_MISSING_MESSAGE}
    if not row.get("refreshToken"):
        return {**base, "status": STATUS_NEEDS_REAUTH, "message": AUTH_EXPIRED_MESSAGE}
    if not probe:
        return {
            **base,
            "status": STATUS_CONNECTED,
            "message": (
                "Google Calendar access is granted for this account (stored "
                "grant; not re-verified on this request)."
            ),
        }
    try:
        service.probe()
    except CalendarScopeNotGrantedError:
        return {
            **base,
            "status": STATUS_SCOPE_MISSING,
            "probed": True,
            "message": SCOPE_MISSING_MESSAGE,
        }
    except CalendarAuthError:
        return {
            **base,
            "status": STATUS_NEEDS_REAUTH,
            "probed": True,
            "message": AUTH_EXPIRED_MESSAGE,
        }
    except CalendarError as exc:
        # Honest third state: we could not verify. NOT "connected".
        return {
            **base,
            "status": STATUS_UNAVAILABLE,
            "probed": True,
            "message": (
                "Google Calendar could not be reached just now, so its "
                f"connection could not be verified: {exc}"
            ),
        }
    return {
        **base,
        "status": STATUS_CONNECTED,
        "probed": True,
        "message": f"Google Calendar connected as {account_email}.",
    }


# ---------------------------------------------------------------------------
# Free/busy -> proposable windows
# ---------------------------------------------------------------------------

#: Business-hours window (local to the calendar's own timezone) that a slot may
#: start in, and how far ahead to look.
_DAY_START_HOUR = 9
_DAY_END_HOUR = 17
_LOOKAHEAD_DAYS = 14
_SLOT_MINUTES = 60


def suggest_free_windows(
    user_id: str,
    max_slots: int = 3,
    slot_minutes: int = _SLOT_MINUTES,
    account_id: str | None = None,
) -> list[FreeWindow]:
    """Windows the user is REALLY free, derived from Google free/busy.

    Every returned window is one the calendar itself reports as unbusy — this
    function invents nothing. Raises the same honest refusals as the rest of
    the service when the grant is missing, so a caller can never mistake "no
    calendar" for "no free time".
    """
    service = GoogleCalendarService(user_id, account_id=account_id)
    service.require_calendar_account()

    tz_name = service.primary_timezone()
    tzinfo = _zone(tz_name)
    now = datetime.now(timezone.utc)
    window_start = now
    window_end = now + timedelta(days=_LOOKAHEAD_DAYS)
    busy = service.busy_periods(window_start, window_end)

    slots: list[FreeWindow] = []
    local_now = now.astimezone(tzinfo)
    # Start from the next whole hour so a proposal is never in the past.
    cursor = (local_now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    day_offset = 0
    while len(slots) < max_slots and day_offset <= _LOOKAHEAD_DAYS:
        day = (local_now + timedelta(days=day_offset)).date()
        hour = _DAY_START_HOUR
        while hour + (slot_minutes / 60) <= _DAY_END_HOUR and len(slots) < max_slots:
            start_local = datetime(
                day.year, day.month, day.day, hour, 0, tzinfo=tzinfo
            )
            end_local = start_local + timedelta(minutes=slot_minutes)
            hour += 1
            if start_local < cursor:
                continue
            if start_local.weekday() >= 5:  # weekends are not proposed
                continue
            start_utc = start_local.astimezone(timezone.utc)
            end_utc = end_local.astimezone(timezone.utc)
            if _overlaps_busy(start_utc, end_utc, busy):
                continue
            slots.append(
                FreeWindow(
                    start=start_utc,
                    end=end_utc,
                    label=_format_window(start_local, end_local, tz_name),
                )
            )
        day_offset += 1
    return slots


def _overlaps_busy(
    start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]
) -> bool:
    for busy_start, busy_end in busy:
        if start < busy_end and end > busy_start:
            return True
    return False


def _zone(tz_name: str) -> Any:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return timezone.utc
