"""RT-008 — event-driven agent trigger + non-stop sweep until pipeline empty.

Operator mandate: the discovery cron runs scout → fit-scorer synchronously,
but the board sweep that consumes the freshly-scored jobs runs on a SEPARATE
10-minute ARQ cron — so a user whose jobs just landed could wait up to 10
minutes before any tailoring / cover work starts. These tests pin the
event-driven trigger that closes that latency gap:

1. ``enqueue_user_sweep`` — the best-effort, idempotent ARQ enqueue seam that
   reuses the cron's ``_job_id`` dedup (an event trigger racing the cron can
   never stack a second concurrent sweep for the same user).
2. ``POST /agents/board-sweep/trigger`` — the explicit operator endpoint.
3. The auto-trigger fired inside ``run_fit_scorer`` when ``scored > 0``.

The sweep's own ``sweep_user_stretch`` (the "non-stop sweep until pipeline
empty" half of the mandate) is already covered by the RT-007 suite; these
tests pin only the EVENT-DRIVEN TRIGGER wiring.
"""
from __future__ import annotations

import types
import uuid

import pytest

from app.workers import board_sweep


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_scored_job(conn, user_id: str) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ('
            '"id","userId","title","company","description","source","sourceUrl",'
            '"status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, user_id, "Engineer", "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", "screening", 80.0),
        )
    conn.commit()
    return job_id


class _FakePool:
    """In-memory ARQ pool stand-in recording ``enqueue_job`` calls."""

    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append(((function_name, *args), dict(kwargs)))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


# ---------------------------------------------------------------------------
# enqueue_user_sweep seam
# ---------------------------------------------------------------------------


class TestEnqueueUserSweep:
    def test_enqueues_when_enabled_and_board_has_work(
        self, db_session, user_id, monkeypatch
    ):
        _seed_scored_job(db_session, user_id)
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        fake = _FakePool()
        monkeypatch.setattr(
            "app.workers.queue.get_arq_pool", lambda: fake, raising=True
        )
        job_id = board_sweep.enqueue_user_sweep(user_id)
        assert job_id is not None and job_id.startswith("fake-arq-")
        assert len(fake.calls) == 1
        (fn, uid), kw = fake.calls[0]
        assert fn == "board_sweep_user" and uid == user_id
        # Reuses the cron's idempotent _job_id dedup — never stacks a 2nd sweep.
        assert kw["_job_id"] == f"board-sweep:{user_id}"

    def test_noop_when_disabled(self, db_session, user_id, monkeypatch):
        _seed_scored_job(db_session, user_id)
        monkeypatch.delenv("AETHER_BOARD_SWEEP_ENABLED", raising=False)

        def _fail(*a, **k):  # pragma: no cover — must not be called
            pytest.fail("disabled trigger must not enqueue")

        monkeypatch.setattr("app.workers.queue.get_arq_pool", _fail, raising=True)
        assert board_sweep.enqueue_user_sweep(user_id) is None

    def test_noop_when_no_board_work(self, user_id, monkeypatch):
        # User has no jobs at all — nothing actionable.
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")

        def _fail(*a, **k):  # pragma: no cover — must not be called
            pytest.fail("trigger must not enqueue for an empty board")

        monkeypatch.setattr("app.workers.queue.get_arq_pool", _fail, raising=True)
        assert board_sweep.enqueue_user_sweep(user_id) is None

    def test_enqueue_failure_is_best_effort(self, db_session, user_id, monkeypatch):
        _seed_scored_job(db_session, user_id)
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")

        def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr("app.workers.queue.get_arq_pool", _boom, raising=True)
        # Must NOT raise — the cron is the floor; a transient outage is logged.
        assert board_sweep.enqueue_user_sweep(user_id) is None

    def test_dedup_returns_none(self, db_session, user_id, monkeypatch):
        """When ARQ dedups (job already queued/running) ``enqueue_job`` returns
        None — the trigger surfaces that honestly without raising."""
        _seed_scored_job(db_session, user_id)
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")

        class _DedupPool:
            async def enqueue_job(self, *a, **k):
                return None  # ARQ already has this _job_id in flight

        monkeypatch.setattr(
            "app.workers.queue.get_arq_pool", lambda: _DedupPool(), raising=True
        )
        assert board_sweep.enqueue_user_sweep(user_id) is None


# ---------------------------------------------------------------------------
# user_has_board_work helper
# ---------------------------------------------------------------------------


class TestUserHasBoardWork:
    def test_true_when_scored_job_without_application(self, db_session, user_id):
        _seed_scored_job(db_session, user_id)
        assert board_sweep.user_has_board_work(user_id) is True

    def test_false_when_no_jobs(self, user_id):
        assert board_sweep.user_has_board_work(user_id) is False

    def test_false_when_job_has_application(self, db_session, user_id):
        import json

        job_id = _seed_scored_job(db_session, user_id)
        app_id, resume_id = _uid(), _uid()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "Resume" ("id","userId","version","sections",'
                '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
                (resume_id, user_id, json.dumps({"summary": "t"}), "hash-t"),
            )
            cur.execute(
                'INSERT INTO "Application" ("id","userId","jobId","resumeId",'
                '"status","createdAt","updatedAt") VALUES (%s,%s,%s,%s,'
                "%s::\"ApplicationStatus\",NOW(),NOW())",
                (app_id, user_id, job_id, resume_id, "draft"),
            )
        db_session.commit()
        assert board_sweep.user_has_board_work(user_id) is False


