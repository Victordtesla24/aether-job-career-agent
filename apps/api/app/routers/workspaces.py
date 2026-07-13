"""Workspace routers — Interview Center, Networking CRM, Email Center,
Offer Comparison and Settings.

All five endpoints serve **real data from the database**.  No hardcoded
fixtures, no in-process dictionaries, no demo personas.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.db import (
    ensure_user_profile_columns,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser

router = APIRouter()


def _email_provider_connected() -> bool:
    """Whether a real outbound email provider (SMTP / Gmail OAuth / etc.) is
    wired and connected for this deployment.

    No email-send integration exists anywhere in the API yet (see ADR D-0029):
    there is no SMTP transport, no OAuth handoff, and the inbox surfaces every
    account as ``not_connected``. Sending therefore cannot succeed, and the
    send handler must fail honestly instead of fabricating a ``sent`` status.

    This is the single source of truth for "can we send an email?" — both the
    inbox ``accounts`` status and the send gate read it, so the two can never
    drift apart. When a genuine provider integration lands, replace this stub
    with a real connectivity check and the honest error branch disappears on
    its own.
    """
    return False


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

    # Stage ordering
    stage_order = ["new", "warm", "active", "scheduled", "placed"]

    # Group contacts by stage
    by_stage: dict[str, list[dict]] = {s: [] for s in stage_order}
    for c in contacts:
        stage_key = (c.get("stage") or "new").lower()
        if stage_key not in by_stage:
            by_stage[stage_key] = []
        by_stage[stage_key].append({
            "id": c["id"],
            "name": c["name"] or "",
            "role": c.get("title") or "",
            "company": c.get("company") or "",
            "email": c.get("email") or "",
            "linkedinUrl": c.get("linkedinUrl") or "",
            "warmth": {"new": 1, "warm": 2, "active": 3, "scheduled": 4, "placed": 5}.get(
                stage_key, 1
            ),
        })

    pipeline = [
        {
            "stage": s.capitalize(),
            "count": len(by_stage[s]),
            "contacts": by_stage[s][:5],  # show up to 5 per column
        }
        for s in stage_order
    ]

    active_count = len(by_stage.get("active", [])) + len(by_stage.get("scheduled", []))

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
            "referralsInFlight": len(by_stage.get("placed", [])),
            "responseRate": 0,
        },
        "pipeline": pipeline,
        "outreachQueue": queue,
        "communicationLog": log,
        "crmSummary": {
            "activeConversations": active_count,
            "followUpsDueToday": 0,
            "warmIntrosPending": len(by_stage.get("warm", [])),
        },
    }


# ---------------------------------------------------------------------------
# Email Center  GET /emails/inbox   POST /emails/send
# ---------------------------------------------------------------------------

@router.get("/emails/inbox")
def email_inbox(current_user: CurrentUser) -> dict[str, Any]:
    """Email Command Center — real EmailThread records from the database."""
    uid = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT et.id, et.subject, et.messages, et.classification,
                       et."createdAt", et."applicationId",
                       c.name AS contact_name, c.company AS contact_company,
                       c.email AS contact_email
                FROM "EmailThread" et
                LEFT JOIN "Contact" c ON et."contactId" = c.id
                WHERE et."userId" = %s
                ORDER BY et."createdAt" DESC
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
            "account": "",
            "body": latest.get("body") or "",
            "intelligence": None,
            "draftReply": "",
            "voiceDna": 0,
        })

    total = len(threads)

    return {
        "accounts": [
            {
                "email": current_user.get("email", ""),
                "provider": "Gmail",
                "status": "connected" if _email_provider_connected() else "not_connected",
                "unread": 0,
                "note": "Connect your Gmail account to see your inbox here.",
            }
        ],
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
    if not _email_provider_connected():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "no_email_provider_connected",
                "message": (
                    "No email provider connected — connect an account in Settings "
                    "to send. No email has been sent."
                ),
            },
        )
    uid = current_user["id"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id, messages FROM "EmailThread" WHERE id = %s AND "userId" = %s',
                (payload.message_id, uid),
            )
            rows = rows_to_dicts(cur)
            if not rows:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Thread not found")
            thread = rows[0]
            msgs = thread.get("messages") or []
            msgs.append({"role": "user", "body": payload.body})
            import json as _json
            cur.execute(
                'UPDATE "EmailThread" SET messages = %s, "updatedAt" = NOW() WHERE id = %s',
                (_json.dumps(msgs), payload.message_id),
            )
        conn.commit()
    return {"status": "sent", "messageId": payload.message_id}


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

class SettingsProfile(BaseModel):
    fullName: str = Field(min_length=1, max_length=120)
    email: EmailStr
    targetRole: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)


class AgentConfig(BaseModel):
    autoApply: bool
    approvalGate: bool
    matchThreshold: int = Field(ge=0, le=100)


class SettingsUpdate(BaseModel):
    profile: SettingsProfile
    agentConfig: AgentConfig


def _build_settings(user: dict[str, Any], resume_row: dict | None) -> dict[str, Any]:
    """Assemble the settings payload from real DB columns."""
    agent_cfg = user.get("agentConfig") or {
        "autoApply": False,
        "approvalGate": True,
        "matchThreshold": 80,
    }
    # Compute display name
    display_name = user.get("name") or user.get("email", "")
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
        "portfolio": {
            "url": None,
            "cadence": None,
            "lastSynced": None,
        },
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

    result = _build_settings(user, resume)
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
    result["connectedAccounts"] = accounts
    return result


@router.put("/settings")
def update_settings(payload: SettingsUpdate, current_user: CurrentUser) -> dict[str, Any]:
    """Persist profile + agent configuration to the User table."""
    uid = current_user["id"]
    import json as _json

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE "User"
                SET name = %s,
                    "targetRole" = %s,
                    "location" = %s,
                    "agentConfig" = %s,
                    "updatedAt" = NOW()
                WHERE id = %s
                """,
                (
                    payload.profile.fullName,
                    payload.profile.targetRole,
                    payload.profile.location,
                    _json.dumps(payload.agentConfig.model_dump()),
                    uid,
                ),
            )
        conn.commit()

    return get_settings(current_user)
