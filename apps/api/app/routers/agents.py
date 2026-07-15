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
from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    AnthropicOAuthStateRepository,
    UserProviderCredentialRepository,
    _ensure_user_agent_tables,
)
from app.services import anthropic_oauth, credential_vault
from app.services.llm_client import (
    LLMUnavailableError,
    QuotaExhaustedError,
    _infer_anthropic_auth_mode,
    get_active_credential_env_var,
    get_quota_block_hours,
    resolve_provider,
    resolve_user_credential,
    user_credential_context,
    verify_provider_credential,
    verify_user_credential,
)

router = APIRouter()

#: Last-resort discovery targets used only when the user has NOT configured a
#: target role/location on their profile (see ``_user_search_defaults``).
_DEFAULT_QUERY = "delivery lead, product owner, business analyst, program manager"
_DEFAULT_LOCATION = "Melbourne, Australia"

#: Canonical agent registry (mirrors the LangGraph node names in
#: packages/agents/src/graph/aether-graph.ts).
AGENT_NAMES = (
    "supervisor", "scout", "matcher", "fitScorer", "tailor", "coverLetter",
    "storyExtractor", "emailAgent"
)

#: Agents whose output is gated behind a human approval.
_APPROVAL_GATED = {"tailor", "coverLetter", "emailAgent"}

# ---------------------------------------------------------------------------
# Agents-screen catalog, provider seeds and model pricing (design/screens/agents.html)
# ---------------------------------------------------------------------------

#: Published per-1K-token pricing (USD) for the models the product assigns to
#: agents. Used to turn a real run's measured I/O size into a real cost
#: estimate (matches the wireframe's "estimates use published per-token
#: pricing"). Values are approximate list prices, kept in one place.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # model: (input $/1K, output $/1K)
    "claude-fable-5": (0.010, 0.050),
    "claude-haiku-4-5-20251001": (0.001, 0.005),
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
     "accent": "indigo", "backend": "scout", "recommended": "deterministic",
     "tip": "Deterministic multi-source discovery (Seek, Greenhouse, Lever, Remotive, "
            "RemoteOK) — scrapes and normalises listings with no LLM cost."},
    {"key": "resumeTailoring", "name": "Resume Tailoring Agent", "icon": "fa-file-pen",
     "accent": "coral", "backend": "tailor", "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for nuanced writing and format preservation. "
            "GPT-4o is a good alternative for speed. Avoid smaller models."},
    {"key": "coverLetter", "name": "Cover Letter Agent", "icon": "fa-envelope-open-text",
     "accent": "amber", "backend": "coverLetter", "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 or GPT-4o. Needs strong creative writing and "
            "tone adaptation capabilities."},
    {"key": "atsOptimization", "name": "ATS Optimization Agent", "icon": "fa-vector-square",
     "accent": "indigo", "backend": "fitScorer", "recommended": "deterministic",
     "tip": "The semantic ATS engine that runs inside Match Scoring — embeds each resume "
            "against the job description (deterministic, no chat cost). Already shipped; "
            "runs as part of fit scoring."},
    {"key": "compliance", "name": "Compliance Agent", "icon": "fa-shield-halved",
     "accent": "green", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for careful reasoning about truthfulness and "
            "evidence verification."},
    {"key": "submission", "name": "Submission Agent", "icon": "fa-paper-plane",
     "accent": "green", "backend": None, "recommended": "gpt-4o",
     "tip": "Best with GPT-4o for reliable form-filling and browser automation reasoning."},
    {"key": "matchScoring", "name": "Match Scoring Agent", "icon": "fa-bullseye",
     "accent": "indigo", "backend": "fitScorer", "recommended": "deterministic",
     "tip": "Deterministic 10-dimension fit scoring + ATS keyword/semantic engine — "
            "scores every discovered job with no LLM cost."},
    {"key": "jobMatching", "name": "Job Matching Agent", "icon": "fa-arrows-to-dot",
     "accent": "indigo", "backend": "matcher", "recommended": "deterministic",
     "tip": "Ranks every fit-scored job and selects the best-fit target for tailoring — "
            "the matcher node of the live pipeline, now runnable on its own. "
            "Deterministic, no LLM cost."},
    {"key": "salaryIntelligence", "name": "Salary Intelligence Agent", "icon": "fa-sack-dollar",
     "accent": "amber", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — aggregates salary data at scale affordably."},
    {"key": "interviewPrep", "name": "Interview Prep Agent", "icon": "fa-comments",
     "accent": "coral", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Best with Claude claude-sonnet-4 for realistic mock interviews and deep reasoning."},
    {"key": "companyResearch", "name": "Company Research Agent", "icon": "fa-building",
     "accent": "indigo", "backend": None, "recommended": "gpt-4o",
     "tip": "Best with GPT-4o for synthesizing company research from web sources."},
    {"key": "skillGap", "name": "Skill Gap Agent", "icon": "fa-code-compare",
     "accent": "green", "backend": "fitScorer", "recommended": "deterministic",
     "tip": "Surfaces the job's missing keywords from the ATS engine "
            "(ATSScore.missing_keywords) — the skill-gap facet of Match Scoring. "
            "Already shipped; deterministic, no LLM cost."},
    {"key": "recruiterOutreach", "name": "Recruiter Outreach Agent", "icon": "fa-handshake",
     "accent": "coral", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Planned: first-touch outbound to a recruiter/contact with no existing thread "
            "(a future dedicated OutreachAgent). Inbox triage and reply/follow-up drafting "
            "already live in the Email Agent."},
    {"key": "emailAgent", "name": "Email Agent", "icon": "fa-envelope",
     "accent": "coral", "backend": "emailAgent", "recommended": "claude-sonnet-4",
     "tip": "Real Gmail-backed inbox triage, evidence-grounded reply and follow-up drafting, "
            "label management and per-thread insights. Sends are approval-gated. Best with "
            "Claude claude-sonnet-4. Connect Gmail (Email Center) to activate live send/sync."},
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
    {"key": "storyExtraction", "name": "Story Extraction Agent", "icon": "fa-book-bookmark",
     "accent": "coral", "backend": "storyExtractor", "recommended": "claude-haiku-4-5-20251001",
     "tip": "Mines the base resume into STAR+R evidence stories for the Story Bank — "
            "runs on the STRUCTURED model tier."},
    {"key": "learningFeedback", "name": "Learning / Feedback Agent", "icon": "fa-graduation-cap",
     "accent": "coral", "backend": None, "recommended": "claude-sonnet-4",
     "tip": "Planned: learns from application outcomes to refine future tailoring."},
    {"key": "orchestration", "name": "Orchestration Agent", "icon": "fa-sitemap",
     "accent": "indigo", "backend": "supervisor", "recommended": "deterministic",
     "tip": "Plans and sequences the live pipeline (supervisor node): scout → fitScorer → "
            "matcher → tailor → coverLetter. Deterministic, no LLM cost."},
    {"key": "notification", "name": "Notification Agent", "icon": "fa-bell",
     "accent": "green", "backend": None, "recommended": "gpt-4o-mini",
     "tip": "Best with GPT-4o-mini — monitors status changes and pushes timely alerts."},
]

_CATALOG_BY_KEY = {a["key"]: a for a in AGENT_CATALOG}
#: Reverse map: backend run name → catalog key (for status derivation).
_BACKEND_TO_KEY = {a["backend"]: a["key"] for a in AGENT_CATALOG if a["backend"]}
#: A single backend can power several catalog facets (fitScorer serves Match
#: Scoring plus its ATS-optimization / skill-gap facets); pin the canonical card
#: so stat displays name the primary agent, not whichever facet sorted last.
_BACKEND_TO_KEY["fitScorer"] = "matchScoring"

#: The 6 AI providers offered by the Agents screen. This is a static catalog
#: of identity/branding only — connection status, active model, and detail
#: strings are derived at request time from the credentials that actually
#: exist in the server environment (see ``_provider_env_state``). Nothing here
#: may claim a connection that does not exist.
PROVIDER_SEED: list[dict[str, Any]] = [
    {"id": "anthropic", "name": "Anthropic Claude", "auth": "API Key",
     "models": [], "icon": "fa-a", "color": "#D97757"},
    {"id": "openrouter", "name": "OpenRouter", "auth": "OAuth + API Key",
     "models": ["deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct"],
     "icon": "fa-route", "color": "#6467F2"},
    {"id": "openai", "name": "OpenAI", "auth": "API Key",
     "models": ["gpt-4o", "gpt-4o-mini", "text-embedding-3-large"], "icon": "fa-brain",
     "color": "#10A37F"},
    {"id": "gemini", "name": "Google Gemini", "auth": "OAuth + API Key",
     "models": ["gemini-2.0-flash"], "icon": "fa-gem", "color": "#4285F4"},
    {"id": "bedrock", "name": "AWS Bedrock", "auth": "Access + Secret Key",
     "models": [], "icon": "fa-aws", "color": "#FF9900"},
    {"id": "groq", "name": "Groq", "auth": "API Key",
     "models": ["llama-3.3-70b-versatile"], "icon": "fa-bolt-lightning", "color": "#F55036"},
    # The Abacus.AI subscription key (ABACUS_API_KEY) is the runtime's last-
    # resort credential in llm_client._call_live's precedence chain. It is a
    # genuine serving path (GAP-P4-055) — not surfacing it here left every
    # tailor/coverLetter/storyExtractor run appearing to come from nowhere
    # while every provider card showed "unconfigured".
    {"id": "abacus", "name": "Abacus Subscription (fallback)", "auth": "API Key",
     "models": [], "icon": "fa-cloud", "color": "#7C3AED"},
]
_PROVIDER_SEED_BY_ID = {p["id"]: p for p in PROVIDER_SEED}

#: Env var that carries each provider's credential.
_PROVIDER_ENV_KEY: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",  # or AETHER_LLM_API_KEY on an Anthropic base URL
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "bedrock": "AWS_ACCESS_KEY_ID",
    "groq": "GROQ_API_KEY",
}


