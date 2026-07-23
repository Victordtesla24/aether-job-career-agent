"""Applications router — pipeline board, tracker metadata, sankey (P2-S10)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.routers.analytics import get_application_counts

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
            cur.execute(
                '''
                SELECT
                    COUNT(*) FILTER (
                        WHERE "status" IN ('screening','interview','offer')
                    ) AS screened,
                    COUNT(*) FILTER (WHERE "status" IN ('interview','offer')) AS interviewed,
                    COUNT(*) FILTER (WHERE "status" = 'offer') AS offers
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
    current_user: CurrentUser, app_status: str | None = None
) -> list[dict[str, Any]]:
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
    where = " AND ".join(clauses)
    with get_connection() as conn:
        with conn.cursor() as cur:
            # DISTINCT ON collapses letter versions: each draft/refine of a
            # cover letter is its own Application row (the studio's version
            # history), but the tracker must show ONE card per job in the
            # draft column — the newest version. Non-draft rows (real
            # submissions and beyond) are all shown.
            cur.execute(
                f'''
                SELECT * FROM (
                    SELECT DISTINCT ON (a."jobId") {_COLUMNS}
                    FROM "Application" a
                    JOIN "Job" j ON j."id" = a."jobId"
                    WHERE {where} AND a."status" = 'draft'
                    ORDER BY a."jobId", a."createdAt" DESC
                ) drafts
                UNION ALL
                SELECT {_COLUMNS} FROM "Application" a
                JOIN "Job" j ON j."id" = a."jobId"
                WHERE {where} AND a."status" <> 'draft'
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
                'SELECT "status" FROM "Application" WHERE "id" = %s AND "userId" = %s',
                (application_id, uid),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            from_status = row[0]
            if from_status in _CLOSED_STATUSES:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Application is {from_status} (closed) — closed applications "
                    "cannot be moved between pipeline stages.",
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


@router.post("/{application_id}/submit")
def submit_application(
    application_id: str, body: SubmitRequest, current_user: CurrentUser
) -> dict[str, Any]:
    """Mark a draft application as submitted, recording the real apply URL.

    The user applies on the company site themselves (human-in-the-loop);
    this endpoint only tracks that it happened. Idempotent: re-submitting an
    already-submitted application is a no-op that returns the current row.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "answers" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, current_user["id"]),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            if row[0] == "draft":
                cur.execute(
                    """
                    UPDATE "Application"
                    SET "status" = 'submitted'::"ApplicationStatus",
                        "answers" = COALESCE("answers", '{}'::jsonb) || %s::jsonb,
                        "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    """,
                    (
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
                conn.commit()
    return get_application(application_id, current_user)
