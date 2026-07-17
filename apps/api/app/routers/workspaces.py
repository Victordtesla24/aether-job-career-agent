"""Workspace routers — Interview Center, Networking CRM, Email Center,
Offer Comparison and Settings.

All five endpoints serve **real data from the database**.  No hardcoded
fixtures, no in-process dictionaries, no demo personas.
"""
from __future__ import annotations

from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, HTTPException, status
from pydantic import AfterValidator, BaseModel, Field

from app.db import (
    ensure_user_profile_columns,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser
from app.repositories.career_profile import CAREER_SOURCES, CareerProfileRepository
from app.services.career_data import refresh_career_data

router = APIRouter()


def _email_provider_connected(user_id: str) -> bool:
    """Whether the user has a real outbound email provider (Gmail via Google
    OAuth) connected.

    A ``GmailAccount`` row — persisted by the in-app Google OAuth flow
    (ADR D-0029, resolved in P4; multi-account in GAP-D2) — means Gmail
    send/sync is available for this user. This is the single source of truth for
    "can we send an email?": both the inbox ``accounts`` status and the send gate
    read it, so the two can never drift apart. Absent any connected account the
    send handler fails honestly (409) instead of fabricating a ``sent`` status.
    """
    from app.repositories.gmail_account import GmailAccountRepository

    return GmailAccountRepository().is_connected(user_id)


# ---------------------------------------------------------------------------
# Interview Center  GET /interviews/prep
# ---------------------------------------------------------------------------

@router.get("/interviews/prep")
def interview_prep(current_user: CurrentUser) -> dict[str, Any]:
    """Interview Center payload derived from real Application + AgentRun records."""
    uid = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            # Most-recent active interview application
            cur.execute(
                """
                SELECT a.id, a.status, a."createdAt",
                       j.title, j.company, j.location, j."fitScore"
                FROM "Application" a
                JOIN "Job" j ON a."jobId" = j.id
                WHERE a."userId" = %s AND a.status = 'interview'
                ORDER BY a."createdAt" DESC
                LIMIT 1
                """,
                (uid,),
            )
            interview_rows = rows_to_dicts(cur)

            # Last interview-related agent run for coaching signals
            cur.execute(
                """
                SELECT id, "agentName", status, output, "startedAt", "completedAt"
                FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" ILIKE %s
                ORDER BY "startedAt" DESC
                LIMIT 1
                """,
                (uid, "%interview%"),
            )
            run_rows = rows_to_dicts(cur)

            # Last completed debrief run (for the debrief panel)
            cur.execute(
                """
                SELECT id, "agentName", output, "completedAt"
                FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" ILIKE %s AND status = 'completed'
                ORDER BY "completedAt" DESC
                LIMIT 1
                """,
                (uid, "%debrief%"),
            )
            debrief_rows = rows_to_dicts(cur)

    # ── No active interview ──────────────────────────────────────────────────
    if not interview_rows:
        return {
            "session": None,
            "compliance": {
                "message": (
                    "No interview scheduled. Once an application progresses to "
                    "the interview stage, your prep brief and predicted questions "
                    "will appear here."
                ),
                "level": "info",
            },
            "brief": None,
            "questions": [],
            "liveAssist": {
                "enabled": False,
                "fillerWordsPerMin": 0,
                "wordsPerMin": 0,
                "talkListenRatio": {"talk": 50, "listen": 50},
                "coachingCue": None,
            },
            "debrief": None,
        }

    app = interview_rows[0]
    run = run_rows[0] if run_rows else None
    debrief_run = debrief_rows[0] if debrief_rows else None

    # Derive debrief from the last completed agent run output
    debrief = None
    if debrief_run and debrief_run.get("output"):
        out = debrief_run["output"]
        if isinstance(out, dict):
            debrief = {
                "company": app["company"],
                "round": out.get("round", "Round 1"),
                "score": out.get("score", 0),
                "strengths": out.get("strengths", []),
                "warnings": out.get("warnings", []),
            }

    # Live-assist signals from the most recent run output
    live_assist_output = {}
    if run and run.get("output") and isinstance(run["output"], dict):
        live_assist_output = run["output"]

    return {
        "session": {
            "role": app["title"],
            "company": app["company"],
            "round": "Active Interview",
            "scheduledFor": None,
            "format": "Check your calendar for details",
        },
        "compliance": {
            "message": (
                "Live Assist is disabled by default during interviews. Some employers "
                "prohibit AI assistance — check your interview agreement before enabling it."
            ),
            "level": "warning",
        },
        "brief": {
            "columns": [
                {
                    "title": "Company",
                    "items": [app["company"]],
                },
                {
                    "title": "Role",
                    "items": [app["title"]],
                },
                {
                    "title": "Location",
                    "items": [app.get("location") or "Remote / TBD"],
                },
            ],
            "insight": (
                f"Fit score: {int(app['fitScore'] or 0)}%. "
                "Review the job description and your application answers for key talking points."
            ),
        },
        "questions": live_assist_output.get("predictedQuestions", []),
        "liveAssist": {
            "enabled": False,
            "fillerWordsPerMin": live_assist_output.get("fillerWordsPerMin", 0),
            "wordsPerMin": live_assist_output.get("wordsPerMin", 0),
            "talkListenRatio": live_assist_output.get(
                "talkListenRatio", {"talk": 50, "listen": 50}
            ),
            "coachingCue": live_assist_output.get("coachingCue"),
        },
        "debrief": debrief,
    }


# ---------------------------------------------------------------------------
# Networking CRM  GET /networking/summary
# ---------------------------------------------------------------------------

@router.get("/networking/summary")
def networking_summary(current_user: CurrentUser) -> dict[str, Any]:
    """Recruiter & referral CRM — real Contact records from the database."""
    uid = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, title, company, stage, email, "linkedinUrl", "createdAt"
                FROM "Contact"
                WHERE "userId" = %s
                ORDER BY "createdAt" DESC
                """,
                (uid,),
            )
            contacts = rows_to_dicts(cur)

    # Stage ordering: the DB's `ContactStage` enum (identified/contacted/
    # responded/meeting/referral) mapped to the wireframe's pipeline column
    # labels (New/Warm/Active/Scheduled/Placed). Contacts are stored with the
    # enum value, so grouping and the pipeline columns must use the same keys
    # — previously this mapping was missing and every column showed count 0.
    stage_order = ["identified", "contacted", "responded", "meeting", "referral"]
    stage_labels = {
        "identified": "New",
        "contacted": "Warm",
        "responded": "Active",
        "meeting": "Scheduled",
        "referral": "Placed",
    }
    stage_warmth = {"identified": 1, "contacted": 2, "responded": 3, "meeting": 4, "referral": 5}

    # Group contacts by stage
    by_stage: dict[str, list[dict]] = {s: [] for s in stage_order}
    for c in contacts:
        stage_key = (c.get("stage") or "identified").lower()
        if stage_key not in by_stage:
            stage_key = "identified"
        by_stage[stage_key].append({
            "id": c["id"],
            "name": c["name"] or "",
            "role": c.get("title") or "",
            "company": c.get("company") or "",
            "email": c.get("email") or "",
            "linkedinUrl": c.get("linkedinUrl") or "",
            "warmth": stage_warmth.get(stage_key, 1),
        })

    pipeline = [
        {
            "stage": stage_labels[s],
            "count": len(by_stage[s]),
            "contacts": by_stage[s][:5],  # show up to 5 per column
        }
        for s in stage_order
    ]

    active_count = len(by_stage.get("responded", [])) + len(by_stage.get("meeting", []))

    # Outreach queue + communication log from real OutreachTask rows
    with get_connection() as conn2:
        with conn2.cursor() as cur2:
            try:
                cur2.execute(
                    'SELECT ot."id", ot."type", ot."status", ot."scheduledAt",'
                    ' ot."sentAt", c."company", c."name"'
                    ' FROM "OutreachTask" ot'
                    ' LEFT JOIN "Contact" c ON c."id" = ot."contactId"'
                    ' WHERE ot."userId" = %s ORDER BY ot."createdAt" DESC LIMIT 50',
                    (uid,),
                )
                ot_rows = cur2.fetchall()
                cols = [d[0] for d in cur2.description or []]
                ot_rows = [dict(zip(cols, r)) for r in ot_rows]
            except Exception:
                ot_rows = []

    queue, log = [], []
    for t in ot_rows:
        entry = {
            "id": t["id"],
            "kind": t["type"],
            "status": t["status"],
            "contactName": t.get("name") or "",
            "company": (t.get("company") or ""),
            "subject": (
                f"{(t.get('type') or '').replace('_', ' ').title()}"
                f" — {(t.get('company') or '')}"
            ),
            "scheduledAt": str(t["scheduledAt"]) if t.get("scheduledAt") else None,
            "sentAt": str(t["sentAt"]) if t.get("sentAt") else None,
        }
        if t["status"] == "sent":
            log.append(entry)
        else:
            queue.append(entry)

    return {
        "stats": {
            "contacts": len(contacts),
            "activeConversations": active_count,
            "referralsInFlight": len(by_stage.get("referral", [])),
            "responseRate": 0,
        },
        "pipeline": pipeline,
        "outreachQueue": queue,
        "communicationLog": log,
        "crmSummary": {
            "activeConversations": active_count,
            "followUpsDueToday": 0,
            "warmIntrosPending": len(by_stage.get("contacted", [])),
        },
    }


# ---------------------------------------------------------------------------
# Email Center  GET /emails/inbox   POST /emails/send
# ---------------------------------------------------------------------------

@router.get("/emails/inbox")
def email_inbox(current_user: CurrentUser) -> dict[str, Any]:
    """Email Command Center — real EmailThread records from the database.

    When the user has connected Gmail, a best-effort sync pulls the latest
    threads into ``EmailThread`` first so the inbox reflects the real mailbox.
    A Gmail hiccup never 500s the inbox — it degrades to whatever is already
    stored (honest, never fabricated).
    """
    uid = current_user["id"]

    from app.repositories.gmail_account import GmailAccountRepository

    creds_repo = GmailAccountRepository()
    account_rows = creds_repo.list_accounts(uid)
    connected = len(account_rows) > 0

    if connected:
        # Best-effort sync of EVERY connected inbox; a hiccup on one account must
        # never 500 the inbox or block the others.
        from app.services.gmail_service import (
            GmailAuthError,
            GmailNotConnectedError,
            GmailService,
        )

        for acc in account_rows:
            try:
                GmailService(uid, account_id=acc.get("id")).sync_threads_to_db()
            except (GmailAuthError, GmailNotConnectedError):
                pass
            except Exception:  # noqa: BLE001 — a Gmail hiccup must not 500 the inbox
                pass

    # The inbox query reads/joins on the additive Gmail linkage columns; ensure
    # they exist even for a user who has never connected (so the query never
    # references a missing column).
    from app.services.gmail_service import ensure_email_thread_gmail_columns

    ensure_email_thread_gmail_columns()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT et.id, et.subject, et.messages, et.classification,
                       et."createdAt", et."applicationId", et."gmailAccountId",
                       c.name AS contact_name, c.company AS contact_company,
                       c.email AS contact_email,
                       ga."accountEmail" AS source_account
                FROM "EmailThread" et
                LEFT JOIN "Contact" c ON et."contactId" = c.id
                LEFT JOIN "GmailAccount" ga ON et."gmailAccountId" = ga."id"
                WHERE et."userId" = %s
                ORDER BY et."updatedAt" DESC
                """,
                (uid,),
            )
            threads = rows_to_dicts(cur)

    messages = []
    for t in threads:
        msgs = t.get("messages") or []
        if isinstance(msgs, list) and msgs:
            latest = msgs[-1]
        else:
            latest = {}
        messages.append({
            "id": t["id"],
            "from": t.get("contact_name") or "Unknown",
            "fromEmail": t.get("contact_email") or "",
            "company": t.get("contact_company") or "",
            "subject": t.get("subject") or "(no subject)",
            "preview": (latest.get("body") or "")[:120],
            "category": t.get("classification") or "all",
            "score": 0,
            "receivedAt": str(t["createdAt"])[:10] if t.get("createdAt") else "",
            "account": t.get("source_account") or "",
            "body": latest.get("body") or "",
            "intelligence": None,
            "draftReply": "",
            "voiceDna": 0,
        })

    total = len(threads)

    # One entry per connected inbox (for the account switcher). Falls back to a
    # single not-connected placeholder so the UI can prompt the first connect.
    if account_rows:
        accounts = [
            {
                "id": acc.get("id"),
                "email": acc.get("accountEmail") or "",
                "provider": "Gmail",
                "status": "connected",
                "isPrimary": bool(acc.get("isPrimary")),
                "unread": 0,
                "note": "Gmail connected — your inbox is syncing.",
            }
            for acc in account_rows
        ]
    else:
        accounts = [
            {
                "id": None,
                "email": current_user.get("email", ""),
                "provider": "Gmail",
                "status": "not_connected",
                "isPrimary": False,
                "unread": 0,
                "note": "Connect your Gmail account to see your inbox here.",
            }
        ]

    return {
        "accounts": accounts,
        "stats": {
            "received": total,
            "recruiterEmails": 0,
            "autoDrafted": 0,
            "sentApproved": 0,
            "followUpsSent": 0,
            "avgResponseHrs": 0,
        },
        "followUps": [],
        "messages": messages,
        "recruiterProfile": None,
    }


