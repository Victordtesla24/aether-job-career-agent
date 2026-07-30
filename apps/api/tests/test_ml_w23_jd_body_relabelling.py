"""ML-W23 / ML-W18 — the §9 claim guard's risk vocabulary was the job TITLE only.

**W-23 (QA3-F-04, proven live.)** Production run
``uat/reports/evidence/prod-verify-3/item1e-confirm-run2.txt``
(job ``c0fa013ab1789b46299ec7d11``, Stripe / *Program Manager, Security GRC*,
2026-07-29T17:17Z) shipped a letter that re-labelled the candidate's real
COBOL **test**-evidence automation as a "central **test-evidence repository**
… cutting **audit evidence** effort by 92%" and an "ATO **audit-evidence
framework**". ``"audit evidence"``, ``"repository"``, ``"soc 2"`` and
``"pci dss"`` have **0 hits** in either résumé — yet ``flagged=[]``.

Root cause is NOT the ML-W11 context classifier: it classified every offending
sentence as ``experience`` correctly. ``unsupported_claim_tokens`` restricts its
candidate tokens to ``tok in jd_stems``, and ``cover_letter_agent.run()`` passes
``jd_risk = job["title"]`` — so the ENTIRE job-description body was outside the
risk vocabulary. ``audit``/``repository``/``artifacts``/``central``/``soc``/
``pci``/``dss`` are all in the JD body and none are in the four-word title, so
no classifier rule ever saw them.

Widening the risk vocabulary to every JD-body word would be a false-positive
storm (measured: the same letter then flags ``create``, ``maintain``,
``global``, ``obligations``, ``represent`` — ordinary words the letter uses to
*quote the requirement*). The fix therefore adds a **phrase-level import
channel scoped to personal-claim spans**: see
``resume_tailor._jd_phrase_index`` / ``_claim_spans`` / ``_imported_jd_phrase_tokens``.

**W-18 (filed residual, orchestrator-adjudicated).** Cross-sentence anaphora:
"My background matches the X role. I held it for three years." Sentence 2
claims tenure through a pronoun and contains no JD token, so neither sentence
alone carried both signals.

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ml_w23_jd_body_relabelling.py -q
"""
from __future__ import annotations

import pytest

from app.agents.cover_letter_agent import SYSTEM_PROMPT
from app.services.resume_tailor import unsupported_claim_tokens

# ---------------------------------------------------------------------------
# REAL production data. Both blocks are verbatim from the live rows behind
# QA3-F-04 (pulled from the production DB, schema ``aether``).
# ---------------------------------------------------------------------------

#: Verbatim excerpt of ``Job.description`` for c0fa013ab1789b46299ec7d11 — the
#: Responsibilities / requirements block the letter mirrored.
_STRIPE_JD_BODY = (
    "Responsibilities Act as an information security subject matter expert "
    "during cross-functional audit engagements, representing the Security team "
    "in walkthrough meetings with auditors and regulators. Create and maintain "
    "a central repository of audit evidence artifacts required for compliance "
    "with SOC 2, PCI DSS, SOX, and other global regulatory standards. Perform "
    "security risk and control assessments against common frameworks to ensure "
    "compliance with Stripe's Information Security Policy and Standards. "
    "Strong program management skills with proficiency in coordinating security "
    "assessments and managing multiple stakeholder engagements across time zones."
)
_STRIPE_TITLE = "Program Manager, Security GRC"

