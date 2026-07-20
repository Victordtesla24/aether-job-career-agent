"""GAP-P7-ASYNC-001 — async background generation (TDD fail-before).

These tests assert the TARGET contract from
``docs/delivery/PHASE7-ASYNC-BLUEPRINT.md`` (APPROVED, fable-5 2026-07-17). They
are written BEFORE the implementation, so every target-behaviour test FAILS
against the current synchronous code (endpoints return 200/503 in-request today;
the ``app.workers`` package and the enqueue/worker seams do not exist yet).

Redis-free strategy (blueprint §8): NO real Redis / ARQ broker is touched. The
enqueue path is exercised by injecting a ``FakeArqPool`` at a module-level seam;
the worker task is exercised by calling ``run_agent_job`` directly with a
hand-built ``ctx`` and a stubbed service callable. ``pytest.importorskip`` is
FORBIDDEN — the not-yet-existing symbols are imported/patched INSIDE each test
body so a missing seam records the test as FAILED (call phase), never as a
collection error that would skip the whole file.

Seam contract implemented in the fix phase (this same fixer):
- ``app.routers.agents._get_arq_pool()`` -> a pool whose
  ``async enqueue_job(func_name, *args)`` returns an object with ``.job_id``.
  The sync ``def`` run handlers obtain the pool via this indirection (so tests
  patch ``agents._get_arq_pool``) when ``AETHER_ASYNC_GENERATION`` is truthy.
- ``app.routers.agents._agent_callable(user_id, name, params) -> (name, fn)`` —
  the pure agent->callable mapping shared by BOTH the sync path and the worker
  (blueprint §4.1: no logic duplication).
- ``app.workers.tasks.run_agent_job(ctx, job_id)`` — the ARQ task body
  (blueprint §4.3), plus ``app.workers.tasks._run_pipeline_body(user_id, params)``
  for the composite pipeline (per-step reserve/refund + crash refund, §3.2/§7.4).
- Status route ``GET /agents/jobs/{job_id}`` (blueprint §3.1 — NOT ``/jobs/{id}``,
  which collides with the job-postings router). Mounted under ``/agents`` in the
  TestClient; nginx adds the public ``/api`` prefix in production.
- ``BackgroundJob`` table (blueprint §2) — created here IF NOT EXISTS in the
  ``aether_test`` schema only (additive, test-scoped) by the ``bg_table`` fixture.

Epistemic tag: [INFERRED-FROM-PROMPT] — the seam names above are the fixer's
contract, chosen to match the blueprint sketch; the fix phase wires them exactly.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import types
import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import (
    UsageQuotaRepository,
    ensure_user_billing,
)
from app.routers import agents as agents_mod

# ---------------------------------------------------------------------------
# Blueprint §2 DDL — additive only, test schema only (IF NOT EXISTS).
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
    'CREATE INDEX IF NOT EXISTS "BackgroundJob_userId_createdAt_idx" '
    'ON "BackgroundJob" ("userId", "createdAt" DESC)',
    'CREATE INDEX IF NOT EXISTS "BackgroundJob_status_idx" '
    'ON "BackgroundJob" ("status")',
)

#: Lowercased markers that must NEVER appear in a failed job's error/result —
#: a failure emits an honest error only, never recorded fixture content
#: (blueprint §9 / §4.3; mirrors the authenticity fixture guard).
_FIXTURE_FINGERPRINTS = (
    "stale fixture content",
    "acme corp",
    "jordan rivera",
    "lorem ipsum",
    "placeholder",
    "fixture",
    "sample resume",
    "todo",
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _model_env(monkeypatch):
    # Metered agents resolve a model for cost computation; pin it so the
    # quota/spend path is deterministic (mirrors test_gap_p6_billing).
    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    monkeypatch.setenv("AETHER_MODEL_STRUCTURED", "claude-haiku-4-5")


@pytest.fixture()
def bg_table(client):
    """Ensure the additive ``BackgroundJob`` table exists (test schema) and is
    empty for the test. Depends on ``client`` so the standard per-test TRUNCATE
    (which wipes ``User``) runs first; then we clean the append-only job table."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            for stmt in _BACKGROUND_JOB_DDL:
                cur.execute(stmt)
            cur.execute('TRUNCATE TABLE "BackgroundJob"')
        conn.commit()
    return True


class FakeArqPool:
    """In-memory stand-in for the ARQ Redis pool (no broker). Records every
    ``enqueue_job`` call and returns a fake job carrying a ``job_id``."""

    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    async def enqueue_job(self, function_name, *args, **kwargs):
        self.calls.append(((function_name, *args), dict(kwargs)))
        return types.SimpleNamespace(job_id="fake-arq-" + uuid.uuid4().hex[:10])


