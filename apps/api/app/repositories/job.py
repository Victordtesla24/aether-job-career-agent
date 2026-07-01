"""Job repository (P2-S02): persistence for discovered jobs.

Raw ``psycopg2`` against the Prisma-migrated ``Job`` table (DECISIONS D-0013).
Ids use the same ``cuid`` scheme Prisma applies client-side, and ``updatedAt``
is set explicitly on every write (the column has no DB default).

Idempotency
-----------
``create`` upserts on ``(userId, sourceUrl)``. Re-discovering a posting refreshes
its descriptive fields but never clobbers pipeline state (``status``,
``fitScore``, ``atsScore``, ``saved``), so scoring/user actions survive re-runs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from cuid import cuid
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json, RealDictCursor

from app.services.discovery.base_adapter import JobRaw

# Columns selected for every ``Job`` read, in a stable order.
_COLUMNS = (
    '"id", "userId", "title", "company", "location", "remote", "description", '
    '"requirements", "source", "sourceUrl", "status", "fitScore", "atsScore", '
    '"saved", "createdAt", "updatedAt"'
)


@dataclass(frozen=True)
class Job:
    """A persisted job posting (snake_case mirror of the ``Job`` row)."""

    id: str
    user_id: str
    title: str
    company: str
    location: Optional[str]
    remote: bool
    description: str
    requirements: list[str]
    source: str
    source_url: Optional[str]
    status: str
    fit_score: Optional[float]
    ats_score: Optional[float]
    saved: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Job":
        """Build a :class:`Job` from a ``RealDictCursor`` row."""
        requirements = row.get("requirements")
        if requirements is None:
            requirements = []
        return cls(
            id=row["id"],
            user_id=row["userId"],
            title=row["title"],
            company=row["company"],
            location=row["location"],
            remote=row["remote"],
            description=row["description"],
            requirements=list(requirements),
            source=row["source"],
            source_url=row["sourceUrl"],
            status=row["status"],
            fit_score=row["fitScore"],
            ats_score=row["atsScore"],
            saved=row["saved"],
            created_at=row["createdAt"],
            updated_at=row["updatedAt"],
        )


class JobRepository:
    """Data-access for the ``Job`` table."""

    def __init__(self, conn: PgConnection) -> None:
        self._conn = conn

    # -- writes ----------------------------------------------------------------

    def create(self, user_id: str, job_raw: JobRaw) -> Job:
        """Upsert a discovered job on ``(userId, sourceUrl)`` (idempotent)."""
        source_url = job_raw.get("sourceUrl")
        existing = (
            self._get_by_source_url(user_id, source_url) if source_url else None
        )
        if existing is not None:
            return self._refresh_descriptive(existing.id, job_raw)
        return self._insert(user_id, job_raw)

    def _insert(self, user_id: str, job_raw: JobRaw) -> Job:
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                INSERT INTO "Job" (
                    "id", "userId", "title", "company", "location", "remote",
                    "description", "requirements", "source", "sourceUrl",
                    "status", "saved", "createdAt", "updatedAt"
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'discovered', FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                RETURNING {_COLUMNS};
                """,
                (
                    cuid(),
                    user_id,
                    job_raw["title"],
                    job_raw["company"],
                    job_raw.get("location") or None,
                    bool(job_raw.get("remote", False)),
                    job_raw.get("description", ""),
                    Json(list(job_raw.get("requirements") or [])),
                    job_raw["source"],
                    job_raw.get("sourceUrl"),
                ),
            )
            row = cur.fetchone()
        self._conn.commit()
        return Job.from_row(row)

    def _refresh_descriptive(self, job_id: str, job_raw: JobRaw) -> Job:
        """Update descriptive fields only; preserve pipeline/user state."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE "Job"
                SET "title" = %s,
                    "company" = %s,
                    "location" = %s,
                    "remote" = %s,
                    "description" = %s,
                    "requirements" = %s,
                    "updatedAt" = CURRENT_TIMESTAMP
                WHERE "id" = %s
                RETURNING {_COLUMNS};
                """,
                (
                    job_raw["title"],
                    job_raw["company"],
                    job_raw.get("location") or None,
                    bool(job_raw.get("remote", False)),
                    job_raw.get("description", ""),
                    Json(list(job_raw.get("requirements") or [])),
                    job_id,
                ),
            )
            row = cur.fetchone()
        self._conn.commit()
        return Job.from_row(row)

    def update_status(self, job_id: str, status: str) -> Job:
        """Set the lifecycle ``status`` for a job."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE "Job"
                SET "status" = %s::"JobStatus", "updatedAt" = CURRENT_TIMESTAMP
                WHERE "id" = %s
                RETURNING {_COLUMNS};
                """,
                (status, job_id),
            )
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            raise LookupError(f"Job {job_id!r} not found")
        return Job.from_row(row)

    def update_fit_score(
        self, job_id: str, fit_score: float, ats_score: float
    ) -> Job:
        """Record the fit/ATS scores produced by the scoring slice."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE "Job"
                SET "fitScore" = %s, "atsScore" = %s,
                    "updatedAt" = CURRENT_TIMESTAMP
                WHERE "id" = %s
                RETURNING {_COLUMNS};
                """,
                (fit_score, ats_score, job_id),
            )
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            raise LookupError(f"Job {job_id!r} not found")
        return Job.from_row(row)

    def set_saved(self, job_id: str, user_id: str, saved: bool) -> Job:
        """Set the ``saved`` flag for a job owned by ``user_id``."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE "Job"
                SET "saved" = %s, "updatedAt" = CURRENT_TIMESTAMP
                WHERE "id" = %s AND "userId" = %s
                RETURNING {_COLUMNS};
                """,
                (saved, job_id, user_id),
            )
            row = cur.fetchone()
        self._conn.commit()
        if row is None:
            raise LookupError(f"Job {job_id!r} not found for user")
        return Job.from_row(row)

    # -- reads -----------------------------------------------------------------

    def list_by_user(
        self,
        user_id: str,
        status: Optional[str] = None,
        source: Optional[str] = None,
        saved: Optional[bool] = None,
    ) -> list[Job]:
        """Return the user's jobs, newest first, with optional filters."""
        clauses = ['"userId" = %s']
        params: list[Any] = [user_id]
        if status is not None:
            clauses.append('"status" = %s::"JobStatus"')
            params.append(status)
        if source is not None:
            clauses.append('"source" = %s')
            params.append(source)
        if saved is not None:
            clauses.append('"saved" = %s')
            params.append(saved)

        where = " AND ".join(clauses)
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Job" WHERE {where} '
                'ORDER BY "createdAt" DESC;',
                tuple(params),
            )
            rows = cur.fetchall()
        return [Job.from_row(row) for row in rows]

    def get_by_id(self, job_id: str, user_id: str) -> Optional[Job]:
        """Return a single job owned by ``user_id``, or ``None``."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Job" '
                'WHERE "id" = %s AND "userId" = %s;',
                (job_id, user_id),
            )
            row = cur.fetchone()
        return Job.from_row(row) if row else None

    def _get_by_source_url(self, user_id: str, source_url: str) -> Optional[Job]:
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f'SELECT {_COLUMNS} FROM "Job" '
                'WHERE "userId" = %s AND "sourceUrl" = %s;',
                (user_id, source_url),
            )
            row = cur.fetchone()
        return Job.from_row(row) if row else None
