"""AUD-LLM-1 (RUN-20260818T0223Z) — failing tests for the two confirmed
defects in ``docs/delivery/evidence/RUN-20260818T0223Z/AUD-LLM-1/
01-scout-reproduction.log``:

(a) ``TailoringLoop.run()`` is wall-clock budgeted only (the shared
    ``llm_client.get_budget_seconds()`` deadline, armed once per client
    instance) plus an ITERATION cap (``DEFAULT_MAX_ITERATIONS = 5``,
    heightened to 7 via ``quality_policy``) — nothing in the stop condition
    ever counts TOKENS. A pathological run (a directive loop that never
    converges, an oversized résumé/JD) can burn the full iteration cap's
    worth of live calls with no token ceiling at all.

(b) Token usage is never persisted on the durable ``AgentRun.billingAuditJson``
    record — it carries only ``{authMode, provider, quotaPath, systemRun,
    credentialSource}`` (see 10-billingauditjson-sample.txt). The ephemeral
    per-agent ``output`` blob DOES carry ``tokensIn``/``tokensOut`` on a
    successful run, but that shape varies per agent and per completion path,
    so there is no ONE stable place a cost/failure audit can read a run's
    token spend from.

Stubs mirror the established convention in ``test_wc_tailoring_loop.py``
(``_CountingService``, a stepwise fake ATS engine) — redefined locally here so
this file stays self-contained.
"""
from __future__ import annotations

from app.services.ats_engine import ATSScore
from app.services.resume_tailor import TailorResult

_RESUME = (
    "JANE DOE\nBackend Engineer\n\nEXPERIENCE\n"
    "• Built backend services handling 500 requests per day.\n"
)
_ORIGINALS = [
    {"text": "Built backend services handling 500 requests per day.", "evidenceRef": "bullet-0"}
]
_JD = "Backend Engineer. We're looking for someone who cares about Kubernetes and Kafka."


class _CountingService:
    """Records every ``job_description`` it is called with; returns the
    (unchanged) originals as a no-op "rewrite" — sufficient for tests that
    only pin loop MECHANICS, not real tailoring content."""

    def __init__(self) -> None:
        self.jd_by_call: list[str] = []

    def tailor(self, resume_text, job_description, originals=None, evidence_extra=""):  # noqa: ANN001
        self.jd_by_call.append(job_description)
        bullets = list(originals or _ORIGINALS)
        return TailorResult(bullets=bullets, changes=1, originals=bullets)

    @property
    def calls(self) -> int:
        return len(self.jd_by_call)


class _StepwiseATS:
    """Returns a pre-programmed sequence of ``overall`` scores, one per call;
    holds the LAST value for any call beyond the sequence."""

    def __init__(self, overalls: list[float], missing_keywords: list[str] | None = None) -> None:
        self._overalls = overalls
        self._missing = missing_keywords or []
        self.calls = 0

    def score(self, resume_text, job_description) -> ATSScore:  # noqa: ANN001
        idx = min(self.calls, len(self._overalls) - 1)
        overall = self._overalls[idx]
        self.calls += 1
        return ATSScore(
            overall=overall,
            keyword_match=overall,
            semantic_similarity=overall,
            experience_gap=overall,
            matched_keywords=[],
            missing_keywords=list(self._missing),
            requires_review=overall < 60.0,
        )


class _GrowingUsage:
    """Stand-in for ``llm_client.get_accumulated_usage`` that reports a
    caller-controlled, ever-growing char count on each call — one call per
    ``TailoringLoop`` iteration in production (the real usage accumulates
    across the whole ``served_model_capture()`` scope, i.e. every iteration
    of the loop, which is exactly what this simulates without a real LLM
    client or capture scope open)."""

    def __init__(self, chars_in_per_call: int, chars_out_per_call: int) -> None:
        self._chars_in_per_call = chars_in_per_call
        self._chars_out_per_call = chars_out_per_call
        self.calls = 0

    def __call__(self) -> dict[str, int]:
        self.calls += 1
        return {
            "charsIn": self._chars_in_per_call * self.calls,
            "charsOut": self._chars_out_per_call * self.calls,
            "calls": self.calls,
        }


