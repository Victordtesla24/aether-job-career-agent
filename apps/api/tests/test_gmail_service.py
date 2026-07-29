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


# ===========================================================================
# W-6 / QA item 4 — inbox latency: TTL sync gate + bounded parallel fetch
# ===========================================================================
#
# The inbox endpoint ran a full Gmail sync for EVERY connected account on EVERY
# request, and each sync did threads().list() + up to 25 SEQUENTIAL
# threads().get() round-trips (~148 threads / 691 KB observed in production) —
# ~11s of Gmail I/O inline in the request path. These tests pin the two-part
# fix: (1) a TTL freshness gate so a sync only runs when the account's
# lastSyncedAt is stale, and (2) a bounded ThreadPoolExecutor for the
# per-thread detail fetch, with a per-worker HTTP client (httplib2 is NOT
# thread-safe), a serialized credential refresh, order/dedup preservation and a
# sequential fail-safe.


class _ThreadFetchRecorder:
    """Records every ``execute()`` a fake Gmail client performs: which thread it
    ran on, which http object it was handed, and how many ran concurrently.

    ``barrier_parties`` forces a hard, deterministic concurrency proof — with N
    parties the barrier only releases when N executes are genuinely in flight at
    the same instant. A sequential implementation times out (and the test then
    fails on ``barrier_passed``) instead of passing by luck.
    """

    def __init__(self, barrier_parties: int = 1, fail_once: set[str] | None = None):
        import threading

        self._lock = threading.Lock()
        self._barrier = threading.Barrier(barrier_parties)
        self.barrier_passed = False
        self.active = 0
        self.max_concurrent = 0
        #: (thread_id_fetched, thread_name, id(http) or None)
        self.calls: list[tuple[str, str, int | None]] = []
        self._fail_once = set(fail_once or ())

    def execute(self, thread_id: str, http):
        import threading
        import time

        with self._lock:
            self.calls.append(
                (thread_id, threading.current_thread().name, id(http) if http is not None else None)
            )
            self.active += 1
            self.max_concurrent = max(self.max_concurrent, self.active)
            should_fail = thread_id in self._fail_once
            if should_fail:
                self._fail_once.discard(thread_id)
        try:
            try:
                self._barrier.wait(timeout=2.0)
                with self._lock:
                    self.barrier_passed = True
            except threading.BrokenBarrierError:
                pass
            time.sleep(0.01)
            if should_fail:
                raise RuntimeError(f"simulated Gmail failure for {thread_id}")
        finally:
            with self._lock:
                self.active -= 1

    # -- convenience views -------------------------------------------------
    @property
    def fetched_order(self) -> list[str]:
        return [c[0] for c in self.calls]

    @property
    def thread_names(self) -> set[str]:
        return {c[1] for c in self.calls}

    def http_by_thread(self) -> dict[str, set[int | None]]:
        out: dict[str, set[int | None]] = {}
        for _tid, name, http_id in self.calls:
            out.setdefault(name, set()).add(http_id)
        return out

    def threads_by_http(self) -> dict[int | None, set[str]]:
        out: dict[int | None, set[str]] = {}
        for _tid, name, http_id in self.calls:
            out.setdefault(http_id, set()).add(name)
        return out


def _thread_payload(thread_id: str) -> dict:
    import base64

    body = base64.urlsafe_b64encode(f"body of {thread_id}".encode()).decode()
    return {
        "id": thread_id,
        "messages": [
            {
                "id": f"msg-{thread_id}",
                "snippet": f"snippet {thread_id}",
                "labelIds": ["INBOX"],
                "payload": {
                    "mimeType": "text/plain",
                    "body": {"data": body},
                    "headers": [
                        {"name": "Subject", "value": f"Subject {thread_id}"},
                        {"name": "From", "value": f"Sender {thread_id} <s-{thread_id}@acme.com>"},
                        {"name": "Date", "value": "Mon, 14 Jul 2026 10:00:00 +0000"},
                    ],
                },
            }
        ],
    }


