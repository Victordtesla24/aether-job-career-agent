"""Story-to-job relevance scoring (§7.3.3/§7.3.4/§7.3.5, GM2-STORY-relevance).

Verified live/by grep: no ``relevance_score``/``relevanceScore``-shaped field
exists anywhere in the API or web app before this module — a job's Story Bank
evidence is either used unconditionally (every story, regardless of fit) or
not at all. This module gives generation a deterministic, bounded [0, 1]
measure of how well a Story Bank entry's OWN evidence backs a SPECIFIC job
posting, so evidence selection can be JD-aware instead of all-or-nothing.

:func:`story_relevance_score` is term-frequency-weighted keyword overlap: a
JD keyword's weight is its OWN frequency within that posting (a term the
posting repeats/emphasises counts more), and the score is the share of that
weighted JD vocabulary the story's own text actually proves. There is no
larger reference corpus to draw a genuine cross-document IDF signal from
(scoring one story against one job description, not a corpus), so this is
deliberately named/documented as term-frequency overlap rather than claiming
full TF-IDF — a real, deterministic, reproducible computation, never an
invented number.

:func:`relevance_threshold` reads the env-configurable selection floor
(§7.3.5): cover-letter/application generation should include only stories
whose score against the target job clears this bar, default 0.4.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

#: Same connective-word list ``app.services.story_paraphrase`` uses.
_STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have i in is it its my of on or
    our that the their this to was we were will with you your who what how
    when across own more most very than then also both each am me not can
    could would should into out about over under they them he she his her
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")

#: Default relevance floor (§7.3.5) — env-overridable via
#: ``AETHER_STORY_RELEVANCE_THRESHOLD``.
_DEFAULT_RELEVANCE_THRESHOLD = 0.4


def _tokens(text: str) -> list[str]:
    words = _WORD_RE.findall((text or "").lower())
    return [w for w in words if len(w) >= 3 and w not in _STOPWORDS]


def _story_text(story: dict[str, Any]) -> str:
    parts = [str(story.get("title") or "")]
    parts.extend(str(t) for t in (story.get("tags") or []))
    for key in ("situation", "task", "action", "result"):
        parts.append(str(story.get(key) or ""))
    metrics = story.get("metrics")
    if isinstance(metrics, dict):
        parts.extend(f"{k} {v}" for k, v in metrics.items())
    return " ".join(parts)


def story_relevance_score(story: dict[str, Any], job_description: str) -> float:
    """Bounded [0, 1] measure of how well ``story`` backs ``job_description``.

    0.0 when either side yields no significant keywords (an empty/boilerplate
    JD or an empty story can never register a spurious match).
    """
    jd_terms = _tokens(job_description)
    if not jd_terms:
        return 0.0
    story_terms = set(_tokens(_story_text(story)))
    if not story_terms:
        return 0.0
    weights = Counter(jd_terms)
    total = sum(weights.values())
    if not total:
        return 0.0
    matched = sum(weight for term, weight in weights.items() if term in story_terms)
    return round(matched / total, 4)


def relevance_threshold() -> float:
    """The configured minimum ``story_relevance_score`` for a story to be
    included in a JD-aware evidence corpus (§7.3.5), default 0.4."""
    try:
        return float(
            os.environ.get(
                "AETHER_STORY_RELEVANCE_THRESHOLD", str(_DEFAULT_RELEVANCE_THRESHOLD)
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_RELEVANCE_THRESHOLD


def filter_stories_by_relevance(
    stories: list[dict[str, Any]],
    job_description: str,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """The subset of ``stories`` whose relevance to ``job_description`` clears
    ``threshold`` (default :func:`relevance_threshold`).

    Ready for a generation caller (cover-letter / tailoring evidence
    building) to select JD-aware evidence instead of flattening every story
    the user owns unconditionally — see this module's docstring.
    """
    floor = relevance_threshold() if threshold is None else threshold
    return [
        story
        for story in stories
        if story_relevance_score(story, job_description) >= floor
    ]
