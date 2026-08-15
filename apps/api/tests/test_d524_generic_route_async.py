"""D.524 — remove the 524-timeout class from the generic agent-run route
(TDD fail-before).

CONTEXT (docs/delivery/ORCH-DELTA-2026-08-14.md row "D generic-route 524";
``uat/reports/evidence/orch-exec/MON-RESIDUALS-EVIDENCE-2026-08-14.md`` probe
5): ``POST /agents/{name}/run`` (``run_named_agent``) is the ONE remaining
fully-synchronous run route. It carries ~24% of all ``/run`` traffic (the six
agents with no dedicated route: submission, salaryIntelligence, marketTrends,
recruiterOutreach, compliance, companyResearch — plus every OTHER agent's
alternate/camelCase alias, e.g. ``coverLetter``) — the exact shape of
Cloudflare-524 exposure MON-020 already fixed for ``scout`` and
GAP-P7-ASYNC-001 already fixed for the dedicated ``tailor``/``cover-letter``
routes.

TARGET CONTRACT asserted here (fails against pre-fix code):

(a) ``AETHER_ASYNC_GENERATION=true`` -> the generic route returns the SAME
    202 ``{"job_id", "status": "enqueued"}`` envelope the dedicated async
    routes return (mirrors ``test_mon020_async_scout.py`` /
    ``test_gap_p7_async_001.py`` assertions), enqueued onto the SAME
    ``run_agent_job`` ARQ machinery, WITHOUT executing the agent in-request.
(b) That job is pollable to a terminal state through the EXISTING
    ``GET /agents/jobs/{job_id}`` route (owner-scoped), driving the worker
    directly exactly as the mon020 tests do.
(c) ``AETHER_ASYNC_GENERATION=false`` (the default) -> byte-compatible
    synchronous behaviour, zero regression for existing consumers.
(d) NO singleton (binding orchestrator ruling OQ-2): two concurrent enqueues
    for the SAME user+agent are BOTH accepted with DISTINCT job ids — the
    generic route makes no single-run-per-agent claim, unlike ``scout``.

Plus two SCOPE item 3 parity checks ("whatever the route enforces today it
must enforce identically on the async path"): agent-name validation (404) and
required-param validation (422) both fire BEFORE anything is enqueued/
persisted/reserved — never discovered only after an async job was accepted —
and one quota-reservation parity check for a METERED backend through the
generic route (R-2b: no ``skip_quota``).

Redis-free strategy inherited from ``test_gap_p7_async_001.py`` /
``test_mon020_async_scout.py``: the ARQ pool is a ``FakeArqPool`` injected at
the ``agents._get_arq_pool`` seam; the worker task is invoked directly. No
broker is touched.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import types
import uuid

import pytest

from app.db import get_connection
from app.routers import agents as agents_mod

# ---------------------------------------------------------------------------
# Shared fixtures / helpers (mirrors test_mon020_async_scout.py /
# test_gap_p7_async_001.py — each async test file owns its own local copies).
# ---------------------------------------------------------------------------

_BACKGROUND_JOB_DDL = (
    '''
    CREATE TABLE IF NOT EXISTS "BackgroundJob" (
        "id"              text PRIMARY KEY DEFAULT gen_random_uuid()::text,
        "userId"          text        NOT NULL,
        "agentKey"        text        NOT NULL,
        "runId"           text,
        "params"          jsonb,
        "status"          text        NOT NULL DEFAULT 'enqueued',
        "arqJobId"        text,
        "result"          jsonb,
        "error"           text,
        "attempts"        integer     NOT NULL DEFAULT 0,
        "quotaReserved"   boolean     NOT NULL DEFAULT false,
        "quotaReservedAt" timestamptz,
        "quotaRefundedAt" timestamptz,
        "startedAt"       timestamptz,
        "finishedAt"      timestamptz,
        "createdAt"       timestamptz NOT NULL DEFAULT now(),
        "updatedAt"       timestamptz NOT NULL DEFAULT now()
    )
    ''',
)


@pytest.fixture()
def bg_table(client):
    """Additive, test-schema-only ``BackgroundJob`` table, emptied per test.

    Depends on ``client`` so the standard per-test TRUNCATE runs first."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in _BACKGROUND_JOB_DDL:
                cur.execute(stmt)
            cur.execute('TRUNCATE TABLE "BackgroundJob"')
        conn.commit()
    return True


