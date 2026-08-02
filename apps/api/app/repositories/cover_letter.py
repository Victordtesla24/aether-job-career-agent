"""Cover letter repository (P2-S06).

Cover letters are stored on the ``Application`` row (``coverLetter`` column,
status ``draft``) — the Prisma schema models a letter as part of a draft
application rather than a standalone table, which keeps the submit pipeline
(resume + letter + answers) in one aggregate.
"""
from __future__ import annotations

import json
from typing import Any

from app.db import (
    ensure_cover_letter_quality_columns,
    get_connection,
    new_id,
    rows_to_dicts,
)

_COLUMNS = (
    '"id", "userId", "jobId", "resumeId", "status", "coverLetter", '
    '"coverLetterQuality", "createdAt", "updatedAt"'
)

# Read paths join the Job row so cards can always show a real title/company —
# the /jobs list excludes applied/archived jobs, so the web app cannot resolve
# every letter's job client-side (P1-10b).
_READ_COLUMNS = (
    'a."id", a."userId", a."jobId", a."resumeId", a."status", a."coverLetter", '
    'a."coverLetterQuality", '
    'a."createdAt", a."updatedAt", j."title" AS "jobTitle", j."company" AS "jobCompany"'
)


class CoverLetterRepository:
    def create(
        self,
        user_id: str,
        job_id: str,
        resume_id: str,
        cover_letter: str,
        quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Insert a letter version (each draft/refine is its own row — the
        studio's version history is built from these). Duplicate-card
        prevention lives one layer up: the approval queue reuses the pending
        request per job, and the tracker shows only the newest draft per job.

        ``quality`` (W-TAILOR-CONVERGE item 4) is the deterministic
        :class:`app.services.cover_letter_quality.CoverLetterQuality`
        breakdown of the letter being stored, plus the per-pass history behind
        it — persisted so a reload shows the same before/after the run
        reported. ``None`` (the default) writes SQL NULL, which is the honest
        value for a caller that measured nothing; a score is never invented
        here.
        """
        ensure_cover_letter_quality_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Application"
                        ("id", "userId", "jobId", "resumeId", "coverLetter",
                         "coverLetterQuality", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    RETURNING {_COLUMNS}
                    ''',
                    (
                        new_id(), user_id, job_id, resume_id, cover_letter,
                        json.dumps(quality) if quality is not None else None,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def get_by_id(self, letter_id: str, user_id: str) -> dict[str, Any] | None:
        ensure_cover_letter_quality_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_READ_COLUMNS} FROM "Application" a '
                    'LEFT JOIN "Job" j ON j."id" = a."jobId" '
                    'WHERE a."id" = %s AND a."userId" = %s '
                    'AND a."coverLetter" IS NOT NULL',
                    (letter_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        ensure_cover_letter_quality_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_READ_COLUMNS} FROM "Application" a '
                    'LEFT JOIN "Job" j ON j."id" = a."jobId" '
                    'WHERE a."userId" = %s AND a."coverLetter" IS NOT NULL '
                    'ORDER BY a."createdAt" DESC',
                    (user_id,),
                )
                return rows_to_dicts(cur)
