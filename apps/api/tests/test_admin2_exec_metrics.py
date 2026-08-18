"""ADMIN-2.0 BE-2 — ``GET /admin/metrics/executive``.

ONE endpoint the executive dashboard polls. Every figure must come from a real
query against real rows; where N is too small to read anything into, the metric
carries its own ``insufficientData`` flag rather than being dressed up.

THE TWO HONESTY INVARIANTS THIS FILE ENFORCES
  1. LLM cost is USD and revenue is AUD. They are reported side by side and
     NEVER summed, differenced or ratio'd — no FX rate is applied, and the
     payload says so (``fxRateApplied: null``).
  2. Revenue counts only money that really arrived: locally-recorded,
     signature-verified ``invoice.paid`` webhook rows, net of real refunds.
     A local "pro/active" Subscription row with nothing behind it at Stripe
     (the owner's own stale row today) is NOT revenue.

SHARED-SCHEMA DISCIPLINE: ``aether_test`` is shared with concurrent sessions and
``Subscription``/``StripeEvent``/``SalesAgent`` are never truncated, so the
assertions below are DELTAS around a before/after snapshot or scoped to a
uuid-unique row — never a global equality.
"""
from __future__ import annotations

import json
import uuid

from app.db import get_connection, new_id
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import _ensure_billing_tables

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1", **kwargs) -> tuple[str, str]:
    payload: dict = {"email": email, "password": password}
    payload.update(kwargs)
    r = client.post("/auth/register", json=payload)
    assert r.status_code == 201, r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["userId"]


def _promote(user_id: str) -> None:
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin(client) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"admin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _metrics(client, headers) -> dict:
    r = client.get("/admin/metrics/executive", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _seed_run(
    user_id: str,
    *,
    cost_usd: float = 0.01,
    days_ago: int = 0,
    status: str = "completed",
    agent_name: str = "scout",
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "AgentRun" ("id","userId","agentName","status","costUsd",
                    "startedAt","completedAt","createdAt")
                VALUES (%s,%s,%s,%s,%s, NOW(), NOW(),
                        NOW() - make_interval(days => %s))
                ''',
                (new_id(), user_id, agent_name, status, cost_usd, days_ago),
            )
        conn.commit()


def _seed_submitted_application(user_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            job_id = new_id()
            cur.execute(
                '''
                INSERT INTO "Job" ("id","userId","title","company","description",
                    "source","sourceUrl","createdAt","updatedAt")
                VALUES (%s,%s,'Job','Acme','desc','seek',%s, NOW(), NOW())
                ''',
                (job_id, user_id, f"https://example.com/{job_id}"),
            )
            cur.execute(
                '''
                INSERT INTO "Resume" ("id","userId","sections","formatHash","updatedAt")
                VALUES (%s,%s,'{}','seedhash', NOW()) RETURNING "id"
                ''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
            cur.execute(
                '''
                INSERT INTO "Application" ("id","userId","jobId","resumeId","status",
                    "createdAt","updatedAt")
                VALUES (%s,%s,%s,%s,'submitted'::"ApplicationStatus", NOW(), NOW())
                ''',
                (new_id(), user_id, job_id, resume_id),
            )
        conn.commit()


def _seed_paid_subscription(user_id: str, customer_id: str, *, plan_id: str = "pro") -> None:
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Subscription" ("userId","planId","status","billingInterval",'
                '"stripeCustomerId","stripeSubscriptionId") VALUES (%s,%s,%s,%s,%s,%s)'
                ' ON CONFLICT ("userId") DO UPDATE SET "planId"=EXCLUDED."planId",'
                '"status"=EXCLUDED."status","billingInterval"=EXCLUDED."billingInterval",'
                '"stripeCustomerId"=EXCLUDED."stripeCustomerId",'
                '"stripeSubscriptionId"=EXCLUDED."stripeSubscriptionId"',
                (user_id, plan_id, "active", "month", customer_id,
                 f"sub_{uuid.uuid4().hex[:16]}"),
            )
        conn.commit()


def _seed_unbacked_paid_subscription(user_id: str) -> None:
    """A local pro/active row with NO Stripe subscription — the owner's real
    stale-row shape. Must never be counted as revenue."""
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Subscription" ("userId","planId","status","billingInterval")'
                ' VALUES (%s,%s,%s,%s) ON CONFLICT ("userId") DO UPDATE SET'
                ' "planId"=EXCLUDED."planId","status"=EXCLUDED."status",'
                ' "stripeSubscriptionId"=NULL',
                (user_id, "pro", "active", "month"),
            )
        conn.commit()