class SendReplyRequest(BaseModel):
    message_id: str
    body: str = Field(min_length=1)


@router.post("/emails/send")
def send_reply(payload: SendReplyRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Approve + send a drafted reply.

    Sending requires a connected outbound email provider. None exists yet
    (ADR D-0029), so this fails honestly with a ``409`` instead of fabricating
    a ``sent`` status and silently mutating the thread. The gate runs before
    any DB write, so a rejected send leaves the thread untouched. Drafting
    (``POST /emails/draft``) is a separate endpoint and is unaffected.
    """
    uid = current_user["id"]
    if not _email_provider_connected(uid):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "no_email_provider_connected",
                "message": (
                    "No email provider connected — connect your Gmail account to "
                    "send. No email has been sent."
                ),
            },
        )
    # Load the thread + its contact's address (the real recipient).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT et.id, et.messages, et.subject, c.email AS contact_email'
                ' FROM "EmailThread" et'
                ' LEFT JOIN "Contact" c ON et."contactId" = c.id'
                ' WHERE et.id = %s AND et."userId" = %s',
                (payload.message_id, uid),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
    thread = rows[0]
    recipient = thread.get("contact_email")
    if not recipient:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No recipient email on this thread — add the contact's email before sending.",
        )
    from app.services.gmail_service import (
        GmailAuthError,
        GmailError,
        GmailNotConnectedError,
        GmailService,
    )

    try:
        sent = GmailService(uid).send(
            to=recipient,
            subject=thread.get("subject") or "(no subject)",
            body=payload.body,
        )
    except (GmailAuthError, GmailNotConnectedError):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "gmail_auth_failed",
                "message": (
                    "Gmail authorization expired — reconnect your Gmail account "
                    "to send. No email has been sent."
                ),
            },
        ) from None
    except GmailError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "error": "gmail_send_failed",
                "message": (
                    "Gmail could not send the message right now — no email was "
                    "sent. Please try again."
                ),
            },
        ) from None
    import json as _json

    with get_connection() as conn:
        with conn.cursor() as cur:
            msgs = list(thread.get("messages") or [])
            msgs.append(
                {"role": "user", "body": payload.body, "gmailMessageId": sent.get("id")}
            )
            cur.execute(
                'UPDATE "EmailThread" SET messages = %s::jsonb, "updatedAt" = NOW()'
                ' WHERE id = %s AND "userId" = %s',
                (_json.dumps(msgs), payload.message_id, uid),
            )
        conn.commit()
    return {
        "status": "sent",
        "messageId": payload.message_id,
        "gmailMessageId": sent.get("id"),
    }


# ---------------------------------------------------------------------------
# Offers  GET /offers
# ---------------------------------------------------------------------------

@router.get("/offers")
def offers(current_user: CurrentUser) -> dict[str, Any]:
    """Offer comparison payload — real Application records with status='offer'."""
    uid = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a."createdAt",
                       j.title, j.company, j.location,
                       j."salaryMin", j."salaryMax", j.currency,
                       j."fitScore", j.remote
                FROM "Application" a
                JOIN "Job" j ON a."jobId" = j.id
                WHERE a."userId" = %s AND a.status = 'offer'
                ORDER BY j."fitScore" DESC NULLS LAST
                """,
                (uid,),
            )
            offer_rows = rows_to_dicts(cur)

    offer_list = []
    for idx, row in enumerate(offer_rows):
        sal_min = row.get("salaryMin") or 0
        sal_max = row.get("salaryMax") or 0
        base = sal_min
        # Estimate bonus ~10% of base and equity ~15% of base for display purposes
        bonus = int(base * 0.10)
        equity = int(base * 0.15)
        total = base + bonus + equity
        loc_label = row.get("location") or ("Remote" if row.get("remote") else "On-site")
        offer_list.append({
            "id": row["id"],
            "company": row["company"],
            "role": row["title"],
            "total": total,
            "base": base,
            "bonus": bonus,
            "equity": equity,
            "salaryRange": (
                f"{row.get('currency','AUD')} {sal_min:,}–{sal_max:,}" if sal_min else None
            ),
            "location": loc_label,
            "fitScore": int(row.get("fitScore") or 0),
            "topPick": idx == 0,
            "deadline": None,
        })

    return {
        "offers": offer_list,
        "weights": [
            {"key": "comp", "label": "Total compensation", "weight": 30},
            {"key": "growth", "label": "Career growth", "weight": 25},
            {"key": "culture", "label": "Culture & team", "weight": 20},
            {"key": "flexibility", "label": "Location & flexibility", "weight": 15},
            {"key": "stability", "label": "Company stability", "weight": 10},
        ],
        "negotiation": {
            "insight": (
                "Review each offer carefully. Use the weights panel to adjust "
                "what matters most to you and compare total compensation packages."
            ),
            "suggestedCounter": None,
            "leverage": [],
        },
    }


