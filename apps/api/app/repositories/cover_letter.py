"""Cover letter repository (P2-S06).

Cover letters are stored on the ``Application`` row (``coverLetter`` column,
status ``draft``) — the Prisma schema models a letter as part of a draft
application rather than a standalone table, which keeps the submit pipeline
(resume + letter + answers) in one aggregate.
"""
from __future__ import annotations

from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

_COLUMNS = (
    '"id", "userId", "jobId", "resumeId", "status", "coverLetter", '
    '"createdAt", "updatedAt"'
)


class CoverLetterRepository:
    def create(
        self, user_id: str, job_id: str, resume_id: str, cover_letter: str
    ) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Application"
                        ("id", "userId", "jobId", "resumeId", "coverLetter", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING {_COLUMNS}
                    ''',
                    (new_id(), user_id, job_id, resume_id, cover_letter),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def get_by_id(self, letter_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "Application" '
                    'WHERE "id" = %s AND "userId" = %s AND "coverLetter" IS NOT NULL',
                    (letter_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "Application" '
                    'WHERE "userId" = %s AND "coverLetter" IS NOT NULL '
                    'ORDER BY "createdAt" DESC',
                    (user_id,),
                )
                return rows_to_dicts(cur)
