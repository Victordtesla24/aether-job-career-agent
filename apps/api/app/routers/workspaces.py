"""Workspace routers — Interview Center, Networking CRM, Email Center,
Offer Comparison and Settings.

All five endpoints serve **real data from the database**.  No hardcoded
fixtures, no in-process dictionaries, no demo personas.
"""
from __future__ import annotations

import logging
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from pydantic import AfterValidator, BaseModel, Field

from app.db import (
    ensure_resume_columns,
    ensure_user_profile_columns,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser
from app.repositories.career_profile import CAREER_SOURCES, CareerProfileRepository
from app.services.career_data import (
    LINKEDIN_EXPORT_FILES,
    MAX_LINKEDIN_EXPORT_BYTES,
    ingest_linkedin_export,
    parse_linkedin_export_zip,
    refresh_career_data,
)
from app.services.offers import create_offer, delete_offer, fetch_offers_payload

router = APIRouter()
logger = logging.getLogger(__name__)

# MON-002: an expired/revoked Google credential (or any other Google-API-shaped
# failure — ``GmailError`` and its subclasses ``GmailAuthError``/
# ``GmailNotConnectedError``) used to be retried on EVERY ``GET
# /emails/inbox`` poll past the freshness TTL, since a failed sync never
# stamps ``lastSyncedAt`` (see ``is_email_sync_fresh``). That produced ~50
# Gmail 403s/hour in production. This process-local negative cache, keyed by
# userId, makes a request within the window skip the inline sync attempt
# entirely instead of hammering Gmail with a credential that is known-bad.
# ``value = (deadline_monotonic, account_ids_in_backoff)`` — mirrors the
# existing ``_cache: dict[str, tuple[float, ...]]`` TTL-cache idiom in
# ``app.services.apply_channel_resolver``, INCLUDING its ``threading.Lock()``
# guard (apply_channel_resolver.py:171-197): ``email_inbox`` is a sync ``def``
# route, which Starlette dispatches on its threadpool, so two concurrent
# requests for the same user really can race this check-then-act state.
# Every read/write below holds ``_gmail_sync_backoff_lock`` — narrowly, never
# across the Gmail network call itself, only around the dict access.
_GMAIL_SYNC_BACKOFF_SECONDS = 15 * 60
_gmail_sync_backoff: dict[str, tuple[float, frozenset[Any]]] = {}
_gmail_sync_backoff_lock = threading.Lock()


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
                SELECT a.id, a.status, a."createdAt", a."jobId",
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

            # The prep brief this panel may render (ML-W4B verification of
            # 25ccabe). Two defects sat in this read, unreachable for as long as
            # NOTHING wrote an ``%interview%`` AgentRun row, and became reachable
            # the moment the interviewPrep agent started writing them:
            #
            #  * it took the newest matching row of ANY status, so a later FAILED
            #    run — the honest 503 when the LLM is unavailable, whose row
            #    carries no usable output — silently WIPED a good brief from an
            #    earlier successful run. Hence ``status = 'completed'``, which the
            #    sibling debrief query below already had.
            #  * it took that run's questions regardless of WHICH job they were
            #    predicted for. ``job_id`` is an OPTIONAL parameter of the agent,
            #    so a run for another job is a normal thing to have — and its
            #    questions, predicted from a DIFFERENT posting, were rendered as
            #    the prep for THIS interview. That is a misattribution of
            #    generated content. Hence the ``output->>'jobId'`` match against
            #    the job actually being rendered.
            #
            # A run that makes no job claim at all (no ``jobId`` key — the
            # pre-4B output shape) cannot be misattributed, so it still renders.
            prep_rows: list[dict[str, Any]] = []
            unrelated_prep_rows: list[dict[str, Any]] = []
            if interview_rows:
                cur.execute(
                    """
                    SELECT id, "agentName", status, output, "startedAt",
                           "completedAt"
                    FROM "AgentRun"
                    WHERE "userId" = %s AND "agentName" ILIKE %s
                          AND status = 'completed'
                          AND jsonb_typeof(output) = 'object'
                          AND (output->>'jobId' IS NULL OR output->>'jobId' = %s)
                    ORDER BY "startedAt" DESC
                    LIMIT 1
                    """,
                    (uid, "%interview%", str(interview_rows[0]["jobId"])),
                )
                prep_rows = rows_to_dicts(cur)
                if not prep_rows:
                    # Nothing for THIS job. Is there a brief at all? If so the
                    # panel must say why it is withholding it, rather than look
                    # identical to "you have never run interview prep".
                    cur.execute(
                        """
                        SELECT output
                        FROM "AgentRun"
                        WHERE "userId" = %s AND "agentName" ILIKE %s
                              AND status = 'completed'
                              AND jsonb_typeof(output) = 'object'
                        ORDER BY "startedAt" DESC
                        LIMIT 1
                        """,
                        (uid, "%interview%"),
                    )
                    unrelated_prep_rows = rows_to_dicts(cur)

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
            # Same key on both branches so the payload shape never varies; there
            # is no interview to attribute a brief to, so nothing to explain.
            "questionsNote": None,
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
    debrief_run = debrief_rows[0] if debrief_rows else None

    # The brief selected above, plus — when the only brief on file belongs to
    # another job — an honest note naming that withholding instead of serving
    # someone else's questions or looking like "never run".
    prep_run = prep_rows[0] if prep_rows else None
    questions_note: str | None = None
    if prep_run is None and unrelated_prep_rows:
        unrelated_output = unrelated_prep_rows[0].get("output") or {}
        other_title = (
            unrelated_output.get("jobTitle")
            if isinstance(unrelated_output, dict)
            else None
        )
        questions_note = (
            "Your most recent interview prep was generated for a different job"
            + (f" ({other_title})" if other_title else "")
            + " — those questions were predicted from another posting, so they "
            "are not shown as this interview's prep. Run Interview Prep for this "
            "role to get questions for it."
        )

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

    # The selected brief's own output — the questions this panel renders, plus
    # whatever live-assist signals a run recorded. ``jsonb_typeof(output) =
    # 'object'`` in the query already guarantees a dict; the isinstance check
    # stays as a cheap belt-and-braces against a shape change.
    live_assist_output: dict[str, Any] = (
        prep_run["output"]
        if prep_run is not None and isinstance(prep_run.get("output"), dict)
        else {}
    )

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
        #: Non-null ONLY when a real prep brief exists but belongs to another job
        #: — the withholding is reported instead of looking like "never run".
        "questionsNote": questions_note,
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


def _email_activity_stats(uid: str) -> dict[str, int]:
    """Real per-user Email Center activity for "This Week's Stats" (last 7 days).

    Every subquery is scoped to ``uid`` — one user's agent runs/approvals never
    leak into another user's stats panel (MV-email-center-005 / reviewer B2).

    ``sentApproved`` counts approved ``email_send`` requests: the human approval
    is the strongest REAL signal that exists (the post-approval Gmail send result
    is not persisted anywhere), so it is an honest proxy for "sent", never a
    fabricated delivery count. Degrades to zeros on any DB hiccup rather than
    500-ing the inbox (consistent with the Gmail-sync best-effort block)."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      GREATEST(
                        (SELECT count(*) FROM "AgentRun"
                           WHERE "userId" = %(uid)s AND "agentName" = 'emailAgent'
                             AND "status" = 'completed'
                             AND "input"->>'mode' IN ('draft_reply','draft_follow_up')
                             AND "createdAt" >= now() - interval '7 days'),
                        (SELECT count(*) FROM "EmailThread"
                           WHERE "userId" = %(uid)s
                             AND COALESCE(classification, '') <> 'personal'
                             AND COALESCE("draftReply", '') <> ''
                             AND "draftReplyAt" >= now() - interval '7 days')
                      ) AS auto_drafted,
                      (SELECT count(*) FROM "AgentRun"
                         WHERE "userId" = %(uid)s AND "agentName" = 'emailAgent'
                           AND "status" = 'completed'
                           AND "input"->>'mode' = 'draft_follow_up'
                           AND "createdAt" >= now() - interval '7 days') AS follow_ups_sent,
                      (SELECT count(*) FROM "ApprovalRequest"
                         WHERE "userId" = %(uid)s AND "type" = 'email_send'
                           AND "status" = 'approved'
                           AND "createdAt" >= now() - interval '7 days') AS sent_approved
                    """,
                    {"uid": uid},
                )
                row = cur.fetchone()
        return {
            "autoDrafted": int((row[0] if row else 0) or 0),
            "followUpsSent": int((row[1] if row else 0) or 0),
            "sentApproved": int((row[2] if row else 0) or 0),
        }
    except Exception:  # noqa: BLE001 — stats are best-effort; never 500 the inbox
        return {"autoDrafted": 0, "followUpsSent": 0, "sentApproved": 0}


