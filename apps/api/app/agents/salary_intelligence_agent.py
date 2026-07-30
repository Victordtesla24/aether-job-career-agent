"""Salary Intelligence Agent — own-corpus salary aggregation (wave-4A, ADR-AG-1).

HONEST SCOPE. Aether has no salary-benchmark data source. The only pay data it
holds is whatever each discovered posting DISCLOSED (``Job.salaryMin`` /
``salaryMax`` / ``currency``, populated by the discovery adapters). This agent
aggregates exactly that, grouped by role family / location / currency, and always
reports how many postings disclosed anything at all ("N of M disclosed").

Three hard rules, each enforced below:

* **Never impute.** A posting that discloses only a maximum contributes to the
  maximum statistics and leaves the minimum statistics genuinely empty. A missing
  bound is never derived from the other bound, from a sibling posting, or from a
  market average.
* **Never merge currencies.** Currency is part of the group key, so an AUD range
  and a USD range are never averaged together. An undisclosed currency is
  labelled ``unspecified`` rather than assumed to be the user's local currency.
* **Never guess a role family.** A title that matches none of the known family
  terms is grouped as ``unclassified`` with its real titles listed.

Deterministic and unmetered: no LLM call, so no spend and no plan-quota
reservation (absent from ``_LLM_TIER_BY_BACKEND``).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.repositories.job import JobRepository
from app.services.discovery.query_builder import ROLE_FAMILY_TERMS

#: Longest term first so "technical program manager" wins over "program manager".
_FAMILY_TERMS: tuple[str, ...] = tuple(
    sorted(ROLE_FAMILY_TERMS, key=len, reverse=True)
)

#: Label for a title that matches no known family term — an honest "not
#: classified", never a silent assignment to the nearest family.
UNCLASSIFIED = "unclassified"

#: Label for a field the posting did not disclose.
UNSPECIFIED = "unspecified"


def classify_role_family(title: str | None) -> str:
    """The role-family term ``title`` belongs to, or :data:`UNCLASSIFIED`.

    Uses the SAME vocabulary the scout query builder broadens searches with
    (``query_builder.ROLE_FAMILY_TERMS``), so discovery and this report never
    disagree about what counts as one family.
    """
    lowered = (title or "").lower()
    for term in _FAMILY_TERMS:
        if term in lowered:
            return term
    return UNCLASSIFIED


@dataclass
class BoundStats:
    """Statistics over ONE salary bound, across only the postings that actually
    disclosed that bound. All ``None`` when nothing disclosed it."""

    disclosed: int = 0
    low: int | None = None
    high: int | None = None
    median: float | None = None


def _bound_stats(values: list[int]) -> BoundStats:
    if not values:
        return BoundStats()
    return BoundStats(
        disclosed=len(values),
        low=min(values),
        high=max(values),
        median=float(statistics.median(values)),
    )


@dataclass
class SalaryGroup:
    roleFamily: str
    location: str
    currency: str
    postings: int
    disclosed: int
    titles: list[str]
    salaryMin: BoundStats
    salaryMax: BoundStats


@dataclass
class SalaryIntelligenceReport:
    postings: int = 0
    disclosed: int = 0
    disclosureRate: float | None = None
    currencies: dict[str, int] = field(default_factory=dict)
    groups: list[SalaryGroup] = field(default_factory=list)
    method: str = (
        "Disclosed ranges only — no imputation of a missing bound, no external "
        "benchmark, and currencies are never merged."
    )
    message: str = ""


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SalaryIntelligenceAgent:
    """Aggregates disclosed salary ranges across the caller's own postings."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str) -> SalaryIntelligenceReport:
        postings = self._jobs.list_by_user(user_id)
        report = SalaryIntelligenceReport(postings=len(postings))
        if not postings:
            report.message = (
                "No discovered postings yet — run Job Discovery first, then this "
                "report has real disclosed ranges to aggregate."
            )
            return report

        buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
        for job in postings:
            currency = (job.get("currency") or "").strip().upper() or UNSPECIFIED
            location = (job.get("location") or "").strip() or UNSPECIFIED
            family = classify_role_family(job.get("title"))
            report.currencies[currency] = report.currencies.get(currency, 0) + 1

            bucket = buckets.setdefault(
                (family, location, currency),
                {"postings": 0, "disclosed": 0, "titles": set(), "mins": [], "maxes": []},
            )
            bucket["postings"] += 1
            title = (job.get("title") or "").strip()
            if title:
                bucket["titles"].add(title)
            low = _int_or_none(job.get("salaryMin"))
            high = _int_or_none(job.get("salaryMax"))
            if low is not None:
                bucket["mins"].append(low)
            if high is not None:
                bucket["maxes"].append(high)
            if low is not None or high is not None:
                bucket["disclosed"] += 1
                report.disclosed += 1

        report.disclosureRate = round(report.disclosed / report.postings, 3)
        report.groups = sorted(
            (
                SalaryGroup(
                    roleFamily=family,
                    location=location,
                    currency=currency,
                    postings=data["postings"],
                    disclosed=data["disclosed"],
                    titles=sorted(data["titles"]),
                    salaryMin=_bound_stats(data["mins"]),
                    salaryMax=_bound_stats(data["maxes"]),
                )
                for (family, location, currency), data in buckets.items()
            ),
            key=lambda g: (-g.postings, g.roleFamily, g.location, g.currency),
        )
        report.message = self._message(report)
        return report

    @staticmethod
    def _message(report: SalaryIntelligenceReport) -> str:
        head = (
            f"{report.disclosed} of {report.postings} discovered postings "
            "disclosed a salary range"
        )
        if report.disclosed == 0:
            return (
                f"{head} — there is nothing to aggregate, and no range is "
                "estimated in its place."
            )
        return (
            f"{head}, aggregated across {len(report.groups)} role-family / "
            "location / currency group(s). Undisclosed bounds are left empty, "
            "never imputed."
        )
