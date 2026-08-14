"""Submit-time snapshots — freezing what was ACTUALLY submitted.

U-AX instrumentation item 1 + build spec item 3 (before/after honesty) and
item 5 ("applications under each policy tier"). Every path that promotes an
``Application`` out of ``draft`` calls :func:`record_submission_snapshot`, so
the columns added by ``db.ensure_application_submission_snapshot_columns``
describe the moment of submission rather than whatever the job/résumé happen to
look like when someone later opens a chart.

Two honesty rules govern this module:

* **Never overwrite a recorded snapshot.** The writes are all
  ``WHERE "<column>" IS NULL`` — a re-submit, a retried approval or a later
  stage move can never rewrite the facts of the original send.
* **Never invent a missing measurement.** Anything that cannot be measured
  (no ATS score on the job, the fit engine unavailable) is simply left NULL.
  A NULL reads as "not measured"; a zero would read as "measured, and bad".

The whole call is best-effort: a failure to record analytics must never refuse
a user's submission, so failures are logged at warning level (visible to an
operator) and the submission proceeds.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db import ensure_application_submission_snapshot_columns, get_connection

logger = logging.getLogger(__name__)

#: Fit-radar label -> the camelCase key used everywhere downstream
#: (``services/quality_policy.DIMENSION_KEYS``). Derived from
#: ``routers/jobs.py::_build_insights``'s ``dimensions[]`` labels; an unmapped
#: label is DROPPED rather than guessed into a key, so a future renamed
#: dimension shows up as a missing dimension (honest) instead of a silently
#: mis-attributed score.
_DIMENSION_KEY_BY_LABEL: dict[str, str] = {
    "Technical Skills": "technicalSkills",
    "Experience Level": "experienceLevel",
    "Industry Match": "industryMatch",
    "Role Alignment": "roleAlignment",
    "Culture Fit": "cultureFit",
    "Salary Fit": "salaryFit",
    "Location Match": "locationMatch",
    "Career Growth": "careerGrowth",
    "Company Stability": "companyStability",
    "North Star Align": "northStarAlign",
}


def measure_dimension_snapshot(user_id: str, job_id: str) -> dict[str, Any] | None:
    """The 10-dimension fit radar for this (user, job), or ``None``.

    Reuses ``routers/jobs.py::_build_insights`` verbatim — the SAME
    deterministic engine the Job Discovery panel renders — so the number stored
    against a submission is the number the user was shown, never a parallel
    re-implementation that could drift.

    DEGRADED dimensions are EXCLUDED. ``_build_insights`` flags a dimension
    ``degraded: True`` when it is wholly or partly the neutral
    ``_DEGRADED_SEMANTIC_SCORE`` placeholder rather than a measurement
    (GMV4-ats-002); storing one would let a placeholder trip — or, worse,
    silently satisfy — the >80% floor check. The excluded labels are recorded
    under ``_meta.degradedExcluded`` so the omission is visible rather than
    mysterious.
    """
    from app.repositories.job import JobRepository
    from app.routers.jobs import _build_insights

    job = JobRepository().get_by_id(job_id, user_id)
    if job is None:
        return None
    insights = _build_insights(job, user_id)
    dimensions = insights.get("dimensions") or []
    scores: dict[str, Any] = {}
    degraded: list[str] = []
    for entry in dimensions:
        label = str(entry.get("label") or "")
        key = _DIMENSION_KEY_BY_LABEL.get(label)
        if key is None:
            continue
        if entry.get("degraded"):
            degraded.append(label)
            continue
        score = entry.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            scores[key] = float(score)
    if not scores:
        return None
    scores["_meta"] = {
        "degradedExcluded": degraded,
        "measuredAgainst": "base résumé vs job description (fit radar engine)",
    }
    return scores


def record_submission_snapshot(
    user_id: str,
    application_id: str,
    job_id: str,
    resume_id: str | None,
    *,
    policy_tier: str | None = None,
) -> None:
    """Freeze the submit-time facts for ``application_id``. Best-effort.

    ``policy_tier`` may be supplied by a caller that already resolved the
    policy for this action (avoiding a second identical computation); when
    omitted it is resolved here so no submission path can silently skip the
    cohort label.
    """
    try:
        ensure_application_submission_snapshot_columns()
        ats_score: float | None = None
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "atsScore" FROM "Job" WHERE "id" = %s AND "userId" = %s',
                    (job_id, user_id),
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    ats_score = float(row[0])
                if resume_id is None:
                    # The résumé the application itself carries IS the version
                    # being submitted — read it rather than leaving the
                    # snapshot blank on paths that do not re-resolve it.
                    cur.execute(
                        'SELECT "resumeId" FROM "Application" WHERE "id" = %s'
                        ' AND "userId" = %s',
                        (application_id, user_id),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        resume_id = str(row[0])

        if policy_tier is None:
            from app.services.quality_policy import resolve_policy_for_user

            policy_tier = str(resolve_policy_for_user(user_id).get("tier") or "") or None

        dimensions = measure_dimension_snapshot(user_id, job_id)

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Every assignment is NULL-guarded: first write wins, so the
                # original send's facts are immutable.
                cur.execute(
                    '''
                    UPDATE "Application" SET
                        "atsScoreAtSubmission" =
                            COALESCE("atsScoreAtSubmission", %s),
                        "tailoredResumeVersionId" =
                            COALESCE("tailoredResumeVersionId", %s),
                        "dimensionScoresAtSubmission" =
                            COALESCE("dimensionScoresAtSubmission", %s::jsonb),
                        "policyTierAtSubmission" =
                            COALESCE("policyTierAtSubmission", %s)
                    WHERE "id" = %s AND "userId" = %s
                    ''',
                    (
                        ats_score,
                        resume_id,
                        json.dumps(dimensions) if dimensions else None,
                        policy_tier,
                        application_id,
                        user_id,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — instrumentation never blocks a send
        logger.warning(
            "submission snapshot failed for application %s (job %s): %s",
            application_id, job_id, exc,
        )
