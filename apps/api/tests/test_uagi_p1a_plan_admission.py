"""U-AGI P1-A — ONE live run plan per user (ADR-AGI-3 risk hold R-1).

The silo class closes the per-BACKEND race: a second plan's ``scout`` /
``submission`` / … step loses the DB claim and refuses honestly. It does NOT
close the per-PLAN race, and that gap was disclosed by the build itself
(``BUILD-P1A.md`` open item #3): the 13 non-silo backends (fitScorer, matcher,
tailor, coverLetter, …) take no claim, so two rapid clicks or two browser tabs
produced two plans and up to 26 duplicate METERED dispatches from one user
action — the same "one unit of work asked for twice" that motivates the silo
class, at plan granularity.

ADR-AGI-3 R-1 says admission must be API-enforced AT THE DATABASE, not by a
disabled button in one browser tab, so these tests pin:

* a second plan is REFUSED (409) while the first is live — honestly, naming the
  live plan, leaving no second row, no second queue job, no second dispatch;
* the refusal is enforced by a partial UNIQUE INDEX, not only by application
  code, so two API processes cannot both pass the check;
* a terminal plan frees the slot immediately;
* a plan abandoned by a SIGKILLed worker is RELEASED after the same staleness
  window the job watchdog uses, so the lockout the build warned about in its
  own recommendation cannot happen — and a plan still inside that window is
  never released, because failing a live plan would fabricate a failure;
* one user's live plan never blocks another user's.
"""
from __future__ import annotations

import types
import uuid

import pytest

from app.db import get_connection
from app.repositories import run_plan as run_plan_mod
from app.repositories.billing import ensure_user_billing
from app.repositories.run_plan import RunPlanRepository
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
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=1000,'
                '"updatedAt"=now() WHERE "userId"=%s',
                ("pro", user_id),
            )
        conn.commit()


def _arm(monkeypatch, user_id: str) -> FakeArqPool:
    """Everything Run-everything needs to reach the admission seam."""
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_ORCH_PLAN_SPACING_SECONDS", "0")
    _set_paid_plan(user_id)
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)
    return fake


def _live_plan_ids(user_id: str) -> list[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "RunPlan" WHERE "userId"=%s '
                "AND \"status\" IN ('planned','running') ORDER BY \"createdAt\"",
                (user_id,),
            )
            return [r[0] for r in cur.fetchall()]


def _all_plan_rows(user_id: str) -> list[tuple]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","status","haltReason" FROM "RunPlan" WHERE "userId"=%s '
                'ORDER BY "createdAt"',
                (user_id,),
            )
            return list(cur.fetchall())


def _plan_job_count(user_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "BackgroundJob" WHERE "userId"=%s '
                'AND "agentKey"=%s',
                (user_id, agents_mod._ORCH_PLAN_AGENT_KEY),
            )
            return int(cur.fetchone()[0])


