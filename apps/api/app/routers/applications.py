"""Applications router — pipeline board, tracker metadata, sankey (P2-S10)."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import psycopg2
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import (
    ensure_application_apply_channel_column,
    ensure_application_apply_resolution_columns,
    ensure_application_manual_step_columns,
    ensure_application_manual_step_question_column,
    ensure_application_submission_truth_columns,
    ensure_application_transmission_columns,
    ensure_application_unique_active_index,
    ensure_job_apply_contact_columns,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser
from app.repositories.application_status_event import record_status_event_best_effort
from app.routers.analytics import get_application_counts
from app.services.stage_transitions import move_application_stage, move_job_stage
from app.services.submission_snapshot import record_submission_snapshot
from app.services.submission_truth import mark_recorded_not_transmitted

logger = logging.getLogger(__name__)

router = APIRouter()

#: Valid Application.status values — mirrors the "ApplicationStatus" enum.
_STATUSES = frozenset(
    {"draft", "submitted", "screening", "interview", "offer", "rejected", "withdrawn"}
)

#: W-SUB: the transmission columns and the job's derived apply address travel
#: with EVERY application read, so no caller can render a "submitted" card
#: without also having the fact of whether anything was actually transmitted.
#: See ``app.services.application_submission.submission_view``.
#:
#: U5 (NO-PREPARED-ONLY invariant): the apply-channel and manual-step columns
#: travel with every read for the SAME reason. TRANSMITTED is only half the
#: invariant — the other half is the honest, actionable manual-step state
#: (``manualStepReason``/``manualStepDetail``/``manualStepAt``, written by
#: ``app.services.apply_executor.record_manual_step``; ``applyChannel``
#: written by ``app.services.apply_channel_resolver``). If these are not
#: SELECTed here, an application blocked by a CAPTCHA, a login wall or a
#: question Aether refuses to fabricate an answer to is recorded honestly in
#: Postgres and shows the user NOTHING — i.e. it reads as silently stuck in
#: "prepared", which is exactly the outcome U5 forbids. Any new writer of a
#: submission-outcome column must be added here in the same change.
_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."answers", a."createdAt", a."updatedAt", j."title" AS "jobTitle", '
    'j."company", j."sourceUrl" AS "applyUrl", j."fitScore", '
    'a."transmittedAt", a."transmittedTo", a."transmissionChannel", '
    'a."transmissionRef", j."applyEmail", j."applyEmailSource", '
    'a."applyChannel", a."manualStepReason", a."manualStepDetail", '
    'a."manualStepAt", a."manualStepQuestions", '
    'a."submissionTruthState", a."submissionTruthAt", '
    # SUB-006: when Aether applied at a canonical ATS form URL rather than the
    # posting URL the user sees, BOTH are on the row — the substitution is
    # disclosed to the client, not only to the server log.
    'a."applyResolvedFrom", a."applyResolvedUrl", a."applyResolvedAt", '
    # U5d-2: does a JOB-TAILORED résumé exist for this application's job? The
    # per-card submit control must promise exactly what the write path will
    # accept (``jobs._resume_for_apply``), so it reads the same fact rather
    # than trusting ``a."resumeId"`` — the only producer of these drafts
    # attaches the BASE résumé, so that column answers a different question.
    'EXISTS (SELECT 1 FROM "Resume" r WHERE r."userId" = a."userId" '
    'AND r."sourceJobId" = a."jobId") AS "hasTailoredResume"'
)


def _ensure_read_columns() -> None:
    """Run the lazy additive DDL every ``_COLUMNS`` read depends on (ADR-TR-1).

    ``_COLUMNS`` names columns added by additive lazy migrations, so the DDL
    MUST run before any statement that reads them — a path that skipped the
    equivalent call for ``contentHash`` raised UndefinedColumn -> HTTP 500 on
    first use. Kept as ONE helper so a future column added to ``_COLUMNS``
    cannot be ensured on one endpoint and forgotten on the other.
    """
    ensure_application_transmission_columns()
    ensure_job_apply_contact_columns()
    ensure_application_apply_channel_column()
    ensure_application_submission_truth_columns()
    ensure_application_manual_step_columns()
    ensure_application_manual_step_question_column()
    ensure_application_apply_resolution_columns()


def _with_submission(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the truthful submission block to each application row (W-SUB).

    ``Application.status`` is left EXACTLY as stored — history is never
    rewritten. What is added is the answer to the question the status alone
    cannot answer: did Aether actually transmit this application anywhere?
    For all 86 pre-existing 'submitted' rows the answer is a recorded, honest
    ``transmitted: false``.
    """
    from app.services.application_submission import submission_view
    from app.services.submission_control import describe_submission_control

    for row in rows:
        row.update(submission_view(row))
        # U5d-2: the per-card control, computed ONCE on the server from the
        # same persisted columns, so no surface can invent a state the row
        # does not support (see app/services/submission_control.py).
        row["submissionControl"] = describe_submission_control(row)
    return rows

router = APIRouter()


