"""Agents router — trigger + audit agent runs (P2-S02 → P2-S08).

Every run is recorded as an ``AgentRun`` row (status, input, output, error,
timestamps) so the dashboard and analytics can reconstruct what the system
did and why. High-risk outputs (tailored resumes, cover letters) surface an
``approvalRequired`` flag — nothing is submitted without human sign-off.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import re
import secrets
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.agents.scout_agent import ScoutAgent
from app.db import ensure_user_profile_columns, get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser
from app.repositories.agent_run import AgentRunRepository
from app.repositories.background_jobs import BackgroundJobRepository
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    subscription_gate_enabled,
)
from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    AnthropicOAuthStateRepository,
    AnthropicOAuthTokenRepository,
    UserProviderCredentialRepository,
    _ensure_user_agent_tables,
)
from app.services import credential_vault
from app.services.discovery.query_builder import ROLE_FAMILY_QUERY, build_scout_query
from app.services.llm_client import (
    LLM_UNAVAILABLE_USER_MESSAGE,
    LLMUnavailableError,
    QuotaExhaustedError,
    _infer_anthropic_auth_mode,
    get_active_credential_env_var,
    get_quota_block_hours,
    resolve_provider,
    resolve_user_credential,
    user_credential_context,
    user_model_context,
    verify_provider_credential,
    verify_user_credential,
)

router = APIRouter()

logger = logging.getLogger(__name__)

#: Last-resort discovery targets used only when the user has NOT configured a
#: target role/location on their profile (see ``_user_search_defaults``).
_DEFAULT_QUERY = ROLE_FAMILY_QUERY
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
    # Static table first (curated, always-available); then the live catalog
    # cache so a user-chosen model is costed at its REAL price (budget accuracy —
    # GAP-P7-MODEL-CHOICE-001); finally a bounded default so spend never reads 0.
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    from app.services.llm_client import cached_model_price

    cached = cached_model_price(model)
    return cached if cached is not None else _DEFAULT_PRICE


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
     # No hardcoded seed models: OpenRouter's model list is the LIVE catalog
     # (GET /agents/providers/openrouter/models, 330+ models) shown by the model
     # picker. A stale 2-item seed here made the provider-card <select> look like
     # "only 2 OpenRouter models exist" (GAP-P7-MODEL-CHOICE-002, user report).
     "models": [],
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
    names the credential source, authMode and provider; the ``quotaPath`` is
    ``metered_api`` for every supported credential (consumer subscription OAuth
    was removed for compliance — GAP-AUTH-001).
    """
    # Reflect the user's chosen model so the audit names the credential/provider
    # of the model that will ACTUALLY serve the run (GAP-P7-MODEL-CHOICE-001).
    model = _model_for_agent(agent_name, override=_user_model_override(user_id, agent_name))
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
    # Consumer subscription OAuth is removed (GAP-AUTH-001): every supported
    # credential (api_key / env) bills as metered API usage.
    return (
        {"credentialSource": cred.source, "authMode": cred.auth_mode,
         "provider": provider, "quotaPath": "metered_api"},
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


def _plan_quota_429(code: str, quota: dict[str, Any] | None) -> HTTPException:
    """Honest 429 for the plan run-quota / USD spend-cap gate (GAP-P6-BILL-002).

    Distinct from the subscription-provider cooldown 429 (``_quota_429``): this
    is the billing plan quota. Carries an upgrade CTA (``/pricing``) and the
    period reset time so the UI can prompt an upgrade or a wait.
    """
    runs_used = int(quota["runsUsed"]) if quota else None
    runs_allowed = int(quota["runsAllowed"]) if quota else None
    period_end = quota.get("periodEnd") if quota else None
    reset = period_end.isoformat() if period_end is not None else None
    if code == "spend_cap_exceeded":
        message = (
            "Your monthly spend cap has been reached. Runs are paused until the "
            "period resets or the cap is raised."
        )
    elif runs_allowed is not None:
        message = f"You've used all {runs_allowed} agent runs this period."
    else:
        message = "You've reached your plan's run quota this period."
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": code,
            "message": message,
            "runsUsed": runs_used,
            "runsAllowed": runs_allowed,
            "upgradeUrl": "/pricing",
            "quotaReset": reset,
        },
    )


#: Header carrying the shared secret for the scoped SYSTEM-RUN exemption
#: (ADR-P7-05 / GAP-P7-DISCOVERY-001).
SYSTEM_RUN_HEADER = "X-Aether-System-Run"

#: The ONLY agent keys the SYSTEM-RUN exemption may ever bypass the
#: subscription gate for — exactly the two calls the platform's own
#: discovery cron makes (``scripts/discovery_cron.sh``: scout, then
#: fit-scorer). Enforced here (not just by which routes read the header) so
#: the exemption can never be widened by wiring the header into another
#: route later without also touching this allowlist.
_SYSTEM_RUN_EXEMPT_AGENTS = frozenset({"scout", "fitScorer"})


def _system_run_secret() -> str | None:
    """The configured system-run shared secret, or ``None`` when unset/empty.

    Read fresh from the environment on every call (not cached at import
    time) so the feature can be enabled/disabled and tests can monkeypatch it
    per-case, same convention as ``subscription_gate_enabled``.
    """
    secret = os.environ.get("AETHER_SYSTEM_RUN_SECRET", "")
    return secret or None


def _is_system_run(request: Request | None) -> bool:
    """True iff ``request`` carries a valid ``X-Aether-System-Run`` secret.

    ADR-P7-05 (GAP-P7-DISCOVERY-001): a scoped exemption for the platform's
    OWN scheduled discovery automation, which necessarily runs as a real user
    account and would otherwise be walled by GAP-P6-PAYWALL exactly like any
    other unpaid user. Disabled entirely when ``AETHER_SYSTEM_RUN_SECRET`` is
    unset/empty — the header is then IGNORED, never a bypass-by-omission.
    Constant-time compare (``secrets.compare_digest``) to avoid a timing
    side-channel on the shared secret.
    """
    if request is None:
        return False
    expected = _system_run_secret()
    if expected is None:
        return False
    provided = request.headers.get(SYSTEM_RUN_HEADER)
    if not provided:
        return False
    return secrets.compare_digest(provided, expected)


def _require_active_subscription(
    user_id: str, *, agent_name: str, system_run: bool = False
) -> None:
    """Entitlement gate (GAP-P6-PAYWALL): Aether is subscription-gated.

    Runs BEFORE any billing/quota work in ``_record_run`` so a user without an
    ACTIVE PAID subscription cannot execute ANY actionable agent (metered LLM
    agents AND deterministic ones — the whole pipeline is walled). Raises an
    honest HTTP 402 ``subscription_required`` pointing at ``/pricing``; it never
    fabricates access. Gated behind ``AETHER_REQUIRE_PAID_SUBSCRIPTION`` (default
    ON) — when the operator sets it 'false' the freemium Free-tier path applies.

    ``system_run`` (ADR-P7-05) skips ONLY this check, and ONLY for
    ``agent_name`` in ``_SYSTEM_RUN_EXEMPT_AGENTS`` — every other guard below
    this call (quota block, plan quota reserve, spend cap) is unaffected.
    """
    if not subscription_gate_enabled():
        return
    if system_run and agent_name in _SYSTEM_RUN_EXEMPT_AGENTS:
        return
    if SubscriptionRepository().has_active_paid_subscription(user_id):
        return
    raise HTTPException(
        status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "error": "subscription_required",
            "message": (
                "An active subscription is required to use Aether. "
                "Subscribe to unlock."
            ),
            "upgradeUrl": "/pricing",
        },
    )


#: Set to a BackgroundJob id while an async pipeline worker runs ``_pipeline_core``
#: so each metered step's reserve/refund is counted on THAT job (reviewer
#: BLOCKING-3 — reservation-scoped pipeline refund). Default None: the sync path
#: and single-agent worker never set it, so the counting is a guarded no-op there.
_pipeline_job_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_pipeline_bg_job", default=None
)