#: Verbatim bullets of the approved tailored résumé ca2792fcc299fa8cd78aba626
#: that the letter drew on. Note what it DOES say: *test*-evidence automation,
#: "cutting evidence effort" — and what it never says: audit, repository.
_VIK_EVIDENCE = (
    "Vikram Deshpande. Business Analyst/Project Manager/Scrum Master. "
    "Test Automation Strategy: Architected the program's COBOL/mainframe "
    "test-evidence automation covering 200+ SIT/E2E scenarios across all eight "
    "squads, cutting evidence effort from ~3 hours to ~15 minutes per scenario "
    "(92% reduction) with a zero-new-approvals toolchain (REXX, SMF, SDSF, "
    "PCOMM, PowerShell, VBA). "
    "Delivery Leadership: Directed a program portfolio valued at over $5M, "
    "leading 5+ cross-functional squads (up to 40 resources, including offshore "
    "teams) to deliver on-time, high-quality releases. "
    "Stakeholder Leadership: Convened a cross-discipline technical war room "
    "that produced a binding automation recommendation in under three hours; "
    "unblocked stalled NTP function testing through L2 environment escalation. "
    "Managed the delivery stream for a critical risk and compliance program, "
    "ensuring 100% regulatory adherence for major data initiatives. Stripe"
)


# ===========================================================================
# W-23 (a) — the proven live leak must flag
# ===========================================================================


def test_live_qa3_f_04_relabelling_sentence_is_flagged() -> None:
    """The exact model-authored opening of the live letter. The candidate's real
    artifact is a *test*-evidence automation; the letter renames it a "central
    test-evidence repository" whose effort was "audit evidence" effort. Both
    re-labels are JD-body vocabulary with zero résumé support."""
    flags = unsupported_claim_tokens(
        "My experience architecting a central test-evidence repository for a "
        "major government reform program, cutting audit evidence effort by 92%, "
        "aligns directly with the need to create and maintain a central "
        "repository of audit evidence artifacts for Stripe's global compliance "
        "obligations.",
        _VIK_EVIDENCE,
        _STRIPE_TITLE,
        jd_body=_STRIPE_JD_BODY,
    )
    for token in ("repository", "audit"):
        assert token in flags, f"{token!r} must be flagged: {flags}"


def test_live_qa3_f_04_full_letter_is_flagged() -> None:
    """End-to-end over the whole model-authored text of the live letter
    (item1e-confirm-run2-letter.txt), which production shipped with
    ``flagged=[]``."""
    flags = unsupported_claim_tokens(
        _LIVE_QA3_LETTER, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body=_STRIPE_JD_BODY
    )
    assert "repository" in flags, flags
    assert "audit" in flags, flags


_LIVE_QA3_LETTER = (
    "My experience architecting a central test-evidence repository for a major "
    "government reform program, cutting audit evidence effort by 92%, aligns "
    "directly with the need to create and maintain a central repository of audit "
    "evidence artifacts for Stripe's global compliance obligations.\n"
    "The role calls for a program manager who can create and maintain a central "
    "repository of audit evidence artifacts for SOC 2, PCI DSS, and other global "
    "standards. At the Australian Taxation Office, I architected a COBOL/mainframe "
    "test-evidence automation harness covering 200+ SIT/E2E scenarios across eight "
    "squads, slashing evidence effort from ~3 hours to ~15 minutes per scenario "
    "(92% reduction) with a zero-new-approvals toolchain. The position also "
    "requires strong program management skills to coordinate security assessments "
    "and manage multiple stakeholder engagements across time zones. At ANZ, I "
    "directed a program portfolio valued at over $5M, leading 5+ cross-functional "
    "squads of up to 40 resources, and facilitated workshops for 40+ GMs and "
    "executives that improved decision-making efficiency by over 55%. Finally, the "
    "need to represent the Security team in audit walkthroughs resonates with my "
    "experience convening a cross-discipline technical war room at the ATO that "
    "produced a binding automation recommendation in under three hours and "
    "unblocked stalled testing through L2 environment escalation.\n"
    "I would welcome the chance to discuss how I can bring this evidence-driven "
    "approach to Stripe's team. I am available for a call at your convenience and "
    "can share concrete examples of the ATO audit-evidence framework and "
    "governance models I have built."
)


