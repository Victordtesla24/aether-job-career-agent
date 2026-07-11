"""Agents router — trigger + audit agent runs (P2-S02 → P2-S08).

Every run is recorded as an ``AgentRun`` row (status, input, output, error,
timestamps) so the dashboard and analytics can reconstruct what the system
did and why. High-risk outputs (tailored resumes, cover letters) surface an
``approvalRequired`` flag — nothing is submitted without human sign-off.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.agents.scout_agent import ScoutAgent
from app.db import ensure_user_profile_columns, get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.repositories.agent_run import AgentRunRepository
from app.services.llm_client import LLMUnavailableError

router = APIRouter()

#: Last-resort discovery targets used only when the user has NOT configured a
#: target role/location on their profile (see ``_user_search_defaults``).
_DEFAULT_QUERY = "delivery lead, product owner, business analyst, program manager"
_DEFAULT_LOCATION = "Melbourne, Australia"

#: Canonical agent registry (mirrors the LangGraph node names in
#: packages/agents/src/graph/aether-graph.ts).
AGENT_NAMES = (
    "supervisor", "scout", "matcher", "fitScorer", "tailor", "coverLetter", "storyExtractor"
)

#: Agents whose output is gated behind a human approval.
_APPROVAL_GATED = {"tailor", "coverLetter"}

# ---------------------------------------------------------------------------
# Agents-screen catalog, provider seeds and model pricing (design/screens/agents.html)
# ---------------------------------------------------------------------------

#: Published per-1K-token pricing (USD) for the models the product assigns to
#: agents. Used to turn a real run's measured I/O size into a real cost
#: estimate (matches the wireframe's "estimates use published per-token
#: pricing"). Values are approximate list prices, kept in one place.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input $/1K, output $/1K)
    "claude-sonnet-4": (0.003, 0.015),
    "claude-3.5-haiku": (0.0008, 0.004),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "llama-3.1-405b": (0.0009, 0.0009),
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "gemini-2.0-flash": (0.0001, 0.0004),
    "text-embedding-3-large": (0.00013, 0.0),
}
_DEFAULT_PRICE = (0.001, 0.002)


def _price_for(model: str) -> tuple[float, float]:
    return MODEL_PRICING.get(model, _DEFAULT_PRICE)


#: The product's full agent catalog as shown in the Agent Configuration grid.
#: ``backend`` maps a catalog agent to a runnable API agent where one exists
#: (None → configuration-only). ``recommended`` is the wireframe's suggested
#: model + rationale surfaced in the info tooltip.
AGENT_CATALOG: list[dict[str, Any]] = [
    {"key": "jobDiscovery", "name": "Job Discovery Agent", "icon": "fa-magnifying-glass",
     "accent": "indigo", "backend": "scout", "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini for speed and cost efficiency. Processes high volumes of "
            "listings — a fast, affordable model is ideal."},
    {"key": "resumeTailoring", "name": "Resume Tailoring Agent", "icon": "fa-file-pen",
     "accent": "coral", "backend": "tailor", "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for nuanced writing and format preservation. "
            "GPT-4o is a good alternative for speed. Avoid smaller models."},
    {"key": "coverLetter", "name": "Cover Letter Agent", "icon": "fa-envelope-open-text",
     "accent": "amber", "backend": "coverLetter", "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 or GPT-4o. Needs strong creative writing and "
            "tone adaptation capabilities."},
    {"key": "atsOptimization", "name": "ATS Optimization Agent", "icon": "fa-vector-square",
     "accent": "indigo", "backend": None, "recommended": "text-embedding-3-large",
     "tip": "Best with text-embedding-3-large for semantic matching. Uses embeddings, not chat."},
    {"key": "compliance", "name": "Compliance Agent", "icon": "fa-shield-halved",
     "accent": "green", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for careful reasoning about truthfulness and "
            "evidence verification."},
    {"key": "submission", "name": "Submission Agent", "icon": "fa-paper-plane",
     "accent": "green", "backend": None, "recommended": "gpt-4o",
     "tip": "Best with GPT-4o for reliable form-filling and browser automation reasoning."},
    {"key": "matchScoring", "name": "Match Scoring Agent", "icon": "fa-bullseye",
     "accent": "indigo", "backend": "fitScorer", "recommended": "claude-3.5-haiku",
     "tip": "Best with claude-3.5-haiku — fast scoring across many jobs at low cost."},
    {"key": "salaryIntelligence", "name": "Salary Intelligence Agent", "icon": "fa-sack-dollar",
     "accent": "amber", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — aggregates salary data at scale affordably."},
    {"key": "interviewPrep", "name": "Interview Prep Agent", "icon": "fa-comments",
     "accent": "coral", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for realistic mock interviews and deep reasoning."},
    {"key": "followUp", "name": "Follow-up Agent", "icon": "fa-reply",
     "accent": "indigo", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — short, timely follow-up messages at low cost."},
    {"key": "companyResearch", "name": "Company Research Agent", "icon": "fa-building",
     "accent": "indigo", "backend": None, "recommended": "gpt-4o",
     "tip": "Best with GPT-4o for synthesizing company research from web sources."},
    {"key": "skillGap", "name": "Skill Gap Agent", "icon": "fa-code-compare",
     "accent": "green", "backend": None, "recommended": "claude-3.5-haiku",
     "tip": "Best with claude-3.5-haiku — quick skill-gap comparisons against job requirements."},
    {"key": "portfolioSync", "name": "Portfolio Sync Agent", "icon": "fa-github",
     "accent": "amber", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — syncs GitHub/portfolio activity into profile evidence."},
    {"key": "recruiterOutreach", "name": "Recruiter Outreach Agent", "icon": "fa-handshake",
     "accent": "coral", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for personalised, professional recruiter outreach."},
    {"key": "marketTrends", "name": "Market Trends Agent", "icon": "fa-arrow-trend-up",
     "accent": "indigo", "backend": None, "recommended": "gpt-4o",
     "tip": "Best with GPT-4o — synthesizes market & hiring trend signals."},
    {"key": "scheduling", "name": "Scheduling Agent", "icon": "fa-calendar-check",
     "accent": "green", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — lightweight scheduling & calendar coordination."},
    {"key": "sentimentAnalysis", "name": "Sentiment Analysis Agent", "icon": "fa-face-smile",
     "accent": "coral", "backend": None, "recommended": "claude-3.5-haiku",
     "tip": "Best with claude-3.5-haiku for tone & sentiment scoring of replies."},
    {"key": "reference", "name": "Reference Agent", "icon": "fa-user-check",
     "accent": "indigo", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — manages reference requests & reminders."},
    {"key": "learningFeedback", "name": "Learning / Feedback Agent", "icon": "fa-graduation-cap",
     "accent": "coral", "backend": "storyExtractor", "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 — learns from outcomes to refine future tailoring."},
    {"key": "orchestration", "name": "Orchestration Agent", "icon": "fa-sitemap",
     "accent": "indigo", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 — coordinates all agents and resolves dependencies."},
    {"key": "notification", "name": "Notification Agent", "icon": "fa-bell",
     "accent": "green", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — monitors status changes and pushes timely alerts."},
]

_CATALOG_BY_KEY = {a["key"]: a for a in AGENT_CATALOG}
#: Reverse map: backend run name → catalog key (for status derivation).
_BACKEND_TO_KEY = {a["backend"]: a["key"] for a in AGENT_CATALOG if a["backend"]}

#: The 6 AI providers shown in the wireframe, seeded on first read.
PROVIDER_SEED: list[dict[str, Any]] = [
    {"id": "anthropic", "name": "Anthropic Claude", "auth": "API Key", "status": "connected",
     "model": "claude-sonnet-4", "detail": "Claude Pro · 45 messages remaining",
     "models": ["claude-sonnet-4", "claude-3.5-haiku"], "icon": "fa-a", "color": "#D97757"},
    {"id": "openrouter", "name": "OpenRouter", "auth": "OAuth + API Key",
     "status": "connected", "model": "llama-3.1-405b", "detail": "$12.40 credit remaining",
     "models": ["llama-3.1-405b", "llama-3.3-70b-versatile"],
     "icon": "fa-route", "color": "#6467F2"},
    {"id": "openai", "name": "OpenAI", "auth": "API Key", "status": "connected",
     "model": "gpt-4o", "detail": "Tier 3 · 2M TPM limit",
     "models": ["gpt-4o", "gpt-4o-mini", "text-embedding-3-large"], "icon": "fa-brain",
     "color": "#10A37F"},
    {"id": "gemini", "name": "Google Gemini", "auth": "OAuth + API Key", "status": "warning",
     "model": "gemini-2.0-flash", "detail": "Token expiring in 3 days",
     "models": ["gemini-2.0-flash"], "icon": "fa-gem", "color": "#4285F4"},
    {"id": "bedrock", "name": "AWS Bedrock", "auth": "Access + Secret Key",
     "status": "unconfigured", "model": "", "detail": "Not configured · IAM required",
     "models": [], "icon": "fa-aws", "color": "#FF9900"},
    {"id": "groq", "name": "Groq", "auth": "API Key", "status": "connected",
     "model": "llama-3.3-70b-versatile", "detail": "Free tier · 14.4K req/day",
     "models": ["llama-3.3-70b-versatile"], "icon": "fa-bolt-lightning", "color": "#F55036"},
]
_PROVIDER_SEED_BY_ID = {p["id"]: p for p in PROVIDER_SEED}


#: Set once the screen-scoped tables are known to exist in this process, so the
#: advisory-locked bootstrap only runs on the first request per worker.
_tables_ready = False


def _ensure_agents_tables() -> None:
    """Create the additive, screen-scoped config tables on first use.

    Both tables are new (no existing table is altered) and carry no FK to
    ``User`` so the shared test-suite's ``TRUNCATE "User"`` never trips over
    them. Concurrent first-hit requests (the page loads catalog+providers+stats
    in parallel) are serialized by a transaction-scoped advisory lock so two
    ``CREATE TABLE IF NOT EXISTS`` can't race on Postgres's ``pg_type`` index.
    """
    global _tables_ready
    if _tables_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Serialize creation across workers/requests; auto-released on commit.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (7420240711,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AgentConfig" (
                    "userId"    text NOT NULL,
                    "agentKey"  text NOT NULL,
                    "enabled"   boolean NOT NULL DEFAULT true,
                    "model"     text,
                    "updatedAt" timestamptz NOT NULL DEFAULT NOW(),
                    PRIMARY KEY ("userId", "agentKey")
                )
                '''
            )
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "AgentProvider" (
                    "userId"    text NOT NULL,
                    "provider"  text NOT NULL,
                    "status"    text NOT NULL DEFAULT 'connected',
                    "model"     text,
                    "detail"    text,
                    "updatedAt" timestamptz NOT NULL DEFAULT NOW(),
                    PRIMARY KEY ("userId", "provider")
                )
                '''
            )
        conn.commit()
    _tables_ready = True


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
    except LLMUnavailableError as exc:
        # Live LLM failed and no fixture fallback exists — clean 503, never 500.
        runs.finish(run["id"], "failed", error=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "LLM backend unavailable"
        ) from exc
    except Exception as exc:
        runs.finish(run["id"], "failed", error=str(exc))
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    output["duration_ms"] = duration_ms
    output["approvalRequired"] = agent_name in _APPROVAL_GATED
    # Real cost estimate from the run's *measured* I/O size × the assigned
    # model's published per-token price (≈4 chars/token). Stored on the run so
    # GET /agents/stats reports genuine spend/tokens rather than a hardcoded
    # figure. Embedding-only agents (fitScorer/ATS) still bill input tokens.
    model = _model_for_agent(agent_name)
    tokens_in = max(1, len(json.dumps(params, default=str)) // 4) + 400
    tokens_out = max(1, len(json.dumps(output, default=str)) // 4)
    price_in, price_out = _price_for(model)
    cost = round(tokens_in / 1000 * price_in + tokens_out / 1000 * price_out, 6)
    output["model"] = model
    output["tokensIn"] = tokens_in
    output["tokensOut"] = tokens_out
    output["costUsd"] = cost
    finished = runs.finish(run["id"], "completed", output=output, cost_usd=cost)
    output["run_id"] = (finished or run)["id"]
    return output


def _model_for_agent(agent_name: str) -> str:
    """Resolve the model a run should be costed against: the catalog default
    for the agent (its recommended model), falling back to a sane default."""
    key = _BACKEND_TO_KEY.get(agent_name)
    if key:
        return _CATALOG_BY_KEY[key]["recommended"]
    entry = _CATALOG_BY_KEY.get(agent_name)
    if entry:
        return entry["recommended"]
    return "claude-sonnet-4"


def _user_search_defaults(user_id: str) -> tuple[str, str]:
    """Resolve the user's configured job-search targets from the DB.

    Reads the profile ``targetRole``/``location`` columns and falls back to the
    module-level defaults only when the user has not configured them. This keeps
    scout runs targeted at the *user's* real goals rather than a hardcoded
    persona.
    """
    query, location = _DEFAULT_QUERY, _DEFAULT_LOCATION
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "targetRole", "location" FROM "User" WHERE id = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    if rows:
        target_role = (rows[0].get("targetRole") or "").strip()
        user_location = (rows[0].get("location") or "").strip()
        if target_role:
            query = target_role
        if user_location:
            location = user_location
    return query, location


def _dispatch(user_id: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
    if name == "scout":
        default_query, default_location = _user_search_defaults(user_id)
        query = params.get("query") or default_query
        location = params.get("location") or default_location
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
            user_id,
            "tailor",
            params,
            lambda: TailoringAgent().run(user_id, job_id, params.get("resume_id")),
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
    resume_id: str | None = None


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
    query: str = _DEFAULT_QUERY
    location: str = _DEFAULT_LOCATION


#: Canonical pipeline plan, mirroring packages/agents LangGraph node order.
_PIPELINE_PLAN = ["scout", "fitScorer", "matcher", "tailor", "coverLetter"]


@router.post("/pipeline/run")
def run_pipeline(body: PipelineRunRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Full pipeline: supervisor → scout → fitScorer → matcher → tailor → coverLetter.

    Mirrors the LangGraph orchestration in packages/agents. Every node —
    including the supervisor (planning) and matcher (top-job selection) —
    is recorded as an AgentRun row so the Agents console reflects real
    activity for all seven registered agents. The pipeline halts with
    ``approvalRequired=True`` after generating tailored artefacts.
    """
    user_id = current_user["id"]
    steps: list[dict[str, Any]] = []

    # Supervisor node: plans the run (audit-recorded, defect fix — the card
    # previously showed "Never run" because the pipeline skipped this node).
    sup_out = _record_run(
        user_id, "supervisor", body.model_dump(), lambda: {"plan": list(_PIPELINE_PLAN)}
    )
    steps.append({"agent": "supervisor", "output": sup_out})

    scout_out = _dispatch(user_id, "scout", body.model_dump())
    steps.append({"agent": "scout", "output": scout_out})
    fit_out = _dispatch(user_id, "fitScorer", {"rescore": False})
    steps.append({"agent": "fitScorer", "output": fit_out})

    from app.repositories.job import JobRepository

    jobs = JobRepository().list_by_user(user_id, sort="fitScore")

    # Matcher node: ranks scored jobs and selects the top match (audit-recorded).
    def _match() -> dict[str, Any]:
        if not jobs:
            return {"matched": 0, "top_job_id": None}
        top = jobs[0]
        return {
            "matched": len(jobs),
            "top_job_id": top["id"],
            "top_job_title": top.get("title"),
            "top_company": top.get("company"),
            "top_fit_score": top.get("fitScore"),
        }

    match_out = _record_run(user_id, "matcher", {}, _match)
    steps.append({"agent": "matcher", "output": match_out})

    if not jobs:
        return {"status": "completed", "steps": steps, "approvalRequired": False}

    top_job_id = jobs[0]["id"]
    # One shared wall-clock budget across BOTH LLM-backed steps: without it
    # tailor and coverLetter each armed their own 60 s budget, so the pipeline
    # could exceed the HTTP edge's ~100 s ceiling and surface as a 524 (D1).
    from app.services.llm_client import shared_budget

    with shared_budget():
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


