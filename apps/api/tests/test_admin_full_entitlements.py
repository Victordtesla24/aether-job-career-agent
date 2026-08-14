"""ADMIN-FULL — ONE server-side entitlement resolver, consulted EVERYWHERE.

USER MANDATE (2026-08-14): "remove ALL restrictions on admin users everywhere in
the app"; "admins/owners have NO subscriptions or plans themselves".

ORCHESTRATOR SCOPE RULING (binding): "restrictions" == quotas, run limits, spend
caps, paywalls / entitlement gates, tier/feature gates and per-user rate limits.
They are ALL exempted through ONE server-side resolver
(``app.services.entitlements``) — never a frontend-only bypass. NOT restrictions
(these stay universal and are deliberately NOT touched here): the honesty
machinery (fabrication guard, transmission proof, completeness verification),
auth itself, and AUDIT.

Every test below is a pair: the admin passes the enforcement point AND the
non-admin's behaviour at the same point is unchanged.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.db import get_connection
from app.repositories.admin import _ensure_admin_schema
from app.repositories.billing import UsageQuotaRepository, ensure_user_billing
from app.routers.agents import _record_run
from app.services import entitlements


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p6_admin).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


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


def _new_user(client, prefix: str) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"{prefix}-{uuid.uuid4().hex[:8]}@example.com")
    ensure_user_billing(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _new_admin(client, prefix: str = "adm") -> tuple[dict[str, str], str]:
    headers, uid = _new_user(client, prefix)
    _promote(uid)
    return headers, uid


def _exhaust_runs(user_id: str) -> None:
    """Drive the user's run quota to fully consumed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "runsUsed"="runsAllowed" WHERE "userId"=%s',
                (user_id,),
            )
        conn.commit()


def _exhaust_spend(user_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "UsageQuota" SET "spendUsedUsd"="spendCapUsd" WHERE "userId"=%s',
                (user_id,),
            )
        conn.commit()


def _sentinel_factory(counter: dict[str, int]):
    def _fn():
        counter["n"] += 1
        return {"resume_id": "r", "changes": [], "rejected": []}

    return _fn


# --------------------------------------------------------------------------- #
# 1. The resolver itself
# --------------------------------------------------------------------------- #


def test_resolver_reports_admin_as_unlimited_and_entitled(client):
    _, admin_id = _new_admin(client)
    ent = entitlements.resolve(admin_id)
    assert ent.is_admin is True
    assert ent.unlimited is True
    assert ent.entitled is True
    assert ent.source == entitlements.SOURCE_ADMIN


def test_resolver_leaves_a_plain_user_on_their_plan(client):
    _, uid = _new_user(client, "plain")
    ent = entitlements.resolve(uid)
    assert ent.is_admin is False
    assert ent.unlimited is False
    assert ent.source == entitlements.SOURCE_PLAN
    assert ent.override_active is False


def test_resolver_never_contradicts_stripe_truth_silently(client):
    """A comp override is entitled, but ``active_paid`` still reports the real
    (unpaid) Stripe/local subscription truth and the override is flagged."""
    _, uid = _new_user(client, "comp")
    _, admin_id = _new_admin(client)
    entitlements.set_override(uid, kind="comp", plan_id="pro", note="beta", actor_id=admin_id)
    ent = entitlements.resolve(uid)
    assert ent.entitled is True
    assert ent.override_active is True
    assert ent.override_kind == "comp"
    assert ent.source == entitlements.SOURCE_OVERRIDE
    assert ent.active_paid is False  # Stripe truth is NOT rewritten


