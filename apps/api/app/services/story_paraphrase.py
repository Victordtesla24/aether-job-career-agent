"""Story-bank paraphrase similarity (GM2-STORY-001/002, §7.3.1).

``StoryRepository.create`` deduped ONLY on an exact sha256 of the five STAR
fields (``app.services.dedup.compute_story_content_hash``) — a single
reworded sentence produced a brand-new row every time. Verified live: 34 of
36 real production stories are paraphrase re-tellings of only 8 distinct
achievements
(``uat/reports/evidence/gold-master-v2/screens/stories-screen-test.md``).

This module adds a SECOND, fuzzy signal layered on top of that exact hash:
two independent Jaccard-similarity checks over normalized keyword sets —

* TITLE similarity: significant (non-stopword, length >= 3) keyword overlap
  between the two titles.
* ACHIEVEMENT similarity: the same keyword-overlap measure over the first
  250 characters of ``action + " " + result`` — the "what was actually
  accomplished" fields, deliberately EXCLUDING ``situation``/``task`` so a
  generic problem-statement rewrite alone can never trip a match on its own.

BOTH signals must independently clear their own ratio AND an absolute
shared-token floor — never a single field alone. A bare title-only or
achievement-only match is exactly the over-aggressive failure mode
``test_we_story_dedup_relevance.py::TestFalsePositiveGuard`` exists to catch:
two genuinely different achievements must never collapse into one row.

Two threshold PRESETS are exposed, calibrated against the real evidence-report
duplicate groups (the JIRA-dashboard and ANZ-banking paraphrase pairs) AND
this repo's pre-existing ``test_story_dedup.py`` regression fixtures (same
title/different body; identical body/different title) so neither an existing
invariant nor the new dedup contract is sacrificed for the other:

* :data:`CREATE_TIME_THRESHOLDS` — conservative, for the live, silent
  create-time merge (``StoryRepository.create``): a user's real-time save
  must never be silently collapsed into the wrong row, so both signals must
  be strongly similar.
* :data:`BULK_MIGRATION_THRESHOLDS` — deliberately more permissive, for the
  explicit, operator-triggered one-time cleanup
  (``app.services.story_dedup_migration.merge_duplicate_stories``), which
  exists specifically to catch the messier, more varied paraphrase drift a
  Story Bank accumulates over many extractor re-runs — a reviewed, logged,
  one-time sweep over EXISTING data, not a silent live write, so a wider net
  is the right trade-off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: Same connective-word list the rest of the codebase's keyword extraction
#: uses (mirrors ``app.routers.cover_letters._STOPWORDS`` in spirit — kept
#: local so this module has no import-time coupling to that router).
_STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have i in is it its my of on or
    our that the their this to was we were will with you your who what how
    when across own more most very than then also both each am me not can
    could would should into out about over under they them he she his her
    """.split()
)

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*")


def _significant_tokens(text: str) -> frozenset[str]:
    """Lowercased keyword set: stopwords and sub-3-character tokens dropped."""
    words = _WORD_RE.findall((text or "").lower())
    return frozenset(w for w in words if len(w) >= 3 and w not in _STOPWORDS)


def _title_tokens(story: dict[str, Any]) -> frozenset[str]:
    return _significant_tokens(str(story.get("title") or ""))


def _achievement_tokens(story: dict[str, Any]) -> frozenset[str]:
    achievement = f"{story.get('action') or ''} {story.get('result') or ''}"[:250]
    return _significant_tokens(achievement)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> tuple[float, int]:
    """(ratio, shared-count) — ``(0.0, 0)`` when either side is empty so an
    empty title/achievement field can never "match" anything by coincidence."""
    if not a or not b:
        return 0.0, 0
    shared = len(a & b)
    union = len(a | b)
    return (shared / union if union else 0.0), shared


@dataclass(frozen=True)
class SimilarityThresholds:
    title_min_jaccard: float
    title_min_shared: int
    achievement_min_jaccard: float
    achievement_min_shared: int


#: Conservative — used at CREATE time (a real-time, silent merge). Requires
#: at least 70% shared significant title vocabulary — a RATIO, not a raw
#: word-difference count, because a short title's single differing word
#: moves its ratio far more than a longer title's does — with at least 4
#: shared title keywords, AND at least 30% shared achievement
#: (action+result) vocabulary with at least 5 shared keywords.
#:
#: Calibrated against the GM2-STORY evidence-report paraphrase pairs (title
#: Jaccard 0.714, achievement Jaccard 0.526 / 0.667) vs. the false-positive
#: guard pair (title Jaccard 0.083) and this repo's PRE-EXISTING
#: ``test_story_dedup.py`` regression fixtures — "same title, different
#: body" (title Jaccard 1.0 but only 3 shared tokens — the absolute floor
#: catches it), "different title, identical body" used by the enrichment/
#: DDL-guard fixtures (0 title overlap — the title signal alone catches it).
#: Every one of those separates cleanly on this preset with real margin.
CREATE_TIME_THRESHOLDS = SimilarityThresholds(
    title_min_jaccard=0.70,
    title_min_shared=4,
    achievement_min_jaccard=0.30,
    achievement_min_shared=5,
)

