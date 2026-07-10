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


# --------------------------------------------------------------------------
# Real-Time Market Pulse (P3 build-out — fixture-backed market intelligence)
# --------------------------------------------------------------------------

_MARKET_PULSE: dict[str, Any] = {
    "sources": [
        {"label": "LinkedIn", "value": 49, "color": "#4F46E5"},
        {"label": "Seek", "value": 30, "color": "#FF6B35"},
        {"label": "Indeed", "value": 21, "color": "#34D399"},
    ],
    "sourcesTotal": 412,
    "topSkills": [
        {"skill": "Python", "demand": 86},
        {"skill": "LLMs / GenAI", "demand": 71},
        {"skill": "Kubernetes", "demand": 58},
        {"skill": "React", "demand": 44},
        {"skill": "Go", "demand": 39},
    ],
    # 5 weeks x 7 days activity intensity (0-4), most recent week last.
    "activityHeatmap": [
        [1, 0, 2, 3, 1, 0, 0],
        [2, 3, 1, 4, 2, 1, 0],
        [3, 2, 4, 3, 2, 0, 1],
        [1, 4, 3, 2, 4, 2, 0],
        [2, 3, 4, 4, 3, 1, 1],
    ],
    "probability": {
        "score": 68,
        "label": "Job Probability Score",
        "note": "Likelihood of landing an offer in the next 60 days",
        "factors": [
            {"label": "Application volume", "value": 74},
            {"label": "Interview conversion", "value": 61},
            {"label": "Market demand", "value": 82},
            {"label": "Skill match", "value": 55},
        ],
    },
    "employerActivity": [
        {"company": "ANZ", "event": "Viewed your application 3× this week", "when": "2h ago", "signal": "hot"},
        {"company": "ATO", "event": "Posted 4 new Senior TPM roles", "when": "6h ago", "signal": "new"},
        {"company": "Atlassian", "event": "Recruiter opened your profile", "when": "Yesterday", "signal": "warm"},
        {"company": "Canva", "event": "Hiring freeze lifted on design platform org", "when": "2d ago", "signal": "new"},
    ],
    "recruiterTrends": {
        "series": [12, 15, 11, 18, 22, 19, 26, 24, 31, 28, 35, 38],
        "rows": [
            {"label": "Recruiter InMails (AU tech)", "delta": "+18% this month"},
            {"label": "Avg response time", "delta": "4.2h · improving"},
        ],
    },
    "marketVsYou": {
        "comparisons": [
            {"label": "Applications / month", "market": 15, "you": 28},
            {"label": "Interview rate", "market": 8, "you": 14, "unit": "%"},
        ],
        "summary": "You're applying 87% more than the market average and converting interviews at 1.75× the median.",
    },
    "trendIndicators": [
        {"label": "TPM openings", "delta": "+22%", "direction": "up", "series": [4, 6, 5, 8, 9, 11, 12]},
        {"label": "AI delivery roles", "delta": "+9%", "direction": "up", "series": [7, 7, 8, 8, 9, 9, 10]},
        {"label": "Avg base salary", "delta": "+14%", "direction": "up", "series": [3, 4, 6, 5, 7, 8, 9]},
        {"label": "Time-to-hire", "delta": "-11%", "direction": "down", "series": [9, 8, 8, 7, 6, 6, 5]},
    ],
}


@router.get("/market-pulse")
def market_pulse(current_user: CurrentUser) -> dict[str, Any]:
    """Real-time market pulse panels (fixture-backed market intelligence)."""
    return _MARKET_PULSE