def test_resolver_never_reports_an_unreadable_billing_store_as_unpaid(
    client, monkeypatch
):
    """"Unknown" must never be silently rendered as "unpaid".

    Swallowing a billing-store read failure would paywall (402) a paying
    customer and blame them for an outage on our side. The error propagates so
    the caller fails honestly instead.
    """
    from app.repositories.billing import SubscriptionRepository

    _, uid = _new_user(client, "dberr")

    # Signature MUST mirror the real method (including the optional ``cur`` the
    # transaction-scoped resolve path passes): a stub that is narrower than what
    # it replaces raises TypeError and would let this test "pass" for the wrong
    # reason — or, as here, fail on the double rather than on the behaviour.
    def _boom(self, _user_id, cur=None):  # noqa: ANN001
        raise RuntimeError("billing store unreadable")

    monkeypatch.setattr(
        SubscriptionRepository, "has_active_paid_subscription", _boom, raising=True
    )
    with pytest.raises(RuntimeError):
        entitlements.resolve(uid)
    # Same guarantee on the transaction-scoped path the admin routes use.
    with pytest.raises(RuntimeError):
        with get_connection() as conn:
            with conn.cursor() as cur:
                entitlements.resolve(uid, cur=cur)


# --------------------------------------------------------------------------- #
# 2. Enforcement point: run quota (429 quota_exceeded)
# --------------------------------------------------------------------------- #


def test_run_quota_admin_exempt_non_admin_unchanged(client):
    _, admin_id = _new_admin(client, "quota-adm")
    _, user_id = _new_user(client, "quota-usr")
    _exhaust_runs(admin_id)
    _exhaust_runs(user_id)

    # non-admin: unchanged -> 429 quota_exceeded BEFORE any LLM call
    calls = {"n": 0}
    with pytest.raises(HTTPException) as ei:
        _record_run(user_id, "tailor", {"job_id": "j"}, _sentinel_factory(calls))
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "quota_exceeded"
    assert calls["n"] == 0

    # admin: the exhausted quota does not stop the run
    admin_calls = {"n": 0}
    out = _record_run(admin_id, "tailor", {"job_id": "j"}, _sentinel_factory(admin_calls))
    assert admin_calls["n"] == 1
    assert out is not None


def test_admin_run_does_not_consume_the_run_allowance(client):
    _, admin_id = _new_admin(client, "noconsume")
    before = UsageQuotaRepository().get_or_create(admin_id)
    calls = {"n": 0}
    _record_run(admin_id, "tailor", {"job_id": "j"}, _sentinel_factory(calls))
    after = UsageQuotaRepository().get_by_user(admin_id)
    assert int(after["runsUsed"]) == int(before["runsUsed"])


# --------------------------------------------------------------------------- #
# 3. Enforcement point: USD spend cap (429 spend_cap_exceeded)
# --------------------------------------------------------------------------- #


def test_spend_cap_admin_exempt_non_admin_unchanged(client):
    _, admin_id = _new_admin(client, "cap-adm")
    _, user_id = _new_user(client, "cap-usr")
    _exhaust_spend(admin_id)
    _exhaust_spend(user_id)

    calls = {"n": 0}
    with pytest.raises(HTTPException) as ei:
        _record_run(user_id, "tailor", {"job_id": "j"}, _sentinel_factory(calls))
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "spend_cap_exceeded"
    assert calls["n"] == 0

    admin_calls = {"n": 0}
    _record_run(admin_id, "tailor", {"job_id": "j"}, _sentinel_factory(admin_calls))
    assert admin_calls["n"] == 1


def test_admin_spend_is_still_RECORDED_even_though_it_is_never_capped(client):
    """Accounting is not a restriction: an admin's realized LLM spend is still
    accumulated so /admin/spend stays truthful."""
    _, admin_id = _new_admin(client, "spendrec")
    quota = UsageQuotaRepository().get_or_create(admin_id)
    before = float(quota["spendUsedUsd"])
    UsageQuotaRepository().record_spend(admin_id, 0.25)
    after = float(UsageQuotaRepository().get_by_user(admin_id)["spendUsedUsd"])
    assert after == pytest.approx(before + 0.25, abs=1e-6)


