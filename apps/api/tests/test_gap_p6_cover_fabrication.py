"""GAP-P6-COV-001 — the tailor's evidence-grounding guard must be applied
CONSISTENTLY to the cover-letter path (§9 zero-tolerance for fabrication).

Writer-audit (uat/reports/evidence/phase6/writer-audit-G.json) finding: a live
Stripe cover letter claimed "my experience in portfolio intake management" and
"my record of leading program intake" — 'intake' is a term from the JOB TITLE
("Program Manager, Intake & Portfolio Management"), NOT from the candidate's
resume. The existing FabricationGuard only checks capitalized entities / numbers
so this lowercase, JD-sourced claim sailed through, while a second (clean) run
had no such claim — i.e. the guard was applied INCONSISTENTLY.

The fix reuses the tailor's ``unsupported_tokens`` mechanism, with the JD as a
RISK SIGNAL only (never evidence), scoped to FIRST-PERSON candidate claims (a
company/role description that echoes the posting is not a fabrication about the
candidate). A JD title/role term the candidate CLAIMS as their own experience
but their resume / story bank / profile never proves is removed via corrective
regeneration, or the run fails loudly rather than shipping it.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.cover_letter_agent import CoverLetterAgent, FabricationError
from app.services.resume_tailor import unsupported_claim_tokens

# --- 1. the guard function: flags JD-title claims, ignores descriptions --------


def test_claim_guard_flags_jd_title_noun_claimed_as_experience() -> None:
    """A job-title specialty ('intake') the candidate CLAIMS in first person but
    their evidence never proves is flagged; a title word they DO have
    ('portfolio') and a company-mission echo are not."""
    evidence = (
        "Led program delivery for a major bank. Managed a $5M program portfolio. "
        "Vikram Deshpande. end-to-end delivery leadership. Stripe"
    )
    jd_title = "Program Manager, Intake & Portfolio Management"
    model_text = (
        "My record of leading program intake aligns with Stripe's mission to grow "
        "revenue and increase the GDP of the internet. "
        "I would welcome a conversation about my experience in portfolio intake management."
    )
    flags = unsupported_claim_tokens(model_text, evidence, jd_title)
    assert "intake" in flags  # JD-title noun claimed as experience, unsupported
    assert "portfolio" not in flags  # candidate genuinely has it (in evidence)
    # company-mission echoes come from the JD DESCRIPTION, not the title risk
    # signal → never flagged (avoids rejecting legitimate company descriptions).
    for company_word in ("revenue", "gdp", "increase", "internet", "grow"):
        assert company_word not in flags, company_word


def test_claim_guard_does_not_over_reject_clean_letter() -> None:
    """The verified-clean Real Time letter (no fabrication) must yield zero
    flags even when the candidate's evidence is minimal — the guard must not
    break letters that legitimately echo the posting's emphasis words."""
    model_text = (
        "The emphasis this posting places on shipping reliable, measurable delivery "
        "outcomes is exactly the work I already do day to day. "
        "My recent work centres on owning sprint cadence and capacity management for "
        "multiple squads. I architected test-automation strategies that cut evidence "
        "effort from roughly 3 hours to about 15 minutes per scenario."
    )
    evidence = (
        "Senior Technical Program Manager. Sprint cadence, capacity management, "
        "squads, test-automation, evidence effort per scenario. Real Time"
    )
    assert unsupported_claim_tokens(model_text, evidence, "Lead BA/Service Designer") == []


def test_claim_guard_ignores_company_description_sentences() -> None:
    """A JD-title term appearing in a NON-first-person company description is not
    a claim about the candidate and must not be flagged."""
    evidence = "Led delivery for a bank. Jane. focus. Stripe"
    jd_title = "Program Manager, Intake & Portfolio Management"
    # No 'I/my/me' → a description of the role, not a candidate claim.
    model_text = "This role centres on intake governance across the portfolio."
    assert unsupported_claim_tokens(model_text, evidence, jd_title) == []


# --- 2. the guard is WIRED into the cover-letter run ---------------------------

_JOB = {
    "title": "Program Manager, Intake & Portfolio Management",
    "company": "Stripe",
    "description": (
        "Own program intake and portfolio prioritisation. Increase the GDP of the "
        "internet by growing revenue for businesses."
    ),
}


class _AlwaysFabricatesLLM:
    """Returns a structurally-valid letter that always claims JD-title 'intake'
    experience the candidate's evidence never proves."""

    def __init__(self) -> None:
        self.calls = 0

    def complete_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        return {
            "hook_reason": "My delivery record maps directly to the demands of this mandate.",
            "body": (
                "I bring deep, hands-on experience in portfolio intake management, "
                "having run delivery for a major bank.\n\n"
                "I would welcome an interview to discuss the role; I am available next week."
            ),
        }


class _StubJobs:
    def get_by_id(self, job_id, user_id):  # noqa: ANN001
        return dict(_JOB)


class _StubUsers:
    def get_by_id(self, user_id):  # noqa: ANN001
        return {"name": "Test User"}

    def get_target_role(self, user_id):  # noqa: ANN001
        return ""


class _StubStories:
    def list_by_user(self, user_id):  # noqa: ANN001
        return []


class _NoPersist:
    def create(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("a letter with a fabricated claim must never be persisted")


def test_cover_letter_run_rejects_fabricated_jd_title_claim() -> None:
    """End-to-end: a draft that claims a JD-title specialty ('intake') absent
    from the candidate's evidence is retried and then REJECTED (FabricationError)
    — never shipped. Before the fix the lowercase JD-sourced claim passed the
    capitalized-only guard and the letter shipped."""
    llm = _AlwaysFabricatesLLM()
    agent = CoverLetterAgent(
        llm=llm,
        jobs=_StubJobs(),
        users=_StubUsers(),
        letters=_NoPersist(),
        approvals=_NoPersist(),
        stories=_StubStories(),
    )
    with pytest.raises(FabricationError) as exc:
        agent.run("user-p6cov", "job-1")
    assert any("intake" in str(t).lower() for t in exc.value.flagged), exc.value.flagged
    # default + retry + retry2 corrective attempts, then reject.
    assert llm.calls == 3
