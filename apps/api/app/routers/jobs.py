"""Job endpoints (P2-S01 introduces the protected listing).

At this slice the router exposes a single authenticated ``GET /jobs`` that
returns the caller's jobs from Postgres (an empty list until the Scout agent
persists any). It is a real query — not a stub — and is expanded in P2-S02 with
filters, single-job detail, save/archive, and the Scout trigger.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor

from app.db import get_db
from app.middleware.auth import CurrentUser, get_current_user

router = APIRouter(tags=["jobs"])


@router.get("/jobs")
def list_jobs(
    current_user: CurrentUser = Depends(get_current_user),
    conn: PgConnection = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return the authenticated user's jobs (empty until discovery runs)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT "id", "title", "company", "location", "remote", "source",
                   "sourceUrl", "status", "fitScore", "atsScore", "saved",
                   "createdAt"
            FROM "Job"
            WHERE "userId" = %s
            ORDER BY "createdAt" DESC;
            """,
            (current_user.id,),
        )
        rows = cur.fetchall()
    return [dict(row) for row in rows]