def _provider_env_state(provider_id: str) -> tuple[str, str, str, list[str]]:
    """(status, active_model, detail, models) from the REAL server env.

    A provider is "connected" only when its credential is actually present.
    Anthropic is special-cased: the product's primary LLM path is a direct
    Anthropic token in ``AETHER_LLM_API_KEY`` with an api.anthropic.com base
    URL (subscription token — deliberately NOT routed through OpenRouter).
    """
    import os

    if provider_id == "anthropic":
        base = os.environ.get("AETHER_LLM_BASE_URL", "")
        direct = bool(os.environ.get("AETHER_LLM_API_KEY")) and "anthropic.com" in base
        if direct or os.environ.get("ANTHROPIC_API_KEY"):
            from app.services.llm_client import get_model

            tiers = {get_model(t) for t in ("REASONING", "STRUCTURED", "FAST", "LIGHT")}
            return (
                "connected",
                get_model("REASONING"),
                "Configured via server environment (legacy)",
                sorted(tiers),
            )
        return (
            "unconfigured",
            "",
            "Not configured — add a key in the Agents panel",
            [],
        )

    if provider_id == "abacus":
        if not os.environ.get("ABACUS_API_KEY"):
            return (
                "unconfigured",
                "",
                "Not configured — add a key in the Agents panel",
                [],
            )
        from app.services.llm_client import get_model

        tiers = sorted({get_model(t) for t in ("REASONING", "STRUCTURED", "FAST", "LIGHT")})
        if get_active_credential_env_var() == "ABACUS_API_KEY":
            return (
                "connected",
                get_model("REASONING"),
                "Abacus subscription key configured · actively serving live runs "
                "(fallback path — no OpenRouter/Anthropic key set)",
                tiers,
            )
        return (
            "connected",
            "",
            "Abacus subscription key (server environment) · standby "
            "(a higher-priority OpenRouter/Anthropic key is the active path)",
            tiers,
        )

    seed = _PROVIDER_SEED_BY_ID[provider_id]
    if os.environ.get(_PROVIDER_ENV_KEY[provider_id]):
        # GAP-PC-005 fix: the old string hardcoded "standby (Anthropic is the
        # active path)" for EVERY provider regardless of truth. State only what
        # is actually true — the key is present in the server env — without
        # asserting which provider is serving live runs.
        return (
            "connected",
            "",
            "Configured via server environment (legacy)",
            seed["models"],
        )
    return (
        "unconfigured",
        "",
        "Not configured — add a key in the Agents panel",
        seed["models"],
    )


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
            # Per-user credential/config columns (GAP-D3) live with the table
            # they extend so they are always present whenever AgentConfig is
            # (re)created — even if the credential-tables guard is already set.
            cur.execute(
                'ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "credentialRef" text'
            )
            cur.execute(
                'ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "provider" text'
            )
            cur.execute(
                'ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS "authMode" text'
            )
            cur.execute(
                'ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS '
                '"temperature" double precision DEFAULT 0.7'
            )
            cur.execute(
                'ALTER TABLE "AgentConfig" ADD COLUMN IF NOT EXISTS '
                '"thinkingEffort" text DEFAULT \'medium\''
            )
        conn.commit()
    _tables_ready = True