# ---------------------------------------------------------------------------
# (a) TailoringLoop — a REAL token budget in the stop condition.
# ---------------------------------------------------------------------------


def test_loop_stops_on_token_budget_with_honest_stop_reason_and_best_draft():
    """FAILS NOW: nothing in ``TailoringLoop.run()`` ever reads accumulated
    token usage, so a run whose score never reaches target burns every
    iteration in ``max_iterations`` regardless of how many tokens it has
    already spent. With a token budget wired in and injected usage that
    crosses it on iteration 2, the loop must STOP THERE — honestly, with the
    best draft achieved so far — never running iterations 3-5."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    # Never reaches the 85 target — isolates the token-budget stop condition
    # from the existing target/iteration-cap stop conditions.
    ats = _StepwiseATS([40.0, 45.0, 50.0, 55.0, 60.0])
    usage = _GrowingUsage(chars_in_per_call=1600, chars_out_per_call=400)
    # iteration 1: charsIn=1600, charsOut=400 -> 400 + 100 = 500 tokens (< 1000)
    # iteration 2: charsIn=3200, charsOut=800 -> 800 + 200 = 1000 tokens (>= 1000)
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=5, target_score=85.0,
        token_budget=1000, usage_provider=usage,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert service.calls == 2, (
        f"loop must stop the instant the token budget is exhausted, not run "
        f"to the iteration cap — got {service.calls} calls"
    )
    assert len(result.iterations) == 2
    assert result.stop_reason == "token_budget_exhausted", result.stop_reason
    assert result.success is False, "45/50 never reached the 85 target"
    assert result.final_bullets, "the best draft achieved so far must still be returned"
    assert result.best_score == 45.0, "iteration 2 (45.0) beat iteration 1 (40.0)"
    assert result.warning, "an honest sub-target warning must be surfaced"
    assert "token" in result.warning.lower(), result.warning


def test_loop_never_hits_a_generous_token_budget_within_the_iteration_cap():
    """PIN: the token budget only bites when it is actually exceeded — a
    generous budget must never truncate a run that the iteration cap alone
    would already bound. Guards against the fix over-firing."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([40.0, 41.0, 42.0, 43.0])
    usage = _GrowingUsage(chars_in_per_call=1600, chars_out_per_call=400)
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=4, target_score=85.0,
        token_budget=1_000_000, usage_provider=usage,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert service.calls == 4, "a generous budget must not truncate the run early"
    assert result.stop_reason == "iteration_cap", result.stop_reason


def test_loop_token_budget_is_a_no_op_when_no_usage_is_observed():
    """PIN: outside a real ``served_model_capture()`` scope (replay/fixture
    mode, or a lightweight test double), ``get_accumulated_usage()`` returns
    ``None`` — the default ``usage_provider``. The loop must behave exactly
    as it did before this fix in that case: ``None`` is 'no observation', not
    a licence to guess or fabricate a token count that would spuriously stop
    a run. This is the DEFAULT usage_provider (no override) with a tiny
    token_budget, to prove the budget cannot fire on nothing observed."""
    from app.services.tailoring_loop import TailoringLoop

    service = _CountingService()
    ats = _StepwiseATS([91.0, 91.0, 91.0])
    loop = TailoringLoop(
        service=service, ats_engine=ats, max_iterations=5, target_score=85.0,
        token_budget=1,
    )
    result = loop.run(_RESUME, _JD, originals=_ORIGINALS)

    assert result.stop_reason == "target_reached"
    assert service.calls == 1


def test_token_budget_knob_is_read_from_the_env_var(monkeypatch):
    """The budget is env-overridable (``AETHER_TAILOR_TOKEN_BUDGET``), same
    pattern as ``llm_client.get_budget_seconds()``'s
    ``AETHER_LLM_BUDGET_SECONDS``. Constructing a loop with no explicit
    ``token_budget`` must read the env knob."""
    from app.services.tailoring_loop import TailoringLoop, get_token_budget

    monkeypatch.setenv("AETHER_TAILOR_TOKEN_BUDGET", "7777")
    assert get_token_budget() == 7777

    loop = TailoringLoop(service=_CountingService(), ats_engine=_StepwiseATS([1.0]))
    assert loop.token_budget == 7777


