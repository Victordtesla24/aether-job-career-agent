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

from app.agents.cover_letter_agent import (
    CoverLetterAgent,
    FabricationError,
    gate_pass_labels,
)
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


def test_employer_possessed_noun_phrase_passes() -> None:
    """A JD noun GENUINELY possessed by the employer ("your onboarding funnel")
    describes their world, not the candidate's track record — including when it
    is the topic of a sentence that goes on to state an opinion."""
    assert unsupported_claim_tokens(
        "Your onboarding funnel is where I see the sharpest leverage.",
        _EVIDENCE,
        _JD_TITLE,
    ) == []


def test_bare_role_noun_tail_without_a_possessor_stays_guarded() -> None:
    """Deliberate tightening after adversarial review of 66747b6
    (wave35-opus-review-verdict.json): an earlier revision exempted any token
    followed by a role-ish noun ("the marketplace CHALLENGES"), with NO
    requirement that the phrase belong to the employer. That tail reads
    identically when the candidate is claiming the work, so real fabrications
    escaped through it. Exemption now REQUIRES a possessor, and this
    unpossessed phrasing — honest but ambiguous — stays guarded; the corrective
    retry re-phrases it."""
    assert unsupported_claim_tokens(
        "The marketplace challenges in this role are the kind of problem that "
        "gets me out of bed.",
        _EVIDENCE,
        _JD_TITLE,
    ) == ["marketplace"]
    # …and the possessed phrasing of the same thought passes.
    assert unsupported_claim_tokens(
        "Your marketplace challenges are the kind of problem that gets me out "
        "of bed.",
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
        self.fixture_keys: list[str] = []

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.calls += 1
        self.prompts.append(user)
        # U2c: the agent labels each draft with WHY it was made — "default",
        # a corrective "retry"/"retry2" the guards forced, or a "quality"
        # quality-gate pass. Recording the label lets a test assert the reason
        # a draft happened instead of inferring it from a raw call count, which
        # conflates two different budgets.
        self.fixture_keys.append(str(kwargs.get("fixture_key") or "default"))
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
    # THE claim: the guards accepted the first draft, so no CORRECTIVE retry was
    # burned. U2c added a second, unrelated reason a draft can be re-run — the
    # quality gate spending its small env-capped budget trying to lift a
    # dimension above the 80% floor — so this asserts the STAGE rather than the
    # raw call count, which would otherwise read a gate pass as a guard failure.
    assert [k for k in llm.fixture_keys if k.startswith("retry")] == [], (
        f"an honest draft must not trigger a corrective retry: {llm.fixture_keys}"
    )
    # ...and whatever the gate spent stayed inside its bounded budget.
    assert llm.calls <= 1 + len(gate_pass_labels()), llm.fixture_keys


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


# ===========================================================================
# Adversarial-review regressions (wave35-opus-review-verdict.json, commit
# 66747b6 FAILED). Four REAL fabrications passed the first classifier because
# it recognised experience from a verb WHITELIST and exempted any token
# followed by a role-ish noun. Reproduction harness:
# uat/reports/evidence/models-live/wave35-opus-review/w11-adversarial-attack.py
# ===========================================================================

#: The reviewer's corpus: proves NOTHING about marketplace/onboarding.
_ATTACK_EVIDENCE = (
    "Software Engineer, Acme Widgets Pty Ltd, 2019-2023. Built internal tooling "
    "in Python and React for the warehouse team. Reduced deployment time by 40% "
    "through CI pipeline improvements. Mentored two junior engineers on test "
    "coverage practices. BSc Computer Science, University of Melbourne."
)
_ATTACK_JD = "Senior Marketplace Trust and Safety Onboarding Manager"


@pytest.mark.parametrize(
    ("bypass", "sentence"),
    [
        # 1. 'drew' (drew up = built) matched only the ASPIRATION cue list.
        (
            "aspiration-verb-disguised past tense",
            "I drew up the marketplace onboarding roadmap for my last three "
            "enterprise clients.",
        ),
        # 2. present continuous was in no cue list at all.
        (
            "present continuous",
            "I'm currently managing the marketplace onboarding pipeline for two "
            "major enterprise clients.",
        ),
        # 3. an ordinary irregular past tense missing from the whitelist.
        (
            "irregular past tense outside the whitelist",
            "I spoke daily with enterprise clients about the marketplace "
            "onboarding roadmap for two years.",
        ),
        # 4. determiner-less nominal self-description.
        (
            "determiner-less nominal self-description",
            "I'm marketplace onboarding lead for enterprise clients.",
        ),
    ],
)
def test_adversarial_review_bypasses_are_closed(bypass: str, sentence: str) -> None:
    """Each of these asserts real, unevidenced experience with a JD-domain noun
    and MUST be flagged. Experience detection now fails CLOSED — any verb after
    "I" is an assertion unless it is a modal or a verb of wanting — so no verb
    the author failed to enumerate can slip through."""
    flags = unsupported_claim_tokens(sentence, _ATTACK_EVIDENCE, _ATTACK_JD)
    assert "marketplace" in flags, f"{bypass} still bypasses the guard: {flags}"


@pytest.mark.parametrize(
    "sentence",
    [
        # present-continuous ASPIRATION counterpart of bypass 2
        "I'm excited to be learning about your marketplace onboarding model.",
        "I'm looking forward to the onboarding problems your team is solving.",
        # nominal-shaped ASPIRATION counterpart of bypass 4
        "I am keen on the marketplace onboarding work your team does.",
        "I'd love to help with your marketplace onboarding roadmap.",
    ],
)
def test_aspiration_counterparts_of_the_closed_bypasses_still_pass(
    sentence: str,
) -> None:
    """The boundary the fix must hold: the same grammatical shapes carrying
    INTEREST rather than experience are not claims. "I'm <-ing>" is a claim only
    when the participle describes work ("managing"), never when it carries
    intent ("looking", "learning"); "I'm <noun phrase>" is a claim only when the
    phrase names a job title."""
    assert unsupported_claim_tokens(sentence, _ATTACK_EVIDENCE, _ATTACK_JD) == []


# --- the produced live letters must keep passing ---------------------------

#: Model-authored text of the two letters this fix produced live against the
#: production-configured model (deepseek/deepseek-v4-pro, 2026-07-29T12:33Z,
#: uat/reports/evidence/models-live/ML-W11/live-proof.json), excluding the
#: deterministic role/company hook the guard never checks. Grounded solely in
#: FIXTURE_LLM_RESUME_TEXT — every one of these sentences is honest, so any
#: future flag here is a false positive that would zero out the product again.
_LIVE_LETTER_GRC = (
    "Deputy's global SaaS platform, serving over 1.5 million workers across "
    "100+ countries, requires rigorous governance and compliance frameworks, "
    "and my track record of delivering fully compliant, high-stakes program "
    "portfolios aligns with that need.\n"
    "The GRC Program Manager role at Deputy involves driving governance, risk "
    "management, and regulatory adherence for a platform of this scale. I "
    "directed AI/ML and MLOps CI/CD initiatives across a program portfolio "
    "valued at over $5M, maintaining 100% regulatory compliance for data "
    "initiatives. My collaboration with engineering and delivery squads, "
    "including leading 6 engineers and owning sprint cadence and PI Planning, "
    "ensures I can embed governance practices directly into development "
    "workflows.\n"
    "I would welcome the opportunity to discuss how my program leadership and "
    "compliance delivery can support Deputy's GRC objectives. I am available "
    "for a call at your convenience."
)
_LIVE_LETTER_MARKETPLACE = (
    "My background leading a six-engineer payments platform that handled 2 "
    "million requests per day, paired with direct experience driving executive "
    "status reporting and PI planning, mirrors this role's need to run "
    "high-volume operations and report risk metrics.\n"
    "At Canvatech, I led a payments platform that processed 2 million requests "
    "per day, improving throughput by 40 percent after migrating services to "
    "Kubernetes and Docker. I owned sprint cadence, capacity management, and "
    "executive status reporting for delivery squads.\n"
    "I would welcome a conversation about how my experience leading engineering "
    "initiatives and delivering clear operational metrics could support Culture "
    "Amp's marketplace trust work. I am available for a call this week or next."
)


@pytest.mark.parametrize(
    ("letter", "jd_title", "company"),
    [
        (_LIVE_LETTER_GRC, "GRC Program Manager", "Deputy"),
        (_LIVE_LETTER_MARKETPLACE, "Marketplace Trust & Safety Lead", "Culture Amp"),
    ],
)
def test_live_produced_letters_do_not_regress(
    letter: str, jd_title: str, company: str
) -> None:
    """Regression floor: the real letters this fix shipped must keep passing the
    guard as the classifier is hardened."""
    from conftest import FIXTURE_LLM_RESUME_TEXT

    flags = unsupported_claim_tokens(
        letter, f"{FIXTURE_LLM_RESUME_TEXT} {company}", jd_title
    )
    assert flags == [], f"a letter produced live is now rejected: {flags}"


# ===========================================================================
# Naming the advertised role vs. claiming to have held it.
# Live evidence (live-proof-hardened.json, 2026-07-29T13:27Z): after the
# referential exemption was tightened to require a possessor, the model's
# perfectly honest "…aligns with the GRC Program Manager role at Deputy" was
# flagged on all three attempts and the Deputy letter died — the original
# zero-letters catastrophe, reproduced. Naming the job you are applying for is
# not a claim to have done it; claiming the TITLE is.
# ===========================================================================

_GRC_EVIDENCE = (
    "Senior Software Engineer. Directed a $5M AI/ML program portfolio. "
    "100% regulatory compliance for data initiatives. Deputy"
)


@pytest.mark.parametrize(
    "sentence",
    [
        # verbatim live model output that was wrongly rejected
        "My experience directing compliance-focused AI/ML initiatives and "
        "managing program portfolios aligns with the GRC Program Manager role "
        "at Deputy.",
        "My delivery record matches the GRC Program Manager role at Deputy.",
        "My background mirrors the GRC Program Manager position described in "
        "your posting.",
    ],
)
def test_naming_the_advertised_role_is_not_a_claim(sentence: str) -> None:
    """A contiguous run of the JOB TITLE followed by a role deictic ("… role",
    "… position"), GOVERNED BY A DESCRIBING/ALIGNING PREDICATE, is the
    posting's own name for the job."""
    assert unsupported_claim_tokens(sentence, _GRC_EVIDENCE, "GRC Program Manager") == []


@pytest.mark.parametrize(
    ("sentence", "evidence", "jd_title"),
    [
        ("I have been a GRC Program Manager for five years.",
         _GRC_EVIDENCE, "GRC Program Manager"),
        ("I was the GRC Program Manager at my last employer.",
         _GRC_EVIDENCE, "GRC Program Manager"),
        ("I'm a Marketplace Trust and Safety Lead by trade.",
         _EVIDENCE, "Marketplace Trust & Safety Lead"),
    ],
)
def test_claiming_to_hold_the_advertised_title_is_still_a_claim(
    sentence: str, evidence: str, jd_title: str
) -> None:
    """The exemption requires BOTH a title run AND a role deictic after it, so
    asserting the candidate HOLDS that title never qualifies."""
    assert unsupported_claim_tokens(sentence, evidence, jd_title) != []


# ===========================================================================
# Second adversarial review of 1be917e (wave35-opus-review-verdict.json):
# the title+deictic exemption fired on ADJACENCY ALONE, so a sentence claiming
# personal TENURE in the exact advertised title was exempted even though the
# classifier had correctly detected it as an EXPERIENCE assertion. This is the
# SOLE guard layer for that claim — FabricationGuard(entities) carries the job
# title in its own evidence corpus by design and never checks title-holding.
# Harness: uat/reports/evidence/models-live/wave35-opus-review/
#          w11-refix-title-deictic-attack.py (11 cases, mirrored below).
# ===========================================================================

_TENURE_EVIDENCE = (
    "Senior Software Engineer, Acme Widgets Pty Ltd, 2019-2023. Built internal "
    "tooling in Python and React for the warehouse team. Reduced deployment "
    "time by 40% through CI pipeline improvements. Mentored two junior "
    "engineers on test coverage practices. BSc Computer Science, University of "
    "Melbourne."
)


@pytest.mark.parametrize(
    ("bypass", "sentence"),
    [
        (
            "tenure claim: 'served in the <title> role'",
            "I served in the GRC Program Manager role for three years, leading "
            "enterprise-wide compliance initiatives.",
        ),
        (
            "tenure claim: 'held the <title> position'",
            "I held the GRC Program Manager position for over three years, "
            "owning enterprise-wide compliance programs.",
        ),
        (
            "deictic gamed by a first-person relative clause",
            "The GRC Program Manager position I excelled in for three years "
            "shaped my approach to governance.",
        ),
        (
            "participial tenure opener",
            "Having spent five years in the GRC Program Manager role, I "
            "understand these compliance demands intimately.",
        ),
        (
            "possessive tenure with the title as object",
            "My three years as a GRC Program Manager role have taught me to "
            "move fast.",
        ),
        (
            "two-word title run as the object of 'I have'",
            "I have the Program Manager role at Deputy.",
        ),
        (
            "relative-clause gloss after a describing predicate",
            "My work matched the GRC Program Manager role I held for three "
            "years.",
        ),
    ],
)
def test_tenure_in_the_advertised_title_is_never_exempt(
    bypass: str, sentence: str
) -> None:
    """Naming the advertised job is not a claim; OCCUPYING it is. The exemption
    requires a describing/aligning predicate to govern the title phrase and no
    first-person relative-clause gloss after it, so the title phrase can never
    be the object of the candidate's own assertion."""
    flags = unsupported_claim_tokens(sentence, _TENURE_EVIDENCE, "GRC Program Manager")
    assert "grc" in flags or "manager" in flags, (
        f"{bypass} still bypasses the guard: {flags}"
    )


@pytest.mark.parametrize(
    "sentence",
    [
        # no deictic after the title run
        "I have five years as a GRC Program Manager.",
        # deictic outside the recognised list
        "I owned the GRC Program Manager gig for three years running "
        "enterprise compliance.",
        # reordered / non-contiguous paraphrase of the title
        "I led the Program Manager, GRC role for three years.",
    ],
)
def test_title_exemption_controls_stay_flagged(sentence: str) -> None:
    """The reviewer's controls: each necessary condition of the exemption is
    load-bearing on its own."""
    assert unsupported_claim_tokens(
        sentence, _TENURE_EVIDENCE, "GRC Program Manager"
    ) != []


def test_object_of_a_first_person_assertion_is_not_role_naming() -> None:
    """Deliberate tightening (second review): a title phrase that is the OBJECT
    of a first-person assertion is no longer exempt, even with a valid deictic.
    "I have followed the GRC Program Manager posting" previously passed on
    adjacency alone; the same thought under a describing predicate still does."""
    assert unsupported_claim_tokens(
        "I have followed the GRC Program Manager posting since it opened.",
        _TENURE_EVIDENCE,
        "GRC Program Manager",
    ) != []
    assert unsupported_claim_tokens(
        "My background matches the GRC Program Manager posting.",
        _TENURE_EVIDENCE,
        "GRC Program Manager",
    ) == []


# ===========================================================================
# Third adversarial review of e05bcbd: the role-naming exemption's
# "no first-person gloss after the deictic" condition used a 2-TOKEN
# lookahead, and six graded gloss constructions simply stepped over it.
# The fix removes the distance parameter class rather than widening it: the
# exemption is voided by ANY return to the first person between the role
# phrase and the end of the sentence. Harness:
# uat/reports/evidence/models-live/wave35-opus-review/
#     w11-round3-gloss-distance-attack.py
# ===========================================================================


@pytest.mark.parametrize(
    ("bypass", "sentence"),
    [
        (
            "'where' clause 3+ tokens after the deictic",
            "My background matches the GRC Program Manager role at Deputy, "
            "where I spent three years leading it.",
        ),
        (
            "appositive gloss further out",
            "My skill set aligns with the GRC Program Manager role at Deputy, a "
            "position I held for three years and thrived in.",
        ),
        (
            "'that I' relative clause placed far after the deictic",
            "This opportunity mirrors the GRC Program Manager position at "
            "Deputy that I filled for three years.",
        ),
        (
            "sentence-final 'since I' gloss clause",
            "My track record suits the GRC Program Manager role at Deputy, "
            "since I handled the exact same governance duties for three years.",
        ),
        (
            "far \"I've\" gloss after a possessive company phrase",
            "My history relates to the GRC Program Manager role at Deputy's "
            "finance arm, where I've led compliance teams for three years.",
        ),
        (
            "two filler tokens probing the old lookahead boundary",
            "My background matches the GRC Program Manager role here at "
            "Deputy, where I spent three years leading it.",
        ),
        # --- my own attempts at the same class, beyond the reviewer's set ---
        (
            "em-dash gloss carrying only a possessive",
            "My background matches the GRC Program Manager role at Deputy — my "
            "own three years in it were formative.",
        ),
        (
            "'which my … tenure' relative clause",
            "My background matches the GRC Program Manager role at Deputy, "
            "which my three years of tenure prepared me for.",
        ),
        (
            "semicolon gloss (not a sentence boundary)",
            "My background matches the GRC Program Manager role at Deputy; I "
            "ran it for three years.",
        ),
        (
            "possessive-only gloss with no 'I' pronoun at all",
            "My background matches the GRC Program Manager role at Deputy, a "
            "position on my resume for three years.",
        ),
        (
            "gloss at the end of a very long sentence",
            "My background matches the GRC Program Manager role at Deputy, a "
            "global SaaS company serving over 1.5 million workers across more "
            "than one hundred countries worldwide, and I owned exactly that "
            "remit for three years.",
        ),
    ],
)
def test_any_first_person_after_the_role_phrase_voids_the_exemption(
    bypass: str, sentence: str
) -> None:
    """Categorical, distance-free: a sentence that names the advertised role and
    then swings back to the candidate is asserting something the guard cannot
    verify, at ANY distance and across ANY clause boundary."""
    flags = unsupported_claim_tokens(sentence, _TENURE_EVIDENCE, "GRC Program Manager")
    assert "grc" in flags or "manager" in flags, (
        f"{bypass} still bypasses the guard: {flags}"
    )


@pytest.mark.parametrize(
    "sentence",
    [
        "My background aligns with the GRC Program Manager role at Deputy.",
        "My delivery record matches the GRC Program Manager role at Deputy.",
        "My track record suits the GRC Program Manager role at Deputy.",
        "My background mirrors the GRC Program Manager position described in "
        "your posting.",
    ],
)
def test_role_naming_that_ends_the_sentence_still_passes(sentence: str) -> None:
    """The boundary that makes the categorical rule affordable: every
    legitimate role-naming shape finishes after naming the job, so voiding on
    any later first person costs nothing here."""
    assert unsupported_claim_tokens(
        sentence, _TENURE_EVIDENCE, "GRC Program Manager"
    ) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "The GRC Program Manager role at Deputy is exactly the kind of work I "
        "want to do.",
        "I am applying for the GRC Program Manager role because I admire the "
        "mission.",
        "I would welcome the chance to take on the GRC Program Manager role at "
        "Deputy.",
        "I'm excited about the GRC Program Manager role and what I could learn "
        "there.",
    ],
)
def test_aspiration_about_the_role_survives_the_categorical_rule(
    sentence: str,
) -> None:
    """These DO return to the first person after naming the role, and must
    still pass — they are exempt as ASPIRATION, independently of the
    role-naming rule. This is why the categorical rule does not cost the
    product its ordinary voice."""
    assert unsupported_claim_tokens(
        sentence, _TENURE_EVIDENCE, "GRC Program Manager"
    ) == []
