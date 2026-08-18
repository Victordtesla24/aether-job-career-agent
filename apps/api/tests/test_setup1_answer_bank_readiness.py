"""SETUP-1 — the readiness figures behind the Settings panel and first-run prompt.

The Answer Bank already learns from every question the user answers, but nothing
told the user how far that had got them. These tests pin the numbers that claim
to answer *"can my agent apply without me yet?"*.

The honesty bar for a METRIC is the same as for an answer: it must be a count of
something that exists. Two failure modes are pinned deliberately because both
would look fine on a dashboard:

* a coverage figure that counts user-gated classes as outstanding set-up — a
  progress bar that can never reach the end, since a judgement/sensitive class
  is gated by design (:data:`ESSENTIAL_SEED_CONCEPTS`);
* a "ready" claim derived from row COUNT rather than from which concepts are
  covered — twelve answers to the same question is not a covered seed set.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.answer_bank import (
    ESSENTIAL_SEED_CONCEPTS,
    SEED_QUESTIONS,
    SENSITIVITY_FACTUAL,
    readiness_summary,
    semantic_key,
)


def _item(question: str, **overrides) -> dict[str, object]:
    """One bank row as the repository returns it."""
    row: dict[str, object] = {
        "questionText": question,
        "semanticKey": semantic_key(question),
        "answer": "whatever the user typed",
        "scope": "global",
        "scopeValue": "",
        "provenance": "onboarding",
        "provenanceDetail": None,
        "sensitivity": "factual",
        "staleDays": None,
        "expiresAt": None,
        "autoAnswerOptIn": False,
        "timesUsed": 0,
    }
    row.update(overrides)
    return row


class TestPureReadiness:
    def test_an_empty_bank_reports_zeros_not_an_encouraging_fraction(self):
        summary = readiness_summary([])
        assert summary["seedCovered"] == 0
        assert summary["essentialCovered"] == 0
        assert summary["setupComplete"] is False
        assert summary["liveAnswers"] == 0
        assert summary["timesAnswered"] == 0
        assert summary["learnedFromApplications"] == 0
        assert len(summary["seedRemaining"]) == summary["seedTotal"] == len(SEED_QUESTIONS)

    def test_coverage_counts_concepts_not_rows(self):
        """Three answers to the SAME class cover one concept, not three."""
        rows = [
            _item("Are you legally entitled to work in Australia?"),
            _item("Do you have the right to work in this country?"),
            _item("Are you authorised to work in the UK?"),
        ]
        summary = readiness_summary(rows)
        assert summary["liveAnswers"] == 3
        assert summary["seedCovered"] == 1

    def test_setup_is_complete_only_when_every_essential_concept_is_covered(self):
        essential = [q for q in SEED_QUESTIONS if q.concept in ESSENTIAL_SEED_CONCEPTS]
        # One short of the full essential set is NOT complete.
        partial = [_item(q.question) for q in essential[:-1]]
        assert readiness_summary(partial)["setupComplete"] is False

        full = [_item(q.question) for q in essential]
        summary = readiness_summary(full)
        assert summary["setupComplete"] is True
        assert summary["essentialCovered"] == summary["essentialTotal"]

    def test_a_gated_class_is_never_counted_as_outstanding_essential_setup(self):
        """Salary is a judgement call: gated by design, so it cannot block "ready".

        Without this, answering every answerable question still leaves the
        progress readout short, and the user is chased for something Aether
        would refuse to send automatically anyway.
        """
        assert "salary_expectation" not in ESSENTIAL_SEED_CONCEPTS
        for question in SEED_QUESTIONS:
            if question.sensitivity != SENSITIVITY_FACTUAL:
                assert question.concept not in ESSENTIAL_SEED_CONCEPTS

    def test_an_expired_answer_stops_counting_as_coverage_but_is_still_reported(self):
        stale = _item(
            "What is your notice period?",
            expiresAt=datetime.now(timezone.utc) - timedelta(days=1),
        )
        summary = readiness_summary([stale])
        assert summary["liveAnswers"] == 0
        assert summary["expiredAnswers"] == 1
        assert summary["seedCovered"] == 0
        assert any(q["concept"] == "notice_period" for q in summary["seedRemaining"])

    def test_a_judgment_answer_is_gated_until_opted_in(self):
        salary = _item("What are your salary expectations?", sensitivity="judgment")
        assert readiness_summary([salary])["autoAnswerable"] == 0
        assert readiness_summary([salary])["gatedAnswers"] == 1

        opted = _item(
            "What are your salary expectations?",
            sensitivity="judgment",
            autoAnswerOptIn=True,
        )
        assert readiness_summary([opted])["autoAnswerable"] == 1

    def test_a_sensitive_answer_never_counts_as_auto_answerable_even_if_opted_in(self):
        """The class gate is absolute — a stored opt-in cannot open it."""
        row = _item(
            "Do you consent to a police background check?",
            sensitivity="sensitive",
            autoAnswerOptIn=True,
        )
        assert readiness_summary([row])["autoAnswerable"] == 0

    def test_a_row_whose_stored_class_is_softer_than_its_wording_is_still_gated(self):
        """A mislabelled row must not be advertised as auto-answering.

        The matcher takes the STRONGER of the two classes, so a readiness figure
        that trusted the column alone would promise an auto-answer the agent
        then refuses — the page and the agent disagreeing about the same row.
        """
        mislabelled = _item(
            "Do you require visa sponsorship to work here?",
            sensitivity="factual",
        )
        assert readiness_summary([mislabelled])["autoAnswerable"] == 0

    def test_the_learning_loop_is_counted_from_answers_real_applications_produced(self):
        rows = [
            _item("Are you legally entitled to work in Australia?"),
            _item(
                "How many years of Kubernetes do you have?",
                provenance="user_answered",
                provenanceDetail="app_123",
                timesUsed=4,
            ),
            _item(
                "Why do you want to work here?",
                provenance="user_answered",
                provenanceDetail="app_456",
                sensitivity="judgment",
                timesUsed=2,
            ),
        ]
        summary = readiness_summary(rows)
        assert summary["learnedFromApplications"] == 2
        assert summary["timesAnswered"] == 6

    def test_a_hand_added_answer_is_not_counted_as_learned_from_an_application(self):
        """`user_answered` with no application behind it is a manual bank entry."""
        hand_added = _item(
            "Do you hold a current driver's licence?",
            provenance="user_answered",
            provenanceDetail=None,
        )
        assert readiness_summary([hand_added])["learnedFromApplications"] == 0


class TestReadinessEndpoint:
    def test_readiness_is_served_for_an_empty_bank(self, client, auth_headers):
        response = client.get("/answer-bank/readiness", headers=auth_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["setupComplete"] is False
        assert body["seedTotal"] == len(SEED_QUESTIONS)
        assert body["applicationsWaiting"] == 0
        assert body["autoAnswerThreshold"] == pytest.approx(0.86)

    def test_readiness_moves_when_the_user_answers_the_questionnaire(
        self, client, auth_headers
    ):
        before = client.get("/answer-bank/readiness", headers=auth_headers).json()
        client.post(
            "/answer-bank/questionnaire",
            headers=auth_headers,
            json={
                "answers": [
                    {
                        "question": (
                            "Are you legally entitled to work in the country you "
                            "are applying in?"
                        ),
                        "answer": "Yes — Australian citizen, full working rights.",
                    }
                ]
            },
        )
        after = client.get("/answer-bank/readiness", headers=auth_headers).json()
        assert after["seedCovered"] == before["seedCovered"] + 1
        assert after["autoAnswerable"] == before["autoAnswerable"] + 1
        assert len(after["seedRemaining"]) == len(before["seedRemaining"]) - 1

    def test_the_readiness_path_is_not_read_as_an_item_id(self, client, auth_headers):
        """`/readiness` is a literal segment, not a bank item called "readiness"."""
        body = client.get("/answer-bank/readiness", headers=auth_headers).json()
        assert "seedTotal" in body
        assert "questionText" not in body
