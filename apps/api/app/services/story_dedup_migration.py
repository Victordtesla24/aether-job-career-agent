"""GM2-STORY §7.3.2 — bulk paraphrase de-dup for the Story Bank.

``StoryRepository.create`` (see ``app/services/story_paraphrase.py``) catches a
paraphrase duplicate going FORWARD, at create time. It does nothing for the
duplicates that already accumulated in the DB before that fix shipped — the
evidence report's real 34-of-36-stories-are-paraphrases case
(``uat/reports/evidence/gold-master-v2/screens/stories-screen-test.md``), still
visible as 5 near-duplicate clusters covering 16 of 37 live stories
(GMV4-story-002).

:func:`merge_duplicate_stories` is the operator-triggered, idempotent sweep
that cleans up that EXISTING data for one user. It reuses the exact same
similarity primitives ``StoryRepository.create`` uses
(:mod:`app.services.story_paraphrase` — never a second, hand-rolled comparison,
per §13.1), with the deliberately more permissive ``BULK_MIGRATION_THRESHOLDS``
preset by default.

GMV4-story-004 — WHY THIS MODULE LOOKS THE WAY IT DOES
------------------------------------------------------
An earlier revision hard-``DELETE``d the losing row of every merge. Story
content is user-authored career history that CANNOT be regenerated, and the
sweep is driven by a heuristic that is *deliberately* looser than the
create-time one. An over-matching heuristic wired to an irreversible DELETE is
a data-destruction hazard; the only reason nobody had lost data is that this
function had zero call sites and had never run. Four properties now hold:

1. RECOVERABLE. A merge never deletes. The loser is soft-archived
   (``archivedAt`` / ``mergedIntoId`` / ``mergeSnapshot``; see
   ``app.db.ensure_story_archive_columns``) with its own content untouched in
   place, plus a snapshot of the SURVIVOR's pre-merge content — the only part
   of a merge that is otherwise destroyed. :func:`restore_merged_stories`
   reverses a batch exactly.
2. PREVIEWABLE. ``dry_run=True`` returns every proposed pair with its real
   similarity signals and READS ONLY — it performs ZERO writes to story data.
   (It is not connectionless: it necessarily reads the user's rows through
   ``StoryRepository.list_by_user``, which opens a connection and may run the
   lazy additive ``ADD COLUMN IF NOT EXISTS`` DDL. An earlier revision of this
   docstring claimed "not one connection", which was simply false — round-2
   review finding 3. What matters, and what holds, is that no story row is
   inserted, updated, archived or deleted.)
3. PROVABLE. The result carries genuine ``before_count`` / ``after_count``
   (§8.1(a)); ``after_count`` is a fresh re-count from the DB after the
   commit, never the arithmetic the caller could have done itself.
4. REACHABLE, BUT NOT BY ACCIDENT. ``scripts/story_dedup_sweep.py`` is the
   production entrypoint. It is dry-run by DEFAULT and refuses to write
   without ``--apply`` plus a human-signed plan file plus a re-stated user id.

``dry_run`` defaults to False at THIS layer (the function is the mechanism, and
the pinned tests call it directly to perform real merges); the dry-run default
lives at the entrypoint, which is the thing an operator actually invokes.

Idempotent: a second run over an already-merged set finds nothing left to merge
and returns ``merged: 0`` — archived rows are excluded from
``StoryRepository.list_by_user``, so a re-run cannot see them.
"""
from __future__ import annotations

import getpass
import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from app.db import (
    ensure_story_archive_columns,
    ensure_story_dedup_column,
    get_connection,
    rows_to_dicts,
)
from app.repositories.evidence_corpus import EvidenceCorpusRepository
from app.repositories.story import StoryRepository
from app.services.dedup import compute_story_content_hash
from app.services.story_corpus import story_corpus_item, story_item_id
from app.services.story_paraphrase import (
    BULK_MIGRATION_THRESHOLDS,
    SimilarityThresholds,
    is_paraphrase_match,
    paraphrase_signals,
    thresholds_as_dict,
)

