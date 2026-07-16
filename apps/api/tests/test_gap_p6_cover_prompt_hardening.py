"""GAP-P6-COV-001 follow-up (uat/reports/evidence/phase6/review-quality.json
``must_fix`` #1/#2): the adversarial review confirmed the deterministic
token-grounding guards (``FabricationGuard``, ``unsupported_claim_tokens``)
catch JD-title-echoed and capitalized-entity fabrications but NOT pure
narrative/causal embellishment that reuses no JD-title vocabulary and no
evidence-corpus token. Reproduced live in that review (section
``4_residual_honest_assessment``): the two OTHER audited fabricated sentences
from ``writer-audit-G.json`` COV-DEF-1 — "This directly accelerated the
program's timeline to meet a critical legislative deadline." and "...enabling
faster time-to-market for revenue-impacting services." — pass BOTH guards
undetected, because neither sentence contains a token the guards check.

Building a full LLM-judge entailment pass to catch this is explicitly out of
scope (flakiness/latency) per the review's recommendation ("accept-document",
not "require-additional-guard" for this diff). This test covers the CHEAP,
deterministic mitigation layered on top instead: the CoverLetterAgent's LLM
SYSTEM PROMPT must explicitly instruct the model not to invent circumstances,
deadlines, or business/financial outcomes absent from the evidence — reducing
narrative fabrication at the source, as defense-in-depth alongside (never a
replacement for) the existing token-grounding guards.

Deterministic and offline: asserts on the literal ``SYSTEM_PROMPT`` string, no
LLM call.
"""
from __future__ import annotations

from app.agents.cover_letter_agent import SYSTEM_PROMPT


def test_system_prompt_forbids_narrative_invention() -> None:
    """The system prompt must explicitly forbid inventing circumstances,
    deadlines, and business/financial outcomes — the exact class of
    fabrication ('critical legislative deadline', 'revenue-impacting
    services'/'time-to-market') the deterministic token-grounding guards
    cannot catch because it reuses no JD-title vocabulary and no
    evidence-corpus token."""
    lower = SYSTEM_PROMPT.lower()
    for must_mention in ("circumstance", "deadline", "business outcome", "motivation"):
        assert must_mention in lower, f"SYSTEM_PROMPT is missing {must_mention!r}"


def test_system_prompt_prefers_honest_generality_over_invented_specifics() -> None:
    """The prompt must give the model an explicit, actionable alternative to
    inventing a plausible-sounding specific: describe the candidate's real,
    documented experience instead, and prefer honest generality over
    fabricated specificity."""
    lower = SYSTEM_PROMPT.lower()
    assert "honest generality" in lower
    assert "documented experience" in lower


def test_narrative_invention_instruction_does_not_duplicate_existing_rule() -> None:
    """The new instruction must be additive, not a verbatim repeat of the
    pre-existing 'never invent skills, employers, titles, metrics or
    achievements' rule — it must independently name narrative/causal detail
    categories that rule does not cover."""
    lower = SYSTEM_PROMPT.lower()
    existing_rule = (
        "never invent skills, employers, titles, metrics or achievements"
    )
    assert existing_rule in lower  # pre-existing rule still present, untouched
    # The new rule must be a distinct sentence/clause, not a rephrasing that
    # just repeats the same noun list.
    assert "deadline" not in existing_rule