def _to_output(result: Any) -> dict[str, Any]:
    if is_dataclass(result) and not isinstance(result, type):
        return asdict(result)
    return dict(result) if isinstance(result, dict) else {"result": str(result)}


def _persist_billing_audit(
    runs: AgentRunRepository, run_id: str, audit: dict[str, Any]
) -> None:
    """Best-effort write of the billing audit to AgentRun (never fails a run)."""
    try:
        _ensure_user_agent_tables()
        runs.set_billing_audit(run_id, audit)
    except Exception:  # noqa: BLE001 — audit is additive; a run stays valid
        pass


def _billing_audit(user_id: str, agent_name: str) -> tuple[dict[str, Any], str | None]:
    """Resolve the billing provenance for a run (GAP-D3) without side effects.

    Returns ``(audit, provider)``. Deterministic (non-LLM) agents have no
    provider and record ``{'quotaPath': 'none'}``. For LLM agents the audit
    names the credential source, authMode and provider, and derives the
    ``quotaPath`` — ``subscription`` for a Claude subscription-OAuth token,
    ``metered_api`` for an API key.
    """
    model = _model_for_agent(agent_name)
    if model is None:
        return {"quotaPath": "none"}, None
    provider = resolve_provider(model)
    try:
        cred = resolve_user_credential(provider, user_id, agent_name)
    except Exception:  # noqa: BLE001 — audit must never break a run
        cred = None
    if cred is None:
        return (
            {"credentialSource": "none", "authMode": None,
             "provider": provider, "quotaPath": "none"},
            provider,
        )
    quota_path = "subscription" if cred.auth_mode == "subscription_oauth" else "metered_api"
    return (
        {"credentialSource": cred.source, "authMode": cred.auth_mode,
         "provider": provider, "quotaPath": quota_path},
        provider,
    )


