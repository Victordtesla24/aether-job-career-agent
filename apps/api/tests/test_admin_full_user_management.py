"""ADMIN-FULL — admin user-management API (AdminUser-gated, fully audited).

USER MANDATE (2026-08-14): "admin users can change plans, subscriptions,
username/password of ANY user".

BILLING INVARIANTS (sacred): an admin plan change is an in-app ENTITLEMENT
override (comp / tier / unlimited — immediate, Stripe-independent) that NEVER
hand-mutates Stripe state; where a REAL Stripe subscription exists, the admin's
cancel/refund actions route through the EXISTING billing service paths
(``stripe_gateway`` + ``_revoke_to_free``). No-double-billing, refund/dispute
revoke and dunning grace are untouched.

AUDIT is universal and NOT a "restriction": every admin mutation on any account
appends an ``AdminAuditLog`` row with actor, target, action and before->after for
non-secret fields. A password change logs the EVENT and NEVER any value.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    ensure_user_billing,
)
from app.security import verify_password
from app.services import entitlements

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


def _target(client, password: str = "Passw0rd1") -> tuple[dict[str, str], str, str]:
    email = f"target-{uuid.uuid4().hex[:8]}@example.com"
    token, uid = _register(client, email, password)
    ensure_user_billing(uid)
    return {"Authorization": f"Bearer {token}"}, uid, email


def _seed_paid_sub(user_id: str, *, plan_id: str = "pro") -> tuple[str, str]:
    ensure_user_billing(user_id)
    customer_id = "cus_" + new_id()
    subscription_id = "sub_" + new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=\'active\','
                '"billingInterval"=\'month\',"stripeCustomerId"=%s,'
                '"stripeSubscriptionId"=%s,"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, customer_id, subscription_id, user_id),
            )
        conn.commit()
    return customer_id, subscription_id


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


def _password_hash(user_id: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "passwordHash" FROM "User" WHERE "id"=%s', (user_id,))
            return cur.fetchone()[0]


# --------------------------------------------------------------------------- #
# Gating — every new route is AdminUser-gated (401 anon, 403 non-admin)
# --------------------------------------------------------------------------- #

_MUTATIONS = [
    ("/entitlement", {"kind": "unlimited"}),
    ("/password", {"newPassword": "Sup3rSecret9"}),
    ("/identity", {"name": "Nope"}),
    ("/subscription/cancel", {"atPeriodEnd": True}),
    ("/subscription/refund", {}),
]


@pytest.mark.parametrize("suffix,body", _MUTATIONS)
def test_admin_user_management_routes_require_auth(client, suffix, body):
    r = client.post(f"/admin/users/some-id{suffix}", json=body)
    assert r.status_code == 401, f"{suffix}: {r.status_code}"


@pytest.mark.parametrize("suffix,body", _MUTATIONS)
def test_admin_user_management_routes_reject_non_admins(client, auth_headers, suffix, body):
    r = client.post(f"/admin/users/some-id{suffix}", json=body, headers=auth_headers)
    assert r.status_code == 403, f"{suffix}: {r.status_code} {r.text}"


def test_per_user_audit_route_is_admin_gated(client, auth_headers):
    assert client.get("/admin/users/x/audit").status_code == 401
    assert client.get("/admin/users/x/audit", headers=auth_headers).status_code == 403


# --------------------------------------------------------------------------- #
# 1. Entitlement override (tier / comp / unlimited) — visible + audited
# --------------------------------------------------------------------------- #


def test_admin_sets_a_tier_override_and_quota_follows_immediately(client):
    admin_headers, admin_id = _admin(client)
    _, target_id, _ = _target(client)

    r = client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "tier", "planId": "power", "note": "support credit"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entitlement"]["overrideActive"] is True
    assert body["entitlement"]["overrideKind"] == "tier"
    assert body["entitlement"]["planId"] == "power"

    quota = UsageQuotaRepository().get_by_user(target_id)
    assert int(quota["runsAllowed"]) == 300  # power plan limits applied immediately

    # Stripe truth untouched — the override never rewrites the Subscription row.
    sub = SubscriptionRepository().get_by_user(target_id)
    assert sub["planId"] == "free"
    assert sub["stripeSubscriptionId"] is None

    actions = [a["action"] for a in _audit_rows(target_id)]
    assert "set_entitlement_override" in actions
    entry = next(a for a in _audit_rows(target_id) if a["action"] == "set_entitlement_override")
    assert entry["actor"] == admin_id
    assert entry["detail"]["before"]["overrideKind"] is None
    assert entry["detail"]["after"]["overrideKind"] == "tier"


def test_admin_grants_unlimited_and_the_resolver_agrees(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    r = client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "unlimited", "note": "founding user"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert entitlements.resolve(target_id).unlimited is True


def test_admin_clears_an_override_and_it_is_audited(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "comp", "planId": "pro"},
        headers=admin_headers,
    )
    r = client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "none"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["entitlement"]["overrideActive"] is False
    assert entitlements.resolve(target_id).override_active is False
    assert "clear_entitlement_override" in [a["action"] for a in _audit_rows(target_id)]


def test_entitlement_override_rejects_an_unknown_kind(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    r = client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "platinum"},
        headers=admin_headers,
    )
    assert r.status_code == 422, r.text


def test_admin_user_detail_surfaces_the_override_flag(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "comp", "planId": "pro", "note": "beta tester"},
        headers=admin_headers,
    )
    d = client.get(f"/admin/users/{target_id}", headers=admin_headers).json()
    assert d["entitlement"]["overrideActive"] is True
    assert d["entitlement"]["overrideKind"] == "comp"
    assert d["entitlement"]["overrideNote"] == "beta tester"
    assert d["entitlement"]["activePaid"] is False


# --------------------------------------------------------------------------- #
# 2. Stripe-linked actions route through the EXISTING billing service
# --------------------------------------------------------------------------- #


def test_admin_cancel_at_period_end_uses_the_billing_gateway(client, monkeypatch):
    import app.services.stripe_gateway as gw

    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _cust, sub_id = _seed_paid_sub(target_id)

    seen = {}
    monkeypatch.setattr(gw, "is_configured", lambda: True)

    def _set_cape(subscription_id, value):
        seen["id"] = subscription_id
        seen["value"] = value
        return {"id": subscription_id, "cancelAtPeriodEnd": value}

    monkeypatch.setattr(gw, "set_cancel_at_period_end", _set_cape, raising=False)

    r = client.post(
        f"/admin/users/{target_id}/subscription/cancel",
        json={"atPeriodEnd": True},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert seen == {"id": sub_id, "value": True}
    sub = SubscriptionRepository().get_by_user(target_id)
    assert bool(sub["cancelAtPeriodEnd"]) is True
    assert sub["planId"] == "pro"  # still entitled until the period ends
    assert "cancel_subscription" in [a["action"] for a in _audit_rows(target_id)]


def test_admin_cancel_without_stripe_subscription_is_an_honest_409(client, monkeypatch):
    import app.services.stripe_gateway as gw

    monkeypatch.setattr(gw, "is_configured", lambda: True)
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    r = client.post(
        f"/admin/users/{target_id}/subscription/cancel",
        json={"atPeriodEnd": True},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text


def test_admin_refund_from_the_user_page_reuses_the_existing_refund_path(
    client, monkeypatch
):
    import app.services.stripe_gateway as gw

    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _cust, sub_id = _seed_paid_sub(target_id, plan_id="power")
    cancelled: list[str] = []
    monkeypatch.setattr(gw, "is_configured", lambda: True)
    monkeypatch.setattr(gw, "latest_paid_charge", lambda cid: "ch_admin_full")
    monkeypatch.setattr(
        gw, "create_refund", lambda ch: {"id": "re_admin_full", "status": "succeeded"}
    )
    monkeypatch.setattr(gw, "cancel_subscription", lambda sid: cancelled.append(sid))

    r = client.post(
        f"/admin/users/{target_id}/subscription/refund", json={}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["refundId"] == "re_admin_full"
    assert cancelled == [sub_id]
    sub = SubscriptionRepository().get_by_user(target_id)
    assert sub["planId"] == "free" and sub["status"] == "canceled"
    assert "billing_refund" in [a["action"] for a in _audit_rows(target_id)]


# --------------------------------------------------------------------------- #
# 3. Credentials: password
# --------------------------------------------------------------------------- #


def test_admin_sets_a_password_hashes_it_and_invalidates_sessions(client):
    admin_headers, admin_id = _admin(client)
    user_headers, target_id, email = _target(client)
    assert client.get("/auth/me", headers=user_headers).status_code == 200
    old_hash = _password_hash(target_id)

    new_password = "R0tatedPassw0rd"
    r = client.post(
        f"/admin/users/{target_id}/password",
        json={"newPassword": new_password},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["sessionsInvalidated"] is True

    stored = _password_hash(target_id)
    assert stored != old_hash
    assert stored != new_password  # never stored in the clear
    assert verify_password(new_password, stored)

    # O-4 session invalidation: the pre-change token no longer authenticates.
    assert client.get("/auth/me", headers=user_headers).status_code == 401
    # ... and the new password works.
    login = client.post("/auth/login", json={"email": email, "password": new_password})
    assert login.status_code == 200, login.text


def test_admin_password_change_audits_the_event_but_never_the_value(client):
    admin_headers, admin_id = _admin(client)
    _, target_id, _ = _target(client)
    secret = "N3verLogThisOne"
    client.post(
        f"/admin/users/{target_id}/password",
        json={"newPassword": secret},
        headers=admin_headers,
    )
    rows = _audit_rows(target_id)
    entry = next(a for a in rows if a["action"] == "set_user_password")
    assert entry["actor"] == admin_id
    serialized = repr(entry["detail"])
    assert secret not in serialized
    # No KEY hints at a stored secret either (no "password"/"hash" field).
    keys = {k.lower() for k in (entry["detail"] or {})}
    assert not any("password" in k or "hash" in k for k in keys)
    assert entry["detail"].get("sessionsInvalidated") is True
    # No key anywhere in the detail carries the value.
    assert all(secret not in str(v) for v in (entry["detail"] or {}).values())


def test_admin_password_change_enforces_the_password_policy(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    r = client.post(
        f"/admin/users/{target_id}/password",
        json={"newPassword": "short"},
        headers=admin_headers,
    )
    assert r.status_code == 422, r.text
    assert "password" in r.text.lower()


# --------------------------------------------------------------------------- #
# 4. Credentials: email / username / name — uniqueness + before->after audit
# --------------------------------------------------------------------------- #


def test_admin_changes_email_and_username_with_before_after_audit(client):
    admin_headers, admin_id = _admin(client)
    _, target_id, old_email = _target(client)
    new_email = f"renamed-{uuid.uuid4().hex[:8]}@example.com"
    new_username = f"user{uuid.uuid4().hex[:8]}"

    r = client.post(
        f"/admin/users/{target_id}/identity",
        json={"email": new_email, "username": new_username, "name": "Renamed Person"},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["before"]["email"] == old_email
    assert body["after"]["email"] == new_email
    assert body["after"]["username"] == new_username

    entry = next(
        a for a in _audit_rows(target_id) if a["action"] == "update_user_identity"
    )
    assert entry["actor"] == admin_id
    assert entry["detail"]["before"]["email"] == old_email
    assert entry["detail"]["after"]["email"] == new_email

    # The new email is a real login identity.
    login = client.post(
        "/auth/login", json={"email": new_email, "password": "Passw0rd1"}
    )
    assert login.status_code == 200, login.text


def test_admin_email_change_enforces_uniqueness(client):
    admin_headers, _ = _admin(client)
    _, first_id, first_email = _target(client)
    _, second_id, _ = _target(client)
    r = client.post(
        f"/admin/users/{second_id}/identity",
        json={"email": first_email},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text


def test_admin_username_change_enforces_uniqueness(client):
    admin_headers, _ = _admin(client)
    _, first_id, _ = _target(client)
    _, second_id, _ = _target(client)
    taken = f"taken{uuid.uuid4().hex[:8]}"
    assert (
        client.post(
            f"/admin/users/{first_id}/identity",
            json={"username": taken},
            headers=admin_headers,
        ).status_code
        == 200
    )
    r = client.post(
        f"/admin/users/{second_id}/identity",
        json={"username": taken},
        headers=admin_headers,
    )
    assert r.status_code == 409, r.text


def test_identity_change_on_a_missing_user_is_404(client):
    admin_headers, _ = _admin(client)
    r = client.post(
        "/admin/users/does-not-exist/identity",
        json={"name": "x"},
        headers=admin_headers,
    )
    assert r.status_code == 404, r.text


# --------------------------------------------------------------------------- #
# 5. Search + per-user audit trail
# --------------------------------------------------------------------------- #


def test_admin_user_search_matches_username(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    username = f"findme{uuid.uuid4().hex[:8]}"
    client.post(
        f"/admin/users/{target_id}/identity",
        json={"username": username},
        headers=admin_headers,
    )
    r = client.get(f"/admin/users?q={username}", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert [u["id"] for u in r.json()["users"]] == [target_id]


def test_per_user_audit_trail_returns_only_that_users_entries(client):
    admin_headers, _ = _admin(client)
    _, target_id, _ = _target(client)
    _, other_id, _ = _target(client)
    client.post(
        f"/admin/users/{target_id}/entitlement",
        json={"kind": "unlimited"},
        headers=admin_headers,
    )
    client.post(f"/admin/users/{other_id}/suspend", headers=admin_headers)

    r = client.get(f"/admin/users/{target_id}/audit", headers=admin_headers)
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    assert entries, "expected at least the override entry"
    assert {e["targetId"] for e in entries} == {target_id}
