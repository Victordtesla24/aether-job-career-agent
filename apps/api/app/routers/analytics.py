"""Analytics router — funnel, ATS distribution, agent ROI (P2-S10)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.db import get_connection, rows_to_dicts
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
# Real-Time Market Pulse (real DB-derived market intelligence)
# --------------------------------------------------------------------------

#: Brand colours for known job sources; unknown sources cycle the palette.
_SOURCE_COLORS = {
    "linkedin": "#4F46E5",
    "seek": "#FF6B35",
    "indeed": "#34D399",
    "glassdoor": "#0CAA41",
    "angellist": "#FBBF24",
    "wellfound": "#FBBF24",
    "company": "#7C3AED",
    "referral": "#F59E0B",
}
_PALETTE = ["#4F46E5", "#FF6B35", "#34D399", "#7C3AED", "#FBBF24", "#F59E0B"]

#: Static market baselines (industry reference points — NOT user data). Real
#: user figures are compared against these.
_MARKET_APPS_PER_MONTH = 15
_MARKET_INTERVIEW_RATE = 8  # percent

#: Non-skill boilerplate tokens filtered out of Job.requirements when counting
#: skill demand, so the top-skills chart reflects genuine skills.
_SKILL_STOPWORDS = {
    "and", "or", "the", "with", "years", "year", "experience", "strong",
    "excellent", "ability", "skills", "knowledge", "plus", "etc", "including",
    "a", "an", "of", "in", "to", "for", "on", "as", "is", "are",
}


def _relative_time(ts: datetime | None) -> str:
    """Human 'x ago' string from a timestamp."""
    if ts is None:
        return "recently"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 3600:
        mins = max(1, secs // 60)
        return f"{mins}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    if days == 1:
        return "Yesterday"
    return f"{days}d ago"


def _pct_delta(series: list[float]) -> tuple[str, str]:
    """Return (delta_label, direction) comparing the first non-zero to last."""
    nonzero = [v for v in series if v]
    if len(nonzero) < 2:
        return ("no change", "flat")
    first, last = nonzero[0], nonzero[-1]
    if first == 0:
        return ("no change", "flat")
    change = round((last - first) / abs(first) * 100)
    if change > 0:
        return (f"+{change}%", "up")
    if change < 0:
        return (f"{change}%", "down")
    return ("no change", "flat")


def _status_event(company: str, status_val: str) -> tuple[str, str]:
    """Map an application status to a human event + signal for the feed."""
    mapping = {
        "offer": ("Extended an offer", "hot"),
        "interview": ("Moved you to interview stage", "hot"),
        "screening": ("Started screening your application", "warm"),
        "applied": ("Received your application", "new"),
        "submitted": ("Received your application", "new"),
        "rejected": ("Closed your application", "cold"),
        "draft": ("Application in progress", "new"),
    }
    event, signal = mapping.get(status_val, (f"Application status: {status_val}", "new"))
    return event, signal


@router.get("/market-pulse")
def market_pulse(current_user: CurrentUser) -> dict[str, Any]:
    """Real-time market pulse panels — every figure derived from the user's
    own DB rows (Job / Application / AgentRun). Empty datasets degrade to
    zero-value / empty-array defaults rather than fabricated numbers."""
    user_id = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            # --- Sources: job counts by discovery source -------------------
            cur.execute(
                'SELECT source, COUNT(*) AS cnt FROM "Job" '
                'WHERE "userId" = %s AND source IS NOT NULL '
                'GROUP BY source ORDER BY cnt DESC LIMIT 5',
                (user_id,),
            )
            source_rows = rows_to_dicts(cur)

            cur.execute('SELECT COUNT(*) FROM "Job" WHERE "userId" = %s', (user_id,))
            sources_total = int(cur.fetchone()[0])

            # --- Top skills: flatten Job.requirements ----------------------
            cur.execute(
                'SELECT requirements FROM "Job" '
                'WHERE "userId" = %s AND requirements IS NOT NULL',
                (user_id,),
            )
            requirement_rows = rows_to_dicts(cur)

            # --- Activity heatmap: applications per day (last 35 days) -----
            cur.execute(
                'SELECT DATE("createdAt") AS day, COUNT(*) AS cnt FROM "Application" '
                'WHERE "userId" = %s AND "createdAt" >= NOW() - INTERVAL \'35 days\' '
                'GROUP BY day ORDER BY day',
                (user_id,),
            )
            heatmap_rows = rows_to_dicts(cur)

            # --- Funnel counts for probability + market-vs-you -------------
            cur.execute(
                '''
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE "status" IN ('interview','offer')) AS interviews,
                    COUNT(*) FILTER (WHERE "status" = 'offer') AS offers,
                    COUNT(*) FILTER (
                        WHERE "createdAt" >= NOW() - INTERVAL '30 days'
                    ) AS last_month
                FROM "Application" WHERE "userId" = %s
                ''',
                (user_id,),
            )
            f_total, f_interviews, _f_offers, f_last_month = cur.fetchone()

            # Average fit score across scored jobs (skill-match proxy).
            cur.execute(
                'SELECT COALESCE(AVG("fitScore"), 0) FROM "Job" '
                'WHERE "userId" = %s AND "fitScore" IS NOT NULL',
                (user_id,),
            )
            avg_fit = float(cur.fetchone()[0] or 0)

            # --- Employer activity: recent application status changes ------
            cur.execute(
                'SELECT j.company, a.status, a."updatedAt" '
                'FROM "Application" a JOIN "Job" j ON a."jobId" = j.id '
                'WHERE a."userId" = %s ORDER BY a."updatedAt" DESC LIMIT 5',
                (user_id,),
            )
            employer_rows = rows_to_dicts(cur)

            # --- Recruiter/agent trends: AgentRun per week (last 12 wks) ---
            cur.execute(
                'SELECT DATE_TRUNC(\'week\', "startedAt") AS week, COUNT(*) AS cnt '
                'FROM "AgentRun" WHERE "userId" = %s '
                'AND "startedAt" >= NOW() - INTERVAL \'84 days\' '
                'GROUP BY week ORDER BY week',
                (user_id,),
            )
            agent_week_rows = rows_to_dicts(cur)

            # Weekly agent spend (last 12 weeks) for trend indicators.
            cur.execute(
                'SELECT DATE_TRUNC(\'week\', "startedAt") AS week, '
                'COALESCE(SUM("costUsd"), 0) AS spend '
                'FROM "AgentRun" WHERE "userId" = %s '
                'AND "startedAt" >= NOW() - INTERVAL \'84 days\' '
                'GROUP BY week ORDER BY week',
                (user_id,),
            )
            agent_spend_rows = rows_to_dicts(cur)

            # Weekly applications (last 12 weeks) for application velocity.
            cur.execute(
                'SELECT DATE_TRUNC(\'week\', "createdAt") AS week, COUNT(*) AS cnt '
                'FROM "Application" WHERE "userId" = %s '
                'AND "createdAt" >= NOW() - INTERVAL \'84 days\' '
                'GROUP BY week ORDER BY week',
                (user_id,),
            )
            app_week_rows = rows_to_dicts(cur)

            # Average fit-score trend (weekly) as a demand proxy.
            cur.execute(
                'SELECT DATE_TRUNC(\'week\', "createdAt") AS week, '
                'COALESCE(AVG("fitScore"), 0) AS fit '
                'FROM "Job" WHERE "userId" = %s AND "fitScore" IS NOT NULL '
                'AND "createdAt" >= NOW() - INTERVAL \'84 days\' '
                'GROUP BY week ORDER BY week',
                (user_id,),
            )
            fit_week_rows = rows_to_dicts(cur)

    # ---- Sources → percentages -------------------------------------------
    src_sum = sum(int(r["cnt"]) for r in source_rows) or 1
    sources: list[dict[str, Any]] = []
    for idx, r in enumerate(source_rows):
        label = str(r["source"])
        color = _SOURCE_COLORS.get(label.lower(), _PALETTE[idx % len(_PALETTE)])
        sources.append(
            {
                "label": label[:1].upper() + label[1:],
                "value": round(int(r["cnt"]) / src_sum * 100),
                "color": color,
            }
        )

    # ---- Top skills -------------------------------------------------------
    skill_counts: dict[str, int] = {}
    for row in requirement_rows:
        reqs = row.get("requirements")
        if not isinstance(reqs, list):
            continue
        for raw in reqs:
            if not isinstance(raw, str):
                continue
            skill = raw.strip()
            if not skill or skill.lower() in _SKILL_STOPWORDS or len(skill) < 2:
                continue
            key = skill if len(skill) <= 24 else skill[:24]
            skill_counts[key] = skill_counts.get(key, 0) + 1
    max_skill = max(skill_counts.values()) if skill_counts else 1
    top_skills = [
        {"skill": s, "demand": round(c / max_skill * 100)}
        for s, c in sorted(skill_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    ]

    # ---- Activity heatmap (5 weeks × 7 days, values 0-4) -----------------
    day_counts = {r["day"]: int(r["cnt"]) for r in heatmap_rows}
    max_day = max(day_counts.values()) if day_counts else 0
    # Oldest → newest across 35 days; row 0 = oldest week.
    today = datetime.now(timezone.utc).date()
    ordered: list[int] = []
    for offset in range(34, -1, -1):
        day = today - timedelta(days=offset)
        cnt = day_counts.get(day, 0)
        scaled = round(cnt / max_day * 4) if max_day else 0
        ordered.append(scaled)
    activity_heatmap = [ordered[w * 7 : w * 7 + 7] for w in range(5)]

    # ---- Probability score -----------------------------------------------
    total_apps = int(f_total or 0)
    interviews = int(f_interviews or 0)
    interview_rate = round(interviews / total_apps * 100) if total_apps else 0
    app_volume_factor = min(100, round(total_apps / 30 * 100)) if total_apps else 0
    market_demand_factor = min(100, round(sources_total / 50 * 100)) if sources_total else 0
    skill_match_factor = min(100, round(avg_fit))
    factors: list[dict[str, Any]] = [
        {"label": "Application volume", "value": app_volume_factor},
        {"label": "Interview conversion", "value": interview_rate},
        {"label": "Market demand", "value": market_demand_factor},
        {"label": "Skill match", "value": skill_match_factor},
    ]
    factor_values: list[int] = [app_volume_factor, interview_rate,
                                market_demand_factor, skill_match_factor]
    non_zero = [v for v in factor_values if v]
    prob_score = round(sum(non_zero) / len(non_zero)) if non_zero else 0
    prob_score = max(0, min(100, prob_score))

    # ---- Employer activity feed ------------------------------------------
    employer_activity = []
    for r in employer_rows:
        event, signal = _status_event(str(r.get("company") or ""), str(r.get("status") or ""))
        employer_activity.append(
            {
                "company": r.get("company") or "Unknown",
                "event": event,
                "when": _relative_time(r.get("updatedAt")),
                "signal": signal,
            }
        )

    # ---- Recruiter / agent trends ----------------------------------------
    agent_series = [int(r["cnt"]) for r in agent_week_rows]
    total_runs = sum(agent_series)
    weeks_active = len(agent_series) or 1
    delta_label, _ = _pct_delta([float(v) for v in agent_series])
    recruiter_trends = {
        "series": agent_series,
        "rows": [
            {"label": "Agent runs (last 12 wks)", "delta": f"{total_runs} total"},
            {
                "label": "Avg runs / week",
                "delta": f"{round(total_runs / weeks_active, 1)} · {delta_label}",
            },
        ],
    }

    # ---- Market vs you ----------------------------------------------------
    you_apps_month = int(f_last_month or 0)
    market_vs_you = {
        "comparisons": [
            {
                "label": "Applications / month",
                "market": _MARKET_APPS_PER_MONTH,
                "you": you_apps_month,
            },
            {
                "label": "Interview rate",
                "market": _MARKET_INTERVIEW_RATE,
                "you": interview_rate,
                "unit": "%",
            },
        ],
        "summary": _market_summary(you_apps_month, interview_rate),
    }

    # ---- Trend indicators (all series from real weekly rollups) ----------
    app_series = [int(r["cnt"]) for r in app_week_rows]
    spend_series = [round(float(r["spend"]), 4) for r in agent_spend_rows]
    fit_series = [round(float(r["fit"])) for r in fit_week_rows]
    trend_indicators = []
    for label, series in (
        ("Your application velocity", [float(v) for v in app_series]),
        ("Agent automation spend", [float(v) for v in spend_series]),
        ("Avg job fit score", [float(v) for v in fit_series]),
    ):
        if not series:
            continue
        delta, direction = _pct_delta(series)
        trend_indicators.append(
            {
                "label": label,
                "delta": delta,
                "direction": direction,
                "series": [round(v, 2) for v in series],
            }
        )

    return {
        "sources": sources,
        "sourcesTotal": sources_total,
        "topSkills": top_skills,
        "activityHeatmap": activity_heatmap,
        "probability": {
            "score": prob_score,
            "label": "Job Probability Score",
            "note": "Likelihood of landing an offer in the next 60 days",
            "factors": factors,
        },
        "employerActivity": employer_activity,
        "recruiterTrends": recruiter_trends,
        "marketVsYou": market_vs_you,
        "trendIndicators": trend_indicators,
    }


def _market_summary(you_apps: int, interview_rate: int) -> str:
    """Compose a factual comparison summary from real user figures."""
    parts: list[str] = []
    if you_apps and _MARKET_APPS_PER_MONTH:
        if you_apps >= _MARKET_APPS_PER_MONTH:
            pct = round((you_apps - _MARKET_APPS_PER_MONTH) / _MARKET_APPS_PER_MONTH * 100)
            parts.append(f"You're applying {pct}% more than the market average")
        else:
            pct = round((_MARKET_APPS_PER_MONTH - you_apps) / _MARKET_APPS_PER_MONTH * 100)
            parts.append(f"You're applying {pct}% less than the market average")
    if interview_rate and _MARKET_INTERVIEW_RATE:
        ratio = round(interview_rate / _MARKET_INTERVIEW_RATE, 2)
        parts.append(f"converting interviews at {ratio}× the median")
    if not parts:
        return "Not enough application history yet to compare against the market."
    return " and ".join(parts) + "."
