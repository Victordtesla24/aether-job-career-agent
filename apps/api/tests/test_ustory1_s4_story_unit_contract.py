"""U-STORY-1 step 4 — story evidence carries the corpus unit contract.

Discovery §2.1 (``U-STORY-DISCOVERY.md``): the blank-line split at
``resume_tailor.py:2031`` (``re.split(r"\\n\\s*\\n", evidence_extra)``) is the
load-bearing contract of the tailoring evidence chain — it scopes each evidence
unit to the bullet context it can license.
``evidence_corpus.corpus_items_to_evidence_text`` was written to match it
exactly: one item per unit, units separated by a blank line, each unit tagged
``[source · stated|inferred · confidence X]``. **``build_story_evidence`` did
not follow it properly**: it emitted one blank-line chunk per story but with no
epistemic tag and no source label, so a Story Bank claim was indistinguishable
from résumé text to everything downstream.

This pins the shared contract:

* every story unit ends in ``[story_bank · stated · confidence high]``;
* a story unit and a corpus unit built from the same claim are byte-identical
  in shape — the two producers render through ONE function, so they cannot
  drift apart (the discovery's reason step 4 lands before step 5);
* the tag introduces NO new proper-noun anchor, so ``_scoped_evidence_map``
  scopes a tagged story exactly as it scoped an untagged one — an employer-
  scoped story still lends its vocabulary only to that employer's bullets.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ustory1_s4_story_unit_contract.py -p no:randomly -q
"""
from __future__ import annotations

import re
from typing import Any

from app.agents.tailor_agent import build_story_evidence
from app.services.evidence_corpus import corpus_items_to_evidence_text
from app.services.resume_tailor import _scoped_evidence_map, proper_noun_anchors

_STORY: dict[str, Any] = {
    "id": "story-1",
    "title": "Kookaburras platform migration",
    "situation": "The Kookaburras estate ran on fragile virtual machines.",
    "task": "Lead the migration.",
    "action": "Rebuilt the Kookaburras deployment pipeline in Rundeck.",
    "result": "Release reliability improved.",
    "tags": ["platform"],
    "metrics": {},
}

_SECOND_STORY: dict[str, Any] = {
    "id": "story-2",
    "title": "Telstra billing reconciliation",
    "situation": "Telstra invoices drifted from the ledger.",
    "task": "Reconcile them.",
    "action": "Built a reconciliation job at Telstra in Ruby.",
    "result": "Drift eliminated.",
    "tags": ["finance"],
    "metrics": {},
}


class _StubStories:
    def __init__(self, stories: list[dict[str, Any]]) -> None:
        self._stories = stories

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        return list(self._stories)


def test_every_story_unit_carries_the_epistemic_tag() -> None:
    evidence = build_story_evidence("user-1", repo=_StubStories([_STORY, _SECOND_STORY]))
    units = [u for u in re.split(r"\n\s*\n", evidence) if u.strip()]
    assert len(units) == 2, units
    for unit in units:
        assert unit.endswith("[story_bank · stated · confidence high]"), unit


def test_a_story_unit_and_a_corpus_unit_share_one_renderer() -> None:
    """Both producers must emit the SAME unit shape — the contract step 5's
    corpus mirror depends on."""
    evidence = build_story_evidence("user-1", repo=_StubStories([_STORY]))
    claim = evidence.split("\n[")[0]
    expected = corpus_items_to_evidence_text(
        [
            {
                "claim": claim,
                "source": "story_bank",
                "stated_or_inferred": "stated",
                "confidence": "high",
            }
        ]
    )
    assert evidence == expected, (evidence, expected)


def test_the_tag_adds_no_proper_noun_anchor() -> None:
    """``_scoped_evidence_map`` scopes units by proper-noun anchors; a tag that
    introduced one would silently re-scope every story."""
    evidence = build_story_evidence("user-1", repo=_StubStories([_STORY]))
    claim = evidence.split("\n[")[0]
    assert proper_noun_anchors(evidence) == proper_noun_anchors(claim), evidence


def test_a_tagged_story_is_still_scoped_to_its_own_employer() -> None:
    """The pin: an employer-anchored story lends its vocabulary only to that
    employer's bullets, exactly as before the tag existed."""
    structured = [
        {"evidenceRef": "b1", "text": "Ran the Kookaburras platform team."},
        {"evidenceRef": "b2", "text": "Ran the Telstra billing team."},
    ]
    resume_text = "Ran the Kookaburras platform team. Ran the Telstra billing team."
    evidence_extra = build_story_evidence(
        "user-1", repo=_StubStories([_STORY, _SECOND_STORY])
    )
    scoped = _scoped_evidence_map(structured, resume_text, evidence_extra)
    b1_stems, _ = scoped["b1"]
    b2_stems, _ = scoped["b2"]
    assert "rundeck" in b1_stems, sorted(b1_stems)
    assert "rundeck" not in b2_stems, sorted(b2_stems)
    assert "ruby" in b2_stems, sorted(b2_stems)
    assert "ruby" not in b1_stems, sorted(b1_stems)