def _quota_429(provider: str, expires_at: Any) -> HTTPException:
    """Build the honest 429 raised when a subscription's quota is exhausted."""
    from datetime import datetime, timezone

    retry_after = int(get_quota_block_hours() * 3600)
    if expires_at is not None:
        try:
            exp = expires_at
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            retry_after = max(1, int((exp - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            pass
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "subscription_quota_exceeded",
            "message": (
                f"Your {provider} subscription quota is exhausted. Runs are paused "
                "until it resets."
            ),
            "retryAfter": retry_after,
            "suggestion": "Switch this agent to API-key billing in Agent Settings.",
        },
    )


def _record_run(
    user_id: str, agent_name: str, params: dict[str, Any], fn: Callable[[], Any]
) -> dict[str, Any]:
    """Execute ``fn`` under an AgentRun audit record.

    The run is executed inside a ``user_credential_context`` so the deep LLM
    call path resolves THIS user's credential (GAP-E5). Billing provenance is
    recorded to ``AgentRun.billingAuditJson`` (GAP-D3), and a prior
    subscription-quota block short-circuits the run with an honest 429 (never a
    silent reroute to another payer).
    """
    runs = AgentRunRepository()
    audit, provider = _billing_audit(user_id, agent_name)
    # Quota cooldown check BEFORE starting a run row — a blocked user gets a
    # clean 429 with no wasted audit record.
    if provider is not None:
        try:
            block = AgentQuotaBlockRepository().get_active(user_id, provider)
        except Exception:  # noqa: BLE001 — block store down → allow the run
            block = None
        if block is not None:
            raise _quota_429(provider, block.get("expiresAt"))
    run = runs.start(user_id, agent_name, params)
    _persist_billing_audit(runs, run["id"], audit)
    started = time.monotonic()
    try:
        with user_credential_context(user_id, agent_name):
            output = _to_output(fn())
    except HTTPException:
        runs.finish(run["id"], "failed", error="http error")
        raise
    except QuotaExhaustedError as exc:
        # Subscription quota exhausted mid-run — record honestly and 429.
        runs.finish(run["id"], "failed", error=str(exc))
        expires_at = exc.expires_at
        if expires_at is None:
            try:
                blk = AgentQuotaBlockRepository().get_active(user_id, exc.provider)
                expires_at = blk.get("expiresAt") if blk else None
            except Exception:  # noqa: BLE001
                expires_at = None
        raise _quota_429(exc.provider, expires_at) from exc
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
    output["billingAudit"] = audit
    # Real cost estimate from the run's *measured* I/O size × the published
    # per-token price of the model the agent ACTUALLY ran on (≈4 chars/token).
    # Deterministic agents (scout/fitScorer/matcher/supervisor) make no LLM
    # calls, so they record zero tokens and zero spend — anything else would
    # fabricate the spend/ROI figures GET /agents/stats reports.
    model = _model_for_agent(agent_name)
    if model is None:
        cost = 0.0
        output["model"] = None
        output["tokensIn"] = 0
        output["tokensOut"] = 0
        output["costUsd"] = 0.0
    else:
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


#: LLM tier each backend agent actually calls through ``llm_client`` — kept in
#: sync with the ``get_model(...)`` calls in the agent implementations.
#: Backends absent here (scout, fitScorer, matcher, supervisor) are
#: deterministic: scraping, embeddings, and plain code — no LLM spend.
_LLM_TIER_BY_BACKEND: dict[str, str] = {
    "tailor": "REASONING",
    "coverLetter": "REASONING",
    "storyExtractor": "STRUCTURED",
    "emailAgent": "REASONING",
}


def _model_for_agent(agent_name: str) -> str | None:
    """The model this backend agent ACTUALLY runs on (resolved from the same
    ``AETHER_MODEL_<TIER>`` env vars the LLM client uses), or None for
    deterministic agents that make no LLM calls. Costing against the model
    that really served the run keeps spend/ROI figures genuine."""
    tier = _LLM_TIER_BY_BACKEND.get(agent_name)
    if tier is None:
        return None
    from app.services.llm_client import get_model

    return get_model(tier)


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
    if name in ("matcher", "job-matching", "jobMatching"):
        from app.agents.matcher_agent import MatcherAgent

        return _record_run(
            user_id, "matcher", params, lambda: MatcherAgent().run(user_id)
        )
    if name in ("emailAgent", "email-agent", "email"):
        from app.agents.email_agent import EmailAgent

        return _record_run(
            user_id, "emailAgent", params, lambda: EmailAgent().run(user_id, **params)
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
    return {
        "status": "accepted",
        "persisted": output["persisted"],
        "updated": output.get("updated", 0),
        "errors": output["errors"],
        # Honest per-source breakdown (GAP-SRC-002): {source, fetched,
        # persisted, updated, error, status} — a failing source is surfaced
        # here as status="error", never as a silent persisted=0.
        "per_source": output.get("per_source", []),
    }


@router.get("/scout/sources")
def scout_sources(current_user: CurrentUser) -> list[dict[str, Any]]:
    """Latest per-source discovery sync status for the authenticated user."""
    from app.repositories.job_source_status import JobSourceStatusRepository

    return JobSourceStatusRepository().list_by_user(current_user["id"])


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
        "conversionMetrics": output["conversionMetrics"],
    }


@router.post("/cover-letter/run")
def run_cover_letter(body: JobTargetRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Draft a fabrication-guarded cover letter; requires human approval (P2-S06)."""
    from app.agents.cover_letter_agent import FabricationError, StructuralError

    try:
        output = _dispatch(current_user["id"], "coverLetter", body.model_dump())
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except FabricationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cover letter rejected by fabrication guard: {exc.flagged}",
        ) from exc
    except StructuralError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cover letter rejected — §10.2 format contract not met: {exc.issues}",
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


class EmailAgentRequest(BaseModel):
    mode: str = Field(default="triage")
    thread_id: str | None = None
    to: str | None = None
    subject: str | None = None
    body: str | None = None
    #: Optional PDFs to attach on an approved send (resolved in-process at
    #: execute time). Only ids travel — never the bytes.
    attach_resume_id: str | None = None
    attach_cover_letter_id: str | None = None


@router.post("/email/run")
def run_email_agent(body: EmailAgentRequest, current_user: CurrentUser) -> dict[str, Any]:
    """Run the Email Agent: triage / draft_reply / insights / send (P4).

    Gmail-backed when the user has connected Gmail; otherwise degrades honestly
    to local ``EmailThread`` rows (never fabricates inbox data). ``send`` mode
    never sends directly — it opens a pending ``email_send`` approval so the
    human-in-the-loop gate always adjudicates a real outbound email.
    """
    params = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return _dispatch(current_user["id"], "emailAgent", params)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


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

    from app.agents.matcher_agent import MatcherAgent

    # Matcher node: ranks scored jobs and selects the top match (audit-recorded).
    # Reuses the now first-class MatcherAgent so the pipeline and the standalone
    # /agents/matcher/run trigger share one implementation.
    match_out = _record_run(user_id, "matcher", {}, lambda: MatcherAgent().run(user_id))
    steps.append({"agent": "matcher", "output": match_out})

    top_job_id = match_out.get("top_job_id")
    if not top_job_id:
        return {"status": "completed", "steps": steps, "approvalRequired": False}
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


#: Full per-agent config projection (extended columns added by the lazy DDL).
_AGENT_CONFIG_COLS = (
    '"agentKey", "enabled", "model", "provider", "authMode", "credentialRef", '
    '"temperature", "thinkingEffort"'
)


def _ensure_agent_config_schema() -> None:
    """Ensure the AgentConfig table AND its per-user credential columns exist."""
    _ensure_agents_tables()
    _ensure_user_agent_tables()


def _config_map(user_id: str) -> dict[str, dict[str, Any]]:
    _ensure_agent_config_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_AGENT_CONFIG_COLS} FROM "AgentConfig" WHERE "userId" = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return {r["agentKey"]: r for r in rows}


def _config_defaults(agent_key: str) -> dict[str, Any]:
    """The default config for an agent with no persisted row."""
    entry = _CATALOG_BY_KEY[agent_key]
    return {
        "key": agent_key,
        "agentKey": agent_key,
        "enabled": True,
        "model": entry["recommended"],
        "provider": None,
        "authMode": None,
        "credentialRef": None,
        "temperature": 0.7,
        "thinkingEffort": "medium",
    }


def _config_response(agent_key: str, row: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a persisted row over the agent defaults for GET/PUT responses."""
    out = _config_defaults(agent_key)
    if row:
        for k in ("enabled", "model", "provider", "authMode", "credentialRef",
                  "temperature", "thinkingEffort"):
            if row.get(k) is not None:
                out[k] = row[k]
    out["key"] = agent_key
    return out


@router.get("/catalog")
def agent_catalog(current_user: CurrentUser) -> dict[str, Any]:
    """Full agent catalog merged with persisted config + real run status.

    ``status`` is derived from live data: an agent whose latest AgentRun failed
    is ``error``; a disabled agent is ``paused``; an implemented agent is
    ``active``. Catalog entries with no backend implementation are ``planned``
    — they are roadmap cards and are never presented as running (no fabricated
    activity). ``model`` is the model the agent ACTUALLY runs on ("deterministic"
    for non-LLM agents, "—" for planned ones).
    """
    user_id = current_user["id"]
    cfg = _config_map(user_id)
    last = AgentRunRepository().last_run_by_agent(user_id)
    agents: list[dict[str, Any]] = []
    active = paused = error = planned = 0
    for entry in AGENT_CATALOG:
        key = entry["key"]
        c = cfg.get(key, {})
        enabled = bool(c.get("enabled", True))
        backend = entry["backend"]
        run = last.get(backend) if backend else None
        if backend is None:
            state = "planned"
            planned += 1
            model = "—"
        else:
            model = _model_for_agent(backend) or "deterministic"
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
                "runnable": backend in ("scout", "fitScorer", "matcher", "tailor",
                                        "coverLetter", "storyExtractor", "emailAgent"),
                "backend": backend,
                "enabled": enabled,
                "status": state,
                "last_run": run["createdAt"].isoformat() if run else None,
            }
        )
    return {
        "agents": agents,
        "counts": {
            "total": len(agents),
            "active": active,
            "paused": paused,
            "error": error,
            "planned": planned,
        },
    }


