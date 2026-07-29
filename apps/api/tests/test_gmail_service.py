"""P4 — GmailService unit tests (google client fully mocked, no network).

The Gmail REST client is replaced with a MagicMock so we assert the service
builds the right requests and normalizes responses, without any live call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.services.gmail_service import (
    GmailAuthError,
    GmailError,
    GmailNotConnectedError,
    GmailService,
    _decode_body,
    _split_address,
)


class _FakeCreds:
    """A credential repo returning nothing → not connected."""

    def get(self, user_id):
        return None

    def is_connected(self, user_id):
        return False


class _FakeAccountRepo:
    """QA-RES-001 — a credential repo returning a real stored row (with a
    timezone-aware ``accessTokenExpiresAt``, exactly as ``GmailAccountRepository``
    reads it back from the ``timestamptz`` column) and recording every
    ``update_access_token`` call so tests can assert the persist branch fires."""

    def __init__(self, expiry, access_token: str = "OLD_TOKEN") -> None:
        self._expiry = expiry
        self._access_token = access_token
        self.update_calls: list[dict] = []

    def get(self, user_id, account_id=None):
        return {
            "id": "acct1",
            "refreshToken": "refresh-tok",
            "accessToken": self._access_token,
            "accessTokenExpiresAt": self._expiry,
            "scopes": "https://www.googleapis.com/auth/gmail.readonly",
        }

    def update_access_token(self, user_id, access_token, expires_at, account_id=None):
        self.update_calls.append(
            {
                "user_id": user_id,
                "access_token": access_token,
                "expires_at": expires_at,
                "account_id": account_id,
            }
        )


def _mock_client() -> MagicMock:
    return MagicMock()


# ------------------------------------------------------------------ helpers
def test_split_address_variants():
    assert _split_address("Sarah Chen <sarah@acme.com>") == ("Sarah Chen", "sarah@acme.com")
    assert _split_address("plain@acme.com") == ("plain@acme.com", "plain@acme.com")


def test_decode_body_walks_multipart():
    import base64

    text = "Hello from the recruiter"
    data = base64.urlsafe_b64encode(text.encode()).decode()
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": ""}},
            {"mimeType": "text/plain", "body": {"data": data}},
        ],
    }
    assert _decode_body(payload) == text


# ------------------------------------------------------------------ auth gate
def test_send_without_credential_raises_not_connected():
    svc = GmailService("u1", creds_repo=_FakeCreds())
    with pytest.raises(GmailNotConnectedError):
        svc.send(to="r@x.com", subject="Hi", body="Hello")


# --------------------------------------------------- QA-RES-001 credential expiry
def test_credentials_applies_stored_expiry_so_stale_token_is_expired(monkeypatch):
    """A stale, timezone-aware stored expiry must make ``creds.expired`` True.

    Regression for QA-RES-001: ``_credentials()`` built ``Credentials`` without
    ``expiry=``, so google-auth's default ``expiry=None`` made every token
    ``valid`` (never-expiring) regardless of how stale it really was. The
    stub ``refresh`` below is a deliberate no-op — it neither raises nor
    updates ``creds.token``/``creds.expiry`` — so if the returned credentials
    object is still ``expired`` after ``_credentials()`` returns, that proves
    the ORIGINAL stored (past) expiry was actually threaded into the
    ``Credentials`` constructor and survived the naive/aware UTC conversion
    without google-auth's ``.expired`` raising ``TypeError`` on the mismatch.
    """
    stale_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
    repo = _FakeAccountRepo(expiry=stale_expiry)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    noop_refresh = MagicMock(return_value=None)
    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", noop_refresh
    )

    svc = GmailService("u1", creds_repo=repo, account_id="acct1")
    creds = svc._credentials()

    assert creds.expired is True
    # The no-op refresh must actually have been reached — i.e. the buggy
    # never-expiring token would have skipped this branch entirely.
    noop_refresh.assert_called_once()


def test_credentials_refresh_persists_new_token_for_expired_credential(monkeypatch):
    """QA-RES-001 — the existing refresh-and-persist branch (gmail_service.py
    :229-246) must actually fire and write the refreshed token/expiry back to
    the repo once a genuinely expired stored token is detected. The persisted
    expiry must be stamped aware-UTC (hardening (a)) even though google-auth's
    refresh_grant hands back a naive datetime, so it self-describes its
    timezone in the `timestamp with time zone` column regardless of the
    Postgres session TimeZone."""
    stale_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
    repo = _FakeAccountRepo(expiry=stale_expiry, access_token="OLD_TOKEN")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    # naive, like the real google-auth refresh_grant/_parse_expiry result
    new_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)

    def _fake_refresh(self, request):
        self.token = "NEW_TOKEN"
        self.expiry = new_expiry

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", _fake_refresh
    )

    svc = GmailService("u1", creds_repo=repo, account_id="acct1")
    creds = svc._credentials()

    assert creds.token == "NEW_TOKEN"
    assert len(repo.update_calls) == 1
    call = repo.update_calls[0]
    assert call["user_id"] == "u1"
    assert call["access_token"] == "NEW_TOKEN"
    assert call["expires_at"] == new_expiry.replace(tzinfo=timezone.utc)
    assert call["expires_at"].tzinfo is not None
    assert call["account_id"] == "acct1"


def test_credentials_with_fresh_expiry_never_refreshes(monkeypatch):
    """QA-RES-001 M4 — the load-bearing invariant of the whole fix: a stored
    token that is genuinely NOT stale must never trigger a refresh or a DB
    write, across two independently-constructed ``GmailService`` instances
    (mirrors the router building a fresh service per request/account).

    Without this assertion, a mutant that always threads an already-past
    expiry (e.g. ``datetime.now(timezone.utc) - timedelta(days=1)``,
    ignoring the stored value entirely) passes the stale-expiry tests above
    green while causing a Google refresh grant + a DB write on EVERY
    request — strictly worse than the ~11.9s bug this fix closes."""
    fresh_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    repo = _FakeAccountRepo(expiry=fresh_expiry, access_token="STILL_GOOD")
    refresh_spy = MagicMock(return_value=None)
    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", refresh_spy
    )

    creds1 = GmailService("u1", creds_repo=repo, account_id="acct1")._credentials()
    creds2 = GmailService("u1", creds_repo=repo, account_id="acct1")._credentials()

    assert creds1.expired is False
    assert creds2.expired is False
    assert creds1.token == "STILL_GOOD"
    assert creds2.token == "STILL_GOOD"
    refresh_spy.assert_not_called()
    assert repo.update_calls == []


# --------------------------------------------------- QA-RES-001 error taxonomy
def test_credentials_transport_error_maps_to_gmail_error_not_auth_error(monkeypatch):
    """QA-RES-001 M1 — ``google.auth.exceptions.TransportError`` is a SIBLING
    of ``RefreshError`` under ``GoogleAuthError`` (not a subclass), raised by
    ``google.auth.transport.requests.Request`` on any requests-level failure
    (DNS, connect timeout, connection reset) talking to Google's token
    endpoint. Now that the refresh path is hot, this must map to the
    ordinary ``GmailError`` taxonomy (transient failure) — NOT
    ``GmailAuthError`` ("reconnect your account"), which would misdiagnose
    a network hiccup as the user's grant being revoked."""
    from google.auth.exceptions import TransportError

    stale_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
    repo = _FakeAccountRepo(expiry=stale_expiry)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")

    def _raise_transport_error(self, request):
        raise TransportError("connection reset by peer")

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", _raise_transport_error
    )

    svc = GmailService("u1", creds_repo=repo, account_id="acct1")
    with pytest.raises(GmailError) as excinfo:
        svc._credentials()

    assert not isinstance(excinfo.value, GmailAuthError)
    assert repo.update_calls == []


