"""SUB-008 — answer-bank coverage of the two recurring screening classes the
bank did not have: "how did you hear about us" and acknowledgement checkboxes.

LEDGER REQUIREMENT (verbatim): *answer-bank coverage of recurring screening
questions (visa/work-auth/'how did you hear'/acknowledgement checkboxes) so
plans stop raising ``unknown_required_question``.*

``work_rights`` and ``visa_details`` already existed. The other two classes did
not exist ANYWHERE — no concept, no seed question, no matcher recognition — so
every ATS form carrying one of them became a manual step even for a user who
had answered the same question on the previous ten applications.

The honesty floor is unchanged and is pinned here as hard as the coverage is:

* the referral answer is the USER'S OWN words, taken from the seed
  questionnaire, never a value Aether derives from where it happened to source
  the job;
* the acknowledgement class covers PURE acknowledgements only — "the
  information I have given is true", "I have read the privacy policy". A
  checkbox that consents to a background check, a medical, a diversity
  disclosure or anything else in a sensitive/legal class must NOT fall into it
  and must stay user-gated;
* adding these two classes must not reclassify a single question that already
  had a class.

Nothing here touches a network, a browser, an employer or an LLM.
"""
from __future__ import annotations

import pytest

# The synthetic employer form. Greenhouse dialect, hand-built for this test —
# no real posting is ever contacted. It carries the two classes under test as
# REQUIRED fields, which is exactly the shape that raised
# ``unknown_required_question`` before this fix.
SYNTHETIC_FORM_HTML = """
<html><body><form>
  <label for="first_name">First Name *</label>
  <input id="first_name" name="first_name" type="text" aria-required="true">
  <label for="last_name">Last Name *</label>
  <input id="last_name" name="last_name" type="text" aria-required="true">
  <label for="email">Email *</label>
  <input id="email" name="email" type="email" aria-required="true">
  <label for="question_88001">How did you hear about us? *</label>
  <input id="question_88001" name="question_88001" type="text" aria-required="true">
  <label for="question_88002">I certify that the information provided in this
    application is true and complete.</label>
  <input id="question_88002" name="question_88002" type="checkbox" required>
</form></body></html>
"""

#: A second synthetic form: the same two classes PLUS a required
#: background-check consent tick. The consent must keep blocking.
SYNTHETIC_FORM_WITH_CONSENT_HTML = SYNTHETIC_FORM_HTML.replace(
    "</form>",
    """
  <label for="question_88003">I consent to a criminal record check being
    carried out.</label>
  <input id="question_88003" name="question_88003" type="checkbox" required>
</form>""",
)

PROFILE = {
    "name": "Vikram Sarkar",
    "firstName": "Vikram",
    "lastName": "Sarkar",
    "email": "vikram@example.com",
}

#: What the user typed into the seed questionnaire. Both are the user's own
#: words — the whole point of the class is that Aether repeats them, not that
#: it composes something plausible.
USER_REFERRAL_ANSWER = "LinkedIn Jobs — that is where I find most of the roles I apply for."
USER_ACKNOWLEDGEMENT_ANSWER = (
    "Yes — everything I put in an application is true and complete, and I "
    "accept a standard privacy policy and application terms."
)


def _seed_question_for(concept: str) -> str:
    from app.services.answer_bank import SEED_QUESTIONS

    matches = [q.question for q in SEED_QUESTIONS if q.concept == concept]
    assert matches, f"seed questionnaire has no question for {concept}"
    return matches[0]


def _banked(question: str, answer: str) -> dict[str, object]:
    """One bank row, shaped exactly as ``AnswerBankRepository.list_for_user``
    returns it — sensitivity DERIVED from the question, never asserted by the
    caller, so a test cannot hand itself a gate it should not have."""
    from app.services.answer_bank import classify_sensitivity

    return {
        "id": f"item-{abs(hash(question)) % 10_000}",
        "questionText": question,
        "answer": answer,
        "scope": "global",
        "scopeValue": "",
        "provenance": "onboarding",
        "sensitivity": classify_sensitivity(question),
        "autoAnswerOptIn": False,
        "expiresAt": None,
    }


def _seeded_bank() -> list[dict[str, object]]:
    return [
        _banked(_seed_question_for("referral_source"), USER_REFERRAL_ANSWER),
        _banked(_seed_question_for("acknowledgement"), USER_ACKNOWLEDGEMENT_ANSWER),
    ]


# ---------------------------------------------------------------------------
# 1. The concepts exist and recognise the real employer phrasings
# ---------------------------------------------------------------------------


