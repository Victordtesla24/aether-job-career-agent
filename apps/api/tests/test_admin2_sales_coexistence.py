"""ADMIN-2.0 × native Sales AI Agent — do the two sales features coexist safely?

WHY THIS FILE EXISTS. Two unrelated "sales agent" features were built the same
week by two sessions that never saw each other's tree:

* ``origin/main@382f0c2`` — the NATIVE Sales AI Agent: in-app campaigns, leads,
  an outreach log, a 30-minute timer, and REAL Gmail sends whenever it is not in
  shadow/dry-run mode (``app/agents/sales_agent.py``, ``repositories/sales.py``,
  routes under ``/admin/sales-agent``).
* ``feat/admin-2-0`` — the RESELLER surface: human sales agents, referral codes,
  commission reports (``repositories/sales_agents.py``, routes under
  ``/admin/sales-agents``). It sends no mail and moves no money.

Round-1 review made the merge of those two branches a blocking condition and
noted that NO evidence existed showing they coexist safely — every gate on
either side had been captured against a tree that did not contain the other
feature. This file is that missing evidence, and it is deliberately behavioural
rather than structural: the disjointness of their advisory-lock ids, table
names and route prefixes is easy to eyeball and is asserted at the bottom, but
the defect that actually mattered was invisible to inspection of either branch
alone.

THE COLLISION THIS FILE PINS. ADMIN-2.0 introduced ``User.deletedAt`` — an
admin SOFT delete (hard delete is impossible; eight child tables cascade off
``User.id``). The row therefore SURVIVES the delete, which is exactly what the
native Sales AI Agent, written before that column existed, walks over:

  1. ``SalesAgent._lifecycle_candidates`` selects free-plan accounts to email
     and filtered only on plan and ``email IS NOT NULL``. In LIVE mode an
     account an admin had just deleted would still be sent a real marketing
     email. That is the harm: not a wrong number on a screen, an outbound
     message to someone the operator believes is gone.
  2. ``SalesRepository.overview`` reported ``signups`` as ``COUNT(*)`` over
     ``User``, so deleted accounts kept inflating the growth figure the admin
     console shows — while ADMIN-2.0's own ``/admin/metrics/executive`` excludes
     them (``admin_metrics.py:90,179``). Two admin screens, two different
     answers about the same population, one of them counting the dead.

Neither is a defect in either feature as written; both are created by the two
landing together, which is why they are fixed and pinned here rather than in
either feature's own suite.

SCOPE — WHAT IS DELIBERATELY *NOT* FIXED HERE. ``User.suspended`` has the same
shape of problem (a suspended account is still a lifecycle-email candidate) and
is NOT addressed by this file. That gap is genuinely pre-existing on
``origin/main``: ``suspended`` was added by ADMIN-FULL and was already live when
``382f0c2`` shipped the agent without filtering it, so it is neither caused nor
worsened by ADMIN-2.0. Widening this branch's diff into another feature's
semantics to fix it would be unsanctioned scope; it is reported to the
orchestrator as a separate finding instead. ``deletedAt`` is fixed here
precisely because ADMIN-2.0 is what created it.

SHARED-SCHEMA DISCIPLINE. ``aether_test`` is shared with concurrent sessions and
``Subscription`` is never truncated, so every assertion below is a DELTA around
a before/after snapshot or is scoped to a uuid-unique account — never a global
equality.
"""
from __future__ import annotations

import uuid

from app.agents.sales_agent import SalesAgent
from app.db import get_connection
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import ensure_user_billing
from app.repositories.sales import SalesRepository, _ensure_sales_tables

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
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


def _dormant_free_account(client) -> tuple[str, str]:
    """A free-plan account that IS a genuine ``reengagement`` candidate.

    The native agent's own rule: account older than 14 days with no agent run in
    the last 14 days. Registration stamps ``createdAt`` at now, so it is
    backdated here — this is the ONE thing standing between the account and a
    real outbound email, and the test would prove nothing if the account were
    not a candidate to begin with.
    """
    email = f"dormant-{uuid.uuid4().hex[:8]}@example.com"
    _, uid = _register(client, email)
    ensure_user_billing(uid)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "createdAt" = NOW() - interval \'60 days\''
                ' WHERE "id" = %s',
                (uid,),
            )
        conn.commit()
    return uid, email


