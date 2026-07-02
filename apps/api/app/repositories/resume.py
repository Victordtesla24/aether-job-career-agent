"""Resume repository — raw psycopg2 against the Prisma ``Resume`` table (P2-S05)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_RESUME_COLUMNS = (
    '"id", "userId", "version", "label", "sections", "sourceJobId", '
    '"parentId", "formatHash", "createdAt", "updatedAt"'
)


class ResumeRepository:
    """CRUD over the versioned ``Resume`` table."""

    def create(
        self,
        user_id: str,
        sections: dict[str, Any],
        format_hash: str,
        *,
        label: str | None = None,
        version: int = 1,
        parent_id: str | None = None,
        source_job_id: str | None = None,
    ) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Resume" (
                        "id", "userId", "version", "label", "sections",
                        "sourceJobId", "parentId", "formatHash", "updatedAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING {_RESUME_COLUMNS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        version,
                        label,
                        json.dumps(sections),
                        source_job_id,
                        parent_id,
                        format_hash,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def get_by_id(self, resume_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RESUME_COLUMNS} FROM "Resume" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (resume_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_base(self, user_id: str) -> dict[str, Any] | None:
        """The user's base (root) resume: no parent, lowest version first."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RESUME_COLUMNS} FROM "Resume" '
                    'WHERE "userId" = %s AND "parentId" IS NULL '
                    'ORDER BY "version" ASC, "createdAt" ASC LIMIT 1',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RESUME_COLUMNS} FROM "Resume" '
                    'WHERE "userId" = %s ORDER BY "createdAt" DESC',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def next_version(self, user_id: str) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COALESCE(MAX("version"), 0) + 1 FROM "Resume" WHERE "userId" = %s',
                    (user_id,),
                )
                return int(cur.fetchone()[0])