class AgentConfigUpdate(BaseModel):
    enabled: bool | None = None
    model: str | None = Field(default=None, min_length=1)
    provider: str | None = None
    authMode: str | None = Field(default=None, pattern="^(api_key|subscription_oauth)$")
    #: Empty string clears the pinned credential; a non-empty value must
    #: reference one of the caller's own stored credentials (validated below).
    credentialRef: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thinkingEffort: str | None = Field(default=None, pattern="^(none|low|medium|high)$")


#: Deterministic (non-LLM) agents — their config panel disables temperature.
_DETERMINISTIC_BACKENDS = frozenset(
    {"scout", "fitScorer", "matcher", "supervisor"}
)


@router.get("/config")
def list_agent_config(current_user: CurrentUser) -> list[dict[str, Any]]:
    """Full per-agent config for every catalog agent (persisted values merged)."""
    cfg = _config_map(current_user["id"])
    return [_config_response(a["key"], cfg.get(a["key"])) for a in AGENT_CATALOG]


@router.get("/config/{agent_key}")
def get_agent_config(agent_key: str, current_user: CurrentUser) -> dict[str, Any]:
    """One agent's persisted config merged over defaults (was 405 — GAP-D3)."""
    if agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{agent_key}'")
    cfg = _config_map(current_user["id"])
    return _config_response(agent_key, cfg.get(agent_key))


@router.put("/config/{agent_key}")
def update_agent_config(
    agent_key: str, body: AgentConfigUpdate, current_user: CurrentUser
) -> dict[str, Any]:
    """Persist ALL per-agent settings (partial update merges over existing).

    Fields: enabled, model, provider, authMode, credentialRef, temperature
    (0.0–2.0; out of range → 422), thinkingEffort (none|low|medium|high). A
    non-empty ``credentialRef`` must reference one of the caller's own stored
    credentials — a dangling ref is rejected 422 rather than silently pinned.
    """
    if agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{agent_key}'")
    entry = _CATALOG_BY_KEY[agent_key]
    user_id = current_user["id"]
    _ensure_agent_config_schema()

    # Validate a non-empty credentialRef belongs to THIS user (never cross-user).
    cred_ref_update = body.credentialRef
    if cred_ref_update:
        owned = {c["id"] for c in UserProviderCredentialRepository().list_masked(user_id)}
        if cred_ref_update not in owned:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "credentialRef does not reference one of your stored credentials.",
            )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT {_AGENT_CONFIG_COLS} FROM "AgentConfig" '
                'WHERE "userId" = %s AND "agentKey" = %s',
                (user_id, agent_key),
            )
            existing = rows_to_dicts(cur)
            row0 = existing[0] if existing else {}
            enabled = row0.get("enabled", True) if body.enabled is None else body.enabled
            model = (
                (row0.get("model") if existing else entry["recommended"])
                if body.model is None else body.model
            )
            provider = row0.get("provider") if body.provider is None else body.provider
            auth_mode = row0.get("authMode") if body.authMode is None else body.authMode
            if body.credentialRef is None:
                credential_ref = row0.get("credentialRef")
            else:
                credential_ref = cred_ref_update or None  # "" clears the pin
            temperature = (
                (row0.get("temperature") if existing else 0.7)
                if body.temperature is None else body.temperature
            )
            thinking = (
                (row0.get("thinkingEffort") if existing else "medium")
                if body.thinkingEffort is None else body.thinkingEffort
            )
            cur.execute(
                f'''
                INSERT INTO "AgentConfig" ("userId", "agentKey", "enabled", "model",
                    "provider", "authMode", "credentialRef", "temperature",
                    "thinkingEffort", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT ("userId", "agentKey")
                DO UPDATE SET "enabled" = EXCLUDED."enabled", "model" = EXCLUDED."model",
                              "provider" = EXCLUDED."provider",
                              "authMode" = EXCLUDED."authMode",
                              "credentialRef" = EXCLUDED."credentialRef",
                              "temperature" = EXCLUDED."temperature",
                              "thinkingEffort" = EXCLUDED."thinkingEffort",
                              "updatedAt" = NOW()
                RETURNING {_AGENT_CONFIG_COLS}
                ''',
                (user_id, agent_key, enabled, model, provider, auth_mode,
                 credential_ref, temperature, thinking),
            )
            row = rows_to_dicts(cur)[0]
        conn.commit()
    return _config_response(agent_key, row)


