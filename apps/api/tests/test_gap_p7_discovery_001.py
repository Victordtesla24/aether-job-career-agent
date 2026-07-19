"""GAP-P7-DISCOVERY-001 — scoped SYSTEM-RUN exemption (ADR-P7-05).

TDD fail-before: the Phase-6 paywall (GAP-P6-PAYWALL) walls ALL actionable
agent runs behind an active-paid-subscription check, including the
platform's own scheduled discovery cron (``scripts/discovery_cron.sh``),
which necessarily runs as a real (currently Free-plan) user account. That
broke ``aether-discovery.service`` in production (exit 22 — confirmed by
direct reproduction, not hypothesis; see
``uat/reports/evidence/phase7/gap-discovery-rca.md``).

ADR-P7-05 ruling (fable-5, 2026-07-17): a scoped SYSTEM-RUN exemption. The
cron sends ``X-Aether-System-Run: <secret>`` (shared secret from
``AETHER_SYSTEM_RUN_SECRET``); the server bypasses ONLY the subscription
gate, ONLY for the discovery pipeline's own agent keys (``scout``,
``fitScorer``), ONLY when the secret matches (constant-time compare).
REJECTED alternatives: hand-granting the account a fake paid subscription
(fakes billing state), and silently swallowing the 402 in the cron script
(leaves discovery actually broken).

Covers:
- (a) scout / fit-scorer run WITH a valid system-run header for a free-plan
  account -> permitted past the gate (FAILS today: 402 — the header/secret
  mechanism does not exist yet).
- (b) the same run WITHOUT the header, WITH a WRONG secret, or with the
  header set but the server-side secret unconfigured -> still 402 (the
  header alone must never bypass anything on its own).
- (c) a NON-discovery agent (tailor) WITH a valid secret -> still 402 (the
  exemption must not open any other agent, even with the right secret).
- (d) a permitted system run is recorded with ``systemRun: true`` in its
  billing-audit trail (``AgentRun.billingAuditJson``); an ordinary paid
  user's run is never marked that way.
"""
from __future__ import annotations

import pytest

from app.db import get_connection
from app.repositories.billing import ensure_user_billing

SYSTEM_SECRET = "test-system-run-secret-p7-discovery"
SCOUT_PARAMS = {
    "query": "Senior Technical Program Manager",
    "location": "Melbourne, Australia",
}


@pytest.fixture(autouse=True)
def _gate_on(monkeypatch):
    # The suite-wide default (conftest) pins the paywall OFF; every test here
    # needs it explicitly ON, same convention as test_gap_p6_paywall.py.
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")


def _set_paid_plan(user_id: str, plan_id: str = "pro", status: str = "active") -> None:
    """Force an ACTIVE PAID Subscription row (mirrors test_gap_p6_paywall._set_plan)."""
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


def _billing_audit_for_latest_run(user_id: str, agent_name: str) -> dict:
    """Raw read of the most recent AgentRun's billingAuditJson for
    ``agent_name``. The repository's list/get methods project a fixed column
    set that does not include this column (agent_run.py:_COLUMNS), so this
    reads the audit trail directly rather than presupposing a particular API
    surface for it."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "billingAuditJson" FROM "AgentRun" '
                'WHERE "userId" = %s AND "agentName" = %s '
                'ORDER BY "createdAt" DESC LIMIT 1',
                (user_id, agent_name),
            )
            row = cur.fetchone()
    return row[0] if row and row[0] else {}


# ---------------------------------------------------------------------------
# (a) Valid system-run header permits a free-plan discovery run
# ---------------------------------------------------------------------------


def test_scout_run_with_valid_system_secret_bypasses_paywall(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
    headers = {**auth_headers, "X-Aether-System-Run": SYSTEM_SECRET}
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=headers)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "accepted"


def test_fit_scorer_run_with_valid_system_secret_bypasses_paywall(
    client, auth_headers, test_user_id, monkeypatch
):
    from conftest import seed_own_resume

    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)
    # NF-final-B-008: the fit scorer scores only against the caller's own resume.
    seed_own_resume(client, auth_headers)
    headers = {**auth_headers, "X-Aether-System-Run": SYSTEM_SECRET}
    r = client.post("/agents/fit-scorer/run", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# (b) No header / wrong secret / secret unconfigured -> still 402 (guard)
# ---------------------------------------------------------------------------


def test_scout_run_without_header_still_402(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=auth_headers)
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["error"] == "subscription_required"


def test_scout_run_with_wrong_secret_still_402(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)
    headers = {**auth_headers, "X-Aether-System-Run": "wrong-secret"}
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=headers)
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["error"] == "subscription_required"


def test_scout_run_with_header_but_server_secret_unset_still_402(
    client, auth_headers, test_user_id, monkeypatch
):
    # AETHER_SYSTEM_RUN_SECRET unset/empty server-side -> the header is
    # IGNORED entirely, never treated as a bypass-by-omission.
    monkeypatch.delenv("AETHER_SYSTEM_RUN_SECRET", raising=False)
    ensure_user_billing(test_user_id)
    headers = {**auth_headers, "X-Aether-System-Run": SYSTEM_SECRET}
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=headers)
    assert r.status_code == 402, r.text


# ---------------------------------------------------------------------------
# (c) Scope guard: a non-discovery agent is NEVER exempt, even with the
#     correct secret
# ---------------------------------------------------------------------------


def test_tailor_run_with_valid_system_secret_still_402(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)
    headers = {**auth_headers, "X-Aether-System-Run": SYSTEM_SECRET}
    r = client.post("/agents/tailor/run", json={"job_id": "j"}, headers=headers)
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["error"] == "subscription_required"


# ---------------------------------------------------------------------------
# (d) A permitted system run is audited with systemRun=true; an ordinary
#     paid user's run never is
# ---------------------------------------------------------------------------


def test_system_run_is_audited_with_system_run_marker(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    ensure_user_billing(test_user_id)
    headers = {**auth_headers, "X-Aether-System-Run": SYSTEM_SECRET}
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=headers)
    assert r.status_code == 202, r.text
    audit = _billing_audit_for_latest_run(test_user_id, "scout")
    assert audit.get("systemRun") is True


def test_ordinary_paid_user_run_is_not_marked_system_run(
    client, auth_headers, test_user_id, monkeypatch
):
    # An active paid subscriber running scout WITHOUT the header must never
    # be marked systemRun -- the marker is exclusively for the exempted path.
    monkeypatch.setenv("AETHER_SYSTEM_RUN_SECRET", SYSTEM_SECRET)
    _set_paid_plan(test_user_id)
    r = client.post("/agents/scout/run", json=SCOUT_PARAMS, headers=auth_headers)
    assert r.status_code == 202, r.text
    audit = _billing_audit_for_latest_run(test_user_id, "scout")
    assert audit.get("systemRun") is not True
