"""ML-W11 — the §9 CLAIM guard rejects EVERY cover letter (100% loss).

Production defect (QA #2, ``uat/reports/evidence/prod-verify-2-wave2/
PROD-VERIFY-2.json``): since 2026-07-26T02:15Z **zero** real cover letters were
produced (0/781, 0/864, 0/209 daily). The LLM calls themselves were healthy
(6/6 HTTP 200); every draft died at ``cover_letter_agent.py`` ::

    raise FabricationError(claim_flags)   # the §9 CLAIM guard

``unsupported_claim_tokens`` (``app/services/resume_tailor.py``) flags a
JOB-TITLE noun the candidate's evidence never proves whenever it appears in ANY
sentence carrying ``I``/``my``/``me``. A writer of ordinary craft opens with an
*aspirational* sentence — "I am drawn to the marketplace challenges at X",
"I am excited by your trust and safety mission" — which contains a first-person
pronoun but asserts **no experience whatsoever**. Those got flagged
('marketplace', 'litigation', 'yield', 'onboarding', 'trust'/'safety', 'legal',
'JD'), survived every corrective retry, and the letter was rejected outright.

The bar itself is NOT the bug and must not move: a first-person claim to
personally possess a JD-domain capability the résumé never evidences must still
be rejected. This suite pins BOTH directions:

  (a) aspiration / role-referential shapes with the SAME tokens now PASS;
  (b) genuine fabricated experience claims with those tokens are STILL rejected;
  (c) the corrective retry enumerates the exact flagged tokens AND the rule, so
      a retry can actually converge instead of repeating the offence.

Run under the shared test DB lock::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ml_w11_cover_claim_context.py -q
"""
from __future__ import annotations

import pytest
from conftest import seed_own_resume

from app.agents.cover_letter_agent import CoverLetterAgent, FabricationError
from app.repositories.job import JobRepository
from app.services.fabrication_guard import FabricationGuard
from app.services.resume_tailor import unsupported_claim_tokens

# ---------------------------------------------------------------------------
# Shared corpus — the candidate's REAL evidence proves delivery/platform work
# and proves NONE of the JD-domain nouns the live rejections tripped over.
# ---------------------------------------------------------------------------

_EVIDENCE = (
    "Jordan Rivera. Senior Software Engineer. Led 6 engineers on a payments "
    "platform in Python and PostgreSQL, improving throughput 40 percent. "
    "Migrated services to Kubernetes and Docker. Owned sprint cadence and "
    "capacity management for delivery squads. Acme"
)

#: The JOB TITLE is the guard's risk vocabulary (never evidence). Every noun
#: below is one the live production rejections actually flagged.
_JD_TITLE = "Marketplace Trust & Safety Lead — Litigation, Onboarding & Yield (Legal)"


# ===========================================================================
# (a) The previously-rejected ASPIRATIONAL shapes must now pass
# ===========================================================================


@pytest.mark.parametrize(
    "sentence",
    [
        # the exact shape named in the production root cause
        "I am drawn to the marketplace challenges at Acme.",
        "I am excited by your trust and safety mission.",
        "The onboarding problems your team is solving are exactly what I want "
        "to work on.",
        "I would welcome the chance to help with the yield strategy this role "
        "owns.",
        "I am applying for this litigation role because the legal work "
        "resonates with me.",
        "What draws me here is the scale of your marketplace operations.",
    ],
)
def test_aspirational_jd_noun_sentences_are_not_claims(sentence: str) -> None:
    """A JD-domain noun used to express INTEREST in the role/company — no
    experience asserted — is not a fabrication about the candidate."""
    assert unsupported_claim_tokens(sentence, _EVIDENCE, _JD_TITLE) == []


def test_full_aspirational_letter_body_produces_no_claim_flags() -> None:
    """The realistic multi-sentence draft shape that died in production: an
    aspirational opener naming the role's domain, then evidence-grounded
    experience sentences, then an aspirational close."""
    model_text = (
        "I am drawn to the trust and safety problems your marketplace team is "
        "solving. My own record is in high-throughput platform delivery: I led "
        "6 engineers on a payments platform in Python and PostgreSQL, improving "
        "throughput 40 percent. I would welcome a conversation about how that "
        "delivery record maps onto your onboarding roadmap; I am available for "
        "an interview next week."
    )
    assert unsupported_claim_tokens(model_text, _EVIDENCE, _JD_TITLE) == []


