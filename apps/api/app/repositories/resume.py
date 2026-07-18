"""Resume repository — raw psycopg2 against the Prisma ``Resume`` table (P2-S05)."""
from __future__ import annotations

import json
from typing import Any

from app.db import ensure_resume_columns, get_connection, new_id, rows_to_dicts

_RESUME_COLUMNS = (
    '"id", "userId", "version", "label", "sections", "sourceJobId", '
    '"parentId", "formatHash", "approvalStatus", "createdAt", "updatedAt"'
)

#: Valid human-review states of a résumé version. ``approved`` is the default so
#: every pre-existing version (base + historical tailored) stays authoritative
#: and downloadable; a freshly tailored child version is created ``pending`` and
#: flips to ``approved``/``rejected`` when its ApprovalRequest is resolved
#: (MV-resume-studio-001).
RESUME_APPROVAL_STATES = frozenset({"approved", "pending", "rejected"})


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
        approval_status: str = "approved",
    ) -> dict[str, Any]:
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Resume" (
                        "id", "userId", "version", "label", "sections",
                        "sourceJobId", "parentId", "formatHash", "approvalStatus",
                        "updatedAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                        approval_status,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def set_approval_status(
        self, resume_id: str, user_id: str, status: str
    ) -> dict[str, Any] | None:
        """Set a résumé version's human-review state (MV-resume-studio-001).

        Owner-scoped and validated against :data:`RESUME_APPROVAL_STATES`. Called
        when the version's linked tailor ApprovalRequest is approved/rejected so a
        tailored version stays ``pending`` until a human signs off — no longer a
        decorative flag."""
        if status not in RESUME_APPROVAL_STATES:
            raise ValueError(f"Invalid résumé approval status '{status}'")
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "Resume"
                    SET "approvalStatus" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_RESUME_COLUMNS}
                    ''',
                    (status, resume_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def update_sections(
        self, resume_id: str, user_id: str, sections: dict[str, Any], format_hash: str
    ) -> dict[str, Any] | None:
        """Replace a resume's sections/formatHash (used to heal empty bases)."""
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "Resume"
                    SET "sections" = %s, "formatHash" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_RESUME_COLUMNS}
                    ''',
                    (json.dumps(sections), format_hash, resume_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def get_by_id(self, resume_id: str, user_id: str) -> dict[str, Any] | None:
        ensure_resume_columns()
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
        ensure_resume_columns()
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
        ensure_resume_columns()
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