def _soft_delete(client, admin_headers: dict[str, str], user_id: str, email: str) -> None:
    r = client.request(
        "DELETE",
        f"/admin/users/{user_id}",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "soft"


def _candidate_emails() -> set[str]:
    return {
        (c.get("email") or "").lower()
        for c in SalesAgent(repo=SalesRepository())._lifecycle_candidates()
    }


# --------------------------------------------------------------------------- #
# 1. The native agent must not email an account ADMIN-2.0 deleted
# --------------------------------------------------------------------------- #


def test_a_dormant_free_account_is_a_lifecycle_candidate_before_it_is_deleted(client):
    """Control. Without this the deletion assertion below could pass vacuously."""
    _, email = _dormant_free_account(client)
    assert email.lower() in _candidate_emails()


def test_a_soft_deleted_account_is_not_a_lifecycle_email_candidate(client):
    admin_headers, _ = _admin(client)
    uid, email = _dormant_free_account(client)
    assert email.lower() in _candidate_emails(), "precondition: was a candidate"

    _soft_delete(client, admin_headers, uid, email)

    assert email.lower() not in _candidate_emails(), (
        "an account the admin deleted is still queued for a real marketing email"
    )


def test_a_suspended_account_is_not_a_lifecycle_email_candidate(client):
    admin_headers, _ = _admin(client)
    uid, email = _dormant_free_account(client)
    assert email.lower() in _candidate_emails(), "precondition: was a candidate"

    suspended = client.post(f"/admin/users/{uid}/suspend", headers=admin_headers)
    assert suspended.status_code == 200, suspended.text

    assert email.lower() not in _candidate_emails(), (
        "a suspended account is still queued for a real marketing email"
    )


def test_the_soft_delete_does_not_shrink_the_candidate_set_for_anyone_else(client):
    """The filter must remove exactly the deleted account, not the population."""
    admin_headers, _ = _admin(client)
    _, keep_email = _dormant_free_account(client)
    drop_uid, drop_email = _dormant_free_account(client)
    before = _candidate_emails()
    assert {keep_email.lower(), drop_email.lower()} <= before

    _soft_delete(client, admin_headers, drop_uid, drop_email)

    after = _candidate_emails()
    assert keep_email.lower() in after
    assert drop_email.lower() not in after
    assert before - after == {drop_email.lower()}


def test_a_fully_restored_account_is_reachable_again(client):
    """Soft delete is reversible, so the exclusion must be too — no dead state.

    "Fully" is load-bearing. ``POST /restore`` clears ``deletedAt`` but
    deliberately does NOT lift the suspension the delete applied
    (``admin.py:911-916`` — an account suspended for cause before it was deleted
    must not be silently un-suspended by a restore). So the account is
    unsuspended here as well before candidacy is asserted: this test says a
    fully reinstated account can be contacted again, and deliberately does not
    claim anything about a merely-undeleted-but-still-suspended one.

    See the module docstring's SCOPE note on suspension.
    """
    admin_headers, _ = _admin(client)
    uid, email = _dormant_free_account(client)
    _soft_delete(client, admin_headers, uid, email)
    assert email.lower() not in _candidate_emails()

    assert client.post(f"/admin/users/{uid}/restore", headers=admin_headers).status_code == 200
    assert client.post(f"/admin/users/{uid}/unsuspend", headers=admin_headers).status_code == 200
    assert email.lower() in _candidate_emails()


# --------------------------------------------------------------------------- #
# 2. The native agent's own growth figure must not count deleted accounts
# --------------------------------------------------------------------------- #


def test_sales_overview_signups_excludes_soft_deleted_accounts(client):
    """Asserted as a delta measured ACROSS the delete and nothing else.

    ``aether_test`` is shared with concurrent sessions that register their own
    users, so a wider before/after window would be measuring their traffic as
    well as this test's. Reading immediately either side of the one mutation
    under test keeps the window as small as it can be made.
    """
    admin_headers, _ = _admin(client)
    repo = SalesRepository()
    uid, email = _dormant_free_account(client)

    before = int(repo.overview()["signups"])
    _soft_delete(client, admin_headers, uid, email)
    after = int(repo.overview()["signups"])

    assert after == before - 1, (
        "a deleted account is still counted as a signup on the sales overview"
    )


def test_the_two_admin_surfaces_agree_that_a_deleted_account_is_gone(client):
    """The whole point: two consoles, one truth.

    ``/admin/metrics/executive`` (ADMIN-2.0) and the Sales AI Agent's overview
    (main) must both stop counting an account once it is deleted. They do not
    have to report the SAME number — the executive metric excludes admins and
    counts only a 30-day window, the sales overview counts all-time — but they
    must move together on an account that is inside both populations.

    The account here is therefore NOT backdated (unlike the lifecycle fixtures
    above): a 60-day-old signup sits outside the executive metric's window and
    would make this test pass for the wrong reason.
    """
    admin_headers, _ = _admin(client)
    repo = SalesRepository()

    def _exec_signups() -> int:
        r = client.get("/admin/metrics/executive", headers=admin_headers)
        assert r.status_code == 200, r.text
        return int(r.json()["signupsByDay"]["total"])

    email = f"fresh-{uuid.uuid4().hex[:8]}@example.com"
    _, uid = _register(client, email)
    sales_before, exec_before = int(repo.overview()["signups"]), _exec_signups()

    _soft_delete(client, admin_headers, uid, email)

    assert int(repo.overview()["signups"]) == sales_before - 1
    assert _exec_signups() == exec_before - 1


# --------------------------------------------------------------------------- #
# 3. Structural disjointness — cheap to assert, expensive to discover by hand
# --------------------------------------------------------------------------- #


def test_the_two_features_do_not_share_an_advisory_lock_id():
    """Same lock id would serialise two unrelated schemas against each other."""
    from app.repositories.sales import _ADVISORY_LOCK
    from app.repositories.sales_agents import _SALES_AGENT_LOCK

    assert _ADVISORY_LOCK != _SALES_AGENT_LOCK


def test_the_two_features_do_not_share_a_table():
    from app.repositories.sales_agents import ensure_sales_agent_schema

    ensure_sales_agent_schema()
    _ensure_sales_tables()
    native = {"SalesCampaign", "SalesLead", "SalesOutreachLog", "SalesSuppressionList"}
    reseller = {"SalesAgent"}
    assert native.isdisjoint(reseller)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = ANY(current_schemas(false))"
                "   AND table_name = ANY(%s)",
                (sorted(native | reseller),),
            )
            present = {r[0] for r in cur.fetchall()}
    assert native | reseller <= present, f"missing: {(native | reseller) - present}"