def _record_invoice_paid(
    customer_id: str, amount_minor: int, *, currency: str = "aud", days_ago: int = 0
) -> None:
    _ensure_billing_tables()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex[:16]}",
                "customer": customer_id,
                "currency": currency,
                "amount_paid": amount_minor,
                "billing_reason": "subscription_cycle",
            }
        },
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "StripeEvent" ("id","type","status","payloadJson",'
                '"receivedAt","processedAt") VALUES (%s,%s,\'processed\',%s::jsonb,'
                " NOW() - make_interval(days => %s), NOW())",
                (event_id, "invoice.paid", json.dumps(payload), days_ago),
            )
        conn.commit()


# --------------------------------------------------------------------------- #
# Gating + shape
# --------------------------------------------------------------------------- #


def test_executive_metrics_is_admin_gated(client, auth_headers):
    assert client.get("/admin/metrics/executive").status_code == 401
    assert client.get("/admin/metrics/executive", headers=auth_headers).status_code == 403


def test_executive_metrics_returns_every_block_the_dashboard_polls(client):
    headers, _ = _admin(client)
    body = _metrics(client, headers)
    for key in (
        "asOf",
        "windowDays",
        "currencies",
        "gstRegistered",
        "insufficientDataThreshold",
        "revenue",
        "signupsByDay",
        "runsByDay",
        "funnel",
        "costVsRevenue",
        "topReferrers",
        "failedRuns24h",
        "salesAi",
    ):
        assert key in body, f"missing block: {key}"
    assert body["currencies"] == {"revenue": "AUD", "llmCost": "USD"}
    assert body["gstRegistered"] is False  # the operator is not GST-registered
    assert body["windowDays"] == 30


def test_every_metric_block_carries_its_own_insufficient_data_flag(client):
    headers, _ = _admin(client)
    body = _metrics(client, headers)
    for block in ("revenue", "signupsByDay", "runsByDay", "funnel", "costVsRevenue",
                  "topReferrers", "failedRuns24h", "salesAi"):
        assert isinstance(body[block]["insufficientData"], bool), block
        assert isinstance(body[block]["sampleSize"], int), block


def test_failed_runs_24h_counts_failed_not_completed(client):
    headers, uid = _admin(client)
    before = _metrics(client, headers)["failedRuns24h"]
    _seed_run(uid, status="failed")
    _seed_run(uid, status="completed")
    after = _metrics(client, headers)["failedRuns24h"]
    assert after["failed"] == before["failed"] + 1
    assert after["total"] == before["total"] + 2
    assert after["windowHours"] == 24


def test_sales_ai_block_is_the_outreach_agent_not_human_resellers(client):
    headers, _ = _admin(client)
    block = _metrics(client, headers)["salesAi"]
    assert "enabled" in block
    assert "dryRun" in block
    assert block["cannotAttributeSignups"] is True
    assert "UTM" in block["cannotAttributeReason"]
    assert "emailsSent" in block
    assert "repliesObserved" in block


# --------------------------------------------------------------------------- #
# MRR / paid count / by-plan mix
# --------------------------------------------------------------------------- #


def test_revenue_block_carries_mrr_paid_count_and_plan_mix(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"mrr-{uuid.uuid4().hex[:8]}@example.com")
    before = _metrics(client, headers)["revenue"]
    _seed_paid_subscription(uid, f"cus_{uuid.uuid4().hex[:16]}", plan_id="pro")
    after = _metrics(client, headers)["revenue"]

    assert after["paidSubscribers"] == before["paidSubscribers"] + 1
    assert round(after["mrrAud"] - before["mrrAud"], 2) == 39.0  # Pro = A$39/month
    assert after["arrAud"] == round(after["mrrAud"] * 12, 2)
    pro = next(b for b in after["byPlan"] if b["planId"] == "pro")
    assert pro["count"] >= 1
    assert after["currency"] == "AUD"


def test_a_local_paid_row_with_no_stripe_subscription_is_not_revenue(client):
    """The owner's stale pro/active row must be visible, never counted."""
    headers, _ = _admin(client)
    _t, uid = _register(client, f"stale-{uuid.uuid4().hex[:8]}@example.com")
    before = _metrics(client, headers)["revenue"]
    _seed_unbacked_paid_subscription(uid)
    after = _metrics(client, headers)["revenue"]

    assert after["paidSubscribers"] == before["paidSubscribers"]
    assert after["mrrAud"] == before["mrrAud"]
    assert after["unbackedPaidRows"] == before["unbackedPaidRows"] + 1