def _inbox_intelligence(raw: Any) -> dict[str, Any] | None:
    """Return persisted insights only when they include a real numeric score.

    A missing or non-numeric score stays ``None`` (honest 'not analyzed'),
    never a fabricated 0.
    """
    if not isinstance(raw, dict):
        return None
    score = raw.get("score")
    if not isinstance(score, (int, float)):
        return None
    breakdown = raw.get("breakdown")
    return {
        "score": int(score),
        "breakdown": breakdown if isinstance(breakdown, list) else [],
        "summary": str(raw.get("summary") or ""),
    }


def _unread_by_account(uid: str) -> dict[str, int]:
    """Career-inbox unread counts per Gmail account from stored UNREAD labels.

    Personal threads are excluded. Degrades to {} rather than 500-ing the inbox.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT "gmailAccountId", count(*)
                    FROM "EmailThread"
                    WHERE "userId" = %s
                      AND COALESCE(classification, '') <> 'personal'
                      AND labels IS NOT NULL
                      AND 'UNREAD' = ANY(labels)
                    GROUP BY "gmailAccountId"
                    """,
                    (uid,),
                )
                return {
                    str(row[0]): int(row[1] or 0)
                    for row in cur.fetchall()
                    if row[0]
                }
    except Exception:  # noqa: BLE001 — unread is best-effort
        return {}


