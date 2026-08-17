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
import random
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

_DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "llm"

#: Last-resort model retried once when a SYSTEM-DEFAULT primary 404s / 429s
#: (D-0014). Also the ultimate tier default for an unknown/unset tier.
#:
#: OWNER DIRECTIVE (MODEL-DEFAULT, 2026-08-14): the system default is the
#: operator's Anthropic Pro subscription, NEVER OpenRouter. So this is a bare
#: ``claude-*`` id (``resolve_provider`` -> ``"anthropic"``) — the cheapest,
#: always-served tier, which bounds a runaway retry and keeps the un-chosen
#: system-default one-retry on the SAME provider as its primary (opus -> haiku).
#: OpenRouter is reached ONLY via an explicit per-agent slash-model pick, never
#: as a default or automatic fallback.
#:
#: NOTE — this is DISTINCT from the ADMIN-ONLY OpenRouter free-model rescue
#: (:data:`_DEFAULT_ADMIN_FREE_FALLBACK_MODELS`, the nvidia ``:free`` pair): that
#: rescue is env-gated, admin-scoped, and engages only on an HTTP 402
#: insufficient-credits signal — it does NOT read this constant.
FALLBACK_MODEL = "claude-haiku-4-5"

#: Per-tier system-default model ids, applied when ``AETHER_MODEL_<TIER>`` is
#: unset so behaviour is correct WITHOUT env too (the served ``.env`` flip is a
#: documented config edit applied at land time; these code defaults must agree
#: with it). Every id is a bare ``claude-*`` the operator's Anthropic
#: subscription serves (MODEL-DEFAULT-SCOUT D1, == the app's static anthropic
#: catalog): reasoning/heavy -> opus-class, structured -> sonnet-class,
#: fast/light -> haiku-class. No tier default is ever an OpenRouter id.
_DEFAULT_MODEL_BY_TIER = {
    "REASONING": "claude-opus-4-8",
    "HEAVY": "claude-opus-4-8",
    "STRUCTURED": "claude-sonnet-4-6",
    "FAST": "claude-haiku-4-5",
    "LIGHT": "claude-haiku-4-5",
}


def get_fallback_model() -> str:
    """Fallback model id (bare ``claude-*`` by default), env-overridable."""
    return os.environ.get("AETHER_MODEL_FALLBACK", FALLBACK_MODEL)


#: FREE OpenRouter models used by the ADMIN-ONLY insufficient-credits rescue
#: (see :func:`get_admin_free_fallback_models` / :meth:`LLMClient._auto`). Both
#: ids were verified live on the app's own zero-credit key on 2026-07-29 —
#: HTTP 200 with clean, coherent, correctly-terminated prose — while paid models
#: 402'd on the SAME key at the same moment (OpenRouter's credit gate is
#: per-model-price, not account-wide).
#:
#: ORDER IS EVIDENCE-BASED (QA-FAIL-01, probe artifact
#: ``uat/reports/evidence/models-live/free-chain-shaping-probe.txt``,
#: 2026-07-29): under the SHAPED request body (see
#: :func:`_build_openrouter_request`) the ultra model returned valid strict JSON
#: in 8 of 9 live attempts on the real deployed cover-letter prompt — its single
#: miss a transient upstream 502, not a refusal — while the super model managed
#: 4 of 9 (its misses were prose refusals, not timeouts). The chain therefore
#: leads with the more RELIABLE model; the faster-but-flakier one still follows
#: it, because with the shaping in place a whole extra attempt now fits inside
#: the budget that one unshaped attempt used to consume on its own.
_DEFAULT_ADMIN_FREE_FALLBACK_MODELS = (
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)


def get_admin_free_fallback_models() -> list[str]:
    """Free model ids the ADMIN account's chain falls through to on an HTTP 402.

    Configured via ``AETHER_ADMIN_FREE_FALLBACK_MODELS`` (comma-separated). The
    free catalog churns, so the list is env-overridable; it defaults to the
    live-verified ids above so the rescue works out of the box. Setting the var
    to an EMPTY value is the kill switch: no rescue for anyone, i.e. exactly the
    pre-feature behaviour.
    """
    raw = os.environ.get("AETHER_ADMIN_FREE_FALLBACK_MODELS")
    if raw is None:
        return list(_DEFAULT_ADMIN_FREE_FALLBACK_MODELS)
    return [model.strip() for model in raw.split(",") if model.strip()]


#: Completion-token cap applied to ADMIN free-chain attempts only. The real
#: cover-letter JSON measured 93-489 completion tokens live with reasoning off,
#: so 2000 is ~4x headroom — generous enough that the cap never truncates a
#: legitimate letter, tight enough to bound a runaway.
_DEFAULT_ADMIN_FREE_FALLBACK_MAX_TOKENS = 2000


def get_admin_free_fallback_max_tokens() -> int:
    """``max_tokens`` for ADMIN free-chain attempts (env-overridable).

    Configured via ``AETHER_ADMIN_FREE_FALLBACK_MAX_TOKENS``. A malformed or
    non-positive value falls back to the default rather than taking the rescue
    path down with a ValueError.
    """
    raw = os.environ.get("AETHER_ADMIN_FREE_FALLBACK_MAX_TOKENS")
    if raw is None:
        return _DEFAULT_ADMIN_FREE_FALLBACK_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_ADMIN_FREE_FALLBACK_MAX_TOKENS
    return value if value > 0 else _DEFAULT_ADMIN_FREE_FALLBACK_MAX_TOKENS


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

#: How many EXTRA times a single model is re-tried when its live response is
#: well-formed HTTP-wise but the caller's validator rejects it (malformed /
#: truncated JSON). Bounded so a persistently-garbled backend is never hammered
#: (ML-pipeline-001). A same-model re-draft on malformed content is NOT model
#: substitution (ADR-ML-3), so it is allowed even for a user-chosen single-model
#: chain; a genuine call EXCEPTION still falls straight through to the next model
#: with no same-model retry (the honest-failure contract is unchanged).
_MALFORMED_JSON_RETRIES = 1


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


def remaining_budget_seconds() -> float:
    """Seconds left in the CURRENTLY-ACTIVE shared LLM budget window.

    Returns ``0.0`` when no :func:`shared_budget` window is active, so an
    OPTIONAL extra live call (e.g. the cover letter's quality-improvement
    pass) never fires outside a window that has actually reserved time for it.
    Read-only: unlike ``LLMClient._remaining_budget`` it never ARMS a deadline
    as a side effect, so merely asking cannot start a clock.
    """
    shared = _shared_deadline.get()
    if shared is None:
        return 0.0
    return max(0.0, shared - time.monotonic())


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

# --------------------------------------------------------------------------
# CRITICAL-3 — upstream FAILURE CLASSES.
#
# Production, 2026-08-02: OpenRouter returned HTTP 402 (out of credits) and the
# chain-exhaustion raise below erased that fact, surfacing every 402 as a bare
# ``LLMUnavailableError`` -> "The AI service is temporarily unavailable. Please
# try again in a moment." Both halves of that sentence were false, and the
# board-sweep autopilot believed them: it re-attempted the SAME 10 jobs every
# 10-minute cron tick — 37 failed tailor runs per job, 60/hour, indefinitely,
# every one a real POST to a metered API.
#
# A failure class is now carried from the transport all the way to the HTTP
# response and to the autopilot's breaker:
#   * ``insufficient_credits`` (402) and ``auth`` (401/403) are NOT retryable —
#     the upstream has already answered the question and asking again costs
#     money and time while changing nothing. Fail fast, say why.
#   * everything else (429, 5xx, timeout, network, malformed content) IS
#     retryable — back off exponentially with jitter and try again.
# --------------------------------------------------------------------------
LLM_FAILURE_RETRYABLE = "retryable"
LLM_FAILURE_INSUFFICIENT_CREDITS = "insufficient_credits"
LLM_FAILURE_AUTH = "auth"

#: Classes for which further attempts are pointless until a human acts.
LLM_NON_RETRYABLE_FAILURE_CLASSES = frozenset(
    {LLM_FAILURE_INSUFFICIENT_CREDITS, LLM_FAILURE_AUTH}
)

#: Honest, secret-free user messages for the non-retryable classes. Unlike
#: :data:`LLM_UNAVAILABLE_USER_MESSAGE` these say what is wrong and what fixes
#: it, and explicitly deny that retrying helps — the autopilot and the UI both
#: render this text, so it must never invite a retry that cannot succeed.
LLM_INSUFFICIENT_CREDITS_USER_MESSAGE = (
    "The AI provider rejected the request because the account is out of "
    "credits. Automated runs are paused until the balance is topped up — "
    "retrying now will not help."
)
LLM_AUTH_FAILED_USER_MESSAGE = (
    "The AI provider rejected the configured credential (authentication "
    "failed). Automated runs are paused until the API key is corrected in "
    "Agent Settings — retrying now will not help."
)

_LLM_FAILURE_USER_MESSAGES = {
    LLM_FAILURE_INSUFFICIENT_CREDITS: LLM_INSUFFICIENT_CREDITS_USER_MESSAGE,
    LLM_FAILURE_AUTH: LLM_AUTH_FAILED_USER_MESSAGE,
}


class LLMUnavailableError(RuntimeError):
    """Raised when the live LLM backend failed AND no fixture fallback exists.

    Routers convert this into a clean HTTP 503 with an honest, secret-free
    user message — :func:`llm_failure_user_message`, which is
    :data:`LLM_UNAVAILABLE_USER_MESSAGE` for the retryable class and a
    class-specific actionable message otherwise.

    ``failure_class`` defaults to :data:`LLM_FAILURE_RETRYABLE`, so every
    pre-existing raise site (malformed JSON, budget exhaustion, unclassified
    transport errors) keeps its exact previous meaning and message.
    """

    def __init__(
        self,
        *args: Any,
        failure_class: str = LLM_FAILURE_RETRYABLE,
        provider: str | None = None,
        expires_at: Any = None,
    ) -> None:
        super().__init__(*args)
        self.failure_class = failure_class
        self.provider = provider
        self.expires_at = expires_at

    @property
    def retryable(self) -> bool:
        return self.failure_class not in LLM_NON_RETRYABLE_FAILURE_CLASSES


class LLMCircuitOpenError(LLMUnavailableError):
    """Raised INSTEAD of making a live call while the circuit breaker is open.

    A subclass of :class:`LLMUnavailableError` so every existing handler
    (routers' 503 + refund, the worker's honest degrade) treats it correctly
    with no new plumbing — but it carries the class that tripped the breaker
    and the instant the cooling period ends, so the message stays honest and
    the autopilot stops instead of grinding.
    """


class ProviderAuthError(RuntimeError):
    """Raised when a provider rejects the CREDENTIAL itself (HTTP 401/403).

    Narrower than the generic ``RuntimeError`` the ``status_code >= 400``
    branch used to raise, and carrying the same message, so the only behaviour
    that changes is that the chain can now tell "this key is wrong" (no amount
    of retrying fixes it) from "this call failed" (retrying might).
    """

    def __init__(self, message: str, *, provider: str = "", status_code: int = 401) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


def classify_llm_failure(exc: BaseException | None) -> str:
    """The failure class of a transport-level exception.

    Conservative by construction: ONLY the two exception types the transport
    raises deliberately for 402 and 401/403 are non-retryable. Anything else —
    including an unrecognised ``RuntimeError`` — stays retryable, because
    wrongly declaring a transient blip permanent would stall a user's board for
    the whole cooling period.
    """
    if isinstance(exc, InsufficientCreditsError):
        return LLM_FAILURE_INSUFFICIENT_CREDITS
    if isinstance(exc, ProviderAuthError):
        return LLM_FAILURE_AUTH
    if isinstance(exc, LLMUnavailableError):
        return exc.failure_class
    return LLM_FAILURE_RETRYABLE


def llm_failure_user_message(exc: BaseException | None) -> str:
    """The honest, secret-free user message for an LLM failure.

    Never exposes the raw exception text (which carries prompt names, 'hard
    budget', provider bodies); routers use this for BOTH the 503 detail and
    the ``AgentRun.error`` audit column so the owner-visible record and the
    HTTP response can never disagree.
    """
    return _LLM_FAILURE_USER_MESSAGES.get(
        classify_llm_failure(exc), LLM_UNAVAILABLE_USER_MESSAGE
    )


