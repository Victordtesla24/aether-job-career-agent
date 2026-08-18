"""ADMIN-2.0 BE-2 — the executive dashboard's single metrics read.

``GET /admin/metrics/executive`` is the ONE endpoint the dashboard polls, so the
page makes one request instead of racing six, and every tile on it is derived
from the same instant (``asOf``).

THE RULES THIS MODULE IS BUILT AROUND
    1. EVERY figure comes from a real query over real rows. There is no
       constant, no sample data and no interpolation anywhere in this file.
    2. LLM cost is USD (providers bill USD) and subscription money is AUD. They
       are reported side by side and NEVER summed, differenced or divided: no FX
       rate is available here, so ``fxRateApplied`` is ``null`` and no combined
       figure is offered at all. Publishing a margin computed on an invented
       rate would be a fabricated number on an executive screen.
    3. Revenue is money that ARRIVED — locally recorded, signature-verified
       ``invoice.paid`` webhook payloads, net of real refunds. A local
       "pro/active" Subscription row with nothing behind it at Stripe (the
       owner's own stale row today) is reported as ``unbackedPaidRows``, never
       as revenue.
    4. The platform has ~10 accounts and ~0 external subscribers TODAY. Small
       numbers are shown as they are; what is suppressed is the RATE-shaped
       reading of them. Every block therefore carries ``sampleSize`` and
       ``insufficientData`` so the UI can render an honest "not enough data yet"
       state instead of a precise-looking percentage drawn from three rows.

Read-only by construction: this module issues SELECTs only.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.db import (
    ensure_application_transmission_columns,
    ensure_user_lifecycle_columns,
    get_connection,
    rows_to_dicts,
)
from app.repositories.admin_billing import BILLABLE_STATUSES, billing_summary
from app.repositories.billing import _ensure_billing_tables
from app.repositories.sales_agents import (
    PLATFORM_CURRENCY,
    _accumulate,
    _minor_to_major,
    _payment_event_rows,
    attribution_counts,
    ensure_sales_agent_schema,
)

#: Trailing window for every time-series and every "last 30 days" figure.
WINDOW_DAYS = 30

#: Below this many observations a RATE or a trend is not a reading, it is noise.
#: Exposed in the payload (``insufficientDataThreshold``) so the number the UI
#: renders against is the same number the API applied — not a second, drifting
#: copy in the frontend.
INSUFFICIENT_DATA_THRESHOLD = 20

#: How many agents the "top referrers" block returns.
TOP_REFERRER_LIMIT = 5


def _utc_today() -> date:
    return datetime.now(tz=timezone.utc).date()


def _window_dates(days: int = WINDOW_DAYS) -> list[date]:
    """The ``days`` UTC dates ending today, oldest first."""
    today = _utc_today()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _insufficient(sample: int) -> bool:
    return sample < INSUFFICIENT_DATA_THRESHOLD


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


def _signups_by_day(cur: Any, cur_since: datetime, dates: list[date]) -> dict[str, Any]:
    """New non-admin, non-deleted accounts per UTC day, zero-filled.

    Admin/owner accounts are staff, not growth, so they are excluded here and
    counted in the ``excluded`` block instead of inflating the series.

    The WHERE compares the raw ``timestamptz`` against the window start (index
    friendly); only the GROUP BY converts to a UTC calendar day, so the buckets
    are UTC regardless of the session time zone.
    """
    cur.execute(
        'SELECT ("createdAt" AT TIME ZONE \'UTC\')::date AS "day", count(*) AS "n"'
        ' FROM "User"'
        ' WHERE "isAdmin" = false AND "deletedAt" IS NULL AND "createdAt" >= %s'
        " GROUP BY 1",
        (cur_since,),
    )
    counts = {row["day"]: int(row["n"]) for row in rows_to_dicts(cur)}
    series: list[dict[str, Any]] = []
    total = 0
    for day in dates:
        count = counts.get(day, 0)
        total += count
        series.append({"date": day.isoformat(), "count": count})
    return {
        "series": series,
        "total": total,
        "windowDays": len(dates),
        "excludes": "admin accounts and soft-deleted accounts",
        "sampleSize": total,
        "insufficientData": _insufficient(total),
    }


def _runs_by_day(cur: Any, cur_since: datetime, dates: list[date]) -> dict[str, Any]:
    """Agent runs and their REAL USD LLM cost per UTC day, zero-filled.

    Deliberately counts EVERY run, admin/owner runs included: the provider
    charged for those too, so excluding them would understate real spend.
    """
    cur.execute(
        'SELECT ("createdAt" AT TIME ZONE \'UTC\')::date AS "day", count(*) AS "n",'
        ' COALESCE(SUM("costUsd"), 0) AS "cost"'
        ' FROM "AgentRun" WHERE "createdAt" >= %s'
        " GROUP BY 1",
        (cur_since,),
    )
    rows = {
        row["day"]: (int(row["n"]), float(row["cost"])) for row in rows_to_dicts(cur)
    }
    series = []
    total_runs = 0
    total_cost = 0.0
    for day in dates:
        runs, cost = rows.get(day, (0, 0.0))
        total_runs += runs
        total_cost += cost
        series.append(
            {"date": day.isoformat(), "runs": runs, "costUsd": round(cost, 4)}
        )
    return {
        "series": series,
        "totalRuns": total_runs,
        "totalCostUsd": round(total_cost, 4),
        "currency": "USD",
        "windowDays": len(dates),
        "includes": "all accounts (admin runs cost real money too)",
        "sampleSize": total_runs,
        "insufficientData": _insufficient(total_runs),
    }


#: What each funnel stage MEANS, shipped with the numbers so the dashboard
#: cannot relabel them into something they are not.
_FUNNEL_DEFINITIONS = {
    "signup": (
        "Accounts created (admin/owner accounts and soft-deleted accounts "
        "excluded)."
    ),
    "firstRun": "Of those accounts, the ones with at least one AgentRun row.",
    # AUD-META-1 (RUN-20260818T0223Z, r2): this stage's LABEL used to read
    # "Submitted an application", which claims a transmission the underlying
    # query cannot support — "status <> 'draft'" is the user's own tracker
    # state, set the instant an application leaves draft, whether or not
    # anything was ever sent to an employer. Relabelled to "Prepared an
    # application", matching the "Prepared" vocabulary already shipped for
    # this exact population on the cohorts/Sankey/market-pulse surfaces
    # (fix 4688c29a). See "firstTransmission" for the verified-send count.
    "firstSubmission": (
        "Of those accounts, the ones with at least one Application that left "
        "'draft'. This is the user's own tracker state — it records "
        "preparation, not a verified transmission (see 'firstTransmission')."
    ),
    # AUD-META-1 (r2): additive — the DISTINCT subset of the same accounts
    # with a real send behind them (`transmittedAt` is stamped only by the
    # actual submission path, never by a bare status change).
    "firstTransmission": (
        "Of those accounts, the ones with at least one Application Aether "
        "verifiably transmitted ('transmittedAt' IS NOT NULL) — the real "
        "send path, not merely a status that left 'draft'."
    ),
    "paid": (
        "Of those accounts, the ones on a non-free plan in a billable status "
        "WITH a real Stripe subscription behind it."
    ),
    "_shape": (
        "Stages are INDEPENDENT milestone counts over the same signup "
        "population, not nested subsets. A later stage can therefore exceed an "
        "earlier one (e.g. someone paid without ever submitting) — that is a "
        "real signal and is not smoothed away."
    ),
}


def _funnel(cur: Any) -> dict[str, Any]:
    # AUD-META-1 (r2): the "firstTransmission" sub-select below reads the lazy
    # additive "transmittedAt" column — callers of this function MUST have
    # already called ensure_application_transmission_columns() (see
    # executive_metrics(), which does so before the read connection is
    # taken, per this module's own "Lazy DDL … never inside it" rule).
    cur.execute(
        'WITH base AS ('
        '  SELECT u."id" FROM "User" u'
        '  WHERE u."isAdmin" = false AND u."deletedAt" IS NULL'
        ")"
        " SELECT"
        "   (SELECT count(*) FROM base) AS signups,"
        '   (SELECT count(DISTINCT r."userId") FROM "AgentRun" r'
        '      JOIN base b ON b."id" = r."userId") AS first_run,'
        '   (SELECT count(DISTINCT a."userId") FROM "Application" a'
        '      JOIN base b ON b."id" = a."userId"'
        "      WHERE a.\"status\" <> 'draft') AS first_submission,"
        # AUD-META-1 (r2): the same population's verified-send subset —
        # "transmittedAt" is stamped only by the real send path
        # (app.agents.submission_agent), never by a bare status change. Same
        # query shape as the sub-select above (additive, cheap: one more
        # DISTINCT-userId scan of "Application" joined to the same base CTE).
        '   (SELECT count(DISTINCT a."userId") FROM "Application" a'
        '      JOIN base b ON b."id" = a."userId"'
        '      WHERE a."transmittedAt" IS NOT NULL) AS first_transmission,'
        '   (SELECT count(DISTINCT s."userId") FROM "Subscription" s'
        '      JOIN base b ON b."id" = s."userId"'
        '      WHERE s."stripeSubscriptionId" IS NOT NULL'
        "        AND COALESCE(s.\"planId\",'free') <> 'free'"
        '        AND s."status" = ANY(%s)) AS paid',
        (list(BILLABLE_STATUSES),),
    )
    row = rows_to_dicts(cur)[0]
    signups = int(row["signups"])
    stages: list[dict[str, Any]] = []
    for key, label, count in (
        ("signup", "Signed up", signups),
        ("firstRun", "Ran an agent", int(row["first_run"])),
        # AUD-META-1 (r2): "status <> 'draft'" is preparation, not a verified
        # send — the label must not claim "submitted"/"applied"/"sent" (see
        # the "firstTransmission" stage immediately below for that claim).
        ("firstSubmission", "Prepared an application", int(row["first_submission"])),
        ("firstTransmission", "Sent an application", int(row["first_transmission"])),
        ("paid", "Paid", int(row["paid"])),
    ):
        stages.append(
            {
                "key": key,
                "label": label,
                "count": count,
                # A share of the signup population — well defined at any N. The
                # block-level insufficientData flag says whether it is worth
                # reading; None when there is no population to divide by.
                "shareOfSignups": round(count / signups, 4) if signups else None,
            }
        )
    return {
        "window": "all time",
        "stages": stages,
        "definitions": _FUNNEL_DEFINITIONS,
        "sampleSize": signups,
        "insufficientData": _insufficient(signups),
    }


def _excluded_counts(cur: Any) -> dict[str, int]:
    cur.execute(
        'SELECT count(*) FILTER (WHERE "isAdmin" = true) AS admins,'
        ' count(*) FILTER (WHERE "deletedAt" IS NOT NULL) AS deleted'
        ' FROM "User"'
    )
    row = rows_to_dicts(cur)[0]
    return {
        "adminAccounts": int(row["admins"]),
        "deletedAccounts": int(row["deleted"]),
    }


def _cost_vs_revenue(
    cur: Any, since: datetime, llm_cost_usd: float, window_days: int
) -> dict[str, Any]:
    """LLM spend (USD) beside money actually received (AUD) — never combined.

    Revenue here is NOT the MRR estimate: it is the sum of real ``invoice.paid``
    events in the window, net of real refunds in the window. A refund of an
    older charge lands in the window it was issued, because that is when the
    money left.
    """
    rows = _payment_event_rows(cur, since=since)
    by_customer, unparsable, unattributed = _accumulate(rows)
    gross_minor = 0
    refunded_minor = 0
    payment_count = 0
    other: dict[str, int] = {}
    for totals in by_customer.values():
        gross_minor += totals.gross.get(PLATFORM_CURRENCY, 0)
        refunded_minor += totals.refunded.get(PLATFORM_CURRENCY, 0)
        payment_count += totals.counts.get(PLATFORM_CURRENCY, 0)
        for currency, amount in totals.gross.items():
            if currency != PLATFORM_CURRENCY:
                other[currency] = other.get(currency, 0) + amount
    gross = _minor_to_major(gross_minor)
    refunds = _minor_to_major(refunded_minor)
    return {
        "windowDays": window_days,
        "llmCostUsd": round(llm_cost_usd, 4),
        "grossRevenueAud": gross,
        "refundsAud": refunds,
        "revenueAud": round(gross - refunds, 2),
        "paymentCount": payment_count,
        "otherCurrencyGrossMinorUnits": other,
        # No FX rate is available to this service, so no cross-currency figure
        # is published. The two numbers above are NOT comparable as printed.
        "fxRateApplied": None,
        "note": (
            "LLM cost is USD and revenue is AUD. No exchange rate is applied "
            "and no combined margin is reported — the two figures are shown "
            "side by side, not netted."
        ),
        "revenueSource": (
            "real invoice.paid Stripe webhook events recorded locally, net of "
            "real charge.refunded events in the same window. A refund is "
            "recognised at the cumulative refunded total its charge showed "
            "inside the window, so a charge refunded partly before and partly "
            "during the window is deducted at its running total, not at the "
            "in-window increment"
        ),
        "unparsablePaymentEvents": unparsable,
        "unattributedRefundEvents": unattributed,
        "sampleSize": payment_count,
        "insufficientData": _insufficient(payment_count),
    }


def _top_referrers(cur: Any) -> dict[str, Any]:
    """Sales agents that have actually brought accounts in, best first.

    Agents with zero attributed signups are omitted — a "top referrer" list
    padded with people who have referred nobody is decoration, not information.
    """
    counts = attribution_counts(cur)
    if not counts:
        return {
            "agents": [],
            "sampleSize": 0,
            "insufficientData": True,
            "limit": TOP_REFERRER_LIMIT,
        }
    cur.execute(
        'SELECT "id","name","referralCode","status","commissionPct"'
        ' FROM "SalesAgent" WHERE "id" = ANY(%s)',
        (list(counts.keys()),),
    )
    agents = []
    for row in rows_to_dicts(cur):
        bucket = counts.get(row["id"], {})
        agents.append(
            {
                "id": row["id"],
                "name": row["name"],
                "referralCode": row["referralCode"],
                "status": row["status"],
                "commissionPct": round(float(row["commissionPct"]), 4),
                "attributedSignups": bucket.get("signups", 0),
                "convertedPaid": bucket.get("converted", 0),
            }
        )
    agents.sort(
        key=lambda a: (-a["convertedPaid"], -a["attributedSignups"], a["name"] or "")
    )
    total_attributed = sum(a["attributedSignups"] for a in agents)
    return {
        "agents": agents[:TOP_REFERRER_LIMIT],
        "totalAgentsWithSignups": len(agents),
        "totalAttributedSignups": total_attributed,
        "limit": TOP_REFERRER_LIMIT,
        "sampleSize": total_attributed,
        "insufficientData": _insufficient(total_attributed),
    }


def _failed_runs_24h(cur: Any) -> dict[str, Any]:
    """Failed AgentRun rows in the last 24 hours. Rate stays null below threshold."""
    cur.execute(
        'SELECT COUNT(*) FILTER (WHERE "status" = %s) AS failed,'
        ' COUNT(*) AS total'
        ' FROM "AgentRun"'
        ' WHERE "startedAt" >= NOW() - INTERVAL \'24 hours\'',
        ("failed",),
    )
    row = rows_to_dicts(cur)[0]
    failed = int(row["failed"] or 0)
    total = int(row["total"] or 0)
    rate = (failed / total) if total > 0 else None
    return {
        "failed": failed,
        "total": total,
        "rate": rate,
        "windowHours": 24,
        "sampleSize": total,
        "insufficientData": total == 0 or _insufficient(total),
    }


def sales_ai_cost_usd_30d() -> float:
    """USD billed on salesAgent runs in the last 30 days. Unwritten cost stays 0."""
    from app.agents.sales_agent import AGENT_KEY

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT COALESCE(SUM("costUsd"), 0) FROM "AgentRun"'
                ' WHERE "agentName" = %s'
                ' AND "startedAt" >= NOW() - INTERVAL \'30 days\'',
                (AGENT_KEY,),
            )
            return round(float(cur.fetchone()[0] or 0), 4)


def _sales_ai_block() -> dict[str, Any]:
    """In-app Sales AI outreach — not the human-reseller SalesAgent table."""
    from app.agents.sales_agent import sales_agent_dry_run, sales_agent_enabled
    from app.repositories.sales import SalesRepository

    ov = SalesRepository().overview()
    sample = int(ov.get("emailsSent") or 0)
    attributed_signups = int(ov.get("attributedSignups") or 0)
    attributed_paid = int(ov.get("attributedPaid") or 0)
    return {
        "enabled": sales_agent_enabled(),
        "dryRun": sales_agent_dry_run(),
        "emailsSent": ov["emailsSent"],
        "dryRunLogged": ov["dryRunLogged"],
        "repliesObserved": ov["repliesObserved"],
        "replyRate": ov["replyRate"],
        "leads": ov["leads"],
        "linkedinDraftsQueued": ov["linkedinDraftsQueued"],
        "llmCostUsd30d": sales_ai_cost_usd_30d(),
        "attributedSignups": attributed_signups,
        "attributedPaid": attributed_paid,
        "cannotAttributeSignups": False,
        "cannotAttributeReason": (
            "First-touch count of accounts whose signup URL carried "
            "utm_source=aether_sales_agent. That is a landing, not a proven "
            "causal conversion."
        ),
        "sampleSize": sample,
        "insufficientData": _insufficient(sample),
    }


# --------------------------------------------------------------------------- #
# The endpoint's payload
# --------------------------------------------------------------------------- #


def executive_metrics(window_days: Optional[int] = None) -> dict[str, Any]:
    """Everything the executive dashboard renders, from one consistent read."""
    days = int(window_days or WINDOW_DAYS)
    days = max(1, min(days, 365))
    dates = _window_dates(days)
    since = datetime.combine(dates[0], datetime.min.time(), tzinfo=timezone.utc)

    # Lazy DDL happens BEFORE the read connection is taken, never inside it.
    ensure_user_lifecycle_columns()
    # AUD-META-1 (r2): _funnel()'s "firstTransmission" stage reads
    # Application."transmittedAt" — the lazy additive column this call adds.
    ensure_application_transmission_columns()
    ensure_sales_agent_schema()
    _ensure_billing_tables()
    revenue = billing_summary()

    with get_connection() as conn:
        with conn.cursor() as cur:
            signups = _signups_by_day(cur, since, dates)
            runs = _runs_by_day(cur, since, dates)
            funnel = _funnel(cur)
            excluded = _excluded_counts(cur)
            cost_vs_revenue = _cost_vs_revenue(
                cur, since, runs["totalCostUsd"], days
            )
            referrers = _top_referrers(cur)
            failed_runs = _failed_runs_24h(cur)

    sales_ai = _sales_ai_block()

    revenue = dict(revenue)
    revenue["sampleSize"] = int(revenue.get("paidSubscribers", 0))
    revenue["insufficientData"] = _insufficient(revenue["sampleSize"])

    return {
        "asOf": datetime.now(tz=timezone.utc).isoformat(),
        "windowDays": days,
        "currencies": {"revenue": "AUD", "llmCost": "USD"},
        "gstRegistered": False,
        "insufficientDataThreshold": INSUFFICIENT_DATA_THRESHOLD,
        "revenue": revenue,
        "signupsByDay": signups,
        "runsByDay": runs,
        "funnel": funnel,
        "costVsRevenue": cost_vs_revenue,
        "topReferrers": referrers,
        "failedRuns24h": failed_runs,
        "salesAi": sales_ai,
        "excluded": excluded,
    }
