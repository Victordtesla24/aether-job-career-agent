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
import threading
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


# ---------------------------------------------------------------------------
# 5) Duplicate-run guard (round-2 review FAIL-1) — SERVER-SIDE, idempotent
#
# The round-1 fix made the enqueue cheap (<1s) and left the browser's
# `disabled={running}` flag as the ONLY protection against a second concurrent
# discovery pass. That flag is per-component state: it does not survive a
# second browser tab, and it does not cover the THREE independent buttons that
# now hit this endpoint (Jobs "Sync Now", Settings' "Sync All Job Boards", the
# Agents console's scout Run), let alone a direct POST or a double click landing
# inside the pre-guard `await`.
#
# CONTRACT asserted here: a POST for a user who already has an ACTIVE
# (enqueued/processing) scout job is IDEMPOTENT — 202 carrying the EXISTING
# job_id, one BackgroundJob row, one AgentRun audit row, one queue push. Not a
# 409: the caller's intent ("make sure discovery is running") is already
# satisfied, and the FE polls the returned id either way. The guard releases as
# soon as that job reaches a terminal state, and a job whose worker died is
# released by the SAME lazy watchdog GET /agents/jobs/{id} already applies, so
# a dead worker can never lock a user out of syncing.
# ---------------------------------------------------------------------------


def _count_bg_jobs(user_id: str, agent_key: str = "scout") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "BackgroundJob" '
                'WHERE "userId"=%s AND "agentKey"=%s',
                (user_id, agent_key),
            )
            return int(cur.fetchone()[0])


def _count_agent_runs(user_id: str, agent_name: str = "scout") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "AgentRun" WHERE "userId"=%s AND "agentName"=%s',
                (user_id, agent_name),
            )
            return int(cur.fetchone()[0])


def _backdate_processing(job_id: str, age_secs: int) -> None:
    """Put a job into ``processing`` started ``age_secs`` ago (dead worker)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "BackgroundJob" SET "status"=\'processing\','
                '"startedAt"=now() - make_interval(secs => %s),'
                '"createdAt"=now() - make_interval(secs => %s) WHERE "id"=%s',
                (age_secs, age_secs, job_id),
            )
        conn.commit()


def _second_paid_user(client) -> tuple[str, dict[str, str]]:
    """Register a SECOND real user (own profile + paid) — the guard must be
    scoped per user, never a global one-scout-at-a-time lock."""
    email = f"mon020-second-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "Sup3rSecret"}
    assert client.post("/auth/register", json=creds).status_code == 201
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    from app.db import ensure_user_profile_columns

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "User" SET "targetRole"=%s,"location"=%s WHERE id=%s',
                ("Delivery Lead", "Sydney, AU", user_id),
            )
        conn.commit()
    _paid(user_id)
    return user_id, headers


def _post_background_scout(client, headers):
    return client.post(
        "/agents/scout/run?background=true",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=headers,
    )


def test_double_post_background_scout_reuses_the_active_job(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """Two POSTs while one pass is still in flight = ONE run, same job_id."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    _stub_scout(monkeypatch, [])

    first = _post_background_scout(client, auth_headers)
    second = _post_background_scout(client, auth_headers)

    assert first.status_code == 202, first.text
    # Idempotent, NOT a 409: the caller asked for discovery to be running, and
    # it is — hand back the id of the run that is already doing it.
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] == first.json()["job_id"]
    assert _count_bg_jobs(user_id) == 1, "a second BackgroundJob row was created"
    assert _count_agent_runs(user_id) == 1, "a second AgentRun audit row was created"
    assert fake_pool.calls == [("run_agent_job", first.json()["job_id"])]


def test_scout_guard_releases_once_the_active_job_is_terminal(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """The guard is about CONCURRENCY, not a cooldown: once the run finishes,
    the very next Sync starts a genuinely new pass."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    _stub_scout(monkeypatch, [])
    from app.repositories.background_jobs import BackgroundJobRepository

    first_id = _post_background_scout(client, auth_headers).json()["job_id"]
    assert BackgroundJobRepository().mark_completed(first_id, dict(_SCOUT_OUTPUT))

    second = _post_background_scout(client, auth_headers)
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] != first_id
    assert _count_bg_jobs(user_id) == 2


def test_scout_guard_releases_a_job_whose_worker_died(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """A job stuck in ``processing`` past the staleness window must not lock the
    user out: the SAME lazy watchdog the poll route applies fails it (honestly)
    and the new Sync gets its own job."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    _stub_scout(monkeypatch, [])
    from app.routers.agents import _job_stale_thresholds

    first_id = _post_background_scout(client, auth_headers).json()["job_id"]
    _backdate_processing(first_id, _job_stale_thresholds()[1] + 60)

    second = _post_background_scout(client, auth_headers)
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] != first_id
    dead = _get_bg_job(first_id)
    assert dead["status"] == "failed"
    assert "timed out" in (dead["error"] or "")


