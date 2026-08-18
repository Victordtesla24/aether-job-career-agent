"""Networking router — contacts and outreach tasks (P3).

Manages professional contacts and outreach tasks. The ``Contact`` table is
defined in the Prisma schema; the ``OutreachTask`` table is created
idempotently on first use.
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parseaddr
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.db import get_connection, new_id, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.repositories.sales import SalesRepository
from app.services.networking_insights import (
    refresh_contacts_from_inbox,
    upsert_contact,
)

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

_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_PROFESSIONAL_SIGNAL = re.compile(
    r"\b(recruit(?:er|ing)|hiring|role|position|opportunit(?:y|ies)|"
    r"career|interview|talent|staffing|engineering|director|manager|"
    r"professional)\b",
    re.IGNORECASE,
)

#: Exclude the user's own outbound/trash traffic so SENT never becomes a Contact.
_GMAIL_IMPORT_QUERY = "-in:sent -in:drafts -in:trash"


def _self_mailbox_emails(user_id: str) -> set[str]:
    """Addresses that belong to this user (app User + connected Gmail accounts)."""
    emails: set[str] = set()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT LOWER("email") FROM "User" WHERE "id" = %s', (user_id,))
            row = cur.fetchone()
            if row and row[0]:
                emails.add(str(row[0]).strip().lower())
            cur.execute(
                'SELECT LOWER("accountEmail") FROM "GmailAccount" '
                'WHERE "userId" = %s AND "accountEmail" IS NOT NULL',
                (user_id,),
            )
            for (addr,) in cur.fetchall() or []:
                if addr:
                    emails.add(str(addr).strip().lower())
    return {e for e in emails if e and _EMAIL_RE.fullmatch(e)}


def _professional_sender(message: dict[str, Any]) -> tuple[str, str] | None:
    """Return normalized ``(name, email)`` only for an evidenced work signal.

    This uses just the authenticated inbox's sender/header/body data, retains
    no body text, and never guesses an address or consent basis.
    """
    name, email = parseaddr(message.get("from") or "")
    email = email.strip().lower()
    evidence = " ".join(
        str(message.get(key) or "") for key in ("subject", "text", "html")
    )
    if not _EMAIL_RE.fullmatch(email) or not _PROFESSIONAL_SIGNAL.search(evidence):
        return None
    return (name.strip() or email.split("@", 1)[0], email)


@router.post("/gmail/import-contacts")
def import_gmail_contacts(current_user: CurrentUser) -> dict[str, int]:
    """Owner-authorized import of professional inbound Gmail contacts.

    Candidates need a real sender address plus a professional signal. CRM
    imports create Contact rows only — they do **not** inject into the global
    SalesLead funnel (NW-ADV). Suppressed senders are neither saved nor
    counted as contacts. Nothing is sent.
    """
    from app.services.gmail_service import (
        GmailAuthError,
        GmailError,
        GmailNotConnectedError,
        GmailService,
    )

    uid = current_user["id"]
    gmail = GmailService(uid)
    sales = SalesRepository()
    self_emails = _self_mailbox_emails(uid)
    seen: set[str] = set()
    counts = {
        "contactsCreated": 0,
        "contactsUpdated": 0,
        "leadsCreated": 0,
        "duplicates": 0,
        "suppressed": 0,
        "ignored": 0,
    }
    # F5-008: a user without Gmail connected (or with expired authorization)
    # is a normal client condition, not a server fault — map it to 409 exactly
    # like the other Gmail-backed routes (approvals, workspaces) instead of
    # letting GmailNotConnectedError escape as a 500.
    try:
        headers = gmail.list_message_headers(
            query=_GMAIL_IMPORT_QUERY, max_results=100
        )
    except (GmailAuthError, GmailNotConnectedError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "gmail_not_connected",
                "message": (
                    "No Gmail account connected (or authorization expired) — "
                    "connect Gmail to import contacts. Nothing was imported."
                ),
            },
        ) from None
    except GmailError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "gmail_unavailable",
                "message": (
                    "Gmail could not be reached right now — nothing was "
                    "imported. Please try again."
                ),
            },
        ) from None
    for header in headers:
        try:
            message = gmail.get_message_bodies(header["id"])
        except GmailError:
            # One unreadable message must not fail the whole import.
            counts["ignored"] += 1
            continue
        candidate = _professional_sender(message)
        if candidate is None:
            counts["ignored"] += 1
            continue
        name, email = candidate
        if email in self_emails:
            # Own mailbox address must never become a CRM contact.
            counts["ignored"] += 1
            continue
        if email in seen:
            counts["duplicates"] += 1
            continue
        seen.add(email)
        if sales.is_suppressed(email):
            counts["suppressed"] += 1
            continue

        _cid, action = upsert_contact(uid, name=name, email=email)
        if action == "created":
            counts["contactsCreated"] += 1
        elif action == "updated":
            counts["contactsUpdated"] += 1
        else:
            counts["duplicates"] += 1
        # NW-ADV: CRM import does not write global SalesLead rows.
    return counts


def _connections_csv_rows(text: str) -> list[dict[str, str]]:
    """Parse LinkedIn's ``Connections.csv``, tolerating its ``Notes:`` preamble.

    LinkedIn prepends a few free-text "Notes:" lines before the real header
    row (``First Name,Last Name,...``). Skip to the header, then parse with
    the same CSV reader the B7 ingest uses. Pure in-memory — no network.
    """
    import csv as _csv  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.lstrip('\ufeff"').lower().startswith("first name"):
            start = i
            break
    else:
        return []
    reader = _csv.DictReader(_io.StringIO("\n".join(lines[start:])))
    return [
        {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        for row in reader
    ]


@router.post("/linkedin/import-contacts")
async def import_linkedin_contacts(
    current_user: CurrentUser, file: UploadFile = File(...)
) -> dict[str, int]:
    """Owner-provided LinkedIn export → professional contacts (R4.1).

    Accepts LinkedIn's "Download your data" export **.zip** (only
    ``Connections.csv`` is opened — reusing the B7 bounded zip reader) or the
    loose ``Connections.csv``. This is a compliant, upload-only path: **zero
    network calls to LinkedIn — ever**. Rows dedupe into the ``Contact``
    table; rows that carry an email the connection chose to share also become
    Sales leads with ratified ``existing_relationship`` consent provenance.
    Suppressed emails are neither saved nor handed off. Nothing is sent.
    """
    import zipfile  # noqa: PLC0415

    from app.services.career_data import (  # noqa: PLC0415
        MAX_LINKEDIN_EXPORT_BYTES,
        parse_linkedin_export_zip,
    )

    data = await file.read(MAX_LINKEDIN_EXPORT_BYTES + 1)
    if len(data) > MAX_LINKEDIN_EXPORT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"LinkedIn export is larger than the "
            f"{MAX_LINKEDIN_EXPORT_BYTES // (1024 * 1024)}MB upload limit.",
        )
    filename = (file.filename or "").strip()
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix == "zip":
        try:
            csv_texts = parse_linkedin_export_zip(data, filenames=("Connections.csv",))
        except zipfile.BadZipFile:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Uploaded file is not a valid zip archive.",
            ) from None
        text = csv_texts.get("Connections.csv", "")
        if not text:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Zip archive did not contain Connections.csv.",
            )
    elif suffix == "csv":
        if filename.rsplit("/", 1)[-1].lower() != "connections.csv":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unrecognized CSV file '{filename}'. Expected Connections.csv "
                "from LinkedIn's 'Download your data' export.",
            )
        text = data.decode("utf-8", errors="replace")
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unsupported file type — upload the .zip from LinkedIn's "
            "'Download your data' export, or its Connections.csv.",
        )

    uid = current_user["id"]
    sales = SalesRepository()
    counts = {
        "rows": 0,
        "contactsCreated": 0,
        "contactsUpdated": 0,
        "leadsCreated": 0,
        "duplicates": 0,
        "suppressed": 0,
        "ignored": 0,
    }
    seen_emails: set[str] = set()
    seen_names: set[tuple[str, str]] = set()
    for row in _connections_csv_rows(text):
        counts["rows"] += 1
        name = " ".join(
            p for p in (row.get("First Name", ""), row.get("Last Name", "")) if p
        ).strip()
        email = (row.get("Email Address") or "").strip().lower()
        company = (row.get("Company") or "").strip()
        title = (row.get("Position") or "").strip()
        url = (row.get("URL") or "").strip()
        if email and not _EMAIL_RE.fullmatch(email):
            email = ""
        if not name and not email:
            counts["ignored"] += 1
            continue
        # In-upload dedupe: by shared email when present, else by name+company.
        if email:
            if email in seen_emails:
                counts["duplicates"] += 1
                continue
            seen_emails.add(email)
        else:
            key = (name.lower(), company.lower())
            if key in seen_names:
                counts["duplicates"] += 1
                continue
            seen_names.add(key)
        if email and sales.is_suppressed(email):
            counts["suppressed"] += 1
            continue

        _cid, action = upsert_contact(
            uid,
            name=name or (email.split("@", 1)[0] if email else ""),
            email=email or None,
            title=title or None,
            company=company or None,
            linkedin_url=url or None,
        )
        if action == "created":
            counts["contactsCreated"] += 1
        elif action == "updated":
            counts["contactsUpdated"] += 1
        else:
            counts["duplicates"] += 1
        # NW-ADV: LinkedIn CRM import does not write global SalesLead rows.
    return counts


@router.post("/refresh-from-inbox")
def refresh_from_inbox(current_user: CurrentUser) -> dict[str, int]:
    """Refresh Contact rows from already-synced career EmailThread senders.

    Does not call Gmail and does not steal Email Center sync. Personal
    classification is ignored. Nothing is sent.
    """
    return refresh_contacts_from_inbox(current_user["id"])


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
    _ensure_outreach_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COUNT(*) FROM "OutreachTask" WHERE "userId" = %s', (uid,)
            )
            outreach = cur.fetchone()[0]
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
