"""U2c / U-STORY-1 ruling E2 — the dedup sweep must reconcile the corpus mirror.

``StoryRepository._mirror_to_corpus`` recorded this residual in its own
docstring rather than leaving it unwritten::

    the bulk paraphrase de-dup sweep archives a row directly in its own audited
    transaction (services/story_dedup_migration.py:273) and un-archives it at
    :578. Those two writes do not touch the mirror, so between an operator sweep
    and the next save of that story its claim would remain in the corpus while
    ``list_by_user`` no longer returns it.

That is a live-evidence hole, not a cosmetic one: ``build_corpus_evidence``
reads ``EvidenceCorpusItem`` on every tailoring and cover-letter run, so an
archived story kept grounding claims in generated documents even though the
user could no longer see it — and a RESTORED story stayed invisible to the
guards, so its own true content read as unsupported.

The sweep's whole design is audited, all-or-nothing transactions with count
reconciliation. A mirror write that lands outside that transaction would be a
second, unaudited source of truth, so these tests pin BOTH directions AND that
the reconciliation happens inside the same transaction that moves the row.
"""
from __future__ import annotations

import time

from app.repositories.evidence_corpus import EvidenceCorpusRepository
from app.repositories.story import StoryRepository
from app.services.story_corpus import STORY_CORPUS_SOURCE, story_item_id
from app.services.story_dedup_migration import (
    merge_duplicate_stories,
    restore_merged_stories,
)

_STAR_FIELDS = ("title", "situation", "task", "action", "result")


def _story(title: str, action: str, result: str, **extra):
    payload = {
        "title": title,
        "situation": "The legacy core banking stack blocked modernisation.",
        "task": "Modernise onto cloud-native .NET and Azure services.",
        "action": action,
        "result": result,
    }
    payload.update(extra)
    return payload


#: Same pair the archive/restore suite uses: below CREATE_TIME_THRESHOLDS (so
#: both persist) and above BULK_MIGRATION_THRESHOLDS (so one sweep folds them).
_OLDEST = _story(
    "ANZ Cloud-Native Core Banking transformation",
    "Led a 5+ cross-functional squad (up to 40 people) migrating core banking.",
    "30% faster delivery, 15% infra cost cut, 95-100% compliance.",
    tags=["banking"],
)
_MIDDLE = _story(
    "ANZ Cloud-Native Core Banking Modernisation",
    "Directed a cross-functional squad of up to 40 people through the migration.",
    "Delivery sped up ~30%, infra cost fell ~15%, compliance reached 95-100%.",
    tags=["azure"],
)
_NEWEST = _story(
    "ANZ Cloud-Native Core Banking overhaul",
    "Drove a cross-functional squad of as many as 40 people through the migration.",
    "Delivery accelerated ~30%, infra cost dropped ~15%, compliance hit 95-100%.",
    tags=["dotnet"],
)


def _seed(repo: StoryRepository, user_id: str, *payloads) -> list[dict]:
    created = []
    for i, payload in enumerate(payloads):
        if i:
            time.sleep(0.05)
        created.append(repo.create(user_id, payload))
    assert len({r["id"] for r in created}) == len(payloads), (
        "create-time dedup must not already merge these rows"
    )
    return created


def _mirror(user_id: str) -> dict[str, dict]:
    return {
        item["itemId"]: item
        for item in EvidenceCorpusRepository().list_by_user(user_id)
        if item.get("source") == STORY_CORPUS_SOURCE
    }


class TestArchiveRetractsTheMirror:
    def test_a_merged_away_story_stops_being_citable_evidence(self, test_user_id):
        repo = StoryRepository()
        survivor, loser = _seed(repo, test_user_id, _OLDEST, _MIDDLE)

        before = _mirror(test_user_id)
        assert story_item_id(loser["id"]) in before, (
            "precondition: the CRUD mirror must have published both stories"
        )
        assert story_item_id(survivor["id"]) in before

        result = merge_duplicate_stories(test_user_id)
        assert result["merged"] == 1, result
        assert result["reconciled"] is True, result

        after = _mirror(test_user_id)
        assert story_item_id(loser["id"]) not in after, (
            "the archived story is still citable evidence — a claim the user "
            "can no longer see is still grounding generated documents"
        )
        assert story_item_id(survivor["id"]) in after, (
            "the SURVIVOR must stay citable — the sweep must not retract the "
            "row it kept"
        )

    def test_the_survivors_mirror_carries_its_MERGED_content(self, test_user_id):
        """The merge REWRITES the survivor's STAR fields. A mirror left holding
        the pre-merge wording is stale evidence of exactly the class this fix
        exists to remove — the same defect wearing the other row's label."""
        repo = StoryRepository()
        survivor, _loser = _seed(repo, test_user_id, _OLDEST, _MIDDLE)

        merge_duplicate_stories(test_user_id)

        merged = repo.get_by_id(survivor["id"], test_user_id)
        claim = _mirror(test_user_id)[story_item_id(survivor["id"])]["claim"]
        for field in _STAR_FIELDS:
            value = (merged.get(field) or "").strip()
            if value:
                assert value in claim, (
                    f"the survivor's mirrored claim is missing its merged "
                    f"{field!r} — the corpus holds pre-merge content"
                )

    def test_the_sweep_reports_the_mirror_reconciliation_it_performed(
        self, test_user_id
    ):
        """The sweep's result is its audit record. A reconciliation that
        happened but was not reported is indistinguishable from one that did
        not happen."""
        repo = StoryRepository()
        _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        result = merge_duplicate_stories(test_user_id)
        assert result["mirror_retracted"] == 1, result
        assert result["mirror_refreshed"] == 1, result

    def test_a_dry_run_still_touches_no_evidence(self, test_user_id):
        repo = StoryRepository()
        _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        before = _mirror(test_user_id)

        result = merge_duplicate_stories(test_user_id, dry_run=True)

        assert result["merged"] == 0
        assert result["mirror_retracted"] == 0
        assert result["mirror_refreshed"] == 0
        assert _mirror(test_user_id).keys() == before.keys()


