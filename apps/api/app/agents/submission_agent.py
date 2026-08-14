"""Submission Agent — records a caller's own ready application in their
tracker and reports, truthfully, whether anything was TRANSMITTED (U5d).

WHY THIS FILE WAS REWRITTEN (production forensics 2026-08-14,
``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md``). The previous version
returned ``submitted=True`` unconditionally and the sentence *"Submitted your
application for … at WSP USA."* Three production runs did that while:

* performing **no write at all** — job-scoped, they resolved the job's NEWEST
  application (already ``submitted``), took ``submit_application_for_job``'s
  idempotent reuse branch, and left the READY DRAFT the agent had actually
  selected untouched (its ``updatedAt`` never moved across three runs);
* **discarding** the backend's own honest verdict — that same call returned
  ``submission.reason = "no_published_recipient"`` and the sentence *"this
  application is recorded as prepared, not transmitted"*, which the old
  ``SubmissionResult`` had no field capable of carrying;
* finishing in **0.19–0.61 s**, because nothing was ever transmitted.

The database agrees: 0 of 606 production applications has ever carried a
``transmittedAt``. 346 nonetheless claimed ``status='submitted'``.

THE INVARIANT THIS FILE NOW ENFORCES
------------------------------------
**A transmission claim requires transmission evidence.** ``transmitted`` is
read back from ``Application."transmittedAt"`` AFTER the write — it is never
derived from control flow, and there is no field or code path here that can
assert a submission without that column. The old ``submitted`` flag is gone:
a field with that name cannot be made honest on a path that transmits nothing.

HONEST SCOPE. This agent does the tracker bookkeeping the Jobs board's Apply
button does — the SAME gate and write
(:func:`app.routers.jobs.submit_application_for_job`, imported and called
verbatim, never reimplemented): a job-tailored resume plus a non-empty Cover
Letter Studio draft, then the Application row moves to ``submitted`` and the
job to ``applied``. It transmits nothing itself. Transmission lives behind the
ApprovalRequest gate and the U5 apply engine
(``app.workers.apply_sweep`` / ``app.services.apply_executor``), and this
agent's terminal state says exactly which of those a run reached.

Degradation is honest at every edge, the SAME convention every wave-4B/4C
agent uses (ADR-AG-1):

* an EXPLICIT ``job_id`` that is not the caller's own -> ``LookupError`` ->
  404, never quietly substituted for another job;
* an EXPLICIT ``job_id`` whose gate is not satisfied yet (no job-tailored
  resume / no cover letter draft / a placeholder sign-off in the draft) ->
  the SAME honest 422 ``submit_application_for_job`` already raises for the
  Apply button — never a silent no-op, never a fabricated submission;
* no ``job_id`` at all -> the caller's own most recently updated application
  that ALREADY satisfies both gates is picked, BY ID, and the choice is
  reported back (``jobSelection="readyToApply"``); with none ready, a
  COMPLETED zero-cost no-op with an honest message and ``submissionState
  ="none"`` — never an error, never a fabricated submission.

Deterministic and unmetered: no LLM call is ever made, so this backend is
deliberately ABSENT from ``_LLM_TIER_BY_BACKEND`` (app/routers/agents.py) —
identical to the other real-write / report agents in this family (matcher,
compliance, notification).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.db import (
    APPLICATION_ACTIVE_STATUSES,
    ensure_application_manual_step_columns,
    ensure_application_transmission_columns,
    get_connection,
    rows_to_dicts,
)
from app.repositories.job import JobRepository
from app.routers.jobs import submit_application_for_job

#: Terminal states a run can honestly report. They are DISTINCT — a caller
#: must never collapse them, because the difference between them is the whole
#: point of U5d.
#:
#: * ``transmitted``          — ``Application."transmittedAt"`` is set. A real
#:   message left the system and ``transmissionRef`` can be checked against
#:   the user's own Sent folder. The ONLY state that claims a submission.
#: * ``awaiting_approval``    — a W-SUB ``application_submit`` ApprovalRequest
#:   is queued. Nothing has been sent; the user's approval is the gate.
#: * ``manual_step_required`` — the apply engine hit an obstacle it refuses to
#:   fabricate its way past (CAPTCHA, login wall, an unanswerable required
#:   question). Honest, actionable, persisted — assisted, not automatic.
#: * ``recorded_not_transmitted`` — the tracker was really written and nothing
#:   was transmitted (e.g. the posting publishes no application address).
#: * ``no_change``            — the row was already recorded; this run wrote
#:   nothing. The state the three production false positives were really in.
#: * ``none``                 — nothing was ready; no row was touched.
STATE_TRANSMITTED = "transmitted"
STATE_AWAITING_APPROVAL = "awaiting_approval"
STATE_MANUAL_STEP_REQUIRED = "manual_step_required"
STATE_RECORDED_NOT_TRANSMITTED = "recorded_not_transmitted"
STATE_NO_CHANGE = "no_change"
STATE_NONE = "none"


def _empty_counts() -> dict[str, int]:
    """The four DISTINCT outcomes a run reports, all zero.

    A run is counted in exactly one bucket (or none, when nothing was ready),
    so "transmitted N / assisted M / manual-step K / recorded-only J" on the
    Agents screen is arithmetic over the run record rather than prose.
    """
    return {"transmitted": 0, "assisted": 0, "manualStep": 0, "recordedOnly": 0}


@dataclass
class SubmissionResult:
    """What the run ACTUALLY did — every field backed by persisted state.

    There is deliberately no ``submitted`` field. The old one was set to
    ``True`` on every run regardless of what happened, and no naming or
    docstring could have made it true on a path that transmits nothing.
    """

    #: A REAL write happened (``rowcount``-derived, from
    #: ``submit_application_for_job``'s ``changed`` signal) — never assumed.
    recorded: bool = False
    #: Read back from ``Application."transmittedAt"`` AFTER the call. The one
    #: field permitted to claim that something left the system.
    transmitted: bool = False
    #: One of the module-level ``STATE_*`` constants.
    submissionState: str = STATE_NONE
    jobId: str | None = None
    jobTitle: str | None = None
    company: str | None = None
    applicationId: str | None = None
    #: "requested" (an explicit job_id was honoured), "readyToApply" (auto-picked
    #: the caller's own most recent ready application) or "none" (nothing ready).
    jobSelection: str = "none"
    #: The backend's own machine-readable verdict, propagated verbatim rather
    #: than discarded (``no_published_recipient``, ``already_recorded``, a
    #: manual-step reason, …).
    reason: str | None = None
    #: What the user has to do next for this application to actually reach the
    #: employer. Never a promise the product cannot keep.
    nextStep: str | None = None
    #: Checkable evidence for a positive claim; both NULL unless transmitted.
    transmittedAt: Any = None
    transmissionRef: str | None = None
    #: Four distinct outcomes, counted (see :func:`_empty_counts`).
    counts: dict[str, int] = field(default_factory=_empty_counts)
    message: str = ""


#: The caller's own most recently updated DRAFT application that ALREADY has a
#: non-empty Cover Letter Studio draft AND a job-tailored resume for the same
#: job — i.e. one that would pass ``submit_application_for_job``'s own gate
#: right now. This mirrors the EXACT two conditions
#: ``_cover_letter_for_apply`` / ``_resume_for_apply`` (app/routers/jobs.py)
#: check for that same job — not a second, looser gate, the same gate applied
#: as a pre-filter so auto-selection never lands on an unready application.
#:
#: U5d: it selects ``a."id"`` as well as ``a."jobId"``. Collapsing the answer
#: to a job id was the whole first defect — ``submit_application_for_job`` then
#: re-resolved the job's NEWEST application (an already-submitted row),
#: skipped every gate and wrote nothing, three times in production.
_READY_TO_APPLY_SQL = '''
    SELECT a."id", a."jobId"
    FROM "Application" a
    WHERE a."userId" = %s
      AND a."status" = 'draft'::"ApplicationStatus"
      AND NULLIF(BTRIM(a."coverLetter"), '') IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM "Resume" r
          WHERE r."userId" = a."userId" AND r."sourceJobId" = a."jobId"
      )
    ORDER BY a."updatedAt" DESC
    LIMIT 1
'''

#: The transmission facts, re-read from the row AFTER the write. This SELECT is
#: the single source of every truth claim this agent makes.
_TRANSMISSION_TRUTH_SQL = '''
    SELECT "transmittedAt", "transmissionRef", "transmissionChannel",
           "manualStepReason", "manualStepDetail"
    FROM "Application"
    WHERE "id" = %s AND "userId" = %s
'''


class SubmissionAgent:
    """Records ONE of the caller's own ready applications and reports, from
    persisted state, whether anything was transmitted. No browser automation,
    no invented capability, no claim without evidence."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str, job_id: str | None = None) -> SubmissionResult:
        job, application_id, selection = self._resolve_target(user_id, job_id)
        if job is None:
            return SubmissionResult(
                submissionState=STATE_NONE,
                jobSelection="none",
                reason="nothing_ready",
                nextStep=(
                    "Tailor a resume and generate a cover letter for a job, "
                    "then run this agent again."
                ),
                message=(
                    "No application is ready to submit yet — tailor a resume "
                    "and generate a cover letter for a job first (or submit a "
                    "specific job_id), then run this agent again."
                ),
            )
        if application_id is not None:
            # The database allows exactly ONE active (submitted/screening/
            # interview/offer) application per job — ``Application_user_job_
            # active_key``. Production's target job carried BOTH an untouched
            # ready draft and an already-active row, so promoting the draft is
            # not merely redundant, it is impossible. Report the active row's
            # REAL state instead of attempting a write that the constraint
            # would reject, and without inventing a submission for either row.
            blocking = self._active_application_for_job(user_id, job["id"])
            if blocking is not None and blocking != application_id:
                return self._describe(
                    user_id,
                    job,
                    selection,
                    {
                        "applicationId": blocking,
                        "submission": {"queued": False, "reason": "already_recorded"},
                        "changed": False,
                        "alreadySubmitted": True,
                    },
                )
        outcome = submit_application_for_job(
            user_id, job["id"], application_id=application_id
        )
        return self._describe(user_id, job, selection, outcome)

    # -- truth assembly ---------------------------------------------------

    def _describe(
        self,
        user_id: str,
        job: dict[str, Any],
        selection: str,
        outcome: dict[str, Any],
    ) -> SubmissionResult:
        """Build the result from PERSISTED state only.

        Order matters: the transmission columns are re-read from the row after
        the write, and ``transmitted`` is decided by that read alone. No branch
        below can set ``transmitted=True`` without ``transmittedAt``.
        """
        application_id = str(outcome["applicationId"])
        truth = self._transmission_truth(user_id, application_id)
        submission = outcome.get("submission") or {}
        title = job.get("title") or "this role"
        company = job.get("company")
        where = f"{title}{f' at {company}' if company else ''}"

        result = SubmissionResult(
            recorded=bool(outcome.get("changed")),
            jobId=job["id"],
            jobTitle=job.get("title"),
            company=company,
            applicationId=application_id,
            jobSelection=selection,
            transmittedAt=truth.get("transmittedAt"),
            transmissionRef=truth.get("transmissionRef"),
        )

        if truth.get("transmittedAt") is not None:
            # The ONLY branch that may claim a submission, and it claims it
            # because the row proves it.
            result.transmitted = True
            result.submissionState = STATE_TRANSMITTED
            result.counts["transmitted"] = 1
            result.reason = "transmitted"
            result.nextStep = "Nothing — watch for the employer's reply."
            ref = truth.get("transmissionRef")
            result.message = (
                f"Transmitted your application for {where}"
                f"{f' (reference {ref})' if ref else ''}."
            )
            return result

        if truth.get("manualStepReason"):
            reason = str(truth["manualStepReason"])
            detail = truth.get("manualStepDetail")
            result.submissionState = STATE_MANUAL_STEP_REQUIRED
            result.counts["manualStep"] = 1
            result.reason = reason
            result.nextStep = str(detail) if detail else (
                "Finish this application on the employer's site."
            )
            result.message = (
                f"NOT transmitted — {where} needs a manual step "
                f"({reason.replace('_', ' ')}). "
                f"{result.nextStep}"
            )
            return result

        if submission.get("queued"):
            # A W-SUB approval card exists. Nothing has left the system, and
            # nothing will until the user approves it.
            result.submissionState = STATE_AWAITING_APPROVAL
            result.counts["assisted"] = 1
            result.reason = "awaiting_approval"
            result.nextStep = (
                "Approve it in Approvals to transmit — nothing has been sent yet."
            )
            recipient = submission.get("recipient")
            result.message = (
                f"Recorded {where} in your tracker and queued it for sending"
                f"{f' to {recipient}' if recipient else ''} — NOT transmitted yet. "
                "Approve it in Approvals to send."
            )
            return result

        if outcome.get("alreadySubmitted") or not result.recorded:
            # The exact state the three production runs were really in.
            # Counted in NO bucket on purpose: a run that changed nothing is
            # not a "recorded-only" run, and conflating the two is how a
            # dashboard starts reporting work that never happened.
            result.submissionState = STATE_NO_CHANGE
            result.reason = str(submission.get("reason") or "already_recorded")
            result.nextStep = (
                "Apply on the employer's site if you have not already — Aether "
                "has no evidence this application was ever transmitted."
            )
            result.message = (
                f"No change — {where} was already recorded in your tracker, and "
                "Aether has NOT transmitted it."
            )
            return result

        result.submissionState = STATE_RECORDED_NOT_TRANSMITTED
        result.counts["recordedOnly"] = 1
        result.reason = str(submission.get("reason") or "no_published_recipient")
        result.nextStep = (
            "Apply on the employer's site — this posting publishes no "
            "application address Aether can send to."
        )
        result.message = (
            f"Recorded {where} in your tracker as applied — NOT transmitted. "
            f"{result.nextStep}"
        )
        return result

    @staticmethod
    def _transmission_truth(user_id: str, application_id: str) -> dict[str, Any]:
        """Re-read the evidence columns. Empty dict if the row vanished — which
        yields no claim, never an assumed one."""
        ensure_application_transmission_columns()
        ensure_application_manual_step_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_TRANSMISSION_TRUTH_SQL, (application_id, user_id))
                rows = rows_to_dicts(cur)
        return rows[0] if rows else {}

    # -- target resolution ------------------------------------------------

    def _resolve_target(
        self, user_id: str, job_id: str | None
    ) -> tuple[dict[str, Any] | None, str | None, str]:
        """``(job, application_id, selection)``.

        An EXPLICIT id that is not the caller's own is a caller error
        (``LookupError`` -> 404), never quietly replaced by another job;
        whether it is actually READY is enforced honestly (422) by
        ``submit_application_for_job`` itself, not silently skipped here.

        With no id at all, the caller's own most recent already-ready
        application is carried BY ID into the write, so the write cannot land
        on a different row than the one this agent selected (U5d).
        """
        requested = (job_id or "").strip()
        if requested:
            job = self._jobs.get_by_id(requested, user_id)
            if job is None:
                raise LookupError(f"Job {requested} not found for user")
            return job, None, "requested"
        ready = self._ready_to_apply(user_id)
        if ready is not None:
            job = self._jobs.get_by_id(ready["jobId"], user_id)
            if job is not None:
                return job, ready["id"], "readyToApply"
        return None, None, "none"

    @staticmethod
    def _active_application_for_job(user_id: str, job_id: str) -> str | None:
        """The job's existing ACTIVE application, if any — the row the unique
        partial index (``APPLICATION_ACTIVE_STATUSES``) already reserves the
        slot for. Newest first, mirroring the index's own notion of active so
        the two can never disagree."""
        placeholders = ",".join(["%s"] * len(APPLICATION_ACTIVE_STATUSES))
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT "id" FROM "Application" '
                    f'WHERE "userId" = %s AND "jobId" = %s '
                    f'AND "status"::text IN ({placeholders}) '
                    f'ORDER BY "createdAt" DESC LIMIT 1',
                    (user_id, job_id, *APPLICATION_ACTIVE_STATUSES),
                )
                rows = rows_to_dicts(cur)
        return str(rows[0]["id"]) if rows else None

    @staticmethod
    def _ready_to_apply(user_id: str) -> dict[str, str] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_READY_TO_APPLY_SQL, (user_id,))
                rows = rows_to_dicts(cur)
        if not rows:
            return None
        return {"id": str(rows[0]["id"]), "jobId": str(rows[0]["jobId"])}
