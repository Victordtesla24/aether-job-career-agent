"""Story bank repository — ``StoryEntry`` table (P2-S09).

G-P4-STORY-DEDUP-004: ``create`` hashes the five STAR content fields + userId
into a ``contentHash`` and returns the existing row instead of inserting when
that hash is already present, and ``update`` refreshes the hash whenever a STAR
field changes. This stops both re-run duplicates from the story-extractor agent
and double-saves from the REST create endpoint.

``contentHash`` is INTERNAL and is deliberately ABSENT from ``_COLUMNS`` — the
single column list every read/write path returns. Never selecting it is what
keeps the insert path and the dedup-hit path returning the SAME response shape
and keeps the sha256 out of API responses at the source (the router strips it
again as defence in depth; see ``routers/stories.py::_INTERNAL_COLUMNS``).
"""
from __future__ import annotations

import json
from typing import Any

from app.db import ensure_story_dedup_column, get_connection, new_id, rows_to_dicts
from app.services.dedup import compute_story_content_hash
from app.services.story_paraphrase import CREATE_TIME_THRESHOLDS, best_paraphrase_match

#: Client-safe columns — the internal ``contentHash`` is NEVER selected.
_COLUMNS = (
    '"id", "userId", "title", "situation", "task", "action", "result", '
    '"metrics", "tags", "createdAt", "updatedAt"'
)

#: STAR fields that constitute a story's content identity (drive the hash).
_STAR_FIELDS = ("title", "situation", "task", "action", "result")


class StoryRepository:
    def create(self, user_id: str, story: dict[str, Any]) -> dict[str, Any]:
        """Insert a story, or MERGE it into an existing matching one.

        Two dedup layers, checked in order:

        1. EXACT match — an identical sha256 of the five STAR fields
           (``contentHash``). NOT an error and NOT a silent drop: the caller
           gets back the row that already holds this exact content, in the
           same shape an insert returns, so ``POST /stories`` stays
           idempotent for identical content instead of growing the Story
           Bank a duplicate per double-click.
        2. PARAPHRASE match (GM2-STORY-001/002, §7.3.1) — a reworded
           re-telling of the SAME achievement (title + achievement keyword
           similarity, ``app.services.story_paraphrase``). Verified live: 34
           of the owner's 36 real stories were paraphrase re-tellings of only
           8 distinct achievements that the exact-hash check alone let
           through as brand-new rows every time. On a paraphrase match the
           EXISTING row is UPDATED to the new (freshest) wording — tags and
           metrics are MERGED (union), never dropped — and returned; nothing
           is inserted.
        """
        ensure_story_dedup_column()
        content_hash = compute_story_content_hash(
            user_id, *(story[f] for f in _STAR_FIELDS)
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id" FROM "StoryEntry" '
                    'WHERE "userId" = %s AND "contentHash" = %s LIMIT 1',
                    (user_id, content_hash),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        f'SELECT {_COLUMNS} FROM "StoryEntry" WHERE "id" = %s',
                        (existing[0],),
                    )
                    return rows_to_dicts(cur)[0]

                cur.execute(
                    'SELECT "id","title","situation","task","action","result",'
                    '"metrics","tags" FROM "StoryEntry" WHERE "userId" = %s',
                    (user_id,),
                )
                candidates = rows_to_dicts(cur)
                match = best_paraphrase_match(story, candidates, CREATE_TIME_THRESHOLDS)
                if match is not None:
                    merged_metrics = {
                        **(match.get("metrics") or {}),
                        **(story.get("metrics") or {}),
                    }
                    merged_tags = list(
                        dict.fromkeys(
                            [*(match.get("tags") or []), *(story.get("tags") or [])]
                        )
                    )
                    merged_hash = compute_story_content_hash(
                        user_id, *(story[f] for f in _STAR_FIELDS)
                    )
                    cur.execute(
                        f'''
                        UPDATE "StoryEntry" SET
                            "title" = %s, "situation" = %s, "task" = %s,
                            "action" = %s, "result" = %s, "metrics" = %s,
                            "tags" = %s, "contentHash" = %s, "updatedAt" = NOW()
                        WHERE "id" = %s
                        RETURNING {_COLUMNS}
                        ''',
                        (
                            story["title"], story["situation"], story["task"],
                            story["action"], story["result"],
                            json.dumps(merged_metrics), merged_tags, merged_hash,
                            match["id"],
                        ),
                    )
                    rows = rows_to_dicts(cur)
                    conn.commit()
                    return rows[0]

                cur.execute(
                    f'''
                    INSERT INTO "StoryEntry"
                        ("id", "userId", "title", "situation", "task", "action",
                         "result", "metrics", "tags", "contentHash", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING {_COLUMNS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        story["title"],
                        story["situation"],
                        story["task"],
                        story["action"],
                        story["result"],
                        json.dumps(story.get("metrics") or {}),
                        story.get("tags") or [],
                        content_hash,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "StoryEntry" WHERE "userId" = %s '
                    'ORDER BY "createdAt" DESC',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def get_by_id(self, story_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "StoryEntry" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (story_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update(self, story_id: str, user_id: str, story: dict[str, Any]) -> dict[str, Any] | None:
        # The column is written below whenever a STAR field moves, so the lazy
        # DDL MUST be ensured here too — not only in ``create``. Skipping it was
        # WIP-BRANCH-AUDIT-2026-07-29 blocker #2: the first PUT on a schema that
        # had never run the DDL raised UndefinedColumn -> HTTP 500.
        ensure_story_dedup_column()
        allowed = ("title", "situation", "task", "action", "result", "metrics", "tags")
        sets, params = [], []
        changed: set[str] = set()
        for key in allowed:
            if key in story:
                sets.append(f'"{key}" = %s')
                value = story[key]
                params.append(json.dumps(value) if key == "metrics" else value)
                changed.add(key)
        if not sets:
            return self.get_by_id(story_id, user_id)
        # Refresh the content identity ONLY when a STAR field actually moved —
        # a tags/metrics-only edit is decoration and must leave the identity
        # (and therefore future dedup behaviour) untouched.
        if changed & set(_STAR_FIELDS):
            current = self.get_by_id(story_id, user_id)
            if current is None:
                return None
            sets.append('"contentHash" = %s')
            params.append(
                compute_story_content_hash(
                    user_id,
                    *(story.get(f, current[f]) for f in _STAR_FIELDS),
                )
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "StoryEntry" SET {", ".join(sets)}, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_COLUMNS}
                    ''',
                    (*params, story_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def delete(self, story_id: str, user_id: str) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "StoryEntry" WHERE "id" = %s AND "userId" = %s',
                    (story_id, user_id),
                )
                deleted = cur.rowcount
            conn.commit()
        return deleted > 0
