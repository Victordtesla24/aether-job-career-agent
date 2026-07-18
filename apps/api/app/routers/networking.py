"""Networking router — contacts and outreach tasks (P3).

Manages professional contacts and outreach tasks. The ``Contact`` table is
defined in the Prisma schema; the ``OutreachTask`` table is created
idempotently on first use.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()

#: Valid ContactStage values per the Prisma enum.
_CONTACT_STAGES = frozenset(
    {"identified", "contacted", "responded", "meeting", "referral"}
)

#: Valid OutreachTask.status values.
_OUTREACH_STATUSES = frozenset({"pending", "sent", "accepted", "declined", "bounced"})

#: Valid OutreachTask.type values.
_OUTREACH_TYPES = frozenset({"connection_request", "message", "follow_up", "introduction"})

#: Contact columns for SELECT queries.
_CONTACT_COLUMNS = (
    'c."id", c."userId", c."name", c."title", c."company",'
    ' c."stage", c."email", c."linkedinUrl", c."createdAt", c."updatedAt"'
)

# ---------------------------------------------------------------------------
# Table bootstrap
# ---------------------------------------------------------------------------

_outreach_tables_ready = False


def _ensure_outreach_tables() -> None:
    """Idempotently create the ``OutreachTask`` table on first use.

    The ``Contact`` table is managed by Prisma migrations and expected to
    already exist. The ``OutreachTask`` table is additive, created here
    following the same advisory-lock pattern as ``ensure_user_profile_columns``.
    """
    global _outreach_tables_ready
    if _outreach_tables_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'OutreachTask'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _outreach_tables_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240714,))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "OutreachTask" (
                    "id"            text PRIMARY KEY,
                    "userId"        text NOT NULL,
                    "contactId"     text REFERENCES "Contact"("id") ON DELETE CASCADE,
                    "type"          text NOT NULL DEFAULT 'message',
                    "status"        text NOT NULL DEFAULT 'pending',
                    "message"       text,
                    "scheduledAt"   timestamptz,
                    "sentAt"        timestamptz,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_outreach_userId"'
                ' ON "OutreachTask" ("userId")'
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_outreach_contactId"'
                ' ON "OutreachTask" ("contactId")'
            )
        conn.commit()
    _outreach_tables_ready = True


_OUTREACH_COLUMNS = (
    'o."id", o."userId", o."contactId", o."type", o."status",'
    ' o."message", o."scheduledAt", o."sentAt", o."createdAt", o."updatedAt"'
)


# ---------------------------------------------------------------------------
# Root summary
# ---------------------------------------------------------------------------


@router.get("")
def networking_summary(current_user: CurrentUser) -> dict[str, Any]:
    """Return counts of contacts and outreach tasks for the current user."""
    uid = current_user["id"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "Contact" WHERE "userId" = %s', (uid,)
            )
            contacts = cur.fetchone()[0]
    try:
        _ensure_outreach_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COUNT(*) FROM "OutreachTask" WHERE "userId" = %s', (uid,)
                )
                outreach = cur.fetchone()[0]
    except Exception:
        outreach = 0
    return {"contacts": contacts, "outreach": outreach}


# ---------------------------------------------------------------------------
# Pydantic schemas — Contacts
# ---------------------------------------------------------------------------


class ContactCreate(BaseModel):
    """Payload for creating a new contact."""

    name: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    linkedin_url: str | None = Field(default=None, max_length=2000)
    stage: str = Field(default="identified")


class ContactUpdate(BaseModel):
    """Payload for updating an existing contact."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    linkedin_url: str | None = Field(default=None, max_length=2000)
    stage: str | None = None


# ---------------------------------------------------------------------------
# Pydantic schemas — Outreach Tasks
# ---------------------------------------------------------------------------


class OutreachTaskCreate(BaseModel):
    """Payload for creating a new outreach task."""

    contact_id: str
    type: str = Field(default="message")
    message: str | None = Field(default=None, max_length=10_000)
    scheduled_at: datetime | None = None


class OutreachTaskUpdate(BaseModel):
    """Payload for updating an existing outreach task."""

    type: str | None = None
    status: str | None = None
    message: str | None = Field(default=None, max_length=10_000)
    scheduled_at: datetime | None = None


# ---------------------------------------------------------------------------
# Contact endpoints
# ---------------------------------------------------------------------------


