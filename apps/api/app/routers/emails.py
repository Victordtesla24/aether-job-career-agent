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
) -> list[dict[str, Any]]:
    """List email threads for the current user.

    Optionally filter by ``?application_id=`` or ``?contact_id=``.
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

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "EmailThread" e'
                f' WHERE {" AND ".join(clauses)}'
                ' ORDER BY e."updatedAt" DESC',
                params,
            )
            return rows_to_dicts(cur)


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