class TestReferralSourceConcept:
    @pytest.mark.parametrize(
        "asked",
        [
            "How did you hear about us?",
            "How did you hear about this role?",
            "Where did you hear about this opportunity?",
            "How did you find out about this position?",
            "How did you learn about this job?",
            "Where did you see this role advertised?",
            "Referral source",
        ],
    )
    def test_every_common_phrasing_is_one_class(self, asked):
        from app.services.answer_bank import detect_concept

        concept = detect_concept(asked)
        assert concept is not None, f"{asked!r} still belongs to no class"
        assert concept.key == "referral_source"

    def test_the_class_is_factual_and_therefore_auto_answerable(self):
        from app.services.answer_bank import SENSITIVITY_FACTUAL, classify_sensitivity

        assert classify_sensitivity("How did you hear about us?") == SENSITIVITY_FACTUAL

    def test_all_phrasings_share_one_semantic_key(self):
        from app.services.answer_bank import semantic_key

        assert semantic_key("How did you hear about us?") == semantic_key(
            "Where did you hear about this opportunity?"
        )

    def test_it_never_swallows_a_motivation_question(self):
        """"Why do you want to work here" is a judgement call about an
        employer. Answering it with "LinkedIn" would be both wrong and
        ungated."""
        from app.services.answer_bank import detect_concept

        concept = detect_concept(
            "Why do you want to work here, and how did you hear about us?"
        )
        assert concept is not None and concept.key == "motivation"


class TestAcknowledgementConcept:
    @pytest.mark.parametrize(
        "asked",
        [
            "I certify that the information provided in this application is true and complete.",
            "I confirm the information above is accurate.",
            "I have read and agree to the privacy policy.",
            "I have read and accept the terms and conditions.",
            "Please acknowledge that you have read the above.",
            "Do you agree to the terms and conditions?",
        ],
    )
    def test_pure_acknowledgements_are_one_class(self, asked):
        from app.services.answer_bank import detect_concept

        concept = detect_concept(asked)
        assert concept is not None, f"{asked!r} still belongs to no class"
        assert concept.key == "acknowledgement"

    def test_the_class_is_factual_and_therefore_auto_answerable(self):
        from app.services.answer_bank import SENSITIVITY_FACTUAL, classify_sensitivity

        assert (
            classify_sensitivity("I certify that the information provided is true.")
            == SENSITIVITY_FACTUAL
        )

    @pytest.mark.parametrize(
        "asked",
        [
            "I consent to a criminal record check being carried out.",
            "I acknowledge that a police check will be required.",
            "I consent to a pre-employment medical and drug test.",
            "I acknowledge that I will need visa sponsorship.",
            "I acknowledge the collection of my gender and ethnicity for EEO reporting.",
            "I certify that I hold a current security clearance.",
        ],
    )
    def test_a_consent_or_legal_tick_is_never_a_pure_acknowledgement(self, asked):
        """The tick is worded like an acknowledgement and is NOT one. Either it
        keeps its own sensitive class or it belongs to no class at all — what it
        must never be is a factual acknowledgement Aether ticks by itself."""
        from app.services.answer_bank import (
            SENSITIVITY_FACTUAL,
            classify_sensitivity,
            detect_concept,
        )

        concept = detect_concept(asked)
        assert concept is None or concept.key != "acknowledgement"
        if concept is not None:
            assert classify_sensitivity(asked) != SENSITIVITY_FACTUAL

    def test_a_sanctions_eligibility_disclosure_is_never_a_pure_acknowledgement(self):
        """SUB-008-R2 regression. Real Databricks/Greenhouse wording: the
        applicant is asked to disclose sanctions/export-control status, and
        the surrounding boilerplate happens to co-occur "confirm" with
        "information" — a bare pair that used to fire the acknowledgement
        class on ANY co-occurrence, auto-ticking a box that in fact asks the
        candidate to self-disclose residency/citizenship in sanctioned
        countries. That must never be auto-answered."""
        from app.services.answer_bank import (
            SENSITIVITY_FACTUAL,
            classify_sensitivity,
            detect_concept,
        )

        asked = (
            "Please confirm whether any of the below applies to you.  Select "
            "all that apply.\n\nNote: This information will only be used to "
            "ensure compliance with U.S. sanctions and export controls."
        )
        concept = detect_concept(asked)
        assert concept is None or concept.key != "acknowledgement"
        if concept is not None:
            assert classify_sensitivity(asked) != SENSITIVITY_FACTUAL

    def test_a_banked_acknowledgement_never_answers_a_consent_tick(self):
        from app.services.answer_bank import find_match

        assert (
            find_match(
                "I consent to a criminal record check being carried out.",
                _seeded_bank(),
            )
            is None
        )