@router.get("/contacts")
def list_contacts(
    current_user: CurrentUser,
    stage: str | None = None,
    company: str | None = None,
) -> list[dict[str, Any]]:
    """List contacts for the current user.

    Filters: ``?stage=identified|contacted|…``, ``?company=Acme``.
    """
    uid = current_user["id"]
    clauses = ['c."userId" = %s']
    params: list[Any] = [uid]

    if stage is not None:
        if stage not in _CONTACT_STAGES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid stage '{stage}'. Valid: {sorted(_CONTACT_STAGES)}",
            )
        clauses.append('c."stage" = %s')
        params.append(stage)
    if company is not None:
        clauses.append('c."company" ILIKE %s')
        params.append(f"%{company}%")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_CONTACT_COLUMNS} FROM "Contact" c'
                f' WHERE {" AND ".join(clauses)}'
                ' ORDER BY c."updatedAt" DESC',
                params,
            )
            return rows_to_dicts(cur)


@router.get("/contacts/{contact_id}")
def get_contact(
    contact_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Get a single contact by id."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_CONTACT_COLUMNS} FROM "Contact" c'
                ' WHERE c."id" = %s AND c."userId" = %s',
                (contact_id, current_user["id"]),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return rows[0]


@router.post("/contacts", status_code=status.HTTP_201_CREATED)
def create_contact(
    body: ContactCreate, current_user: CurrentUser
) -> dict[str, Any]:
    """Create a new contact."""
    uid = current_user["id"]

    if body.stage not in _CONTACT_STAGES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid stage '{body.stage}'. Valid: {sorted(_CONTACT_STAGES)}",
        )

    contact_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "Contact" (
                    "id", "userId", "name", "title", "company",
                    "stage", "email", "linkedinUrl",
                    "createdAt", "updatedAt"
                ) VALUES (%s, %s, %s, %s, %s, %s::"ContactStage", %s, %s, now(), now())
                """,
                (
                    contact_id,
                    uid,
                    body.name,
                    body.title,
                    body.company,
                    body.stage,
                    body.email,
                    body.linkedin_url,
                ),
            )
        conn.commit()

    return get_contact(contact_id, current_user)


@router.patch("/contacts/{contact_id}")
def update_contact(
    contact_id: str, body: ContactUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Update contact fields. Only supplied fields are changed."""
    uid = current_user["id"]
    get_contact(contact_id, current_user)  # 404 check

    if body.stage is not None and body.stage not in _CONTACT_STAGES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid stage '{body.stage}'. Valid: {sorted(_CONTACT_STAGES)}",
        )

    sets: list[str] = []
    params: list[Any] = []

    if body.name is not None:
        sets.append('"name" = %s')
        params.append(body.name)
    if body.title is not None:
        sets.append('"title" = %s')
        params.append(body.title)
    if body.company is not None:
        sets.append('"company" = %s')
        params.append(body.company)
    if body.email is not None:
        sets.append('"email" = %s')
        params.append(body.email)
    if body.linkedin_url is not None:
        sets.append('"linkedinUrl" = %s')
        params.append(body.linkedin_url)
    if body.stage is not None:
        sets.append('"stage" = %s::"ContactStage"')
        params.append(body.stage)

    if sets:
        sets.append('"updatedAt" = now()')
        params.extend([contact_id, uid])
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "Contact" SET {", ".join(sets)}'
                    ' WHERE "id" = %s AND "userId" = %s',
                    params,
                )
            conn.commit()

    return get_contact(contact_id, current_user)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: str, current_user: CurrentUser) -> None:
    """Delete a contact."""
    uid = current_user["id"]
    get_contact(contact_id, current_user)  # 404 check
    _ensure_outreach_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            # App-level cascade (MV-networking-007): remove dependent outreach
            # tasks first so no orphan survives even where the deployed table's
            # declared ON DELETE CASCADE is not active.
            cur.execute(
                'DELETE FROM "OutreachTask" WHERE "contactId" = %s AND "userId" = %s',
                (contact_id, uid),
            )
            cur.execute(
                'DELETE FROM "Contact" WHERE "id" = %s AND "userId" = %s',
                (contact_id, uid),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Outreach Task endpoints
# ---------------------------------------------------------------------------


@router.get("/outreach")
def list_outreach_tasks(
    current_user: CurrentUser,
    contact_id: str | None = None,
    task_status: str | None = None,
) -> list[dict[str, Any]]:
    """List outreach tasks for the current user.

    Filters: ``?contact_id=``, ``?task_status=pending|sent|…``.
    """
    _ensure_outreach_tables()
    uid = current_user["id"]
    clauses = ['o."userId" = %s']
    params: list[Any] = [uid]

    if contact_id is not None:
        clauses.append('o."contactId" = %s')
        params.append(contact_id)
    if task_status is not None:
        if task_status not in _OUTREACH_STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid status '{task_status}'. Valid: {sorted(_OUTREACH_STATUSES)}",
            )
        clauses.append('o."status" = %s')
        params.append(task_status)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_OUTREACH_COLUMNS} FROM "OutreachTask" o'
                f' WHERE {" AND ".join(clauses)}'
                ' ORDER BY o."createdAt" DESC',
                params,
            )
            return rows_to_dicts(cur)


