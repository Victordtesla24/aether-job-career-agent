"""GMV4-story-004 — the merge ARCHIVE is a real recovery mechanism, not a label.

``test_story_dedup_invocation.py`` pins that a merge never physically deletes
the losing row. That alone is not enough to call the hazard closed: an archive
nobody can reverse is *worse* than an honest ``DELETE``, because it looks safe
while the content is just as unreachable. The reverse path
(:func:`~app.services.story_dedup_migration.restore_merged_stories`) had ZERO
test coverage anywhere in the suite when this file was written — this file is
that coverage.

What it proves, against a REAL database rather than by reading source:

1. ``dry_run=True`` moves nothing — same rows, same content, nothing archived.
2. A merge ARCHIVES the loser: its own content survives untouched in place, it
   leaves every live listing, and it carries a snapshot pointing at where its
   content went.
3. A restore puts BOTH sides back EXACTLY — the survivor's overwritten text is
   the part a merge otherwise destroys, so byte-equality there is the whole
   claim.
4. A PARTIAL restore of a merge chain is REFUSED, not silently half-applied.
   When one survivor absorbed two duplicates, restoring only the first would
   rewrite the survivor with content predating the second merge and discard it
   with no record. The apply path must write NOTHING in that case.
5. Restoring the WHOLE chain unwinds it in reverse merge order.

Run under the shared test-DB lock (the ``aether_test`` schema is shared across
concurrent swarms)::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \\
        tests/test_story_dedup_archive_restore.py -v
"""
from __future__ import annotations

import time

import pytest

from app.repositories.story import StoryRepository
from app.services.story_dedup_migration import (
    list_archived_merges,
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


#: Three tellings of the same achievement. Every pair sits BELOW
#: ``CREATE_TIME_THRESHOLDS`` (title Jaccard 0.667 < 0.70) so all three are
#: guaranteed to persist as separate rows, and ABOVE
#: ``BULK_MIGRATION_THRESHOLDS`` (>= 0.60) so one sweep folds them together —
#: verified pairwise, not assumed.
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
    """Create the given stories oldest-first, with a gap so ``createdAt``
    ordering (which decides which row survives) is deterministic."""
    created = []
    for i, payload in enumerate(payloads):
        if i:
            time.sleep(0.05)
        row = repo.create(user_id, payload)
        created.append(row)
    ids = {r["id"] for r in created}
    assert len(ids) == len(payloads), (
        "sanity check: create-time dedup must NOT already merge these rows "
        "(they sit below CREATE_TIME_THRESHOLDS by design) — got "
        f"{len(ids)} distinct rows from {len(payloads)} creates"
    )
    return created


def _content(row: dict) -> dict:
    return {f: row[f] for f in _STAR_FIELDS}


class TestDryRunTouchesNothing:
    def test_dry_run_against_a_real_database_changes_nothing(self, test_user_id):
        """The mocked-connection guard in test_story_dedup_invocation.py proves
        the routine issues no SQL. This proves the OUTCOME against a real DB:
        after a dry run the bank is byte-identical and nothing is archived."""
        repo = StoryRepository()
        _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        before = {r["id"]: _content(r) for r in repo.list_by_user(test_user_id)}

        result = merge_duplicate_stories(test_user_id, dry_run=True)

        assert result["dry_run"] is True
        assert result["merged"] == 0, "a dry run must merge nothing"
        assert result["would_merge"] >= 1, (
            f"the seeded pair must be PROPOSED, else this test proves nothing "
            f"about a dry run's restraint; got {result!r}"
        )
        after = {r["id"]: _content(r) for r in repo.list_by_user(test_user_id)}
        assert after == before, "dry_run=True rewrote story content"
        assert list_archived_merges(test_user_id) == [], (
            "dry_run=True archived a row"
        )


class TestMergeArchivesRecoverably:
    def test_merge_archives_the_loser_with_a_restorable_snapshot(self, test_user_id):
        repo = StoryRepository()
        older, newer = _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        older_before = _content(older)

        result = merge_duplicate_stories(test_user_id)
        assert result["merged"] == 1, result
        assert result["reconciled"] is True, result
        assert result["before_count"] == 2 and result["after_count"] == 1, result

        # The loser left every live listing ...
        live_ids = {r["id"] for r in repo.list_by_user(test_user_id)}
        assert live_ids == {older["id"]}, (
            f"only the survivor may remain live, got {live_ids!r}"
        )
        # ... but its OWN content is still there, untouched, resolvable by id.
        loser = repo.get_by_id(newer["id"], test_user_id)
        assert loser is not None, "the archived row must stay resolvable by id"
        assert _content(loser) == _content(newer), (
            "an archived row's own content must be left untouched in place"
        )

        archived = list_archived_merges(test_user_id)
        assert [r["id"] for r in archived] == [newer["id"]], archived
        entry = archived[0]
        assert entry["mergedIntoId"] == older["id"], (
            "an archived row must point at where its content went"
        )
        snapshot = entry["mergeSnapshot"]
        assert snapshot["batch_id"] == result["batch_id"]
        assert snapshot["signals"]["title_jaccard"] >= 0.60
        assert snapshot["survivor_before"] | older_before == snapshot["survivor_before"], (
            "the snapshot must capture the survivor's pre-merge content — the "
            "only part of a merge that is otherwise destroyed; got "
            f"{snapshot.get('survivor_before')!r}"
        )


class TestRestoreRoundTrip:
    def test_restore_puts_the_survivor_and_the_loser_back_exactly(self, test_user_id):
        repo = StoryRepository()
        older, newer = _seed(repo, test_user_id, _OLDEST, _MIDDLE)
        older_before = _content(older)

        merged = merge_duplicate_stories(test_user_id)
        assert merged["merged"] == 1
        survivor_after_merge = repo.get_by_id(older["id"], test_user_id)
        assert _content(survivor_after_merge) != older_before, (
            "precondition: the merge must actually have overwritten the "
            "survivor, otherwise the restore below proves nothing"
        )

        preview = restore_merged_stories(test_user_id, batch_id=merged["batch_id"])
        assert preview["dry_run"] is True
        assert preview["restored"] == 0, "a restore dry run must write nothing"
        assert preview["restorable"] == 1, preview
        assert repo.get_by_id(older["id"], test_user_id) == survivor_after_merge, (
            "the restore DRY RUN rewrote the survivor"
        )

        done = restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=False
        )
        assert done["restored"] == 1, done
        assert done["reconciled"] is True, done
        assert done["unrestorable"] == [] and done["blocked"] == []

        live = {r["id"]: _content(r) for r in repo.list_by_user(test_user_id)}
        assert set(live) == {older["id"], newer["id"]}, (
            f"both rows must be live again after a restore, got {set(live)!r}"
        )
        assert live[older["id"]] == older_before, (
            "the survivor must be restored to its EXACT pre-merge content — "
            "this is the part a merge destroys, so anything less than "
            "byte-equality means the archive is not a real recovery mechanism"
        )
        assert live[newer["id"]] == _content(newer)
        assert list_archived_merges(test_user_id) == [], (
            "a fully restored batch must leave nothing archived"
        )


