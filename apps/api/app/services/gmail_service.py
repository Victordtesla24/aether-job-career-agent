"""Gmail API service — real send / sync / label operations for the Email Agent.

Wraps the Gmail v1 API with the user's stored OAuth credentials
(:class:`app.repositories.gmail_account.GmailAccountRepository`, the multi-account
store — GAP-D2). Access tokens are auto-refreshed from the long-lived refresh
token and the new token is persisted back, so a session never dies mid-flight. A
revoked/expired grant surfaces as :class:`GmailNotConnectedError` (the caller
degrades honestly and tells the user to reconnect) — never as an opaque 500.

Google client libraries are imported lazily inside methods (matching the
codebase's ``import httpx`` convention) so importing this module — e.g. from the
approvals router — never requires the google packages at import time.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts
from app.repositories.gmail_account import GmailAccountRepository
from app.services.google_oauth import GOOGLE_SCOPES

logger = logging.getLogger(__name__)

#: Distinct advisory-lock ids for the additive EmailThread DDL. See the lock-id
#: ledger in app/repositories/background_jobs.py — 717 is taken
#: (user_provider_credential) and 722 (background_jobs), so the aiScore lock uses
#: the next free id, 723.
_EMAIL_COLS_LOCK = 7420240716
_EMAIL_AI_COLS_LOCK = 7420240723

#: Gmail caps a single message at 25 MB (attachments + body, pre-base64).
_MAX_MESSAGE_BYTES = 25 * 1024 * 1024

#: Conservative fallback TTL applied when a refresh grant's response carries no
#: expiry at all (``creds.expiry is None`` after ``creds.refresh()``). Google's
#: access tokens are ~1h in practice, so 55 minutes is comfortably inside that
#: window without risking a false "still fresh" read (qa-res-001 niceToHave (c)).
_FALLBACK_EXPIRY_MINUTES = 55

#: Freshness window (seconds) for the Email Center's best-effort inbox sync.
#: A sync is threads().list() + up to ``max_results`` threads().get() round-trips
#: PER connected account, so re-running it on every page load put ~11s of Gmail
#: I/O inline in the request path (W-6). Within this window the stored
#: ``EmailThread`` copy is served as-is — no Gmail call at all.
_DEFAULT_SYNC_TTL_SECONDS = 120

#: Bounded fan-out for the per-thread detail fetch. Small on purpose: Gmail
#: per-user rate limits are shared across the whole account, and each worker
#: holds its own TCP/TLS connection.
_DEFAULT_SYNC_MAX_WORKERS = 5
_MAX_SYNC_WORKERS = 10

#: Sentinel for "this thread has no result yet" — distinct from any legitimate
#: (even falsy) Gmail payload.
_UNFETCHED = object()

_cols_ready = False
_ai_cols_ready = False


def _env_int(name: str, default: int) -> int:
    """Read an integer knob from the environment, degrading to ``default`` on a
    missing/malformed value (a typo in a deploy env must never 500 the inbox)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(
            "%s=%r is not an integer — falling back to %d", name, raw, default
        )
        return default


def email_sync_ttl_seconds() -> int:
    """Freshness window for the inbox sync, from ``AETHER_EMAIL_SYNC_TTL_SECONDS``
    (default 120). Zero or negative DISABLES the gate — every request syncs, the
    pre-W-6 behaviour."""
    return _env_int("AETHER_EMAIL_SYNC_TTL_SECONDS", _DEFAULT_SYNC_TTL_SECONDS)


def email_sync_max_workers() -> int:
    """Worker cap for the parallel thread-detail fetch, from
    ``AETHER_EMAIL_SYNC_MAX_WORKERS`` (default 5), clamped to
    ``1.._MAX_SYNC_WORKERS`` so a bad value can neither disable the fetch nor
    unleash unbounded fan-out at Gmail. ``1`` keeps the fetch strictly
    sequential."""
    return max(
        1,
        min(
            _env_int("AETHER_EMAIL_SYNC_MAX_WORKERS", _DEFAULT_SYNC_MAX_WORKERS),
            _MAX_SYNC_WORKERS,
        ),
    )


