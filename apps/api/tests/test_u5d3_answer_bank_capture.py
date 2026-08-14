"""U5d-3 Pillars 1+4a — capture, auto-answer, and the native in-card question.

The loop this file pins, end to end:

1. an employer asks a required question nobody has answered → the apply engine
   raises a manual step carrying the question STRUCTURE (text, input kind,
   options), which is persisted so the card can render a real input;
2. the user types the answer INSIDE Aether (``POST /applications/{id}
   /answer-question``) → it is banked with provenance, written against this
   application, and the card's blocker clears — honestly reporting that the
   paused browser session is NOT resumed (that is U5d-4) and the answer will be
   used on the next attempt;
3. the next attempt (and every future application asking the same thing) gets
   the answer injected automatically, with an audit row recording WHICH banked
   item, WHAT confidence, and the question EXACTLY as the employer asked it;
4. except when the question is sensitive/legal — those are refused forever, no
   matter what the bank holds.

ABSOLUTE SAFETY: no browser is launched, no employer is contacted, no email is
sent. Every plan is built from an inline HTML string, and the one execution
uses the existing dependency-injection seam with a stub submitter.
"""
from __future__ import annotations

import json
import uuid

import pytest


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    from app.services import apply_executor

    def _forbidden(**kwargs):  # pragma: no cover - must never run
        raise AssertionError("a REAL browser submission was about to be attempted")

    monkeypatch.setattr(apply_executor, "playwright_form_submitter", _forbidden)
    monkeypatch.setattr(apply_executor, "fetch_apply_page", _forbidden)
    yield


PROFILE = {
    "name": "Test Candidate",
    "email": "candidate@example.com",
    "phone": "0400 000 000",
    "location": "Sydney",
}


def _form(question: str, *, name: str = "custom_q1", kind: str = "text") -> str:
    """An Ashby-shaped application form — the REAL dialect ``_parse_ashby``
    reads (``[data-field-path]`` blocks, requiredness on the label's
    ``_required*`` class), so these tests exercise the production parser rather
    than a shape only they produce."""
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
        <input name="{name}" type="{kind}" required />
      </div>
      <button type="submit">Submit application</button>
    </form>
    """


# ---------------------------------------------------------------------------
# The plan consults the bank
# ---------------------------------------------------------------------------


class TestPlanConsultsTheBank:
    def test_without_a_bank_the_plan_behaves_exactly_as_before(self):
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc:
            build_form_fill_plan(
                _form("What is your notice period?"), channel="ashby", profile=PROFILE
            )
        assert exc.value.reason == "unknown_required_question"

    def test_a_banked_answer_is_injected_and_audited(self):
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import build_form_fill_plan

        bank = [
            {
                "id": "itm_notice",
                "questionText": "Notice period",
                "answer": "4 weeks",
                "scope": "global",
                "scopeValue": "",
                "provenance": "onboarding",
                "sensitivity": "factual",
                "autoAnswerOptIn": False,
                "expiresAt": None,
            }
        ]
        plan = build_form_fill_plan(
            _form("What is your notice period?"),
            channel="ashby",
            profile=PROFILE,
            answer_bank=build_resolver(bank),
        )
        values = {field["name"]: field["value"] for field in plan["fields"]}
        assert values["custom_q1"] == "4 weeks"

        audit = plan["answerBankAudit"]
        assert len(audit) == 1
        assert audit[0]["answerBankItemId"] == "itm_notice"
        assert audit[0]["questionAsSeen"] == "What is your notice period?"
        assert audit[0]["matchConfidence"] >= 0.86
        assert audit[0]["fieldName"] == "custom_q1"

    def test_the_bank_never_overrides_an_answer_the_profile_already_has(self):
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import build_form_fill_plan

        bank = [
            {
                "id": "itm_bad",
                "questionText": "Email",
                "answer": "someone-else@example.com",
                "scope": "global",
                "scopeValue": "",
                "provenance": "onboarding",
                "sensitivity": "factual",
                "autoAnswerOptIn": False,
                "expiresAt": None,
            }
        ]
        plan = build_form_fill_plan(
            _form("Notice period", name="notice"),
            channel="ashby",
            profile={**PROFILE, "customAnswers": {"notice": "4 weeks"}},
            answer_bank=build_resolver(bank),
        )
        values = {field["name"]: field["value"] for field in plan["fields"]}
        assert values["_systemfield_email"] == "candidate@example.com"
        assert values["notice"] == "4 weeks"
        assert plan["answerBankAudit"] == [], (
            "nothing was answered FROM the bank, so nothing may be audited as if it were"
        )

    def test_a_sensitive_question_is_a_manual_step_even_with_a_banked_answer(self):
        """Test-pinned honesty floor: a background-check consent NEVER
        auto-answers, whatever the bank contains."""
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        bank = [
            {
                "id": "itm_bg",
                "questionText": "Do you consent to a criminal background check?",
                "answer": "Yes",
                "scope": "global",
                "scopeValue": "",
                "provenance": "user_answered",
                "sensitivity": "sensitive",
                "autoAnswerOptIn": True,
                "expiresAt": None,
            }
        ]
        with pytest.raises(ManualStepRequired) as exc:
            build_form_fill_plan(
                _form("Do you consent to a criminal background check?"),
                channel="ashby",
                profile=PROFILE,
                answer_bank=build_resolver(bank),
            )
        assert exc.value.reason == "unknown_required_question"

    def test_an_answer_the_user_typed_for_this_application_is_used_once(self):
        """Pillar 4a: the user answering a sensitive question in the card for
        THIS employer is the user answering — not the agent reusing an old
        answer — so it is injected into THIS application's attempt."""
        from app.services.answer_bank import build_resolver
        from app.services.apply_executor import build_form_fill_plan

        resolver = build_resolver(
            [],
            screening_answers={
                "Do you consent to a criminal background check?": "Yes, I consent."
            },
        )
        plan = build_form_fill_plan(
            _form("Do you consent to a criminal background check?"),
            channel="ashby",
            profile=PROFILE,
            answer_bank=resolver,
        )
        values = {field["name"]: field["value"] for field in plan["fields"]}
        assert values["custom_q1"] == "Yes, I consent."
        assert plan["answerBankAudit"][0]["perApplication"] is True

    def test_a_manual_step_carries_the_question_structure_not_just_a_string(self):
        from app.services.apply_executor import ManualStepRequired, build_form_fill_plan

        with pytest.raises(ManualStepRequired) as exc:
            build_form_fill_plan(
                _form("How many years of Kubernetes experience do you have?"),
                channel="ashby",
                profile=PROFILE,
            )
        fields = exc.value.fields
        assert len(fields) == 1
        assert fields[0]["label"] == "How many years of Kubernetes experience do you have?"
        assert fields[0]["name"] == "custom_q1"
        assert fields[0]["kind"] == "text"
        assert fields[0]["sensitivity"] == "factual"