@router.get("/funnel/sankey")
def funnel_sankey(current_user: CurrentUser) -> dict[str, Any]:
    """Real-time application-flow sankey computed from live DB counts.

    CUMULATIVE model (MV-application-tracker-006): each node counts
    applications that have reached AT LEAST that stage, mirroring the
    nested-IN stage definitions analytics.funnel() already uses — the
    ``applied`` stage is the canonical non-draft count from
    get_application_counts() (status <> 'draft', consistent with the funnel's
    own stage and the dashboard summary), "screened" is status IN (screening,
    interview, offer), "interviewed" is status IN (interview, offer), and
    "offers" is status = 'offer'. Each stage is therefore always >= the next
    stage, so every dropoff (stage_N - stage_{N+1}) is always >= 0.

    AUD-META-1 ("Dashboard/Analytics label apps 'submitted/applied' when not
    transmitted"): that stage KEY stays ``applied`` — the FE binds stage
    identity and dropoffs to it — but its user-visible LABEL is "Prepared",
    because ``status <> 'draft'`` is preparation and carries no evidence that
    anything was sent. The payload additionally carries ``transmitted``
    (``transmittedAt IS NOT NULL``, the same DISTINCT-jobId discipline), and
    the insight prose states both figures separately. Pinned by
    ``tests/test_meta1_cohort_transmitted.py``.

    A prior stage-EXCLUSIVE model (status == 'submitted'/'screening'/etc.
    exactly) was disproven live: an application that skipped straight to
    'interview' with nobody currently sitting in exact 'screening' produced
    a negative dropoff (screened=0, interviewed=3 -> -3), which rendered as
    the broken literal "−-3 · no response / screened out" in the Sankey UI
    (MV-application-tracker-006). Do not revert to per-exact-status buckets.
    """
    uid = current_user["id"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "Job" WHERE "userId" = %s', (uid,))
            jobs_found = cur.fetchone()[0]
            sankey_counts = get_application_counts(cur, uid)
            applied = sankey_counts["submitted"]
            # AUD-META-1: the verified-send subset of that same population —
            # ``transmittedAt IS NOT NULL``, stamped only by the real send
            # path. The node below keeps the ``applied`` KEY (stage identity
            # and dropoff wiring the FE binds to) but no longer CLAIMS the
            # word: its label is "Prepared", and this is the count that may
            # honestly be described as sent.
            transmitted = sankey_counts["transmitted"]
            # RT-004: DISTINCT jobs, not letter-version rows — 9 submitted
            # versions of one job are ONE application in the funnel.
            cur.execute(
                '''
                SELECT
                    COUNT(DISTINCT "jobId") FILTER (
                        WHERE "status" IN ('screening','interview','offer')
                    ) AS screened,
                    COUNT(DISTINCT "jobId") FILTER (
                        WHERE "status" IN ('interview','offer')
                    ) AS interviewed,
                    COUNT(DISTINCT "jobId") FILTER (WHERE "status" = 'offer') AS offers
                FROM "Application" WHERE "userId" = %s
                ''',
                (uid,),
            )
            screened, interviewed, offers = cur.fetchone()
    return {
        "stages": [
            # R-VIZ: the funnel is ONE measure (a count) walking ordered
            # stages, so it takes an ordinal gilt ramp anchored on chart-gold
            # — not five categorical hues (a 5th hue is forbidden) and not one
            # flat gold that erases the progression. Values only: keys, labels
            # and shape are untouched. Every step clears 4.5:1 on the card
            # ground #0F0F12, because the client paints each stage's numeral
            # in its own node colour.
            {"key": "jobs_found", "label": "Jobs Found", "value": jobs_found, "color": "#9C8038"},
            # AUD-META-1: "Prepared", not "Applied" — this count is
            # ``status <> 'draft'`` (preparation), and the FE renders this
            # label verbatim. The verified-send figure travels beside the
            # stages as ``transmitted``.
            {"key": "applied", "label": "Prepared", "value": applied, "color": "#AE8E32"},
            {"key": "screened", "label": "Screened", "value": screened, "color": "#C9A84C"},
            {"key": "interviewed", "label": "Interviewed", "value": interviewed,
             "color": "#D4B65C"},
            {"key": "offers", "label": "Offers", "value": offers, "color": "#E8D5A3"},
        ],
        "dropoffs": [
            {"after": "jobs_found", "count": jobs_found - applied,
             "reason": "below match threshold"},
            {"after": "applied", "count": applied - screened, "reason": "not shortlisted"},
            {"after": "screened", "count": screened - interviewed,
             "reason": "no response / screened out"},
            {"after": "interviewed", "count": interviewed - offers, "reason": "not selected"},
        ],
        # AUD-META-1: the verified-send count, exposed distinctly from the
        # prepared population above so no reader has to infer one from the
        # other. Additive — every pre-existing key keeps its exact meaning.
        "transmitted": transmitted,
        "insight": (
            f"{jobs_found} jobs found, {applied} applications prepared, "
            f"{transmitted} verifiably sent by Aether. "
            "Track applications through the pipeline to improve conversion."
        ),
    }


@router.get("/apply-sweep-status")
def apply_sweep_status(current_user: CurrentUser) -> dict[str, Any]:
    """Live read of the operator's apply-sweep kill-switch (SHOULD-FIX 6,
    round-3 re-review of U5).

    The FE's "automatic […] submission is not enabled on this deployment
    yet" copy (``tracker-lib.ts`` ``notTransmittedReason`` /
    ``automaticSubmissionDisclaimer``) used to be hardcoded — true only by
    accident and false the instant an operator sets
    ``AETHER_APPLY_SWEEP_ENABLED`` (the mandate's own end state, per
    ``apps/api/app/workers/apply_sweep.py``). This mirrors the precedent at
    ``app.workers.board_sweep.sweep_enabled()``, read live inside
    ``POST /agents/board-sweep/trigger`` — a real capability signal instead
    of an assumption baked into the client.

    Registered ahead of ``GET /{application_id}`` (same fixed-path-before-
    catch-all ordering as ``/funnel/sankey`` above) so this literal path
    segment is never swallowed as an application id.
    """
    from app.workers.apply_sweep import sweep_enabled

    return {"sweepEnabled": sweep_enabled()}



@router.get("/timeline")
def applications_timeline(current_user: CurrentUser) -> dict[str, Any]:
    """Horizontal Application Tracker timeline — status-event swimlanes.

    SESSION TL-VIZ. Same board identity as ``GET /applications`` (RT-004
    DISTINCT ON jobId), plus every observed ``ApplicationStatusEvent`` for
    those displayed application ids only. Backfill genesis rows
    (``fromStatus`` null, ``source = backfill:current-status``) are returned
    verbatim — never expanded into invented prior stages.

    Empty account: ``items: []`` and ``range.start`` / ``range.end`` are
    ``null`` so the client cannot paint a fake "today" axis.

    Registered ahead of ``GET /{application_id}`` so the literal path segment
    ``timeline`` is never swallowed as an id.
    """
    from app.repositories.application_status_event import (
        list_status_events_for_applications,
    )

    apps = list_applications(current_user)
    app_ids = [a["id"] for a in apps]
    raw_events = list_status_events_for_applications(app_ids)

    def _iso(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    by_app: dict[str, list[dict[str, Any]]] = {aid: [] for aid in app_ids}
    all_ats: list[str] = []
    for ev in raw_events:
        aid = str(ev["applicationId"])
        at = _iso(ev.get("at"))
        row = {
            "id": ev["id"],
            "applicationId": aid,
            "fromStatus": ev.get("fromStatus"),
            "toStatus": ev["toStatus"],
            "at": at,
            "source": ev["source"],
        }
        if aid in by_app:
            by_app[aid].append(row)
        if at is not None:
            all_ats.append(at)

    items = [
        {"application": app, "events": by_app.get(app["id"], [])}
        for app in apps
    ]
    if not all_ats:
        rng: dict[str, str | None] = {"start": None, "end": None}
    else:
        rng = {"start": min(all_ats), "end": max(all_ats)}
    return {"items": items, "range": rng}


@router.get("")
def list_applications(
    current_user: CurrentUser,
    app_status: str | None = None,
    include_applied: bool = False,
) -> list[dict[str, Any]]:
    """List the authenticated user's applications, joined with job metadata.

    ML-APP-003 (§8, HIGH): this listing is the board's data source and it is
    driven by ``Application.status`` ALONE — the same population
    ``/applications/funnel/sankey`` counts. It used to additionally exclude
    every row whose parent ``Job.status`` was 'applied' or 'archived', which
    made the board and the funnel answer differently about identical data:
    ``POST /jobs/{id}/apply`` (and ``POST /applications/{id}/submit``) flip
    ``Job.status`` to 'applied' the moment an application is created/promoted
    and NEVER advance it again, so an application the user then moved on to
    screening / interview / offer stayed invisible on the board — live
    evidence: the "In Review" column showed 0 while the Sankey said
    "Screened: 2" for the SAME 2 rows. That filter also emptied the board's
    Submitted column by construction (every submitted application has an
    'applied' job), i.e. the entire application-fed half of the board.

    The Job.status filter is a JOB-lifecycle concept and belongs to the board's
    first three columns, which are fed by ``GET /jobs`` (an 'applied' or
    'archived' job has no stage key in tracker-lib's JOB_STAGE map, so its job
    card correctly disappears from the pipeline half). Applying to a job ends
    the JOB's pipeline, not the APPLICATION's — so the application card must
    stay visible in its true stage column. A card on the board is now always
    counted by the funnel and vice versa; the application's own closed states
    (rejected/withdrawn) remain the way a row leaves the active pipeline.

    ``?include_applied=true`` is unchanged: it is the separate Applied/History
    view (phase4, apps/web ``fetchAppliedApplications``) and still answers with
    exactly the applications whose job the user has applied to.
    """
    clauses = ['a."userId" = %s']
    params: list[Any] = [current_user["id"]]
    if app_status is not None:
        if app_status not in _STATUSES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Invalid app_status '{app_status}'. Valid: {sorted(_STATUSES)}",
            )
        clauses.append('a."status" = %s::"ApplicationStatus"')
        params.append(app_status)
    if include_applied:
        clauses.append('j."status" = %s::"JobStatus"')
        params.append("applied")
    where = " AND ".join(clauses)
    _ensure_read_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            # RT-004: ONE board card per job, however many letter-version rows
            # exist. Application rows double as the cover-letter studio's
            # version history (one row per draft/refine), and historically each
            # promoted version became its own permanent card (live evidence:
            # 11 cards for one Plenti job). ACTIVE rows collapse per job to the
            # most-advanced status (offer > interview > screening > submitted >
            # draft; ties → newest); CLOSED rows (rejected/withdrawn) collapse
            # per job to the newest and may coexist with an active
            # re-application card.
            cur.execute(
                f'''
                SELECT * FROM (
                    SELECT DISTINCT ON (a."jobId") {_COLUMNS}
                    FROM "Application" a
                    JOIN "Job" j ON j."id" = a."jobId"
                    WHERE {where} AND a."status" IN
                        ('draft','submitted','screening','interview','offer')
                    ORDER BY a."jobId",
                        CASE a."status"
                            WHEN 'offer' THEN 5
                            WHEN 'interview' THEN 4
                            WHEN 'screening' THEN 3
                            WHEN 'submitted' THEN 2
                            ELSE 1
                        END DESC,
                        a."createdAt" DESC
                ) active
                UNION ALL
                SELECT * FROM (
                    SELECT DISTINCT ON (a."jobId") {_COLUMNS}
                    FROM "Application" a
                    JOIN "Job" j ON j."id" = a."jobId"
                    WHERE {where} AND a."status" IN ('rejected','withdrawn')
                    ORDER BY a."jobId", a."createdAt" DESC
                ) closed
                ORDER BY "createdAt" DESC
                ''',
                params + params,
            )
            return _with_submission(rows_to_dicts(cur))


@router.get("/{application_id}")
def get_application(application_id: str, current_user: CurrentUser) -> dict[str, Any]:
    _ensure_read_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Application" a '
                'JOIN "Job" j ON j."id" = a."jobId" '
                'WHERE a."id" = %s AND a."userId" = %s',
                (application_id, current_user["id"]),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return _with_submission(rows)[0]


def _account_row(user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "name", "email" FROM "User" WHERE "id" = %s', (user_id,))
            rows = rows_to_dicts(cur)
    return rows[0] if rows else {}


def _tailored_resume_row(user_id: str, job_id: str) -> dict[str, Any] | None:
    """The most recent résumé tailored to THIS job, or ``None``.

    The same fact ``_COLUMNS``'s ``hasTailoredResume`` and
    ``jobs._resume_for_apply`` read (``Resume.sourceJobId = jobId``, newest
    version first), so the pack points at exactly the document the submission
    path would attach — never the base résumé standing in for it.
    """
    if not job_id:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "version", "label", "sections", "updatedAt" '
                'FROM "Resume" WHERE "userId" = %s AND "sourceJobId" = %s '
                'ORDER BY "version" DESC, "updatedAt" DESC LIMIT 1',
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _resume_row(user_id: str, resume_id: str) -> dict[str, Any] | None:
    if not resume_id:
        return None
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "version", "label", "sections", "updatedAt" '
                'FROM "Resume" WHERE "id" = %s AND "userId" = %s',
                (resume_id, user_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _contact_from_resume(
    resume: dict[str, Any] | None,
) -> tuple[str, tuple[str, ...], str]:
    """``(name, contact lines, location)`` off a stored résumé record.

    Parsed by ``resume_document.parse_resume_document`` — the SAME document
    model the renderer draws and the completeness verifier measures — so the
    contact details the pack shows are the ones printed on the document the
    employer receives, not a second reading of the same JSON.
    """
    if not resume:
        return "", (), ""
    from app.services.resume_document import parse_resume_document

    document = parse_resume_document(resume)
    payload = resume.get("sections")
    contact = payload.get("contact") if isinstance(payload, dict) else None
    location = ""
    if isinstance(contact, dict):
        for key in ("location", "address", "city"):
            value = str(contact.get(key) or "").strip()
            if value:
                location = value
                break
    return document.name, document.contact, location


@router.get("/{application_id}/answer-pack")
def application_answer_pack(
    application_id: str, current_user: CurrentUser
) -> dict[str, Any]:
    """SUB-010 — the SMART SHORTLIST pack for one manual application.

    READ-ONLY, and auth-scoped to the owning user (another user's application
    is a 404 with no id echoed back, exactly like ``GET /applications/{id}``).
    It writes nothing, transmits nothing and contacts no employer: every value
    is fused from rows this product already holds —

    * the user's account + their résumé's own contact block + Career Data →
      the profile fields the form will ask for;
    * the questions the employer's form actually asked (captured on the row)
      plus the seed set of questions nearly every ATS asks → matched against
      the user's Answer Bank and this application's own answers;
    * the résumé tailored to THIS job → an artifact reference, not a copy;
    * the cover letter Aether wrote for THIS application → verbatim.

    Anything absent is reported absent, with the place to go and fix it. The
    payload never claims the application was applied for or sent — see
    ``app.services.answer_pack`` rules 1-3, and the honesty block it returns.
    """
    from app.repositories.answer_bank import AnswerBankRepository
    from app.repositories.career_profile import CareerProfileRepository
    from app.services.answer_pack import build_answer_pack

    user_id = current_user["id"]
    _ensure_read_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Application" a '
                'JOIN "Job" j ON j."id" = a."jobId" '
                'WHERE a."id" = %s AND a."userId" = %s',
                (application_id, user_id),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    row = rows[0]

    account = _account_row(user_id)
    tailored = _tailored_resume_row(user_id, str(row.get("jobId") or ""))
    # The contact block comes from the tailored document when one exists (that
    # is the résumé this application ships), and from the application's own
    # résumé otherwise — never invented when neither is readable.
    contact_source = tailored or _resume_row(user_id, str(row.get("resumeId") or ""))
    resume_name, contact_lines, location = _contact_from_resume(contact_source)

    return build_answer_pack(
        row=row,
        account_name=str(account.get("name") or ""),
        account_email=str(account.get("email") or ""),
        resume_name=resume_name,
        resume_contact=contact_lines,
        resume_location=location,
        career_profiles=CareerProfileRepository().list_by_user(user_id),
        bank_items=AnswerBankRepository().list_for_user(user_id),
        tailored_resume=tailored,
    )


class ScreeningAnswer(BaseModel):
    """One answer the user typed into the card for one employer question."""

    question: str = Field(..., max_length=2000)
    answer: str = Field(..., max_length=8000)


class AnswerQuestionRequest(BaseModel):
    """Payload for the native in-card answer (U5d-3 Pillar 4a)."""

    answers: list[ScreeningAnswer] = Field(..., min_length=1, max_length=25)
    #: Bank this answer for THIS employer only rather than every application.
    scope: str = Field(default="global", max_length=32)


@router.post("/{application_id}/answer-question")
def answer_question(
    application_id: str, body: AnswerQuestionRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """U5d-3 Pillar 4a — the user answers the employer's question INSIDE Aether.

    ADR-SUB-AUTON-1: *"UNKNOWN QUESTION → rendered NATIVELY in the card; user
    answers inside Aether; agent injects it, resumes, and BANKS the answer. No
    site visit."* This endpoint is the "banks the answer" half and the
    "injects it" half; the "resumes" half is honestly reported as NOT DONE,
    because it requires the paused-session persistence designed for U5d-4
    (``uat/reports/evidence/agents-uplift/u5d3/SESSION-TTL-DESIGN.md``). The
    response says so in ``resumed: false`` rather than implying the application
    went out.

    What it does, in order:

    1. **Banks** each answer with provenance ``user_answered`` and this
       application as the provenance detail, so the Answer Bank page can show
       exactly where each answer came from. The answer is stored VERBATIM —
       nothing rewrites, expands or "improves" what the user typed.
    2. **Records it against THIS application** (``Application.answers
       .screeningAnswers``), which is the layer the apply-executor consults
       first and the ONLY way a sensitive/legal question ever gets answered:
       the user answering their own form for this employer is not the agent
       reusing an old answer, so that layer is not class-gated (see
       ``answer_bank.build_resolver``).
    3. **Re-checks the blocker.** The manual step clears only when EVERY
       captured question now has an answer. A partially answered blocker stays
       standing and the response names what is still missing.

    It transmits nothing. Submitting is still the separate, explicit act it was
    before — this endpoint only removes the reason the card could not offer it.
    """
    from app.repositories.answer_bank import AnswerBankRepository
    from app.services.answer_bank import (
        SCOPE_COMPANY,
        build_resolver,
        coerce_scope,
        question_text_for_field,
    )

    user_id = current_user["id"]
    row = get_application(application_id, current_user)

    provided: dict[str, str] = {}
    for item in body.answers:
        question = item.question.strip()
        answer = item.answer.strip()
        if not question or not answer:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                (
                    "An empty answer cannot be saved — Aether will not send a "
                    "blank response to an employer's question."
                ),
            )
        provided[question] = answer

    scope = coerce_scope(body.scope)
    company = str(row.get("company") or "")
    repo = AnswerBankRepository()
    banked: list[dict[str, Any]] = []
    for question, answer in provided.items():
        banked_item = repo.upsert(
            user_id,
            question=question,
            answer=answer,
            provenance="user_answered",
            provenance_detail=application_id,
            scope=scope,
            scope_value=company if scope == SCOPE_COMPANY else None,
        )
        if banked_item is not None:
            banked.append(banked_item)

    # The per-application layer: what the user just said, for THIS employer.
    stored = row.get("answers")
    answers_blob: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
    screening = answers_blob.get("screeningAnswers")
    screening = dict(screening) if isinstance(screening, dict) else {}
    screening.update(provided)
    answers_blob["screeningAnswers"] = screening

    captured = row.get("manualStepQuestions")
    captured = captured if isinstance(captured, list) else []
    resolve = build_resolver(
        repo.list_for_user(user_id), screening_answers=screening, company=company
    )
    remaining = [
        question_text_for_field(field)
        for field in captured
        if isinstance(field, dict) and field.get("required", True) and resolve(field) is None
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            if remaining:
                cur.execute(
                    'UPDATE "Application" SET "answers" = %s::jsonb, '
                    '"updatedAt" = NOW() WHERE "id" = %s AND "userId" = %s',
                    (json.dumps(answers_blob), application_id, user_id),
                )
            else:
                # Every captured question is answered: the obstacle is gone, so
                # the row stops claiming one. transmittedAt is untouched —
                # clearing a blocker is not a submission.
                cur.execute(
                    'UPDATE "Application" SET "answers" = %s::jsonb, '
                    '"manualStepReason" = NULL, "manualStepDetail" = NULL, '
                    '"manualStepQuestions" = NULL, "manualStepAt" = NULL, '
                    '"updatedAt" = NOW() WHERE "id" = %s AND "userId" = %s',
                    (json.dumps(answers_blob), application_id, user_id),
                )
        conn.commit()

    from app.repositories.admin import write_audit

    write_audit(
        user_id,
        "answer_bank.in_card_answer",
        target_type="application",
        target_id=application_id,
        detail={"banked": len(banked), "remaining": len(remaining)},
    )

    if remaining:
        detail = (
            "Saved. "
            f"{len(remaining)} question{'' if len(remaining) == 1 else 's'} still "
            "need an answer before Aether can submit this one."
        )
    else:
        detail = (
            "Saved to your Answer Bank. Nothing has been sent — Aether will use "
            "this answer on the next submission attempt for this application, "
            "and on future applications that ask the same thing."
        )

    return {
        "applicationId": application_id,
        "banked": [
            {
                "id": item["id"],
                "questionText": item["questionText"],
                "sensitivity": item["sensitivity"],
                "provenance": item["provenance"],
                "reusable": item["sensitivity"] == "factual",
            }
            for item in banked
        ],
        "remainingQuestions": remaining,
        # Honest, and deliberately explicit: the browser session that hit this
        # question was NOT held open, so nothing resumed and nothing was sent.
        "resumed": False,
        "transmitted": False,
        "detail": detail,
    }


@router.post("/{application_id}/reconfirm-submission")
def reconfirm_submission(application_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """One-click re-approval for a submission whose approval aged out (U5).

    The sweep refuses to auto-execute an approval older than
    ``AETHER_APPROVAL_MAX_AGE_DAYS`` (``apply_sweep._expire_stale_approval``)
    and records ``manualStepReason = 'approval_expired'`` instead. This is the
    honest way back: it creates a FRESH ``ApprovalRequest`` through the
    EXISTING approval machinery (same repository, same approve() path, same
    audit trail) and clears ONLY the expired state.

    Deliberately narrow:

    * it transmits NOTHING — it re-arms the gate, and the sweep (when the
      operator has it enabled) does the work under all the usual guards;
    * it refuses (409) for any other manual-step reason. A CAPTCHA or a login
      wall is not solved by re-approving, and wiping that state would put the
      row straight back into a loop that re-discovers the same obstacle;
    * it never touches an application it does not own (404).
    """
    from app.repositories.admin import write_audit
    from app.repositories.approval import ApprovalRepository

    user_id = current_user["id"]
    ensure_application_manual_step_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "jobId", "manualStepReason" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            job_id, manual_step_reason = row
            if manual_step_reason != "approval_expired":
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    (
                        "This application is not waiting on an expired approval, "
                        "so there is nothing to re-confirm."
                        if not manual_step_reason
                        else (
                            "This application is blocked by something a re-approval "
                            f"cannot fix ({manual_step_reason}) — nothing was changed."
                        )
                    ),
                )
            cur.execute(
                '''SELECT "payload" FROM "ApprovalRequest"
                   WHERE "applicationId" = %s AND "userId" = %s
                     AND "type" = 'application_submit'::"ApprovalType"
                   ORDER BY "createdAt" DESC LIMIT 1''',
                (application_id, user_id),
            )
            prior = cur.fetchone()
    if prior is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This application has never been approved for submission, so there "
            "is nothing to re-confirm.",
        )
    payload = prior[0] if isinstance(prior[0], dict) else {}
    if not payload:
        payload = {"kind": "site_apply", "job_id": job_id, "application_id": application_id}

    repo = ApprovalRepository()
    fresh = repo.create(user_id, "application_submit", payload, application_id=application_id)
    approved = repo.approve(fresh["id"], user_id)
    if approved is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Could not re-confirm this application — please try again.",
        )
    # Only NOW is the expired state cleared, and only while it is still the
    # expired state: if the approve above had failed, the row would keep its
    # honest "reconfirm to submit" message instead of silently re-entering the
    # queue with the same stale approval.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''UPDATE "Application"
                   SET "manualStepReason" = NULL, "manualStepDetail" = NULL,
                       "manualStepAt" = NULL, "updatedAt" = NOW()
                   WHERE "id" = %s AND "userId" = %s
                     AND "manualStepReason" = 'approval_expired' ''',
                (application_id, user_id),
            )
        conn.commit()
    write_audit(
        user_id,
        "approval.reconfirm",
        target_type="approval",
        target_id=approved["id"],
        detail={
            "applicationId": application_id,
            "reason": "approval_expired",
            "previousApprovalReplaced": True,
        },
    )
    return {
        "reconfirmed": True,
        "approvalId": approved["id"],
        "applicationId": application_id,
        "detail": (
            "Approval refreshed. Nothing has been submitted yet — this "
            "re-arms the submission gate with today's confirmation."
        ),
    }


@router.post("/{application_id}/request-submission")
def request_submission(application_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """U5d-2 — the per-card Submit control: THIS click IS the user's approval.

    USER MANDATE (2026-08-14): "the click IS the user's approval for THAT
    application". This endpoint therefore creates AND approves an
    ``application_submit`` ApprovalRequest — through the EXISTING repository
    (``create`` then ``approve``, the same compare-and-set the Approvals screen
    uses, the same audit trail), scoped to this one application.

    It is NOT a bypass, and it transmits NOTHING. The single place a real
    submission can happen is still ``POST /approvals/{id}/execute`` and its
    single-shot ``claim_execution`` guard; this endpoint hands the caller the
    approval id to execute next, and says so in its response
    (``transmitted: false``).

    It refuses, honestly and specifically, rather than approving something the
    product would then decline to do:

    * 404 — not the caller's own application;
    * 409 — a channel Aether will not drive (an ASSISTED platform, Seek, or a
      destination that would not resolve). The user gets the direct link
      instead, which is what the card already shows;
    * 409 — the application is already transmitted, already recorded, or
      blocked by a manual step that a submission cannot fix;
    * 422 — the gate artifacts are missing, with the same wording the Apply
      button uses.
    """
    from app.repositories.approval import ApprovalRepository
    from app.services.application_submission import (
        queue_submission_approval,
        resolve_job_apply_recipient,
    )
    from app.services.apply_channel_resolver import (
        AUTOMATABLE_CHANNELS,
        resolve_and_persist_apply_channel,
    )
    from app.services.submission_control import describe_submission_control

    user_id = current_user["id"]
    row = get_application(application_id, current_user)
    if not (row.get("applyEmail") or "").strip():
        # Derive + cache the address the EMPLOYER published in the posting body.
        # The board's read path is deliberately offline (no outbound request per
        # rendered card), so a posting whose address has never been derived
        # reads as its URL's channel. Deriving it HERE — once, on the click that
        # authorises a submission — is what stops an assisted-looking card from
        # refusing a submission the W-SUB email path could actually make.
        if resolve_job_apply_recipient(user_id, str(row["jobId"])) is not None:
            row = get_application(application_id, current_user)
    control = row.get("submissionControl") or describe_submission_control(row)
    if control["state"] != "ready":
        if control["action"] == "fix_artifacts":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, control["detail"]
            )
        raise HTTPException(status.HTTP_409_CONFLICT, control["detail"])

    # The channel is RESOLVED here (one network hop at most, for an Adzuna
    # redirector) rather than reused from the read path's offline
    # classification: this is the moment a real submission is being authorised,
    # so it is worth learning the true destination, and the answer is persisted
    # for every later read.
    resolved = resolve_and_persist_apply_channel(
        user_id,
        application_id,
        {"sourceUrl": row.get("applyUrl"), "applyEmail": row.get("applyEmail")},
    )
    channel = str(resolved["channel"])
    apply_url = str(resolved.get("applyUrl") or row.get("applyUrl") or "")
    if channel != "email" and channel not in AUTOMATABLE_CHANNELS:
        # The offline classification and the resolved one disagreed (an
        # unresolved redirector, most often). Say so; never approve a card for
        # a channel that would be refused at execute time.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            (
                "Aether does not auto-submit on this platform, so nothing was "
                "approved. Open the posting and apply yourself"
                + (f": {apply_url}" if apply_url else ".")
            ),
        )
    approval = queue_submission_approval(
        user_id,
        str(row["jobId"]),
        application_id,
        row.get("resumeId"),
        channel=channel,
        apply_url=apply_url,
    )
    if approval is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            (
                "Aether could not prepare a submission for this posting, so "
                "nothing was approved and nothing was sent."
            ),
        )
    repo = ApprovalRepository()
    approved = repo.approve(approval["id"], user_id)
    if approved is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Could not record your approval — please try again. Nothing was sent.",
        )
    from app.repositories.admin import write_audit

    write_audit(
        user_id,
        "approval.card_submit_click",
        target_type="approval",
        target_id=approved["id"],
        detail={"applicationId": application_id, "channel": channel},
    )
    return {
        "approvalId": approved["id"],
        "applicationId": application_id,
        "channel": channel,
        "transmitted": False,
        "detail": (
            "Your approval is recorded. Nothing has been sent yet — executing "
            "this approval is what submits the application."
        ),
    }


class SubmitRequest(BaseModel):
    """Payload for marking an application as submitted on the company site."""

    applied_url: str | None = Field(default=None, max_length=2000)


# ---- §8.1 / FEAT-B2: move cards between kanban stages -----------------------
#
# The board (apps/web tracker-lib.ts) has 8 columns. The FIRST 3 are fed by
# Job.status (discovered / evaluating / tailoring — the agent pipeline half);
# the LAST 5 are fed by Application.status. Moves are therefore two card
# families: application cards move between the 5 app-fed stages, job cards
# between the 3 job-fed stages. Crossing the split is rejected with an honest
# 422 — an application's presence is what removes the job card from the
# pipeline half.
#
# GOV-003 / §13.1: ALL of the rules (stage matrix, closed-application guard,
# RT-004 one-active-application-per-job invariant, audit write) live in ONE
# shared transition service — app/services/stage_transitions.py. The three
# routes below are thin transport adapters over it; there is no second
# implementation. PATCH /applications/{id}/stage is the CANONICAL contract
# (§8.1); the two POST .../move routes are the legacy transports kept for
# their live callers (apps/web tracker-api.ts).


class MoveRequest(BaseModel):
    """Target stage for moving a kanban card (legacy FEAT-B2 payload)."""

    to_stage: str = Field(..., max_length=50, description="Target stage key")


class StageTransitionRequest(BaseModel):
    """Canonical §8.1 stage-move payload: where the card was, where it goes."""

    from_stage: str = Field(
        ..., max_length=50, description="Stage key the card is moving OUT of"
    )
    to_stage: str = Field(
        ..., max_length=50, description="Stage key the card is moving INTO"
    )


@router.patch("/{application_id}/stage")
def patch_application_stage(
    application_id: str, body: StageTransitionRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Canonical stage move for an APPLICATION card (§8.1, GOV-003).

    Delegates to :func:`app.services.stage_transitions.move_application_stage`
    — the same service the legacy ``POST /applications/{id}/move`` route uses,
    so the two transports can never drift apart (§13.1).

    Legal matrix: any transition between ready/submitted/in-review/interview/
    offer, forward or backward — the user is the source of truth for their own
    pipeline; same-stage is an idempotent no-op. Enforced SERVER-SIDE:
      * job-fed (discovered/evaluating/tailoring) or unknown stage keys in
        EITHER field → 422 naming the offending stage;
      * a closed (rejected/withdrawn) application → 422;
      * ``from_stage`` that disagrees with the application's real stage → 409
        naming the real one (a stale board never silently overwrites a move
        that happened in between);
      * another user's (or an unknown) application → 404 "Application not
        found", the same owner-scoped answer every other application endpoint
        gives — never a silent success;
      * every applied transition is audited as ``application.stage_move`` with
        actor / from / to / timestamp, atomically with the update.

    Returns the updated application row (identical shape to
    ``GET /applications/{id}``).
    """
    move_application_stage(
        user_id=current_user["id"],
        application_id=application_id,
        to_stage=body.to_stage,
        from_stage=body.from_stage,
        # This router owns the request's unit of work — the transition runs on
        # the same connection source as the read that renders the response.
        connection_factory=get_connection,
    )
    return get_application(application_id, current_user)


@router.post("/pipeline/{job_id}/move")
def move_pipeline_job(
    job_id: str, body: MoveRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Move a pipeline JOB card between the 3 job-fed stages (FEAT-B2).

    422 for app-fed/unknown targets; 409 when the job already has an
    application (it is no longer a pipeline card — move the application
    instead); 404 unknown/foreign job. Audited as ``job.stage_move``.
    Delegates to the shared transition service (GOV-003).
    """
    move = move_job_stage(
        user_id=current_user["id"],
        job_id=job_id,
        to_stage=body.to_stage,
        connection_factory=get_connection,
    )
    return {"id": move.job_id, "status": move.to_status, "stage": move.to_stage}


@router.post("/{application_id}/move")
def move_application(
    application_id: str, body: MoveRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Move an APPLICATION card between the 5 application-fed stages (FEAT-B2).

    LEGACY transport for the canonical PATCH ``/applications/{id}/stage``
    above: same shared transition service, same rules, same responses — it
    simply carries no ``from_stage``, so no stale-board conflict check is
    possible for its callers. Kept because the shipped web client
    (``apps/web`` tracker-api ``moveApplication``) calls it.
    """
    move_application_stage(
        user_id=current_user["id"],
        application_id=application_id,
        to_stage=body.to_stage,
        connection_factory=get_connection,
    )
    return get_application(application_id, current_user)


# ---- Clear Pipeline (FEAT-CLEAR): archive every agent-pipeline job card ----
#
# The board's first 3 columns (Discovered / Evaluating / Tailoring) are fed by
# Job.status — the agent-driven pipeline half. "Clear Pipeline" archives every
# one of the user's jobs still sitting in that half (status IN discovered /
# screening / matched / tailoring) AND with no application yet, in one audited
# transaction. Soft-archive only (jobs are never destroyed — see DELETE
# /jobs/{id}); the rows stay recoverable in the history view. Jobs that already
# have an application are untouched — they left the pipeline half when the
# application was created and now live on the application-fed side of the
# board, where each card is a real application the user chose to track.

#: Job.status values that render in the 3 pipeline-fed columns.
_PIPELINE_JOB_STATUSES = ("discovered", "screening", "matched", "tailoring")


class ClearPipelineRequest(BaseModel):
    """Optional confirm flag so the client signals the user saw the gate."""

    confirm: bool = Field(
        default=False, description="Must be true — the UI confirms first."
    )


@router.post("/pipeline/clear")
def clear_pipeline(
    body: ClearPipelineRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Archive every agent-pipeline job card (FEAT-CLEAR).

    Idempotent: an empty pipeline is a 200 with ``archived=0``. Only the 3
    pipeline-fed columns are touched — applications, closed cards and already
    applied/archived jobs are never modified. Every archived job is recorded
    in the audit log as ``job.pipeline_clear`` so the action is traceable to
    the actor even though no single ``target_id`` covers a bulk delete.
    """
    if not body.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Confirmation required — set confirm=true to clear the pipeline.",
        )
    uid = current_user["id"]
    archived_ids: list[str] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Pipeline jobs WITH no application — the visible board cards in
            # Discovered/Evaluating/Tailoring. Jobs that already have an
            # application left the pipeline half and must be left alone.
            cur.execute(
                f'''
                SELECT j."id" FROM "Job" j
                WHERE j."userId" = %s
                  AND j."status" IN ({",".join(
                      "%s::\"JobStatus\"" for _ in _PIPELINE_JOB_STATUSES
                  )})
                  AND NOT EXISTS (
                      SELECT 1 FROM "Application" a
                      WHERE a."jobId" = j."id" AND a."userId" = j."userId"
                  )
                ''',
                (uid, *_PIPELINE_JOB_STATUSES),
            )
            ids = [r[0] for r in cur.fetchall()]
            if ids:
                cur.execute(
                    '''
                    UPDATE "Job"
                    SET "status" = 'archived'::"JobStatus", "updatedAt" = NOW()
                    WHERE "userId" = %s AND "id" = ANY(%s)
                    ''',
                    (uid, ids),
                )
                from app.repositories.admin import write_audit

                write_audit(
                    uid,
                    "job.pipeline_clear",
                    target_type="job",
                    target_id=None,
                    detail={"archived_count": len(ids), "job_ids": ids},
                    cur=cur,
                )
                archived_ids = ids
            conn.commit()
    return {"archived": len(archived_ids), "jobIds": archived_ids}


@router.post("/{application_id}/submit")
def submit_application(
    application_id: str, body: SubmitRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Mark a draft application as submitted, recording the real apply URL.

    The user applies on the company site themselves (human-in-the-loop);
    this endpoint only tracks that it happened. Idempotent: re-submitting an
    already-submitted application is a no-op that returns the current row.

    Advances the parent Job.status to 'applied' so the card is removed from
    the active pipeline board and moves to the Applied view (phase4).
    """
    submitted_job_id: str | None = None
    #: Bound inside the draft branch below; kept declared here so the U-AX
    #: snapshot call after the transaction is unambiguously defined on every
    #: path (it only runs when ``submitted_job_id`` is set, i.e. that branch
    #: ran and assigned it).
    tailored_resume_id: str | None = None
    ensure_application_unique_active_index()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "answers", "jobId", "coverLetter", "resumeId" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, current_user["id"]),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            if row[0] == "draft":
                if not row[3] or not row[3].strip():
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "Cannot submit — this application has no cover letter. "
                        "Generate one from the Cover Letter Studio.",
                    )
                # FEAT-SUBMISSION-GATE requires a JOB-TAILORED resume to EXIST
                # before a draft can be submitted. Resolve it the same way the
                # sibling promotion path does (jobs._resume_for_apply), rather
                # than trusting the draft's own "resumeId": the only producer of
                # these drafts (CoverLetterRepository.create, called by
                # cover_letter_agent with TailoringAgent().ensure_base_resume)
                # always attaches the BASE resume, so demanding that the ALREADY
                # attached row be the tailored one made this endpoint
                # unsatisfiable for every draft the product can actually create.
                # The tailored-resume requirement itself is unchanged — no
                # tailored version for this job is still a hard 422. When the
                # draft already carries a tailored version for the job it wins;
                # otherwise the newest tailored version is used and stamped onto
                # the row below, exactly as jobs.apply_to_job does.
                cur.execute(
                    'SELECT "id" FROM "Resume" '
                    'WHERE "userId" = %s AND "sourceJobId" = %s '
                    'ORDER BY ("id" = %s) DESC NULLS LAST, "version" DESC '
                    'LIMIT 1',
                    (current_user["id"], row[2], row[4]),
                )
                resume = cur.fetchone()
                if resume is None:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "Cannot submit — your resume is not tailored for this job. "
                        "Tailor your resume first.",
                    )
                tailored_resume_id = resume[0]
                # RT-004 promotion guard — one active application per job (see
                # move_application): submitting a second letter-version of an
                # already-applied job would mint a duplicate board card.
                cur.execute(
                    'SELECT "id" FROM "Application" WHERE "userId" = %s '
                    'AND "jobId" = %s AND "id" <> %s AND "status" IN '
                    "('submitted','screening','interview','offer') LIMIT 1",
                    (current_user["id"], row[2], application_id),
                )
                if cur.fetchone() is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "This job already has an active application — this draft "
                        "stays in the letter's version history.",
                    )
                # Double-submit race guard (reviewer niceToHave #3,
                # ml-adjudication-review-verdict.json): the WHERE clause below
                # includes "AND status = 'draft'" as a compare-and-swap — two
                # concurrent submits can both pass the "row[0] == 'draft'"
                # check above (both read the row before either committed),
                # but only the FIRST one's UPDATE can still match a 'draft'
                # row; by the time the second one's UPDATE runs, the row is
                # already 'submitted' and RETURNING comes back empty. That
                # second caller must NOT be treated as a fresh promotion — it
                # falls through to the same idempotent
                # ``return get_application(...)`` at the bottom that an
                # already-submitted application always took, instead of
                # silently overwriting the winner's answers/resumeId.
                #
                # NTH-R10 (wave35-sonnet-review-verdict.json): the CAS above
                # only protects THIS row — it cannot stop a concurrent
                # promotion of a DIFFERENT draft for the SAME job, which can
                # commit between this request's guard SELECT (above) and
                # this UPDATE. The partial unique index
                # (ensure_application_unique_active_index) is the real
                # backstop for that cross-row race; map its violation to the
                # IDENTICAL 409 the guard above returns, so the client
                # contract is unchanged whether the race is caught there or
                # here.
                try:
                    cur.execute(
                        """
                        UPDATE "Application"
                        SET "status" = 'submitted'::"ApplicationStatus",
                            "resumeId" = %s,
                            "answers" = COALESCE("answers", '{}'::jsonb) || %s::jsonb,
                            "updatedAt" = NOW()
                        WHERE "id" = %s AND "userId" = %s
                          AND "status" = 'draft'::"ApplicationStatus"
                        RETURNING "id"
                        """,
                        (
                            tailored_resume_id,
                            json.dumps(
                                {
                                    "appliedUrl": body.applied_url,
                                    "submittedAt": datetime.now(UTC).isoformat(),
                                }
                            ),
                            application_id,
                            current_user["id"],
                        ),
                    )
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "This job already has an active application — this draft "
                        "stays in the letter's version history.",
                    )
                if cur.fetchone() is not None:
                    submitted_job_id = row[2]
                conn.commit()
    # U-AX instrumentation: ``submitted_job_id`` is set ONLY when the
    # compare-and-swap above genuinely promoted this draft (RETURNING matched),
    # so the loser of a double-submit race records nothing — the transition it
    # would claim never happened.
    if submitted_job_id is not None:
        record_status_event_best_effort(
            application_id, "draft", "submitted", "applications.submit"
        )
        record_submission_snapshot(
            current_user["id"], application_id, submitted_job_id, tailored_resume_id
        )
        # U5d-2 WRITE-TIME TRUTH MARKER. This endpoint records that the USER
        # applied on the company's site themselves; Aether transmitted nothing.
        # Stamping that AT WRITE TIME (rather than leaving a later census to
        # infer it) is what turns "claimed submitted with no proof" from an
        # open question into a self-evident state — after this slice, an
        # UNMARKED claimed-submitted row is a bug, not an ambiguity.
        mark_recorded_not_transmitted(current_user["id"], application_id)
    # Phase 4: advance the parent job to 'applied' so the card flushes from
    # the active board. Guarded forward-only via advance_status — an
    # already-applied job is left untouched (idempotent).
    if submitted_job_id is not None:
        from app.repositories.job import JobRepository

        JobRepository().advance_status(
            submitted_job_id,
            "applied",
            allowed_from={"discovered", "screening", "matched", "tailoring", "ready"},
        )
    return get_application(application_id, current_user)