def is_email_sync_fresh(
    last_synced_at: Optional[datetime], now: Optional[datetime] = None
) -> bool:
    """True when an account's last sync is recent enough to serve the stored
    threads without touching Gmail (W-6 TTL gate).

    Deliberately conservative — it returns False (i.e. "sync") whenever
    freshness cannot be positively established:

    * never synced (``None``) — there may be nothing in the DB at all;
    * the TTL is disabled (``<= 0``);
    * the stamp is implausible (further in the future than one whole TTL),
      which must never stall the user's inbox indefinitely.

    Small future offsets ARE treated as fresh: ``lastSyncedAt`` is stamped by
    the DATABASE clock (``mark_synced`` writes ``now()``) and compared here
    against the API process clock, and the hosted Postgres runs measurably
    ahead of the app server (~3s observed 2026-07-29). Rejecting every future
    stamp would disable the gate entirely on this deployment, so the comparison
    is symmetric: fresh when the two stamps are within one TTL of each other,
    in either direction.

    A naive stamp is read as UTC — ``GmailAccount.lastSyncedAt`` is
    ``timestamptz`` (always aware in practice), but a naive value must degrade
    rather than raise into the inbox request.
    """
    ttl = email_sync_ttl_seconds()
    if ttl <= 0 or not isinstance(last_synced_at, datetime):
        return False
    if last_synced_at.tzinfo is None:
        last_synced_at = last_synced_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age_seconds = (now - last_synced_at).total_seconds()
    return abs(age_seconds) < ttl


class _SerializedCredentials:
    """Thread-safe façade over ONE shared google-auth ``Credentials`` object.

    The bounded parallel thread fetch gives every worker its own
    ``AuthorizedHttp`` (httplib2 is not thread-safe) but they all authenticate
    from the same credentials instance, and google-auth does NOT serialize a
    refresh: ``Credentials.before_request`` -> ``_blocking_refresh``
    (google/auth/credentials.py) is a bare ``if not self.valid:
    self.refresh(request)``, and ``google_auth_httplib2.AuthorizedHttp.request``
    calls ``credentials.refresh`` on a 401 with no lock either (verified against
    google-auth 2.55.2 / google-auth-httplib2 0.3.1). Two workers meeting an
    expired token would therefore run two concurrent refresh grants — and
    Google's newer token can invalidate the older one mid-flight.

    This wrapper holds one lock across the whole check-then-refresh, and
    re-checks validity inside :meth:`refresh` so the second caller skips a
    redundant grant. In practice no refresh happens here at all: the eager
    refresh in :meth:`GmailService._credentials` (which also PERSISTS the new
    token) runs on the calling thread before any worker starts. A refresh from a
    worker is the rare mid-flight-expiry case and stays in memory only —
    identical to the pre-existing ``AuthorizedHttp`` 401-retry behaviour, so the
    stored token is simply refreshed-and-persisted on the next request.

    Only the surface ``AuthorizedHttp`` actually uses is exposed
    (``before_request``/``refresh``, plus read-through ``token``/``valid``).
    """

    __slots__ = ("_creds", "_lock")

    def __init__(self, credentials: Any, lock: threading.Lock) -> None:
        self._creds = credentials
        self._lock = lock

    def before_request(self, request: Any, method: str, url: str, headers: Any) -> None:
        with self._lock:
            self._creds.before_request(request, method, url, headers)

    def refresh(self, request: Any) -> None:
        with self._lock:
            if getattr(self._creds, "valid", False):
                # Another worker already refreshed under this same lock.
                return
            self._creds.refresh(request)

    @property
    def token(self) -> Any:
        return self._creds.token

    @property
    def valid(self) -> bool:
        return bool(self._creds.valid)


class GmailError(RuntimeError):
    """A Gmail API call failed (network, quota, malformed request)."""


class GmailNotConnectedError(GmailError):
    """No Gmail credential stored — the user has never connected an account."""


class GmailAuthError(GmailError):
    """A stored credential exists but the grant is expired/revoked — the user
    must reconnect. Distinct from :class:`GmailNotConnectedError` so callers can
    message "reconnect" vs "connect" precisely, though both fail the send-gate."""


