"""Networking CRM honesty, freshness, and agent hand-off.

The Recruiter CRM used to fabricate a 0% response rate, invent outreach
subjects, skip re-import updates, and never feed Sales / Orchestrator. This
module is the single place those numbers and upserts are computed.

Honesty law: unmeasured values are ``None`` (UI: "not measured"), never a
fake 0. Gold is never a status colour.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any
from zoneinfo import ZoneInfo

from app.db import get_connection, new_id, rows_to_dicts

MELBOURNE = ZoneInfo("Australia/Melbourne")

_CONTACT_STAGES = (
    "identified",
    "contacted",
    "responded",
    "meeting",
    "referral",
)
_STAGE_LABELS = {
    "identified": "New",
    "contacted": "Warm",
    "responded": "Active",
    "meeting": "Scheduled",
    "referral": "Placed",
}
_STAGE_WARMTH = {
    "identified": 1,
    "contacted": 2,
    "responded": 3,
    "meeting": 4,
    "referral": 5,
}
_TERMINAL_OUTREACH = frozenset({"sent", "accepted", "declined", "bounced"})
_RESPONDED_OUTREACH = frozenset({"accepted", "declined"})
_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
_NURTURE_CONSENT = frozenset({"existing_relationship", "inbound_signal"})
_NURTURE_STATUSES = frozenset({"new", "contacted"})


def _as_aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None


def _prefer(incoming: str | None, existing: str | None) -> tuple[str | None, bool]:
    """Keep the existing value unless the incoming one is a real change."""
    incoming_clean = (incoming or "").strip() or None
    existing_clean = (existing or "").strip() or None
    if incoming_clean is None:
        return existing_clean, False
    if incoming_clean != existing_clean:
        return incoming_clean, True
    return existing_clean, False


def _outreach_subject(row: dict[str, Any]) -> str:
    message = (row.get("message") or "").strip()
    if message:
        return message.splitlines()[0].strip()[:120]
    kind = (row.get("type") or "message").replace("_", " ").strip().title()
    company = (row.get("company") or "").strip()
    return f"{kind} — {company}" if company else kind


def _response_rate(rows: list[dict[str, Any]]) -> int | None:
    attempts = [t for t in rows if (t.get("status") or "") in _TERMINAL_OUTREACH]
    if not attempts:
        return None
    responded = [t for t in attempts if t["status"] in _RESPONDED_OUTREACH]
    return round(100 * len(responded) / len(attempts))


def _follow_ups_due_today(rows: list[dict[str, Any]]) -> int:
    today = datetime.now(MELBOURNE).date()
    due = 0
    for row in rows:
        if (row.get("status") or "") != "pending":
            continue
        scheduled = _as_aware(row.get("scheduledAt"))
        if scheduled is None:
            continue
        if scheduled.astimezone(MELBOURNE).date() == today:
            due += 1
    return due


def upsert_contact(
    user_id: str,
    *,
    name: str,
    email: str | None = None,
    title: str | None = None,
    company: str | None = None,
    linkedin_url: str | None = None,
    stage: str = "identified",
) -> tuple[str, str]:
    """Insert or refresh a Contact. Returns ``(id, created|updated|duplicate)``.

    Matching: shared email (case-insensitive) when present, otherwise
    lower(name) among email-less rows. Stage is set on create only — a
    re-import must not shove a Warm contact back to New.
    """
    name_clean = (name or "").strip()
    email_norm = (email or "").strip().lower() or None
    if email_norm and not _EMAIL_RE.fullmatch(email_norm):
        email_norm = None
    if not name_clean and email_norm:
        name_clean = email_norm.split("@", 1)[0]
    if not name_clean:
        raise ValueError("upsert_contact requires a name or email")
    stage_key = stage if stage in _CONTACT_STAGES else "identified"

    with get_connection() as conn:
        with conn.cursor() as cur:
            if email_norm:
                cur.execute(
                    'SELECT "id","name","title","company","linkedinUrl" '
                    'FROM "Contact" WHERE "userId" = %s AND LOWER("email") = %s '
                    "LIMIT 1",
                    (user_id, email_norm),
                )
            else:
                cur.execute(
                    'SELECT "id","name","title","company","linkedinUrl" '
                    'FROM "Contact" WHERE "userId" = %s AND LOWER("name") = %s '
                    'AND "email" IS NULL LIMIT 1',
                    (user_id, name_clean.lower()),
                )
            row = cur.fetchone()
            if row is None:
                contact_id = new_id()
                cur.execute(
                    '''INSERT INTO "Contact" (
                        "id", "userId", "name", "title", "company", "stage",
                        "email", "linkedinUrl", "createdAt", "updatedAt"
                    ) VALUES (%s, %s, %s, %s, %s, %s::"ContactStage",
                              %s, %s, now(), now())''',
                    (
                        contact_id,
                        user_id,
                        name_clean,
                        (title or "").strip() or None,
                        (company or "").strip() or None,
                        stage_key,
                        email_norm,
                        (linkedin_url or "").strip() or None,
                    ),
                )
                conn.commit()
                return contact_id, "created"

            contact_id, old_name, old_title, old_company, old_url = row
            new_name, name_changed = _prefer(name_clean, old_name)
            new_title, title_changed = _prefer(title, old_title)
            new_company, company_changed = _prefer(company, old_company)
            new_url, url_changed = _prefer(linkedin_url, old_url)
            if not (name_changed or title_changed or company_changed or url_changed):
                conn.commit()
                return str(contact_id), "duplicate"
            cur.execute(
                '''UPDATE "Contact" SET
                    "name" = %s, "title" = %s, "company" = %s,
                    "linkedinUrl" = %s, "updatedAt" = now()
                   WHERE "id" = %s AND "userId" = %s''',
                (new_name, new_title, new_company, new_url, contact_id, user_id),
            )
        conn.commit()
    return str(contact_id), "updated"


def build_crm_summary(user_id: str) -> dict[str, Any]:
    """Wire-shape for GET /workspaces/networking/summary — honest stats."""
    try:
        from app.routers.networking import _ensure_outreach_tables

        _ensure_outreach_tables()
    except Exception:
        pass

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, title, company, stage, email, "linkedinUrl",
                       "createdAt", "updatedAt"
                FROM "Contact"
                WHERE "userId" = %s
                ORDER BY "createdAt" DESC
                """,
                (user_id,),
            )
            contacts = rows_to_dicts(cur)

    by_stage: dict[str, list[dict[str, Any]]] = {s: [] for s in _CONTACT_STAGES}
    last_updated: datetime | None = None
    for contact in contacts:
        stage_key = (contact.get("stage") or "identified").lower()
        if stage_key not in by_stage:
            stage_key = "identified"
        by_stage[stage_key].append(
            {
                "id": contact["id"],
                "name": contact["name"] or "",
                "role": contact.get("title") or "",
                "company": contact.get("company") or "",
                "email": contact.get("email") or "",
                "linkedinUrl": contact.get("linkedinUrl") or "",
                "warmth": _STAGE_WARMTH.get(stage_key, 1),
            }
        )
        stamp = _as_aware(contact.get("updatedAt")) or _as_aware(contact.get("createdAt"))
        if stamp is not None and (last_updated is None or stamp > last_updated):
            last_updated = stamp

    pipeline = [
        {
            "stage": _STAGE_LABELS[stage],
            "count": len(by_stage[stage]),
            "contacts": by_stage[stage][:5],
        }
        for stage in _CONTACT_STAGES
    ]
    active_count = len(by_stage["responded"]) + len(by_stage["meeting"])

    ot_rows: list[dict[str, Any]] = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT ot."id", ot."type", ot."status", ot."message",'
                    ' ot."scheduledAt", ot."sentAt", c."company", c."name"'
                    ' FROM "OutreachTask" ot'
                    ' LEFT JOIN "Contact" c ON c."id" = ot."contactId"'
                    ' WHERE ot."userId" = %s ORDER BY ot."createdAt" DESC LIMIT 50',
                    (user_id,),
                )
                ot_rows = rows_to_dicts(cur)
    except Exception:
        ot_rows = []

    queue: list[dict[str, Any]] = []
    log: list[dict[str, Any]] = []
    for task in ot_rows:
        entry = {
            "id": task["id"],
            "kind": task["type"],
            "status": task["status"],
            "contactName": task.get("name") or "",
            "company": task.get("company") or "",
            "subject": _outreach_subject(task),
            "scheduledAt": str(task["scheduledAt"]) if task.get("scheduledAt") else None,
            "sentAt": str(task["sentAt"]) if task.get("sentAt") else None,
        }
        if task["status"] == "sent":
            log.append(entry)
        else:
            queue.append(entry)

    return {
        "stats": {
            "contacts": len(contacts),
            "activeConversations": active_count,
            "referralsInFlight": len(by_stage["referral"]),
            "responseRate": _response_rate(ot_rows),
        },
        "pipeline": pipeline,
        "outreachQueue": queue,
        "communicationLog": log,
        "crmSummary": {
            "activeConversations": active_count,
            "followUpsDueToday": _follow_ups_due_today(ot_rows),
            "warmIntrosPending": len(by_stage["contacted"]),
            "lastContactUpdatedAt": last_updated.isoformat() if last_updated else None,
        },
    }


