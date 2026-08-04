"""Analytics router — funnel, ATS distribution, agent ROI (P2-S10)."""
from __future__ import annotations

import re
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


def get_application_counts(
    cur: Any, user_id: str, period_clause: str = ""
) -> dict[str, int]:
    """Canonical application counts for a user — the single source of truth
    every CUMULATIVE "applications" figure across the dashboard, mobile
    dashboard, application tracker and analytics surfaces must derive from
    (data-consistency ruling: MV-dashboard-001, MV-mobile-dashboard-005/006,
    MV-analytics-004/005/006, MV-application-tracker-002).

    ``total`` is every ``Application`` row regardless of status — the
    canonical "applications" figure for any surface whose label does not
    itself narrow to a subset (e.g. the analytics dashboard-summary card).

    ``submitted`` is the subset whose status has left ``draft`` (i.e. it was
    actually sent to an employer). Any surface whose label narrows to
    "submitted", "applied" or similar (the funnel's "Applied" stage, the
    stat card's "Active Applications", Market Pulse's "Applications / month",
    and — as of MV-application-tracker-006 — the Sankey's "Applied" node)
    must use ``submitted``, never ``total``, and must say so honestly.

    Before this helper, several call sites computed "applications" with
    divergent inline queries — one of them (Market Pulse's rolling monthly
    count) mixed ALL statuses while the funnel's all-time "Applied" excluded
    drafts, so a monthly figure could impossibly exceed the all-time total
    (MV-mobile-dashboard-005: "you 14" vs "Applied 7"). A separate attempt to
    keep ``applications.py``'s ``funnel_sankey()`` on a stage-EXCLUSIVE model
    (status == 'submitted' exactly) was disproven live: an application that
    skipped straight to 'interview' undercounted earlier stages and produced
    a negative dropoff (MV-application-tracker-006). ``funnel_sankey()`` now
    also calls this function for its "Applied" node — every cumulative
    surface derives from this one function, with no divergent queries left.

    ``period_clause`` is an optional ``AND ...`` SQL fragment (see
    ``_period_clause``) applied to both counts, e.g. a rolling time window.
    """
    # RT-004: count DISTINCT JOBS, not Application rows. Application rows
    # double as cover-letter versions (one row per draft/refine), so raw
    # row-counts inflated every "applications" surface — live evidence
    # 2026-07-24: one Plenti job with 9 promoted letter-versions counted as
    # 9 applications in the funnel's "Applied" node.
    #
    # ``interviewed`` (§5.3.5, GOLD-MASTER-V2): the SAME DISTINCT-jobId
    # discipline, applied to the interview stage — a job with three
    # Application rows (re-tailored/re-drafted versions of one submitted
    # application) counts as ONE interviewed job, not three. This is the
    # canonical numerator for ``interview_conversion_rate``; market-pulse's
    # separate "Interview conversion" factor (its ``interviewed / total``,
    # not ``interviewed / submitted``) ALSO now derives both terms from this
    # function (GAP-market-pulse-interview-count-divergence, fixed) — it
    # previously used a raw ``COUNT(*)`` instead, which could disagree with
    # this canonical figure on the SAME analytics page for the SAME data.
    cur.execute(
        f'''
        SELECT
            COUNT(DISTINCT "jobId") AS total,
            COUNT(DISTINCT "jobId") FILTER (WHERE "status" <> 'draft') AS submitted,
            COUNT(DISTINCT "jobId") FILTER (
                WHERE "status" IN ('interview', 'offer')
            ) AS interviewed
        FROM "Application" WHERE "userId" = %s{period_clause}
        ''',
        (user_id,),
    )
    total, submitted, interviewed = cur.fetchone()
    return {
        "total": int(total),
        "submitted": int(submitted),
        "interviewed": int(interviewed),
    }


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
            # "Applied" and "interviewed" are the canonical DISTINCT-jobId
            # counts (see get_application_counts docstring) — not divergent
            # inline queries. The funnel is a stage count of OPPORTUNITIES: a
            # user has one application to a job, not N — a job re-tailored/
            # re-drafted into several Application (letter-version) rows must
            # not count as several funnel entries (GOLD-MASTER-V2 §15
            # raw-count divergence class; see also RT-004/get_application_
            # counts's own docstring for the live "9 rows, 1 job" evidence).
            counts = get_application_counts(cur, user_id, job_filter)
            applied = counts["submitted"]
            interviewed = counts["interviewed"]
            # "screened" and "offers" have no canonical helper key (§15: do
            # not modify get_application_counts itself) — computed here with
            # the SAME DISTINCT-jobId discipline instead of a raw COUNT(*).
            cur.execute(
                f'''
                SELECT
                    COUNT(DISTINCT "jobId") FILTER (
                        WHERE "status" IN ('screening','interview','offer')
                    ) AS screened,
                    COUNT(DISTINCT "jobId") FILTER (WHERE "status" = 'offer') AS offers
                FROM "Application" WHERE "userId" = %s{job_filter}
                ''',
                (user_id,),
            )
            screened, offers = cur.fetchone()
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
    """Stage-to-stage conversion rates derived from the funnel.

    ``interview_conversion_rate`` (§5.3.5, GOLD-MASTER-V2): interviews booked
    over applications SUBMITTED — a real DB computation via the canonical
    ``get_application_counts`` (DISTINCT jobId, never a raw Application-row
    count; see that function's docstring), never a placeholder. Healthy at
    the >=1:5 (20%) industry-standard floor.
    """
    data = funnel(current_user, period)

    def rate(numerator: int, denominator: int) -> float:
        return round(numerator / denominator * 100, 2) if denominator else 0.0

    user_id = current_user["id"]
    job_filter = _period_clause(period, '"createdAt"')
    with get_connection() as conn:
        with conn.cursor() as cur:
            counts = get_application_counts(cur, user_id, job_filter)
    interview_conversion_rate = rate(counts["interviewed"], counts["submitted"])

    return {
        "period": period,
        "found_to_applied": rate(data["applied"], data["jobs_found"]),
        "applied_to_screened": rate(data["screened"], data["applied"]),
        "screened_to_interview": rate(data["interviewed"], data["screened"]),
        "interview_to_offer": rate(data["offers"], data["interviewed"]),
        "interview_conversion_rate": interview_conversion_rate,
        "interview_conversion_healthy": interview_conversion_rate >= 20.0,
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

#: No real external market-benchmark data provider is integrated. Market vs.
#: You must never present a hardcoded guess as if it were sourced market
#: data (see GAP-P4-060) — the panel instead reports the source as
#: not-connected and shows only the user's own real figures.
_MARKET_DATA_SOURCE_CONNECTED = False

#: Reference application count the "Application volume" factor is scaled
#: against. It is a stated CONVENTION, not a measurement and not a market
#: benchmark — nothing in this product knows how many applications a role
#: takes. ``_PROGRESS_METHODOLOGY`` discloses it verbatim on the surface so
#: the scaled number can never be read as evidence about the market
#: (PROD-UAT-2026-08-03 F-04).
_APPLICATION_VOLUME_REFERENCE = 30

#: Honest naming for the composite formerly shipped as "Job Probability Score
#: — Likelihood of landing an offer in the next 60 days" (F-04). There is no
#: offer-outcome model, no calibration set and no base rates anywhere in this
#: codebase, so no offer likelihood can be computed; what CAN be computed is
#: the average of the user's own measured signals, which is what this is.
_PROGRESS_LABEL = "Job Search Progress"
_PROGRESS_NOTE = (
    "Average of the measured signals below — all from your own applications, "
    "interview outcomes and job-fit scores."
)
_PROGRESS_METHODOLOGY = (
    "Not an offer-likelihood estimate. Aether has no offer-outcome model and "
    "no external market-data provider, so it cannot tell you how likely an "
    "offer is. What it does measure: applications you have submitted (scaled "
    f"against a {_APPLICATION_VOLUME_REFERENCE}-application reference), the "
    "share of those that reached an interview, and the average fit score of "
    'your fit-scored jobs. A signal with no data yet reads "not measured" and '
    "is left out of the average — never counted as a zero."
)
_PROGRESS_UNMEASURED_REASON = (
    "Not measured — none of these signals has data yet. Apply to a job, or "
    "score a job for fit, and this will start reporting."
)

#: Non-skill boilerplate tokens filtered out of Job.requirements when counting
#: skill demand, so the top-skills chart reflects genuine skills.
_SKILL_STOPWORDS = {
    "and", "or", "the", "with", "years", "year", "experience", "strong",
    "excellent", "ability", "skills", "knowledge", "plus", "etc", "including",
    "a", "an", "of", "in", "to", "for", "on", "as", "is", "are",
}

#: Curated skill lexicon for the Top Skills chart. JD requirement strings are
#: mostly full sentences, so raw phrase counting produced clipped fragments;
#: instead each of these terms is matched (word-boundary, case-insensitive)
#: against every job's requirements. A reported skill therefore literally
#: appears in that many jobs' JDs — real counts, clean labels.
_SKILL_LEXICON: tuple[str, ...] = (
    "Agile", "Scrum", "Kanban", "SAFe", "Jira", "Confluence",
    "Salesforce", "SAP", "ServiceNow", "Genesys", "Playwright",
    "AWS", "Azure", "GCP", "Cloud", "SaaS", "CRM", "ERP", "ITIL",
    "SQL", "Python", "Power BI", "Tableau", "DevOps", "API",
    "Stakeholder management", "Project management", "Program management",
    "Change management", "Risk management", "Business analysis",
    "Process mapping", "Process improvement", "Gap analysis",
    "Governance", "Compliance", "Automation", "Testing", "Integration",
    "Migration", "Transformation", "Delivery", "Leadership",
    "Communication", "Negotiation", "Vendor management", "Procurement",
    "PMO", "Roadmap", "Budget", "Machine learning", "AI",
)


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
            # Interview figures must use the SAME canonical, DISTINCT-jobId
            # get_application_counts() every other cumulative "applications"
            # figure on the platform derives from (see that function's
            # docstring) — a raw COUNT(*) double-counts jobs that carry
            # multiple Application rows (draft/re-tailored cover-letter
            # versions), inflating/deflating this factor against the
            # canonical interview_conversion_rate shown elsewhere on the SAME
            # analytics page (GAP-market-pulse-interview-count-divergence).
            pulse_counts = get_application_counts(cur, user_id)
            f_total, f_interviews = pulse_counts["total"], pulse_counts["interviewed"]

            # "Applications / month" (Market vs. You) must count the SAME
            # submitted set as every other "applications" figure on this
            # user's dashboard (data-consistency ruling) — not all statuses
            # in the window, or a rolling monthly count can silently exceed
            # the all-time "Applied" total (MV-mobile-dashboard-005: drafts
            # inflated this to "you 14" against the funnel's honest 7).
            f_last_month = get_application_counts(
                cur, user_id, ' AND "createdAt" >= NOW() - INTERVAL \'30 days\''
            )["submitted"]

            # Average fit score across scored jobs (skill-match proxy). The
            # COUNT rides along because "no job has ever been fit-scored" and
            # "the average fit score really is 0" are DIFFERENT facts, and the
            # progress panel must not conflate them: the old gate tested the
            # average's truthiness, so an unscored board and a genuine 0 were
            # indistinguishable and both still shipped a rendered "0"
            # (PROD-UAT-2026-08-03 F-04).
            cur.execute(
                'SELECT COUNT(*), COALESCE(AVG("fitScore"), 0) FROM "Job" '
                'WHERE "userId" = %s AND "fitScore" IS NOT NULL',
                (user_id,),
            )
            fit_row = cur.fetchone()
            fit_scored_jobs = int(fit_row[0] or 0)
            avg_fit = float(fit_row[1] or 0)

            # --- Employer activity: recent application status changes ------
            cur.execute(
                'SELECT j.company, a.status, a."updatedAt" '
                'FROM "Application" a JOIN "Job" j ON a."jobId" = j.id '
                'WHERE a."userId" = %s ORDER BY a."updatedAt" DESC LIMIT 5',
                (user_id,),
            )
            employer_rows = rows_to_dicts(cur)

            # --- Recruiter/agent trends: AgentRun per week (last 12 wks) ---
            # Zero-filled across the full 12-week window (via generate_series)
            # so a divisor of len(agent_week_rows) always equals the fixed
            # window length instead of collapsing to the count of weeks that
            # merely happen to have data (GAP-P4-059).
            cur.execute(
                '''
                SELECT gs.week AS week, COALESCE(runs.cnt, 0) AS cnt
                FROM generate_series(
                    DATE_TRUNC('week', NOW()) - INTERVAL '11 weeks',
                    DATE_TRUNC('week', NOW()),
                    INTERVAL '1 week'
                ) AS gs(week)
                LEFT JOIN (
                    SELECT DATE_TRUNC('week', "startedAt") AS week, COUNT(*) AS cnt
                    FROM "AgentRun" WHERE "userId" = %s
                    AND "startedAt" >= NOW() - INTERVAL '84 days'
                    GROUP BY week
                ) runs ON runs.week = gs.week
                ORDER BY gs.week
                ''',
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
            # "Your application velocity" narrows to "applications" — the
            # SAME concept as the canonical, DISTINCT-jobId "Applications /
            # month" comparison computed via get_application_counts() below
            # on this SAME response. A raw COUNT(*) counted every re-tailored
            # draft/letter-version row on one job as a separate "application"
            # this week, diverging from that canonical figure on the SAME
            # page for the SAME underlying data (GOLD-MASTER-V2 §15
            # raw-count divergence class).
            cur.execute(
                'SELECT DATE_TRUNC(\'week\', "createdAt") AS week, '
                'COUNT(DISTINCT "jobId") AS cnt '
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

    # Compute rounded percentages via largest remainder so they sum to 100%.
    raw_pcts = [int(r["cnt"]) / src_sum * 100 for r in source_rows]
    floored = [int(p) for p in raw_pcts]
    remainders = [(raw_pcts[i] - floored[i], i) for i in range(len(raw_pcts))]
    remaining = 100 - sum(floored)
    for _, idx in sorted(remainders, key=lambda x: (-x[0], x[1]))[:remaining]:
        floored[idx] += 1

    # Fallback colors for unmapped sources must skip colors already claimed
    # by mapped sources — otherwise adjacent donut segments are identical.
    claimed = {
        _SOURCE_COLORS[str(r["source"]).lower()]
        for r in source_rows
        if str(r["source"]).lower() in _SOURCE_COLORS
    }
    fallback_cycle = [c for c in _PALETTE if c not in claimed] or list(_PALETTE)
    fallback_idx = 0
    for idx, r in enumerate(source_rows):
        label = str(r["source"])
        color = _SOURCE_COLORS.get(label.lower())
        if color is None:
            color = fallback_cycle[fallback_idx % len(fallback_cycle)]
            fallback_idx += 1
        sources.append(
            {
                "label": label[:1].upper() + label[1:],
                "value": floored[idx],
                "color": color,
            }
        )

    # ---- Top skills (lexicon match — counted once per job) ----------------
    skill_counts: dict[str, int] = {}
    for row in requirement_rows:
        reqs = row.get("requirements")
        if not isinstance(reqs, list):
            continue
        text = " ".join(r for r in reqs if isinstance(r, str)).lower()
        if not text:
            continue
        for skill in _SKILL_LEXICON:
            if re.search(rf"(?<![a-z]){re.escape(skill.lower())}(?![a-z])", text):
                skill_counts[skill] = skill_counts.get(skill, 0) + 1
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

    # ---- Job-search progress index ---------------------------------------
    # HONESTY CONTRACT (PROD-UAT-2026-08-03 F-04, ADR-F04-PROBABILITY-SCORE-
    # HONESTY.md). Every factor here is a measurement of THIS user's own
    # recorded evidence, and the composite claims nothing beyond being their
    # average.
    #
    # REMOVED: ``market_demand_factor = min(100, round(sources_total/50*100))``.
    # ``sources_total`` is COUNT(*) of the user's OWN "Job" rows, so it carried
    # no information about the market, about demand, or about this person's
    # chances — and it saturated at 50 jobs, pinning to 100 for anyone whose
    # scout agent had run once (the UAT account held 1637). It was labelled
    # "Market demand" and averaged into a headline that claimed to be the
    # likelihood of an offer, on the same response that reports
    # ``_MARKET_DATA_SOURCE_CONNECTED = False``. The input has no information,
    # so no weight is correct except zero: it is deleted, not renamed and not
    # down-weighted, and the composite stays the plain unweighted mean of
    # whatever remains measured.
    #
    # MEASURED means "this factor's basis has rows". Applied UNIFORMLY — the
    # old code stated this rule in a comment but exempted two of its four
    # factors from it, so an empty account still scored a confident 0% and an
    # unscored board still rendered "Skill match 0". A genuinely measured zero
    # (7 applications, 0 interviews) still counts; only an empty basis is
    # excluded, and it is reported as not-measured on the wire rather than
    # silently dropped while a "0" stays on screen.
    total_apps = int(f_total or 0)
    interviews = int(f_interviews or 0)
    interview_rate = round(interviews / total_apps * 100) if total_apps else 0

    # (label, value, measured, requires_market_data)
    factor_specs: list[tuple[str, int, bool, bool]] = [
        (
            "Application volume",
            min(100, round(total_apps / _APPLICATION_VOLUME_REFERENCE * 100)),
            total_apps > 0,
            False,
        ),
        ("Interview conversion", interview_rate, total_apps > 0, False),
        ("Skill match", min(100, round(avg_fit)), fit_scored_jobs > 0, False),
    ]
    # STRUCTURAL GUARANTEE (F-04). Market-data dependence is part of a factor's
    # DEFINITION and is filtered against the very same constant that drives the
    # "Market vs. You" not-connected banner below, so a factor claiming market
    # evidence cannot be emitted while that banner says none is connected —
    # the factor is simply not built. No factor sets the flag today; the
    # mechanism exists so the next one has to declare its dependence rather
    # than quietly reintroduce the contradiction this fix removed.
    factors: list[dict[str, Any]] = [
        {"label": label, "value": value if measured else None, "measured": measured}
        for label, value, measured, requires_market_data in factor_specs
        if _MARKET_DATA_SOURCE_CONNECTED or not requires_market_data
    ]

    measured_values = [f["value"] for f in factors if f["measured"]]
    # No measurable signal at all → NO score. The product's established
    # degraded-scoring vocabulary (LetterQualityPanel / Resume Studio "not
    # measured") applies: a missing number presented honestly beats a
    # confident 0%, which on the old copy read as "zero chance of an offer"
    # asserted from no data whatsoever.
    prob_score = (
        max(0, min(100, round(sum(measured_values) / len(measured_values))))
        if measured_values
        else None
    )

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

    # ---- Market vs you ------------------------------------------------
    # No real external market-benchmark data source is connected (see
    # _MARKET_DATA_SOURCE_CONNECTED above) — report that honestly instead of
    # fabricating "market average" figures (GAP-P4-060).
    you_apps_month = int(f_last_month or 0)
    market_vs_you = {
        "marketDataConnected": _MARKET_DATA_SOURCE_CONNECTED,
        "comparisons": [
            {
                "label": "Applications / month",
                "market": None,
                "you": you_apps_month,
            },
            {
                "label": "Interview rate",
                "market": None,
                "you": interview_rate,
                "unit": "%",
            },
        ],
        "summary": _market_summary(),
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
        # sourcesTotal is a count of Job rows (discovery-source breakdown),
        # not applications — the caption must say so honestly (GAP-P4-058).
        "sourcesLabel": "jobs sourced",
        "topSkills": top_skills,
        "activityHeatmap": activity_heatmap,
        # The wire key stays "probability" for its six existing consumers, but
        # nothing rendered from it claims a probability any more (F-04): the
        # score is null when unmeasurable, every factor states its own
        # provenance, and the copy the UI renders comes from here rather than
        # being hardcoded in the component where the server could never
        # correct it.
        "probability": {
            "score": prob_score,
            "measured": prob_score is not None,
            "label": _PROGRESS_LABEL,
            "note": _PROGRESS_NOTE,
            "methodology": _PROGRESS_METHODOLOGY,
            "unmeasuredReason": None if prob_score is not None else _PROGRESS_UNMEASURED_REASON,
            # SAME constant as marketVsYou.marketDataConnected below — one
            # source of truth, so this panel and that banner cannot disagree.
            "marketDataConnected": _MARKET_DATA_SOURCE_CONNECTED,
            "factors": factors,
        },
        "employerActivity": employer_activity,
        "recruiterTrends": recruiter_trends,
        "marketVsYou": market_vs_you,
        "trendIndicators": trend_indicators,
    }


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


def _dashboard(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Build a dashboard summary from existing analytics queries."""
    user_id = current_user["id"]
    app_filter = _period_clause(period, '"createdAt"')
    job_filter = _period_clause(period, '"createdAt"')
    agent_filter = _period_clause(period, '"startedAt"')
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Application stats — "totalApplications" is the canonical, ALL-
            # statuses figure (see get_application_counts docstring): this
            # card's label is the unqualified "Applications", so it must
            # show every Application row, not a narrower submitted-only
            # count. "interviews" lives on the SAME card next to that
            # already-canonical figure, so it must derive from the SAME
            # DISTINCT-jobId helper rather than a raw COUNT(*) that can
            # silently diverge from it (GOLD-MASTER-V2 §15 raw-count
            # divergence class).
            counts = get_application_counts(cur, user_id, app_filter)
            total_apps = counts["total"]
            interviews = counts["interviewed"]

            # "offers" has no canonical helper key (§15: do not modify
            # get_application_counts itself) — computed here with the SAME
            # DISTINCT-jobId discipline instead of a raw COUNT(*).
            cur.execute(
                f'''SELECT COUNT(DISTINCT "jobId") FROM "Application"
                   WHERE "userId" = %s AND "status" = 'offer'{app_filter}''',
                (user_id,),
            )
            offers = cur.fetchone()[0]  # type: ignore[index]

            # Job stats
            cur.execute(
                f'SELECT COUNT(*) FROM "Job" WHERE "userId" = %s{job_filter}',
                (user_id,),
            )
            jobs_found = cur.fetchone()[0]  # type: ignore[index]

            cur.execute(
                f'''SELECT COALESCE(AVG("fitScore"), 0)
                   FROM "Job" WHERE "userId" = %s AND "fitScore" IS NOT NULL{job_filter}''',
                (user_id,),
            )
            avg_fit = float(cur.fetchone()[0])  # type: ignore[index]

            # Agent stats
            cur.execute(
                f'''SELECT COALESCE(SUM("costUsd"), 0), COUNT(*)
                   FROM "AgentRun" WHERE "userId" = %s{agent_filter}''',
                (user_id,),
            )
            total_cost, total_runs = cur.fetchone()  # type: ignore[misc]

    return {
        "totalApplications": total_apps,
        "interviews": interviews,
        "offers": offers,
        "jobsFound": jobs_found,
        "avgFitScore": round(avg_fit, 1),
        "agentRuns": int(total_runs),
        "agentCostUsd": float(total_cost),
    }


@router.get("")
def dashboard_root(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Dashboard summary — alias for the root analytics path."""
    return _dashboard(current_user, period)


@router.get("/dashboard")
def dashboard(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Dashboard summary with key metrics across all analytics dimensions."""
    return _dashboard(current_user, period)


def _market_summary() -> str:
    """Honest summary when no real market-benchmark data source is wired up.

    Previously this fabricated a comparison against hardcoded constants
    (_MARKET_APPS_PER_MONTH / _MARKET_INTERVIEW_RATE) presented as if they
    were real market data — see GAP-P4-060. Until a real market-data
    provider is integrated (tracked for ADR), report the gap honestly
    instead of inventing numbers.
    """
    return "No market data source connected — showing your own figures only."