def _record_run(
    user_id: str,
    agent_name: str,
    params: dict[str, Any],
    fn: Callable[[], Any],
    *,
    system_run: bool = False,
) -> dict[str, Any]:
    """Execute ``fn`` under an AgentRun audit record.

    The run is executed inside a ``user_credential_context`` so the deep LLM
    call path resolves THIS user's credential (GAP-E5). Billing provenance is
    recorded to ``AgentRun.billingAuditJson`` (GAP-D3), and a prior
    subscription-quota block short-circuits the run with an honest 429 (never a
    silent reroute to another payer).

    ``system_run`` (ADR-P7-05 / GAP-P7-DISCOVERY-001): True only when the
    caller verified a valid ``X-Aether-System-Run`` secret (see
    ``_is_system_run``); marks the run's billing audit ``systemRun: true`` so
    the exemption is honestly traceable, and is otherwise inert here — the
    actual gate skip happens (scoped to ``agent_name``) in
    ``_require_active_subscription``.
    """
    # Entitlement gate FIRST (GAP-P6-PAYWALL): no active paid subscription -> an
    # honest 402 before any audit row, quota reserve, or LLM call.
    _require_active_subscription(user_id, agent_name=agent_name, system_run=system_run)
    runs = AgentRunRepository()
    audit, provider = _billing_audit(user_id, agent_name)
    if system_run:
        audit["systemRun"] = True
    # Quota cooldown check BEFORE starting a run row — a blocked user gets a
    # clean 429 with no wasted audit record.
    if provider is not None:
        try:
            block = AgentQuotaBlockRepository().get_active(user_id, provider)
        except Exception:  # noqa: BLE001 — block store down → allow the run
            block = None
        if block is not None:
            raise _quota_429(provider, block.get("expiresAt"))

    # Plan quota gate (GAP-P6-BILL-002): atomically RESERVE one run BEFORE the
    # run row is created. Only metered agents (those that actually call the LLM)
    # consume quota — deterministic agents (scout/fitScorer/matcher/supervisor)
    # make no LLM calls and pass through unmetered. The USD spend cap is checked
    # against the accumulated spend right after reserving; on breach the reserved
    # run is refunded and the caller gets a distinct 429. A run reserved here is
    # refunded on any failure path below, so a failed run is never billed.
    metered = agent_name in _LLM_TIER_BY_BACKEND
    quota_repo = UsageQuotaRepository() if metered else None
    if quota_repo is not None:
        reserved = quota_repo.reserve(user_id)
        if reserved is None:
            raise _plan_quota_429("quota_exceeded", quota_repo.get_by_user(user_id))
        if float(reserved["spendUsedUsd"]) >= float(reserved["spendCapUsd"]):
            quota_repo.refund_run(user_id)
            raise _plan_quota_429("spend_cap_exceeded", reserved)
        # Pipeline reservation-scoping (GAP-P7-ASYNC-001, reviewer BLOCKING-3):
        # when this metered step runs inside an async pipeline worker, record the
        # reservation on THAT BackgroundJob so a mid-pipeline crash refunds only
        # this job's own outstanding reservations (never a user-wide delta).
        _bg = _pipeline_job_ctx.get()
        if _bg:
            try:
                BackgroundJobRepository().increment_reserved(_bg)
            except Exception:  # noqa: BLE001 — accounting is best-effort
                pass

    run = runs.start(user_id, agent_name, params)
    _persist_billing_audit(runs, run["id"], audit)
    # Reserve + AgentRun row now stand; execution (and refund-on-failure) is the
    # shared block reused verbatim by the async worker (GAP-P7-ASYNC-001 §4.1).
    return _execute_reserved_run(
        run["id"], user_id, agent_name, params, fn, quota_repo, audit
    )


def _execute_reserved_run(
    run_id: str,
    user_id: str,
    agent_name: str,
    params: dict[str, Any],
    fn: Callable[[], Any],
    quota_repo: Any,
    audit: dict[str, Any],
    manage_quota: bool = True,
) -> dict[str, Any]:
    """Execute an already-reserved run (quota reserved + AgentRun row created by
    the caller) and finish it, refunding the reserved run on ANY failure path.

    Extracted verbatim from ``_record_run`` (GAP-P7-ASYNC-001 §4.1) so BOTH the
    sync endpoint path (flag OFF) AND the async worker (flag ON) share ONE
    implementation — zero logic duplication, identical billing/refund semantics.
    Runs inside ``user_credential_context`` so the deep LLM path resolves THIS
    user's credential; honours any ``shared_budget`` set by the caller.

    ``manage_quota`` (default True, the sync path) makes this function itself
    refund-on-failure and record-spend-on-success via ``quota_repo``. The async
    single-agent worker passes ``manage_quota=False`` so the refund/spend are
    performed by the worker AFTER it wins the atomic first-terminal-wins
    BackgroundJob transition — closing the watchdog-vs-worker double-refund /
    free-run race (reviewer BLOCKING-1/2). When a pipeline step runs under
    ``_pipeline_job_ctx``, an actual refund is additionally counted on the job so
    a mid-pipeline crash refund is reservation-scoped (BLOCKING-3).
    """
    from app.agents.tailor_agent import NoChangesApplied

    runs = AgentRunRepository()
    _bg = _pipeline_job_ctx.get()

    def _refund_once() -> None:
        if manage_quota and quota_repo is not None:
            quota_repo.refund_run(user_id)
            if _bg:
                try:
                    BackgroundJobRepository().increment_refunded(_bg)
                except Exception:  # noqa: BLE001
                    pass

    # Resolve the user's chosen model ONCE — used to bind the run AND to cost it
    # against the model that actually served it (GAP-P7-MODEL-CHOICE-001).
    _override_model = _user_model_override(user_id, agent_name)
    started = time.monotonic()
    try:
        # Bind BOTH the credential context and the user's chosen model so the
        # deep LLM path resolves THIS user's key AND model.
        with user_credential_context(user_id, agent_name), user_model_context(
            _override_model
        ):
            output = _to_output(fn())
    except HTTPException:
        runs.finish(run_id, "failed", error="http error")
        _refund_once()  # reserved run produced no output
        raise
    except NoChangesApplied as exc:
        # MV-adv-A-002 (AgentRun audit-row half): every proposed edit was
        # rejected by the anti-fabrication guard — a legitimate business
        # no-op, NOT a failure. ``GET /agents/runs`` is a plain-CurrentUser
        # (owner-visible, not admin-gated) endpoint rendered verbatim in the
        # /dashboard/agents "Recent runs" table, so recording this as
        # status='failed' with ``str(exc)`` would leak nothing extra here
        # (str(exc) itself carries no class name) but STILL mislabels an
        # honest no-op as a red "failed" row to its own owner. Record an
        # honest COMPLETED no-op — the exact same body the caller's
        # ``except NoChangesApplied`` handling returns over HTTP (sync
        # ``run_tailor``) or completes the BackgroundJob with (async
        # ``run_agent_job``) — then re-raise so those callers keep building
        # their own response/job-result shape unchanged.
        honest_output = {
            "resume_id": None,
            "changes": 0,
            "rejected": exc.rejected,
            "conversionMetrics": None,
            "noChangesApplied": True,
            "approvalRequired": False,
            "message": str(exc),
        }
        runs.finish(run_id, "completed", output=honest_output, cost_usd=0.0)
        # Refund only when THIS function manages quota (the sync path,
        # manage_quota=True); the async worker performs its own refund via
        # BackgroundJobRepository.refund_single_reservation AFTER this
        # re-raises (manage_quota=False here makes _refund_once() a no-op),
        # so a no-op is refunded exactly once on either path, never twice.
        _refund_once()
        raise
    except QuotaExhaustedError as exc:
        # Subscription quota exhausted mid-run — record honestly and 429.
        runs.finish(run_id, "failed", error=str(exc))
        _refund_once()
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
        # MV-cover-letter-studio-005: record + surface an HONEST, secret-free
        # message on both the AgentRun audit record and the 503 detail; the raw
        # exception (carrying 'hard budget', 'live call', the prompt name) is
        # logged server-side only, never shown to the user. Quota is refunded.
        logger.warning("agent run %s LLM-unavailable: %s", run_id, exc)
        runs.finish(run_id, "failed", error=LLM_UNAVAILABLE_USER_MESSAGE)
        _refund_once()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, LLM_UNAVAILABLE_USER_MESSAGE
        ) from exc
    except Exception as exc:
        runs.finish(run_id, "failed", error=str(exc))
        _refund_once()
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    output["duration_ms"] = duration_ms
    output["approvalRequired"] = agent_name in _APPROVAL_GATED
    output["billingAudit"] = audit
    # An honest "no letter produced" degrade: the cover-letter agent hit an
    # LLMUnavailableError on its FIRST draft and returned a coverLetterUnavailable
    # result rather than raising (cover _draft() resilience, coordinated with the
    # guard-rejection degrade — ML-cover-002). Normalize to the pipeline path's
    # camelCase flag so the worker + FE recognize the SAME shape, and never bill
    # it (no letter was produced), exactly like the guard-rejection degrade.
    cover_degraded = bool(
        output.get("cover_letter_unavailable") or output.get("coverLetterUnavailable")
    )
    if cover_degraded:
        output["coverLetterUnavailable"] = True
    # A metered agent that HONESTLY reports it made no LLM call this run (an
    # early-return no-op — e.g. EmailAgent._triage with nothing to classify sets
    # ``llm_called=False``) must record ZERO cost/tokens and no model stamp:
    # charging off the tiny request/response payload size would bill for work
    # that never happened (ML-email-001). Agents that do not report the flag
    # (``None``) are metered exactly as before, so no existing costing changes.
    no_llm_call = output.pop("llm_called", None) is False
    # Real cost estimate from the run's *measured* I/O size × the published
    # per-token price of the model the agent ACTUALLY ran on (≈4 chars/token).
    # Deterministic agents (scout/fitScorer/matcher/supervisor) make no LLM
    # calls, so they record zero tokens and zero spend — anything else would
    # fabricate the spend/ROI figures GET /agents/stats reports. The user's
    # chosen model (if any) is what actually ran, so cost against IT.
    model = _model_for_agent(agent_name, override=_override_model)
    if model is None or no_llm_call or cover_degraded:
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
    finished = runs.finish(run_id, "completed", output=output, cost_usd=cost)
    if cover_degraded:
        # No letter produced — refund the reserved run (sync path). The async
        # worker refunds via its own atomic first-terminal-wins transition
        # (manage_quota=False makes _refund_once a no-op here), mirroring the
        # guard-rejection degrade so a degraded run is NEVER billed.
        _refund_once()
    elif manage_quota and quota_repo is not None:
        # Record realized USD spend against the reserved run (metered agents
        # only). The reserved run-count already stands; here we only accumulate
        # spend so the USD cap halts the NEXT run once this period's spend passes
        # the ceiling. ``manage_quota=False`` (async single-agent worker) defers
        # this so spend is recorded only after the worker wins the atomic
        # mark_completed (reviewer BLOCKING-2): a job the watchdog already failed
        # must not accrue spend.
        quota_repo.record_spend(user_id, cost)
    output["run_id"] = (finished or {"id": run_id})["id"]
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