def build_analytics_snapshot(user_id: str) -> dict[str, Any]:
    """Orchestrator-facing CRM snapshot. Counts and employer names, no emails."""
    summary = build_crm_summary(user_id)
    companies: list[str] = []
    seen: set[str] = set()
    for column in summary["pipeline"]:
        for contact in column["contacts"]:
            company = (contact.get("company") or "").strip()
            key = company.lower()
            if company and key not in seen:
                seen.add(key)
                companies.append(company)
    return {
        "contacts": summary["stats"]["contacts"],
        "activeConversations": summary["stats"]["activeConversations"],
        "referralsInFlight": summary["stats"]["referralsInFlight"],
        "responseRate": summary["stats"]["responseRate"],
        "followUpsDueToday": summary["crmSummary"]["followUpsDueToday"],
        "lastContactUpdatedAt": summary["crmSummary"]["lastContactUpdatedAt"],
        "pipeline": {col["stage"]: col["count"] for col in summary["pipeline"]},
        "companies": companies[:12],
    }


def network_snapshot_for_prompt(user_id: str | None) -> str:
    """Grounding block for Sales marketing prompts — counts, never PII."""
    if not user_id:
        return (
            "NETWORK SNAPSHOT: contacts: 0; last contact update: not measured. "
            "No contact emails or names are included."
        )
    try:
        snap = build_analytics_snapshot(user_id)
    except Exception:
        return (
            "NETWORK SNAPSHOT: contacts: 0; last contact update: not measured. "
            "No contact emails or names are included."
        )
    pipeline = snap.get("pipeline") or {}
    pipeline_bits = ", ".join(
        f"{label} {pipeline.get(label, 0)}" for label in _STAGE_LABELS.values()
    )
    last = snap.get("lastContactUpdatedAt") or "not measured"
    employers = ", ".join(snap.get("companies") or []) or "none recorded"
    rate = snap.get("responseRate")
    rate_text = "not measured" if rate is None else f"{rate} percent of terminal outreach"
    return (
        "NETWORK SNAPSHOT (no personal data):\n"
        f"- contacts: {snap.get('contacts', 0)}\n"
        f"- pipeline: {pipeline_bits}\n"
        f"- follow-ups due today: {snap.get('followUpsDueToday', 0)}\n"
        f"- last contact update: {last}\n"
        f"- response rate: {rate_text}\n"
        f"- employer names: {employers}\n"
    )