#: The provider ids that support stored (encrypted-vault) credentials — exactly
#: the 6 real ids already backed by an env key in ``_PROVIDER_ENV_KEY``. The
#: abacus fallback and any others keep behaving as today (no credential CRUD).
_CREDENTIAL_PROVIDERS = frozenset(_PROVIDER_ENV_KEY)


def _env_secret_for(provider_id: str) -> str | None:
    """The raw env secret backing ``provider_id``'s 'environment' source, if any.

    Used ONLY to derive the masked last-4 hint + authMode for an env-sourced
    provider; the value never leaves this module.
    """
    import os

    if provider_id == "anthropic":
        base = os.environ.get("AETHER_LLM_BASE_URL", "")
        direct = os.environ.get("AETHER_LLM_API_KEY")
        if direct and "anthropic.com" in base:
            return direct
        return os.environ.get("ANTHROPIC_API_KEY")
    if provider_id == "abacus":
        return os.environ.get("ABACUS_API_KEY")
    key_var = _PROVIDER_ENV_KEY.get(provider_id)
    return os.environ.get(key_var) if key_var else None


def _provider_db_masked(provider_id: str) -> dict[str, Any] | None:
    """Masked DB credential row for a supported provider, or None.

    Degrades to None on ANY read error (missing table / DB hiccup) so the
    providers panel never fails because the credential store is unavailable.
    """
    if provider_id not in _CREDENTIAL_PROVIDERS:
        return None
    try:
        return ProviderCredentialRepository().get_masked(provider_id)
    except Exception:  # noqa: BLE001 — providers panel must stay up
        return None


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (value or None)


def _build_provider_entry(
    seed: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    """One provider's honest status: DB credential FIRST, then env, then none.

    ``source`` is the truth about where a live credential would come from
    (``database`` / ``environment`` / ``none``); a provider is never shown
    ``connected`` without a real credential (D-0020). A persisted per-user
    override may only DOWNGRADE a connected provider or pick a preferred model.
    """
    provider_id = seed["id"]
    env_status, env_model, env_detail, env_models = _provider_env_state(provider_id)
    # A stored credential is only usable when the vault key is present; without
    # it the ciphertext can't be decrypted, so per ADR-PC-3 the read degrades to
    # the env source (or none) instead of dishonestly claiming a DB connection.
    db = _provider_db_masked(provider_id) if credential_vault.key_present() else None
    if db:
        source = "database"
        status = "connected"
        auth_mode = db.get("authMode")
        secret_hint = db.get("secretHint")
        base_url = db.get("baseUrl")
        last_verified_at = _iso_or_none(db.get("lastVerifiedAt"))
        last_verify_status = db.get("lastVerifyStatus")
        detail = f"Credential stored in the encrypted vault ({secret_hint})"
        if last_verify_status:
            detail += f" · last verify: {last_verify_status}"
    elif env_status == "connected":
        source = "environment"
        status = "connected"
        secret = _env_secret_for(provider_id)
        if provider_id == "anthropic" and secret:
            auth_mode = _infer_anthropic_auth_mode(secret)
        else:
            auth_mode = "api_key" if secret else None
        secret_hint = credential_vault.secret_hint(secret) if secret else None
        base_url = None
        last_verified_at = None
        last_verify_status = None
        detail = env_detail
    else:
        source = "none"
        status = "unconfigured"
        auth_mode = None
        secret_hint = None
        base_url = None
        last_verified_at = None
        last_verify_status = None
        detail = env_detail
    if override.get("status") in ("warning", "unconfigured") and status == "connected":
        status = override["status"]
    model = override.get("model") or env_model
    return {
        "id": provider_id,
        "label": seed["name"],
        "name": seed["name"],
        "auth": seed["auth"],
        "icon": seed["icon"],
        "color": seed["color"],
        "models": env_models,
        "status": status,
        "source": source,
        "authMode": auth_mode,
        "secretHint": secret_hint,
        "baseUrl": base_url,
        "lastVerifiedAt": last_verified_at,
        "lastVerifyStatus": last_verify_status,
        "model": model if status == "connected" else "",
        "detail": detail,
    }


def _user_provider_overrides(user_id: str) -> dict[str, dict[str, Any]]:
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "provider", "status", "model", "detail" FROM "AgentProvider" '
                'WHERE "userId" = %s',
                (user_id,),
            )
            return {r["provider"]: r for r in rows_to_dicts(cur)}


def _provider_status_object(provider_id: str, user_id: str) -> dict[str, Any]:
    """Full masked status object for a single provider (PUT/DELETE responses)."""
    override = _user_provider_overrides(user_id).get(provider_id, {})
    return _build_provider_entry(_PROVIDER_SEED_BY_ID[provider_id], override)


