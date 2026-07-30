"""ML-W4C — emailAgent must not bill a run that never reaches a model.

Same defect class as 4a9cd6c closed for ``companyResearch``, deliberately left
out of scope there ("re-pricing another wave's agent is not this fix's remit and
needs its own ruling") and now authorized by the wave-4C ruling.

``emailAgent`` sits in ``_LLM_TIER_BY_BACKEND`` and was metered PER BACKEND, so
every call reserved one run from the user's paid plan allowance — including the
modes that provably never call an LLM:

* ``mode=send``          — creates a pending ``email_send`` ApprovalRequest;
* ``mode=apply_labels``  — a Gmail label mutation (or an honest degrade when
                           Gmail is not connected);
* ``mode=triage`` with nothing to classify — the agent's own documented
  ``llm_called=False`` no-op, which was ALREADY reported honestly but whose
  reserved run was never refunded because the backstop in
  ``_execute_reserved_run`` is scoped to ``_OPTIONAL_LLM_BY_BACKEND`` members.

Both halves are asserted here: the params-decidable modes must not reserve at
all, and the DB-state-dependent triage no-op must be refunded by the backstop so
the END STATE of ``runsUsed`` is unchanged. The other direction is pinned too —
a triage that really classifies threads still reserves exactly one run — so the
atomic reserve-BEFORE-the-LLM-call rail is provably not weakened.

Fail-before at 3ed5aba: every ``runsUsed`` assertion below advances by one per
call, and the ``mode=send`` run records a fabricated non-zero ``costUsd`` priced
off request payload size for a run that called no model.
"""
from __future__ import annotations

import uuid

import pytest

from app.db import get_connection, new_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture()
def billing_seeded(user_id):
    """Materialise the quota row so ``runsUsed`` is a real number rather than an
    absent row that would make every assertion vacuous."""
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    return user_id


def _runs_used(user_id: str) -> int:
    from app.repositories.billing import UsageQuotaRepository

    row = UsageQuotaRepository().get_by_user(user_id)
    return int(row["runsUsed"]) if row else 0


def _seed_thread(user_id: str, subject: str = "Re: Delivery Lead role") -> str:
    thread_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "EmailThread" ("id","userId","subject","messages",'
                '"updatedAt") VALUES (%s,%s,%s,%s::jsonb,now())',
                (
                    thread_id,
                    user_id,
                    subject,
                    '[{"role":"received","body":"We have an opening for you."}]',
                ),
            )
        conn.commit()
    return thread_id


# ---------------------------------------------------------------------------
# Params-decidable no-LLM modes: no reserve at all
# ---------------------------------------------------------------------------


