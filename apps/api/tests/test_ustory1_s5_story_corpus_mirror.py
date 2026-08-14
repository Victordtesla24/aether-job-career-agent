"""U-STORY-1 step 5 — every story is mirrored into ``EvidenceCorpusItem``.

Discovery §2.4 B (``U-STORY-DISCOVERY.md``): ``EvidenceCorpusItem`` already has
exactly the columns a story needs (``claim``, ``category``, ``source``,
``sourceUrl``, ``statedOrInferred``, ``confidence``, ``note``, ``asOf`` —
``repositories/evidence_corpus.py:55-70``) and ``upsert_many`` is idempotent on
``(userId, itemId)`` (:126). Mirroring a story there on every story write —
``itemId = "story:<id>"``, ``source = "story_bank"`` — costs no schema change
and buys three things at once:

* stories inherit JD ranking and the 4,000-char budget for free;
* a story becomes individually **citable** — the first time anything downstream
  can say WHICH story grounded a claim, the prerequisite for any learning loop;
* ``replace_sources={"story_bank"}`` makes a re-extraction a clean wholesale
  replace.

This pins the round trip, idempotency, update-in-place and deletion, and the
one regression the mirror could introduce: the SAME story text arriving twice
in the tailoring prompt (once from ``build_story_evidence``, once from
``build_corpus_evidence``) — the token load step 1 just priced down.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ustory1_s5_story_corpus_mirror.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

from app.repositories.evidence_corpus import EvidenceCorpusRepository
from app.repositories.story import StoryRepository
from app.services.evidence_corpus import build_corpus_evidence

_STORY: dict[str, Any] = {
    "title": "Kookaburras platform migration",
    "situation": "The Kookaburras estate ran on fragile virtual machines.",
    "task": "Lead the migration to a container platform.",
    "action": "Rebuilt the Kookaburras deployment pipeline in Rundeck.",
    "result": "Release reliability improved by 40 percent.",
    "tags": ["platform", "migration"],
    "metrics": {"reliability": "+40%"},
}


def _story_items(user_id: str) -> list[dict[str, Any]]:
    return [
        i
        for i in EvidenceCorpusRepository().list_by_user(user_id)
        if i.get("source") == "story_bank"
    ]


def test_creating_a_story_mirrors_it_into_the_corpus(test_user_id: str) -> None:
    row = StoryRepository().create(test_user_id, dict(_STORY))
    items = _story_items(test_user_id)
    assert len(items) == 1, items
    item = items[0]
    assert item["itemId"] == f"story:{row['id']}"
    assert item["statedOrInferred"] == "stated"
    assert item["confidence"] == "high"
    assert row["id"] in (item["sourceUrl"] or "")
    assert "Rundeck" in item["claim"]
    assert "+40%" in item["claim"], item["claim"]


def test_the_mirror_is_idempotent(test_user_id: str) -> None:
    """Saving the same content twice is a dedup hit, not a second story — and
    must not be a second corpus row either."""
    repo = StoryRepository()
    first = repo.create(test_user_id, dict(_STORY))
    second = repo.create(test_user_id, dict(_STORY))
    assert first["id"] == second["id"]
    items = _story_items(test_user_id)
    assert len(items) == 1, items


def test_updating_a_story_updates_its_mirror_in_place(test_user_id: str) -> None:
    repo = StoryRepository()
    row = repo.create(test_user_id, dict(_STORY))
    repo.update(
        row["id"],
        test_user_id,
        {"action": "Rebuilt the Kookaburras deployment pipeline in Ansible."},
    )
    items = _story_items(test_user_id)
    assert len(items) == 1, items
    assert "Ansible" in items[0]["claim"], items[0]["claim"]
    assert "Rundeck" not in items[0]["claim"], items[0]["claim"]


def test_deleting_a_story_removes_its_mirror(test_user_id: str) -> None:
    repo = StoryRepository()
    row = repo.create(test_user_id, dict(_STORY))
    assert _story_items(test_user_id)
    assert repo.delete(row["id"], test_user_id) is True
    assert _story_items(test_user_id) == []


def test_a_mirrored_story_is_individually_citable(test_user_id: str) -> None:
    """The point of the mirror: the story reaches the JD-ranked, budgeted
    corpus evidence path with its own provenance tag."""
    StoryRepository().create(test_user_id, dict(_STORY))
    evidence = build_corpus_evidence(
        test_user_id, "Platform engineer. Kookaburras migration and Rundeck pipelines."
    )
    assert "Rundeck" in evidence, evidence
    assert "[story_bank · stated · confidence high]" in evidence, evidence


def test_the_tailoring_prompt_never_carries_the_same_story_twice(
    test_user_id: str,
) -> None:
    """Both producers now emit the SAME unit for a mirrored story. Joining them
    naively would double the Story Bank's token cost in every tailoring
    prompt — the exact load step 1 priced down."""
    import re

    from app.agents.tailor_agent import build_story_evidence

    StoryRepository().create(test_user_id, dict(_STORY))
    jd = "Platform engineer. Kookaburras migration and Rundeck pipelines."
    from app.agents.tailor_agent import join_evidence_units

    joined = join_evidence_units(
        build_story_evidence(test_user_id, job_description=jd),
        build_corpus_evidence(test_user_id, jd),
    )
    units = [u for u in re.split(r"\n\s*\n", joined) if u.strip()]
    assert len(units) == len(set(units)), units
    assert sum("Rundeck" in u for u in units) == 1, units