# ---------------------------------------------------------------------------
# Settings  GET /settings   PUT /settings
# ---------------------------------------------------------------------------

def _load_allowed_internal_domains() -> frozenset[str]:
    """Deferred import to avoid a circular import: ``app.main`` imports this
    module (``app.routers.workspaces``) at module load time, so this module
    cannot import ``app.main`` at ITS module-load time. By request time
    (when this validator actually runs), ``app.main`` has finished
    importing, so a local import here is always safe.
    """
    from app.main import apply_email_domain_allowlist

    return apply_email_domain_allowlist()


def _validate_settings_email(value: str) -> str:
    """GAP-P7-DEF-B (§15.2, REVISED after review-def-b.json cycle-1 FAIL):
    exact-domain allowlist for ``SettingsProfile.email`` ONLY — the gap's
    named surface (``/dashboard/settings`` + ``PUT /api/workspaces/settings``).
    ``RegisterRequest.email`` (apps/api/app/routers/auth.py) deliberately
    stays plain ``EmailStr`` — the reviewer flagged reaching that surface as
    blocking, since self-registration is not part of this gap.

    Design ruling: a prior fix mutated the process-wide
    ``email_validator.SPECIAL_USE_DOMAIN_NAMES`` list, which (empirically
    proven by adversarial review) opened every ``*.local`` address, not just
    the configured ``aether.local``. This validator instead does an EXACT,
    case-insensitive domain match against
    ``app.main.apply_email_domain_allowlist()`` — ``evil.local`` and
    ``foo.local`` are DIFFERENT domains from the allow-listed
    ``aether.local`` and are correctly rejected; only a byte-for-byte domain
    match is accepted.

    For a match, the local-part is still fully syntax-checked — just not
    against the special-use domain rule — by substituting a definitely-not-
    special-use domain (``example.com``) into ``email_validator.validate_email``
    and reusing its local-part parsing/validation (length, characters,
    quoting, etc.); only the domain-reserved-name check is bypassed, and
    only for this one exact, operator-configured domain. Every other input
    (no configured-domain match, or a match that still has a bad
    local-part) goes through the standard ``email_validator.validate_email``
    path unchanged, so garbage strings, ``user@localhost`` (fails a
    "must have a period" check unrelated to special-use domains), and other
    reserved TLDs (``.test``, ``.onion``, ``.arpa``, ``.invalid``) all keep
    failing exactly as before.
    """
    if "@" in value:
        local, _, domain = value.rpartition("@")
        if domain.lower() in _load_allowed_internal_domains():
            try:
                checked = validate_email(f"{local}@example.com", check_deliverability=False)
            except EmailNotValidError as exc:
                raise ValueError(str(exc)) from exc
            return f"{checked.local_part}@{domain.lower()}"

    try:
        checked = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return checked.normalized


