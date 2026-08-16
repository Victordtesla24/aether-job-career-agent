"""RT-002 — a résumé with ZERO tailorable bullets must refuse honestly, not 503.

LIVE INCIDENT (production, owner account, resume v2 ``Vik_Resume_BA.pdf``):
the designed multi-column layout has no marker lines, so the heuristic
``extract_bullets`` parsed **0** bullets while ``raw_text`` came through fine
(3.4 KB). ``TailoringAgent.run`` then called the LLM with an EMPTY "Original
bullets:" block. The user-chosen model (``anthropic/claude-sonnet-4.6`` — a
deliberate pick, so ADR-ML-3 suppresses any fallback) answered honestly, in
PROSE: "the original bullets section is empty...". ``complete_json`` failed to
parse at char 0 and raised ``LLMUnavailableError``, which the router rendered as
"The AI service is temporarily unavailable. Please try again in a moment."

Every clause of that sentence was false. The AI service was fine; the INPUT was
unusable. Because the class was ``retryable``, ``board_sweep`` burned its three
attempts, opened its LLM circuit, and suppressed 1405 eligible jobs on EVERY
cycle, indefinitely.

The same class already bit .docx uploads once (``routers/resumes.py``
``_extract_docx_text`` docstring: "a .docx résumé previously extracted ZERO
bullets ... the upload succeeded and then nothing in it could ever be
tailored") and was fixed per-FORMAT. These tests fix it at the CLASS level:
zero tailorable bullets is an INPUT error, named as such, before any model is
contacted.

Fail-before (unfixed tree): the guard does not exist — ``TailoringAgent.run``
reaches ``LLMClient.complete_json`` (test 1 fails), no
``ResumeBulletsUnavailableError`` symbol exists to import, and the board sweep
has no branch for it.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

import pytest

from app.workers import board_sweep

#: The production shape: a designed résumé whose flat text layer carries NO
#: bullet markers, so ``extract_bullets`` returns [] while the text is complete.
BULLETLESS_RESUME_TEXT = """VIKRAM SARKAR    Melbourne VIC    vik@example.com
Business Analyst
PROFILE
Business analyst with fifteen years across banking and government platforms.
EXPERIENCE
Australian Taxation Office    Business Analyst    2021 to 2024
Delivered the Payday Super discovery across eight agency stakeholders.
Reduced manual reconciliation effort by 92 percent with an automated harness.
Telstra    Senior Analyst    2018 to 2021
Mapped the order to activate journey for the enterprise fibre portfolio.
EDUCATION
Master of Business Systems, Monash University, 2010
"""


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, fit: float = 80.0) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Business Analyst", "Acme", "Analyse things.",
             "greenhouse", f"https://example.com/job/{job_id}", "screening", fit),
        )
    conn.commit()
    return job_id


def _seed_bulletless_resume(conn, user_id: str, label: str = "Vik_Resume_BA") -> str:
    """The live defect, persisted: complete ``raw_text``, ``bullets == []``."""
    resume_id = _uid()
    sections = {"raw_text": BULLETLESS_RESUME_TEXT, "bullets": [], "contact": {}}
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","label","sections",'
            '"formatHash","createdAt","updatedAt") '
            'VALUES (%s,%s,1,%s,%s,%s,NOW(),NOW())',
            (resume_id, user_id, label, json.dumps(sections), "hash-rt002"),
        )
    conn.commit()
    return resume_id


@pytest.fixture()
def no_llm(monkeypatch):
    """Every LLM entry point becomes a tripwire: the guard must fire first."""
    from app.services.llm_client import LLMClient

    calls: list[str] = []

    def _tripwire(self, prompt_name, *a, **k):  # noqa: ANN001
        calls.append(prompt_name)
        raise AssertionError(
            f"the tailor run called the LLM ({prompt_name!r}) despite having "
            "ZERO tailorable bullets to send it"
        )

    monkeypatch.setattr(LLMClient, "complete", _tripwire)
    monkeypatch.setattr(LLMClient, "complete_json", _tripwire)
    return calls


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


# ---------------------------------------------------------------------------
# 1-3: the guard itself — honest, actionable, and BEFORE any model call
# ---------------------------------------------------------------------------
class TestGuardFiresBeforeTheModel:
    def test_zero_tailorable_bullets_refuses_without_any_llm_call(
        self, db_session, user_id, no_llm
    ):
        """THE defect. A résumé the parser found no bullets in must never be
        sent to a model with an empty "Original bullets:" block."""
        from app.agents.tailor_agent import TailoringAgent
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        _seed_bulletless_resume(db_session, user_id)
        job_id = _seed_job(db_session, user_id)

        with pytest.raises(ResumeBulletsUnavailableError):
            TailoringAgent().run(user_id, job_id)
        assert no_llm == [], f"the model was contacted anyway: {no_llm}"

    def test_the_message_names_the_real_cause_and_the_real_remedy(
        self, db_session, user_id, no_llm
    ):
        from app.agents.tailor_agent import TailoringAgent
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        _seed_bulletless_resume(db_session, user_id, label="Vik_Resume_BA")
        job_id = _seed_job(db_session, user_id)

        with pytest.raises(ResumeBulletsUnavailableError) as ei:
            TailoringAgent().run(user_id, job_id)
        message = str(ei.value)
        assert "no tailorable bullet points" in message.lower()
        assert "0 were parsed" in message
        assert "Vik_Resume_BA" in message, message
        assert "Resume Studio" in message, message

    def test_the_message_never_blames_the_ai_service(
        self, db_session, user_id, no_llm
    ):
        """The exact falsehood the incident surfaced. The upstream was healthy;
        saying otherwise sent the owner (and the autopilot) chasing a
        non-existent outage."""
        from app.agents.tailor_agent import TailoringAgent
        from app.services.llm_client import LLM_UNAVAILABLE_USER_MESSAGE
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        _seed_bulletless_resume(db_session, user_id)
        job_id = _seed_job(db_session, user_id)

        with pytest.raises(ResumeBulletsUnavailableError) as ei:
            TailoringAgent().run(user_id, job_id)
        message = str(ei.value)
        assert "AI service" not in message
        assert "temporarily unavailable" not in message.lower()
        assert message != LLM_UNAVAILABLE_USER_MESSAGE


# ---------------------------------------------------------------------------
# 4-5: it is an INPUT error, not an LLM failure — nothing may classify it as one
# ---------------------------------------------------------------------------
class TestClassifiedAsInputNotLLM:
    def test_it_is_not_an_llm_failure_and_carries_no_retryable_class(self):
        from app.services.llm_client import (
            LLM_NON_RETRYABLE_FAILURE_CLASSES,
            LLMUnavailableError,
        )
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        exc = ResumeBulletsUnavailableError("no bullets")
        assert not isinstance(exc, LLMUnavailableError), (
            "an input error inheriting the LLM failure type would be counted by "
            "every LLM circuit breaker in the product"
        )
        assert getattr(exc, "retryable", False) is False
        assert LLM_NON_RETRYABLE_FAILURE_CLASSES  # sanity: the classes exist

    def test_the_board_sweeps_llm_classifier_does_not_recognise_it(self):
        """``board_sweep._llm_failure`` is the seam that decides whether a
        failure counts toward ``LLM_OUTAGE_BREAKER``. It must return ``None``
        here or a bad résumé opens the LLM circuit."""
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        assert board_sweep._llm_failure(
            ResumeBulletsUnavailableError("no bullets")
        ) is None


# ---------------------------------------------------------------------------
# 6-8: the board sweep stops for that user, honestly, without burning the circuit
# ---------------------------------------------------------------------------
class TestBoardSweepStopsTheStretch:
    def test_one_attempt_then_stop_because_every_job_shares_the_resume(
        self, db_session, user_id, monkeypatch
    ):
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        for _ in range(6):
            _seed_job(db_session, user_id)
        calls: list[str] = []

        def _boom(uid, agent, params):
            calls.append(agent)
            raise ResumeBulletsUnavailableError(
                "This resume has no tailorable bullet points (0 were parsed "
                "from 'Vik_Resume_BA'). Open Resume Studio and run bullet "
                "extraction, or upload a text-based resume."
            )

        monkeypatch.setattr(board_sweep, "_run_agent", _boom)
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert len(calls) == 1, f"expected one attempt, got {len(calls)}: {calls}"
        assert summary["reason"] == "resume-no-bullets", summary
        assert summary["needs_continuation"] is False

    def test_the_remaining_jobs_are_suppressed_not_failed(
        self, db_session, user_id, monkeypatch
    ):
        """"Not attempted" is the truth: no model was contacted for any of
        them, so counting them as failures would fabricate work."""
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        for _ in range(5):
            _seed_job(db_session, user_id)

        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: (_ for _ in ()).throw(
                ResumeBulletsUnavailableError("no tailorable bullet points")
            ),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert summary["suppressed"] == 4, summary
        assert summary["failures"] == 0, summary

    def test_the_honest_reason_is_logged_once_and_names_the_input(
        self, db_session, user_id, monkeypatch, caplog
    ):
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        for _ in range(4):
            _seed_job(db_session, user_id)
        message = (
            "This resume has no tailorable bullet points (0 were parsed from "
            "'Vik_Resume_BA')."
        )
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: (_ for _ in ()).throw(
                ResumeBulletsUnavailableError(message)
            ),
        )
        with caplog.at_level(logging.WARNING, logger="app.workers.board_sweep"):
            board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        records = [
            r for r in caplog.records
            if "tailorable bullet points" in r.getMessage()
        ]
        assert len(records) == 1, [r.getMessage() for r in caplog.records]
        joined = records[0].getMessage()
        assert "suppressed" in joined.lower()
        assert "AI service" not in joined

    def test_the_llm_outage_breaker_is_never_touched(
        self, db_session, user_id, monkeypatch
    ):
        """A bad résumé must not open the LLM circuit — that is what suppressed
        1405 jobs per cycle in production."""
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        for _ in range(4):
            _seed_job(db_session, user_id)
        opened: list[tuple] = []
        monkeypatch.setattr(
            board_sweep, "_run_agent",
            lambda *a, **k: (_ for _ in ()).throw(
                ResumeBulletsUnavailableError("no tailorable bullet points")
            ),
        )
        import app.services.llm_client as lc

        monkeypatch.setattr(
            lc, "_record_llm_circuit_open",
            lambda *a, **k: opened.append(a),
        )
        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())
        assert opened == [], "an input error tripped the LLM circuit breaker"
        assert not summary["reason"].startswith("llm-")
        assert summary["reason"] != "llm-unavailable"


# ---------------------------------------------------------------------------
# 9-10: the message reaches the audit row and the HTTP surface VERBATIM
# ---------------------------------------------------------------------------
class TestTheMessageSurvivesToTheUser:
    def test_the_agent_run_row_records_the_honest_message_verbatim(
        self, db_session, user_id
    ):
        from app.db import get_connection
        from app.routers.agents import _record_run
        from app.services.resume_grounding import ResumeBulletsUnavailableError

        message = (
            "This resume has no tailorable bullet points (0 were parsed from "
            "'Vik_Resume_BA'). Open Resume Studio and run bullet extraction, "
            "or upload a text-based resume."
        )

        def _boom():
            raise ResumeBulletsUnavailableError(message)

        with pytest.raises(ResumeBulletsUnavailableError):
            _record_run(user_id, "tailor", {}, _boom)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "error" FROM "AgentRun" WHERE "userId" = %s '
                    'AND "agentName" = %s ORDER BY "startedAt" DESC LIMIT 1',
                    (user_id, "tailor"),
                )
                row = cur.fetchone()
        assert row is not None
        assert row[0] == message, row[0]

    def test_the_http_surface_is_an_actionable_422_not_a_503(
        self, client, auth_headers, db_session, user_id, no_llm
    ):
        """503 = "our fault, try again". This is neither: the user has to fix
        their résumé, so the status must not invite a retry."""
        _seed_bulletless_resume(db_session, user_id)
        job_id = _seed_job(db_session, user_id)

        res = client.post(
            "/agents/tailor/run", json={"job_id": job_id}, headers=auth_headers
        )
        assert res.status_code == 422, res.text
        detail = res.json()["detail"]
        assert "no tailorable bullet points" in detail.lower()
        assert "AI service" not in detail