class TestRestoreRepublishesTheMirror:
    def test_a_restored_story_becomes_citable_again(self, test_user_id):
        repo = StoryRepository()
        survivor, loser = _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        merged = merge_duplicate_stories(test_user_id)
        assert merged["merged"] == 1

        result = restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=False
        )
        assert result["restored"] == 1, result
        assert result["reconciled"] is True, result

        after = _mirror(test_user_id)
        assert story_item_id(loser["id"]) in after, (
            "the restored story is invisible to the guards — its own true "
            "content now reads as unsupported evidence"
        )
        assert story_item_id(survivor["id"]) in after

    def test_the_survivors_mirror_returns_to_its_pre_merge_content(
        self, test_user_id
    ):
        repo = StoryRepository()
        survivor, _loser = _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        before_claim = _mirror(test_user_id)[story_item_id(survivor["id"])]["claim"]

        merged = merge_duplicate_stories(test_user_id)
        restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=False
        )

        after_claim = _mirror(test_user_id)[story_item_id(survivor["id"])]["claim"]
        assert after_claim == before_claim, (
            "a restore put the story row back but left the corpus holding the "
            "merged wording — the two sources of truth disagree"
        )

    def test_the_restore_reports_the_mirror_reconciliation_it_performed(
        self, test_user_id
    ):
        repo = StoryRepository()
        _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        merged = merge_duplicate_stories(test_user_id)
        result = restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=False
        )
        assert result["mirror_republished"] == 1, result
        assert result["mirror_refreshed"] == 1, result

    def test_a_restore_dry_run_still_touches_no_evidence(self, test_user_id):
        repo = StoryRepository()
        _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        merged = merge_duplicate_stories(test_user_id)
        before = _mirror(test_user_id)

        result = restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=True
        )

        assert result["restored"] == 0
        assert result["mirror_republished"] == 0
        assert _mirror(test_user_id).keys() == before.keys()


class TestTheReconciliationIsInsideTheAuditedTransaction:
    def test_a_failed_merge_leaves_both_the_rows_and_the_mirror_untouched(
        self, test_user_id, monkeypatch
    ):
        """All-or-nothing is the sweep's whole safety property. If the mirror
        were reconciled outside the transaction, a merge that rolls back would
        leave the corpus already retracted — evidence deleted for a merge that
        never happened."""
        import app.services.story_dedup_migration as migration

        repo = StoryRepository()
        # THREE near-duplicates so the sweep plans TWO merges: the failure is
        # injected into the second, AFTER the first has already retracted its
        # mirror row. Only a shared transaction can put that row back.
        seeded = _seed(repo, test_user_id, _OLDEST, _MIDDLE, _NEWEST)
        before = _mirror(test_user_id)

        real_hash = migration.compute_story_content_hash
        calls = {"n": 0}

        def _boom(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("simulated failure mid-merge")
            return real_hash(*args, **kwargs)

        monkeypatch.setattr(migration, "compute_story_content_hash", _boom)

        try:
            merge_duplicate_stories(test_user_id)
        except RuntimeError:
            pass
        else:  # pragma: no cover — the injected failure must actually fire
            raise AssertionError(
                "the sweep planned fewer than 2 merges, so no failure was "
                "injected mid-transaction and this test proves nothing"
            )

        after = _mirror(test_user_id)
        assert after.keys() == before.keys(), (
            "the mirror was reconciled outside the merge transaction — a "
            "rolled-back merge still deleted the user's evidence"
        )
        assert {r["id"] for r in repo.list_by_user(test_user_id)} == {
            row["id"] for row in seeded
        }