def _thread_recency(thread: dict[str, Any], latest: dict[str, Any]) -> datetime:
    """Newest-message time for latest-first sort. Never uses triage stamps."""
    stamp = thread.get("lastMessageAt")
    if isinstance(stamp, datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    raw = latest.get("createdAt") or thread.get("createdAt")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if raw:
        text = str(raw)
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _received_at_iso(thread: dict[str, Any], latest: dict[str, Any]) -> str:
    recency = _thread_recency(thread, latest)
    if recency.year <= 1:
        return ""
    return recency.astimezone(timezone.utc).isoformat()


def _ingest_inbound_interviews(uid: str, threads: list[dict[str, Any]]) -> None:
    """Best-effort: calendar events + Gmail interview invites → analytics."""
    from app.services.interview_ingest import ingest_inbound_for_user

    ingest_inbound_for_user(uid, threads)


@router.get("/emails/inbox")
def email_inbox(
    current_user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    thread_id: str | None = Query(default=None),
    full: bool = Query(default=False),
    force: bool = Query(default=False),
) -> dict[str, Any]:
    """Email Command Center — real EmailThread records from the database.

    When the user has connected Gmail, a best-effort sync pulls the latest
    threads into ``EmailThread`` first so the inbox reflects the real mailbox.
    A Gmail hiccup never 500s the inbox — it degrades to whatever is already
    stored (honest, never fabricated).

    W-13 (QA #2, wave-3.5): this used to return EVERY thread with its FULL
    latest-message body on every load (measured 723KB / ~148 threads, 5.62s
    cold). The default LIST response is now bounded to the ``limit`` most
    recently-updated threads (default 50, max 200) with ``body`` truncated to
    the same snippet already used for ``preview`` — the list view never
    rendered the full body anyway. Full, untruncated content for ONE thread
    (what the detail panel needs) stays reachable via ``?thread_id=<id>``
    (which also ignores ``limit`` — it targets exactly one thread, still
    scoped to the calling user), or via the ``?full=1`` escape hatch for the
    bounded set. No query params -> identical default shape (backward
    compatible).
    """
    uid = current_user["id"]

    from app.repositories.gmail_account import GmailAccountRepository

    creds_repo = GmailAccountRepository()
    account_rows = creds_repo.list_accounts(uid)
    connected = len(account_rows) > 0

    # GM2-EMAIL-001: accounts whose sync JUST failed with a real auth failure
    # (expired/revoked token) must never be reported as "connected" below —
    # capture which account ids failed instead of silently swallowing it.
    auth_failed_account_ids: set[Any] = set()

    if connected:
        # Best-effort sync of EVERY connected inbox; a hiccup on one account must
        # never 500 the inbox or block the others.
        from app.services.gmail_service import (
            GmailError,
            GmailService,
            is_email_sync_fresh,
        )

        # MON-002: a still-active backoff for this user means at least one
        # account's credential was PROVEN dead on a recent request — skip the
        # sync attempt for exactly those accounts instead of re-hammering
        # Gmail every poll. An expired entry is dropped so the next attempt
        # below can retry (and clear it on success, or re-arm it on another
        # failure).
        backoff_account_ids: frozenset[Any] = frozenset()
        with _gmail_sync_backoff_lock:
            backoff_entry = _gmail_sync_backoff.get(uid)
            if backoff_entry is not None:
                deadline, backoff_account_ids = backoff_entry
                if time.monotonic() >= deadline:
                    _gmail_sync_backoff.pop(uid, None)
                    backoff_account_ids = frozenset()

        for acc in account_rows:
            # W-6 TTL gate: one sync is threads().list() + up to 50
            # threads().get() round-trips PER account. Inside the freshness
            # window the stored EmailThread rows are already current, so this
            # request makes ZERO Gmail calls unless `force=true` (Sync Now).
            # A sync that fails never stamps lastSyncedAt, so a broken account
            # is retried on the next request rather than being cached as "fresh".
            if not force and is_email_sync_fresh(acc.get("lastSyncedAt")):
                continue
            acc_id = acc.get("id")
            if acc_id in backoff_account_ids:
                auth_failed_account_ids.add(acc_id)
                continue
            try:
                from app.services.career_email_filter import CAREER_GMAIL_QUERY

                GmailService(uid, account_id=acc_id).sync_threads_to_db(
                    query=CAREER_GMAIL_QUERY, max_results=50
                )
            except GmailError:
                # Covers GmailAuthError/GmailNotConnectedError AND the plain
                # GmailError a real Google 403 ("insufficientPermissions" /
                # invalid_grant) actually arrives as (gmail_service.py
                # list_threads wraps every HttpError into GmailError, not
                # just auth-shaped ones) — this is the exact case that used
                # to fall through to the silent `except Exception: pass`
                # below and get retried on every single poll.
                auth_failed_account_ids.add(acc_id)
                with _gmail_sync_backoff_lock:
                    # The log-once decision MUST be made inside the same
                    # locked section that writes the entry — otherwise two
                    # concurrent requests can both read "not yet backed off"
                    # before either writes, and both log.
                    already_backed_off = uid in _gmail_sync_backoff
                    _gmail_sync_backoff[uid] = (
                        time.monotonic() + _GMAIL_SYNC_BACKOFF_SECONDS,
                        frozenset(auth_failed_account_ids),
                    )
                if not already_backed_off:
                    # One structured warning on ENTERING backoff, not one per
                    # request — subsequent polls within the window hit the
                    # `continue` above and never reach this except block.
                    logger.warning(
                        "gmail_sync_backoff_entered user_id=%s account_id=%s "
                        "backoff_seconds=%s",
                        uid,
                        acc_id,
                        _GMAIL_SYNC_BACKOFF_SECONDS,
                    )
            except Exception:  # noqa: BLE001 — a non-Gmail hiccup must not 500 the inbox
                pass
            else:
                # A successful sync proves the credential is good again —
                # clear any backoff this user was previously in.
                with _gmail_sync_backoff_lock:
                    _gmail_sync_backoff.pop(uid, None)

    # The inbox query reads/joins on the additive Gmail linkage columns plus the
    # additive aiScore column; ensure they exist even for a user who has never
    # connected/triaged (so the query never references a missing column).
    from app.services.gmail_service import (
        ensure_email_thread_agent_columns,
        ensure_email_thread_ai_columns,
        ensure_email_thread_gmail_columns,
        ensure_email_thread_last_message_column,
    )

    ensure_email_thread_gmail_columns()
    ensure_email_thread_ai_columns()
    ensure_email_thread_last_message_column()
    ensure_email_thread_agent_columns()

    # A specific thread_id targets exactly one thread (the detail panel's
    # on-demand full-body fetch) and always gets its full body, regardless of
    # `full`. Otherwise this is the bounded LIST query (`limit`-capped, most
    # recently updated first) — `full` toggles whether its bodies stay
    # truncated to the `preview` snippet (default) or come back untruncated.
    include_full_body = full or thread_id is not None

    with get_connection() as conn:
        with conn.cursor() as cur:
            if thread_id is not None:
                cur.execute(
                    """
                    SELECT et.id, et.subject, et.messages, et.classification,
                           et."aiScore",
                           et."createdAt", et."lastMessageAt", et."applicationId",
                           et."gmailAccountId", et."gmailThreadId", et."gmailMessageId",
                           et."draftReply", et."aiInsights", et.labels,
                           c.name AS contact_name, c.company AS contact_company,
                           c.email AS contact_email,
                           ga."accountEmail" AS source_account
                    FROM "EmailThread" et
                    LEFT JOIN "Contact" c ON et."contactId" = c.id
                    LEFT JOIN "GmailAccount" ga ON et."gmailAccountId" = ga."id"
                    WHERE et."userId" = %s AND et.id = %s
                    """,
                    (uid, thread_id),
                )
            else:
                cur.execute(
                    """
                    SELECT et.id, et.subject, et.messages, et.classification,
                           et."aiScore",
                           et."createdAt", et."lastMessageAt", et."applicationId",
                           et."gmailAccountId", et."gmailThreadId", et."gmailMessageId",
                           et."draftReply", et."aiInsights", et.labels,
                           c.name AS contact_name, c.company AS contact_company,
                           c.email AS contact_email,
                           ga."accountEmail" AS source_account
                    FROM "EmailThread" et
                    LEFT JOIN "Contact" c ON et."contactId" = c.id
                    LEFT JOIN "GmailAccount" ga ON et."gmailAccountId" = ga."id"
                    WHERE et."userId" = %s
                    AND COALESCE(et.classification, '') <> 'personal'
                    ORDER BY COALESCE(et."lastMessageAt", et."createdAt") DESC
                    LIMIT %s
                    """,
                    (uid, max(limit * 4, 200)),
                )
            threads = rows_to_dicts(cur)

            # Real totals across the WHOLE mailbox (never just the bounded
            # page), so "This Week's Stats" stays honest regardless of `limit`
            # — W-13 must not silently make a large inbox's counters wrong.
            cur.execute(
                """
                SELECT count(*) FILTER (
                         WHERE COALESCE(classification, '') <> 'personal'
                       ) AS total,
                       count(*) FILTER (
                         WHERE classification IN ('priority', 'followup')
                       ) AS recruiter_emails
                FROM "EmailThread"
                WHERE "userId" = %s
                """,
                (uid,),
            )
            totals_row = cur.fetchone()

    if thread_id is None:
        _ingest_inbound_interviews(uid, threads)

    from app.services.career_email_filter import classify_thread

    scored: list[tuple[datetime, dict[str, Any], dict[str, Any], Any]] = []
    hidden_ids: list[str] = []
    for t in threads:
        msgs = t.get("messages") or []
        latest = msgs[-1] if isinstance(msgs, list) and msgs else {}
        if not isinstance(latest, dict):
            latest = {}
        verdict = classify_thread(t, latest)
        if thread_id is None and not verdict.keep:
            if t.get("id"):
                hidden_ids.append(str(t["id"]))
            continue
        scored.append((_thread_recency(t, latest), t, latest, verdict))
    scored.sort(key=lambda row: row[0], reverse=True)
    if thread_id is None:
        scored = scored[:limit]

    if hidden_ids:
        # Persist the hide so stats.received and the next poll's SQL window
        # stop counting personal mail the classifier already rejected.
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "EmailThread" SET classification = %s'
                    ' WHERE "userId" = %s AND id = ANY(%s)'
                    " AND COALESCE(classification, '') <> 'personal'",
                    ("personal", uid, hidden_ids),
                )
                cur.execute(
                    """
                    SELECT count(*) FILTER (
                             WHERE COALESCE(classification, '') <> 'personal'
                           ) AS total,
                           count(*) FILTER (
                             WHERE classification IN ('priority', 'followup')
                           ) AS recruiter_emails
                    FROM "EmailThread"
                    WHERE "userId" = %s
                    """,
                    (uid,),
                )
                totals_row = cur.fetchone()
            conn.commit()

    total = int((totals_row[0] if totals_row else 0) or 0)
    recruiter_emails = int((totals_row[1] if totals_row else 0) or 0)

    messages = []
    for _recency, t, latest, verdict in scored:
        full_body = latest.get("body") or ""
        preview = full_body[:120]
        # Honest, explicit marker (MF-1, wave-3.5 adversarial review) — never a
        # client-side length heuristic. True only when `body` below is
        # genuinely NOT the complete content: false whenever this response
        # already carries the full body (?thread_id=/?full=1), and also false
        # when the real body was <=120 chars to begin with (truncating it
        # would have been a no-op, so there is nothing missing to hide).
        is_truncated = (not include_full_body) and len(full_body) > 120
        # P1-7 residual (QA-RES-001): the CRM Contact join is the preferred
        # sender identity, but threads synced straight from Gmail have no
        # contactId — their REAL sender lives in the latest synced message
        # (gmail_service._normalize_thread stores "from"/"fromEmail"). Fall
        # back to that before ever admitting "Unknown".
        msg_from = latest.get("from") or ""
        msg_from_email = latest.get("fromEmail") or ""
        category = t.get("classification") or "all"
        if verdict.keep and verdict.category:
            if verdict.category == "auto":
                category = "auto"
            elif verdict.is_interview_invite:
                category = "priority"
            elif category in (None, "all", "personal"):
                category = verdict.category
        labels = t.get("labels") or []
        unread = any(str(x).upper() == "UNREAD" for x in (labels or []))
        messages.append({
            "id": t["id"],
            "from": t.get("contact_name") or msg_from or msg_from_email or "Unknown",
            "fromEmail": t.get("contact_email") or msg_from_email,
            "company": t.get("contact_company") or "",
            "subject": t.get("subject") or "(no subject)",
            "preview": preview,
            "category": category,
            # REAL per-thread triage score (MV-email-center-001), or null when the
            # thread has never been triaged — never a fabricated 0. Deep
            # intelligence (breakdown + summary) and draft replies are computed
            # ON DEMAND by the client via POST /agents/email/run, so the inbox
            # load stays one query (never 64 LLM calls).
            "score": t.get("aiScore"),
            "receivedAt": _received_at_iso(t, latest),
            "account": t.get("source_account") or "",
            # Truncated to the same `preview` snippet for the bounded LIST
            # response (W-13 / QA #2: was 723KB / 148 full bodies on every
            # load) — full, untruncated content is returned only for the
            # explicit `?thread_id=<id>` detail fetch or the `?full=1` escape
            # hatch.
            "body": full_body if include_full_body else preview,
            "bodyTruncated": is_truncated,
            "intelligence": _inbox_intelligence(t.get("aiInsights")),
            "draftReply": str(t.get("draftReply") or ""),
            "unread": unread,
        })

    activity = _email_activity_stats(uid)
    unread_map = _unread_by_account(uid)
    follow_ups: list[dict[str, str]] = []
    seen_followups: set[tuple[str, str]] = set()
    for m in messages:
        if m.get("category") != "followup":
            continue
        key = (str(m.get("subject") or ""), str(m.get("fromEmail") or m.get("from") or ""))
        if key in seen_followups:
            continue
        seen_followups.add(key)
        follow_ups.append(
            {
                "company": m["company"] or m["from"],
                "role": m["subject"],
                "dueIn": (
                    "Draft ready for review"
                    if (m.get("draftReply") or "").strip()
                    else "Needs a follow-up draft"
                ),
                "status": "draft" if (m.get("draftReply") or "").strip() else "queued",
            }
        )

    # One entry per connected inbox (for the account switcher). Falls back to a
    # single not-connected placeholder so the UI can prompt the first connect.
    if account_rows:
        accounts = []
        for acc in account_rows:
            # GM2-EMAIL-001: honest status — this SAME request's own sync
            # attempt (above) already proved the stored token is dead. Never
            # report "connected" when a live auth check just failed.
            needs_reauth = acc.get("id") in auth_failed_account_ids
            synced_raw = acc.get("lastSyncedAt")
            if isinstance(synced_raw, datetime):
                synced_iso = (
                    synced_raw.astimezone(timezone.utc).isoformat()
                    if synced_raw.tzinfo
                    else synced_raw.replace(tzinfo=timezone.utc).isoformat()
                )
            elif synced_raw:
                synced_iso = str(synced_raw)
            else:
                synced_iso = None
            accounts.append({
                "id": acc.get("id"),
                "email": acc.get("accountEmail") or "",
                "provider": "Gmail",
                "status": "needs_reauth" if needs_reauth else "connected",
                "isPrimary": bool(acc.get("isPrimary")),
                "unread": unread_map.get(str(acc.get("id") or ""), 0),
                "actionRequired": needs_reauth,
                "lastSyncedAt": synced_iso,
                "note": (
                    "Gmail authorization expired or was revoked — "
                    "reconnect your account to resume syncing."
                    if needs_reauth
                    else "Gmail connected — your inbox is syncing."
                ),
            })
    else:
        accounts = [
            {
                "id": None,
                "email": current_user.get("email", ""),
                "provider": "Gmail",
                "status": "not_connected",
                "isPrimary": False,
                "unread": 0,
                "lastSyncedAt": None,
                "note": "Connect your Gmail account to see your inbox here.",
            }
        ]

    return {
        "accounts": accounts,
        "stats": {
            "received": total,
            "recruiterEmails": recruiter_emails,
            "autoDrafted": activity["autoDrafted"],
            "sentApproved": activity["sentApproved"],
            "followUpsSent": activity["followUpsSent"],
            "avgResponseHrs": None,
        },
        "followUps": follow_ups,
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
# Offers  GET /offers · POST /offers · DELETE /offers/{id}
# ---------------------------------------------------------------------------

#: Currencies accepted for a manually-entered offer. Kept intentionally small
#: and explicit so the stored/displayed currency code is always a real value the
#: user chose (MV-offer-comparison-006 — never a fabricated default badge).
_OFFER_CURRENCIES = frozenset({"AUD", "USD", "NZD", "GBP", "EUR", "SGD", "CAD", "INR"})


class OfferCreate(BaseModel):
    """Payload for persisting a user-entered offer (POST /workspaces/offers)."""

    company: str = Field(min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    base: int = Field(gt=0)
    bonus: int = Field(default=0, ge=0)
    equity: int = Field(default=0, ge=0)
    location: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="AUD", max_length=8)


@router.get("/offers")
def offers(current_user: CurrentUser) -> dict[str, Any]:
    """Offer comparison payload — real Application(status='offer') records plus
    the user's persisted manual offers (see ``app.services.offers``)."""
    return fetch_offers_payload(current_user["id"])


@router.post("/offers", status_code=status.HTTP_201_CREATED)
def add_offer(body: OfferCreate, current_user: CurrentUser) -> dict[str, Any]:
    """Persist a user-entered offer, scoped to the current user (MV-001).

    Replaces the old client-only "Add Offer" mock: the offer is now written to
    the additive ``"Offer"`` table and survives reloads/navigation.
    """
    company = body.company.strip()
    location = body.location.strip()
    if not company:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Company is required.")
    if not location:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Location is required.")
    currency = body.currency.strip().upper() or "AUD"
    if currency not in _OFFER_CURRENCIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unsupported currency '{currency}'. Supported: {sorted(_OFFER_CURRENCIES)}",
        )
    role = (body.role or "").strip() or None
    return create_offer(
        current_user["id"],
        company=company,
        role=role,
        base=body.base,
        bonus=body.bonus,
        equity=body.equity,
        location=location,
        currency=currency,
    )


