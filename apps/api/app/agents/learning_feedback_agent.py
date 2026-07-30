"""Learning / Feedback Agent — read-only outcomes report (wave-4A, ADR-AG-1).

HONEST SCOPE. Nothing in Aether adapts, retrains or re-weights itself from
application outcomes: there is no feedback loop into the tailoring prompts, the
ATS engine or the matcher. The card copy that promised it "learns from
application outcomes to refine future tailoring" described a system that does not
exist. What ships instead is a READ-ONLY outcomes report the human can act on:

* every application's status, bucketed into advanced / rejected / still-pending;
* the real fit-score spread per outcome bucket;
* the split by whether the résumé submitted was actually TAILORED for that job
  (``Resume.sourceJobId == Application.jobId``) and whether a cover letter was
  attached.

Honesty rails, each enforced below:

* **Association, never causation, never learning.** The report carries an
  explicit caveat and changes no behaviour anywhere.
* **Sample threshold.** Rates are reported ONLY when the whole sample clears
  :data:`MIN_SAMPLE` *and* the specific bucket has at least
  :data:`MIN_DECIDED_PER_BUCKET` decided applications. Below that the raw counts
  are still shown (they are real) but every rate is ``None`` — a 1-of-1
  "100% success rate" is noise dressed as a finding.
* **Pending is not an outcome.** draft / submitted / screening / withdrawn
  applications are counted separately and never scored as wins or losses.
* **Read-only.** One SELECT; the agent writes nothing but its own audit row.

Deterministic and unmetered: no LLM call, so no spend and no plan-quota
reservation (absent from ``_LLM_TIER_BY_BACKEND``).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.db import get_connection, rows_to_dicts

#: Application statuses that represent a real forward outcome.
ADVANCED_STATUSES = frozenset({"interview", "offer"})
#: …a real negative outcome.
REJECTED_STATUSES = frozenset({"rejected"})
#: …and no outcome yet (never scored either way).
PENDING_STATUSES = frozenset({"draft", "submitted", "screening", "withdrawn"})

#: Minimum total applications before any RATE is reported.
MIN_SAMPLE = 8

#: Minimum DECIDED (advanced + rejected) applications in a bucket before that
#: bucket's rate is reported.
MIN_DECIDED_PER_BUCKET = 3

CAVEAT = (
    "Observed association only — this report is read-only and never adapts, "
    "retrains or re-weights anything. Correlation here is not evidence of cause."
)


@dataclass
class OutcomeBucket:
    applications: int = 0
    advanced: int = 0
    rejected: int = 0
    pending: int = 0
    advanceRate: float | None = None


@dataclass
class ScoreSummary:
    scored: int = 0
    mean: float | None = None
    median: float | None = None


@dataclass
class LearningFeedbackReport:
    applications: int = 0
    byStatus: dict[str, int] = field(default_factory=dict)
    outcomes: dict[str, int] = field(
        default_factory=lambda: {"advanced": 0, "rejected": 0, "pending": 0}
    )
    tailored: OutcomeBucket = field(default_factory=OutcomeBucket)
    untailored: OutcomeBucket = field(default_factory=OutcomeBucket)
    coverLetter: dict[str, OutcomeBucket] = field(
        default_factory=lambda: {
            "withLetter": OutcomeBucket(),
            "withoutLetter": OutcomeBucket(),
        }
    )
    fitScoreByOutcome: dict[str, ScoreSummary] = field(
        default_factory=lambda: {
            "advanced": ScoreSummary(),
            "rejected": ScoreSummary(),
            "pending": ScoreSummary(),
        }
    )
    fitScoreDisclosed: int = 0
    insufficientData: bool = True
    minSample: int = MIN_SAMPLE
    minDecidedPerBucket: int = MIN_DECIDED_PER_BUCKET
    caveat: str = CAVEAT
    message: str = ""


_QUERY = """
    SELECT a."status"::text AS status,
           a."jobId"       AS "jobId",
           (a."coverLetter" IS NOT NULL AND a."coverLetter" <> '') AS "hasLetter",
           j."fitScore"    AS "fitScore",
           r."sourceJobId" AS "resumeSourceJobId"
    FROM "Application" a
    JOIN "Job" j ON j."id" = a."jobId"
    LEFT JOIN "Resume" r ON r."id" = a."resumeId"
    WHERE a."userId" = %s
