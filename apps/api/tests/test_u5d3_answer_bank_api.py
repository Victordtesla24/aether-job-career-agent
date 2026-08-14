"""U5d-3 — the Answer Bank REST surface + the seed questionnaire (RED first).

ADR-SUB-AUTON-1 Pillar 1: *"USER-VISIBLE: Answer Bank is a first-class UI
surface (view/edit/expire/delete every answer; see where each was used)."*
This file pins the API that surface reads and writes, plus the onboarding
questionnaire that seeds the bank before the first application is ever sent.
"""
from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


class TestQuestionnaire:
    def test_the_seed_questionnaire_is_served_with_no_answers_in_it(
        self, client, auth_headers
    ):
        body = client.get("/answer-bank/questionnaire", headers=auth_headers).json()
        assert len(body["questions"]) >= 8
        for question in body["questions"]:
            assert "answer" not in question
            assert question["question"]
            assert question["sensitivity"] in {"factual", "judgment", "sensitive"}

    def test_each_question_says_honestly_whether_it_will_ever_auto_answer(
        self, client, auth_headers
    ):
        body = client.get("/answer-bank/questionnaire", headers=auth_headers).json()
        by_concept = {q["concept"]: q for q in body["questions"]}
        assert by_concept["work_rights"]["autoAnswerable"] is True
        assert by_concept["salary_expectation"]["autoAnswerable"] is False

    def test_answered_questions_are_banked_with_onboarding_provenance(
        self, client, auth_headers, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        response = client.post(
            "/answer-bank/questionnaire",
            headers=auth_headers,
            json={
                "answers": [
                    {
                        "question": "Are you legally entitled to work in the country you are applying in?",
                        "answer": "Yes — Australian citizen.",
                    },
                    {"question": "What is your notice period?", "answer": "4 weeks"},
                ]
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["banked"] == 2

        items = {i["semanticKey"]: i for i in AnswerBankRepository().list_for_user(user_id)}
        assert items["concept:work_rights"]["provenance"] == "onboarding"
        assert items["concept:work_rights"]["answer"] == "Yes — Australian citizen."
        assert items["concept:notice_period"]["answer"] == "4 weeks"

    def test_an_answered_question_is_reported_as_answered_whatever_its_key_shape(
        self, client, auth_headers
    ):
        """The progress readout must not under-report the user's own work.

        A SUBJECT-SENSITIVE class keys its rows as
        ``concept:years_experience:<subject>`` so two skills cannot collide on
        one row. The questionnaire reports progress by CONCEPT, so it has to
        read the concept out of that key rather than assume the key is only
        ever ``concept:<name>`` — otherwise a user who answered the years
        question is told they still have not, and is asked for it again.
        """
        client.post(
            "/answer-bank/questionnaire",
            headers=auth_headers,
            json={
                "answers": [
                    {
                        "question": "How many years of professional experience "
                        "do you have in your field?",
                        "answer": "11 years, the last 5 in platform engineering.",
                    },
                    {"question": "What is your notice period?", "answer": "4 weeks"},
                ]
            },
        )
        body = client.get("/answer-bank/questionnaire", headers=auth_headers).json()
        assert "years_experience" in body["answeredConcepts"]
        assert "notice_period" in body["answeredConcepts"]

    def test_skipped_questions_bank_nothing_and_are_not_an_error(
        self, client, auth_headers, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        response = client.post(
            "/answer-bank/questionnaire",
            headers=auth_headers,
            json={
                "answers": [
                    {"question": "What is your notice period?", "answer": "   "},
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["banked"] == 0
        assert AnswerBankRepository().list_for_user(user_id) == []

    def test_the_questionnaire_can_be_answered_again_without_duplicating(
        self, client, auth_headers, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        payload = {
            "answers": [{"question": "What is your notice period?", "answer": "4 weeks"}]
        }
        client.post("/answer-bank/questionnaire", headers=auth_headers, json=payload)
        payload["answers"][0]["answer"] = "6 weeks"
        client.post("/answer-bank/questionnaire", headers=auth_headers, json=payload)
        items = AnswerBankRepository().list_for_user(user_id)
        assert len(items) == 1 and items[0]["answer"] == "6 weeks"


class TestBankCrud:
    def _bank(self, client, auth_headers, question: str, answer: str) -> dict:
        return client.post(
            "/answer-bank",
            headers=auth_headers,
            json={"question": question, "answer": answer},
        ).json()

    def test_an_empty_bank_lists_as_empty(self, client, auth_headers):
        body = client.get("/answer-bank", headers=auth_headers).json()
        assert body["items"] == []
        assert body["autoAnswerThreshold"] == pytest.approx(0.86)

    def test_a_banked_item_lists_with_its_provenance_and_class(
        self, client, auth_headers
    ):
        self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        items = client.get("/answer-bank", headers=auth_headers).json()["items"]
        assert len(items) == 1
        assert items[0]["answer"] == "4 weeks"
        assert items[0]["sensitivity"] == "factual"
        assert items[0]["provenance"] == "user_answered"
        assert items[0]["usedOn"] == []
        assert items[0]["timesUsed"] == 0

    def test_where_used_is_read_from_the_recorded_audit_never_invented(
        self, client, auth_headers, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        item = self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        AnswerBankRepository().record_usage(
            user_id,
            item["id"],
            application_id="app_9",
            job_id="job_9",
            question_as_seen="How much notice must you give?",
            confidence=0.93,
            method="concept",
        )
        listed = client.get("/answer-bank", headers=auth_headers).json()["items"][0]
        assert listed["timesUsed"] == 1
        assert listed["usedOn"][0]["questionAsSeen"] == "How much notice must you give?"
        assert listed["usedOn"][0]["matchConfidence"] == pytest.approx(0.93)

    def test_editing_an_answer_changes_what_will_be_sent(self, client, auth_headers):
        item = self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        response = client.patch(
            f"/answer-bank/{item['id']}", headers=auth_headers, json={"answer": "6 weeks"}
        )
        assert response.status_code == 200
        assert response.json()["answer"] == "6 weeks"

    def test_expiring_an_item_keeps_it_visible_but_stops_it_being_sent(
        self, client, auth_headers, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository
        from app.services.answer_bank import find_match

        item = self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        assert (
            client.post(
                f"/answer-bank/{item['id']}/expire", headers=auth_headers
            ).status_code
            == 200
        )
        listed = client.get("/answer-bank", headers=auth_headers).json()["items"]
        assert len(listed) == 1 and listed[0]["expired"] is True
        assert find_match(
            "What is your notice period?", AnswerBankRepository().list_for_user(user_id)
        ) is None

    def test_deleting_an_item_removes_it(self, client, auth_headers):
        item = self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        assert (
            client.delete(f"/answer-bank/{item['id']}", headers=auth_headers).status_code
            == 204
        )
        assert client.get("/answer-bank", headers=auth_headers).json()["items"] == []

    def test_a_judgement_item_can_be_switched_on_for_auto_answering(
        self, client, auth_headers
    ):
        item = self._bank(
            client, auth_headers, "What are your salary expectations?", "AUD 180k"
        )
        assert item["sensitivity"] == "judgment"
        assert item["autoAnswerOptIn"] is False
        updated = client.patch(
            f"/answer-bank/{item['id']}",
            headers=auth_headers,
            json={"autoAnswerOptIn": True},
        ).json()
        assert updated["autoAnswerOptIn"] is True

    def test_a_sensitive_item_refuses_to_be_switched_on(self, client, auth_headers):
        item = self._bank(
            client,
            auth_headers,
            "Do you consent to a criminal background check?",
            "Yes",
        )
        assert item["sensitivity"] == "sensitive"
        response = client.patch(
            f"/answer-bank/{item['id']}",
            headers=auth_headers,
            json={"autoAnswerOptIn": True},
        )
        assert response.status_code == 200
        assert response.json()["autoAnswerOptIn"] is False
        assert "never" in response.json()["gateReason"].lower()

    def test_another_users_item_is_invisible_and_untouchable(
        self, client, auth_headers
    ):
        item = self._bank(client, auth_headers, "What is your notice period?", "4 weeks")
        credentials = {
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "Sup3rSecret",
        }
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/login", json=credentials).json()["access_token"]
        other = {"Authorization": f"Bearer {token}"}

        assert client.get("/answer-bank", headers=other).json()["items"] == []
        assert (
            client.patch(
                f"/answer-bank/{item['id']}", headers=other, json={"answer": "x"}
            ).status_code
            == 404
        )
        assert client.delete(f"/answer-bank/{item['id']}", headers=other).status_code == 404

    def test_banking_a_blank_answer_is_refused(self, client, auth_headers):
        response = client.post(
            "/answer-bank",
            headers=auth_headers,
            json={"question": "What is your notice period?", "answer": "  "},
        )
        assert response.status_code == 422

    def test_the_bank_requires_authentication(self, client):
        assert client.get("/answer-bank").status_code in (401, 403)