class InsufficientCreditsError(RuntimeError):
    """Raised when OPENROUTER returns HTTP 402 — the account is out of credits.

    Deliberately a plain :class:`RuntimeError` subclass carrying the SAME message
    the generic ``resp.status_code >= 400`` branch used to raise, so every
    existing handler (``_auto``'s broad ``except Exception``, the routers'
    503 mapping, the honest-failure/refund path) keeps behaving byte-for-byte as
    before. The subclass exists only so the chain can DISTINGUISH "we cannot pay
    for this model" (rescuable with a $0-priced model on the same credential)
    from "this model/endpoint failed" (404/429/5xx — not rescuable that way).

    It is NOT a :class:`QuotaExhaustedError`: that one means a subscription's
    provider quota is spent and must surface as an honest 429 with no
    substitution of any kind. A 402 stays a 503-class failure.
    """

    def __init__(self, message: str, *, provider: str = "openrouter") -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = 402


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

#: The model id that ACTUALLY served the most recent SUCCESSFUL live call in
#: this context — an OBSERVATION, written by :meth:`LLMClient._call_live`, never
#: by a caller (the inverse direction of every other ContextVar in this module).
#:
#: Why it exists (ML-W14): the model a run is BILLED against was resolved from
#: config (``routers/agents.py::_model_for_agent``), i.e. it is intent, not
#: observation. When the ADMIN free-chain rescue substitutes a $0 model after an
#: OpenRouter 402 (:meth:`_extend_chain_with_admin_free_models`), the id that
#: served the run existed only as a local in :meth:`_auto` and was discarded, so
#: a free run was costed at the paid model's published price — inflating
#: ``AgentRun.costUsd``, ``GET /agents/stats`` ROI and the USD spend cap.
#:
#: A ContextVar (rather than a richer return type) keeps ``complete``/
#: ``complete_json`` returning ``str``/parsed JSON exactly as every existing
#: caller and every strict-signature test double expects.
_last_served_model: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_llm_last_served_model", default=None
)

#: REAL accumulated request/response character counts (+ call count) across
#: every successful live call in this context — a sibling observation to
#: ``_last_served_model``, same lifecycle, published at the identical two call
#: sites (MF-1, wave5-w2122 review of QA3-F-05). Exists because a run can make
#: SEVERAL successful calls before an outcome is decided (the cover-letter
#: corrective loop's draft + retry + retry2 — each a real, accepted LLM
#: response) and a caller costing that run off a single locally-authored
#: string (e.g. an English refusal message built after every attempt was
#: rejected) would understate the actual spend by the number of attempts.
#: ``None`` outside an open :func:`served_model_capture` scope.
_accumulated_usage: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "aether_llm_accumulated_usage", default=None
)

#: WHY the run moved off its primary model, when it did — the third sibling of
#: ``_last_served_model`` / ``_accumulated_usage``, on the same lifecycle.
#:
#: Why it exists (R-5): a served-model substitution is already recorded and
#: correctly costed, and is invisible to the user. Rendering "served by fallback"
#: without a reason would just move the mystery, so the reason is PUBLISHED BY
#: THE MECHANISM THAT ENGAGED — never inferred later from a model id, which
#: could not tell an admin credit rescue from a timeout.
#:
#: Two-phase on purpose. ``_staged`` holds the reason the moment an attempt
#: fails; it is PROMOTED to ``_last_fallback_reason`` only when a LATER model
#: actually succeeds. A chain that fails outright therefore publishes nothing —
#: there was no fallback, only a failure, and the caller already reports that.
_staged_fallback_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_llm_staged_fallback_reason", default=None
)
_last_fallback_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_llm_last_fallback_reason", default=None
)


@contextmanager
def served_model_capture() -> Iterator[None]:
    """Open a fresh served-model + accumulated-usage observation scope for ONE
    run.

    Contract:

    - Entering RESETS both observations, so a value observed by an earlier
      run in the same thread/task context can never be read as if it
      belonged to this one.
    - :func:`get_last_served_model` is valid INSIDE this scope, immediately
      after a successful call; on exit the previous scope's value is restored.
    - The served-model value reflects the LAST successful live call made
      inside the scope. A run that makes several calls therefore reports the
      model that served its final one — the same granularity as the single
      model id a run is recorded against today.
    - :func:`get_accumulated_usage` reflects EVERY successful call made so far
      in the scope (unlike the served-model, which is last-call-only) — see
      that function.
    - ``None`` means "nothing observed": replay/fixture mode, a deterministic
      agent that never calls the LLM, a run whose every attempt failed, or a
      call made on a thread this context was not copied into. Callers MUST
      treat ``None`` as "no observation" and keep their existing behaviour —
      never as a licence to guess which model served or invent a usage figure.
    """
    model_token = _last_served_model.set(None)
    usage_token = _accumulated_usage.set(None)
    staged_token = _staged_fallback_reason.set(None)
    reason_token = _last_fallback_reason.set(None)
    try:
        yield
    finally:
        _last_served_model.reset(model_token)
        _accumulated_usage.reset(usage_token)
        _staged_fallback_reason.reset(staged_token)
        _last_fallback_reason.reset(reason_token)


def _accumulate_usage(chars_in: int, chars_out: int) -> None:
    """Add one successful call's REAL request/response char counts to the
    active scope's running total. A no-op outside an open
    :func:`served_model_capture` scope (mirrors ``_publish_served_model``'s own
    silent no-op there — this module never raises for an absent scope)."""
    current = _accumulated_usage.get()
    base = current or {"charsIn": 0, "charsOut": 0, "calls": 0}
    _accumulated_usage.set(
        {
            "charsIn": base["charsIn"] + max(0, chars_in),
            "charsOut": base["charsOut"] + max(0, chars_out),
            "calls": base["calls"] + 1,
        }
    )


def get_last_served_model() -> str | None:
    """The model id the PROVIDER reported as having served the most recent
    successful live call in the active :func:`served_model_capture` scope, or
    ``None`` when nothing was observed (see that function's contract)."""
    return _last_served_model.get()


def _stage_fallback_reason(failed_model: str, exc: BaseException) -> None:
    """Note WHY ``failed_model`` was abandoned, pending a later success.

    The text names the model that failed and the CLASS the failure was already
    classified as by ``classify_llm_failure`` — no new taxonomy, no provider
    payload (which could carry account detail), no secret. It becomes a
    user-visible chip, so it says what happened and nothing more.
    """
    try:
        failure_class = classify_llm_failure(exc)
    except Exception:  # noqa: BLE001 — classification must never break a run
        failure_class = "unknown"
    _staged_fallback_reason.set(
        f"primary model {failed_model} was unavailable ({failure_class})"
    )


def _promote_fallback_reason() -> None:
    """A later model succeeded: the staged reason is now a real fallback."""
    staged = _staged_fallback_reason.get()
    if staged:
        _last_fallback_reason.set(staged)


def get_last_fallback_reason() -> str | None:
    """Why the active :func:`served_model_capture` scope ended up on a model
    other than its primary, or ``None`` when no fallback engaged.

    ``None`` also covers "the whole chain failed" — nothing was served, so
    nothing fell back. Callers MUST treat ``None`` as "no reason observed" and
    never invent one (R-5: the fields exist to remove a mystery, not to move it).
    """
    return _last_fallback_reason.get()


def get_accumulated_usage() -> dict[str, int] | None:
    """The REAL accumulated request/response character counts + call count
    across every successful live call made so far in the active
    :func:`served_model_capture` scope (MF-1), or ``None`` when the scope
    isn't open or no call has yet succeeded in it. Keys: ``charsIn``,
    ``charsOut``, ``calls``. Must be read INSIDE the scope, before it exits —
    ``served_model_capture``'s ``finally`` resets it on unwind, same as
    :func:`get_last_served_model`."""
    return _accumulated_usage.get()


