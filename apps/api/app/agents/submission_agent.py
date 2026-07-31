"""Submission Agent — genuinely submits a caller's own ready application
(GM2-AGENTS-001).

HONEST SCOPE. The catalog card's original tip promised "reliable form-filling
and browser automation reasoning" for GPT-4o — no browser-automation or
third-party form-filling integration exists anywhere in this product, and this
agent invents none. What it DOES do is real: it is the EXACT same submission
gate and write ``POST /jobs/{job_id}/apply`` already performs
(:func:`app.routers.jobs.submit_application_for_job`, imported and called
verbatim, never reimplemented) — requiring a job-tailored resume and a
non-empty Cover Letter Studio draft before creating/promoting the Application
to ``submitted`` and advancing the job to ``applied`` — now also runnable from
the Agents screen, not only from the Jobs board's Apply button.

Degradation is honest at every edge, the SAME convention every wave-4B/4C
agent uses (ADR-AG-1):

* an EXPLICIT ``job_id`` that is not the caller's own -> ``LookupError`` ->
  404, never quietly substituted for another job;
* an EXPLICIT ``job_id`` whose gate is not satisfied yet (no job-tailored
  resume / no cover letter draft) -> the SAME honest 422
  ``submit_application_for_job`` already raises for the Apply button — never a
  silent no-op, never a fabricated submission;
* no ``job_id`` at all -> the caller's own most recently updated application
  that ALREADY satisfies both gates is picked and the choice is reported back
  (``jobSelection="readyToApply"``, the wave-4A/4B/4C convention); with none
  ready, a COMPLETED zero-cost no-op with an honest message — never an error,
  never a fabricated submission.

Deterministic and unmetered: no LLM call is ever made, so this backend is
deliberately ABSENT from ``_LLM_TIER_BY_BACKEND`` (app/routers/agents.py) —
identical to the other real-write / report agents in this family (matcher,
compliance, notification).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db import get_connection, rows_to_dicts
from app.repositories.job import JobRepository
from app.routers.jobs import submit_application_for_job


@dataclass
class SubmissionResult:
    submitted: bool = False
    jobId: str | None = None
    jobTitle: str | None = None
    company: str | None = None
    applicationId: str | None = None
    #: "requested" (an explicit job_id was honoured), "readyToApply" (auto-picked
    #: the caller's own most recent ready application) or "none" (nothing ready).
    jobSelection: str = "none"
    message: str = ""


#: The caller's own most recently updated DRAFT application that ALREADY has a
#: non-empty Cover Letter Studio draft AND a job-tailored resume for the same
#: job — i.e. one that would pass ``submit_application_for_job``'s own gate
#: right now. This mirrors the EXACT two conditions
#: ``_cover_letter_for_apply`` / ``_resume_for_apply`` (app/routers/jobs.py)
#: check for that same job — not a second, looser gate, the same gate applied
#: as a pre-filter so auto-selection never lands on an unready application.
_READY_TO_APPLY_SQL = '''
    SELECT a."jobId"
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


class SubmissionAgent:
    """Submits ONE of the caller's own ready applications — a real write over
    real data, no browser automation, no invented capability."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str, job_id: str | None = None) -> SubmissionResult:
        job, selection = self._resolve_job(user_id, job_id)
        if job is None:
            return SubmissionResult(
                jobSelection="none",
                message=(
                    "No application is ready to submit yet — tailor a resume "
                    "and generate a cover letter for a job first (or submit a "
                    "specific job_id), then run this agent again."
                ),
            )
        outcome = submit_application_for_job(user_id, job["id"])
        title = job.get("title") or "this role"
        company = job.get("company")
        return SubmissionResult(
            submitted=True,
            jobId=job["id"],
            jobTitle=job.get("title"),
            company=company,
            applicationId=outcome.get("applicationId"),
            jobSelection=selection,
            message=(
                f"Submitted your application for {title}"
                f"{f' at {company}' if company else ''}."
            ),
        )

    # -- job resolution --------------------------------------------------

    def _resolve_job(
        self, user_id: str, job_id: str | None
    ) -> tuple[dict[str, Any] | None, str]:
        """``(job, selection)``. An EXPLICIT id that is not the caller's own is
        a caller error (``LookupError`` -> 404), never quietly replaced by
        another job; whether it is actually READY to submit is enforced
        honestly (422) by ``submit_application_for_job`` itself, not silently
        skipped here. With no id at all, the caller's own most recent
        already-ready application's job is used."""
        requested = (job_id or "").strip()
        if requested:
            job = self._jobs.get_by_id(requested, user_id)
            if job is None:
                raise LookupError(f"Job {requested} not found for user")
            return job, "requested"
        ready_job_id = self._ready_to_apply_job_id(user_id)
        if ready_job_id:
            job = self._jobs.get_by_id(ready_job_id, user_id)
            if job is not None:
                return job, "readyToApply"
        return None, "none"

    @staticmethod
    def _ready_to_apply_job_id(user_id: str) -> str | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_READY_TO_APPLY_SQL, (user_id,))
                rows = rows_to_dicts(cur)
        return str(rows[0]["jobId"]) if rows else None
