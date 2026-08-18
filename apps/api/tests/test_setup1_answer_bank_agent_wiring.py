"""SETUP-1 — questionnaire answers must actually reach the apply executor.

The Settings panel and the first-run prompt only matter if the words the user
typed are the same words ``build_form_fill_plan`` types into an ATS field, and
if answering a new question on an application card grows the bank for the next
attempt. This file pins that loop against a real Ashby-shaped form — no
browser, no employer, no invented answer.

The honesty bar is the same as the rest of the bank:

* without a stored answer the plan MUST still raise ``ManualStepRequired``;
* a questionnaire answer (provenance ``onboarding``) auto-fills and is counted
  as a reuse, not as something "learned from an application";
* an in-card answer (provenance ``user_answered`` + this application) is what
  increments ``learnedFromApplications``.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.services.apply_executor import (
    ManualStepRequired,
    build_answer_bank_resolver,
    build_form_fill_plan,
    record_answer_bank_usage,
)


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


PROFILE = {
    "name": "Test Candidate",
    "email": "candidate@example.com",
    "phone": "0400 000 000",
    "location": "Sydney",
}

NOTICE_QUESTION = "What is your notice period?"
NOTICE_ANSWER = "4 weeks from the date I accept."
WORK_RIGHTS_QUESTION = (
    "Are you legally entitled to work in the country you are applying in?"
)
WORK_RIGHTS_ANSWER = "Yes — Australian citizen with full working rights."
YEARS_QUESTION = "How many years of Kubernetes experience do you have?"
YEARS_ANSWER = "6 years, the last 3 in production."


def _form(question: str, *, name: str = "custom_q1") -> str:
    """Ashby dialect the production parser reads (``[data-field-path]``)."""
    return f"""
    <form>
      <div data-field-path="_systemfield_name">
        <label class="_label _required_a1">Full name *</label>
        <input name="_systemfield_name" type="text" required />
      </div>
      <div data-field-path="_systemfield_email">
        <label class="_label _required_a2">Email *</label>
        <input name="_systemfield_email" type="email" required />
      </div>
      <div data-field-path="{name}">
        <label class="_label _required_a3">{question} *</label>
        <input name="{name}" type="text" required />
      </div>
      <button type="submit">Submit application</button>
    </form>
    """


def _seed_application(conn, user_id: str) -> str:
    job_id, resume_id, application_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id", "userId", "title", "company", "description",'
            ' "source", "sourceUrl", "status", "createdAt", "updatedAt")'
            " VALUES (%s, %s, 'Platform Engineer', 'Acme Pty Ltd', 'A role.',"
            " 'test', 'https://jobs.ashbyhq.com/acme/1', 'discovered', NOW(), NOW())",
            (job_id, user_id),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id", "userId", "version", "sections",'
            ' "formatHash", "sourceJobId", "updatedAt")'
            " VALUES (%s, %s, 1, %s, 'h', %s, NOW())",
            (
                resume_id,
                user_id,
                json.dumps({"contact": {"name": "Test Candidate"}}),
                job_id,
            ),
        )
        cur.execute(
            'INSERT INTO "Application" ("id", "userId", "jobId", "resumeId", "status",'
            ' "coverLetter", "createdAt", "updatedAt")'
            " VALUES (%s, %s, %s, %s, 'draft', 'Dear team', NOW(), NOW())",
            (application_id, user_id, job_id, resume_id),
        )
    conn.commit()
    return application_id


class TestQuestionnaireReachesTheExecutor:
    def test_without_a_banked_answer_the_plan_still_refuses_to_invent_one(self):
        with pytest.raises(ManualStepRequired) as exc:
            build_form_fill_plan(
                _form(NOTICE_QUESTION), channel="ashby", profile=PROFILE
            )
        assert exc.value.reason == "unknown_required_question"

    def test_a_questionnaire_answer_fills_the_ats_field_and_is_counted_as_reused(
        self, client, auth_headers, user_id, db_session
    ):
        before = client.get("/answer-bank/readiness", headers=auth_headers).json()
        assert before["timesAnswered"] == 0
        assert before["learnedFromApplications"] == 0
        assert before["setupComplete"] is False

        saved = client.post(
            "/answer-bank/questionnaire",
            headers=auth_headers,
            json={
                "answers": [
                    {"question": WORK_RIGHTS_QUESTION, "answer": WORK_RIGHTS_ANSWER},
                    {"question": NOTICE_QUESTION, "answer": NOTICE_ANSWER},
                ]
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["banked"] == 2

        resolver = build_answer_bank_resolver(user_id, PROFILE)
        plan = build_form_fill_plan(
            _form(NOTICE_QUESTION),
            channel="ashby",
            profile=PROFILE,
            answer_bank=resolver,
        )
        values = {field["name"]: field["value"] for field in plan["fields"]}
        assert values["custom_q1"] == NOTICE_ANSWER
        assert plan["answerBankAudit"], "an auto-fill must be auditable"

        application_id = _seed_application(db_session, user_id)
        recorded = record_answer_bank_usage(user_id, application_id, plan)
        assert recorded == 1

        mid = client.get("/answer-bank/readiness", headers=auth_headers).json()
        assert mid["timesAnswered"] == 1
        assert mid["learnedFromApplications"] == 0
        assert mid["autoAnswerable"] >= 2
        assert mid["setupComplete"] is False

    def test_an_in_card_answer_is_what_the_learning_loop_counts_and_reuses(
        self, client, auth_headers, user_id, db_session
    ):
        from app.db import (
            ensure_application_manual_step_columns,
            ensure_application_manual_step_question_column,
        )
        from app.services.apply_executor import record_manual_step

        application_id = _seed_application(db_session, user_id)
        ensure_application_manual_step_columns()
        ensure_application_manual_step_question_column()
        record_manual_step(
            user_id,
            application_id,
            "unknown_required_question",
            YEARS_QUESTION,
            questions=[
                {
                    "name": "custom_q1",
                    "label": YEARS_QUESTION,
                    "kind": "text",
                    "required": True,
                    "sensitivity": "factual",
                }
            ],
        )

        response = client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": YEARS_QUESTION, "answer": YEARS_ANSWER}]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["transmitted"] is False

        learned = client.get("/answer-bank/readiness", headers=auth_headers).json()
        assert learned["learnedFromApplications"] == 1

        resolver = build_answer_bank_resolver(user_id, PROFILE)
        plan = build_form_fill_plan(
            _form(YEARS_QUESTION),
            channel="ashby",
            profile=PROFILE,
            answer_bank=resolver,
        )
        values = {field["name"]: field["value"] for field in plan["fields"]}
        assert values["custom_q1"] == YEARS_ANSWER
