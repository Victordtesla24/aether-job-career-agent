"""Shared kanban stage-transition service (GOLD-MASTER-V2 §8.1, GOV-003).

ONE implementation of the board's stage-move rules, shared by every transport
that moves a card:

* ``PATCH /applications/{application_id}/stage`` — the CANONICAL contract
  (§8.1); takes ``{from_stage, to_stage}``.
* ``POST /applications/{application_id}/move`` — legacy application-card move
  (FEAT-B2); live callers (``apps/web`` tracker-api ``moveApplication``) keep
  their existing ``{to_stage}``-only payload and identical responses.
* ``POST /applications/pipeline/{job_id}/move`` — legacy job-card move
  (FEAT-B2).

§13.1 forbids a second independent implementation of these rules, so the
validation matrix, the RT-004 one-active-application-per-job guard, the
UniqueViolation→409 mapping and the audit write all live HERE and the routers
are thin adapters. Behaviour of the two legacy routes is unchanged — the code
below is the code that used to live inline in ``app.routers.applications``.

Board shape (apps/web ``components/applications/tracker-lib.ts``): 8 columns.
The first 3 are fed by ``Job.status`` (discovered / evaluating / tailoring —
the agent-pipeline half); the last 5 are fed by ``Application.status``
(ready / submitted / in-review / interview / offer). Crossing the split is an
honest 422 — an application's very existence is what removes the job card from
the pipeline half.

Legal matrix for application cards: ANY transition between the 5 app-fed
stages, forward or backward — the user is the source of truth for their own
pipeline — and same-stage is an idempotent no-op. Closed applications
(rejected / withdrawn) live in the board's closed strip and cannot move at all.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

import psycopg2
from fastapi import HTTPException, status

from app.db import ensure_application_unique_active_index, get_connection
from app.repositories.application_status_event import record_status_event_best_effort
from app.services.submission_snapshot import record_submission_snapshot

logger = logging.getLogger(__name__)

#: A request's unit-of-work source. The CALLER owns the transaction boundary
#: for the request it is serving, so every entry point below takes the factory
#: instead of reaching for a module-global of its own: whatever connection
#: source the calling router is using for the rest of that request (its
#: listing/detail reads included) is the one this service's guard SELECT,
#: UPDATE and audit INSERT run on too — one seam per request, never two.
ConnectionFactory = Callable[[], AbstractContextManager[Any]]

#: stage key → ``Application.status`` (the 5 application-fed columns).
APP_STAGE_TO_STATUS: dict[str, str] = {
    "ready": "draft",
    "submitted": "submitted",
    "in-review": "screening",
    "interview": "interview",
    "offer": "offer",
}

#: stage key → ``Job.status`` (the 3 job-fed columns). "evaluating" renders
#: both 'screening' and 'matched' jobs; 'screening' is the canonical write
#: target.
JOB_STAGE_TO_STATUS: dict[str, str] = {
    "discovered": "discovered",
    "evaluating": "screening",
    "tailoring": "tailoring",
}

ALL_STAGE_KEYS = frozenset(APP_STAGE_TO_STATUS) | frozenset(JOB_STAGE_TO_STATUS)

#: ``Application.status`` → stage key, for naming the server's real stage back
#: to a client whose ``from_stage`` premise was stale.
STATUS_TO_APP_STAGE: dict[str, str] = {
    app_status: stage for stage, app_status in APP_STAGE_TO_STATUS.items()
}

#: Closed applications live in the board's "closed" strip, not a column — they
#: cannot be dragged back into the pipeline via a stage move.
CLOSED_STATUSES = frozenset({"rejected", "withdrawn"})

#: The single RT-004 duplicate-active-application message, returned identically
#: whether the check-then-act guard or the partial unique index caught it.
_DUPLICATE_ACTIVE_DETAIL = (
    "This job already has an active application — move that card instead; "
    "this draft stays in the letter's version history."
)


@dataclass(frozen=True)
class ApplicationMove:
    """Outcome of an application-card stage transition."""

    application_id: str
    job_id: str
    from_status: str
    to_status: str
    to_stage: str
    changed: bool


@dataclass(frozen=True)
class JobMove:
    """Outcome of a pipeline job-card stage transition."""

    job_id: str
    from_status: str
    to_status: str
    to_stage: str
    changed: bool


def validate_stage(stage: str, mapping: dict[str, str], side: str) -> str:
    """Resolve a stage key to a status, with honest 422s for illegal targets."""
    if stage not in ALL_STAGE_KEYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown stage '{stage}'. Valid stages: {sorted(ALL_STAGE_KEYS)}",
        )
    if stage not in mapping:
        other = "Job-status-fed" if side == "application" else "Application-status-fed"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Stage '{stage}' is {other} — a {side} card cannot move there. "
            f"Valid targets for a {side} card: {sorted(mapping)}",
        )
    return mapping[stage]


def move_application_stage(
    *,
    user_id: str,
    application_id: str,
    to_stage: str,
    from_stage: str | None = None,
    connection_factory: ConnectionFactory = get_connection,
) -> ApplicationMove:
    """Move an application card between the 5 application-fed stages.

    ``from_stage`` is the caller's belief about where the card currently sits
    (the canonical §8.1 contract sends it; the legacy ``POST .../move`` payload
    has no such field and passes ``None``). When supplied it is enforced, not
    decorated: a stale board that asks to move a card out of a stage it has
    already left gets a 409 naming the server's real stage, never a silent
    overwrite of whatever actually happened in between.

    Raises ``HTTPException`` — 422 (unknown/job-fed stage, closed application),
    404 (unknown or another user's application), 409 (stale ``from_stage``, or
    the RT-004 one-active-application-per-job invariant).
    """
    new_status = validate_stage(to_stage, APP_STAGE_TO_STATUS, "application")
    expected_status = (
        validate_stage(from_stage, APP_STAGE_TO_STATUS, "application")
        if from_stage is not None
        else None
    )
    ensure_application_unique_active_index()
    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "jobId" FROM "Application" '
                'WHERE "id" = %s AND "userId" = %s',
                (application_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                # Owner-scoped: another user's application is indistinguishable
                # from a missing one, and uses the same detail string every
                # other application endpoint returns (get_application).
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
            from_status, job_id = row
            if from_status in CLOSED_STATUSES:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Application is {from_status} (closed) — closed applications "
                    "cannot be moved between pipeline stages.",
                )
            if expected_status is not None and expected_status != from_status:
                actual_stage = STATUS_TO_APP_STAGE.get(from_status, from_status)
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Stage conflict — this application is in '{actual_stage}', "
                    f"not '{from_stage}'. Reload the board and move it again.",
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
                    (user_id, job_id, application_id),
                )
                if cur.fetchone() is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, _DUPLICATE_ACTIVE_DETAIL
                    )
            changed = from_status != new_status
            if changed:
                # NTH-R10 (wave35-sonnet-review-verdict.json): the guard just
                # above is check-then-act -- a concurrent promotion of a
                # DIFFERENT draft for the SAME job can commit between this
                # request's SELECT and its own UPDATE below, so the guard
                # alone cannot stop a cross-row duplicate. The partial unique
                # index (ensure_application_unique_active_index) is the real
                # backstop; map its violation to the IDENTICAL 409 the guard
                # above returns, so the client contract is unchanged whether
                # the race is caught here or up there.
                try:
                    cur.execute(
                        'UPDATE "Application" '
                        'SET "status" = %s::"ApplicationStatus", "updatedAt" = NOW() '
                        'WHERE "id" = %s AND "userId" = %s',
                        (new_status, application_id, user_id),
                    )
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, _DUPLICATE_ACTIVE_DETAIL
                    )
                from app.repositories.admin import write_audit

                # Audited atomically with the update (same cursor/transaction):
                # actor = the calling user, from/to = the real statuses, plus
                # the stage key the caller used; "createdAt" is the audit row's
                # own DB-side timestamp.
                write_audit(
                    user_id,
                    "application.stage_move",
                    target_type="application",
                    target_id=application_id,
                    detail={
                        "from": from_status,
                        "to": new_status,
                        "to_stage": to_stage,
                        **({"from_stage": from_stage} if from_stage is not None else {}),
                    },
                    cur=cur,
                )
            conn.commit()
    if changed:
        # U-AX instrumentation: the kanban move is a REAL status transition —
        # this is the ONLY path by which an application ever reaches
        # 'interview' or 'offer' today, so without it the conversion metric the
        # rigor policy consumes would have no history at all. Recorded after
        # the commit (its own connection) and guarded on ``changed`` so a
        # same-stage drop writes nothing.
        record_status_event_best_effort(
            application_id, from_status, new_status, "stage_transitions.move"
        )
        if from_status == "draft" and new_status != "draft" and job_id:
            # Leaving draft via the board IS a submission — snapshot it with
            # the same facts the Apply button records.
            record_submission_snapshot(user_id, application_id, str(job_id), None)
    return ApplicationMove(
        application_id=application_id,
        job_id=job_id,
        from_status=from_status,
        to_status=new_status,
        to_stage=to_stage,
        changed=changed,
    )


def move_job_stage(
    *,
    user_id: str,
    job_id: str,
    to_stage: str,
    connection_factory: ConnectionFactory = get_connection,
) -> JobMove:
    """Move a pipeline JOB card between the 3 job-fed stages.

    Raises ``HTTPException`` — 422 (unknown/app-fed stage), 404 (unknown or
    another user's job), 409 (the job already has an application, so it is no
    longer a pipeline card).
    """
    new_status = validate_stage(to_stage, JOB_STAGE_TO_STATUS, "job")
    with connection_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status" FROM "Job" WHERE "id" = %s AND "userId" = %s',
                (job_id, user_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
            from_status = row[0]
            cur.execute(
                'SELECT 1 FROM "Application" WHERE "jobId" = %s AND "userId" = %s LIMIT 1',
                (job_id, user_id),
            )
            if cur.fetchone() is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "This job already has an application — move the application "
                    "card instead.",
                )
            changed = from_status != new_status
            if changed:
                cur.execute(
                    'UPDATE "Job" SET "status" = %s::"JobStatus", "updatedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s',
                    (new_status, job_id, user_id),
                )
                from app.repositories.admin import write_audit

                write_audit(
                    user_id,
                    "job.stage_move",
                    target_type="job",
                    target_id=job_id,
                    detail={
                        "from": from_status,
                        "to": new_status,
                        "to_stage": to_stage,
                    },
                    cur=cur,
                )
            conn.commit()
    # RT-008 event-driven trigger: a card moved into evaluating or tailoring is
    # exactly the signal that creates board-sweep work — enqueue a sweep NOW
    # instead of waiting up to 10 minutes for the next cron tick. The cron
    # remains the floor: best-effort, never blocks or surfaces an enqueue
    # failure to the user making the move.
    if changed and new_status in ("screening", "tailoring"):
        try:
            from app.workers.board_sweep import enqueue_user_sweep

            enqueue_user_sweep(user_id)
        except Exception:  # noqa: BLE001 — best-effort; cron still fires
            logger.exception("job.stage_move %s: sweep trigger failed", job_id)
    return JobMove(
        job_id=job_id,
        from_status=from_status,
        to_status=new_status,
        to_stage=to_stage,
        changed=changed,
    )
