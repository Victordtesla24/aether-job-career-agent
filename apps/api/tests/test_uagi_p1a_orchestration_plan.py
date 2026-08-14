"""U-AGI P1-A — server-owned RunPlan: the $0 plan view and Run-everything.

ADR-AGI-3 Decision 1 + its risk holds:

* the plan is VISIBLE before it is powerful — ``GET /agents/orchestration/plan``
  renders the Supervisor's plan with a per-step rationale and dispatches nothing
  ($0, no AgentRun row, no LLM call);
* ``POST /agents/orchestration/run-everything`` is ASYNC-ONLY (R-1: the silo
  guard lives on the async path, so a sync plan would make ``silo`` a comment)
  and refuses honestly when the flag is off;
* plan runs use NORMAL quota accounting — never ``skip_quota`` (R-2b);
* admission is API-enforced at the DATABASE for silo-class steps (R-1), not by
  a disabled button in one browser tab.
"""
from __future__ import annotations

import types
import uuid

import pytest

from app.db import get_connection
from app.repositories.billing import ensure_user_billing
from app.routers import agents as agents_mod


class FakeArqPool:
    def __init__(self):
        self.calls: list[tuple] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append((function_name, *args))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


def _set_paid_plan(user_id: str) -> None:
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                ("pro", "active", user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                ("pro", user_id),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# GET /agents/orchestration/plan — read-only, $0, honest.
# ---------------------------------------------------------------------------


def test_plan_endpoint_returns_19_steps_covering_21_cards(client, auth_headers):
    res = client.get("/agents/orchestration/plan", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["agentCount"] == 19
    assert body["cardCount"] == 21
    assert len(body["steps"]) == 19
    covered = [c for s in body["steps"] for c in s["coversCards"]]
    assert len(covered) == len(set(covered)) == 21


def test_plan_endpoint_dispatches_nothing_and_costs_zero(client, auth_headers):
    before = client.get("/agents/runs", headers=auth_headers).json()
    res = client.get("/agents/orchestration/plan", headers=auth_headers)
    assert res.status_code == 200
    after = client.get("/agents/runs", headers=auth_headers).json()
    assert len(after) == len(before), "the plan view must not record a run"
    assert res.json()["estimatedCostUsd"] == 0.0


def test_every_plan_step_carries_a_human_rationale(client, auth_headers):
    body = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    for step in body["steps"]:
        assert step["rationale"].strip(), step["backend"]
        assert step["execClass"] in {"sequential", "independent", "silo"}
        assert step["onRefusal"] in {"halt-chain", "isolate"}
    assert body["notes"], "the plan must state its own bounds"


def test_plan_narrates_the_ceiling_it_actually_runs_at(client, auth_headers, monkeypatch):
    monkeypatch.setenv("AETHER_ORCH_PLAN_CONCURRENCY", "1")
    body = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    assert body["concurrency"] == 1
    assert all(len(g) == 1 for g in body["groups"])
    assert "1" in body["concurrencyBasis"]


def test_plan_ceiling_is_clamped_to_the_worker_capacity(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_ORCH_PLAN_CONCURRENCY", "50")
    body = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    assert body["concurrency"] <= 3
    assert all(len(g) <= body["concurrency"] for g in body["groups"])


def test_silo_steps_are_alone_in_their_group_in_the_rendered_plan(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_ORCH_PLAN_CONCURRENCY", "3")
    body = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    by_group: dict[int, list] = {}
    for step in body["steps"]:
        by_group.setdefault(step["group"], []).append(step)
    for members in by_group.values():
        if any(m["execClass"] == "silo" for m in members):
            assert len(members) == 1


def test_plan_states_honestly_whether_run_everything_is_available(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "false")
    off = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    assert off["runnable"] is False
    assert off["refusal"]
    assert "async" in off["refusal"].lower()

    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    on = client.get("/agents/orchestration/plan", headers=auth_headers).json()
    assert on["runnable"] is True
    assert on["refusal"] is None


def test_plan_endpoint_requires_authentication(client):
    assert client.get("/agents/orchestration/plan").status_code == 401


# ---------------------------------------------------------------------------
# POST /agents/orchestration/run-everything
# ---------------------------------------------------------------------------


def test_run_everything_refuses_honestly_when_async_is_off(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "false")
    _set_paid_plan(test_user_id)
    res = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "async" in detail.lower()
    # An honest refusal records NO plan and NO run.
    assert client.get("/agents/runs", headers=auth_headers).json() == []


def test_run_everything_enqueues_one_plan_job_not_nineteen(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    _set_paid_plan(test_user_id)
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    res = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert res.status_code == 202, res.text
    body = res.json()
    assert body["status"] == "enqueued"
    assert body["stepCount"] == 19
    assert body["planId"]
    assert body["job_id"]
    # ONE stream of work over the plan, not 19 competing jobs (SSE cap / R-3).
    assert len(fake.calls) == 1


def test_run_everything_persists_the_plan_server_side(
    client, auth_headers, test_user_id, monkeypatch
):
    """The client batch runner dies with the tab; a server plan does not."""
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    _set_paid_plan(test_user_id)
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: FakeArqPool(), raising=True)

    plan_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]

    got = client.get(f"/agents/orchestration/plans/{plan_id}", headers=auth_headers)
    assert got.status_code == 200
    stored = got.json()
    assert stored["status"] == "planned"
    assert len(stored["steps"]) == 19
    assert all(s["state"] == "pending" for s in stored["steps"])


def test_a_plan_belongs_to_its_owner_alone(client, auth_headers, test_user_id, monkeypatch):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    _set_paid_plan(test_user_id)
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: FakeArqPool(), raising=True)
    plan_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]

    credentials = {
        "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup3rSecret",
    }
    assert client.post("/auth/register", json=credentials).status_code == 201
    login = client.post("/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    res = client.get(
        f"/agents/orchestration/plans/{plan_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_run_everything_never_uses_skip_quota(monkeypatch):
    """R-2b: sweep exemptions stay sweep-only. A plan step is a user-triggered
    run and consumes the user's plan allowance exactly like pressing Run."""
    import inspect

    from app.services.run_scheduler import executor as executor_mod

    source = inspect.getsource(executor_mod)
    assert "skip_quota" not in source
    plan_source = inspect.getsource(agents_mod.run_everything)
    assert "skip_quota" not in plan_source


def test_run_everything_requires_a_paid_subscription_when_the_gate_is_on(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # free plan, no active paid subscription
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: FakeArqPool(), raising=True)
    res = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert res.status_code == 402


def test_run_everything_requires_authentication(client):
    assert client.post("/agents/orchestration/run-everything").status_code == 401


# ---------------------------------------------------------------------------
# execute_run_plan — the real persistence + admission path (no agents dispatched).
# ---------------------------------------------------------------------------


def _enqueue_plan(client, auth_headers, test_user_id, monkeypatch) -> str:
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_ORCH_PLAN_SPACING_SECONDS", "0")
    _set_paid_plan(test_user_id)
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: FakeArqPool(), raising=True)
    return client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]