logger = logging.getLogger(__name__)

_MERGE_RETURNING = '"title","situation","task","action","result","metrics","tags"'

#: STAR content fields a merge rewrites on the survivor.
_STAR_FIELDS = ("title", "situation", "task", "action", "result")

#: Fields captured in ``mergeSnapshot.survivor_before`` — everything needed to
#: put the survivor back exactly as it was.
_SNAPSHOT_FIELDS = (
    "id", "title", "situation", "task", "action", "result",
    "metrics", "tags", "createdAt", "updatedAt",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _executing_account() -> dict[str, str]:
    """Who and where the sweep ran as — recorded on every archived row so the
    risk officer's 'cron-account-only execution' condition is auditable after
    the fact, not merely asserted beforehand."""
    try:
        account = getpass.getuser()
    except Exception:  # pragma: no cover - no passwd entry (rare container)
        account = "unknown"
    return {"account": account, "host": socket.gethostname()}


def _plan_merges(
    rows: list[dict[str, Any]], thresholds: SimilarityThresholds
) -> list[dict[str, Any]]:
    """Compute the FULL merge plan without touching the database.

    Pure: takes the user's rows oldest-first, returns one proposal per merge.
    The apply path executes exactly this plan and nothing else, so what a
    human reviews in a dry run is what actually runs — the dry run is not a
    separate, approximate simulation of the write path.

    Each later duplicate folds into the earliest-created row of its group (a
    stable id for anything already referencing it), and that survivor's
    in-memory content is updated as it goes so a THIRD duplicate in the same
    run compares against the just-merged wording, not stale pre-merge text.
    """
    kept: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        survivor = next(
            (k for k in kept if is_paraphrase_match(row, k, thresholds)), None
        )
        if survivor is None:
            kept.append(row)
            continue

        signals = paraphrase_signals(row, survivor)
        survivor_before = {f: survivor.get(f) for f in _SNAPSHOT_FIELDS}
        merged_metrics = {
            **(survivor.get("metrics") or {}),
            **(row.get("metrics") or {}),
        }
        merged_tags = list(
            dict.fromkeys([*(survivor.get("tags") or []), *(row.get("tags") or [])])
        )
        merged_content = {f: row[f] for f in _STAR_FIELDS}
        merged_content["metrics"] = merged_metrics
        merged_content["tags"] = merged_tags

        proposals.append(
            {
                "survivor_id": survivor["id"],
                "survivor_title": survivor_before["title"],
                "duplicate_id": row["id"],
                "duplicate_title": row["title"],
                "signals": signals,
                "survivor_before": survivor_before,
                "merged": merged_content,
            }
        )
        # Mirror the write path in memory (see docstring).
        survivor.update(merged_content)
    return proposals


def merge_duplicate_stories(
    user_id: str,
    *,
    dry_run: bool = False,
    thresholds: SimilarityThresholds = BULK_MIGRATION_THRESHOLDS,
    operator: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    """Merge paraphrase-duplicate ``StoryEntry`` rows for ``user_id``.

    The earliest-created row of a duplicate group SURVIVES and takes the later
    duplicate's wording as the freshest telling of the same achievement;
    ``tags`` and ``metrics`` are UNIONED, never dropped. The duplicate is
    ARCHIVED (soft-deleted, fully restorable) — never deleted.

    ``dry_run=True`` returns the same plan the apply path would execute, with
    the similarity signals behind every pair, and performs ZERO WRITES to
    story data. It is a READ: the rows come from ``list_by_user``, which does
    open a connection (and may run the lazy additive DDL). Nothing below the
    ``if dry_run`` branch — no UPDATE, no archive, no commit of story data —
    is reached.

    Returns ``before_count`` / ``after_count`` / ``merged`` (§8.1(a)).
    ``after_count`` is re-read from the database after the commit;
    ``reconciled`` is False when it does not equal ``before_count - merged``
    (a concurrent write, or a merge that did not land), which is surfaced, not
    swallowed.

    Scoped to ONE user by construction: every row comes from
    ``list_by_user(user_id)`` and every write additionally carries
    ``AND "userId" = %s``.
    """
    rows = sorted(StoryRepository().list_by_user(user_id), key=lambda r: r["createdAt"])
    before_count = len(rows)
    proposals = _plan_merges(rows, thresholds)

    if dry_run:
        # Nothing below this point may touch the DB: no DDL, no connection.
        return {
            "dry_run": True,
            "user_id": user_id,
            "thresholds": thresholds_as_dict(thresholds),
            "before_count": before_count,
            "after_count": before_count,  # a dry run changes nothing
            "merged": 0,
            "would_merge": len(proposals),
            "projected_after_count": before_count - len(proposals),
            "proposed": proposals,
            "generated_at": _now_iso(),
            "batch_id": None,
            "reconciled": True,
            # U-STORY-1 E2: a dry run reconciles no mirror because it moves no
            # row. Reported as real zeros rather than omitted, so a caller
            # never has to guess whether the key's absence meant "none" or
            # "this build predates the reconciliation".
            "mirror_retracted": 0,
            "mirror_refreshed": 0,
        }

    ensure_story_dedup_column()
    ensure_story_archive_columns()
    # U-STORY-1 E2: the mirror is reconciled INSIDE the transaction below, so
    # its lazily-created table must exist BEFORE that transaction opens — the
    # bootstrap takes an advisory-locked connection of its own and must never
    # run nested inside the sweep's.
    corpus_repo = EvidenceCorpusRepository()
    corpus_repo.ensure_table()
    batch = batch_id or uuid.uuid4().hex
    account = _executing_account()
    merged = 0
    mirror_retracted = 0
    mirror_refreshed = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for proposal in proposals:
                content = proposal["merged"]
                new_hash = compute_story_content_hash(
                    user_id, *(content[f] for f in _STAR_FIELDS)
                )
                cur.execute(
                    f'''
                    UPDATE "StoryEntry" SET
                        "title" = %s, "situation" = %s, "task" = %s,
                        "action" = %s, "result" = %s, "metrics" = %s,
                        "tags" = %s, "contentHash" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL
                    RETURNING {_MERGE_RETURNING}
                    ''',
                    (
                        content["title"], content["situation"], content["task"],
                        content["action"], content["result"],
                        json.dumps(content["metrics"]), content["tags"], new_hash,
                        proposal["survivor_id"], user_id,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        "story merge aborted: expected to update exactly 1 "
                        f"surviving row {proposal['survivor_id']!r} for user "
                        f"{user_id!r}, updated {cur.rowcount} — nothing is "
                        "committed"
                    )
                rows_to_dicts(cur)  # drain RETURNING

                snapshot = {
                    "batch_id": batch,
                    "merged_at": _now_iso(),
                    "operator": operator,
                    **account,
                    "thresholds": thresholds_as_dict(thresholds),
                    "signals": proposal["signals"],
                    "merged_into_id": proposal["survivor_id"],
                    # The archived row keeps its OWN content in place; what a
                    # restore additionally needs is the survivor's pre-merge
                    # content, which the UPDATE above just overwrote.
                    "survivor_before": proposal["survivor_before"],
                }
                cur.execute(
                    '''
                    UPDATE "StoryEntry" SET
                        "archivedAt" = NOW(), "mergedIntoId" = %s,
                        "mergeSnapshot" = %s::jsonb, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL
                    ''',
                    (
                        proposal["survivor_id"],
                        json.dumps(snapshot, default=str),
                        proposal["duplicate_id"],
                        user_id,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        "story merge aborted: expected to archive exactly 1 "
                        f"duplicate row {proposal['duplicate_id']!r} for user "
                        f"{user_id!r}, archived {cur.rowcount} — nothing is "
                        "committed"
                    )
                # U-STORY-1 ruling E2 — RECONCILE THE EVIDENCE MIRROR, HERE.
                #
                # ``StoryRepository`` mirrors every story into
                # ``EvidenceCorpusItem`` so the guards can cite it, and this
                # sweep moved rows straight past that mirror. The result was a
                # live-evidence hole in both directions: the archived row's
                # claim kept grounding generated documents even though the user
                # could no longer see the story, and the SURVIVOR's mirror still
                # held its pre-merge wording — stale evidence of exactly the
                # class the retraction fixes, wearing the other row's label.
                #
                # Both writes run on THIS cursor, inside THIS transaction: the
                # sweep's safety property is all-or-nothing with a counted
                # reconciliation, and a mirror write on its own connection would
                # survive a rollback — deleting a user's evidence for a merge
                # that never happened.
                mirror_retracted += corpus_repo.delete_items_with_cursor(
                    cur, user_id, [story_item_id(proposal["duplicate_id"])]
                )
                survivor_item = story_corpus_item(
                    {"id": proposal["survivor_id"], **content}
                )
                if survivor_item is not None:
                    mirror_refreshed += corpus_repo.upsert_many_with_cursor(
                        cur, user_id, [survivor_item]
                    )
                merged += 1
        conn.commit()

    after_count = len(StoryRepository().list_by_user(user_id))
    reconciled = after_count == before_count - merged
    if not reconciled:
        logger.error(
            "merge_duplicate_stories: COUNT RECONCILIATION FAILED for user %s "
            "batch %s — before=%d merged=%d expected_after=%d actual_after=%d",
            user_id, batch, before_count, merged, before_count - merged, after_count,
        )
    logger.info(
        "merge_duplicate_stories: archived %d duplicate row(s) for user %s "
        "(batch %s, before=%d after=%d, reconciled=%s, mirror retracted=%d "
        "refreshed=%d)",
        merged, user_id, batch, before_count, after_count, reconciled,
        mirror_retracted, mirror_refreshed,
    )
    return {
        "dry_run": False,
        "user_id": user_id,
        "thresholds": thresholds_as_dict(thresholds),
        "before_count": before_count,
        "after_count": after_count,
        "merged": merged,
        "proposed": proposals,
        "batch_id": batch,
        "generated_at": _now_iso(),
        "reconciled": reconciled,
        #: U-STORY-1 E2: what this sweep did to the evidence mirror, counted —
        #: an unreported reconciliation is indistinguishable from one that
        #: never ran, and this result IS the sweep's audit record.
        "mirror_retracted": mirror_retracted,
        "mirror_refreshed": mirror_refreshed,
    }


def list_archived_merges(
    user_id: str, *, batch_id: str | None = None
) -> list[dict[str, Any]]:
    """Every archived (merged-away) row for ``user_id``, newest archive first.

    The read side of recoverability: what was merged away, into what, on which
    signals, by which batch and account.
    """
    ensure_story_archive_columns()
    sql = (
        'SELECT "id","userId","title","situation","task","action","result",'
        '"metrics","tags","createdAt","updatedAt","archivedAt","mergedIntoId",'
        '"mergeSnapshot" FROM "StoryEntry" '
        'WHERE "userId" = %s AND "archivedAt" IS NOT NULL'
    )
    params: list[Any] = [user_id]
    if batch_id is not None:
        sql += ' AND "mergeSnapshot"->>\'batch_id\' = %s'
        params.append(batch_id)
    sql += ' ORDER BY "archivedAt" DESC'
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return rows_to_dicts(cur)


def _restore_order_key(row: dict[str, Any]) -> tuple[Any, str]:
    """Total order in which merges were APPLIED to a given survivor.

    ``archivedAt`` alone is NOT sufficient. A whole sweep runs inside ONE
    transaction and PostgreSQL's ``NOW()`` is the transaction timestamp, so
    every row archived by the same batch carries the SAME ``archivedAt`` — two
    duplicates folded into one survivor by one sweep are indistinguishable by
    it, and the SQL ``ORDER BY "archivedAt" DESC`` therefore returns them in
    an arbitrary order. ``mergeSnapshot.merged_at`` is stamped per proposal
    inside the merge loop, so it strictly increases within a batch and breaks
    that tie.

    A row with no usable ``merged_at`` sorts as ``""``, i.e. EQUAL to its
    same-timestamp siblings, which under the ``>=`` test in
    :func:`_blocking_merges` makes such rows mutually blocking: an unknown
    merge order is treated as unsafe, never as safe.
    """
    snapshot = row.get("mergeSnapshot")
    merged_at = ""
    if isinstance(snapshot, dict) and isinstance(snapshot.get("merged_at"), str):
        merged_at = snapshot["merged_at"]
    return (row.get("archivedAt"), merged_at)


def _blocking_merges(
    row: dict[str, Any],
    all_archived: list[dict[str, Any]],
    restoring_ids: set[str],
) -> list[dict[str, Any]]:
    """Archived siblings that must be restored together with ``row``, or first.

    GMV4-story-004 round-2 review finding 2 — silent corruption on a PARTIAL
    restore. If survivor S absorbed D1 (batch B1) and then D2 (batch B2),
    restoring ONLY B1 rewrites S with D1's ``survivor_before`` — S's content
    from before D1, which predates D2's merge entirely. D2's contribution is
    discarded from S while D2 itself stays archived: no error, no
    ``unrestorable`` entry, no warning, and the loss is invisible because the
    only record of it was the survivor's own text.

    The FULL-set restore was always sound (the chain unwinds newest-merge
    first). It is the subset — ``batch_id`` naming one of several batches, or
    ``story_ids`` naming some of a batch's rows — that corrupts. A blocker is
    therefore any OTHER archived row folded into the SAME survivor, at or
    after ``row`` in merge order, that this operation is not also restoring.
    """
    survivor_id = row.get("mergedIntoId")
    if survivor_id is None:
        return []
    key = _restore_order_key(row)
    blockers: list[dict[str, Any]] = []
    for other in all_archived:
        if other["id"] == row["id"] or other["id"] in restoring_ids:
            continue
        if other.get("mergedIntoId") != survivor_id:
            continue
        try:
            at_or_after = _restore_order_key(other) >= key
        except TypeError:  # pragma: no cover — non-comparable timestamps
            at_or_after = True  # unknown order is unsafe, so it blocks
        if at_or_after:
            blockers.append(other)
    return blockers


def restore_merged_stories(
    user_id: str,
    *,
    batch_id: str | None = None,
    story_ids: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Reverse merges: un-archive rows and put their survivors back.

    This is what makes the archive a real recovery mechanism rather than a
    label. Rows are processed NEWEST-MERGE-FIRST — ordered by
    :func:`_restore_order_key`, not by the SQL ``archivedAt DESC`` alone,
    which cannot order two rows archived by the same transaction — so a chain
    of merges into one survivor unwinds in the exact reverse order it was
    applied. Each step un-archives the row and rewrites the survivor with the
    ``survivor_before`` content captured at merge time, recomputing the
    survivor's ``contentHash`` from the restored text.

    Defaults to ``dry_run=True`` for symmetry with the sweep.

    TWO ways a row is refused instead of restored. Both are REPORTED; neither
    is ever silent:

    * ``unrestorable`` — its snapshot holds no complete ``survivor_before``,
      so there is nothing to put back.
    * ``blocked`` — restoring it would discard a LATER merge into the same
      survivor that this operation is not also restoring (finding 2 above).
      A dry run lists these. The APPLY path REFUSES OUTRIGHT and writes
      nothing at all, rather than restoring the unblocked rows and skipping
      these: the refusal names the exact rows to add, and restoring them
      together unwinds the chain correctly.
    """
    ensure_story_dedup_column()
    ensure_story_archive_columns()
    # The full archive is needed even for a subset restore: the blocking check
    # asks about siblings this operation is deliberately leaving out, so it
    # cannot be answered from the filtered set.
    all_archived = list_archived_merges(user_id)
    archived = list_archived_merges(user_id, batch_id=batch_id)
    if story_ids is not None:
        wanted = set(story_ids)
        archived = [r for r in archived if r["id"] in wanted]

    # Pass 1 — which rows even have something to restore. Only these count as
    # "part of this operation" when the blocking check runs: a row that will
    # NOT be written cannot cover for a sibling.
    restorable_rows: list[dict[str, Any]] = []
    unrestorable: list[dict[str, Any]] = []
    for row in archived:
        snapshot = row.get("mergeSnapshot") or {}
        before = snapshot.get("survivor_before") if isinstance(snapshot, dict) else None
        if not isinstance(before, dict) or not all(f in before for f in _STAR_FIELDS):
            unrestorable.append(
                {
                    "story_id": row["id"],
                    "reason": "mergeSnapshot has no complete survivor_before capture",
                }
            )
            continue
        restorable_rows.append(row)

    # Pass 2 — chain safety, then the plan itself, newest merge first.
    restoring_ids = {r["id"] for r in restorable_rows}
    plan: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    ordered = sorted(restorable_rows, key=_restore_order_key, reverse=True)
    for row in ordered:
        blockers = _blocking_merges(row, all_archived, restoring_ids)
        if blockers:
            blocked.append(
                {
                    "story_id": row["id"],
                    "story_title": row["title"],
                    "survivor_id": row["mergedIntoId"],
                    "blocked_by": [b["id"] for b in blockers],
                    "blocked_by_batches": sorted(
                        {
                            str((b.get("mergeSnapshot") or {}).get("batch_id"))
                            for b in blockers
                        }
                    ),
                    "reason": (
                        "restoring this row alone would overwrite survivor "
                        f"{row['mergedIntoId']} with content from BEFORE a later "
                        "merge that stays archived, silently discarding that "
                        "later merge — include the blocking rows in this "
                        "restore so the chain unwinds in order"
                    ),
                }
            )
            continue
        snapshot = row["mergeSnapshot"]
        before = snapshot["survivor_before"]
        plan.append(
            {
                "story_id": row["id"],
                "story_title": row["title"],
                "survivor_id": row["mergedIntoId"],
                "survivor_restored_title": before["title"],
                # Content identity of exactly what the survivor is rewritten
                # to. Lets a reviewed restore plan be digest-verified against
                # the live archive the same way a merge plan is.
                "survivor_restored_hash": compute_story_content_hash(
                    user_id, *(before[f] for f in _STAR_FIELDS)
                ),
                "batch_id": snapshot.get("batch_id"),
            }
        )

    if dry_run:
        return {
            "dry_run": True,
            "user_id": user_id,
            "restorable": len(plan),
            "restored": 0,
            "plan": plan,
            "unrestorable": unrestorable,
            "blocked": blocked,
            # U-STORY-1 E2: a dry run republishes nothing because it restores
            # nothing. Real zeros, never an omitted key.
            "mirror_republished": 0,
            "mirror_refreshed": 0,
        }

    if blocked:
        raise RuntimeError(
            "story restore REFUSED: "
            + "; ".join(
                f"{b['story_id']} is blocked by {b['blocked_by']} "
                f"(batches {b['blocked_by_batches']}) on survivor "
                f"{b['survivor_id']}"
                for b in blocked
            )
            + " — restoring these rows without their later merges would "
            "silently discard content from the survivor. Re-run the restore "
            "including the blocking rows. NOTHING WAS WRITTEN."
        )

    by_id = {row["id"]: row for row in restorable_rows}
    before_count = len(StoryRepository().list_by_user(user_id))
    restored = 0
    mirror_republished = 0
    mirror_refreshed = 0
    # U-STORY-1 E2: same rule as the merge path — the mirror is reconciled
    # inside the restore's own transaction, so its lazy table bootstrap has to
    # happen first, on its own advisory-locked connection.
    corpus_repo = EvidenceCorpusRepository()
    corpus_repo.ensure_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            for entry in plan:
                row = by_id[entry["story_id"]]
                before = row["mergeSnapshot"]["survivor_before"]
                survivor_hash = entry["survivor_restored_hash"]
                cur.execute(
                    '''
                    UPDATE "StoryEntry" SET
                        "title" = %s, "situation" = %s, "task" = %s,
                        "action" = %s, "result" = %s, "metrics" = %s,
                        "tags" = %s, "contentHash" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    ''',
                    (
                        before["title"], before["situation"], before["task"],
                        before["action"], before["result"],
                        json.dumps(before.get("metrics") or {}),
                        before.get("tags") or [], survivor_hash,
                        row["mergedIntoId"], user_id,
                    ),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        "story restore aborted: survivor "
                        f"{row['mergedIntoId']!r} for user {user_id!r} did not "
                        f"resolve to exactly 1 row (got {cur.rowcount}) — "
                        "nothing is committed"
                    )
                cur.execute(
                    'UPDATE "StoryEntry" SET "archivedAt" = NULL, '
                    '"mergedIntoId" = NULL, "updatedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NOT NULL',
                    (row["id"], user_id),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(
                        f"story restore aborted: archived row {row['id']!r} for "
                        f"user {user_id!r} did not un-archive (got "
                        f"{cur.rowcount}) — nothing is committed"
                    )
                # U-STORY-1 ruling E2, the reverse direction. The restored row
                # is live again, so it must be citable again: without this its
                # own true, user-visible content reads as unsupported evidence
                # to the fabrication and claim guards. The survivor is
                # re-mirrored from the SAME ``before`` snapshot its row was just
                # rewritten with, so the corpus and the story bank tell one
                # story. Both writes are on this transaction's cursor.
                mirror_republished += corpus_repo.upsert_many_with_cursor(
                    cur, user_id, [item for item in [story_corpus_item(row)] if item]
                )
                survivor_item = story_corpus_item(
                    {"id": row["mergedIntoId"], **before}
                )
                if survivor_item is not None:
                    mirror_refreshed += corpus_repo.upsert_many_with_cursor(
                        cur, user_id, [survivor_item]
                    )
                restored += 1
        conn.commit()

    after_count = len(StoryRepository().list_by_user(user_id))
    # Un-archiving N rows must raise the LIVE count by exactly N. Symmetric
    # with the merge path's reconciliation, and the same reason: a count that
    # does not add up means a concurrent write or a restore that did not land,
    # and it must be surfaced rather than assumed away.
    reconciled = after_count == before_count + restored
    if not reconciled:
        logger.error(
            "restore_merged_stories: COUNT RECONCILIATION FAILED for user %s "
            "batch %s — before=%d restored=%d expected_after=%d actual_after=%d",
            user_id, batch_id, before_count, restored,
            before_count + restored, after_count,
        )
    logger.info(
        "restore_merged_stories: restored %d archived row(s) for user %s "
        "(batch %s, before=%d after=%d, reconciled=%s, mirror republished=%d "
        "refreshed=%d)",
        restored, user_id, batch_id, before_count, after_count, reconciled,
        mirror_republished, mirror_refreshed,
    )
    return {
        "dry_run": False,
        "user_id": user_id,
        "restorable": len(plan),
        "restored": restored,
        "plan": plan,
        "unrestorable": unrestorable,
        "blocked": blocked,
        "before_count": before_count,
        "after_count": after_count,
        "reconciled": reconciled,
        #: U-STORY-1 E2, counted for the same reason the merge path counts it.
        "mirror_republished": mirror_republished,
        "mirror_refreshed": mirror_refreshed,
    }
