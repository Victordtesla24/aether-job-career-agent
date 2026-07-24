"""Job repository — raw psycopg2 against the Prisma ``Job`` table (P2-S02)."""
from __future__ import annotations

import json
from typing import Any

from app.db import ensure_job_dedup_columns, get_connection, new_id, rows_to_dicts
from app.services.dedup import (
    compute_description_hash,
    compute_null_source_url_hash,
    normalize_source_url,
)
from app.services.discovery.base_adapter import JobRaw

_JOB_COLUMNS = (
    '"id", "userId", "title", "company", "location", "remote", "salaryMin", '
    '"salaryMax", "currency", "description", "requirements", "source", '
    '"sourceUrl", "status", "fitScore", "atsScore", "saved", "postedAt", '
    '"createdAt", "updatedAt"'
)

#: RT-010: the id of the newest résumé tailored FOR this job (Resume.sourceJobId
#: == Job.id), or NULL. Lets the Jobs screen show a job's real tailored state
#: instead of an ephemeral client-only "untailored" step, and drives the honest
#: apply gate. Selected as an extra column alongside ``_JOB_COLUMNS``; the "j"
#: alias is bound in the queries that use it.
_TAILORED_RESUME_SUBQUERY = (
    '(SELECT r."id" FROM "Resume" r '
    'WHERE r."userId" = j."userId" AND r."sourceJobId" = j."id" '
    'ORDER BY r."version" DESC LIMIT 1) AS "tailoredResumeId"'
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
        """Insert a discovered job; idempotent upsert on (userId, sourceUrl).

        Dedup strategy (Phase 2A):
        1. sourceUrl is normalized (strip tracking params, lowercase, etc.)
           before insert, so the DB-level ON CONFLICT catches more matches.
        2. For NULL sourceUrl jobs: a composite hash of
           (userId + title + company + location) is computed and checked
           against the ``dedupHash`` column — if a match exists, the job is
           treated as an update (returning wasInserted=False).
        3. A ``contentHash`` (sha256 of first 500 chars of description) is
           stored as a secondary dedup signal for future use.
        """
        ensure_job_dedup_columns()

        requirements = json.dumps(job_raw.get("requirements") or [])
        raw_source_url = job_raw.get("sourceUrl")
        normalized_url = normalize_source_url(raw_source_url)

        # Compute dedup hashes
        dedup_hash: str | None = None
        content_hash: str | None = None
        if job_raw.get("description"):
            content_hash = compute_description_hash(job_raw["description"])
        if normalized_url is None:
            # NULL sourceUrl — compute composite hash to close the NULL != NULL gap
            dedup_hash = compute_null_source_url_hash(
                user_id,
                job_raw["title"],
                job_raw["company"],
                job_raw.get("location"),
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                # --- NULL sourceUrl dedup check ---
                if dedup_hash is not None:
                    cur.execute(
                        'SELECT "id" FROM "Job" '
                        'WHERE "userId" = %s AND "dedupHash" = %s LIMIT 1',
                        (user_id, dedup_hash),
                    )
                    existing = cur.fetchone()
                    if existing:
                        # Duplicate detected — update the existing record instead
                        existing_id = existing[0]
                        cur.execute(
                            """
                            UPDATE "Job" SET
                                "title" = %s,
                                "company" = %s,
                                "location" = %s,
                                "remote" = %s,
                                "description" = %s,
                                "requirements" = %s,
                                "salaryMin" = COALESCE(%s, "Job"."salaryMin"),
                                "salaryMax" = COALESCE(%s, "Job"."salaryMax"),
                                "currency" = COALESCE(%s, "Job"."currency"),
                                "postedAt" = COALESCE(%s, "Job"."postedAt"),
                                "sourceUrl" = %s,
                                "contentHash" = COALESCE(%s, "Job"."contentHash"),
                                "updatedAt" = NOW()
                            WHERE "id" = %s
                            RETURNING """
                            + _JOB_COLUMNS
                            + """, FALSE AS "wasInserted"
                            """,
                            (
                                job_raw["title"],
                                job_raw["company"],
                                job_raw.get("location"),
                                job_raw.get("remote", False),
                                job_raw.get("description", ""),
                                requirements,
                                job_raw.get("salaryMin"),
                                job_raw.get("salaryMax"),
                                job_raw.get("currency"),
                                job_raw.get("postedAt"),
                                normalized_url,
                                content_hash,
                                existing_id,
                            ),
                        )
                        rows = rows_to_dicts(cur)
                        conn.commit()
                        return rows[0]

                # --- Standard upsert path ---
                cur.execute(
                    f"""
                    INSERT INTO "Job" (
                        "id", "userId", "title", "company", "location", "remote",
                        "description", "requirements", "source", "sourceUrl",
                        "salaryMin", "salaryMax", "currency", "postedAt",
                        "dedupHash", "contentHash", "updatedAt"
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
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
                        "dedupHash" = COALESCE(EXCLUDED."dedupHash", "Job"."dedupHash"),
                        "contentHash" = COALESCE(EXCLUDED."contentHash", "Job"."contentHash"),
                        "updatedAt" = NOW()
                    RETURNING {_JOB_COLUMNS}, (xmax = 0) AS "wasInserted"
                    """,
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
                        normalized_url,
                        job_raw.get("salaryMin"),
                        job_raw.get("salaryMax"),
                        job_raw.get("currency"),
                        job_raw.get("postedAt"),
                        dedup_hash,
                        content_hash,
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
                    f'SELECT {_JOB_COLUMNS}, {_TAILORED_RESUME_SUBQUERY} '
                    f'FROM "Job" j WHERE {" AND ".join(clauses)} '
                    f"ORDER BY {order_column} DESC NULLS LAST",
                    params,
                )
                return rows_to_dicts(cur)

    def get_by_id(self, job_id: str, user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_JOB_COLUMNS}, {_TAILORED_RESUME_SUBQUERY} '
                    f'FROM "Job" j WHERE "id" = %s AND "userId" = %s',
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update_status(self, job_id: str, status: str) -> dict[str, Any] | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid job status '{status}'. Valid: {sorted(VALID_STATUSES)}")
        return self._update(job_id, '"status" = %s::"JobStatus"', (status,))

    def advance_status(
        self, job_id: str, status: str, *, allowed_from: set[str] | frozenset[str]
    ) -> bool:
        """Forward-only guarded transition (RT-005 agent board management).

        Sets ``status`` ONLY when the row currently sits in one of
        ``allowed_from`` — a silent no-op otherwise, so an agent-driven advance
        can never demote a manual FEAT-B2 move or touch a terminal state
        (mirrors the ``AND "status" = 'draft'`` guard pattern in
        ``ApprovalRepository._sync_application``). Returns True when the row
        actually advanced.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid job status '{status}'. Valid: {sorted(VALID_STATUSES)}"
            )
        bad = set(allowed_from) - VALID_STATUSES
        if bad:
            raise ValueError(
                f"Invalid allowed_from statuses {sorted(bad)}. "
                f"Valid: {sorted(VALID_STATUSES)}"
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE "Job" SET "status" = %s::"JobStatus", "updatedAt" = NOW()
                    WHERE "id" = %s AND "status"::text = ANY(%s)
                    """,
                    (status, job_id, sorted(allowed_from)),
                )
                advanced = cur.rowcount == 1
            conn.commit()
        return advanced

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
                    f"""
                    UPDATE "Job" SET "saved" = NOT "saved", "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_JOB_COLUMNS}
                    """,
                    (job_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def _update(self, job_id: str, set_clause: str, params: tuple) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE "Job" SET {set_clause}, "updatedAt" = NOW()
                    WHERE "id" = %s
                    RETURNING {_JOB_COLUMNS}
                    """,
                    (*params, job_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None
