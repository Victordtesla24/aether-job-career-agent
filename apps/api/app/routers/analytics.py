"""Analytics router — funnel, ATS distribution, agent ROI (P2-S10)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.db import get_connection
from app.middleware.auth import CurrentUser

router = APIRouter()

#: Supported look-back windows (days). ``all`` disables the filter.
_PERIODS = {"7d": 7, "30d": 30, "90d": 90, "all": None}


def _period_clause(period: str, column: str) -> str:
    if period not in _PERIODS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Invalid period '{period}'. Valid: {sorted(_PERIODS)}",
        )
    days = _PERIODS[period]
    if days is None:
        return ""
    return f' AND {column} >= NOW() - INTERVAL \'{days} days\''


@router.get("/funnel")
def funnel(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Application funnel counts for the requested look-back window."""
    user_id = current_user["id"]
    job_filter = _period_clause(period, '"createdAt"')
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM "Job" WHERE "userId" = %s{job_filter}',
                (user_id,),
            )
            jobs_found = cur.fetchone()[0]
            cur.execute(
                f'''
                SELECT
                    COUNT(*) FILTER (WHERE "status" <> 'draft') AS applied,
                    COUNT(*) FILTER (
                        WHERE "status" IN ('screening','interview','offer')
                    ) AS screened,
                    COUNT(*) FILTER (WHERE "status" IN ('interview','offer')) AS interviewed,
                    COUNT(*) FILTER (WHERE "status" = 'offer') AS offers
                FROM "Application" WHERE "userId" = %s{job_filter}
                ''',
                (user_id,),
            )
            applied, screened, interviewed, offers = cur.fetchone()
    return {
        "period": period,
        "jobs_found": jobs_found,
        "applied": applied,
        "screened": screened,
        "interviewed": interviewed,
        "offers": offers,
    }


@router.get("/ats-distribution")
def ats_distribution(current_user: CurrentUser) -> dict[str, Any]:
    """Histogram of ATS scores in 10-point buckets."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT LEAST(FLOOR("atsScore" / 10) * 10, 90)::int AS bucket, COUNT(*)
                FROM "Job"
                WHERE "userId" = %s AND "atsScore" IS NOT NULL
                GROUP BY bucket ORDER BY bucket
                ''',
                (current_user["id"],),
            )
            rows = cur.fetchall()
    counts = {int(bucket): int(count) for bucket, count in rows}
    return {
        "buckets": [
            {"range": f"{lo}-{lo + 10}", "count": counts.get(lo, 0)}
            for lo in range(0, 100, 10)
        ],
        "total": sum(counts.values()),
    }


@router.get("/agent-roi")
def agent_roi(current_user: CurrentUser) -> dict[str, Any]:
    """Aggregate cost + time spent by the agent fleet."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT
                    COALESCE(SUM("costUsd"), 0),
                    COUNT(*),
                    COALESCE(AVG(
                        EXTRACT(EPOCH FROM ("completedAt" - "startedAt")) * 1000
                    ), 0)
                FROM "AgentRun" WHERE "userId" = %s
                ''',
                (current_user["id"],),
            )
            total_cost, total_runs, avg_ms = cur.fetchone()
    return {
        "total_cost_usd": float(total_cost),
        "total_runs": int(total_runs),
        "avg_duration_ms": round(float(avg_ms), 2),
    }


@router.get("/conversion")
def conversion(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Stage-to-stage conversion rates derived from the funnel."""
    data = funnel(current_user, period)

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator * 100, 2) if denominator else 0.0

    return {
        "period": period,
        "found_to_applied": rate(data["applied"], data["jobs_found"]),
        "applied_to_screened": rate(data["screened"], data["applied"]),
        "screened_to_interview": rate(data["interviewed"], data["screened"]),
        "interview_to_offer": rate(data["offers"], data["interviewed"]),
    }
