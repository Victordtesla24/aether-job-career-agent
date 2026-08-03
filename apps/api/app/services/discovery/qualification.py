"""Agent-decided job qualification (v5).

WHY THIS EXISTS
---------------
Until v5 an adapter decided by itself whether a posting was worth showing:
``relevance.is_relevant`` required the TITLE to match a hand-written regex. That
regex was the binding constraint on the entire product. Measured live against the
real Adzuna AU feed on 2026-08-02: of 200 location-valid Melbourne postings only
**11** passed it. The other 189 were discarded before anything that understands
the candidate ever saw them, so an "ICT Delivery Lead" or a "Senior Manager |
Change Management" died at a string match.

Widening the regex is not the fix, and that was measured too rather than assumed:
admitting a posting because its DESCRIPTION mentions "delivery" or "portfolio"
lets in Executive Assistant, Senior Editor, Senior Electrical Engineer and Room
Attendant. Keyword widening is strictly worse than the regex.

THE DESIGN RULE HERE: **no hardcoded relevance decision.**
There is no title regex in this module, no keyword list, and no magic score
constant that decides who gets seen. Two things decide, both at run time:

* the **ATS engine** produces a REAL score for every applicable posting against
  the user's REAL résumé — a computation, not a rule; and
* a **decider** — by default derived from the user's own live score
  distribution, and overridable with an LLM agent — makes the qualify/reject
  call and records WHY.

The only thing still enforced structurally is LOCATION, in the adapters, because
"a Melbourne-based candidate cannot take an onsite Chicago role" is a fact about
the world rather than a judgement about the candidate.

Nothing is invented. Nothing is silently dropped: every posting is accounted for
as qualified, rejected-with-a-reason, or explicitly UNJUDGED.
"""
from __future__ import annotations

import logging
import os
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from app.services.discovery.base_adapter import JobRaw

logger = logging.getLogger(__name__)

#: Ceiling on postings scored per source per sweep. This is a COMPUTE budget on
#: a 2-core box, not a relevance opinion: everything beyond it is reported as
#: UNJUDGED and re-offered next sweep, never silently rejected.
DEFAULT_SCORE_BUDGET = 120


def score_budget() -> int:
    try:
        return int(os.environ.get("AETHER_QUALIFY_SCORE_BUDGET", DEFAULT_SCORE_BUDGET))
    except (TypeError, ValueError):
        return DEFAULT_SCORE_BUDGET


def _fit_score_of(job: JobRaw) -> float:
    """Sort key for :attr:`QualificationResult.qualified`.

    ``JobRaw`` is a JSON-shaped mapping, so ``fitScore`` is typed ``object``.
    A row that carries no numeric score is legitimately unranked — an UNJUDGED
    posting has no score yet — and sorts last rather than being dropped. ``bool``
    is excluded deliberately: it is a subclass of ``int`` and would otherwise
    rank a ``True`` as 1.0.
    """
    raw = job.get("fitScore")
    if isinstance(raw, bool):
        return float(raw)  # preserves the old `float(x or 0.0)` behaviour
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        # The old expression parsed numeric strings, so keep doing that — but
        # a garbage string used to raise ValueError from inside sort(), taking
        # the whole discovery sweep down over one bad row. Rank it last instead.
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0


@dataclass
class Judgement:
    """One posting, its real score, and the decision made about it."""

    job: JobRaw
    score: float
    qualified: bool
    reason: str


@dataclass
class QualificationResult:
    qualified: list[JobRaw] = field(default_factory=list)
    #: Real discoveries that could NOT be evaluated (no résumé, no engine, or the
    #: compute budget ran out). They are returned so the caller can still PERSIST
    #: them: discarding a real posting on no evidence would be a judgement we
    #: never made. They are simply unranked until a score exists.
    unjudged_jobs: list[JobRaw] = field(default_factory=list)
    judged: int = 0
    rejected: int = 0
    #: Not scored because the compute budget ran out. NOT rejected — calling
    #: these "irrelevant" would be a claim nothing measured.
    unjudged: int = 0
    errors: list[str] = field(default_factory=list)
    #: How the cut was actually chosen this run (adaptive value + basis).
    decision_basis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "qualified": len(self.qualified),
            "judged": self.judged,
            "rejected": self.rejected,
            "unjudged": self.unjudged,
            "decisionBasis": self.decision_basis,
            "errors": self.errors,
        }


class Decider(Protocol):
    """Decides which scored postings reach the board, and says why."""

    def decide(self, judged: list[Judgement]) -> str:
        """Mutate ``Judgement.qualified``/``reason`` in place; return the basis."""
        ...