@router.delete("/offers/{offer_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_offer(offer_id: str, current_user: CurrentUser) -> None:
    """Delete one of the caller's own manual offers (MV-005 mitigation for the
    now-permanent write). Application-derived offers are managed in the
    Application Tracker and are not deletable here — a 404 is returned."""
    if not delete_offer(current_user["id"], offer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")


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
    # ML-settings-006: a NUL byte (0x00) in fullName/targetRole/location used
    # to reach ``update_settings``'s ``cur.execute(...)`` (below, ~line 1092)
    # unguarded, where psycopg2 raises a raw ValueError before the SQL ever
    # reaches Postgres -- an unhandled 500. That is now caught application-
    # wide at the single lowest common seam every DB call in this codebase
    # passes through (``app.db.get_connection``'s cursor_factory), not with a
    # per-field pydantic guard here (§13.1 — one shared mechanism, not a
    # per-router/per-field patch; see app/db.py's ``_NulByteGuardCursor``).
    # ``email`` needs no extra guard either way: ``_validate_settings_email``
    # -> ``email_validator`` already rejects a NUL byte in the local-part
    # before the DB layer.
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
    base_resume_row: dict | None,
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
            # U2a (R-F1), re-refixed 2026-08-13 per the ORCHESTRATOR RULING
            # (NEW-2/F-2): whether the user's BASELINE résumé — the MOST
            # RECENT Settings upload with stored original bytes (`parentId IS
            # NULL`, newest `createdAt` among rows with `"originalFile" IS NOT
            # NULL`; see `base_resume_row`'s query above) — has its original
            # upload bytes stored. That is the honest signal for "a future
            # format-preserving engine (U2b/R-F4) has a source document for
            # this user's baseline" vs. "this account's baseline predates
            # original-byte storage, or has none." Deliberately NOT keyed off
            # `resume_row` (whichever résumé is newest, tailored children
            # included): every tailored child is created with no
            # `originalFile` at all, so that would flip a permanently-stored
            # baseline's badge to a pointless re-upload prompt the moment the
            # user's first tailoring run completes. Also NOT keyed off the
            # user's FIRST-ever upload: a user who re-uploads (the exact
            # remedy this badge's negative state instructs) gets a NEW
            # `parentId IS NULL` row with bytes, and the badge must pick that
            # fresher row, not stay pinned to the original upload forever.
            # False (never None) when the user has no baseline with stored
            # bytes at all, so the Settings panel never has to special-case a
            # missing summary object.
            "originalStored": (
                bool(base_resume_row.get("hasOriginal")) if base_resume_row else False
            ),
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
    # U2a (R-F1): "originalFile" is a lazily-added column (app.db.ensure_resume_
    # columns) — must run before the "Latest resume" query below selects a
    # presence check on it, exactly like every other Resume read path.
    ensure_resume_columns()

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

            # Latest resume — feeds "activeFile"/"uploadedAt" only. The
            # "original stored" badge is a SEPARATE query below
            # (base_resume_rows), since the badge must track the immutable
            # baseline, not whichever résumé is newest (a tailored child
            # never has stored original bytes) — see the ORCHESTRATOR
            # RULING comment on that query for the full reasoning.
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

            # ORCHESTRATOR RULING (2026-08-13, resolves FE re-review NEW-2 +
            # F-2 permanently): the "baseline" row is the user's MOST RECENT
            # Settings upload that has stored original bytes — `parentId IS
            # NULL AND "originalFile" IS NOT NULL`, newest `createdAt` first.
            # That is exactly what `POST /resumes/upload` creates and what the
            # UI's "re-upload" instruction produces, so a legacy user (base v1,
            # no bytes) who re-uploads gets base v2 picked here immediately —
            # unlike the old "lowest version" rule, which pinned the badge to
            # the FIRST upload ever made forever, even after a fresher one
            # with real bytes existed (NEW-2).
            #
            # The `ORDER BY` below expresses that as a two-tier preference
            # rather than a hard `WHERE ... AND "originalFile" IS NOT NULL`
            # filter: rows WITH stored bytes sort first (newest of those wins,
            # per the RULING); only when the user has NO byte-stored root row
            # at all does this fall back to their newest root row regardless.
            # That fallback matters because this same "baseline" row also has
            # to stay resolvable for callers that mean something narrower by
            # "the baseline" — the user's root document for content grounding
            # — never whichever résumé happens to be newest overall. Every
            # tailored child is created with no `originalFile` at all
            # (`TailorAgent.run`'s `_resumes.create(...)` call never passes
            # original-file fields — see `apps/api/app/agents/tailor_agent.py`),
            # so keying this off `resume_rows` (latest version, tailored
            # children included) would flip a permanently-stored baseline's
            # badge to the "re-upload" prompt the instant the user's first
            # tailoring run completes — the default state for almost every
            # active user (7 base vs 378 tailored résumé rows observed in
            # prod). When the picked row genuinely has no stored bytes,
            # `"hasOriginal"` below is honestly `false` — the fallback never
            # fabricates a stored-original claim.
            cur.execute(
                """
                SELECT "originalFile" IS NOT NULL AS "hasOriginal"
                FROM "Resume"
                WHERE "userId" = %s AND "parentId" IS NULL
                ORDER BY ("originalFile" IS NOT NULL) DESC, "createdAt" DESC,
                    "version" DESC
                LIMIT 1
                """,
                (uid,),
            )
            base_resume_rows = rows_to_dicts(cur)

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
    base_resume = base_resume_rows[0] if base_resume_rows else None
    version_count = cnt_rows[0]["cnt"] if cnt_rows else 0

    portfolio_row = CareerProfileRepository().get(uid, "portfolio")
    result = _build_settings(user, resume, base_resume, portfolio_row)
    result["resume"]["versions"] = version_count
    # I4-FE-03: whether a source counts as "connected" is a backend fact —
    # a source with historical Job rows (e.g. discovered before a compliance
    # gate was added) must not be shown as active once that gate excludes it
    # from the live registry. ``build_live_registry()`` re-reads the gate's
    # env flag (AETHER_ENABLE_SEEK) on every call, so this stays correct
    # both when the gate is off (default) and if it is ever enabled — no
    # source name is hardcoded here.
    from app.services.discovery.adapter_registry import build_live_registry

    live_sources = build_live_registry()
    result["integrations"] = [
        {
            "name": row["source"].capitalize() if row["source"].islower() else row["source"],
            "status": "connected" if row["source"] in live_sources else "not_configured",
            "detail": (
                f"{row['cnt']} jobs discovered · last sync "
                f"{str(row['last_seen'])[:16]} UTC"
            )
            if row["source"] in live_sources
            else "Not currently active",
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

    google_accounts = GmailAccountRepository().list_accounts(uid)
    for gacc in google_accounts:
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
    # Real Google Calendar connection (W-CAL / ADR-CALENDAR-V4). Reported ONLY
    # for a user who has a Google account at all — and then per GM2-EMAIL-001,
    # from REAL token validity: an account whose stored grant lacks
    # calendar.events is settled without a network call, and one that has it is
    # LIVE-probed so "connected" means Google accepted the token just now, not
    # that a row exists. A row is never enough to claim a capability.
    if google_accounts:
        from app.services.calendar_service import STATUS_UNAVAILABLE, connection_status

        try:
            cal = connection_status(uid)
        except Exception as exc:  # noqa: BLE001 — settings must never 500 on this
            # Honest third state, never an assumed "connected": we say we could
            # not check rather than guessing either way.
            cal = {
                "status": STATUS_UNAVAILABLE,
                "message": (
                    "Google Calendar connection could not be checked just now: "
                    f"{exc}"
                ),
            }
        accounts.append(
            {
                "name": "Google Calendar",
                "status": str(cal["status"]),
                "detail": str(cal["message"]),
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


#: Basename (lowercased) → canonical export filename, for a single loose .csv.
_LINKEDIN_CSV_BASENAMES = {name.lower(): name for name in LINKEDIN_EXPORT_FILES}


@router.post("/career-data/linkedin-upload")
async def upload_linkedin_export(
    current_user: CurrentUser, file: UploadFile = File(...)
) -> dict[str, Any]:
    """Ingest LinkedIn's official "Download your data" export (B7).

    Accepts the export **.zip**, or one of its individual CSVs
    (``Profile.csv``/``Positions.csv``/``Education.csv``/``Skills.csv``)
    uploaded loose. This is a compliant, upload-only path: nothing here ever
    fetches linkedin.com or any other network resource — the parsed CSVs are
    normalized into the same text shape the candidate-paste box produces and
    handed to the SAME ``ingest_linkedin`` that path uses
    (``app.services.career_data.ingest_linkedin_export``), so storage,
    corpus assembly and honest empty/error semantics are inherited, not
    reimplemented.
    """
    # Bounded read: one byte past the cap proves it's oversized without ever
    # buffering (or persisting) a huge upload whole.
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
            csv_texts = parse_linkedin_export_zip(data)
        except zipfile.BadZipFile:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Uploaded file is not a valid zip archive.",
            ) from None
        if not csv_texts:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Zip archive contained none of the expected LinkedIn export "
                "files: " + ", ".join(LINKEDIN_EXPORT_FILES) + ".",
            )
    elif suffix == "csv":
        basename = filename.rsplit("/", 1)[-1]
        canonical = _LINKEDIN_CSV_BASENAMES.get(basename.lower())
        if canonical is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unrecognized CSV file '{filename}'. Expected one of: "
                + ", ".join(LINKEDIN_EXPORT_FILES) + ".",
            )
        csv_texts = {canonical: data.decode("utf-8", errors="replace")}
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Unsupported file type — upload the .zip from LinkedIn's "
            "'Download your data' export, or one of its CSV files: "
            + ", ".join(LINKEDIN_EXPORT_FILES) + ".",
        )

    result = ingest_linkedin_export(csv_texts)
    repo = CareerProfileRepository()
    saved = repo.upsert(
        current_user["id"],
        "linkedin",
        status=result["status"],
        url=result["url"],
        content=result["content"],
        summary=result["summary"],
        error=result["error"],
    )
    return {
        "source": _shape_source("linkedin", saved),
        "ingestedCounts": result["ingestedCounts"],
        "linkedinNote": _LINKEDIN_NOTE,
    }