def _backdate(plan_id: str, seconds: int) -> None:
    """Push a plan's clocks back by DB-clock arithmetic (never app-clock)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "RunPlan" SET "createdAt"="createdAt" - make_interval(secs=>%s),'
                '"startedAt"=CASE WHEN "startedAt" IS NULL THEN NULL '
                'ELSE "startedAt" - make_interval(secs=>%s) END '
                'WHERE "id"=%s',
                (float(seconds), float(seconds), plan_id),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# The endpoint refuses the second plan.
# ---------------------------------------------------------------------------


def test_a_second_plan_is_refused_while_the_first_is_live(
    client, auth_headers, test_user_id, monkeypatch
):
    fake = _arm(monkeypatch, test_user_id)

    first = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert first.status_code == 202, first.text
    first_id = first.json()["planId"]

    second = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    # Honest AND actionable: it names the plan that is holding the slot, so the
    # user is sent to the run they already have instead of being told "no".
    assert detail["planId"] == first_id
    assert detail["error"] == "plan_already_running"
    assert "already" in detail["message"].lower()

    # The refusal left NO trace that could be mistaken for a second attempt.
    assert _live_plan_ids(test_user_id) == [first_id]
    assert len(fake.calls) == 1, "the refused plan must not enqueue a second job"
    assert _plan_job_count(test_user_id) == 1


def test_the_refused_plan_dispatches_nothing(
    client, auth_headers, test_user_id, monkeypatch
):
    """The whole point: 13 non-silo backends must not be metered twice."""
    _arm(monkeypatch, test_user_id)
    dispatched: list[str] = []
    monkeypatch.setattr(
        agents_mod,
        "_dispatch",
        lambda uid, backend, params: dispatched.append(backend) or {"run_id": "r"},
        raising=True,
    )
    assert (
        client.post(
            "/agents/orchestration/run-everything", headers=auth_headers
        ).status_code
        == 202
    )
    before = client.get("/agents/runs", headers=auth_headers).json()
    assert (
        client.post(
            "/agents/orchestration/run-everything", headers=auth_headers
        ).status_code
        == 409
    )
    assert dispatched == []
    after = client.get("/agents/runs", headers=auth_headers).json()
    assert len(after) == len(before), "a refused plan records no run"


def test_a_running_plan_holds_the_slot_too(
    client, auth_headers, test_user_id, monkeypatch
):
    """``planned`` → ``running`` is the worker picking the plan up; the slot is
    held across that transition, not released by it."""
    _arm(monkeypatch, test_user_id)
    plan_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]
    assert RunPlanRepository().mark_running(plan_id) is True

    second = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["planId"] == plan_id


@pytest.mark.parametrize("terminal", ["completed", "partial", "halted", "failed"])
def test_a_finished_plan_frees_the_slot(
    client, auth_headers, test_user_id, monkeypatch, terminal
):
    """No lockout after a plan ENDS — in any of its four terminal states."""
    _arm(monkeypatch, test_user_id)
    plan_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]
    assert RunPlanRepository().finish(plan_id, terminal, summary={"status": terminal})

    again = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert again.status_code == 202, again.text
    assert again.json()["planId"] != plan_id


def test_a_live_plan_never_blocks_another_user(
    client, auth_headers, test_user_id, monkeypatch
):
    _arm(monkeypatch, test_user_id)
    assert (
        client.post(
            "/agents/orchestration/run-everything", headers=auth_headers
        ).status_code
        == 202
    )

    credentials = {
        "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup3rSecret",
    }
    assert client.post("/auth/register", json=credentials).status_code == 201
    login = client.post("/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    other_id = client.get("/auth/me", headers=other_headers).json()["id"]
    _set_paid_plan(other_id)

    res = client.post("/agents/orchestration/run-everything", headers=other_headers)
    assert res.status_code == 202, res.text


# ---------------------------------------------------------------------------
# Staleness release — the lockout the build's own recommendation warned about.
# ---------------------------------------------------------------------------


def test_a_plan_abandoned_by_a_dead_worker_is_released_honestly(
    client, auth_headers, test_user_id, monkeypatch
):
    """A SIGKILLed worker leaves a ``running`` plan forever. Without a release
    the user is locked out of Run-everything with no way back."""
    _arm(monkeypatch, test_user_id)
    dead_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]
    assert RunPlanRepository().mark_running(dead_id) is True
    _backdate(dead_id, 172_800)  # two days — past any configured window

    res = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert res.status_code == 202, res.text

    rows = {r[0]: (r[1], r[2]) for r in _all_plan_rows(test_user_id)}
    status_v, halt_reason = rows[dead_id]
    # Released, not deleted, and it says WHY — a plan row is the only record
    # that the run ever existed.
    assert status_v == "failed"
    assert halt_reason and "worker" in halt_reason.lower()
    assert _live_plan_ids(test_user_id) == [res.json()["planId"]]


def test_a_live_plan_inside_its_window_is_never_released(
    client, auth_headers, test_user_id, monkeypatch
):
    """The mirror image, and the more dangerous direction: releasing a plan a
    worker is still executing would fabricate a failure AND let the same 19
    dispatches run twice."""
    _arm(monkeypatch, test_user_id)
    plan_id = client.post(
        "/agents/orchestration/run-everything", headers=auth_headers
    ).json()["planId"]
    assert RunPlanRepository().mark_running(plan_id) is True
    _backdate(plan_id, 30)  # 30s into a run — nowhere near the ceiling

    second = client.post("/agents/orchestration/run-everything", headers=auth_headers)
    assert second.status_code == 409
    rows = {r[0]: r[1] for r in _all_plan_rows(test_user_id)}
    assert rows[plan_id] == "running", "a live plan must not be failed by the release"


def test_the_staleness_window_is_the_workers_own_ceiling(monkeypatch):
    """Not a new magic number: the release reuses the SAME two windows the job
    watchdog derives from the worker's per-job execution ceiling, so the two can
    never drift into failing plans that are still legitimately running."""
    monkeypatch.setenv("AETHER_WORKER_JOB_TIMEOUT_SECONDS", "600")
    monkeypatch.delenv("AETHER_JOB_PROCESSING_STALE_SECONDS", raising=False)
    monkeypatch.setenv("AETHER_JOB_STALE_SECONDS", "900")
    assert agents_mod._plan_stale_thresholds() == agents_mod._job_stale_thresholds()
    assert agents_mod._plan_stale_thresholds()[1] >= 600


# ---------------------------------------------------------------------------
# The database, not the application, is the guarantee (R-1).
# ---------------------------------------------------------------------------


def _finish_duplicate_live_plans() -> int:
    """Shared-schema hygiene: leave at most ONE live plan per user.

    ``RunPlan`` is created lazily and is NOT in conftest's truncation set, so
    rows survive between tests — including any pair written by a tree that
    predates this admission guard (the fail-before capture writes exactly such a
    pair). The partial unique index cannot be created while a violation exists,
    which is precisely the degraded state ``_ensure_admission_index`` logs and
    then retries out of, so these tests state that precondition explicitly
    rather than depending on the order they happen to run in. Returns the number
    of duplicates closed — asserted to be irrelevant, never assumed to be zero.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE "RunPlan" SET "status"='failed',
                       "haltReason"='closed by the test suite: duplicate live plan',
                       "finishedAt"=now(),"updatedAt"=now()
                 WHERE "id" IN (
                       SELECT "id" FROM (
                           SELECT "id", row_number() OVER (
                               PARTITION BY "userId" ORDER BY "createdAt"
                           ) AS rn
                             FROM "RunPlan" WHERE "status" IN ('planned','running')
                       ) ranked WHERE rn > 1)
                RETURNING "id"
                """
            )
            closed = len(cur.fetchall())
        conn.commit()
    return closed


def test_the_admission_index_is_added_once_the_duplicates_are_resolved(client):
    """A database that already collected duplicates rejects the index. That must
    degrade (advisory lock still holds) and then SELF-HEAL — not stay unindexed
    until every worker is restarted."""
    run_plan_mod._reset_ready_for_tests()
    run_plan_mod._ensure_table()
    _finish_duplicate_live_plans()
    run_plan_mod._ensure_admission_index()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
                (run_plan_mod.RUN_PLAN_ACTIVE_INDEX,),
            )
            row = cur.fetchone()
    assert row is not None, "the index must exist once nothing violates it"
    indexdef = row[0]
    assert "UNIQUE" in indexdef
    assert '"userId"' in indexdef
    # Constrains LIVE plans only — plan history stays unbounded.
    assert "planned" in indexdef and "running" in indexdef


def test_a_partial_unique_index_enforces_one_live_plan_per_user(client):
    """Two API processes cannot both pass an application-level check. This is
    the half that makes the refusal atomic across them."""
    import psycopg2

    run_plan_mod._reset_ready_for_tests()
    run_plan_mod._ensure_table()
    _finish_duplicate_live_plans()
    run_plan_mod._ensure_admission_index()
    repo = RunPlanRepository()
    user_id = f"admission-{uuid.uuid4().hex[:12]}"
    first, created = repo.create_admitted(
        user_id,
        steps=[{"key": "fitScorer", "coversCards": []}],
        concurrency=1,
        spacing_seconds=0.0,
        planned_stale_seconds=900.0,
        running_stale_seconds=900.0,
    )
    assert created is True

    with pytest.raises(psycopg2.errors.UniqueViolation):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "RunPlan" ("id","userId","status","steps") '
                    "VALUES (%s,%s,'planned','[]'::jsonb)",
                    (f"raw-{uuid.uuid4().hex[:8]}", user_id),
                )
            conn.commit()

    assert repo.finish(first, "completed", summary={"status": "completed"})
    # …and the index constrains only LIVE plans: history is unbounded.
    second, created_again = repo.create_admitted(
        user_id,
        steps=[{"key": "fitScorer", "coversCards": []}],
        concurrency=1,
        spacing_seconds=0.0,
        planned_stale_seconds=900.0,
        running_stale_seconds=900.0,
    )
    assert created_again is True and second != first


def test_create_admitted_returns_the_live_plan_instead_of_inserting(client):
    """Mirrors ``BackgroundJobRepository.create_singleton``: ``created`` is True
    only when THIS call inserted the row, and the id that comes back is always a
    real plan the caller may report on."""
    run_plan_mod._reset_ready_for_tests()
    repo = RunPlanRepository()
    user_id = f"admission-{uuid.uuid4().hex[:12]}"
    kwargs = dict(
        steps=[{"key": "matcher", "coversCards": []}],
        concurrency=1,
        spacing_seconds=0.0,
        planned_stale_seconds=900.0,
        running_stale_seconds=900.0,
    )
    first, created = repo.create_admitted(user_id, **kwargs)
    again, created_again = repo.create_admitted(user_id, **kwargs)
    assert created is True
    assert created_again is False
    assert again == first
    assert len(_live_plan_ids(user_id)) == 1


def test_there_is_no_unguarded_way_to_create_a_plan():
    """The guard is only real if it cannot be walked around. A second public
    creator on this repository would let the next caller re-open the race."""
    repo = RunPlanRepository()
    assert not hasattr(repo, "create"), (
        "the unguarded INSERT must not survive alongside the admitted one"
    )
