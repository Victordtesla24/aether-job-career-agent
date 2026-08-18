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
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.cover_letter_agent import (
    FabricationError,
    PlaceholderSignerError,
    StructuralError,
)
from app.agents.scout_agent import ScoutAgent
from app.db import ensure_user_profile_columns, get_connection, rows_to_dicts
from app.middleware.auth import AdminUser, CurrentUser
from app.repositories.agent_run import AgentRunRepository
from app.repositories.background_jobs import BackgroundJobRepository
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    subscription_gate_enabled,
)
from app.repositories.job import JobRepository
from app.repositories.provider_credential import ProviderCredentialRepository
from app.repositories.user_provider_credential import (
    AgentQuotaBlockRepository,
    AnthropicOAuthStateRepository,
    AnthropicOAuthTokenRepository,
    UserProviderCredentialRepository,
    _ensure_user_agent_tables,
)
from app.services import credential_vault, entitlements
from app.services.agent_run_stream import (
    SSE_HEADERS,
    StreamCapExceeded,
    StreamSlots,
    iter_agent_run_events,
    release_slot_when_done,
)
from app.services.agent_run_watchdog import (
    ABANDONED_ERROR_MARKER,
    agent_run_heartbeat,
)
from app.services.discovery.query_builder import build_scout_query
from app.services.llm_client import (
    LLMUnavailableError,
    QuotaExhaustedError,
    _infer_anthropic_auth_mode,
    circuit_block_error,
    classify_llm_failure,
    claude_auth_mode_filter,
    get_accumulated_usage,
    get_active_credential_env_var,
    get_last_fallback_reason,
    get_last_served_model,
    get_quota_block_hours,
    is_claude_model,
    llm_failure_user_message,
    normalize_model_id,
    resolve_provider,
    resolve_user_credential,
    served_model_capture,
    user_credential_context,
    user_model_context,
    verify_provider_credential,
    verify_user_credential,
)

router = APIRouter()

logger = logging.getLogger(__name__)

#: There is deliberately NO default query/location constant here (F-02). This
#: module used to carry ``_DEFAULT_QUERY = ROLE_FAMILY_QUERY`` +
#: ``_DEFAULT_LOCATION = "Melbourne, Australia"`` and hand them to any caller
#: who supplied none — so every user's "Run All" scouted the same hardcoded
#: PM/BA persona in Melbourne. A discovery run is now derived from the
#: CALLER'S OWN profile (``_user_search_defaults``) or refused outright
#: (``_resolve_scout_target``); with no constant left to fall back to,
#: reintroducing that substitution means adding the literal back here.

#: The LIVE PIPELINE nodes, in pipeline order (mirrors the LangGraph node names
#: in packages/agents/src/graph/aether-graph.ts, and the ``NODES`` array the
#: Orchestration workflow graph renders in
#: apps/web/src/components/agents/Orchestration.tsx, which looks each one up BY
#: NAME in ``GET /agents``). This is the pipeline TOPOLOGY, not the full agent
#: registry: :data:`AGENT_NAMES` below extends it with every other implemented
#: catalog agent, derived so it can never fall behind again (F-3).
_PIPELINE_AGENT_NAMES = (
    "supervisor", "scout", "matcher", "fitScorer", "tailor", "coverLetter",
    "storyExtractor", "emailAgent",
)

#: Agents whose output is gated behind a human approval. The wave-4C outreach
#: agents that produce an OUTBOUND email belong here: like ``emailAgent``, their
#: terminal act is a pending ``email_send`` ApprovalRequest and the single point
#: where a real email leaves the system stays ``POST /approvals/{id}/execute``.
#: An agent that only classifies or drafts text and sends nothing does NOT belong
#: here — the gate marks a pending outbound side-effect, not "produced text".
#:
#: U5d-2: ``submission`` joined this set when its terminal act became a real
#: pending ``application_submit`` ApprovalRequest (FORENSICS.md §4.2). Note the
#: per-run refinement at the ``approvalRequired`` assignment below — membership
#: here declares what the AGENT's terminal act is, and the run record still
#: reports only the gate that run genuinely created.
_APPROVAL_GATED = {
    "tailor", "coverLetter", "emailAgent",
    "recruiterOutreach", "reference", "notification",
    "submission",
}

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


def _price_guarding_down_pricing(
    served_model: str, requested_model: "str | None"
) -> tuple[float, float]:
    """The served model's price, EXCEPT when it has no established price
    (falls through to the flat ``_DEFAULT_PRICE``) while ``requested_model``
    (the user/config-INTENDED model, only non-``None`` on a genuine
    substitution) DOES have one. Adopting the flat default there would
    silently DOWN-price a run whose intended model is properly priced — a
    spend-cap bypass (ML-W14). Keep the intended model's established price
    instead; the served id itself is still recorded honestly by the caller.

    Shared by the genuine-success costing tail and the guard-rejection
    degrade branch (MF-2, wave5-w2122 review) so the two paths cannot drift.
    """
    price_in, price_out = _price_for(served_model)
    if (
        requested_model is not None
        and (price_in, price_out) == _DEFAULT_PRICE
        and _price_for(requested_model) != _DEFAULT_PRICE
    ):
        price_in, price_out = _price_for(requested_model)
    return price_in, price_out


def _static_catalog_model_ids(provider_id: str) -> list[str]:
    """The curated static catalog ids for a provider without an open ``/models``
    endpoint (today: anthropic only — ADR-ML-4 justifies the static list because
    Anthropic exposes no open catalog to curate FROM).

    ONE source of truth: ``llm_client._STATIC_MODEL_CATALOG``, the exact list
    ``GET /agents/providers/{provider}/models`` already serves. Returns ``[]``
    for every provider that has no static catalog, so nothing is ever invented.
    """
    from app.services.llm_client import _STATIC_MODEL_CATALOG

    return [m["id"] for m in _STATIC_MODEL_CATALOG.get(provider_id, [])]


def _flagship_static_model_id(provider_id: str) -> str:
    """The premium-tier ("flagship") id of a provider's static catalog, or ``""``."""
    from app.services.llm_client import _STATIC_MODEL_CATALOG

    for model in _STATIC_MODEL_CATALOG.get(provider_id, []):
        if model.get("tier") == "premium":
            return str(model["id"])
    return ""


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
    # ADR-AG-1 (wave-4A): the old tip promised "careful reasoning about
    # truthfulness and evidence verification" — a second-opinion LLM verifier
    # that does not exist. The ONLY truthfulness authority is the generation-time
    # fabrication/entailment guard, so this card surfaces ITS verdicts.
    {"key": "compliance", "name": "Compliance Agent", "icon": "fa-shield-halved",
     "accent": "green", "backend": "compliance", "recommended": "deterministic",
     "tip": "Per-artifact compliance report over the fabrication/entailment guard "
            "verdicts your own tailoring and cover-letter runs already recorded — "
            "which claims were rejected, flagged or withheld, and which artifacts "
            "came back clean. Runs that never reached a verdict are excluded, never "
            "passed. Deterministic, no LLM cost."},
    # ADR-AG-1 (GM2-AGENTS-001) + U5d + U5d-2. The tip has been wrong twice. It
    # first promised "reliable form-filling and browser automation reasoning";
    # that was replaced with "Submits one of your OWN ready applications", which
    # production proved is ALSO false — the card wrote tracker bookkeeping and
    # transmitted nothing (0 of 606 applications has ever carried a
    # transmittedAt; FORENSICS.md). U5d-2 rewired the run to the real U5 apply
    # engine, so the tip now describes THAT: it prepares and gates, it never
    # transmits, and the approval is named as the thing that does.
    {"key": "submission", "name": "Submission Agent", "icon": "fa-paper-plane",
     "accent": "green", "backend": "submission", "recommended": "deterministic",
     "tip": "Takes one of your OWN ready applications (a job-tailored resume "
            "plus a non-empty Cover Letter Studio draft — the exact gate the "
            "Jobs board's Apply button enforces), works out how that posting "
            "can actually be applied to, and queues it for your approval. It "
            "transmits NOTHING itself: a run ends as a pending card in "
            "Approvals, and the application only reaches the employer when you "
            "approve it there or press Submit on the application card. Where "
            "Aether will not auto-submit — Lever, SmartRecruiters, an "
            "employer's own form, Seek — it says so and hands you the direct "
            "link instead of pretending. Every run reports its real state — "
            "transmitted, awaiting approval, manual step required, or no "
            "change — read back from the row, never assumed. With no job "
            "specified it picks your most recently updated ready application "
            "and reports which one. Deterministic, no LLM cost."},
    {"key": "matchScoring", "name": "Match Scoring Agent", "icon": "fa-bullseye",
     "accent": "indigo", "backend": "fitScorer", "recommended": "deterministic",
     "tip": "Deterministic 10-dimension fit scoring + ATS keyword/semantic engine — "
            "scores every discovered job with no LLM cost."},
    {"key": "jobMatching", "name": "Job Matching Agent", "icon": "fa-arrows-to-dot",
     "accent": "indigo", "backend": "matcher", "recommended": "deterministic",
     "tip": "Ranks every fit-scored job and selects the best-fit target for tailoring — "
            "the matcher node of the live pipeline, now runnable on its own. "
            "Deterministic, no LLM cost."},
    # ADR-AG-1 (wave-4A): "aggregates salary data at scale" implied a salary
    # data source. There is none — the only pay data Aether holds is what each
    # discovered posting disclosed, so that is exactly what this aggregates.
    {"key": "salaryIntelligence", "name": "Salary Intelligence Agent", "icon": "fa-sack-dollar",
     "accent": "amber", "backend": "salaryIntelligence", "recommended": "deterministic",
     "tip": "Aggregates the salary ranges your own discovered postings actually "
            "disclosed, grouped by role family, location and currency, and always "
            "reports how many of them disclosed pay at all. A missing bound is left "
            "empty — never imputed, never benchmarked against outside data, and "
            "currencies are never merged. Deterministic, no LLM cost."},
    # ADR-AG-1 (wave-4B): "realistic mock interviews" described an interactive
    # session (turn-taking, speech analysis) that does not exist. What does exist
    # is a prep brief: questions predicted from the real posting, answered from
    # the user's own Story Bank in STAR + Reflection form, and an honest "prepare
    # one" wherever no real story fits.
    {"key": "interviewPrep", "name": "Interview Prep Agent", "icon": "fa-comments",
     "accent": "coral", "backend": "interviewPrep", "recommended": "claude-sonnet-4",
     "tip": "Predicts the questions this employer is likely to ask from the real "
            "job description and requirements, then answers each one from YOUR "
            "Story Bank as a STAR + reflection sketch. A suggested story is "
            "always one of your real stories and an answer only uses what that "
            "story says — where nothing fits, it says so and tells you to "
            "prepare one. Feeds the Interview Center's prep panel."},
    # ADR-AG-1 (wave-4A): there is no web-research integration, so "from web
    # sources" was unachievable. The honest scope is synthesis over the user's
    # OWN postings, with an opt-in, guard-checked LLM narrative.
    {"key": "companyResearch", "name": "Company Research Agent", "icon": "fa-building",
     "accent": "indigo", "backend": "companyResearch", "recommended": "gpt-4o",
     "tip": "Synthesises what your own discovered postings say about a company — "
            "roles, locations, remote mix, disclosed pay, boards, first/last seen — "
            "and flags low confidence when only one posting exists. No external web "
            "research. An optional LLM narrative (opt-in per run, metered) is "
            "grounded in those same postings and withheld if the fabrication guard "
            "flags it."},
    {"key": "skillGap", "name": "Skill Gap Agent", "icon": "fa-code-compare",
     "accent": "green", "backend": "fitScorer", "recommended": "deterministic",
     "tip": "Surfaces the job's missing keywords from the ATS engine "
            "(ATSScore.missing_keywords) — the skill-gap facet of Match Scoring. "
            "Already shipped; deterministic, no LLM cost."},
    # ADR-AG-1 (wave-4C): the promised "future dedicated OutreachAgent" now
    # exists, at exactly the scope the old tip reserved for it — no enrichment,
    # no external research, no auto-send.
    {"key": "recruiterOutreach", "name": "Recruiter Outreach Agent", "icon": "fa-handshake",
     "accent": "coral", "backend": "recruiterOutreach", "recommended": "claude-sonnet-4",
     "tip": "Drafts the FIRST outbound email to a contact of yours who has no email "
            "thread yet — grounded only in your own résumé, Story Bank, and that "
            "contact's recorded details, with no enrichment and no external research. Blocks "
            "honestly when the contact has no email address, and points you at the "
            "Email Agent when a thread already exists. The send is approval-gated: "
            "nothing leaves until you approve it, and approving needs a connected "
            "Gmail."},
    {"key": "emailAgent", "name": "Email Agent", "icon": "fa-envelope",
     "accent": "coral", "backend": "emailAgent", "recommended": "claude-sonnet-4",
     "tip": "Real Gmail-backed inbox triage, evidence-grounded reply and follow-up drafting, "
            "label management and per-thread insights. Sends are approval-gated. Best with "
            "Claude claude-sonnet-4. Connect Gmail (Email Center) to activate live send/sync."},
    # ADR-AG-1 (wave-4A): Aether subscribes to no market-data feed, so
    # "market & hiring trend signals" claimed a source that does not exist. The
    # honest scope is trends WITHIN the user's own discovery feed.
    {"key": "marketTrends", "name": "Market Trends Agent", "icon": "fa-arrow-trend-up",
     "accent": "indigo", "backend": "marketTrends", "recommended": "deterministic",
     "tip": "Trends inside your own discovery feed — keyword shifts between the "
            "earlier and recent half of your postings, the remote/onsite mix, and "
            "postings per week by discovery date. No external market-data feed. "
            "Says \"not enough data\" below the sample threshold instead of "
            "reporting a flat trend. Deterministic, no LLM cost."},
    # ADR-AG-1 (wave-4C) forbade any calendar claim because no Calendar OAuth
    # existed. ADR-CALENDAR-V4 (W-CAL) supersedes that: calendar.events is now
    # really requested, so the capability is CONDITIONAL on this user's own
    # grant — and the copy says so in both directions rather than picking one.
    {"key": "scheduling", "name": "Scheduling Agent", "icon": "fa-calendar-check",
     "accent": "green", "backend": "scheduling", "recommended": "gpt-4o-mini",
     "tip": "Drafts your reply on an email thread attached to an application that "
            "is really at the Interview stage. With Google Calendar connected it "
            "proposes windows your real free/busy shows as free; without it Aether "
            "reads no calendar for you and proposes only the availability you pass "
            "it, otherwise asking the sender for windows — it never invents a time, "
            "never books anything and never sends. Send the draft from the Email "
            "Center when you are happy with it."},
    # ADR-AG-1 (wave-4C): the scope was real, but the tip described a capability
    # ("scoring of replies") without saying what it reads or how it degrades.
    {"key": "sentimentAnalysis", "name": "Sentiment Analysis Agent", "icon": "fa-face-smile",
     "accent": "coral", "backend": "sentimentAnalysis", "recommended": "claude-3.5-haiku",
     "tip": "Reads the tone of ONE of your real synced email threads per run — a "
            "tone from a fixed set, a 0-100 positivity score, the phrases that drove "
            "the call, and a short explanation withheld if the fabrication guard "
            "flags it. Reports which thread it read, says so honestly when you have "
            "no threads or the message is empty, and never changes the Email Agent's "
            "own triage labels."},
    # ADR-AG-1 (wave-4C): "& reminders" claimed a reminder scheduler that does not
    # exist. The real half — drafting the reference REQUEST itself — ships here.
    {"key": "reference", "name": "Reference Agent", "icon": "fa-user-check",
     "accent": "indigo", "backend": "reference", "recommended": "gpt-4o-mini",
     "tip": "Drafts the reference REQUEST to one of your contacts, grounded only in "
            "your own résumé, Story Bank, and that contact's recorded details, and reports the "
            "requests it already raised for them so a repeat run is a visible "
            "re-draft. No reminder scheduling exists, so none is claimed. The send "
            "is approval-gated — nothing leaves until you approve it, and approving "
            "needs a connected Gmail."},
    {"key": "storyExtraction", "name": "Story Extraction Agent", "icon": "fa-book-bookmark",
     "accent": "coral", "backend": "storyExtractor", "recommended": "claude-haiku-4-5-20251001",
     "tip": "Mines the base resume into STAR+R evidence stories for the Story Bank — "
            "runs on the STRUCTURED model tier."},
    # ADR-AG-1 (wave-4A): nothing in Aether adapts or retrains from outcomes, so
    # "learns from application outcomes to refine future tailoring" described a
    # feedback loop that does not exist. Ships as a read-only outcomes report.
    {"key": "learningFeedback", "name": "Learning / Feedback Agent", "icon": "fa-graduation-cap",
     "accent": "coral", "backend": "learningFeedback", "recommended": "deterministic",
     "tip": "Read-only outcomes report: your application statuses cross-referenced "
            "with fit score, whether the résumé was tailored for that job, and "
            "whether a cover letter was attached. Reports observed association only "
            "— it never adapts, retrains or re-weights anything — and withholds "
            "every rate below the sample threshold. Deterministic, no LLM cost."},
    # ML-U1X-b: the Orchestrator ROLE. Its sequencing today is deterministic
    # code, but the role now carries the model the supervisor/planning step is
    # assigned — defaulting to the Anthropic catalog's flagship, user-switchable
    # down to sonnet/haiku through the SAME per-agent override machinery every
    # other role uses (see ``_ROLE_MODEL_BACKENDS``).
    {"key": "orchestration", "name": "Orchestration Agent", "icon": "fa-sitemap",
     "accent": "indigo", "backend": "supervisor",
     "recommended": _flagship_static_model_id("anthropic"),
     "tip": "Plans and sequences the live pipeline (supervisor node): scout → fitScorer → "
            "matcher → tailor → coverLetter. The model assigned here is the "
            "orchestrator role's model; today's sequencing itself is "
            "deterministic, so this assignment costs nothing until a planning "
            "call runs on it."},
    # ADR-AG-1 (wave-4C): "pushes timely alerts" claimed a push channel that does
    # not exist (no web-push, no SMS, no mobile app). The channel that DOES exist
    # is the user's own connected Gmail, so that is what this now says.
    {"key": "notification", "name": "Notification Agent", "icon": "fa-bell",
     "accent": "green", "backend": "notification", "recommended": "deterministic",
     "tip": "Emails you a digest of your OWN activity — applications whose record "
            "changed and newly scored matches — to your connected Gmail, and only "
            "after you approve it. \"Since last digest\" means the last digest you "
            "actually sent, so a digest you reject is never lost. With nothing new "
            "it queues nothing rather than sending an empty update, and with no "
            "Gmail connected it says so instead of pretending to send. Deterministic, "
            "no LLM cost."},
]

_CATALOG_BY_KEY = {a["key"]: a for a in AGENT_CATALOG}
#: Reverse map: backend run name → catalog key (for status derivation).
_BACKEND_TO_KEY = {a["backend"]: a["key"] for a in AGENT_CATALOG if a["backend"]}
#: A single backend can power several catalog facets (fitScorer serves Match
#: Scoring plus its ATS-optimization / skill-gap facets); pin the canonical card
#: so stat displays name the primary agent, not whichever facet sorted last.
_BACKEND_TO_KEY["fitScorer"] = "matchScoring"


def honest_catalog_counts() -> dict[str, int]:
    """The honest basis behind every agent count this product shows.

    AUD-AGENT-4. :data:`AGENT_CATALOG` is a list of CARDS, not of agents: one
    deterministic engine (``fitScorer``) is presented as THREE cards — Match
    Scoring, ATS Optimization and Skill Gap — so ``len(AGENT_CATALOG)`` has
    never been a count of agents. ``GET /agents/catalog`` transmitted only that
    length (as ``counts.total``) and every surface rendered it as "22 agents",
    which counted one engine three times and padded the product's headline
    number.

    BOTH facts are computed here and BOTH are transmitted, so no screen has to
    guess which number it is holding:

    ``engines``  distinct implemented backends — the agents that actually exist.
    ``cards``    catalog entries — what the configuration grid renders.

    Cards with no backend are roadmap entries: they are counted as cards (they
    are on screen) and never as engines (nothing runs behind them).
    """
    return {
        "engines": len({a["backend"] for a in AGENT_CATALOG if a.get("backend")}),
        "cards": len(AGENT_CATALOG),
    }


def honest_map_counts(agent_keys: Iterable[str]) -> dict[str, int]:
    """The same honest basis as :func:`honest_catalog_counts`, per WORKFLOW MAP.

    AUD-AGENT-4, round 2. The orchestration screen draws one panel per map and
    its header stated a scale. That header summed the map's NODES, and a node
    is a CARD: the "Fit Scoring" stage lists ``matchScoring``,
    ``atsOptimization`` and ``skillGap``, which are three faces of the single
    ``fitScorer`` engine, so the header claimed 12 agents for a pipeline of 10.
    Exactly the padding this finding names, on the same screen as the catalog
    surfaces its first half fixed.

    So the server computes the map's scale too, and transmits BOTH numbers:
    the header states them as a pair ("N engines powering M cards") rather than
    picking one and calling it agents. Duplicate keys within a map collapse —
    a card placed twice is still one card.

    Keys with no catalog entry are ignored (the map builder drops them from the
    payload as well, so counting them would describe nodes nobody can see).
    """
    keys = [k for k in dict.fromkeys(agent_keys) if k in _CATALOG_BY_KEY]
    backends = {b for b in (_CATALOG_BY_KEY[k].get("backend") for k in keys) if b}
    return {"engines": len(backends), "cards": len(keys)}


#: Canonical agent registry — every DISTINCT implemented agent, DERIVED from the
#: catalog rather than hardcoded (F-3, PROD-VERIFY-5A).
#:
#: This was an 8-name literal while ``GET /agents/catalog`` reported 16 active
#: cards, so ``GET /agents`` — read by the sidebar Agent Pulse ("N agents
#: ready", rendered on EVERY dashboard screen), the topbar search index and the
#: Orchestration view — silently omitted all six wave-4A/4B agents and the
#: product contradicted itself on screen. Deriving the set means wiring a new
#: agent into :data:`AGENT_CATALOG` cannot leave this list (or those counts)
#: stale again.
#:
#: Ordering is deliberate and load-bearing: the pipeline nodes come FIRST, in
#: pipeline order, because the Orchestration workflow graph renders that
#: topology and reads each node's health out of this list by name. The remaining
#: implemented agents follow in catalog order.
#:
#: One row per AGENT, not per card: ``fitScorer`` powers three catalog facets
#: (Match Scoring, ATS Optimization, Skill Gap) but is one agent, so ``len()``
#: here is legitimately lower than the catalog's ``counts.active`` card total —
#: the two numbers count different things and stay reconcilable, unlike the
#: 8-vs-16 disagreement about the agent SET that this replaces. Catalog entries
#: with no ``backend`` are roadmap cards ("planned") and are deliberately absent:
#: an agent that cannot run is never reported as ready.
AGENT_NAMES: tuple[str, ...] = _PIPELINE_AGENT_NAMES + tuple(
    backend
    for backend in dict.fromkeys(
        e["backend"] for e in AGENT_CATALOG if e.get("backend")
    )
    if backend not in _PIPELINE_AGENT_NAMES
)