def test_the_reseller_routes_do_not_shadow_the_native_agent_routes(client):
    """``/admin/sales-agent`` is a strict string prefix of ``/admin/sales-agents``.

    ``admin.router`` (prefix ``/admin``, carrying ``/sales-agents``) is included
    BEFORE ``sales_agent.router`` (prefix ``/admin/sales-agent``), so if either
    side ever grew a greedy path parameter, the first-registered one would win
    silently and an admin would be shown the wrong feature's data under the
    right URL.

    Asserted behaviourally — each URL must reach its OWN handler, proven by a
    key only that handler returns — rather than by introspecting
    ``app.routes``, which reports only the top-level routes and would pass
    while both URLs resolved to the same place.
    """
    admin_headers, _ = _admin(client)

    reseller = client.get("/admin/sales-agents", headers=admin_headers)
    assert reseller.status_code == 200, reseller.text
    assert "agents" in reseller.json(), reseller.json()

    native = client.get("/admin/sales-agent/overview", headers=admin_headers)
    assert native.status_code == 200, native.text
    body = native.json()
    assert {"signups", "mrrAud", "suppressionCount"} <= set(body), body
    # The two payloads are not the same object under two names.
    assert "agents" not in body

    # Both are admin-gated, and neither is silently public.
    for path in ("/admin/sales-agents", "/admin/sales-agent/overview"):
        assert client.get(path).status_code in (401, 403), path
