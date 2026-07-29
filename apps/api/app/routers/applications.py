"""Applications router — pipeline board, tracker metadata, sankey (P2-S10)."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.routers.analytics import get_application_counts

logger = logging.getLogger(__name__)

router = APIRouter()

#: Valid Application.status values — mirrors the "ApplicationStatus" enum.
_STATUSES = frozenset(
    {"draft", "submitted", "screening", "interview", "offer", "rejected", "withdrawn"}
)

_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."answers", a."createdAt", a."updatedAt", j."title" AS "jobTitle", '
    'j."company", j."sourceUrl" AS "applyUrl", j."fitScore"'
)

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

    By default excludes jobs whose Job.status is 'applied' or 'archived' —
    those are terminal and live in the separate Applied/History views
    (phase4). Pass ``?include_applied=true`` to fetch only those terminal
    jobs.
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
    else:
        clauses.append('j."status" NOT IN (%s::"JobStatus", %s::"JobStatus")')
        params.extend(["applied", "archived"])
    where = " AND ".join(clauses)
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
            return rows_to_dicts(cur)


@router.get("/{application_id}")
def get_application(application_id: str, current_user: CurrentUser) -> dict[str, Any]:
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
    return rows[0]


class SubmitRequest(BaseModel):
    """Payload for marking an application as submitted on the company site."""

    applied_url: str | None = Field(default=None, max_length=2000)


# ---- FEAT-B2: move cards between kanban stages ------------------------------
#
# The board (apps/web tracker-lib.ts) has 8 columns. The FIRST 3 are fed by
# Job.status (discovered / evaluating / tailoring — the agent pipeline half);
# the LAST 5 are fed by Application.status. Moves are therefore two endpoints:
# application cards move between the 5 app-fed stages, job cards between the
# 3 job-fed stages. Crossing the split is rejected with an honest 422 — an
# application's presence is what removes the job card from the pipeline half.

#: stage key → Application.status (the 5 application-fed columns).
_APP_STAGE_TO_STATUS = {
    "ready": "draft",
    "submitted": "submitted",
    "in-review": "screening",
    "interview": "interview",
    "offer": "offer",
}

#: stage key → Job.status (the 3 job-fed columns). "evaluating" renders both
#: 'screening' and 'matched' jobs; 'screening' is the canonical write target.
_JOB_STAGE_TO_STATUS = {
    "discovered": "discovered",
    "evaluating": "screening",
    "tailoring": "tailoring",
}

_ALL_STAGE_KEYS = set(_APP_STAGE_TO_STATUS) | set(_JOB_STAGE_TO_STATUS)

#: Closed applications live in the board's "closed" strip, not a column —
#: they cannot be dragged back into the pipeline via a stage move.
_CLOSED_STATUSES = frozenset({"rejected", "withdrawn"})


class MoveRequest(BaseModel):
    """Target stage for moving a kanban card (FEAT-B2)."""

    to_stage: str = Field(..., max_length=50, description="Target stage key")


def _validate_stage(to_stage: str, mapping: dict[str, str], side: str) -> str:
    """Resolve a stage key to a status, with honest 422s for illegal targets."""
    if to_stage not in _ALL_STAGE_KEYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown stage '{to_stage}'. Valid stages: {sorted(_ALL_STAGE_KEYS)}",
        )
    if to_stage not in mapping:
        other = "Job-status-fed" if side == "application" else "Application-status-fed"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Stage '{to_stage}' is {other} — a {side} card cannot move there. "
            f"Valid targets for a {side} card: {sorted(mapping)}",
        )
    return mapping[to_stage]


@router.post("/pipeline/{job_id}/move")
def move_pipeline_job(
    job_id: str, body: MoveRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Move a pipeline JOB card between the 3 job-fed stages (FEAT-B2).

    422 for app-fed/unknown targets; 409 when the job already has an
    application (it is no longer a pipeline card — move the application
    instead); 404 unknown/foreign job. Audited as ``job.stage_move``.
    """
    uid = current_user["id"]
    new_status = _validate_stage(body.to_stage, _JOB_STAGE_TO_STATUS, "job")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status" FROM "Job" WHERE "id" = %s AND "userId" = %s',
                (job_id, uid),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
            from_status = row[0]
            cur.execute(
                'SELECT 1 FROM "Application" WHERE "jobId" = %s AND "userId" = %s LIMIT 1',
                (job_id, uid),
            )
            if cur.fetchone() is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "This job already has an application — move the application "
                    "card instead.",
                )
            if from_status != new_status:
                cur.execute(
                    'UPDATE "Job" SET "status" = %s::"JobStatus", "updatedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s',
                    (new_status, job_id, uid),
                )
                from app.repositories.admin import write_audit

                write_audit(
                    uid,
                    "job.stage_move",
                    target_type="job",
                    target_id=job_id,
                    detail={
                        "from": from_status,
                        "to": new_status,
                        "to_stage": body.to_stage,
                    },
                    cur=cur,
                )
            conn.commit()
    # RT-008 event-driven trigger: a card moved into evaluating or tailoring
    # is exactly the signal that creates board-sweep work — enqueue a sweep
    # NOW instead of waiting up to 10 minutes for the next cron tick. The
    # cron remains the floor: best-effort, never blocks or surfaces an
    # enqueue failure to the user making the move.
    if from_status != new_status and new_status in ("screening", "tailoring"):
        try:
            from app.workers.board_sweep import enqueue_user_sweep

            enqueue_user_sweep(uid)
        except Exception:  # noqa: BLE001 — best-effort; cron still fires
            logger.exception("job.stage_move %s: sweep trigger failed", job_id)
    return {"id": job_id, "status": new_status, "stage": body.to_stage}