def _model_for_agent(agent_name: str, override: "str | None" = None) -> str | None:
    """The model this backend agent ACTUALLY runs on, or None for deterministic
    agents that make no LLM calls. Costing against the model that really served
    the run keeps spend/ROI (and the USD spend cap) genuine — so when the user
    chose a model (``override``) it MUST be reflected for the same generation
    tiers ``get_model`` honours it on (STRUCTURED stays on the env default)."""
    tier = _LLM_TIER_BY_BACKEND.get(agent_name)
    if tier is None:
        return None
    from app.services.llm_client import _USER_OVERRIDABLE_TIERS, get_model

    if override and tier.upper() in _USER_OVERRIDABLE_TIERS:
        return override
    return get_model(tier)


def _model_overridable(agent_name: "str | None") -> bool:
    """Whether a user-picked per-agent model is actually HONOURED at run time
    for this backend (ML-agents-001) — the authoritative signal the FE picker
    locks on, so it never renders a functional model picker that silently
    no-ops.

    False for planned agents (no backend) and deterministic backends
    (scout/fitScorer/matcher/supervisor — no LLM call); otherwise True only
    when the backend's LLM tier is one ``get_model`` honours an override for
    (:data:`_USER_OVERRIDABLE_TIERS`). STRUCTURED (storyExtractor) is a real
    LLM tier but is deliberately EXCLUDED from user override, so it resolves
    to False — an honest "fixed model, not user-selectable" lock rather than a
    picker whose selection is never read."""
    if agent_name is None or agent_name in _DETERMINISTIC_BACKENDS:
        return False
    tier = _LLM_TIER_BY_BACKEND.get(agent_name)
    if tier is None:
        return False
    from app.services.llm_client import _USER_OVERRIDABLE_TIERS

    return tier.upper() in _USER_OVERRIDABLE_TIERS


#: backend agent name -> UI ``AgentConfig.agentKey`` (the two namespaces differ,
#: e.g. backend ``tailor`` is stored under UI key ``resumeTailoring``).
_UI_KEY_FOR_BACKEND: dict[str, str] = {
    e["backend"]: e["key"] for e in AGENT_CATALOG if e.get("backend")
}
#: backend agent name -> its catalog ``recommended`` model. ``AgentConfig.model``
#: is SEEDED with this recommended value (agents.py ~1624), so a stored value
#: EQUAL to it is a phantom default, NOT a deliberate user choice — it must be
#: ignored (else the seeded ``claude-sonnet-4`` would silently route every run
#: to the anthropic path). Only a value that DIFFERS is a real user selection.
_RECOMMENDED_FOR_BACKEND: dict[str, str] = {
    e["backend"]: (e.get("recommended") or "")
    for e in AGENT_CATALOG
    if e.get("backend")
}


def _user_model_override(user_id: str, agent_name: str) -> "str | None":
    """The model this user DELIBERATELY chose for ``agent_name``
    (GAP-P7-MODEL-CHOICE-001), or ``None`` to use the env default.

    Precedence: a per-agent ``AgentConfig.model`` that DIFFERS from the catalog
    default (a real change) wins; else the user's default model on any
    ``AgentProvider`` row (preferring ``openrouter``). A stored value equal to
    the agent's seeded ``recommended`` default is treated as "no choice" so the
    write-only seed can never take effect. Best-effort: any read error returns
    ``None`` — a preference lookup can NEVER break a run. The chosen id still
    flows through ``resolve_provider`` downstream (billing separation intact); a
    deliberate pick that points at an unconfigured provider fails HONESTLY at
    call time rather than being silently swapped.
    """
    # Deterministic agents make no LLM call — nothing to override.
    if agent_name not in _LLM_TIER_BY_BACKEND:
        return None
    ui_key = _UI_KEY_FOR_BACKEND.get(agent_name, agent_name)
    default_model = _RECOMMENDED_FOR_BACKEND.get(agent_name, "")
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "model" FROM "AgentConfig" '
                    'WHERE "userId" = %s AND "agentKey" = %s',
                    (user_id, ui_key),
                )
                row = cur.fetchone()
                if row and (row[0] or "").strip():
                    chosen = row[0].strip()
                    if chosen != default_model:  # a real per-agent change
                        return chosen
                # Fall through to the user's provider-level default model — SCOPED
                # to the openrouter provider only. The ModelPicker sets exactly this
                # row; scoping stops a stale/incidental model saved on ANOTHER
                # provider card's legacy <select> (openai/gemini/groq, which carry
                # non-credential-gated static model lists) from silently becoming a
                # live override for this user's runs (adversarial-review finding).
                cur.execute(
                    'SELECT "model" FROM "AgentProvider" '
                    "WHERE \"userId\" = %s AND \"provider\" = 'openrouter' "
                    "AND \"model\" IS NOT NULL AND \"model\" <> ''",
                    (user_id,),
                )
                row = cur.fetchone()
                if row and (row[0] or "").strip():
                    return row[0].strip()
    except Exception:  # noqa: BLE001 — preference read is best-effort, never fatal
        return None
    return None