@router.get("/providers")
def list_providers(current_user: CurrentUser) -> list[dict[str, Any]]:
    """The AI providers with connection state derived from real credentials.

    Status is DB-first with an honest ``source`` (``database``/``environment``/
    ``none``): a stored encrypted-vault credential wins, else a legacy env key
    (ADR-PC-4), else unconfigured. A provider can never show ``connected``
    without an actual credential (D-0020). A persisted user override may only
    DOWNGRADE a connected provider or pick a preferred model — never upgrade a
    keyless provider to connected. Secrets are masked to a last-4 hint only.
    """
    overrides = _user_provider_overrides(current_user["id"])
    return [
        _build_provider_entry(seed, overrides.get(seed["id"], {}))
        for seed in PROVIDER_SEED
    ]


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
    env_status, env_model, env_detail, _env_models = _provider_env_state(provider)
    if body.status == "connected" and env_status != "connected":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{provider}' has no credential configured — add one in the Agents "
            "panel before marking it connected.",
        )
    _ensure_agents_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status", "model", "detail" FROM "AgentProvider" '
                'WHERE "userId" = %s AND "provider" = %s',
                (current_user["id"], provider),
            )
            existing = rows_to_dicts(cur)
            cur_status = existing[0]["status"] if existing else env_status
            cur_model = existing[0]["model"] if existing else env_model
            new_status = cur_status if body.status is None else body.status
            new_model = cur_model if body.model is None else body.model
            detail = env_detail
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


# ---------------------------------------------------------------------------
# Provider credential CRUD + verification (PROVIDER-CONFIG-RUN §1 contract).
# Fully in-UI, encrypted at rest (ADR-PC-3), no cross-provider billing.
# ---------------------------------------------------------------------------


class ProviderCredentialBody(BaseModel):
    authMode: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    baseUrl: str | None = None


def _validate_provider_auth(provider: str, auth_mode: str, secret: str) -> None:
    """Reject an authMode/secret that does not match the provider (REQ-PC-2/3).

    Anthropic accepts ``api_key`` (``sk-ant-api…``) or ``subscription_oauth``
    (``sk-ant-oat…``) with the matching key prefix; every other provider
    accepts only ``api_key``.
    """
    if provider == "anthropic":
        if auth_mode == "api_key":
            if not secret.startswith("sk-ant-api"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Anthropic api_key must start with 'sk-ant-api'.",
                )
        elif auth_mode == "subscription_oauth":
            if not secret.startswith("sk-ant-oat"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Anthropic subscription_oauth token must start with 'sk-ant-oat'.",
                )
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Anthropic accepts authMode 'api_key' or 'subscription_oauth'.",
            )
    elif auth_mode != "api_key":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Provider '{provider}' accepts only authMode 'api_key'.",
        )


@router.put("/providers/{provider}/credential")
def put_provider_credential(
    provider: str, body: ProviderCredentialBody, current_user: CurrentUser
) -> dict[str, Any]:
    """Store (encrypt) a provider credential entirely in-UI; return masked row.

    Honest failures: an unknown/unsupported provider is 404; a mismatched
    authMode/prefix is 422; a missing ``AETHER_CREDENTIAL_KEY`` is a 503 (the
    secret is never stored in the clear — ADR-PC-3).
    """
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support stored credentials.",
        )
    _validate_provider_auth(provider, body.authMode, body.secret)
    if not credential_vault.key_present():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not "
            "configured on the server.",
        )
    try:
        ProviderCredentialRepository().upsert(
            provider, auth_mode=body.authMode, secret=body.secret, base_url=body.baseUrl
        )
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        ) from exc
    return _provider_status_object(provider, current_user["id"])


@router.delete("/providers/{provider}/credential")
def delete_provider_credential(
    provider: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Remove a stored credential; status falls back to the env source (ADR-PC-4)."""
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support stored credentials.",
        )
    ProviderCredentialRepository().delete(provider)
    return _provider_status_object(provider, current_user["id"])


@router.post("/providers/{provider}/verify")
def verify_provider(provider: str, current_user: CurrentUser) -> dict[str, Any]:
    """Perform a REAL provider round-trip and record the honest result (REQ-PC-7).

    Never marks a credential verified without a genuine 2xx. The result is
    stamped onto the stored row (when one exists) as ``lastVerifiedAt`` /
    ``lastVerifyStatus``.
    """
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support verification.",
        )
    ok, status_token, detail = verify_provider_credential(provider)
    ProviderCredentialRepository().mark_verified(provider, "ok" if ok else "failed")
    return {"ok": ok, "status": status_token, "detail": detail}


# ---------------------------------------------------------------------------
# Per-user provider credentials (GAP-D1/E5) — encrypted, per-user, verified on
# save (GAP-NEW-001). Distinct from the deployment-wide /providers/{p}/credential
# routes above: these bill against the SIGNED-IN user's own key/subscription.
# ---------------------------------------------------------------------------


@router.get("/user/providers")
def list_user_credentials(current_user: CurrentUser) -> list[dict[str, Any]]:
    """This user's stored provider credentials, masked (never the secret)."""
    rows = UserProviderCredentialRepository().list_masked(current_user["id"])
    for r in rows:
        r["lastVerifiedAt"] = _iso_or_none(r.get("lastVerifiedAt"))
        r["expiresAt"] = _iso_or_none(r.get("expiresAt"))
        r["createdAt"] = _iso_or_none(r.get("createdAt"))
        r["updatedAt"] = _iso_or_none(r.get("updatedAt"))
    return rows


def _user_credential_masked(user_id: str, provider: str) -> dict[str, Any]:
    row = UserProviderCredentialRepository().get_masked(user_id, provider) or {
        "provider": provider,
        "authMode": None,
        "secretHint": None,
        "lastVerifiedAt": None,
        "lastVerifyStatus": None,
    }
    row["lastVerifiedAt"] = _iso_or_none(row.get("lastVerifiedAt"))
    row["expiresAt"] = _iso_or_none(row.get("expiresAt"))
    row["createdAt"] = _iso_or_none(row.get("createdAt"))
    row["updatedAt"] = _iso_or_none(row.get("updatedAt"))
    return row


@router.put("/user/providers/{provider}/credential")
def put_user_credential(
    provider: str, body: ProviderCredentialBody, current_user: CurrentUser
) -> dict[str, Any]:
    """Store THIS user's encrypted credential, then verify it (GAP-NEW-001).

    After the secret is stored a real verify round-trip runs so the 'connected'
    badge reflects a genuine result — a failed verify records ``failed`` (never
    a fake ``ok``). The secret never leaves the server; only a last-4 hint and
    the honest verify status are returned.
    """
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support stored credentials.",
        )
    _validate_provider_auth(provider, body.authMode, body.secret)
    if not credential_vault.key_present():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not "
            "configured on the server.",
        )
    user_id = current_user["id"]
    repo = UserProviderCredentialRepository()
    try:
        repo.upsert(
            user_id, provider, auth_mode=body.authMode,
            secret=body.secret, base_url=body.baseUrl,
        )
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # GAP-NEW-001: verify round-trip so the badge is truthful (best-effort).
    try:
        ok, _token, _detail = verify_user_credential(provider, user_id)
        repo.mark_verified(user_id, provider, "ok" if ok else "failed")
    except Exception:  # noqa: BLE001 — a verify outage must not fail the save
        pass
    return _user_credential_masked(user_id, provider)