def _publish_served_model(body: object, requested_model_id: str) -> None:
    """Record which model served the call just completed.

    The provider's own ``model`` field is authoritative — every live OpenRouter
    200 captured by the free-model probe carries it (evidence:
    ``uat/reports/evidence/free-model-fallback/free-model-*-response.json``),
    and the Anthropic Messages API returns it too. When a provider omits it,
    the id we actually put on the wire is the honest answer; nothing is ever
    inferred from a log line or a chain candidate.
    """
    served = body.get("model") if isinstance(body, dict) else None
    if not isinstance(served, str) or not served.strip():
        served = requested_model_id
    _last_served_model.set(served.strip())


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

    MODEL-SUB-QUOTA: whatever the source (per-run override, env default, code
    default), a Claude id is returned in its BARE form — the spelling that
    routes to the operator's Anthropic subscription. Same model either way; only
    the redundant OpenRouter namespace is dropped (:func:`normalize_model_id`).
    """
    tier_key = tier.upper()
    if tier_key in _USER_OVERRIDABLE_TIERS:
        override = _user_model_context.get()
        if override:
            return normalize_model_id(override)
    return normalize_model_id(
        os.environ.get(
            f"AETHER_MODEL_{tier_key}",
            _DEFAULT_MODEL_BY_TIER.get(tier_key, FALLBACK_MODEL),
        )
    )


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


#: A CLAUDE model id in either spelling the app can be handed: the direct
#: native id (``claude-opus-4-8``) or OpenRouter's namespaced form
#: (``anthropic/claude-opus-4-8``). Case-insensitive because a picker/catalog
#: id, an env default and a hand-typed pin do not agree on case. The
#: ``anthropic/`` namespace ALONE is deliberately not enough — OpenRouter could
#: serve a non-Claude model under it, and that model is genuinely OpenRouter's.
_CLAUDE_MODEL_RE = re.compile(r"^(?:anthropic/)?claude-", re.IGNORECASE)

#: The OpenRouter namespace stripped from a Claude id to reach the direct
#: Anthropic Messages API. Stripping the NAMESPACE is not a model change — the
#: remaining id names the same model, served by its own vendor (ADR-ML-3 is
#: about serving a DIFFERENT model, which this never does).
_ANTHROPIC_NAMESPACE_RE = re.compile(r"^anthropic/", re.IGNORECASE)


def is_claude_model(model: str | None) -> bool:
    """Whether ``model`` names a Claude model in EITHER spelling.

    OWNER DIRECTIVE (MODEL-SUB-QUOTA, 2026-08-17): "all the claude requests
    [must] use my Anthropic Pro Subscription quota instead of consuming extra
    credits via an API_KEY including for openrouter". The two spellings name one
    model, so they must resolve to one provider — the subscription.
    """
    return bool(_CLAUDE_MODEL_RE.match((model or "").strip()))


def normalize_model_id(model: str | None) -> str:
    """The id the app actually calls a model by, at the routing seam.

    For a Claude id in OpenRouter's namespaced spelling this strips the
    ``anthropic/`` prefix so the native Messages API receives the bare id it
    understands (``anthropic/claude-opus-4-8`` -> ``claude-opus-4-8``). SAME
    model, direct provider — never a substitution. Every other id (including a
    non-Claude ``anthropic/…`` model, which really is OpenRouter's) is returned
    unchanged apart from surrounding whitespace.
    """
    m = (model or "").strip()
    if is_claude_model(m):
        return _ANTHROPIC_NAMESPACE_RE.sub("", m, count=1)
    return m


class ClaudeOnOpenRouterError(RuntimeError):
    """A Claude model reached the OpenRouter transport. Never expected.

    Belt-and-braces for the MODEL-SUB-QUOTA directive: :func:`resolve_provider`
    already sends every Claude id to the direct Anthropic path, so this is the
    second, independent wall — raised INSTEAD of building a request, so no code
    path (a future caller that bypasses routing, a hand-built chain) can spend
    OpenRouter credit on a model the operator's subscription serves.
    """


def resolve_provider(model: str) -> str:
    """Map a model id to its billing provider: ``'anthropic'`` or ``'openrouter'``.

    ONE model id resolves to ONE provider and one credential source.

    * ANY Claude id — bare ``claude-…`` OR namespaced ``anthropic/claude-…`` —
      resolves ``'anthropic'`` and is served DIRECTLY by the operator's Anthropic
      subscription (MODEL-SUB-QUOTA, OWNER DIRECTIVE 2026-08-17). The two
      spellings name the same model; routing them to different billing accounts
      is what made a Claude pick silently consume OpenRouter credit.
    * Every other ``vendor/model`` id is OpenRouter-served and OpenRouter-billed
      — the slash rule is UNCHANGED for them (``deepseek/…``, ``qwen/…``,
      ``openai/…``, and even a hypothetical non-Claude ``anthropic/…`` model,
      which OpenRouter really would be serving).

    HISTORY. The prior rule was slash-first: any namespaced id billed through
    OpenRouter, which was the correct answer to GAP-P7-MODEL-CHOICE-001's
    question ("bill the credential the user chose the model with") but the wrong
    answer to the owner's: a Claude model must never be bought twice. The
    billing separation that fix protects is intact — nothing here reroutes a
    NON-Claude model, and the credential for an anthropic-resolved model is
    still strictly the Anthropic one (no cross-provider fallback, ADR-PC-2).

    Pure function so the router, verify endpoint and transport all agree on one
    resolution.
    """
    m = (model or "").strip().lower()
    if is_claude_model(m):
        return "anthropic"
    if "/" in m:  # any other vendor/model id is OpenRouter-served + billed
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


#: OPERATOR-SCOPED agent keys (ADR-AGI-3 Decision 3 / U-AGI F7). An agent named
#: here is the OPERATOR's own role — today the in-app Supervisor — not a
#: subscriber's content generation. Its credential resolution is deliberately
#: DIFFERENT in both directions, and both are enforced in
#: :func:`resolve_user_credential`:
#:
#: * it consumes ONLY the operator-scoped slot (the deployment-wide
#:   ``ProviderCredential`` row, then provider-scoped env). A subscriber's own
#:   key is never reachable from it — that would bill the wrong party for the
#:   operator's planning.
#: * it is the ONE role permitted to consume the operator's SUBSCRIPTION row
#:   (the owner's Anthropic Max/Pro session connected through the admin-gated
#:   PKCE flow), because that binding is the operator mandate itself.
#:
#: Kept as DATA next to the resolver so the enforcement point and the rule are
#: one thing. Pinned equal to ``routers.agents._ROLE_MODEL_BACKENDS`` by a test,
#: so a new role cannot be assigned a model without also being scoped here.
OPERATOR_SCOPED_AGENT_KEYS = frozenset({"supervisor"})

#: Auth modes that identify a CONSUMER-SUBSCRIPTION credential rather than a
#: metered API key. ``oauth_token`` is the live one (a pasted Claude Code token
#: or the admin PKCE session); ``subscription_oauth`` is the legacy, already
#: unusable form. These name the credentials the ``allow_operator_subscription``
#: wall can scope OFF (:func:`resolve_credential`).
#:
#: MODEL-DEFAULT reconciliation (OWNER DIRECTIVE, 2026-08-14): the wall is
#: RETAINED as a general capability, but user-content generation is NO LONGER
#: walled off from the operator's subscription row — that subscription IS the
#: intended system default ("the system default must be anthropic pro subs
#: quota"). A single subscriber can no longer drain it because every metered run
#: is bounded per-user by the EXISTING quota + spend cap (agents._record_run),
#: not by a credential wall. Only OpenRouter stays user-choice-only.
_SUBSCRIPTION_AUTH_MODES = frozenset({"oauth_token", "subscription_oauth"})


def resolve_credential(
    provider: str, *, allow_operator_subscription: bool = True
) -> "ProviderCredentialResolution | None":
    """Resolve ``provider``'s credential: DB row FIRST, then legacy env fallback.

    Returns ``None`` when neither exists — the caller must then raise an honest,
    provider-named error and must NOT reroute to the other provider.

    ``allow_operator_subscription`` (default True — every pre-existing caller is
    unchanged) is the F8 wall: pass ``False`` and a deployment-wide row holding a
    CONSUMER SUBSCRIPTION token is skipped, falling through to the env fallback
    and then to an honest ``None``. A deployment-wide API KEY is untouched by
    this: that is metered API billing and stays exactly as it shipped.
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
        if not allow_operator_subscription and auth_mode in _SUBSCRIPTION_AUTH_MODES:
            logger.info(
                "operator subscription credential for '%s' is not available to "
                "user-content generation; falling through to a provider-scoped "
                "source", provider,
            )
            row = None
        # A pre-existing subscription_oauth row is no longer usable (GAP-AUTH-001):
        # skip it and fall through to the env fallback / honest no-credential.
        elif _resolution_is_supported(provider, auth_mode):
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


#: How long an ``isAdmin`` lookup is trusted, in seconds. The flag gates the
#: admin-only free-model rescue only; being stale by <= this window is
#: acceptable and saves a DB round-trip on EVERY live LLM call.
_ADMIN_FLAG_TTL_SECONDS = 60.0

#: ``userId -> (isAdmin, monotonic expiry)``. Process-local; a plain dict is
#: enough (CPython dict get/set are atomic, so a race costs at most one extra
#: query, never a wrong answer). Bounded below so a long-lived process with many
#: users cannot grow it without limit.
_admin_flag_cache: dict[str, tuple[bool, float]] = {}
_ADMIN_FLAG_CACHE_MAX = 1000


def _user_is_admin(user_id: str) -> bool:
    """Is this user the ADMIN account? Fresh DB read, cached for a short TTL.

    Mirrors :func:`_lookup_agent_credential_ref`: a raw, self-contained query
    keyed by the ``_user_cred_context`` user id, so no call-site signature in
    ``routers/agents.py`` or ``workers/tasks.py`` has to change (the worker path
    only ever has the bare user id anyway). Fails CLOSED and silently: any DB
    error means "not admin" and is NOT cached, so an outage can neither grant the
    rescue nor break a run.
    """
    now = time.monotonic()
    cached = _admin_flag_cache.get(user_id)
    if cached is not None and now < cached[1]:
        return cached[0]
    try:
        from app.db import get_connection, rows_to_dicts

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT "isAdmin" FROM "User" WHERE "id" = %s', (user_id,))
                rows = rows_to_dicts(cur)
    except Exception as exc:  # noqa: BLE001 — missing column/table/DB down -> not admin
        logger.debug("isAdmin lookup failed (treating as non-admin): %s", exc)
        return False
    is_admin = bool(rows[0].get("isAdmin")) if rows else False
    if len(_admin_flag_cache) >= _ADMIN_FLAG_CACHE_MAX:
        _admin_flag_cache.clear()
    _admin_flag_cache[user_id] = (is_admin, now + _ADMIN_FLAG_TTL_SECONDS)
    return is_admin


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

    STRUCTURAL SEPARATION (U-AGI F7/F8, ADR-AGI-3 Decision 3). Two rules are
    enforced here, and here only, because this is the one seam every live call
    passes through:

    * **F7** — an OPERATOR-SCOPED role (:data:`OPERATOR_SCOPED_AGENT_KEYS`)
      resolves ONLY the operator slot: steps 1 and 2 are skipped entirely, so a
      subscriber's own key can never fund the operator's planning, and an empty
      operator slot is an honest ``None`` rather than a silent substitution.
    * **F8** — everything else is USER-CONTENT generation. It resolves the user's
      OWN credential first (steps 1-2); with none, it reaches the deployment-wide
      row (step 3). MODEL-DEFAULT reconciliation (OWNER DIRECTIVE, 2026-08-14):
      that row — the operator's Anthropic Pro subscription — IS the intended
      system default for user-content ("the system default must be anthropic pro
      subs quota"), so the P1-A hard wall that returned ``None`` here is lifted.
      No single subscriber can drain it: every metered run is bounded per-user by
      the EXISTING quota + spend cap (``agents._record_run``), which fires BEFORE
      the model call regardless of which provider serves it. OpenRouter is NOT
      reachable from this path — it is per-agent user-choice only.

    Both rules are one-directional and neither introduces a new provider path:
    the no-cross-provider invariant is untouched.
    """
    if agent_key in OPERATOR_SCOPED_AGENT_KEYS:
        return resolve_credential(provider)
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
    # 3 + 4. Deployment-wide DB row, then legacy env. This branch is USER-CONTENT
    # generation by definition (an operator role returned above). MODEL-DEFAULT
    # reconciliation (OWNER DIRECTIVE, 2026-08-14): the operator's Anthropic
    # subscription IS the intended system default here — the P1-A wall that
    # scoped it OFF is lifted, and a runaway is bounded per-user by the quota +
    # spend cap in ``agents._record_run`` (which fires before the model call),
    # not by withholding the credential. OpenRouter is never reached from here.
    return resolve_credential(provider)


def _is_operator_scoped_run() -> bool:
    """Whether the ACTIVE run belongs to an operator-scoped role (F7).

    Read from the same ``user_credential_context`` the credential resolver
    reads, so the model chain and the credential can never disagree about whose
    run this is.
    """
    ctx = _user_cred_context.get()
    if ctx is None:
        return False
    return ctx[1] in OPERATOR_SCOPED_AGENT_KEYS


def operator_fallback_chain() -> tuple[str, ...]:
    """The operator role's ordered fallback models, from configuration.

    ADR-AGI-3 Decision 3 binds the Supervisor to the operator's Anthropic
    credential and allows a fallback chain (OpenRouter → Abacus → Google) ONLY
    on quota/credit exhaustion. The ORDER is an operator decision, so it lives in
    ``AETHER_OPERATOR_FALLBACK_MODELS`` (comma-separated model ids, in order)
    rather than in source — and each id routes through the unchanged
    :func:`resolve_provider`, so the billing separation the chain crosses is the
    same one every other model id crosses.

    Empty by default. An unconfigured chain means the operator role fails
    honestly on its primary rather than being rerouted onto a payer nobody
    chose, and an empty string is the kill switch.
    """
    raw = os.environ.get("AETHER_OPERATOR_FALLBACK_MODELS")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


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


# --------------------------------------------------------------------------
# CRITICAL-3 — retry backoff (exponential, full jitter) + circuit breaker.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# RT-005 — per-model short cooldown after a SUSTAINED run of ambiguous 429s.
#
# Live incident (2026-08-16 14:15-14:25Z): the subscription credential served
# sustained HTTP 429s whose body carried no quota phrase and no long
# retry-after, so ``_anthropic_429_is_subscription_quota`` (correctly,
# conservatively) classified every one as transient — and the chain paid a
# doomed live call + backoff on EVERY attempt for over ten minutes. This
# tracker adds the missing middle: after ``AETHER_MODEL_429_STREAK`` (default
# 4) consecutive 429s for one model with no success in between, that model
# cools for ``AETHER_MODEL_429_COOLDOWN_SECONDS`` (default 900 — 15 minutes,
# deliberately SHORT so a wrong guess can never pause anyone for hours the
# way the quota block would). While cooling, an attempt raises the same
# 429-shaped error the live call would have produced — through the IDENTICAL
# handling path (operator-chain rules, user-chain rules, fallback staging,
# disclosure) — just without the network call or the pointless backoff sleep.
# A success for the model clears its streak. In-process state only: each
# api/worker process learns independently, which is exactly the scope a
# burst-limiter needs (no schema, no cross-process coordination to go wrong).
# --------------------------------------------------------------------------

_RATE_LIMIT_STREAKS: dict[str, dict[str, float]] = {}
_RATE_LIMIT_STREAKS_LOCK = threading.Lock()

#: RT-006 — the one bounded same-model retry window for a sole-model chain
#: that hit a real 429 (jittered so concurrent runs don't re-collide).
_SAME_MODEL_429_RETRY_DELAY_MIN = 2.0
_SAME_MODEL_429_RETRY_DELAY_MAX = 5.0


def get_model_429_streak_threshold() -> int:
    """Consecutive 429s before a model cools (``AETHER_MODEL_429_STREAK``)."""
    try:
        n = int(os.environ.get("AETHER_MODEL_429_STREAK", "4"))
    except ValueError:
        return 4
    return max(2, n)


def get_model_429_cooldown_seconds() -> float:
    """Cooldown length (``AETHER_MODEL_429_COOLDOWN_SECONDS``, default 900)."""
    try:
        s = float(os.environ.get("AETHER_MODEL_429_COOLDOWN_SECONDS", "900"))
    except ValueError:
        return 900.0
    return max(30.0, s)


def _exc_is_http_429(exc: BaseException) -> bool:
    return "HTTP 429" in str(exc)


def _note_model_429(model: str) -> None:
    """Record one real 429 for ``model``; open its cooldown at the threshold."""
    now = time.monotonic()
    with _RATE_LIMIT_STREAKS_LOCK:
        entry = _RATE_LIMIT_STREAKS.setdefault(model, {"count": 0.0, "cooled_until": 0.0})
        entry["count"] += 1
        if entry["count"] >= get_model_429_streak_threshold() and entry["cooled_until"] <= now:
            entry["cooled_until"] = now + get_model_429_cooldown_seconds()
            logger.warning(
                "model %s entered a %.0fs rate-limit cooldown after %d consecutive "
                "429s — attempts will fail fast (no live call) until it expires",
                model, get_model_429_cooldown_seconds(), int(entry["count"]),
            )


def _clear_model_429(model: str) -> None:
    with _RATE_LIMIT_STREAKS_LOCK:
        _RATE_LIMIT_STREAKS.pop(model, None)


def _model_cooling_seconds_left(model: str) -> float:
    with _RATE_LIMIT_STREAKS_LOCK:
        entry = _RATE_LIMIT_STREAKS.get(model)
        if not entry:
            return 0.0
        return max(0.0, entry["cooled_until"] - time.monotonic())


def get_llm_retry_backoff_base_seconds() -> float:
    """Base delay of the exponential backoff between RETRYABLE live attempts.

    ``AETHER_LLM_RETRY_BACKOFF_BASE_SECONDS`` (default 0.5s). ``0`` disables
    the wait entirely — kept as an explicit operator escape hatch, never the
    default, because "no wait" is exactly the behaviour that let a failing
    upstream be re-hammered at machine speed.
    """
    try:
        base = float(os.environ.get("AETHER_LLM_RETRY_BACKOFF_BASE_SECONDS", "0.5"))
    except ValueError:
        return 0.5
    return max(0.0, base)


def get_llm_retry_backoff_max_seconds() -> float:
    """Ceiling of the exponential backoff (``AETHER_LLM_RETRY_BACKOFF_MAX_SECONDS``,
    default 8s). Bounded so a retry can never outlive the run's wall-clock
    budget, which would turn resilience into a hang."""
    try:
        cap = float(os.environ.get("AETHER_LLM_RETRY_BACKOFF_MAX_SECONDS", "8"))
    except ValueError:
        return 8.0
    return max(0.0, cap)


def _backoff_delay(attempt: int) -> float:
    """FULL-JITTER exponential backoff: ``uniform(0, min(cap, base * 2**attempt))``.

    Full jitter (rather than a fixed or an equal-jitter delay) is deliberate:
    the sweep enqueues one stretch per user and several users can hit the same
    upstream in the same tick, so identical deterministic delays would keep
    their retries phase-locked and re-create the very burst this is meant to
    spread out.
    """
    base = get_llm_retry_backoff_base_seconds()
    if base <= 0:
        return 0.0
    ceiling = min(get_llm_retry_backoff_max_seconds(), base * (2 ** max(0, attempt)))
    if ceiling <= 0:
        return 0.0
    return random.uniform(0.0, ceiling)


def _sleep_for_backoff(seconds: float) -> None:
    """Module-level sleep seam so tests can assert the backoff WITHOUT waiting
    (and so a future async transport can override it in one place)."""
    if seconds > 0:
        time.sleep(seconds)


#: ``AgentQuotaBlock.reason`` prefix that marks a row as a CIRCUIT-BREAKER
#: cooldown rather than a subscription-quota cooldown. The two share the table
#: (one row per user+provider, already indexed and already consulted before
#: every live call) but must never be confused: a subscription block means
#: "your plan is spent, switch billing" and surfaces as HTTP 429, while a
#: circuit block means "the provider refused and we stopped asking" and
#: surfaces as an honest 503 carrying the class that tripped it.
CIRCUIT_REASON_PREFIX = "llm_circuit_open:"


def get_llm_breaker_cooldown_seconds() -> float:
    """How long the circuit stays open after a non-retryable upstream refusal.

    ``AETHER_LLM_BREAKER_COOLDOWN_SECONDS``, default 900s (15 min). Long
    enough that a 10-minute cron tick cannot re-probe a dead upstream every
    cycle; short enough that a top-up is picked up without operator action.
    Floored at 30s so a bad value cannot make the breaker a no-op.
    """
    try:
        seconds = float(os.environ.get("AETHER_LLM_BREAKER_COOLDOWN_SECONDS", "900"))
    except ValueError:
        seconds = 900.0
    return max(30.0, seconds)


def _circuit_cooldown_expiry() -> datetime:
    """When a freshly tripped circuit re-closes (UTC), with up to 10% jitter so
    many users tripped by the same outage do not all re-probe in lockstep."""
    seconds = get_llm_breaker_cooldown_seconds()
    seconds += random.uniform(0.0, seconds * 0.1)
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _record_llm_circuit_open(
    user_id: str | None, provider: str, failure_class: str
) -> "datetime | None":
    """Open the circuit for ``user_id`` + ``provider`` for a cooling period.

    Returns the expiry (or ``None`` when nothing was recorded). Never raises:
    a breaker that cannot be persisted must degrade to the pre-existing
    behaviour, not turn a provider outage into a 500.

    An ACTIVE subscription-quota block is left untouched — it is a stronger,
    longer statement about the same user+provider, and the two share one row.
    """
    if not user_id or failure_class not in LLM_NON_RETRYABLE_FAILURE_CLASSES:
        return None
    try:
        from app.repositories.user_provider_credential import AgentQuotaBlockRepository

        repo = AgentQuotaBlockRepository()
        existing = repo.get_active(user_id, provider)
        if existing is not None and not str(
            existing.get("reason") or ""
        ).startswith(CIRCUIT_REASON_PREFIX):
            return None
        expires_at = _circuit_cooldown_expiry()
        repo.set_block(
            user_id, provider,
            expires_at=expires_at,
            reason=f"{CIRCUIT_REASON_PREFIX}{failure_class}",
        )
    except Exception as exc:  # noqa: BLE001 — never hide the underlying failure
        logger.warning(
            "failed to record %s circuit breaker (%s): %s",
            provider, failure_class, type(exc).__name__,
        )
        return None
    logger.error(
        "LLM circuit OPEN for user=%s provider=%s class=%s until %s — further "
        "live calls are refused without contacting the provider",
        user_id, provider, failure_class, expires_at.isoformat(timespec="seconds"),
    )
    return expires_at


def is_circuit_block(block: "dict[str, Any] | None") -> bool:
    """Whether an ``AgentQuotaBlock`` row is a CIRCUIT-BREAKER cooldown.

    The single authority on what a block row MEANS. One table carries two
    completely different statements about the same user+provider:

    * ``reason`` WITHOUT the circuit prefix — the user's own subscription quota
      is spent. Their problem, their reset time, HTTP 429.
    * ``reason`` WITH :data:`CIRCUIT_REASON_PREFIX` — OUR upstream provider
      refused (402 out of credits / 401 bad key) and we stopped asking. The
      operator's problem, HTTP 503, and never billed to the user.

    Every reader of the row must branch on this, not on "a row exists". The
    reviewer of 0b6102d found the two router gates
    (``_record_run`` / ``_enqueue_single_agent``) doing exactly that: from the
    SECOND attempt onward — the first opens the circuit, so only later ones see
    the row — an out-of-credit upstream was reported to the paying user as
    "your subscription quota is exhausted", complete with a billing suggestion
    that could not possibly help.
    """
    if not block:
        return False
    return str(block.get("reason") or "").startswith(CIRCUIT_REASON_PREFIX)


def circuit_block_error(
    provider: str, block: "dict[str, Any] | None"
) -> "LLMCircuitOpenError | None":
    """The classified circuit-open error for ``block``, or ``None`` when the row
    is NOT a circuit cooldown (i.e. it is a genuine subscription-quota block and
    the caller must keep its existing 429 behaviour).

    The public seam the router gates use so the reason-parsing above lives in
    exactly one place.
    """
    if not is_circuit_block(block):
        return None
    return _circuit_open_error(provider, block or {})


def _circuit_open_error(provider: str, block: "dict[str, Any]") -> LLMCircuitOpenError:
    """The honest error raised in place of a live call while the circuit is open."""
    reason = str(block.get("reason") or "")
    failure_class = reason[len(CIRCUIT_REASON_PREFIX):] or LLM_FAILURE_RETRYABLE
    if failure_class not in LLM_NON_RETRYABLE_FAILURE_CLASSES:
        failure_class = LLM_FAILURE_RETRYABLE
    expires_at = block.get("expiresAt")
    return LLMCircuitOpenError(
        f"LLM circuit open for provider '{provider}' ({failure_class}); "
        f"cooling until {expires_at}",
        failure_class=failure_class,
        provider=provider,
        expires_at=expires_at,
    )


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
    *,
    free_chain: bool = False,
) -> dict[str, Any]:
    """Prepare the existing OpenAI-compatible OpenRouter chat request.

    ``free_chain`` marks an attempt the ADMIN insufficient-credits rescue
    APPENDED to the chain (:meth:`LLMClient._extend_chain_with_admin_free_models`).
    Those — and ONLY those — attempts get a latency-shaped body. Every other
    request (paid, system-default, and any model the user chose themselves,
    including a ``:free`` one they picked deliberately) keeps the byte-identical
    body it has always had: the shaping is keyed on chain PROVENANCE, never on
    the model id.

    Why the shaping exists (QA-FAIL-01, live evidence in
    ``uat/reports/evidence/models-live/free-chain-shaping-probe.txt``): the
    rescue models are REASONING models. With the unshaped body they spent
    3.4k-6.0k unbounded reasoning tokens before emitting any letter — 60.4 s and
    116.5 s on the real deployed prompt against a ~50 s per-attempt slice — so
    the first rescue model consumed the entire run budget and the second never
    got a turn (3 of 3 live production runs produced no letter). Two levers,
    both verified against the live API before being written:

    - ``max_tokens``: a generous cap (see
      :func:`get_admin_free_fallback_max_tokens`). Reasoning tokens count
      against the completion budget, which is exactly why it must be paired
      with the parameter below rather than used alone.
    - ``reasoning: {"enabled": False}``: genuinely DISABLES reasoning
      generation. The obvious-looking ``{"exclude": True}`` was probed first and
      is actively harmful here — per OpenRouter's contract it only HIDES
      reasoning (the model still generates it, so no latency is saved), and with
      the reasoning channel suppressed both rescue models dumped raw
      chain-of-thought into ``content`` instead of the strict JSON: 2 of 2 live
      attempts unparseable, one truncated at ``finish_reason=length``. With
      ``enabled: False`` the same prompt returned 0 reasoning tokens and valid
      strict JSON in 1.5-23.5 s.

    Nothing else changes: same prompts, same temperature, same strict-JSON
    contract, same downstream fabrication/entailment guards. The shaping is
    transport-level only.

    HARD GUARD (MODEL-SUB-QUOTA, OWNER DIRECTIVE 2026-08-17). A Claude model
    never reaches this builder: it raises :class:`ClaudeOnOpenRouterError`
    before a request exists, so no caller — present or future — can spend
    OpenRouter credit on a model the operator's Anthropic subscription serves.
    :func:`resolve_provider` already prevents this; the guard exists so a
    bypassed or hand-built chain cannot.
    """
    if is_claude_model(model):
        raise ClaudeOnOpenRouterError(
            f"model '{(model or '').strip()}' is a Claude model and must be served "
            "by the direct anthropic provider on the operator's subscription — "
            "an OpenRouter request for it is refused (MODEL-SUB-QUOTA)."
        )
    base = (cred.base_url or "https://openrouter.ai/api/v1").rstrip("/")
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if free_chain:
        body["max_tokens"] = get_admin_free_fallback_max_tokens()
        body["reasoning"] = {"enabled": False}
    else:
        # U1X-a: every OTHER request carries a BOUNDED completion window too.
        # Omitting ``max_tokens`` does not mean "no cap" — it means the upstream
        # provider default applies, which for a reasoning-tier model reached
        # 65536 and is what drove the production 402s (a call is pre-authorised
        # against max_tokens, so an unbounded ask fails on credit long before
        # the real ~500-token completion would have). The size is the per-call
        # -class ceiling, narrowed to the affordable window only when a FRESH
        # cached credits+price reading exists. This is a transport bound, not a
        # model choice: the model, prompts, temperature and every downstream
        # guard are untouched (ADR-ML-3 is about substitution, not token caps),
        # and a truncated response still fails the caller's validator honestly
        # rather than being passed off as a complete generation.
        remaining_credit, completion_price = _affordability_signal(model)
        body["max_tokens"] = size_max_tokens_for_call(
            _prompt_name_context.get() or "",
            remaining_credit_usd=remaining_credit,
            completion_price_per_m=completion_price,
        )
    return {
        "url": f"{base}/chat/completions",
        "json": body,
        "headers": {
            "Authorization": f"Bearer {cred.secret}",
            "Content-Type": "application/json",
            **_extra_headers(),
        },
    }


#: Phrases a provider uses when it refuses a request PARAMETER (as opposed to
#: refusing the prompt, the model or the credential). Seeded from the verbatim
#: production body in ``uat/reports/evidence/market-perf/mon-019/`` —
#: ``"`temperature` is deprecated for this model."`` — plus the wordings the
#: OpenAI-compatible gateways use for the same class of rejection.
_PARAMETER_REJECTION_PHRASES: tuple[str, ...] = (
    "deprecated",
    "not supported",
    "unsupported",
    "does not support",
    "unrecognized",
    "unknown parameter",
    "not a supported parameter",
    "not permitted",
)


def _rejects_request_parameter(body: str, parameter: str) -> bool:
    """Whether a 400 body blames ``parameter`` specifically.

    Deliberately CONSERVATIVE, and never a general-purpose 400 handler: the
    provider must name the parameter AND use rejection wording, so a generic
    ``{"error":{"code":400}}`` (prompt too long, malformed request, refusal…)
    is still spent on its first request instead of being blindly reshaped.
    """
    text = (body or "").lower()
    if parameter.lower() not in text:
        return False
    return any(phrase in text for phrase in _PARAMETER_REJECTION_PHRASES)


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


# ---------------------------------------------------------------------------
# U1X-a reliability: affordable-window ``max_tokens`` sizing, wall-clock attempt
# planning, and an honest remaining-credit reading.
#
# Ground truth (agents-uplift discovery, live-verified 2026-08-13): production
# 402s were driven by an unbounded completion ask — the OpenAI-compatible body
# omits ``max_tokens`` on every non-rescue attempt, so the upstream provider
# default (up to 65536 for a reasoning-tier model) applies no matter how little
# credit is left. The 503 storm was wall-clock exhaustion: a fixed 2-attempt
# chain planned against a 65 s budget while observed REASONING-tier latency was
# 70.9-94.4 s, so neither attempt could ever finish.
#
# WHERE THESE ARE APPLIED (they are not advisory helpers — the production paths
# call them, and the tests below assert the real request/attempt shape):
#   * ``size_max_tokens_for_call`` -> ``_build_openrouter_request`` sets
#     ``max_tokens`` on EVERY non-rescue body from it.
#   * ``plan_attempt_count``       -> ``LLMClient._auto`` decides from it whether
#     to slice the wall-clock budget for a fallback attempt at all.
# ---------------------------------------------------------------------------

#: Per-call-class completion ceilings. These are what a call of that class can
#: actually USE — an entailment verdict is a short strict-JSON object, a drafted
#: letter is long-form prose — never the provider's unbounded default.
_MAX_TOKENS_BY_CALL_CLASS: dict[str, int] = {
    "tailor_entailment": 2048,
    "tailor": 8192,
    "cover_letter": 8192,
    "story_extraction": 4096,
}

#: Ceiling for a call class we have no measured figure for. Deliberately well
#: under the 65536 unbounded ask, and above every observed real completion.
_DEFAULT_MAX_TOKENS = 4096

#: Smallest completion window worth requesting. A near-empty credit balance is
#: an honest 402/credits-check problem, not a reason to send ``max_tokens=0``
#: (a request that can never produce output while still being billed for input).
_MIN_MAX_TOKENS = 64


def size_max_tokens_for_call(
    prompt_name: str,
    *,
    remaining_credit_usd: float,
    completion_price_per_m: float,
) -> int:
    """``max_tokens`` to REQUEST for a call of this class, capped to what the
    remaining credit can actually afford.

    ``completion_price_per_m`` is $/M completion tokens (the same unit
    :data:`_STATIC_MODEL_CATALOG` and the OpenRouter catalog carry). The result
    is ``min(per-call-class ceiling, affordable window)`` with a
    :data:`_MIN_MAX_TOKENS` floor — never the provider's unbounded default, and
    never ``0``.
    """
    ceiling = _MAX_TOKENS_BY_CALL_CLASS.get(prompt_name, _DEFAULT_MAX_TOKENS)
    try:
        price = float(completion_price_per_m)
        credit = float(remaining_credit_usd)
    except (TypeError, ValueError):
        return ceiling
    if price <= 0 or credit <= 0:
        # No usable price signal (free model / unknown price) — the class
        # ceiling is still a real bound, which is the whole point.
        return ceiling
    affordable = int((credit / price) * 1_000_000)
    return max(_MIN_MAX_TOKENS, min(ceiling, affordable))


def plan_attempt_count(
    *,
    budget_seconds: float,
    per_attempt_seconds: float,
    requested_attempts: int,
) -> int:
    """How many of ``requested_attempts`` actually FIT in the wall-clock budget.

    Returns the largest count ``<= requested_attempts`` whose total attempt time
    fits inside ``budget_seconds``, or ``0`` when not even one attempt fits —
    an honest fail-fast signal instead of promising an attempt that is
    guaranteed to be cut off mid-flight (indistinguishable, to the caller, from
    a real provider failure).
    """
    try:
        budget = float(budget_seconds)
        per_attempt = float(per_attempt_seconds)
        requested = int(requested_attempts)
    except (TypeError, ValueError):
        return max(0, int(requested_attempts or 0))
    if requested <= 0:
        return 0
    if per_attempt <= 0:
        return requested
    return max(0, min(requested, int(budget // per_attempt)))


#: Call class (``prompt_name``) of the generation currently in flight, so the
#: transport layer can size ``max_tokens`` per class without changing
#: :meth:`LLMClient._call_live`'s signature (several suites install
#: strict-signature doubles on that seam; a ContextVar keeps every existing
#: call site byte-identical). Set once in :meth:`LLMClient.complete`.
_prompt_name_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aether_llm_prompt_name", default=None
)


def get_expected_attempt_seconds() -> float:
    """Wall-clock seconds a single live attempt is EXPECTED to take, used by
    :func:`plan_attempt_count` to decide whether the budget can really hold
    more than one attempt.

    The default is the LOW end of the live-observed REASONING-tier latency band
    (70.9-94.4 s, agents-uplift discovery 2026-08-13) — deliberately the low
    end, so the multi-attempt slicing is only abandoned when even the most
    optimistic estimate says a second attempt cannot fit. Env-overridable via
    ``AETHER_LLM_EXPECTED_ATTEMPT_SECONDS`` once ops has a better measurement.
    """
    try:
        seconds = float(os.environ.get("AETHER_LLM_EXPECTED_ATTEMPT_SECONDS", "70.9"))
    except ValueError:
        seconds = 70.9
    return max(0.0, seconds)


def _cached_completion_price_per_m(model: str) -> float:
    """$/M completion tokens for ``model`` from ALREADY-CACHED catalogs only.

    Never performs a network call — this runs on the request path. ``0.0`` means
    "unknown", which makes :func:`size_max_tokens_for_call` fall back to the
    per-call-class ceiling (still a real bound, never the upstream default).
    """
    for _fetched_at, entries in _MODEL_CATALOG_CACHE.values():
        for entry in entries or ():
            if entry.get("id") == model:
                try:
                    return float(entry.get("completionPerM") or 0.0)
                except (TypeError, ValueError):
                    return 0.0
    for entries in _STATIC_MODEL_CATALOG.values():
        for entry in entries:
            if entry.get("id") == model:
                return float(entry.get("completionPerM") or 0.0)
    return 0.0


def _affordability_signal(model: str) -> tuple[float, float]:
    """``(remaining_credit_usd, completion_price_per_m)`` from cached readings.

    Both come from in-process caches (:data:`_CREDITS_CACHE`,
    :data:`_MODEL_CATALOG_CACHE`) — a request must never block on a credits or
    catalog fetch, and a stale-cache miss must never be papered over with an
    invented number. When either is unknown the pair is ``(0.0, 0.0)`` and the
    caller falls back to the per-call-class ceiling.
    """
    cached = _CREDITS_CACHE
    if cached is None or (time.monotonic() - cached[0]) >= _CREDITS_TTL:
        return (0.0, 0.0)
    try:
        remaining = float(cached[1].get("remaining") or 0.0)
    except (TypeError, ValueError):
        return (0.0, 0.0)
    return (remaining, _cached_completion_price_per_m(model))


class CreditsUnavailableError(RuntimeError):
    """Raised when the provider's remaining credit can't be read (no
    credential / network / upstream error). Mirrors :class:`ModelCatalogError`'s
    honest-failure role: a credits reading is NEVER fabricated."""


#: Cached credits reading: (fetched_at_monotonic, envelope).
_CREDITS_CACHE: "tuple[float, dict[str, Any]] | None" = None
#: Credits move only as spend happens; a short TTL keeps the reading honest
#: without hammering the provider from every page render.
_CREDITS_TTL = 60.0


def get_openrouter_credits(*, force_refresh: bool = False) -> dict[str, Any]:
    """Real remaining OpenRouter credit: ``{"remaining", "total", "asOf"}``.

    Reads OpenRouter's own ``GET /credits`` with the deployment credential and
    caches for :data:`_CREDITS_TTL` (same pattern as the model catalog). Fails
    CLOSED with :class:`CreditsUnavailableError` — an unreachable upstream falls
    back to the last real reading if one exists, and otherwise raises rather
    than inventing a balance.
    """
    global _CREDITS_CACHE

    now = time.monotonic()
    cached = _CREDITS_CACHE
    if not force_refresh and cached is not None and now - cached[0] < _CREDITS_TTL:
        return dict(cached[1])

    cred = resolve_credential("openrouter")
    if cred is None or not getattr(cred, "secret", None):
        raise CreditsUnavailableError(
            "No OpenRouter credential is configured — remaining credit cannot be read."
        )

    import httpx

    base = (getattr(cred, "base_url", None) or "https://openrouter.ai/api/v1").rstrip("/")
    try:
        resp = httpx.get(
            f"{base}/credits",
            headers={"Authorization": f"Bearer {cred.secret}"},
            timeout=15.0,
        )
        if resp.status_code != 200:
            raise CreditsUnavailableError(
                f"OpenRouter returned HTTP {resp.status_code} for GET /credits."
            )
        payload = resp.json() or {}
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise CreditsUnavailableError("OpenRouter /credits returned an unexpected shape.")
        total = float(data.get("total_credits") or 0.0)
        used = float(data.get("total_usage") or 0.0)
    except CreditsUnavailableError:
        if cached is not None:
            return dict(cached[1])
        raise
    except Exception as exc:  # noqa: BLE001 — network/parse: honest failure
        if cached is not None:
            return dict(cached[1])
        raise CreditsUnavailableError(f"OpenRouter /credits is unreachable: {exc}") from exc

    envelope: dict[str, Any] = {
        "remaining": round(total - used, 6),
        "total": round(total, 6),
        "asOf": datetime.now(timezone.utc).isoformat(),
    }
    _CREDITS_CACHE = (now, envelope)
    return dict(envelope)

#: F-2 (HIGH, uat/reports/evidence/prod-verify-5a/PROD-VERIFY-5A.json) —
#: ``_MODEL_CATALOG_CACHE`` above is in-process memory only, so it reopens
#: COLD on every API restart/deploy. Until something happens to browse the
#: catalog in that fresh process, every metered run on an id absent from
#: ``MODEL_PRICING``/``_STATIC_MODEL_CATALOG`` (e.g. the deployment's own
#: configured ``deepseek/deepseek-v4-pro``) falls through to the flat
#: ``_DEFAULT_PRICE`` — live A/B proof: $0.006355 (cold, flat default) vs the
#: real $0.002759 catalog price for the identical call, a ~2.3x over-charge
#: against the customer's spend cap. This file persists the last successfully
#: fetched catalog to disk so a fresh process starts from REAL last-known
#: prices instead of the flat default — env-overridable so the test suite
#: never touches (or is touched by) the real production file.
_MODEL_PRICE_CACHE_FILE = Path(
    os.environ.get("AETHER_MODEL_PRICE_CACHE_FILE", "/tmp/aether_model_price_cache.json")
)

#: Set True after this process's ONE lazy disk-cache load attempt (success,
#: absence, or corruption) so a later in-memory cache clear (e.g. a test
#: popping ``_MODEL_CATALOG_CACHE["openrouter"]``) never re-triggers a reload
#: mid-run — disk persistence only ever warms a genuinely COLD start.
_disk_price_cache_load_attempted = False


def _persist_model_catalog_to_disk(
    provider: str, fetched_at_monotonic: float, models: list[dict[str, Any]]
) -> None:
    """Best-effort write of a freshly-fetched catalog to disk (F-2 fix).

    Never raises: disk persistence is a cold-start optimisation, not a
    correctness requirement, so a write failure (read-only FS, disk full, …)
    must never break the catalog fetch that triggered it.
    """
    if provider != "openrouter" or not models:
        return
    try:
        elapsed = max(0.0, time.monotonic() - fetched_at_monotonic)
        fetched_at_utc = (datetime.now(timezone.utc) - timedelta(seconds=elapsed)).isoformat()
        payload = {"provider": provider, "fetchedAtUtc": fetched_at_utc, "models": models}
        _MODEL_PRICE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _MODEL_PRICE_CACHE_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload))
        tmp_path.replace(_MODEL_PRICE_CACHE_FILE)  # atomic on the same filesystem
    except OSError:
        pass


def _load_model_catalog_from_disk() -> None:
    """Lazy, at-most-once-per-process load of the last persisted catalog into
    ``_MODEL_CATALOG_CACHE`` (F-2 fix). Runs on the first cold price lookup so
    a freshly restarted process prices a metered run at the real last-known
    catalog price instead of the flat default — with NO network I/O added to
    the pricing path. The reconstructed entry ages normally: ``catalog_
    freshness`` honestly reports it ``stale`` once its real fetch time is past
    the usual TTL, same as any other cache entry.
    """
    global _disk_price_cache_load_attempted
    if _disk_price_cache_load_attempted:
        return
    _disk_price_cache_load_attempted = True
    if "openrouter" in _MODEL_CATALOG_CACHE:
        return  # already warm in-memory — persisted data can only be staler
    try:
        payload = json.loads(_MODEL_PRICE_CACHE_FILE.read_text())
        models = payload.get("models")
        fetched_at_utc = payload.get("fetchedAtUtc")
        if not isinstance(models, list) or not models or not isinstance(fetched_at_utc, str):
            return
        fetched_dt = datetime.fromisoformat(fetched_at_utc)
        elapsed = max(0.0, (datetime.now(timezone.utc) - fetched_dt).total_seconds())
        _MODEL_CATALOG_CACHE["openrouter"] = (time.monotonic() - elapsed, models)
    except (OSError, ValueError, TypeError):
        # No persisted cache yet, or it's unreadable/corrupt — an honestly
        # cold start proceeds to the flat default exactly as before this fix.
        return


#: OpenRouter's own suffix for a zero-price variant of a model. VERIFIED
#: against the 367-model live catalog snapshot
#: ``uat/reports/evidence/free-model-fallback/models-list-raw.json``
#: (2026-07-29): all 14 ``:free``-suffixed ids carry
#: ``pricing.prompt == pricing.completion == 0``. The implication is
#: one-directional — ``:free`` ⇒ $0; a $0 model need NOT carry the suffix — so
#: it is only ever used to prove a price is zero, never to prove one is not.
_FREE_MODEL_ID_SUFFIX = ":free"


def cached_model_price(model_id: str) -> "tuple[float, float] | None":
    """``(prompt, completion)`` price in $/1K-tokens for ``model_id``, resolved
    without network I/O, or ``None`` when it cannot be established.

    Sources, in order of authority: the already-fetched OpenRouter catalog
    (F-2 fix: lazily seeded from the on-disk persisted catalog — see
    ``_load_model_catalog_from_disk`` — the FIRST time this process sees a
    cold cache, so a fresh restart prices off the real last-known catalog
    instead of nothing), the always-available static catalogs, then
    OpenRouter's own zero-price ``:free`` id convention. Lets the cost path
    price a USER-CHOSEN model (or a model the ADMIN free-chain rescue
    substituted, ML-W14) accurately instead of a flat default.
    """
    mid = (model_id or "").strip()
    if not mid:
        return None
    if "openrouter" not in _MODEL_CATALOG_CACHE:
        _load_model_catalog_from_disk()
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
    # Catalogs are authoritative and are consulted FIRST; this is the last
    # resort, and it replaces only the caller's flat non-zero default — which
    # for a $0 model is spend the user never incurred.
    if mid.endswith(_FREE_MODEL_ID_SUFFIX):
        return (0.0, 0.0)
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


# ADR-ML-4 (docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md, 2026-07-22, binding) —
# catalog curation for ML-model-001/002 (§3.4.3c). OpenRouter's /models payload
# carries NO availability signal — a permanently-dead model has the exact same
# full schema entry as a working one — so a heuristic chat-compat filter (e.g.
# "no 'temperature' in supported_parameters") is DISHONEST: it would also hide
# 50+ functional Anthropic-via-OpenRouter models that use native params instead
# of 'temperature'. Instead this is a maintained EXACT-ID denylist seeded from
# the §3.4 live run-sweep evidence (uat/reports/evidence/models-live/models/
# RUN-SWEEP.md), which PROVED each of the 5 ids below permanently unable to
# serve a chat completion for this key:
#   no-endpoint 404 (every attempt):  allenai/olmo-3-32b-think
#                                      inflection/inflection-3-pi
#   structurally non-chat (apply/diff/background-tool endpoints, not chat):
#                                      relace/relace-apply-3
#                                      morph/morph-v3-fast
#                                      openai/o3-deep-research
# ONLY permanent-failure classes (404 no-endpoints, structural 400 incompatible)
# belong here. TRANSIENT failures (rate-limit, timeout, transient-malformed —
# e.g. a deepseek/deepseek-v4-pro or moonshotai/kimi-k3 blip during a sweep)
# MUST NOT be added — the catalog must stay honest about what's live rather
# than degrade UX for a model that merely had a bad moment. Membership is exact
# string equality only, never substring/prefix, so a real future model (e.g. a
# hypothetical morph/morph-v3-fast-turbo) can never become collateral damage.
# To extend: add a new id here ONLY after run-sweep evidence proves it
# permanently broken (not merely flaky), with a one-line citation of that
# evidence, following the same format as the entries above.
_OPENROUTER_PROVEN_BROKEN_IDS: frozenset[str] = frozenset(
    {
        "allenai/olmo-3-32b-think",
        "inflection/inflection-3-pi",
        "relace/relace-apply-3",
        "morph/morph-v3-fast",
        "openai/o3-deep-research",
    }
)


def _curate_openrouter_models(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project OpenRouter's verbose ``/models`` payload to the fields the picker
    needs, tagged with a budget tier, sorted cheapest-first within tier.

    Excludes the small set of ids in ``_OPENROUTER_PROVEN_BROKEN_IDS`` (ADR-ML-4)
    — models proven permanently unable to serve a chat completion for this key —
    by exact id match only.

    Also excludes every ``anthropic/claude-*`` row (MODEL-SUB-QUOTA, OWNER
    DIRECTIVE 2026-08-17). Those models ARE offered — under the Anthropic
    catalog, which the operator's subscription serves — and picking one here
    would now be routed away from OpenRouter anyway, so listing them in the
    OpenRouter catalog with an OpenRouter price would be a disclosure lie.
    """
    out: list[dict[str, Any]] = []
    for m in raw:
        mid = m.get("id")
        if not mid:
            continue
        if mid in _OPENROUTER_PROVEN_BROKEN_IDS:
            continue
        if is_claude_model(mid):
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
    provider: str,
    user_id: str | None = None,
    *,
    timeout: float = 15.0,
    force_refresh: bool = False,
    allow_fetch: bool = True,
) -> list[dict[str, Any]]:
    """Live, curated model catalog for ``provider`` (GAP-P7-MODEL-CHOICE-001).

    OpenRouter → its full ``/models`` catalog (300+ models) fetched with the
    user's own credential when present, else the deployment credential, curated
    to ``{id, name, promptPerM, completionPerM, contextLength, tier, reasoning}``
    and cached ~1 h. Providers without an open catalog (anthropic, …) return a
    small curated static list.

    ``force_refresh`` bypasses the TTL cache (manual refresh, ML-catalog-003).
    ``allow_fetch=False`` never makes a network call — it serves a warm cache if
    present and otherwise raises :class:`ModelCatalogError`; used by non-blocking
    callers (e.g. config-save validation) so a request never stalls on a slow
    upstream.

    Honest degradation (ML-catalog-002): when the TTL has lapsed (or a manual
    refresh is forced) and every upstream fetch attempt fails, the last-good
    cached list is served rather than raised — the UI is never left empty and a
    catalog is NEVER fabricated. :class:`ModelCatalogError` is raised only when
    there is genuinely nothing to serve (no cache AND no working upstream).
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
    if not force_refresh and cached is not None and now - cached[0] < _MODEL_CATALOG_TTL:
        return cached[1]
    if not allow_fetch:
        # Non-blocking caller: serve the warm cache if we have one, else signal
        # "not known" — never open a network connection on this path.
        if cached is not None:
            return cached[1]
        raise ModelCatalogError(
            "The OpenRouter model catalog is not cached yet — browse it once to load it."
        )
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
        # No credential to refresh with — serve last-good stale data if present
        # (never block the UI), else an honest, actionable error.
        if cached is not None:
            return cached[1]
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
            # F-2 fix: persist so the NEXT process restart starts warm too.
            _persist_model_catalog_to_disk(provider, now, curated)
            return curated
        last_err = f"HTTP {resp.status_code}"
    # Every refresh attempt failed. Serve the last-good cache (flagged stale by
    # the router via catalog_freshness) rather than block the UI or fabricate.
    if cached is not None:
        return cached[1]
    raise ModelCatalogError(f"Model catalog request failed ({last_err}).")


def catalog_freshness(provider: str) -> tuple[str, bool]:
    """``(lastRefreshedAt, stale)`` for ``provider``'s model catalog (ML-catalog-002).

    ``lastRefreshedAt`` is an ISO-8601 UTC timestamp of the wall-clock moment the
    currently-served catalog was actually fetched from upstream (derived from the
    stored monotonic fetch time), NOT the moment of this call. ``stale`` is True
    only when a cached OpenRouter catalog is past its TTL — i.e. the last refresh
    attempt failed and we are serving last-good data. Providers with no cache
    entry (the static anthropic catalog, or a never-fetched openrouter) report
    "now" and ``stale=False``: they are computed fresh each call, never stale.
    """
    from datetime import datetime, timedelta, timezone

    prov = (provider or "").strip().lower()
    now_dt = datetime.now(timezone.utc)
    cached = _MODEL_CATALOG_CACHE.get(prov)
    if cached is None:
        return now_dt.isoformat(), False
    elapsed = max(0.0, time.monotonic() - cached[0])
    fetched_at = now_dt - timedelta(seconds=elapsed)
    return fetched_at.isoformat(), elapsed >= _MODEL_CATALOG_TTL


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
        validate: "Callable[[str], Any] | None" = None,
    ) -> str:
        """Return the assistant's text for a system+user prompt pair.

        ``validate`` (auto mode only): a callable that RAISES if the returned
        content is unusable (e.g. malformed JSON). A validation failure is then
        treated as a retryable live failure inside :meth:`_auto` (ML-pipeline-001)
        so a single garbled response no longer hard-fails the call.
        """
        if self.mode == "replay":
            return self._replay(prompt_name, fixture_key)
        # Carry the call class down to the transport so the request can be sized
        # per class (U1X-a ``max_tokens``) without touching ``_call_live``'s
        # signature. Reset on the way out so a nested/subsequent call can never
        # inherit a stale class.
        token = _prompt_name_context.set(prompt_name)
        try:
            if self.mode == "auto":
                return self._auto(
                    prompt_name, system, user,
                    model=model, temperature=temperature, fixture_key=fixture_key,
                    validate=validate,
                )
            # live / record modes: propagate live errors unchanged (dev modes).
            content = self._call_live(system, user, model=model, temperature=temperature)
            if self.mode == "record":
                self._record(prompt_name, fixture_key, content)
            return content
        finally:
            _prompt_name_context.reset(token)

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        """Like :meth:`complete` but parses the response as JSON.

        In ``auto`` mode a malformed/truncated live response (e.g. the model hit
        its token limit mid-object) is an honest live FAILURE — it raises
        :class:`LLMUnavailableError` (mapped to 503, run refunded). It is NEVER
        answered with a recorded fixture masqueraded as live output
        (GAP-P6-AUTH-002); fixtures serve only in ``replay`` mode.
        """
        # In auto mode, hand ``_auto`` a validator so a malformed/truncated
        # response is treated as a RETRYABLE live failure (bounded same-model
        # re-draft, then the fallback model) rather than hard-failing the whole
        # call on the first garbled response (ML-pipeline-001). ``_auto`` raises
        # an honest ``LLMUnavailableError`` only once every bounded attempt is
        # still malformed — never a raw ``JSONDecodeError`` to the caller.
        validate = None
        if self.mode == "auto":
            def validate(content: str) -> None:  # noqa: E306 — local validator
                # strict=False: models (observed live: anthropic/claude-sonnet-5
                # cover letters, RT-001) emit well-formed JSON whose string
                # values contain LITERAL control characters (raw newlines/tabs).
                # That content is genuinely usable; rejecting it made every
                # same-model re-draft fail identically and 503'd the run.
                # Truncated/structurally-malformed JSON still fails the parse.
                json.loads(self._strip_fences(content), strict=False)

        raw = self.complete(prompt_name, system, user, validate=validate, **kwargs)
        try:
            return json.loads(self._strip_fences(raw), strict=False)
        except json.JSONDecodeError as exc:
            if self.mode != "auto":
                raise
            # Auto mode: ``_auto`` already validated + retried and would have
            # raised ``LLMUnavailableError`` on all-malformed, so a parse error
            # here is not expected — still surface it honestly, never raw.
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
        validate: "Callable[[str], Any] | None" = None,
    ) -> str:
        """Live-first with one model-fallback retry, then an HONEST error.

        The one-retry fallback is suppressed for a user-CHOSEN model
        (:meth:`_model_chain`, ADR-ML-3) so a deliberate pick that fails raises
        honestly instead of being silently substituted by a different model.

        ``validate`` (optional): a callable that RAISES when the live content is
        unusable (e.g. malformed/truncated JSON — ML-pipeline-001). A validation
        failure is RETRYABLE: the SAME model is re-drafted a bounded number of
        times (``_MALFORMED_JSON_RETRIES``; a same-model re-draft is NOT model
        substitution, so it is allowed even for a user-chosen single-model chain)
        and, if still unusable, the chain falls through to the fallback model
        exactly like a raised call error. A genuine call EXCEPTION, by contrast,
        is NOT re-tried on the same model — it falls straight to the next model,
        preserving the honest-failure contract.

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
        # NOTE: ``chain`` may GROW during the loop — an OpenRouter 402 on the
        # ADMIN account appends the free rescue models (see
        # ``_extend_chain_with_admin_free_models``). Hence an explicit index walk
        # rather than ``enumerate(chain)``: the growth is part of the contract,
        # not an accident of iterating a mutating list.
        #
        # Models the ADMIN rescue APPENDED to this chain. Only these attempts
        # get the latency-shaped OpenRouter body (QA-FAIL-01) — carrying the
        # provenance here, rather than sniffing the model id downstream, is what
        # keeps every other caller's request byte-identical.
        free_chain_models: set[str] = set()
        #: Number of RETRYABLE failures so far in this chain — the exponent of
        #: the backoff below. Non-retryable failures deliberately do not
        #: advance it: they never wait.
        retry_attempt = 0
        same_model_429_retries = 0  # RT-006: at most one per call, sole-model chains
        idx = 0
        while idx < len(chain):
            attempt_model = chain[idx]
            # A validation (malformed-content) failure re-drafts the SAME model a
            # bounded number of times before the outer loop falls through to the
            # next model; a raised call error breaks straight to the next model
            # (no same-model retry) — see the docstring.
            for _draft_attempt in range(_MALFORMED_JSON_RETRIES + 1):
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
                    # fallback. remaining at the first attempt is the full
                    # (possibly shared) budget, so this is a fraction of the
                    # total; the fallback (last attempt) keeps the entire
                    # remaining budget.
                    #
                    # U1X-a: that slicing is only WORTH doing when the budget can
                    # actually hold more than one attempt. Production ran a 65 s
                    # budget against 70.9-94.4 s observed REASONING-tier latency,
                    # so the fraction handed the primary ~39 s — too short to ever
                    # finish — and the leftover was too short for the fallback
                    # either: both attempts were structurally guaranteed to be cut
                    # off, which is the 503 storm. When the planner says a second
                    # attempt cannot fit, the primary gets the WHOLE remaining
                    # window (one attempt that can actually complete) instead of a
                    # fraction that cannot.
                    if plan_attempt_count(
                        budget_seconds=remaining,
                        per_attempt_seconds=get_expected_attempt_seconds(),
                        requested_attempts=len(chain) - idx,
                    ) > 1:
                        attempt_seconds = max(
                            _MIN_ATTEMPT_SECONDS,
                            remaining * get_primary_budget_fraction(),
                        )
                    else:
                        logger.info(
                            "LLM budget %.1fs holds fewer than 2 attempts at the "
                            "expected %.1fs/attempt — giving the primary model %s "
                            "the full window instead of a %.0f%% slice "
                            "(prompt=%s)",
                            remaining, get_expected_attempt_seconds(), attempt_model,
                            get_primary_budget_fraction() * 100, prompt_name,
                        )
                try:
                    # ``free_chain`` is passed ONLY for a rescue attempt, so the
                    # ``_call_live`` seam keeps its exact pre-existing signature
                    # on every unchanged path (several suites install
                    # strict-signature doubles there, and this fix must not
                    # perturb behaviour that has nothing to do with the rescue).
                    # Semantically identical to passing the False default.
                    shaping = (
                        {"free_chain": True}
                        if attempt_model in free_chain_models
                        else {}
                    )
                    # RT-005: a model in an active rate-limit cooldown fails
                    # fast with the SAME 429-shaped error a live call would
                    # produce, through the identical handling below — minus
                    # the doomed network call and the pointless backoff.
                    cooling_left = _model_cooling_seconds_left(attempt_model)
                    if cooling_left > 0:
                        cooling_exc = RuntimeError(
                            f"LLM provider HTTP 429 (cooling): model "
                            f"{attempt_model} is rate-limited; cooldown ends "
                            f"in {cooling_left:.0f}s"
                        )
                        cooling_exc._aether_cooling_skip = True  # type: ignore[attr-defined]
                        raise cooling_exc
                    content = self._call_live(
                        system, user, model=attempt_model, temperature=temperature,
                        max_seconds=attempt_seconds, **shaping,
                    )
                except QuotaExhaustedError as exc:
                    # Subscription quota is exhausted — NEVER fall back to a
                    # fixture or another model/credential (that would fake
                    # success or shift the bill). Propagate so the router
                    # returns an honest 429.
                    #
                    # ONE exception, and it shifts no user's bill: an
                    # OPERATOR-SCOPED run (ADR-AGI-3 Decision 3) is spending the
                    # operator's OWN credential, and exhausting it is precisely
                    # the signal its configured chain exists for. The next entry
                    # is still resolved through the same operator slot, still
                    # billed to the operator, and still recorded as a served-model
                    # substitution — never silent.
                    if not (_is_operator_scoped_run() and idx + 1 < len(chain)):
                        raise
                    last_error = exc
                    _stage_fallback_reason(attempt_model, exc)
                    logger.info(
                        "operator chain: %s is out of quota (prompt=%s) — "
                        "continuing with the configured next model",
                        attempt_model, prompt_name,
                    )
                    break
                except LLMCircuitOpenError:
                    # CRITICAL-3: the breaker is already open for this
                    # user+provider. Walking the rest of the chain would just
                    # re-raise this for every model; propagate immediately so
                    # the caller fails fast with the honest reason.
                    raise
                except Exception as exc:  # 404/429/5xx/network/timeout — next model
                    last_error = exc
                    logger.warning(
                        "LLM live call failed (model=%s, prompt=%s): %s",
                        attempt_model, prompt_name, exc,
                    )
                    # RT-005: count only REAL 429s toward the cooldown streak —
                    # a synthetic cooling skip must never extend its own block.
                    if _exc_is_http_429(exc) and not getattr(
                        exc, "_aether_cooling_skip", False
                    ):
                        _note_model_429(attempt_model)
                    # ADR-AGI-3 Decision 3: the OPERATOR chain advances on
                    # EXHAUSTION SIGNALS ONLY. A 404/5xx/timeout is a failure OF
                    # the operator's chosen model, and walking to the next
                    # provider for it would be exactly the silent substitution
                    # ADR-ML-3 forbids — so the chain ends here and the honest
                    # error is raised. Reachable only for an operator-scoped
                    # run; every user run's behaviour is byte-for-byte unchanged.
                    if _is_operator_scoped_run() and classify_llm_failure(exc) != (
                        LLM_FAILURE_INSUFFICIENT_CREDITS
                    ):
                        chain = chain[: idx + 1]
                        break
                    _stage_fallback_reason(attempt_model, exc)
                    if isinstance(exc, InsufficientCreditsError):
                        free_chain_models.update(
                            self._extend_chain_with_admin_free_models(
                                chain, prompt_name
                            )
                        )
                    # CRITICAL-3: exponential backoff with FULL JITTER before
                    # the next model — but ONLY for a retryable class. A 402 /
                    # 401 answer does not change while we wait, so waiting on
                    # one would only add latency to a failure that is already
                    # certain (the admin free-model rescue appended above is
                    # a DIFFERENT question — a $0-priced model on the same
                    # credential — so it is asked immediately).
                    if (
                        classify_llm_failure(exc) == LLM_FAILURE_RETRYABLE
                        and idx + 1 < len(chain)
                        # RT-005: no wait after a synthetic cooling skip — the
                        # answer was known without a network call.
                        and not getattr(exc, "_aether_cooling_skip", False)
                    ):
                        delay = _backoff_delay(retry_attempt)
                        # Never spend budget a real attempt still needs.
                        headroom = self._remaining_budget() - _MIN_ATTEMPT_SECONDS
                        delay = min(delay, max(0.0, headroom))
                        if delay > 0:
                            logger.info(
                                "LLM backoff %.2fs before next model (prompt=%s, "
                                "attempt=%d)", delay, prompt_name, retry_attempt + 1,
                            )
                            _sleep_for_backoff(delay)
                        retry_attempt += 1
                    # RT-006: the PRIMARY model (the user's explicit pick /
                    # the configured first choice) that hits a REAL 429 gets
                    # exactly ONE same-model retry after a short jittered wait
                    # BEFORE any fallback is consulted.
                    # Live evidence (2026-08-16 ~14:42Z, subscription window at
                    # its boundary): the identical request 429'd then served
                    # 'OK' seconds later — so one bounded retry converts an
                    # honest-but-avoidable failure into the user's chosen model
                    # actually serving. Guards: never for a synthetic cooling
                    # skip, never while the model is cooling, at most once per
                    # call, and only when the budget still holds an attempt.
                    if (
                        idx == 0
                        and same_model_429_retries == 0
                        and _exc_is_http_429(exc)
                        and not getattr(exc, "_aether_cooling_skip", False)
                        and _model_cooling_seconds_left(attempt_model) <= 0
                        and self._remaining_budget()
                        > _MIN_ATTEMPT_SECONDS + _SAME_MODEL_429_RETRY_DELAY_MAX
                    ):
                        same_model_429_retries += 1
                        delay = random.uniform(
                            _SAME_MODEL_429_RETRY_DELAY_MIN,
                            _SAME_MODEL_429_RETRY_DELAY_MAX,
                        )
                        logger.info(
                            "RT-006: sole-model %s hit a 429 — one same-model "
                            "retry in %.1fs (prompt=%s)",
                            attempt_model, delay, prompt_name,
                        )
                        _sleep_for_backoff(delay)
                        continue
                    break  # genuine call error → next model (no same-model retry)
                if validate is not None:
                    try:
                        validate(content)
                    except Exception as exc:  # malformed/unusable — retryable
                        last_error = exc
                        logger.warning(
                            "LLM returned unusable content (model=%s, prompt=%s): "
                            "%s — retrying", attempt_model, prompt_name, exc,
                        )
                        continue  # bounded same-model re-draft, then next model
                # A LATER model served this call, so the staged reason is now a
                # real fallback engagement rather than one more failed attempt
                # (R-5). Published here, at the only point that knows both that
                # the primary was abandoned AND that something else worked.
                if idx > 0:
                    _promote_fallback_reason()
                # RT-005: a real success ends the model's 429 streak.
                _clear_model_429(attempt_model)
                # Record only if missing so curated replay fixtures are
                # never clobbered by variable live output.
                if not self._fixture_path(prompt_name, fixture_key).is_file():
                    self._record(prompt_name, fixture_key, content)
                return content
            if budget_exhausted:
                break
            idx += 1
        # Live retry chain exhausted — surface an HONEST failure, never a fixture.
        detail = (
            "budget exhausted before any live attempt could complete"
            if budget_exhausted
            else f"live call failed{f': {last_error}' if last_error else ''}"
        )
        # CRITICAL-3: carry the CLASS of the failure that ended the chain.
        # Erasing it here is what turned an OpenRouter 402 into "temporarily
        # unavailable, try again in a moment" and let the autopilot re-attempt
        # the same 10 jobs every cron tick, indefinitely, on a metered API.
        # A budget exhaustion is always retryable regardless of what any
        # earlier attempt raised — the provider never got the last word.
        failure_class = (
            LLM_FAILURE_RETRYABLE if budget_exhausted
            else classify_llm_failure(last_error)
        )
        provider = getattr(last_error, "provider", None)
        if failure_class in LLM_NON_RETRYABLE_FAILURE_CLASSES:
            ctx = _user_cred_context.get()
            ctx_user_id = ctx[0] if ctx else None
            _record_llm_circuit_open(
                ctx_user_id, provider or resolve_provider(primary), failure_class
            )
        raise LLMUnavailableError(
            f"LLM backend unavailable: {detail} for '{prompt_name}'",
            failure_class=failure_class,
            provider=provider,
        )

    @staticmethod
    def _extend_chain_with_admin_free_models(
        chain: list[str], prompt_name: str
    ) -> list[str]:
        """ADMIN-ONLY rescue: append FREE models after an OpenRouter HTTP 402.

        An operator mandate (MODELS-LIVE, evidence
        ``uat/reports/evidence/free-model-fallback/PROBE-REPORT.json``): when the
        OpenRouter account is out of credits, the OWNER's pipeline must keep
        producing by continuing the chain with $0-priced models — which the live
        probe proved still return HTTP 200 on the very same zero-credit key,
        because OpenRouter's 402 gate is per-model-price, not account-wide.

        Scope, deliberately narrow:

        - ONLY on :class:`InsufficientCreditsError` (OpenRouter 402). A 404 /
          429 / 5xx / timeout is untouched — those are model failures, and
          swapping models for them is what ADR-ML-3 forbids.
        - ONLY when the run carries a user context whose ``User.isAdmin`` is
          true (today: the owner alone). No user context (background/CLI) or a
          non-admin user → this is a no-op and the caller's behaviour is
          byte-for-byte what it was before the feature existed.
        - ONLY when the configured free list is non-empty (empty = kill switch).

        The extension is *idempotent*: models already in the chain are filtered
        out, so a 402 from a free model cannot re-extend or re-log.

        ADR-ML-3 interaction (documented, not incidental): when the primary is
        the user's deliberately CHOSEN model, ``_model_chain`` returns it alone
        so it is never silently substituted. A 402 is not a failure OF that
        model — it is a billing impossibility no model choice can satisfy — so
        for the admin account the rescue still engages. It is not silent: the
        INFO line below names every substituted model id and is greppable as
        ``admin-free-fallback``. Nothing changes for any other user.

        The appended models are ordinary chain entries: same ``_call_live``,
        same prompts, same validator, same downstream entailment/fabrication
        guards. There is no relaxed path and no silent success on garbage. Their
        REQUEST BODY is shaped (token cap + reasoning disabled, QA-FAIL-01) —
        which is why the appended ids are RETURNED: the caller records them so
        only these attempts are shaped and every other request stays identical.

        Returns the ids actually appended (empty when the rescue is a no-op).
        """
        free_models = get_admin_free_fallback_models()
        if not free_models:
            return []
        ctx = _user_cred_context.get()
        user_id = ctx[0] if ctx else None
        if not user_id or not _user_is_admin(user_id):
            return []
        pending = [m for m in free_models if m not in chain]
        if not pending:
            return []
        chain.extend(pending)
        logger.info(
            "admin-free-fallback: OpenRouter HTTP 402 (insufficient credits) — "
            "extending the model chain with free models [%s] for prompt=%s "
            "userId=%s",
            ", ".join(pending), prompt_name, user_id,
        )
        return pending

    @staticmethod
    def _model_chain(primary: str) -> list[str]:
        """Primary model, then one retry with the fallback model — EXCEPT when
        the primary IS the user's deliberately chosen model.

        ADR-ML-3 (§3.4.4 BLOCKER): a run bound to a USER-SELECTED model (the
        active :func:`user_model_context` resolved to exactly this ``primary``)
        must NEVER be silently served by a DIFFERENT model on failure — that is
        silent model substitution. In that case the chain is the chosen model
        ALONE, so a failure surfaces honestly (``LLMUnavailableError`` -> 503,
        reserved quota refunded by the router) instead of a fake success built
        from the hardcoded fallback the user never picked. The un-chosen
        SYSTEM-DEFAULT path keeps its existing one-retry resilience.

        OPERATOR ROLE (ADR-AGI-3 Decision 3): a run bound to an operator-scoped
        role gets the CONFIGURED operator chain appended after its primary —
        configuration of this same machinery, not a new provider layer. Two
        properties fall straight out of building the chain per call: the primary
        (the operator's Anthropic binding) leads EVERY invocation, so the
        auto-return the ADR requires is structural rather than a timer; and an
        unconfigured chain is empty, so the default behaviour is an honest
        failure rather than a reroute onto a payer nobody chose.
        """
        user_chosen = _user_model_context.get()
        if user_chosen is not None and primary == user_chosen:
            return [primary]
        if _is_operator_scoped_run():
            chain = [primary]
            for model in operator_fallback_chain():
                if model not in chain:
                    chain.append(model)
            return chain
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
        free_chain: bool = False,
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

        ``free_chain`` marks an attempt the ADMIN insufficient-credits rescue
        appended to the chain; it shapes the OpenRouter body (token cap +
        reasoning disabled — see :func:`_build_openrouter_request`) and nothing
        else. It is a no-op for the Anthropic transport, which never serves the
        rescue chain.
        """
        import httpx

        # MODEL-SUB-QUOTA: normalise AT the routing seam, so provider
        # resolution, the request body, the served-model disclosure and the cost
        # record all name the SAME id. For a Claude model this strips
        # OpenRouter's ``anthropic/`` namespace to the bare id the native
        # Messages API understands — same model, direct provider.
        model_id = normalize_model_id(model or get_model("REASONING"))
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
                # CRITICAL-3: the same row also carries the circuit breaker.
                # An OPEN circuit means the provider already refused for a
                # non-retryable reason (402/401) and we stopped asking — so we
                # refuse HERE, before a credential is resolved and before any
                # HTTP request exists, and say why.
                circuit = circuit_block_error(provider, block)
                if circuit is not None:
                    raise circuit
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
        # MODEL-SUB-QUOTA credential pin: a Claude model is served by the
        # Anthropic credential or by NOTHING. A resolution that came back
        # holding another provider's secret would be a bug, not a fallback —
        # refuse here rather than let it reach a transport.
        if is_claude_model(model_id) and cred.provider != "anthropic":
            raise RuntimeError(
                f"model '{model_id}' is a Claude model but the resolved credential "
                f"is for provider '{cred.provider}'. Claude runs are served only by "
                "the Anthropic credential (the operator's subscription) — the "
                "request is refused rather than billed to another account."
            )
        if provider == "anthropic":
            req = build_anthropic_request(
                model_id, system, user,
                auth_mode=cred.auth_mode, secret=cred.secret, base_url=cred.base_url,
            )
        else:
            req = _build_openrouter_request(
                model_id, system, user, temperature, cred, free_chain=free_chain
            )

        def _execute(request: dict[str, Any], seconds: float | None) -> httpx.Response:
            connect = CONNECT_TIMEOUT
            read = READ_TIMEOUT
            if seconds is not None:
                connect = max(1.0, min(connect, seconds))
                read = max(1.0, min(read, seconds))
            timeout = httpx.Timeout(connect=connect, read=read, write=10.0, pool=10.0)

            def _do_request() -> httpx.Response:
                return httpx.post(
                    request["url"], json=request["json"],
                    headers=request["headers"], timeout=timeout,
                )

            if seconds is None:
                return _do_request()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(_do_request)
                try:
                    return future.result(timeout=seconds)
                except concurrent.futures.TimeoutError as exc:
                    future.cancel()
                    raise RuntimeError(
                        f"LLM call exceeded hard budget of {seconds:.1f}s"
                    ) from exc
            finally:
                # Don't block on a straggling request thread; let it finish
                # in the background and be reaped when the response arrives.
                executor.shutdown(wait=False)

        started = time.monotonic()
        resp = _execute(req, max_seconds)
        #: The body actually on the wire for the LAST request of this attempt —
        #: a re-send below strips a key from THIS, never from the original, so
        #: each parameter is dropped at most once per attempt.
        sent = req
        if free_chain and resp.status_code == 400 and "reasoning" in req["json"]:
            # The rescue list is env-overridable against a CHURNING free catalog,
            # so an operator can legitimately point it at a model that rejects
            # the reasoning parameter. A 400 on a body WE shaped is a
            # request-shape rejection, so the attempt is re-sent ONCE with that
            # parameter dropped (the token cap is kept) rather than being spent.
            # Same model, same prompt, same credential — this is a re-send, not
            # model substitution, and it is bounded to exactly one extra request.
            remaining = (
                None if max_seconds is None
                else max_seconds - (time.monotonic() - started)
            )
            if remaining is None or remaining >= 1.0:
                logger.warning(
                    "free-chain model %s rejected the reasoning parameter "
                    "(HTTP 400: %s); re-sending once without it",
                    model_id, resp.text[:150],
                )
                unshaped = {
                    **req,
                    "json": {k: v for k, v in req["json"].items() if k != "reasoning"},
                }
                sent = unshaped
                resp = _execute(unshaped, remaining)
        if (
            resp.status_code == 400
            and "temperature" in sent["json"]
            and _rejects_request_parameter(resp.text, "temperature")
        ):
            # MON-019: the provider explicitly refused a request PARAMETER we
            # chose, not the prompt or the model. Same reasoning (and the same
            # bound) as the free-chain re-send above: drop ONLY the named key
            # and re-send once — same model, same prompt, same credential, so
            # this is a re-send, not model substitution (ADR-ML-3), and it is
            # never silent (the warning below names the model and the body).
            #
            # Why it matters beyond the historical signature: a user-CHOSEN
            # model gets a single-model chain, so one parameter-shape 400 would
            # otherwise spend the whole run — and OpenRouter serves many models
            # that take native params instead of ``temperature`` (ADR-ML-4).
            # A 400 that does NOT name the parameter is still spent on the
            # first request exactly as before.
            remaining = (
                None if max_seconds is None
                else max_seconds - (time.monotonic() - started)
            )
            if remaining is None or remaining >= 1.0:
                logger.warning(
                    "model %s rejected the temperature parameter (HTTP 400: %s); "
                    "re-sending once without it — same model, no substitution",
                    model_id, resp.text[:150],
                )
                stripped = {
                    **sent,
                    "json": {
                        k: v for k, v in sent["json"].items() if k != "temperature"
                    },
                }
                sent = stripped
                resp = _execute(stripped, remaining)
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
            message = f"LLM provider HTTP {resp.status_code}: {resp.text[:200]}"
            if provider == "openrouter" and resp.status_code == 402:
                # Out of OpenRouter credits. Same message and same RuntimeError
                # taxonomy as before — only the CLASS is narrower, so the chain
                # can tell "cannot pay for this model" apart from "this model
                # failed". OpenRouter-only by design: a 402 on the direct
                # Anthropic transport must never pull OpenRouter models (and
                # therefore OpenRouter billing) into an Anthropic-billed run.
                raise InsufficientCreditsError(message, provider=provider)
            if resp.status_code in (401, 403):
                # CRITICAL-3: the credential itself was rejected. Same message
                # and same RuntimeError taxonomy as before — only the CLASS is
                # narrower, so the chain can stop instead of re-presenting a
                # key the provider has already refused. Applies to BOTH
                # transports: a bad key is a bad key regardless of provider.
                raise ProviderAuthError(
                    message, provider=provider, status_code=resp.status_code
                )
            raise RuntimeError(message)
        body = resp.json()
        # The served model (+ accumulated usage, MF-1) is published only on
        # SUCCESS — after the content has been extracted and accepted — so a
        # failed attempt never leaves an observation the biller could mistake
        # for the model/spend that served (ML-W14; see
        # :func:`served_model_capture`).
        if provider == "anthropic":
            content = parse_anthropic_response(body)
            _publish_served_model(body, model_id)
            _accumulate_usage(len(system) + len(user), len(content))
            return content
        if "error" in body:
            raise RuntimeError(f"LLM provider error: {body['error']}")
        content = body["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM returned empty content")
        _publish_served_model(body, model_id)
        _accumulate_usage(len(system) + len(user), len(content))
        return content
