"""Market Trends Agent — own-feed trends (wave-4A, ADR-AG-1).

HONEST SCOPE. Aether subscribes to NO market-data feed: there is no BLS/Seek
insights/Indeed-hiring-lab integration anywhere in the codebase. The only
labour-market signal it holds is the user's OWN discovery feed. So this agent
reports trends strictly inside that feed:

* **Keyword shifts** — document frequency of each keyword (title + requirements)
  in the EARLIER half of the user's own postings vs the RECENT half. Only real
  movement is reported; an unchanged keyword is not a "shift" and never pads the
  list.
* **Remote mix** — the real remote/onsite split of those postings.
* **Volume** — postings per ISO week, plus the mean over the REAL span
  (including weeks with none), so the average is not inflated by dropping the
  quiet weeks.

Everything is keyed on the DISCOVERY date (``Job.createdAt``) because that is
the only date every source provides; ``postedAt`` disclosure is reported
separately rather than silently substituted.

Below the sample threshold the report says "not enough data" and returns NO
trends at all — a two-posting feed cannot yield an honest trend, and emitting
zeroed-out series would read as "the market is flat" (a fabricated finding).

Deterministic and unmetered: no LLM call, so no spend and no plan-quota
reservation (absent from ``_LLM_TIER_BY_BACKEND``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.repositories.job import JobRepository

#: Minimum postings before ANY trend is reported.
MIN_POSTINGS = 5

#: Minimum postings in EACH half of the window before a keyword shift is called.
MIN_PER_HALF = 3

#: Cap on reported shifts (largest absolute movement first).
MAX_SHIFTS = 12

_WORD_RE = re.compile(r"[a-z][a-z0-9+#.]*")

#: Generic job-ad vocabulary that carries no trend signal. Deliberately small:
#: over-filtering would hide real movement, so only structural filler is listed.
_STOPWORDS = frozenset(
    """
    and or the for with from into onto our your their this that these those
    you we they it its role roles job jobs work working works team teams
    experience experienced years year strong excellent good great ability
    able skills skill knowledge understanding required require requires
    requirement requirements responsibilities responsible plus must nice have
    has had will would should can could may might etc across within about
    based new senior junior lead mid level levels part full time permanent
    contract remote hybrid onsite office day days week weeks month months
    company companies client clients business businesses
    """.split()
)


@dataclass
class KeywordShift:
    keyword: str
    earlierCount: int
    recentCount: int
    delta: int


@dataclass
class WeeklyVolume:
    weekStart: str
    postings: int


@dataclass
class MarketTrendsReport:
    postings: int = 0
    windowStart: str | None = None
    windowEnd: str | None = None
    insufficientData: bool = True
    minPostings: int = MIN_POSTINGS
    minPerHalf: int = MIN_PER_HALF
    remoteMix: dict[str, Any] | None = None
    postingsPerWeek: list[WeeklyVolume] = field(default_factory=list)
    weeksSpanned: int | None = None
    postingsPerWeekMean: float | None = None
    keywordShifts: list[KeywordShift] = field(default_factory=list)
    keywordShiftsAvailable: bool = False
    earlierPostings: int = 0
    recentPostings: int = 0
    postedAtDisclosed: int = 0
    basis: str = (
        "Your own discovery feed, keyed on the DISCOVERY date (when Aether found "
        "each posting) — no external market-data feed is involved."
    )
    message: str = ""


def _keywords(job: dict[str, Any]) -> set[str]:
    """The distinct trend keywords one posting contributes (document frequency,
    so a posting that repeats a word ten times still counts once)."""
    requirements = job.get("requirements")
    if isinstance(requirements, str):
        try:
            requirements = json.loads(requirements)
        except ValueError:
            requirements = [requirements]
    if not isinstance(requirements, (list, tuple)):
        requirements = []
    text = " ".join(
        [str(job.get("title") or "")] + [str(r) for r in requirements]
    ).lower()
    return {
        token
        for token in _WORD_RE.findall(text)
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _week_start(value: datetime | date) -> date:
    day = value.date() if isinstance(value, datetime) else value
    return day - timedelta(days=day.weekday())


class MarketTrendsAgent:
    """Computes trends inside the caller's own discovery feed."""

    def __init__(self, jobs: JobRepository | None = None) -> None:
        self._jobs = jobs or JobRepository()

    def run(self, user_id: str) -> MarketTrendsReport:
        postings = [
            j for j in self._jobs.list_by_user(user_id) if j.get("createdAt") is not None
        ]
        postings.sort(key=lambda j: j["createdAt"])
        report = MarketTrendsReport(postings=len(postings))
        report.postedAtDisclosed = sum(
            1 for j in postings if j.get("postedAt") is not None
        )
        if len(postings) < MIN_POSTINGS:
            report.message = (
                f"Not enough data yet — trends need at least {MIN_POSTINGS} "
                f"discovered postings and you have {len(postings)}. Nothing is "
                "reported rather than guessing a trend from a handful of rows."
            )
            return report

        report.insufficientData = False
        report.windowStart = postings[0]["createdAt"].isoformat()
        report.windowEnd = postings[-1]["createdAt"].isoformat()

        remote = sum(1 for j in postings if j.get("remote"))
        report.remoteMix = {
            "remote": remote,
            "onsite": len(postings) - remote,
            "remoteShare": round(remote / len(postings), 3),
        }

        weekly: dict[date, int] = {}
        for job in postings:
            week = _week_start(job["createdAt"])
            weekly[week] = weekly.get(week, 0) + 1
        report.postingsPerWeek = [
            WeeklyVolume(weekStart=week.isoformat(), postings=count)
            for week, count in sorted(weekly.items())
        ]
        first_week, last_week = min(weekly), max(weekly)
        report.weeksSpanned = ((last_week - first_week).days // 7) + 1
        report.postingsPerWeekMean = round(len(postings) / report.weeksSpanned, 2)

        mid = len(postings) // 2
        earlier, recent = postings[:mid], postings[mid:]
        report.earlierPostings, report.recentPostings = len(earlier), len(recent)
        if len(earlier) >= MIN_PER_HALF and len(recent) >= MIN_PER_HALF:
            report.keywordShiftsAvailable = True
            report.keywordShifts = self._shifts(earlier, recent)
        report.message = self._message(report)
        return report

    @staticmethod
    def _shifts(
        earlier: list[dict[str, Any]], recent: list[dict[str, Any]]
    ) -> list[KeywordShift]:
        earlier_counts: dict[str, int] = {}
        recent_counts: dict[str, int] = {}
        for job in earlier:
            for token in _keywords(job):
                earlier_counts[token] = earlier_counts.get(token, 0) + 1
        for job in recent:
            for token in _keywords(job):
                recent_counts[token] = recent_counts.get(token, 0) + 1
        shifts = [
            KeywordShift(
                keyword=token,
                earlierCount=earlier_counts.get(token, 0),
                recentCount=recent_counts.get(token, 0),
                delta=recent_counts.get(token, 0) - earlier_counts.get(token, 0),
            )
            for token in set(earlier_counts) | set(recent_counts)
        ]
        # Only genuine movement is a "shift"; ties are ordered by keyword so the
        # report is byte-stable for the same feed.
        shifts = [s for s in shifts if s.delta != 0]
        shifts.sort(key=lambda s: (-abs(s.delta), s.keyword))
        return shifts[:MAX_SHIFTS]

    @staticmethod
    def _message(report: MarketTrendsReport) -> str:
        head = (
            f"Trends across {report.postings} discovered postings "
            f"({report.postingsPerWeekMean} per week over "
            f"{report.weeksSpanned} week(s))."
        )
        if not report.keywordShiftsAvailable:
            return (
                f"{head} Keyword shifts need at least {MIN_PER_HALF} postings in "
                f"each half of the window ({report.earlierPostings} earlier / "
                f"{report.recentPostings} recent), so none are reported."
            )
        if not report.keywordShifts:
            return (
                f"{head} No keyword moved between the earlier and recent half of "
                "the window."
            )
        return f"{head} {len(report.keywordShifts)} keyword(s) moved."