@router.delete("/user/providers/{provider}/credential")
def delete_user_credential(
    provider: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Remove THIS user's stored credential for a provider."""
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support stored credentials.",
        )
    UserProviderCredentialRepository().delete(current_user["id"], provider)
    return _user_credential_masked(current_user["id"], provider)


@router.post("/user/providers/{provider}/verify")
def verify_user_provider(provider: str, current_user: CurrentUser) -> dict[str, Any]:
    """Real round-trip against THIS user's stored credential; honest result."""
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support verification.",
        )
    user_id = current_user["id"]
    ok, status_token, detail = verify_user_credential(provider, user_id)
    UserProviderCredentialRepository().mark_verified(
        user_id, provider, "ok" if ok else "failed"
    )
    return {"ok": ok, "status": status_token, "detail": detail}


# ---------------------------------------------------------------------------
# Anthropic subscription OAuth (PKCE) — GAP-D1.
# ---------------------------------------------------------------------------


@router.get("/auth/anthropic/start")
def anthropic_oauth_start(current_user: CurrentUser) -> dict[str, Any]:
    """Begin the Anthropic subscription OAuth flow; return the consent URL.

    Honest 501 when the deployment has no OAuth client id (never fakes a URL).
    """
    if not anthropic_oauth.is_configured():
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "error": "not_configured",
                "message": (
                    "Anthropic subscription OAuth is not configured on this "
                    "server (AETHER_ANTHROPIC_OAUTH_CLIENT_ID is unset). Use an "
                    "API key instead, or ask the operator to enable OAuth."
                ),
            },
        )
    user_id = current_user["id"]
    verifier, challenge = anthropic_oauth.generate_pkce()
    state_token = anthropic_oauth.sign_state(user_id)
    AnthropicOAuthStateRepository().create(state_token, user_id, verifier)
    return {
        "authorizeUrl": anthropic_oauth.build_authorize_url(challenge, state_token),
        "state": state_token,
    }


@router.get("/auth/anthropic/callback")
def anthropic_oauth_callback(
    current_user: CurrentUser, code: str, state: str
) -> dict[str, Any]:
    """Exchange the authorization code for tokens; store encrypted; masked reply.

    Validates the signed state, single-uses the persisted state row, exchanges
    the code with PKCE, encrypts the access+refresh tokens, and upserts both the
    OAuth token store and the user's ``subscription_oauth`` credential. Returns
    only ``{authMode, hint}`` — NEVER the token.
    """
    if not anthropic_oauth.is_configured():
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail={"error": "not_configured", "message": "OAuth is not configured."},
        )
    try:
        state_user = anthropic_oauth.verify_state(state)
    except Exception as exc:  # noqa: BLE001 — bad signature/expired state
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state."
        ) from exc
    if state_user != current_user["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state user mismatch.")
    row = AnthropicOAuthStateRepository().consume(state)
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "OAuth state unknown or already used."
        )
    if not credential_vault.key_present():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential encryption unavailable: AETHER_CREDENTIAL_KEY is unset.",
        )
    try:
        tokens = anthropic_oauth.exchange_code(code, row["codeVerifier"])
    except anthropic_oauth.OAuthExchangeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Anthropic token exchange failed: {exc}"
        ) from exc
    masked = anthropic_oauth.persist_tokens(current_user["id"], tokens)
    return masked


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

    Returns the model the agent actually runs on, an estimated token count and
    cost from the provider's published per-token pricing, and — instead of a
    simulated figure — the REAL cost/tokens/duration of the agent's most
    recent completed run (null when it has never run). Never invokes the live
    LLM, so it is safe to call repeatedly and honestly charges nothing.
    """
    if body.agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{body.agent_key}'")
    entry = _CATALOG_BY_KEY[body.agent_key]
    backend = entry["backend"]
    model = _model_for_agent(backend) if backend else None
    est_cost = None
    est_tokens: int | None = None
    if model is not None:
        price_in, price_out = _price_for(model)
        est_tokens_in, est_tokens_out = 2800, 1400
        est_tokens = est_tokens_in + est_tokens_out
        est_cost = round(
            est_tokens_in / 1000 * price_in + est_tokens_out / 1000 * price_out, 3
        )
    # Real figures from the last completed run of this backend, if any.
    actual_cost = actual_tokens = response_seconds = None
    if backend:
        last = AgentRunRepository().last_run_by_agent(current_user["id"]).get(backend)
        out = (last or {}).get("output") or {}
        if last and last.get("status") == "completed":
            actual_cost = out.get("costUsd")
            t_in, t_out = out.get("tokensIn"), out.get("tokensOut")
            if t_in is not None and t_out is not None:
                actual_tokens = t_in + t_out
            if out.get("duration_ms") is not None:
                response_seconds = round(out["duration_ms"] / 1000, 1)
    return {
        "agent_key": body.agent_key,
        "name": entry["name"],
        "model": model,
        "estTokens": est_tokens,
        "estCost": est_cost,
        "actualCost": actual_cost,
        "actualTokens": actual_tokens,
        "responseSeconds": response_seconds,
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