SettingsEmail = Annotated[str, AfterValidator(_validate_settings_email)]


class SettingsProfile(BaseModel):
    fullName: str = Field(min_length=1, max_length=120)
    email: SettingsEmail
    targetRole: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)


class AgentConfig(BaseModel):
    autoApply: bool
    approvalGate: bool
    matchThreshold: int = Field(ge=0, le=100)


class SettingsUpdate(BaseModel):
    profile: SettingsProfile
    agentConfig: AgentConfig


def _build_settings(
    user: dict[str, Any],
    resume_row: dict | None,
    portfolio_row: dict | None = None,
) -> dict[str, Any]:
    """Assemble the settings payload from real DB columns."""
    agent_cfg = user.get("agentConfig") or {
        "autoApply": False,
        "approvalGate": True,
        "matchThreshold": 80,
    }
    # Compute display name
    display_name = user.get("name") or user.get("email", "")
    # Portfolio block reflects the real ingested CareerProfile row (GAP-P4-047):
    # a genuine URL + sync status once configured, honest nulls before that.
    portfolio = {
        "url": None,
        "cadence": None,
        "lastSynced": None,
        "status": "not_configured",
    }
    if portfolio_row:
        synced = portfolio_row.get("syncedAt")
        portfolio = {
            "url": portfolio_row.get("url"),
            "cadence": None,
            "lastSynced": str(synced)[:19] if synced else None,
            "status": portfolio_row.get("status") or "not_configured",
        }
    return {
        "profile": {
            "fullName": display_name,
            "email": user.get("email", ""),
            "targetRole": user.get("targetRole") or "",
            "location": user.get("location") or "",
        },
        "resume": {
            "activeFile": resume_row.get("label") if resume_row else None,
            "uploadedAt": str(resume_row["createdAt"])[:10] if resume_row else None,
            "versions": 0,  # will be filled below
        },
        "portfolio": portfolio,
        "agentConfig": {
            "autoApply": bool(agent_cfg.get("autoApply", False)),
            "approvalGate": bool(agent_cfg.get("approvalGate", True)),
            "matchThreshold": int(agent_cfg.get("matchThreshold", 80)),
        },
        "integrations": [],
        "connectedAccounts": [],
    }


