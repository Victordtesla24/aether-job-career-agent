"""MON-020 — the Jobs "Sync" button 524s behind Cloudflare (TDD fail-before).

USER-REPORTED (MONITORING-LEDGER.md row MON-020, 2026-08-13 23:06Z): the Jobs
screen's Sync button POSTs ``/agents/scout/run``, which executes the whole
discovery pass INSIDE the request. Cloudflare gives up at ~100s and returns its
own HTML error page, which the frontend then rendered verbatim.

Measured evidence for "the run is genuinely long", from the production
discovery cron's own log (``/var/log/aether/discovery.log``, 1318 scout runs;
extraction = wall time between each ``scout run:`` line and its ``scout:``
result line):

    p50 36s, recent-window runs 255-473s, MAX 968s

So no amount of proxy tuning makes a synchronous scout survivable: the run has
to leave the request path.

TARGET CONTRACT asserted here (fails against ``origin/main``):

1. ``POST /agents/scout/run?background=true`` ENQUEUES onto the existing ARQ
   ``run_agent_job`` machinery and returns 202 + ``{"job_id", "status":
   "enqueued"}`` WITHOUT executing the scout in the request path.
2. That job is readable through the EXISTING poll route
   ``GET /agents/jobs/{job_id}`` (owner-scoped), so the frontend can poll with
   the resolver it already has (``lib/api/agents.ts:resolveRun``).
3. The worker executes it to a terminal ``completed`` carrying the real scout
   result — same ``_agent_callable`` path the synchronous route uses.
4. REGRESSION GUARD: the DEFAULT (no query param) call stays SYNCHRONOUS and
   returns the unchanged ``{"status": "accepted", persisted, updated, errors,
   per_source}`` body, because ``scripts/discovery_cron.sh`` depends on scout
   having FINISHED before it calls ``/agents/fit-scorer/run`` on the next line.
   Breaking that silently breaks scheduled discovery for every user.
5. A background scout must be allowed to run for as long as the measured worst
   case, and the lazy stale watchdog must not fabricate a "timed out" failure
   for a job the worker is still legitimately permitted to be executing.

Redis-free strategy is inherited from ``test_gap_p7_async_001.py``: the ARQ pool
is a ``FakeArqPool`` injected at the ``agents._get_arq_pool`` seam, and the
worker task is invoked directly. No broker is touched.
"""
from __future__ import annotations

import asyncio
import json
import types
import uuid

import pytest

from app.db import get_connection
from app.routers import agents as agents_mod
from tests.conftest import seed_search_target

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

#: The real shape ``ScoutAgent.run`` returns, as consumed by ``run_scout``.
_SCOUT_OUTPUT = {
    "persisted": 3,
    "updated": 1,
    "errors": [],
    "per_source": [
        {
            "source": "adzuna",
            "fetched": 4,
            "persisted": 3,
            "updated": 1,
            "error": None,
            "status": "ok",
        }
    ],
}


class FakeArqPool:
    """In-memory stand-in for the ARQ Redis pool (no broker)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append((function_name, *args))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


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


@pytest.fixture()
def fake_pool(monkeypatch):
    pool = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: pool, raising=True)
    return pool


def _paid(user_id: str) -> None:
    """ACTIVE PAID subscription so the entitlement gate is not what we measure."""
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                ("pro", "active", user_id),
            )
        conn.commit()


def _stub_scout(monkeypatch, calls: list) -> None:
    """Replace ScoutAgent.run with a recorder returning a real-shaped result."""

    def _run(self, *args, **kwargs):
        calls.append((args, kwargs))
        return dict(_SCOUT_OUTPUT)

    monkeypatch.setattr("app.agents.scout_agent.ScoutAgent.run", _run, raising=True)


def _get_bg_job(job_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","userId","agentKey","status","result","error","params" '
                'FROM "BackgroundJob" WHERE "id"=%s',
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


# ---------------------------------------------------------------------------
# 1) Background mode: 202 + job_id, nothing executed in the request path
# ---------------------------------------------------------------------------


def test_background_scout_returns_202_enqueue_envelope(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """The Sync path must return an enqueue envelope, not a 300-600s response."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    resp = client.post(
        "/agents/scout/run?background=true",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "enqueued", body
    assert isinstance(body.get("job_id"), str) and body["job_id"], body
    # The scout itself must NOT have run inside the request — that is the whole
    # point of the fix (a run in-request is exactly what Cloudflare 524s on).
    assert scout_calls == [], "scout executed synchronously in background mode"
    # It went onto the EXISTING queue machinery, addressed to run_agent_job.
    assert fake_pool.calls == [("run_agent_job", body["job_id"])], fake_pool.calls
    job = _get_bg_job(body["job_id"])
    assert job["agentKey"] == "scout"
    assert job["status"] == "enqueued"
    # The resolved target is persisted with the job, so the worker searches the
    # user's REAL target rather than re-deriving (or fabricating) one.
    assert job["params"]["query"] == "Delivery Lead"
    assert job["params"]["location"] == "Melbourne, AU"


