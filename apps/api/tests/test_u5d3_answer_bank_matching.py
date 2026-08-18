"""U5d-3 Pillar 1 — the Answer Bank matcher (RED first).

ADR-SUB-AUTON-1 makes ONE promise about this module and one refusal:

* the promise — a screening question the user has already answered ONCE is
  answered again by the agent, in the user's OWN words, without waiting for
  them; and every such auto-answer is auditable (which banked item, what
  confidence, the question exactly as the employer asked it);
* the refusal — the honesty floor. The bank NEVER invents an answer, never
  stretches one question's answer over a different question, and never
  auto-answers a sensitive/legal class (background-check consent, diversity
  disclosures, visa specifics) no matter what the bank contains.

Every test here is about one of those two. Nothing in this file touches a
network, a browser, an employer or an LLM — the matcher is pure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Normalisation + semantic keys
# ---------------------------------------------------------------------------


class TestNormalisation:
    def test_normalise_strips_punctuation_case_and_filler(self):
        from app.services.answer_bank import normalize_question

        assert normalize_question("  Are you legally authorised to work in Australia?  ") == (
            normalize_question("are you legally authorised to work in australia")
        )
        assert "?" not in normalize_question("Notice period?")

    def test_negation_survives_normalisation(self):
        """"Do you require sponsorship" and "do you NOT require sponsorship"
        are opposite questions; a normaliser that drops "not" would let one
        answer the other."""
        from app.services.answer_bank import question_tokens

        assert "not" in question_tokens("Do you not require visa sponsorship?")
        assert "not" not in question_tokens("Do you require visa sponsorship?")

    def test_same_concept_questions_share_a_semantic_key(self):
        from app.services.answer_bank import semantic_key

        a = semantic_key("Are you legally authorised to work in Australia?")
        b = semantic_key("Do you have the right to work in Australia?")
        assert a == b, "work-rights phrasings must collapse to one key"

    def test_different_concepts_never_share_a_semantic_key(self):
        from app.services.answer_bank import semantic_key

        assert semantic_key("What is your current salary?") != semantic_key(
            "What are your salary expectations?"
        )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


class TestMatchConfidence:
    def test_identical_questions_score_one(self):
        from app.services.answer_bank import match_confidence

        score, method = match_confidence("Notice period?", "notice period")
        assert score == pytest.approx(1.0)
        assert method == "exact"

    def test_paraphrase_of_the_same_concept_clears_the_auto_threshold(self):
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, match_confidence

        score, method = match_confidence(
            "Are you legally authorised to work in Australia?",
            "Do you have the right to work in Australia?",
        )
        assert score >= AUTO_ANSWER_CONFIDENCE
        assert method == "concept"

    def test_lexically_similar_but_conceptually_opposite_questions_score_zero(self):
        """The single most dangerous false positive in this whole feature.

        "What is your current salary?" and "What are your salary expectations?"
        share almost every content word. Answering one with the other publishes
        a number about the candidate they never said.
        """
        from app.services.answer_bank import match_confidence

        score, _method = match_confidence(
            "What is your current salary?", "What are your salary expectations?"
        )
        assert score == 0.0

    def test_unrelated_questions_do_not_clear_the_threshold(self):
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, match_confidence

        score, _method = match_confidence(
            "How many years of Python experience do you have?",
            "What is your notice period?",
        )
        assert score < AUTO_ANSWER_CONFIDENCE

    def test_a_bare_lexical_near_miss_stays_below_the_threshold(self):
        """One side carries a recognised concept and the other does not: that
        asymmetry is evidence they are NOT the same question, so the pair is
        capped below the auto threshold and becomes an honest manual step."""
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, match_confidence

        score, _method = match_confidence(
            "What is your notice period?",
            "What is your favourite period of history?",
        )
        assert score < AUTO_ANSWER_CONFIDENCE

    @pytest.mark.parametrize(
        ("asked", "banked"),
        [
            # A GENERAL years-of-experience answer is not an answer about one
            # named skill. "11 years, the last 5 in platform engineering" sent
            # to "how many years of Kubernetes" publishes a duration the
            # candidate never claimed — the exact thing honesty floor 1
            # forbids, and the reason a shared concept alone cannot authorise
            # an auto-answer.
            (
                "How many years of hands-on Kubernetes experience do you have?",
                "How many years of professional experience do you have in your field?",
            ),
            # One named skill never answers for another.
            (
                "How many years of Python experience do you have?",
                "How many years of Kubernetes experience do you have?",
            ),
            # A motivation answer written about one employer must never be
            # sent to a different one — it would name the wrong company.
            (
                "Why do you want to work at Northwind Robotics?",
                "Why do you want to work at Harbourline Health?",
            ),
        ],
    )
    def test_a_subject_specific_question_is_never_answered_from_another_subject(
        self, asked, banked
    ):
        """Same class, DIFFERENT subject ⇒ no auto-answer, ever.

        Sharing a concept means the two questions are about the same KIND of
        thing. It does not mean they are about the same thing: years-of-X and
        why-company-Y both carry a subject that changes what the true answer
        is. Scoring these on wording would clear the threshold (they differ by
        one word) and send an answer the user never gave.
        """
        from app.services.answer_bank import find_match, match_confidence

        score, method = match_confidence(asked, banked)
        assert score == 0.0, f"{asked!r} vs {banked!r} scored {score} ({method})"
        assert (
            find_match(
                asked,
                [
                    {
                        "id": "item-subject",
                        "questionText": banked,
                        "answer": "11 years, the last 5 in platform engineering.",
                        "scope": "global",
                        "sensitivity": "factual",
                        "autoAnswerOptIn": True,
                        "expiresAt": None,
                    }
                ],
            )
            is None
        )

    @pytest.mark.parametrize(
        ("asked", "banked"),
        [
            # The SAME subject, worded differently, still matches — the guard
            # discriminates on subject, it does not disable the concept path.
            (
                "How many years of Kubernetes experience do you have?",
                "Years of experience with Kubernetes?",
            ),
            # A generic years question against a generic banked one: neither
            # names a subject, so there is nothing to disagree about.
            (
                "How many years of experience do you have?",
                "How many years of professional experience do you have in your field?",
            ),
        ],
    )
    def test_the_same_subject_still_matches(self, asked, banked):
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, match_confidence

        score, _method = match_confidence(asked, banked)
        assert score >= AUTO_ANSWER_CONFIDENCE

    @pytest.mark.parametrize(
        ("asked", "banked"),
        [
            (
                "Are you legally authorised to work in Australia?",
                "Are you NOT legally authorised to work in Australia?",
            ),
            ("Are you willing to relocate?", "Are you not willing to relocate?"),
            ("Do you require visa sponsorship?", "Do you not require visa sponsorship?"),
            # Contractions are the same question in the user's eyes and the
            # opposite question in fact, so they must survive normalisation.
            ("Do you hold a current driver's licence?", "Don't you hold a driver's licence?"),
        ],
    )
    def test_opposite_polarity_scores_zero_even_within_one_concept(self, asked, banked):
        """The concept path must not talk over a negation.

        Two questions can be the SAME class and still be opposites — "are you
        authorised to work here" vs "are you NOT authorised to work here" share
        every content word and their concept. Answering one with the other
        publishes the reverse of what the candidate said, which is the exact
        fabrication this bank exists to prevent.
        """
        from app.services.answer_bank import match_confidence

        score, method = match_confidence(asked, banked)
        assert score == 0.0
        assert method == "polarity_mismatch"

    def test_matching_polarity_is_unaffected(self):
        """The guard fires on a DIFFERENCE in polarity, never on its presence:
        two negated phrasings of one question still match."""
        from app.services.answer_bank import AUTO_ANSWER_CONFIDENCE, match_confidence

        score, _method = match_confidence(
            "Are you not willing to relocate?", "Are you not willing to relocate for work?"
        )
        assert score >= AUTO_ANSWER_CONFIDENCE


# ---------------------------------------------------------------------------
# Sensitivity classification
# ---------------------------------------------------------------------------


class TestSensitivity:
    @pytest.mark.parametrize(
        "question",
        [
            "Do you consent to a criminal background check?",
            "Are you willing to undergo a police check?",
            "How would you describe your gender identity?",
            "Do you identify as Aboriginal or Torres Strait Islander?",
            "Do you have a disability?",
            "Are you a protected veteran?",
            "Do you now or in the future require visa sponsorship?",
            "What is your visa subclass and expiry date?",
            "Have you ever been convicted of a criminal offence?",
        ],
    )
    def test_sensitive_and_legal_questions_are_classified_sensitive(self, question):
        from app.services.answer_bank import SENSITIVITY_SENSITIVE, classify_sensitivity

        assert classify_sensitivity(question) == SENSITIVITY_SENSITIVE

    @pytest.mark.parametrize(
        "question",
        [
            "Are you legally authorised to work in Australia?",
            "Do you have full working rights in Australia?",
            "What is your notice period?",
            "How many years of experience do you have with Python?",
            "Are you willing to relocate to Sydney?",
        ],
    )
    def test_stable_factual_questions_are_classified_factual(self, question):
        from app.services.answer_bank import SENSITIVITY_FACTUAL, classify_sensitivity

        assert classify_sensitivity(question) == SENSITIVITY_FACTUAL

    @pytest.mark.parametrize(
        "question",
        [
            "What are your salary expectations?",
            "Why do you want to work for us?",
        ],
    )
    def test_judgement_questions_are_classified_judgement(self, question):
        from app.services.answer_bank import SENSITIVITY_JUDGMENT, classify_sensitivity

        assert classify_sensitivity(question) == SENSITIVITY_JUDGMENT


# ---------------------------------------------------------------------------
# find_match — the honesty gate
# ---------------------------------------------------------------------------


def _item(**over):
    base = {
        "id": "itm_1",
        "questionText": "Are you legally authorised to work in Australia?",
        "semanticKey": "",
        "answer": "Yes — I am an Australian citizen.",
        "scope": "global",
        "scopeValue": "",
        "provenance": "user_answered",
        "sensitivity": "factual",
        "autoAnswerOptIn": False,
        "expiresAt": None,
    }
    base.update(over)
    from app.services.answer_bank import semantic_key

    base["semanticKey"] = base["semanticKey"] or semantic_key(base["questionText"])
    return base


class TestFindMatch:
    def test_high_confidence_factual_match_is_returned_with_full_audit(self):
        from app.services.answer_bank import find_match

        match = find_match("Do you have the right to work in Australia?", [_item()])
        assert match is not None
        assert match.answer == "Yes — I am an Australian citizen."
        assert match.item_id == "itm_1"
        assert match.confidence >= 0.86
        assert match.question_as_seen == "Do you have the right to work in Australia?"
        assert match.method == "concept"

    @pytest.mark.parametrize(
        "asked",
        [
            "Do you have full working rights in Australia?",
            "Do you have Australian working rights?",
            "Do you have unrestricted working rights?",
        ],
    )
    def test_australian_working_rights_phrasing_matches_the_seeded_work_rights_answer(
        self, asked
    ):
        """AU ATS forms say 'working rights', not 'right to work'.

        The seed questionnaire banks the legally-entitled phrasing. If the
        matcher requires a standalone 'work' token, every Ashby/Lever form
        that asks 'full working rights' stops even though the user already
        answered the same fact. That is a missed auto-answer, not a gate.
        """
        from app.services.answer_bank import find_match

        bank = [_item()]
        match = find_match(asked, bank)
        assert match is not None, asked
        assert match.answer == bank[0]["answer"]

    def test_a_visa_sponsorship_question_is_never_answered_from_working_rights(self):
        """The working-rights widening must not open the visa gate.

        'Do you require visa sponsorship?' is sensitive. A banked 'yes I have
        working rights' must never fill it — even after 'working rights' is
        recognised as the same class as 'right to work'.
        """
        from app.services.answer_bank import find_match

        assert find_match("Do you require visa sponsorship to work here?", [_item()]) is None
        assert find_match("Do you now or in the future require visa sponsorship?", [_item()]) is None

    def test_right_skills_to_work_is_not_a_work_rights_answer(self):
        """'Right' + 'work' in a skills/fit question is not authorisation to work.

        Auto-sending 'I am an Australian citizen' to 'do you have the right
        skills to work in a fast-paced team' publishes a fact the candidate
        never said about that question.
        """
        from app.services.answer_bank import find_match

        assert (
            find_match("Do you have the right skills to work in a fast-paced team?", [_item()])
            is None
        )
        assert (
            find_match("Do you think you would be the right fit to work in our team?", [_item()])
            is None
        )

    def test_the_banked_answer_is_returned_verbatim_never_reworded(self):
        from app.services.answer_bank import find_match

        answer = "4 weeks' notice — my last day would be the 12th."
        match = find_match(
            "What is your notice period?",
            [_item(questionText="Notice period", answer=answer, sensitivity="factual")],
        )
        assert match is not None
        assert match.answer == answer

    def test_low_confidence_never_auto_answers(self):
        from app.services.answer_bank import find_match

        assert find_match("How many years of Kubernetes do you have?", [_item()]) is None

    def test_sensitive_questions_are_never_auto_answered_even_when_banked(self):
        """Test-pinned honesty floor. The user HAS banked this answer, the
        match is exact, and it is still refused — a background-check consent is
        the user's to give on every single application."""
        from app.services.answer_bank import find_match

        banked = _item(
            id="itm_bg",
            questionText="Do you consent to a criminal background check?",
            answer="Yes",
            sensitivity="sensitive",
        )
        assert find_match("Do you consent to a criminal background check?", [banked]) is None

    def test_a_sensitive_question_cannot_be_answered_from_a_factual_item(self):
        """The gate reads the sensitivity of the question AS ASKED as well as
        the banked item's, so mislabelling an item cannot open the gate."""
        from app.services.answer_bank import find_match

        mislabelled = _item(
            id="itm_x",
            questionText="Do you consent to a criminal background check?",
            answer="Yes",
            sensitivity="factual",
        )
        assert (
            find_match("Do you consent to a criminal background check?", [mislabelled])
            is None
        )

    def test_sensitive_items_cannot_be_opted_in_to_auto_answering(self):
        from app.services.answer_bank import find_match

        banked = _item(
            id="itm_bg",
            questionText="Do you have a disability?",
            answer="Prefer not to say",
            sensitivity="sensitive",
            autoAnswerOptIn=True,
        )
        assert find_match("Do you have a disability?", [banked]) is None

    def test_judgement_questions_are_user_gated_until_explicitly_opted_in(self):
        from app.services.answer_bank import find_match

        gated = _item(
            id="itm_sal",
            questionText="What are your salary expectations?",
            answer="AUD 180,000 base",
            sensitivity="judgment",
        )
        assert find_match("What are your salary expectations?", [gated]) is None

        opted_in = dict(gated, autoAnswerOptIn=True)
        match = find_match("What are your salary expectations?", [opted_in])
        assert match is not None
        assert match.answer == "AUD 180,000 base"

    def test_an_expired_item_is_never_auto_answered(self):
        from app.services.answer_bank import find_match

        stale = _item(
            id="itm_stale",
            questionText="What is your notice period?",
            answer="2 weeks",
            expiresAt=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert find_match("What is your notice period?", [stale]) is None

    def test_a_company_scoped_item_beats_a_global_one_for_that_company(self):
        from app.services.answer_bank import find_match

        global_item = _item(
            id="g", questionText="What is your notice period?", answer="4 weeks"
        )
        company_item = _item(
            id="c",
            questionText="What is your notice period?",
            answer="2 weeks for this role",
            scope="company",
            scopeValue="acme pty ltd",
        )
        match = find_match(
            "What is your notice period?",
            [global_item, company_item],
            company="Acme Pty Ltd",
        )
        assert match is not None and match.item_id == "c"

    def test_a_company_scoped_item_is_not_used_for_another_company(self):
        from app.services.answer_bank import find_match

        company_item = _item(
            id="c",
            questionText="What is your notice period?",
            answer="2 weeks for this role",
            scope="company",
            scopeValue="acme pty ltd",
        )
        assert (
            find_match("What is your notice period?", [company_item], company="Globex")
            is None
        )

    def test_an_empty_bank_answers_nothing(self):
        from app.services.answer_bank import find_match

        assert find_match("Are you legally authorised to work in Australia?", []) is None


# ---------------------------------------------------------------------------
# Staleness policy
# ---------------------------------------------------------------------------


class TestStalenessPolicy:
    def test_salary_and_notice_answers_expire_and_work_rights_do_not(self):
        from app.services.answer_bank import stale_days_for

        assert stale_days_for("What are your salary expectations?") is not None
        assert stale_days_for("What is your notice period?") is not None
        assert stale_days_for("Are you legally authorised to work in Australia?") is None


# ---------------------------------------------------------------------------
# Seed questionnaire
# ---------------------------------------------------------------------------


class TestSeedQuestionnaire:
    def test_the_seed_set_covers_every_question_class_the_adr_names(self):
        from app.services.answer_bank import SEED_QUESTIONS

        concepts = {q.concept for q in SEED_QUESTIONS}
        for required in (
            "work_rights",
            "notice_period",
            "salary_expectation",
            "relocation",
            "remote_preference",
            "start_date",
            "references",
        ):
            assert required in concepts, f"seed questionnaire is missing {required}"

    def test_every_seed_question_declares_its_own_sensitivity_honestly(self):
        from app.services.answer_bank import SEED_QUESTIONS, classify_sensitivity

        for question in SEED_QUESTIONS:
            assert classify_sensitivity(question.question) == question.sensitivity

    def test_no_seed_question_ships_a_prefilled_answer(self):
        """A questionnaire that suggests answers is a fabrication engine."""
        from app.services.answer_bank import SEED_QUESTIONS

        for question in SEED_QUESTIONS:
            assert not getattr(question, "answer", None)