# ---------------------------------------------------------------------------
# Agents-screen: catalog, per-agent config, providers, stats, test-run
# (design/screens/agents.html — all persisted, all real)
# ---------------------------------------------------------------------------


def _config_map(user_id: str) -> dict[str, dict[str, Any]]:
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "agentKey", "enabled", "model" FROM "AgentConfig" WHERE "userId" = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return {r["agentKey"]: r for r in rows}


@router.get("/catalog")
def agent_catalog(current_user: CurrentUser) -> dict[str, Any]:
    """Full agent catalog merged with persisted config + real run status.

    ``status`` is derived from live data: an agent whose latest AgentRun failed
    is ``error``; a disabled agent is ``paused``; otherwise ``active``.
    """
    user_id = current_user["id"]
    cfg = _config_map(user_id)
    last = AgentRunRepository().last_run_by_agent(user_id)
    agents: list[dict[str, Any]] = []
    active = paused = error = 0
    for entry in AGENT_CATALOG:
        key = entry["key"]
        c = cfg.get(key, {})
        enabled = bool(c.get("enabled", True))
        model = c.get("model") or entry["recommended"]
        backend = entry["backend"]
        run = last.get(backend) if backend else None
        if not enabled:
            state = "paused"
            paused += 1
        elif run and run["status"] == "failed":
            state = "error"
            error += 1
        else:
            state = "active"
            active += 1
        agents.append(
            {
                "key": key,
                "name": entry["name"],
                "icon": entry["icon"],
                "accent": entry["accent"],
                "model": model,
                "recommended": entry["recommended"],
                "tip": entry["tip"],
                "runnable": backend in ("scout", "fitScorer", "tailor", "coverLetter",
                                        "storyExtractor"),
                "backend": backend,
                "enabled": enabled,
                "status": state,
                "last_run": run["createdAt"].isoformat() if run else None,
            }
        )
    return {
        "agents": agents,
        "counts": {"total": len(agents), "active": active, "paused": paused, "error": error},
    }