def test_role_referential_noun_phrase_in_a_neutral_sentence_passes() -> None:
    """A JD noun modifying a ROLE/COMPANY head noun ("the marketplace
    challenges", "your onboarding roadmap") describes the employer's world, not
    the candidate's track record — even with no explicit aspiration verb."""
    assert unsupported_claim_tokens(
        "The marketplace challenges in this role are the kind of problem that "
        "gets me out of bed.",
        _EVIDENCE,
        _JD_TITLE,
    ) == []
    assert unsupported_claim_tokens(
        "Your onboarding funnel is where I see the sharpest leverage.",
        _EVIDENCE,
        _JD_TITLE,
    ) == []


# ===========================================================================
# (b) Genuine fabricated EXPERIENCE claims — same tokens — still rejected
# ===========================================================================


@pytest.mark.parametrize(
    ("sentence", "token"),
    [
        ("I led marketplace expansion for two years.", "marketplace"),
        ("My litigation experience spans complex commercial disputes.", "litigation"),
        ("I have run trust and safety operations at scale.", "trust"),
        ("I built the onboarding programme end to end.", "onboarding"),
        ("I own yield strategy for a two-sided platform.", "yield"),
        ("I am experienced in legal risk assessment.", "legal"),
        ("My background in marketplace policy is deep.", "marketplace"),
        ("I know the litigation lifecycle inside out.", "litigation"),
        ("Having run onboarding for a large platform, this is familiar ground "
         "for me.", "onboarding"),
        ("I am excited to bring my marketplace instincts to Acme.", "marketplace"),
        ("Drawing on my marketplace experience, I am excited by this role.",
         "marketplace"),
        ("I would love to return to litigation.", "litigation"),
    ],
)
def test_first_person_experience_claims_are_still_rejected(
    sentence: str, token: str
) -> None:
    """Unchanged bar: asserting personal experience with a JD-domain noun the
    evidence never proves is a fabrication — including when the assertion is
    wrapped in aspirational packaging ("excited to bring my marketplace
    instincts") or sits in the same sentence as an aspiration cue."""
    flags = unsupported_claim_tokens(sentence, _EVIDENCE, _JD_TITLE)
    assert token in flags, f"{token!r} must stay flagged in {sentence!r}: {flags}"


@pytest.mark.parametrize(
    ("sentence", "evidence", "jd_title"),
    [
        # Both sentences below are VERBATIM live output of the production
        # reasoning model (deepseek/deepseek-v4-pro), captured by
        # uat/reports/evidence/models-live/ML-W11/live-proof-run1-prerefinement.json.
        # They are the canonical cover-letter closing, and both were rejected.
        (
            "I would welcome a conversation about how my background in "
            "compliance-driven data infrastructure and program coordination "
            "could support Deputy's GRC goals.",
            # Mirrors the résumé corpus of that live run: it proves 'program'
            # (a $5M program portfolio) but never 'grc'.
            "Senior Software Engineer. 100% regulatory compliance for data "
            "initiatives. sprint cadence, PI Planning, capacity management. "
            "Directed a $5M AI/ML program portfolio. Deputy",
            "GRC Program Manager",
        ),
        (
            "I would welcome the opportunity to discuss how my experience in "
            "engineering leadership and operational data could support Culture "
            "Amp's marketplace.",
            "Senior Software Engineer. Led 6 engineers on a payments platform. "
            "executive status reporting. Culture Amp",
            "Marketplace Trust & Safety Lead",
        ),
    ],
)
def test_hypothetical_offer_to_the_employer_is_not_an_experience_claim(
    sentence: str, evidence: str, jd_title: str
) -> None:
    """The candidate's own background is described in THEIR vocabulary; the JD
    noun belongs to the EMPLOYER ("could support <Company>'s <X>"). A modal
    offer of future contribution asserts nothing about the candidate's past, so
    it must not be flagged even though the sentence also states real
    experience."""
    assert unsupported_claim_tokens(sentence, evidence, jd_title) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "I have supported your marketplace team for three years.",
        "I led the marketplace roadmap at my last company.",
        "I built your onboarding funnel.",
    ],
)
def test_hypothetical_exemption_never_covers_a_past_tense_claim(
    sentence: str,
) -> None:
    """The modal/offer exemption is scoped to HYPOTHETICAL predicates. A past
    or present-perfect assertion about the same employer-owned noun phrase is
    still a claim and stays flagged."""
    assert unsupported_claim_tokens(sentence, _EVIDENCE, _JD_TITLE) != []