def _set_paid_plan(user_id: str) -> None:
    """Give the user an ACTIVE PAID (pro) subscription with headroom so the
    entitlement gate passes and a reserve has a ceiling to count against."""
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


def _stub_tailor(monkeypatch, *, raises: Exception | None = None):
    """Replace TailoringAgent.run so the sync/worker execution is deterministic
    (a clean tailored payload, or a raised failure to exercise refund paths)."""

    def _run(self, *args, **kwargs):
        if raises is not None:
            raise raises
        return {
            "resume_id": "r1",
            "changes": [],
            "rejected": [],
            "conversionMetrics": {"before": 0.0, "after": 0.0},
        }

    monkeypatch.setattr(
        "app.agents.tailor_agent.TailoringAgent.run", _run, raising=True
    )


def _seed_bg_job(
    user_id: str,
    agent_key: str,
    *,
    status: str = "enqueued",
    run_id: str | None = None,
    params: dict | None = None,
    quota_reserved: bool = False,
    result: dict | None = None,
    error: str | None = None,
) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "BackgroundJob" '
                '("id","userId","agentKey","runId","params","status",'
                '"quotaReserved","result","error") '
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s)",
                (
                    job_id,
                    user_id,
                    agent_key,
                    run_id,
                    json.dumps(params) if params is not None else None,
                    status,
                    quota_reserved,
                    json.dumps(result) if result is not None else None,
                    error,
                ),
            )
        conn.commit()
    return job_id


def _get_bg_job(job_id: str) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id","userId","agentKey","status","result","error",'
                '"quotaReserved","finishedAt" FROM "BackgroundJob" WHERE "id"=%s',
                (job_id,),
            )
            row = cur.fetchone()
            cols = [c.name for c in cur.description]
    if row is None:
        raise AssertionError(f"BackgroundJob {job_id} not found")
    rec = dict(zip(cols, row))
    if isinstance(rec.get("result"), str):
        rec["result"] = json.loads(rec["result"])
    return rec


def _count_bg_jobs(user_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "BackgroundJob" WHERE "userId"=%s', (user_id,)
            )
            return int(cur.fetchone()[0])


def _register_user(client) -> tuple[dict, str]:
    """Register + login a fresh second user; return (auth_headers, user_id)."""
    email = f"p7async-{uuid.uuid4().hex[:8]}@example.com"
    creds = {"email": email, "password": "Sup3rSecret"}
    reg = client.post("/auth/register", json=creds)
    assert reg.status_code in (201, 409), reg.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _no_fingerprint(text: str | None) -> bool:
    if not text:
        return True
    low = text.lower()
    return not any(fp in low for fp in _FIXTURE_FINGERPRINTS)


# ===========================================================================
# 1) Enqueue endpoints -> 202 when the async flag is ON (FakeArqPool)
# ===========================================================================


