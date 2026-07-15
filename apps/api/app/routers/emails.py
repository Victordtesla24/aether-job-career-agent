"""Emails router — draft and reply to email threads (P3).

Operates on the ``EmailThread`` model from the Prisma schema. Threads are
keyed by user and optionally linked to an application or contact.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.repositories.gmail_account import GmailAccountRepository, _mask_email
from app.services.google_oauth import (
    OAuthError,
    build_consent_url,
    oauth_configured,
    revoke_token,
)

router = APIRouter()

_COLUMNS = (
    'e."id", e."userId", e."applicationId", e."contactId", e."subject",'
    ' e."messages", e."classification", e."createdAt", e."updatedAt"'
)


class DraftEmail(BaseModel):
    """Payload for creating a new draft email thread."""

    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)
    application_id: str | None = None
    contact_id: str | None = None
    classification: str | None = Field(default=None, max_length=100)


class ReplyEmail(BaseModel):
    """Payload for replying to an existing email thread."""

    body: str = Field(min_length=1, max_length=20_000)
    classification: str | None = Field(default=None, max_length=100)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_threads(
    current_user: CurrentUser,
    application_id: str | None = None,
    contact_id: str | None = None,
    account_id: str | None = None,
) -> list[dict[str, Any]]:
    """List email threads for the current user.

    Optionally filter by ``?application_id=``, ``?contact_id=`` or
    ``?account_id=`` (a connected Gmail inbox). With no ``account_id`` the
    result is the UNIFIED inbox — threads from every connected account merged,
    newest first.
    """
    uid = current_user["id"]
    clauses = ['e."userId" = %s']
    params: list[Any] = [uid]

    if application_id is not None:
        clauses.append('e."applicationId" = %s')
        params.append(application_id)
    if contact_id is not None:
        clauses.append('e."contactId" = %s')
        params.append(contact_id)
    if account_id is not None:
        from app.services.gmail_service import ensure_email_thread_gmail_columns

        ensure_email_thread_gmail_columns()
        clauses.append('e."gmailAccountId" = %s')
        params.append(account_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "EmailThread" e'
                f' WHERE {" AND ".join(clauses)}'
                ' ORDER BY e."updatedAt" DESC',
                params,
            )
            return rows_to_dicts(cur)


# ---------------------------------------------------------------------------
# Multi-account Gmail inboxes (GAP-D2)
#
# These routes are registered BEFORE ``/{thread_id}`` so ``/accounts`` and
# ``/oauth/status`` are never captured by the thread-id path parameter.
# ---------------------------------------------------------------------------


@router.get("/oauth/status")
def oauth_status(current_user: CurrentUser) -> dict[str, Any]:
    """Whether Google OAuth is configured on the server and how many Gmail
    inboxes the user has connected. Replaces the previous 404 with an honest
    200 the UI can read on load."""
    accounts = GmailAccountRepository().list_public(current_user["id"])
    return {
        "configured": oauth_configured(),
        "connected": len(accounts) > 0,
        "accountCount": len(accounts),
    }


@router.get("/accounts")
def list_accounts(current_user: CurrentUser) -> list[dict[str, Any]]:
    """List the user's connected Gmail inboxes (masked, NO tokens)."""
    return GmailAccountRepository().list_public(current_user["id"])


@router.post("/accounts/connect")
def connect_account(current_user: CurrentUser) -> dict[str, str]:
    """Return a Google consent URL for adding ANOTHER Gmail inbox. The account
    chooser is always shown (``prompt=select_account``), so this never silently
    reuses the already-connected account."""
    if not oauth_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth is not configured on the server",
        )
    try:
        return {"authUrl": build_consent_url(current_user["id"])}
    except OAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.delete("/accounts/{account_id}")
def disconnect_account(account_id: str, current_user: CurrentUser) -> dict[str, str]:
    """Revoke + remove ONE Gmail inbox. Only this account's rows are deleted —
    the user's other inboxes are untouched. Revocation is best-effort."""
    removed = GmailAccountRepository().delete_account(current_user["id"], account_id)
    if removed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    # Best-effort revoke at Google (never surfaces or logs the token).
    revoke_token(removed.get("refreshToken") or removed.get("accessToken") or "")
    return {"status": "disconnected", "accountId": account_id}


@router.patch("/accounts/{account_id}/set-primary")
def set_primary_account(account_id: str, current_user: CurrentUser) -> dict[str, str]:
    """Make one inbox the user's primary (exactly one primary per user)."""
    if not GmailAccountRepository().set_primary(current_user["id"], account_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return {"status": "primary", "accountId": account_id}


@router.get("/accounts/{account_id}/sync-status")
def account_sync_status(account_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Sync summary for one inbox: thread count + last-updated timestamp."""
    uid = current_user["id"]
    repo = GmailAccountRepository()
    row = repo.get(uid, account_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    from app.services.gmail_service import ensure_email_thread_gmail_columns

    ensure_email_thread_gmail_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "EmailThread"'
                ' WHERE "userId" = %s AND "gmailAccountId" = %s',
                (uid, account_id),
            )
            count_row = cur.fetchone()
    thread_count = int(count_row[0]) if count_row else 0
    return {
        "accountId": account_id,
        "accountEmail": _mask_email(row.get("accountEmail")),
        "isPrimary": bool(row.get("isPrimary")),
        "connected": True,
        "threadCount": thread_count,
        "lastSyncedAt": row.get("lastSyncedAt") or row.get("updatedAt"),
    }


@router.get("/{thread_id}")
def get_thread(thread_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Get a single email thread by id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "EmailThread" e'
                ' WHERE e."id" = %s AND e."userId" = %s',
                (thread_id, current_user["id"]),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email thread not found")
    return rows[0]


@router.post("/draft", status_code=status.HTTP_201_CREATED)
def create_draft(body: DraftEmail, current_user: CurrentUser) -> dict[str, Any]:
    """Create a new email draft thread.

    The initial message is stored inside the ``messages`` JSON column as the
    first entry in a list.
    """
    uid = current_user["id"]
    thread_id = new_id()

    messages = [{"role": "draft", "body": body.body, "createdAt": None}]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "EmailThread" (
                    "id", "userId", "applicationId", "contactId",
                    "subject", "messages", "classification",
                    "createdAt", "updatedAt"
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, now(), now())
                """,
                (
                    thread_id,
                    uid,
                    body.application_id,
                    body.contact_id,
                    body.subject,
                    json.dumps(messages),
                    body.classification,
                ),
            )
        conn.commit()

    return get_thread(thread_id, current_user)


@router.post("/{thread_id}/reply")
def reply_to_thread(
    thread_id: str, body: ReplyEmail, current_user: CurrentUser
) -> dict[str, Any]:
    """Append a reply to an existing email thread.

    The reply is appended to the ``messages`` JSON array.
    """
    uid = current_user["id"]

    thread = get_thread(thread_id, current_user)
    messages = list(thread.get("messages") or [])
    messages.append({"role": "reply", "body": body.body, "createdAt": None})

    classification_clause = ""
    params: list[Any] = [json.dumps(messages)]

    if body.classification is not None:
        classification_clause = ', "classification" = %s'
        params.append(body.classification)

    params.extend([thread_id, uid])

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'UPDATE "EmailThread" SET "messages" = %s::jsonb,'
                f' "updatedAt" = now(){classification_clause}'
                ' WHERE "id" = %s AND "userId" = %s',
                params,
            )
        conn.commit()

    return get_thread(thread_id, current_user)