class TestNoExistingClassIsReclassified:
    """The two new classes are additive. A question that already had a class
    keeps it — otherwise this fix would be a silent behaviour change to the
    gate that decides what Aether may answer by itself."""

    @pytest.mark.parametrize(
        "asked,expected",
        [
            ("Are you legally entitled to work in Australia?", "work_rights"),
            ("Do you require visa sponsorship now or in the future?", "visa_details"),
            ("Have you ever been convicted of a criminal offence?", "background_check"),
            ("What are your salary expectations?", "salary_expectation"),
            ("What is your current salary?", "salary_current"),
            ("Why do you want to work at Northwind?", "motivation"),
            ("What is your notice period?", "notice_period"),
            ("What is the earliest date you could start?", "start_date"),
            ("Are you willing to relocate for this role?", "relocation"),
            (
                "What is your preferred working arrangement (remote, hybrid or onsite)?",
                "remote_preference",
            ),
            ("Are you able to provide professional references?", "references"),
            ("How many years of professional experience do you have?", "years_experience"),
            ("Do you hold a current driver's licence?", "drivers_licence"),
            ("Are you willing to travel for this role?", "notice_of_travel"),
            ("Do you identify as Aboriginal or Torres Strait Islander?", "diversity"),
        ],
    )
    def test_existing_classes_are_unchanged(self, asked, expected):
        from app.services.answer_bank import detect_concept

        concept = detect_concept(asked)
        assert concept is not None and concept.key == expected


# ---------------------------------------------------------------------------
# 2. Seed questionnaire — the ONLY source of an answer for either class
# ---------------------------------------------------------------------------


class TestSeedQuestionnaireCoversBothClasses:
    @pytest.mark.parametrize("concept", ["referral_source", "acknowledgement"])
    def test_the_questionnaire_asks_the_user_for_this_class(self, concept):
        from app.services.answer_bank import SEED_QUESTIONS

        assert concept in {q.concept for q in SEED_QUESTIONS}

    @pytest.mark.parametrize("concept", ["referral_source", "acknowledgement"])
    def test_the_seed_question_is_itself_recognised_as_its_own_class(self, concept):
        """A seed question the matcher does not put in its own class banks a row
        that the employer's phrasing can never reach."""
        from app.services.answer_bank import detect_concept

        detected = detect_concept(_seed_question_for(concept))
        assert detected is not None and detected.key == concept

    @pytest.mark.parametrize("concept", ["referral_source", "acknowledgement"])
    def test_the_seed_question_ships_no_answer_of_its_own(self, concept):
        from app.services.answer_bank import SEED_QUESTIONS

        for question in SEED_QUESTIONS:
            if question.concept == concept:
                assert not getattr(question, "answer", None)
                assert not getattr(question, "default", None)
                assert question.placeholder.lower().startswith("e.g.")

    def test_the_payload_declares_both_as_auto_answerable(self):
        from app.services.answer_bank import seed_question_payload

        payload = {row["concept"]: row for row in seed_question_payload()}
        for concept in ("referral_source", "acknowledgement"):
            assert payload[concept]["autoAnswerable"] is True
            assert payload[concept]["sensitivity"] == "factual"

    def test_the_acknowledgement_helper_states_the_boundary_it_will_not_cross(self):
        """Honest copy is half of this fix: the user is told, on the very
        question they are answering, that Aether ticks pure acknowledgements
        only and still stops for anything that consents to a check."""
        from app.services.answer_bank import SEED_QUESTIONS

        helper = next(
            q.helper for q in SEED_QUESTIONS if q.concept == "acknowledgement"
        ).lower()
        assert "consent" in helper
        assert "background check" in helper or "criminal" in helper


# ---------------------------------------------------------------------------
# 3. The matcher resolves a real ATS field of either class from the bank
# ---------------------------------------------------------------------------


class TestMatcherResolvesBothClassesFromTheBank:
    @pytest.mark.parametrize(
        "asked",
        [
            "How did you hear about us?",
            "Where did you see this role advertised?",
        ],
    )
    def test_a_referral_field_resolves_to_the_users_own_words(self, asked):
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, find_match

        match = find_match(asked, _seeded_bank())
        assert match is not None, f"{asked!r} is still unanswerable"
        assert match.answer == USER_REFERRAL_ANSWER
        assert match.confidence >= AUTO_ANSWER_CONFIDENCE
        assert match.question_as_seen == asked

    @pytest.mark.parametrize(
        "asked",
        [
            "I certify that the information provided in this application is true and complete.",
            "I have read and agree to the privacy policy.",
        ],
    )
    def test_an_acknowledgement_field_resolves_to_the_users_own_words(self, asked):
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, find_match

        match = find_match(asked, _seeded_bank())
        assert match is not None, f"{asked!r} is still unanswerable"
        assert match.answer == USER_ACKNOWLEDGEMENT_ANSWER
        assert match.confidence >= AUTO_ANSWER_CONFIDENCE