def test_tailor_run_returns_202_when_flag_on(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)
    _stub_tailor(monkeypatch)
    fake = FakeArqPool()
    # Seam absent today -> AttributeError here -> test FAILED (fail-before).
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    r = client.post("/agents/tailor/run", json={"job_id": "job-1"}, headers=auth_headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert isinstance(body.get("job_id"), str) and body["job_id"]
    assert body.get("status") == "enqueued"
    assert fake.calls, "expected the tailor run to be enqueued to the ARQ pool"


def test_pipeline_run_returns_202_when_flag_on(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    r = client.post(
        "/agents/pipeline/run",
        json={"query": "backend engineer", "location": "Remote"},
        headers=auth_headers,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert isinstance(body.get("job_id"), str) and body["job_id"]
    assert body.get("status") == "enqueued"
    assert fake.calls, "expected the pipeline run to be enqueued to the ARQ pool"


# ===========================================================================
# 2) Flag OFF preserves the synchronous behaviour (backward-compat guard).
#    This is NOT a target-async test — it passes both before and after.
# ===========================================================================


def test_flag_off_preserves_synchronous_behavior(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "false")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)
    _stub_tailor(monkeypatch)

    r = client.post("/agents/tailor/run", json={"job_id": "job-1"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("resume_id") == "r1"
    assert "job_id" not in body  # legacy synchronous shape, no enqueue envelope
    assert _count_bg_jobs(test_user_id) == 0  # nothing queued


# ===========================================================================
# 3) Status polling endpoint GET /agents/jobs/{id}
# ===========================================================================


def test_job_status_polling_transitions_enqueued_to_completed(
    client, auth_headers, test_user_id, bg_table
):
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued",
                          params={"job_id": "job-1"}, quota_reserved=True)

    r1 = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "enqueued"
    assert r1.json().get("result") is None

    # Worker completes the job (simulated by the terminal-state write).
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "BackgroundJob" SET "status"=%s, "result"=%s::jsonb, '
                '"finishedAt"=now(), "updatedAt"=now() WHERE "id"=%s',
                ("completed", json.dumps({"resume_id": "r1"}), job_id),
            )
        conn.commit()

    r2 = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["status"] == "completed"
    assert body["result"]["resume_id"] == "r1"


def test_status_endpoint_scoped_to_owner(
    client, auth_headers, test_user_id, bg_table
):
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued",
                          params={"job_id": "job-1"})

    # Owner can read their own job.
    owner = client.get(f"/agents/jobs/{job_id}", headers=auth_headers)
    assert owner.status_code == 200, owner.text
    assert owner.json()["job_id"] == job_id

    # A different user cannot read it -> 404 (no cross-user leakage).
    other_headers, _other_id = _register_user(client)
    intruder = client.get(f"/agents/jobs/{job_id}", headers=other_headers)
    assert intruder.status_code == 404, intruder.text


# ===========================================================================
# 4) Quota reserved AT ENQUEUE (single-agent), not at completion.
# ===========================================================================


def test_quota_reserved_at_enqueue_not_at_completion(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)
    _stub_tailor(monkeypatch)
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    before = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    r = client.post("/agents/tailor/run", json={"job_id": "job-1"}, headers=auth_headers)
    assert r.status_code == 202, r.text
    # Reserved at enqueue, BEFORE any worker completion: exactly one consumed now.
    after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert after == before + 1
    # And the BackgroundJob row records the reservation.
    job_id = r.json()["job_id"]
    row = _get_bg_job(job_id)
    assert row["status"] == "enqueued"
    assert row["quotaReserved"] is True


# ===========================================================================
# 5) Paywall 402 AT ENQUEUE, before any queueing / reserve / row.
# ===========================================================================


def test_paywall_402_at_enqueue_before_queueing(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # Free/active -> NOT a paid subscriber
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    r = client.post("/agents/tailor/run", json={"job_id": "job-1"}, headers=auth_headers)
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["error"] == "subscription_required"
    # Paywall fired FIRST: nothing was enqueued, reserved, or persisted.
    assert fake.calls == []
    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0
    assert _count_bg_jobs(test_user_id) == 0


# ===========================================================================
# 6) Worker failure -> quota refunded + honest error + no fixture content.
# ===========================================================================


def test_quota_refunded_on_worker_failure(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    _set_paid_plan(test_user_id)
    # Simulate the enqueue-time reservation for a single-agent job.
    UsageQuotaRepository().reserve(test_user_id)
    reserved = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert reserved == 1
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)
    _stub_tailor(monkeypatch, raises=RuntimeError("simulated upstream generation failure"))

    from app.workers.tasks import run_agent_job  # absent today -> FAILED

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    assert row["status"] == "failed"
    # The reserved run is refunded on failure (atomic, floors at 0).
    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0


def test_no_fixture_content_in_failed_job_result(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    _set_paid_plan(test_user_id)
    UsageQuotaRepository().reserve(test_user_id)
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)
    _stub_tailor(monkeypatch, raises=RuntimeError("simulated upstream generation failure"))

    from app.workers.tasks import run_agent_job  # absent today -> FAILED

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    assert row["status"] == "failed"
    # A failed job carries NO result payload and NO recorded fixture content.
    assert row["result"] in (None, {}, [])
    assert _no_fingerprint(row.get("error"))
    assert _no_fingerprint(json.dumps(row.get("result")))


def test_honest_error_body_on_worker_failure(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    _set_paid_plan(test_user_id)
    UsageQuotaRepository().reserve(test_user_id)
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)
    _stub_tailor(monkeypatch, raises=RuntimeError("simulated upstream generation failure"))

    from app.workers.tasks import run_agent_job  # absent today -> FAILED

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    assert row["status"] == "failed"
    err = row.get("error")
    assert isinstance(err, str) and err.strip()
    assert err.strip().lower() not in ("none", "null", "todo", "placeholder", "")
    assert _no_fingerprint(err)


def test_noop_tailor_completes_not_failed(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    """MV-adv-A-002: a legitimate business no-op (the anti-fabrication guard
    rejected EVERY proposed edit) must NOT be surfaced as a failed job — that
    leaks the raw 'NoChangesApplied: ...' exception-class text to the client
    (via ``_honest_message``) and reports a benign no-op as a failure. Mirror
    the honest synchronous ``/tailor/run`` contract (``run_tailor``'s explicit
    ``except NoChangesApplied`` handling, agents.py ~1250-1263): complete the
    job with an honest ``noChangesApplied`` result and refund the reservation
    (never billed for a run that changed nothing), exactly like Resume
    Studio's no-op handling (MV-resume-studio-003)."""
    from app.agents.tailor_agent import NoChangesApplied

    _set_paid_plan(test_user_id)
    UsageQuotaRepository().reserve(test_user_id)
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)
    _stub_tailor(
        monkeypatch,
        raises=NoChangesApplied(rejected=["bullet one", "bullet two"]),
    )

    from app.workers.tasks import run_agent_job

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    # Completed (not failed) — a no-op is an honest OUTCOME, not a failure.
    assert row["status"] == "completed"
    assert row.get("error") is None
    result = row["result"]
    assert result is not None
    assert result["noChangesApplied"] is True
    assert result["resume_id"] is None
    assert result["changes"] == 0
    assert result["rejected"] == ["bullet one", "bullet two"]
    message = (result.get("message") or "").lower()
    assert "no verifiable changes" in message
    # NEVER the raw Python exception-class prefix a user should never see.
    assert "nochangesapplied" not in message
    # The reserved run is refunded — a legitimate no-op is never billed.
    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0


def test_missing_resume_completes_not_failed(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    """NF-final-PII-002: a no-résumé user's async cover-letter/tailor refusal
    (``MissingResumeError``, NF-final-B-001/005) must NOT surface as a 'failed'
    job with the raw 'MissingResumeError: ...' exception-class prefix leaked via
    ``_honest_message`` — that both leaks an internal class name AND mislabels a
    legitimate, honest refusal as a failure. Mirror
    ``test_noop_tailor_completes_not_failed`` immediately above: complete the
    job with the SAME honest message the synchronous 422 path surfaces (no
    class prefix — main.py's ``MissingResumeError`` handler uses ``str(exc)``
    verbatim) and refund the reservation — never billed for a refused run."""
    from app.services.resume_grounding import MissingResumeError

    _set_paid_plan(test_user_id)
    UsageQuotaRepository().reserve(test_user_id)
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)
    _stub_tailor(
        monkeypatch,
        raises=MissingResumeError(
            "Add your resume before tailoring or generating an application."
        ),
    )

    from app.workers.tasks import run_agent_job

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    # Completed (not failed) — an honest refusal is an outcome, not a failure.
    assert row["status"] == "completed"
    assert row.get("error") is None
    result = row["result"]
    assert result is not None
    message = result.get("message") or ""
    assert message == "Add your resume before tailoring or generating an application."
    # NEVER the raw Python exception-class prefix a user should never see.
    assert "missingresumeerror" not in message.lower()
    # The reserved run is refunded — never billed for a refused run.
    assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0


# ===========================================================================
# 7) Pipeline partial refund on a mid-run worker crash (fable-5 condition 1).
# ===========================================================================


def test_pipeline_partial_refund_on_midrun_crash(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    _set_paid_plan(test_user_id)
    baseline = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    job_id = _seed_bg_job(test_user_id, "pipeline", status="enqueued",
                          params={"query": "x", "location": "y"})

    from app.repositories.background_jobs import BackgroundJobRepository
    from app.workers import tasks as wtasks  # absent today -> FAILED
    from app.workers.tasks import run_agent_job

    def _crashing_pipeline_body(user_id, params):
        # A metered step reserved one run on THIS job (as a real step does under
        # _pipeline_job_ctx), then the worker crashed BEFORE that step could refund
        # itself. The crash refund is scoped to this job's own reservation count
        # (reviewer BLOCKING-3), never a user-wide runsUsed delta.
        UsageQuotaRepository().reserve(user_id)
        BackgroundJobRepository().increment_reserved(job_id)
        raise RuntimeError("simulated mid-pipeline worker crash")

    monkeypatch.setattr(wtasks, "_run_pipeline_body", _crashing_pipeline_body, raising=True)

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    assert row["status"] == "failed"
    # Reserved-but-unfinished steps MUST be refunded on crash -> no quota leak.
    after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert after == baseline, f"leaked {after - baseline} reserved run(s) after crash"


def test_pipeline_missing_resume_completes_not_failed(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    """NF-final-PII-002 (review gap — consolidated-residuals-review.json): the
    PIPELINE branch of ``run_agent_job`` must apply the SAME honest-refusal
    contract as the single-agent branch (``test_missing_resume_completes_not_failed``
    above) when a step inside ``_pipeline_core`` (tailor / coverLetter) raises
    ``MissingResumeError`` for a no-résumé user. Mirrors
    ``test_pipeline_partial_refund_on_midrun_crash``'s monkeypatch-of-
    ``_run_pipeline_body`` seam (a metered step reserved one run on THIS job,
    as a real step does under ``_pipeline_job_ctx``, before the terminal
    exception fires) but with the terminal exception swapped for
    ``MissingResumeError`` instead of a crash. Must complete (not fail), carry
    the honest message with NO leaked 'MissingResumeError:' class prefix, and
    refund the reservation — never billed for a refused pipeline run."""
    from app.services.resume_grounding import MissingResumeError

    _set_paid_plan(test_user_id)
    baseline = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    job_id = _seed_bg_job(test_user_id, "pipeline", status="enqueued",
                          params={"query": "x", "location": "y"})

    from app.repositories.background_jobs import BackgroundJobRepository
    from app.workers import tasks as wtasks
    from app.workers.tasks import run_agent_job

    def _refusing_pipeline_body(user_id, params):
        # A metered step (e.g. coverLetter) reserved one run on THIS job (as a
        # real step does under _pipeline_job_ctx), then refused because this
        # user has no résumé on file — same seam as
        # test_pipeline_partial_refund_on_midrun_crash, different terminal
        # exception.
        UsageQuotaRepository().reserve(user_id)
        BackgroundJobRepository().increment_reserved(job_id)
        raise MissingResumeError(
            "Add your resume before generating a cover letter."
        )

    monkeypatch.setattr(
        wtasks, "_run_pipeline_body", _refusing_pipeline_body, raising=True
    )

    asyncio.run(run_agent_job({}, job_id))

    row = _get_bg_job(job_id)
    # Completed (not failed) — an honest refusal is an outcome, not a failure.
    assert row["status"] == "completed"
    assert row.get("error") is None
    result = row["result"]
    assert result is not None
    message = result.get("message") or ""
    assert message == "Add your resume before generating a cover letter."
    # NEVER the raw Python exception-class prefix a user should never see.
    assert "missingresumeerror" not in message.lower()
    # The reserved run is refunded — never billed for a refused pipeline run.
    after = int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"])
    assert after == baseline, f"leaked {after - baseline} reserved run(s) after refusal"


# ===========================================================================
# 8) Worker reuses the SAME service callable as the sync path (no duplication).
# ===========================================================================


def test_worker_task_calls_existing_service_path(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    _set_paid_plan(test_user_id)
    UsageQuotaRepository().reserve(test_user_id)
    run = AgentRunRepository().start(test_user_id, "tailor", {"job_id": "job-1"})
    job_id = _seed_bg_job(test_user_id, "tailor", status="enqueued", run_id=run["id"],
                          params={"job_id": "job-1"}, quota_reserved=True)

    from app.workers.tasks import run_agent_job  # absent today -> FAILED

    calls: dict = {}

    def _spy_agent_callable(user_id, name, params):
        calls["args"] = (user_id, name, params)
        return "tailor", (lambda: {"resume_id": "from-shared-callable"})

    # Seam absent today -> AttributeError here -> FAILED. After the §4.1 refactor
    # the worker MUST route through this shared mapping (no duplicated dispatch).
    monkeypatch.setattr(agents_mod, "_agent_callable", _spy_agent_callable, raising=True)

    asyncio.run(run_agent_job({}, job_id))

    assert "args" in calls, "worker did not resolve the callable via _agent_callable"
    assert calls["args"][0] == test_user_id
    assert calls["args"][1] == "tailor"
    row = _get_bg_job(job_id)
    assert row["status"] == "completed"
    assert row["result"]["resume_id"] == "from-shared-callable"


# ===========================================================================
# 9) 20 concurrent enqueues -> all 202, zero 503 (mocked queue soak).
# ===========================================================================


def test_20_concurrent_enqueues_zero_503(
    client, auth_headers, test_user_id, bg_table, monkeypatch
):
    monkeypatch.setenv("AETHER_ASYNC_GENERATION", "true")
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_paid_plan(test_user_id)
    _stub_tailor(monkeypatch)
    fake = FakeArqPool()
    monkeypatch.setattr(agents_mod, "_get_arq_pool", lambda: fake, raising=True)

    def _enqueue(_i):
        return client.post(
            "/agents/tailor/run", json={"job_id": "job-1"}, headers=auth_headers
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(_enqueue, range(20)))

    assert len(statuses) == 20
    assert all(s == 202 for s in statuses), f"non-202 present: {statuses}"
    assert statuses.count(503) == 0