class TestMergeChainRestoreSafety:
    """One survivor, two duplicates, one sweep — the case where a partial
    restore silently destroys content if it is not refused."""

    def _seed_chain(self, repo: StoryRepository, user_id: str):
        oldest, middle, newest = _seed(
            repo, user_id, _OLDEST, _MIDDLE, _NEWEST
        )
        merged = merge_duplicate_stories(user_id)
        assert merged["merged"] == 2, (
            f"precondition: both duplicates must fold into ONE survivor, got "
            f"{merged['merged']}"
        )
        assert merged["after_count"] == 1
        archived_ids = {r["id"] for r in list_archived_merges(user_id)}
        assert archived_ids == {middle["id"], newest["id"]}, archived_ids
        return oldest, middle, newest, merged

    def test_partial_restore_of_a_chain_is_refused_and_writes_nothing(
        self, test_user_id
    ):
        repo = StoryRepository()
        oldest, middle, newest, merged = self._seed_chain(repo, test_user_id)
        survivor_after_merge = repo.get_by_id(oldest["id"], test_user_id)

        # Restoring ONLY the first-merged duplicate would rewrite the survivor
        # with content from before the SECOND merge, discarding it silently.
        preview = restore_merged_stories(test_user_id, story_ids=[middle["id"]])
        assert preview["restorable"] == 0, preview
        assert [b["story_id"] for b in preview["blocked"]] == [middle["id"]], preview
        assert newest["id"] in preview["blocked"][0]["blocked_by"], preview

        with pytest.raises(RuntimeError, match="REFUSED"):
            restore_merged_stories(
                test_user_id, story_ids=[middle["id"]], dry_run=False
            )

        assert repo.get_by_id(oldest["id"], test_user_id) == survivor_after_merge, (
            "a REFUSED restore must write NOTHING — the survivor was mutated"
        )
        assert {r["id"] for r in list_archived_merges(test_user_id)} == {
            middle["id"], newest["id"]
        }, "a REFUSED restore must leave the archive untouched"

    def test_restoring_the_whole_chain_unwinds_it_in_reverse_merge_order(
        self, test_user_id
    ):
        repo = StoryRepository()
        oldest, middle, newest, merged = self._seed_chain(repo, test_user_id)
        oldest_before = _content(oldest)

        done = restore_merged_stories(
            test_user_id, batch_id=merged["batch_id"], dry_run=False
        )
        assert done["restored"] == 2, done
        assert done["blocked"] == [] and done["unrestorable"] == []
        assert done["reconciled"] is True, done

        live = {r["id"]: _content(r) for r in repo.list_by_user(test_user_id)}
        assert set(live) == {oldest["id"], middle["id"], newest["id"]}
        assert live[oldest["id"]] == oldest_before, (
            "unwinding the chain must return the survivor to its ORIGINAL "
            "content — if the steps were applied in the wrong order it lands "
            "on an intermediate merged state instead"
        )
        assert live[middle["id"]] == _content(middle)
        assert live[newest["id"]] == _content(newest)
        assert list_archived_merges(test_user_id) == []
