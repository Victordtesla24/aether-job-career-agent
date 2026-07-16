"""GAP-P6-PAYWALL — subscription entitlement gate (limited-beta paid wall).

Aether is a SUBSCRIPTION-GATED product: a user cannot run ANY actionable agent
(tailor / coverLetter / storyExtractor / emailAgent / scout / matcher /
fitScorer / supervisor pipeline) without an ACTIVE PAID subscription
(``status='active'`` AND ``planId != 'free'``). The gate runs BEFORE the plan
quota reserve in ``agents._record_run`` and returns an honest HTTP 402
``subscription_required`` — never fabricates access.

The gate is flag-controlled by ``AETHER_REQUIRE_PAID_SUBSCRIPTION`` (default
``'true'`` in production). When ``'false'`` the old freemium behaviour (Free tier
5 runs) is restored. The suite-wide default is pinned OFF in ``conftest`` (like
``AETHER_LLM_MODE=replay``) so the freemium quota suites keep exercising the
Free path; every test here sets the flag EXPLICITLY.

Covers:
- (a) a user with NO active paid sub gets 402 ``subscription_required`` on an
  agent run (and consumes NO quota — the gate fires before the reserve);
- (b) a user WITH an active paid sub (``status='active'``, ``planId='pro'``) is
  allowed through to the quota check (one run is reserved);
- (c) ``AETHER_REQUIRE_PAID_SUBSCRIPTION='false'`` restores freemium (Free tier
  allowed);
- helper ``SubscriptionRepository.has_active_paid_subscription`` semantics
  (free -> False, pro/active -> True, pro/past_due -> False);
- the gate also blocks UNMETERED agents (scout) — the whole actionable pipeline
  is walled, not just the metered LLM agents;
- the HTTP surface: POST /agents/tailor/run returns 402 with the honest body;
- GET /billing/entitlement reports {active_paid, plan, requiresSubscription}.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import get_connection
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    ensure_user_billing,
)
from app.routers.agents import _record_run


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p6_billing).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


def _tailor_stub():
    return {"resume_id": "r1", "changes": [], "rejected": []}


def _set_plan(user_id: str, plan_id: str, status: str) -> None:
    """Force the user's Subscription row to (plan_id, status), keeping a
    matching UsageQuota so a reserved run has a ceiling to count against."""
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (plan_id, status, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, user_id),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# (a) No active paid sub -> 402 subscription_required, no quota consumed
# ---------------------------------------------------------------------------


def test_non_subscriber_gets_402_subscription_required(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
    with pytest.raises(HTTPException) as ei:
        _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert ei.value.status_code == 402
    detail = ei.value.detail
    assert detail["error"] == "subscription_required"
    assert "subscribe" in detail["message"].lower()
    assert detail["upgradeUrl"] == "/pricing"
    # The gate fired BEFORE the reserve — no run was consumed.
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 0


def test_gate_blocks_unmetered_agent_too(
    client, auth_headers, test_user_id, monkeypatch
):
    # scout is deterministic/unmetered, but it is still an actionable agent —
    # the wall blocks the WHOLE pipeline, not only the metered LLM agents.
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    with pytest.raises(HTTPException) as ei:
        _record_run(
            test_user_id, "scout", {},
            lambda: {"persisted": 0, "updated": 0, "errors": []},
        )
    assert ei.value.status_code == 402
    assert ei.value.detail["error"] == "subscription_required"


def test_tailor_endpoint_returns_402_for_non_subscriber(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    r = client.post("/agents/tailor/run", json={"job_id": "j"}, headers=auth_headers)
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["detail"]["error"] == "subscription_required"
    assert body["detail"]["upgradeUrl"] == "/pricing"


# ---------------------------------------------------------------------------
# (b) Active paid sub -> allowed through to the quota reserve
# ---------------------------------------------------------------------------


def test_paid_subscriber_is_allowed_through_to_quota(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")
    assert SubscriptionRepository().has_active_paid_subscription(test_user_id) is True
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert out["resume_id"] == "r1"
    # Allowed past the gate -> the reserve ran and consumed exactly one run.
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 1


# ---------------------------------------------------------------------------
# (c) Flag off -> freemium restored (Free tier allowed)
# ---------------------------------------------------------------------------


def test_flag_false_restores_freemium(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "false")
    ensure_user_billing(test_user_id)  # Free/active
    assert SubscriptionRepository().has_active_paid_subscription(test_user_id) is False
    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    assert out["resume_id"] == "r1"
    q = UsageQuotaRepository().get_by_user(test_user_id)
    assert int(q["runsUsed"]) == 1  # freemium Free-tier run allowed


# ---------------------------------------------------------------------------
# has_active_paid_subscription semantics
# ---------------------------------------------------------------------------


def test_has_active_paid_subscription_semantics(
    client, auth_headers, test_user_id
):
    repo = SubscriptionRepository()
    ensure_user_billing(test_user_id)  # Free / active
    assert repo.has_active_paid_subscription(test_user_id) is False  # free != paid

    _set_plan(test_user_id, "pro", "active")
    assert repo.has_active_paid_subscription(test_user_id) is True

    _set_plan(test_user_id, "pro", "past_due")
    assert repo.has_active_paid_subscription(test_user_id) is False  # not active

    _set_plan(test_user_id, "pro", "canceled")
    assert repo.has_active_paid_subscription(test_user_id) is False


def test_has_active_paid_subscription_false_when_no_row(client, auth_headers):
    # A user id with no Subscription row at all -> not paid (no crash).
    assert (
        SubscriptionRepository().has_active_paid_subscription("nonexistent-user-id")
        is False
    )


# ---------------------------------------------------------------------------
# GET /billing/entitlement
# ---------------------------------------------------------------------------


def test_entitlement_endpoint_reports_non_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    r = client.get("/billing/entitlement", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_paid"] is False
    assert body["requiresSubscription"] is True
    assert body["plan"]["id"] == "free"


def test_entitlement_endpoint_reports_paid_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")
    r = client.get("/billing/entitlement", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_paid"] is True
    assert body["plan"]["id"] == "pro"
    assert body["requiresSubscription"] is True


def test_entitlement_endpoint_flag_off_reports_not_required(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "false")
    r = client.get("/billing/entitlement", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["requiresSubscription"] is False