def test_execute_run_plan_persists_every_step_state(
    client, auth_headers, test_user_id, monkeypatch
):
    """Narration may only be fed from a PERSISTED transition, so every step's
    terminal state must be on the plan row when the executor returns."""
    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    dispatched: list[str] = []
    monkeypatch.setattr(
        agents_mod,
        "_dispatch",
        lambda uid, backend, params: dispatched.append(backend)
        or {"run_id": f"run-{backend}", "top_job_id": "job-1"},
    )

    summary = agents_mod.execute_run_plan(test_user_id, plan_id)
    assert summary["status"] == "completed"
    assert len(dispatched) == 19

    stored = client.get(
        f"/agents/orchestration/plans/{plan_id}", headers=auth_headers
    ).json()
    assert stored["status"] == "completed"
    assert {s["state"] for s in stored["steps"]} == {"completed"}
    assert stored["haltedAtStep"] is None
    # The recorded order is the planned order — the row is readable as a story.
    assert [s["backend"] for s in stored["steps"]][:3] == ["scout", "fitScorer", "matcher"]


def test_execute_run_plan_claims_the_db_slot_for_every_silo_step(
    client, auth_headers, test_user_id, monkeypatch
):
    """R-1: admission is API-enforced at the database, not by a disabled
    button. Every silo step must hold a real (user, agentKey) claim."""
    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    monkeypatch.setattr(
        agents_mod, "_dispatch",
        lambda uid, backend, params: {"run_id": "r", "top_job_id": "job-1"},
    )
    agents_mod.execute_run_plan(test_user_id, plan_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "agentKey", "status" FROM "BackgroundJob" '
                'WHERE "userId"=%s AND "agentKey" <> %s',
                (test_user_id, agents_mod._ORCH_PLAN_AGENT_KEY),
            )
            claims = dict(cur.fetchall())
    silos = {
        b for b, e in agents_mod._EXEC_CLASS_BY_BACKEND.items()
        if e["execClass"] == "silo"
    }
    assert set(claims) == silos, "a silo step ran without claiming its slot"
    assert set(claims.values()) == {"completed"}, "a claim was never released"


