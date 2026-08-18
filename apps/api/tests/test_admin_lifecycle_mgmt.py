"""ADMIN-MGMT E1 — lifecycle views, HARD purge with cascade, subscription-record
deletion, hygiene report.

Owner mandate under test: an admin has FULL management power over real accounts,
and a deleted or stale record must be removable FOR REAL — not merely flagged.

Contract (all five routes ``AdminUser``-gated, every mutation audited):

* ``GET    /admin/users?view=active|suspended|deleted|all`` — lifecycle slice,
  default ``active``; additive ``counts:{active,suspended,deleted}``.
* ``POST   /admin/users/{id}/purge`` — hard delete + full child cascade, guarded
  four ways (typed email, protected account, prior soft delete, live Stripe).
* ``DELETE /admin/users/{id}/subscription`` — delete the LOCAL billing rows
  (works for orphans whose ``User`` row is already gone).
* ``GET    /admin/hygiene`` — read-only stale-data report.
* ``POST   /admin/hygiene/purge-orphans`` — delete ONLY owner-less billing pairs.

THE LOAD-BEARING ASSERTION in the purge happy path is not "the route returned
200": it is that rows seeded in ten child tables (including a join-keyed one,
``ApplicationStatusEvent``, which has no ``userId`` column at all) are counted to
ZERO afterwards, while the ``AdminAuditLog`` trail SURVIVES. A purge that reports
success and leaves rows behind is the exact failure this file exists to catch.

MONEY SAFETY: nothing here touches Stripe. The "live subscription" cases are
local rows written by SQL; the route's job is to REFUSE them.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import _ensure_billing_tables, ensure_user_billing

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


@pytest.fixture()
def admin_headers(client) -> dict[str, str]:
    token, uid = _register(client, f"mgmt-admin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}


def _target(client) -> tuple[str, str]:
    """Register an ordinary user; return ``(user_id, email)``."""
    email = f"mgmt-target-{uuid.uuid4().hex[:8]}@example.com"
    _, uid = _register(client, email)
    return uid, email


def _soft_delete(client, admin_headers, user_id: str, email: str) -> None:
    r = client.request(
        "DELETE",
        f"/admin/users/{user_id}",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


#: The child tables seeded by :func:`_seed_child_rows`, with the predicate that
#: finds this user's rows. ``ApplicationStatusEvent`` is keyed to its PARENT —
#: it has no ``userId`` column — which is precisely why it is in the list.
_SEEDED_TABLES: tuple[tuple[str, str], ...] = (
    ("Job", 'SELECT count(*) FROM "Job" WHERE "userId"=%s'),
    ("Resume", 'SELECT count(*) FROM "Resume" WHERE "userId"=%s'),
    ("Application", 'SELECT count(*) FROM "Application" WHERE "userId"=%s'),
    (
        "ApplicationStatusEvent",
        'SELECT count(*) FROM "ApplicationStatusEvent" e'
        ' JOIN "Application" a ON a."id"=e."applicationId" WHERE a."userId"=%s',
    ),
    ("AgentRun", 'SELECT count(*) FROM "AgentRun" WHERE "userId"=%s'),
    ("StoryEntry", 'SELECT count(*) FROM "StoryEntry" WHERE "userId"=%s'),
    ("Contact", 'SELECT count(*) FROM "Contact" WHERE "userId"=%s'),
    ("AgentConfig", 'SELECT count(*) FROM "AgentConfig" WHERE "userId"=%s'),
    (
        "EvidenceCorpusItem",
        'SELECT count(*) FROM "EvidenceCorpusItem" WHERE "userId"=%s',
    ),
    ("JobSourceStatus", 'SELECT count(*) FROM "JobSourceStatus" WHERE "userId"=%s'),
    ("Subscription", 'SELECT count(*) FROM "Subscription" WHERE "userId"=%s'),
    ("UsageQuota", 'SELECT count(*) FROM "UsageQuota" WHERE "userId"=%s'),
)


def _seed_child_rows(user_id: str) -> dict[str, str]:
    """Seed one row per table in ``_SEEDED_TABLES``. Returns the ids created."""
    _ensure_admin_schema()
    _ensure_billing_tables()
    # Registration does NOT create the billing pair (it is seeded lazily on the
    # first billing read), so seed it explicitly — the purge has to clear it.
    ensure_user_billing(user_id)
    job_id, resume_id, app_id = new_id(), new_id(), new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Job" ("id","userId","title","company","description",'
                '"source","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,now())',
                (job_id, user_id, "Engineer", "Acme", "desc", "seed"),
            )
            cur.execute(
                'INSERT INTO "Resume" ("id","userId","sections","formatHash",'
                '"updatedAt") VALUES (%s,%s,%s,%s,now())',
                (resume_id, user_id, "{}", "hash"),
            )
            cur.execute(
                'INSERT INTO "Application" ("id","userId","jobId","resumeId",'
                '"updatedAt") VALUES (%s,%s,%s,%s,now())',
                (app_id, user_id, job_id, resume_id),
            )
            cur.execute(
                'INSERT INTO "ApplicationStatusEvent" ("id","applicationId",'
                '"toStatus","source") VALUES (%s,%s,%s,%s)',
                (new_id(), app_id, "applied", "seed"),
            )
            cur.execute(
                'INSERT INTO "AgentRun" ("id","userId","agentName")'
                " VALUES (%s,%s,%s)",
                (new_id(), user_id, "scout"),
            )
            cur.execute(
                'INSERT INTO "StoryEntry" ("id","userId","title","situation","task",'
                '"action","result","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,now())',
                (new_id(), user_id, "t", "s", "t", "a", "r"),
            )
            cur.execute(
                'INSERT INTO "Contact" ("id","userId","name","updatedAt")'
                " VALUES (%s,%s,%s,now())",
                (new_id(), user_id, "A Contact"),
            )
            cur.execute(
                'INSERT INTO "AgentConfig" ("userId","agentKey") VALUES (%s,%s)',
                (user_id, "scout"),
            )
            cur.execute(
                'INSERT INTO "EvidenceCorpusItem" ("userId","itemId","claim")'
                " VALUES (%s,%s,%s)",
                (user_id, new_id(), "a claim"),
            )
            cur.execute(
                'INSERT INTO "JobSourceStatus" ("userId","source") VALUES (%s,%s)',
                (user_id, "adzuna"),
            )
        conn.commit()
    return {"jobId": job_id, "resumeId": resume_id, "applicationId": app_id}


def _row_counts(user_id: str) -> dict[str, int]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            out: dict[str, int] = {}
            for table, sql in _SEEDED_TABLES:
                cur.execute(sql, (user_id,))
                out[table] = int(cur.fetchone()[0])
    return out


def _user_exists(user_id: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "User" WHERE "id"=%s', (user_id,))
            return int(cur.fetchone()[0]) == 1


def _audit_actions(target_id: str) -> list[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "action" FROM "AdminAuditLog" WHERE "targetId"=%s'
                ' ORDER BY "createdAt"',
                (target_id,),
            )
            return [r[0] for r in cur.fetchall()]


def _audit_detail(target_id: str, action: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "detailJson" FROM "AdminAuditLog"'
                ' WHERE "targetId"=%s AND "action"=%s ORDER BY "createdAt" DESC',
                (target_id, action),
            )
            row = cur.fetchone()
    assert row is not None, f"no {action} audit row for {target_id}"
    return row[0]


def _make_billable(user_id: str, status: str = "active") -> None:
    """Give the user a LOCAL row that names a live Stripe subscription."""
    _ensure_billing_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "stripeSubscriptionId"=%s,"status"=%s'
                ' WHERE "userId"=%s',
                (f"sub_test_{uuid.uuid4().hex[:8]}", status, user_id),
            )
            if cur.rowcount == 0:
                cur.execute(
                    'INSERT INTO "Subscription" ("id","userId","planId","status",'
                    '"stripeSubscriptionId") VALUES (%s,%s,%s,%s,%s)',
                    (
                        new_id(),
                        user_id,
                        "pro",
                        status,
                        f"sub_test_{uuid.uuid4().hex[:8]}",
                    ),
                )
        conn.commit()


def _make_orphan_billing() -> str:
    """A Subscription+UsageQuota pair whose ``userId`` has NO ``User`` row."""
    _ensure_billing_tables()
    orphan_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Subscription" ("id","userId","planId","status")'
                " VALUES (%s,%s,%s,%s)",
                (new_id(), orphan_id, "free", "canceled"),
            )
            cur.execute(
                'INSERT INTO "UsageQuota" ("id","userId","planId","periodStart",'
                '"periodEnd","runsAllowed","spendCapUsd") VALUES'
                " (%s,%s,%s,date_trunc('month',now()),"
                " date_trunc('month',now()) + interval '1 month',%s,%s)",
                (new_id(), orphan_id, "free", 5, 1.0),
            )
        conn.commit()
    return orphan_id


# --------------------------------------------------------------------------- #
# (a) Gating — every one of the five routes is AdminUser-gated
# --------------------------------------------------------------------------- #


def test_all_five_routes_reject_anonymous_callers(client):
    """401 for an anonymous caller on every route — including the ones whose
    body is malformed. Auth resolves BEFORE the body is read (the
    body-before-auth hazard ``_parse_json_object`` exists for), so a caller with
    no credentials can never learn a validation detail."""
    assert client.get("/admin/users", params={"view": "deleted"}).status_code == 401
    assert client.post("/admin/users/x/purge", json={}).status_code == 401
    assert client.request("DELETE", "/admin/users/x/subscription").status_code == 401
    assert client.get("/admin/hygiene").status_code == 401
    assert client.post("/admin/hygiene/purge-orphans", json={}).status_code == 401
    # Malformed body still 401, not 422.
    assert (
        client.post(
            "/admin/users/x/purge",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        ).status_code
        == 401
    )


def test_all_five_routes_reject_non_admin_users(client, auth_headers):
    assert (
        client.post("/admin/users/x/purge", json={}, headers=auth_headers).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE", "/admin/users/x/subscription", headers=auth_headers
        ).status_code
        == 403
    )
    assert client.get("/admin/hygiene", headers=auth_headers).status_code == 403
    assert (
        client.post(
            "/admin/hygiene/purge-orphans", json={"confirm": True}, headers=auth_headers
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/admin/users", params={"view": "all"}, headers=auth_headers
        ).status_code
        == 403
    )


# --------------------------------------------------------------------------- #
# (b) Lifecycle views + counts
# --------------------------------------------------------------------------- #


def test_view_filters_split_active_from_deleted(client, admin_headers):
    live_id, _live_email = _target(client)
    gone_id, gone_email = _target(client)
    _soft_delete(client, admin_headers, gone_id, gone_email)

    def ids(view: str | None) -> set[str]:
        params = {"limit": 500}
        if view is not None:
            params["view"] = view
        r = client.get("/admin/users", params=params, headers=admin_headers)
        assert r.status_code == 200, r.text
        return {u["id"] for u in r.json()["users"]}

    # Default is ACTIVE: the soft-deleted account is no longer mixed in.
    assert live_id in ids(None)
    assert gone_id not in ids(None)

    assert gone_id in ids("deleted")
    assert live_id not in ids("deleted")

    assert live_id in ids("active")
    assert gone_id not in ids("active")

    both = ids("all")
    assert live_id in both and gone_id in both


def test_suspended_view_excludes_deleted_accounts(client, admin_headers):
    """A soft delete also suspends. ``view=suspended`` must still mean "an active
    account that is suspended" — otherwise every deleted account would show up
    under a tab that promises the opposite."""
    suspended_id, _ = _target(client)
    assert (
        client.post(
            f"/admin/users/{suspended_id}/suspend", headers=admin_headers
        ).status_code
        == 200
    )
    deleted_id, deleted_email = _target(client)
    _soft_delete(client, admin_headers, deleted_id, deleted_email)

    r = client.get(
        "/admin/users", params={"view": "suspended", "limit": 500}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    ids = {u["id"] for u in r.json()["users"]}
    assert suspended_id in ids
    assert deleted_id not in ids


def test_counts_are_additive_and_span_every_bucket(client, admin_headers):
    live_id, _ = _target(client)
    gone_id, gone_email = _target(client)
    _soft_delete(client, admin_headers, gone_id, gone_email)

    r = client.get("/admin/users", params={"limit": 500}, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Existing shape untouched.
    assert {"users", "total", "limit", "offset"} <= set(body)
    counts = body["counts"]
    assert set(counts) == {"active", "suspended", "deleted"}
    assert counts["deleted"] >= 1
    assert counts["active"] >= 2  # live target + the admin making the call
    # The counts are NOT scoped to the selected view: the default view returned
    # only active rows, yet the deleted bucket is still reported.
    assert body["total"] == counts["active"]

    deleted_view = client.get(
        "/admin/users", params={"view": "deleted", "limit": 500}, headers=admin_headers
    ).json()
    assert deleted_view["total"] == counts["deleted"]
    assert deleted_view["counts"] == counts


def test_legacy_suspended_param_is_unchanged_without_view(client, admin_headers):
    """The legacy boolean keeps its exact old meaning: no lifecycle predicate is
    applied, so a soft-deleted (therefore suspended) account is still returned."""
    gone_id, gone_email = _target(client)
    _soft_delete(client, admin_headers, gone_id, gone_email)

    r = client.get(
        "/admin/users",
        params={"suspended": "true", "limit": 500},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert gone_id in {u["id"] for u in r.json()["users"]}


def test_unknown_view_is_an_honest_422(client, admin_headers):
    r = client.get(
        "/admin/users", params={"view": "archived"}, headers=admin_headers
    )
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# (c) Purge guards — each refuses and writes NOTHING
# --------------------------------------------------------------------------- #


def test_purge_refuses_an_account_that_is_not_soft_deleted(client, admin_headers):
    user_id, email = _target(client)
    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert "soft-delete" in r.json()["detail"].lower()
    assert _user_exists(user_id)
    assert "purge_user" not in _audit_actions(user_id)


def test_purge_refuses_a_protected_admin_account(client, admin_headers):
    user_id, email = _target(client)
    _promote(user_id)
    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    assert "admin privileges" in r.json()["detail"]
    assert _user_exists(user_id)


def test_purge_refuses_while_a_live_stripe_subscription_exists(
    client, admin_headers
):
    user_id, email = _target(client)
    _soft_delete(client, admin_headers, user_id, email)
    _make_billable(user_id, status="active")
    seeded = _row_counts(user_id)
    assert seeded["Subscription"] == 1

    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "cancel" in detail.lower() and "subscription/cancel" in detail
    # Nothing was written: the account and its billing row are both intact.
    assert _user_exists(user_id)
    assert _row_counts(user_id)["Subscription"] == 1
    assert "purge_user" not in _audit_actions(user_id)


def test_purge_allows_a_canceled_subscription(client, admin_headers):
    """The guard is about MONEY STILL MOVING, not about the presence of a Stripe
    id. A canceled subscription bills nobody, so it must not block cleanup."""
    user_id, email = _target(client)
    _soft_delete(client, admin_headers, user_id, email)
    _make_billable(user_id, status="canceled")

    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert not _user_exists(user_id)


def test_purge_refuses_a_mismatched_confirm_email(client, admin_headers):
    user_id, email = _target(client)
    _soft_delete(client, admin_headers, user_id, email)
    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": "someone-else@example.com"},
        headers=admin_headers,
    )
    assert r.status_code == 422, r.text
    assert _user_exists(user_id)

    # A missing confirmEmail is the same refusal, not a silent success.
    assert (
        client.post(
            f"/admin/users/{user_id}/purge", json={}, headers=admin_headers
        ).status_code
        == 422
    )
    assert _user_exists(user_id)


def test_purge_of_an_unknown_user_is_404(client, admin_headers):
    r = client.post(
        "/admin/users/no-such-user/purge",
        json={"confirmEmail": "x@example.com"},
        headers=admin_headers,
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# (d) Purge happy path — the cascade actually empties every child table
# --------------------------------------------------------------------------- #


def test_purge_cascades_every_child_table_and_keeps_the_audit_trail(
    client, admin_headers
):
    user_id, email = _target(client)
    _seed_child_rows(user_id)

    before = _row_counts(user_id)
    seeded_tables = [t for t, n in before.items() if n > 0]
    assert len(seeded_tables) >= 6, before
    # The join-keyed table (no userId column of its own) is genuinely populated.
    assert before["ApplicationStatusEvent"] == 1

    _soft_delete(client, admin_headers, user_id, email)

    r = client.post(
        f"/admin/users/{user_id}/purge",
        json={"confirmEmail": email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["userId"] == user_id
    assert body["purged"] is True

    # Every seeded table is EMPTY for this user.
    after = _row_counts(user_id)
    assert all(n == 0 for n in after.values()), after

    # The User row itself is gone.
    assert not _user_exists(user_id)

    # The per-table receipt is real, not decorative.
    tables = body["tables"]
    assert tables["User"] == 1
    for table in ("Job", "Resume", "Application", "ApplicationStatusEvent", "AgentRun"):
        assert tables[table] == 1, (table, tables)

    # The audit trail SURVIVES the purge, and records it with the counts.
    actions = _audit_actions(user_id)
    assert "delete_user" in actions, "the soft-delete audit row must not be purged"
    assert "purge_user" in actions
    detail = _audit_detail(user_id, "purge_user")
    assert detail["mode"] == "hard"
    assert detail["tables"]["Job"] == 1


def test_purge_does_not_touch_another_users_rows(client, admin_headers):
    victim_id, victim_email = _target(client)
    bystander_id, _ = _target(client)
    _seed_child_rows(victim_id)
    _seed_child_rows(bystander_id)

    _soft_delete(client, admin_headers, victim_id, victim_email)
    r = client.post(
        f"/admin/users/{victim_id}/purge",
        json={"confirmEmail": victim_email},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text

    survivors = _row_counts(bystander_id)
    for table in ("Job", "Resume", "Application", "ApplicationStatusEvent", "AgentRun"):
        assert survivors[table] == 1, (table, survivors)
    assert _user_exists(bystander_id)


# --------------------------------------------------------------------------- #
# (e) DELETE the local subscription record
# --------------------------------------------------------------------------- #


def test_delete_subscription_record_removes_local_billing_rows(client, admin_headers):
    user_id, _ = _target(client)
    _seed_child_rows(user_id)
    assert _row_counts(user_id)["Subscription"] == 1

    r = client.request(
        "DELETE", f"/admin/users/{user_id}/subscription", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["userId"] == user_id
    assert body["deleted"]["subscription"] == 1
    assert body["deleted"]["usageQuota"] >= 0

    after = _row_counts(user_id)
    assert after["Subscription"] == 0
    assert after["UsageQuota"] == 0
    # The account itself is untouched — this is record cleanup, not a delete.
    assert _user_exists(user_id)
    assert "delete_subscription_record" in _audit_actions(user_id)


def test_delete_subscription_record_refuses_a_live_stripe_subscription(
    client, admin_headers
):
    user_id, _ = _target(client)
    _seed_child_rows(user_id)
    _make_billable(user_id, status="past_due")

    r = client.request(
        "DELETE", f"/admin/users/{user_id}/subscription", headers=admin_headers
    )
    assert r.status_code == 409, r.text
    assert "cancel" in r.json()["detail"].lower()
    assert _row_counts(user_id)["Subscription"] == 1
    assert "delete_subscription_record" not in _audit_actions(user_id)


def test_delete_subscription_record_cleans_an_orphan_with_no_user_row(
    client, admin_headers
):
    """The single most useful case: the User row is already gone. Keying on the
    userId alone is what makes this route able to clear it at all."""
    orphan_id = _make_orphan_billing()
    assert not _user_exists(orphan_id)

    r = client.request(
        "DELETE", f"/admin/users/{orphan_id}/subscription", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == {"subscription": 1, "usageQuota": 1}
    assert _row_counts(orphan_id)["Subscription"] == 0
    assert _row_counts(orphan_id)["UsageQuota"] == 0
    assert _audit_detail(orphan_id, "delete_subscription_record")["userRowExists"] is (
        False
    )


# --------------------------------------------------------------------------- #
# (f) Hygiene report + orphan purge
# --------------------------------------------------------------------------- #


def test_hygiene_report_shape_and_content(client, admin_headers):
    gone_id, gone_email = _target(client)
    _soft_delete(client, admin_headers, gone_id, gone_email)
    orphan_id = _make_orphan_billing()

    r = client.get("/admin/hygiene", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {
        "softDeletedUsers",
        "orphanedBillingPairs",
        "canceledSubscriptions",
        "neverLoggedIn30d",
    }
    assert body["softDeletedUsers"]["count"] >= 1
    sample_ids = {s["id"] for s in body["softDeletedUsers"]["sample"]}
    assert gone_id in sample_ids
    assert all(
        set(s) == {"id", "email", "deletedAt"} for s in body["softDeletedUsers"]["sample"]
    )
    assert body["orphanedBillingPairs"]["count"] >= 1
    # The sample is newest-first, so an orphan created moments ago is visible
    # even on a schema carrying thousands of ancient ones.
    assert orphan_id in body["orphanedBillingPairs"]["sample"]
    assert len(body["orphanedBillingPairs"]["sample"]) <= 10
    assert body["canceledSubscriptions"]["count"] >= 1
    assert isinstance(body["neverLoggedIn30d"]["count"], int)

    # Read-only: nothing it reported was disposed of by reporting it.
    assert _user_exists(gone_id)
    assert _row_counts(orphan_id)["Subscription"] == 1


def test_purge_orphans_requires_explicit_confirmation(client, admin_headers):
    orphan_id = _make_orphan_billing()
    for body in ({}, {"confirm": False}, {"confirm": "true"}):
        r = client.post("/admin/hygiene/purge-orphans", json=body, headers=admin_headers)
        assert r.status_code == 422, (body, r.text)
    assert _row_counts(orphan_id)["Subscription"] == 1


def test_purge_orphans_deletes_only_orphans(client, admin_headers):
    orphan_id = _make_orphan_billing()
    live_id, _ = _target(client)
    _seed_child_rows(live_id)
    assert _row_counts(live_id)["Subscription"] == 1

    r = client.post(
        "/admin/hygiene/purge-orphans", json={"confirm": True}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["purged"] is True
    assert body["deleted"]["subscription"] >= 1
    assert body["deleted"]["usageQuota"] >= 1
    assert body["userIdCount"] >= 1
    assert len(body["userIdSample"]) <= 10

    # The orphan is gone; the live account's billing is untouched.
    assert _row_counts(orphan_id)["Subscription"] == 0
    assert _row_counts(orphan_id)["UsageQuota"] == 0
    assert _row_counts(live_id)["Subscription"] == 1
    assert _row_counts(live_id)["UsageQuota"] == 1
    assert _user_exists(live_id)

    # Audited, with the exact counts.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "detailJson" FROM "AdminAuditLog" WHERE "action"=%s'
                ' ORDER BY "createdAt" DESC LIMIT 1',
                ("purge_orphans",),
            )
            detail = cur.fetchone()[0]
    assert detail["subscription"] == body["deleted"]["subscription"]
    assert detail["usageQuota"] == body["deleted"]["usageQuota"]


def test_purge_orphans_is_a_no_op_on_the_second_call(client, admin_headers):
    """Idempotent, and — the point of the test — it stops. The first call clears
    whatever orphans exist; the second must find none and delete nothing, rather
    than reaching for rows that merely look stale."""
    live_id, _ = _target(client)
    _seed_child_rows(live_id)
    _make_orphan_billing()

    first = client.post(
        "/admin/hygiene/purge-orphans", json={"confirm": True}, headers=admin_headers
    )
    assert first.status_code == 200, first.text
    assert first.json()["deleted"]["subscription"] >= 1

    second = client.post(
        "/admin/hygiene/purge-orphans", json={"confirm": True}, headers=admin_headers
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["deleted"] == {"subscription": 0, "usageQuota": 0}
    assert body["userIdCount"] == 0
    assert body["userIdSample"] == []

    # The live account is still fully intact after two bulk passes.
    assert _row_counts(live_id)["Subscription"] == 1
    assert _row_counts(live_id)["UsageQuota"] == 1
    assert _user_exists(live_id)
