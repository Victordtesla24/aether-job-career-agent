"""GAP-P6-ADMIN-001 / ADMIN-003 / SEC-001 — Admin Tier 1 + security (Cluster F).

Covers (§15 Tier 1 + §14.7 + §14.8):
- Admin route gating: non-admin -> 403, unauthenticated -> 401 on /admin/*.
- User list + detail with LLM spend in USD == SUM("AgentRun"."costUsd").
- /admin/spend totals + per-user spend (USD).
- POST spend-cap sets UsageQuota.spendCapUsd and an admin-set low cap trips the
  billing reserve's 429 spend_cap_exceeded BEFORE the LLM call (fn never runs).
- Suspend -> 403 on authenticated routes; unsuspend restores access.
- Signup toggle: settings signupEnabled=false -> POST /auth/register 403.
- Append-only AdminAuditLog: every admin mutation writes a row; no delete/edit.
- §14.7 rotation: seeded admin/admin123 is demoted to isAdmin=false; an
  env-configured admin (AETHER_ADMIN_EMAIL/PASSWORD_HASH) is granted isAdmin=true.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.db import get_connection, new_id
from app.repositories.admin import (
    _ensure_admin_schema,
    _reset_admin_ready_for_tests,
    apply_admin_rotation,
)
from app.repositories.billing import ensure_user_billing
from app.routers.agents import _record_run


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p6_billing).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    """Register + login a user; return (bearer_token, user_id)."""
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
    """A logged-in ADMIN user; return (auth_headers, admin_user_id).

    The JWT carries no privilege claim — ``get_current_user`` re-reads
    ``isAdmin`` from the row on every request, so promoting after login is
    enough for the existing token to act as admin.
    """
    token, uid = _register(client, f"admin-{uuid.uuid4().hex[:8]}@example.com")
    _promote(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _seed_runs(user_id: str, costs: list[float]) -> float:
    """Insert completed AgentRun rows with the given costUsd; return the sum."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for c in costs:
                cur.execute(
                    'INSERT INTO "AgentRun" '
                    '("id","userId","agentName","status","costUsd","startedAt",'
                    '"completedAt","createdAt") '
                    "VALUES (%s,%s,'tailor','completed'::\"AgentRunStatus\",%s,"
                    "NOW(),NOW(),NOW())",
                    (new_id(), user_id, c),
                )
        conn.commit()
    return round(sum(costs), 6)


# --------------------------------------------------------------------------- #
# Route gating (GATE-17)
# --------------------------------------------------------------------------- #


def test_admin_routes_require_authentication(client):
    for path in ("/admin/users", "/admin/health", "/admin/spend", "/admin/audit-log"):
        r = client.get(path)
        assert r.status_code == 401, f"{path}: {r.status_code}"


def test_non_admin_gets_403_on_admin_routes(client, auth_headers):
    for path in ("/admin/users", "/admin/health", "/admin/spend", "/admin/audit-log"):
        r = client.get(path, headers=auth_headers)
        assert r.status_code == 403, f"{path}: {r.status_code} {r.text}"


def test_admin_can_reach_admin_routes(client):
    headers, _ = _admin(client)
    r = client.get("/admin/users", headers=headers)
    assert r.status_code == 200, r.text
    assert "users" in r.json()


# --------------------------------------------------------------------------- #
# Users list + spend == SUM(costUsd) (GATE-17)
# --------------------------------------------------------------------------- #