@pytest.mark.parametrize(
    ("shape", "sentence", "token"),
    [
        (
            "compliance-standard pair claimed as own experience",
            "I ran SOC 2 and PCI DSS audit programmes for three years.",
            "pci",
        ),
        (
            "JD noun phrase possessed by 'my'",
            "My central repository of audit evidence artifacts covered eight "
            "squads.",
            "repository",
        ),
        (
            "JD noun phrase as the object of a first-person assertion",
            "I built a central repository for the compliance team.",
            "repository",
        ),
        (
            "re-label grafted onto the candidate's own real phrase",
            "I cut audit evidence effort by 92% across 200+ scenarios.",
            "audit",
        ),
        (
            "possessed-track-record framing",
            "My background covers security risk and control assessments against "
            "common frameworks.",
            "assessments",
        ),
    ],
)
def test_jd_body_phrases_claimed_as_experience_are_flagged(
    shape: str, sentence: str, token: str
) -> None:
    """A JD-BODY noun phrase the résumé never supports, asserted as the
    candidate's own experience, is a fabrication regardless of whether its words
    happen to appear in the four-word job title."""
    flags = unsupported_claim_tokens(
        sentence, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body=_STRIPE_JD_BODY
    )
    assert token in flags, f"{shape}: {token!r} must be flagged: {flags}"


# ===========================================================================
# W-23 (b) — the OTHER direction: legitimate JD-referential / aspirational
# usage of the very same phrases must stay exempt. These are the shapes whose
# over-flagging zeroed the product for three days (ML-W11).
# ===========================================================================


@pytest.mark.parametrize(
    "sentence",
    [
        # describing what the ROLE needs — no first person at all
        "The role calls for a central repository of audit evidence artifacts "
        "for SOC 2, PCI DSS, and other global standards.",
        # first person, but the phrase belongs to the employer
        "Your central repository of audit evidence artifacts is the asset I "
        "would want to strengthen.",
        # first person, but ASPIRATION
        "I am drawn to the audit evidence repository work this role owns.",
        "I would welcome the chance to build a central repository of audit "
        "evidence artifacts.",
        "I am excited by the SOC 2 and PCI DSS challenges your team faces.",
        # a modal offer of future contribution
        "My delivery record could support the central repository of audit "
        "evidence artifacts you need.",
    ],
)
def test_jd_referential_and_aspirational_usage_stays_exempt(sentence: str) -> None:
    """The phrase channel fires only inside a personal-CLAIM span of a sentence
    the ML-W11 classifier already reads as asserting EXPERIENCE. Describing the
    employer's need, or wanting to do the work, asserts nothing about the
    candidate's past and must never be flagged."""
    assert (
        unsupported_claim_tokens(
            sentence, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body=_STRIPE_JD_BODY
        )
        == []
    )


def test_requirement_clause_before_the_claim_span_adds_nothing() -> None:
    """The live letter's honest third paragraph: it quotes the JD requirement
    ("represent the Security team in audit walkthroughs") and then says that
    requirement resonates with a résumé-backed war-room story. The quoted
    requirement sits OUTSIDE the personal-claim span, so the new channel must
    add nothing to whatever the pre-W-23 title channel already said (it flags
    'security' here, from the job TITLE — unchanged behaviour that this fix
    must neither weaken nor extend)."""
    sentence = (
        "Finally, the need to represent the Security team in audit walkthroughs "
        "resonates with my experience convening a cross-discipline technical war "
        "room at the ATO that produced a binding automation recommendation in "
        "under three hours."
    )
    before = unsupported_claim_tokens(sentence, _VIK_EVIDENCE, _STRIPE_TITLE)
    after = unsupported_claim_tokens(
        sentence, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body=_STRIPE_JD_BODY
    )
    assert after == before, f"the phrase channel over-fired: {before} -> {after}"