#: Deliberately more permissive — used ONLY by the explicit, operator-
#: triggered bulk migration. A real user's Story Bank accumulates paraphrase
#: drift over MANY extractor re-runs (the evidence report's 34-of-36 case),
#: so titles can drift further than the conservative live threshold allows
#: (e.g. the report's "ANZ Cloud-Native Core Banking transformation" vs.
#: "... Modernisation" pair: title Jaccard 0.667, below the create-time 0.70
#: floor) while still describing the exact same achievement. The bulk sweep
#: is a reviewed, logged, one-time operation over EXISTING data — not a
#: silent live write — so a wider net is the correct trade-off here. Still
#: requires the SAME absolute-shared-token floors as the live preset, so it
#: never degrades to a single-field match either.
#:
#: GMV4-story-004 THRESHOLD RE-DECISION (kept at 0.60, deliberately):
#: when this preset drove an irreversible ``DELETE`` its looseness was
#: indefensible. It no longer does — a merge now archives the losing row with
#: a full pre-merge snapshot and is reversible
#: (``story_dedup_migration.restore_merged_stories``), and the only production
#: entrypoint (``scripts/story_dedup_sweep.py``) is dry-run by default and
#: refuses to write until a human has reviewed and signed the emitted plan.
#: The "reviewed" premise this docstring always asserted is now ENFORCED
#: rather than assumed, and the human gate — not the ratio — is what bounds a
#: false merge. Tightening to the create-time 0.70 would buy no protection the
#: human gate does not already give, while silently missing verified-real
#: duplicate clusters that sit between the two values (the ANZ pair above:
#: title Jaccard 0.667), which is the entire defect GMV4-story-002 reports.
#: ALTERNATIVE, implemented and available, not chosen as the default: run the
#: sweep with :data:`CREATE_TIME_THRESHOLDS` instead
#: (``story_dedup_sweep.py --conservative``) for an operator who wants the
#: machine to pre-filter harder at the cost of leaving real duplicates behind.
BULK_MIGRATION_THRESHOLDS = SimilarityThresholds(
    title_min_jaccard=0.60,
    title_min_shared=4,
    achievement_min_jaccard=0.30,
    achievement_min_shared=5,
)


def paraphrase_signals(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The four raw similarity signals for the pair, plus the combined score.

    Derived from the very same primitives :func:`is_paraphrase_match` decides
    with (``_title_tokens`` / ``_achievement_tokens`` / ``_jaccard``) — never a
    second, hand-rolled comparison (§13.1). A human reviewing a proposed merge
    in the bulk sweep's dry-run report therefore sees the actual numbers that
    produced the decision. Ratios are rounded to 4dp for readability HERE
    ONLY; the match decision itself still compares the unrounded values, so a
    borderline pair can never be flipped by presentation rounding.
    """
    title_jaccard, title_shared = _jaccard(_title_tokens(a), _title_tokens(b))
    achievement_jaccard, achievement_shared = _jaccard(
        _achievement_tokens(a), _achievement_tokens(b)
    )
    return {
        "title_jaccard": round(title_jaccard, 4),
        "title_shared": title_shared,
        "achievement_jaccard": round(achievement_jaccard, 4),
        "achievement_shared": achievement_shared,
        "score": round(title_jaccard + achievement_jaccard, 4),
    }


def is_paraphrase_match(
    a: dict[str, Any], b: dict[str, Any], thresholds: SimilarityThresholds
) -> bool:
    """True when ``a`` and ``b`` describe the SAME achievement under
    ``thresholds``. Both the title AND the achievement (action+result)
    signal must independently clear their ratio AND absolute-shared-count
    floor — defense in depth against a single-field false positive (see the
    module docstring)."""
    title_jaccard, title_shared = _jaccard(_title_tokens(a), _title_tokens(b))
    if (
        title_jaccard < thresholds.title_min_jaccard
        or title_shared < thresholds.title_min_shared
    ):
        return False
    achievement_jaccard, achievement_shared = _jaccard(
        _achievement_tokens(a), _achievement_tokens(b)
    )
    return (
        achievement_jaccard >= thresholds.achievement_min_jaccard
        and achievement_shared >= thresholds.achievement_min_shared
    )


def thresholds_as_dict(thresholds: SimilarityThresholds) -> dict[str, Any]:
    """Serialisable form of a preset, for audit trails and dry-run reports."""
    return {
        "title_min_jaccard": thresholds.title_min_jaccard,
        "title_min_shared": thresholds.title_min_shared,
        "achievement_min_jaccard": thresholds.achievement_min_jaccard,
        "achievement_min_shared": thresholds.achievement_min_shared,
    }


def similarity_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Combined title+achievement Jaccard — used only to rank MULTIPLE
    qualifying candidates so the best (not merely the first) match wins."""
    title_jaccard, _ = _jaccard(_title_tokens(a), _title_tokens(b))
    achievement_jaccard, _ = _jaccard(_achievement_tokens(a), _achievement_tokens(b))
    return title_jaccard + achievement_jaccard


def best_paraphrase_match(
    candidate: dict[str, Any],
    existing: list[dict[str, Any]],
    thresholds: SimilarityThresholds,
) -> dict[str, Any] | None:
    """The highest-scoring row in ``existing`` that paraphrase-matches
    ``candidate`` under ``thresholds``, or ``None`` when nothing qualifies."""
    best: dict[str, Any] | None = None
    best_score = -1.0
    for row in existing:
        if not is_paraphrase_match(candidate, row, thresholds):
            continue
        score = similarity_score(candidate, row)
        if score > best_score:
            best_score = score
            best = row
    return best