def test_a_silo_step_already_in_flight_is_refused_not_duplicated(
    client, auth_headers, test_user_id, monkeypatch
):
    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    # Somebody else (a sweep, another tab) already holds the scout slot.
    from app.repositories.background_jobs import BackgroundJobRepository

    BackgroundJobRepository().create_singleton(test_user_id, "scout", params={})

    dispatched: list[str] = []
    monkeypatch.setattr(
        agents_mod, "_dispatch",
        lambda uid, backend, params: dispatched.append(backend)
        or {"run_id": "r", "top_job_id": "job-1"},
    )
    summary = agents_mod.execute_run_plan(test_user_id, plan_id)

    assert "scout" not in dispatched, "a second concurrent discovery pass was started"
    by_key = {s["key"]: s for s in summary["steps"]}
    assert by_key["scout"]["state"] == "refused"
    # scout is halt-chain, so its chain is skipped — the enrichment fan-out is not.
    assert by_key["fitScorer"]["state"] == "not_attempted"
    assert by_key["marketTrends"]["state"] == "completed"
    assert summary["status"] == "partial"


def test_a_quota_429_halts_the_plan_once_and_records_what_was_not_attempted(
    client, auth_headers, test_user_id, monkeypatch
):
    from fastapi import HTTPException

    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    calls: list[str] = []

    def _dispatch(uid, backend, params):
        calls.append(backend)
        raise HTTPException(429, "quota_exceeded")

    monkeypatch.setattr(agents_mod, "_dispatch", _dispatch)
    summary = agents_mod.execute_run_plan(test_user_id, plan_id)

    assert len(calls) == 1, "the plan re-asked a question already answered"
    assert summary["status"] == "halted"
    assert summary["haltedAtStep"] == "scout"
    assert "quota" in summary["haltReason"]
    assert len(summary["notAttempted"]) == 18

    stored = client.get(
        f"/agents/orchestration/plans/{plan_id}", headers=auth_headers
    ).json()
    assert stored["status"] == "halted"
    assert stored["haltedAtStep"] == "scout"


def test_a_replayed_queue_message_never_restarts_a_running_plan(
    client, auth_headers, test_user_id, monkeypatch
):
    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        agents_mod, "_dispatch",
        lambda uid, backend, params: calls.append(backend) or {"run_id": "r"},
    )
    agents_mod.execute_run_plan(test_user_id, plan_id)
    first = len(calls)
    agents_mod.execute_run_plan(test_user_id, plan_id)  # re-delivery
    assert len(calls) == first, "a re-delivered plan job dispatched everything twice"


def test_a_plan_cannot_be_executed_for_another_user(
    client, auth_headers, test_user_id, monkeypatch
):
    plan_id = _enqueue_plan(client, auth_headers, test_user_id, monkeypatch)
    with pytest.raises(ValueError):
        agents_mod.execute_run_plan("someone-else", plan_id)