def test_user_list_includes_plan_signup_and_spend(client):
    headers, _ = _admin(client)
    token, uid = _register(client, f"target-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)
    total = _seed_runs(uid, [0.10, 0.25, 0.05])

    r = client.get("/admin/users", headers=headers)
    assert r.status_code == 200, r.text
    rows = {u["id"]: u for u in r.json()["users"]}
    assert uid in rows
    row = rows[uid]
    assert row["plan"] == "free"
    assert row["signupAt"] is not None
    assert float(row["spendUsd"]) == pytest.approx(total, abs=1e-6)


def test_user_detail_spend_equals_sum_costusd(client):
    headers, _ = _admin(client)
    token, uid = _register(client, f"detail-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)
    total = _seed_runs(uid, [1.00, 2.50, 0.75])

    r = client.get(f"/admin/users/{uid}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == uid
    assert float(body["spendUsd"]) == pytest.approx(total, abs=1e-6)
    assert body["subscription"] is not None
    assert body["quota"] is not None


def test_spend_endpoint_totals_and_per_user(client):
    headers, _ = _admin(client)
    _, uid_a = _register(client, f"a-{uuid.uuid4().hex[:8]}@example.com")
    _, uid_b = _register(client, f"b-{uuid.uuid4().hex[:8]}@example.com")
    sum_a = _seed_runs(uid_a, [0.30, 0.20])
    sum_b = _seed_runs(uid_b, [1.10])

    r = client.get("/admin/spend", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    per = {p["userId"]: float(p["spendUsd"]) for p in body["perUser"]}
    assert per[uid_a] == pytest.approx(sum_a, abs=1e-6)
    assert per[uid_b] == pytest.approx(sum_b, abs=1e-6)
    assert float(body["totalUsd"]) + 1e-6 >= sum_a + sum_b


# --------------------------------------------------------------------------- #
# Spend cap: admin-set low cap trips 429 BEFORE the LLM call (§4.1)
# --------------------------------------------------------------------------- #


def test_set_spend_cap_persists_and_writes_audit(client):
    headers, admin_id = _admin(client)
    _, uid = _register(client, f"cap-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)

    r = client.post(
        f"/admin/users/{uid}/spend-cap", json={"spendCapUsd": 3.5}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert float(r.json()["spendCapUsd"]) == pytest.approx(3.5)

    # Persisted on the shared UsageQuota row.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "spendCapUsd" FROM "UsageQuota" WHERE "userId"=%s', (uid,)
            )
            assert float(cur.fetchone()[0]) == pytest.approx(3.5)
            # An audit row was written for this admin action.
            cur.execute(
                'SELECT count(*) FROM "AdminAuditLog" '
                'WHERE "actorUserId"=%s AND "action"=%s AND "targetId"=%s',
                (admin_id, "set_spend_cap", uid),
            )
            assert cur.fetchone()[0] == 1


# --------------------------------------------------------------------------- #
# MV-admin-settings-003 — auth gates before body parsing, for EVERY body shape
# (identical body-before-auth hazard/fix as MV-admin-settings-002, applied to
# admin_set_spend_cap).
# --------------------------------------------------------------------------- #


def test_spend_cap_malformed_json_unauth_is_401(client):
    _, uid = _register(client, f"cap-401a-{uuid.uuid4().hex[:8]}@example.com")
    resp = client.post(
        f"/admin/users/{uid}/spend-cap",
        content="not-json-at-all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401, resp.text


def test_spend_cap_wrong_type_unauth_is_401(client):
    _, uid = _register(client, f"cap-401b-{uuid.uuid4().hex[:8]}@example.com")
    resp = client.post(
        f"/admin/users/{uid}/spend-cap",
        json={"spendCapUsd": "not-a-number-xyz"},
    )
    assert resp.status_code == 401, resp.text


def test_spend_cap_malformed_json_authed_is_422(client):
    headers, _ = _admin(client)
    _, uid = _register(client, f"cap-422-{uuid.uuid4().hex[:8]}@example.com")
    resp = client.post(
        f"/admin/users/{uid}/spend-cap",
        content="not-json-at-all",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text


def test_spend_cap_invalid_value_authed_is_422(client):
    headers, _ = _admin(client)
    _, uid = _register(client, f"cap-422b-{uuid.uuid4().hex[:8]}@example.com")
    resp = client.post(
        f"/admin/users/{uid}/spend-cap",
        json={"spendCapUsd": -5},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text


def test_spend_cap_valid_body_still_ok_for_admin(client):
    headers, _ = _admin(client)
    _, uid = _register(client, f"cap-200-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)
    resp = client.post(
        f"/admin/users/{uid}/spend-cap", json={"spendCapUsd": 7.25}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert float(resp.json()["spendCapUsd"]) == pytest.approx(7.25)


def test_admin_low_cap_trips_429_before_llm_call(client):
    headers, _ = _admin(client)
    _, uid = _register(client, f"llm-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)

    # Admin sets a zero cap through the API (shares UsageQuota with the reserve).
    r = client.post(
        f"/admin/users/{uid}/spend-cap", json={"spendCapUsd": 0}, headers=headers
    )
    assert r.status_code == 200, r.text

    called = {"n": 0}

    def _sentinel():
        called["n"] += 1  # would only fire if the LLM/agent path executed
        return {"resume_id": "r", "changes": [], "rejected": []}

    with pytest.raises(HTTPException) as ei:
        _record_run(uid, "tailor", {"job_id": "j"}, _sentinel)
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "spend_cap_exceeded"
    assert called["n"] == 0  # blocked BEFORE any LLM call


# --------------------------------------------------------------------------- #
# Suspend -> 403 on authenticated routes (§15)
# --------------------------------------------------------------------------- #


def test_suspend_blocks_authenticated_routes_and_unsuspend_restores(client):
    headers, _ = _admin(client)
    token, uid = _register(client, f"susp-{uuid.uuid4().hex[:8]}@example.com")
    user_headers = {"Authorization": f"Bearer {token}"}

    # Baseline: the user can reach an authenticated route.
    assert client.get("/auth/me", headers=user_headers).status_code == 200

    s = client.post(f"/admin/users/{uid}/suspend", headers=headers)
    assert s.status_code == 200, s.text
    assert client.get("/auth/me", headers=user_headers).status_code == 403

    u = client.post(f"/admin/users/{uid}/unsuspend", headers=headers)
    assert u.status_code == 200, u.text
    assert client.get("/auth/me", headers=user_headers).status_code == 200


# --------------------------------------------------------------------------- #
# Signup toggle (§15 settings)
# --------------------------------------------------------------------------- #


def test_signup_toggle_disables_registration(client):
    headers, _ = _admin(client)

    off = client.post("/admin/settings", json={"signupEnabled": False}, headers=headers)
    assert off.status_code == 200, off.text
    assert off.json()["signupEnabled"] is False

    blocked = client.post(
        "/auth/register",
        json={"email": f"blocked-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd1"},
    )
    assert blocked.status_code == 403, blocked.text

    on = client.post("/admin/settings", json={"signupEnabled": True}, headers=headers)
    assert on.status_code == 200 and on.json()["signupEnabled"] is True
    allowed = client.post(
        "/auth/register",
        json={"email": f"allowed-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd1"},
    )
    assert allowed.status_code == 201, allowed.text


# --------------------------------------------------------------------------- #
# Append-only audit log (ADMIN-003)
# --------------------------------------------------------------------------- #


def test_every_mutation_writes_audit_and_log_is_append_only(client):
    headers, admin_id = _admin(client)
    _, uid = _register(client, f"aud-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)

    client.post(f"/admin/users/{uid}/spend-cap", json={"spendCapUsd": 2}, headers=headers)
    client.post(f"/admin/users/{uid}/suspend", headers=headers)
    client.post("/admin/settings", json={"signupEnabled": True}, headers=headers)

    r = client.get("/admin/audit-log", headers=headers)
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    actions = {e["action"] for e in entries if e["actorUserId"] == admin_id}
    assert {"set_spend_cap", "suspend_user", "update_settings"} <= actions
    # Every entry carries the append-only provenance fields.
    for e in entries:
        assert e["actorUserId"] and e["action"] and e["createdAt"]

    # Append-only: no mutation verbs are exposed on the audit-log resource.
    assert client.delete("/admin/audit-log", headers=headers).status_code in (404, 405)
    assert client.put("/admin/audit-log", headers=headers).status_code in (404, 405)


# --------------------------------------------------------------------------- #
# §14.7 credential rotation (GATE-31 / SEC-001)
# --------------------------------------------------------------------------- #


def test_rotation_demotes_seeded_admin_admin123(client):
    from scripts.seed_demo import ADMIN_EMAIL, seed_admin_user

    seed_admin_user()
    # Simulate a stray promotion of the seeded credential.
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "isAdmin"=true WHERE "email"=%s', (ADMIN_EMAIL,)
            )
        conn.commit()

    apply_admin_rotation()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "isAdmin" FROM "User" WHERE "email"=%s', (ADMIN_EMAIL,)
            )
            assert cur.fetchone()[0] is False  # GATE-31: demoted


def test_rotation_promotes_env_admin_and_keeps_seed_nonadmin(client, monkeypatch):
    from app.security import hash_password
    from scripts.seed_demo import ADMIN_EMAIL, seed_admin_user

    seed_admin_user()
    env_email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    monkeypatch.setenv("AETHER_ADMIN_EMAIL", env_email)
    monkeypatch.setenv("AETHER_ADMIN_PASSWORD_HASH", hash_password("Str0ngOwnerPass"))

    _reset_admin_ready_for_tests()
    apply_admin_rotation()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "isAdmin" FROM "User" WHERE "email"=%s', (env_email,))
            row = cur.fetchone()
            assert row is not None and row[0] is True  # env admin granted
            cur.execute('SELECT "isAdmin" FROM "User" WHERE "email"=%s', (ADMIN_EMAIL,))
            assert cur.fetchone()[0] is False  # seed stays non-admin
