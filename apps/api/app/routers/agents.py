"""Agents router — trigger + audit agent runs (P2-S02 → P2-S08).

Every run is recorded as an ``AgentRun`` row (status, input, output, error,
timestamps) so the dashboard and analytics can reconstruct what the system
did and why. High-risk outputs (tailored resumes, cover letters) surface an
``approvalRequired`` flag — nothing is submitted without human sign-off.
"""
from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.scout_agent import ScoutAgent
from app.middleware.auth import CurrentUser
from app.repositories.agent_run import AgentRunRepository

router = APIRouter()

#: Canonical agent registry (mirrors the LangGraph node names in
#: packages/agents/src/graph/aether-graph.ts).
AGENT_NAMES = (
    "supervisor", "scout", "matcher", "fitScorer", "tailor", "coverLetter", "storyExtractor"
)

#: Agents whose output is gated behind a human approval.
_APPROVAL_GATED = {"tailor", "coverLetter"}


def _to_output(result: Any) -> dict[str, Any]:
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    return dict(result) if isinstance(result, dict) else {"result": str(result)}


def _record_run(
    user_id: str, agent_name: str, params: dict[str, Any], fn: Callable[[], Any]
) -> dict[str, Any]:
    """Execute ``fn`` under an AgentRun audit record."""
    runs = AgentRunRepository()
    run = runs.start(user_id, agent_name, params)
    started = time.monotonic()
    try:
        output = _to_output(fn())
    except HTTPException:
        runs.finish(run["id"], "failed", error="http error")
        raise
    except Exception as exc:
        runs.finish(run["id"], "failed", error=str(exc))
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    output["duration_ms"] = duration_ms
    output["approvalRequired"] = agent_name in _APPROVAL_GATED
    finished = runs.finish(run["id"], "completed", output=output, cost_usd=0.0)
    output["run_id"] = (finished or run)["id"]
    return output


def _dispatch(user_id: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
    if name == "scout":
        query = params.get("query", "software engineer")
        location = params.get("location", "Australia")
        return _record_run(
            user_id, "scout", params, lambda: ScoutAgent().run(user_id, query, location)
        )
    if name in ("fitScorer", "fit-scorer"):
        from app.agents.fit_scorer import FitScorerAgent

        return _record_run(
            user_id, "fitScorer", params,
            lambda: FitScorerAgent().run(user_id, rescore=bool(params.get("rescore"))),
        )
    if name == "tailor":
        from app.agents.tailor_agent import TailoringAgent

        job_id = _require_job_id(params)
        return _record_run(
            user_id, "tailor", params, lambda: TailoringAgent().run(user_id, job_id)
        )
    if name in ("coverLetter", "cover-letter"):
        from app.agents.cover_letter_agent import CoverLetterAgent

        job_id = _require_job_id(params)
        return _record_run(
            user_id, "coverLetter", params, lambda: CoverLetterAgent().run(user_id, job_id)
        )
    if name in ("storyExtractor", "story-extractor"):
        from app.agents.story_extractor import StoryExtractorAgent

        return _record_run(
            user_id, "storyExtractor", params, lambda: StoryExtractorAgent().run(user_id)
        )
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{name}'")


def _require_job_id(params: dict[str, Any]) -> str:
    job_id = params.get("job_id")
    if not job_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "job_id is required")
    return str(job_id)


# ---------------------------------------------------------------------------
# Listing / audit endpoints (declared before the generic /{name}/run)
# ---------------------------------------------------------------------------


@router.get("")
def list_agents(current_user: CurrentUser) -> list[dict[str, Any]]:
    """All known agents with their most recent run (P2-S08)."""
    last = AgentRunRepository().last_run_by_agent(current_user["id"])
    agents = []
    for name in AGENT_NAMES:
        run = last.get(name)
        agents.append(
            {
                "name": name,
                "status": run["status"] if run else "idle",
                "last_run": run["createdAt"].isoformat() if run else None,
                "approval_gated": name in _APPROVAL_GATED,
            }
        )
    return agents


@router.get("/runs")
def list_runs(current_user: CurrentUser, limit: int = 50) -> list[dict[str, Any]]:
    return AgentRunRepository().list_recent(current_user["id"], limit=min(limit, 200))