def _user_search_defaults(user_id: str) -> tuple[str, str]:
    """Resolve the user's configured job-search targets from the DB.

    Reads the profile ``targetRole``/``location`` columns and falls back to the
    module-level defaults only when the user has not configured them. This keeps
    scout runs targeted at the *user's* real goals rather than a hardcoded
    persona.

    The returned ``query`` may still be a single narrow title (whatever the
    user typed into their profile) — ``_dispatch`` runs it through
    ``query_builder.build_scout_query`` afterwards to broaden it to the
    user's whole target-role family (GAP-SRC-001).
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


def _agent_callable(
    user_id: str, name: str, params: dict[str, Any]
) -> tuple[str, Callable[[], Any]]:
    """Resolve ``(canonical_name, fn)`` for an agent run — a PURE mapping with no
    side effects, lifted verbatim from the old ``_dispatch`` body.

    Shared by BOTH the synchronous path (``_dispatch`` -> ``_record_run``) and
    the async worker (``workers.tasks._run_single_agent_body``) so there is a
    single source of the agent->callable binding (GAP-P7-ASYNC-001 §4.1). No
    logic duplication: the exact service functions bound here are the same ones
    the sync endpoints have always called. The SYSTEM-RUN exemption (ADR-P7-05)
    is NOT threaded here — it is a paywall concern handled by ``_dispatch`` /
    the enqueue seam via ``_record_run(..., system_run=...)``; this mapping is
    identical for a system run and a normal run.
    """
    if name == "scout":
        default_query, default_location = _user_search_defaults(user_id)
        raw_query = params.get("query") or default_query
        location = params.get("location") or default_location
        # Broaden whatever query arrived (an explicit caller-supplied query,
        # a cron/UI hardcode, or the profile-derived default above) into the
        # user's full target-role family — GAP-SRC-001: a single narrow
        # title starves discovery volume regardless of where it came from.
        query = build_scout_query(raw_query)
        return "scout", (lambda: ScoutAgent().run(user_id, query, location))
    if name in ("fitScorer", "fit-scorer"):
        from app.agents.fit_scorer import FitScorerAgent

        return "fitScorer", (
            lambda: FitScorerAgent().run(user_id, rescore=bool(params.get("rescore")))
        )
    if name == "tailor":
        from app.agents.tailor_agent import TailoringAgent

        job_id = _require_job_id(params)
        return "tailor", (
            lambda: TailoringAgent().run(user_id, job_id, params.get("resume_id"))
        )
    if name in ("coverLetter", "cover-letter"):
        from app.agents.cover_letter_agent import CoverLetterAgent

        job_id = _require_job_id(params)
        return "coverLetter", (lambda: CoverLetterAgent().run(user_id, job_id))
    if name in ("storyExtractor", "story-extractor"):
        from app.agents.story_extractor import StoryExtractorAgent

        return "storyExtractor", (lambda: StoryExtractorAgent().run(user_id))
    if name in ("matcher", "job-matching", "jobMatching"):
        from app.agents.matcher_agent import MatcherAgent

        return "matcher", (lambda: MatcherAgent().run(user_id))
    if name in ("emailAgent", "email-agent", "email"):
        from app.agents.email_agent import EmailAgent

        return "emailAgent", (lambda: EmailAgent().run(user_id, **params))
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{name}'")


def _dispatch(
    user_id: str, name: str, params: dict[str, Any], *, system_run: bool = False
) -> dict[str, Any]:
    """Resolve the agent callable (pure) then execute + audit it. ``system_run``
    (ADR-P7-05) is threaded to ``_record_run`` -> ``_require_active_subscription``,
    which honors the paywall exemption ONLY for ``_SYSTEM_RUN_EXEMPT_AGENTS``
    (scout, fitScorer). Every other agent name ignores it (defense in depth)."""
    canonical, fn = _agent_callable(user_id, name, params)
    return _record_run(user_id, canonical, params, fn, system_run=system_run)


def _require_job_id(params: dict[str, Any]) -> str:
    job_id = params.get("job_id")
    if not job_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "job_id is required")
    return str(job_id)


# ---------------------------------------------------------------------------
# Async background generation (GAP-P7-ASYNC-001) — enqueue + status polling.
# Gated behind AETHER_ASYNC_GENERATION (default OFF): when OFF the run handlers
# keep their legacy synchronous 200 behaviour untouched.
# ---------------------------------------------------------------------------

#: Env values (case-insensitive) that keep async generation DISABLED.
_ASYNC_OFF = frozenset({"false", "0", "no", "off", ""})


def async_generation_enabled() -> bool:
    """Whether async background generation is enabled (blueprint §7.1).

    Code default OFF; the deployer flips ``AETHER_ASYNC_GENERATION=true`` in
    ``.env`` after the J3 soak passes. Read via ``os.environ`` on every call so a
    hot env change takes effect and no flag is baked into source.
    """
    return os.environ.get(
        "AETHER_ASYNC_GENERATION", "false"
    ).strip().lower() not in _ASYNC_OFF


def _get_arq_pool():
    """Seam for the ARQ enqueue pool (patched to a FakeArqPool in tests)."""
    from app.workers.queue import get_arq_pool

    return get_arq_pool()


def _enqueue_to_arq(job_id: str) -> str | None:
    """Bridge the sync handler to ARQ's async ``enqueue_job`` (blueprint §3.2).

    Runs the whole enqueue in one ``asyncio.run`` so the redis connection lives
    inside a single event loop. Returns the ARQ job id (or None). Raises on a
    queue failure so the caller can compensate (refund + honest 503)."""
    pool = _get_arq_pool()
    result = asyncio.run(pool.enqueue_job("run_agent_job", job_id))
    return getattr(result, "job_id", None) if result is not None else None


def _enqueue_single_agent(
    user_id: str, agent_key: str, params: dict[str, Any], *, system_run: bool = False
) -> str:
    """Enqueue a metered single-agent run (tailor / coverLetter), blueprint §3.2.

    Ordering is identical to the sync ``_record_run`` pre-execution steps —
    paywall FIRST, then cooldown, then ATOMIC reserve-at-enqueue — before the
    AgentRun + BackgroundJob rows and the queue push. On a queue failure the
    reservation is refunded, the job marked failed, and an honest 503 raised
    (never a silent success, never a silent sync fallthrough).

    ``system_run`` (ADR-P7-05) is honored for the paywall check exactly as the
    sync path — but ONLY for ``_SYSTEM_RUN_EXEMPT_AGENTS`` (scout, fitScorer),
    which are NOT enqueued here, so a metered agent with a valid secret still
    hits the paywall (402). Threaded for parity + defense in depth."""
    # 1) Paywall FIRST (honest 402 before any row/reserve/enqueue) — scoped
    #    system-run exemption applies identically to the sync path.
    _require_active_subscription(user_id, agent_name=agent_key, system_run=system_run)
    runs = AgentRunRepository()
    audit, provider = _billing_audit(user_id, agent_key)
    if system_run:
        audit["systemRun"] = True
    # 2) Subscription-provider cooldown block -> 429.
    if provider is not None:
        try:
            block = AgentQuotaBlockRepository().get_active(user_id, provider)
        except Exception:  # noqa: BLE001 — block store down -> allow
            block = None
        if block is not None:
            raise _quota_429(provider, block.get("expiresAt"))
    # 3) Atomic reserve AT ENQUEUE (metered agents only).
    metered = agent_key in _LLM_TIER_BY_BACKEND
    quota_repo = UsageQuotaRepository() if metered else None
    reserved_flag = False
    if quota_repo is not None:
        reserved = quota_repo.reserve(user_id)
        if reserved is None:
            raise _plan_quota_429("quota_exceeded", quota_repo.get_by_user(user_id))
        if float(reserved["spendUsedUsd"]) >= float(reserved["spendCapUsd"]):
            quota_repo.refund_run(user_id)
            raise _plan_quota_429("spend_cap_exceeded", reserved)
        reserved_flag = True
    # 4) AgentRun audit row + BackgroundJob row.
    run = runs.start(user_id, agent_key, params)
    _persist_billing_audit(runs, run["id"], audit)
    repo = BackgroundJobRepository()
    job_id = repo.create(
        user_id, agent_key, run_id=run["id"], params=params,
        quota_reserved=reserved_flag,
    )
    # 5) Enqueue; compensate on failure (refund + fail + honest 503).
    try:
        arq_job_id = _enqueue_to_arq(job_id)
    except Exception as exc:  # noqa: BLE001
        if reserved_flag and quota_repo is not None:
            quota_repo.refund_run(user_id)
        runs.finish(run["id"], "failed", error="generation queue unavailable")
        repo.mark_failed(
            job_id, "generation queue temporarily unavailable", refunded=reserved_flag
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "generation queue temporarily unavailable",
        ) from exc
    repo.set_arq_job_id(job_id, arq_job_id)
    return job_id


def _enqueue_pipeline(
    user_id: str, params: dict[str, Any], *, system_run: bool = False
) -> str:
    """Enqueue a composite pipeline run (blueprint §3.2 / D6): paywall FIRST at
    enqueue only — the metered footprint is data-dependent, so per-step atomic
    reserve/refund stays inside the worker's ``_pipeline_core``.

    ``pipeline`` is NOT a ``_SYSTEM_RUN_EXEMPT_AGENTS`` key, so a valid secret
    never bypasses the paywall here — the composite is always walled."""
    _require_active_subscription(user_id, agent_name="pipeline", system_run=system_run)
    repo = BackgroundJobRepository()
    job_id = repo.create(user_id, "pipeline", run_id=None, params=params,
                         quota_reserved=False)
    try:
        arq_job_id = _enqueue_to_arq(job_id)
    except Exception as exc:  # noqa: BLE001
        repo.mark_failed(job_id, "generation queue temporarily unavailable")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "generation queue temporarily unavailable",
        ) from exc
    repo.set_arq_job_id(job_id, arq_job_id)
    return job_id


def _job_stale_thresholds() -> tuple[int, int]:
    """(enqueued_secs, processing_secs) staleness windows (blueprint §7.4).

    enqueued stale > 15 min; processing stale > 12 min. Tunable via
    ``AETHER_JOB_STALE_SECONDS`` (the enqueued window; processing = that − 180)."""
    try:
        enq = int(os.environ.get("AETHER_JOB_STALE_SECONDS", "900"))
    except ValueError:
        enq = 900
    return enq, max(60, enq - 180)


def _apply_stale_watchdog(
    job: dict[str, Any], repo: "BackgroundJobRepository"
) -> dict[str, Any]:
    """Lazy-on-GET watchdog (blueprint §7.4): a poll of a non-terminal job older
    than the staleness window atomically marks it failed + refunds the
    enqueue-time reservation, so a polling user always reaches a terminal state
    even if the worker is dead."""
    status_v = job.get("status")
    if status_v not in ("enqueued", "processing"):
        return job
    from datetime import datetime, timezone

    enq_secs, proc_secs = _job_stale_thresholds()
    limit = enq_secs if status_v == "enqueued" else proc_secs
    anchor = job.get("startedAt") if status_v == "processing" else None
    anchor = anchor or job.get("createdAt")
    if anchor is None:
        return job
    if getattr(anchor, "tzinfo", None) is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - anchor).total_seconds()
    if age < limit:
        return job
    # First-terminal-wins (reviewer BLOCKING-1/2): only the caller that atomically
    # transitions the job to failed performs the refund, and the refund itself is
    # atomic + idempotent + reservation-scoped. Two concurrent watchdog pollers,
    # or a watchdog racing a live-but-slow worker, therefore refund exactly once
    # (and a job the worker already completed can never be failed/refunded).
    if repo.mark_failed(job["id"], "generation timed out (worker unavailable)"):
        if job.get("agentKey") == "pipeline":
            repo.refund_pipeline_outstanding(job["id"])
        else:
            repo.refund_single_reservation(job["id"])
    return repo.get_for_user(job["id"], job["userId"]) or job


def _job_status_payload(job: dict[str, Any]) -> dict[str, Any]:
    """The public polling projection (blueprint §3.3)."""

    def _iso(v: Any) -> Any:
        return v.isoformat() if hasattr(v, "isoformat") else v

    return {
        "job_id": job["id"],
        "status": job["status"],
        "agentKey": job.get("agentKey"),
        "result": job.get("result"),
        "error": job.get("error"),
        "createdAt": _iso(job.get("createdAt")),
        "startedAt": _iso(job.get("startedAt")),
        "finishedAt": _iso(job.get("finishedAt")),
    }


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
def list_runs(
    current_user: CurrentUser, limit: int = Query(default=50, ge=0)
) -> list[dict[str, Any]]:
    # ``ge=0`` rejects a negative limit with an honest 422 (MV-agents-002) instead
    # of passing ``LIMIT -5`` to Postgres and surfacing a bare 500; the upper
    # bound is still clamped so an over-large limit is capped, not rejected.
    return AgentRunRepository().list_recent(current_user["id"], limit=min(limit, 200))


@router.get("/runs/{run_id}")
def get_run(run_id: str, current_user: CurrentUser) -> dict[str, Any]:
    run = AgentRunRepository().get_by_id(run_id, current_user["id"])
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found")
    return run


@router.get("/jobs/{job_id}")
def get_background_job(job_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """Poll an async background generation job (GAP-P7-ASYNC-001 §3.3).

    Owner-scoped: a job not found OR not owned by the caller returns 404 (no
    cross-user leakage). Applies the lazy staleness watchdog so a dead worker
    still resolves to a terminal ``failed`` (with refund) for a polling user.
    Route lives under ``/agents`` deliberately — ``GET /jobs/{id}`` on the
    job-postings router would collide (blueprint §3.1)."""
    repo = BackgroundJobRepository()
    job = repo.get_for_user(job_id, current_user["id"])
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    job = _apply_stale_watchdog(job, repo)
    return _job_status_payload(job)


# ---------------------------------------------------------------------------
# Dedicated agent triggers (stable P2-S02..S06 contracts)
# ---------------------------------------------------------------------------


class ScoutRunRequest(BaseModel):
    query: str = Field(min_length=1)
    location: str = Field(min_length=1)


@router.post("/scout/run", status_code=status.HTTP_202_ACCEPTED)
def run_scout(
    body: ScoutRunRequest, current_user: CurrentUser, request: Request
) -> dict[str, Any]:
    """Kick off a scout discovery run for the authenticated user."""
    output = _dispatch(
        current_user["id"], "scout", body.model_dump(),
        system_run=_is_system_run(request),
    )
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
def run_fit_scorer(
    current_user: CurrentUser, request: Request, rescore: bool = False
) -> dict[str, Any]:
    """Score every unscored job for the authenticated user (P2-S04)."""
    output = _dispatch(
        current_user["id"], "fitScorer", {"rescore": rescore},
        system_run=_is_system_run(request),
    )
    return {"status": "completed", "scored": output["scored"], "errors": output["errors"]}


class JobTargetRequest(BaseModel):
    job_id: str = Field(min_length=1)
    resume_id: str | None = None


@router.post("/tailor/run")
def run_tailor(
    body: JobTargetRequest, current_user: CurrentUser, request: Request,
    response: Response,
) -> dict[str, Any]:
    """Produce a tailored child resume version for a target job (P2-S05).

    When ``AETHER_ASYNC_GENERATION`` is ON, returns 202 + an enqueue envelope
    (``{"job_id","status":"enqueued"}``) and the worker generates in the
    background; when OFF, the legacy synchronous 200 body is returned unchanged.
    ``system_run`` is threaded to both paths for parity, but ``tailor`` is not a
    ``_SYSTEM_RUN_EXEMPT_AGENTS`` key so a valid secret never bypasses the paywall."""
    from app.agents.tailor_agent import NoChangesApplied

    system_run = _is_system_run(request)
    if async_generation_enabled():
        job_id = _enqueue_single_agent(
            current_user["id"], "tailor", body.model_dump(), system_run=system_run
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
    try:
        output = _dispatch(
            current_user["id"], "tailor", body.model_dump(), system_run=system_run
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except NoChangesApplied as exc:
        # MV-resume-studio-003: the guards rejected every proposed edit, so no
        # version was created and the reserved run was already refunded by
        # _execute_reserved_run. Return an HONEST no-op (never a silent billed
        # "Tailored" version); the client renders it as an informational notice.
        return {
            "resume_id": None,
            "changes": 0,
            "rejected": exc.rejected,
            "conversionMetrics": None,
            "noChangesApplied": True,
            "approvalRequired": False,
            "message": str(exc),
        }
    return {
        "resume_id": output["resume_id"],
        "changes": output["changes"],
        "rejected": output["rejected"],
        "conversionMetrics": output["conversionMetrics"],
        # MV-resume-studio-001: the approvalRequired flag is now backed by a REAL
        # pending ApprovalRequest — surface its id/status so the client can link to
        # the human-in-the-loop review just as the cover-letter run does.
        "approvalRequired": output.get("approvalRequired", False),
        "approval_id": output.get("approval_id"),
        "approval_status": output.get("approval_status"),
    }


@router.post("/cover-letter/run")
def run_cover_letter(
    body: JobTargetRequest, current_user: CurrentUser, request: Request,
    response: Response,
) -> dict[str, Any]:
    """Draft a fabrication-guarded cover letter; requires human approval (P2-S06).

    Async-enabled: 202 + enqueue envelope when ``AETHER_ASYNC_GENERATION`` is ON,
    legacy synchronous 200 otherwise. ``coverLetter`` is not system-run exempt."""
    from app.agents.cover_letter_agent import FabricationError, StructuralError

    system_run = _is_system_run(request)
    if async_generation_enabled():
        job_id = _enqueue_single_agent(
            current_user["id"], "coverLetter", body.model_dump(), system_run=system_run
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
    try:
        output = _dispatch(
            current_user["id"], "coverLetter", body.model_dump(), system_run=system_run
        )
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
    if output.get("coverLetterUnavailable"):
        # cover _draft() resilience (ML-cover-002/003): the writing model was
        # unavailable on the FIRST draft, so the agent degraded honestly rather
        # than raising — the reserved run was already refunded (never billed).
        # Surface the SAME honest coverLetterUnavailable shape the async job
        # completes with, so the studio renders "temporarily unavailable — try
        # again" instead of a raw error or a fabricated empty letter.
        return {
            "cover_letter_id": None,
            "coverLetterUnavailable": True,
            "message": output.get("message"),
        }
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


def _pipeline_core(
    user_id: str, params: dict[str, Any], budget_seconds: float | None = None
) -> dict[str, Any]:
    """Full pipeline orchestration: supervisor → scout → fitScorer → matcher →
    tailor → coverLetter.

    Mirrors the LangGraph orchestration in packages/agents. Every node —
    including the supervisor (planning) and matcher (top-job selection) — is
    recorded as an AgentRun row. Each metered step reserves + refunds-on-failure
    atomically via ``_record_run``, so the composite's data-dependent metered
    footprint is billed correctly (GAP-P7-ASYNC-001 D6). Shared by BOTH the sync
    handler (``budget_seconds=None`` → default HTTP budget) and the async worker
    (``budget_seconds`` → the more-generous worker pipeline budget)."""
    steps: list[dict[str, Any]] = []

    # Supervisor node: plans the run (audit-recorded, defect fix — the card
    # previously showed "Never run" because the pipeline skipped this node).
    sup_out = _record_run(
        user_id, "supervisor", params, lambda: {"plan": list(_PIPELINE_PLAN)}
    )
    steps.append({"agent": "supervisor", "output": sup_out})

    scout_out = _dispatch(user_id, "scout", params)
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
    from app.agents.cover_letter_agent import FabricationError, StructuralError
    from app.agents.tailor_agent import NoChangesApplied
    from app.services.llm_client import shared_budget

    with shared_budget(budget_seconds):
        try:
            tailor_out: dict[str, Any] = _dispatch(
                user_id, "tailor", {"job_id": top_job_id}
            )
        except NoChangesApplied as exc:
            # MV-resume-studio-003: the guards rejected every proposed edit, so no
            # tailored version was created and the tailor run was refunded. This
            # must NOT fail the whole pipeline — the cover-letter step draws on the
            # base résumé regardless — so record the honest no-op and continue.
            tailor_out = {"noChangesApplied": True, "changes": 0, "message": str(exc)}
        steps.append({"agent": "tailor", "output": tailor_out})
        try:
            letter_out = _dispatch(user_id, "coverLetter", {"job_id": top_job_id})
        except (FabricationError, StructuralError) as exc:
            # GAP-P7-COV-PIPE-001: the cover step's own fabrication/structural
            # guard rejected the draft — an ungrounded term or §10.2 format
            # violation survived every corrective retry. That is the guard
            # WORKING (Aether never ships a fabricated cover letter), but it must
            # NOT discard the SUCCESSFUL tailoring that precedes it. The
            # coverLetter AgentRun is already recorded failed and its reserved
            # quota refunded inside _dispatch/_record_run, so here we ONLY degrade
            # gracefully: keep the tailored résumé and complete the pipeline with
            # the cover marked unavailable + an honest, actionable message —
            # instead of failing the whole job with a raw guard exception.
            reason = getattr(exc, "flagged", None) or getattr(exc, "issues", None)
            steps.append(
                {
                    "agent": "coverLetter",
                    "output": {"coverLetterUnavailable": True, "reason": str(reason)},
                }
            )
            # Honest message (adversarial-review fix): the lead must reflect what
            # the tailor step ACTUALLY did. If tailoring ALSO no-op'd
            # (NoChangesApplied -> 0 changes, no new résumé version persisted),
            # never claim "your résumé was tailored" — that would be a false
            # success claim in the compound (tailor no-op + cover rejected) case.
            tailored = not tailor_out.get("noChangesApplied") and int(
                tailor_out.get("changes") or 0
            ) > 0
            lead = (
                "Your résumé was tailored for this role, but an auto-generated "
                "cover letter"
                if tailored
                else "No verifiable résumé changes could be applied for this "
                "role, and an auto-generated cover letter"
            )
            return {
                "status": "completed",
                "steps": steps,
                "top_job_id": top_job_id,
                "approvalRequired": False,
                "coverLetterUnavailable": True,
                "message": (
                    f"{lead} couldn't be produced without unverifiable wording, "
                    "so it was withheld — open the Cover Letter studio to generate "
                    "or write one manually."
                ),
            }
        steps.append({"agent": "coverLetter", "output": letter_out})

    return {
        "status": "awaiting_approval",
        "steps": steps,
        "top_job_id": top_job_id,
        "approvalRequired": True,
        "approval_id": letter_out.get("approval_id"),
    }


@router.post("/pipeline/run")
def run_pipeline(
    body: PipelineRunRequest, current_user: CurrentUser, request: Request,
    response: Response,
) -> dict[str, Any]:
    """Full pipeline. Async-enabled: 202 + enqueue envelope when
    ``AETHER_ASYNC_GENERATION`` is ON (the composite runs in the background,
    per-step metering inside the worker); legacy synchronous body otherwise.

    The pipeline halts with ``approvalRequired=True`` after generating artefacts.
    ``pipeline`` is not a ``_SYSTEM_RUN_EXEMPT_AGENTS`` key, so a valid secret
    never bypasses the paywall (the sync path is walled by the supervisor step's
    own ``_record_run``; the async path by ``_enqueue_pipeline``)."""
    user_id = current_user["id"]
    if async_generation_enabled():
        job_id = _enqueue_pipeline(
            user_id, body.model_dump(), system_run=_is_system_run(request)
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
    return _pipeline_core(user_id, body.model_dump())


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
            model = (
                _model_for_agent(
                    backend, override=_user_model_override(user_id, backend)
                )
                or "deterministic"
            )
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
                # Authoritative per-agent signal for the FE picker lock
                # (ML-agents-001): True only when a user-picked model is
                # actually honoured at run time for this backend's tier.
                "modelOverridable": _model_overridable(backend),
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
    authMode: str | None = Field(default=None, pattern="^(api_key|oauth_token)$")
    #: Empty string clears the pinned credential; a non-empty value must
    #: reference one of the caller's own stored credentials (validated below).
    credentialRef: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thinkingEffort: str | None = Field(default=None, pattern="^(none|low|medium|high)$")


#: Deterministic (non-LLM) agents — their config panel disables temperature.
_DETERMINISTIC_BACKENDS = frozenset(
    {"scout", "fitScorer", "matcher", "supervisor"}
)

#: Non-catalog ``model`` values that must always remain valid: the literal
#: sentinel a deterministic (non-LLM) agent stores instead of a model id.
_MODEL_VALIDATION_SENTINELS = frozenset({"deterministic"})

#: Providers whose model catalog is a genuine LIVE, exhaustive list that a
#: chosen id can be validated against (ML-catalog-004 / §3.1.3). The static
#: curated catalogs (anthropic, …) are indicative shortlists — NOT an
#: exhaustive allowlist — so they must never be used to REJECT a model, which
#: would be exactly the hardcoded-allowlist antipattern §3.1.3 forbids.
_LIVE_CATALOG_PROVIDERS = frozenset({"openrouter"})


def _validate_agent_model(model: str, user_id: str) -> None:
    """Reject a ``model`` id that is not offered by the live catalog of the
    provider it would bill through (ML-catalog-004 / §3.1.3).

    Accepts the ``deterministic`` sentinel, any id present in that provider's
    live catalog, and any direct-Anthropic (bare ``claude-…``) id — those route
    to a curated static shortlist that is deliberately NOT treated as an
    exhaustive allowlist. When the live catalog cannot be consulted right now
    (cold cache — validation never opens a network connection, ``allow_fetch``
    is False) the id is accepted rather than rejected on a transient gap; a
    genuinely wrong id then fails honestly at call time (matching the
    ``_user_model_override`` "no silent substitution" contract). Never applies a
    hardcoded model allowlist.
    """
    m = (model or "").strip()
    if not m or m in _MODEL_VALIDATION_SENTINELS:
        return
    from app.services.llm_client import (
        ModelCatalogError,
        list_provider_models,
        resolve_provider,
    )

    provider = resolve_provider(m)
    if provider not in _LIVE_CATALOG_PROVIDERS:
        return
    try:
        catalog = list_provider_models(provider, user_id, allow_fetch=False)
    except ModelCatalogError:
        # Live catalog not warm — can't disprove the id without blocking on a
        # slow upstream fetch, so accept (fails honestly at run time if wrong).
        return
    if any((row.get("id") == m) for row in catalog):
        return
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        f"model '{m}' is not in the live {provider} catalog — choose one from the catalog.",
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

    # Validate a chosen model against the live catalog (ML-catalog-004): an id
    # no provider offers is rejected 422 rather than silently persisted and then
    # failing opaquely at run time. Only runs when the caller is actually
    # setting `model` (a partial update that omits it must not be gated).
    if body.model is not None:
        _validate_agent_model(body.model, user_id)

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


def _anthropic_oauth_needs_reauth(user_id: str | None) -> bool:
    """True when this user's Anthropic subscription OAuth session is marked
    needs_reauth (auto-refresh failed / token revoked — ADR-ML-2a DECISION-1b).

    Degrades to False on ANY read error so the providers panel never fails
    because the token store is unavailable. Reads the REAL stored row — it never
    fabricates a status.
    """
    if not user_id:
        return False
    try:
        row = AnthropicOAuthTokenRepository().get(user_id)
    except Exception:  # noqa: BLE001 — providers panel must stay up
        return False
    return bool(row and row.get("scopes") == "needs_reauth")


def _build_provider_entry(
    seed: dict[str, Any], override: dict[str, Any], user_id: str | None = None
) -> dict[str, Any]:
    """One provider's honest status: DB credential FIRST, then env, then none.

    ``source`` is the truth about where a live credential would come from
    (``database`` / ``environment`` / ``none``); a provider is never shown
    ``connected`` without a real credential (D-0020). A stored credential
    whose most recent real verify round-trip came back ``failed`` (expired
    OAuth token, revoked API key, ...) is demoted to ``warning`` — the SAME
    status the frontend already renders as "Re-authenticate" — rather than
    the green "Connected" badge a genuinely working credential gets
    (MV-agents-004). This reads the STORED ``lastVerifyStatus`` only; it never
    triggers a live re-verify on render. A persisted per-user override may
    only DOWNGRADE a connected/warning provider or pick a preferred model.
    """
    provider_id = seed["id"]
    env_status, env_model, env_detail, env_models = _provider_env_state(provider_id)
    # A stored credential is only usable when the vault key is present; without
    # it the ciphertext can't be decrypted, so per ADR-PC-3 the read degrades to
    # the env source (or none) instead of dishonestly claiming a DB connection.
    db = _provider_db_masked(provider_id) if credential_vault.key_present() else None
    if db:
        source = "database"
        auth_mode = db.get("authMode")
        secret_hint = db.get("secretHint")
        base_url = db.get("baseUrl")
        last_verified_at = _iso_or_none(db.get("lastVerifiedAt"))
        last_verify_status = db.get("lastVerifyStatus")
        # Honest demotion: a credential row existing is NOT proof it still
        # works — only a genuine verify success is. A known-failed last
        # verify must never show the same "Connected" badge as a healthy one.
        status = "warning" if last_verify_status == "failed" else "connected"
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
    if override.get("status") in ("warning", "unconfigured") and status in (
        "connected",
        "warning",
    ):
        status = override["status"]
    # Honest needs_reauth surfacing (ML-agents-cred-002, ADR-ML-2a DECISION-1b):
    # a subscription OAuth session whose auto-refresh failed / token was revoked
    # is marked needs_reauth. The (now-stale) deployment ProviderCredential row
    # would otherwise still render "connected" — a false-optimistic badge. Demote
    # to "warning" (the status the FE already renders as re-authenticate) and
    # emit an explicit ``needsReauth`` flag so the modal shows the Reconnect /
    # Renew affordance. Reads the REAL token row; never fabricated.
    needs_reauth = _anthropic_oauth_needs_reauth(user_id) if provider_id == "anthropic" else False
    if needs_reauth:
        status = "warning"
        detail = (
            "Anthropic subscription session expired — reconnect required "
            "(Connect with Anthropic, or Renew)."
        )
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
        "needsReauth": needs_reauth,
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
    return _build_provider_entry(_PROVIDER_SEED_BY_ID[provider_id], override, user_id)


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
        _build_provider_entry(seed, overrides.get(seed["id"], {}), current_user["id"])
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


#: Names BOTH accepted Anthropic credential formats (GATE-04 / J1 step 10). The
#: pasted value is NEVER included in this message. ``sk-ant-oat01-`` is kept as
#: a worked example (ML-agents-cred-001) but the wording no longer implies it
#: is the ONLY accepted version — Anthropic increments this digit over time.
_ANTHROPIC_CREDENTIAL_HELP = (
    "Anthropic credential not recognized. Console API keys start with "
    "'sk-ant-api'. Claude Code OAuth tokens start with 'sk-ant-oat' followed "
    "by a version number, for example 'sk-ant-oat01-'. Check which credential "
    "you are pasting."
)

#: Digit-anchored Claude-Code OAuth token prefix (ML-agents-cred-001): accepts
#: any version generation (oat01, oat02, oat03, …) Anthropic's CLI issues, but
#: REQUIRES at least one digit between "oat" and the trailing hyphen. A bare
#: ``sk-ant-oat-`` (no digit) is the legacy in-app subscription-OAuth shape and
#: must NOT match (ADR-P7-01 NON-goal) — see the bare-oat compliance guards in
#: tests/test_ml_cred_001.py.
_ANTHROPIC_OAT_TOKEN_RE = re.compile(r"^sk-ant-oat\d+-")

#: Unicode whitespace/invisible characters a pasted credential can be
#: wrapped in that a plain ASCII strip misses (ML-agents-cred-001): NBSP
#: (U+00A0), zero-width space (U+200B), BOM/ZWNBSP (U+FEFF), and the
#: U+2000-U+200A general-punctuation spaces. Written as explicit escapes
#: (never literal invisible characters) so the source stays reviewable.
_INVISIBLE_STRIP_CHARS = "\u00a0\u200b\ufeff" + "".join(
    chr(cp) for cp in range(0x2000, 0x200B)
)
#: Full set of characters stripped from the edges of a pasted credential:
#: ordinary ASCII whitespace plus the Unicode invisibles above.
_CREDENTIAL_STRIP_CHARS = " \t\n\r\v\f" + _INVISIBLE_STRIP_CHARS


def _normalize_credential_secret(secret: str) -> str:
    """Strip whitespace/invisible chars and ONE pair of surrounding quotes.

    Handles common "smart paste" artifacts (NBSP, ZWSP, BOM, general-
    punctuation spaces) and a credential copied out of a JSON/YAML snippet
    still wrapped in a matching quote pair — including ASCII whitespace
    nested INSIDE that quote pair (ML-agents-cred-001). Pure function shared
    by detection and validation so both agree on the same normalized value.
    """
    value = secret.strip(_CREDENTIAL_STRIP_CHARS)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip(_CREDENTIAL_STRIP_CHARS)
    return value


def _detect_anthropic_auth_mode(secret: str) -> str | None:
    """Server-derived Anthropic authMode from the normalized secret prefix.

    The secret is first normalized (ML-agents-cred-001: whitespace/invisible
    chars + one surrounding quote pair stripped) so a copy-pasted token is
    judged on its real prefix, not on paste artifacts. ``sk-ant-api…`` →
    ``api_key``; a digit-versioned ``sk-ant-oat<N>-…`` (oat01, oat02, …) →
    ``oauth_token`` (a pasted ``claude setup-token`` output). Any other
    value — including the legacy non-versioned ``sk-ant-oat-`` subscription
    shape — → ``None`` (unrecognized).
    """
    value = _normalize_credential_secret(secret)
    if value.startswith("sk-ant-api"):
        return "api_key"
    if _ANTHROPIC_OAT_TOKEN_RE.match(value):
        return "oauth_token"
    return None


def _validate_provider_auth(
    provider: str, auth_mode: str, secret: str
) -> tuple[str, str]:
    """Validate the credential and RETURN ``(server-derived authMode, secret to store)``.

    Anthropic (GAP-P7-DEF-A, ML-agents-cred-001): the submitted secret is
    first normalized (whitespace/invisible chars + one surrounding quote pair
    stripped) so a paste artifact never causes a false-negative reject NOR
    gets persisted verbatim as an unusable credential. The authMode is then
    DERIVED from the normalized secret's prefix (authoritative): a digit-
    versioned ``sk-ant-oat<N>-`` token (oat01, oat02, …) is accepted as
    ``oauth_token``; a Console ``sk-ant-api…`` key as ``api_key``. Anything
    else — including the legacy non-versioned ``sk-ant-oat-`` subscription
    shape — is a 422 naming BOTH formats. If the client's declared
    ``authMode`` contradicts the detected prefix, that is also a 422
    (anti-mislabel — never silently store the wrong label, which would pick
    the wrong transport header at run time). The legacy in-app
    ``subscription_oauth`` OAuth flow stays unsupported (ADR-P7-01 NON-goal).

    Every other provider accepts only ``api_key`` and is stored unnormalized
    (out of scope for this fix — ML-agents-cred-001 is Anthropic-only).
    """
    if provider == "anthropic":
        detected = _detect_anthropic_auth_mode(secret)
        if detected is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, _ANTHROPIC_CREDENTIAL_HELP
            )
        if auth_mode and auth_mode != detected:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Credential prefix is a '{detected}' credential but you selected "
                f"'{auth_mode}'. Select the matching mode, or paste the matching "
                "credential.",
            )
        return detected, _normalize_credential_secret(secret)
    if auth_mode != "api_key":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Provider '{provider}' accepts only authMode 'api_key'.",
        )
    return "api_key", secret


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
    stored_mode, stored_secret = _validate_provider_auth(
        provider, body.authMode, body.secret
    )
    if not credential_vault.key_present():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not "
            "configured on the server.",
        )
    try:
        ProviderCredentialRepository().upsert(
            provider, auth_mode=stored_mode, secret=stored_secret, base_url=body.baseUrl
        )
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)
        ) from exc
    if stored_mode == "oauth_token":
        # Sync CLAUDE_CODE_OAUTH_TOKEN to the repo-root .env (GAP-P7-DEF-A §3.3).
        # Best-effort: the encrypted DB row is the source of truth, so a sync
        # failure does not fail the save (the token is never logged).
        from app.services import env_file_writer

        env_file_writer.sync_oauth_token_env(stored_secret)
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


@router.get("/providers/{provider}/models")
def list_provider_models_endpoint(
    provider: str, current_user: CurrentUser
) -> dict[str, Any]:
    """LIVE, curated model catalog for a provider (GAP-P7-MODEL-CHOICE-001).

    OpenRouter → its full 300+ model catalog, each row carrying per-model
    ``$/M-token`` prompt+completion pricing, context length and a budget tier
    (free / budget / standard / premium), so a user can choose ANY model — a
    high-end frontier model or a free open-source one — by budget. Uses the
    signed-in user's OWN provider key when configured, else the deployment key.
    Returns an HONEST 400 with an actionable message (never a fabricated
    catalog) when no credential is available or the catalog can't be reached.
    """
    from app.services.llm_client import (
        ModelCatalogError,
        catalog_freshness,
        list_provider_models,
    )

    prov = provider.strip().lower()
    try:
        models = list_provider_models(provider, current_user["id"])
    except ModelCatalogError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    last_refreshed, stale = catalog_freshness(prov)
    return {
        "provider": prov,
        "models": models,
        "count": len(models),
        "lastRefreshedAt": last_refreshed,
        "stale": stale,
    }


@router.post("/providers/{provider}/models/refresh")
def refresh_provider_models_endpoint(
    provider: str, current_user: CurrentUser
) -> dict[str, Any]:
    """Force a fresh upstream fetch of a provider's live model catalog, bypassing
    the ~1 h TTL cache (ML-catalog-003). Same envelope as GET .../models. On an
    upstream failure with a warm cache it still serves last-good data
    (``stale: true``) rather than blocking — never a fabricated list. A provider
    without a live catalog (groq, bedrock, …) is rejected with an honest 400,
    matching the GET endpoint.
    """
    from app.services.llm_client import (
        ModelCatalogError,
        catalog_freshness,
        list_provider_models,
    )

    prov = provider.strip().lower()
    try:
        models = list_provider_models(provider, current_user["id"], force_refresh=True)
    except ModelCatalogError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    last_refreshed, stale = catalog_freshness(prov)
    return {
        "provider": prov,
        "models": models,
        "count": len(models),
        "lastRefreshedAt": last_refreshed,
        "stale": stale,
    }


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
    stored_mode, stored_secret = _validate_provider_auth(
        provider, body.authMode, body.secret
    )
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
            user_id, provider, auth_mode=stored_mode,
            secret=stored_secret, base_url=body.baseUrl,
        )
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if stored_mode == "oauth_token":
        # Sync CLAUDE_CODE_OAUTH_TOKEN to the repo-root .env (GAP-P7-DEF-A §3.3);
        # best-effort, DB row is source of truth, token never logged.
        from app.services import env_file_writer

        env_file_writer.sync_oauth_token_env(stored_secret)
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
# In-app "Connect with Anthropic" (subscription) OAuth — ML-agents-cred-002,
# operator-mandated (ADR-ML-1), approved ADR-ML-2/2a. This is the COMPLIANT
# re-authoring of the flow removed in GAP-AUTH-001/Gate-14: the operator
# authorizes on Anthropic's OWN pages with their OWN Pro/Max account and pastes
# back a one-time code (never the long-lived token). The exchanged access token
# is stored in the SAME deployment-wide ProviderCredential('anthropic') seam the
# manual oauth_token paste uses (transport unchanged: Bearer + anthropic-beta:
# oauth-2025-04-20). Manual API-key / setup-token paste remain as honest
# fallback. See app/services/anthropic_oauth.py.
# ---------------------------------------------------------------------------


class AnthropicOAuthExchangeBody(BaseModel):
    pastedCode: str


def _oauth_vault_ready_or_503() -> None:
    """Fail closed (503) when the vault key is absent — the refresh token can't
    be stored honestly without it (never proceed unencrypted)."""
    if not credential_vault.key_present():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Credential encryption unavailable: AETHER_CREDENTIAL_KEY is not "
            "configured on the server.",
        )


@router.post("/providers/anthropic/oauth/start")
def anthropic_oauth_start(current_user: CurrentUser) -> dict[str, Any]:
    """Begin the Connect-with-Anthropic flow: return the authorize URL.

    Generates a server-side PKCE verifier + opaque single-use state, persists
    them (the verifier NEVER leaves the server), and returns Anthropic's own
    authorize URL. 503 when the vault key is absent (fail closed).
    """
    from app.services import anthropic_oauth

    _oauth_vault_ready_or_503()
    verifier, challenge = anthropic_oauth.generate_pkce()
    state = anthropic_oauth.generate_state()
    AnthropicOAuthStateRepository().create(state, current_user["id"], verifier)
    return {"authorizeUrl": anthropic_oauth.build_authorize_url(challenge, state)}


def _parse_pasted_oauth_code(pasted: str) -> tuple[str, str]:
    """Split a pasted ``code#state`` into ``(code, state)`` — both halves required.

    A 422 (honest) when malformed. The submitted value is NEVER echoed in the
    error (nor is any secret).
    """
    value = (pasted or "").strip()
    code, sep, state = value.partition("#")
    if not sep or not code or not state:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Paste the full 'code#state' value Anthropic showed you (both halves "
            "are required).",
        )
    return code, state


@router.post("/providers/anthropic/oauth/exchange")
def anthropic_oauth_exchange(
    body: AnthropicOAuthExchangeBody, current_user: CurrentUser
) -> dict[str, Any]:
    """Exchange the pasted one-time ``code#state`` for a subscription token.

    422 malformed paste; 400 unknown/expired/replayed state; 403 state started
    by a different user; 502 honest token-endpoint error (incl. an unexpected
    response shape — defensive parse, never a fake success). On success the
    access token is stored deployment-wide (oauth_token) and the refresh
    material per-user; the masked provider status object is returned (no token).
    """
    from app.services import anthropic_oauth

    code, state = _parse_pasted_oauth_code(body.pastedCode)
    _oauth_vault_ready_or_503()
    row = AnthropicOAuthStateRepository().consume(state)
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Authorization state is unknown, expired, or already used — restart "
            "Connect with Anthropic.",
        )
    if row.get("userId") != current_user["id"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This authorization was started by a different user.",
        )
    try:
        tok = anthropic_oauth.exchange_code(code, row["codeVerifier"], state)
    except anthropic_oauth.OAuthExchangeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Anthropic rejected the authorization code — restart Connect with "
            "Anthropic.",
        ) from exc
    try:
        anthropic_oauth.persist_tokens(current_user["id"], tok)
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _provider_status_object("anthropic", current_user["id"])


@router.post("/providers/anthropic/oauth/refresh")
def anthropic_oauth_refresh(current_user: CurrentUser) -> dict[str, Any]:
    """Force-refresh the stored subscription token (the "Renew now" action).

    502 + ``needs_reauth`` marked on an honest refresh failure; NEVER a stale
    token, NEVER a cross-provider fallback. Returns the rotated masked status.
    """
    from app.services import anthropic_oauth

    try:
        anthropic_oauth.force_refresh(current_user["id"])
    except anthropic_oauth.OAuthExchangeError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Anthropic could not refresh the subscription session — click Connect "
            "with Anthropic to sign in again.",
        ) from exc
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _provider_status_object("anthropic", current_user["id"])


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

    ``model`` is never raw ``null`` — deterministic/planned agents (no LLM
    tier) fall back to the literal string ``"deterministic"``, the SAME
    fallback ``GET /agents/catalog`` applies (MV-agents-003), so the
    frontend's non-nullable ``TestRunSchema.model`` always parses. The
    cost/token ESTIMATE stays genuinely null for those agents (no fabricated
    spend for a non-LLM run) — only the display string is guaranteed non-null.
    """
    if body.agent_key not in _CATALOG_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{body.agent_key}'")
    entry = _CATALOG_BY_KEY[body.agent_key]
    backend = entry["backend"]
    # Cost the preview against the model this agent will ACTUALLY run on —
    # threading the user's saved per-agent override, exactly as the real run
    # path (`_execute_reserved_run`) and billing audit do (ML-agents-004).
    # Two agents with differently-priced saved models must estimate different
    # cost, never a constant tier-default placeholder.
    llm_model = (
        _model_for_agent(
            backend, override=_user_model_override(current_user["id"], backend)
        )
        if backend
        else None
    )
    model = llm_model or "deterministic"
    est_cost = None
    est_tokens: int | None = None
    if llm_model is not None:
        price_in, price_out = _price_for(llm_model)
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