class _FakeThreadRequest:
    def __init__(self, thread_id: str, recorder: _ThreadFetchRecorder):
        self._thread_id = thread_id
        self._recorder = recorder

    def execute(self, http=None, num_retries=0):
        self._recorder.execute(self._thread_id, http)
        return _thread_payload(self._thread_id)


class _FakeListRequest:
    def __init__(self, thread_ids: list[str]):
        self._thread_ids = thread_ids

    def execute(self, http=None, num_retries=0):
        return {"threads": [{"id": t} for t in self._thread_ids]}


class _FakeGmailApi:
    """Stand-in for the built Gmail discovery client (``svc``)."""

    def __init__(self, thread_ids: list[str], recorder: _ThreadFetchRecorder):
        self._thread_ids = thread_ids
        self._recorder = recorder

    def users(self):
        return self

    def threads(self):
        return self

    def list(self, userId=None, q=None, maxResults=None):  # noqa: N803
        return _FakeListRequest(self._thread_ids)

    def get(self, userId=None, id=None, format=None):  # noqa: A002,N803
        return _FakeThreadRequest(id, self._recorder)


def _connected_service(monkeypatch, thread_ids, recorder):
    """A ``GmailService`` with REAL (fresh, never-refreshing) google-auth
    credentials and a fake Gmail client — so ``_new_authorized_http`` builds a
    genuine ``AuthorizedHttp``/``httplib2.Http`` without any network call."""
    repo = _FakeAccountRepo(
        expiry=datetime.now(timezone.utc) + timedelta(hours=1), access_token="STILL_GOOD"
    )
    svc = GmailService("u1", creds_repo=repo, account_id="acct1")
    monkeypatch.setattr(svc, "_client", lambda: _FakeGmailApi(thread_ids, recorder))
    return svc, repo


# ------------------------------------------------------- parallel thread fetch
def test_list_threads_fetches_details_in_parallel_with_per_thread_http_client(
    monkeypatch,
):
    """The per-thread ``threads().get()`` fan-out must run on a bounded pool,
    and each worker thread must use its OWN ``AuthorizedHttp``.

    httplib2 (and therefore ``google_auth_httplib2.AuthorizedHttp``) is NOT
    thread-safe — sharing the service's single http object across workers
    corrupts connection state. The assertions below are the safety contract:
    every http object is seen by exactly ONE worker thread, and every worker
    thread uses exactly ONE http object (so connections are still reused within
    a thread). The barrier proves the concurrency is real, not incidental.
    """
    thread_ids = ["th1", "th2", "th3", "th4"]
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "4")
    recorder = _ThreadFetchRecorder(barrier_parties=len(thread_ids))
    svc, _repo = _connected_service(monkeypatch, thread_ids, recorder)

    threads = svc.list_threads(max_results=25)

    # Ordering/dedup semantics of the sequential code are preserved exactly.
    assert [t["gmailThreadId"] for t in threads] == thread_ids
    assert [t["subject"] for t in threads] == [f"Subject {t}" for t in thread_ids]
    # Real concurrency (the barrier only releases with all 4 in flight at once).
    assert recorder.barrier_passed is True, (
        "threads().get() calls never overlapped — the fetch is still sequential"
    )
    assert recorder.max_concurrent == len(thread_ids)
    assert len(recorder.thread_names) == len(thread_ids)
    # Per-worker http client: no http object crosses threads, no thread uses two.
    assert all(len(names) == 1 for names in recorder.threads_by_http().values())
    assert all(len(https) == 1 for https in recorder.http_by_thread().values())
    assert None not in recorder.threads_by_http(), (
        "a worker executed on the SHARED service http instead of its own client"
    )


