"""ADMIN-2.0 BE-2 — sales agents: CRUD, signup attribution, commission report.

Contract under test (every ``/admin/*`` route is ``AdminUser``-gated and every
mutation appends an ``AdminAuditLog`` row on the SAME cursor as the mutation):

* ``POST   /admin/sales-agents``             — create with a unique referral code
* ``GET    /admin/sales-agents``             — list + attributed signup/conversion counts
* ``PATCH  /admin/sales-agents/{id}``        — update (status change = deactivate)
* ``GET    /admin/sales-agents/{id}/report`` — commission report, REPORT-ONLY
* ``POST   /auth/register`` with ``ref``     — attribution, zero behaviour change when absent

MONEY SAFETY: nothing in this file reaches Stripe. The "real payments" the
commission report reads are the locally-recorded, signature-verified
``StripeEvent`` webhook rows the billing spine already persists — the tests
insert those rows directly, so no charge, refund or payout can occur.

SHARED-SCHEMA DISCIPLINE: ``aether_test`` is shared with concurrent sessions and
``SalesAgent``/``Subscription``/``StripeEvent`` are NOT truncated between tests.
Every assertion here is therefore scoped to a uuid-unique agent, referral code
and Stripe customer id — never to a global count.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db import get_connection
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


def _code() -> str:
    return f"REF{uuid.uuid4().hex[:8].upper()}"


def _create_agent(client, headers, **overrides) -> dict:
    body = {
        "name": overrides.pop("name", f"Rep {uuid.uuid4().hex[:6]}"),
        "referralCode": overrides.pop("referralCode", _code()),
        "commissionPct": overrides.pop("commissionPct", 10),
    }
    body.update(overrides)
    r = client.post("/admin/sales-agents", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _audit_rows(target_id: str) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action","detailJson","actorUserId" FROM "AdminAuditLog"'
                ' WHERE "targetId"=%s ORDER BY "createdAt" DESC',
                (target_id,),
            )
            return [
                {"action": r[0], "detail": r[1], "actor": r[2]} for r in cur.fetchall()
            ]


def _referred_by(user_id: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "referredBy" FROM "User" WHERE "id"=%s', (user_id,))
            row = cur.fetchone()
    assert row is not None, "user row missing"
    return row[0]


def _agent_row_count(agent_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "SalesAgent" WHERE "id"=%s', (agent_id,))
            return int(cur.fetchone()[0])


def _seed_paid_subscription(user_id: str, customer_id: str, *, plan_id: str = "pro") -> None:
    """Give ``user_id`` a Stripe-backed active subscription (local mirror only)."""
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
                (
                    user_id,
                    plan_id,
                    "active",
                    "month",
                    customer_id,
                    f"sub_{uuid.uuid4().hex[:16]}",
                ),
            )
        conn.commit()


def _record_invoice_paid(customer_id: str, amount_minor: int, currency: str = "aud") -> str:
    """Insert the SAME row the signed webhook handler persists for a real payment."""
    _ensure_billing_tables()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex[:16]}",
                "object": "invoice",
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
                'INSERT INTO "StripeEvent" ("id","type","status","payloadJson","processedAt")'
                " VALUES (%s,%s,'processed',%s::jsonb,now())",
                (event_id, "invoice.paid", json.dumps(payload)),
            )
        conn.commit()
    return event_id


def _record_charge_refunded(
    customer_id: str, amount_refunded_minor: int, *, charge_id: str, currency: str = "aud"
) -> str:
    _ensure_billing_tables()
    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": charge_id,
                "object": "charge",
                "customer": customer_id,
                "currency": currency,
                "amount": amount_refunded_minor,
                "amount_refunded": amount_refunded_minor,
                "refunded": True,
            }
        },
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "StripeEvent" ("id","type","status","payloadJson","processedAt")'
                " VALUES (%s,%s,'processed',%s::jsonb,now())",
                (event_id, "charge.refunded", json.dumps(payload)),
            )
        conn.commit()
    return event_id


# --------------------------------------------------------------------------- #
# Schema — additive, idempotent, no FK to User (shared-test-DB TRUNCATE safety)
# --------------------------------------------------------------------------- #


def test_sales_agent_schema_is_idempotent_and_additive(client):
    from app.repositories import sales_agents

    sales_agents.ensure_sales_agent_schema()
    sales_agents._sales_agent_schema_ready = False  # force the DDL path again
    sales_agents.ensure_sales_agent_schema()  # must not raise on a second run

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_name='SalesAgent'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            columns = {r[0] for r in cur.fetchall()}
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_name='User' AND column_name='referredBy'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            has_referred_by = int(cur.fetchone()[0])

    assert {"id", "name", "referralCode", "commissionPct", "status"} <= columns
    assert has_referred_by == 1


def test_referred_by_is_nullable_so_every_pre_existing_user_reads_correctly(client):
    """The new column must not break a plain registration (no default, no NOT NULL)."""
    _token, uid = _register(client, f"plain-{uuid.uuid4().hex[:8]}@example.com")
    assert _referred_by(uid) is None


# --------------------------------------------------------------------------- #
# Gating — 401 anonymous, 403 authenticated non-admin
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/admin/sales-agents"),
        ("GET", "/admin/sales-agents"),
        ("PATCH", "/admin/sales-agents/some-id"),
        ("GET", "/admin/sales-agents/some-id/report"),
    ],
)
def test_sales_agent_routes_are_admin_gated(client, auth_headers, method, path):
    body = {"name": "x"}
    assert client.request(method, path, json=body).status_code == 401
    assert client.request(method, path, json=body, headers=auth_headers).status_code == 403


# --------------------------------------------------------------------------- #
# CREATE
# --------------------------------------------------------------------------- #


def test_create_sales_agent_normalises_the_code_and_audits(client):
    headers, admin_id = _admin(client)
    raw = f"  ref{uuid.uuid4().hex[:8]}  "
    r = client.post(
        "/admin/sales-agents",
        json={
            "name": "Jane Rep",
            "email": "jane@example.com",
            "referralCode": raw,
            "commissionPct": 12.5,
            "notes": "AU channel",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["referralCode"] == raw.strip().upper()
    assert agent["name"] == "Jane Rep"
    assert agent["commissionPct"] == 12.5
    assert agent["status"] == "active"
    assert agent["createdBy"] == admin_id

    audits = [a for a in _audit_rows(agent["id"]) if a["action"] == "create_sales_agent"]
    assert len(audits) == 1
    assert audits[0]["actor"] == admin_id
    assert audits[0]["detail"]["referralCode"] == agent["referralCode"]


def test_create_sales_agent_generates_a_code_when_none_is_supplied(client):
    headers, _ = _admin(client)
    r = client.post(
        "/admin/sales-agents", json={"name": "No Code Rep"}, headers=headers
    )
    assert r.status_code == 201, r.text
    code = r.json()["referralCode"]
    assert code and code == code.upper() and " " not in code


def test_create_sales_agent_rejects_a_duplicate_code_with_409(client):
    headers, _ = _admin(client)
    code = _code()
    _create_agent(client, headers, referralCode=code)
    r = client.post(
        "/admin/sales-agents",
        json={"name": "Copycat", "referralCode": code.lower()},
        headers=headers,
    )
    assert r.status_code == 409, r.text

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "SalesAgent" WHERE "referralCode"=%s', (code,)
            )
            assert int(cur.fetchone()[0]) == 1


@pytest.mark.parametrize("bad", ["", "  ", "a", "has space", "sym$bol", "x" * 40])
def test_create_sales_agent_rejects_an_invalid_code_with_422(client, bad):
    headers, _ = _admin(client)
    r = client.post(
        "/admin/sales-agents",
        json={"name": "Bad Code", "referralCode": bad},
        headers=headers,
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", [-1, 100.1, "ten", None])
def test_create_sales_agent_rejects_an_out_of_range_commission(client, bad):
    headers, _ = _admin(client)
    r = client.post(
        "/admin/sales-agents",
        json={"name": "Bad Pct", "referralCode": _code(), "commissionPct": bad},
        headers=headers,
    )
    assert r.status_code == 422, r.text


def test_create_sales_agent_requires_a_name(client):
    headers, _ = _admin(client)
    r = client.post(
        "/admin/sales-agents", json={"referralCode": _code()}, headers=headers
    )
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# LIST — attributed signup / conversion counts
# --------------------------------------------------------------------------- #


def test_list_sales_agents_reports_real_attributed_counts(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)

    # Two attributed signups; ONE of them converts to a Stripe-backed paid plan.
    _t1, u1 = _register(client, f"ref1-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _t2, _u2 = _register(client, f"ref2-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _seed_paid_subscription(u1, f"cus_{uuid.uuid4().hex[:16]}")

    r = client.get("/admin/sales-agents", headers=headers)
    assert r.status_code == 200, r.text
    listing = r.json()
    row = next(a for a in listing["agents"] if a["id"] == agent["id"])
    assert row["attributedSignups"] == 2
    assert row["convertedPaid"] == 1


def test_list_sales_agents_can_filter_by_status(client):
    headers, _ = _admin(client)
    live = _create_agent(client, headers)
    dead = _create_agent(client, headers)
    assert (
        client.patch(
            f"/admin/sales-agents/{dead['id']}", json={"status": "inactive"}, headers=headers
        ).status_code
        == 200
    )

    active_ids = {
        a["id"] for a in client.get("/admin/sales-agents?status=active", headers=headers).json()["agents"]
    }
    inactive_ids = {
        a["id"]
        for a in client.get("/admin/sales-agents?status=inactive", headers=headers).json()["agents"]
    }
    assert live["id"] in active_ids and dead["id"] not in active_ids
    assert dead["id"] in inactive_ids and live["id"] not in inactive_ids


# --------------------------------------------------------------------------- #
# UPDATE — deactivate, never hard-delete
# --------------------------------------------------------------------------- #


def test_deactivating_an_agent_keeps_the_row_and_audits(client):
    headers, admin_id = _admin(client)
    agent = _create_agent(client, headers)

    r = client.patch(
        f"/admin/sales-agents/{agent['id']}", json={"status": "inactive"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "inactive"
    assert _agent_row_count(agent["id"]) == 1  # deactivated, NOT deleted

    audits = [a for a in _audit_rows(agent["id"]) if a["action"] == "update_sales_agent"]
    assert len(audits) == 1
    assert audits[0]["actor"] == admin_id
    assert audits[0]["detail"]["changed"]["status"] == "inactive"


def test_there_is_no_hard_delete_route_for_a_sales_agent(client):
    headers, _ = _admin(client)
    agent = _create_agent(client, headers)
    r = client.delete(f"/admin/sales-agents/{agent['id']}", headers=headers)
    assert r.status_code == 405, r.text
    assert _agent_row_count(agent["id"]) == 1


def test_update_sales_agent_rejects_an_unknown_status(client):
    headers, _ = _admin(client)
    agent = _create_agent(client, headers)
    r = client.patch(
        f"/admin/sales-agents/{agent['id']}", json={"status": "deleted"}, headers=headers
    )
    assert r.status_code == 422, r.text


def test_update_sales_agent_refuses_to_rewrite_the_referral_code(client):
    """Codes are already in the wild on shared links — rewriting one silently
    breaks every link an agent has distributed."""
    headers, _ = _admin(client)
    agent = _create_agent(client, headers)
    r = client.patch(
        f"/admin/sales-agents/{agent['id']}",
        json={"referralCode": _code()},
        headers=headers,
    )
    assert r.status_code == 422, r.text


def test_update_unknown_sales_agent_is_404(client):
    headers, _ = _admin(client)
    r = client.patch(
        f"/admin/sales-agents/{uuid.uuid4().hex}", json={"status": "inactive"}, headers=headers
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# ATTRIBUTION — the signup hook
# --------------------------------------------------------------------------- #


def test_signup_with_a_matching_ref_code_is_attributed(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)
    _t, uid = _register(client, f"att-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    assert _referred_by(uid) == agent["id"]


def test_ref_code_matching_is_case_and_whitespace_insensitive(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)
    _t, uid = _register(
        client, f"att-{uuid.uuid4().hex[:8]}@example.com", ref=f"  {code.lower()} "
    )
    assert _referred_by(uid) == agent["id"]


def test_signup_with_an_unknown_ref_code_still_succeeds_unattributed(client):
    _t, uid = _register(
        client, f"unk-{uuid.uuid4().hex[:8]}@example.com", ref=f"NOSUCH{uuid.uuid4().hex[:6].upper()}"
    )
    assert _referred_by(uid) is None


def test_signup_with_an_inactive_agents_code_is_not_attributed(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)
    client.patch(
        f"/admin/sales-agents/{agent['id']}", json={"status": "inactive"}, headers=headers
    )
    _t, uid = _register(client, f"inact-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    assert _referred_by(uid) is None


def test_signup_without_a_ref_is_unchanged(client):
    """Zero behaviour change when the parameter is absent."""
    email = f"noref-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "Passw0rd1"})
    assert r.status_code == 201, r.text
    assert _referred_by(r.json()["id"]) is None


def test_ref_can_also_arrive_as_a_query_parameter(client):
    """``/signup?ref=CODE`` forwarded as a query string must work too."""
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)
    email = f"q-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        f"/auth/register?ref={code}", json={"email": email, "password": "Passw0rd1"}
    )
    assert r.status_code == 201, r.text
    assert _referred_by(r.json()["id"]) == agent["id"]


# --------------------------------------------------------------------------- #
# COMMISSION REPORT — real payments only, report-only
# --------------------------------------------------------------------------- #


def test_commission_report_uses_real_payment_records(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=10)

    _t, uid = _register(client, f"pay-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 3900)  # A$39.00
    _record_invoice_paid(customer, 3900)  # a second billing cycle

    r = client.get(f"/admin/sales-agents/{agent['id']}/report", headers=headers)
    assert r.status_code == 200, r.text
    report = r.json()

    assert report["currency"] == "AUD"
    assert report["commissionPct"] == 10
    assert report["totals"]["grossPaidAud"] == 78.0
    assert report["totals"]["refundedAud"] == 0.0
    assert report["totals"]["netPaidAud"] == 78.0
    assert report["totals"]["commissionAud"] == 7.8
    assert report["totals"]["paymentCount"] == 2
    assert report["totals"]["attributedUsers"] == 1
    assert report["totals"]["payingUsers"] == 1

    user_row = next(u for u in report["attributedUsers"] if u["userId"] == uid)
    assert user_row["netPaidAud"] == 78.0
    assert user_row["converted"] is True


def test_commission_report_nets_off_real_refunds(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=20)

    _t, uid = _register(client, f"ref-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 5000)  # A$50.00
    _record_charge_refunded(customer, 1000, charge_id=f"ch_{uuid.uuid4().hex[:16]}")

    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["totals"]["grossPaidAud"] == 50.0
    assert report["totals"]["refundedAud"] == 10.0
    assert report["totals"]["netPaidAud"] == 40.0
    assert report["totals"]["commissionAud"] == 8.0


def test_commission_report_does_not_double_count_a_cumulative_refund(client):
    """Stripe re-sends ``charge.refunded`` with a CUMULATIVE ``amount_refunded``
    for each partial refund of the same charge — summing them would invent money
    that was never returned."""
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=50)

    _t, uid = _register(client, f"cum-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 10000)
    charge = f"ch_{uuid.uuid4().hex[:16]}"
    _record_charge_refunded(customer, 2000, charge_id=charge)
    _record_charge_refunded(customer, 3000, charge_id=charge)  # cumulative, not +3000

    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["totals"]["refundedAud"] == 30.0
    assert report["totals"]["netPaidAud"] == 70.0


def test_commission_report_never_folds_a_foreign_currency_into_the_aud_total(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=10)

    _t, uid = _register(client, f"fx-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 1000, currency="aud")
    _record_invoice_paid(customer, 9900, currency="usd")

    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["totals"]["grossPaidAud"] == 10.0  # the USD invoice is NOT converted
    assert report["totals"]["commissionAud"] == 1.0
    assert report["otherCurrencies"]["usd"]["grossMinorUnits"] == 9900


def test_commission_report_is_report_only_and_mutates_nothing(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=10)
    _t, uid = _register(client, f"ro-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 3900)

    def _snapshot() -> tuple:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "planId","status","stripeSubscriptionId" FROM "Subscription"'
                    ' WHERE "userId"=%s',
                    (uid,),
                )
                sub = cur.fetchone()
                cur.execute('SELECT count(*) FROM "AdminAuditLog"')
                audits = int(cur.fetchone()[0])
                cur.execute('SELECT count(*) FROM "StripeEvent"')
                events = int(cur.fetchone()[0])
        return sub, audits, events

    before = _snapshot()
    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    after = _snapshot()

    assert report["reportOnly"] is True
    assert report["payoutPerformed"] is False
    assert before == after


def test_commission_report_for_an_unknown_agent_is_404(client):
    headers, _ = _admin(client)
    r = client.get(f"/admin/sales-agents/{uuid.uuid4().hex}/report", headers=headers)
    assert r.status_code == 404, r.text


def test_commission_report_on_a_brand_new_agent_is_an_honest_zero(client):
    headers, _ = _admin(client)
    agent = _create_agent(client, headers, commissionPct=15)
    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["attributedUsers"] == []
    assert report["totals"]["grossPaidAud"] == 0.0
    assert report["totals"]["commissionAud"] == 0.0
    assert report["insufficientData"] is True


def test_commission_report_never_credits_one_payment_to_two_accounts(client):
    """Two local rows can point at the same Stripe customer. Crediting that
    customer's money to both would inflate the commission the operator owes."""
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=10)

    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _t1, first = _register(client, f"dup1-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _t2, second = _register(client, f"dup2-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    _seed_paid_subscription(first, customer)
    _seed_paid_subscription(second, customer)
    _record_invoice_paid(customer, 4000)

    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["totals"]["grossPaidAud"] == 40.0  # counted once, not twice
    assert report["totals"]["commissionAud"] == 4.0
    assert report["sharedStripeCustomerAccounts"] == 1
    later = next(u for u in report["attributedUsers"] if u["userId"] == second)
    assert later["grossPaidAud"] == 0.0
    assert later["sharesStripeCustomerWith"] == first


def test_commission_report_discloses_a_payment_event_it_could_not_read(client):
    """A malformed payload is COUNTED, never silently dropped from the total."""
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code, commissionPct=10)
    _t, uid = _register(client, f"bad-{uuid.uuid4().hex[:8]}@example.com", ref=code)
    customer = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid, customer)
    _record_invoice_paid(customer, 2500)

    event_id = f"evt_{uuid.uuid4().hex}"
    payload = {
        "id": event_id,
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": f"in_{uuid.uuid4().hex[:16]}",
                "customer": customer,
                "currency": "aud",
                "amount_paid": "not-a-number",
            }
        },
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "StripeEvent" ("id","type","status","payloadJson")'
                " VALUES (%s,'invoice.paid','processed',%s::jsonb)",
                (event_id, json.dumps(payload)),
            )
        conn.commit()

    report = client.get(
        f"/admin/sales-agents/{agent['id']}/report", headers=headers
    ).json()
    assert report["totals"]["grossPaidAud"] == 25.0  # the readable payment only
    assert report["unparsablePaymentEvents"] >= 1