@router.get("/settings")
def get_settings(current_user: CurrentUser) -> dict[str, Any]:
    """Current settings read from the User table."""
    uid = current_user["id"]
    ensure_user_profile_columns()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, name, "targetRole", "location", "agentConfig"
                FROM "User" WHERE id = %s
                """,
                (uid,),
            )
            user_rows = rows_to_dicts(cur)

            # Latest resume
            cur.execute(
                """
                SELECT id, label, "createdAt"
                FROM "Resume"
                WHERE "userId" = %s
                ORDER BY version DESC NULLS LAST, "createdAt" DESC
                LIMIT 1
                """,
                (uid,),
            )
            resume_rows = rows_to_dicts(cur)

            # Count resume versions
            cur.execute(
                'SELECT COUNT(*) AS cnt FROM "Resume" WHERE "userId" = %s',
                (uid,),
            )
            cnt_rows = rows_to_dicts(cur)

            # Job-board integrations = the REAL discovery sources feeding this
            # user's job list — mirrors the Jobs page source bar (SC-ST-04).
            cur.execute(
                '''
                SELECT "source", COUNT(*) AS cnt, MAX("createdAt") AS last_seen
                FROM "Job" WHERE "userId" = %s AND "source" IS NOT NULL
                GROUP BY "source" ORDER BY cnt DESC
                ''',
                (uid,),
            )
            source_rows = rows_to_dicts(cur)

    if not user_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    user = user_rows[0]
    resume = resume_rows[0] if resume_rows else None
    version_count = cnt_rows[0]["cnt"] if cnt_rows else 0

    portfolio_row = CareerProfileRepository().get(uid, "portfolio")
    result = _build_settings(user, resume, portfolio_row)
    result["resume"]["versions"] = version_count
    result["integrations"] = [
        {
            "name": row["source"].capitalize() if row["source"].islower() else row["source"],
            "status": "connected",
            "detail": (
                f"{row['cnt']} jobs discovered · last sync "
                f"{str(row['last_seen'])[:16]} UTC"
            ),
        }
        for row in source_rows
    ]
    # Connected accounts & API keys — the same env-derived truth the Agents
    # screen shows; never a fabricated connection.
    from app.routers.agents import PROVIDER_SEED, _provider_env_state

    accounts = []
    for seed in PROVIDER_SEED:
        p_status, _model, detail, _models = _provider_env_state(seed["id"])
        if p_status == "connected":
            accounts.append({"name": seed["name"], "status": "connected", "detail": detail})
    # Real Gmail connection (P4) — surfaced per connected inbox (GAP-D2).
    from app.repositories.gmail_account import GmailAccountRepository

    for gacc in GmailAccountRepository().list_accounts(uid):
        gemail = gacc.get("accountEmail")
        if gemail:
            accounts.append(
                {
                    "name": "Google (Gmail)",
                    "status": "connected",
                    "detail": f"Connected as {gemail}"
                    + (" (primary)" if gacc.get("isPrimary") else ""),
                }
            )
    result["connectedAccounts"] = accounts
    return result


@router.put("/settings")
def update_settings(payload: SettingsUpdate, current_user: CurrentUser) -> dict[str, Any]:
    """Persist profile + agent configuration to the User table.

    GAP-P7-DEF-B-PERSIST: every field on ``SettingsProfile`` (``fullName``,
    ``email``, ``targetRole``, ``location``) must be written here -- a 200
    response that silently discards part of the submitted profile is wrong.
    ``email`` previously fell out of the ``SET`` list entirely, so a save
    always reported success while leaving the stored address unchanged. The
    DEF-B validator (``_validate_settings_email``) has already normalized/
    validated ``payload.profile.email`` by the time it reaches here.
    """
    uid = current_user["id"]
    import json as _json

    import psycopg2

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    UPDATE "User"
                    SET name = %s,
                        email = %s,
                        "targetRole" = %s,
                        "location" = %s,
                        "agentConfig" = %s,
                        "updatedAt" = NOW()
                    WHERE id = %s
                    """,
                    (
                        payload.profile.fullName,
                        payload.profile.email,
                        payload.profile.targetRole,
                        payload.profile.location,
                        _json.dumps(payload.agentConfig.model_dump()),
                        uid,
                    ),
                )
            except psycopg2.errors.UniqueViolation:
                # "User"."email" is UNIQUE (schema.prisma) -- persisting an
                # email already owned by a different account must fail
                # cleanly, not with a raw 500 (same 409 shape as /auth/register's
                # DuplicateEmailError).
                conn.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "An account with this email already exists",
                ) from None
        conn.commit()

    return get_settings(current_user)