# ---------------------------------------------------------------------------
# Persisting the question structure
# ---------------------------------------------------------------------------


class TestManualStepQuestionsArePersisted:
    def test_record_manual_step_persists_the_structured_questions(
        self, user_id, db_session
    ):
        from app.db import ensure_application_manual_step_columns
        from app.services.apply_executor import record_manual_step

        application_id = _seed_application(db_session, user_id)
        ensure_application_manual_step_columns()
        record_manual_step(
            user_id,
            application_id,
            "unknown_required_question",
            "Flexible Working",
            questions=[
                {
                    "name": "custom_q1",
                    "label": "Flexible Working",
                    "kind": "text",
                    "required": True,
                    "sensitivity": "factual",
                }
            ],
        )
        from app.db import ensure_application_manual_step_question_column

        ensure_application_manual_step_question_column()
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "manualStepQuestions" FROM "Application" WHERE "id" = %s',
                (application_id,),
            )
            stored = cur.fetchone()[0]
        assert stored[0]["label"] == "Flexible Working"
        assert stored[0]["kind"] == "text"

    def test_the_card_control_renders_the_question_natively(self):
        from app.services.submission_control import describe_submission_control

        control = describe_submission_control(
            {
                "id": "a1",
                "jobId": "j1",
                "status": "draft",
                "applyUrl": "https://jobs.ashbyhq.com/example/1",
                "manualStepReason": "unknown_required_question",
                "manualStepDetail": "Flexible Working",
                "manualStepQuestions": [
                    {
                        "name": "custom_q1",
                        "label": "Flexible Working",
                        "kind": "text",
                        "required": True,
                        "sensitivity": "factual",
                    }
                ],
                "hasTailoredResume": True,
                "coverLetter": "Dear team",
            }
        )
        assert control["state"] == "manual_step"
        assert control["action"] == "answer_question"
        assert control["questions"][0]["label"] == "Flexible Working"
        assert "Answer it here" in control["label"] or "answer" in control["label"].lower()

    def test_a_manual_step_with_no_captured_questions_keeps_the_old_control(self):
        from app.services.submission_control import describe_submission_control

        control = describe_submission_control(
            {
                "id": "a1",
                "jobId": "j1",
                "status": "draft",
                "applyUrl": "https://jobs.ashbyhq.com/example/1",
                "manualStepReason": "captcha",
                "manualStepDetail": "This page is showing a CAPTCHA challenge.",
                "hasTailoredResume": True,
                "coverLetter": "Dear team",
            }
        )
        assert control["state"] == "manual_step"
        assert control["action"] == "open_posting"
        assert control["questions"] == []


# ---------------------------------------------------------------------------
# The in-card answer endpoint
# ---------------------------------------------------------------------------