def test_patch_response_carries_the_same_count_fields_as_the_list(client):
    headers, _ = _admin(client)
    code = _code()
    agent = _create_agent(client, headers, referralCode=code)
    _register(client, f"pc-{uuid.uuid4().hex[:8]}@example.com", ref=code)

    patched = client.patch(
        f"/admin/sales-agents/{agent['id']}", json={"notes": "renewed"}, headers=headers
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["attributedSignups"] == 1
    assert body["convertedPaid"] == 0
    listed = next(
        a
        for a in client.get("/admin/sales-agents", headers=headers).json()["agents"]
        if a["id"] == agent["id"]
    )
    assert set(body) == set(listed)


def test_update_agent_repository_refuses_a_column_outside_the_whitelist():
    """Column names are interpolated into the UPDATE, so the whitelist is
    enforced at the point of interpolation, not only at the router."""
    from app.repositories import sales_agents

    class _ExplodingCursor:
        def execute(self, *_args, **_kwargs):  # pragma: no cover - must not run
            raise AssertionError("SQL must never be built for a rejected column")

    with pytest.raises(ValueError):
        sales_agents.update_agent(
            _ExplodingCursor(), "any-id", {'status"; DROP TABLE "SalesAgent"; --': "x"}
        )


def test_commission_report_excludes_another_agents_users(client):
    headers, _ = _admin(client)
    code_a, code_b = _code(), _code()
    agent_a = _create_agent(client, headers, referralCode=code_a, commissionPct=10)
    _create_agent(client, headers, referralCode=code_b, commissionPct=10)

    _t, uid_b = _register(client, f"b-{uuid.uuid4().hex[:8]}@example.com", ref=code_b)
    customer_b = f"cus_{uuid.uuid4().hex[:16]}"
    _seed_paid_subscription(uid_b, customer_b)
    _record_invoice_paid(customer_b, 9900)

    report_a = client.get(
        f"/admin/sales-agents/{agent_a['id']}/report", headers=headers
    ).json()
    assert report_a["totals"]["attributedUsers"] == 0
    assert report_a["totals"]["grossPaidAud"] == 0.0