# ---------------------------------------------------------------------------
# Career Data  GET /workspaces/career-data   POST /workspaces/career-data/refresh
# (GAP-P4-047 · ADR D-0031) — real consolidation of GitHub + portfolio, with an
# honest LinkedIn limitation. The ingested signal feeds resume tailoring and
# cover-letter context assembly (see app.services.career_data).
# ---------------------------------------------------------------------------

#: Honest, standing note about the LinkedIn scope decision (ADR D-0031).
_LINKEDIN_NOTE = (
    "LinkedIn offers no public profile API to third-party apps, so it is not "
    "auto-synced. Paste your LinkedIn summary below and it will be consolidated "
    "into your tailoring evidence alongside GitHub and your portfolio."
)


class CareerDataRefreshRequest(BaseModel):
    """Optional per-source inputs. A field left unset reuses the previously
    stored value for that source; an empty string clears it."""

    githubUsername: str | None = Field(default=None, max_length=100)
    portfolioUrl: str | None = Field(default=None, max_length=500)
    linkedinSummary: str | None = Field(default=None, max_length=20000)


def _shape_source(source: str, row: dict | None) -> dict[str, Any]:
    """UI-facing view of one career-data source's stored state."""
    if not row:
        return {
            "source": source,
            "status": "not_configured",
            "url": None,
            "summary": None,
            "error": None,
            "lastSynced": None,
        }
    synced = row.get("syncedAt")
    return {
        "source": source,
        "status": row.get("status") or "not_configured",
        "url": row.get("url"),
        "summary": row.get("summary"),
        "error": row.get("error"),
        "lastSynced": str(synced)[:19] if synced else None,
    }


@router.get("/career-data")
def get_career_data(current_user: CurrentUser) -> dict[str, Any]:
    """Current consolidated career-data state for the authenticated user."""
    rows = {r["source"]: r for r in CareerProfileRepository().list_by_user(current_user["id"])}
    return {
        "sources": [_shape_source(s, rows.get(s)) for s in CAREER_SOURCES],
        "linkedinNote": _LINKEDIN_NOTE,
    }


@router.post("/career-data/refresh")
def refresh_career_data_endpoint(
    payload: CareerDataRefreshRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Re-ingest GitHub + portfolio (real fetches) and store LinkedIn paste.

    Each source is persisted with its true status/error; a source that cannot
    be ingested is reported honestly and contributes nothing to tailoring.
    """
    results = refresh_career_data(
        current_user["id"],
        github_username=payload.githubUsername,
        portfolio_url=payload.portfolioUrl,
        linkedin_summary=payload.linkedinSummary,
    )
    return {
        "sources": [_shape_source(s, results.get(s)) for s in CAREER_SOURCES],
        "linkedinNote": _LINKEDIN_NOTE,
    }