@router.get("/runs/{run_id}")
def get_run(run_id: str, current_user: CurrentUser) -> dict[str, Any]:
    run = AgentRunRepository().get_by_id(run_id, current_user["id"])
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found")
    return run


# ---------------------------------------------------------------------------
# Dedicated agent triggers (stable P2-S02..S06 contracts)
# ---------------------------------------------------------------------------


class ScoutRunRequest(BaseModel):
    query: str = Field(min_length=1)
    location: str = Field(min_length=1)


@router.post("/scout/run", status_code=status.HTTP_202_ACCEPTED)
def run_scout(body: ScoutRunRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Kick off a scout discovery run for the authenticated user."""
    output = _dispatch(current_user["id"], "scout", body.model_dump())
    return {"status": "accepted", "persisted": output["persisted"], "errors": output["errors"]}


@router.post("/fit-scorer/run")
def run_fit_scorer(current_user: CurrentUser, rescore: bool = False) -> dict[str, Any]:
    """Score every unscored job for the authenticated user (P2-S04)."""
    output = _dispatch(current_user["id"], "fitScorer", {"rescore": rescore})
    return {"status": "completed", "scored": output["scored"], "errors": output["errors"]}


class JobTargetRequest(BaseModel):
    job_id: str = Field(min_length=1)


@router.post("/tailor/run")
def run_tailor(body: JobTargetRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Produce a tailored child resume version for a target job (P2-S05)."""
    try:
        output = _dispatch(current_user["id"], "tailor", body.model_dump())
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {
        "resume_id": output["resume_id"],
        "changes": output["changes"],
        "rejected": output["rejected"],
    }


@router.post("/cover-letter/run")
def run_cover_letter(body: JobTargetRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Draft a fabrication-guarded cover letter; requires human approval (P2-S06)."""
    from app.agents.cover_letter_agent import FabricationError

    try:
        output = _dispatch(current_user["id"], "coverLetter", body.model_dump())
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except FabricationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cover letter rejected by fabrication guard: {exc.flagged}",
        ) from exc
    return {
        "cover_letter_id": output["cover_letter_id"],
        "cover_letter": output["cover_letter"],
        "approval_id": output["approval_id"],
        "approval_status": output["approval_status"],
    }


@router.post("/story-extractor/run")
def run_story_extractor(current_user: CurrentUser) -> dict[str, Any]:
    """Extract STAR stories from the base resume (P2-S09)."""
    return _dispatch(current_user["id"], "storyExtractor", {})


# ---------------------------------------------------------------------------
# Orchestration (P2-S08)
# ---------------------------------------------------------------------------


class PipelineRunRequest(BaseModel):
    query: str = "software engineer"
    location: str = "Australia"


@router.post("/pipeline/run")
def run_pipeline(body: PipelineRunRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Full pipeline: scout → fitScorer → tailor → coverLetter (top job).

    Mirrors the LangGraph orchestration in packages/agents; the pipeline halts
    with ``approvalRequired=True`` after generating tailored artefacts.
    """
    user_id = current_user["id"]
    steps: list[dict[str, Any]] = []

    scout_out = _dispatch(user_id, "scout", body.model_dump())
    steps.append({"agent": "scout", "output": scout_out})
    fit_out = _dispatch(user_id, "fitScorer", {"rescore": False})
    steps.append({"agent": "fitScorer", "output": fit_out})

    from app.repositories.job import JobRepository

    jobs = JobRepository().list_by_user(user_id, sort="fitScore")
    if not jobs:
        return {"status": "completed", "steps": steps, "approvalRequired": False}

    top_job_id = jobs[0]["id"]
    tailor_out = _dispatch(user_id, "tailor", {"job_id": top_job_id})
    steps.append({"agent": "tailor", "output": tailor_out})
    letter_out = _dispatch(user_id, "coverLetter", {"job_id": top_job_id})
    steps.append({"agent": "coverLetter", "output": letter_out})

    return {
        "status": "awaiting_approval",
        "steps": steps,
        "top_job_id": top_job_id,
        "approvalRequired": True,
        "approval_id": letter_out.get("approval_id"),
    }


# Generic trigger — declared last so specific routes above win.
@router.post("/{name}/run")
def run_named_agent(
    name: str, current_user: CurrentUser, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Trigger any registered agent by name with free-form params (P2-S08)."""
    try:
        return _dispatch(current_user["id"], name, params or {})
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