def test_truthful_terminology_mirroring_is_not_a_fabrication() -> None:
    """The FP floor that makes the channel affordable, measured on a real
    QA-PASSED letter (``prod-verify-3/item1-headline-letter.txt``, job
    c7ccd0437bbe6ff278b656427 — Samsara). Its opening imports the JD's own
    phrase "internal tools and AI-assisted workflows" into a first-person claim,
    but the substance (a JIRA analytics dashboard generating LLM-powered sprint
    plans) is genuinely the candidate's. Only ONE word of the imported phrase is
    unevidenced, and removing it leaves no résumé phrase behind — so this is
    terminology mirroring, not re-labelling."""
    samsara_jd = (
        "In this role you will create clickable prototypes, stand up your own "
        "dashboards and data models, and ship internal tools and AI-assisted "
        "workflows with engineering partnering to harden them for scale. Own "
        "what you ship as a living product: instrument adoption, track usage "
        "and business impact, and iterate. A track record of driving real "
        "adoption of internal tools, not just launching them."
    )
    # Verbatim further bullets of the same live tailored résumé — including the
    # one that evidences 'tool', which is why only ONE word of the imported
    # phrase is unevidenced.
    evidence = (
        _VIK_EVIDENCE
        + " AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, "
        "TypeScript, React/Next.js, Kubernetes, Docker. Relationship Timeline "
        "Visualisation: Developed a React/TypeScript visualisation tool "
        "featuring D3 event arcs for showcasing dynamic customer data. Built a "
        "JIRA analytics dashboard with Next.js and Supabase that generates "
        "LLM-powered sprint plans and retrospective insights, and stood up a "
        "Langfuse and Phoenix evaluation stack. Samsara"
    )
    flags = unsupported_claim_tokens(
        "My experience building internal AI-assisted tools that directly "
        "improve team velocity, like a JIRA analytics dashboard that generates "
        "LLM-powered sprint plans, aligns with your need for a builder who "
        "prototypes and ships solutions.",
        evidence,
        "Principal Business Technology Product Manager",
        jd_body=samsara_jd,
    )
    assert flags == [], f"a QA-PASSED live letter is now rejected: {flags}"


def test_evidence_backed_claim_using_jd_phrases_passes() -> None:
    """A candidate who genuinely has the JD's phrase in their evidence keeps it:
    the JD is a RISK signal, never the thing that makes a claim false."""
    evidence = _VIK_EVIDENCE + (
        " Built and maintained a central repository of audit evidence artifacts "
        "for SOC 2 and PCI DSS across eight squads."
    )
    assert (
        unsupported_claim_tokens(
            "I built and maintained a central repository of audit evidence "
            "artifacts for SOC 2 and PCI DSS.",
            evidence,
            _STRIPE_TITLE,
            jd_body=_STRIPE_JD_BODY,
        )
        == []
    )


@pytest.mark.parametrize(
    ("bypass", "sentence"),
    [
        (
            "describing verb used as the claim's own verb (gerund)",
            "My experience mapping a central repository of audit evidence "
            "artifacts spans eight squads.",
        ),
        (
            "describing verb used as the claim's own finite verb",
            "My background matches a central repository of audit evidence "
            "artifacts I built.",
        ),
        (
            "claim placed after the pivot to the posting",
            "My delivery record aligns with the posting, and I built a central "
            "repository of audit evidence artifacts.",
        ),
        (
            "possessed phrase across an appositive comma",
            "My work, a central repository of audit evidence artifacts, covered "
            "eight squads.",
        ),
    ],
)
def test_self_adversarial_span_bypasses_are_closed(bypass: str, sentence: str) -> None:
    """Found by attacking this fix's own claim-span rule
    (``uat/reports/evidence/models-live/w23-w18/w23-self-adversarial-attack.py``).
    A describing/aligning word ends a claim span because it normally pivots to
    the posting — but as the COMPLEMENT of the candidate's own track-record noun
    ("my experience MAPPING …") it is not a pivot, and treating it as one
    collapsed the span to a single word and let the phrase through."""
    flags = unsupported_claim_tokens(
        sentence, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body=_STRIPE_JD_BODY
    )
    assert "repository" in flags, f"{bypass} still bypasses the guard: {flags}"