# --------------------------------------------------------------------------- #
# Signups by day (30d) + run volume by day
# --------------------------------------------------------------------------- #


def test_signups_by_day_is_a_zero_filled_thirty_day_series(client):
    headers, _ = _admin(client)
    before = _metrics(client, headers)["signupsByDay"]
    assert len(before["series"]) == 30
    dates = [point["date"] for point in before["series"]]
    assert dates == sorted(dates)  # oldest first
    assert len(set(dates)) == 30  # every day present exactly once, zero-filled

    _register(client, f"today-{uuid.uuid4().hex[:8]}@example.com")
    after = _metrics(client, headers)["signupsByDay"]
    assert after["series"][-1]["count"] >= before["series"][-1]["count"] + 1
    assert after["total"] >= before["total"] + 1


def test_run_volume_by_day_reports_real_runs_and_real_llm_cost(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"runs-{uuid.uuid4().hex[:8]}@example.com")
    before = _metrics(client, headers)["runsByDay"]
    assert len(before["series"]) == 30

    _seed_run(uid, cost_usd=0.25)
    _seed_run(uid, cost_usd=0.25)
    after = _metrics(client, headers)["runsByDay"]

    assert after["totalRuns"] == before["totalRuns"] + 2
    assert round(after["totalCostUsd"] - before["totalCostUsd"], 4) == 0.5
    assert after["series"][-1]["runs"] >= 2
    assert after["currency"] == "USD"


def test_a_run_older_than_the_window_is_outside_the_series(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"old-{uuid.uuid4().hex[:8]}@example.com")
    before = _metrics(client, headers)["runsByDay"]
    _seed_run(uid, cost_usd=1.0, days_ago=45)
    after = _metrics(client, headers)["runsByDay"]
    assert after["totalRuns"] == before["totalRuns"]
    assert after["totalCostUsd"] == before["totalCostUsd"]


# --------------------------------------------------------------------------- #
# Funnel: signup -> first run -> first submission -> paid
# --------------------------------------------------------------------------- #


def test_funnel_stages_are_ordered_bounded_and_self_describing(client):
    """Stages are INDEPENDENT milestone counts over the same signup population.

    They are deliberately not forced into a nested, always-narrowing shape: a
    user really can pay without ever submitting, and hiding that would be a
    prettier chart drawn on a false claim. Every stage is bounded by the signup
    population, and each ships the definition it was computed from.
    """
    headers, _ = _admin(client)
    funnel = _metrics(client, headers)["funnel"]
    keys = [stage["key"] for stage in funnel["stages"]]
    assert keys == ["signup", "firstRun", "firstSubmission", "paid"]

    signups = funnel["stages"][0]["count"]
    for stage in funnel["stages"]:
        assert stage["count"] <= signups, stage
        assert stage["label"]
    for key in keys:
        assert funnel["definitions"][key]
    assert funnel["definitions"]["_shape"]


def test_one_user_walking_the_whole_funnel_moves_every_stage_by_one(client):
    headers, _ = _admin(client)

    def _counts() -> dict[str, int]:
        return {
            s["key"]: s["count"] for s in _metrics(client, headers)["funnel"]["stages"]
        }

    before = _counts()
    _t, uid = _register(client, f"funnel-{uuid.uuid4().hex[:8]}@example.com")
    after_signup = _counts()
    assert after_signup["signup"] == before["signup"] + 1
    assert after_signup["firstRun"] == before["firstRun"]

    _seed_run(uid)
    after_run = _counts()
    assert after_run["firstRun"] == before["firstRun"] + 1
    assert after_run["firstSubmission"] == before["firstSubmission"]

    _seed_submitted_application(uid)
    after_submit = _counts()
    assert after_submit["firstSubmission"] == before["firstSubmission"] + 1
    assert after_submit["paid"] == before["paid"]

    _seed_paid_subscription(uid, f"cus_{uuid.uuid4().hex[:16]}")
    after_paid = _counts()
    assert after_paid["paid"] == before["paid"] + 1


def test_a_second_run_by_the_same_user_does_not_double_count_the_funnel(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"twice-{uuid.uuid4().hex[:8]}@example.com")
    _seed_run(uid)
    first = _metrics(client, headers)["funnel"]["stages"][1]["count"]
    _seed_run(uid)
    second = _metrics(client, headers)["funnel"]["stages"][1]["count"]
    assert second == first  # stages count USERS, not events