@router.post("/{application_id}/move")
def move_application(
    application_id: str, body: MoveRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Move an APPLICATION card between the 5 application-fed stages (FEAT-B2).

    Legal matrix: any transition between ready/submitted/in-review/interview/
    offer, forward or backward — the user is the source of truth for their own
    pipeline; same-stage is an idempotent no-op. Honest 422s for job-fed or
    unknown targets and for closed (rejected/withdrawn) applications. The
    transition is audited (who/when/from→to) atomically with the update, so
    ``/funnel/sankey`` — computed live from statuses with the cumulative
    model — can never double-count or orphan a moved application.
    """
    uid = current_user["id"]
    new_status = _validate_stage(body.to_stage, _APP_STAGE_TO_STATUS, "application")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "jobId" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, uid),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            from_status, move_job_id = row
            if from_status in _CLOSED_STATUSES:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Application is {from_status} (closed) — closed applications "
                    "cannot be moved between pipeline stages.",
                )
            if from_status == "draft" and new_status != "draft":
                # RT-004 promotion guard: Application rows double as
                # cover-letter versions; promoting a SECOND version of an
                # already-applied job minted a permanent duplicate board card
                # (live evidence: 11 cards for one job). One active
                # application per job.
                cur.execute(
                    'SELECT "id" FROM "Application" WHERE "userId" = %s '
                    'AND "jobId" = %s AND "id" <> %s AND "status" IN '
                    "('submitted','screening','interview','offer') LIMIT 1",
                    (uid, move_job_id, application_id),
                )
                if cur.fetchone() is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        "This job already has an active application — move that "
                        "card instead; this draft stays in the letter's version "
                        "history.",
                    )
            if from_status != new_status:
                cur.execute(
                    'UPDATE "Application" '
                    'SET "status" = %s::"ApplicationStatus", "updatedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s',
                    (new_status, application_id, uid),
                )
                from app.repositories.admin import write_audit

                write_audit(
                    uid,
                    "application.stage_move",
                    target_type="application",
                    target_id=application_id,
                    detail={
                        "from": from_status,
                        "to": new_status,
                        "to_stage": body.to_stage,
                    },
                    cur=cur,
                )
            conn.commit()
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
                      f"%s::\"JobStatus\"" for _ in _PIPELINE_JOB_STATUSES
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
                    f'''
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
                if cur.fetchone() is not None:
                    submitted_job_id = row[2]
                conn.commit()
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