# --------------------------------------------------------------------------- #
# 4. Enforcement point: subscription paywall (402 subscription_required)
# --------------------------------------------------------------------------- #


def test_paywall_admin_exempt_non_admin_unchanged(client, monkeypatch):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _, admin_id = _new_admin(client, "wall-adm")
    _, user_id = _new_user(client, "wall-usr")

    calls = {"n": 0}
    with pytest.raises(HTTPException) as ei:
        _record_run(user_id, "tailor", {"job_id": "j"}, _sentinel_factory(calls))
    assert ei.value.status_code == 402
    assert ei.value.detail["error"] == "subscription_required"
    assert calls["n"] == 0

    admin_calls = {"n": 0}
    _record_run(admin_id, "tailor", {"job_id": "j"}, _sentinel_factory(admin_calls))
    assert admin_calls["n"] == 1


def test_entitlement_endpoint_marks_admin_unlimited(client, monkeypatch):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    admin_headers, _ = _new_admin(client, "ent-adm")
    user_headers, _ = _new_user(client, "ent-usr")

    a = client.get("/billing/entitlement", headers=admin_headers)
    assert a.status_code == 200, a.text
    assert a.json()["unlimited"] is True
    assert a.json()["entitled"] is True
    assert a.json()["source"] == "admin"

    u = client.get("/billing/entitlement", headers=user_headers)
    assert u.status_code == 200, u.text
    assert u.json()["unlimited"] is False
    assert u.json()["entitled"] is False
    assert u.json()["active_paid"] is False


def test_subscription_endpoint_exposes_the_unlimited_entitlement(client):
    admin_headers, _ = _new_admin(client, "sub-adm")
    user_headers, _ = _new_user(client, "sub-usr")

    a = client.get("/billing/subscription", headers=admin_headers).json()
    assert a["entitlement"]["unlimited"] is True
    assert a["entitlement"]["source"] == "admin"

    u = client.get("/billing/subscription", headers=user_headers).json()
    assert u["entitlement"]["unlimited"] is False
    assert u["quota"] is not None  # plain users keep their quota surface


# --------------------------------------------------------------------------- #
# 5. Enforcement point: per-user rate limiters (checkout / portal)
# --------------------------------------------------------------------------- #


def test_checkout_rate_limiter_admin_exempt_non_admin_unchanged(client):
    class _DenyAll:
        def allow(self, _user_id: str) -> bool:
            return False

        def retry_after(self, _user_id: str) -> int:
            return 60

    client.app.state.checkout_rate_limiter = _DenyAll()
    try:
        user_headers, _ = _new_user(client, "rl-usr")
        admin_headers, _ = _new_admin(client, "rl-adm")
        body = {"planId": "pro", "interval": "month"}

        u = client.post("/billing/checkout", json=body, headers=user_headers)
        assert u.status_code == 429, u.text

        a = client.post("/billing/checkout", json=body, headers=admin_headers)
        assert a.status_code != 429, a.text
    finally:
        client.app.state.checkout_rate_limiter = None


def test_scout_sync_cooldown_admin_exempt_non_admin_unchanged(client):
    """The manual-Sync cooldown (S-FIX-A / S-7) is a PER-USER rate limit.

    The scout report's §1.7 said the checkout limiter was the only one; it
    missed this seam. Under the binding ruling a per-user click cooldown is a
    restriction, so an admin is exempt — while the SHARED protection it was
    built to defend is untouched: the Adzuna daily budget is enforced
    independently inside ``app.services.discovery.adzuna_adapter``
    (``_daily_budget`` / ``budget_snapshot``), not here, so an exempt admin
    still cannot spend past the deployment-wide ceiling.
    """
    from app.routers.agents import _guard_scout_cooldown

    class _DenyAll:
        max_calls = 3
        window_seconds = 600.0

        def allow(self, _user_id: str) -> bool:
            return False

        def retry_after(self, _user_id: str) -> int:
            return 60

    class _Req:
        def __init__(self, app):
            self.app = app

    request = _Req(client.app)
    client.app.state.scout_rate_limiter = _DenyAll()
    try:
        _, user_id = _new_user(client, "scout-usr")
        _, admin_id = _new_admin(client, "scout-adm")

        with pytest.raises(HTTPException) as ei:
            _guard_scout_cooldown(user_id, request, False)
        assert ei.value.status_code == 429  # non-admin still cooled down

        _guard_scout_cooldown(admin_id, request, False)  # admin: no refusal
    finally:
        client.app.state.scout_rate_limiter = None


