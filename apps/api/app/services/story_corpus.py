"""The Story Bank as provenance-tagged corpus evidence (U-STORY-1 steps 4-5).

One definition of "what a story looks like as evidence", shared by the two
places that need it:

* :func:`~app.agents.tailor_agent.build_story_evidence`, which renders live
  stories into the tailoring / cover-letter evidence text, and
* :class:`~app.repositories.story.StoryRepository`, which mirrors every story
  write into ``EvidenceCorpusItem`` so a story is individually citable and
  inherits the corpus path's JD ranking and character budget.

Keeping the mapping here (rather than in either caller) is what makes the two
agree by construction: the mirror's ``claim`` is byte-identical to the claim
the evidence renderer emits, so the same story can never reach one guard in two
different wordings — and the tailoring prompt can de-duplicate the two
producers' units by simple equality.

This module holds no guard logic. ``statedOrInferred`` and ``confidence`` are a
LABEL on the candidate's own evidence: nothing in the fabrication or entailment
path reads them.
"""
from __future__ import annotations

from typing import Any, Mapping

#: ``EvidenceCorpusItem.source`` for every mirrored story. Also the key a
#: wholesale re-extraction would pass to
#: ``EvidenceCorpusRepository.delete_sources`` / ``replace_sources``.
STORY_CORPUS_SOURCE = "story_bank"

#: ``EvidenceCorpusItem.itemId`` prefix — the mirror is keyed on the story's own
#: id, so ``upsert_many`` updates a story's claim in place instead of growing a
#: row per save.
STORY_ITEM_PREFIX = "story:"

#: A story is the candidate's OWN account of their OWN achievement, so its
#: source STATES the claim — never "inferred".
STORY_EPISTEMIC = "stated"

#: ``high`` records that the extractor's grounding layer already refused any
#: story whose numbers or organisation the résumé did not evidence
#: (``services/resume_bullets.py`` guards + ``story_extractor._ground_narrative``),
#: and that a hand-authored story is the candidate asserting it directly.
STORY_CONFIDENCE = "high"

#: ``EvidenceCorpusItem.category`` for stories, so a corpus reader can tell a
#: STAR achievement from a résumé line or a repo-derived claim.
STORY_CATEGORY = "story"

#: STAR fields folded into the claim, in narrative order.
_STAR_FIELDS = ("situation", "task", "action", "result")


def story_item_id(story_id: str) -> str:
    """``EvidenceCorpusItem.itemId`` for a story id."""
    return f"{STORY_ITEM_PREFIX}{story_id}"


def story_claim_text(story: Mapping[str, Any]) -> str:
    """One story flattened into a single evidence claim.

    Title + tags + the four STAR fields + every quantified metric, so
    metric-bearing evidence survives into the corpus rather than being summed
    away — losing an evidenced number is precisely what the Story Bank exists
    to prevent.
    """
    fields = [str(story.get("title") or ""), " ".join(story.get("tags") or [])]
    for key in _STAR_FIELDS:
        fields.append(str(story.get(key) or ""))
    metrics = story.get("metrics")
    if isinstance(metrics, dict):
        fields.extend(f"{k} {v}" for k, v in metrics.items())
    return " ".join(f for f in fields if f).strip()


def story_corpus_item(story: Mapping[str, Any]) -> dict[str, Any] | None:
    """One story as an ``EvidenceCorpusItem`` row, or ``None`` when it has no
    citable content.

    ``sourceUrl`` points at the story on the user's own Story Bank screen: the
    provenance of a story is the story itself, which is what makes "which story
    grounded this bullet?" answerable for the first time.
    """
    claim = story_claim_text(story)
    story_id = str(story.get("id") or "").strip()
    if not claim:
        return None
    item: dict[str, Any] = {
        "claim": claim,
        "category": STORY_CATEGORY,
        "source": STORY_CORPUS_SOURCE,
        "stated_or_inferred": STORY_EPISTEMIC,
        "confidence": STORY_CONFIDENCE,
    }
    if story_id:
        item["id"] = story_item_id(story_id)
        item["sourceUrl"] = f"/dashboard/stories#{story_id}"
    return item