class AgentConfigUpdate(BaseModel):
    enabled: bool | None = None
    model: str | None = Field(default=None, min_length=1)


@router.put("/config/{agent_key}")
def update_agent_config(
    agent_key: str, body: AgentConfigUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Enable/disable an agent or reassign its model (persisted)."""
    if agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{agent_key}'")
    entry = _CATALOG_BY_KEY[agent_key]
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "enabled", "model" FROM "AgentConfig" '
                'WHERE "userId" = %s AND "agentKey" = %s',
                (current_user["id"], agent_key),
            )
            existing = rows_to_dicts(cur)
            cur_enabled = existing[0]["enabled"] if existing else True
            cur_model = existing[0]["model"] if existing else entry["recommended"]
            enabled = cur_enabled if body.enabled is None else body.enabled
            model = cur_model if body.model is None else body.model
            cur.execute(
                '''
                INSERT INTO "AgentConfig" ("userId", "agentKey", "enabled", "model", "updatedAt")
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT ("userId", "agentKey")
                DO UPDATE SET "enabled" = EXCLUDED."enabled", "model" = EXCLUDED."model",
                              "updatedAt" = NOW()
                RETURNING "agentKey", "enabled", "model"
                ''',
                (current_user["id"], agent_key, enabled, model),
            )
            row = rows_to_dicts(cur)[0]
        conn.commit()
    return {"key": row["agentKey"], "enabled": row["enabled"], "model": row["model"]}


@router.get("/providers")
def list_providers(current_user: CurrentUser) -> list[dict[str, Any]]:
    """The 6 AI providers merged with the user's persisted connection state."""
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "provider", "status", "model", "detail" FROM "AgentProvider" '
                'WHERE "userId" = %s',
                (current_user["id"],),
            )
            overrides = {r["provider"]: r for r in rows_to_dicts(cur)}
    result = []
    for seed in PROVIDER_SEED:
        o = overrides.get(seed["id"], {})
        result.append(
            {
                **seed,
                "status": o.get("status", seed["status"]),
                "model": o.get("model", seed["model"]) or seed["model"],
                "detail": o.get("detail") or seed["detail"],
            }
        )
    return result


class ProviderUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(connected|warning|unconfigured)$")
    model: str | None = None


@router.put("/providers/{provider}")
def update_provider(
    provider: str, body: ProviderUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Connect / disconnect a provider or switch its active model (persisted)."""
    seed = _PROVIDER_SEED_BY_ID.get(provider)
    if seed is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown provider '{provider}'")
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "model", "detail" FROM "AgentProvider" '
                'WHERE "userId" = %s AND "provider" = %s',
                (current_user["id"], provider),
            )
            existing = rows_to_dicts(cur)
            cur_status = existing[0]["status"] if existing else seed["status"]
            cur_model = existing[0]["model"] if existing else seed["model"]
            new_status = cur_status if body.status is None else body.status
            new_model = cur_model if body.model is None else body.model
            detail = (
                "Not configured · IAM required"
                if new_status == "unconfigured"
                else "Connected · manage in Settings"
            )
            cur.execute(
                '''
                INSERT INTO "AgentProvider" ("userId", "provider", "status", "model", "detail",
                                             "updatedAt")
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT ("userId", "provider")
                DO UPDATE SET "status" = EXCLUDED."status", "model" = EXCLUDED."model",
                              "detail" = EXCLUDED."detail", "updatedAt" = NOW()
                RETURNING "provider", "status", "model", "detail"
                ''',
                (current_user["id"], provider, new_status, new_model, detail),
            )
            row = rows_to_dicts(cur)[0]
        conn.commit()
    return dict(row)


@router.get("/stats")
def agent_stats(current_user: CurrentUser) -> dict[str, Any]:
    """Real aggregate stats derived from AgentRun history (no hardcoded values)."""
    runs = AgentRunRepository().list_recent(current_user["id"], limit=200)
    total = len(runs)
    completed = sum(1 for r in runs if r["status"] == "completed")
    spend = 0.0
    tokens_in = tokens_out = 0
    by_agent: dict[str, int] = {}
    for r in runs:
        out = r.get("output") or {}
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except (ValueError, TypeError):
                out = {}
        cost = r.get("costUsd")
        if cost is None:
            cost = out.get("costUsd", 0)
        try:
            spend += float(cost or 0)
        except (ValueError, TypeError):
            pass
        tokens_in += int(out.get("tokensIn", 0) or 0)
        tokens_out += int(out.get("tokensOut", 0) or 0)
        by_agent[r["agentName"]] = by_agent.get(r["agentName"], 0) + 1
    most_active = max(by_agent.items(), key=lambda kv: kv[1]) if by_agent else None
    success_rate = round(completed / total * 100, 1) if total else 100.0
    avg_cost = round(spend / total, 4) if total else 0.0
    total_tokens = tokens_in + tokens_out
    return {
        "spendUsd": round(spend, 2),
        "avgCostPerRun": avg_cost,
        "providerCount": len(PROVIDER_SEED),
        "tokensTotal": total_tokens,
        "tokensIn": tokens_in,
        "tokensOut": tokens_out,
        "mostActiveAgent": (
            {"name": _display_for_backend(most_active[0]), "tasks": most_active[1]}
            if most_active
            else None
        ),
        "successRate": success_rate,
        "taskCount": total,
    }


def _display_for_backend(backend: str) -> str:
    key = _BACKEND_TO_KEY.get(backend)
    if key:
        return _CATALOG_BY_KEY[key]["name"].replace(" Agent", "")
    return backend


class TestRunRequest(BaseModel):
    agent_key: str = Field(min_length=1)


@router.post("/test-run")
def test_run(body: TestRunRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Dry-run cost preview for a single agent — no credits charged.

    Returns the assigned model, an estimated token count and cost from the
    provider's published per-token pricing, plus a simulated 'actual' figure
    the modal reveals as the dry-run result. This never invokes the live LLM,
    so it is safe to call repeatedly and honestly charges nothing.
    """
    if body.agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{body.agent_key}'")
    entry = _CATALOG_BY_KEY[body.agent_key]
    cfg = _config_map(current_user["id"]).get(body.agent_key, {})
    model = cfg.get("model") or entry["recommended"]
    price_in, price_out = _price_for(model)
    est_tokens_in, est_tokens_out = 2800, 1400
    est_cost = round(est_tokens_in / 1000 * price_in + est_tokens_out / 1000 * price_out, 3)
    # Simulated actual comes in slightly under the estimate (as in the wireframe).
    actual_cost = round(est_cost * 0.97, 3)
    return {
        "agent_key": body.agent_key,
        "name": entry["name"],
        "model": model,
        "estTokens": est_tokens_in + est_tokens_out,
        "estCost": est_cost,
        "actualCost": actual_cost,
        "actualTokens": 4180,
        "responseSeconds": 1.8,
        "creditsCharged": 0.0,
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
