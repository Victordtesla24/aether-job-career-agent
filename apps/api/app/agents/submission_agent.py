"""Submission Agent — selects ONE of the caller's own ready applications,
resolves how that posting can actually be applied to, and queues the approval
that a real transmission needs (U5d-2, FORENSICS recommendation **(a)**).

WHY THIS FILE WAS REWIRED (production forensics 2026-08-14,
``uat/reports/evidence/agents-uplift/u5d/FORENSICS.md``).

U5d (slice b) made this agent stop LYING. It did not make it stop being
DISCONNECTED. The forensics proved, by repo-wide grep, that
``apply_channel_resolver`` and ``apply_executor`` — the only code in the
product that can put an application in front of an employer — had exactly one
caller family: the OFF ``apply_sweep`` worker. There was no path at all from
the Agents card to a transmission, and the census agreed: **0 of 606
production applications has ever carried a ``transmittedAt``, and 0 of 556
``application_submit`` approvals has ever been executed.**

WHAT CHANGED HERE
-----------------
1. **Application-scoped, end to end.** ``_READY_TO_APPLY_SQL`` already knew the
   ready draft's identity; U5d stopped it collapsing to a ``jobId`` and this
   slice carries that id through every branch. The job-scoped bookkeeping call
   (``submit_application_for_job``) is GONE — with it goes the newest-row-wins
   reuse branch that produced all three observed false positives.
2. **The channel is really resolved**, by ``apply_channel_resolver`` — the U5
   module this agent could not previously reach — and persisted on the row.
3. **The terminal state is the approval, not a submission.** A correct run
   CANNOT end "submitted": the ApprovalRequest gate is the product's safety
   contract, so this agent's terminal act is a queued W-SUB card and
   ``submissionState = "awaiting_approval"``. The single place a real
   transmission can happen stays ``POST /approvals/{id}/execute``.
4. **No bookkeeping.** This agent no longer promotes anything to ``submitted``.
   Writing "submitted" over a row nothing had transmitted is precisely the 346-
   row falsehood; the user's own tracker control still records what THEY did.

THE INVARIANT THIS FILE ENFORCES
--------------------------------
**A transmission claim requires transmission evidence.** ``transmitted`` is
read back from ``Application."transmittedAt"`` AFTER the work — never derived
from control flow — and there is no field or code path here that can assert a
submission without that column. There is deliberately no ``submitted`` field: a
name that cannot be made true on a path that transmits nothing.

WHAT IS STILL REFUSED, LOUDLY
-----------------------------
The gate the card advertises is unchanged and is the SAME code the Jobs board's
Apply button runs — imported from ``app.routers.jobs``, never reimplemented: a
job-tailored résumé (``_resume_for_apply``), a non-empty Cover Letter Studio
draft (``_cover_letter_for_apply``) and the BLOCKER-002 placeholder-sign-off
guard (``_guard_apply_cover_letter_source``). An unsatisfied gate is the same
honest 422 the button raises, never a silent no-op and never a queued card.

Degradation is honest at every edge (ADR-AG-1):

* an EXPLICIT ``job_id`` that is not the caller's own -> ``LookupError`` ->
  404, never quietly substituted for another job;
* a channel Aether will not drive (ASSISTED by ruling U5-F3, Seek by
  ADR-SEEK-V3, or a destination that would not resolve) -> a persisted,
  actionable manual step carrying the real link — never an approval card that
  implies a submission the product would then refuse to make;
* no ready application at all -> a COMPLETED zero-cost no-op with
  ``submissionState = "none"``.

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
from app.routers.jobs import (
    _cover_letter_for_apply,
    _guard_apply_cover_letter_source,
    _resume_for_apply,
)
from app.services.application_submission import (
    auto_apply_enabled,
    load_agent_config,
    queue_submission_approval,
    resolve_job_apply_recipient,
)
from app.services.apply_channel_resolver import (
    AUTOMATABLE_CHANNELS,
    resolve_and_persist_apply_channel,
)
from app.services.apply_executor import (
    RETRYABLE_MANUAL_REASONS,
    retryable_manual_reason_sql,
)

#: Terminal states a run can honestly report. They are DISTINCT — a caller
#: must never collapse them, because the difference between them is the whole
#: point of U5d.
#:
#: * ``transmitted``          — ``Application."transmittedAt"`` is set. A real
#:   message left the system and ``transmissionRef`` can be checked against
#:   the user's own Sent folder. The ONLY state that claims a submission.
#: * ``awaiting_approval``    — a W-SUB ``application_submit`` ApprovalRequest
#:   is queued. Nothing has been sent; the user's approval is the gate. This
#:   is the honest TERMINAL state of a correct U5d-2 run.
#: * ``manual_step_required`` — the apply engine hit an obstacle it refuses to
#:   fabricate its way past (an ASSISTED platform that needs the user's click,
#:   Seek, a CAPTCHA, an unresolvable destination). Honest, actionable,
#:   persisted — assisted, not automatic.
#: * ``recorded_not_transmitted`` — the tracker holds a record and nothing was
#:   transmitted. Since U5d-2 this agent no longer WRITES that state (it does
#:   no bookkeeping); it is retained because the bookkeeping write paths and
#:   the ``submissionTruthState`` column still speak exactly this vocabulary,
#:   and a consumer that learned the six states must not have one removed
#:   under it.
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

    #: The TRACKER was really promoted to ``submitted`` by this run. Always
    #: ``False`` since U5d-2: this agent performs no bookkeeping at all, on
    #: purpose — writing "submitted" over a row nothing had transmitted is the
    #: exact 346-row falsehood this workstream exists to remove. Kept (rather
    #: than deleted) so the run-record shape every existing consumer parses is
    #: unchanged, and so the field can never quietly start meaning something
    #: weaker than it says.
    recorded: bool = False
    #: Read back from ``Application."transmittedAt"`` AFTER the work. The one
    #: field permitted to claim that something left the system.
    transmitted: bool = False
    #: One of the module-level ``STATE_*`` constants.
    submissionState: str = STATE_NONE
    jobId: str | None = None
    jobTitle: str | None = None
    company: str | None = None
    applicationId: str | None = None
    #: The channel ``apply_channel_resolver`` really resolved for this posting
    #: (``ashby``/``greenhouse``/``lever``/``email``/``seek-manual``/…), or
    #: ``None`` when this run never got as far as resolving one.
    applyChannel: str | None = None
    #: The W-SUB ApprovalRequest this run queued, when it queued one. Present
    #: ONLY alongside ``awaiting_approval`` — the id is checkable, so a state
    #: that names an approval can be audited against the row.
    approvalId: str | None = None
    #: "requested" (an explicit job_id was honoured), "readyToApply" (auto-picked
    #: the caller's own most recent ready application) or "none" (nothing ready).
    jobSelection: str = "none"
    #: The backend's own machine-readable verdict, propagated verbatim rather
    #: than discarded (``assisted_manual_submit``, ``already_recorded``, a
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
#: job — i.e. one that would pass the Apply button's own gate right now. This
#: mirrors the EXACT two conditions ``_cover_letter_for_apply`` /
#: ``_resume_for_apply`` (app/routers/jobs.py) check for that same job — not a
#: second, looser gate, the same gate applied as a pre-filter so auto-selection
#: never lands on an unready application.
#:
#: U5d: it selects ``a."id"`` as well as ``a."jobId"``. Collapsing the answer to
#: a job id was the whole first defect.
#:
#: U5d-2: rows that already carry a recorded manual step sort LAST. A manual
#: step is a real write, so it bumps ``updatedAt``; without this ordering the
#: agent would re-pick the same blocked row on every subsequent run and never
#: reach the caller's other ready drafts. It is a tie-break, not a filter — a
#: blocked row is still selectable when it is the only one, and re-reporting
#: its honest obstacle is the correct answer in that case.
#:
#: Submitted-not-transmitted rows stay eligible: the tracker "Submitted"
#: swimlane is bookkeeping until ``transmittedAt`` is set. Retryable misses
#: (submit control not found, form not ready) sort with unblocked rows so a
#: one-shot SPA race is retried instead of parked forever.
_READY_RETRYABLE_SQL = retryable_manual_reason_sql("a")
_READY_TO_APPLY_SQL = '''
    SELECT a."id", a."jobId"
    FROM "Application" a
    WHERE a."userId" = %s
      AND a."status"::text IN ('draft', 'submitted')
      AND a."transmittedAt" IS NULL
      AND ''' + _READY_RETRYABLE_SQL + '''
      AND NULLIF(BTRIM(a."coverLetter"), '') IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM "Resume" r
          WHERE r."userId" = a."userId" AND r."sourceJobId" = a."jobId"
      )
      {job_clause}
    ORDER BY ''' + _READY_RETRYABLE_SQL + ''' DESC, a."updatedAt" DESC
    LIMIT 1
'''

#: The same statement scoped to one job. Built from the SAME template so the
#: account-wide pick and the per-job pick can never drift into two different
#: definitions of "ready".
_READY_ACCOUNT_SQL = _READY_TO_APPLY_SQL.format(job_clause="")
_READY_FOR_JOB_SQL = _READY_TO_APPLY_SQL.format(job_clause='AND a."jobId" = %s')

#: The transmission facts plus the row's own status, re-read AFTER the work.
#: This SELECT is the single source of every truth claim this agent makes.
_TRANSMISSION_TRUTH_SQL = '''
    SELECT "status"::text AS "status", "transmittedAt", "transmissionRef",
           "transmissionChannel", "manualStepReason", "manualStepDetail",
           "applyChannel"
    FROM "Application"
    WHERE "id" = %s AND "userId" = %s
'''


class SubmissionAgent:
    """Selects ONE of the caller's own ready applications, resolves how that
    posting can actually be applied to, and queues the approval a real
    transmission needs. It transmits nothing itself and claims nothing without
    evidence."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str, job_id: str | None = None) -> SubmissionResult:
        job, application_id, selection = self._resolve_target(user_id, job_id)
        if job is None or application_id is None:
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
        # The database allows exactly ONE active (submitted/screening/interview/
        # offer) application per job — ``Application_user_job_active_key``.
        # Production's target job carried BOTH an untouched ready draft and an
        # already-active row (FORENSICS §2.2). When another row holds the slot,
        # THAT row is the truth about this job: queueing the draft as well would
        # put a SECOND application in front of the same employer.
        blocking = self._active_application_for_job(user_id, job["id"])
        if blocking is not None and blocking != application_id:
            application_id = blocking
        return self._act(user_id, job, application_id, selection)

    # -- the run itself ----------------------------------------------------

    def _act(
        self,
        user_id: str,
        job: dict[str, Any],
        application_id: str,
        selection: str,
    ) -> SubmissionResult:
        """Decide from PERSISTED state, in strict precedence order.

        Order matters and is enforced here, not by callers: transmission
        evidence outranks everything (nothing may talk over a proven send), a
        recorded manual step outranks any new attempt, and an already-recorded
        row is never re-queued. Only a genuine READY DRAFT reaches the gate,
        the channel resolution and the approval.
        """
        truth = self._transmission_truth(user_id, application_id)
        title = job.get("title") or "this role"
        company = job.get("company")
        where = f"{title}{f' at {company}' if company else ''}"
        result = SubmissionResult(
            jobId=job["id"],
            jobTitle=job.get("title"),
            company=company,
            applicationId=application_id,
            jobSelection=selection,
            applyChannel=(truth.get("applyChannel") or None),
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

        manual_reason = truth.get("manualStepReason")
        if manual_reason and str(manual_reason) not in RETRYABLE_MANUAL_REASONS:
            return self._manual_step_result(
                result,
                where,
                str(manual_reason),
                truth.get("manualStepDetail"),
            )

        status = str(truth.get("status") or "")
        if status not in ("draft", "submitted"):
            # Screening / interview / offer / withdrawn: this agent does not
            # re-apply. Draft and submitted-not-transmitted still need a send.
            result.submissionState = STATE_NO_CHANGE
            result.reason = "already_recorded"
            result.nextStep = (
                "Apply on the employer's site if you have not already — Aether "
                "has no evidence this application was ever transmitted."
            )
            result.message = (
                f"No change — {where} was already recorded in your tracker, and "
                "Aether has NOT transmitted it."
            )
            return result

        return self._queue_for_approval(user_id, job, application_id, result, where)

    def _queue_for_approval(
        self,
        user_id: str,
        job: dict[str, Any],
        application_id: str,
        result: SubmissionResult,
        where: str,
    ) -> SubmissionResult:
        """A genuine ready draft: run the gate, resolve the channel, queue.

        The gate is the Jobs board's OWN gate, imported rather than
        reimplemented, so the Agents card can never enforce a looser one than
        the button. It runs BEFORE the channel is persisted, so a refusal
        leaves the row byte-identical.
        """
        job_id = job["id"]
        resume_id = _resume_for_apply(user_id, job_id)
        if resume_id is None:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=(
                    "A tailored resume is required before applying. Tailor "
                    "your resume first."
                ),
            )
        if not _cover_letter_for_apply(user_id, job_id) and not self._row_has_cover_letter(
            user_id, application_id
        ):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=422,
                detail=(
                    "A cover letter is required before applying. Generate one "
                    "in the Cover Letter Studio first."
                ),
            )
        # BLOCKER-002 d2 — the letter about to be queued must not carry a
        # placeholder/test-probe sign-off. Runs before ANY write, so a refusal
        # leaves the application untouched and no approval card created.
        _guard_apply_cover_letter_source(user_id, job_id, application_id)

        # Derive (and cache on the Job row) the address the EMPLOYER published
        # in the posting, before the channel is decided. ``resolve_apply_channel``
        # reads ``Job."applyEmail"`` and gives it precedence over any URL (U5a
        # rule 1); that column is only populated by this call, so skipping it
        # would demote every description-published address to "no automatable
        # channel" and silently retire the W-SUB email path. Owner-scoped,
        # idempotent (it records the negative answer too, so a second run does
        # not re-derive), and it neither sends nor promises anything.
        resolve_job_apply_recipient(user_id, job_id)
        # Read the job's OWN destination columns rather than the
        # ``JobRepository`` projection: ``applyEmail`` is an additive W-SUB
        # column that projection does not carry.
        destination = self._apply_destination(user_id, job_id)
        resolved = resolve_and_persist_apply_channel(
            user_id, application_id, destination
        )
        channel = str(resolved["channel"])
        apply_url = str(
            resolved.get("applyUrl") or destination.get("sourceUrl") or ""
        )
        result.applyChannel = channel

        approval = None
        if channel == "email" or channel in AUTOMATABLE_CHANNELS:
            approval = queue_submission_approval(
                user_id,
                job_id,
                application_id,
                resume_id,
                channel=channel,
                apply_url=apply_url,
            )
        if approval is not None:
            # A W-SUB approval card exists. Nothing has left the system. With
            # auto-apply on, the card is granted here so the apply sweep can
            # open the employer's site; the agent still does not transmit.
            if auto_apply_enabled(load_agent_config(user_id)):
                from app.repositories.approval import ApprovalRepository

                granted = ApprovalRepository().approve(str(approval["id"]), user_id)
                if granted is not None:
                    approval = granted
            result.submissionState = STATE_AWAITING_APPROVAL
            result.approvalId = str(approval["id"])
            result.counts["assisted"] = 1
            result.reason = "awaiting_approval"
            if approval.get("status") == "approved":
                result.nextStep = (
                    "The apply sweep will open the employer's site and submit "
                    "— nothing has been sent yet."
                )
                result.message = (
                    f"Prepared {where} for submission via "
                    f"{channel} — queued and approved for the apply sweep, "
                    "NOT transmitted yet."
                )
            else:
                result.nextStep = (
                    "Approve it in Approvals (or press Submit on the application "
                    "card) to transmit — nothing has been sent yet."
                )
                recipient = (approval.get("payload") or {}).get("recipient") \
                    if isinstance(approval.get("payload"), dict) else None
                result.message = (
                    f"Prepared {where} for submission via "
                    f"{recipient or channel} and queued it for your approval — "
                    "NOT transmitted yet. Approve it to send."
                )
            return result

        # No approval is possible for this channel. Record the honest,
        # actionable obstacle on the row — the SAME reason codes and copy the
        # U5 sweep writes, from the same function, so the two paths can never
        # tell the user different stories about the same posting.
        from app.services.apply_executor import record_manual_step
        from app.workers.apply_sweep import no_channel_reason

        reason, message = no_channel_reason(channel, destination, apply_url)
        record_manual_step(user_id, application_id, reason, message)
        return self._manual_step_result(result, where, reason, message)

    @staticmethod
    def _manual_step_result(
        result: SubmissionResult, where: str, reason: str, detail: Any
    ) -> SubmissionResult:
        result.submissionState = STATE_MANUAL_STEP_REQUIRED
        result.counts["manualStep"] = 1
        result.reason = reason
        result.nextStep = str(detail) if detail else (
            "Finish this application on the employer's site."
        )
        result.message = (
            f"NOT transmitted — {where} needs a manual step "
            f"({reason.replace('_', ' ')}). {result.nextStep}"
        )
        return result

    @staticmethod
    def _transmission_truth(user_id: str, application_id: str) -> dict[str, Any]:
        """Re-read the evidence columns. Empty dict if the row vanished — which
        yields no claim, never an assumed one."""
        from app.db import ensure_application_apply_channel_column

        ensure_application_transmission_columns()
        ensure_application_manual_step_columns()
        ensure_application_apply_channel_column()
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
        whether it is actually READY is enforced honestly (422) in
        :meth:`_queue_for_approval`, never silently skipped here.

        The answer is ALWAYS an application id, never a bare job id (U5d-2).
        For an explicit job the ready draft wins; failing that, the job's most
        recent application is reported AS IT IS (so an already-transmitted or
        already-recorded row states its own real state) rather than a new one
        being invented.
        """
        requested = (job_id or "").strip()
        if requested:
            job = self._jobs.get_by_id(requested, user_id)
            if job is None:
                raise LookupError(f"Job {requested} not found for user")
            application_id = self._ready_draft_for_job(
                user_id, requested
            ) or self._latest_application_for_job(user_id, requested)
            return job, application_id, "requested"
        ready = self._ready_to_apply(user_id)
        if ready is not None:
            job = self._jobs.get_by_id(ready["jobId"], user_id)
            if job is not None:
                return job, ready["id"], "readyToApply"
        return None, None, "none"

    @staticmethod
    def _apply_destination(user_id: str, job_id: str) -> dict[str, Any]:
        """``{"sourceUrl": …, "applyEmail": …, "resolvedApplyUrl": …}`` — the
        columns the channel resolver reads, straight off the owner's own Job
        row.

        ``applyEmail`` is an additive W-SUB column that ``JobRepository``'s
        read projection does not carry, so it must be read here; resolving a
        channel from a projection that always says ``applyEmail = None`` would
        route every email posting into the "no automatable channel" branch.
        ``resolvedApplyUrl`` is the SUB-009 ingest-time Adzuna redirect
        resolution — reading it here is what lets ``resolve_apply_channel``
        give it precedence over a fresh live hop at submission time.
        """
        from app.db import ensure_job_apply_contact_columns, ensure_job_resolved_apply_url_columns

        ensure_job_apply_contact_columns()
        ensure_job_resolved_apply_url_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "sourceUrl", "applyEmail", "resolvedApplyUrl" FROM "Job" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return (
            rows[0]
            if rows
            else {"sourceUrl": None, "applyEmail": None, "resolvedApplyUrl": None}
        )

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
    def _ready_draft_for_job(user_id: str, job_id: str) -> str | None:
        """This job's ready DRAFT — the same gate as :data:`_READY_TO_APPLY_SQL`,
        scoped to one job."""
        ensure_application_manual_step_columns()
        ensure_application_transmission_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_READY_FOR_JOB_SQL, (user_id, job_id))
                rows = rows_to_dicts(cur)
        return str(rows[0]["id"]) if rows else None

    @staticmethod
    def _latest_application_for_job(user_id: str, job_id: str) -> str | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id" FROM "Application" WHERE "userId" = %s '
                    'AND "jobId" = %s ORDER BY "createdAt" DESC LIMIT 1',
                    (user_id, job_id),
                )
                rows = rows_to_dicts(cur)
        return str(rows[0]["id"]) if rows else None

    @staticmethod
    def _row_has_cover_letter(user_id: str, application_id: str) -> bool:
        """True when THIS application already carries a non-empty letter.

        ``_cover_letter_for_apply`` only looks at ``status='draft'`` rows
        (the Jobs Apply button copies from Studio). A submitted-not-
        transmitted card already has the letter on the row being driven.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT 1 FROM "Application" '
                    'WHERE "id" = %s AND "userId" = %s '
                    "AND NULLIF(BTRIM(\"coverLetter\"), '') IS NOT NULL",
                    (application_id, user_id),
                )
                return cur.fetchone() is not None

    @staticmethod
    def _ready_to_apply(user_id: str) -> dict[str, str] | None:
        ensure_application_manual_step_columns()
        ensure_application_transmission_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_READY_ACCOUNT_SQL, (user_id,))
                rows = rows_to_dicts(cur)
        if not rows:
            return None
        return {"id": str(rows[0]["id"]), "jobId": str(rows[0]["jobId"])}
