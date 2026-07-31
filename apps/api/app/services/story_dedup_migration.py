"""GM2-STORY §7.3.2 — one-time bulk paraphrase de-dup for the Story Bank.

``StoryRepository.create`` (see ``app/services/story_paraphrase.py``) now
catches a paraphrase duplicate going FORWARD, at create time. It does nothing
for the duplicates that already accumulated in the DB before that fix shipped
— the evidence report's real 34-of-36-stories-are-paraphrases case
(``uat/reports/evidence/gold-master-v2/screens/stories-screen-test.md``).

:func:`merge_duplicate_stories` is the operator-triggered, idempotent sweep
that cleans up that EXISTING data for one user. It reuses the exact same
similarity primitives ``StoryRepository.create`` uses
(:mod:`app.services.story_paraphrase` — never a second, hand-rolled
comparison, per §13.1), with the deliberately more permissive
``BULK_MIGRATION_THRESHOLDS`` preset (see that module's docstring for the
rationale: a one-time, reviewed, logged sweep over existing data can afford a
wider net than a live, silent create-time merge).

Run it (e.g. from a one-off ops script or an admin action) as::

    from app.services.story_dedup_migration import merge_duplicate_stories
    result = merge_duplicate_stories(user_id=some_user_id)
    # {"merged": <int>}

Idempotent: a second run over an already-merged set finds nothing left to
merge and returns ``{"merged": 0}`` — no persisted "already ran" marker is
needed, because once duplicates are actually merged away there is nothing
left in the DB for a re-run to find.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db import ensure_story_dedup_column, get_connection, rows_to_dicts
from app.repositories.story import StoryRepository
from app.services.dedup import compute_story_content_hash
from app.services.story_paraphrase import BULK_MIGRATION_THRESHOLDS, is_paraphrase_match

logger = logging.getLogger(__name__)

_MERGE_RETURNING = '"title","situation","task","action","result","metrics","tags"'


def merge_duplicate_stories(user_id: str) -> dict[str, Any]:
    """Merge paraphrase-duplicate ``StoryEntry`` rows for ``user_id`` in place.

    Processes the user's stories oldest-first: the earliest-created row of a
    duplicate group survives (a stable id for anything that already
    referenced it) and each later duplicate's wording is folded into it as
    the freshest telling of the same achievement — mirroring the merge
    ``StoryRepository.create`` performs at create time. Tags and metrics are
    MERGED (union), never dropped. Every merge deletes the duplicate row, so
    the total ``StoryEntry`` count for this user drops by exactly the
    reported ``merged`` count.
    """
    ensure_story_dedup_column()
    rows = sorted(StoryRepository().list_by_user(user_id), key=lambda r: r["createdAt"])

    kept: list[dict[str, Any]] = []
    merged = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for row in rows:
                survivor = next(
                    (
                        k
                        for k in kept
                        if is_paraphrase_match(row, k, BULK_MIGRATION_THRESHOLDS)
                    ),
                    None,
                )
                if survivor is None:
                    kept.append(row)
                    continue

                merged_metrics = {
                    **(survivor.get("metrics") or {}),
                    **(row.get("metrics") or {}),
                }
                merged_tags = list(
                    dict.fromkeys(
                        [*(survivor.get("tags") or []), *(row.get("tags") or [])]
                    )
                )
                new_hash = compute_story_content_hash(
                    user_id, row["title"], row["situation"], row["task"],
                    row["action"], row["result"],
                )
                cur.execute(
                    f'''
                    UPDATE "StoryEntry" SET
                        "title" = %s, "situation" = %s, "task" = %s,
                        "action" = %s, "result" = %s, "metrics" = %s,
                        "tags" = %s, "contentHash" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_MERGE_RETURNING}
                    ''',
                    (
                        row["title"], row["situation"], row["task"],
                        row["action"], row["result"],
                        json.dumps(merged_metrics), merged_tags, new_hash,
                        survivor["id"],
                    ),
                )
                updated = rows_to_dicts(cur)[0]
                # Keep the in-memory "kept" record fresh so a THIRD duplicate
                # in the same run compares against the just-merged content,
                # not the survivor's stale pre-merge wording.
                survivor.update(updated)
                cur.execute('DELETE FROM "StoryEntry" WHERE "id" = %s', (row["id"],))
                merged += 1
        conn.commit()

    logger.info(
        "merge_duplicate_stories: merged %d duplicate row(s) for user %s",
        merged, user_id,
    )
    return {"merged": merged}