def test_list_threads_parallel_result_is_identical_to_sequential(monkeypatch):
    """Result-equivalence: the parallel path must return byte-identical output
    to the sequential path (same threads, same order, same normalization)."""
    thread_ids = ["ta", "tb", "tc", "td", "te"]

    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "1")
    seq_recorder = _ThreadFetchRecorder()
    seq_svc, _ = _connected_service(monkeypatch, thread_ids, seq_recorder)
    sequential = seq_svc.list_threads(max_results=25)

    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "5")
    par_recorder = _ThreadFetchRecorder()
    par_svc, _ = _connected_service(monkeypatch, thread_ids, par_recorder)
    parallel = par_svc.list_threads(max_results=25)

    assert parallel == sequential
    assert seq_recorder.fetched_order == thread_ids
    assert sorted(par_recorder.fetched_order) == sorted(thread_ids)
    # The "parallel" run must genuinely have used the pool (every fetch on a
    # worker's own http), otherwise this equivalence proves nothing.
    assert None not in par_recorder.threads_by_http()
    # workers=1 must stay strictly sequential on the calling thread with the
    # shared service http (no pool, no per-thread client).
    assert seq_recorder.max_concurrent == 1
    assert seq_recorder.threads_by_http() == {None: {"MainThread"}}


def test_list_threads_falls_back_to_sequential_when_a_worker_fails(monkeypatch, caplog):
    """Fail-safe: ANY per-thread failure in the parallel path must be retried on
    the sequential path (shared service http, calling thread) so the sync still
    returns the COMPLETE, correctly-ordered thread set — with exactly one INFO
    log recording the degradation (never a silent partial result)."""
    import logging

    thread_ids = ["tx1", "tx2", "tx3", "tx4"]
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "4")
    recorder = _ThreadFetchRecorder(fail_once={"tx3"})
    svc, _repo = _connected_service(monkeypatch, thread_ids, recorder)

    with caplog.at_level(logging.INFO, logger="app.services.gmail_service"):
        threads = svc.list_threads(max_results=25)

    assert [t["gmailThreadId"] for t in threads] == thread_ids
    # tx3 was attempted twice: once in a worker (failed), once sequentially.
    tx3_calls = [c for c in recorder.calls if c[0] == "tx3"]
    assert len(tx3_calls) == 2
    assert tx3_calls[1][1] == "MainThread"
    assert tx3_calls[1][2] is None, "sequential fallback must use the shared service http"
    # Exactly one INFO — the degradation is reported once, not per thread.
    degraded = [
        r
        for r in caplog.records
        if r.name == "app.services.gmail_service" and r.levelno == logging.INFO
    ]
    assert len(degraded) == 1, [r.getMessage() for r in degraded]


def test_list_threads_stays_sequential_without_resolvable_credentials(monkeypatch):
    """Without credentials there is no way to build a per-thread authorized
    client, so the fetch must stay sequential rather than share one non
    thread-safe http across workers."""
    thread_ids = ["tn1", "tn2", "tn3"]
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "5")
    recorder = _ThreadFetchRecorder()
    svc = GmailService("u1", creds_repo=_FakeCreds())
    monkeypatch.setattr(svc, "_client", lambda: _FakeGmailApi(thread_ids, recorder))

    threads = svc.list_threads(max_results=25)

    assert [t["gmailThreadId"] for t in threads] == thread_ids
    assert recorder.max_concurrent == 1
    assert recorder.threads_by_http() == {None: {"MainThread"}}