def _seed_application(conn, user_id: str, *, manual: bool = False) -> str:
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


QUESTION = "How many years of Kubernetes experience do you have?"


class TestInCardAnswering:
    def _blocked_application(self, db_session, user_id: str) -> str:
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
            QUESTION,
            questions=[
                {
                    "name": "custom_q1",
                    "label": QUESTION,
                    "kind": "text",
                    "required": True,
                    "sensitivity": "factual",
                }
            ],
        )
        return application_id

    def test_answering_in_the_card_banks_the_answer_with_provenance(
        self, client, auth_headers, db_session, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        application_id = self._blocked_application(db_session, user_id)
        response = client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": QUESTION, "answer": "6 years"}]},
        )
        assert response.status_code == 200, response.text

        banked = AnswerBankRepository().list_for_user(user_id)
        assert len(banked) == 1
        assert banked[0]["answer"] == "6 years"
        assert banked[0]["provenance"] == "user_answered"
        assert banked[0]["provenanceDetail"] == application_id

    def test_the_response_is_honest_that_the_paused_attempt_is_not_resumed(
        self, client, auth_headers, db_session, user_id
    ):
        application_id = self._blocked_application(db_session, user_id)
        body = client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": QUESTION, "answer": "6 years"}]},
        ).json()
        assert body["resumed"] is False
        assert body["transmitted"] is False
        assert "next" in body["detail"].lower()

    def test_answering_every_blocking_question_clears_the_card_blocker(
        self, client, auth_headers, db_session, user_id
    ):
        application_id = self._blocked_application(db_session, user_id)
        client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": QUESTION, "answer": "6 years"}]},
        )
        row = client.get(
            f"/applications/{application_id}", headers=auth_headers
        ).json()
        assert row["manualStepReason"] is None
        assert row["submissionControl"]["state"] == "ready"

    def test_an_answer_for_only_some_questions_leaves_the_blocker_standing(
        self, client, auth_headers, db_session, user_id
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
            f"{QUESTION}; Why do you want to work here?",
            questions=[
                {"name": "q1", "label": QUESTION, "kind": "text", "required": True,
                 "sensitivity": "factual"},
                {"name": "q2", "label": "Why do you want to work here?",
                 "kind": "textarea", "required": True, "sensitivity": "judgment"},
            ],
        )
        body = client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": QUESTION, "answer": "6 years"}]},
        ).json()
        assert body["remainingQuestions"], "the unanswered question must still be named"
        row = client.get(f"/applications/{application_id}", headers=auth_headers).json()
        assert row["manualStepReason"] == "unknown_required_question"

    def test_a_blank_answer_is_refused_and_banks_nothing(
        self, client, auth_headers, db_session, user_id
    ):
        from app.repositories.answer_bank import AnswerBankRepository

        application_id = self._blocked_application(db_session, user_id)
        response = client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": QUESTION, "answer": "   "}]},
        )
        assert response.status_code == 422
        assert AnswerBankRepository().list_for_user(user_id) == []

    def test_another_users_application_cannot_be_answered(
        self, client, auth_headers, db_session, user_id
    ):
        application_id = self._blocked_application(db_session, user_id)
        credentials = {
            "email": f"other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "Sup3rSecret",
        }
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/login", json=credentials).json()["access_token"]
        response = client.post(
            f"/applications/{application_id}/answer-question",
            headers={"Authorization": f"Bearer {token}"},
            json={"answers": [{"question": QUESTION, "answer": "6 years"}]},
        )
        assert response.status_code == 404

    def test_a_sensitive_answer_given_in_the_card_is_banked_but_stays_gated(
        self, client, auth_headers, db_session, user_id
    ):
        from app.db import (
            ensure_application_manual_step_columns,
            ensure_application_manual_step_question_column,
        )
        from app.repositories.answer_bank import AnswerBankRepository
        from app.services.answer_bank import find_match
        from app.services.apply_executor import record_manual_step

        sensitive = "Do you consent to a criminal background check?"
        application_id = _seed_application(db_session, user_id)
        ensure_application_manual_step_columns()
        ensure_application_manual_step_question_column()
        record_manual_step(
            user_id,
            application_id,
            "unknown_required_question",
            sensitive,
            questions=[
                {"name": "q1", "label": sensitive, "kind": "text", "required": True,
                 "sensitivity": "sensitive"},
            ],
        )
        client.post(
            f"/applications/{application_id}/answer-question",
            headers=auth_headers,
            json={"answers": [{"question": sensitive, "answer": "Yes, I consent."}]},
        )
        repo = AnswerBankRepository()
        banked = repo.list_for_user(user_id)
        assert len(banked) == 1 and banked[0]["sensitivity"] == "sensitive"
        # Banked, and STILL never auto-answered on a future application.
        assert find_match(sensitive, banked) is None