def test_soft_skill_register_is_not_a_relabelling() -> None:
    """Regression for a REAL false positive this fix introduced and then closed.

    A JD's soft-skill register forms phrases too. With the body channel's first
    cut, the posting "We need a designer who ships fast and communicates clearly
    with engineering" made the ordinary letter clause "I ship fast and
    communicate clearly with engineering teams" flag
    ``['communicate', 'clearly', 'ship', 'fast']`` — killing four cases in
    tests/test_mv_cluster_a_cover_letter.py and tests/test_gap_p5_cover*.py.
    That is not a re-labelling, it is how every cover letter is written, and
    over-flagging it is exactly the ML-W11 zero-letters failure mode.

    An -ly adverb modifies a verb and can never be part of a checkable noun
    phrase, and generic action/manner vocabulary names no qualification — both
    are now excluded when the JD is indexed. Note the exclusion is scoped to
    THIS channel: putting these words in ``_GENERIC_PROFESSIONAL`` would have
    exempted them everywhere, including as capitalized entities on the tailor
    path, which would be a real weakening."""
    jd = (
        "We need a designer who ships fast and communicates clearly with "
        "engineering. Must have 3+ years of UX experience."
    )
    thin_evidence = (
        "Jordan Rivera. Senior Software Engineer. Led 6 engineers on a payments "
        "platform in Python and PostgreSQL. Initrode"
    )
    assert (
        unsupported_claim_tokens(
            "I ship fast and communicate clearly with engineering teams, which "
            "matches this role directly.",
            thin_evidence,
            "Product Designer",
            jd_body=jd,
        )
        == []
    )


def test_manner_exclusion_does_not_disarm_noun_phrases_around_it() -> None:
    """The -ly skip must not break the run it sits inside: "clearly documented
    audit evidence artifacts" still yields the {audit, evidence, artifacts}
    noun phrase, so the re-labelling it guards is still caught."""
    flags = unsupported_claim_tokens(
        "My experience covers a central repository of audit evidence artifacts.",
        _VIK_EVIDENCE,
        _STRIPE_TITLE,
        jd_body="Create and maintain a clearly documented central repository of "
        "audit evidence artifacts required for compliance with SOC 2.",
    )
    assert "repository" in flags, flags


def test_single_word_relabelling_is_a_documented_residual() -> None:
    """The channel's unit is a JD noun PHRASE, so importing exactly one JD word
    and pairing it with nothing else from that phrase stays at the pre-ML-W23
    behaviour. This is a deliberate, measured trade: widening to lone words was
    tried and rejected — on the live QA3-F-04 letter it also flags 'create',
    'maintain', 'global', 'obligations' and 'represent', the ordinary words the
    letter uses to QUOTE the requirement. Pinned so the trade-off is visible and
    any future narrowing of it is a conscious change, not an accident."""
    assert (
        unsupported_claim_tokens(
            "My experience architecting a repository for a reform program was "
            "decisive.",
            _VIK_EVIDENCE,
            _STRIPE_TITLE,
            jd_body=_STRIPE_JD_BODY,
        )
        == []
    )


def test_empty_jd_body_is_backward_compatible() -> None:
    """Default/empty ``jd_body`` reproduces the pre-W-23 behaviour exactly — the
    ML-W11 regression floor and all three wave35 attack harnesses call the guard
    without it."""
    text = (
        "My experience architecting a central test-evidence repository, cutting "
        "audit evidence effort by 92%, is directly relevant."
    )
    assert unsupported_claim_tokens(
        text, _VIK_EVIDENCE, _STRIPE_TITLE
    ) == unsupported_claim_tokens(text, _VIK_EVIDENCE, _STRIPE_TITLE, jd_body="")


# ===========================================================================
# W-18 — cross-sentence anaphoric tenure claims
# ===========================================================================

_GRC_TENURE_EVIDENCE = (
    "Senior Software Engineer, Acme Widgets Pty Ltd, 2019-2023. Built internal "
    "tooling in Python and React for the warehouse team. Reduced deployment "
    "time by 40% through CI pipeline improvements. Deputy"
)


