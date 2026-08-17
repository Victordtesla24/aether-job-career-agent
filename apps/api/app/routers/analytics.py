"""Analytics router — funnel, ATS distribution, agent ROI (P2-S10)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, status

from app.agents.salary_intelligence_agent import (
    MarketBenchmark,
    benchmark_query_terms,
    benchmark_region_label,
    fetch_market_benchmark,
    user_disclosed_salary_median,
)
from app.db import (
    ensure_application_transmission_columns,
    ensure_user_profile_columns,
    get_connection,
    rows_to_dicts,
)
from app.middleware.auth import CurrentUser

router = APIRouter()

#: MON-015: Market Pulse's activity heatmap and weekly trend series bucket
#: calendar days/weeks in THIS timezone, not the DB's UTC-naive storage — the
#: page is explicitly AU/Melbourne-branded (target-role location, "hiring &
#: recruitment trends · AU" caption) but previously bucketed by raw UTC
#: calendar day, silently shifting ~28% of a live user's applications onto
#: the wrong Melbourne day. Both the SQL bucketing (``AT TIME ZONE 'UTC' AT
#: TIME ZONE _ANALYTICS_TIMEZONE``) and the Python "today" anchor below use
#: this SAME zone, and the response discloses it on the wire so a reader is
#: never left guessing which calendar the boundaries use.
_ANALYTICS_TIMEZONE = "Australia/Melbourne"
_ANALYTICS_ZONEINFO = ZoneInfo(_ANALYTICS_TIMEZONE)

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
    cur: Any,
    user_id: str,
    period_clause: str = "",
    period_params: tuple[Any, ...] = (),
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

    ``transmitted`` (CLI-D3, audit wf_9a87f76f-eaa — "submitted must mean
    sent"; the ADDITIVE exception to GOLD-MASTER-V2 §15's "do not modify this
    helper", made by Architect decision CLI-D3): the DISTINCT-jobId subset
    whose ``transmittedAt`` is NOT NULL — stamped only by the real send path
    (``application_submission``) at the moment a message verifiably left the
    building, never by a status change. The honest semantics the audit
    demanded: **submitted counts applications that left draft — preparation;
    transmitted counts verified sends** (live evidence: 391 "submitted" rows
    that were never transmitted anywhere). ``submitted`` keeps its exact
    prior meaning for funnel continuity; any surface whose label claims
    "sent"/"verified" must use ``transmitted``. Same DISTINCT-jobId
    discipline and the SAME ``period_clause`` as every other key.

    ``period_clause`` is an optional ``AND ...`` SQL fragment (see
    ``_period_clause``) applied to all counts, e.g. a rolling time window.
    Any ``%s`` placeholder(s) inside a caller-supplied ``period_clause`` are
    bound from ``period_params``, appended after ``user_id`` in that order
    (MUST-FIX-2, AX round-3 final re-review) — this lets a caller pass an
    explicit anchor instant (e.g. market-pulse's single frozen ``now_utc``)
    instead of a raw ``NOW()`` literal baked into the clause, while every
    existing caller that passes a literal (non-parameterized) clause via
    ``_period_clause`` keeps its exact prior default-now behavior unchanged
    (``period_params`` defaults to empty).
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
    # CLI-D3: the query below names the lazy additive "transmittedAt" column
    # (ADR-TR-1 / ensure_application_transmission_columns docstring: MUST be
    # called by every path that reads it, before the statement that names
    # it). Process-latched — after the first call this is a plain boolean
    # check; the first call briefly borrows a second pooled connection for
    # the information_schema probe.
    ensure_application_transmission_columns()
    cur.execute(
        f'''
        SELECT
            COUNT(DISTINCT "jobId") AS total,
            COUNT(DISTINCT "jobId") FILTER (WHERE "status" <> 'draft') AS submitted,
            COUNT(DISTINCT "jobId") FILTER (
                WHERE "status" IN ('interview', 'offer')
            ) AS interviewed,
            COUNT(DISTINCT "jobId") FILTER (
                WHERE "transmittedAt" IS NOT NULL
            ) AS transmitted
        FROM "Application" WHERE "userId" = %s{period_clause}
        ''',
        (user_id, *period_params),
    )
    total, submitted, interviewed, transmitted = cur.fetchone()
    return {
        "total": int(total),
        "submitted": int(submitted),
        "interviewed": int(interviewed),
        "transmitted": int(transmitted),
    }


@router.get("/funnel")
def funnel(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Application funnel counts for the requested look-back window.

    CLI-D3 (audit wf_9a87f76f-eaa): the payload additionally carries
    ``transmitted`` — DISTINCT jobs with a verified send
    (``transmittedAt IS NOT NULL``), same window. Submitted ("applied")
    counts applications that left draft — preparation; transmitted counts
    verified sends. Every pre-existing field keeps its exact prior meaning
    (additive contract — the FE's zod schema pins them).
    """
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
        # CLI-D3 additive: verified sends only — "applied" above keeps
        # counting every left-draft application (funnel continuity), this
        # counts the subset that verifiably went out the door.
        "transmitted": counts["transmitted"],
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

    CLI-D3 (audit wf_9a87f76f-eaa) — honest semantics: **submitted counts
    applications that left draft — preparation; transmitted counts verified
    sends** (``transmittedAt IS NOT NULL``). The payload therefore ALSO
    carries, additively:

    * ``transmitted`` — the verified-send count for the same window.
    * ``verified_interview_conversion_rate`` — interviews over TRANSMITTED,
      the rate a user can trust as "of what actually went out, how much
      converted". The legacy ``interview_conversion_rate`` stays present and
      byte-identical (its denominator includes recorded-but-never-sent
      applications — live audit: 391 of them); the FE relabels it honestly
      (Track D) rather than this endpoint silently changing its meaning.
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
    # CLI-D3: the SAME numerator over the VERIFIED denominator. With zero
    # verified sends this is an honest 0.0 (rate()'s zero-denominator arm),
    # never a copy of the legacy figure.
    verified_interview_conversion_rate = rate(
        counts["interviewed"], counts["transmitted"]
    )

    return {
        "period": period,
        "found_to_applied": rate(data["applied"], data["jobs_found"]),
        "applied_to_screened": rate(data["screened"], data["applied"]),
        "screened_to_interview": rate(data["interviewed"], data["screened"]),
        "interview_to_offer": rate(data["offers"], data["interviewed"]),
        "interview_conversion_rate": interview_conversion_rate,
        "interview_conversion_healthy": interview_conversion_rate >= 20.0,
        # CLI-D3 additive fields — see this endpoint's docstring for the
        # submitted-vs-transmitted semantics.
        "transmitted": counts["transmitted"],
        "verified_interview_conversion_rate": verified_interview_conversion_rate,
    }


# --------------------------------------------------------------------------
# Agent Performance Policy (U-AX build spec item 2) — the LIVE self-improvement
# loop, made legible: which tier the agents are running at, WHICH measured
# metric forced it, what they do differently, and what each agent's last run
# actually consumed.
# --------------------------------------------------------------------------