class FakeArqPool:
    """In-memory stand-in for the ARQ Redis pool (no broker)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append((function_name, *args))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


@pytest.fixture()
def fake_pool(monkeypatch):
    pool = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: pool, raising=True)
    return pool


def _get_bg_job(job_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","userId","agentKey","status","result","error","params",'
                '"quotaReserved" FROM "BackgroundJob" WHERE "id"=%s',
                (job_id,),
            )
            row = cur.fetchone()
            cols = [c.name for c in cur.description]
    if row is None:
        raise AssertionError(f"BackgroundJob {job_id} not found")
    rec = dict(zip(cols, row))
    for key in ("result", "params"):
        if isinstance(rec.get(key), str):
            rec[key] = json.loads(rec[key])
    return rec


def _count_bg_jobs(user_id: str, agent_key: str = "compliance") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "BackgroundJob" '
                'WHERE "userId"=%s AND "agentKey"=%s',
                (user_id, agent_key),
            )
            return int(cur.fetchone()[0])


def _count_agent_runs(user_id: str, agent_name: str = "compliance") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "AgentRun" WHERE "userId"=%s AND "agentName"=%s',
                (user_id, agent_name),
            )
            return int(cur.fetchone()[0])


def _set_paid_plan(user_id: str) -> None:
    """ACTIVE PAID subscription + quota headroom, for the metered-parity test."""
    from app.repositories.billing import ensure_user_billing

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


# ===========================================================================
# (a) async-on: 202 + poll-id envelope, agent NOT executed in-request
# ===========================================================================


def test_generic_route_async_on_returns_202_enqueue_envelope(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    """``compliance`` has NO dedicated route (probe 5's own list) — a pure
    generic-route agent. Deterministic + unmetered, so no LLM/quota setup
    needed; asserts the SAME shape ``test_mon020_async_scout.py`` asserts for
    scout's background mode."""
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    resp = client.post("/agents/compliance/run", json={}, headers=auth_headers)

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "enqueued", body
    assert isinstance(body.get("job_id"), str) and body["job_id"], body
    # Went onto the EXISTING queue machinery, addressed to run_agent_job — the
    # agent itself must NOT have executed inside the request (the whole point).
    assert fake_pool.calls == [("run_agent_job", body["job_id"])], fake_pool.calls
    job = _get_bg_job(body["job_id"])
    assert job["agentKey"] == "compliance"
    assert job["status"] == "enqueued"


# ===========================================================================
# (b) the enqueued job is pollable to a terminal state via the EXISTING route
# ===========================================================================


def test_generic_route_async_job_pollable_to_terminal_state(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    job_id = client.post(
        "/agents/compliance/run", json={}, headers=auth_headers
    ).json()["job_id"]

    poll = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert poll.status_code == 200, poll.text
    payload = poll.json()
    assert payload["job_id"] == job_id
    assert payload["status"] in ("enqueued", "processing")
    assert payload["agentKey"] == "compliance"

    from app.workers.tasks import run_agent_job

    asyncio.run(run_agent_job({}, job_id))

    job = _get_bg_job(job_id)
    assert job["status"] == "completed", job
    assert job["error"] is None
    # ComplianceAgent.run() scans this user's recent AgentRun rows, which
    # (verified live, RED run) already includes THIS run's own in-flight row
    # at execution time — scanned=1 for a fresh user, a REAL result, never
    # fixture content.
    assert job["result"]["scanned"] == 1

    poll2 = client.get(f"/agents/jobs/{job_id}", headers=auth_headers).json()
    assert poll2["status"] == "completed"
    assert poll2["result"]["scanned"] == 1

    # Owner-scoped: a different user cannot read it.
    other = {"email": f"d524-{uuid.uuid4().hex[:8]}@example.com", "password": "Sup3rSecret"}
    assert client.post("/auth/register", json=other).status_code in (201, 409)
    other_headers = {
        "Authorization": "Bearer "
        + client.post("/auth/login", json=other).json()["access_token"]
    }
    assert client.get(f"/agents/jobs/{job_id}", headers=other_headers).status_code == 404


# ===========================================================================
# (c) async-off: byte-compatible synchronous behaviour, zero regression
# ===========================================================================


def test_generic_route_async_off_stays_synchronous(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "false")

    resp = client.post("/agents/compliance/run", json={}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Legacy synchronous shape — the real ComplianceReport dict (self-
    # referential scanned=1, verified live above), never an enqueue envelope.
    assert body["scanned"] == 1, body
    assert "job_id" not in body
    assert "status" not in body or body.get("status") != "enqueued"
    # Nothing was queued or persisted as a background job.
    assert fake_pool.calls == []
    assert _count_bg_jobs(test_user_id) == 0


def test_generic_route_async_flag_absent_defaults_synchronous(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    """No explicit env value at all (conftest's default) -> still synchronous."""
    monkeypatch.delenv("AETHER_ASYNC_GENERATION", raising=False)

    resp = client.post("/agents/compliance/run", json={}, headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert "job_id" not in resp.json()
    assert fake_pool.calls == []


# ===========================================================================
# (d) NO singleton (OQ-2) — concurrent enqueues for the same agent all accept
# ===========================================================================


def test_generic_route_no_singleton_two_sequential_enqueues_both_accepted(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    """Unlike scout's ``background=true`` (singleton=True, second POST reuses
    the FIRST job's id), the generic route makes NO single-run-per-agent claim
    (OQ-2): two POSTs for the same user+agent while the first is still
    ``enqueued`` are BOTH accepted, with DISTINCT job ids and DISTINCT
    BackgroundJob/AgentRun rows — mirroring how tailor/coverLetter behave."""
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    first = client.post("/agents/compliance/run", json={}, headers=auth_headers)
    second = client.post("/agents/compliance/run", json={}, headers=auth_headers)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    first_id, second_id = first.json()["job_id"], second.json()["job_id"]
    # The absence of the singleton-refusal/reuse shape MON-020 gives scout:
    # a genuinely SECOND job, not the first one handed back again.
    assert second_id != first_id
    assert _count_bg_jobs(test_user_id) == 2
    assert _count_agent_runs(test_user_id) == 2
    assert fake_pool.calls == [
        ("run_agent_job", first_id), ("run_agent_job", second_id),
    ], fake_pool.calls


def test_generic_route_no_singleton_concurrent_enqueues_all_202(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    def _enqueue(_i):
        r = client.post("/agents/compliance/run", json={}, headers=auth_headers)
        return r.status_code, r.json().get("job_id")

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_enqueue, range(5)))

    assert len(results) == 5
    assert all(status == 202 for status, _ in results), results
    job_ids = [jid for _, jid in results]
    assert len(set(job_ids)) == 5, "expected 5 DISTINCT jobs — singleton dedup fired"
    assert _count_bg_jobs(test_user_id) == 5


# ===========================================================================
# SCOPE item 3 — validation parity: 404 / 422 fire BEFORE any enqueue
# ===========================================================================


def test_generic_route_async_unknown_agent_still_404_before_enqueue(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    resp = client.post(
        "/agents/totally-bogus-agent-name/run", json={}, headers=auth_headers
    )

    assert resp.status_code == 404, resp.text
    assert fake_pool.calls == []
    assert _count_bg_jobs(test_user_id, "totally-bogus-agent-name") == 0


def test_generic_route_async_missing_required_param_still_422_before_enqueue(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    """``coverLetter`` (camelCase alias — NOT the dedicated ``/cover-letter/run``
    path, so this genuinely exercises the generic catch-all, exactly as
    ``test_ml_f1_f3_run_route_and_agent_list.py`` already does for the guard-
    rejection case) requires ``job_id``; omitting it must still 422 BEFORE
    anything is queued, exactly like the synchronous path does today."""
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")

    resp = client.post("/agents/coverLetter/run", json={}, headers=auth_headers)

    assert resp.status_code == 422, resp.text
    assert fake_pool.calls == []
    assert _count_bg_jobs(test_user_id, "coverLetter") == 0


# ===========================================================================
# SCOPE item 3 — quota reserved AT ENQUEUE for a METERED backend (R-2b: no
# skip_quota), through the GENERIC route specifically.
# ===========================================================================


def test_generic_route_async_reserves_quota_same_as_dedicated_routes(
    client, auth_headers, test_user_id, bg_table, fake_pool, monkeypatch
):
    from app.repositories.billing import UsageQuotaRepository

    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)

    def _run(self, *args, **kwargs):
        return {"contact_id": None, "drafted": False, "message": "no eligible contact"}

    monkeypatch.setattr(
        "app.agents.recruiter_outreach_agent.RecruiterOutreachAgent.run",
        _run, raising=True,
    )

    before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    # Reached via the GENERIC route with the hyphenated alias — not a
    # dedicated route — exactly the traffic shape probe 5 measured.
    resp = client.post(
        "/agents/recruiter-outreach/run", json={}, headers=auth_headers
    )
    assert resp.status_code == 202, resp.text
    after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    # Reserved at ENQUEUE, before any worker execution — same as
    # test_gap_p7_async_001.py::test_quota_reserved_at_enqueue_not_at_completion.
    assert after == before + 1
    job_id = resp.json()["job_id"]
    row = _get_bg_job(job_id)
    assert row["status"] == "enqueued"
    assert row["quotaReserved"] is True
    # Stored under the CANONICAL name (not the hyphenated alias), so the
    # worker's later _agent_callable(user_id, agentKey, params) call resolves
    # exactly like every other metered lookup in this file.
    assert row["agentKey"] == "recruiterOutreach"