#: The 6 AI providers offered by the Agents screen. This is a static catalog
#: of identity/branding only — connection status, active model, and detail
#: strings are derived at request time from the credentials that actually
#: exist in the server environment (see ``_provider_env_state``). Nothing here
#: may claim a connection that does not exist.
PROVIDER_SEED: list[dict[str, Any]] = [
    # ML-U1X-a: the anthropic seed hardcoded ``[]`` while a working 3-model
    # curated catalog existed and was already served by
    # GET /agents/providers/anthropic/models — so a genuinely connected+verified
    # Anthropic credential still rendered "No preset models". The seed now
    # carries that same catalog (identical wire shape: list[str]); whether a
    # card actually OFFERS them still depends on a real credential existing
    # (see ``_build_provider_entry`` / ``_build_user_provider_entry``, D-0020).
    {"id": "anthropic", "name": "Anthropic Claude", "auth": "API Key",
     "models": _static_catalog_model_ids("anthropic"), "icon": "fa-a", "color": "#D97757"},
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
    names the credential source, authMode and provider.

    ``quotaPath`` is ``subscription_quota`` when the resolved credential is the
    operator's Anthropic subscription token (``authMode=oauth_token``) — the
    ONLY credential a Claude run may spend (MODEL-SUB-QUOTA) and one that draws
    the Pro/Max subscription, not metered credits — and ``metered_api`` for
    every other supported credential. The legacy in-app consumer OAuth flow
    stays removed for compliance (GAP-AUTH-001); this is the pasted Claude Code
    token added by GAP-P7-DEF-A, which really is subscription-funded, so
    labelling it ``metered_api`` was a false disclosure.
    """
    # ML-U1X-b: a backend that makes no metered LLM call has no billing
    # provenance to name — including a ROLE backend (supervisor) that carries an
    # assigned model for the picker but never calls it. Unchanged behaviour for
    # every metered backend below.
    if agent_name not in _LLM_TIER_BY_BACKEND:
        return {"quotaPath": "none"}, None
    # Reflect the user's chosen model so the audit names the credential/provider
    # of the model that will ACTUALLY serve the run (GAP-P7-MODEL-CHOICE-001).
    model = _model_for_agent(agent_name, override=_user_model_override(user_id, agent_name))
    if model is None:
        return {"quotaPath": "none"}, None
    provider = resolve_provider(model)
    try:
        # MODEL-SUB-QUOTA clause 6: resolve through the SAME filter the live
        # call uses (``llm_client._call_live``), or the audit would name a
        # credential that will never serve this run — e.g. a user's Anthropic
        # api_key recorded as the payer of a Claude run the operator's
        # subscription actually funds. The audit must describe the real one.
        cred = resolve_user_credential(
            provider, user_id, agent_name,
            require_auth_modes=claude_auth_mode_filter(model),
        )
    except Exception:  # noqa: BLE001 — audit must never break a run
        cred = None
    if cred is None:
        return (
            {"credentialSource": "none", "authMode": None,
             "provider": provider, "quotaPath": "none"},
            provider,
        )
    # Consumer subscription OAuth is removed (GAP-AUTH-001): every supported
    # credential (api_key / env) bills as metered API usage. The one exception
    # is the operator's Anthropic SUBSCRIPTION token — the only credential a
    # Claude run may spend (MODEL-SUB-QUOTA) — which draws the Pro/Max
    # subscription quota, not metered credits, and is labelled as such.
    quota_path = (
        "subscription_quota"
        if provider == "anthropic" and cred.auth_mode == "oauth_token"
        else "metered_api"
    )
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


def _raise_if_llm_circuit_open(provider: str, block: dict[str, Any]) -> None:
    """Refuse the run with an honest 503 when ``block`` is a CIRCUIT cooldown.

    CRITICAL-3b (adversarial review of 0b6102d, BLOCKING). The circuit breaker
    parks its cooldown in the SAME ``AgentQuotaBlock`` row that carries
    subscription-quota cooldowns, distinguished only by ``reason``. The gates
    that consult that row before every run did not read ``reason``, so from the
    SECOND attempt onward — the first attempt opens the circuit, so only later
    ones ever see the row — an upstream HTTP 402 (OUR provider is out of
    credit) was reported to the paying user as:

        "Your <provider> subscription quota is exhausted. Runs are paused until
         it resets." + "Switch this agent to API-key billing."

    Every clause of that is false for a 402, it blames the user for an operator
    failure, and the suggested remedy cannot work. Worse, ``board_sweep``
    treats an HTTP 429 as ``reason="quota-exhausted"``, so the operator's own
    telemetry agreed with the lie and hid the dead upstream.

    A circuit cooldown now raises the SAME honest, class-specific 503 the
    in-run failure path raises (``llm_failure_user_message``), so a user sees
    one consistent story on attempt 1 and attempt 2:

    * ``insufficient_credits`` / ``auth`` → an operator/service problem, stated
      plainly, with NO upgrade CTA and no claim that retrying helps;
    * anything else (a row whose class we cannot read) → the unchanged
      transient message, i.e. retry with backoff.

    ``raise ... from circuit`` is load-bearing, not cosmetic: it sets
    ``__cause__``, which is how ``board_sweep._llm_failure`` recovers the class
    through the HTTP translation and stops the autopilot instead of counting an
    ordinary failure. A genuine subscription-quota row returns here untouched
    and keeps its 429.

    Raised BEFORE any quota reserve or ``AgentRun`` row, so a run refused
    because our upstream is out of credit consumes nothing of the user's plan.
    """
    circuit = circuit_block_error(provider, block)
    if circuit is None:
        return
    logger.warning(
        "refusing run for user provider=%s: LLM circuit open (class=%s) until %s",
        provider, circuit.failure_class, circuit.expires_at,
    )
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, llm_failure_user_message(circuit)
    ) from circuit


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

    ADMIN-FULL: the "is this caller entitled" question is answered by the ONE
    resolver (``app.services.entitlements``) rather than by a local
    ``has_active_paid_subscription`` call. For an ordinary user the verdict is
    byte-identical (the resolver asks the very same repository); an admin, or a
    user an admin granted a comp/tier/unlimited entitlement, passes here without
    a Stripe subscription — which is the whole point of the mandate.
    """
    if not subscription_gate_enabled():
        return
    if system_run and agent_name in _SYSTEM_RUN_EXEMPT_AGENTS:
        return
    if entitlements.resolve(user_id).entitled:
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


class _SpendOnlyQuota:
    """Quota facade for automated system runs: USD cap ON, run-count quota OFF.

    S-4 split what used to be one ``skip_quota`` switch into its two genuinely
    different halves. Skipping the RUN-COUNT quota is correct — the board sweep
    is infrastructure and must not eat a subscriber's paid run allowance. But
    the same switch also disabled the USD spend cap and the spend accounting, so
    sweep-driven tailor/coverLetter calls spent real money that the cap could
    neither see nor stop.

    This object is handed to ``_execute_reserved_run`` in place of
    ``UsageQuotaRepository`` for those runs, so:

    * ``refund_run`` is an honest no-op — no run was ever reserved, and
      decrementing ``runsUsed`` here would refund a run the user never spent,
      handing them free quota every time the sweep failed.
    * ``record_spend`` writes through unchanged, so realized sweep spend lands in
      ``spendUsedUsd`` and the pre-dispatch cap check above halts the NEXT run
      once the ceiling is reached.
    """

    def __init__(self) -> None:
        self._repo = UsageQuotaRepository()

    def refund_run(self, user_id: str) -> None:
        return None

    def record_spend(self, user_id: str, cost_usd: float) -> None:
        self._repo.record_spend(user_id, cost_usd)

    def get_by_user(self, user_id: str) -> dict[str, Any] | None:
        return self._repo.get_by_user(user_id)


def _record_run(
    user_id: str,
    agent_name: str,
    params: dict[str, Any],
    fn: Callable[[], Any],
    *,
    system_run: bool = False,
    skip_quota: bool = False,
    parent_run_id: str | None = None,
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

    ``skip_quota``: True when the caller is an automated system operation
    (e.g. the board sweep) that MUST NOT consume the user's paid plan RUN
    allowance. The exemption covers the run-count reserve ONLY (S-4): the
    per-user USD ``spendCapUsd`` is still enforced before dispatch and the
    realized spend is still recorded afterwards (see ``_SpendOnlyQuota``),
    because automated work spends the user's real dollars. The audit row is
    stamped ``systemRun: true`` so the exemption is honestly traceable, and the
    quota cooldown block check still runs — a genuinely blocked user should
    never have system ops run either.

    ``parent_run_id`` (B6, ORCH-B1-BLUEPRINT-2026-08-14.md §4.4): the id of the
    AgentRun that CAUSED this one — set by ``_pipeline_core`` for every step it
    dispatches, so the agents-console orchestration map can draw a REAL causal
    edge. ``None`` (the default) is the honest value for a directly-triggered
    run: it has no parent, and nothing here invents one.
    """
    # Entitlement gate FIRST (GAP-P6-PAYWALL): no active paid subscription -> an
    # honest 402 before any audit row, quota reserve, or LLM call.
    _require_active_subscription(user_id, agent_name=agent_name, system_run=system_run)
    # U-AX: idempotent — ``_dispatch`` has normally stamped the policy already;
    # this covers the direct ``_record_run`` callers (the pipeline's supervisor
    # and matcher nodes) so EVERY AgentRun row carries the tier it ran under.
    # ``agent_name`` is already canonical here (every caller passes a real
    # backend key, never an alias), so it doubles directly as the B1b
    # directive-resolution key.
    params = _with_quality_policy(user_id, params, agent_key=agent_name)
    runs = AgentRunRepository()
    audit, provider = _billing_audit(user_id, agent_name)
    if system_run or skip_quota:
        audit["systemRun"] = True
    # Quota cooldown check BEFORE starting a run row — a blocked user gets a
    # clean 429 with no wasted audit record.
    if provider is not None:
        try:
            block = AgentQuotaBlockRepository().get_active(user_id, provider)
        except Exception:  # noqa: BLE001 — block store down → allow the run
            block = None
        if block is not None:
            # CRITICAL-3b: a CIRCUIT cooldown (our upstream refused) is an
            # operator failure — honest 503, never the user's quota. A genuine
            # subscription-quota row falls through and keeps its 429.
            _raise_if_llm_circuit_open(provider, block)
            raise _quota_429(provider, block.get("expiresAt"))

    # Plan quota gate (GAP-P6-BILL-002): atomically RESERVE one run BEFORE the
    # run row is created. Only metered agents (those that actually call the LLM)
    # consume quota — deterministic agents (scout/fitScorer/matcher/supervisor)
    # make no LLM calls and pass through unmetered. The USD spend cap is checked
    # against the accumulated spend right after reserving; on breach the reserved
    # run is refunded and the caller gets a distinct 429. A run reserved here is
    # refunded on any failure path below, so a failed run is never billed.
    #
    # When ``skip_quota`` is True (automated system operations such as the board
    # sweep), the plan-quota reserve / spend-cap gates are skipped entirely so
    # system work cannot exhaust the user's paid plan quota. The cooldown block
    # above still applies — a blocked user gets no system ops either.
    # ``_call_is_metered`` (not bare ``in _LLM_TIER_BY_BACKEND``): a backend whose
    # LLM use is OPT-IN per call is unmetered on a call that makes no LLM call, so
    # a $0 deterministic run never reserves a paid run (see
    # ``_OPTIONAL_LLM_BY_BACKEND``). Every call that does reach the model still
    # reserves atomically here, BEFORE execution, exactly as before.
    metered = _call_is_metered(agent_name, params)
    quota_repo: Any = None
    if metered and entitlements.unlimited(user_id):
        # ADMIN-FULL: an admin (or an admin-granted unlimited entitlement) has no
        # run allowance and no USD ceiling, so nothing is reserved and nothing is
        # checked. Realized spend is STILL recorded through ``_SpendOnlyQuota`` —
        # accounting is not a restriction, and /admin/spend must stay truthful.
        quota_repo = _SpendOnlyQuota()
    elif metered and skip_quota:
        # S-4: the exemption is RUN-COUNT ONLY. An automated system run spends
        # the USER's real dollars, so the per-user USD ceiling is checked here —
        # BEFORE the AgentRun row and before any LLM call — and the realized
        # spend is recorded afterwards through ``_SpendOnlyQuota`` exactly like a
        # manual run. Without this the board sweep could spend without limit and
        # the product's own spend cap could neither see it nor stop it.
        capped = UsageQuotaRepository().get_or_create(user_id)
        if capped is not None and float(capped["spendUsedUsd"]) >= float(
            capped["spendCapUsd"]
        ):
            raise _plan_quota_429("spend_cap_exceeded", capped)
        quota_repo = _SpendOnlyQuota()
    elif metered:
        quota_repo = UsageQuotaRepository()
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

    run = runs.start(user_id, agent_name, params, parent_run_id=parent_run_id)
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

    # ML-STOPALL-001: refuse HERE — the ONE seam every dispatch path converges
    # on immediately before real work happens (the sync ``_record_run`` caller
    # has already created this AgentRun row + reservation; the async ARQ
    # worker's ``_run_single_agent_body`` calls this function DIRECTLY,
    # bypassing ``_record_run`` entirely) — when the user has paused this
    # agent (``AgentConfig.enabled=false``, set by the Agents-page per-agent
    # toggle OR the bulk "Stop All Agents" action). Checking here — rather
    # than duplicating the check in both ``_record_run`` and the enqueue seam
    # — means an agent paused AFTER a background job was already enqueued is
    # still honestly refused the instant it reaches execution, with the check
    # written exactly once. Finished + refunded exactly like every other
    # pre-existing refusal below, never a silent run against a config the user
    # disabled and never a bill for work that never happened.
    if not _agent_enabled_for_dispatch(user_id, agent_name):
        message = (
            f'Agent "{agent_name}" is paused (you disabled it on the Agents '
            "page). Re-enable it to run."
        )
        runs.finish(run_id, "failed", error=message)
        _refund_once()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "agent_paused", "message": message, "agentKey": agent_name},
        )

    # Resolve the user's chosen model ONCE — used to bind the run AND to cost it
    # against the model that actually served it (GAP-P7-MODEL-CHOICE-001).
    _override_model = _user_model_override(user_id, agent_name)
    started = time.monotonic()
    # QA3-F-05: when the corrective drafting loop's retries make real,
    # successfully-served LLM calls and the guard only rejects the CONTENT of
    # the final one, ``get_last_served_model()``/``get_accumulated_usage()``
    # still hold that observation — but ONLY until this function's
    # ``served_model_capture()`` scope exits, which resets both on unwind. The
    # ``except (FabricationError, StructuralError)`` handler below runs AFTER
    # that reset (it is attached to the outer ``try``, outside the ``with``),
    # so both must be captured HERE, inside the scope, the instant the
    # exception is caught.
    _degraded_served_model: str | None = None
    _degraded_usage: dict[str, int] | None = None
    _degraded_fallback_reason: str | None = None
    _fallback_reason: str | None = None
    try:
        # Bind BOTH the credential context and the user's chosen model so the
        # deep LLM path resolves THIS user's key AND model.
        #
        # ``agent_run_heartbeat`` (CRITICAL-1) stamps AgentRun.heartbeatAt for
        # as long as this run actually executes. THIS is the seam because it is
        # the ONE place both the sync HTTP path (``_record_run``) and the ARQ
        # worker (``workers.tasks._run_single_agent_body``) — and every pipeline
        # step, which routes through ``_record_run`` too — share. Without the
        # stamp the watchdog could not tell a live run from a dead one and would
        # have to time runs out on age alone, which would murder legitimately
        # long runs. It writes nothing on the success/failure paths below: the
        # ``status='running'`` guard in ``AgentRunRepository.heartbeat`` makes a
        # stamp on an already-finished run impossible.
        with agent_run_heartbeat(run_id), user_credential_context(
            user_id, agent_name
        ), user_model_context(_override_model), served_model_capture():
            try:
                output = _to_output(fn())
            except (FabricationError, StructuralError):
                _degraded_served_model = get_last_served_model()
                # MF-1 (wave5-w2122 review): the REAL accumulated char counts
                # of every successful call the corrective loop made before the
                # guard rejected the final draft's content — never the
                # locally-authored refusal string built after the fact.
                _degraded_usage = get_accumulated_usage()
                _degraded_fallback_reason = get_last_fallback_reason()
                raise
            # OBSERVE (never infer) which model actually served this run, while
            # the observation scope is still open — the LLM client publishes the
            # provider's own ``model`` field on each successful call (ML-W14).
            # ``None`` = nothing observed (deterministic agent, replay mode, or
            # no successful call); the costing below then behaves exactly as it
            # did before this existed.
            _served_model = get_last_served_model()
            # R-5: WHY the chain moved off its primary, published by the
            # mechanism that engaged. Captured inside the scope, next to the
            # served id, because ``served_model_capture``'s ``finally`` resets
            # both on unwind.
            _fallback_reason = get_last_fallback_reason()
            # QA4-F-01 (W-24): the SAME real accumulated char counts the
            # guard-rejection degrade branch already reads (MF-1) — captured
            # here, inside the scope, for the genuine-SUCCESS costing tail
            # below. ``None`` when replay/fixture mode served the run (no
            # live ``_call_live`` call was ever made) or the agent made no
            # LLM call at all; the costing below falls back to the legacy
            # measured-params estimate in exactly that case.
            _success_usage = get_accumulated_usage()
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
        # B6xP1A (ORCH-B1-BLUEPRINT-2026-08-14.md §4.4): the AgentRun row
        # above was created with ``parentRunId`` already set (``_record_run``
        # threads it through ``runs.start(..., parent_run_id=...)`` before
        # execution starts), so the no-op run IS correctly parented in the
        # database. But this handler's re-raise means the caller never gets a
        # dict back to read a "run_id" off of — ``_pipeline_core`` builds its
        # own ``tailor_out`` from the caught exception, and without this it
        # has no way to look the row back up (e.g. via ``GET /agents/runs``)
        # to confirm that parentage. Carried on the exception instance, same
        # precedent as ``exc.degradedUsage`` on the FabricationError/
        # StructuralError branch below.
        exc.run_id = run_id
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
        #
        # CRITICAL-3: the message is now chosen by the FAILURE CLASS the
        # transport attached. A 402 (out of credits) or 401 (bad key) is not
        # "temporarily unavailable" and will not fix itself in "a moment" —
        # telling the owner otherwise is what made a week of a dead upstream
        # look like routine flakiness, and what invited the autopilot to keep
        # retrying. The retryable class keeps the exact previous message.
        user_message = llm_failure_user_message(exc)
        logger.warning(
            "agent run %s LLM-unavailable (class=%s): %s",
            run_id, classify_llm_failure(exc), exc,
        )
        runs.finish(run_id, "failed", error=user_message)
        _refund_once()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, user_message
        ) from exc
    except (FabricationError, StructuralError) as exc:
        # GAP-P4-002: the cover agent's fabrication / §10.2 structural guard
        # rejected the draft after every corrective retry. The guard WORKING is
        # NOT a failure — Aether refuses to ship an ungrounded or non-compliant
        # letter — so record an honest COMPLETED degrade instead of letting the
        # generic ``except Exception`` below stamp the owner-visible "Recent
        # runs" table (and the Agents-screen health classification) with a red
        # ``failed`` row for a correct refusal. This mirrors the treatment the
        # async worker (workers/tasks.py) and ``_pipeline_core`` already give
        # the same two exceptions, so all three paths now agree.
        #
        # Placed AFTER every pre-existing handler and before the generic one so
        # no other clause's reachability changes. The two names are imported at
        # MODULE scope (top of this file): the reverted WIP referenced them with
        # no binding at all, which raised ``NameError`` here and made every
        # handler declared below unreachable — orphaning the AgentRun row in
        # 'running' and skipping the refund (WIP-BRANCH-AUDIT-2026-07-29 #1).
        #
        # ``flagged``/``issues`` are the guard's own entity/issue lists already
        # rendered into English by the exception constructors — never verbatim
        # LLM output, so there is no PII or prompt-leak risk in the audit row.
        reason = getattr(exc, "flagged", None) or getattr(exc, "issues", None)
        honest_output: dict[str, Any] = {
            "cover_letter_id": None,
            "coverLetterUnavailable": True,
            "reason": str(reason),
            "message": (
                "An auto-generated cover letter couldn't be produced without "
                "unverifiable wording, so it was withheld — open the Cover "
                "Letter studio to generate or write one manually."
            ),
        }
        # QA3-F-05: the corrective retries that led here made real,
        # successfully-served LLM calls before the guard rejected the final
        # draft's CONTENT — only a run whose EVERY attempt failed outright
        # (``_degraded_served_model`` is None: nothing was ever observed, e.g.
        # an LLMUnavailableError on the very first draft) genuinely spent
        # nothing. Cost the served calls with the SAME measured-I/O-size
        # estimate + published per-token price every other run is costed with
        # (ML-W14's ``_price_for`` — no new pricing logic invented), instead of
        # the previous hardcoded zero that hid real spend from the audit row,
        # GET /agents/stats and the USD spend cap.
        if _degraded_served_model:
            # MF-1 (wave5-w2122 review, HIGH): tokensOut must measure what the
            # model ACTUALLY emitted across every successful call the
            # corrective loop made (draft + retry + retry2 all reach this
            # handler only when a FabricationError/StructuralError survives
            # every retry — i.e. every one of them ran) — never the
            # `honest_output` refusal dict, which is an English sentence THIS
            # handler authors locally and no model ever produced.
            # ``get_accumulated_usage()`` was captured above, inside the
            # ``served_model_capture()`` scope, before it could reset.
            usage = _degraded_usage or {}
            tokens_in = max(1, usage.get("charsIn", 0) // 4)
            tokens_out = max(1, usage.get("charsOut", 0) // 4)
            # MF-2 (wave5-w2122 review, MED): mirror the success path's
            # no-silent-substitution bookkeeping (agents.py's costing tail
            # below, ``output["requestedModel"]``) — a degraded run can be
            # served by a different model than the one intended just like a
            # successful one, and that must stay auditable here too.
            _intended_model = _model_for_agent(agent_name, override=_override_model)
            if _intended_model is not None and _intended_model != _degraded_served_model:
                honest_output["requestedModel"] = _intended_model
                if _degraded_fallback_reason:
                    honest_output["fallbackReason"] = _degraded_fallback_reason
            # R-5 recorded ``servedModel`` only on a substitution; D5 (audit
            # wf_9a87f76f-eaa, Track E) discloses the served model AND its
            # billing provider on EVERY degraded run that made a real LLM call
            # — mirroring the success tail below. Same observation truth
            # (``get_last_served_model``, captured inside the scope) and the
            # same pure provider resolution the billing audit uses; nothing is
            # fabricated — this whole branch is gated on the observation.
            honest_output["servedModel"] = _degraded_served_model
            honest_output["servedProvider"] = resolve_provider(_degraded_served_model)
            price_in, price_out = _price_guarding_down_pricing(
                _degraded_served_model, honest_output.get("requestedModel")
            )
            degraded_cost = round(
                tokens_in / 1000 * price_in + tokens_out / 1000 * price_out, 6
            )
            honest_output["model"] = _degraded_served_model
            honest_output["tokensIn"] = tokens_in
            honest_output["tokensOut"] = tokens_out
            honest_output["costUsd"] = degraded_cost
        else:
            degraded_cost = 0.0
            honest_output["model"] = None
            honest_output["tokensIn"] = 0
            honest_output["tokensOut"] = 0
            honest_output["costUsd"] = 0.0
        runs.finish(run_id, "completed", output=honest_output, cost_usd=degraded_cost)
        # No LETTER was produced, so the reserved RUN is refunded — exactly like
        # the NoChangesApplied no-op above. On the ASYNC path manage_quota=False
        # makes this a no-op and the worker refunds after winning its own atomic
        # first-terminal-wins transition, so the refund happens exactly once on
        # either path, never twice. The run-count refund is a SEPARATE ledger
        # from the realized USD cost recorded above — a degrade is never billed
        # against the user's run allowance, but real LLM spend still counts.
        _refund_once()
        if degraded_cost and manage_quota and quota_repo is not None:
            # Mirrors the success-tail's spend accumulation further below: the
            # USD spend cap must see this cost even though the run itself was
            # refunded, exactly like a genuine success's
            # ``quota_repo.record_spend`` (QA3-F-05). The async single-agent
            # worker (manage_quota=False here) instead reads this cost off the
            # exception attribute below and records it after winning its own
            # atomic terminal transition (workers/tasks.py).
            quota_repo.record_spend(user_id, degraded_cost)
        # Carry the computed usage onto the exception instance so the async
        # worker's mirrored handler (workers/tasks.py) can record the SAME
        # figures on the BackgroundJob result without recomputing them.
        # FabricationError/StructuralError are plain exception subclasses with
        # no such field, so this is purely additive and never breaks their
        # existing (``flagged``/``issues``) contract.
        exc.degradedUsage = {
            "model": honest_output["model"],
            "requestedModel": honest_output.get("requestedModel"),
            # R-5: carried so the async worker's mirrored handler can render the
            # same "served by fallback" chip the sync path does, without
            # recomputing (or re-guessing) anything.
            "servedModel": honest_output.get("servedModel"),
            "fallbackReason": honest_output.get("fallbackReason"),
            "tokensIn": honest_output["tokensIn"],
            "tokensOut": honest_output["tokensOut"],
            "costUsd": honest_output["costUsd"],
        }
        # Re-raise so each caller keeps its own response shape unchanged:
        # ``run_cover_letter`` -> 422, ``_pipeline_core`` -> graceful degrade,
        # the async worker -> its own honest ``coverLetterUnavailable`` result.
        # NOTE: those terminal writes are on the BackgroundJob row, a different
        # table from the AgentRun row finished here, so there is no double
        # terminal transition on any single row (open question API-6).
        raise
    except Exception as exc:
        runs.finish(run_id, "failed", error=str(exc))
        _refund_once()
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    output["duration_ms"] = duration_ms
    # U5d: a run that ITSELF reports it ended awaiting an approval IS gated,
    # whatever the agent-level table says. Derived from the run's OWN output,
    # never assumed, so it cannot report a gate for a run that did not create
    # one.
    #
    # U5d-2: ``submission`` is now IN ``_APPROVAL_GATED`` (its terminal act is a
    # real W-SUB card), which on its own would make the static answer ``true``
    # for EVERY submission run — including the ones that end in a manual step
    # having created no approval at all. That is the same shape of falsehood,
    # pointed the other way, so for any agent whose output carries a
    # ``submissionState`` the run's own persisted state is authoritative: it
    # created a gate iff it says it is awaiting one.
    submission_state = output.get("submissionState")
    output["approvalRequired"] = (
        submission_state == "awaiting_approval"
        if submission_state is not None
        else _run_is_approval_gated(agent_name, params)
    )
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
    # ML-W14: ``_model_for_agent`` is CONFIG-derived INTENT. When the ADMIN
    # free-chain rescue substitutes a $0 model after an OpenRouter 402
    # (llm_client._extend_chain_with_admin_free_models), or the un-chosen
    # system-default chain falls through to its fallback model, the run is
    # served by a DIFFERENT model than the one intended — and costing it against
    # the intended model's published price bills a free run at the paid rate,
    # inflating AgentRun.costUsd, GET /agents/stats ROI and the USD spend cap.
    # The served id observed above wins; the intent is preserved (never erased)
    # as ``requestedModel`` so the substitution stays auditable. Only a genuine
    # difference is recorded, so the ordinary run's output is byte-identical.
    if model is not None and _served_model and _served_model != model:
        logger.info(
            "served-model substitution on run %s (agent=%s): requested=%s "
            "served=%s — costing against the SERVED model",
            run_id, agent_name, model, _served_model,
        )
        output["requestedModel"] = model
        # R-5 (ADR-ML-3 visibility half): the substitution was ALREADY recorded
        # and correctly costed, and was invisible to the user — 19 green plan
        # steps of which some ran on a rescue model is exactly the graceful
        # fiction the design principle forbids. These two additive fields are
        # what the run record and the plan narration render as a "served by
        # fallback" chip. ``model`` already carries the served id, but naming it
        # explicitly means the FE never has to know that ``model`` means
        # "served"; ``fallbackReason`` is written ONLY when the client actually
        # published one, so partial knowledge stays partial instead of being
        # rounded up to a story.
        output["servedModel"] = _served_model
        if _fallback_reason:
            output["fallbackReason"] = _fallback_reason
        model = _served_model
    # D5 (audit wf_9a87f76f-eaa, Track E): the substitution branch above
    # disclosed the served model ONLY when it differed from the config-derived
    # intent — so a run served by exactly the configured cheap/free model (the
    # "auto"/default chains that route to OpenRouter models while the plan copy
    # advertises Claude) disclosed nothing, and NO run output named the billing
    # provider. Disclose both on EVERY run that factually reached an LLM: gated
    # on the provider-published observation itself (``get_last_served_model``,
    # the same truth the costing above uses), with the provider resolved by the
    # SAME pure function the billing audit uses (``resolve_provider``). A run
    # with no successful live call (deterministic agents, honest no-LLM no-ops,
    # replay/fixture mode) observes nothing and stays keyless — never fabricated.
    if _served_model:
        output["servedModel"] = _served_model
        output["servedProvider"] = resolve_provider(_served_model)
    # F-1 re-fix (ML-U1X-b regression): ``_model_for_agent`` now returns a real
    # id for a ROLE backend (``supervisor``/Orchestrator, ``_ROLE_MODEL_BACKENDS``)
    # even though that backend makes NO LLM call today — its sequencing is
    # deterministic (see the comment above ``_LLM_TIER_BY_BACKEND``). A backend
    # absent from ``_LLM_TIER_BY_BACKEND`` NEVER reaches the model regardless of
    # what its picker displays, so it must stay zero-cost/zero-token exactly like
    # every other deterministic agent (scout/fitScorer/matcher) — anything else
    # fabricates the spend/ROI figures GET /agents/stats reports, and would do so
    # for every pipeline run since the supervisor step runs on all of them.
    if (
        model is None
        or no_llm_call
        or cover_degraded
        or agent_name not in _LLM_TIER_BY_BACKEND
    ):
        cost = 0.0
        output["model"] = None
        output["tokensIn"] = 0
        output["tokensOut"] = 0
        output["costUsd"] = 0.0
    else:
        # QA4-F-01 (W-24, HIGH): a SUCCESSFUL run was still costed off
        # ``params`` (the tiny run-trigger dict, e.g. ``{"job_id": ...}``) —
        # near-constant regardless of the real prompt size, while the
        # guard-rejection degrade branch above already reads REAL accumulated
        # usage (MF-1). Live A/B proof: a 3-call success and a 4-call degrade
        # on the SAME build/model/agent recorded tokensIn=414 vs tokensIn
        # =26263 — a ~16x under-report on the revenue-generating path. Use
        # the SAME accumulated-usage observation here, falling back to the
        # legacy params/output estimate ONLY when nothing was accumulated
        # (replay/fixture-mode tests, where no live ``_call_live`` call is
        # ever made — those keep recording exactly what they always have).
        if _success_usage and (_success_usage.get("charsIn") or _success_usage.get("charsOut")):
            tokens_in = max(1, _success_usage.get("charsIn", 0) // 4)
            tokens_out = max(1, _success_usage.get("charsOut", 0) // 4)
        else:
            tokens_in = max(1, len(json.dumps(params, default=str)) // 4) + 400
            tokens_out = max(1, len(json.dumps(output, default=str)) // 4)
        # ML-W14 no-silent-down-pricing rail (shared with the guard-rejection
        # degrade branch above via ``_price_guarding_down_pricing`` — MF-2):
        # the direction of error stays conservative, and the served id is
        # still recorded honestly above regardless of which price wins.
        price_in, price_out = _price_guarding_down_pricing(model, output.get("requestedModel"))
        cost = round(tokens_in / 1000 * price_in + tokens_out / 1000 * price_out, 6)
        output["model"] = model
        output["tokensIn"] = tokens_in
        output["tokensOut"] = tokens_out
        output["costUsd"] = cost
    # Backstop for a backend registered in ``_OPTIONAL_LLM_BY_BACKEND``: the
    # pre-execution predicate said this call WOULD reach the model, so a run was
    # reserved — but the agent then honestly reported it made no LLM call (e.g.
    # companyResearch asked for a narrative with no postings to ground one in;
    # interviewPrep asked to prep with no job and no interview-stage application).
    # Refund it: a reserved run that never touched a model must not be billed, and
    # end-state ``runsUsed`` must be unchanged. Scoped to those backends so the
    # existing per-backend metering of tailor / coverLetter / storyExtractor /
    # emailAgent is not silently re-priced by this change.
    optional_llm_noop = no_llm_call and agent_name in _OPTIONAL_LLM_BY_BACKEND
    if optional_llm_noop:
        # Durable, honest marker (same camelCase convention as
        # ``noChangesApplied`` / ``coverLetterUnavailable`` / ``missingResume``):
        # it records on the audit row that no model was called, and it is the
        # signal the ASYNC worker reads to perform the same refund after winning
        # its own atomic terminal transition. Set only for the scoped backends, so
        # no other agent's output shape changes.
        output["noLlmCall"] = True
    # U2c RULES item 5: stamp the run's quality-gate trail (attempts, each
    # attempt's own score + verdict, the honest terminal state) onto the
    # AgentRun's additive columns, so the Supervisor's directive loop
    # (ADR-AGI-2) can SELECT on it rather than scanning output blobs. This is
    # the one seam both the sync HTTP path and the ARQ worker share, so neither
    # can forget it. Best-effort and derived purely from ``output``: it never
    # re-scores, never fails a run, and writes nothing for a run the gate never
    # judged.
    try:
        runs.record_quality_instrumentation(run_id, output)
    except Exception:  # noqa: BLE001 — instrumentation is additive
        logger.warning("agent run %s: quality instrumentation not recorded", run_id)
    finished = runs.finish(run_id, "completed", output=output, cost_usd=cost)
    if cover_degraded or optional_llm_noop:
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
#: Backends absent here (scout, fitScorer, matcher, supervisor, and the wave-4A
#: report agents compliance/salaryIntelligence/marketTrends/learningFeedback) are
#: deterministic: scraping, embeddings, aggregation and plain code — no LLM spend.
_LLM_TIER_BY_BACKEND: dict[str, str] = {
    "tailor": "REASONING",
    "coverLetter": "REASONING",
    "storyExtractor": "STRUCTURED",
    # RT-004: résumé bullet extraction is ONE STRUCTURED ``complete_json`` call
    # that copies the user's own bullets verbatim out of their résumé text
    # (``services.resume_bullets_llm``). It really does reach a model, so it rides
    # the SAME atomic reserve-before-call / refund-on-failure rail as every
    # other LLM backend — the exemption seam (``_DETERMINISTIC_BACKENDS`` /
    # ``_OPTIONAL_LLM_BY_BACKEND``) exists only for calls that reach NO model,
    # and exempting this one would hand out unmetered LLM capacity at one free
    # run per résumé (the mirror image of F-03's silent metered run).
    #
    # Deliberately ABSENT from ``_RUNNABLE_BACKENDS`` / ``AGENT_CATALOG`` /
    # ``_EXEC_CLASS_BY_BACKEND``: it is a Resume-Studio action on ONE résumé the
    # caller names, not a board-level agent card the Supervisor could schedule,
    # so it is dispatched straight through ``_record_run`` (the same direct
    # seam the pipeline's supervisor/matcher nodes use) rather than
    # ``_dispatch``. STRUCTURED also keeps it OFF the user model-override list
    # — extraction is a fixed-model structured task, not generation.
    "bulletExtractor": "STRUCTURED",
    "emailAgent": "REASONING",
    # companyResearch's deterministic synthesis is free, but its OPT-IN narrative
    # calls the LLM — and metering is per-backend, so the backend must be metered
    # for that call to go through the standard atomic reserve-before-call /
    # refund-on-failure path. Its DEFAULT (narrative-off) call makes no LLM call
    # at all and is therefore not metered either — see
    # ``_OPTIONAL_LLM_BY_BACKEND`` below.
    "companyResearch": "REASONING",
    # wave-4B: interviewPrep reasons over the posting + the user's own STAR
    # stories on every run that has a job to prep for; a run with nothing to prep
    # for reports ``llm_called=False`` and is stamped zero-cost.
    "interviewPrep": "REASONING",
    # wave-4C outreach family. Each drafts or classifies with the model on a run
    # that has real data to work from, and each has honest refusal paths that
    # reach NO model (no eligible contact/thread, a contact with no email address,
    # no résumé) — those report ``llm_called=False`` and are refunded by the
    # backstop, see ``_OPTIONAL_LLM_BY_BACKEND``. ``notification`` is deliberately
    # ABSENT: its digest is a deterministic composition of the user's own rows and
    # calls no model at all.
    "recruiterOutreach": "REASONING",
    "reference": "REASONING",
    "sentimentAnalysis": "REASONING",
    "scheduling": "REASONING",
}


#: EXECUTION CHARTER (ADR-AGI-3 Decision 1) — the Supervisor's scheduler reads
#: THIS and nothing else. Kept adjacent to :data:`_LLM_TIER_BY_BACKEND` because
#: it is the same kind of thing: per-agent facts as DATA, in ONE place, so a
#: scheduler never needs to know an agent's name (``DESIGN-PRINCIPLE.md`` line 9
#: — per-agent branching in the scheduler fails review; a grep test enforces it).
#:
#: Every row was re-verified against the agent's ACTUAL writes at
#: ``uat/reports/evidence/market-perf/u-agi/p1a/EXEC-CLASSES.md`` §2 (R-8: the
#: original classification was scout TESTIMONY and contradicted itself, listing
#: ``emailAgent`` as both SILO and INDEPENDENT). Field meanings:
#:
#: ``execClass``   governs ADMISSION only.
#:   * ``sequential``  — placed by topological order; the application spine.
#:   * ``independent`` — eligible for concurrency, subject to the plan ceiling.
#:   * ``silo``        — at most one in flight per (user, backend), enforced by
#:                       the partial unique index built from
#:                       ``repositories.background_jobs._SINGLETON_AGENTS``. The
#:                       two sets are pinned equal by a test: without the index
#:                       this field would be decorative (F-R8-1).
#: ``siloBasis``   present iff ``silo``. ``race-proven`` = an unguarded
#:                 concurrent-write hazard is cited in EXEC-CLASSES §2;
#:                 ``tier-conservative`` = no race proven, siloed because U-AGI
#:                 §5.3 makes it a T3 real-world actor. Recording the difference
#:                 stops the charter claiming a race it cannot cite.
#: ``onRefusal``   governs PROPAGATION only: ``halt-chain`` ends the plan (the
#:                 spine's shipped ``_pipeline_core`` semantics), ``isolate``
#:                 leaves the rest of the plan running.
#: ``dependsOn``   HARD topological predecessors — a refusal, no-op or degraded
#:                 output follows without them. Sourced from EXEC-CLASSES §2,
#:                 NOT from AGENT-GRAPH.json, which carries only the pipeline
#:                 spine and would under-constrain the plan (§5 "semantic
#:                 drift"): it has no edge for submission←tailor /
#:                 submission←coverLetter (the hard 422 gates at
#:                 ``submission_agent.py:364-383``) or coverLetter←tailor.
#: ``enrichedBy``  SOFT read edges — display/ordering preference only. Never a
#:                 gate: these agents degrade honestly with an empty input.
#: ``coversCards`` the catalog cards ONE dispatch accounts for. This fact lived
#:                 only in the browser (``orchestration-run-plan.ts``), so a
#:                 server plan iterating catalog keys would bill ``fitScorer``
#:                 three times for one unit of work (R-2a). Moved here.
#:
#: ``supervisor`` is deliberately ABSENT: it is not in :data:`_RUNNABLE_BACKENDS`
#: so it is never a plan STEP — it is the thing that builds the plan. Its card
#: (``orchestration``) is covered by the plan itself.
_EXEC_CLASS_BY_BACKEND: dict[str, dict[str, Any]] = {
    "scout": {
        "execClass": "silo", "siloBasis": "race-proven", "onRefusal": "halt-chain",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("jobDiscovery",),
    },
    "fitScorer": {
        "execClass": "sequential", "onRefusal": "halt-chain",
        "dependsOn": ("scout",), "enrichedBy": (),
        "coversCards": ("matchScoring", "atsOptimization", "skillGap"),
    },
    "matcher": {
        "execClass": "sequential", "onRefusal": "halt-chain",
        "dependsOn": ("fitScorer",), "enrichedBy": (),
        "coversCards": ("jobMatching",),
    },
    # ``paramsFrom``: the matcher's chosen job IS the target for both drafting
    # steps — the same value ``_pipeline_core`` threads by hand today. Declaring
    # it as data means a plan can carry a real target without the scheduler
    # knowing what a job is, and a matcher that selected nothing produces an
    # honest "nothing to work on" skip rather than a 422 dressed as a failure.
    "tailor": {
        "execClass": "sequential", "onRefusal": "halt-chain",
        "dependsOn": ("matcher",), "enrichedBy": ("storyExtractor",),
        "paramsFrom": {"job_id": ("matcher", "top_job_id")},
        "coversCards": ("resumeTailoring",),
    },
    "coverLetter": {
        "execClass": "sequential", "onRefusal": "halt-chain",
        "dependsOn": ("tailor", "matcher"), "enrichedBy": ("storyExtractor",),
        "paramsFrom": {"job_id": ("matcher", "top_job_id")},
        "coversCards": ("coverLetter",),
    },
    "submission": {
        "execClass": "silo", "siloBasis": "race-proven", "onRefusal": "isolate",
        "dependsOn": ("tailor", "coverLetter"), "enrichedBy": (),
        "coversCards": ("submission",),
    },
    "emailAgent": {
        "execClass": "silo", "siloBasis": "race-proven", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("emailAgent",),
    },
    "notification": {
        "execClass": "silo", "siloBasis": "race-proven", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("notification",),
    },
    "recruiterOutreach": {
        "execClass": "silo", "siloBasis": "tier-conservative", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("recruiterOutreach",),
    },
    "reference": {
        "execClass": "silo", "siloBasis": "tier-conservative", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("reference",),
    },
    "storyExtractor": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("storyExtraction",),
    },
    "compliance": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("tailor", "coverLetter"),
        "coversCards": ("compliance",),
    },
    "learningFeedback": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": (), "coversCards": ("learningFeedback",),
    },
    "marketTrends": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("scout",), "coversCards": ("marketTrends",),
    },
    "salaryIntelligence": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("scout",),
        "coversCards": ("salaryIntelligence",),
    },
    "companyResearch": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("scout",), "coversCards": ("companyResearch",),
    },
    "interviewPrep": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("scout", "storyExtractor"),
        "coversCards": ("interviewPrep",),
    },
    "sentimentAnalysis": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("emailAgent",),
        "coversCards": ("sentimentAnalysis",),
    },
    "scheduling": {
        "execClass": "independent", "onRefusal": "isolate",
        "dependsOn": (), "enrichedBy": ("emailAgent",), "coversCards": ("scheduling",),
    },
}


def _company_research_wants_narrative(params: dict[str, Any]) -> bool:
    """Whether a companyResearch run will make an LLM call.

    SINGLE source of that decision: ``_agent_callable`` passes this same value to
    :class:`CompanyResearchAgent` as its ``narrative`` argument, and
    :data:`_OPTIONAL_LLM_BY_BACKEND` reads it to decide whether to meter the call.
    Because both sides read ONE function, the metering decision can never
    disagree with what the agent actually does — an unmetered LLM call (a quota
    bypass) is structurally impossible rather than merely unlikely.
    """
    return bool(params.get("narrative"))


def _interview_prep_will_call_llm(params: dict[str, Any]) -> bool:
    """Whether an interviewPrep run will make an LLM call — unknowable from the
    params, so conservatively True (ML-W4B, applying the ruling above).

    Unlike companyResearch, whose opt-in is literally a param, interviewPrep's
    ONE no-LLM-call path depends on DB STATE: no ``job_id`` was supplied AND no
    application of the caller's sits at the interview stage, i.e. there is
    nothing to prep for. Deciding that here would mean re-running the agent's own
    job-resolution query inside the metering predicate — a second source of truth
    that could drift from what the agent actually does, plus an extra query on
    every run. So the atomic reserve-BEFORE-the-LLM-call rail is kept for EVERY
    call, and the honest ``llm_called=False`` the agent reports AFTERWARDS is what
    triggers the refund backstop in ``_execute_reserved_run``. Registering this
    backend below is therefore about the BACKSTOP, never about skipping a
    reserve — a metered call can still never reach a model unreserved.
    """
    return True


#: ``emailAgent`` modes that provably construct NO LLM call at all: ``send``
#: creates a pending ``email_send`` ApprovalRequest, ``apply_labels`` mutates
#: Gmail labels (or degrades honestly when Gmail is not connected), and
#: ``job_alerts`` reads job-alert mail with a deterministic regex/HTML parser
#: (``app.services.job_alert_parser`` — no model, by design: an LLM guessing an
#: employer name out of an email is exactly the fabrication this product
#: refuses). All three are decidable from the params alone, so they are never
#: even reserved.
_EMAIL_AGENT_NO_LLM_MODES = frozenset(
    {"send", "apply_labels", "job_alerts", "job-alerts"}
)

#: The ONLY ``emailAgent`` mode that actually opens an ``ApprovalRequest``.
#: ``emailAgent`` is listed in :data:`_APPROVAL_GATED` because its terminal
#: OUTBOUND act is gated — but the gate is created by ``send`` alone. Every
#: other mode (triage, draft_reply, draft_follow_up, insights, apply_labels,
#: job_alerts) creates no approval row at all, so stamping
#: ``approvalRequired: true`` on them was a DECORATIVE flag — exactly what the
#: MV-resume-studio-001 ruling forbids ("``approvalRequired: true`` must be
#: backed by a real ApprovalRequest, not a decorative flag"). It was harmless
#: while every emailAgent mode produced text a human had to send by hand; it
#: became actively misleading with ``job_alerts``, whose 45 persisted Job rows
#: are final and await nothing.
_EMAIL_AGENT_APPROVAL_MODES = frozenset({"send"})


def _run_is_approval_gated(agent_name: str, params: dict[str, Any]) -> bool:
    """Whether THIS run's terminal act is held behind a human approval.

    Agent-level for every backend except ``emailAgent``, whose approval gate is
    MODE-level (see :data:`_EMAIL_AGENT_APPROVAL_MODES`).
    """
    if agent_name not in _APPROVAL_GATED:
        return False
    if agent_name == "emailAgent":
        mode = str(params.get("mode") or "triage").strip()
        return mode in _EMAIL_AGENT_APPROVAL_MODES
    return True


def _email_agent_will_call_llm(params: dict[str, Any]) -> bool:
    """Whether an emailAgent run will make an LLM call (ML-W4C).

    ``emailAgent`` was metered PER BACKEND, so every mode reserved a run from the
    user's paid plan allowance — including the modes that reach no model. Two
    distinct paths existed and both are covered:

    * PARAMS-DECIDABLE (``send`` / ``apply_labels``): no model is constructed
      whatever the DB holds, so this returns False and no run is reserved at all.
    * DB-STATE-DEPENDENT (``triage`` with nothing to classify — the agent's own
      documented ``llm_called=False`` early return): unknowable from the params
      without re-running the agent's own thread query here (a second source of
      truth), so it stays conservatively metered and the post-execution refund
      backstop in :func:`_execute_reserved_run` restores the reserved run. The
      atomic reserve-BEFORE-the-LLM-call rail therefore still covers every call
      that DOES reach a model.

    An unrecognised mode is metered conservatively: the agent raises
    ``EmailAgentError`` after dispatch, which the standard failure path refunds —
    an unknown name never buys a free pass around the reserve.
    """
    mode = str(params.get("mode") or "triage").strip()
    return mode not in _EMAIL_AGENT_NO_LLM_MODES


def _outreach_will_call_llm(params: dict[str, Any]) -> bool:  # noqa: ARG001
    """Whether a wave-4C outreach run will make an LLM call — unknowable from the
    params, so conservatively True (the ``_interview_prep_will_call_llm`` ruling,
    applied to the four LLM agents of this family).

    Every agent of this family has honest refusal paths that reach no model, but
    every one of them depends on DB STATE (is there an eligible contact? does it
    have an email address? is there a thread? does the caller have a résumé?),
    never on the params. Deciding it here would mean re-running each agent's own
    resolution queries inside the metering predicate — a second source of truth
    that could drift from what the agent actually does, plus extra queries on
    every run.

    So the atomic reserve-BEFORE-the-LLM-call rail is kept for EVERY call, and the
    honest ``llm_called=False`` these agents report AFTERWARDS is what triggers the
    refund backstop in :func:`_execute_reserved_run`. Registering these backends is
    therefore about the BACKSTOP, never about skipping a reserve: a metered call
    can still never reach a model unreserved.
    """
    return True


#: Metered backends eligible for the no-LLM-call accounting above: backend ->
#: predicate over the run params, True when this call will really reach the LLM.
#: A backend listed here is ALSO covered by ``_execute_reserved_run``'s
#: post-execution refund backstop, which is the only mechanism available when
#: whether a model is reached depends on DB state rather than on params.
#:
#: ``_record_run``'s metering is otherwise per-BACKEND, which is correct for every
#: agent whose whole purpose is an LLM call. companyResearch is different: its
#: DEFAULT call (no params) is a purely deterministic aggregation that makes no
#: LLM call and costs $0, yet membership in ``_LLM_TIER_BY_BACKEND`` alone made it
#: reserve a run from the user's paid plan allowance anyway (wave-4A review,
#: reproduced live: two narrative-off calls moved runsUsed 1 -> 2). Charging a
#: paid run for work that never touched a model is not honest metering, so a call
#: the predicate says makes no LLM call is treated as UNMETERED — no reserve, no
#: spend, end-state ``runsUsed`` unchanged.
#:
#: interviewPrep (ML-W4B) has the same class of path — a run with nothing to prep
#: for never reaches a model — but cannot detect it from params, so its predicate
#: is unconditionally True and only the post-execution backstop applies (see
#: :func:`_interview_prep_will_call_llm`). Measured pre-fix: a nothing-to-prep-for
#: run moved runsUsed 0 -> 1 at $0 cost.
#:
#: emailAgent (ML-W4C, authorized by the wave-4C ruling — deliberately deferred
#: by 4a9cd6c as another wave's agent) has BOTH shapes at once: two modes are
#: params-decidable free paths and its triage no-op is DB-state-dependent, so it
#: gets a mode-aware predicate plus the same backstop. Measured pre-fix: a
#: ``mode=send`` run moved ``runsUsed`` 0 -> 1 AND recorded a non-zero ``costUsd``
#: priced off request payload size for a run that called no model.
#:
#: Deliberately scoped to the backends listed here: tailor / coverLetter /
#: storyExtractor keep their existing per-backend metering exactly as-is, so this
#: closes the reported defects without silently re-pricing any other agent. The
#: atomic reserve-BEFORE-LLM-call rail is untouched for every call that DOES
#: reach the model.
_OPTIONAL_LLM_BY_BACKEND: dict[str, Callable[[dict[str, Any]], bool]] = {
    "companyResearch": _company_research_wants_narrative,
    "interviewPrep": _interview_prep_will_call_llm,
    "emailAgent": _email_agent_will_call_llm,
    # wave-4C: honest refusals (no eligible contact/thread, no email address, no
    # résumé) reach no model and must not cost a paid run.
    "recruiterOutreach": _outreach_will_call_llm,
    "reference": _outreach_will_call_llm,
    "sentimentAnalysis": _outreach_will_call_llm,
    "scheduling": _outreach_will_call_llm,
}


def _call_is_metered(agent_name: str, params: dict[str, Any]) -> bool:
    """Whether THIS call consumes plan quota (reserve + spend).

    True for every backend in :data:`_LLM_TIER_BY_BACKEND`, EXCEPT a backend in
    :data:`_OPTIONAL_LLM_BY_BACKEND` whose predicate says this particular call
    makes no LLM call. Shared by the sync path (``_record_run``), the async
    reserve-at-enqueue seam (``_enqueue_single_agent``) and the worker
    (``workers.tasks._run_single_agent_body``) so all three always agree.
    """
    if agent_name not in _LLM_TIER_BY_BACKEND:
        return False
    predicate = _OPTIONAL_LLM_BY_BACKEND.get(agent_name)
    return True if predicate is None else predicate(params)


#: ROLE backends (ML-U1X-b): backends whose model is a user-assignable ROLE
#: rather than a metered per-call tier. ``supervisor`` (the Orchestrator card)
#: is the first: its sequencing is deterministic code, so it is deliberately
#: ABSENT from ``_LLM_TIER_BY_BACKEND`` — no quota is reserved and no spend is
#: recorded for it (``_call_is_metered`` stays False) — but the operator/user
#: does assign it a model, defaulting to the Anthropic catalog's flagship.
#: Mapped to that default here, so the catalog reports the role's REAL assigned
#: model instead of the "deterministic" sentinel a picker cannot bind to.
_ROLE_MODEL_BACKENDS: dict[str, str] = {
    "supervisor": _flagship_static_model_id("anthropic"),
}


def _model_for_agent(agent_name: str, override: "str | None" = None) -> str | None:
    """The model this backend agent ACTUALLY runs on, or None for deterministic
    agents that make no LLM calls. Costing against the model that really served
    the run keeps spend/ROI (and the USD spend cap) genuine — so when the user
    chose a model (``override``) it MUST be reflected for the same generation
    tiers ``get_model`` honours it on (STRUCTURED stays on the env default)."""
    if agent_name in _ROLE_MODEL_BACKENDS:
        # A role's assignment IS the answer — the user's pick when they made
        # one, else the role's default. Never an env generation tier: the role
        # is assigned explicitly, not inherited from a tier it never calls.
        return (override or "").strip() or _ROLE_MODEL_BACKENDS[agent_name] or None
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
    if agent_name is None:
        return False
    # ML-U1X-b: a ROLE backend's assignment IS read back (through the same
    # ``_user_model_override`` resolver as every other role), so its picker is
    # genuinely functional even though the role reserves no quota.
    if agent_name in _ROLE_MODEL_BACKENDS:
        return True
    if agent_name in _DETERMINISTIC_BACKENDS:
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
#: INTERIM (SEV-1 2026-08-14) — superseded by ML-STOPALL-001 at
#: ``_execute_reserved_run``. Backend agent name -> EVERY UI card key that
#: dispatches it: ``_UI_KEY_FOR_BACKEND`` keeps only the last card per backend,
#: but ``fitScorer`` is dispatched by THREE cards (atsOptimization,
#: matchScoring, skillGap), and the Stop-All guard needs the full set — a
#: backend is paused only when every card that can dispatch it is disabled, so
#: a partial stop never blocks a card the user deliberately left running.
_ALL_UI_KEYS_FOR_BACKEND: dict[str, tuple[str, ...]] = {}
for _catalog_entry in AGENT_CATALOG:
    if _catalog_entry.get("backend"):
        _ALL_UI_KEYS_FOR_BACKEND[_catalog_entry["backend"]] = (
            _ALL_UI_KEYS_FOR_BACKEND.get(_catalog_entry["backend"], ())
            + (_catalog_entry["key"],)
        )


def _agent_paused_by_user(user_id: str, backend_name: str) -> bool:
    """INTERIM — superseded by ML-STOPALL-001 at ``_execute_reserved_run``.

    Whether the user has stopped every UI agent card that dispatches
    ``backend_name``. SEV-1 2026-08-14: "Stop All Agents" wrote
    ``AgentConfig.enabled = false`` for all 22 cards at 12:31Z, but no dispatch
    path read the flag — the board sweep kept dispatching (and spending) for
    nine hours after the user's stop.

    Semantics agreed with the permanent ML-STOPALL-001 enforcement so behaviour
    does not flip when it lands: an absent row means enabled; a backend shared
    by several cards is paused only when EVERY card is disabled; a read error
    fails open (mirrors ``_user_model_override`` — a preference lookup can
    never break a run; the permanent guard at the reserve point owns the
    closed-world check).
    """
    ui_keys = _ALL_UI_KEYS_FOR_BACKEND.get(backend_name)
    if not ui_keys:
        return False
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "agentKey", "enabled" FROM "AgentConfig" '
                    'WHERE "userId" = %s AND "agentKey" = ANY(%s)',
                    (user_id, list(ui_keys)),
                )
                rows = cur.fetchall()
    except Exception:  # noqa: BLE001 — best-effort, mirrors _user_model_override
        return False
    disabled = {key for key, enabled in rows if enabled is False}
    return all(key in disabled for key in ui_keys)
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


def _agent_enabled_for_dispatch(user_id: str, agent_name: str) -> bool:
    """Whether ``user_id`` has NOT paused ``agent_name`` (ML-STOPALL-001).

    2026-08-14 rebind: this used to resolve ``agent_name`` through the
    single-key ``_UI_KEY_FOR_BACKEND`` mapping, which keeps only the LAST UI
    card per backend. ``fitScorer`` is dispatched by THREE cards
    (atsOptimization, matchScoring, skillGap;
    ``_UI_KEY_FOR_BACKEND["fitScorer"] == "skillGap"``), so a user who
    disabled only ``skillGap`` while leaving atsOptimization/matchScoring
    running was wrongly refused HERE (inside ``_execute_reserved_run``, the
    async worker's direct entry point) even though ``_dispatch``'s pre-check
    — which already used the correct every-card rule — agreed the run should
    proceed. Delegating to :func:`_agent_paused_by_user` (the interim guard's
    helper, using ``_ALL_UI_KEYS_FOR_BACKEND``) makes both layers share the
    ONE rule: a backend is paused only when EVERY UI card that can dispatch
    it is disabled.

    Absent-row and read-fault semantics are unchanged by this rebind:
    ``_agent_paused_by_user`` also treats a backend with no matching disabled
    row as "not paused" (``all(key in disabled for key in ui_keys)`` is
    vacuously true only when every key IS disabled; an empty ``disabled`` set
    — no rows, or rows that are all ``enabled`` — leaves it False) and a DB
    read fault as "not paused" (``except Exception: return False``) —
    ``not False`` is ``True`` here, the exact same fail-open default this
    function already returned on a read fault. The two helpers were already
    in agreement on both edge cases; no reconciliation was needed.
    """
    _ensure_agent_config_schema()
    return not _agent_paused_by_user(user_id, agent_name)


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
    # Deterministic agents make no LLM call — nothing to override. ROLE
    # backends (ML-U1X-b, ``_ROLE_MODEL_BACKENDS``) are the exception: they are
    # not metered tiers, but their assignment IS a real, readable choice.
    is_role = agent_name in _ROLE_MODEL_BACKENDS
    if not is_role and agent_name not in _LLM_TIER_BY_BACKEND:
        return None
    ui_key = _UI_KEY_FOR_BACKEND.get(agent_name, agent_name)
    # For a ROLE the stored value is ALWAYS the answer: a role has exactly one
    # model (the picker writes it, the role default is what the card shows when
    # unset), so a stored value equal to the default is still that role's real
    # assignment — not the phantom seed the tier agents have to filter out.
    default_model = "" if is_role else _RECOMMENDED_FOR_BACKEND.get(agent_name, "")
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
                    # MODEL-SUB-QUOTA: a pin written BEFORE the save-time
                    # normalization may still hold OpenRouter's
                    # ``anthropic/claude-…`` spelling. Read it through the SAME
                    # normalizer the routing seam uses, so a legacy row can
                    # never be the one path that still bills OpenRouter for a
                    # Claude model. Same model — only the namespace is dropped.
                    chosen = normalize_model_id(row[0])
                    if chosen != default_model:  # a real per-agent change
                        return chosen
                if is_role:
                    # A ROLE never inherits the provider card's default model:
                    # its unset state is the role's OWN default (rendered by the
                    # catalog), not whatever was last saved on another card.
                    return None
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
                    return normalize_model_id(row[0])
    except Exception:  # noqa: BLE001 — preference read is best-effort, never fatal
        return None
    return None


def _user_search_defaults(user_id: str) -> tuple[str, str]:
    """The user's OWN configured job-search targets, or ``""`` for each unset.

    Reads the profile ``targetRole``/``location`` columns — the same two fields
    Settings > Profile writes and the topbar chip renders. It substitutes
    NOTHING (F-02): an empty string means "this user has not told us", and
    :func:`_resolve_scout_target` turns that into an honest refusal rather than
    somebody else's search.

    The returned ``query`` may still be a single narrow title (whatever the
    user typed into their profile) — ``_agent_callable`` runs it through
    ``query_builder.build_scout_query`` afterwards to broaden it to the
    user's whole target-role family (GAP-SRC-001).
    """
    query, location = "", ""
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


#: Profile columns a discovery run is derived from -> how to name them to a
#: human in the refusal below.
_SEARCH_TARGET_LABELS = {"targetRole": "target role", "location": "location"}


def _missing_search_target_422(missing: list[str]) -> HTTPException:
    """The honest refusal for a discovery run with nothing to search for (F-02).

    Mirrors the frontend prompt (``discovery-target-prompt``): name the profile
    field that is missing and where to fix it, rather than substituting a
    persona the customer never chose. Refusing is the whole point — a
    fabricated search writes unfiltered postings to the user's own board and
    then calls them theirs.

    ``detail`` is a plain STRING on purpose, not the structured object the
    plan-quota 429 uses. The Agents console renders a backend 422 through
    ``agents-feedback.runErrorNotice``, whose ``extractApiJsonDetail`` surfaces
    only a string detail; an object falls through to that branch's hardcoded
    "run Scout to discover jobs" copy, which for THIS refusal is both wrong and
    misdirecting (running Scout is refused for the same reason). A structured
    detail is only worth introducing together with the frontend change that
    reads it.
    """
    human = " and ".join(f"no {_SEARCH_TARGET_LABELS[field]}" for field in missing)
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        f"Your profile has {human}, so there is nothing to search for. "
        f"Add {'them' if len(missing) > 1 else 'it'} in Settings > Profile, or "
        "supply an explicit query and location with the run.",
    )


def _resolve_scout_target(user_id: str, params: dict[str, Any]) -> tuple[str, str]:
    """What this discovery run searches for, and where — or an honest refusal.

    Precedence, and the ONE place it is decided for every caller (both HTTP
    routes, the async worker, ``_pipeline_core``):

    1. An EXPLICIT caller-supplied value wins. The Jobs screen, Settings' Sync
       All and ``scripts/discovery_cron.sh`` all send one, so none of them is
       affected by this resolution at all.
    2. Otherwise the user's OWN profile (:func:`_user_search_defaults`) — this
       is the path a caller that supplies nothing (the Agents console's "Run
       All", which posts ``{}``) now reaches. It was unreachable before F-02:
       the request models materialised hardcoded defaults, so
       ``params.get("query")`` was always truthy.
    3. Otherwise NOTHING — which is a 422, never a substitution.

    The returned query is the caller's/profile's own wording, unbroadened;
    ``_agent_callable`` applies ``build_scout_query`` exactly once.
    """
    query = str(params.get("query") or "").strip()
    location = str(params.get("location") or "").strip()
    if not query or not location:
        profile_query, profile_location = _user_search_defaults(user_id)
        query = query or profile_query
        location = location or profile_location
    missing = [
        field
        for field, value in (("targetRole", query), ("location", location))
        if not value
    ]
    if missing:
        raise _missing_search_target_422(missing)
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
        # F-02: the caller's own explicit target, else THIS user's profile,
        # else an honest 422 — resolved here, before ``_record_run``, so a
        # refused run reserves no quota and leaves no audit row.
        raw_query, location = _resolve_scout_target(user_id, params)
        # Broaden whatever query arrived (an explicit caller-supplied query,
        # the discovery cron's, or the profile-derived one above) into the
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
        # U-AX: the resolved rigor tier's knobs (iteration ceiling + ATS
        # target). ``{}`` keeps the agent's shipped defaults verbatim.
        knobs = _policy_knobs(params)
        return "tailor", (
            lambda: TailoringAgent().run(
                user_id, job_id, params.get("resume_id"), policy_knobs=knobs
            )
        )
    if name in ("coverLetter", "cover-letter"):
        from app.agents.cover_letter_agent import CoverLetterAgent

        job_id = _require_job_id(params)
        knobs = _policy_knobs(params)
        return "coverLetter", (
            lambda: CoverLetterAgent().run(user_id, job_id, policy_knobs=knobs)
        )
    if name in ("storyExtractor", "story-extractor"):
        from app.agents.story_extractor import StoryExtractorAgent

        # B1c (ORCH-B1-BLUEPRINT-2026-08-14.md §4.3): storyExtractor was the
        # one metered T2 content producer receiving no knobs at all — since
        # ``_dispatch`` stamps the resolved policy onto the run regardless,
        # every prior run recorded a ``policyTier`` it never obeyed. Matches
        # tailor/coverLetter's shape exactly; ``{}`` degrades to today's
        # shipped defaults.
        knobs = _policy_knobs(params)
        return "storyExtractor", (
            lambda: StoryExtractorAgent().run(user_id, policy_knobs=knobs)
        )
    if name in ("matcher", "job-matching", "jobMatching"):
        from app.agents.matcher_agent import MatcherAgent

        return "matcher", (lambda: MatcherAgent().run(user_id))
    if name in ("emailAgent", "email-agent", "email"):
        from app.agents.email_agent import EmailAgent

        return "emailAgent", (lambda: EmailAgent().run(user_id, **params))
    # --- wave-4A report agents (ADR-AG-1) ---------------------------------
    # All four deterministic ones take no required params, so the Agents-screen
    # Run button works with the FE's default empty body and needs no
    # RUN_PARAMS/AGENT_ROUTE entry (``AGENT_ROUTE[backend] ?? backend``).
    if name in ("compliance", "compliance-agent"):
        from app.agents.compliance_agent import ComplianceAgent

        return "compliance", (lambda: ComplianceAgent().run(user_id))
    if name in ("salaryIntelligence", "salary-intelligence"):
        from app.agents.salary_intelligence_agent import SalaryIntelligenceAgent

        return "salaryIntelligence", (lambda: SalaryIntelligenceAgent().run(user_id))
    if name in ("marketTrends", "market-trends"):
        from app.agents.market_trends_agent import MarketTrendsAgent

        return "marketTrends", (lambda: MarketTrendsAgent().run(user_id))
    if name in ("learningFeedback", "learning-feedback"):
        from app.agents.learning_feedback_agent import LearningFeedbackAgent

        return "learningFeedback", (lambda: LearningFeedbackAgent().run(user_id))
    if name in ("companyResearch", "company-research"):
        from app.agents.company_research_agent import CompanyResearchAgent

        # ``company`` is optional: with none supplied the agent picks the company
        # the user has the most postings for (and reports which). ``narrative``
        # is opt-in — the default run makes no LLM call at all. The flag is read
        # through the SAME helper the metering decision uses, so "will this call
        # the LLM?" has exactly one answer on both sides.
        company = params.get("company")
        narrative = _company_research_wants_narrative(params)
        return "companyResearch", (
            lambda: CompanyResearchAgent().run(
                user_id,
                company=str(company) if company else None,
                narrative=narrative,
            )
        )
    # --- wave-4B (ADR-AG-1) -----------------------------------------------
    if name in ("interviewPrep", "interview-prep"):
        from app.agents.interview_prep_agent import InterviewPrepAgent

        # ``job_id`` is OPTIONAL so the Agents-screen Run button works with the
        # FE's default empty body (no RUN_PARAMS/AGENT_ROUTE entry needed): with
        # none supplied the agent preps for the job of the caller's most recent
        # interview-stage application and REPORTS that choice back in
        # ``jobSelection`` (the wave-4A ``companyResearch`` convention). An
        # EXPLICIT id that is not the caller's own still raises LookupError ->
        # honest 404, never a substituted job.
        job_id = params.get("job_id")
        return "interviewPrep", (
            lambda: InterviewPrepAgent().run(
                user_id, job_id=str(job_id) if job_id else None
            )
        )
    # --- wave-4C outreach family (ADR-AG-1) --------------------------------
    # Every param is OPTIONAL so the Agents-screen Run button works with the FE's
    # default empty body (no AGENT_ROUTE/RUN_PARAMS entry needed): each agent
    # resolves its own subject from the caller's own data and REPORTS that choice
    # back (the wave-4A/4B convention). An EXPLICIT id that is not the caller's
    # own raises LookupError -> honest 404, never a substituted row.
    if name in ("recruiterOutreach", "recruiter-outreach"):
        from app.agents.recruiter_outreach_agent import RecruiterOutreachAgent

        contact_id = params.get("contact_id")
        return "recruiterOutreach", (
            lambda: RecruiterOutreachAgent().run(
                user_id, contact_id=str(contact_id) if contact_id else None
            )
        )
    if name in ("reference", "reference-agent"):
        from app.agents.reference_agent import ReferenceAgent

        contact_id = params.get("contact_id")
        return "reference", (
            lambda: ReferenceAgent().run(
                user_id, contact_id=str(contact_id) if contact_id else None
            )
        )
    if name in ("sentimentAnalysis", "sentiment-analysis"):
        from app.agents.sentiment_analysis_agent import SentimentAnalysisAgent

        thread_id = params.get("thread_id")
        return "sentimentAnalysis", (
            lambda: SentimentAnalysisAgent().run(
                user_id, thread_id=str(thread_id) if thread_id else None
            )
        )
    if name in ("scheduling", "scheduling-agent"):
        from app.agents.scheduling_agent import SchedulingAgent

        thread_id = params.get("thread_id")
        # ``proposed_times`` are the CALLER'S OWN availability windows and always
        # take precedence. Since W-CAL (ADR-CALENDAR-V4) they are no longer the
        # ONLY source of a concrete time: with Google Calendar connected the
        # agent falls back to windows read from real free/busy. With neither, it
        # still proposes nothing of its own.
        proposed = params.get("proposed_times")
        return "scheduling", (
            lambda: SchedulingAgent().run(
                user_id,
                thread_id=str(thread_id) if thread_id else None,
                proposed_times=list(proposed) if isinstance(proposed, list) else None,
            )
        )
    if name in ("notification", "notification-agent"):
        from app.agents.notification_agent import NotificationAgent

        # Takes NO params: the digest window is derived from the last digest the
        # user actually sent, never from caller input.
        return "notification", (lambda: NotificationAgent().run(user_id))
    # GM2-AGENTS-001: real submission gate + write (app.routers.jobs
    # submit_application_for_job, verbatim — never a second, looser gate).
    # ``job_id`` is OPTIONAL so the Agents-screen Run button works with the
    # FE's default empty body (no RUN_PARAMS/AGENT_ROUTE entry needed): with
    # none supplied the agent picks the caller's own most recent already-ready
    # application and REPORTS that choice back (the wave-4A/4B/4C
    # convention). An EXPLICIT id that is not the caller's own raises
    # LookupError -> honest 404, never a substituted job.
    if name in ("submission", "submission-agent"):
        from app.agents.submission_agent import SubmissionAgent

        job_id = params.get("job_id")
        return "submission", (
            lambda: SubmissionAgent().run(
                user_id, job_id=str(job_id) if job_id else None
            )
        )
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown agent '{name}'")


#: Backends the Agents-screen card exposes a working Run button for — i.e. every
#: name ``_agent_callable`` above resolves. Kept adjacent to that mapping (and
#: read by ``GET /agents/catalog``'s ``runnable`` flag) so a newly wired agent
#: cannot be dispatchable while its card still renders as un-runnable, or vice
#: versa.
_RUNNABLE_BACKENDS = frozenset(
    {
        "scout", "fitScorer", "matcher", "tailor", "coverLetter",
        "storyExtractor", "emailAgent",
        "compliance", "salaryIntelligence", "marketTrends", "companyResearch",
        "learningFeedback",
        "interviewPrep",
        "recruiterOutreach", "reference", "sentimentAnalysis", "scheduling",
        "notification",
        "submission",
    }
)


#: Alternate/legacy spellings ``_agent_callable`` accepts for a canonical
#: backend name (B1b, ORCH-B1-BLUEPRINT-2026-08-14.md §4.2). The directive
#: seam needs the CANONICAL agent key BEFORE ``_agent_callable`` runs —
#: ``_dispatch`` resolves the policy first so tailor/coverLetter's knobs are
#: computed from the ALREADY-amended policy (the U-AX ordering this module
#: has always relied on), so canonicalizing name->key cannot itself call
#: ``_agent_callable``. This is a plain lookup table, kept in sync BY HAND
#: with the ``if name in (...)`` aliases below it — an unrecognized alias
#: falls through to ``name`` unchanged, which simply resolves zero directives
#: (the same honest degrade an unset ``agent_key`` already produces), never a
#: wrong dispatch: ``_agent_callable`` remains the sole source of truth for
#: WHICH agent actually runs.
_AGENT_ALIASES: dict[str, str] = {
    "fit-scorer": "fitScorer",
    "cover-letter": "coverLetter",
    "story-extractor": "storyExtractor",
    "job-matching": "matcher",
    "jobMatching": "matcher",
    "email-agent": "emailAgent",
    "email": "emailAgent",
    "compliance-agent": "compliance",
    "salary-intelligence": "salaryIntelligence",
    "market-trends": "marketTrends",
    "learning-feedback": "learningFeedback",
    "company-research": "companyResearch",
    "interview-prep": "interviewPrep",
    "recruiter-outreach": "recruiterOutreach",
    "reference-agent": "reference",
    "sentiment-analysis": "sentimentAnalysis",
    "scheduling-agent": "scheduling",
    "notification-agent": "notification",
    "submission-agent": "submission",
}


def _canonical_agent_key(name: str) -> str:
    """Best-effort canonical backend key for a possibly-aliased ``name`` —
    used ONLY to resolve which agent's directives apply, never for dispatch."""
    return _AGENT_ALIASES.get(name, name)


def _with_quality_policy(
    user_id: str, params: dict[str, Any], *, agent_key: str | None = None
) -> dict[str, Any]:
    """The SINGLE rigor-policy enforcement seam (U-AX build spec items 2-3).

    Resolves this user's deterministic rigor tier once and merges it into the
    run's own params as ``qualityPolicy``. Placing it here — upstream of
    ``_agent_callable`` (which reads ``qualityPolicy.knobs`` to configure the
    tailor loop / cover-letter retries) and upstream of
    ``AgentRunRepository.start`` (which persists ``policyTier`` +
    ``metricSnapshot`` off the same dict) — is what guarantees the tier the
    agent OBEYED and the tier the run card DISPLAYS are the same object, not
    two independent computations that could disagree.

    Idempotent: an already-stamped params dict (async worker replaying a stored
    payload, or ``_dispatch`` handing off to ``_record_run``) is returned
    unchanged, so the policy is resolved exactly once per run.

    Never raises: a policy-resolution failure must not take down an agent run.
    ``resolve_policy_for_user`` already fails closed to an honest
    ``insufficient_data`` verdict with a stated reason; this guard covers the
    residual (import/programming) case by leaving params untouched, which
    persists NULL columns — "no policy recorded" — rather than a fabricated
    tier.

    B1b (ORCH-B1-BLUEPRINT-2026-08-14.md §4.2): after resolving the baseline
    policy, any ACTIVE ``AgentDirective`` for ``agent_key`` amends it via
    ``app.services.agent_directives.effective_policy`` — inside the SAME
    try/except, so a directive-store failure degrades to the baseline policy
    exactly as a policy-resolution failure does. ``agent_key=None`` resolves
    NO directives (never "all of them") — the honest degrade for a caller
    that cannot yet name the agent.
    """
    if isinstance(params.get("qualityPolicy"), dict):
        return params
    try:
        from app.services.quality_policy import resolve_policy_for_user

        policy = resolve_policy_for_user(user_id)
    except Exception:  # noqa: BLE001
        logger.warning("rigor policy unresolved for user %s", user_id, exc_info=True)
        return params
    if agent_key and agent_directives_enabled():
        try:
            from app.repositories.agent_directive import AgentDirectiveRepository
            from app.services.agent_directives import effective_policy

            directives = AgentDirectiveRepository().list_active(user_id, agent_key)
            policy = effective_policy(policy, directives)
        except Exception:  # noqa: BLE001
            logger.warning(
                "directive resolution failed for user %s agent %s — running on "
                "the baseline policy",
                user_id, agent_key, exc_info=True,
            )
    return {**params, "qualityPolicy": policy}


def _policy_knobs(params: dict[str, Any]) -> dict[str, Any]:
    """The pipeline knobs for this run, or ``{}`` when no policy was resolved.

    ``{}`` means "use the callee's shipped defaults" — the exact behaviour that
    shipped before U-AX, so an unresolved policy degrades to today's product
    rather than to a weaker one.
    """
    policy = params.get("qualityPolicy")
    if not isinstance(policy, dict):
        return {}
    knobs = policy.get("knobs")
    return knobs if isinstance(knobs, dict) else {}


def _dispatch(
    user_id: str, name: str, params: dict[str, Any], *, system_run: bool = False,
    skip_quota: bool = False, parent_run_id: str | None = None,
) -> dict[str, Any]:
    """Resolve the agent callable (pure) then execute + audit it. ``system_run``
    (ADR-P7-05) is threaded to ``_record_run`` -> ``_require_active_subscription``,
    which honors the paywall exemption ONLY for ``_SYSTEM_RUN_EXEMPT_AGENTS``
    (scout, fitScorer). Every other agent name ignores it (defense in depth).

    ``skip_quota`` is threaded to ``_record_run`` so automated system operations
    (e.g. the board sweep) bypass the user's paid plan-quota reserve/spend-cap
    gates while still keeping the cooldown block and an honest audit trail.

    ``parent_run_id`` (B6) is threaded to ``_record_run`` -> ``AgentRunRepository
    .start`` unchanged: this function makes no causal claim of its own, it only
    carries the caller's (``_pipeline_core``'s)."""
    # ML-STOPALL-001 defense-in-depth: pre-side-effect early refusal for a
    # user-stopped agent — no ``AgentRun`` row, no quota reserve, nothing to
    # refund. The COMPLETE guard (covering the async worker's direct
    # ``_execute_reserved_run`` path, with an honest recorded run row) lives in
    # ``_execute_reserved_run``; both layers share one semantic via the
    # every-card key rule. The board sweep's per-job ``except HTTPException``
    # records the refusal and moves on; API callers get the coded 409.
    if _agent_paused_by_user(user_id, name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"agent_paused: {name} is stopped by the user's agent controls "
            "(Stop All / per-agent toggle). Re-enable the agent on the Agents "
            "page to run it.",
        )
    # U-AX: resolve the rigor tier BEFORE binding the callable, so the agent
    # receives the knobs and the AgentRun row records the very same policy.
    # B1b: the CANONICAL agent key is needed for directive resolution here —
    # ``name`` may be an alias (e.g. "cover-letter"), and canonicalizing it
    # cannot itself call ``_agent_callable`` (that would compute tailor/
    # coverLetter's knobs from the policy BEFORE directives amend it, exactly
    # the ordering bug this seam exists to prevent) — see ``_canonical_agent_key``.
    params = _with_quality_policy(
        user_id, params, agent_key=_canonical_agent_key(name)
    )
    canonical, fn = _agent_callable(user_id, name, params)
    return _record_run(
        user_id, canonical, params, fn,
        system_run=system_run, skip_quota=skip_quota, parent_run_id=parent_run_id,
    )


def _guard_rejection_http_error(
    subject: str, exc: "FabricationError | StructuralError"
) -> HTTPException:
    """The ONE honest HTTP translation of a generation-guard rejection, shared by
    every route that dispatches an agent (F-1, PROD-VERIFY-5A).

    A ``FabricationError``/``StructuralError`` escaping :func:`_dispatch` is a
    NORMAL product outcome — the guard WORKING, i.e. Aether refusing to ship
    ungrounded or non-compliant text after every corrective retry — never a
    server fault. ``_record_run``'s guard-rejection handler has ALREADY recorded
    the honest ``completed`` degrade and refunded the reserved run by the time
    the exception reaches a route, so this is purely the HTTP translation.

    Only ``run_cover_letter`` translated it before, so the generic
    ``POST /agents/{name}/run`` returned a bare ``Internal Server Error`` plus a
    full ASGI traceback for a correct refusal (reproduced live:
    ``FabricationError: Fabricated entities detected: ['prm']``) — and every
    occurrence wrote a traceback that masks real incidents in the log.

    The ``fabrication guard: [...]`` and ``format contract not met: [...]``
    anchors are a CONTRACT with the frontend's rejection parser
    (apps/web/src/components/cover-letters/rejection.ts), which reads the guard's
    flagged items straight out of ``detail`` to render the honest rejection panel
    instead of a generic error banner. They are preserved verbatim in both
    messages; only the ``subject`` varies, so a caller of the generic route
    learns WHICH agent refused.

    ``PlaceholderSignerError`` (BLOCKER-002) is a ``StructuralError`` subclass
    (so it reaches this function on the same catch-all path) but is a
    DIFFERENT guard category — a placeholder/test-probe identity, not a
    §10.2 format violation — so it gets its own explicit, actionable
    message rather than the misleading "format contract not met" wording.
    It intentionally does not match either frontend regex above; an
    unmatched 422 falls back to the generic error banner there, which still
    surfaces this ``detail`` text to the user.
    """
    if isinstance(exc, FabricationError):
        detail = f"{subject} rejected by fabrication guard: {exc.flagged}"
    elif isinstance(exc, PlaceholderSignerError):
        detail = f"{subject} rejected: {exc.issues[0]}"
    else:
        detail = f"{subject} rejected — §10.2 format contract not met: {exc.issues}"
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


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


#: B1b reversibility (ORCH-B1-BLUEPRINT-2026-08-14.md §9.1, ADR-AGI-2's
#: "Reversibility" clause): the global directive-issuance/application kill
#: switch. Code default OFF, same convention as ``_ASYNC_OFF`` above.
_DIRECTIVES_OFF = frozenset({"false", "0", "no", "off", ""})


def agent_directives_enabled() -> bool:
    """Whether B1b directives currently AMEND agent policy.

    Code default OFF; a deployer flips ``AETHER_AGI_DIRECTIVES_ENABLED=true``
    in ``.env`` to turn amendment on. When OFF, ``_with_quality_policy`` never
    calls ``effective_policy`` — every run gets the baseline tier policy
    unchanged — but this does NOT stop the Supervisor's rules stage from
    evaluating and recording directives (``POST /agents/directives/evaluate``
    still writes history): ADR-AGI-2's reversibility clause pauses
    APPLICATION ("agents then run on charter defaults"); history stays
    readable and displayed the whole time, which is what lets a deployer
    re-enable amendment later without having lost the audit trail. Read via
    ``os.environ`` on every call so a hot env change takes effect immediately.
    """
    return os.environ.get(
        "AETHER_AGI_DIRECTIVES_ENABLED", "false"
    ).strip().lower() not in _DIRECTIVES_OFF


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
    user_id: str,
    agent_key: str,
    params: dict[str, Any],
    *,
    system_run: bool = False,
    singleton: bool = False,
) -> str:
    """Enqueue a metered single-agent run (tailor / coverLetter), blueprint §3.2.

    Ordering is identical to the sync ``_record_run`` pre-execution steps —
    paywall FIRST, then cooldown, then ATOMIC reserve-at-enqueue — before the
    AgentRun + BackgroundJob rows and the queue push. On a queue failure the
    reservation is refunded, the job marked failed, and an honest 503 raised
    (never a silent success, never a silent sync fallthrough).

    ``system_run`` (ADR-P7-05) is honored for the paywall check exactly as the
    sync path — but ONLY for ``_SYSTEM_RUN_EXEMPT_AGENTS``, so a metered agent
    with a valid secret still hits the paywall (402).

    ``scout`` reaches this seam too since MON-020 (``/scout/run?background=true``).
    It is not in :data:`_LLM_TIER_BY_BACKEND`, so ``_call_is_metered`` returns
    False for it and no quota is reserved or refunded — identical to what the
    synchronous ``_record_run`` path already does for scout. Nothing about the
    metering, paywall or cooldown decision changes with the transport.

    ``singleton`` (MON-020 round-2) makes the enqueue IDEMPOTENT for agents of
    which one run per user is the whole unit of work: if a run is already in
    flight, its job id comes back and nothing new is created or queued. It is a
    SERVER-side guard on purpose — the browser's ``disabled`` flag is per
    component, so it cannot cover a second tab, the three separate buttons that
    reach this endpoint, or a direct POST. Deliberately 202-with-the-existing-id
    rather than 409: the caller's intent ("make sure discovery is running") is
    already satisfied, and the frontend polls the returned id either way."""
    # INTERIM — superseded by ML-STOPALL-001 at ``_execute_reserved_run``.
    # Same pre-side-effect refusal as ``_dispatch``: this async seam BYPASSES
    # ``_dispatch`` (the worker body calls ``_execute_reserved_run`` directly),
    # so without this check a user-stopped tailor/coverLetter still enqueued
    # and SPENT (proven live 21:56Z: POST /agents/tailor/run billed $0.048
    # while every AgentConfig row read enabled=false). Refuse before paywall,
    # reserve, rows and queue — nothing to refund, nothing queued.
    if _agent_paused_by_user(user_id, agent_key):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"agent_paused: {agent_key} is stopped by the user's agent controls "
            "(Stop All / per-agent toggle). Re-enable the agent on the Agents "
            "page to run it.",
        )
    # 1) Paywall FIRST (honest 402 before any row/reserve/enqueue) — scoped
    #    system-run exemption applies identically to the sync path.
    _require_active_subscription(user_id, agent_name=agent_key, system_run=system_run)
    # U-AX: stamp the rigor policy onto the params BEFORE they are persisted to
    # both the AgentRun row and the BackgroundJob payload, so the ARQ worker
    # replays the exact policy this enqueue resolved (never a fresh one that
    # could differ by the time the job is picked up). ``agent_key`` here is
    # already canonical (every caller passes a real backend key, and D.524's
    # generic-route caller resolves ``canonical`` via ``_agent_callable``
    # before reaching this function — see ``run_named_agent``).
    params = _with_quality_policy(user_id, params, agent_key=agent_key)
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
            # CRITICAL-3b: same split as the sync gate — a circuit cooldown is
            # an honest 503 raised BEFORE the reserve, so an out-of-credit
            # upstream costs the user nothing; a real quota row keeps its 429.
            _raise_if_llm_circuit_open(provider, block)
            raise _quota_429(provider, block.get("expiresAt"))
    repo = BackgroundJobRepository()
    # 2b) Duplicate-run guard, part one (MON-020): hand back the run that is
    #     already in flight instead of starting a second one. The lookup is
    #     cheap and covers every ordinary double-submit; the same-millisecond
    #     race is closed at the DB in step 4 (``create_singleton``), so this
    #     read is an optimisation and a stale-job RELEASE, never the guarantee.
    #     Applying the same lazy watchdog ``GET /agents/jobs/{id}`` applies is
    #     what keeps a dead worker from locking the user out of syncing: a job
    #     past the staleness window is failed (honestly, with its refund) here
    #     and the new run proceeds.
    if singleton:
        active = repo.find_active(user_id, agent_key)
        if active is not None:
            active = _apply_stale_watchdog(active, repo)
            if active.get("status") in ("enqueued", "processing"):
                return str(active["id"])
    # 3) Atomic reserve AT ENQUEUE (metered calls only — ``_call_is_metered``
    #    keeps this seam in step with the sync path for opt-in-LLM backends).
    #    ADMIN-FULL: the SAME resolver the sync path consults — an unlimited
    #    caller reserves nothing here either, so the two seams can never
    #    disagree about who is exempt.
    metered = _call_is_metered(agent_key, params)
    quota_repo = (
        UsageQuotaRepository()
        if metered and not entitlements.unlimited(user_id)
        else None
    )
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
    if singleton:
        # Duplicate-run guard, part two: the job row is claimed FIRST, because
        # that insert (advisory-locked + backed by the partial unique index) is
        # the atomic claim. Only the winner then writes the AgentRun audit row,
        # so a lost race leaves no orphan "running" run in the user's history.
        job_id, created = repo.create_singleton(
            user_id, agent_key, params=params, quota_reserved=reserved_flag
        )
        if not created:
            # Another request claimed it between step 2b and here. We never ran
            # anything, so anything we reserved goes straight back.
            if reserved_flag and quota_repo is not None:
                quota_repo.refund_run(user_id)
            return job_id
        run = runs.start(user_id, agent_key, params)
        _persist_billing_audit(runs, run["id"], audit)
        repo.set_run_id(job_id, run["id"])
    else:
        run = runs.start(user_id, agent_key, params)
        _persist_billing_audit(runs, run["id"], audit)
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

    ``enqueued`` stale > 15 min, tunable via ``AETHER_JOB_STALE_SECONDS``: how
    long a job may sit unclaimed before we conclude no worker will claim it.

    ``processing`` is a DIFFERENT question — "has the worker died mid-run?" —
    so it is derived from the worker's own per-job execution ceiling
    (:func:`app.workers.queue.job_timeout_seconds`) plus a 120s settling margin,
    and overridable with ``AETHER_JOB_PROCESSING_STALE_SECONDS`` (MON-020).

    It used to be ``enqueued − 180``, which only accidentally sat above the ARQ
    ceiling. Now that background discovery runs share this queue (measured
    255-473s typical, 968s worst case) the two numbers must not drift apart: a
    processing window BELOW the ceiling makes the lazy watchdog mark a run
    "generation timed out (worker unavailable)" — and refund it — while the
    worker is still legitimately executing it, i.e. a fabricated failure on a
    run that then completes. Deriving it from the ceiling makes that
    structurally impossible rather than merely unlikely."""
    from app.workers.queue import job_timeout_seconds

    try:
        enq = int(os.environ.get("AETHER_JOB_STALE_SECONDS", "900"))
    except ValueError:
        enq = 900
    default_proc = job_timeout_seconds() + 120
    try:
        proc = int(
            os.environ.get("AETHER_JOB_PROCESSING_STALE_SECONDS", str(default_proc))
        )
    except ValueError:
        proc = default_proc
    return enq, max(60, proc)


def _job_age_seconds(anchor: Any) -> float:
    """Seconds elapsed since a DB-stamped ``anchor``, CLAMPED at zero.

    ``BackgroundJob.createdAt``/``startedAt`` are stamped by the DATABASE clock
    (``now()``) while this comparison runs on the APP clock. The hosted Postgres
    was measured ~3s AHEAD of the app server
    (``uat/reports/evidence/models-live/clock-skew-sweep-2026-07-29.md``,
    finding #4), so a job polled immediately after enqueue can produce a
    NEGATIVE age.

    Nothing misbehaves today — a negative age is trivially below every
    staleness limit, so the watchdog correctly declines to fire — but a
    negative "age" is a nonsense value to log or reuse, and this is the closest
    structural sibling to the W-6 freshness bug the sweep was opened for.
    Clamping at zero keeps it honest AND keeps the watchdog fail-safe;
    ``abs()`` (the symmetric fix that was right for the 120s email-sync window)
    would be actively wrong here, turning a future-stamped anchor into a large
    age and failing a brand-new job.

    A naive timestamp is read as UTC, exactly as the caller did before.
    """
    from datetime import datetime, timezone

    if getattr(anchor, "tzinfo", None) is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - anchor).total_seconds())


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
    enq_secs, proc_secs = _job_stale_thresholds()
    limit = enq_secs if status_v == "enqueued" else proc_secs
    anchor = job.get("startedAt") if status_v == "processing" else None
    anchor = anchor or job.get("createdAt")
    if anchor is None:
        return job
    if _job_age_seconds(anchor) < limit:
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
    """All known agents with their most recent run (P2-S08).

    The SET is :data:`AGENT_NAMES`, derived from :data:`AGENT_CATALOG` — every
    distinct implemented agent, pipeline nodes first (F-3). It was a hardcoded
    8-tuple, so this list omitted all six wave-4A/4B agents while the catalog
    reported them active: the sidebar Agent Pulse said "8 agents ready" on every
    dashboard screen next to an Agents screen showing 16 active cards, and the
    Orchestration view — which reads ``AgentSummary.status`` from THIS list —
    could not surface the new agents at all.

    ``status`` is transient-tolerant and SEMANTICALLY CONSISTENT with
    ``GET /agents/catalog`` (ML-agents-err-001 OBS-B): both endpoints classify
    agent health through the shared ``_latest_failure_is_hard`` helper over the
    SAME recent-run window (``recent_runs_by_agent``), so the Agents-screen
    catalog cards and the Orchestration view — which reads
    ``AgentSummary.status`` from THIS list — never disagree about whether an
    agent is broken. A genuine/chronic failure is reported as the raw
    ``"failed"`` (hard failure, matching the catalog's "error"); a lone
    transient upstream blip on an otherwise-healthy agent is reported as
    ``"active"`` (matching the catalog's "active"), NOT the raw ``"failed"``.
    ``AgentSummary.status`` is a free-form string and Orchestration.nodeStatus
    renders any non-"idle" status as a healthy (green) node, so "active" (like
    the pre-existing raw "completed"/"queued"/"running") renders correctly;
    only "idle" and "failed" carry special handling, both preserved here.
    """
    recent = AgentRunRepository().recent_runs_by_agent(current_user["id"])
    agents = []
    for name in AGENT_NAMES:
        runs = recent.get(name)
        run = runs[0] if runs else None
        if run is None:
            status_value = "idle"
        elif run["status"] == "failed" and not _latest_failure_is_hard(runs):
            # Tolerated transient/upstream blip — not a hard failure. Report the
            # same health verdict the catalog shows ("active") rather than the
            # raw "failed", so the Orchestration node does not paint red while
            # the catalog card is green for the identical underlying run.
            status_value = "active"
        else:
            status_value = run["status"]
        agents.append(
            {
                "name": name,
                "status": status_value,
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


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str, request: Request, current_user: CurrentUser
) -> StreamingResponse:
    """Server-Sent Events feed of one agent run's REAL persisted state
    (GMV4-sse-001, §14.5.5).

    Authorisation is the SAME model as the ``GET /runs/{run_id}`` poll directly
    above — same ``CurrentUser`` dependency, same owner-scoped
    ``AgentRunRepository.get_by_id(run_id, user_id)`` whose SQL predicate is
    ``"userId" = %s``. A run belonging to anyone else resolves to ``None`` and
    gets the identical honest 404: the non-owner is never told the run exists
    and never receives a single stream frame.

    The polling endpoint is UNCHANGED and remains supported; this is an
    additive transport over the same row, not a replacement.

    What the stream does and does not claim is documented on
    ``app.services.agent_run_stream`` — in particular it does NOT emit the
    six-step submission vocabulary, because four of those six steps have no
    recorded backing in this codebase and a timer-driven sequence of them would
    be a fabricated progress animation.

    CONCURRENCY (GMV4-sse-005, governance §5e). Every open stream re-reads its
    row on its own short-lived database connection, against an app-wide
    25-connection ceiling (``app/db.py:8-9``), so admission is capped per user
    AND globally by ``app.state.sse_stream_slots``. A refused stream gets an
    explicit ``429``/``503`` carrying a real reason — never a hang, never an
    empty 200 dressed up as a live stream. The slot is taken BEFORE the
    ownership lookup so a refused request does no database work at all, and is
    released on every exit path (see below).
    """
    slots: StreamSlots = request.app.state.sse_stream_slots
    try:
        token = slots.acquire(current_user["id"])
    except StreamCapExceeded as exc:
        logger.warning(
            "agent-run stream refused (%s cap %s) user=%s run=%s",
            exc.scope, exc.limit, current_user["id"], run_id,
        )
        # Per-user breach is the caller's own doing (429); a global breach is
        # the server being out of capacity (503). Both carry the real reason.
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS
            if exc.scope == "user"
            else status.HTTP_503_SERVICE_UNAVAILABLE,
            exc.message,
            headers={"Retry-After": "5"},
        ) from None

    repo = AgentRunRepository()
    try:
        run = await run_in_threadpool(repo.get_by_id, run_id, current_user["id"])
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent run not found")
    except BaseException:
        # No StreamingResponse gets built on this path, so no generator
        # ``finally`` can ever run — release here or every 404 (and every
        # failed lookup, and any cancellation) permanently burns a slot.
        slots.release(token)
        raise

    return StreamingResponse(
        # The slot is released when the generator finishes for ANY reason:
        # terminal status, stream_timeout, stream_error, client disconnect, or
        # an exception. ``release`` is idempotent, so the unwind above and this
        # wrapper can never double-free.
        release_slot_when_done(
            iter_agent_run_events(
                run=run,
                run_id=run_id,
                user_id=current_user["id"],
                reload_run=repo.get_by_id,
                is_disconnected=request.is_disconnected,
            ),
            lambda: slots.release(token),
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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
    """Explicit discovery targets — BOTH optional since F-02.

    Omitting one falls back to the caller's OWN profile
    (``_resolve_scout_target``), and a profile with nothing configured is
    refused with a 422 naming the missing field — never completed with a
    hardcoded persona. A value that IS supplied must still be a real one, so
    ``min_length=1`` continues to reject an explicitly empty string."""

    query: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)


def _guard_scout_cooldown(user_id: str, request: Request, system_run: bool) -> None:
    """Per-user manual-Sync cooldown (S-FIX-A / S-7).

    Scout is deterministic and unmetered, so it is exempt from the plan-quota
    and spend-cap machinery entirely — before this, nothing at all slowed a
    user clicking Sync repeatedly, and every uncached run spends from the ONE
    shared Adzuna daily budget (250 calls/day for the whole deployment). The
    limiter lives on ``app.state`` (see ``app.main.create_app``) so each app —
    and each test — owns isolated counters.

    SCHEDULED runs are exempt: the platform's own sweep is already paced, and
    counting it would let the automation lock a user out of their own button.
    The refusal is an honest 429 naming the wait and the automatic fallback —
    never a silent no-op or a fabricated "no new jobs".
    """
    if system_run:
        return
    limiter = getattr(request.app.state, "scout_rate_limiter", None)
    if limiter is None:  # app built without the limiter (older test harness)
        return
    # ADMIN-FULL: this is a PER-USER rate limit, which the binding scope ruling
    # classes as a restriction — so the ONE resolver exempts an admin here just
    # as it does at the checkout/portal limiters. The SHARED protection this
    # cooldown was built to defend is untouched: the deployment-wide Adzuna
    # daily budget is enforced independently inside
    # ``app.services.discovery.adzuna_adapter`` (``_daily_budget`` /
    # ``budget_snapshot``), so an exempt admin still cannot spend past the
    # ceiling — they simply are not throttled on their own clicks. The check
    # short-circuits BEFORE ``allow()`` because that call consumes a token.
    if entitlements.is_admin(user_id):
        return
    if limiter.allow(user_id):
        return
    retry_after = limiter.retry_after(user_id)
    minutes = max(1, round(retry_after / 60))
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "scout_cooldown",
            "message": (
                f"Sync is cooling down — {limiter.max_calls} manual refreshes in "
                f"{int(limiter.window_seconds // 60)} minutes is the cap. "
                f"Try again in about {minutes} minute{'s' if minutes != 1 else ''}; "
                "scheduled discovery keeps running for you in the background."
            ),
            "retryAfterSeconds": retry_after,
            "limit": limiter.max_calls,
            "windowSeconds": int(limiter.window_seconds),
        },
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/scout/run", status_code=status.HTTP_202_ACCEPTED)
def run_scout(
    body: ScoutRunRequest,
    current_user: CurrentUser,
    request: Request,
    background: bool = Query(
        default=False,
        description=(
            "Enqueue the discovery pass onto the background worker and return "
            "a job id to poll at GET /agents/jobs/{job_id}, instead of running "
            "the whole pass inside this request."
        ),
    ),
) -> dict[str, Any]:
    """Kick off a scout discovery run for the authenticated user.

    TWO modes, and the DEFAULT is deliberately the synchronous one:

    * ``background=false`` (default) — the pass runs in-request and the response
      carries its real counts. ``scripts/discovery_cron.sh`` depends on exactly
      this: it POSTs here and then immediately POSTs ``/agents/fit-scorer/run``
      to score whatever landed, so scout MUST have finished first. Flipping the
      default would silently break scheduled discovery for every user. The cron
      calls 127.0.0.1 directly with no proxy in front of it and no client
      timeout, so a multi-minute run is perfectly fine there.

    * ``background=true`` (MON-020) — the pass is enqueued onto the SAME ARQ
      ``run_agent_job`` machinery every other long-running agent already uses,
      and the caller immediately gets ``{"status": "enqueued", "job_id"}`` to
      poll at ``GET /agents/jobs/{job_id}``. This is what the browser uses (the
      Jobs screen's Sync button, Settings' "Sync All Job Boards"): those calls
      cross Cloudflare, which aborts a request at ~100s and answers with its own
      HTML error page, while a real pass measures 255-473s (968s worst case).
      Background mode is IDEMPOTENT per user: a POST while a pass is already
      enqueued/processing returns that pass's ``job_id`` instead of starting a
      second one (a second pass would search the same boards for the same user,
      double the upstream calls and race its own upserts). The guard lives on
      the server because the three buttons that call this — Jobs "Sync Now",
      Settings' "Sync All Job Boards", the Agents console — each only know
      their own component's disabled flag.

    Both modes resolve the search target FIRST (F-02), so the AgentRun audit row
    — and, in background mode, the queued job's params — record the search that
    ACTUALLY runs: the caller's own profile values when the body omitted them,
    never two nulls and never a borrowed persona. Both modes go through the same
    entitlement/cooldown gates; background mode adds no bypass.
    """
    user_id = current_user["id"]
    _guard_scout_cooldown(user_id, request, _is_system_run(request))
    # F-02: resolve BEFORE dispatch (same as ``run_pipeline``) so the AgentRun
    # audit row records the search that ACTUALLY ran — the caller's own profile
    # values when the body omitted them — rather than the two nulls it was sent.
    # ``_agent_callable`` re-resolves from these now-explicit params without a
    # second DB read, and refuses identically if this route is bypassed.
    params = body.model_dump()
    params["query"], params["location"] = _resolve_scout_target(user_id, params)
    system_run = _is_system_run(request)
    if background:
        # A queue outage raises an honest 503 from ``_enqueue_single_agent``.
        # There is deliberately NO fallback to the synchronous path: silently
        # falling back would reintroduce the very 100s proxy timeout this mode
        # exists to escape, and would look to the caller like a slow success.
        #
        # ``singleton=True``: a user gets ONE discovery pass at a time. A second
        # POST while one is running is answered with THAT run's job id — same
        # 202 envelope, no second pass, no second set of upstream board calls.
        job_id = _enqueue_single_agent(
            user_id, "scout", params, system_run=system_run, singleton=True
        )
        return {"status": "enqueued", "job_id": job_id}
    output = _dispatch(
        user_id, "scout", params,
        system_run=system_run,
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


@router.get("/scout/sources/availability")
def scout_source_availability(current_user: CurrentUser) -> list[dict[str, Any]]:
    """Backend-derived per-source availability (ML-audit-seek-fe-hardcode-001).

    ``{"source", "available", "reason"}`` rows computed at call time from the
    adapter registry (env-gated Seek included) — the FE drives its source
    filter options from this instead of hardcoding availability.
    """
    from app.services.discovery.adapter_registry import source_availability

    return source_availability()


@router.post("/fit-scorer/run")
def run_fit_scorer(
    current_user: CurrentUser, request: Request, rescore: bool = False
) -> dict[str, Any]:
    """Score every unscored job for the authenticated user (P2-S04)."""
    output = _dispatch(
        current_user["id"], "fitScorer", {"rescore": rescore},
        system_run=_is_system_run(request),
    )
    # Event-driven trigger (RT-008): fit-scorer completion is the event that
    # creates board work — jobs move from "discovered" to "screening" with a
    # fitScore, which is exactly what the board sweep consumes. Enqueue a sweep
    # stretch NOW instead of waiting up to 10 minutes for the next cron tick.
    # Best-effort: the cron is the floor; a transient enqueue failure must not
    # taint the honest fit-scorer result the caller already paid for.
    if int(output.get("scored") or 0) > 0:
        try:
            from app.workers.board_sweep import enqueue_user_sweep

            enqueue_user_sweep(current_user["id"])
        except Exception:  # noqa: BLE001 — best-effort; cron still fires
            pass
    return {"status": "completed", "scored": output["scored"], "errors": output["errors"]}


def _positive_int_env(name: str, default: int) -> int:
    """Positive int from the environment; malformed/non-positive -> ``default``.

    Non-positive falls back deliberately: a 0 cap would silently disable the
    sweep (and a 0 budget the guard), which is exactly the silent-no-op failure
    these bounds exist to prevent.
    """
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _sweep_eligible_users(limit: int) -> list[dict[str, str]]:
    """Every subscriber the scheduled sweep must serve (S-FIX-A / S-1).

    "Must serve" = has a usable search target (a non-empty ``targetRole`` — a
    run without one is refused by ``_resolve_scout_target`` rather than
    completed with somebody else's persona), is not suspended, and — while the
    subscription gate is ON — holds an ENTITLED PAID subscription by exactly
    the same definition the paywall uses (``SubscriptionRepository``'s
    ``_ENTITLED_STATUSES`` + ``planId != 'free'``). When the operator turns the
    gate off (freemium), entitlement is not a filter, mirroring
    ``_require_active_subscription``.

    Oldest accounts first, bounded by ``limit``, so the sweep is deterministic
    and its external-API cost is predictable.
    """
    from app.repositories.billing import _ensure_billing_tables

    ensure_user_profile_columns()
    _ensure_billing_tables()
    entitled_clause = ""
    params: tuple[Any, ...] = (limit,)
    if subscription_gate_enabled():
        # ADMIN-FULL: the sweep's SQL filter must agree with the ONE resolver, or
        # an admin (and an admin-granted comp/tier/unlimited user) would be
        # silently excluded from autopilot despite passing every runtime gate.
        # Same three-way precedence as ``entitlements.resolve``, expressed as a
        # set-returning predicate so the sweep stays one query.
        entitlements.ensure_entitlement_schema()
        statuses = SubscriptionRepository._ENTITLED_STATUSES
        entitled_clause = (
            " AND (COALESCE(u.\"isAdmin\", false)"
            ' OR EXISTS (SELECT 1 FROM "UserEntitlementOverride" o'
            ' WHERE o."userId" = u."id")'
            ' OR EXISTS (SELECT 1 FROM "Subscription" s WHERE s."userId" = u."id"'
            ' AND s."status" = ANY(%s) AND s."planId" <> \'free\'))'
        )
        params = (list(statuses), limit)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT u."id", u."email" FROM "User" u'
                ' WHERE btrim(COALESCE(u."targetRole", \'\')) <> \'\''
                ' AND COALESCE(u."suspended", false) = false'
                f"{entitled_clause}"
                ' ORDER BY u."createdAt" ASC LIMIT %s',
                params,
            )
            return rows_to_dicts(cur)


@router.post("/discovery/sweep")
def run_discovery_sweep(request: Request) -> dict[str, Any]:
    """Scheduled discovery for EVERY entitled subscriber (S-FIX-A / S-1).

    THE GAP THIS CLOSES: the only automatic discovery path was
    ``scripts/discovery_cron.sh``, which logs in as ONE hardcoded account and
    runs scout + fit-scorer for that user alone. Every other paying subscriber
    got zero automatic job discovery — their board only moved when they clicked
    Sync. For a job-search product that is the core value, so it cannot depend
    on the customer remembering to press a button.

    Authenticated by the ``X-Aether-System-Run`` shared secret ALONE (no user
    session — the platform has no password for its subscribers, and inventing
    one would be far worse than a scoped secret). The secret is compared in
    constant time by ``_is_system_run``; when ``AETHER_SYSTEM_RUN_SECRET`` is
    unset the endpoint is unreachable (401) rather than open.

    Each user's runs go through the SAME ``_dispatch`` as their own manual run,
    with ``system_run=True`` — so the scoped paywall exemption for scout /
    fit-scorer applies exactly as it already does for the cron, and every other
    guard (quota reserve, spend cap, AgentRun audit row) is untouched. Runs are
    SPACED (``AETHER_DISCOVERY_SWEEP_SPACING_SECONDS``) and bounded
    (``AETHER_DISCOVERY_SWEEP_USER_CAP``) so N subscribers cannot burst the
    shared Adzuna budget or the 25-connection database ceiling; the adapter's
    own cache + daily-budget guard is the second line.

    One user's failure is reported against THAT user and never aborts the rest,
    and the response carries the live Adzuna budget so the operator can see
    exactly how much of the day's quota the sweep consumed.
    """
    if not _is_system_run(request):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "system_run_required",
                "message": (
                    "The scheduled discovery sweep requires a valid "
                    "X-Aether-System-Run secret."
                ),
            },
        )
    cap = _positive_int_env("AETHER_DISCOVERY_SWEEP_USER_CAP", 25)
    spacing = max(
        0.0, float(os.environ.get("AETHER_DISCOVERY_SWEEP_SPACING_SECONDS", "5") or 5)
    )
    users = _sweep_eligible_users(cap)
    rows: list[dict[str, Any]] = []
    for index, user in enumerate(users):
        user_id = str(user["id"])
        row: dict[str, Any] = {
            "userId": user_id, "email": user.get("email"), "status": "ok",
            "persisted": 0, "updated": 0, "scored": 0, "error": None,
        }
        try:
            query, location = _resolve_scout_target(user_id, {})
            scout = _dispatch(
                user_id, "scout", {"query": query, "location": location},
                system_run=True,
            )
            row["persisted"] = int(scout.get("persisted") or 0)
            row["updated"] = int(scout.get("updated") or 0)
            row["perSource"] = scout.get("per_source", [])
            scored = _dispatch(user_id, "fitScorer", {"rescore": False}, system_run=True)
            row["scored"] = int(scored.get("scored") or 0)
            # Parity with POST /agents/fit-scorer/run (RT-008): newly scored
            # jobs are exactly the board work the sweep consumes, so nudge it
            # now instead of waiting up to 10 minutes for the ARQ cron.
            # Best-effort — an enqueue hiccup must not taint an honest run.
            if row["scored"] > 0:
                try:
                    from app.workers.board_sweep import enqueue_user_sweep

                    enqueue_user_sweep(user_id)
                except Exception:  # noqa: BLE001 — cron remains the floor
                    pass
        except Exception as exc:  # noqa: BLE001 — report, never abort the sweep
            row["status"] = "error"
            row["error"] = f"{type(exc).__name__}: {exc}"
            logger.warning("discovery-sweep: user %s failed: %s", user_id, row["error"])
        rows.append(row)
        # Space the runs so N users do not burst the shared external API budget
        # or the database connection ceiling. Never sleeps after the last user.
        if spacing and index < len(users) - 1:
            time.sleep(spacing)
    from app.services.discovery.adzuna_adapter import budget_snapshot

    logger.info(
        "discovery-sweep: %d users swept (%d errors)",
        len(rows), sum(1 for r in rows if r["status"] == "error"),
    )
    return {
        "status": "completed",
        "sweptUsers": len(rows),
        "userCap": cap,
        "users": rows,
        "adzunaBudget": budget_snapshot(),
    }


@router.post("/board-sweep/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_board_sweep(
    current_user: CurrentUser, request: Request
) -> dict[str, Any]:
    """Event-driven trigger: enqueue a board-sweep stretch for the caller NOW.

    Closes the latency gap between discovery (scout + fit-scorer, which run
    synchronously on the 30-minute discovery timer) and the board sweep (which
    otherwise runs on a SEPARATE 10-minute ARQ cron). The operator can also hit
    this endpoint manually to nudge a user's board forward without waiting for
    the next cron tick.

    Gated by the same ``AETHER_BOARD_SWEEP_ENABLED`` kill-switch as the cron,
    and a no-op (200 ``{"status":"skipped"}``) when the user has no actionable
    board work — so a scout that found nothing, or a board that's already
    complete, does not enqueue an empty stretch.

    ``system_run`` is honored for parity with the discovery cron path (scout /
    fit-scorer are ``_SYSTEM_RUN_EXEMPT_AGENTS``), but this endpoint only
    ENQUEUES the sweep — the sweep itself is the one that calls ``_run_agent``
    with ``system_run=True, skip_quota=True``, so the user's paid quota is
    never consumed (RT-007). The idempotent ``_job_id`` dedup the cron uses is
    reused here, so an event trigger racing the cron can never stack a second
    concurrent sweep for the same user.
    """
    from app.workers.board_sweep import enqueue_user_sweep, sweep_enabled

    if not sweep_enabled():
        return {"status": "skipped", "reason": "board-sweep disabled"}
    job_id = enqueue_user_sweep(current_user["id"])
    if job_id is None:
        return {"status": "skipped", "reason": "no board work or deduped"}
    return {"status": "enqueued", "job_id": job_id}


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
        # §5.3.1 point 5: an honest sub-85 warning from the score-aware
        # TailoringLoop — None when the loop reached the target.
        "warning": output.get("warning"),
        # GMV4-tailor-001 (§6.1(b)/§6.2): per-attempt progress trail + the
        # winning iteration's still-missing JD keywords — ALREADY computed by
        # TailoringLoop and returned on TailorRunResult (tailor_agent.py); this
        # endpoint previously whitelisted its response keys and silently
        # dropped both, even though the async job-result path
        # (``_job_status_payload`` -> ``job.get("result")``) already forwards
        # ``output`` unfiltered. Defaulting to ``[]`` only guards a non-tailor
        # backend's output shape — ``_dispatch`` for "tailor" always sets both.
        "iterations": output.get("iterations", []),
        "gapKeywords": output.get("gapKeywords", []),
        # W-TAILOR-CONVERGE: the run's honest verdict + headline numbers —
        # target, best score, which iteration won, why the loop stopped, and
        # the JD keywords no truthful rewrite could ever add. Identical to the
        # dict persisted on the Resume row, so the response and a later reload
        # always agree.
        "tailoringSummary": output.get("tailoringSummary", {}),
        # U2c (ad0eb388): the 80%-all-dimensions quality-floor verdict for the
        # SHIPPED version — already computed by TailoringLoop and lifted to
        # the top level of TailorRunResult "so the run card can read it
        # without unpacking the summary" (tailor_agent.py), but this
        # hand-built whitelist previously dropped it, the exact bug class
        # test_router_whitelist_does_not_silently_drop_new_result_fields
        # exists to catch. ``None`` iff the gate was never armed for this run.
        "qualityGate": output.get("qualityGate"),
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
    except (FabricationError, StructuralError) as exc:
        # Unified with the generic /{name}/run route on ONE translation (F-1) so
        # the two cannot drift again. The subject stays the studio's established
        # wording — the rejection panel's documented detail shape.
        raise _guard_rejection_http_error("Cover letter", exc) from exc
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
        # W-TAILOR-CONVERGE item 4: the deterministic quality breakdown of the
        # letter actually stored (initial-draft vs shipped score, the passes
        # behind it, and the JD keywords the candidate's evidence cannot
        # support). Identical to Application.coverLetterQuality, so the studio
        # shows the same numbers before and after a reload.
        "quality": output.get("quality", {}),
        # AUD-COV-2: the honest low-fit disclosure for an EXPLICITLY requested
        # letter on a role below the caller's own matchThreshold (or unscored).
        # Empty string when the job clears the bar. Whitelisted here because
        # this response is a whitelist — omitting it would drop the one signal
        # that makes the explicit path honest rather than merely permitted.
        "fit_disclosure": output.get("fit_disclosure", ""),
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
    # --- job_alerts mode -------------------------------------------------
    #: How far back to scan each mailbox (days, 1-30; default 7).
    days: int | None = None
    #: Per-mailbox message budget for the scan (1-500; default 200).
    max_messages: int | None = None
    #: Restrict the scan to ONE connected mailbox. Omit to scan them all.
    account_id: str | None = None
    #: Explicit lighter-model retry after a provider 429. Never a free-form
    #: model id — ADR-ML-3 forbids the client choosing an arbitrary substitute.
    light_retry: bool = False


@router.post("/email/run")
def run_email_agent(
    body: EmailAgentRequest, current_user: CurrentUser, request: Request,
    response: Response,
) -> dict[str, Any]:
    """Run the Email Agent: triage / draft_reply / insights / send /
    job_alerts (P4, W-ALERT).

    Gmail-backed when the user has connected Gmail; otherwise degrades honestly
    to local ``EmailThread`` rows (never fabricates inbox data). ``send`` mode
    never sends directly — it opens a pending ``email_send`` approval so the
    human-in-the-loop gate always adjudicates a real outbound email.
    ``job_alerts`` reads the candidate's OWN automated job-alert mail across
    every connected mailbox and persists each extracted posting as a real
    ``Job`` row (deterministic, no LLM, nothing invented).

    EMAIL-DRAFTING-FIX item 5: ``triage``/``draft_reply``/``draft_follow_up``/
    ``insights`` are real LLM calls (measured live at 26.7s-61.0s) that a
    synchronous request behind a proxy can 503 on. When
    ``AETHER_ASYNC_GENERATION`` is ON, exactly those modes are routed through
    the SAME enqueue + ``GET /agents/jobs/{id}`` polling path tailor/coverLetter
    already use (the web client's ``runAgent``/``resolveRun`` already handles
    the 202 envelope generically — no frontend change needed). ``send`` /
    ``apply_labels`` / ``job_alerts`` reach no model at all
    (``_email_agent_will_call_llm``, the SAME predicate ML-W4C already uses to
    decide metering) and stay synchronous — enqueuing a sub-100ms Gmail
    mutation would only add latency for no benefit.
    """
    params = {k: v for k, v in body.model_dump().items() if v is not None}
    if async_generation_enabled() and _email_agent_will_call_llm(params):
        system_run = _is_system_run(request)
        job_id = _enqueue_single_agent(
            current_user["id"], "emailAgent", params, system_run=system_run
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
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
    """Same contract as :class:`ScoutRunRequest`, and for the same reason.

    F-02: these two fields defaulted to ``_DEFAULT_QUERY``/``_DEFAULT_LOCATION``.
    ``runPipeline()`` posts ``body: {}``, so pydantic materialised those
    literals and ``_user_search_defaults`` — the profile-derived helper that
    already existed — was never consulted: every user's "Run All" scouted the
    same hardcoded PM/BA persona in Melbourne and wrote the results to their own
    board. ``None`` is what makes the user's own profile reachable."""

    query: str | None = Field(default=None, min_length=1)
    location: str | None = Field(default=None, min_length=1)


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
    (``budget_seconds`` → the more-generous worker pipeline budget).

    B6 (ORCH-B1-BLUEPRINT-2026-08-14.md §4.4): this is the ONE place in this
    tree where one run genuinely causes others (B1a's scheduler is a separate,
    uncommitted worktree — not present here). Every step below is dispatched
    BY this pipeline invocation, so each one's ``parentRunId`` is the
    SUPERVISOR run's id — a sibling of the others, not chained to the previous
    step. That is the real, traceable cause: the supervisor is what decided
    this sequence would run at all."""
    steps: list[dict[str, Any]] = []

    # Supervisor node: plans the run (audit-recorded, defect fix — the card
    # previously showed "Never run" because the pipeline skipped this node).
    # It is the top of this run's causal chain, so it takes no parent itself.
    sup_out = _record_run(
        user_id, "supervisor", params, lambda: {"plan": list(_PIPELINE_PLAN)}
    )
    steps.append({"agent": "supervisor", "output": sup_out})
    sup_run_id = sup_out.get("run_id")
    # ORCH-ADV: the supervisor records a plan. Consume it. A plan that is not
    # exactly the canonical sequence falls back to that sequence rather than
    # inventing a new LLM planner.
    plan = sup_out.get("plan")
    if not isinstance(plan, list) or plan != list(_PIPELINE_PLAN):
        plan = list(_PIPELINE_PLAN)
    spine = [step for step in plan if step in ("scout", "fitScorer", "matcher")]
    writing = [step for step in plan if step in ("tailor", "coverLetter")]

    top_job_id = None
    for step_name in spine:
        if step_name == "scout":
            scout_out = _dispatch(user_id, "scout", params, parent_run_id=sup_run_id)
            steps.append({"agent": "scout", "output": scout_out})
        elif step_name == "fitScorer":
            fit_out = _dispatch(
                user_id, "fitScorer", {"rescore": False}, parent_run_id=sup_run_id
            )
            steps.append({"agent": "fitScorer", "output": fit_out})
        elif step_name == "matcher":
            from app.agents.matcher_agent import MatcherAgent

            # Matcher node: ranks scored jobs and selects the top match.
            # Reuses the now first-class MatcherAgent so the pipeline and the
            # standalone /agents/matcher/run trigger share one implementation.
            match_out = _record_run(
                user_id, "matcher", {}, lambda: MatcherAgent().run(user_id),
                parent_run_id=sup_run_id,
            )
            steps.append({"agent": "matcher", "output": match_out})
            top_job_id = match_out.get("top_job_id")
            if not top_job_id:
                return {"status": "completed", "steps": steps, "approvalRequired": False}
            # RT-005: the matcher chose this job — surface that on the board
            # ("matched" renders in the Evaluating column). Forward-only
            # guarded advance; kept here (not in MatcherAgent) so the
            # standalone read-only ranking endpoint stays side-effect-free.
            JobRepository().advance_status(
                top_job_id, "matched", allowed_from={"discovered", "screening"}
            )

    if not top_job_id or not writing:
        return {"status": "completed", "steps": steps, "approvalRequired": False}

    # One shared wall-clock budget across BOTH LLM-backed steps: without it
    # tailor and coverLetter each armed their own 60 s budget, so the pipeline
    # could exceed the HTTP edge's ~100 s ceiling and surface as a 524 (D1).
    from app.agents.cover_letter_agent import FabricationError, StructuralError
    from app.agents.tailor_agent import NoChangesApplied
    from app.services.application_submission import (
        job_fit_score,
        load_agent_config,
        low_fit_skip_message,
        meets_match_threshold,
        user_match_threshold,
    )
    from app.services.llm_client import shared_budget

    tailor_out: dict[str, Any] = {}
    letter_out: dict[str, Any] = {}
    with shared_budget(budget_seconds):
        for step_name in writing:
            if step_name == "tailor":
                try:
                    tailor_out = _dispatch(
                        user_id, "tailor", {"job_id": top_job_id},
                        parent_run_id=sup_run_id,
                    )
                except NoChangesApplied as exc:
                    # MV-resume-studio-003: the guards rejected every proposed
                    # edit, so no tailored version was created and the tailor
                    # run was refunded. This must NOT fail the whole pipeline
                    # — the cover-letter step draws on the base résumé
                    # regardless — so record the honest no-op and continue.
                    #
                    # B6xP1A: "run_id" is included here too, exactly like
                    # every other step's output — the AgentRun row this no-op
                    # finished is already correctly parented under the
                    # supervisor (``_dispatch`` above passed
                    # ``parent_run_id=sup_run_id``); omitting the id from this
                    # branch only would silently make the no-op case
                    # unrecoverable from ``GET /agents/runs``, a dishonest gap
                    # the success case doesn't have.
                    tailor_out = {
                        "noChangesApplied": True, "changes": 0,
                        "message": str(exc),
                        "run_id": getattr(exc, "run_id", None),
                    }
                steps.append({"agent": "tailor", "output": tailor_out})
            elif step_name == "coverLetter":
                # AUD-COV-2: this job was chosen BY the matcher, not by the
                # user, so the cover step below is AUTO-generation and obeys
                # the same fit bar the board sweep does. Below the user's own
                # matchThreshold — or unscored — Aether does not write a
                # letter whose §10.2 opener asserts a "direct match". The
                # tailored résumé above is kept (it makes no claim about
                # fit), and the honest skip is reported as this step's
                # output rather than a silently missing step.
                pipeline_threshold = user_match_threshold(load_agent_config(user_id))
                pipeline_fit = job_fit_score(user_id, top_job_id)
                if not meets_match_threshold(pipeline_fit, pipeline_threshold):
                    skip_message = low_fit_skip_message(
                        pipeline_fit, pipeline_threshold
                    )
                    steps.append({
                        "agent": "coverLetter",
                        "output": {
                            "skipped": True,
                            "reason": "below_match_threshold",
                            "fitScore": pipeline_fit,
                            "matchThreshold": pipeline_threshold,
                            "message": skip_message,
                        },
                    })
                    return {
                        "status": "completed",
                        "steps": steps,
                        "top_job_id": top_job_id,
                        "approvalRequired": False,
                        "message": skip_message,
                    }
                try:
                    letter_out = _dispatch(
                        user_id, "coverLetter", {"job_id": top_job_id},
                        parent_run_id=sup_run_id,
                    )
                except (FabricationError, StructuralError) as exc:
                    # GAP-P7-COV-PIPE-001: the cover step's own fabrication /
                    # structural guard rejected the draft. That is the guard
                    # WORKING (Aether never ships a fabricated cover letter),
                    # but it must NOT discard the SUCCESSFUL tailoring that
                    # precedes it. The coverLetter AgentRun is already recorded
                    # as an honest COMPLETED degrade (GAP-P4-002) and its
                    # reserved quota refunded inside _dispatch/_record_run, so
                    # here we ONLY degrade gracefully.
                    reason = getattr(exc, "flagged", None) or getattr(
                        exc, "issues", None
                    )
                    steps.append(
                        {
                            "agent": "coverLetter",
                            "output": {
                                "coverLetterUnavailable": True,
                                "reason": str(reason),
                            },
                        }
                    )
                    # Honest message: the lead must reflect what the tailor
                    # step ACTUALLY did. If tailoring ALSO no-op'd, never
                    # claim "your résumé was tailored".
                    tailored = not tailor_out.get("noChangesApplied") and int(
                        tailor_out.get("changes") or 0
                    ) > 0
                    lead = (
                        "Your résumé was tailored for this role, but an "
                        "auto-generated cover letter"
                        if tailored
                        else "No verifiable résumé changes could be applied "
                        "for this role, and an auto-generated cover letter"
                    )
                    return {
                        "status": "completed",
                        "steps": steps,
                        "top_job_id": top_job_id,
                        "approvalRequired": False,
                        "coverLetterUnavailable": True,
                        "message": (
                            f"{lead} couldn't be produced without unverifiable "
                            "wording, so it was withheld — open the Cover "
                            "Letter studio to generate or write one manually."
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
    # F-02: resolve the discovery target HERE, before anything is enqueued or
    # recorded. "Run All" posts an empty body, so this is the point at which a
    # user who has configured no target role/location is honestly refused
    # (422) instead of having somebody else's search fabricated for them —
    # and doing it at the route means the ASYNC path refuses at request time
    # rather than failing a background job the user only discovers later. The
    # resolved values are stored on the params the worker replays, so the
    # queued job carries the SAME search the caller was told about.
    params = body.model_dump()
    params["query"], params["location"] = _resolve_scout_target(user_id, params)
    if async_generation_enabled():
        job_id = _enqueue_pipeline(
            user_id, params, system_run=_is_system_run(request)
        )
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
    return _pipeline_core(user_id, params)


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


#: Case-insensitive substrings that mark a ``failed`` AgentRun as a TRANSIENT /
#: upstream-unavailable blip rather than genuine agent breakage (ML-agents-err-001).
#: Kept conservative on purpose: these are all provider/transport signals (rate
#: limiting, upstream 429/5xx, timeouts, "temporarily unavailable" — the real
#: LLM_UNAVAILABLE_USER_MESSAGE text), never the agent's own deterministic logic
#: errors — so a real failure such as a KeyError during tailoring does NOT match
#: and still surfaces as "error". This ERROR-MESSAGE keyword is the ONLY honest
#: transient signal: a ``costUsd IS NULL`` run is NOT evidence of a transient
#: failure, because EVERY failed AgentRun has ``costUsd`` NULL in production (no
#: ``finish(..., "failed", ...)`` call site records cost — only the success path
#: does), so a cost-based refund heuristic would classify all failures transient
#: and hide genuine breakage. Cost is deliberately not consulted here.
_TRANSIENT_FAILURE_KEYWORDS = (
    "temporarily unavailable",
    "rate limit",
    "rate-limited",
    "429",
    "503",
    "502",
    "504",
    "timeout",
    "timed out",
    "overloaded",
    "service unavailable",
    "try again",
)

#: The keyword tuple is split — WITHOUT duplicating it — into the phrase
#: keywords (matched as plain substrings, as before) and the bare numeric
#: HTTP-status codes (matched only as standalone tokens via word boundaries).
#: Derived from the single tuple above so the two never drift (ML-agents-err-001
#: OBS-A). An unanchored substring match on "429"/"502"/"503"/"504" wrongly
#: classified a GENUINE failure whose message merely embeds those digits inside
#: an unrelated identifier — a cuid ("Job c429k2j9x... not found"), a record id,
#: a field name ("field_503_value") — as a transient upstream blip, hiding real
#: breakage behind an "active"/"completed" card. The ``\b`` anchoring makes a
#: digit run count only when it stands alone as an HTTP-status token (e.g.
#: "HTTP 503 Service Unavailable"), not when buried in an identifier.
_TRANSIENT_PHRASE_KEYWORDS = tuple(
    k for k in _TRANSIENT_FAILURE_KEYWORDS if not k.isdigit()
)
_TRANSIENT_CODE_TOKENS = tuple(
    k for k in _TRANSIENT_FAILURE_KEYWORDS if k.isdigit()
)
_TRANSIENT_CODE_RE = (
    re.compile(r"\b(?:" + "|".join(re.escape(k) for k in _TRANSIENT_CODE_TOKENS) + r")\b")
    if _TRANSIENT_CODE_TOKENS
    else None
)


def _is_transient_failure(run: dict[str, Any]) -> bool:
    """True when a ``failed`` run is an honest transient/upstream-unavailable
    blip, not genuine agent breakage (ML-agents-err-001).

    Classified by the ERROR MESSAGE ONLY: the lowercased ``run["error"]``
    contains a known transient/upstream signal — a phrase keyword (provider
    rate-limit / timeout / "temporarily unavailable") matched as a substring,
    OR a bare HTTP-status code (429/502/503/504) matched only as a STANDALONE
    token (word-boundary anchored), never as a digit run embedded inside an
    unrelated identifier such as a cuid / record id / field name (OBS-A). Cost
    is intentionally NOT consulted: every failed AgentRun has ``costUsd`` NULL
    in production (no ``finish(..., "failed", ...)`` call site records cost), so
    a ``costUsd IS NULL`` refund heuristic would match ALL failures and
    misclassify a genuine billed logic error (KeyError, validation) as transient
    — hiding a broken agent behind an "active" card.

    Pure and side-effect free. Deliberately conservative so a genuine failure
    (non-transient message) returns False and still paints the card "error".
    """
    error = (run.get("error") or "").lower()
    # CRITICAL-1: an ABANDONED run (watchdog-reconciled — the owning process
    # died and stopped heartbeating) is never a transient upstream blip, and
    # must never be tolerated into an "active" card. Checked FIRST, because the
    # honest error quotes real elapsed minutes and a value like "503.0 minutes"
    # would otherwise trip the bare-HTTP-status token match below and re-hide
    # the very concealment this watchdog exists to remove.
    if ABANDONED_ERROR_MARKER in error:
        return False
    if any(keyword in error for keyword in _TRANSIENT_PHRASE_KEYWORDS):
        return True
    return bool(_TRANSIENT_CODE_RE is not None and _TRANSIENT_CODE_RE.search(error))


def _latest_failure_is_hard(runs: list[dict[str, Any]] | None) -> bool:
    """Single source of truth for whether an agent's MOST-RECENT run is a HARD
    failure (operator-visible breakage) vs a tolerated transient blip
    (ML-agents-err-001 OBS-B).

    ``runs`` is the recent window (newest-first, from
    ``AgentRunRepository.recent_runs_by_agent``). Returns True only when the
    latest run failed AND that failure is genuine breakage: either CHRONIC
    (the last 3 runs are all ``failed``) or the latest error message is
    non-transient. A lone transient/upstream blip (rate-limit / 5xx / timeout /
    "temporarily unavailable") on an otherwise-healthy agent is NOT a hard
    failure; a completed / queued / running / absent latest run is not either.

    Both ``GET /agents/catalog`` (agent_catalog) and ``GET /agents``
    (list_agents) classify agent health through THIS one helper over the same
    recent-run window, so the Agents-screen catalog cards and the Orchestration
    view never disagree about whether an agent is broken.
    """
    if not runs:
        return False
    latest = runs[0]
    if latest["status"] != "failed":
        return False
    chronic = len(runs) >= 3 and all(r["status"] == "failed" for r in runs[:3])
    return chronic or not _is_transient_failure(latest)


# ---------------------------------------------------------------------------
# Agent orchestration maps (U-AX build spec item 5) — the end-to-end workflow
# every catalog agent occupies, with its real/planned status, the metrics it
# consumes, the thresholds it is answerable for, and its measured trend.
# ---------------------------------------------------------------------------

#: ONE operating loop rather than three panels. Independent review (ORCH-ADV)
#: proved the three-map split hid the Story Bank → tailoring team, buried the
#: conductor inside a fabricated "Learning Loop" that claimed to re-tune
#: agents, and parked correspondence with Submission. U-PLAN.md still allows
#: multiple maps; the constraint is the end result. One loop is the honest
#: picture of how these agents actually work as a team.
#:
#: ``(mapKey, mapName, mapSubtitle, [(stage, [agentKey, ...]), ...])``.
_ORCHESTRATION_MAPS: tuple[tuple[str, str, str, tuple[tuple[str, tuple[str, ...]], ...]], ...] = (
    (
        "career-operating-loop",
        "Career Search Operating Loop",
        "How the catalog agents work as one team, from the conductor through "
        "discovery, evidence, writing, approval-gated send, and a read-only "
        "review of outcomes.",
        (
            ("Conduct", ("orchestration",)),
            ("Discovery", ("jobDiscovery",)),
            (
                "Market & employer context",
                ("marketTrends", "salaryIntelligence", "companyResearch"),
            ),
            (
                "Fit & ranking",
                ("matchScoring", "atsOptimization", "skillGap", "jobMatching"),
            ),
            ("Evidence", ("storyExtraction",)),
            ("Tailoring", ("resumeTailoring",)),
            ("Cover Letter", ("coverLetter",)),
            ("Quality gate", ("compliance",)),
            ("Prepare & queue", ("submission",)),
            (
                "Correspondence",
                ("emailAgent", "sentimentAnalysis", "scheduling", "notification"),
            ),
            ("Interview readiness", ("interviewPrep",)),
            ("Networking", ("recruiterOutreach", "reference")),
            ("Outcomes & review", ("learningFeedback",)),
        ),
    ),
)

#: Per-agent metric/threshold visibility. Keys are catalog keys; an agent
#: absent from this table reports EMPTY lists — honest ("nothing recorded")
#: rather than a generic filler sentence that would read as a real
#: responsibility. Thresholds name only the two the product actually measures
#: (the >80% 10-dimension floor and the 1-in-5 interview conversion target,
#: U2c/U5 ENRICHMENT MANDATE item 2).
_AGENT_METRIC_VISIBILITY: dict[str, dict[str, tuple[str, ...]]] = {
    "jobDiscovery": {
        "metrics": ("jobs discovered per run", "source availability"),
        "thresholds": (),
    },
    "matchScoring": {
        "metrics": ("10-dimension fit scores", "ATS score"),
        "thresholds": ("every fit dimension > 80%",),
    },
    "atsOptimization": {
        "metrics": ("ATS keyword + semantic subscores",),
        "thresholds": ("every fit dimension > 80%",),
    },
    "skillGap": {
        "metrics": ("matched vs missing JD keywords",),
        "thresholds": ("every fit dimension > 80%",),
    },
    "jobMatching": {
        "metrics": ("fit score ranking",),
        "thresholds": (),
    },
    "resumeTailoring": {
        "metrics": (
            "ATS score before/after",
            "policy rigor tier",
        ),
        "thresholds": (
            "ATS target score set by the current rigor tier",
            "every fit dimension > 80%",
        ),
    },
    "coverLetter": {
        "metrics": (
            "cover-letter quality score",
            "policy rigor tier",
        ),
        "thresholds": ("cover-letter quality target 85",),
    },
    "compliance": {
        "metrics": ("fabrication/entailment guard verdicts",),
        "thresholds": ("zero unverifiable claims shipped",),
    },
    "submission": {
        "metrics": (
            "applications prepared and queued for approval",
            "resolved transmission channel",
        ),
        "thresholds": (),
    },
    "emailAgent": {
        "metrics": ("messages transmitted",),
        "thresholds": (),
    },
    "notification": {
        "metrics": (
            "records changed since last digest",
            "new scored matches",
            "digests sent after approval",
        ),
        "thresholds": (),
    },
    "scheduling": {
        "metrics": ("time-proposal drafts", "availability source"),
        "thresholds": (),
    },
    "orchestration": {
        "metrics": ("pipeline step outcomes", "policy rigor tier"),
        "thresholds": (),
    },
    "storyExtraction": {"metrics": ("evidence stories captured",), "thresholds": ()},
    "sentimentAnalysis": {"metrics": ("employer response sentiment",), "thresholds": ()},
    "learningFeedback": {
        "metrics": (
            "interview conversion rate of transmitted applications",
            "10-dimension fit scores at submission",
            "ATS score trend",
        ),
        "thresholds": (
            "1 interview per 5 transmitted applications",
            "every fit dimension > 80%",
        ),
    },
    "marketTrends": {
        "metrics": (
            "keyword shifts in your own discovery feed",
            "remote mix in your own feed",
            "postings per week in your own feed",
        ),
        "thresholds": (),
    },
    "salaryIntelligence": {
        "metrics": (
            "advertised pay disclosed by your own postings",
            "share of postings that disclosed pay",
        ),
        "thresholds": (),
    },
    "companyResearch": {"metrics": ("employer profile coverage",), "thresholds": ()},
    "recruiterOutreach": {
        "metrics": ("outreach drafts queued for approval",),
        "thresholds": (),
    },
    "reference": {
        "metrics": ("reference-request drafts queued for approval",),
        "thresholds": (),
    },
    "interviewPrep": {"metrics": ("prep packs generated",), "thresholds": ()},
}

#: How each catalog agent sits on the operating loop as a teammate, not a
#: silo. ``dependsOn`` / ``supports`` name catalog keys this agent honestly
#: consumes or feeds — never a market-trends → matcher edge the runtime
#: does not have, and never a learning-feedback "re-tune".
_AGENT_TEAM: dict[str, dict[str, Any]] = {
    "orchestration": {
        "role": (
            "Conducts the live pipeline: records the plan, then dispatches "
            "discovery, fit scoring, matching, tailoring and the cover letter "
            "as one run."
        ),
        "dependsOn": (),
        "supports": (
            "jobDiscovery",
            "matchScoring",
            "jobMatching",
            "resumeTailoring",
            "coverLetter",
        ),
    },
    "jobDiscovery": {
        "role": (
            "Finds open roles from your configured sources so later agents "
            "have a real posting to score, rank, and write against."
        ),
        "dependsOn": (),
        "supports": (
            "matchScoring",
            "atsOptimization",
            "skillGap",
            "jobMatching",
            "marketTrends",
            "salaryIntelligence",
            "companyResearch",
        ),
    },
    "marketTrends": {
        "role": (
            "Reads keyword, remote-mix and volume shifts inside your own "
            "discovery feed. It does not score jobs or change matching."
        ),
        "dependsOn": ("jobDiscovery",),
        "supports": (),
    },
    "salaryIntelligence": {
        "role": (
            "Aggregates pay ranges your own postings actually disclosed. It "
            "does not import an external salary benchmark."
        ),
        "dependsOn": ("jobDiscovery",),
        "supports": (),
    },
    "companyResearch": {
        "role": (
            "Synthesises what your own discovered postings already say about "
            "an employer. It does not browse the public web."
        ),
        "dependsOn": ("jobDiscovery",),
        "supports": (),
    },
    "matchScoring": {
        "role": (
            "Scores every discovered job on ten dimensions plus ATS. One "
            "engine also powers the ATS and skill-gap cards."
        ),
        "dependsOn": ("jobDiscovery",),
        "supports": (
            "atsOptimization",
            "skillGap",
            "jobMatching",
            "resumeTailoring",
            "learningFeedback",
        ),
    },
    "atsOptimization": {
        "role": (
            "The ATS keyword and semantic facet of Match Scoring — the same "
            "fitScorer run, shown as its own card."
        ),
        "dependsOn": ("matchScoring",),
        "supports": ("resumeTailoring",),
    },
    "skillGap": {
        "role": (
            "The missing-keyword facet of Match Scoring — the same fitScorer "
            "run, shown as its own card."
        ),
        "dependsOn": ("matchScoring",),
        "supports": ("resumeTailoring", "interviewPrep"),
    },
    "jobMatching": {
        "role": (
            "Ranks scored jobs and picks the top target the pipeline will "
            "tailor and write a cover letter for."
        ),
        "dependsOn": ("matchScoring",),
        "supports": ("resumeTailoring", "coverLetter", "submission"),
    },
    "storyExtraction": {
        "role": (
            "Banks STAR evidence the writing, interview-prep and outreach "
            "agents are allowed to use."
        ),
        "dependsOn": (),
        "supports": (
            "resumeTailoring",
            "coverLetter",
            "interviewPrep",
            "recruiterOutreach",
            "reference",
        ),
    },
    "resumeTailoring": {
        "role": (
            "Rewrites your résumé against one job using only the Story Bank "
            "and the posting, then holds the result for you."
        ),
        "dependsOn": ("storyExtraction", "jobMatching"),
        "supports": ("coverLetter", "submission", "compliance"),
    },
    "coverLetter": {
        "role": (
            "Drafts a cover letter from the same Story Bank and job the "
            "tailor just used, then queues it for approval."
        ),
        "dependsOn": ("storyExtraction", "resumeTailoring"),
        "supports": ("submission", "compliance"),
    },
    "compliance": {
        "role": (
            "Reports fabrication and entailment guard verdicts already "
            "recorded on your tailoring and cover-letter runs."
        ),
        "dependsOn": ("resumeTailoring", "coverLetter"),
        "supports": ("submission",),
    },
    "submission": {
        "role": (
            "Prepares one of your own ready applications and queues it for "
            "approval. It transmits nothing itself."
        ),
        "dependsOn": ("resumeTailoring", "coverLetter", "compliance"),
        "supports": ("learningFeedback",),
    },
    "emailAgent": {
        "role": (
            "Drafts replies and follow-ups on real Gmail threads. Sends stay "
            "behind Approvals. Recruiter outreach hands off here once a "
            "thread exists."
        ),
        "dependsOn": (),
        "supports": (
            "sentimentAnalysis",
            "scheduling",
            "notification",
            "recruiterOutreach",
        ),
    },
    "sentimentAnalysis": {
        "role": (
            "Reads the tone of one of your synced threads. It never changes "
            "the Email Agent's labels."
        ),
        "dependsOn": ("emailAgent",),
        "supports": (),
    },
    "scheduling": {
        "role": (
            "Drafts a time-proposal reply. It never books a calendar event "
            "and never sends."
        ),
        "dependsOn": ("emailAgent",),
        "supports": (),
    },
    "notification": {
        "role": (
            "Queues a digest of your own activity to connected Gmail, and "
            "only after you approve it."
        ),
        "dependsOn": ("jobMatching", "submission"),
        "supports": (),
    },
    "interviewPrep": {
        "role": (
            "Predicts questions from the real posting and answers them from "
            "your Story Bank as STAR sketches."
        ),
        "dependsOn": ("storyExtraction",),
        "supports": (),
    },
    "recruiterOutreach": {
        "role": (
            "Drafts a first-touch email from your résumé and Story Bank. "
            "Nothing leaves until you approve it."
        ),
        "dependsOn": ("storyExtraction",),
        "supports": ("emailAgent",),
    },
    "reference": {
        "role": (
            "Drafts a reference request from your résumé and Story Bank. "
            "Nothing leaves until you approve it."
        ),
        "dependsOn": ("storyExtraction",),
        "supports": (),
    },
    "learningFeedback": {
        "role": (
            "Read-only outcomes report across your applications. It never "
            "adapts or retrains another agent."
        ),
        "dependsOn": ("submission", "matchScoring", "resumeTailoring"),
        "supports": (),
    },
}

#: Where a per-run numeric quality signal lives inside ``AgentRun.output``, per
#: agent backend. ONLY these two agents record one today; every other agent's
#: trend is honestly reported as unavailable rather than substituted with
#: duration or cost, which measure the machine and not the work.
_TREND_METRIC_PATHS: dict[str, tuple[tuple[str, ...], str]] = {
    "tailor": (("tailoringSummary", "bestScore"), "best ATS score"),
    "coverLetter": (("quality", "overall"), "cover-letter quality score"),
}


def _numeric_at(payload: Any, path: tuple[str, ...]) -> float | None:
    """Follow ``path`` through nested dicts to a real number, else ``None``."""
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, bool) or not isinstance(node, (int, float)):
        return None
    return float(node)


def _agent_trend(backend: str, runs: list[dict[str, Any]] | None) -> dict[str, Any]:
    """This agent's improvement trend across its recent runs — or an honest null.

    ``runs`` is newest-first (``AgentRunRepository.recent_runs_by_agent``).
    ``direction`` is non-null ONLY when the agent records a comparable
    per-run quality number and at least two runs carry one; otherwise it is
    ``None`` with a ``basis`` explaining why. An agent that has never run gets
    zeros and a null direction — never an invented "steady".
    """
    runs = runs or []
    spec = _TREND_METRIC_PATHS.get(backend)
    if spec is None:
        return {
            "runs": len(runs),
            "metric": None,
            "latest": None,
            "previous": None,
            "delta": None,
            "direction": None,
            "basis": "this agent records no comparable per-run quality metric",
        }
    path, label = spec
    # Oldest-first so "previous" really is the earlier run.
    series = [
        value
        for run in reversed(runs)
        if (value := _numeric_at(run.get("output"), path)) is not None
    ]
    if len(series) < 2:
        return {
            "runs": len(runs),
            "metric": label,
            "latest": series[-1] if series else None,
            "previous": None,
            "delta": None,
            "direction": None,
            "basis": (
                "not enough scored runs yet to compare"
                if series
                else "no scored run recorded yet"
            ),
        }
    latest, previous = series[-1], series[-2]
    delta = round(latest - previous, 2)
    return {
        "runs": len(runs),
        "metric": label,
        "latest": latest,
        "previous": previous,
        "delta": delta,
        "direction": (
            "improving" if delta > 0 else "declining" if delta < 0 else "steady"
        ),
        "basis": f"{label}, latest run vs the one before it",
    }


@router.get("/orchestration-map")
def orchestration_map(current_user: CurrentUser) -> dict[str, Any]:
    """Every catalog agent placed in a defined end-to-end workflow (U-AX item 5).

    HONESTY INVARIANTS enforced structurally, not by convention:

    * ``status`` is ``real`` iff the catalog entry has a backend implementation
      and ``planned`` otherwise — a roadmap card can never render as executing.
    * ``lastRunPolicyTier`` / ``trend`` come from THIS user's own AgentRun rows.
      An agent that has never run reports ``null``, never a fabricated tier or
      a manufactured "steady" trend.
    * Any catalog agent not placed in a map above lands in an explicit
      "Unmapped" stage rather than disappearing, so adding an agent to the
      catalog can never silently shrink this view.
    """
    user_id = current_user["id"]
    last_runs = AgentRunRepository().last_policy_run_by_agent(user_id)
    recent_runs = AgentRunRepository().recent_runs_by_agent(user_id, window=5)

    def entry_for(agent_key: str) -> dict[str, Any]:
        catalog = _CATALOG_BY_KEY[agent_key]
        backend = catalog.get("backend")
        visibility = _AGENT_METRIC_VISIBILITY.get(agent_key, {})
        team = _AGENT_TEAM.get(agent_key, {})
        last = last_runs.get(backend) if backend else None
        return {
            "agentKey": agent_key,
            "name": catalog["name"],
            "backend": backend,
            "status": "real" if backend else "planned",
            "runnable": bool(backend) and backend in _RUNNABLE_BACKENDS,
            "metricsConsumed": list(visibility.get("metrics", ())),
            "thresholds": list(visibility.get("thresholds", ())),
            "lastRunPolicyTier": (last or {}).get("policyTier"),
            "lastRunAt": (last or {}).get("createdAt"),
            "lastRunStatus": (last or {}).get("status"),
            "trend": _agent_trend(backend or "", recent_runs.get(backend or "")),
            "teamRole": str(team.get("role") or "").strip(),
            "dependsOn": list(team.get("dependsOn") or ()),
            "supports": list(team.get("supports") or ()),
        }

    placed: set[str] = set()
    maps: list[dict[str, Any]] = []
    for map_key, map_name, subtitle, stages in _ORCHESTRATION_MAPS:
        stage_payload = []
        mapped_keys: list[str] = []
        for stage_name, agent_keys in stages:
            known = [k for k in agent_keys if k in _CATALOG_BY_KEY]
            placed.update(known)
            mapped_keys.extend(known)
            stage_payload.append(
                {"stage": stage_name, "agents": [entry_for(k) for k in known]}
            )
        maps.append(
            {
                "key": map_key,
                "name": map_name,
                "subtitle": subtitle,
                "stages": stage_payload,
                # AUD-AGENT-4: the map's own honest scale, so its header states
                # the server's arithmetic instead of summing nodes (which
                # counts one engine once per facet card).
                "counts": honest_map_counts(mapped_keys),
            }
        )

    unmapped = [a["key"] for a in AGENT_CATALOG if a["key"] not in placed]
    if unmapped:
        # Visible-by-construction drift guard: a newly added catalog agent
        # shows up here labelled as unplaced instead of vanishing from the
        # workflow view.
        maps.append(
            {
                "key": "unmapped",
                "name": "Not yet placed in a workflow",
                "subtitle": (
                    "These agents exist in the catalog but have not been assigned "
                    "a workflow stage yet."
                ),
                "stages": [
                    {
                        "stage": "Unmapped",
                        "agents": [entry_for(k) for k in unmapped],
                    }
                ],
                "counts": honest_map_counts(unmapped),
            }
        )
    return {"maps": maps}


# ---------------------------------------------------------------------------
# Supervisor RUN PLAN (ADR-AGI-3 Decision 1) — plan visibility first ($0), then
# one server-owned execution of it. The scheduler itself is
# ``app.services.run_scheduler``: pure planning, zero agent names. Everything
# agent-specific lives in :data:`_EXEC_CLASS_BY_BACKEND` (charter DATA) and in
# the seams below, which reuse the EXISTING dispatch chain rather than adding a
# second billing path.
# ---------------------------------------------------------------------------

#: Env dial for plan concurrency. Code default 1 — identical to today's
#: behaviour — and clamped by the worker's own ``max_jobs`` so a plan can never
#: claim more parallelism than the machine owns (R-3).
_ORCH_PLAN_CONCURRENCY_ENV = "AETHER_ORCH_PLAN_CONCURRENCY"
#: Inter-step spacing, copied from the discovery sweep's shipped default so the
#: fifth scheduler does not burst what the other four deliberately space out.
_ORCH_PLAN_SPACING_ENV = "AETHER_ORCH_PLAN_SPACING_SECONDS"

#: ``BackgroundJob.agentKey`` a whole plan runs under. Deliberately NOT a
#: backend name: it is a composite, like ``pipeline``, so ``_call_is_metered``
#: returns False for it and the plan row itself reserves nothing — every metered
#: reserve happens per STEP, inside ``_record_run`` (R-2b / R-4).
_ORCH_PLAN_AGENT_KEY = "orchestrationPlan"


def _orch_plan_concurrency() -> int:
    """The ceiling this plan will ACTUALLY run at.

    ``MAX_PLAN_CONCURRENCY`` is the worker's own ``max_jobs`` (a test pins the
    two equal). It is read from the scheduler rather than by importing
    ``workers.settings`` here, which would drag the sweep modules and an ARQ
    Redis import into every API request that renders a plan.
    """
    from app.services.run_scheduler import MAX_PLAN_CONCURRENCY, plan_concurrency_ceiling

    try:
        dial = int(os.environ.get(_ORCH_PLAN_CONCURRENCY_ENV, "1") or 1)
    except ValueError:
        dial = 1
    return plan_concurrency_ceiling(
        worker_max_jobs=MAX_PLAN_CONCURRENCY, admin_dial=dial
    )


def _orch_plan_spacing_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get(_ORCH_PLAN_SPACING_ENV, "5") or 5))
    except ValueError:
        return 5.0


def _build_supervisor_plan():
    """The plan the Supervisor WOULD run, built from charter data alone.

    Pure and free: no dispatch, no AgentRun row, no LLM call, no quota touched.
    ``metered`` is resolved through the SAME ``_call_is_metered`` the dispatch
    path uses, so the plan's "this step consumes a paid run" claim cannot drift
    from what actually gets billed.
    """
    from app.services.run_scheduler import build_plan, normalize_charter

    charter = normalize_charter(_EXEC_CLASS_BY_BACKEND)
    metered = {b for b in charter if _call_is_metered(b, {})}
    return build_plan(
        charter,
        concurrency=_orch_plan_concurrency(),
        spacing_seconds=_orch_plan_spacing_seconds(),
        metered=metered,
    )


def _plan_refusal_reason() -> str | None:
    """Why "Run everything" cannot run right now, or ``None``.

    ONE source of truth for the plan view's ``runnable`` flag and the POST's
    503, so the button can never promise what the endpoint refuses.

    Async-only is a PREREQUISITE, not a preference (R-1): the exclusive-slot
    guard for silo-class steps lives on the BackgroundJob claim path, and a plan
    executed inside an HTTP request would also have to finish inside the edge's
    ~100 s ceiling. Without the async path the ``silo`` class would be a comment.
    """
    if not async_generation_enabled():
        return (
            "Running every agent needs background execution, which is currently "
            "switched off on this deployment (AETHER_ASYNC_GENERATION). Without "
            "it the exclusive-slot guard that stops two runs of the same "
            "side-effecting agent would not apply, so the plan is refused "
            "rather than run unguarded."
        )
    return None


def _plan_step_payload(step) -> dict[str, Any]:
    """One plan step as the API renders (and persists) it.

    ``key`` is kept alongside ``backend``: the scheduler and the recorded plan
    are keyed on ``key`` (the executor and the per-step state writer both match
    on it), while ``backend`` is the name the product uses for the same thing.
    Dropping one of them in favour of the other has been the source of exactly
    one silent bug already — the state writer matching a field the stored rows
    did not carry — so both are written, explicitly.
    """
    payload = step.as_dict()
    payload["backend"] = payload["key"]
    payload["cardNames"] = [
        _CATALOG_BY_KEY[c]["name"] for c in step.covers_cards if c in _CATALOG_BY_KEY
    ]
    return payload


@router.get("/orchestration/plan")
def orchestration_plan(current_user: CurrentUser) -> dict[str, Any]:
    """The Supervisor's plan, rendered BEFORE anything runs — and it costs $0.

    ADR-AGI-3 Decision 2: plan visibility ships first because it is the cheapest
    honesty win in the design — the user sees the Supervisor think (order,
    parallel groups, exclusive slots, dedup notes, a rationale per step) before
    a single run is billed. This endpoint dispatches nothing, records no
    AgentRun row and makes no LLM call, which is why ``estimatedCostUsd`` is a
    literal 0.0 rather than a projection nobody could verify.

    Counts are DERIVED from the charter, never hardcoded: 19 dispatches covering
    21 cards, plus the supervisor's own ``orchestration`` card, which the plan
    itself covers.
    """
    plan = _build_supervisor_plan()
    refusal = _plan_refusal_reason()
    return {
        "concurrency": plan.concurrency,
        "concurrencyBasis": (
            f"min(worker max_jobs, {_ORCH_PLAN_CONCURRENCY_ENV}) = "
            f"{plan.concurrency}"
        ),
        "spacingSeconds": plan.spacing_seconds,
        "agentCount": len(plan.steps),
        "cardCount": len(plan.covered_cards),
        "duplicateCardsCollapsed": plan.duplicate_targets_collapsed,
        "meteredStepCount": plan.metered_step_count,
        "estimatedCostUsd": 0.0,
        "groups": [list(g) for g in plan.groups],
        "steps": [_plan_step_payload(s) for s in plan.steps],
        "notes": list(plan.notes),
        "asyncEnabled": async_generation_enabled(),
        "runnable": refusal is None,
        "refusal": refusal,
    }


@router.get("/orchestration/plans/{plan_id}")
def orchestration_plan_record(plan_id: str, current_user: CurrentUser) -> dict[str, Any]:
    """A RECORDED plan and the live state of each of its steps.

    Owner-scoped: another user's plan is a 404, never a confirmation that it
    exists. This is the row the (P1-B) narration reads — a step may only be
    narrated from a persisted transition, so this endpoint is that source.
    """
    from app.repositories.run_plan import RunPlanRepository

    plan = RunPlanRepository().get_for_user(plan_id, current_user["id"])
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run plan not found")
    return plan


def _plan_stale_thresholds() -> tuple[int, int]:
    """(planned_secs, running_secs) after which a live plan is RELEASED.

    Deliberately not a new pair of numbers: a plan is carried by exactly one
    ``BackgroundJob`` on the same queue, under the same worker, so "will anything
    ever claim this?" and "has the worker died mid-run?" are the identical two
    questions :func:`_job_stale_thresholds` already answers — and its second
    window is derived from the worker's own per-job execution ceiling. Inventing
    a separate constant here is how the two drift until the release starts
    failing plans a worker is still legitimately executing, which would both
    fabricate a failure and let the same 19 dispatches run a second time.
    """
    return _job_stale_thresholds()


@router.post("/orchestration/run-everything")
def run_everything(current_user: CurrentUser, response: Response) -> dict[str, Any]:
    """Run every runnable agent once, as ONE server-recorded plan.

    What this is NOT: a loop over the catalog. Cards that share a backend are
    covered by a single dispatch (R-2a — the shipped dedup was frontend-only, so
    a naive server loop would bill ``fitScorer`` three times for one unit of
    work), and every step goes through the SAME
    ``_dispatch`` → ``_record_run`` → ``_execute_reserved_run`` chain as pressing
    Run on one card: same paywall, same atomic reserve-before-the-LLM-call, same
    refund-on-failure, same audit row. No exemption is threaded through here —
    a plan run is a user-triggered run and consumes the user's plan allowance
    exactly like a manual one (R-2b: the sweeps' run-count exemption stays
    sweep-only).

    ONE queue job carries the whole plan rather than 19 competing ones: 19 jobs
    would defeat the ordering, the spacing and the SSE admission cap in a single
    move (R-3).

    And ONE live plan per user (R-1). The silo class already refuses a second
    plan's ``scout``/``submission``/… step at the database, but the 13 non-silo
    backends take no claim — so two rapid clicks or two tabs used to produce two
    plans and up to 26 duplicate METERED dispatches from one user action. That
    is the same "one unit of work asked for twice" the silo class exists for,
    at plan granularity, so it gets the same answer: an honest 409 that names
    the plan already running rather than a second bill.
    """
    user_id = current_user["id"]
    refusal = _plan_refusal_reason()
    if refusal is not None:
        # Honest 503 BEFORE any row is written: a refused plan leaves no trace
        # that could later be mistaken for an attempt.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, refusal)
    # Paywall FIRST, exactly like every other enqueue seam. The composite is
    # always walled: ``_ORCH_PLAN_AGENT_KEY`` is not a system-run-exempt agent,
    # so a valid system secret cannot buy a free plan.
    _require_active_subscription(
        user_id, agent_name=_ORCH_PLAN_AGENT_KEY, system_run=False
    )

    from app.repositories.run_plan import RunPlanRepository

    plan = _build_supervisor_plan()
    plans = RunPlanRepository()
    planned_stale, running_stale = _plan_stale_thresholds()
    plan_id, admitted = plans.create_admitted(
        user_id,
        steps=[_plan_step_payload(s) for s in plan.steps],
        concurrency=plan.concurrency,
        spacing_seconds=plan.spacing_seconds,
        planned_stale_seconds=planned_stale,
        running_stale_seconds=running_stale,
        initiator="user",
    )
    if not admitted:
        # Refused BEFORE the queue job, so the second click costs nothing and
        # leaves nothing: no plan row, no BackgroundJob, no dispatch. The id of
        # the LIVE plan goes back so the caller can open the run it already has
        # instead of being told only "no" — the plan is already narratable at
        # GET /agents/orchestration/plans/{id}.
        live = plans.get_for_user(plan_id, user_id) or {}
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "error": "plan_already_running",
                "message": (
                    "A run plan is already in flight for this account — running "
                    "every agent a second time would repeat the same work and "
                    "bill for it twice. Open the plan that is running, or wait "
                    "for it to finish."
                ),
                "planId": plan_id,
                "planStatus": live.get("status"),
            },
        )
    repo = BackgroundJobRepository()
    job_id = repo.create(
        user_id,
        _ORCH_PLAN_AGENT_KEY,
        run_id=None,
        params={"runPlanId": plan_id},
        quota_reserved=False,
    )
    try:
        arq_job_id = _enqueue_to_arq(job_id)
    except Exception as exc:  # noqa: BLE001
        repo.mark_failed(job_id, "generation queue temporarily unavailable")
        plans.finish(
            plan_id,
            "failed",
            summary={"reason": "generation queue temporarily unavailable"},
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "generation queue temporarily unavailable",
        ) from exc
    repo.set_arq_job_id(job_id, arq_job_id)
    response.status_code = status.HTTP_202_ACCEPTED
    return {
        "job_id": job_id,
        "planId": plan_id,
        "status": "enqueued",
        "stepCount": len(plan.steps),
        "cardCount": len(plan.covered_cards),
        "concurrency": plan.concurrency,
    }


def _plan_halting_reason(exc: BaseException) -> str | None:
    """Which failures end the whole plan rather than just their own step (R-4).

    A plan that presses on after a quota/spend-cap refusal collects N identical
    429s while the first one was the answer, so a plan-wide stop is the honest
    response — and the summary records exactly where it stopped and what was
    never attempted. A 402 (no active subscription) is the same class of answer:
    it cannot become true again inside this plan.
    """
    code = getattr(exc, "status_code", None)
    if code == status.HTTP_429_TOO_MANY_REQUESTS:
        return (
            "the account's run quota or spend cap was reached, so the remaining "
            "steps were not attempted"
        )
    if code == status.HTTP_402_PAYMENT_REQUIRED:
        return "an active subscription is required, so the plan stopped"
    return None


def execute_run_plan(user_id: str, plan_id: str) -> dict[str, Any]:
    """Drive a recorded plan to a terminal state. Called by the ARQ worker.

    The scheduler package owns the LOOP; this function owns the seams it cannot
    have (dispatch, the database admission claim, state persistence), so no
    agent name and no billing rule leaks into ``run_scheduler``.

    Admission (R-1): a silo-class step claims the SAME
    ``(userId, agentKey)`` in-flight slot the async single-agent path uses — a
    partial unique index in Postgres, not a disabled button in one browser tab
    — so a plan cannot race the discovery sweep, another tab, or itself. A lost
    claim is an honest ``refused``, never a silently duplicated side effect.
    """
    from app.repositories.run_plan import RunPlanRepository
    from app.services.run_scheduler.executor import execute_plan

    plans = RunPlanRepository()
    row = plans.get(plan_id)
    if row is None or row["userId"] != user_id:
        raise ValueError(f"run plan {plan_id} not found for this user")
    if not plans.mark_running(plan_id):
        # Already running or already terminal — a re-delivered queue message
        # must never restart a plan or double-dispatch its steps.
        logger.info("run plan %s is not in the 'planned' state; skipping", plan_id)
        return {"status": row["status"], "planId": plan_id, "steps": [], "notAttempted": []}

    steps = list(row["steps"] or [])

    repo = BackgroundJobRepository()

    def _claim(backend: str) -> tuple[Any, bool]:
        """Take the exclusive in-flight slot for a silo-class step."""
        job_id, created = repo.create_singleton(
            user_id, backend, params={"runPlanId": plan_id}, quota_reserved=False
        )
        if not created:
            return None, False
        # Move it to ``processing`` immediately: the ``enqueued`` staleness
        # window is far shorter than a long discovery pass, and a watchdog that
        # failed a live step would fabricate a failure on a run still executing.
        repo.mark_processing(job_id)
        return job_id, True

    def _release(token: Any, backend: str, ok: bool) -> None:
        if not token:
            return
        try:
            if ok:
                repo.mark_completed(token, {"runPlanId": plan_id, "backend": backend})
            else:
                repo.mark_failed(
                    token, f"{backend} step did not complete", refunded=False
                )
        except Exception:  # noqa: BLE001 — releasing a slot must never fail a plan
            logger.warning(
                "run plan %s could not release the %s slot", plan_id, backend,
                exc_info=True,
            )

    summary = execute_plan(
        steps=steps,
        dispatch=lambda backend, params: _dispatch(user_id, backend, dict(params)),
        claim=_claim,
        release=_release,
        on_state=lambda key, state, detail: plans.record_step_state(
            plan_id, key, state, dict(detail)
        ),
        halting_reason=_plan_halting_reason,
        spacing_seconds=float(row["spacingSeconds"] or 0.0),
    )
    plans.finish(
        plan_id,
        summary["status"],
        summary=summary,
        halted_at_step=summary["haltedAtStep"],
        halt_reason=summary["haltReason"],
    )
    summary["planId"] = plan_id
    return summary


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
    recent = AgentRunRepository().recent_runs_by_agent(user_id)
    agents: list[dict[str, Any]] = []
    active = paused = error = planned = 0
    for entry in AGENT_CATALOG:
        key = entry["key"]
        c = cfg.get(key, {})
        enabled = bool(c.get("enabled", True))
        backend = entry["backend"]
        runs = recent.get(backend) if backend else None
        run = runs[0] if runs else None
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
                # ML-agents-err-001: windowed, transient-tolerant health via the
                # shared classifier (OBS-B: the SAME source of truth list_agents
                # uses, so the two endpoints never disagree). A chronically
                # broken agent (last 3 runs ALL failed) or a genuine
                # non-transient error surfaces as "error"; a lone transient
                # upstream blip on an otherwise-healthy agent does not paint the
                # card red.
                if _latest_failure_is_hard(runs):
                    state = "error"
                    error += 1
                else:
                    state = "active"
                    active += 1
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
                "runnable": backend in _RUNNABLE_BACKENDS,
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
    # AUD-AGENT-4: ``engines`` and ``cards`` are the two honest numbers (see
    # ``honest_catalog_counts``). ``total`` is retained on the wire because it
    # is what older clients read, and it has always been the CARD total — never
    # an agent count. Clients must render the pair, not ``total`` alone.
    scale = honest_catalog_counts()
    return {
        "agents": agents,
        "counts": {
            "total": len(agents),
            "engines": scale["engines"],
            "cards": scale["cards"],
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
#: The wave-4A report agents belong here: they aggregate the user's OWN persisted
#: data and never call a model, so a per-agent model pick would be a no-op.
#: ``companyResearch`` is deliberately NOT here — its opt-in narrative really
#: does run on the picked model.
_DETERMINISTIC_BACKENDS = frozenset(
    {
        "scout", "fitScorer", "matcher", "supervisor",
        "compliance", "salaryIntelligence", "marketTrends", "learningFeedback",
        # wave-4C: the notification digest is a deterministic composition of the
        # user's own rows — no model is ever called, so a per-agent model pick
        # would be a no-op and the picker is honestly locked.
        "notification",
        # GM2-AGENTS-001: the submission gate + write is a deterministic DB
        # operation (the same one POST /jobs/{id}/apply performs) — no model
        # is ever called, so a per-agent model pick would be a no-op here too.
        "submission",
    }
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


def _validate_agent_model(model: str, user_id: str, agent_key: str | None = None) -> None:
    """Reject a ``model`` id that is not offered by the catalog of the provider
    it would bill through (ML-catalog-004 / §3.1.3, MODEL-SUB-QUOTA clause 4).

    Accepts the ``deterministic`` sentinel and any id present in that provider's
    catalog. Two catalogs, two different kinds of list:

    * OPENROUTER — a genuine LIVE, exhaustive list. When it cannot be consulted
      right now (cold cache — validation never opens a network connection,
      ``allow_fetch`` is False) the id is accepted rather than rejected on a
      transient gap; a genuinely wrong id then fails honestly at call time
      (matching the ``_user_model_override`` "no silent substitution" contract).
    * ANTHROPIC — the app's OWN curated catalog of the Claude models it can
      route (:data:`llm_client._STATIC_MODEL_CATALOG`). MODEL-SUB-QUOTA makes
      this list load-bearing: every Claude pin is now served by the operator's
      subscription through the native Messages API, and an id that catalog does
      not carry is one the app cannot serve. Rejecting it 422 is the honest
      answer — the alternative is a pin that dies at run time, and quietly
      swapping in a NEARBY Claude model would be exactly the silent
      substitution ADR-ML-3 forbids. (This is a departure from §3.1.3's
      "never reject on the static shortlist", which was written when a bare
      claude id was a rare hand-typed thing rather than the system default.)

    An agent's OWN seeded ``recommended`` value is accepted unconditionally. It
    is not a user choice — it is what the app itself wrote into the catalog row
    and renders when nothing is pinned, and ``_user_model_override`` deliberately
    treats a stored value equal to it as "no choice made" (the phantom seed), so
    it never reaches a model. 422-ing a client that echoes back the value we
    showed it would be rejecting our own default.

    Never applies a hardcoded model allowlist beyond those two catalogs.
    """
    m = (model or "").strip()
    if not m or m in _MODEL_VALIDATION_SENTINELS:
        return
    if agent_key and m == (_CATALOG_BY_KEY.get(agent_key, {}).get("recommended") or ""):
        return
    from app.services.llm_client import (
        ModelCatalogError,
        list_provider_models,
        resolve_provider,
    )

    provider = resolve_provider(m)
    if provider == "anthropic":
        catalog = list_provider_models("anthropic", user_id, allow_fetch=False)
        if any((row.get("id") == m) for row in catalog):
            return
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"model '{m}' is not one of the Claude models this app can serve on "
            "your Anthropic subscription — choose one from the Anthropic catalog "
            f"({', '.join(str(r.get('id')) for r in catalog)}).",
        )
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

    # MODEL-SUB-QUOTA clause 4: normalize BEFORE validating and persisting, so a
    # Claude pick is stored in the spelling that routes to the operator's
    # Anthropic subscription. ``anthropic/claude-opus-4-8`` -> ``claude-opus-4-8``
    # is the same model on its own vendor's API, not a substitution; every other
    # id (including a non-Claude ``anthropic/…``) is untouched.
    model_in = (
        normalize_model_id(body.model) if body.model is not None else None
    )
    # Validate a chosen model against its provider's catalog (ML-catalog-004): an
    # id no provider offers is rejected 422 rather than silently persisted and
    # then failing opaquely at run time. Only runs when the caller is actually
    # setting `model` (a partial update that omits it must not be gated).
    if model_in is not None:
        _validate_agent_model(model_in, user_id, agent_key)

    # MODEL-SUB-QUOTA clause 5: `provider` is a DERIVED disclosure field, not a
    # user choice — `resolve_provider(model)` alone decides who serves and bills
    # a run. Stored, though, it is what the Agents UI shows the user (the FE
    # prefers the persisted value over its own derivation), so a client that
    # mis-derived it could persist "this Claude run bills OpenRouter" and have
    # the app repeat that forever about runs the subscription actually funds.
    # Refused HONESTLY (422) rather than silently rewritten to the truth, so the
    # caller learns its derivation is wrong instead of being quietly corrected.
    # Claude-only: every other model keeps storing whatever it declares.
    if body.provider is not None:
        declared = str(body.provider).strip().lower()
        effective_model = (
            model_in
            if model_in is not None
            else ((_config_map(user_id).get(agent_key) or {}).get("model")
                  or entry["recommended"])
        )
        if declared and is_claude_model(effective_model):
            expected = resolve_provider(effective_model)
            if declared != expected:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"agent '{agent_key}' runs the Claude model "
                    f"'{effective_model}', which is served by the operator's "
                    f"Anthropic subscription — its provider is '{expected}', not "
                    f"'{declared}'. A Claude run is never billed to OpenRouter or "
                    "to a metered API key, so that provider was not stored.",
                )

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
                if model_in is None else model_in
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
    # ML-agents-cred-005: only applies when a credential ACTUALLY exists
    # (source != "none") — once the credential has been deleted, an orphaned
    # per-user needs_reauth token row is meaningless and must not demote an
    # already-honest "unconfigured" provider to a leftover "warning" badge.
    needs_reauth = (
        _anthropic_oauth_needs_reauth(user_id)
        if provider_id == "anthropic" and source != "none"
        else False
    )
    if needs_reauth:
        status = "warning"
        detail = (
            "Anthropic subscription session expired — reconnect required "
            "(Connect with Anthropic, or Renew)."
        )
    model = override.get("model") or env_model
    # ML-U1X-a: a provider whose catalog is a curated STATIC list (anthropic —
    # no open /models endpoint, ADR-ML-4) offers exactly that list once a real
    # credential exists for this scope, whether it came from the DB vault or the
    # legacy env path. ``env_models`` never knew about the DB row at all, which
    # is why a connected+verified deployment credential still rendered an empty
    # <select>. ``source == "none"`` (no credential anywhere) keeps the honest
    # empty list — a catalog is never offered for a provider nobody can call
    # (D-0020).
    models = env_models
    static_ids = _static_catalog_model_ids(provider_id)
    if static_ids:
        models = static_ids if source != "none" else []
    return {
        "id": provider_id,
        "label": seed["name"],
        "name": seed["name"],
        "auth": seed["auth"],
        "icon": seed["icon"],
        "color": seed["color"],
        "models": models,
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
def list_providers(current_user: AdminUser) -> list[dict[str, Any]]:
    """The AI providers with connection state derived from real credentials.

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ). This reads the
    DEPLOYMENT-WIDE ``ProviderCredential`` store plus the server environment —
    one shared store with no user id anywhere in it — so its rows (source,
    last-4 ``secretHint``, ``lastVerifiedAt``) are the operator's credential
    state, not the caller's. It is gated by the SAME ``AdminUser`` dependency
    ``/api/admin/*`` uses. A customer's own keys live at
    ``GET /agents/user/providers`` + ``GET /agents/user/providers/catalog``.

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
    provider: str, body: ProviderCredentialBody, current_user: AdminUser
) -> dict[str, Any]:
    """Store (encrypt) a provider credential entirely in-UI; return masked row.

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ):
    ``ProviderCredentialRepository`` takes no user id — this WRITES the single
    deployment-wide credential every run bills against. The ``AdminUser``
    dependency resolves before the body of this function, so an ungated caller
    gets 403 BEFORE the provider-name check below and never learns which
    provider ids are configured. Customers store their own keys at
    ``PUT /agents/user/providers/{provider}/credential``.

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
    provider: str, current_user: AdminUser
) -> dict[str, Any]:
    """Remove a stored credential; status falls back to the env source (ADR-PC-4).

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): this DELETES the
    deployment-wide credential for every user at once. The live probe that
    found the hole hit exactly this route — an ungated DELETE of an unknown
    provider answered 404 (name check first). ``AdminUser`` now resolves first,
    so the answer is 403.
    """
    if provider not in _CREDENTIAL_PROVIDERS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Provider '{provider}' does not support stored credentials.",
        )
    ProviderCredentialRepository().delete(provider)
    return _provider_status_object(provider, current_user["id"])


@router.post("/providers/{provider}/verify")
def verify_provider(provider: str, current_user: AdminUser) -> dict[str, Any]:
    """Perform a REAL provider round-trip and record the honest result (REQ-PC-7).

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): this spends the
    OPERATOR's credential on a live upstream call and mutates the shared row's
    ``lastVerifyStatus``, so an ungated caller could both burn the operator's
    money and probe whether their credential is still valid. Customers verify
    their own key at ``POST /agents/user/providers/{provider}/verify``.

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


@router.get("/providers/openrouter/credits")
def openrouter_credits_endpoint(current_user: AdminUser) -> dict[str, Any]:
    """Real remaining OpenRouter credit for the DEPLOYMENT account (ML-U1X-a).

    OPERATOR-ONLY, the same ``AdminUser`` gate as the rest of the
    deployment-wide provider family (F-01): this is the operator's billing
    balance, not the caller's. The figure is OpenRouter's own ``GET /credits``
    reading, cached briefly upstream. When it cannot be read (no credential,
    unreachable upstream) the answer is an explicit ``available: false``
    envelope — never a fabricated balance, never an opaque 500 — so the UI can
    say "unavailable" honestly instead of implying healthy credit.
    """
    from app.services import llm_client

    try:
        credits = llm_client.get_openrouter_credits(force_refresh=False)
    except llm_client.CreditsUnavailableError as exc:
        return {
            "available": False,
            "remaining": None,
            "total": None,
            "asOf": None,
            "detail": str(exc),
        }
    return {
        "available": True,
        "remaining": credits.get("remaining"),
        "total": credits.get("total"),
        "asOf": credits.get("asOf"),
    }


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


def _build_user_provider_entry(
    seed: dict[str, Any], cred: dict[str, Any] | None, override: dict[str, Any]
) -> dict[str, Any]:
    """One provider's PER-USER status, derived ONLY from this user's own rows.

    Deliberately does NOT call ``_provider_env_state`` or read
    ``ProviderCredential``: nothing about the operator's deployment-wide
    credential (its existence, source, last-4 hint or verify history) may reach
    a customer (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ). ``status`` is honest —
    a stored key whose last real verify came back ``failed`` is demoted to
    ``warning``, exactly as the deployment-wide builder does, and a provider
    with no key of the user's own is ``unconfigured``. Shape matches the
    frontend ``ProviderSchema`` so the same panel component renders both views.
    """
    if cred:
        status_token = "warning" if cred.get("lastVerifyStatus") == "failed" else "connected"
        source = "database"
        detail = f"Your own key, stored in the encrypted vault ({cred.get('secretHint')})"
        if cred.get("lastVerifyStatus"):
            detail += f" · last test: {cred['lastVerifyStatus']}"
    else:
        status_token = "unconfigured"
        source = "none"
        detail = f"You have not added your own {seed['name']} key."
    # ML-U1X-a: same static-catalog rule as the deployment-wide builder, scoped
    # to THIS user's own credential (F-01): a customer who added their own
    # verified Anthropic key sees the real catalog; a customer with no key of
    # their own sees an honest empty list — never the operator's state, never a
    # fabricated catalog (D-0020).
    models = seed["models"]
    static_ids = _static_catalog_model_ids(seed["id"])
    if static_ids:
        models = static_ids if cred else []
    return {
        "id": seed["id"],
        "label": seed["name"],
        "name": seed["name"],
        "auth": seed["auth"],
        "icon": seed["icon"],
        "color": seed["color"],
        "models": models,
        "status": status_token,
        "source": source,
        "authMode": cred.get("authMode") if cred else None,
        "secretHint": cred.get("secretHint") if cred else None,
        "baseUrl": cred.get("baseUrl") if cred else None,
        "lastVerifiedAt": _iso_or_none(cred.get("lastVerifiedAt")) if cred else None,
        "lastVerifyStatus": cred.get("lastVerifyStatus") if cred else None,
        "needsReauth": False,
        # The user's OWN provider-level default model (the ModelPicker's row);
        # "" means "no override — agents run the app default".
        "model": override.get("model") or "",
        "detail": detail,
    }


@router.get("/user/providers/catalog")
def list_user_provider_catalog(current_user: CurrentUser) -> list[dict[str, Any]]:
    """The provider panel an ORDINARY customer sees: their own keys only.

    Added for F-01 (ADR-F01-PROVIDER-CREDENTIAL-AUTHZ). ``GET /agents/providers``
    is now operator-only because it exposes the deployment-wide credential
    store; this is the per-user replacement customers get instead. It combines
    static provider identity (``PROVIDER_SEED`` — branding + the static model
    list, no credential material) with THIS user's own
    ``UserProviderCredential`` rows and THIS user's own ``AgentProvider``
    default-model preference. It reads no deployment credential and no provider
    env var, so it cannot leak the operator's state.

    Scoped to ``_CREDENTIAL_PROVIDERS`` — the providers that actually accept a
    stored user credential. ``abacus`` is excluded because a user cannot supply
    one, and offering a card for it would be a dead control.
    """
    user_id = current_user["id"]
    creds = {
        row["provider"]: row
        for row in UserProviderCredentialRepository().list_masked(user_id)
    }
    overrides = _user_provider_overrides(user_id)
    return [
        _build_user_provider_entry(
            seed, creds.get(seed["id"]), overrides.get(seed["id"], {})
        )
        for seed in PROVIDER_SEED
        if seed["id"] in _CREDENTIAL_PROVIDERS
    ]


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
    # Do NOT sync CLAUDE_CODE_OAUTH_TOKEN here. That env var is the operator's
    # restart-survival copy of the DEPLOYMENT-WIDE credential (GAP-P7-DEF-A
    # §3.3) and is written only by ``PUT /agents/providers/{id}/credential``
    # and ``anthropic_oauth.persist_tokens``. Syncing a customer's token into
    # it would re-bill every bare ``claude-*`` run — including cron — to this
    # user, which is the F-01 failure mode the per-user store exists to prevent.
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


def _begin_anthropic_oauth(user_id: str) -> str:
    """Mint a PKCE pair + single-use state for ``user_id``; return the authorize URL.

    Shared step 1 of BOTH Connect-with-Anthropic scopes (the operator flow
    below and the per-user mint at ``/user/providers/anthropic/oauth/start``).
    The two differ only in what step 2 does with the resulting token, never in
    how the authorization is started, so this is deliberately one implementation.

    The verifier is persisted server-side and NEVER leaves the process. Fails
    closed with 503 when the vault key is absent: without it the credential
    this flow leads to cannot be stored encrypted, so starting the flow would
    only strand the user at its final step.
    """
    from app.services import anthropic_oauth

    _oauth_vault_ready_or_503()
    verifier, challenge = anthropic_oauth.generate_pkce()
    state = anthropic_oauth.generate_state()
    AnthropicOAuthStateRepository().create(state, user_id, verifier)
    return anthropic_oauth.build_authorize_url(challenge, state)


@router.post("/providers/anthropic/oauth/start")
def anthropic_oauth_start(current_user: AdminUser) -> dict[str, Any]:
    """Begin the Connect-with-Anthropic flow: return the authorize URL.

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): this is step 1 of
    a flow whose step 2 (``/exchange``) writes the DEPLOYMENT-WIDE
    ``ProviderCredential('anthropic')`` row — see
    ``anthropic_oauth.persist_tokens``. It is the same shared store the manual
    paste writes, so the whole flow is gated as one family. Customers begin the
    per-user mint at ``POST /agents/user/providers/anthropic/oauth/start``.
    """
    return {"authorizeUrl": _begin_anthropic_oauth(current_user["id"])}


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


def _mint_anthropic_token(pasted_code: str, user_id: str) -> dict[str, Any]:
    """Redeem a pasted ``code#state`` for a token set. PERSISTS NOTHING.

    Shared step 2 of BOTH Connect-with-Anthropic scopes: validation, CSRF/state
    binding and upstream error mapping are identical whether the caller is the
    operator (who then persists deployment-wide) or a customer (who receives
    the token to store against their OWN row). Only what happens to the
    returned dict differs, so only that lives in the two routes.

    Returns the normalised ``{access_token, refresh_token, expires_at, scope}``.

    Honest failures — never a fake success, never another user's session:
      * 422 malformed paste, or an upstream CODE-REJECTION (a real HTTP
        response reached us with a non-2xx status: a stale, mistyped or
        replayed code). ML-adv-002: this is a 4xx rather than a 502 because an
        intermediary may replace a 502 body with a generic page and hide the
        actionable detail; 4xx bodies pass through untouched.
      * 400 unknown / expired / already-used state.
      * 403 the state was started by a different user.
      * 502 a genuine network/gateway failure where no response arrived at all,
        including an unexpected 2xx shape — the defensive parse in
        ``anthropic_oauth._normalize_token_response`` never fakes success.
    """
    from app.services import anthropic_oauth

    code, state = _parse_pasted_oauth_code(pasted_code)
    _oauth_vault_ready_or_503()
    row = AnthropicOAuthStateRepository().consume(state)
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Authorization state is unknown, expired, or already used — restart "
            "Connect with Anthropic.",
        )
    if row.get("userId") != user_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This authorization was started by a different user.",
        )
    try:
        return anthropic_oauth.exchange_code(code, row["codeVerifier"], state)
    except anthropic_oauth.OAuthExchangeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.upstream_status is not None
            else status.HTTP_502_BAD_GATEWAY,
            "Anthropic rejected the authorization code — restart Connect with "
            "Anthropic.",
        ) from exc


@router.post("/providers/anthropic/oauth/exchange")
def anthropic_oauth_exchange(
    body: AnthropicOAuthExchangeBody, current_user: AdminUser
) -> dict[str, Any]:
    """Exchange the pasted one-time ``code#state`` for a subscription token.

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): on success this
    OVERWRITES the deployment-wide ``ProviderCredential('anthropic')`` row, so
    before the gate any authenticated customer could have replaced the
    operator's subscription token with their own — silently re-billing every
    bare ``claude-*`` run on the deployment (including cron) to whoever
    connected last. The per-user ``AnthropicOAuthState`` owner check below is a
    CSRF/state binding, not an authorization gate.

    Validation, state binding and upstream error mapping live in the shared
    ``_mint_anthropic_token`` (see its docstring for the full status contract);
    the line after it is what makes this route the OPERATOR's. On success the
    access token is stored deployment-wide (oauth_token) and the refresh
    material per-user; the masked provider status object is returned (no token).
    """
    from app.services import anthropic_oauth

    tok = _mint_anthropic_token(body.pastedCode, current_user["id"])
    try:
        anthropic_oauth.persist_tokens(current_user["id"], tok)
    except credential_vault.CredentialVaultError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _provider_status_object("anthropic", current_user["id"])


@router.post("/providers/anthropic/oauth/refresh")
def anthropic_oauth_refresh(current_user: AdminUser) -> dict[str, Any]:
    """Force-refresh the stored subscription token (the "Renew now" action).

    OPERATOR-ONLY (F-01, ADR-F01-PROVIDER-CREDENTIAL-AUTHZ): a successful
    refresh rotates the deployment-wide ``ProviderCredential('anthropic')`` row
    via ``persist_tokens``, and a failure marks the session ``needs_reauth`` —
    both are deployment-wide effects.

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


# ---------------------------------------------------------------------------
# Per-user "Connect with Anthropic" subscription-token MINT (UPO-1).
#
# The operator routes above are admin-gated because their exchange overwrites
# the deployment-wide ``ProviderCredential('anthropic')`` row every bare
# ``claude-*`` run bills against (F-01). That left an ordinary customer with no
# in-app way to obtain a Claude subscription token at all — the per-user dialog
# offered only a manual paste of a token the customer had to mint themselves
# with ``claude setup-token`` on their own machine.
#
# These two routes are the per-user twin. They reuse the SAME authorize and
# redeem helpers, and differ in exactly one respect: the exchange PERSISTS
# NOTHING. It returns the freshly minted token to the customer who just
# authenticated, so the dialog can populate its OAuth-token field; the
# customer then clicks Save, which stores it through the existing
# ``PUT /agents/user/providers/{provider}/credential`` path. Keeping Save as
# the single write path is what makes a non-admin route safe here — there is
# no deployment-wide side effect to escalate into.
# ---------------------------------------------------------------------------


@router.post("/user/providers/anthropic/oauth/start")
def user_anthropic_oauth_start(current_user: CurrentUser) -> dict[str, Any]:
    """Begin the customer's own Connect-with-Anthropic flow.

    Open to any AUTHENTICATED user: nothing this route touches is shared. It
    persists only a short-lived PKCE state row bound to the caller, and returns
    Anthropic's own authorize URL for the caller to approve with their OWN
    Claude Pro/Max account. 503 when the vault key is absent (fail closed —
    see ``_begin_anthropic_oauth``).
    """
    return {"authorizeUrl": _begin_anthropic_oauth(current_user["id"])}


@router.post("/user/providers/anthropic/oauth/exchange")
def user_anthropic_oauth_exchange(
    body: AnthropicOAuthExchangeBody, response: Response, current_user: CurrentUser
) -> dict[str, Any]:
    """Redeem the pasted ``code#state`` and RETURN the minted token to its owner.

    This is the only response in the application that carries a live
    credential, so it is deliberately narrow:

    * The token returned belongs to the caller — it was minted seconds earlier
      from an authorization the caller personally approved on Anthropic's own
      pages, against their own subscription. It is the same value they would
      otherwise paste in by hand from ``claude setup-token``, so this widens no
      trust boundary; it removes a manual step.
    * ``Cache-Control: no-store`` so no browser, proxy or bfcache retains it.
    * Nothing is written: not the deployment-wide ``ProviderCredential`` row
      (that would re-bill the whole deployment to this customer), and not the
      ``AnthropicOAuthToken`` refresh store (that would make the operator's
      auto-refresh hook rotate a session this flow does not own). Save is the
      single write path.
    * The refresh token is deliberately NOT returned: it is refresh material
      for the operator flow and has no use in a browser.

    Status contract: see ``_mint_anthropic_token``.
    """
    tok = _mint_anthropic_token(body.pastedCode, current_user["id"])
    access = tok["access_token"]
    expires_at = tok.get("expires_at")
    response.headers["Cache-Control"] = "no-store"
    return {
        "token": access,
        "authMode": "oauth_token",
        "secretHint": credential_vault.secret_hint(access),
        "expiresAt": _iso_or_none(expires_at),
        "scope": tok.get("scope"),
    }


@router.get("/stats")
def agent_stats(current_user: CurrentUser) -> dict[str, Any]:
    """Real aggregate stats derived from AgentRun history (no hardcoded values)."""
    runs = AgentRunRepository().list_recent(current_user["id"], limit=200)
    all_runs = runs
    # STORM-1: a paused-episode row (board_sweep._record_paused_skip_episode)
    # records that autopilot SKIPPED work while the user had an agent stopped.
    # No model was asked anything, so it is not a task, not a success and not a
    # failure — it belongs in NEITHER side of the ratio. That is the one way it
    # differs from the letterless cover degrade below, which WAS a real attempt
    # and so stays in the denominator.
    def _is_skip_row(run: dict[str, Any]) -> bool:
        out = run.get("output") or {}
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except (ValueError, TypeError):
                return False
        return isinstance(out, dict) and out.get("skipped") is True
    skipped = sum(1 for r in all_runs if _is_skip_row(r))
    runs = [r for r in all_runs if not _is_skip_row(r)]
    total = len(runs)
    completed = 0
    degraded = 0
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
        if r["status"] == "completed":
            completed += 1
            # QA3-F-03: a letterless coverLetter degrade (guard rejection / LLM
            # unavailable on the first draft) is recorded as status='completed'
            # (GAP-P4-002 — the guard working is not a failure), but it is NOT a
            # successful outcome for the "Success Rate" stat — count it
            # distinctly instead of silently inflating the success numerator.
            if r["agentName"] == "coverLetter" and out.get("coverLetterUnavailable") is True:
                degraded += 1
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
    success_rate = round((completed - degraded) / total * 100, 1) if total else 100.0
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
        "degradedCount": degraded,
        # STORM-1: runs autopilot deliberately did NOT perform because the user
        # had the agent stopped. Reported so the number is visible rather than
        # silently dropped — it is excluded from every ratio above.
        "skippedCount": skipped,
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
    # R-1 re-fix (ML-U1X-refix round 2): mirror the run-costing tail's
    # zero-cost gate (agents.py's ``_record_run``, "F-1 re-fix" comment
    # above). ``llm_model is not None`` alone is no longer sufficient — a
    # ROLE backend (``supervisor``/Orchestrator, ``_ROLE_MODEL_BACKENDS``)
    # now returns a real display id from ``_model_for_agent`` even though it
    # makes NO LLM call today (see ``_LLM_TIER_BY_BACKEND``'s module
    # comment). Only a backend actually METERED — present in
    # ``_LLM_TIER_BY_BACKEND`` — gets a derived spend/token estimate; every
    # other backend keeps its role/display id in ``model`` but leaves
    # est_cost/est_tokens genuinely null, exactly like the deterministic
    # agents this docstring already promises never fabricate spend.
    if llm_model is not None and backend in _LLM_TIER_BY_BACKEND:
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
    name: str, current_user: CurrentUser, response: Response,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Trigger any registered agent by name with free-form params (P2-S08).

    A fabrication/structural guard rejection gets the SAME honest 422 the
    dedicated cover-letter route returns (F-1 — see
    :func:`_guard_rejection_http_error`); it used to escape as an unhandled 500 +
    traceback. This route is not a back door: the Agents-screen Run button
    reaches every agent WITHOUT a dedicated route through here
    (``runAgent(AGENT_ROUTE[backend] ?? backend)``,
    apps/web/src/app/dashboard/agents/page.tsx), so the bare 500 was
    customer-reachable, not merely a scripting inconvenience.

    D.524: this was the LAST fully-synchronous run route — probe 5
    (``uat/reports/evidence/orch-exec/MON-RESIDUALS-EVIDENCE-2026-08-14.md``)
    measured it carrying ~24% of all ``/run`` traffic (every agent with no
    dedicated route, plus any dedicated agent's alternate/camelCase alias),
    the same Cloudflare-524 exposure shape MON-020 already fixed for
    ``scout`` and GAP-P7-ASYNC-001 already fixed for the dedicated
    ``tailor``/``cover-letter`` routes. When ``AETHER_ASYNC_GENERATION`` is
    ON, this mirrors those dedicated routes EXACTLY: the SAME
    ``_enqueue_single_agent`` background-job machinery, the SAME
    ``202 {"job_id", "status": "enqueued"}`` envelope — WITHOUT
    ``singleton=True`` (binding orchestrator ruling OQ-2: unlike ``scout``,
    the generic route makes no single-run-per-agent claim, so concurrent runs
    of the same agent are all accepted, exactly like tailor/coverLetter
    today). When OFF (the default), behaviour is BYTE-IDENTICAL to before
    this change.

    The agent name is resolved through the SAME pure ``_agent_callable`` seam
    on both paths, so an unknown agent name or a missing required param (e.g.
    ``coverLetter``'s ``job_id``) gets the identical honest 404/422 whichever
    path is taken — resolved BEFORE anything is persisted, reserved, or
    queued, never discovered only after an async job was already accepted.
    """
    user_id = current_user["id"]
    params = params or {}
    if async_generation_enabled():
        # Validate/resolve FIRST (same seam _dispatch uses internally) so an
        # unknown agent (HTTPException 404, raised directly by
        # _agent_callable) or a missing required param (e.g. HTTPException
        # 422 from _require_job_id) is refused before anything is enqueued,
        # reserved or persisted — identical to the synchronous path below.
        canonical, _ = _agent_callable(user_id, name, params)
        job_id = _enqueue_single_agent(user_id, canonical, params)
        response.status_code = status.HTTP_202_ACCEPTED
        return {"job_id": job_id, "status": "enqueued"}
    try:
        return _dispatch(user_id, name, params)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (FabricationError, StructuralError) as exc:
        # ``name`` is already a REGISTERED alias here — _agent_callable raises its
        # own 404 for anything else — so the subject echoes a known agent's
        # display name, never arbitrary caller input.
        raise _guard_rejection_http_error(_display_for_backend(name), exc) from exc
