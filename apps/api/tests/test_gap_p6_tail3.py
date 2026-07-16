"""GAP-P6-TAIL-003 — robust anti-fabrication via ENTAILMENT verification, plus
budget allocation so a slow primary model never starves the faster fallback.

Two problems found by live production QA (uat/reports/evidence/phase6/
qa-prod-craft2.json):

1. **Semantic fabrication residual (§9 zero-tolerance).** After 3 deterministic
   token-grounding cycles a tailored bullet still occasionally gains an
   unsupported qualifier ("for financial institutions" on an InfoCentric bullet)
   whose individual words all appear elsewhere in the corpus (on a *different*
   employer), so the keyword guard waves it through. An LLM-judge entailment
   pass on the CHANGED bullets catches this class: a claim is entailed only if
   the evidence directly supports it for THIS bullet's context; anything else
   reverts to the original. A genuinely-supported change is kept (no
   over-revert), and a verifier FAILURE reverts conservatively — an unverified
   claim is never shipped.

2. **Budget starvation.** The heavy reasoning primary (deepseek-v4-pro,
   ~110-120s) consumed the whole ~85s budget before the faster fallback
   (deepseek-v4-flash) ever ran, so live attempts 503'd. Capping the primary
   attempt to a fraction of the budget leaves the fallback a real turn.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import llm_client
from app.services.llm_client import LLMClient, LLMUnavailableError
from app.services.resume_tailor import ResumeTailorService


class _ScriptedLLM:
    """Stub LLM that answers the tailor call and the entailment call distinctly.

    ``complete_json`` returns the tailor rewrite for the ``tailor`` prompt and a
    scripted verdict for the ``tailor_entailment`` prompt, recording that the
    entailment pass ran. ``fail_entailment`` makes the verifier call raise, to
    exercise the conservative fail-safe.
    """

    def __init__(
        self,
        tailor_raw: dict[str, Any],
        entailment_raw: dict[str, Any] | None = None,
        *,
        fail_entailment: bool = False,
    ) -> None:
        self.tailor_raw = tailor_raw
        self.entailment_raw = entailment_raw or {"results": []}
        self.fail_entailment = fail_entailment
        self.entailment_called = False
        self.entailment_model: str | None = None

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        if prompt_name == "tailor_entailment":
            self.entailment_called = True
            self.entailment_model = kwargs.get("model")
            if self.fail_entailment:
                raise LLMUnavailableError("entailment verifier down")
            return self.entailment_raw
        return self.tailor_raw


# --- Problem 1 (a): unsupported qualifier is reverted by entailment -----------

# The words "financial institutions" exist in the corpus — on the NAB bullet —
# so the deterministic token guard passes the InfoCentric rewrite. Only a
# semantic entailment judge can catch that InfoCentric is never tied to finance.
_RESUME_MIXED = (
    "EXPERIENCE\n"
    "NAB\n"
    "2015 - 2018 | Melbourne\n"
    "• Led regulatory reporting programs for financial institutions across core "
    "banking systems.\n"
    "InfoCentric\n"
    "2011 - 2014 | Sydney\n"
    "• Delivered analytics and Business Intelligence projects, boosting customer "
    "engagement by 20%.\n"
)
_ORIG_MIXED = [
    {
        "text": "Led regulatory reporting programs for financial institutions across "
        "core banking systems.",
        "evidenceRef": "bullet-0",
    },
    {
        "text": "Delivered analytics and Business Intelligence projects, boosting "
        "customer engagement by 20%.",
        "evidenceRef": "bullet-1",
    },
]
_JD_BA = (
    "Business Analyst, financial institutions. Requirements: analytics, business "
    "intelligence, financial services."
)


def test_entailment_reverts_unsupported_qualifier() -> None:
    """A tailored bullet whose added qualifier is NOT entailed by the evidence
    (even though its words appear elsewhere in the corpus) is reverted."""
    rewrite = {
        "bullets": [
            {
                "text": "Delivered analytics and Business Intelligence projects for "
                "financial institutions, boosting customer engagement by 20%.",
                "evidenceRef": "bullet-1",
            }
        ],
        "evidenceRefs": ["bullet-1"],
    }
    entail = {
        "results": [
            {
                "ref": "bullet-1",
                "entailed": False,
                "reason": "Evidence never ties InfoCentric to financial institutions.",
            }
        ]
    }
    llm = _ScriptedLLM(rewrite, entail)
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME_MIXED, _JD_BA, originals=_ORIG_MIXED
    )
    assert llm.entailment_called, "entailment verification pass did not run"
    reverted = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert reverted["text"] == _ORIG_MIXED[1]["text"], "fabrication was not reverted"
    assert "for financial institutions" not in reverted["text"]
    assert result.changes == 0
    assert any("financial institutions" in r for r in result.rejected)


# --- Problem 1 (b): a genuinely-supported change is KEPT (no over-revert) -----

_RESUME_K = (
    "EXPERIENCE\n"
    "Acme\n"
    "2019 - 2024 | Sydney\n"
    "• Built backend services, cutting latency by 40%.\n"
)
_ORIG_K = [
    {"text": "Built backend services, cutting latency by 40%.", "evidenceRef": "bullet-0"}
]
_EVID_K = "Story: Deployed Kubernetes clusters in production behind the backend services."
_JD_K = "Backend Engineer. Requirements: Kubernetes, backend services."
_REWRITE_K = {
    "bullets": [
        {
            "text": "Built backend services on Kubernetes, cutting latency by 40%.",
            "evidenceRef": "bullet-0",
        }
    ],
    "evidenceRefs": ["bullet-0"],
}


def test_entailment_keeps_supported_change() -> None:
    """A change the candidate's evidence genuinely proves (Kubernetes, in the
    Story Bank) is entailed and MUST be kept — strict ATS lift is preserved."""
    entail = {"results": [{"ref": "bullet-0", "entailed": True, "reason": "Story proves Kubernetes."}]}
    llm = _ScriptedLLM(_REWRITE_K, entail)
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME_K, _JD_K, originals=_ORIG_K, evidence_extra=_EVID_K
    )
    assert llm.entailment_called, "entailment verification pass did not run"
    kept = next(b for b in result.bullets if b["evidenceRef"] == "bullet-0")
    assert "Kubernetes" in kept["text"], "supported change was over-reverted"
    assert result.changes == 1
    assert not result.rejected


# --- Problem 1 (c): verifier failure reverts conservatively ------------------


def test_entailment_call_failure_reverts_conservatively() -> None:
    """If the entailment verifier call itself fails, every changed bullet is
    reverted — an unverified claim is never shipped (§9 zero-tolerance)."""
    llm = _ScriptedLLM(_REWRITE_K, fail_entailment=True)
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME_K, _JD_K, originals=_ORIG_K, evidence_extra=_EVID_K
    )
    assert llm.entailment_called
    kept = next(b for b in result.bullets if b["evidenceRef"] == "bullet-0")
    assert kept["text"] == _ORIG_K[0]["text"], "unverified claim shipped on verifier failure"
    assert result.changes == 0


def test_entailment_uses_structured_model() -> None:
    """The bounded verifier call uses the fast STRUCTURED tier, not the heavy
    reasoning model, so it fits inside the LLM budget."""
    import os

    llm = _ScriptedLLM(_REWRITE_K, {"results": []})
    ResumeTailorService(llm=llm).tailor(
        _RESUME_K, _JD_K, originals=_ORIG_K, evidence_extra=_EVID_K
    )
    assert llm.entailment_called
    assert llm.entailment_model == os.environ.get("AETHER_MODEL_STRUCTURED", llm.entailment_model)


# --- Problem 2 (d): primary attempt is capped so the fallback gets a turn -----


def test_primary_attempt_capped_so_fallback_gets_a_turn(monkeypatch) -> None:
    """A slow primary must not consume the entire budget. With the cap, when the
    primary uses its whole (capped) share and fails, the faster fallback still
    runs within the remaining budget. Without the cap the primary eats all 100s
    and the fallback is starved -> honest 503 (the live-QA failure)."""
    monkeypatch.setenv("AETHER_LLM_MODE", "auto")
    monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "100")
    monkeypatch.setenv("AETHER_LLM_PRIMARY_BUDGET_FRACTION", "0.55")
    monkeypatch.setenv("AETHER_MODEL_REASONING", "primary-model")
    monkeypatch.setenv("AETHER_MODEL_FALLBACK", "fallback-model")

    calls: list[tuple[str, float | None]] = []
    clock = {"t": 1000.0}
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: clock["t"])

    client = LLMClient()

    def fake_call_live(system, user, *, model, temperature, max_seconds=None):  # noqa: ANN001
        calls.append((model, max_seconds))
        if model == "primary-model":
            # Primary consumes its ENTIRE capped attempt, then fails (timeout).
            clock["t"] += max_seconds
            raise RuntimeError("primary reasoning model exceeded its cap")
        return '{"ok": true}'

    monkeypatch.setattr(client, "_call_live", fake_call_live)

    out = client.complete("tailor", "sys", "user")
    assert out == '{"ok": true}'
    assert calls[0][0] == "primary-model"
    # Primary capped at ~55% of the 100s budget, NOT the whole budget.
    assert calls[0][1] is not None and calls[0][1] <= 56.0
    # The fallback still got a turn within the remaining budget.
    assert any(model == "fallback-model" for model, _ in calls), "fallback was starved"
    fallback_call = next(c for c in calls if c[0] == "fallback-model")
    assert fallback_call[1] is not None and fallback_call[1] > 0


def test_primary_budget_fraction_env_default_and_clamp(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_LLM_PRIMARY_BUDGET_FRACTION", raising=False)
    assert llm_client.get_primary_budget_fraction() == 0.55
    monkeypatch.setenv("AETHER_LLM_PRIMARY_BUDGET_FRACTION", "not-a-number")
    assert llm_client.get_primary_budget_fraction() == 0.55
    monkeypatch.setenv("AETHER_LLM_PRIMARY_BUDGET_FRACTION", "1.5")  # out of band
    assert llm_client.get_primary_budget_fraction() == 0.55
    monkeypatch.setenv("AETHER_LLM_PRIMARY_BUDGET_FRACTION", "0.6")
    assert llm_client.get_primary_budget_fraction() == pytest.approx(0.6)