def test_serialized_credentials_refreshes_once_under_concurrency():
    """The shared credentials object is refreshed by AT MOST ONE thread.

    google-auth 2.55.2 does NOT serialize this: ``Credentials.before_request``
    -> ``_blocking_refresh`` (google/auth/credentials.py) is an unguarded
    ``if not self.valid: self.refresh(request)``, and
    ``google_auth_httplib2.AuthorizedHttp.request`` calls ``credentials.refresh``
    on a 401 with no lock either. Two workers hitting an expired token would run
    two concurrent refresh grants — the second invalidating the first's token.
    """
    import threading

    from app.services.gmail_service import _SerializedCredentials

    class _Creds:
        def __init__(self):
            self.valid = False
            self.refresh_calls = 0
            self.applied = 0

        def refresh(self, request):
            import time

            time.sleep(0.05)  # widen the race window
            self.refresh_calls += 1
            self.valid = True

        def before_request(self, request, method, url, headers):
            if not self.valid:
                self.refresh(request)
            self.applied += 1

    creds = _Creds()
    guarded = _SerializedCredentials(creds, threading.Lock())
    start = threading.Barrier(8)

    def _worker():
        start.wait(timeout=5.0)
        guarded.refresh(object())
        guarded.before_request(object(), "GET", "https://example/", {})

    workers = [threading.Thread(target=_worker) for _ in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=10.0)

    assert creds.refresh_calls == 1, "concurrent refresh was not serialized"
    assert creds.applied == 8
    assert guarded.valid is True


# --------------------------------------------------------------- TTL freshness
def test_is_email_sync_fresh_semantics(monkeypatch):
    """The TTL gate's exact contract (default 120s, env-overridable)."""
    from app.services.gmail_service import email_sync_ttl_seconds, is_email_sync_fresh

    monkeypatch.delenv("AETHER_EMAIL_SYNC_TTL_SECONDS", raising=False)
    assert email_sync_ttl_seconds() == 120

    now = datetime.now(timezone.utc)
    # Never synced -> always stale (must sync).
    assert is_email_sync_fresh(None, now=now) is False
    # Inside the window -> fresh (serve from DB, ZERO Gmail I/O).
    assert is_email_sync_fresh(now - timedelta(seconds=5), now=now) is True
    assert is_email_sync_fresh(now - timedelta(seconds=119), now=now) is True
    # Outside the window -> stale.
    assert is_email_sync_fresh(now - timedelta(seconds=121), now=now) is False
    assert is_email_sync_fresh(now - timedelta(hours=3), now=now) is False
    # A naive stored timestamp is read as UTC (never crashes the inbox).
    assert is_email_sync_fresh((now - timedelta(seconds=5)).replace(tzinfo=None), now=now) is True
    # lastSyncedAt is stamped by the DATABASE clock and compared to the API
    # process clock; the hosted Postgres runs ~3s AHEAD of the app server, so a
    # small future offset MUST still count as fresh — rejecting it disables the
    # gate outright on this deployment (observed 2026-07-29).
    assert is_email_sync_fresh(now + timedelta(seconds=3), now=now) is True
    assert is_email_sync_fresh(now + timedelta(seconds=119), now=now) is True
    # An implausible future stamp must never stall the sync forever.
    assert is_email_sync_fresh(now + timedelta(minutes=10), now=now) is False

    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "600")
    assert email_sync_ttl_seconds() == 600
    assert is_email_sync_fresh(now - timedelta(seconds=300), now=now) is True

    # 0/negative disables the gate entirely (always sync — the old behaviour).
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "0")
    assert is_email_sync_fresh(now - timedelta(seconds=1), now=now) is False

    # A malformed value falls back to the default rather than crashing.
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "not-a-number")
    assert email_sync_ttl_seconds() == 120


def test_email_sync_max_workers_is_bounded(monkeypatch):
    """Worker count is env-capped and clamped to a sane range (never unbounded
    fan-out at Gmail, never zero workers)."""
    from app.services.gmail_service import email_sync_max_workers

    monkeypatch.delenv("AETHER_EMAIL_SYNC_MAX_WORKERS", raising=False)
    assert email_sync_max_workers() == 5
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "3")
    assert email_sync_max_workers() == 3
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "0")
    assert email_sync_max_workers() == 1
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "999")
    assert email_sync_max_workers() == 10
    monkeypatch.setenv("AETHER_EMAIL_SYNC_MAX_WORKERS", "junk")
    assert email_sync_max_workers() == 5