def test_background_scout_job_is_pollable_by_owner_only(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """The frontend polls the EXISTING GET /agents/jobs/{id} route."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    _stub_scout(monkeypatch, [])

    job_id = client.post(
        "/agents/scout/run?background=true",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    ).json()["job_id"]

    poll = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert poll.status_code == 200, poll.text
    payload = poll.json()
    assert payload["job_id"] == job_id
    assert payload["status"] in ("enqueued", "processing")
    assert payload["agentKey"] == "scout"

    # A different signed-in user must not be able to read it.
    other = {"email": f"mon020-{uuid.uuid4().hex[:8]}@example.com",
             "password": "Sup3rSecret"}
    assert client.post("/auth/register", json=other).status_code in (201, 409)
    other_headers = {
        "Authorization": "Bearer "
        + client.post("/auth/login", json=other).json()["access_token"]
    }
    assert client.get(f"/agents/jobs/{job_id}", headers=other_headers).status_code == 404


def test_background_scout_completes_through_the_worker(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """The enqueued job runs the REAL scout callable and lands its real result."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    job_id = client.post(
        "/agents/scout/run?background=true",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    ).json()["job_id"]

    from app.workers.tasks import run_agent_job

    asyncio.run(run_agent_job({}, job_id))

    assert len(scout_calls) == 1, "worker did not execute the scout exactly once"
    job = _get_bg_job(job_id)
    assert job["status"] == "completed", job
    assert job["error"] is None
    assert job["result"]["persisted"] == 3
    assert job["result"]["per_source"][0]["source"] == "adzuna"

    poll = client.get(f"/agents/jobs/{job_id}", headers=auth_headers).json()
    assert poll["status"] == "completed"
    assert poll["result"]["persisted"] == 3


# ---------------------------------------------------------------------------
# 2) Regression guard: the discovery cron's synchronous contract is untouched
# ---------------------------------------------------------------------------


def test_default_scout_run_stays_synchronous_for_the_discovery_cron(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """``scripts/discovery_cron.sh`` POSTs with NO query param and then calls
    ``/agents/fit-scorer/run`` on the very next line, so scout must have already
    finished and reported its real counts. Nothing here may become async."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    resp = client.post(
        "/agents/scout/run",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body == {
        "status": "accepted",
        "persisted": 3,
        "updated": 1,
        "errors": [],
        "per_source": _SCOUT_OUTPUT["per_source"],
    }, body
    assert "job_id" not in body
    assert len(scout_calls) == 1, "the default call must run the scout in-request"
    assert fake_pool.calls == [], "the default call must not enqueue"


def test_explicit_background_false_is_also_synchronous(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    resp = client.post(
        "/agents/scout/run?background=false",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "accepted"
    assert len(scout_calls) == 1
    assert fake_pool.calls == []


# ---------------------------------------------------------------------------
# 3) A background scout is allowed to take as long as it really takes
# ---------------------------------------------------------------------------


def test_worker_timeout_covers_the_measured_worst_case_scout_run():
    """ARQ must not kill a scout that is merely slow.

    Bound comes from production measurement, not a guess: the discovery cron's
    log records a 968s scout run (see module docstring). A ceiling below that
    would turn a genuinely-successful discovery into a killed job."""
    from app.workers.settings import WorkerSettings

    assert WorkerSettings.job_timeout >= 1000, (
        "worker job_timeout must cover the measured 968s worst-case scout run"
    )


def test_stale_watchdog_never_fails_a_job_the_worker_may_still_be_running():
    """The lazy ``processing`` staleness window must sit ABOVE the worker's own
    execution ceiling. Otherwise a long-but-healthy run is marked
    "generation timed out (worker unavailable)" while the worker is still
    working on it — a fabricated failure, and (for a metered agent) a refund of
    a run that then completes."""
    from app.routers.agents import _job_stale_thresholds
    from app.workers.settings import WorkerSettings

    _enqueued, processing = _job_stale_thresholds()
    assert processing > WorkerSettings.job_timeout, (
        f"processing staleness window {processing}s must exceed the worker "
        f"job_timeout {WorkerSettings.job_timeout}s"
    )


def test_scout_stale_window_is_operator_tunable(monkeypatch):
    """Both windows stay env-driven (no baked-in constant)."""
    from app.routers.agents import _job_stale_thresholds

    monkeypatch.setenv("AETHER_JOB_STALE_SECONDS", "1234")
    monkeypatch.setenv("AETHER_JOB_PROCESSING_STALE_SECONDS", "4321")
    assert _job_stale_thresholds() == (1234, 4321)


# ---------------------------------------------------------------------------
# 4) Honest failure: a queue outage is a real 503, never a silent success
# ---------------------------------------------------------------------------


def test_background_scout_reports_queue_outage_honestly(
    client, auth_headers, bg_table, monkeypatch
):
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    class DeadPool:
        async def enqueue_job(self, *args, **kwargs):
            raise RuntimeError("redis down")

    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: DeadPool(), raising=True)

    resp = client.post(
        "/agents/scout/run?background=true",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    )
    assert resp.status_code == 503, resp.text
    assert "queue" in resp.json()["detail"].lower()
    # Never silently fell back to the synchronous 300-600s path.
    assert scout_calls == []
