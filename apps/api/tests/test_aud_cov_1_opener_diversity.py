"""AUD-COV-1 — opener diversity + honesty (RUN-20260818T0223Z).

Regression guard for the defect the audit found: ``build_body()`` hardcoded
an unconditional "... is a direct match for the <role> role at <company>."
as sentence 1, with the model's JD-grounded ``hook_reason`` only trailing
it — so every letter's substantive opening CLAIM was identical (only
role/company text varied) and asserted "direct match" even for a poor-fit
role. See docs/delivery/evidence/RUN-20260818T0223Z/AUD-COV-1/
01-scout-reproduction.log for the reproduction and file:line references
(``cover_letter_agent.py:980-998``).

The fix: ``hook_reason`` — the model-authored, JD-grounded sentence — IS
sentence 1 (the substantive opener); the deterministic clause that follows
only NAMES the real role/company, with no unconditional "direct match" /
fit-strength assertion. This file pins that shape directly against
``build_body()`` — the exact function the audit named as the root cause —
so the regression is caught even if some other code path reintroduces the
phrase.
"""
from __future__ import annotations

from app.agents.cover_letter_agent import (
    build_body,
    split_paragraphs,
    strip_letter_scaffolding,
)

_JOB_A = {"title": "Senior Machine Learning Engineer", "company": "Nearmap"}
_JOB_B = {"title": "Delivery Solutions Architect", "company": "Databricks"}

_HOOK_REASON_A = (
    "Nearmap's need for production-quality Python in shared platform "
    "services lines up with the real-time telemetry servers I built."
)
_HOOK_REASON_B = (
    "Databricks' need for a technical lead who can own post-sale delivery "
    "matches the cloud-migration programs I have run end to end."
)

_LLM_BODY = (
    "I delivered measurable outcomes across cross-functional teams.\n\n"
    "I would welcome an interview to discuss the role further."
)

_POSITION = "Delivery Lead"


class TestNoUnearnedDirectMatchClaim:
    def test_opener_never_asserts_direct_match(self):
        for job, reason in ((_JOB_A, _HOOK_REASON_A), (_JOB_B, _HOOK_REASON_B)):
            body = build_body(_LLM_BODY, job, _POSITION, reason)
            assert "is a direct match for" not in body.lower()

    def test_opener_never_asserts_direct_match_even_with_no_hook_reason(self):
        """Honest fallback (empty hook_reason): the deterministic clause
        alone must still never assert an unconditional, fit-unaware match."""
        body = build_body(_LLM_BODY, _JOB_A, _POSITION, "")
        assert "is a direct match for" not in body.lower()


class TestHookReasonLeads:
    def test_hook_reason_is_the_substantive_opening_sentence(self):
        body = build_body(_LLM_BODY, _JOB_A, _POSITION, _HOOK_REASON_A)
        hook_paragraph = split_paragraphs(body)[0]
        assert hook_paragraph.startswith(_HOOK_REASON_A), (
            f"hook_reason must lead the opener, got: {hook_paragraph!r}"
        )

    def test_role_and_company_still_present_in_paragraph_one(self):
        body = build_body(_LLM_BODY, _JOB_A, _POSITION, _HOOK_REASON_A)
        hook_paragraph = split_paragraphs(body)[0]
        assert _JOB_A["title"] in hook_paragraph
        assert _JOB_A["company"] in hook_paragraph


class TestDistinctOpeners:
    def test_openers_differ_across_differing_jobs(self):
        """The pre-fix defect: every letter's substantive opening claim was
        identical text with only role/company substituted. Two different
        jobs with two different (JD-grounded) hook_reasons must now produce
        genuinely DIFFERENT opening sentences, not a shared template."""
        body_a = build_body(_LLM_BODY, _JOB_A, _POSITION, _HOOK_REASON_A)
        body_b = build_body(_LLM_BODY, _JOB_B, _POSITION, _HOOK_REASON_B)
        opener_a = split_paragraphs(body_a)[0]
        opener_b = split_paragraphs(body_b)[0]
        assert opener_a != opener_b
        # Not just different because role/company differ — the SUBSTANTIVE
        # sentence (the hook_reason clause) itself must differ.
        assert _HOOK_REASON_A in opener_a and _HOOK_REASON_A not in opener_b
        assert _HOOK_REASON_B in opener_b and _HOOK_REASON_B not in opener_a


class TestParagraphArithmeticPreserved:
    def test_three_paragraph_total_unaffected(self):
        """Structural invariant ``_structural_issues`` depends on (AUD-COV-1
        scout log, SUMMARY): total paragraph count stays 3 (hook + 2
        llm_body paragraphs) regardless of the opener wording change."""
        body = build_body(_LLM_BODY, _JOB_A, _POSITION, _HOOK_REASON_A)
        assert len(split_paragraphs(body)) == 3


class TestNewPhraseDedup:
    """``strip_letter_scaffolding``'s dedup regex must stay in lockstep with
    ``build_body``'s opener wording — see AUD-COV-1/01-scout-reproduction.log
    (b), which flags that a refine-model echoing the deterministic hook back
    would ship it TWICE if the regex's anchor phrase ever drifts from what
    build_body actually emits. This test proves the NEW anchor phrase ("led
    me to the") strips an echoed copy of the new opener end-to-end: an
    echoed deterministic clause is removed by strip_letter_scaffolding, and
    build_body then re-adds the real one exactly once."""

    def test_echoed_new_opener_is_stripped_so_build_body_adds_it_once(self):
        echoed_model_output = (
            f"My background led me to the {_JOB_A['title']} role at "
            f"{_JOB_A['company']}. I would be a strong fit for this "
            "position.\n\n"
            "I already own delivery outcomes across multiple squads."
        )
        cleaned = strip_letter_scaffolding(echoed_model_output)
        anchor = f"led me to the {_JOB_A['title']} role at {_JOB_A['company']}"
        assert anchor not in cleaned, (
            f"echoed opener was not stripped before recomposition: {cleaned!r}"
        )

        final_body = build_body(cleaned, _JOB_A, _POSITION, _HOOK_REASON_A)
        assert final_body.count(anchor) == 1, (
            "the real opener must appear exactly once after recomposition, "
            f"got {final_body.count(anchor)}: {final_body!r}"
        )

    def test_dedup_regex_does_not_over_strip_unrelated_sentences(self):
        """Control: a paragraph that names the role/company WITHOUT the
        anchor phrase must survive untouched (the regex targets the specific
        echoed clause, not any role/company mention)."""
        text = (
            f"I am excited about the {_JOB_A['title']} opening at "
            f"{_JOB_A['company']}.\n\nI would welcome an interview."
        )
        cleaned = strip_letter_scaffolding(text)
        assert _JOB_A["title"] in cleaned
        assert _JOB_A["company"] in cleaned