@router.get("/outreach/{task_id}")
def get_outreach_task(
    task_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Get a single outreach task by id."""
    _ensure_outreach_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_OUTREACH_COLUMNS} FROM "OutreachTask" o'
                ' WHERE o."id" = %s AND o."userId" = %s',
                (task_id, current_user["id"]),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Outreach task not found")
    return rows[0]


@router.post("/outreach", status_code=status.HTTP_201_CREATED)
def create_outreach_task(
    body: OutreachTaskCreate, current_user: CurrentUser
) -> dict[str, Any]:
    """Create a new outreach task linked to a contact."""
    _ensure_outreach_tables()
    uid = current_user["id"]

    # Referential integrity (MV-networking-007): the referenced contact must
    # exist AND belong to the caller. Validating here yields an honest 404 and
    # never creates an orphan task nor surfaces a raw DB FK-violation 500.
    get_contact(body.contact_id, current_user)

    if body.type not in _OUTREACH_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid type '{body.type}'. Valid: {sorted(_OUTREACH_TYPES)}",
        )

    task_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO "OutreachTask" (
                    "id", "userId", "contactId", "type", "status",
                    "message", "scheduledAt",
                    "createdAt", "updatedAt"
                ) VALUES (%s, %s, %s, %s, 'pending', %s, %s, now(), now())
                """,
                (
                    task_id,
                    uid,
                    body.contact_id,
                    body.type,
                    body.message,
                    body.scheduled_at,
                ),
            )
        conn.commit()

    return get_outreach_task(task_id, current_user)


@router.patch("/outreach/{task_id}")
def update_outreach_task(
    task_id: str, body: OutreachTaskUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Update outreach task fields. Only supplied fields are changed."""
    _ensure_outreach_tables()
    uid = current_user["id"]
    get_outreach_task(task_id, current_user)  # 404 check

    if body.type is not None and body.type not in _OUTREACH_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid type '{body.type}'. Valid: {sorted(_OUTREACH_TYPES)}",
        )
    if body.status is not None and body.status not in _OUTREACH_STATUSES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid status '{body.status}'. Valid: {sorted(_OUTREACH_STATUSES)}",
        )

    sets: list[str] = []
    params: list[Any] = []

    if body.type is not None:
        sets.append('"type" = %s')
        params.append(body.type)
    if body.status is not None:
        sets.append('"status" = %s')
        params.append(body.status)
    if body.message is not None:
        sets.append('"message" = %s')
        params.append(body.message)
    if body.scheduled_at is not None:
        sets.append('"scheduledAt" = %s')
        params.append(body.scheduled_at)

    if body.status == "sent":
        sets.append('"sentAt" = now()')

    if sets:
        sets.append('"updatedAt" = now()')
        params.extend([task_id, uid])
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'UPDATE "OutreachTask" SET {", ".join(sets)}'
                    ' WHERE "id" = %s AND "userId" = %s',
                    params,
                )
            conn.commit()

    return get_outreach_task(task_id, current_user)


@router.delete("/outreach/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_outreach_task(task_id: str, current_user: CurrentUser) -> None:
    """Delete an outreach task."""
    _ensure_outreach_tables()
    uid = current_user["id"]
    get_outreach_task(task_id, current_user)  # 404 check
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "OutreachTask" WHERE "id" = %s AND "userId" = %s',
                (task_id, uid),
            )
        conn.commit()