"""


def _summary(values: list[float]) -> ScoreSummary:
    if not values:
        return ScoreSummary()
    return ScoreSummary(
        scored=len(values),
        mean=round(sum(values) / len(values), 1),
        median=float(statistics.median(values)),
    )


def _outcome_of(status: str) -> str:
    if status in ADVANCED_STATUSES:
        return "advanced"
    if status in REJECTED_STATUSES:
        return "rejected"
    return "pending"


class LearningFeedbackAgent:
    """Read-only outcomes report over the caller's own applications."""

    def run(self, user_id: str) -> LearningFeedbackReport:
        rows = self._read(user_id)
        report = LearningFeedbackReport(applications=len(rows))
        if not rows:
            report.message = (
                "No applications yet — there are no outcomes to report, and none "
                "are estimated in their place."
            )
            return report

        scores: dict[str, list[float]] = {"advanced": [], "rejected": [], "pending": []}
        for row in rows:
            status = str(row.get("status") or "")
            outcome = _outcome_of(status)
            report.byStatus[status] = report.byStatus.get(status, 0) + 1
            report.outcomes[outcome] += 1
            if row.get("fitScore") is not None:
                scores[outcome].append(float(row["fitScore"]))
                report.fitScoreDisclosed += 1

            tailored = bool(
                row.get("resumeSourceJobId")
                and row.get("resumeSourceJobId") == row.get("jobId")
            )
            self._tally(report.tailored if tailored else report.untailored, outcome)
            letter_key = "withLetter" if row.get("hasLetter") else "withoutLetter"
            self._tally(report.coverLetter[letter_key], outcome)

        report.fitScoreByOutcome = {k: _summary(v) for k, v in scores.items()}
        report.insufficientData = len(rows) < MIN_SAMPLE
        if not report.insufficientData:
            for bucket in (
                report.tailored,
                report.untailored,
                *report.coverLetter.values(),
            ):
                self._rate(bucket)
        report.message = self._message(report)
        return report

    @staticmethod
    def _read(user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_QUERY, (user_id,))
                return rows_to_dicts(cur)

    @staticmethod
    def _tally(bucket: OutcomeBucket, outcome: str) -> None:
        bucket.applications += 1
        setattr(bucket, outcome, getattr(bucket, outcome) + 1)

    @staticmethod
    def _rate(bucket: OutcomeBucket) -> None:
        decided = bucket.advanced + bucket.rejected
        if decided >= MIN_DECIDED_PER_BUCKET:
            bucket.advanceRate = round(bucket.advanced / decided, 3)

    @staticmethod
    def _message(report: LearningFeedbackReport) -> str:
        head = (
            f"{report.applications} application(s): "
            f"{report.outcomes['advanced']} advanced, "
            f"{report.outcomes['rejected']} rejected, "
            f"{report.outcomes['pending']} still pending."
        )
        if report.insufficientData:
            return (
                f"{head} Not enough data for rates — at least {MIN_SAMPLE} "
                "applications are needed before any rate is reported, so only "
                "the raw counts above are shown."
            )
        withheld = [
            name
            for name, bucket in (
                ("tailored", report.tailored),
                ("untailored", report.untailored),
            )
            if bucket.advanceRate is None
        ]
        if withheld:
            return (
                f"{head} Rates for {', '.join(withheld)} are withheld — fewer "
                f"than {MIN_DECIDED_PER_BUCKET} decided applications in those "
                "groups."
            )
        return head