def test_credentials_missing_oauth_config_raises_gmail_error_not_auth_error(monkeypatch):
    """QA-RES-001 (b) — a server misconfiguration (missing
    GOOGLE_OAUTH_CLIENT_ID/SECRET) must surface as an ordinary ``GmailError``
    ("service unavailable"), not ``GmailAuthError`` ("reconnect your
    account") — this is OUR fault, not a revoked per-user grant, and must
    not tell every user to reconnect a perfectly fine account. ``refresh()``
    must not even be attempted."""
    stale_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
    repo = _FakeAccountRepo(expiry=stale_expiry)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    refresh_spy = MagicMock(return_value=None)
    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.refresh", refresh_spy
    )

    svc = GmailService("u1", creds_repo=repo, account_id="acct1")
    with pytest.raises(GmailError) as excinfo:
        svc._credentials()

    assert not isinstance(excinfo.value, GmailAuthError)
    refresh_spy.assert_not_called()
    assert repo.update_calls == []


# ------------------------------------------------------------------ send
def test_send_builds_message_and_calls_api(monkeypatch):
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "m1",
        "threadId": "T1",
    }
    monkeypatch.setattr(svc, "_client", lambda: mock)

    result = svc.send(to="r@x.com", subject="Re: role", body="Thanks!", thread_id="T1")

    assert result == {"id": "m1", "threadId": "T1"}
    send_call = mock.users.return_value.messages.return_value.send
    _, kwargs = send_call.call_args
    assert kwargs["userId"] == "me"
    assert "raw" in kwargs["body"]
    assert kwargs["body"]["threadId"] == "T1"