def test_admin_accounts_are_excluded_from_the_funnel_and_counted_separately(client):
    headers, _ = _admin(client)
    before = _metrics(client, headers)
    _t, uid = _register(client, f"newadmin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    after = _metrics(client, headers)

    before_signup = before["funnel"]["stages"][0]["count"]
    after_signup = after["funnel"]["stages"][0]["count"]
    assert after_signup == before_signup
    assert after["excluded"]["adminAccounts"] == before["excluded"]["adminAccounts"] + 1


# --------------------------------------------------------------------------- #
# LLM cost (USD) vs revenue (AUD) — reported side by side, NEVER combined
# --------------------------------------------------------------------------- #


def test_cost_vs_revenue_reports_both_currencies_without_inventing_an_fx_rate(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"cvr-{uuid.uuid4().hex[:8]}@example.com")
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)

    before = _metrics(client, headers)["costVsRevenue"]
    _seed_run(uid, cost_usd=2.0)
    _record_invoice_paid(customer, 3900)
    after = _metrics(client, headers)["costVsRevenue"]

    assert round(after["llmCostUsd"] - before["llmCostUsd"], 4) == 2.0
    assert round(after["revenueAud"] - before["revenueAud"], 2) == 39.0
    # No FX rate is applied and no cross-currency figure is offered.
    assert after["fxRateApplied"] is None
    assert "marginAud" not in after and "marginUsd" not in after
    assert "netAud" not in after and "profit" not in after
    assert after["note"]


def test_revenue_in_window_comes_from_real_payment_events_only(client):
    """A subscription with no ``invoice.paid`` behind it contributes A$0 to the
    30-day revenue figure — a plan price is a claim, a paid invoice is money."""
    headers, _ = _admin(client)
    _t, uid = _register(client, f"noinv-{uuid.uuid4().hex[:8]}@example.com")
    before = _metrics(client, headers)["costVsRevenue"]["revenueAud"]
    _seed_paid_subscription(uid, f"cus_{uuid.uuid4().hex[:16]}")
    after = _metrics(client, headers)["costVsRevenue"]["revenueAud"]
    assert after == before


def test_a_payment_older_than_the_window_is_not_counted_as_window_revenue(client):
    headers, _ = _admin(client)
    _t, uid = _register(client, f"oldpay-{uuid.uuid4().hex[:8]}@example.com")
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    before = _metrics(client, headers)["costVsRevenue"]["revenueAud"]
    _record_invoice_paid(customer, 9900, days_ago=60)
    after = _metrics(client, headers)["costVsRevenue"]["revenueAud"]
    assert after == before


# --------------------------------------------------------------------------- #
# Top referrers
# --------------------------------------------------------------------------- #


def test_top_referrers_reflects_real_attributed_signups(client):
    headers, _ = _admin(client)
    code = f"REF{uuid.uuid4().hex[:8].upper()}"
    created = client.post(
        "/admin/sales-agents",
        json={"name": "Top Rep", "referralCode": code, "commissionPct": 10},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]

    assert not [
        a for a in _metrics(client, headers)["topReferrers"]["agents"]
        if a["id"] == agent_id
    ]

    _register(client, f"tr1-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _t, uid = _register(client, f"tr2-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _seed_paid_subscription(uid, f"cus_{uuid.uuid4().hex[:16]}")

    row = next(
        a for a in _metrics(client, headers)["topReferrers"]["agents"] if a["id"] == agent_id
    )
    assert row["attributedSignups"] == 2
    assert row["convertedPaid"] == 1
    assert row["referralCode"] == code


# --------------------------------------------------------------------------- #
# Honest small-N reporting
# --------------------------------------------------------------------------- #


def test_insufficient_data_is_true_while_the_sample_is_below_the_threshold(client):
    headers, _ = _admin(client)
    body = _metrics(client, headers)
    threshold = body["insufficientDataThreshold"]
    assert threshold > 1
    for block in ("revenue", "funnel", "costVsRevenue", "topReferrers"):
        sample = body[block]["sampleSize"]
        assert body[block]["insufficientData"] is (sample < threshold), block


def test_metrics_endpoint_mutates_nothing(client):
    headers, _ = _admin(client)

    def _snapshot() -> tuple[int, int, int]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT count(*) FROM "AdminAuditLog"')
                audits = int(cur.fetchone()[0])
                cur.execute('SELECT count(*) FROM "Subscription"')
                subs = int(cur.fetchone()[0])
                cur.execute('SELECT count(*) FROM "User"')
                users = int(cur.fetchone()[0])
        return audits, subs, users

    before = _snapshot()
    _metrics(client, headers)
    assert _snapshot() == before