# ---------------------------------------------------------------------------
# 4. The plan: no manual step for either seeded class (the ledger requirement)
# ---------------------------------------------------------------------------


class TestSyntheticFormPlan:
    def test_without_the_bank_both_classes_are_honest_manual_steps(self):
        """RED-side control: with nothing banked the plan MUST still refuse —
        this fix widens what the bank covers, it never invents an answer."""
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(
                SYNTHETIC_FORM_HTML, channel="greenhouse", profile=PROFILE
            )
        assert exc_info.value.reason == "unknown_required_question"
        question = exc_info.value.question or ""
        assert "How did you hear" in question
        assert "certify" in question

    def test_the_seeded_bank_removes_the_manual_step_entirely(self):
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(
            SYNTHETIC_FORM_HTML,
            channel="greenhouse",
            profile=PROFILE,
            answer_bank=build_resolver(_seeded_bank()),
        )
        assert plan["unanswerable_required"] == []
        values = {f["name"]: f["value"] for f in plan["fields"]}
        assert values["question_88001"] == USER_REFERRAL_ANSWER
        assert values["question_88002"] == USER_ACKNOWLEDGEMENT_ANSWER

    def test_every_auto_answer_carries_its_audit_row(self):
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import build_form_fill_plan

        plan = build_form_fill_plan(
            SYNTHETIC_FORM_HTML,
            channel="greenhouse",
            profile=PROFILE,
            answer_bank=build_resolver(_seeded_bank()),
        )
        audit = {row["fieldName"]: row for row in plan["answerBankAudit"]}
        assert set(audit) == {"question_88001", "question_88002"}
        for row in audit.values():
            assert row["matchConfidence"] >= 0.86
            assert row["bankedQuestion"]
            assert row["questionAsSeen"]

    def test_a_consent_tick_on_the_same_form_still_blocks(self):
        """The bank now covers the acknowledgement next to it — and the consent
        must be untouched by that, or this fix would have quietly opened the
        sensitive gate."""
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc_info:
            build_form_fill_plan(
                SYNTHETIC_FORM_WITH_CONSENT_HTML,
                channel="greenhouse",
                profile=PROFILE,
                answer_bank=build_resolver(_seeded_bank()),
            )
        err = exc_info.value
        assert err.reason == "unknown_required_question"
        assert "criminal record check" in (err.question or "")
        assert "certify" not in (err.question or "")
        blocked = {field["name"] for field in (err.fields or [])}
        assert blocked == {"question_88003"}


# ---------------------------------------------------------------------------
# 5. The tick itself — a resolved acknowledgement has to actually land
# ---------------------------------------------------------------------------


class TestAcknowledgementCheckboxIsActuallyTicked:
    ONLY_OPTION = "I certify that the information provided is true and complete"

    def test_an_affirmative_answer_ticks_the_lone_acknowledgement_box(self):
        """A single-checkbox acknowledgement offers nothing to choose BETWEEN.
        A bare "Yes" shares no wording with the employer's statement, so
        without this the resolved answer would leave the required box unticked
        and the submission would abort as ``form_fill_failed``."""
        from app.services.apply_executor import _match_choice_option

        assert _match_choice_option("Yes", [self.ONLY_OPTION]) == self.ONLY_OPTION
        assert (
            _match_choice_option("I agree", [self.ONLY_OPTION]) == self.ONLY_OPTION
        )

    def test_a_declined_acknowledgement_is_never_ticked(self):
        """The refusal below SHARES most of its wording with the employer's
        statement, so the token-overlap rule would tick the box for a user who
        said no. On a lone option there is no second option to lose the tie
        to — the polarity of the answer is the only thing that can stop it."""
        from app.services.apply_executor import _match_choice_option

        assert _match_choice_option("No", [self.ONLY_OPTION]) is None
        assert (
            _match_choice_option(
                "No — I do not want a blanket declaration that the information "
                "provided is true; ask me on each application.",
                [self.ONLY_OPTION],
            )
            is None
        )

    def test_a_real_two_option_choice_is_unaffected(self):
        from app.services.apply_executor import _match_choice_option

        assert _match_choice_option("Yes", ["Yes, I am", "No"]) == "Yes, I am"
        assert _match_choice_option("No", ["Yes, I am", "No"]) == "No"