def _sender_from_messages(messages: Any) -> tuple[str, str] | None:
    """Best (name, email) from an EmailThread.messages jsonb payload."""
    payload: Any = messages
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        payload = payload.get("messages") or payload.get("items") or [payload]
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        email = (item.get("fromEmail") or "").strip().lower()
        name = ""
        raw_from = item.get("from") or item.get("fromName") or ""
        parsed_name, parsed_email = parseaddr(str(raw_from))
        if not email and parsed_email:
            email = parsed_email.strip().lower()
        name = (parsed_name or item.get("fromName") or "").strip()
        if email and _EMAIL_RE.fullmatch(email):
            return (name or email.split("@", 1)[0], email)
    return None


def refresh_contacts_from_inbox(user_id: str, *, limit: int = 500) -> dict[str, int]:
    """Promote already-synced career EmailThread senders into Contact rows.

    Does not call Gmail. Personal classification is skipped. Sets
    ``EmailThread.contactId`` when a contact is created or matched.
    """
    from app.services.gmail_service import (
        ensure_email_thread_gmail_columns,
        ensure_email_thread_last_message_column,
    )

    ensure_email_thread_gmail_columns()
    ensure_email_thread_last_message_column()
    counts = {
        "contactsCreated": 0,
        "contactsUpdated": 0,
        "threadsLinked": 0,
        "ignored": 0,
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''SELECT "id", "subject", "messages", "classification", "contactId"
                   FROM "EmailThread"
                   WHERE "userId" = %s
                     AND COALESCE("classification", '') <> 'personal'
                   ORDER BY COALESCE("lastMessageAt", "updatedAt") DESC NULLS LAST
                   LIMIT %s''',
                (user_id, max(1, min(int(limit), 2000))),
            )
            threads = rows_to_dicts(cur)

    for thread in threads:
        sender = _sender_from_messages(thread.get("messages"))
        if sender is None:
            counts["ignored"] += 1
            continue
        name, email = sender
        contact_id, action = upsert_contact(user_id, name=name, email=email)
        if action == "created":
            counts["contactsCreated"] += 1
        elif action == "updated":
            counts["contactsUpdated"] += 1
        if thread.get("contactId") != contact_id:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'UPDATE "EmailThread" SET "contactId" = %s, "updatedAt" = now() '
                        'WHERE "id" = %s AND "userId" = %s',
                        (contact_id, thread["id"], user_id),
                    )
                conn.commit()
            counts["threadsLinked"] += 1
    return counts


def list_nurture_candidates(user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Sales leads with ratified relationship consent that this user already
    stores as Contact rows. Cap is small on purpose (one run, five addresses).
    """
    from app.repositories.sales import SalesRepository

    SalesRepository()  # ensure sales tables exist
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT sl."id" AS "leadId", sl."email", sl."name",
                       sl."consentType", sl."status", sl."source",
                       c."id" AS "contactId", c."company"
                FROM "SalesLead" sl
                INNER JOIN "Contact" c
                  ON LOWER(c."email") = LOWER(sl."email")
                 AND c."userId" = %s
                WHERE sl."consentType" = ANY(%s)
                  AND sl."status" = ANY(%s)
                ORDER BY sl."createdAt" DESC
                LIMIT %s
                ''',
                (
                    user_id,
                    list(_NURTURE_CONSENT),
                    list(_NURTURE_STATUSES),
                    max(1, min(int(limit), 20)),
                ),
            )
            return rows_to_dicts(cur)