def test_company_possessive_does_not_launder_an_experience_claim() -> None:
    """"your marketplace" is role-referential — but not when the candidate
    claims to have DONE it. The referential exemption must never apply to a
    sentence that asserts experience."""
    flags = unsupported_claim_tokens(
        "I led your marketplace expansion last year.", _EVIDENCE, _JD_TITLE
    )
    assert "marketplace" in flags, flags


# ===========================================================================
# End-to-end through CoverLetterAgent.run()
# ===========================================================================

_JOB = {
    "title": "Marketplace Trust & Safety Lead",
    "company": "Acme",
    "description": (
        "Own trust and safety policy for a two-sided marketplace. Partner with "
        "legal on escalations and improve seller onboarding."
    ),
}


class _StubLLM:
    """Deterministic stand-in for LLMClient.complete_json; records every user
    prompt so the corrective-retry feedback can be asserted on."""

    def __init__(self, hook_reason: str, body: str) -> None:
        self.hook_reason = hook_reason
        self.body = body
        self.calls = 0
        self.prompts: list[str] = []

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.calls += 1
        self.prompts.append(user)
        return {"hook_reason": self.hook_reason, "body": self.body}


def _seed_job(user_id: str, suffix: str) -> str:
    created = JobRepository().create(
        user_id,
        {
            **_JOB,
            "location": "Remote",
            "remote": True,
            "requirements": [],
            "source": "test",
            "sourceUrl": f"https://example.test/ml-w11/{suffix}",
            "postedAt": None,
        },
    )
    return created["id"]


#: An honest draft of ordinary craft: aspiration about the role's domain, then
#: experience claims grounded ONLY in the seeded résumé. Exactly the shape
#: production kept producing and the guard kept rejecting.
_HONEST_HOOK = "I am drawn to the trust and safety problems this role owns."
_HONEST_BODY = (
    "The marketplace challenges your team is solving are the kind of problem I "
    "want to work on. My own record is in high-throughput platform delivery: I "
    "led 6 engineers on a payments platform in Python and PostgreSQL, improving "
    "throughput 40 percent, and I migrated services to Kubernetes and Docker.\n\n"
    "I would welcome a conversation about how that delivery record maps onto "
    "your onboarding roadmap; I am available for an interview next week."
)

#: The same JD nouns, but asserted as the candidate's own experience — a real
#: fabrication the guard must keep rejecting.
_FABRICATED_HOOK = "My marketplace trust and safety record maps onto this mandate."
_FABRICATED_BODY = (
    "I have run trust and safety operations for a large marketplace, owning "
    "policy and enforcement end to end.\n\n"
    "I would welcome an interview to discuss the role; I am available next week."
)


def test_honest_aspirational_letter_is_produced(client, auth_headers) -> None:
    """THE customer-critical outcome: a letter that expresses interest in the
    role's domain and grounds every experience claim in the résumé must be
    PRODUCED — on the FIRST draft, with no corrective retry burned."""
    seed_own_resume(client, auth_headers)
    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    job_id = _seed_job(user_id, "honest")
    llm = _StubLLM(_HONEST_HOOK, _HONEST_BODY)
    agent = CoverLetterAgent(llm=llm, guard=FabricationGuard())

    result = agent.run(user_id, job_id)

    assert result.cover_letter, "no letter produced"
    assert "trust and safety" in result.cover_letter
    assert "marketplace challenges" in result.cover_letter
    assert result.approval_id, "no approval created for the drafted letter"
    assert llm.calls == 1, f"an honest draft must not trigger a retry: {llm.calls}"


