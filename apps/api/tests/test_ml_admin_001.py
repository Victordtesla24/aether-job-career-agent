"""ML-admin-001 (HIGH) — GET /api/admin/users?plan=<any> unconditionally 500s.

RCA (verified by reading apps/api/app/repositories/admin.py): ``list_users``
builds a shared ``where_sql`` fragment that, when a ``plan`` filter is given,
references the joined alias ``s."planId"`` (apps/api/app/repositories/admin.py
around line 243: ``where.append('s."planId" = %s')``). The row-fetching query
(~line 250-261) JOINs ``"Subscription" s`` so that alias resolves there, but
the COUNT query built at line 264::

    cur.execute(f'SELECT count(*) FROM "User" u{where_sql}', params)

has a FROM clause of only ``"User" u`` — no ``JOIN "Subscription" s`` — so
whenever ``where_sql`` contains the plan predicate, referencing alias ``s``
in the COUNT's WHERE clause is a missing-FROM-clause-entry error at the
database (psycopg2 raises ``UndefinedTable``/"missing FROM-clause entry for
table \"s\""), which FastAPI surfaces as a 500 to the caller. The `q` and
`suspended` filters don't touch `s`, so only `plan=` triggers this.

This module intentionally does NOT touch existing GAP-P6-ADMIN tests in
tests/test_gap_p6_admin.py (append-only addition per the assignment brief).
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection
from app.repositories.billing import ensure_user_billing

# --------------------------------------------------------------------------- #
# Helpers (mirrors tests/test_gap_p6_admin.py conventions)
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["userId"]


def _promote(user_id: str) -> None:
    from app.repositories.admin import _ensure_admin_schema

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin(client) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"admin-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _set_plan(user_id: str, plan: str) -> None:
    """Give a user a concrete Subscription.planId (ensure_user_billing seeds
    'free'; this upgrades it in place so filter tests have a real 'pro' row
    to match against)."""
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s WHERE "userId"=%s',
                (plan, user_id),
            )
        conn.commit()


# --------------------------------------------------------------------------- #
# ML-admin-001 — plan filter must not 500
# --------------------------------------------------------------------------- #


def test_admin_users_plan_free_filter_returns_200_not_500(client):
    """Fail-before: GET /admin/users?plan=free currently 500s (missing
    Subscription JOIN in the COUNT query). Expected: 200 with a count that
    matches the filtered rows, and only free-plan users returned."""
    headers, admin_id = _admin(client)
    _set_plan(admin_id, "free")

    _, free_uid = _register(client, f"free-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(free_uid, "free")

    _, pro_uid = _register(client, f"pro-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(pro_uid, "pro")

    r = client.get("/admin/users", params={"plan": "free"}, headers=headers)
    assert r.status_code == 200, (
        f"expected 200, got {r.status_code}: {r.text} "
        "(ML-admin-001: COUNT query at admin.py:264 has no Subscription JOIN "
        "but references s.\"planId\" through where_sql when plan= is set)"
    )
    body = r.json()
    assert "total" in body and "users" in body

    rows = {u["id"]: u for u in body["users"]}
    assert admin_id in rows
    assert free_uid in rows
    assert pro_uid not in rows, "pro-plan user leaked into plan=free filter"

    # Every row actually has plan == 'free' (filter correctness).
    for u in body["users"]:
        assert u["plan"] == "free", u

    # The reported total must be consistent with the filtered rows returned
    # (both users created here fit well under the default limit=100).
    assert body["total"] == len(body["users"]) == 2, body


def test_admin_users_plan_pro_filter_returns_200_not_500(client):
    """Same defect, second plan value — proves it isn't free-plan-specific."""
    headers, admin_id = _admin(client)
    _set_plan(admin_id, "free")

    _, pro_uid_a = _register(client, f"proa-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(pro_uid_a, "pro")
    _, pro_uid_b = _register(client, f"prob-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(pro_uid_b, "pro")
    _, free_uid = _register(client, f"freeb-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(free_uid, "free")

    r = client.get("/admin/users", params={"plan": "pro"}, headers=headers)
    assert r.status_code == 200, (
        f"expected 200, got {r.status_code}: {r.text} (ML-admin-001)"
    )
    body = r.json()
    rows = {u["id"]: u for u in body["users"]}
    assert pro_uid_a in rows and pro_uid_b in rows
    assert free_uid not in rows
    assert admin_id not in rows
    for u in body["users"]:
        assert u["plan"] == "pro", u
    assert body["total"] == len(body["users"]) == 2, body


def test_admin_users_unfiltered_call_still_works(client):
    """Guard: the no-filter path (q=None, plan=None, suspended=None) must
    keep working exactly as before — this defect must not regress it."""
    headers, admin_id = _admin(client)
    _set_plan(admin_id, "free")
    _, uid = _register(client, f"guard-ml001-{uuid.uuid4().hex[:8]}@example.com")
    _set_plan(uid, "power")

    r = client.get("/admin/users", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {u["id"] for u in body["users"]}
    assert {admin_id, uid} <= ids
    assert body["total"] == len(body["users"]) == 2, body


def test_admin_users_query_and_plan_filters_combine_without_500(client):
    """Combining `q` (which does not touch alias s) with `plan` (which does)
    must not 500 either — exercises the same COUNT-query code path with a
    non-empty where_sql built from two predicates."""
    headers, admin_id = _admin(client)
    _set_plan(admin_id, "free")

    email = f"combo-ml001-{uuid.uuid4().hex[:8]}@example.com"
    _, uid = _register(client, email)
    _set_plan(uid, "starter")

    r = client.get(
        "/admin/users", params={"q": "combo-ml001", "plan": "starter"}, headers=headers
    )
    assert r.status_code == 200, (
        f"expected 200, got {r.status_code}: {r.text} (ML-admin-001)"
    )
    body = r.json()
    ids = {u["id"] for u in body["users"]}
    assert ids == {uid}
    assert body["total"] == 1, body