# --------------------------------------------------------------------------- #
# 6. Enforcement point: autopilot / board-sweep spend-cap stop
# --------------------------------------------------------------------------- #


def test_board_sweep_spend_cap_stop_admin_exempt_non_admin_unchanged(client):
    # ``_spend_cap_breach`` is the real seam autopilot consults before dispatch
    # (board_sweep.py:778, called at :954 and :1035) — a non-None return halts
    # the sweep for that user.
    from app.workers.board_sweep import _spend_cap_breach

    _, admin_id = _new_admin(client, "sweep-adm")
    _, user_id = _new_user(client, "sweep-usr")
    _exhaust_spend(admin_id)
    _exhaust_spend(user_id)

    assert _spend_cap_breach(user_id) is not None  # non-admin still stopped
    assert _spend_cap_breach(admin_id) is None  # admin never stopped by the cap


def test_autopilot_eligibility_includes_an_admin_and_still_excludes_a_free_user(
    client, monkeypatch
):
    """``_sweep_eligible_users`` is a SQL-side copy of the paywall.

    If it disagreed with the resolver, an admin would pass every runtime gate
    and still be silently dropped from autopilot — the exact silent divergence
    the ONE-resolver rule exists to prevent. The free non-admin must stay
    excluded, so the gate itself is not weakened for anyone else.
    """
    from app.routers import agents as agents_mod

    monkeypatch.setattr(agents_mod, "subscription_gate_enabled", lambda: True)
    _, admin_id = _new_admin(client, "elig-adm")
    _, free_id = _new_user(client, "elig-usr")
    # ``_sweep_eligible_users`` only serves accounts with a real search target.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "targetRole"=%s WHERE "id" = ANY(%s)',
                ("Staff Engineer", [admin_id, free_id]),
            )
        conn.commit()

    eligible = {row["id"] for row in agents_mod._sweep_eligible_users(500)}
    assert admin_id in eligible  # admin is served by autopilot
    assert free_id not in eligible  # free non-admin still excluded


# --------------------------------------------------------------------------- #
# 7. Enforcement point: async enqueue seam reserves nothing for an admin
# --------------------------------------------------------------------------- #


def test_async_enqueue_does_not_reserve_for_an_admin(client, monkeypatch):
    from app.routers import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_enqueue_to_arq", lambda job_id: f"arq-{job_id}")
    _, admin_id = _new_admin(client, "enq-adm")
    _exhaust_runs(admin_id)
    job_id = agents_mod._enqueue_single_agent(admin_id, "tailor", {"job_id": "j"})
    assert job_id
    quota = UsageQuotaRepository().get_by_user(admin_id)
    assert int(quota["runsUsed"]) == int(quota["runsAllowed"])  # nothing extra reserved


def test_async_enqueue_still_429s_a_non_admin_over_quota(client, monkeypatch):
    from app.routers import agents as agents_mod

    monkeypatch.setattr(agents_mod, "_enqueue_to_arq", lambda job_id: f"arq-{job_id}")
    _, user_id = _new_user(client, "enq-usr")
    _exhaust_runs(user_id)
    with pytest.raises(HTTPException) as ei:
        agents_mod._enqueue_single_agent(user_id, "tailor", {"job_id": "j"})
    assert ei.value.status_code == 429