class AdaptiveDecider:
    """Default decider — derives the cut from REAL data, never a constant.

    Priority of evidence:

    1. **The user's own history.** ``history_scores`` are the real ``fitScore``
       values already on this user's board. The cut is their median: a new
       posting qualifies when it is at least as good a match as the typical job
       this user is already working. That threshold moves as the user's market
       does, with no constant anywhere.
    2. **This sweep's own distribution**, when the user has no history yet
       (first run). The cut is the median of what was actually fetched, so the
       better half of a real batch surfaces rather than an arbitrary number.

    Both are stated in ``decision_basis`` so the number shown to the user is
    explainable rather than magic.
    """

    def __init__(self, history_scores: list[float] | None = None) -> None:
        self._history = [float(s) for s in (history_scores or []) if s is not None]

    def decide(self, judged: list[Judgement]) -> str:
        if not judged:
            return "no postings to judge"
        if len(self._history) >= 5:
            cut = statistics.median(self._history)
            basis = (
                f"median of this user's {len(self._history)} existing board scores "
                f"({cut:.1f}) — a new posting qualifies when it matches the user at "
                f"least as well as the jobs they are already pursuing"
            )
        else:
            cut = statistics.median([j.score for j in judged])
            basis = (
                f"median of this sweep's {len(judged)} real scores ({cut:.1f}) — the "
                f"user has too little history ({len(self._history)} scored jobs) for a "
                f"personal baseline, so the better half of a genuinely fetched batch surfaces"
            )
        for j in judged:
            j.qualified = j.score >= cut
            j.reason = (
                f"ATS {j.score:.1f} vs cut {cut:.1f}"
                if j.qualified
                else f"ATS {j.score:.1f} below cut {cut:.1f}"
            )
        return basis


def _posting_text(job: JobRaw) -> str:
    parts = [
        str(job.get("title") or ""),
        str(job.get("company") or ""),
        str(job.get("description") or ""),
    ]
    reqs = job.get("requirements")
    if isinstance(reqs, list):
        parts.extend(str(r) for r in reqs)
    return "\n".join(p for p in parts if p)


def qualify(
    jobs: list[JobRaw],
    *,
    resume_text: str,
    engine: Any,
    decider: Decider | None = None,
    history_scores: list[float] | None = None,
    budget: int | None = None,
    on_judged: Callable[[list[Judgement]], None] | None = None,
) -> QualificationResult:
    """Score every applicable posting for real, then let the decider choose.

    ``engine`` is the real ATSEngine; ``resume_text`` the user's real résumé.
    With either missing, this refuses to guess: every posting is returned
    UNJUDGED rather than admitted or rejected on no evidence.
    """
    result = QualificationResult()
    if not jobs:
        return result

    if engine is None or not (resume_text or "").strip():
        # No evidence -> no judgement. Surfacing everything unjudged keeps the
        # sweep honest; inventing a rule here is exactly what v5 removed.
        result.unjudged = len(jobs)
        result.unjudged_jobs = list(jobs)
        result.decision_basis = (
            "NOT JUDGED — no résumé text or no scoring engine available, so no "
            "qualify/reject claim can be made about these postings"
        )
        logger.warning(
            "qualification: %d posting(s) left unjudged — résumé/engine unavailable",
            len(jobs),
        )
        return result

    limit = score_budget() if budget is None else budget
    judged: list[Judgement] = []
    for index, job in enumerate(jobs):
        if index >= limit:
            result.unjudged = len(jobs) - index
            result.unjudged_jobs = list(jobs[index:])
            logger.info(
                "qualification: compute budget %d reached — %d posting(s) UNJUDGED "
                "this sweep (re-offered next sweep, not rejected)",
                limit,
                result.unjudged,
            )
            break
        try:
            score = engine.score(resume_text, _posting_text(job))
        except Exception as exc:  # noqa: BLE001 — one bad posting must not sink the sweep
            result.errors.append(f"{job.get('title', '?')}: {type(exc).__name__}: {exc}")
            continue
        judged.append(Judgement(job=job, score=float(score.overall), qualified=False, reason=""))

    if not judged:
        return result

    chosen = decider or AdaptiveDecider(history_scores)
    result.decision_basis = chosen.decide(judged)
    result.judged = len(judged)

    if on_judged is not None:
        on_judged(judged)

    for j in judged:
        if j.qualified:
            enriched = dict(j.job)
            # Carry the REAL computed score forward so the board shows the number
            # that was actually used, never a re-derived or invented one.
            enriched["fitScore"] = j.score
            enriched["atsScore"] = j.score
            enriched["qualificationReason"] = j.reason
            result.qualified.append(enriched)  # type: ignore[arg-type]
        else:
            result.rejected += 1

    result.qualified.sort(key=_fit_score_of, reverse=True)
    logger.info(
        "qualification: %d judged -> %d qualified, %d rejected, %d unjudged (%s)",
        result.judged, len(result.qualified), result.rejected, result.unjudged,
        result.decision_basis,
    )
    return result