def _policy_run_view(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """One agent's last run as the policy panel needs it, or ``None``.

    ``None`` means the agent has genuinely never run for this user — the
    honest answer. It is deliberately NOT an empty object with zeroed fields,
    which would render as "ran, scored nothing".
    """
    if run is None:
        return None
    return {
        "runId": run.get("id"),
        "status": run.get("status"),
        "startedAt": run.get("startedAt"),
        "completedAt": run.get("completedAt"),
        "costUsd": float(run["costUsd"]) if run.get("costUsd") is not None else None,
        "jobId": run.get("jobId"),
        "applicationId": run.get("applicationId"),
        # The tier this run OBEYED and the exact snapshot it consumed —
        # NULL for every run recorded before the policy loop existed, never
        # back-stamped with today's verdict.
        "policyTier": run.get("policyTier"),
        "policyInputs": run.get("metricSnapshot"),
    }


@router.get("/agent-policy")
def agent_policy(current_user: CurrentUser) -> dict[str, Any]:
    """The current rigor tier, why it is what it is, and per-agent visibility.

    Everything here is derived from the SAME
    ``services.quality_policy.resolve_policy_for_user`` that governs live agent
    runs — the panel cannot show one tier while the agents obey another,
    because there is only one computation.

    ``perAgent`` covers every REAL (backend-having) catalog agent, reporting
    ``lastRun: null`` for agents that have never run rather than omitting them:
    "this agent has never run" is information a subscriber is entitled to, and
    silently dropping the row would read as though the agent did not exist.
    """
    from app.repositories.agent_run import AgentRunRepository
    from app.routers.agents import AGENT_CATALOG
    from app.services.quality_policy import resolve_policy_for_user

    user_id = current_user["id"]
    policy = resolve_policy_for_user(user_id)
    metrics = policy.get("metrics") or {}
    last_runs = AgentRunRepository().last_policy_run_by_agent(user_id)

    per_agent = [
        {
            "agentKey": entry["key"],
            "name": entry["name"],
            "backend": entry["backend"],
            "lastRun": _policy_run_view(last_runs.get(entry["backend"])),
        }
        for entry in AGENT_CATALOG
        if entry.get("backend")
    ]

    return {
        "tier": policy["tier"],
        "triggers": policy["triggers"],
        "behaviour": policy.get("behaviour"),
        "knobs": policy.get("knobs"),
        "thresholds": policy.get("thresholds"),
        "metricSnapshot": {
            "sampleSize": metrics.get("sampleSize", 0),
            # Percentage for display; the policy itself compares fractions.
            "conversionRate": _percent(metrics.get("conversionRate")),
            "interviewCount": metrics.get("interviewCount", 0),
            "dimensionScores": metrics.get("dimensionScores") or {},
            "dimensionSampleSize": metrics.get("dimensionSampleSize", 0),
            "dimensionsEvaluated": policy.get("dimensionsEvaluated", 0),
            # False when the underlying reads failed — the panel must say so
            # rather than render zeros as measurements.
            "available": bool(metrics.get("available", False)),
            "unavailableReason": metrics.get("reason"),
        },
        "perAgent": per_agent,
    }


def _percent(fraction: Any) -> float:
    """A 0-1 fraction as a display percentage, rounded once, at this boundary.

    ``quality_policy`` compares FRACTIONS (0.2 == the 1-in-5 target); every
    analytics surface renders PERCENTAGES. Converting in exactly one helper is
    what stops the two representations drifting apart across endpoints.
    """
    try:
        return round(float(fraction or 0.0) * 100, 2)
    except (TypeError, ValueError):
        return 0.0


@router.get("/agent-policy/history")
def agent_policy_history(current_user: CurrentUser, limit: int = 500) -> dict[str, Any]:
    """Rigor tier over time, next to the metrics that forced it (U-AX item 2c).

    Derived entirely from instrumentation that already exists —
    ``AgentRun.policyTier`` + ``AgentRun.metricSnapshot``, both written by the
    single enforcement seam (``routers/agents.py::_with_quality_policy``) at
    the moment the run was authorised. So a point on this series is not a
    reconstruction of what the policy WOULD have said; it is what the agent
    actually obeyed.

    Consecutive runs whose (tier, sample size, conversion rate) are unchanged
    collapse into ONE point carrying a ``runs`` count. Thirty identical rows is
    not a trend, and rendering them as one would make a genuinely flat period
    look like activity.

    Honest gaps: runs that recorded NO tier (everything predating the loop) are
    excluded from the series and reported separately as ``runsWithoutPolicy``,
    never back-filled with today's verdict.
    """
    from app.repositories.agent_run import AgentRunRepository
    from app.services.quality_policy import (
        DIMENSION_FLOOR,
        INTERVIEW_CONVERSION_TARGET,
        MIN_SAMPLE_SIZE,
    )

    rows, without_policy = AgentRunRepository().policy_tier_history(
        current_user["id"], limit=max(1, min(limit, 2000))
    )

    points: list[dict[str, Any]] = []
    previous_key: tuple[Any, ...] | None = None
    for row in rows:
        snapshot = row.get("metricSnapshot") or {}
        metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
        metrics = metrics if isinstance(metrics, dict) else {}
        dimension_scores = metrics.get("dimensionScores")
        dimension_scores = dimension_scores if isinstance(dimension_scores, dict) else {}
        below_floor = sorted(
            key
            for key, value in dimension_scores.items()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and float(value) <= DIMENSION_FLOOR
        )
        tier = row.get("policyTier")
        sample_size = int(metrics.get("sampleSize") or 0)
        conversion = _percent(metrics.get("conversionRate"))
        key = (tier, sample_size, conversion)
        if key == previous_key and points:
            points[-1]["runs"] += 1
            continue
        previous_key = key
        points.append(
            {
                "at": row.get("createdAt"),
                "tier": tier,
                "runs": 1,
                "conversionRate": conversion,
                "sampleSize": sample_size,
                "interviewCount": int(metrics.get("interviewCount") or 0),
                "dimensionsBelowFloor": below_floor,
                "dimensionsEvaluated": len(dimension_scores),
                "triggers": (
                    snapshot.get("triggers")
                    if isinstance(snapshot, dict) and isinstance(snapshot.get("triggers"), list)
                    else []
                ),
            }
        )

    return {
        "available": bool(points),
        "reason": (
            None
            if points
            else "no agent run has recorded a rigor policy yet — the trend starts "
            "with the first instrumented run"
        ),
        "runsWithoutPolicy": without_policy,
        "thresholds": {
            "interviewConversionTarget": _percent(INTERVIEW_CONVERSION_TARGET),
            "dimensionFloor": DIMENSION_FLOOR,
            "minSampleSize": MIN_SAMPLE_SIZE,
        },
        "points": points,
    }


#: Display labels for the cohort tiers. An unrecognised tier keeps its raw key
#: rather than being relabelled into one of these — a tier this table does not
#: know about is a fact, not a rendering problem to paper over.
_COHORT_LABELS: dict[str, str] = {
    "standard": "Standard rigor",
    "heightened": "Heightened rigor",
    "insufficient_data": "Insufficient data",
}

#: Stable display order; unknown tiers sort after these, alphabetically.
_COHORT_ORDER: dict[str, int] = {"standard": 0, "heightened": 1, "insufficient_data": 2}


@router.get("/agent-policy/cohorts")
def agent_policy_cohorts(current_user: CurrentUser) -> dict[str, Any]:
    """Interview-conversion progress per policy-tier cohort (U-AX item 3).

    "Applications under each policy tier" — read from
    ``Application.policyTierAtSubmission``, which submission-time
    instrumentation has been writing since round 2 and nothing read until now.
    This is the surface that turns the rigor loop from a claim into a
    measurement: if heightened rigor works, its cohort converts better than the
    standard one, and if it does not, that is visible too.

    AUD-META-1 (cohort residual — "Dashboard/Analytics label apps
    'submitted/applied' when not transmitted"). This endpoint used to report a
    single ``submitted`` bucket built from ``status <> 'draft'`` and divide
    interviews by it. Two things were wrong with that at once: it applied the
    word "submitted" to applications that never left the building (live audit:
    391 of them), and its denominator silently disagreed with
    ``quality_policy.collect_policy_metrics`` — the metric drawn in the SAME
    panel — which CLI-QP had already narrowed to jobs carrying a real
    ``transmittedAt``. The payload now carries the two populations as DISTINCT,
    honestly named counts:

    * ``prepared`` — DISTINCT jobs whose application left ``draft``. That is
      preparation, not proof of sending, and it is never called "submitted",
      "applied" or "sent".
    * ``transmitted`` — DISTINCT jobs with ``transmittedAt IS NOT NULL``,
      stamped only by the real send path at the moment a message verifiably
      left the building. This is the ONLY population the conversion rate is
      computed over.

    Honesty rules:

    * Same counting semantics as ``quality_policy.collect_policy_metrics``
      (verified sends as the denominator, interview reached == status
      ``interview`` or ``offer``, DISTINCT jobs throughout) — so the two charts
      in this panel cannot quote different numbers. Pinned by
      ``tests/test_meta1_cohort_transmitted.py``.
    * A cohort with fewer than ``MIN_SAMPLE_SIZE`` VERIFIED sends reports
      ``conversionRate: null``. One application that did not convert is not
      "0%"; it is one application, and printing a rate there would invite
      exactly the wrong conclusion about the tier that produced it. A tier with
      12 prepared applications and 0 verified sends is likewise not "0%" — it
      still appears, with both counts, and no rate.
    * Applications submitted before the policy existed carry NULL and form
      their own labelled bucket. Folding them into a real tier would credit (or
      blame) a policy that was not running when they were sent.
    """
    from app.services.quality_policy import INTERVIEW_CONVERSION_TARGET, MIN_SAMPLE_SIZE

    target = _percent(INTERVIEW_CONVERSION_TARGET)
    # AUD-META-1: names the lazy additive "transmittedAt" column, so the
    # ADR-TR-1 contract applies here exactly as it does in
    # get_application_counts — ensure before the statement that reads it.
    ensure_application_transmission_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT "policyTierAtSubmission" AS tier,
                       COUNT(DISTINCT "jobId") FILTER (
                           WHERE "status" <> 'draft'::"ApplicationStatus") AS prepared,
                       COUNT(DISTINCT "jobId") FILTER (
                           WHERE "transmittedAt" IS NOT NULL) AS transmitted,
                       COUNT(DISTINCT "jobId") FILTER (
                           WHERE "status" IN ('interview'::"ApplicationStatus",
                                              'offer'::"ApplicationStatus")
                       ) AS interviewed
                FROM "Application"
                WHERE "userId" = %s
                GROUP BY 1
                ''',
                (current_user["id"],),
            )
            rows = cur.fetchall()

    cohorts: list[dict[str, Any]] = []
    untagged = {"prepared": 0, "transmitted": 0, "interviewed": 0}
    for tier, prepared, transmitted, interviewed in rows:
        prepared = int(prepared or 0)
        transmitted = int(transmitted or 0)
        interviewed = int(interviewed or 0)
        if tier is None:
            untagged["prepared"] += prepared
            untagged["transmitted"] += transmitted
            untagged["interviewed"] += interviewed
            continue
        if prepared == 0 and transmitted == 0:
            # Drafts only — nothing was ever prepared or sent under this tier,
            # so there is no population to report at all.
            continue
        sufficient = transmitted >= MIN_SAMPLE_SIZE
        rate = round(interviewed / transmitted * 100, 2) if sufficient else None
        cohorts.append(
            {
                "tier": tier,
                "label": _COHORT_LABELS.get(str(tier), str(tier)),
                # Preparation and verified sending are different facts and are
                # reported as different numbers (AUD-META-1).
                "prepared": prepared,
                "transmitted": transmitted,
                "interviewed": interviewed,
                "conversionRate": rate,
                "sufficientSample": sufficient,
                "meetsTarget": (rate >= target) if rate is not None else None,
                "gapPoints": round(max(0.0, target - rate), 2) if rate is not None else None,
            }
        )
    cohorts.sort(key=lambda c: (_COHORT_ORDER.get(str(c["tier"]), 99), str(c["tier"])))

    return {
        "target": target,
        "minSampleSize": MIN_SAMPLE_SIZE,
        "cohorts": cohorts,
        "untagged": {
            **untagged,
            "reason": (
                "prepared before the rigor policy was instrumented — no tier was "
                "recorded for these, so their outcome cannot be attributed to one"
            ),
        },
    }


# --------------------------------------------------------------------------
# Real-Time Market Pulse (real DB-derived market intelligence)
# --------------------------------------------------------------------------

#: R-VIZ chart palette, in fixed order and NEVER cycled. The donut assigns
#: these by RANK — the largest source takes chart-gold, the next sapphire, and
#: so on — because a colour that means "biggest slice" is readable, whereas the
#: old per-name map handed four different named sources (angellist, wellfound,
#: company, referral) the SAME hue and so drew differently-labelled segments in
#: one colour, which is exactly the collision the uniqueness invariant below
#: exists to prevent.
_CHART_PALETTE = ["#AE8E32", "#4F74B5", "#C16F7B", "#439FC8"]

#: The single reserved overflow tone (--state-neutral). Anything past the top
#: four — including the rolled-up "Other" slice — wears this, because R-VIZ
#: forbids a fifth hue. It is the ONE colour a donut may legitimately repeat:
#: it does not identify a source, it says "this is the tail".
_CHART_OTHER = "#8C8A82"

#: Whether the PROBABILITY model has any market evidence to reason from. It has
#: none — no factor below is computed from anything outside this user's own
#: rows — and no factor may claim otherwise (see the factor gate). The name says
#: what it really governs: it was ``_MARKET_DATA_SOURCE_CONNECTED`` back when
#: the product had no external provider at all and one boolean could honestly
#: answer both "is a market source connected?" and "does the score use market
#: evidence?". Those questions now have DIFFERENT answers — Market vs. You
#: carries a live Adzuna AU benchmark whose rows each report their own
#: ``connected`` state, while a posting count remains no evidence about THIS
#: user's chances — so the two must not be reunited under one flag. Market vs.
#: You must still never present a hardcoded guess as sourced market data
#: (GAP-P4-060); it shows the user's real figures whether or not the provider
#: answered.
_PROBABILITY_USES_MARKET_EVIDENCE = False

#: There is no interview-conversion benchmark provider ANYWHERE — not at
#: Adzuna, not at any licensed source this product can reach. That row is
#: therefore permanently market-unavailable and says so on the surface,
#: rather than borrowing a number from unrelated posting/salary data.
_INTERVIEW_RATE_FOOTNOTE = (
    "No external interview-conversion benchmark provider currently exists."
)

#: The exact honest state shown whenever no external benchmark is available —
#: credentials absent, provider down, or the user has not set a target role
#: and location. Unchanged wording from before any provider was integrated.
_NO_MARKET_DATA_SUMMARY = "No market data source connected — showing your own figures only."

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
#: AUD-META-1 (residual — "Dashboard/Analytics label apps 'submitted/applied'
#: when not transmitted"). This copy used to say the panel measures
#: "applications you have submitted". Its "Application volume" factor is
#: computed from ``get_application_counts(...)["total"]`` — EVERY
#: ``Application`` row for the user, drafts included and transmission
#: irrelevant — so a tracker holding nothing but drafts was described to the
#: reader as a count of submissions. The METRIC is deliberately unchanged
#: (``total`` is the honest basis for a volume-of-work signal, and six
#: consumers already read it); the SENTENCE now names the population it
#: really counts. Pinned by ``tests/test_meta1_cohort_transmitted.py``
#: (``TestProgressMethodologyDescribesWhatItActuallyCounts``).
_PROGRESS_METHODOLOGY = (
    "Not an offer-likelihood estimate. Aether has no offer-outcome model and "
    "no external market-data provider, so it cannot tell you how likely an "
    "offer is. What it does measure: every application in your tracker, "
    "drafts included — work you have started, not work that was sent (scaled "
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


def _period_delta(prior: float, last: float) -> tuple[str, str, str]:
    """Return (delta_label, direction, kind) for exactly two already-chosen
    "prior" and "last" complete-period values. ``kind`` is one of
    "percent" | "new" | "insufficient-data" (RULING-C): a zero-base rise
    reports the real direction without fabricating a magnitude — no honest
    percentage is computable from a zero base — labelled "new" so callers
    never route it through a percent formatter.
    """
    if prior == last:
        return ("no change", "flat", "percent")
    if prior == 0:
        return ("new activity", "up", "new") if last > 0 else ("no change", "flat", "percent")
    change = round((last - prior) / abs(prior) * 100)
    if change > 0:
        return (f"+{change}%", "up", "percent")
    if change < 0:
        return (f"{change}%", "down", "percent")
    return ("no change", "flat", "percent")


def _pct_delta(series: list[float]) -> tuple[str, str, str]:
    """Return (delta_label, direction, kind) for a COUNT/SUM series (zero-
    filled — every week is a real observed value, 0 included) comparing the
    last COMPLETE period to the one immediately before it — the literal
    "vs. the prior period" comparison the Trend Indicators tooltip claims
    (MarketPulse.tsx).

    MON-016: this used to compare the first non-zero point to the last point
    of the WHOLE lookback window, which can — and, in a live 2026-08-13
    audit, did — report the OPPOSITE sign of the true most-recent
    week-over-week change (series [44, 43, 290, 103] displayed "+134%"/up
    from first=44 vs last=103, while the real prior-period change,
    290 -> 103, was -64.5%/down).

    AX-REV-01 (2026-08-13 re-audit of that fix): every series this is
    called with is a weekly rollup whose SQL upper bound is literally "the
    current Melbourne week" — so ``series[-1]`` is ALWAYS the still-in-
    progress current period, never a complete one. Comparing it directly
    against ``series[-2]`` (a complete prior week) divides a partial
    numerator by a complete denominator, biasing the result toward "down"
    without bound the earlier in the week the request lands (live
    2026-08-13T16:11Z evidence: 4d02h into the week, a genuine -47.8%
    like-for-like change rendered as -59.5%; a Monday request for a
    perfectly flat user would render roughly -95%). "Prior period" means
    the last two COMPLETE periods, so this now always drops the trailing
    in-progress bucket before comparing. Because the series is zero-filled,
    every remaining entry is a real value — no gap-skipping is needed (that
    is what distinguishes this from :func:`_pct_delta_avg` below).
    """
    complete = series[:-1]
    if len(complete) < 2:
        return ("no change", "flat", "percent")
    return _period_delta(complete[-2], complete[-1])


def _pct_delta_avg(series: list[float | None]) -> tuple[str, str, str]:
    """Return (delta_label, direction, kind) for an AVERAGE series (RULING-B:
    a missing week is a null gap, never fabricated as 0 — an average of
    nothing is not really 0). Drops the trailing in-progress week first
    (same rule as :func:`_pct_delta`, RULING-A), then compares the two most
    recent COMPLETE weeks that actually HAVE data — skipping any null gaps
    in between, since a week with no scored jobs is a real absence, not a
    disqualifying one. If fewer than two complete weeks have data, the
    delta is the honest "insufficient-data" state (RULING-C) rather than a
    percentage silently computed across an undisclosed multi-week gap.
    """
    complete = series[:-1]
    dated = [v for v in complete if v is not None]
    if len(dated) < 2:
        return ("insufficient data", "flat", "insufficient-data")
    return _period_delta(dated[-2], dated[-1])


def _status_event(
    company: str, status_val: str, *, transmitted: bool = False
) -> tuple[str, str]:
    """Map an application status to a human event + signal for the feed.

    AUD-META-1: "Received your application" is a claim about what the EMPLOYER
    did, and the only evidence for it in this system is ``transmittedAt``.
    A row parked at ``submitted``/``applied`` with nothing transmitted proves
    a status change, not a receipt — so without that evidence the feed says
    what it can actually stand behind (the application is prepared, Aether
    recorded no send) instead of putting words in the employer's mouth.

    Every other status is an outcome the employer really produced — a screen,
    an interview, an offer, a rejection — and stays exactly as it was: a user
    who applied by hand and recorded the result is telling the truth about the
    employer even though Aether transmitted nothing.
    """
    mapping = {
        "offer": ("Extended an offer", "hot"),
        "interview": ("Moved you to interview stage", "hot"),
        "screening": ("Started screening your application", "warm"),
        "applied": ("Received your application", "new"),
        "submitted": ("Received your application", "new"),
        "rejected": ("Closed your application", "cold"),
        "draft": ("Application in progress", "new"),
    }
    if status_val in ("applied", "submitted") and not transmitted:
        return ("Application prepared — no send recorded by Aether", "new")
    event, signal = mapping.get(status_val, (f"Application status: {status_val}", "new"))
    return event, signal


@router.get("/market-pulse")
def market_pulse(current_user: CurrentUser) -> dict[str, Any]:
    """Real-time market pulse panels. Every figure about THIS user is derived
    from their own DB rows (Job / Application / AgentRun). The ONE external
    input is the market side of Market vs. You, fetched live from the Adzuna
    AU API (:func:`fetch_market_benchmark`); each row carries its own
    ``connected`` / ``dataAsOf`` provenance so a reader can tell which side of
    it came from outside. Empty datasets — and an absent, credential-less or
    failing provider — degrade to zero-value / empty-array / honestly
    not-connected defaults rather than fabricated numbers."""
    user_id = current_user["id"]

    # R-02/R-05 (AX re-review round 2): every day/week boundary below must
    # agree on ONE instant, and it must be the same instant a test can
    # freeze. Previously the Python "today" anchor (for the heatmap grid
    # position) was frozen via ``datetime.now()`` while the SQL bucketing
    # queries called Postgres's own ``NOW()`` directly — two independent
    # clocks that a test could only pin one of, which is exactly why the
    # prior round's DST test never actually exercised the router (it had
    # no way to make the DB agree with a frozen Python "now"). Both sides
    # now derive from this single anchor: Python via the value directly,
    # SQL via a bound parameter (``%s::timestamptz``) instead of ``NOW()``.
    now_utc = datetime.now(timezone.utc)

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
            # QA-2026-08-13 M-02: most adapters return an empty requirements
            # list (7k+ jobs, zero populated), which left "Top Skills in
            # Demand" permanently on its empty state. Also fetch title +
            # description so the lexicon matcher can fall back to the posting
            # text when requirements are missing.
            cur.execute(
                'SELECT requirements, title, description FROM "Job" '
                'WHERE "userId" = %s',
                (user_id,),
            )
            requirement_rows = rows_to_dicts(cur)

            # --- Activity heatmap: applications per day (last 35 days) -----
            # MON-015: bucket by the Melbourne-local calendar day, not the
            # DB's UTC-naive storage — "createdAt" AT TIME ZONE 'UTC' AT TIME
            # ZONE _ANALYTICS_TIMEZONE reinterprets the naive UTC value as
            # Melbourne wall-clock time before truncating to a day.
            cur.execute(
                'SELECT DATE("createdAt" AT TIME ZONE \'UTC\' AT TIME ZONE %s) AS day, '
                'COUNT(*) AS cnt FROM "Application" '
                'WHERE "userId" = %s AND "createdAt" >= %s::timestamptz - INTERVAL \'35 days\' '
                'GROUP BY day ORDER BY day',
                (_ANALYTICS_TIMEZONE, user_id, now_utc),
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
            # MUST-FIX-2 (AX round-3 final re-review): this used to bind a raw
            # Postgres ``NOW()`` literal directly in the clause — a SECOND,
            # independent clock from every other query in this endpoint,
            # which all derive from the single frozen ``now_utc`` Python
            # anchor above (R-02/R-05). A frozen-clock test could pin every
            # other boundary here while this one figure still floated on the
            # real DB wall clock, so a single response could mix instants.
            # Now bound via the SAME ``%s::timestamptz`` parameter pattern
            # every other market-pulse query already uses.
            last_month_counts = get_application_counts(
                cur,
                user_id,
                ' AND "createdAt" >= %s::timestamptz - INTERVAL \'30 days\'',
                (now_utc,),
            )
            f_last_month = last_month_counts["submitted"]
            # CLI-D3 (audit wf_9a87f76f-eaa): the verified-send subset of the
            # SAME rolling 30-day window — carried on the "Applications /
            # month" row below so the one market-pulse figure derived from
            # "submitted" also discloses how many of those applications
            # verifiably left the building (transmittedAt IS NOT NULL).
            f_last_month_transmitted = last_month_counts["transmitted"]

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
            # AUD-META-1: ``transmittedAt`` rides along because the feed's
            # "Received your application" line is a claim about the EMPLOYER
            # that only a verified send can support (see _status_event).
            cur.execute(
                'SELECT j.company, a.status, a."updatedAt", a."transmittedAt" '
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
            # MON-015: both the zero-fill anchor and the joined actuals bucket
            # in Melbourne-local weeks (Monday-start, per Postgres's
            # DATE_TRUNC), so the two sides of the LEFT JOIN agree.
            cur.execute(
                '''
                SELECT gs.week AS week, COALESCE(runs.cnt, 0) AS cnt
                FROM generate_series(
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s) - INTERVAL '11 weeks',
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s),
                    INTERVAL '1 week'
                ) AS gs(week)
                LEFT JOIN (
                    SELECT DATE_TRUNC(
                        'week', "startedAt" AT TIME ZONE 'UTC' AT TIME ZONE %s
                    ) AS week, COUNT(*) AS cnt
                    FROM "AgentRun" WHERE "userId" = %s
                    AND "startedAt" >= %s::timestamptz - INTERVAL '84 days'
                    GROUP BY week
                ) runs ON runs.week = gs.week
                ORDER BY gs.week
                ''',
                (
                    now_utc, _ANALYTICS_TIMEZONE, now_utc, _ANALYTICS_TIMEZONE,
                    _ANALYTICS_TIMEZONE, user_id, now_utc,
                ),
            )
            agent_week_rows = rows_to_dicts(cur)

            # Weekly agent spend (last 12 weeks) for trend indicators.
            # AX-REV-02: zero-filled across the SAME 12-week grid as
            # agent_week_rows above (generate_series, not a bare GROUP BY) —
            # without it, a week with $0 spend is simply ABSENT rather than
            # present-as-zero, so series[-2]/series[-1] could silently
            # compare two weeks separated by a multi-week gap while
            # _pct_delta's own contract (and the FE tooltip) claims "the
            # prior period" (live audit: this user's 84-day window had only
            # 4 of 12 weeks present under the old bare GROUP BY).
            cur.execute(
                '''
                SELECT gs.week AS week, COALESCE(spend.total, 0) AS spend
                FROM generate_series(
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s) - INTERVAL '11 weeks',
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s),
                    INTERVAL '1 week'
                ) AS gs(week)
                LEFT JOIN (
                    SELECT DATE_TRUNC(
                        'week', "startedAt" AT TIME ZONE 'UTC' AT TIME ZONE %s
                    ) AS week, SUM("costUsd") AS total
                    FROM "AgentRun" WHERE "userId" = %s
                    AND "startedAt" >= %s::timestamptz - INTERVAL '84 days'
                    GROUP BY week
                ) spend ON spend.week = gs.week
                ORDER BY gs.week
                ''',
                (
                    now_utc, _ANALYTICS_TIMEZONE, now_utc, _ANALYTICS_TIMEZONE,
                    _ANALYTICS_TIMEZONE, user_id, now_utc,
                ),
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
            # AX-REV-02: same zero-fill treatment as agent_spend_rows above —
            # an application-free week must appear as a real 0, not vanish.
            cur.execute(
                '''
                SELECT gs.week AS week, COALESCE(apps.cnt, 0) AS cnt
                FROM generate_series(
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s) - INTERVAL '11 weeks',
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s),
                    INTERVAL '1 week'
                ) AS gs(week)
                LEFT JOIN (
                    SELECT DATE_TRUNC(
                        'week', "createdAt" AT TIME ZONE 'UTC' AT TIME ZONE %s
                    ) AS week, COUNT(DISTINCT "jobId") AS cnt
                    FROM "Application" WHERE "userId" = %s
                    AND "createdAt" >= %s::timestamptz - INTERVAL '84 days'
                    GROUP BY week
                ) apps ON apps.week = gs.week
                ORDER BY gs.week
                ''',
                (
                    now_utc, _ANALYTICS_TIMEZONE, now_utc, _ANALYTICS_TIMEZONE,
                    _ANALYTICS_TIMEZONE, user_id, now_utc,
                ),
            )
            app_week_rows = rows_to_dicts(cur)

            # Average fit-score trend (weekly) as a demand proxy. The grid
            # itself is zero-filled (every week 0..11 always has a row) so
            # ``len(fit_week_rows)`` stays a fixed 12, but the FIT VALUE is
            # deliberately left NULL, never COALESCEd to 0 (R-01, AX
            # re-review round 2): this is an AVERAGE, not a count/sum, so
            # "no job was scored this week" and "the average fit score was
            # genuinely 0.00" are different facts — COALESCE(avg_fit, 0)
            # collapsed them into the same fabricated number (live prod
            # evidence: 8 of 12 weeks predating the account's own creation
            # rendered as a flat "0.00" line, and a week with no scored jobs
            # could compute a spurious "-100%" drop). A week with no scored
            # jobs is an absent measurement and stays absent on the wire.
            cur.execute(
                '''
                SELECT gs.week AS week, fit.avg_fit AS fit
                FROM generate_series(
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s) - INTERVAL '11 weeks',
                    DATE_TRUNC('week', %s::timestamptz AT TIME ZONE %s),
                    INTERVAL '1 week'
                ) AS gs(week)
                LEFT JOIN (
                    SELECT DATE_TRUNC(
                        'week', "createdAt" AT TIME ZONE 'UTC' AT TIME ZONE %s
                    ) AS week, AVG("fitScore") AS avg_fit
                    FROM "Job" WHERE "userId" = %s AND "fitScore" IS NOT NULL
                    AND "createdAt" >= %s::timestamptz - INTERVAL '84 days'
                    GROUP BY week
                ) fit ON fit.week = gs.week
                ORDER BY gs.week
                ''',
                (
                    now_utc, _ANALYTICS_TIMEZONE, now_utc, _ANALYTICS_TIMEZONE,
                    _ANALYTICS_TIMEZONE, user_id, now_utc,
                ),
            )
            fit_week_rows = rows_to_dicts(cur)

    # ---- Sources → percentages -------------------------------------------
    # MON-014: percentages must be normalized against sourcesTotal (the true
    # COUNT(*) of this user's Job rows, shown in this SAME donut's center
    # text) — not the top-5-source subtotal. Normalizing to the truncated
    # subtotal silently dropped every long-tail source from the percentage
    # math while still counting it in the displayed center total (live
    # audit: top-5 subtotal 7,626 vs sourcesTotal 7,801 — 175 jobs vanished
    # from the math). An honest "Other" slice carries whatever the top 5
    # don't, computed by the SAME largest-remainder rounding as every named
    # slice, so the full donut (top-5 + Other) still sums to exactly 100.
    denom = sources_total or 1
    top5_counts = [int(r["cnt"]) for r in source_rows]
    other_count = sources_total - sum(top5_counts)
    has_other = other_count > 0
    slice_counts = [*top5_counts, other_count] if has_other else top5_counts

    # Compute rounded percentages via largest remainder so they sum to 100%.
    raw_pcts = [c / denom * 100 for c in slice_counts]
    floored = [int(p) for p in raw_pcts]
    remainders = [(raw_pcts[i] - floored[i], i) for i in range(len(raw_pcts))]
    remaining = 100 - sum(floored)
    for _, idx in sorted(remainders, key=lambda x: (-x[0], x[1]))[:remaining]:
        floored[idx] += 1

    # Colours are assigned by RANK (source_rows arrives ordered by count), so
    # the top four slices each get their own CHART_PALETTE hue and everything
    # past them — plus the rolled-up "Other" — takes the reserved overflow
    # tone. No cycling, no fifth hue, and no two NAMED sources sharing a hue.
    sources: list[dict[str, Any]] = []
    for idx, r in enumerate(source_rows):
        label = str(r["source"])
        color = _CHART_PALETTE[idx] if idx < len(_CHART_PALETTE) else _CHART_OTHER
        sources.append(
            {
                "label": label[:1].upper() + label[1:],
                "value": floored[idx],
                "color": color,
            }
        )
    if has_other:
        sources.append(
            {
                "label": "Other",
                "value": floored[len(top5_counts)],
                "color": _CHART_OTHER,
            }
        )

    # ---- Top skills (lexicon match — counted once per job) ----------------
    skill_counts: dict[str, int] = {}
    for row in requirement_rows:
        reqs = row.get("requirements")
        text = ""
        if isinstance(reqs, list):
            text = " ".join(r for r in reqs if isinstance(r, str)).lower()
        if not text:
            # QA-2026-08-13 M-02 fallback: requirements are empty for the
            # vast majority of sourced jobs, so match the lexicon against
            # the posting title + description instead of showing "Not
            # enough data" forever. Still counted at most once per job.
            text = " ".join(
                s for s in (row.get("title"), row.get("description")) if isinstance(s, str)
            ).lower()
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
    # Oldest → newest across 35 days; row 0 = oldest week. MON-015: anchor on
    # today's MELBOURNE-local date (matching the query's SQL-side bucketing
    # above), not the UTC date — converted via astimezone() rather than
    # passed directly to now() so this stays correct under any tz argument.
    today = now_utc.astimezone(_ANALYTICS_ZONEINFO).date()
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
    # ``_PROBABILITY_USES_MARKET_EVIDENCE = False``. The input has no information,
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
    # DEFINITION and is filtered against the very same constant this response
    # publishes as ``probability.marketDataConnected``, so a factor claiming
    # market evidence cannot be emitted while that panel says the model has
    # none — the factor is simply not built. That constant is NOT the Market
    # vs. You connection state, which is now per-row and live (R5): a posting
    # count is not evidence about this user's chances, so it gates no factor.
    # No factor sets the flag today; the mechanism exists so the next one has
    # to declare its dependence rather than quietly reintroduce the
    # contradiction this fix removed.
    factors: list[dict[str, Any]] = [
        {"label": label, "value": value if measured else None, "measured": measured}
        for label, value, measured, requires_market_data in factor_specs
        if _PROBABILITY_USES_MARKET_EVIDENCE or not requires_market_data
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
        event, signal = _status_event(
            str(r.get("company") or ""),
            str(r.get("status") or ""),
            transmitted=r.get("transmittedAt") is not None,
        )
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
    delta_label, delta_direction, delta_kind = _pct_delta([float(v) for v in agent_series])
    recruiter_trends = {
        "series": agent_series,
        "rows": [
            {
                "label": "Agent runs (last 12 wks)",
                "delta": f"{total_runs} total",
                # MUST-FIX-1 (AX round-3 final re-review, RULING-A/C extended
                # to this sibling card): this is a plain cumulative count, not
                # a comparison — "total" is a NEW deltaKind (not one of
                # trendIndicators' percent/new/insufficient-data) so the FE
                # can never route it through green/coral directional styling,
                # the exact defect this row previously had (COMPOUNDING part
                # of MUST-FIX-1: unconditional text-aether-green).
                "direction": "flat",
                "deltaKind": "total",
            },
            {
                "label": "Avg runs / week",
                "delta": f"{round(total_runs / weeks_active, 1)} · {delta_label}",
                # `_pct_delta` already computes a real direction/kind for
                # this SAME comparison the delta text embeds — plumbed onto
                # the row (previously discarded) so the FE badge can agree
                # with it instead of hardcoding a color regardless of sign.
                "direction": delta_direction,
                "deltaKind": delta_kind,
            },
        ],
    }

    # ---- Market vs you ------------------------------------------------
    # Each row states its OWN provenance: whether a real external benchmark
    # backs its market side (``connected``), when that data was fetched
    # (``dataAsOf``), what the market number literally counts
    # (``marketNote``), and why it is absent when it is (``footnote``). A row
    # without a provider stays market=None forever rather than borrowing a
    # number from a different measurement (GAP-P4-060).
    you_apps_month = int(f_last_month or 0)
    you_apps_month_transmitted = int(f_last_month_transmitted or 0)
    target_role, target_location = _user_market_target(user_id)
    benchmark = fetch_market_benchmark(target_role, target_location)
    postings_market = benchmark.postingsLast30d if benchmark is not None else None
    postings_as_of = (
        benchmark.dataAsOf
        if benchmark is not None and benchmark.postingsLast30d is not None
        else None
    )

    postings_row: dict[str, Any] = {
        "label": "Applications / month",
        "market": postings_market,
        "you": you_apps_month,
        # CLI-D3 additive: of the ``you`` applications in this same 30-day
        # window, how many carry a verified send (transmittedAt) — submitted
        # counts applications that left draft (preparation), transmitted
        # counts verified sends. ``you`` keeps its exact prior meaning.
        "transmitted": you_apps_month_transmitted,
        "connected": postings_market is not None,
        "dataAsOf": postings_as_of,
    }
    if benchmark is not None and postings_market is not None:
        # The two sides are NOT the same quantity, and the row says so: "you"
        # is applications this user submitted, "market" is employer demand.
        # The scope must be stated as widely as the search really was — the
        # benchmark OR-searches the whole target-role family (the same
        # broadening discovery uses), so a count for a family may never be
        # described as a count for the one title the user typed.
        searched = benchmark_query_terms(benchmark.role)
        scope = (
            benchmark.role
            if len(searched) <= 1
            else f"{benchmark.role} and {len(searched) - 1} related titles in the same role family"
        )
        postings_row["marketNote"] = (
            f"Market = {postings_market} job ads posted in the last 30 days in "
            f"{benchmark.location} for {scope} (Adzuna Australia) — employer "
            "demand, not applications sent by other candidates."
        )

    interview_row: dict[str, Any] = {
        "label": "Interview rate",
        "market": None,
        "you": interview_rate,
        "unit": "%",
        "connected": False,
        "dataAsOf": None,
        "footnote": _INTERVIEW_RATE_FOOTNOTE,
    }

    # Advertised salary — the one row where BOTH sides are salaries, so they
    # are genuinely comparable. Market is the provider's mean over the ads it
    # matched; "you" is the median of what the caller's OWN saved postings
    # disclosed, and is ``None`` (never 0, never the market's figure) when they
    # disclosed nothing. The two sides are independent: the market side stays
    # real when the caller has no disclosures, and the caller's own median
    # stays on screen when the provider is unreachable.
    mean_salary = benchmark.meanAdvertisedSalary if benchmark is not None else None
    salary_as_of = (
        benchmark.dataAsOf
        if benchmark is not None and mean_salary is not None
        else None
    )
    you_salary_median = user_disclosed_salary_median(user_id)
    salary_row: dict[str, Any] = {
        "label": "Advertised salary (mean)",
        "market": round(mean_salary) if mean_salary is not None else None,
        "you": you_salary_median,
        "unit": "A$",
        "connected": mean_salary is not None,
        "dataAsOf": salary_as_of,
    }
    if benchmark is not None and mean_salary is not None:
        # Says whose mean it is and which search produced it, and claims
        # nothing about how the provider computed it — Adzuna publishes the
        # figure, not its denominator, so "across the N ads" would assert more
        # than the response supports.
        salary_row["marketNote"] = (
            "Market = the mean advertised salary Adzuna Australia reports (AUD) "
            + (
                f"for the same search that counted the {benchmark.postingsLast30d} "
                "ads above."
                if benchmark.postingsLast30d is not None
                else "for your target role in that location."
            )
        )
    salary_row["footnote"] = (
        "No disclosed salary data in your saved jobs yet — most ads publish no "
        "range, and none is estimated in their place."
        if you_salary_median is None
        # The caller's side is about ADS, not about them: it is what the jobs
        # they saved advertised, and saying so stops a bar that sits beside a
        # market mean from reading as their current or expected pay.
        else "You = the median salary advertised by your own saved jobs that "
        "published a figure — what those ads offered, not what you earn."
    )

    comparisons: list[dict[str, Any]] = [postings_row, interview_row, salary_row]
    # NO global connected flag (R5): it could only ever be an OR across rows
    # whose provenance genuinely differs — the interview row has no provider
    # at all and never will — so a single boolean would have to misdescribe at
    # least one of them. Every consumer reads the rows.
    market_vs_you = {
        "comparisons": comparisons,
        "summary": _market_summary(benchmark),
    }

    # ---- Trend indicators (all series from real weekly rollups) ----------
    app_series: list[float] = [float(r["cnt"]) for r in app_week_rows]
    spend_series: list[float] = [round(float(r["spend"]), 4) for r in agent_spend_rows]
    # R-01: an unscored week is a real gap, not a fabricated 0 — see the
    # fit_week_rows SQL comment above. ``None`` survives all the way to the
    # wire so the FE renders a genuine gap, never a flat-zero line.
    fit_series: list[float | None] = [
        round(float(r["fit"]), 2) if r["fit"] is not None else None for r in fit_week_rows
    ]

    def _count_indicator(label: str, series: list[float]) -> dict[str, Any] | None:
        """COUNT/SUM trend indicator: zero-filled, no gap-skipping needed."""
        if not series:
            return None
        delta, direction, kind = _pct_delta(series)
        return {
            "label": label,
            "delta": delta,
            "direction": direction,
            "deltaKind": kind,
            "series": [round(v, 2) for v in series],
        }

    def _avg_indicator(label: str, series: list[float | None]) -> dict[str, Any] | None:
        """AVERAGE trend indicator (R-01/RULING-B): ``None`` weeks stay
        ``None`` on the wire (never fabricated as 0) and the delta skips
        them to find the two most recent complete weeks with real data.
        """
        if not series:
            return None
        delta, direction, kind = _pct_delta_avg(series)
        return {
            "label": label,
            "delta": delta,
            "direction": direction,
            "deltaKind": kind,
            "series": [round(v, 2) if v is not None else None for v in series],
        }

    trend_indicators = [
        indicator
        for indicator in (
            _count_indicator("Your application velocity", app_series),
            _count_indicator("Agent automation spend", spend_series),
            _avg_indicator("Avg job fit score", fit_series),
        )
        if indicator is not None
    ]

    return {
        "sources": sources,
        "sourcesTotal": sources_total,
        # sourcesTotal is a count of Job rows (discovery-source breakdown),
        # not applications — the caption must say so honestly (GAP-P4-058).
        "sourcesLabel": "jobs sourced",
        "topSkills": top_skills,
        "activityHeatmap": activity_heatmap,
        # MON-015: the calendar the heatmap/weekly-trend day-and-week
        # boundaries above are actually computed in — disclosed on the wire
        # so a reader (or the FE) never has to guess it.
        "timezone": _ANALYTICS_TIMEZONE,
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
            # DELIBERATELY DECOUPLED from Market vs. You (R5; see the
            # constant's own comment). This flag reports whether the
            # PROBABILITY model has market evidence to reason from — a flat
            # ``False`` — while Market vs. You reports the live state of the
            # Adzuna benchmark PER ROW and carries no global flag of its own.
            # The two readings DISAGREE whenever that benchmark returns data:
            # that is by design, so do not "fix" them back into sync.
            "marketDataConnected": _PROBABILITY_USES_MARKET_EVIDENCE,
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


@router.get("/networking")
def networking_analytics(current_user: CurrentUser) -> dict[str, Any]:
    """Orchestrator CRM snapshot — counts and employer names, never emails."""
    from app.services.networking_insights import build_analytics_snapshot

    return build_analytics_snapshot(current_user["id"])


@router.get("")
def dashboard_root(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Dashboard summary — alias for the root analytics path."""
    return _dashboard(current_user, period)


@router.get("/dashboard")
def dashboard(current_user: CurrentUser, period: str = "all") -> dict[str, Any]:
    """Dashboard summary with key metrics across all analytics dimensions."""
    return _dashboard(current_user, period)


def _user_market_target(user_id: str) -> tuple[str, str]:
    """The user's OWN target role and location (``""`` for each unset).

    Reads the same two profile columns discovery derives a search from
    (``_user_search_defaults`` in the agents router) and substitutes NOTHING
    (F-02): a user who has not told us what they are looking for gets an
    honest "no market data" panel, never somebody else's market.
    """
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "targetRole", "location" FROM "User" WHERE id = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        return "", ""
    return (
        (rows[0].get("targetRole") or "").strip(),
        (rows[0].get("location") or "").strip(),
    )


def _market_summary(benchmark: MarketBenchmark | None) -> str:
    """One sentence naming the real provider and the real numbers, or the
    honest no-provider string.

    This once fabricated a comparison against hardcoded constants
    (_MARKET_APPS_PER_MONTH / _MARKET_INTERVIEW_RATE) presented as if they
    were real market data — see GAP-P4-060. Now it either cites Adzuna
    Australia with the figures actually returned, or reports the gap. No
    adjectives, no interpretation, nothing the response did not contain.

    Each sentence after the first is emitted ONLY when its own field really
    arrived, and states that field's OWN scope — which is not the same for all
    three. The posting count is for the caller's role family in their location;
    the 12-month salary range is for ALL ADVERTISED ROLES in the region the
    provider was actually asked about (``/history`` accepts no role at all);
    the band sentence is for the target role. Saying "the market" flatly across
    the three would be wrong about two of them.
    """
    if benchmark is None or benchmark.postingsLast30d is None:
        return _NO_MARKET_DATA_SUMMARY
    sentences = [
        f"Market data: Adzuna Australia — {benchmark.postingsLast30d} live "
        f"postings (last 30 days) for your target role in {benchmark.location}."
    ]
    if benchmark.meanAdvertisedSalary is not None:
        sentences.append(
            "Adzuna reports a mean advertised salary of "
            f"A${round(benchmark.meanAdvertisedSalary):,} for that same search."
        )
    trend = benchmark.salaryTrend12m
    if trend:
        sentences.append(
            f"Over the last {len(trend)} months the average advertised salary "
            f"across all advertised roles in {benchmark_region_label(benchmark.location)} "
            f"— every role, not just yours — ranged A${round(min(trend.values())):,} "
            f"to A${round(max(trend.values())):,}."
        )
    bands = benchmark.salaryHistogram
    # MON-013: a live Adzuna /histogram response can be a non-empty dict
    # where EVERY band's count is 0 (verified live 2026-08-13) — `if bands:`
    # alone still passes (the dict is non-empty), so `max(...)` picked an
    # arbitrary tied-at-zero band and printed the self-contradicting
    # "(0) advertise the A$X band" sentence. Only emit the clause when some
    # band actually has a non-zero count to name honestly.
    if bands and max(bands.values()) > 0:
        top_band = max(bands, key=lambda band: bands[band])
        sentences.append(
            f"Most live ads for your target role ({bands[top_band]}) advertise "
            f"the {_salary_band_label(top_band)} band."
        )
    return " ".join(sentences)


def _salary_band_label(band: str) -> str:
    """The provider's own histogram band key, thousands-separated for reading.

    The DIGITS are Adzuna's verbatim; only separators and a currency prefix are
    added. A non-numeric key is passed through untouched rather than coerced
    into a number that was never returned.
    """
    try:
        return f"A${int(band):,}"
    except ValueError:
        return band