# ---------------------------------------------------------------------------
# POST /agents/board-sweep/trigger endpoint
# ---------------------------------------------------------------------------


class TestTriggerEndpoint:
    def test_skipped_when_disabled(self, client, auth_headers, monkeypatch):
        monkeypatch.delenv("AETHER_BOARD_SWEEP_ENABLED", raising=False)
        resp = client.post("/agents/board-sweep/trigger", headers=auth_headers)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "skipped"
        assert "disabled" in body["reason"]

    def test_enqueues_when_enabled(self, client, auth_headers, db_session, monkeypatch):
        # Seed a scored job for the authenticated user so board work exists.
        from app.security import decode_access_token
        token = auth_headers["Authorization"].removeprefix("Bearer ")
        uid = decode_access_token(token)["userId"]
        _seed_scored_job(db_session, uid)

        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        fake = _FakePool()
        monkeypatch.setattr(
            "app.workers.queue.get_arq_pool", lambda: fake, raising=True
        )
        resp = client.post("/agents/board-sweep/trigger", headers=auth_headers)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "enqueued"
        assert body["job_id"].startswith("fake-arq-")
        assert len(fake.calls) == 1

    def test_skipped_when_no_board_work(self, client, auth_headers, monkeypatch):
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        resp = client.post("/agents/board-sweep/trigger", headers=auth_headers)
        assert resp.status_code == 202
        assert resp.json()["status"] == "skipped"


# ---------------------------------------------------------------------------
# Auto-trigger inside run_fit_scorer
# ---------------------------------------------------------------------------


class TestFitScorerAutoTrigger:
    def test_fit_scorer_enqueues_sweep_when_jobs_scored(
        self, client, auth_headers, db_session, monkeypatch
    ):
        """The fit-scorer endpoint auto-enqueues a board sweep when it scores
        jobs — the event that creates board work. Mocks the fit-scorer agent
        so the test does not depend on a live LLM / resume."""
        from app.security import decode_access_token
        token = auth_headers["Authorization"].removeprefix("Bearer ")
        uid = decode_access_token(token)["userId"]

        # Patch the FitScorerAgent.run to return a scored result without
        # calling the LLM or requiring a resume.
        from app.agents.fit_scorer import FitScoreResult, FitScorerAgent

        monkeypatch.setattr(
            FitScorerAgent, "run",
            lambda self, user_id, rescore=False: FitScoreResult(scored=3),
        )
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")
        # Seed a board-work row so enqueue_user_sweep doesn't short-circuit.
        _seed_scored_job(db_session, uid)
        fake = _FakePool()
        monkeypatch.setattr(
            "app.workers.queue.get_arq_pool", lambda: fake, raising=True
        )

        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["scored"] == 3
        # The event-driven trigger enqueued exactly one sweep for this user.
        assert len(fake.calls) == 1
        (fn, u), kw = fake.calls[0]
        assert fn == "board_sweep_user" and u == uid
        assert kw["_job_id"] == f"board-sweep:{uid}"

    def test_fit_scorer_no_trigger_when_zero_scored(
        self, client, auth_headers, monkeypatch
    ):
        """When the fit-scorer scores zero jobs (nothing new), no sweep is
        enqueued — there's no new board work to consume."""
        from app.agents.fit_scorer import FitScoreResult, FitScorerAgent

        monkeypatch.setattr(
            FitScorerAgent, "run",
            lambda self, user_id, rescore=False: FitScoreResult(scored=0),
        )
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")

        def _fail(*a, **k):  # pragma: no cover — must not be called
            pytest.fail("zero-scored fit-scorer must not enqueue a sweep")

        monkeypatch.setattr("app.workers.queue.get_arq_pool", _fail, raising=True)
        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["scored"] == 0

    def test_fit_scorer_trigger_failure_does_not_taint_result(
        self, client, auth_headers, monkeypatch
    ):
        """A transient enqueue failure inside the auto-trigger must NOT crash
        the fit-scorer response — the cron is the floor."""
        from app.agents.fit_scorer import FitScoreResult, FitScorerAgent
        from app.security import decode_access_token

        token = auth_headers["Authorization"].removeprefix("Bearer ")
        uid = decode_access_token(token)["userId"]

        monkeypatch.setattr(
            FitScorerAgent, "run",
            lambda self, user_id, rescore=False: FitScoreResult(scored=2),
        )
        monkeypatch.setenv("AETHER_BOARD_SWEEP_ENABLED", "true")

        def _boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr("app.workers.queue.get_arq_pool", _boom, raising=True)
        resp = client.post("/agents/fit-scorer/run", headers=auth_headers)
        # Best-effort trigger: the honest fit-scorer result still returns 200.
        assert resp.status_code == 200
        assert resp.json()["scored"] == 2