def test_scout_guard_is_scoped_per_user(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """User B's Sync must never be answered with user A's job id."""
    user_a = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_a)
    _stub_scout(monkeypatch, [])
    user_b, headers_b = _second_paid_user(client)

    job_a = _post_background_scout(client, auth_headers).json()["job_id"]
    resp_b = _post_background_scout(client, headers_b)

    assert resp_b.status_code == 202, resp_b.text
    assert resp_b.json()["job_id"] != job_a
    assert _count_bg_jobs(user_a) == 1
    assert _count_bg_jobs(user_b) == 1


def test_active_scout_singleton_is_enforced_by_a_partial_unique_index(bg_table):
    """The lookup-then-create window is closed at the DB, not just in Python:
    an additive PARTIAL UNIQUE index makes a second ACTIVE scout row for the
    same user impossible even if two API processes race."""
    import psycopg2

    from app.repositories.background_jobs import (
        _ensure_table,
        _reset_bg_ready_for_tests,
    )

    _reset_bg_ready_for_tests()
    _ensure_table()
    user_id = f"idx-user-{uuid.uuid4().hex[:8]}"

    def _raw_insert(status: str, agent_key: str = "scout") -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "BackgroundJob" ("id","userId","agentKey","status") '
                    "VALUES (%s,%s,%s,%s)",
                    (uuid.uuid4().hex, user_id, agent_key, status),
                )
            conn.commit()

    _raw_insert("enqueued")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _raw_insert("processing")
    # …and the index is genuinely PARTIAL: it constrains only ACTIVE scout rows,
    # so history keeps accumulating and OTHER agents (tailor/coverLetter, which
    # legitimately run several at once) are untouched.
    _raw_insert("completed")
    _raw_insert("completed")
    _raw_insert("enqueued", agent_key="tailor")
    _raw_insert("processing", agent_key="tailor")
    assert _count_bg_jobs(user_id, "tailor") == 2


def test_create_singleton_survives_concurrent_callers(bg_table):
    """Same-millisecond double click across two API workers: exactly one job."""
    from app.repositories.background_jobs import (
        BackgroundJobRepository,
        _ensure_table,
        _reset_bg_ready_for_tests,
    )

    _reset_bg_ready_for_tests()
    _ensure_table()
    repo = BackgroundJobRepository()
    user_id = f"race-user-{uuid.uuid4().hex[:8]}"
    workers = 4
    barrier = threading.Barrier(workers)
    results: list[tuple[str, bool]] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _go() -> None:
        try:
            barrier.wait(timeout=20)
            outcome = repo.create_singleton(user_id, "scout", params={"query": "x"})
        except BaseException as exc:  # noqa: BLE001 — recorded, re-raised below
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_go) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent create_singleton raised: {errors}"
    assert len(results) == workers
    created = [job_id for job_id, was_created in results if was_created]
    assert len(created) == 1, f"expected exactly one creator, got {created}"
    assert {job_id for job_id, _ in results} == {created[0]}
    assert _count_bg_jobs(user_id) == 1


def test_active_background_job_never_blocks_the_synchronous_cron_path(
    client, auth_headers, bg_table, fake_pool, monkeypatch
):
    """The guard is scoped to the BACKGROUND transport.

    ``scripts/discovery_cron.sh`` POSTs the default (synchronous) route and
    fit-scores on the very next line. It is a different caller with different
    semantics — no BackgroundJob row, no queue — and refusing or deduplicating
    it because a user happens to have a browser sync in flight would silently
    break scheduled discovery. It must still run, in-request, to completion."""
    user_id = seed_search_target(
        client, auth_headers, target_role="Delivery Lead", location="Melbourne, AU"
    )
    _paid(user_id)
    scout_calls: list = []
    _stub_scout(monkeypatch, scout_calls)

    assert _post_background_scout(client, auth_headers).status_code == 202
    assert scout_calls == []

    sync = client.post(
        "/agents/scout/run",
        json={"query": "Delivery Lead", "location": "Melbourne, AU"},
        headers=auth_headers,
    )
    assert sync.status_code == 202, sync.text
    body = sync.json()
    assert body["status"] == "accepted", body
    assert body["persisted"] == _SCOUT_OUTPUT["persisted"]
    assert len(scout_calls) == 1, "the cron's synchronous pass did not run"
    # …and it created no second BackgroundJob row either.
    assert _count_bg_jobs(user_id) == 1


def test_create_singleton_refuses_an_agent_the_index_does_not_cover():
    """The Python guard and the partial unique index must cover the SAME agents.

    A caller who got an advisory-lock-only singleton for, say, ``tailor`` would
    believe in a guarantee the database is not enforcing (and would break the
    legitimate several-at-once semantics those agents need). Refuse loudly."""
    from app.repositories.background_jobs import BackgroundJobRepository

    with pytest.raises(ValueError, match="singleton"):
        BackgroundJobRepository().create_singleton(
            "some-user", "tailor", params={"job_id": "j1"}
        )