def test_token_budget_default_is_derived_from_measured_reality(monkeypatch):
    """The DEFAULT (env unset) must be a defensible ceiling ABOVE both the
    measured standard-tier (5-iteration) average — 55,793 prompt + 5,196
    completion tokens ≈ 60,989 tokens per full run (AUD-ECON-2 scout,
    docs/delivery/evidence/RUN-20260818T0223Z/AUD-ECON-2/
    01-scout-reproduction.log (a)) — and the heightened-tier (7-iteration)
    linear extrapolation of that same average (≈ 85,385 tokens), so a
    genuinely convergent heightened-tier run is never clipped mid-way."""
    from app.services.tailoring_loop import DEFAULT_TOKEN_BUDGET, get_token_budget

    monkeypatch.delenv("AETHER_TAILOR_TOKEN_BUDGET", raising=False)
    assert get_token_budget() == DEFAULT_TOKEN_BUDGET
    measured_standard_tier_average = 55793 + 5196
    heightened_tier_extrapolation = measured_standard_tier_average * 7 / 5
    assert DEFAULT_TOKEN_BUDGET > measured_standard_tier_average
    assert DEFAULT_TOKEN_BUDGET > heightened_tier_extrapolation


# ---------------------------------------------------------------------------
# (b) billingAuditJson — token usage persisted beside costUsd (DB test).
# ---------------------------------------------------------------------------


def test_tailor_run_persists_prompt_and_completion_tokens_onto_billing_audit(
    client, auth_headers, test_user_id, monkeypatch,
):
    """FAILS NOW: ``AgentRun.billingAuditJson`` is written once, BEFORE
    execution (``_record_run`` -> ``_persist_billing_audit``), and never
    updated afterward — so it never carries the run's actual token spend,
    only pre-execution provenance (authMode/provider/quotaPath/
    credentialSource). The one place a genuine cost/failure audit could read
    a STABLE, per-agent-independent token figure from has nothing in it,
    exactly the AUD-LLM-1 (b) finding. Additive: existing keys must survive
    untouched."""
    from app.db import get_connection
    from app.repositories.user_provider_credential import UserProviderCredentialRepository
    from app.routers.agents import _record_run

    monkeypatch.setenv("AETHER_MODEL_REASONING", "claude-haiku-4-5")
    UserProviderCredentialRepository().upsert(
        test_user_id, "anthropic", auth_mode="oauth_token",
        secret="sk-ant-oat01-aud-llm-1-tokens",
    )

    def _tailor_stub():
        return {"resume_id": "r1", "changes": [], "rejected": []}

    out = _record_run(test_user_id, "tailor", {"job_id": "j"}, _tailor_stub)
    run_id = out["run_id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "billingAuditJson" FROM "AgentRun" WHERE "id" = %s', (run_id,)
            )
            audit = cur.fetchone()[0]

    assert audit is not None
    assert "promptTokens" in audit, audit
    assert "completionTokens" in audit, audit
    assert audit["promptTokens"] == out["tokensIn"]
    assert audit["completionTokens"] == out["tokensOut"]
    assert audit["promptTokens"] > 0
    # Pre-existing provenance fields survive untouched (additive only).
    assert audit["authMode"] == "oauth_token"
    assert audit["provider"] == "anthropic"
    assert audit["quotaPath"] == "subscription_quota"


def test_deterministic_agent_billing_audit_carries_no_token_fields(
    client, auth_headers, test_user_id,
):
    """PIN: a deterministic (non-LLM) agent's audit stays ``{'quotaPath':
    'none'}`` — the additive token write must never fabricate token fields
    for a run that made no LLM call at all."""
    from app.routers.agents import _record_run

    out = _record_run(
        test_user_id, "scout", {}, lambda: {"persisted": 0, "updated": 0, "errors": []}
    )
    assert out["billingAudit"] == {"quotaPath": "none"}
