"""Story bank repository — ``StoryEntry`` table (P2-S09)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "title", "situation", "task", "action", "result", '
    '"metrics", "tags", "createdAt", "updatedAt"'
)


class StoryRepository:
    def create(self, user_id: str, story: dict[str, Any]) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "StoryEntry"
                        ("id", "userId", "title", "situation", "task", "action",
                         "result", "metrics", "tags", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
        allowed = ("title", "situation", "task", "action", "result", "metrics", "tags")
        sets, params = [], []
        for key in allowed:
            if key in story:
                sets.append(f'"{key}" = %s')
                value = story[key]
                params.append(json.dumps(value) if key == "metrics" else value)
        if not sets:
            return self.get_by_id(story_id, user_id)
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
