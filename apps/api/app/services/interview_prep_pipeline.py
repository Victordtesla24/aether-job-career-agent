"""Persist Interview Prep after an evidenced email/calendar ingest.

Interview Center reads the latest completed ``interviewPrep`` AgentRun for the
job on screen. Email triage used to stop at ``InterviewSchedule``. This module
runs the same Interview Prep agent (STAR questions + deterministic briefing)
and writes that row, so the panel is populated without a second click.

LLM failure does not fail ingest: a completed zero-cost run still carries the
deterministic briefing (logistics, traps, questions to ask) assembled from the
trail and the candidate's own data.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.db import get_connection, rows_to_dicts
from app.repositories.agent_run import AgentRunRepository
from app.services.interview_ingest import IngestResult

logger = logging.getLogger(__name__)


def generate_prep_after_ingest(
    user_id: str,
    results: list[IngestResult] | None,
) -> int:
    """Run Interview Prep once per newly evidenced job. Returns runs written."""
    if not results:
        return 0
    written = 0
    seen: set[str] = set()
    for result in results:
        if not result.application_id:
            continue
        job_id = _job_id_for_application(user_id, result.application_id)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        fingerprint = _fingerprint(user_id, job_id)
        if _already_prepped(user_id, job_id, fingerprint):
            continue
        try:
            output = persist_interview_prep(user_id, job_id, fingerprint=fingerprint)
            written += 1
            try:
                from app.services.interview_pack import assemble_interview_pack

                assemble_interview_pack(
                    user_id,
                    job_id,
                    run_missing=False,
                    prep_output=output,
                )
            except Exception:  # noqa: BLE001 — pack is additive
                logger.warning(
                    "interview pack after ingest failed user=%s job=%s",
                    user_id,
                    job_id,
                    exc_info=True,
                )
        except Exception:  # noqa: BLE001 — ingest must still succeed
            logger.warning(
                "interview prep after ingest failed user=%s job=%s",
                user_id,
                job_id,
                exc_info=True,
            )
    return written


def persist_interview_prep(
    user_id: str,
    job_id: str,
    *,
    fingerprint: str | None = None,
) -> dict[str, Any]:
    """Run the agent and persist a completed interviewPrep AgentRun."""
    from app.agents.interview_prep_agent import InterviewPrepAgent
    from app.services.llm_client import LLMUnavailableError

    runs = AgentRunRepository()
    run = runs.start(
        user_id,
        "interviewPrep",
        {
            "job_id": job_id,
            "fingerprint": fingerprint,
            "source": "email_ingest",
        },
    )
    try:
        result = InterviewPrepAgent().run(user_id, job_id=job_id)
        output = asdict(result)
        llm_called = output.pop("llm_called", True)
        if not llm_called:
            output["noLlmCall"] = True
        runs.finish(run["id"], "completed", output=output, cost_usd=0.0)
        return output
    except (LLMUnavailableError, Exception) as exc:
        output = _briefing_only_output(user_id, job_id, str(exc))
        runs.finish(run["id"], "completed", output=output, cost_usd=0.0)
        logger.warning(
            "interview prep LLM unavailable; stored trail briefing only: %s",
            exc,
        )
        return output


def _briefing_only_output(user_id: str, job_id: str, error: str) -> dict[str, Any]:
    from app.agents.interview_prep_agent import InterviewPrepResult
    from app.repositories.job import JobRepository
    from app.services.interview_prep_briefing import load_prep_context

    job = JobRepository().get_by_id(job_id, user_id) or {}
    job_text = "\n".join(
        str(job.get(k) or "")
        for k in ("title", "company", "location", "description")
    )
    ctx = load_prep_context(user_id, job, job_text=job_text)
    result = InterviewPrepResult(
        jobId=job_id,
        jobTitle=job.get("title"),
        company=job.get("company"),
        location=job.get("location"),
        jobSelection="requested",
        llm_called=False,
        predictedQuestions=[],
        briefing=ctx.briefing,
        careerSourcesUsed=ctx.career_source_count,
        message=(
            "STAR questions need a live model, so none were drafted. Logistics, "
            "traps and questions to ask below are from the email trail and your "
            "own data. "
            + (error[:180] if error else "")
        ),
    )
    output = asdict(result)
    output.pop("llm_called", None)
    output["noLlmCall"] = True
    return output


def _job_id_for_application(user_id: str, application_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "jobId" FROM "Application" WHERE id = %s AND "userId" = %s',
                (application_id, user_id),
            )
            rows = rows_to_dicts(cur)
    return str(rows[0]["jobId"]) if rows else None


def _fingerprint(user_id: str, job_id: str) -> str:
    from app.routers.interviews import _ensure_interview_tables

    _ensure_interview_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i."scheduledAt", i."type"
                FROM "InterviewSchedule" i
                JOIN "Application" a ON a.id = i."applicationId"
                WHERE a."userId" = %s AND a."jobId" = %s
                  AND i.status IN ('scheduled', 'confirmed', 'rescheduled')
                ORDER BY i."scheduledAt" ASC
                LIMIT 1
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    if not rows:
        return f"{job_id}:none"
    when = rows[0].get("scheduledAt")
    stamp = when.isoformat() if hasattr(when, "isoformat") else str(when or "")
    return f"{job_id}:{stamp}:{rows[0].get('type') or ''}"


def _already_prepped(user_id: str, job_id: str, fingerprint: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT input
                FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" = 'interviewPrep'
                  AND status = 'completed'
                  AND jsonb_typeof(output) = 'object'
                  AND output->>'jobId' = %s
                ORDER BY "startedAt" DESC
                LIMIT 8
                """,
                (user_id, job_id),
            )
            rows = rows_to_dicts(cur)
    for row in rows:
        payload = row.get("input") or {}
        if isinstance(payload, dict) and payload.get("fingerprint") == fingerprint:
            return True
    return False