def ensure_email_thread_gmail_columns() -> None:
    """Idempotently add the Gmail linkage columns to the Prisma-managed
    ``EmailThread`` table (additive, backward-compatible; survives TRUNCATE).

    ``gmailAccountId`` (GAP-D2) links each thread to the specific connected Gmail
    inbox it came from, so the unified inbox can badge each thread and an
    ``?account_id`` filter can narrow to one mailbox. Existing threads are
    backfilled to the user's primary ``GmailAccount``."""
    global _cols_ready
    if _cols_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'EmailThread'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('gmailThreadId', 'gmailMessageId', 'labels',"
                " 'gmailAccountId')"
            )
            row = cur.fetchone()
            if row and row[0] == 4:
                _cols_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_EMAIL_COLS_LOCK,))
            cur.execute(
                'ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "gmailThreadId" text'
            )
            cur.execute(
                'ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "gmailMessageId" text'
            )
            cur.execute(
                'ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "labels" text[]'
            )
            cur.execute(
                'ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "gmailAccountId" text'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_emailthread_gmail"'
                ' ON "EmailThread" ("userId", "gmailThreadId")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_emailthread_account"'
                ' ON "EmailThread" ("userId", "gmailAccountId")'
            )
        conn.commit()
    # Backfill existing threads to the user's primary account (needs GmailAccount
    # to exist first — its ensure also backfills legacy GoogleCredential rows).
    GmailAccountRepository()._ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "EmailThread" et SET "gmailAccountId" = ga."id"
                FROM "GmailAccount" ga
                WHERE et."gmailAccountId" IS NULL
                  AND ga."userId" = et."userId"
                  AND ga."isPrimary"
                '''
            )
        conn.commit()
    _cols_ready = True


def ensure_email_thread_ai_columns() -> None:
    """Idempotently add the additive ``aiScore`` column to ``EmailThread``
    (backward-compatible; survives TRUNCATE).

    ``aiScore`` (MV-email-center-001) persists the integer 0-100 triage score the
    :class:`app.agents.email_agent.EmailAgent` produces for a thread, so the
    Email Command Center list can surface the REAL per-thread score instead of a
    hardcoded 0. It is nullable and stays NULL until a thread is actually triaged
    — an un-triaged thread has NO score (never a fabricated 0)."""
    global _ai_cols_ready
    if _ai_cols_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'EmailThread'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'aiScore'"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _ai_cols_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_EMAIL_AI_COLS_LOCK,))
            cur.execute(
                'ALTER TABLE "EmailThread" ADD COLUMN IF NOT EXISTS "aiScore" integer'
            )
        conn.commit()
    _ai_cols_ready = True


def _header(headers: list[dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _split_address(raw: str) -> tuple[str, str]:
    """Split ``"Sarah Chen <sarah@acme.com>"`` into (display, email)."""
    raw = (raw or "").strip()
    if "<" in raw and ">" in raw:
        display = raw.split("<", 1)[0].strip().strip('"')
        addr = raw.split("<", 1)[1].split(">", 1)[0].strip()
        return display or addr, addr
    return raw, raw


def _decode_body(payload: dict[str, Any]) -> str:
    """Extract a best-effort plain-text body from a Gmail message payload."""
    def walk(part: dict[str, Any]) -> Optional[str]:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data.encode()).decode(
                    "utf-8", errors="replace"
                )
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        return None

    return (walk(payload) or "").strip()


def _decode_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    """Both alternatives of a MIME message: ``(text/plain, text/html)``.

    ``_decode_body`` above returns the FIRST text/plain part it finds, which is
    all the inbox needs. The job-alert parser needs both: HTML alert mail keeps
    the real apply URL in an anchor href, while SEEK does the opposite — its
    HTML routes every card through a per-recipient click tracker and only the
    text/plain alternative carries the genuine ``au.seek.com/job/<id>`` URL.
    Returns ``("", "")`` for a payload with neither; never raises.
    """
    found: dict[str, str] = {}

    def walk(part: dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        if data and mime in ("text/plain", "text/html") and mime not in found:
            try:
                found[mime] = base64.urlsafe_b64decode(data.encode()).decode(
                    "utf-8", errors="replace"
                )
            except Exception:  # noqa: BLE001 — a malformed part must not kill the scan
                logger.info("Gmail message part %s could not be decoded", mime)
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload or {})
    return found.get("text/plain", ""), found.get("text/html", "")


class GmailService:
    """Per-user Gmail client. Construct with the app ``user_id``."""

    def __init__(
        self,
        user_id: str,
        creds_repo: GmailAccountRepository | None = None,
        account_id: str | None = None,
    ) -> None:
        self._user_id = user_id
        self._creds_repo = creds_repo or GmailAccountRepository()
        #: The specific connected inbox to operate on. ``None`` means the user's
        #: primary account (backward-compatible single-account behaviour).
        self._account_id = account_id
        #: The account id actually resolved once credentials are loaded — used to
        #: tag synced threads and to persist refreshed tokens to the right row.
        self._resolved_account_id: str | None = account_id
        self._service: Any = None
        #: The credentials object backing ``_service`` — reused (never re-read
        #: from the DB) to mint the per-worker HTTP clients of the parallel
        #: thread fetch, and guarded by ``_credentials_lock`` there.
        self._shared_credentials: Any = None
        self._credentials_lock = threading.Lock()

    # ------------------------------------------------------------------ auth
    def _credentials(self) -> Any:
        # Pass account_id only when targeting a specific inbox so single-account
        # repos/fakes with a one-arg get() keep working (backward compatible).
        if self._account_id is not None:
            row = self._creds_repo.get(self._user_id, self._account_id)
        else:
            row = self._creds_repo.get(self._user_id)
        if not row or not row.get("refreshToken"):
            raise GmailNotConnectedError(
                "Gmail is not connected — connect your account to continue."
            )
        self._resolved_account_id = row.get("id")
        from google.oauth2.credentials import Credentials

        # QA-RES-001: google-auth's Credentials.expired treats expiry=None as
        # "never expires", so omitting it here made creds.valid always True
        # regardless of the token's real (stored) staleness — the explicit
        # refresh-and-persist branch below never fired, every request sent a
        # stale token, and google_auth_httplib2's built-in 401-retry silently
        # refreshed it in memory only (never persisted). google-auth's
        # internal .expired check compares against a NAIVE UTC "now"
        # (google/auth/_helpers.py), so the DB's timezone-aware tokenExpiry
        # must be normalized to naive UTC or the comparison raises TypeError.
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
            scopes=(row.get("scopes") or "").split() or GOOGLE_SCOPES,
            expiry=expiry,
        )
        if not creds.valid:
            # Missing server OAuth config is OUR fault, not the user's grant
            # being revoked — google-auth's own RefreshError message for this
            # case ("credentials do not contain the necessary fields") reads
            # exactly like a revoked grant, which would wrongly tell every
            # user to reconnect their (perfectly fine) account. Surface it as
            # a transient GmailError instead, before ever calling refresh().
            if not client_id or not client_secret:
                detail = (
                    "Gmail email service is temporarily unavailable — server "
                    "OAuth configuration is missing."
                )
                # qa-res-001-review-verdict niceToHave: the routers raise their
                # HTTPException `from None` (approvals.py, workspaces.py), which
                # discards this detail — log it here, at the source, so ops can
                # actually see the misconfiguration instead of it reaching
                # neither the user nor the logs.
                logger.error(
                    "Gmail service misconfigured for user=%s account=%s: %s",
                    self._user_id,
                    self._resolved_account_id,
                    detail,
                )
                raise GmailError(detail)

            from google.auth.exceptions import RefreshError, TransportError
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise GmailAuthError(
                    "Gmail authorization expired or was revoked — reconnect your "
                    "account."
                ) from exc
            except TransportError as exc:
                # A sibling of RefreshError under GoogleAuthError (NOT a
                # subclass) — raised by google.auth.transport.requests.Request
                # on any requests-level failure talking to Google's token
                # endpoint (DNS, connect timeout, connection reset). This is a
                # transient infra hiccup, not an auth problem — map it to the
                # ordinary GmailError taxonomy so callers keep their existing
                # honest "transient failure" handling instead of wrongly
                # telling the user to reconnect.
                raise GmailError(
                    f"Gmail token refresh failed (transient network error): {exc}"
                ) from exc

            # google-auth's refresh_grant hands back a NAIVE UTC datetime
            # (google/auth/_helpers.py); stamp it explicitly aware-UTC before
            # persisting to the `timestamp with time zone` column so its
            # meaning is self-describing regardless of Postgres session
            # TimeZone (symmetric with google_oauth.py's exchange_code).
            new_expiry = creds.expiry
            if new_expiry is not None and new_expiry.tzinfo is None:
                new_expiry = new_expiry.replace(tzinfo=timezone.utc)
            elif new_expiry is None:
                # qa-res-001-review-verdict niceToHave (c): a refresh response
                # without ``expires_in`` leaves ``creds.expiry`` at ``None`` —
                # and google-auth's OWN ``.expired`` treats expiry=None as
                # "never expires". Persisting NULL here would silently
                # RE-DISABLE this very fix for this one account: every future
                # read would see "never expires" and skip refresh forever,
                # regardless of how stale the token really gets. Fall back to
                # a conservative now+55min (Google's refresh grants run ~1h in
                # practice) so the next request's staleness check still fires
                # well before the real token could have expired.
                new_expiry = datetime.now(timezone.utc) + timedelta(
                    minutes=_FALLBACK_EXPIRY_MINUTES
                )
                creds.expiry = new_expiry.replace(tzinfo=None)
                logger.info(
                    "Gmail refresh response for user=%s account=%s carried no "
                    "expiry — falling back to a conservative now+%dmin expiry "
                    "instead of persisting NULL",
                    self._user_id,
                    self._resolved_account_id,
                    _FALLBACK_EXPIRY_MINUTES,
                )

            self._creds_repo.update_access_token(
                self._user_id,
                creds.token,
                new_expiry,
                account_id=self._resolved_account_id,
            )
        self._shared_credentials = creds
        return creds

    def _client(self) -> Any:
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build(
                "gmail", "v1", credentials=self._credentials(), cache_discovery=False
            )
        return self._service

    # --------------------------------------------------------------- reading
    def list_threads(
        self, query: str | None = None, max_results: int = 25
    ) -> list[dict[str, Any]]:
        """Return normalized recent threads (newest message per thread)."""
        try:
            # QA-RES-001 M2: _client() now performs a real (possibly hot)
            # credential refresh via _credentials() instead of a no-op
            # construction, so it must live INSIDE this GmailError-wrapping
            # try — otherwise a token-endpoint hiccup escapes raw past
            # callers that only catch GmailError/GmailAuthError.
            svc = self._client()
            resp = (
                svc.users()
                .threads()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            thread_ids = [t["id"] for t in resp.get("threads", [])]
            return [
                self._normalize_thread(full)
                for full in self._fetch_thread_details(svc, thread_ids)
            ]
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail thread list failed: {exc}") from exc

    def _new_authorized_http(self, credentials: Any) -> Any:
        """A FRESH ``AuthorizedHttp`` (its own ``httplib2.Http`` connection pool)
        for ONE worker thread.

        ``httplib2.Http`` is NOT thread-safe, so the service's single shared http
        object must never be used concurrently. ``build_http()`` is the same
        constructor ``googleapiclient`` uses for the service's own client, so the
        worker inherits the library's default socket timeout and redirect
        handling verbatim. The credentials are shared (one token, one refresh)
        but wrapped so a refresh is serialized."""
        import google_auth_httplib2
        from googleapiclient.http import build_http

        return google_auth_httplib2.AuthorizedHttp(
            _SerializedCredentials(credentials, self._credentials_lock),
            http=build_http(),
        )

    def _fetch_thread_details(
        self, svc: Any, thread_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Full payload for every id in ``thread_ids``, in the SAME order.

        Gmail has no batch "get these N threads" call, so this used to be up to
        25 SEQUENTIAL round-trips inline in the inbox request (W-6, ~11s
        observed). They are now issued on a small bounded pool, each worker
        using its own HTTP client.

        Fail-safe: results are placed by index, so ordering (and therefore the
        caller's dedup/upsert semantics) is identical to the sequential code. If
        ANY worker raises, every still-unfetched thread is retried on the
        sequential path with the shared service client and ONE INFO is logged —
        a partial result is never returned, and a persistent failure still
        surfaces as ``GmailError`` exactly as before."""
        requests = [
            svc.users().threads().get(userId="me", id=tid, format="full")
            for tid in thread_ids
        ]
        workers = min(email_sync_max_workers(), len(requests))

        credentials = self._shared_credentials
        if workers > 1 and credentials is None:
            # A caller that injected a client directly (tests) may never have
            # resolved credentials; resolve them ONCE here, on this thread.
            try:
                credentials = self._credentials()
            except GmailError:
                credentials = None

        if workers < 2 or credentials is None:
            # Sequential: one client, one thread — the pre-W-6 path, kept for a
            # single thread, an env-disabled pool, or credentials we cannot
            # duplicate per worker (sharing one httplib2.Http would be unsafe).
            return [req.execute() for req in requests]

        results: list[Any] = [_UNFETCHED] * len(requests)
        worker_state = threading.local()
        opened_https: list[Any] = []
        opened_lock = threading.Lock()
        first_error: Exception | None = None

        def _run(index: int) -> None:
            http = getattr(worker_state, "http", None)
            if http is None:
                # ONE client per worker thread (not per request), so this
                # thread's connections are still reused across its threads.get()
                # calls while never being touched by another thread.
                http = self._new_authorized_http(credentials)
                worker_state.http = http
                with opened_lock:
                    opened_https.append(http)
            results[index] = requests[index].execute(http=http)

        try:
            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="gmail-thread-fetch"
            ) as pool:
                for future in [pool.submit(_run, i) for i in range(len(requests))]:
                    try:
                        future.result()
                    except Exception as exc:  # noqa: BLE001 — retried sequentially
                        if first_error is None:
                            first_error = exc
        finally:
            # Release the worker sockets deterministically instead of waiting
            # for GC (the pool's threads are gone by now, so nothing can be
            # using them). Never let a close failure mask a real Gmail error.
            for opened in opened_https:
                try:
                    opened.close()
                except Exception:  # noqa: BLE001
                    pass

        if first_error is not None:
            pending = [i for i, result in enumerate(results) if result is _UNFETCHED]
            logger.info(
                "Gmail parallel thread fetch degraded to sequential for %d/%d "
                "threads (first error: %s)",
                len(pending),
                len(requests),
                first_error,
            )
            for index in pending:
                results[index] = requests[index].execute()

        return results

    @staticmethod
    def _normalize_thread(full: dict[str, Any]) -> dict[str, Any]:
        messages = full.get("messages", []) or []
        latest = messages[-1] if messages else {}
        headers = latest.get("payload", {}).get("headers", [])
        display, addr = _split_address(_header(headers, "From"))
        return {
            "gmailThreadId": full.get("id"),
            "gmailMessageId": latest.get("id"),
            "subject": _header(headers, "Subject") or "(no subject)",
            "from": display,
            "fromEmail": addr,
            "snippet": latest.get("snippet", ""),
            "body": _decode_body(latest.get("payload", {})) or latest.get("snippet", ""),
            "receivedAt": _header(headers, "Date"),
            "labelIds": latest.get("labelIds", []),
            "messageCount": len(messages),
        }

    # ------------------------------------------------- message-level reading
    #: Hard ceiling on one job-alert scan, so a huge mailbox can never turn one
    #: agent run into thousands of Gmail calls.
    MAX_SCAN_MESSAGES = 500

    def list_message_headers(
        self, query: str | None = None, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """``[{"id", "from", "subject", "date"}]`` for messages matching ``query``.

        METADATA format on purpose: identifying job-alert mail only needs the
        From and Subject headers, and a metadata fetch is a fraction of the
        Gmail quota cost of a full fetch. The full body is pulled (by
        :meth:`get_message_bodies`) ONLY for the messages that turn out to be
        alerts, which in the operator's own mailbox is 2 of 41.
        """
        max_results = max(1, min(int(max_results), self.MAX_SCAN_MESSAGES))
        try:
            svc = self._client()
            resp = (
                svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            headers: list[dict[str, Any]] = []
            for item in resp.get("messages", []) or []:
                msg = (
                    svc.users()
                    .messages()
                    .get(
                        userId="me",
                        id=item["id"],
                        format="metadata",
                        metadataHeaders=["From", "Subject", "Date"],
                    )
                    .execute()
                )
                raw = (msg.get("payload") or {}).get("headers", [])
                headers.append(
                    {
                        "id": msg.get("id"),
                        # Additive (sales agent): the thread id is needed for
                        # reply threading + the DB send-idempotency gate.
                        "threadId": msg.get("threadId"),
                        "from": _header(raw, "From"),
                        "subject": _header(raw, "Subject"),
                        "date": _header(raw, "Date"),
                    }
                )
            return headers
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail message list failed: {exc}") from exc

    def get_message_bodies(self, message_id: str) -> dict[str, Any]:
        """One message's headers plus BOTH body alternatives
        (``{"id", "from", "subject", "date", "text", "html"}``)."""
        try:
            svc = self._client()
            msg = (
                svc.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail message fetch failed: {exc}") from exc
        payload = msg.get("payload") or {}
        raw = payload.get("headers", [])
        text, html = _decode_bodies(payload)
        return {
            "id": msg.get("id"),
            # Additive (sales agent): thread id for reply threading/idempotency.
            "threadId": msg.get("threadId"),
            "from": _header(raw, "From"),
            "subject": _header(raw, "Subject"),
            "date": _header(raw, "Date"),
            "text": text,
            "html": html,
        }

    def list_labels(self) -> list[dict[str, Any]]:
        svc = self._client()
        try:
            return svc.users().labels().list(userId="me").execute().get("labels", [])
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail label list failed: {exc}") from exc

    # --------------------------------------------------------------- writing
    def _raw_message(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        html_body: str | None = None,
    ) -> str:
        """Build the base64url raw message. When ``html_body`` is given, the
        text ``body`` and the HTML are wrapped in ``multipart/alternative``
        (plain part FIRST per RFC 2046 — least-faithful to most-faithful), so
        text-only clients still get the full compliance-footed plain body."""
        msg: Any

        def _content_part() -> Any:
            if html_body:
                alt = MIMEMultipart("alternative")
                alt.attach(MIMEText(body, "plain", "utf-8"))
                alt.attach(MIMEText(html_body, "html", "utf-8"))
                return alt
            return MIMEText(body, "plain", "utf-8")

        if attachments:
            msg = MIMEMultipart()
            msg.attach(_content_part())
            total = len(body.encode("utf-8")) + len((html_body or "").encode("utf-8"))
            for filename, content, mimetype in attachments:
                total += len(content)
                if total > _MAX_MESSAGE_BYTES:
                    raise GmailError(
                        "Message exceeds Gmail's 25 MB limit with attachments."
                    )
                maintype, _, subtype = mimetype.partition("/")
                part = MIMEBase(maintype or "application", subtype or "octet-stream")
                part.set_payload(content)
                from email import encoders

                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition", "attachment", filename=filename
                )
                msg.attach(part)
        else:
            msg = _content_part()
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        in_reply_to: str | None = None,
        thread_id: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        html_body: str | None = None,
    ) -> dict[str, Any]:
        """Send an email; returns ``{"id", "threadId"}``. Raises
        :class:`GmailNotConnectedError` when the account is not connected.
        ``html_body`` (optional, additive) sends multipart/alternative with
        the plain-text ``body`` preserved as the first alternative."""
        raw = self._raw_message(
            to, subject, body, in_reply_to, attachments, html_body=html_body
        )
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        try:
            # QA-RES-001 M2: _client() now performs a real (possibly hot)
            # credential refresh via _credentials() instead of a no-op
            # construction, so it must live INSIDE this GmailError-wrapping
            # try — otherwise a token-endpoint hiccup escapes raw past
            # approvals.py, turning the honest "no email was sent" 502 into
            # an unhandled 500.
            svc = self._client()
            sent = svc.users().messages().send(userId="me", body=message).execute()
            return {"id": sent.get("id"), "threadId": sent.get("threadId")}
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail send failed: {exc}") from exc

    def modify_labels(
        self, message_id: str, add: list[str] | None = None, remove: list[str] | None = None
    ) -> dict[str, Any]:
        svc = self._client()
        try:
            return (
                svc.users()
                .messages()
                .modify(
                    userId="me",
                    id=message_id,
                    body={
                        "addLabelIds": add or [],
                        "removeLabelIds": remove or [],
                    },
                )
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail label modify failed: {exc}") from exc

    def trash(self, message_id: str) -> dict[str, Any]:
        svc = self._client()
        try:
            return svc.users().messages().trash(userId="me", id=message_id).execute()
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail trash failed: {exc}") from exc

    def ensure_label(self, name: str) -> str:
        """Return the id of the label named ``name``, creating it if absent."""
        for label in self.list_labels():
            if label.get("name") == name:
                return label["id"]
        svc = self._client()
        try:
            created = (
                svc.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
                .execute()
            )
            return created["id"]
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail label create failed: {exc}") from exc

    # ------------------------------------------------------------- syncing
    def sync_threads_to_db(
        self, user_id: str | None = None, query: str | None = None, max_results: int = 25
    ) -> int:
        """Fetch recent Gmail threads and upsert them into ``EmailThread``
        (keyed by ``gmailThreadId``). Returns the number of rows written.

        ``user_id`` defaults to the service's own user, so callers that already
        constructed ``GmailService(uid)`` can call ``.sync_threads_to_db()``."""
        user_id = user_id or self._user_id
        ensure_email_thread_gmail_columns()
        # list_threads loads credentials, which resolves the concrete account id
        # so each synced thread is tagged with the inbox it came from (GAP-D2).
        threads = self.list_threads(query=query, max_results=max_results)
        account_id = self._resolved_account_id
        written = 0
        with get_connection() as conn:
            with conn.cursor() as cur:
                for t in threads:
                    import json as _json

                    messages = _json.dumps(
                        [
                            {
                                "role": "received",
                                "body": t["body"],
                                "from": t["from"],
                                "fromEmail": t["fromEmail"],
                                "createdAt": t["receivedAt"],
                            }
                        ]
                    )
                    cur.execute(
                        'SELECT id FROM "EmailThread"'
                        ' WHERE "userId" = %s AND "gmailThreadId" = %s',
                        (user_id, t["gmailThreadId"]),
                    )
                    existing = rows_to_dicts(cur)
                    if existing:
                        cur.execute(
                            'UPDATE "EmailThread" SET "subject" = %s, "messages" = %s::jsonb,'
                            ' "gmailMessageId" = %s, "labels" = %s,'
                            ' "gmailAccountId" = COALESCE(%s, "gmailAccountId"),'
                            ' "updatedAt" = now()'
                            ' WHERE id = %s',
                            (
                                t["subject"],
                                messages,
                                t["gmailMessageId"],
                                t["labelIds"],
                                account_id,
                                existing[0]["id"],
                            ),
                        )
                    else:
                        cur.execute(
                            'INSERT INTO "EmailThread"'
                            ' ("id", "userId", "subject", "messages", "gmailThreadId",'
                            '  "gmailMessageId", "labels", "gmailAccountId",'
                            '  "createdAt", "updatedAt")'
                            ' VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, now(), now())',
                            (
                                new_id(),
                                user_id,
                                t["subject"],
                                messages,
                                t["gmailThreadId"],
                                t["gmailMessageId"],
                                t["labelIds"],
                                account_id,
                            ),
                        )
                    written += 1
            conn.commit()
        # Best-effort UI signal that this inbox just synced (never gates sending).
        if account_id:
            try:
                self._creds_repo.mark_synced(account_id)
            except Exception:  # noqa: BLE001 — a sync-status write must never fail the sync
                pass
        return written