@pytest.mark.parametrize(
    ("shape", "text"),
    [
        (
            "bare 'it' as the object of a tenure verb",
            "My background matches the GRC Program Manager role at Deputy. I "
            "held it for three years.",
        ),
        (
            "'that role' anaphoric noun phrase",
            "My delivery record matches the GRC Program Manager position at "
            "Deputy. I ran that role for three years.",
        ),
        (
            "'this position' anaphoric noun phrase",
            "My background aligns with the GRC Program Manager role at Deputy. "
            "I owned this position at my last employer.",
        ),
        (
            "present perfect with a bare anaphor",
            "My track record suits the GRC Program Manager role at Deputy. I "
            "have done it before.",
        ),
        (
            "anaphor two sentences of gloss later is still the same claim",
            "My background matches the GRC Program Manager posting. I led it "
            "end to end.",
        ),
    ],
)
def test_cross_sentence_anaphoric_tenure_claim_is_flagged(
    shape: str, text: str
) -> None:
    """Sentence 1 legitimately NAMES the advertised role (exempt). Sentence 2
    then claims to have HELD it, referring back by pronoun with no JD token of
    its own — so neither sentence alone carried both signals and the whole
    letter passed. The antecedent's title tokens are flagged."""
    flags = unsupported_claim_tokens(text, _GRC_TENURE_EVIDENCE, "GRC Program Manager")
    assert "grc" in flags or "manager" in flags, f"{shape} bypasses the guard: {flags}"


def test_writer_side_rails_forbid_relabelling_and_pronoun_tenure() -> None:
    """W-18's two remaining sub-families (a collective "our team ran it", a
    "which I did for three years" gloss of a preceding assertion) cannot be
    separated from honest craft lexically — the orchestrator adjudicated the
    class an accepted residual for exactly that reason. The deterministic rule
    above closes the pronoun-object shape it CAN prove; these writer-side rails
    reduce the incidence of the rest, and unlike a guard rule they can never
    reject an honest letter. Pinned so a prompt edit cannot silently drop
    them."""
    lower = SYSTEM_PROMPT.lower()
    assert "never re-label" in lower, SYSTEM_PROMPT
    assert "has held the advertised job" in lower, SYSTEM_PROMPT
    assert "not by pronoun or reference in a later sentence" in lower, SYSTEM_PROMPT


@pytest.mark.parametrize(
    "text",
    [
        # aspiration about the named role — the anaphor carries no experience
        "My background matches the GRC Program Manager role at Deputy. I am "
        "excited about it.",
        "My delivery record matches the GRC Program Manager role at Deputy. I "
        "would love it.",
        "My background aligns with the GRC Program Manager role at Deputy. I "
        "want it badly.",
        # an experience assertion whose object is NOT an anaphor
        "My background matches the GRC Program Manager role at Deputy. I built "
        "internal tooling in Python and React for the warehouse team.",
        # an ordinary closing after naming the role
        "My track record suits the GRC Program Manager role at Deputy. I am "
        "available for a call at your convenience.",
        # 'it' present but not the object of the experience verb
        "My background matches the GRC Program Manager role at Deputy. I have "
        "spent my career in delivery and it shows.",
        # no antecedent role-naming sentence at all
        "Delivery is what I do. I held it for three years.",
    ],
)
def test_anaphora_rule_does_not_fire_on_ordinary_craft(text: str) -> None:
    """The FP control that makes W-18 affordable: the rule needs BOTH a
    preceding sentence that names the advertised role AND a following
    first-person EXPERIENCE assertion whose DIRECT OBJECT is a bare anaphor.
    Aspiration, a real résumé-backed object, or an incidental 'it' elsewhere in
    the clause all leave the letter untouched."""
    assert (
        unsupported_claim_tokens(text, _GRC_TENURE_EVIDENCE, "GRC Program Manager")
        == []
    )