def test_two_send_mode_runs_leave_runs_used_unchanged(
    client, auth_headers, billing_seeded, user_id
):
    """The two-call shape: ``mode=send`` only queues an approval — no model is
    reached, so back-to-back calls must leave plan quota untouched."""
    before = _runs_used(user_id)
    for i in range(2):
        resp = client.post(
            "/agents/email/run",
            json={
                "mode": "send",
                "to": "recruiter@acme.com",
                "subject": f"Following up {i}",
                "body": "Thanks for your time.",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["approval_id"]
    assert _runs_used(user_id) == before, (
        "a send-mode emailAgent run calls no model and costs $0, so it must not "
        "consume a run from the user's paid plan allowance"
    )


def test_send_mode_records_zero_cost_and_no_model(client, auth_headers, billing_seeded):
    """No model was called, so the audit row must carry NO model stamp and $0 —
    never a cost priced off the request payload size."""
    resp = client.post(
        "/agents/email/run",
        json={
            "mode": "send",
            "to": "recruiter@acme.com",
            "subject": "Following up",
            "body": "Thanks for your time.",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] is None
    assert body["costUsd"] == 0.0
    assert body["tokensIn"] == 0 and body["tokensOut"] == 0
    assert body["noLlmCall"] is True


def test_apply_labels_without_gmail_is_unmetered(
    client, auth_headers, billing_seeded, user_id
):
    """The honest "connect Gmail to manage labels" degrade reaches no model."""
    before = _runs_used(user_id)
    resp = client.post(
        "/agents/email/run",
        json={"mode": "apply_labels", "add": ["Aether"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["connected"] is False and body["degraded"] is True
    assert body["costUsd"] == 0.0 and body["model"] is None
    assert _runs_used(user_id) == before


# ---------------------------------------------------------------------------
# DB-state-dependent no-LLM path: reserved up front, refunded by the backstop
# ---------------------------------------------------------------------------


def test_triage_with_nothing_to_classify_is_refunded(
    client, auth_headers, billing_seeded, user_id
):
    """Whether triage reaches a model depends on DB state, so the reserve still
    happens for EVERY triage call — the agent's honest ``llm_called=False`` is
    what triggers the refund, leaving the end state unchanged."""
    before = _runs_used(user_id)
    resp = client.post("/agents/email/run", json={"mode": "triage"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triaged"] == 0
    assert body["noLlmCall"] is True
    assert body["costUsd"] == 0.0 and body["model"] is None
    assert _runs_used(user_id) == before


def test_a_real_triage_run_consumes_exactly_one_run(
    client, auth_headers, billing_seeded, user_id, monkeypatch
):
    """The other direction — the rail must NOT be weakened: a triage that really
    classifies threads reaches the model and still reserves exactly one run."""
    monkeypatch.setenv("AETHER_MODEL_REASONING", "openai/gpt-4o")
    _seed_thread(user_id, subject=f"Re: role {uuid.uuid4().hex[:6]}")
    before = _runs_used(user_id)
    resp = client.post("/agents/email/run", json={"mode": "triage"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["triaged"] == 1
    assert body.get("noLlmCall") is None
    assert _runs_used(user_id) == before + 1


# ---------------------------------------------------------------------------
# Registration + scoping
# ---------------------------------------------------------------------------


def test_metering_predicate_is_registered_and_scoped():
    from app.routers.agents import (
        _OPTIONAL_LLM_BY_BACKEND,
        _call_is_metered,
        _email_agent_will_call_llm,
    )

    assert _OPTIONAL_LLM_BY_BACKEND["emailAgent"] is _email_agent_will_call_llm
    # No mode supplied == the agent's own default (triage) — conservatively metered.
    assert _call_is_metered("emailAgent", {}) is True
    assert _call_is_metered("emailAgent", {"mode": "triage"}) is True
    assert _call_is_metered("emailAgent", {"mode": "draft_reply"}) is True
    assert _call_is_metered("emailAgent", {"mode": "draft_follow_up"}) is True
    assert _call_is_metered("emailAgent", {"mode": "insights"}) is True
    # The two modes that provably reach no model.
    assert _call_is_metered("emailAgent", {"mode": "send"}) is False
    assert _call_is_metered("emailAgent", {"mode": "apply_labels"}) is False
    # An unknown mode is a 422 the agent raises AFTER dispatch — metered
    # conservatively so the reserve/refund path (not a silent free run) handles it.
    assert _call_is_metered("emailAgent", {"mode": "nope"}) is True
    # Unrelated backends keep their existing metering byte-for-byte.
    for backend in ("tailor", "coverLetter", "storyExtractor"):
        assert _call_is_metered(backend, {}) is True
    assert _call_is_metered("compliance", {}) is False


def test_no_llm_modes_report_llm_called_false_at_the_agent():
    """The router's zero-cost stamp is driven by the AGENT's own honest flag, so
    the flag itself is pinned here — the two modes never construct an LLM call."""
    from app.agents.email_agent import EmailAgent

    agent = EmailAgent(approvals=_FakeApprovals(), credentials=_FakeCredentials(False))
    sent = agent.run("u1", mode="send", to="r@x.com", subject="s", body="b")
    assert sent.llm_called is False
    labels = agent.run("u1", mode="apply_labels", add=["Aether"])
    assert labels.llm_called is False


class _FakeApprovals:
    def create(self, user_id, type_, payload, application_id=None):  # noqa: ANN001
        return {"id": "ap-1", "status": "pending"}


class _FakeCredentials:
    def __init__(self, connected: bool) -> None:
        self._connected = connected

    def is_connected(self, user_id: str) -> bool:  # noqa: ARG002
        return self._connected
