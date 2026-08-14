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
_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."answers", a."createdAt", a."updatedAt", j."title" AS "jobTitle", '
    'j."company", j."sourceUrl" AS "applyUrl", j."fitScore", '
    'a."transmittedAt", a."transmittedTo", a."transmissionChannel", '
    'a."transmissionRef", j."applyEmail", j."applyEmailSource"'
)


def _with_submission(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the truthful submission block to each application row (W-SUB).

    ``Application.status`` is left EXACTLY as stored — history is never
    rewritten. What is added is the answer to the question the status alone
    cannot answer: did Aether actually transmit this application anywhere?
    For all 86 pre-existing 'submitted' rows the answer is a recorded, honest
    ``transmitted: false``.
    """
    from app.services.application_submission import submission_view

    for row in rows:
        row.update(submission_view(row))
    return rows

router = APIRouter()


@router.get("/funnel/sankey")
def funnel_sankey(current_user: CurrentUser) -> dict[str, Any]:
    """Real-time application-flow sankey computed from live DB counts.

    CUMULATIVE model (MV-application-tracker-006): each node counts
    applications that have reached AT LEAST that stage, mirroring the
    nested-IN stage definitions analytics.funnel() already uses — "applied"
    is the canonical non-draft count from get_application_counts()
    (status <> 'draft', consistent with the funnel's "Applied" and the
    dashboard summary), "screened" is status IN (screening, interview,
    offer), "interviewed" is status IN (interview, offer), and "offers" is
    status = 'offer'. Each stage is therefore always >= the next stage, so
    every dropoff (stage_N - stage_{N+1}) is always >= 0.

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
            applied = get_application_counts(cur, uid)["submitted"]
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
            {"key": "jobs_found", "label": "Jobs Found", "value": jobs_found, "color": "#4F46E5"},
            {"key": "applied", "label": "Applied", "value": applied, "color": "#818CF8"},
            {"key": "screened", "label": "Screened", "value": screened, "color": "#FF6B35"},
            {"key": "interviewed", "label": "Interviewed", "value": interviewed,
             "color": "#F59E0B"},
            {"key": "offers", "label": "Offers", "value": offers, "color": "#34D399"},
        ],
        "dropoffs": [
            {"after": "jobs_found", "count": jobs_found - applied,
             "reason": "below match threshold"},
            {"after": "applied", "count": applied - screened, "reason": "not shortlisted"},
            {"after": "screened", "count": screened - interviewed,
             "reason": "no response / screened out"},
            {"after": "interviewed", "count": interviewed - offers, "reason": "not selected"},
        ],
        "insight": (
            f"{jobs_found} jobs found, {applied} applied. "
            "Track applications through the pipeline to improve conversion."
        ),
    }


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
    # W-SUB: ``_COLUMNS`` now names the additive transmission / apply-address
    # columns, so the lazy DDL MUST run before the statement that reads them
    # (ADR-TR-1 — a path that skipped the equivalent call for ``contentHash``
    # raised UndefinedColumn -> HTTP 500 on first use).
    ensure_application_transmission_columns()
    ensure_job_apply_contact_columns()
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
    ensure_application_transmission_columns()
    ensure_job_apply_contact_columns()
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
