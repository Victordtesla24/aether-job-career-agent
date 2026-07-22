"""ML-cover-002 (HIGH) backend half — failing tests BEFORE fix
(MODELS-LIVE §7 step 2).

RCA verified against CURRENT code (2026-07-22):
- The SYNCHRONOUS pipeline path (apps/api/app/routers/agents.py:1558-1600,
  ``except (FabricationError, StructuralError) as exc:``) gracefully degrades
  a cover-letter guard rejection: the pipeline completes with
  ``{"coverLetterUnavailable": True, "reason": ...}`` instead of failing the
  whole request.
- The ASYNC SINGLE-AGENT worker path (apps/api/app/workers/tasks.py) has NO
  equivalent handling. ``run_agent_job``'s single-agent branch
  (tasks.py:214-268) has explicit ``except NoChangesApplied`` (218-239) and
  ``except MissingResumeError`` (240-261) blocks that complete the job
  honestly — but no ``except (FabricationError, StructuralError)`` block.
  Those exceptions fall straight through to the generic
  ``except Exception as exc:`` at tasks.py:262-268, which marks the job
  'failed' with ``_honest_message(exc)`` (a raw ``"FabricationError: ..."``/
  ``"StructuralError: ..."`` class-prefixed string) instead of completing it
  with an honest ``coverLetterUnavailable`` result the way the pipeline does.

This is the root of ML-cover-002: because the async cover job ends up
'failed' rather than gracefully degraded, the FE's ``resolveRun`` (agents.ts)
throws a hardcoded 502 on ANY failed job, and the rejection-panel matcher
(rejection.ts) only recognizes 422 — so the honest rejection panel can never
render for the async single-agent cover-letter path.
"""
from __future__ import annotations

import asyncio

from app.repositories.agent_run import AgentRunRepository
from app.repositories.billing import UsageQuotaRepository
from test_gap_p7_async_001 import _get_bg_job, _seed_bg_job, _set_paid_plan, bg_table  # noqa: F401


def _stub_cover_letter(monkeypatch, *, raises: Exception):
    def _run(self, *args, **kwargs):
        raise raises

    monkeypatch.setattr(
        "app.agents.cover_letter_agent.CoverLetterAgent.run", _run, raising=True
    )


class TestAsyncCoverLetterGracefulDegrade:
    def test_fabrication_error_completes_not_failed(
        self, client, auth_headers, test_user_id, bg_table, monkeypatch
    ):
        """FAILS TODAY: the job ends up status='failed' with a raw
        'FabricationError: ...' message instead of status='completed' with
        an honest coverLetterUnavailable result (mirroring the sync pipeline
        path's own graceful-degrade handling, agents.py:1558-1600)."""
        from app.agents.cover_letter_agent import FabricationError

        _set_paid_plan(test_user_id)
        UsageQuotaRepository().reserve(test_user_id)
        run = AgentRunRepository().start(
            test_user_id, "coverLetter", {"job_id": "job-1"}
        )
        job_id = _seed_bg_job(
            test_user_id, "coverLetter", status="enqueued", run_id=run["id"],
            params={"job_id": "job-1"}, quota_reserved=True,
        )
        _stub_cover_letter(monkeypatch, raises=FabricationError(["Kubernetes"]))

        from app.workers.tasks import run_agent_job

        asyncio.run(run_agent_job({}, job_id))

        row = _get_bg_job(job_id)
        assert row["status"] == "completed", (
            "expected a graceful degrade (status='completed'), got "
            f"{row['status']!r} with error={row.get('error')!r}"
        )
        assert row.get("error") is None
        result = row["result"] or {}
        assert result.get("coverLetterUnavailable") is True, (
            f"expected an honest coverLetterUnavailable result, got {result!r}"
        )
        message = str(result.get("message") or result.get("reason") or "").lower()
        assert "fabricationerror" not in message, (
            "must never leak the raw Python exception-class prefix"
        )
        # A gracefully-degraded run is never billed.
        assert int(UsageQuotaRepository().get_by_user(test_user_id)["runsUsed"]) == 0

    def test_structural_error_completes_not_failed(
        self, client, auth_headers, test_user_id, bg_table, monkeypatch
    ):
        """Same contract for the §10.2 structural-contract rejection."""
        from app.agents.cover_letter_agent import StructuralError

        _set_paid_plan(test_user_id)
        UsageQuotaRepository().reserve(test_user_id)
        run = AgentRunRepository().start(
            test_user_id, "coverLetter", {"job_id": "job-1"}
        )
        job_id = _seed_bg_job(
            test_user_id, "coverLetter", status="enqueued", run_id=run["id"],
            params={"job_id": "job-1"}, quota_reserved=True,
        )
        _stub_cover_letter(
            monkeypatch,
            raises=StructuralError(["missing a specific call-to-action"]),
        )

        from app.workers.tasks import run_agent_job

        asyncio.run(run_agent_job({}, job_id))

        row = _get_bg_job(job_id)
        assert row["status"] == "completed", (
            "expected a graceful degrade (status='completed'), got "
            f"{row['status']!r} with error={row.get('error')!r}"
        )
        result = row["result"] or {}
        assert result.get("coverLetterUnavailable") is True, (
            f"expected an honest coverLetterUnavailable result, got {result!r}"
        )
        message = str(result.get("message") or result.get("reason") or "").lower()
        assert "structuralerror" not in message
