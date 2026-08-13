"""Resume repository — raw psycopg2 against the Prisma ``Resume`` table (P2-S05).

BASELINE IMMUTABILITY (U2a / R-F1). ``originalFile``/``originalFilename``/
``originalContentType`` hold the exact bytes a user uploaded and are written
EXACTLY ONCE, by :meth:`ResumeRepository.create`. No other statement in this
repository — and no other module in the codebase — may name those columns in an
``UPDATE``: the baseline document is the single source of truth every tailoring
run derives from, and rewriting it would silently destroy the user's own file.
``formatHash`` is the SHA-256 of exactly those bytes, so it is immutable for the
same reason and is guarded by :class:`BaselineImmutableError` in
:meth:`update_sections` (the only setter that can touch it).
"""
from __future__ import annotations

import json
from typing import Any

import psycopg2

from app.db import ensure_resume_columns, get_connection, new_id, rows_to_dicts

#: Columns returned by every read/write here. ``originalFile`` is deliberately
#: EXCLUDED: it is a bytea blob (up to 10MB) that is not JSON-serialisable and
#: has exactly one consumer, ``GET /resumes/{id}/original``, which fetches it
#: through :meth:`ResumeRepository.get_original_file`. Selecting it here would
#: load every stored résumé document into memory on a plain list/get.
_RESUME_COLUMNS = (
    '"id", "userId", "version", "label", "sections", "sourceJobId", '
    '"parentId", "formatHash", "approvalStatus", "createdAt", "updatedAt"'
)


class BaselineImmutableError(RuntimeError):
    """Raised when a caller tries to rewrite a stored baseline's identity.

    A résumé that has ``originalFile`` bytes stored IS the user's uploaded
    document. Its ``formatHash`` is the SHA-256 of those bytes, so changing one
    without the other would make the record lie about what it holds — and the
    bytes themselves are never rewritable at all. Raising (rather than silently
    ignoring the write) keeps the violation visible instead of producing a
    record whose hash no longer describes its content.
    """

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
        original_file: bytes | None = None,
        original_filename: str | None = None,
        original_content_type: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new résumé version.

        ``original_file`` (U2a / R-F1) is the EXACT uploaded document — the only
        write of that column anywhere. ``format_hash`` must be the full SHA-256
        of those same bytes when they are supplied, so the pair is consistent
        from birth and can then be treated as immutable.
        """
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Resume" (
                        "id", "userId", "version", "label", "sections",
                        "sourceJobId", "parentId", "formatHash", "approvalStatus",
                        "originalFile", "originalFilename", "originalContentType",
                        "updatedAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                        psycopg2.Binary(original_file) if original_file is not None else None,
                        original_filename,
                        original_content_type,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def update_sections(
        self, resume_id: str, user_id: str, sections: dict[str, Any], format_hash: str
    ) -> dict[str, Any] | None:
        """Replace a resume's sections/formatHash (used to heal empty bases).

        BASELINE IMMUTABILITY (U2a / R-F1): this is the only setter that can
        touch ``formatHash``, and it must never repoint a stored baseline. When
        the row holds ``originalFile`` bytes its ``formatHash`` is the SHA-256
        of exactly those bytes, so a DIFFERENT hash is rejected with
        :class:`BaselineImmutableError` rather than written. Re-passing the
        row's own hash is allowed and is what the real caller does — the
        bullet-healing path in ``TailorAgent`` passes ``base["formatHash"]``
        straight back, so healing keeps working untouched. ``originalFile`` /
        ``originalFilename`` / ``originalContentType`` are absent from the
        ``SET`` clause by design: the uploaded document itself is never
        rewritable by any code path.
        """
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "formatHash", "originalFile" IS NOT NULL AS "hasOriginal" '
                    'FROM "Resume" WHERE "id" = %s AND "userId" = %s',
                    (resume_id, user_id),
                )
                current = cur.fetchone()
                if current is None:
                    return None
                if current[1] and current[0] != format_hash:
                    raise BaselineImmutableError(
                        f"Resume {resume_id} stores its original upload bytes; its "
                        f"formatHash is the SHA-256 of those bytes and cannot be "
                        f"changed (attempted {format_hash!r}, stored {current[0]!r})."
                    )
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

    def get_original_file(self, resume_id: str, user_id: str) -> dict[str, Any] | None:
        """The résumé's stored original upload, or ``None`` when there is no such row.

        Returns ``{"originalFile": bytes | None, "originalFilename": str | None,
        "originalContentType": str | None}``. A row that exists but has
        ``originalFile is None`` is the honest, expected state for every résumé
        created before U2a (bytes were never stored) and for every
        JSON-ingested/tailored version (there was no uploaded file) — callers
        must report that gap, never synthesise a document to fill it.
        """
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "originalFile", "originalFilename", "originalContentType" '
                    'FROM "Resume" WHERE "id" = %s AND "userId" = %s',
                    (resume_id, user_id),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return {
            # psycopg2 hands bytea back as a memoryview — materialise it so the
            # response body is plain bytes.
            "originalFile": bytes(row[0]) if row[0] is not None else None,
            "originalFilename": row[1],
            "originalContentType": row[2],
        }

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
        """The user's baseline (root) résumé — same selection rule as the
        Settings "original stored" badge (apps/api/app/routers/workspaces.py,
        ORCHESTRATOR RULING resolving FE re-review NEW-2/F-2): among the
        user's root résumés (``parentId IS NULL``), prefer the newest one
        that has its original upload bytes stored, so a re-upload (the exact
        remedy the Settings panel's honest-copy instructs) becomes the base
        every subsequent tailoring/grounding call derives from immediately —
        not the FIRST upload ever made, which the old ``ORDER BY "version"
        ASC`` picked forever regardless of how many fresher root uploads
        followed it.

        Falls back to the newest root résumé overall when NONE of the user's
        root résumés has stored bytes (every account created before this
        column existed, until it re-uploads) — this method feeds tailoring
        and cover-letter grounding via ``sections.raw_text``, which every
        résumé row has independent of whether its original bytes were kept,
        so an account with no byte-stored root row must still resolve to its
        real base résumé here rather than a dishonest "no résumé on file".
        """
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RESUME_COLUMNS} FROM "Resume" '
                    'WHERE "userId" = %s AND "parentId" IS NULL '
                    'ORDER BY ("originalFile" IS NOT NULL) DESC, "createdAt" DESC, '
                    '"version" DESC LIMIT 1',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def get_tailored_for_job(self, user_id: str, job_id: str) -> dict[str, Any] | None:
        """Newest resume version already tailored for ``job_id`` (its
        ``sourceJobId``), if one exists — same correlated lookup the
        promotion paths use (jobs._resume_for_apply /
        applications.submit_application's resume resolution): newest
        version for the job wins.
        """
        ensure_resume_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_RESUME_COLUMNS} FROM "Resume" '
                    'WHERE "userId" = %s AND "sourceJobId" = %s '
                    'ORDER BY "version" DESC LIMIT 1',
                    (user_id, job_id),
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
