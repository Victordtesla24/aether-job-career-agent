"""Record-replay LLM client for the Python API (P2-S05, hardened post-review).

Modes (``AETHER_LLM_MODE`` env var):
- ``replay`` (default): read a canned response from the fixture directory —
  no network I/O. This is what CI/tests use.
- ``record``: call the live endpoint and persist the response as a fixture.
- ``live``: call the live endpoint (OpenRouter-compatible) directly.
- ``auto``: try the live endpoint first (recording the fixture on success);
  on ANY live failure (404 stale model id, 429 rate limit, 5xx, network,
  budget/timeout, malformed JSON), retry once with the fallback model, then
  raise an honest :class:`LLMUnavailableError` (mapped to HTTP 503 by the
  routers — never an unhandled 500). It NEVER serves a recorded fixture as if
  it were live output (GAP-P6-AUTH-002): a fixture recorded before a fix would
  otherwise be delivered to a paying user as their "tailored" résumé with no
  signal it is stale, canned content. Fixtures are served ONLY in ``replay``
  mode. Recording a fixture on live SUCCESS in ``auto`` mode is harmless and
  retained.

Fixtures live under ``AETHER_LLM_FIXTURE_DIR`` (defaults to
``apps/api/tests/fixtures/llm``) as ``<prompt_name>/<key>.json`` with shape
``{"content": "..."}``. ``key`` defaults to ``default``.

Model ids are configured via ``AETHER_MODEL_<TIER>`` env vars because
OpenRouter free-tier model ids are volatile (see ADR D-0014).
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

#: Last-resort model retried once when the primary model 404s / 429s (D-0014).
FALLBACK_MODEL = "openai/gpt-oss-20b:free"


def get_fallback_model() -> str:
    """Fallback model id, overridable so non-OpenRouter providers can set one."""
    return os.environ.get("AETHER_MODEL_FALLBACK", FALLBACK_MODEL)


def _extra_headers() -> dict[str, str]:
    """Provider-specific extra HTTP headers from ``AETHER_LLM_EXTRA_HEADERS``.

    Some OpenAI-compatible endpoints require additional headers on every
    request — e.g. Anthropic's compat endpoint needs
    ``anthropic-version: 2023-06-01``. Set the env var to a JSON object,
    e.g.::

        AETHER_LLM_EXTRA_HEADERS={"anthropic-version": "2023-06-01"}

    Malformed or non-object JSON is ignored (returns ``{}``) so a bad env
    value can never take the LLM layer down; values are coerced to str.
    """
    raw = os.environ.get("AETHER_LLM_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items()}


#: Shared wall-clock deadline (monotonic) for multi-agent orchestrations.
#: When set (via :func:`shared_budget`), every LLMClient in the current
#: context honours ONE deadline instead of arming its own — this is what
#: keeps the pipeline (tailor + coverLetter) inside a single budget so the
#: HTTP edge (~100 s) never returns a 524 (defect D1, audit 2026-07-09).
_shared_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "aether_llm_shared_deadline", default=None
)


@contextmanager
def shared_budget(
    seconds: float | None = None, *, not_below_active: bool = False
) -> Iterator[None]:
    """Bound ALL live LLM calls made inside the block by one wall-clock budget.

    ``not_below_active``: when an OUTER shared budget is already active whose
    deadline is FURTHER OUT than this window would set, keep the outer (larger)
    deadline instead of shrinking to it. This lets a step (e.g. the cover-letter
    drafting window) claim its OWN dedicated budget when it would otherwise
    inherit a *drained* one, WITHOUT clawing back a MORE-generous budget the
    caller already granted. Concretely (GAP-P7-COV-WORKER-001): the edge-free
    async WORKER runs the cover step under the 480 s pipeline / 300 s single
    budget, but the cover agent opens its own ``get_cover_budget_seconds()``
    (~88 s, tuned for the ~100 s HTTP edge) window, which previously OVERRODE the
    generous worker budget down to 88 s — starving the slow reasoning primary
    (deepseek-v4-pro ~110-120 s) AND leaving the fast fallback only ~21 s, so the
    worker cover/pipeline chronically 503'd ("AI service temporarily
    unavailable") even though the models were healthy. Flooring to the active
    deadline gives the worker cover its full 300/480 s. In the sync/edge path the
    active outer budget (the 65 s tailoring window, already partly drained) is
    always <= 88 s at cover time, so the behaviour is unchanged (cover still gets
    its edge-safe 88 s).
    """
    deadline = time.monotonic() + (seconds if seconds is not None else get_budget_seconds())
    if not_below_active:
        current = _shared_deadline.get()
        if current is not None and current > deadline:
            deadline = current
    token = _shared_deadline.set(deadline)
    try:
        yield
    finally:
        _shared_deadline.reset(token)

#: Per-call HTTP timeouts (seconds). OpenRouter free tier can stall for
#: minutes; a single call must never hold a request hostage.
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0

#: Minimum useful remaining budget — below this we skip live attempts and go
#: straight to fixture replay / typed error instead of firing a doomed call.
_MIN_ATTEMPT_SECONDS = 5.0


def get_budget_seconds() -> float:
    """Overall wall-clock budget for ALL live LLM calls in one client's life.

    One :class:`LLMClient` instance is created per agent run, so this bounds
    the whole fallback chain (primary + fallback model x corrective retries).

    Default raised to 180s (GAP-P6-AUTH-002): removing the fixture-fallback on
    failure means a genuine multi-call generation that would previously exhaust
    a 60s cap and silently serve a stale fixture now surfaces an honest error
    instead. QA observed real 58-62s tailoring runs hitting the old 60s cap; a
    180s budget gives multi-call tailoring/cover-letter runs room to complete
    live. Overridable via the env var (the production .env sets it at deploy).
    """
    try:
        return float(os.environ.get("AETHER_LLM_BUDGET_SECONDS", "180"))
    except ValueError:
        return 180.0


def get_cover_budget_seconds() -> float:
    """Dedicated wall-clock budget (seconds) for a COVER-LETTER / pipeline
    generation, decoupled from the tailoring-tuned global budget (GAP-P6-COV-002).

    The tailoring path deliberately runs a small global budget
    (``AETHER_LLM_BUDGET_SECONDS``, 65s in production) so the tailor GENERATION
    plus its dedicated ENTAILMENT window (:func:`get_entailment_budget_seconds`)
    both fit under the ~100s HTTP edge. The cover-letter path, however, is a
    SINGLE long generation call with NO entailment step, so that 65s needlessly
    starved it (the heavy reasoning primary fails, then the faster fallback runs
    out of budget) and the request chronically 503'd (live evidence
    qa-final-gates.json GATE-26, UAT-RESULTS-20260716-173502.json). The cover
    feature itself is sound (craft QA: a real 62s, 78-craft, zero-fabrication
    letter) — this is pure budget starvation.

    Because the cover path has no entailment reservation to leave room for, it can
    safely claim up to ~85-90s of the single-request ~100s edge. Applied as a
    fresh :func:`shared_budget` window around the cover drafting loop (exactly
    mirroring the TAIL-004 dedicated entailment window), it overrides the
    tailoring-constrained deadline for the cover generation ONLY — standalone
    cover gets the full window, and in the pipeline the cover no longer inherits
    the already-drained tailoring budget. Env-overridable
    (``AETHER_LLM_COVER_BUDGET_SECONDS``, default 88s); a missing/malformed value
    falls back to 88 and the result is floored at ``_MIN_ATTEMPT_SECONDS`` so a
    bad config can never drive it below a usable attempt. Ops MUST keep it under
    the single-request HTTP edge (~100s).
    """
    try:
        seconds = float(os.environ.get("AETHER_LLM_COVER_BUDGET_SECONDS", "88"))
    except ValueError:
        seconds = 88.0
    return max(_MIN_ATTEMPT_SECONDS, seconds)


def get_worker_budget_seconds() -> float:
    """Wall-clock LLM budget (seconds) for a SINGLE-agent generation running in
    the async background worker (GAP-P7-ASYNC-001, blueprint §4.4).

    The worker has NO ~100 s HTTP edge (its result is polled from Postgres), so
    it is intentionally more generous than the edge-tuned HTTP budgets
    (``AETHER_LLM_BUDGET_SECONDS`` is 65 s in production). A separate env var
    keeps that generosity OUT of the request path. MUST stay below the ARQ
    ``job_timeout`` (600 s) so a job is never killed mid-budget. Default 300 s.
    """
    try:
        return float(os.environ.get("AETHER_LLM_WORKER_BUDGET_SECONDS", "300"))
    except ValueError:
        return 300.0


def get_worker_cover_budget_seconds() -> float:
    """Worker-side cover-letter budget (seconds). Default 300 s (blueprint §4.4)."""
    try:
        return float(os.environ.get("AETHER_LLM_WORKER_COVER_BUDGET_SECONDS", "300"))
    except ValueError:
        return 300.0


def get_worker_pipeline_budget_seconds() -> float:
    """Worker-side SHARED budget (seconds) spanning the pipeline's two metered
    steps (tailor + coverLetter). Default 480 s (blueprint §4.4); MUST stay
    below the ARQ ``job_timeout`` (600 s)."""
    try:
        return float(os.environ.get("AETHER_LLM_WORKER_PIPELINE_BUDGET_SECONDS", "480"))
    except ValueError:
        return 480.0


def _entailment_budget_base_seconds() -> float:
    """Base seconds for the entailment window (``AETHER_LLM_ENTAILMENT_BUDGET_SECONDS``)."""
    try:
        return float(os.environ.get("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "20"))
    except ValueError:
        return 20.0


def get_entailment_budget_seconds(num_candidates: int | None = None) -> float:
    """Dedicated wall-clock budget (seconds) for the ENTAILMENT-verification LLM
    call, independent of and NOT consumable by the tailor GENERATION call that
    precedes it on the same client (GAP-P6-TAIL-004), scaled to the batch size
    (GAP-P6-TAIL-005).

    The tailor generation and the entailment verification previously shared ONE
    ``AETHER_LLM_BUDGET_SECONDS`` deadline (via the per-client budget or the
    pipeline-level :func:`shared_budget`). A slow reasoning primary consumed
    nearly all of it and left the verifier 0-9s, so it timed out and its
    conservative fail-safe reverted EVERY changed bullet — including genuinely
    supported ones — producing ZERO ATS lift (live evidence
    qa-prod-craft3.json: tailoredATS == baseline in 17/17 completions).
    Reserving the verifier its own FRESH budget window (the tailor call is
    already finished when the window opens, so it cannot consume it) lets it run
    and KEEP legitimate edits while STILL reverting real fabrications.

    GAP-P6-TAIL-005: a FIXED window is still too small to verify a full-resume
    batch. A run that proposed genuine story-grounded rewrites over ~18
    candidates timed out and its fail-safe reverted even the legitimate lift
    (qa-prod-craft4.json run 2). ``num_candidates`` scales the window as
    ``base + per_candidate * N`` (per-candidate via
    ``AETHER_LLM_ENTAILMENT_BUDGET_PER_CANDIDATE_SECONDS``, default 2.5s), capped
    by ``AETHER_LLM_ENTAILMENT_BUDGET_MAX_SECONDS`` (default 40s) so a large
    batch can never blow the ~100s HTTP edge, and floored at
    ``_MIN_ATTEMPT_SECONDS``. The tailor batch is now capped to the top-K bullets
    (``AETHER_TAILOR_MAX_BULLETS``), so in practice N is small and the window
    comfortably fits the verification.

    Called with ``num_candidates=None`` this returns the unscaled base window
    (backward compatible: the TAIL-004 dedicated-window contract), env-overridable
    (``AETHER_LLM_ENTAILMENT_BUDGET_SECONDS``, default 20s) with the same floor.
    """
    base = _entailment_budget_base_seconds()
    if num_candidates is None:
        return max(_MIN_ATTEMPT_SECONDS, base)
    try:
        per = float(os.environ.get("AETHER_LLM_ENTAILMENT_BUDGET_PER_CANDIDATE_SECONDS", "2.5"))
    except ValueError:
        per = 2.5
    try:
        cap = float(os.environ.get("AETHER_LLM_ENTAILMENT_BUDGET_MAX_SECONDS", "40"))
    except ValueError:
        cap = 40.0
    scaled = base + per * max(0, num_candidates)
    return max(_MIN_ATTEMPT_SECONDS, min(scaled, cap))


def get_primary_budget_fraction() -> float:
    """Fraction of the live budget the PRIMARY model attempt may consume before
    it is abandoned so the faster FALLBACK model still gets a turn within the
    same overall budget (GAP-P6-TAIL-003).

    Production runs a heavy reasoning primary (deepseek-v4-pro, measured
    ~110-120s for a large tailoring prompt) under an ~85s budget. Without a cap
    the primary's single attempt consumes the ENTIRE budget and the faster
    fallback (deepseek-v4-flash, ~37-58s) never runs, so the request 503s even
    though the fallback would have completed within the budget (live QA:
    3/5 attempts 503'd). Capping the primary to ~55% of the remaining budget
    reserves the rest for the fallback while the total still respects the overall
    budget/edge (~100s). Env-overridable (``AETHER_LLM_PRIMARY_BUDGET_FRACTION``);
    a missing/malformed/out-of-band value falls back to the 0.55 default so a bad
    config can never starve either attempt.
    """
    try:
        frac = float(os.environ.get("AETHER_LLM_PRIMARY_BUDGET_FRACTION", "0.55"))
    except ValueError:
        return 0.55
    if not 0.1 <= frac <= 0.9:
        return 0.55
    return frac


class LLMFixtureMissingError(RuntimeError):
    """Raised in replay mode when no fixture exists for a prompt."""


#: Honest, secret-free message shown to the USER when the live model failed and
#: no fixture fallback exists (MV-cover-letter-studio-005). The raw
#: :class:`LLMUnavailableError` string carries internal terms ('hard budget',
#: 'live call', prompt names) that must never reach a paying user — routers and
#: the async worker map the failure to this message on every user-facing surface
#: (503 detail, AgentRun.error audit, BackgroundJob.error) while keeping the
#: honest 503 + quota-refund semantics.
LLM_UNAVAILABLE_USER_MESSAGE = (
    "The AI service is temporarily unavailable. Please try again in a moment."
)


class LLMUnavailableError(RuntimeError):
    """Raised when the live LLM backend failed AND no fixture fallback exists.

    Routers convert this into a clean HTTP 503 with an honest, secret-free
    user message (:data:`LLM_UNAVAILABLE_USER_MESSAGE`).
    """


class QuotaExhaustedError(RuntimeError):
    """Raised when a subscription's provider quota is exhausted (HTTP 429).

    This is NEVER swallowed into a fixture fallback and NEVER triggers a reroute
    to a different credential/payer (that would be cross-provider billing). The
    router maps it to an honest 429 telling the user to switch this agent to
    API-key billing. Carries the provider and the cooldown expiry so the router
    can compute a ``retryAfter``.
    """

    def __init__(self, provider: str, *, expires_at: Any = None, reason: str = "") -> None:
        super().__init__(reason or f"{provider} subscription quota exhausted")
        self.provider = provider
        self.expires_at = expires_at
        self.reason = reason or f"{provider} subscription quota exhausted"


def get_mode() -> str:
    return os.environ.get("AETHER_LLM_MODE", "replay").strip().lower()


def get_fixture_dir() -> Path:
    override = os.environ.get("AETHER_LLM_FIXTURE_DIR")
    return Path(override) if override else _DEFAULT_FIXTURE_DIR


#: Per-run user MODEL override — a single model id the user chose for their
#: agents (GAP-P7-MODEL-CHOICE-001), bound exactly like ``_user_cred_context``.
#: ``get_model`` honours it ONLY for the GENERATION tiers
#: (:data:`_USER_OVERRIDABLE_TIERS`); STRUCTURED (JSON / entailment extraction)
#: deliberately stays on the tuned env default so a user's free-text pick can
#: never silently break structured output. ``None`` (background/CLI, or a user
#: with no preference) → pure env resolution, unchanged.
_user_model_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_llm_user_model", default=None
)

#: Tiers a user's chosen model may override. STRUCTURED is intentionally absent.
_USER_OVERRIDABLE_TIERS = frozenset({"REASONING", "HEAVY", "FAST", "LIGHT"})


@contextmanager
def user_model_context(model: str | None) -> Iterator[None]:
    """Bind the user's chosen agent model for the current run (see
    :data:`_user_model_context`). A blank/None model is a no-op (env default)."""
    token = _user_model_context.set((model or "").strip() or None)
    try:
        yield
    finally:
        _user_model_context.reset(token)


def get_model(tier: str = "REASONING") -> str:
    """Resolve the model id for a tier (REASONING/FAST/STRUCTURED/LIGHT/HEAVY).

    A per-run user override (:func:`user_model_context`) wins for the GENERATION
    tiers only; STRUCTURED and any unset override fall through to the
    ``AETHER_MODEL_<TIER>`` env default. Provider routing downstream is still
    derived purely from the resolved model id (:func:`resolve_provider`), so the
    user's choice can never cross the anthropic/openrouter billing boundary.
    """
    if tier.upper() in _USER_OVERRIDABLE_TIERS:
        override = _user_model_context.get()
        if override:
            return override
    return os.environ.get(f"AETHER_MODEL_{tier.upper()}", FALLBACK_MODEL)


#: Env vars ``_call_live`` checks for a usable API key, in the exact
#: precedence it applies. Exposed as data (not just inline in ``_call_live``)
#: so callers — notably the Agents providers panel (GAP-P4-055) — can report
#: which credential path is *actually* serving live runs instead of guessing.
_LIVE_API_KEY_ENV_VARS = ("AETHER_LLM_API_KEY", "OPENROUTER_API_KEY", "ABACUS_API_KEY")


def get_active_credential_env_var() -> str | None:
    """The env var ``_call_live`` will use as the API key right now, or ``None``.

    Mirrors ``_call_live``'s own precedence exactly (single source of truth)
    so the providers panel never has to fake or guess which credential path
    — including the ``ABACUS_API_KEY`` fallback — is actually serving runs.
    """
    for name in _LIVE_API_KEY_ENV_VARS:
        if os.environ.get(name):
            return name
    return None


# ---------------------------------------------------------------------------
# Provider-aware routing + native Anthropic transport (PROVIDER-CONFIG-RUN).
#
# A model id resolves to EXACTLY one provider and one credential source. There
# is NO cross-provider fallback: a ``claude-*`` model only ever hits
# api.anthropic.com with the Anthropic credential (native Messages API), and
# every other model only ever hits OpenRouter with the OpenRouter credential.
# A missing credential is an honest, provider-named error — never a silent
# reroute (ADR-PC-2 — the billing separation this feature exists to guarantee).
# ---------------------------------------------------------------------------

#: Native Anthropic Messages API (NOT OpenAI-compatible).
ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


def get_anthropic_max_tokens() -> int:
    """Required ``max_tokens`` for the Anthropic Messages API (env-overridable)."""
    try:
        return int(os.environ.get("AETHER_ANTHROPIC_MAX_TOKENS", "4096"))
    except ValueError:
        return 4096


def resolve_provider(model: str) -> str:
    """Map a model id to its billing provider: ``'anthropic'`` or ``'openrouter'``.

    OpenRouter namespaces EVERY model it serves as ``vendor/model``
    (``anthropic/claude-…``, ``deepseek/…``, ``openai/…``), and those are
    OpenRouter-billed. A DIRECT-Anthropic native id is bare ``claude-…`` (no
    slash). So the presence of a ``/`` means OpenRouter; only a bare
    ``claude-…``/``anthropic…`` id routes to the direct Anthropic API.

    Billing-separation fix (GAP-P7-MODEL-CHOICE-001, adversarial-review finding):
    a model a user picked from the OpenRouter catalog whose id happens to start
    ``anthropic/…`` MUST bill through OpenRouter — the credential they chose it
    with — NOT the direct-Anthropic account. The old ``startswith('anthropic/')``
    heuristic silently crossed that boundary for the 15 ``anthropic/*`` OpenRouter
    catalog entries. Pure function so the router, verify endpoint and transport
    all agree on one resolution.
    """
    m = (model or "").strip().lower()
    if "/" in m:  # any vendor/model id is an OpenRouter-served, OpenRouter-billed model
        return "openrouter"
    if m.startswith("claude-") or m.startswith("anthropic"):
        return "anthropic"
    return "openrouter"


#: Digit-anchored Claude-Code OAuth token prefix (ML-agents-cred-001, mirrors
#: ``app.routers.agents._ANTHROPIC_OAT_TOKEN_RE``): accepts any version
#: generation (oat01, oat02, oat03, …) but REQUIRES at least one digit
#: between "oat" and the trailing hyphen. A bare ``sk-ant-oat-`` (no digit)
#: must NOT match — it stays classified as ``subscription_oauth`` below.
_ANTHROPIC_OAT_TOKEN_RE = re.compile(r"^sk-ant-oat\d+-")


def _infer_anthropic_auth_mode(secret: str) -> str:
    """Anthropic authMode from the key prefix (single source of truth = prefix).

    A digit-versioned ``sk-ant-oat<N>-…`` token (oat01, oat02, …) is a pasted
    Claude Code OAuth token → ``oauth_token`` (supported, GAP-P7-DEF-A /
    ML-agents-cred-001 — Anthropic's CLI increments this version digit over
    time, so the match is not pinned to oat01 alone). Any other
    ``sk-ant-oat…`` (e.g. the legacy bare, non-versioned ``sk-ant-oat-``) is a
    legacy in-app subscription-OAuth token → ``subscription_oauth`` (still
    blocked; ADR-P7-01 NON-goal). Everything else → ``api_key``.
    """
    if _ANTHROPIC_OAT_TOKEN_RE.match(secret):
        return "oauth_token"
    if secret.startswith("sk-ant-oat"):
        return "subscription_oauth"
    return "api_key"


def _resolution_is_supported(provider: str, auth_mode: str) -> bool:
    """Whether a resolved credential may serve a live call.

    The consumer in-app OAuth *authorize* flow (``subscription_oauth``) stays
    removed for compliance (ADR-P7-01 NON-goal): a pre-existing subscription
    credential/token must never be used for a live request — returning ``False``
    makes the resolver fall through rather than fake a success. A pasted Claude
    Code OAuth token (``oauth_token``, GAP-P7-DEF-A) IS supported.
    """
    return not (provider == "anthropic" and auth_mode == "subscription_oauth")


@dataclass(frozen=True)
class ProviderCredentialResolution:
    """A resolved provider credential and where it came from."""

    provider: str
    auth_mode: str          # 'api_key' | 'oauth_token' | 'subscription_oauth'
    secret: str
    base_url: str | None
    source: str             # 'database' | 'environment'


def resolve_credential(provider: str) -> "ProviderCredentialResolution | None":
    """Resolve ``provider``'s credential: DB row FIRST, then legacy env fallback.

    Returns ``None`` when neither exists — the caller must then raise an honest,
    provider-named error and must NOT reroute to the other provider.
    """
    # 1. Encrypted DB credential (the in-UI configured path) wins.
    try:
        from app.repositories.provider_credential import ProviderCredentialRepository

        row = ProviderCredentialRepository().get_secret(provider)
    except Exception as exc:  # DB down / table missing / key rotated -> degrade
        logger.warning(
            "provider-credential DB lookup for '%s' failed; falling back to env: %s",
            provider, exc,
        )
        row = None
    if row and row.get("secret"):
        auth_mode = row.get("authMode") or "api_key"
        # A pre-existing subscription_oauth row is no longer usable (GAP-AUTH-001):
        # skip it and fall through to the env fallback / honest no-credential.
        if _resolution_is_supported(provider, auth_mode):
            return ProviderCredentialResolution(
                provider=provider,
                auth_mode=auth_mode,
                secret=row["secret"],
                base_url=row.get("baseUrl"),
                source="database",
            )
    # 2. Legacy env fallback — strictly provider-scoped, never cross-provider.
    if provider == "anthropic":
        # NOTE (MV-system-002): ``CLAUDE_CODE_OAUTH_TOKEN`` is a downstream SYNC
        # TARGET written by ``env_file_writer`` on an oauth_token save (native-
        # consumer hand-off / restart survival) — NOT an independent credential
        # source for this resolver. The encrypted DB row is the single source of
        # truth for an oauth_token credential and is resolved DB-first above
        # (immediately usable, and it survives restarts because the save always
        # writes the DB row and the ``.env`` line together). Resolving a bare
        # ambient ``CLAUDE_CODE_OAUTH_TOKEN`` here would (a) resurrect a
        # credential the operator deleted from the DB (no companion row), (b) leak
        # a developer's ambient token into per-user/anthropic resolution, and (c)
        # break the no-cross-provider / honest-no-credential invariants
        # (test_provider_config::TestNoCrossProviderFallback,
        # test_gap_p5_auth_compliance). So the resolver never reads it — the
        # oauth_token path is DB-row only.
        base = os.environ.get("AETHER_LLM_BASE_URL", "")
        direct = os.environ.get("AETHER_LLM_API_KEY")
        if direct and "anthropic.com" in base:
            mode = _infer_anthropic_auth_mode(direct)
            if _resolution_is_supported("anthropic", mode):
                return ProviderCredentialResolution(
                    "anthropic", mode, direct, base, "environment"
                )
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            mode = _infer_anthropic_auth_mode(key)
            if _resolution_is_supported("anthropic", mode):
                return ProviderCredentialResolution(
                    "anthropic", mode, key, None, "environment"
                )
        return None
    # openrouter (and every non-anthropic model, which is served via OpenRouter).
    # Strictly provider-scoped — the generic AETHER_LLM_* pair may hold a legacy
    # Anthropic token pointed at api.anthropic.com; handing that to the OpenRouter
    # path is exactly the cross-provider billing crossover ADR-PC-2 forbids.
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        return ProviderCredentialResolution(
            "openrouter", "api_key", or_key,
            os.environ.get("OPENROUTER_BASE_URL"), "environment",
        )
    # Fall back to the generic AETHER_LLM_* pair only when it is NOT pointed at an
    # Anthropic endpoint (mirror of the anthropic-branch guard above). If the only
    # env pair present is Anthropic, return None so the caller raises the honest
    # 'no credential for openrouter' error and fires ZERO HTTP.
    llm_base = os.environ.get("AETHER_LLM_BASE_URL", "")
    llm_key = os.environ.get("AETHER_LLM_API_KEY")
    if llm_key and "anthropic.com" not in llm_base:
        return ProviderCredentialResolution(
            "openrouter", "api_key", llm_key, llm_base or None, "environment"
        )
    abacus = os.environ.get("ABACUS_API_KEY")
    if abacus:
        return ProviderCredentialResolution(
            "openrouter", "api_key", abacus,
            os.environ.get("OPENROUTER_BASE_URL"), "environment",
        )
    return None


#: Per-run user context (userId, agentKey) so the deep live-call path can
#: resolve the RIGHT user's credential (GAP-E5) without threading the ids
#: through every agent/service constructor. Set by the Agents router around a
#: run (see ``user_credential_context``); ``None`` means "no user context"
#: (background/CLI callers) → the resolver falls back to deployment-wide creds.
_user_cred_context: contextvars.ContextVar["tuple[str, str | None] | None"] = (
    contextvars.ContextVar("aether_llm_user_cred", default=None)
)


@contextmanager
def user_credential_context(user_id: str, agent_key: str | None = None) -> Iterator[None]:
    """Bind the current user (and optional agent key) for credential resolution."""
    token = _user_cred_context.set((user_id, agent_key))
    try:
        yield
    finally:
        _user_cred_context.reset(token)


def _lookup_agent_credential_ref(user_id: str, agent_key: str) -> str | None:
    """The ``AgentConfig.credentialRef`` this user pinned for ``agent_key``."""
    try:
        from app.db import get_connection, rows_to_dicts

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "credentialRef" FROM "AgentConfig" '
                    'WHERE "userId" = %s AND "agentKey" = %s',
                    (user_id, agent_key),
                )
                rows = rows_to_dicts(cur)
    except Exception as exc:  # noqa: BLE001 — missing column/table → no override
        logger.debug("agent credentialRef lookup failed: %s", exc)
        return None
    if rows:
        return rows[0].get("credentialRef")
    return None


def resolve_user_credential(
    provider: str, user_id: str | None = None, agent_key: str | None = None
) -> "ProviderCredentialResolution | None":
    """Resolve ``provider``'s credential for a specific user, honestly & scoped.

    Resolution order (NEVER cross-provider — a mismatched provider is skipped,
    not rerouted):

    1. ``AgentConfig.credentialRef`` → that user's ``UserProviderCredential`` row
       (only when its provider matches).
    2. the user's ``UserProviderCredential`` for ``provider`` (a legacy
       ``subscription_oauth`` credential is skipped — no longer supported).
    3. the deployment-wide ``ProviderCredential`` row.
    4. legacy provider-scoped env vars.

    Steps 3–4 are delegated to :func:`resolve_credential` so the legacy path is
    unchanged; passing ``user_id=None`` makes this function behave EXACTLY like
    ``resolve_credential`` (backward compatibility).
    """
    if user_id:
        # Refresh-before-expiry hook (ML-agents-cred-002, ADR-ML-2a DECISION-1b).
        # When a deployment-wide Anthropic subscription OAuth session exists and
        # is near/after expiry, refresh it and propagate the NEW access token into
        # the same ProviderCredential('anthropic') row this resolver reads DB-first
        # — so bare claude-* runs never send a stale token. Best-effort: a refresh
        # outage must not 500 a run, and this NEVER crosses providers (an honest
        # 401 on an un-refreshable expired token is surfaced by the live-call path,
        # with needs_reauth already marked, rather than a silent reroute).
        if provider == "anthropic":
            try:
                from app.services import anthropic_oauth

                anthropic_oauth.refresh_if_needed(user_id)
            except Exception as exc:  # noqa: BLE001 — best-effort; never break resolution
                logger.warning("anthropic oauth refresh-before-use skipped: %s", exc)
        from app.repositories.user_provider_credential import (
            UserProviderCredentialRepository,
        )

        repo = UserProviderCredentialRepository()
        # 1. Per-agent pinned credentialRef (only if it matches this provider).
        if agent_key:
            ref = _lookup_agent_credential_ref(user_id, agent_key)
            if ref:
                try:
                    got = repo.get_secret_by_id(ref, user_id)
                except Exception as exc:  # noqa: BLE001 — degrade to next source
                    logger.warning("credentialRef resolve failed: %s", exc)
                    got = None
                if (
                    got
                    and got.get("provider") == provider
                    and got.get("secret")
                    and _resolution_is_supported(provider, got["authMode"])
                ):
                    return ProviderCredentialResolution(
                        provider, got["authMode"], got["secret"],
                        got.get("baseUrl"), "user_credential_ref",
                    )
        # 2. The user's own credential for this provider.
        try:
            got = repo.get_secret(user_id, provider)
        except Exception as exc:  # noqa: BLE001 — DB hiccup → deployment fallback
            logger.warning("user credential resolve failed: %s", exc)
            got = None
        # A pre-existing subscription_oauth credential is no longer usable
        # (GAP-AUTH-001): skip it so live calls fall through to a supported
        # api_key / env source instead of a faked success.
        if (
            got
            and got.get("secret")
            and _resolution_is_supported(provider, got["authMode"])
        ):
            return ProviderCredentialResolution(
                provider, got["authMode"], got["secret"],
                got.get("baseUrl"), "user_credential",
            )
    # 3 + 4. Deployment-wide DB row, then legacy env (unchanged legacy path).
    return resolve_credential(provider)


#: How long a subscription-quota cooldown lasts after a 429 (env-overridable).
def get_quota_block_hours() -> float:
    try:
        return float(os.environ.get("AETHER_QUOTA_BLOCK_HOURS", "5"))
    except ValueError:
        return 5.0


#: Message substrings that mark an Anthropic 429 as SUBSCRIPTION / spend-cap
#: quota exhaustion (usage paused until reset) rather than a transient per-minute
#: rate limit. Both surface as HTTP 429 with error.type == "rate_limit_error" —
#: there is NO distinct type (verified from the official Anthropic errors +
#: rate-limits docs, 2026-07-17: platform.claude.com/docs/en/api/errors and
#: /rate-limits). The message text + retry-after magnitude are the ONLY signals.
_QUOTA_429_MESSAGE_SIGNALS = (
    "usage limit", "spend", "quota", "credit balance",
    "plan limit", "monthly", "subscription",
)


def get_quota_429_retry_after_seconds() -> float:
    """A ``retry-after`` at/above this many seconds marks a 429 as
    subscription-quota (a spend cap "pauses until the next month" → a very large
    retry-after; a per-minute limit replenishes continuously → a small one).
    Env-overridable via ``AETHER_QUOTA_429_RETRY_AFTER_SECONDS``."""
    try:
        return float(os.environ.get("AETHER_QUOTA_429_RETRY_AFTER_SECONDS", "300"))
    except ValueError:
        return 300.0


def _resp_header(resp: Any, name: str) -> "str | None":
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get(name)
    except Exception:  # noqa: BLE001 — a header mapping without .get()
        return None


def _parse_retry_after(raw: Any) -> "float | None":
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _anthropic_error_message(resp: Any) -> str:
    """Best-effort extraction of ``error.message`` from an Anthropic error body."""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — non-JSON / partial body
        return getattr(resp, "text", "") or ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return getattr(resp, "text", "") or ""


def _anthropic_429_is_subscription_quota(resp: Any) -> bool:
    """Classify an Anthropic 429 as subscription-quota exhaustion (→ cooldown
    block) vs a transient per-minute rate limit.

    CONSERVATIVE (GAP-P7-DEF-A PROBE-DEFA-2): only a positive signal — a
    quota/spend message phrase OR a very large retry-after — counts as quota;
    anything ambiguous is treated as a transient rate limit (a false long block
    would wrongly pause a user for hours). Either way the run is NEVER rerouted
    to a different credential (ADR-PC-2)."""
    message = _anthropic_error_message(resp).lower()
    if any(signal in message for signal in _QUOTA_429_MESSAGE_SIGNALS):
        return True
    retry_after = _parse_retry_after(_resp_header(resp, "retry-after"))
    if retry_after is not None and retry_after >= get_quota_429_retry_after_seconds():
        return True
    return False


def _quota_block_expiry() -> datetime:
    """When a freshly recorded subscription-quota cooldown expires (UTC)."""
    return datetime.now(timezone.utc) + timedelta(hours=get_quota_block_hours())


def _active_quota_block(user_id: str, provider: str) -> "dict[str, Any] | None":
    try:
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository

        return AgentQuotaBlockRepository().get_active(user_id, provider)
    except Exception as exc:  # noqa: BLE001 — never let the block store 500 a run
        logger.debug("quota block lookup failed: %s", exc)
        return None


def anthropic_auth_headers(auth_mode: str, secret: str) -> dict[str, str]:
    """Auth/version headers for the native Anthropic Messages API, per authMode.

    Two supported transports (verified against live wire mechanics, GAP-P7-DEF-A):

    - ``api_key`` (``sk-ant-api…``, Claude Console) → ``x-api-key: <key>``.
    - ``oauth_token`` (``sk-ant-oat01-…``, a pasted ``claude setup-token``) →
      ``Authorization: Bearer <token>`` + ``anthropic-beta: oauth-2025-04-20``
      (x-api-key returns 401 for an oat token; Bearer+beta returns 200).

    The legacy in-app subscription-OAuth flow (``subscription_oauth``) stays
    unsupported (ADR-P7-01 NON-goal) — any other ``auth_mode`` is a hard error.
    """
    headers = {
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    if auth_mode == "api_key":
        headers["x-api-key"] = secret
    elif auth_mode == "oauth_token":
        headers["authorization"] = f"Bearer {secret}"
        headers["anthropic-beta"] = "oauth-2025-04-20"
    else:
        raise RuntimeError(
            f"Unsupported Anthropic authMode '{auth_mode}'; supported: 'api_key' "
            "(Claude Console) and 'oauth_token' (claude setup-token)."
        )
    return headers


def build_anthropic_request(
    model: str,
    system: str | None,
    user: str,
    *,
    auth_mode: str,
    secret: str,
    base_url: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Prepare a native Anthropic Messages request (``{url, json, headers}``).

    Exposed so tests and the verify endpoint can inspect the prepared request
    without a live call. ``temperature``/``top_p`` are deliberately omitted —
    current Anthropic models 400 on them.
    """
    base = (base_url or ANTHROPIC_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens or get_anthropic_max_tokens()),
        "messages": [{"role": "user", "content": user}],
    }
    if system:
        body["system"] = system
    return {
        "url": f"{base}/v1/messages",
        "json": body,
        "headers": anthropic_auth_headers(auth_mode, secret),
    }


def parse_anthropic_response(body: dict[str, Any]) -> str:
    """Extract assistant text from a Messages API response, honestly.

    Concatenates ``content`` blocks where ``type == 'text'``. A ``refusal`` stop
    reason is surfaced as an error; a ``max_tokens`` truncation with no text is
    an error, and with partial text is logged (the JSON caller's parser catches
    a truncated object and degrades to a fixture).
    """
    stop = body.get("stop_reason")
    if stop == "refusal":
        raise RuntimeError("Anthropic declined to answer (stop_reason=refusal)")
    blocks = body.get("content") or []
    text = "".join(
        b.get("text", "")
        for b in blocks
        if isinstance(b, dict) and b.get("type") == "text"
    )
    if not text.strip():
        if stop == "max_tokens":
            raise RuntimeError(
                "Anthropic response truncated at max_tokens before any text; "
                "raise AETHER_ANTHROPIC_MAX_TOKENS"
            )
        raise RuntimeError("Anthropic returned empty content")
    if stop == "max_tokens":
        logger.warning("Anthropic response truncated at max_tokens (partial content)")
    return text


def _build_openrouter_request(
    model: str,
    system: str,
    user: str,
    temperature: float,
    cred: "ProviderCredentialResolution",
) -> dict[str, Any]:
    """Prepare the existing OpenAI-compatible OpenRouter chat request."""
    base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
    return {
        "url": f"{base}/chat/completions",
        "json": {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        "headers": {
            "Authorization": f"Bearer {cred.secret}",
            "Content-Type": "application/json",
            **_extra_headers(),
        },
    }


def verify_provider_credential(
    provider: str, *, timeout: float = 15.0
) -> tuple[bool, str, str]:
    """Perform a REAL minimal round-trip against ``provider``'s stored credential.

    Returns ``(ok, status, detail)``. ``ok`` is only True on a genuine 2xx —
    never fabricated. Anthropic sends a 1-token Messages ping; OpenRouter lists
    models. Providers with no native transport report an honest ``'unsupported'``.
    """
    cred = resolve_credential(provider)
    if cred is None:
        return (False, "no_credential", f"No credential configured for '{provider}'.")
    return verify_resolved_credential(provider, cred, timeout=timeout)


def verify_user_credential(
    provider: str, user_id: str, *, timeout: float = 15.0
) -> tuple[bool, str, str]:
    """Verify a specific USER's stored credential with a real round-trip.

    Resolves the credential through :func:`resolve_user_credential` (per-user
    first), then performs the same honest ping as :func:`verify_provider_credential`.
    """
    cred = resolve_user_credential(provider, user_id)
    if cred is None:
        return (False, "no_credential", f"No credential configured for '{provider}'.")
    return verify_resolved_credential(provider, cred, timeout=timeout)


def verify_resolved_credential(
    provider: str, cred: "ProviderCredentialResolution", *, timeout: float = 15.0
) -> tuple[bool, str, str]:
    """Real minimal round-trip against an already-resolved credential.

    Returns ``(ok, status, detail)``; ``ok`` is True only on a genuine 2xx.
    """
    import httpx

    try:
        if provider == "anthropic":
            req = build_anthropic_request(
                "claude-haiku-4-5", None, "ping",
                auth_mode=cred.auth_mode, secret=cred.secret,
                base_url=cred.base_url, max_tokens=1,
            )
            resp = httpx.post(
                req["url"], json=req["json"], headers=req["headers"], timeout=timeout
            )
        elif provider == "openrouter":
            base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
            resp = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {cred.secret}"},
                timeout=timeout,
            )
        else:
            return (
                False,
                "unsupported",
                f"Live verification is not available for provider '{provider}' "
                "(its models are served through OpenRouter).",
            )
    except Exception as exc:  # network/DNS/timeout — honest failure, never faked
        return (False, "error", f"Verification request failed: {exc}")
    if 200 <= resp.status_code < 300:
        return (True, "ok", f"{provider} responded HTTP {resp.status_code}.")
    if provider == "anthropic" and resp.status_code == 429:
        # Honest 429 disambiguation (GAP-P7-DEF-A §4): distinguish a subscription
        # quota exhaustion from a transient per-minute rate limit so the modal
        # can tell the user to wait vs switch to API-key mode.
        if _anthropic_429_is_subscription_quota(resp):
            return (
                False, "quota_exhausted",
                "Anthropic subscription quota reached; retry later or switch "
                "this credential to API-key mode.",
            )
        return (
            False, "rate_limited",
            "Anthropic rate limit hit (per-minute); retry shortly.",
        )
    return (
        False,
        "failed",
        f"{provider} returned HTTP {resp.status_code}: {resp.text[:150]}",
    )


class ModelCatalogError(RuntimeError):
    """Raised when the live model catalog can't be fetched (no credential /
    network / provider without an open catalog). The router maps it to an honest
    4xx/5xx — a fabricated catalog is NEVER returned (GAP-P7-MODEL-CHOICE-001)."""


#: Curated static catalogs for providers that don't expose an OpenRouter-style
#: open ``/models`` endpoint. Kept tiny + honest (ids the app can actually route
#: via ``resolve_provider`` → anthropic). Prices are indicative $/M-tokens.
_STATIC_MODEL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "anthropic": [
        {"id": "claude-opus-4-8", "name": "Claude Opus 4.8", "promptPerM": 15.0,
         "completionPerM": 75.0, "contextLength": 200000, "tier": "premium",
         "reasoning": True},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6", "promptPerM": 3.0,
         "completionPerM": 15.0, "contextLength": 200000, "tier": "standard",
         "reasoning": True},
        {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "promptPerM": 1.0,
         "completionPerM": 5.0, "contextLength": 200000, "tier": "budget",
         "reasoning": False},
    ],
}

#: Cached OpenRouter catalog: provider -> (fetched_at_monotonic, curated list).
_MODEL_CATALOG_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_MODEL_CATALOG_TTL = 3600.0  # 1 h — the catalog changes rarely.


def cached_model_price(model_id: str) -> "tuple[float, float] | None":
    """``(prompt, completion)`` price in $/1K-tokens for ``model_id`` from the
    already-fetched OpenRouter catalog, or ``None`` if the catalog hasn't been
    loaded or the model isn't in it. Lets the (network-free) cost path price a
    USER-CHOSEN model accurately instead of a flat default — the catalog is
    typically warm because the user browsed it before picking a model."""
    mid = (model_id or "").strip()
    if not mid:
        return None
    # Fetched (OpenRouter) catalogs first, then the always-available STATIC
    # catalogs (anthropic, …). Without the static scan a premium anthropic pick
    # like ``claude-opus-4-8`` fell through to the flat default and was costed
    # ~15-37x under — a spend-cap bypass (adversarial-review finding).
    from itertools import chain

    for models in chain(
        (m for _ts, m in _MODEL_CATALOG_CACHE.values()),
        _STATIC_MODEL_CATALOG.values(),
    ):
        for m in models:
            if m.get("id") == mid:
                return (
                    float(m.get("promptPerM") or 0.0) / 1000.0,
                    float(m.get("completionPerM") or 0.0) / 1000.0,
                )
    return None


def _model_budget_tier(prompt_per_token: float) -> str:
    """Bucket a model by its prompt price ($/token) so the UI can group by
    budget: free / budget (≤$0.50·M) / standard (≤$3·M) / premium."""
    if prompt_per_token <= 0:
        return "free"
    if prompt_per_token <= 0.0000005:
        return "budget"
    if prompt_per_token <= 0.000003:
        return "standard"
    return "premium"


def _curate_openrouter_models(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project OpenRouter's verbose ``/models`` payload to the fields the picker
    needs, tagged with a budget tier, sorted cheapest-first within tier."""
    out: list[dict[str, Any]] = []
    for m in raw:
        mid = m.get("id")
        if not mid:
            continue
        pricing = m.get("pricing") or {}
        try:
            prompt = float(pricing.get("prompt") or 0.0)
        except (TypeError, ValueError):
            prompt = 0.0
        try:
            completion = float(pricing.get("completion") or 0.0)
        except (TypeError, ValueError):
            completion = 0.0
        if prompt < 0 or completion < 0:
            # Sentinel/dynamic-priced rows (e.g. openrouter/auto) — skip so the
            # UI never shows a negative or misleading price.
            continue
        arch = m.get("architecture") or {}
        out.append(
            {
                "id": mid,
                "name": m.get("name") or mid,
                "promptPerM": round(prompt * 1_000_000, 4),
                "completionPerM": round(completion * 1_000_000, 4),
                "contextLength": m.get("context_length"),
                "tier": _model_budget_tier(prompt),
                "reasoning": bool(m.get("reasoning"))
                or "reasoning" in (arch.get("modality") or ""),
            }
        )
    _rank = {"free": 0, "budget": 1, "standard": 2, "premium": 3}
    out.sort(key=lambda x: (_rank.get(x["tier"], 4), x["promptPerM"], x["id"]))
    return out


def list_provider_models(
    provider: str, user_id: str | None = None, *, timeout: float = 15.0
) -> list[dict[str, Any]]:
    """Live, curated model catalog for ``provider`` (GAP-P7-MODEL-CHOICE-001).

    OpenRouter → its full ``/models`` catalog (300+ models) fetched with the
    user's own credential when present, else the deployment credential, curated
    to ``{id, name, promptPerM, completionPerM, contextLength, tier, reasoning}``
    and cached ~1 h. Providers without an open catalog (anthropic, …) return a
    small curated static list. Raises :class:`ModelCatalogError` on a missing
    credential or a network failure — never a fabricated catalog.
    """
    provider = (provider or "").strip().lower()
    if provider in _STATIC_MODEL_CATALOG:
        return list(_STATIC_MODEL_CATALOG[provider])
    if provider != "openrouter":
        raise ModelCatalogError(
            f"No live model catalog is available for provider '{provider}'."
        )
    now = time.monotonic()
    cached = _MODEL_CATALOG_CACHE.get(provider)
    if cached is not None and now - cached[0] < _MODEL_CATALOG_TTL:
        return cached[1]
    # The OpenRouter /models catalog is GLOBAL (identical for any valid key), so
    # try the user's own credential first but FALL BACK to the deployment
    # credential when the user's key is missing/invalid — the catalog stays
    # visible even if a user pasted a bad personal key (GAP-P7-MODEL-CHOICE-002).
    import httpx

    user_cred = resolve_user_credential(provider, user_id, None)
    deploy_cred = resolve_credential(provider)
    creds = [c for c in (user_cred, deploy_cred) if c is not None]
    # de-dupe if both resolved to the same secret
    seen: set[str] = set()
    ordered = []
    for c in creds:
        if c.secret not in seen:
            seen.add(c.secret)
            ordered.append(c)
    if not ordered:
        raise ModelCatalogError(
            "Add an OpenRouter API key (in the Agents panel or the server env) "
            "to browse the live model catalog."
        )
    last_err = ""
    for cred in ordered:
        base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
        try:
            resp = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {cred.secret}"},
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — try the next credential
            last_err = f"could not reach the model catalog: {exc}"
            continue
        if 200 <= resp.status_code < 300:
            curated = _curate_openrouter_models(resp.json().get("data") or [])
            _MODEL_CATALOG_CACHE[provider] = (now, curated)
            return curated
        last_err = f"HTTP {resp.status_code}"
    raise ModelCatalogError(f"Model catalog request failed ({last_err}).")


class LLMClient:
    """Minimal chat-completion client with record/replay/auto support."""

    def __init__(self, mode: str | None = None, fixture_dir: Path | None = None) -> None:
        self.mode = mode or get_mode()
        self.fixture_dir = fixture_dir or get_fixture_dir()
        #: Wall-clock deadline for live calls; armed on the first live attempt
        #: so the whole fallback chain shares one budget (see get_budget_seconds).
        self._deadline: float | None = None

    def _remaining_budget(self) -> float:
        """Seconds left in the live-call budget (arms the deadline lazily).

        A context-level shared deadline (see :func:`shared_budget`) takes
        precedence so multi-agent orchestrations share ONE budget.
        """
        shared = _shared_deadline.get()
        if shared is not None:
            return shared - time.monotonic()
        if self._deadline is None:
            self._deadline = time.monotonic() + get_budget_seconds()
        return self._deadline - time.monotonic()

    def complete(
        self,
        prompt_name: str,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.0,
        fixture_key: str = "default",
    ) -> str:
        """Return the assistant's text for a system+user prompt pair."""
        if self.mode == "replay":
            return self._replay(prompt_name, fixture_key)
        if self.mode == "auto":
            return self._auto(
                prompt_name, system, user,
                model=model, temperature=temperature, fixture_key=fixture_key,
            )
        # live / record modes: propagate live errors unchanged (developer modes).
        content = self._call_live(system, user, model=model, temperature=temperature)
        if self.mode == "record":
            self._record(prompt_name, fixture_key, content)
        return content

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        """Like :meth:`complete` but parses the response as JSON.

        In ``auto`` mode a malformed/truncated live response (e.g. the model hit
        its token limit mid-object) is an honest live FAILURE — it raises
        :class:`LLMUnavailableError` (mapped to 503, run refunded). It is NEVER
        answered with a recorded fixture masqueraded as live output
        (GAP-P6-AUTH-002); fixtures serve only in ``replay`` mode.
        """
        raw = self.complete(prompt_name, system, user, **kwargs)
        try:
            return json.loads(self._strip_fences(raw))
        except json.JSONDecodeError as exc:
            if self.mode != "auto":
                raise
            logger.warning(
                "LLM returned malformed JSON for prompt '%s' in auto mode; "
                "raising honest error (no fixture fallback on failure)",
                prompt_name,
            )
            raise LLMUnavailableError(
                f"LLM backend unavailable: live call for '{prompt_name}' returned "
                "malformed JSON"
            ) from exc

    @staticmethod
    def _strip_fences(raw: str) -> str:
        """Tolerate markdown fences around JSON payloads."""
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        return text

    # ------------------------------------------------------------------
    def _auto(
        self,
        prompt_name: str,
        system: str,
        user: str,
        *,
        model: str | None,
        temperature: float,
        fixture_key: str,
    ) -> str:
        """Live-first with one model-fallback retry, then an HONEST error.

        Every live attempt is bounded by per-call HTTP timeouts AND the
        client-wide wall-clock budget. When the real retry chain is exhausted
        (all attempts failed, or the budget ran out before an attempt could
        start), this raises :class:`LLMUnavailableError` — it NEVER serves a
        recorded fixture as if it were a live generation (GAP-P6-AUTH-002).
        Serving a stale fixture on failure silently handed paying users canned,
        generic content with no signal; the honest error propagates so the run
        is recorded failed and the reserved quota is refunded. Fixtures are for
        ``replay`` mode only. Recording on live SUCCESS below is harmless.
        """
        primary = model or get_model("REASONING")
        chain = self._model_chain(primary)
        has_fallback = len(chain) > 1
        last_error: Exception | None = None
        budget_exhausted = False
        for idx, attempt_model in enumerate(chain):
            remaining = self._remaining_budget()
            if remaining < _MIN_ATTEMPT_SECONDS:
                logger.warning(
                    "LLM budget exhausted before model %s (prompt=%s); "
                    "raising honest error (no fixture fallback on failure)",
                    attempt_model, prompt_name,
                )
                budget_exhausted = True
                break
            attempt_seconds = remaining
            if idx == 0 and has_fallback:
                # GAP-P6-TAIL-003: cap the PRIMARY attempt so a slow reasoning
                # model can't eat the whole budget and starve the faster
                # fallback. remaining at the first attempt is the full (possibly
                # shared) budget, so this is a fraction of the total; the
                # fallback (last attempt) keeps the entire remaining budget.
                attempt_seconds = max(
                    _MIN_ATTEMPT_SECONDS, remaining * get_primary_budget_fraction()
                )
            try:
                content = self._call_live(
                    system, user, model=attempt_model, temperature=temperature,
                    max_seconds=attempt_seconds,
                )
            except QuotaExhaustedError:
                # Subscription quota is exhausted — NEVER fall back to a fixture
                # or another model/credential (that would fake success or shift
                # the bill). Propagate so the router returns an honest 429.
                raise
            except Exception as exc:  # 404/429/5xx/network/timeout/parse — try next
                last_error = exc
                logger.warning(
                    "LLM live call failed (model=%s, prompt=%s): %s",
                    attempt_model, prompt_name, exc,
                )
                continue
            # Record only if missing so curated replay fixtures are
            # never clobbered by variable live output.
            if not self._fixture_path(prompt_name, fixture_key).is_file():
                self._record(prompt_name, fixture_key, content)
            return content
        # Live retry chain exhausted — surface an HONEST failure, never a fixture.
        detail = (
            "budget exhausted before any live attempt could complete"
            if budget_exhausted
            else f"live call failed{f': {last_error}' if last_error else ''}"
        )
        raise LLMUnavailableError(
            f"LLM backend unavailable: {detail} for '{prompt_name}'"
        )

    @staticmethod
    def _model_chain(primary: str) -> list[str]:
        """Primary model, then one retry with the fallback model."""
        fallback = get_fallback_model()
        return [primary] if primary == fallback else [primary, fallback]

    def _fixture_path(self, prompt_name: str, key: str) -> Path:
        return self.fixture_dir / prompt_name / f"{key}.json"

    def _replay(self, prompt_name: str, key: str) -> str:
        path = self._fixture_path(prompt_name, key)
        if not path.is_file():
            raise LLMFixtureMissingError(
                f"LLM replay fixture missing: {path}. Run in record mode first."
            )
        return json.loads(path.read_text())["content"]

    def _record(self, prompt_name: str, key: str, content: str) -> None:
        path = self._fixture_path(prompt_name, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"content": content}, indent=2))

    def _call_live(
        self,
        system: str,
        user: str,
        *,
        model: str | None,
        temperature: float,
        max_seconds: float | None = None,
    ) -> str:
        """Single live call with a HARD wall-clock cap, routed by provider.

        The model id resolves to EXACTLY one provider + credential source
        (:func:`resolve_provider` / :func:`resolve_credential`). Anthropic models
        use the native Messages API; everything else uses the OpenAI-compatible
        OpenRouter path. A missing credential raises an honest, provider-named
        error — the request is NEVER rerouted to the other provider (ADR-PC-2).

        httpx read timeouts are *per-chunk*: a provider that trickles bytes can
        keep a "30 s read timeout" call alive for minutes (observed 133–157 s
        coverLetter runs → edge 524s, defect D1). The request is therefore
        executed in a worker thread and abandoned outright once ``max_seconds``
        elapses, so the caller can move on to the fallback model / fixture while
        still inside the budget.
        """
        import httpx

        model_id = model or get_model("REASONING")
        provider = resolve_provider(model_id)
        ctx = _user_cred_context.get()
        ctx_user_id = ctx[0] if ctx else None
        ctx_agent_key = ctx[1] if ctx else None
        # Quota cooldown: a prior 429 on this user+provider blocks live calls
        # until it expires. We surface an honest QuotaExhaustedError rather than
        # silently rerouting to a different (billable) credential (ADR-PC-2).
        if ctx_user_id is not None:
            block = _active_quota_block(ctx_user_id, provider)
            if block is not None:
                raise QuotaExhaustedError(
                    provider,
                    expires_at=block.get("expiresAt"),
                    reason=block.get("reason") or "subscription_quota_exceeded",
                )
        cred = resolve_user_credential(provider, ctx_user_id, ctx_agent_key)
        if cred is None:
            raise RuntimeError(
                f"No credential configured for provider '{provider}' "
                f"(model '{model_id}'). Add a {provider} credential in the Agents "
                "panel or its server env key. The request will NOT be rerouted to "
                "another provider — billing separation is enforced."
            )
        if provider == "anthropic":
            req = build_anthropic_request(
                model_id, system, user,
                auth_mode=cred.auth_mode, secret=cred.secret, base_url=cred.base_url,
            )
        else:
            req = _build_openrouter_request(model_id, system, user, temperature, cred)

        connect = CONNECT_TIMEOUT
        read = READ_TIMEOUT
        if max_seconds is not None:
            connect = max(1.0, min(connect, max_seconds))
            read = max(1.0, min(read, max_seconds))
        timeout = httpx.Timeout(connect=connect, read=read, write=10.0, pool=10.0)

        def _do_request() -> httpx.Response:
            return httpx.post(
                req["url"], json=req["json"], headers=req["headers"], timeout=timeout
            )

        if max_seconds is None:
            resp = _do_request()
        else:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_do_request)
                try:
                    resp = future.result(timeout=max_seconds)
                except concurrent.futures.TimeoutError as exc:
                    future.cancel()
                    raise RuntimeError(
                        f"LLM call exceeded hard budget of {max_seconds:.1f}s"
                    ) from exc
            finally:
                # Don't block on a straggling request thread; let it finish
                # in the background and be reaped when the response arrives.
                executor.shutdown(wait=False)
        if provider == "anthropic" and resp.status_code == 429:
            # Wire the LIVE 429 → cooldown block (GAP-P7-DEF-A §5.4). A genuine
            # subscription-quota 429 (oauth_token or api_key) records a block and
            # raises an explicit QuotaExhaustedError → honest HTTP 429; it is
            # NEVER swallowed to a fixture nor rerouted to another credential.
            if _anthropic_429_is_subscription_quota(resp):
                expires_at = _quota_block_expiry()
                if ctx_user_id is not None:
                    try:
                        from app.repositories.user_provider_credential import (
                            AgentQuotaBlockRepository,
                        )

                        AgentQuotaBlockRepository().set_block(
                            ctx_user_id, provider,
                            expires_at=expires_at,
                            reason="subscription_quota_exceeded",
                        )
                    except Exception as exc:  # noqa: BLE001 — never hide the 429
                        logger.warning(
                            "failed to record %s quota block: %s",
                            provider, type(exc).__name__,
                        )
                raise QuotaExhaustedError(
                    provider, expires_at=expires_at,
                    reason="subscription_quota_exceeded",
                )
            # Transient per-minute rate limit: fall through to the retryable
            # RuntimeError below (the existing single retry may apply). Still
            # NEVER rerouted to a different credential (ADR-PC-2).
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM provider HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        if provider == "anthropic":
            return parse_anthropic_response(body)
        if "error" in body:
            raise RuntimeError(f"LLM provider error: {body['error']}")
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        return content
