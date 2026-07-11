"""Job repository — raw psycopg2 against the Prisma ``Job`` table (P2-S02)."""
from __future__ import annotations

import json
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts
from app.services.discovery.base_adapter import JobRaw

_JOB_COLUMNS = (
    '"id", "userId", "title", "company", "location", "remote", "salaryMin", '
    '"salaryMax", "currency", "description", "requirements", "source", '
    '"sourceUrl", "status", "fitScore", "atsScore", "saved", "postedAt", '
    '"createdAt", "updatedAt"'
)

#: Statuses accepted by ``update_status`` (mirrors the Prisma JobStatus enum).
VALID_STATUSES = frozenset(
    {
        "discovered",
        "screening",
        "matched",
        "tailoring",
        "ready",
        "applied",
        "archived",
        "rejected",
    }
)


class JobRepository:
    """CRUD over the ``Job`` table using short-lived psycopg2 connections."""

    def create(self, user_id: str, job_raw: JobRaw) -> dict[str, Any]:
        """Insert a discovered job; idempotent upsert on (userId, sourceUrl)."""
        requirements = json.dumps(job_raw.get("requirements") or [])
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "Job" (
                        "id", "userId", "title", "company", "location", "remote",
                        "description", "requirements", "source", "sourceUrl",
                        "salaryMin", "salaryMax", "currency", "postedAt", "updatedAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT ("userId", "sourceUrl") DO UPDATE SET
                        "title" = EXCLUDED."title",
                        "company" = EXCLUDED."company",
                        "location" = EXCLUDED."location",
                        "remote" = EXCLUDED."remote",
                        "description" = EXCLUDED."description",
                        "requirements" = EXCLUDED."requirements",
                        "salaryMin" = COALESCE(EXCLUDED."salaryMin", "Job"."salaryMin"),
                        "salaryMax" = COALESCE(EXCLUDED."salaryMax", "Job"."salaryMax"),
                        "currency" = COALESCE(EXCLUDED."currency", "Job"."currency"),
                        "postedAt" = COALESCE(EXCLUDED."postedAt", "Job"."postedAt"),
                        "updatedAt" = NOW()
                    RETURNING {_JOB_COLUMNS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        job_raw["title"],
                        job_raw["company"],
                        job_raw.get("location"),
                        job_raw.get("remote", False),
                        job_raw.get("description", ""),
                        requirements,
                        job_raw["source"],
                        job_raw["sourceUrl"],
                        job_raw.get("salaryMin"),
                        job_raw.get("salaryMax"),
                        job_raw.get("currency"),
                        job_raw.get("postedAt"),
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0]

    def list_by_user(
        self,
        user_id: str,
        status: str | None = None,
        source: str | None = None,
        saved: bool | None = None,
        sort: str = "createdAt",
    ) -> list[dict[str, Any]]:
        """List a user's jobs with optional filters; newest first by default."""
        clauses = ['"userId" = %s']
        params: list[Any] = [user_id]
        if status is not None:
            clauses.append('"status" = %s')
            params.append(status)
        if source is not None:
            clauses.append('"source" = %s')
            params.append(source)
        if saved is not None:
            clauses.append('"saved" = %s')
            params.append(saved)
        order_column = {
            "createdAt": '"createdAt"',
            "fitScore": '"fitScore"',
            "fit_score": '"fitScore"',
            "title": '"title"',
            "company": '"company"',
        }.get(sort, '"createdAt"')
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_JOB_COLUMNS} FROM "Job" WHERE {" AND ".join(clauses)} '
                    f"ORDER BY {order_column} DESC NULLS LAST",
                    params,
                )
                return rows_to_dicts(cur)

    def get_by_id(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_JOB_COLUMNS} FROM "Job" WHERE "id" = %s AND "userId" = %s',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update_status(self, job_id: str, status: str) -> dict[str, Any] | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid job status '{status}'. Valid: {sorted(VALID_STATUSES)}")
        return self._update(job_id, '"status" = %s::"JobStatus"', (status,))

    def update_fit_score(
        self, job_id: str, fit_score: float, ats_score: float
    ) -> dict[str, Any] | None:
        return self._update(
            job_id, '"fitScore" = %s, "atsScore" = %s', (fit_score, ats_score)
        )

    def toggle_saved(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "Job" SET "saved" = NOT "saved", "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_JOB_COLUMNS}
                    ''',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def _update(self, job_id: str, set_clause: str, params: tuple) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "Job" SET {set_clause}, "updatedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_JOB_COLUMNS}
                    ''',
                    (*params, job_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None
