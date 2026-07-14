"""Gmail API service — real send / sync / label operations for the Email Agent.

Wraps the Gmail v1 API with the user's stored OAuth credentials
(:class:`app.repositories.google_credential.GoogleCredentialRepository`). Access
tokens are auto-refreshed from the long-lived refresh token and the new token is
persisted back, so a session never dies mid-flight. A revoked/expired grant
surfaces as :class:`GmailNotConnectedError` (the caller degrades honestly and
tells the user to reconnect) — never as an opaque 500.

Google client libraries are imported lazily inside methods (matching the
codebase's ``import httpx`` convention) so importing this module — e.g. from the
approvals router — never requires the google packages at import time.
"""
from __future__ import annotations

import base64
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from app.db import get_connection, new_id, rows_to_dicts
from app.repositories.google_credential import GoogleCredentialRepository
from app.services.google_oauth import GOOGLE_SCOPES

#: Distinct advisory-lock id for the additive EmailThread columns
#: (AgentConfig 711, User 712, CareerProfile 713, OutreachTask 714,
#: GoogleCredential 715).
_EMAIL_COLS_LOCK = 7420240716

#: Gmail caps a single message at 25 MB (attachments + body, pre-base64).
_MAX_MESSAGE_BYTES = 25 * 1024 * 1024

_cols_ready = False


class GmailError(RuntimeError):
    """A Gmail API call failed (network, quota, malformed request)."""


class GmailNotConnectedError(GmailError):
    """No Gmail credential stored — the user has never connected an account."""


class GmailAuthError(GmailError):
    """A stored credential exists but the grant is expired/revoked — the user
    must reconnect. Distinct from :class:`GmailNotConnectedError` so callers can
    message "reconnect" vs "connect" precisely, though both fail the send-gate."""


def gmail_connected(user_id: str) -> bool:
    """Whether a Gmail credential exists for ``user_id`` (the send-gate's truth
    source). Does not verify token liveness — existence is the contract; a
    revoked token surfaces at call time as :class:`GmailNotConnectedError`."""
    return GoogleCredentialRepository().is_connected(user_id)


def ensure_email_thread_gmail_columns() -> None:
    """Idempotently add the Gmail linkage columns to the Prisma-managed
    ``EmailThread`` table (additive, backward-compatible; survives TRUNCATE)."""
    global _cols_ready
    if _cols_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name = 'EmailThread'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name IN ('gmailThreadId', 'gmailMessageId', 'labels')"
            )
            row = cur.fetchone()
            if row and row[0] == 3:
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
                'CREATE INDEX IF NOT EXISTS "idx_emailthread_gmail"'
                ' ON "EmailThread" ("userId", "gmailThreadId")'
            )
        conn.commit()
    _cols_ready = True


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


class GmailService:
    """Per-user Gmail client. Construct with the app ``user_id``."""

    def __init__(
        self, user_id: str, creds_repo: GoogleCredentialRepository | None = None
    ) -> None:
        self._user_id = user_id
        self._creds_repo = creds_repo or GoogleCredentialRepository()
        self._service: Any = None

    # ------------------------------------------------------------------ auth
    def _credentials(self) -> Any:
        import os

        row = self._creds_repo.get(self._user_id)
        if not row or not row.get("refreshToken"):
            raise GmailNotConnectedError(
                "Gmail is not connected — connect your account to continue."
            )
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=row.get("accessToken"),
            refresh_token=row["refreshToken"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"),
            scopes=(row.get("scopes") or "").split() or GOOGLE_SCOPES,
        )
        if not creds.valid:
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request

            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise GmailAuthError(
                    "Gmail authorization expired or was revoked — reconnect your "
                    "account."
                ) from exc
            self._creds_repo.update_access_token(
                self._user_id, creds.token, creds.expiry
            )
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
        svc = self._client()
        try:
            resp = (
                svc.users()
                .threads()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            out: list[dict[str, Any]] = []
            for t in resp.get("threads", []):
                full = (
                    svc.users()
                    .threads()
                    .get(userId="me", id=t["id"], format="full")
                    .execute()
                )
                out.append(self._normalize_thread(full))
            return out
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail thread list failed: {exc}") from exc

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
    ) -> str:
        msg: Any
        if attachments:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain", "utf-8"))
            total = len(body.encode("utf-8"))
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
            msg = MIMEText(body, "plain", "utf-8")
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
    ) -> dict[str, Any]:
        """Send an email; returns ``{"id", "threadId"}``. Raises
        :class:`GmailNotConnectedError` when the account is not connected."""
        svc = self._client()
        raw = self._raw_message(to, subject, body, in_reply_to, attachments)
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        try:
            sent = svc.users().messages().send(userId="me", body=message).execute()
            return {"id": sent.get("id"), "threadId": sent.get("threadId")}
        except GmailError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail send failed: {exc}") from exc

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        svc = self._client()
        raw = self._raw_message(to, subject, body)
        message: dict[str, Any] = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        try:
            draft = (
                svc.users()
                .drafts()
                .create(userId="me", body={"message": message})
                .execute()
            )
            return {"id": draft.get("id")}
        except Exception as exc:  # noqa: BLE001
            raise GmailError(f"Gmail draft create failed: {exc}") from exc

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
        threads = self.list_threads(query=query, max_results=max_results)
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
                            ' "gmailMessageId" = %s, "labels" = %s, "updatedAt" = now()'
                            ' WHERE id = %s',
                            (
                                t["subject"],
                                messages,
                                t["gmailMessageId"],
                                t["labelIds"],
                                existing[0]["id"],
                            ),
                        )
                    else:
                        cur.execute(
                            'INSERT INTO "EmailThread"'
                            ' ("id", "userId", "subject", "messages", "gmailThreadId",'
                            '  "gmailMessageId", "labels", "createdAt", "updatedAt")'
                            ' VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, now(), now())',
                            (
                                new_id(),
                                user_id,
                                t["subject"],
                                messages,
                                t["gmailThreadId"],
                                t["gmailMessageId"],
                                t["labelIds"],
                            ),
                        )
                    written += 1
            conn.commit()
        return written