def test_raw_message_attachment_size_guard():
    svc = GmailService("u1")
    huge = ("big.pdf", b"x" * (26 * 1024 * 1024), "application/pdf")
    with pytest.raises(GmailError):
        svc._raw_message("r@x.com", "Subject", "body", attachments=[huge])


# ------------------------------------------------------------------ read
def test_list_threads_normalizes(monkeypatch):
    import base64

    body = base64.urlsafe_b64encode(b"We have an opening").decode()
    full = {
        "id": "th1",
        "messages": [
            {
                "id": "msg1",
                "snippet": "We have an opening",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": body},
                    "headers": [
                        {"name": "Subject", "value": "Exciting role"},
                        {"name": "From", "value": "Sarah Chen <sarah@acme.com>"},
                        {"name": "Date", "value": "Mon, 14 Jul 2026 10:00:00 +0000"},
                    ],
                },
            }
        ],
    }
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.threads.return_value.list.return_value.execute.return_value = {
        "threads": [{"id": "th1"}]
    }
    mock.users.return_value.threads.return_value.get.return_value.execute.return_value = full
    monkeypatch.setattr(svc, "_client", lambda: mock)

    threads = svc.list_threads(max_results=5)
    assert len(threads) == 1
    t = threads[0]
    assert t["gmailThreadId"] == "th1"
    assert t["subject"] == "Exciting role"
    assert t["from"] == "Sarah Chen"
    assert t["fromEmail"] == "sarah@acme.com"
    assert t["body"] == "We have an opening"


def test_list_threads_without_credential_raises_not_connected():
    """QA-RES-001 M2 — ``_client()`` now lives INSIDE ``list_threads()``'s
    GmailError-wrapping try (it performs a real credential refresh via
    ``_credentials()`` instead of a no-op construction). Confirms that move
    still lets ``GmailNotConnectedError`` (a ``GmailError`` subclass) pass
    through unchanged rather than being re-wrapped or swallowed."""
    svc = GmailService("u1", creds_repo=_FakeCreds())
    with pytest.raises(GmailNotConnectedError):
        svc.list_threads()


def test_modify_labels_calls_api(monkeypatch):
    svc = GmailService("u1")
    mock = _mock_client()
    mock.users.return_value.messages.return_value.modify.return_value.execute.return_value = {
        "id": "m1"
    }
    monkeypatch.setattr(svc, "_client", lambda: mock)
    svc.modify_labels("m1", add=["Label_1"], remove=["INBOX"])
    _, kwargs = mock.users.return_value.messages.return_value.modify.call_args
    assert kwargs["body"] == {"addLabelIds": ["Label_1"], "removeLabelIds": ["INBOX"]}