def test_fabricated_experience_letter_is_still_rejected(client, auth_headers) -> None:
    """The honesty centrepiece holds end-to-end: the same JD nouns claimed as
    personal experience are retried and then REJECTED, never shipped."""
    seed_own_resume(client, auth_headers)
    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    job_id = _seed_job(user_id, "fabricated")
    llm = _StubLLM(_FABRICATED_HOOK, _FABRICATED_BODY)
    agent = CoverLetterAgent(llm=llm, guard=FabricationGuard())

    with pytest.raises(FabricationError) as exc:
        agent.run(user_id, job_id)

    flagged = [str(t).lower() for t in exc.value.flagged]
    assert "marketplace" in flagged, flagged
    assert llm.calls == 3, f"expected default + 2 corrective retries: {llm.calls}"


def test_retry_prompt_enumerates_flagged_tokens_and_the_rule(
    client, auth_headers
) -> None:
    """(c) A rejected draft's corrective retry must name the EXACT flagged
    tokens, forbid claiming personal experience with them, and state the
    permitted alternative (express interest) — otherwise the model has no way
    to converge and simply repeats the offence, which is what production did
    for three days."""
    seed_own_resume(client, auth_headers)
    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    job_id = _seed_job(user_id, "retry-enum")
    llm = _StubLLM(_FABRICATED_HOOK, _FABRICATED_BODY)
    agent = CoverLetterAgent(llm=llm, guard=FabricationGuard())

    with pytest.raises(FabricationError):
        agent.run(user_id, job_id)

    retry_prompt = llm.prompts[1]
    lower = retry_prompt.lower()
    for token in ("marketplace", "trust", "safety"):
        assert f"'{token}'" in lower, (
            f"retry prompt must enumerate the flagged token {token!r}: {retry_prompt!r}"
        )
    assert "do not claim personal experience with" in lower, retry_prompt
    assert "express interest" in lower, retry_prompt


def test_unevidenced_domain_noun_in_a_possessed_background_still_flagged() -> None:
    """Control for the case above: strip the evidence that proves 'program' and
    the SAME sentence is flagged again — the exemption is scoped to the
    employer-owned phrase, it never blankets the whole sentence."""
    flags = unsupported_claim_tokens(
        "I would welcome a conversation about how my background in "
        "compliance-driven data infrastructure and program coordination could "
        "support Deputy's GRC goals.",
        "Senior Software Engineer. 100% regulatory compliance for data "
        "initiatives. sprint cadence, PI Planning, capacity management. Deputy",
        "GRC Program Manager",
    )
    assert flags == ["program"], flags


@pytest.mark.parametrize(
    "sentence",
    [
        "I am a marketplace specialist.",
        "I'm a trust and safety lead by trade.",
        "I was the onboarding manager for that platform.",
    ],
)
def test_first_person_nominal_self_description_is_a_claim(sentence: str) -> None:
    """"I am a <JD-domain> <role title>" describes the candidate, so it is a
    claim — even though the same role-title head noun ("specialist", "lead")
    marks a phrase as role-referential when it describes the EMPLOYER's world
    ("the marketplace lead you are hiring")."""
    assert unsupported_claim_tokens(sentence, _EVIDENCE, _JD_TITLE) != []


@pytest.mark.parametrize(
    "sentence",
    [
        "My title was Trust and Safety Manager.",
        "My position was litigation counsel.",
        "My last role was marketplace lead.",
        "My team owned the onboarding funnel.",
    ],
)
def test_possessed_job_history_is_a_claim(sentence: str) -> None:
    """"my title / position / role / team" possesses a piece of the
    candidate's job history, so the sentence asserts experience — the
    role-title head noun inside it ("Manager", "counsel", "lead") must not
    exempt anything."""
    assert unsupported_claim_tokens(sentence, _EVIDENCE, _JD_TITLE) != []


def test_hypothetical_offer_survives_the_possessed_role_rule() -> None:
    """Control: "my role here WOULD BE to support your marketplace goals" is
    still a future offer, not a claim."""
    assert unsupported_claim_tokens(
        "My role here would be to support your marketplace goals.",
        _EVIDENCE,
        _JD_TITLE,
    ) == []
