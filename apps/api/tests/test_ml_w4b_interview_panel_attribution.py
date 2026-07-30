"""ML-W4B verification — the Interview Center prep payload must not mislabel or
lose the prep brief an interviewPrep run produced.

Wave-4B (25ccabe) made ``GET /workspaces/interviews/prep`` genuinely populated
for the first time: it reads the most recent ``AgentRun`` whose ``agentName
ILIKE '%interview%'`` and renders ``output.predictedQuestions`` under a session
header derived from the caller's most recent ``Application`` at the ``interview``
stage. That read was written when NOTHING ever produced such a row, so two
defects in it were unreachable — and became reachable the moment a real agent
started writing them:

D1  It takes the most recent ``%interview%`` run REGARDLESS of status. A FAILED
    run (e.g. the honest 503 when the LLM is unavailable — a documented, common
    outcome) has ``output = NULL``, so it silently WIPES a perfectly good prep
    brief from an earlier successful run. The sibling debrief query in the same
    function already filters ``status = 'completed'``; this one does not.

D2  It takes that run's questions REGARDLESS of which job they were predicted
    for. ``job_id`` is an optional parameter of the agent, so a run for job B
    renders its questions under job A's session header — questions predicted
    from a DIFFERENT posting, presented as the prep for this interview. That is
    a misattribution of generated content, not merely a cosmetic mismatch.

Both are fixed by choosing the run the panel renders honestly: the most recent
COMPLETED run whose own ``output.jobId`` is the job being rendered; and when the
only available brief is for a different job, serving no questions plus an honest
note rather than someone else's.
"""
from __future__ import annotations

import json
import uuid

import pytest

JOB_TITLE = "Senior Platform Engineer"
JOB_COMPANY = "Atlassian"
OTHER_TITLE = "Staff Data Engineer"
OTHER_COMPANY = "Canva"


def _uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture()
def user_id(auth_headers, test_user_id) -> str:
    return test_user_id


def _seed_job(conn, user_id: str, *, title: str, company: str) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","location",'
            '"description","requirements","source","sourceUrl","status",'
            '"fitScore","createdAt","updatedAt") VALUES '
            "(%s,%s,%s,%s,'Melbourne, Australia',%s,%s,'seek',%s,"
            "'discovered'::\"JobStatus\",88.0,NOW(),NOW())",
            (
                job_id, user_id, title, company,
                "We are hiring to scale our Kubernetes platform and lead "
                "incident response for a payments service.",
                json.dumps(["Kubernetes at scale"]),
                f"https://example.com/job/{job_id}",
            ),
        )
    conn.commit()
    return job_id


def _seed_interview_application(conn, user_id: str, job_id: str) -> str:
    app_id, resume_id = _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections",'
            '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "seed"}), f"h-{resume_id}"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") VALUES '
            "(%s,%s,%s,%s,'interview'::\"ApplicationStatus\",NOW(),NOW())",
            (app_id, user_id, job_id, resume_id),
        )
    conn.commit()
    return app_id


def _seed_prep_run(
    conn,
    user_id: str,
    *,
    status: str,
    output: dict | None,
    minutes_ago: int,
    agent_name: str = "interviewPrep",
) -> str:
    """One durable interviewPrep AgentRun row, exactly as ``_record_run`` writes
    it (agentName, status, jsonb output), at a controllable position in time."""
    run_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "AgentRun" ("id","userId","agentName","status","output",'
            '"startedAt","completedAt","createdAt") VALUES '
            "(%s,%s,%s,%s::\"AgentRunStatus\",%s::jsonb,"
            "NOW() - (%s || ' minutes')::interval,"
            "NOW() - (%s || ' minutes')::interval,"
            "NOW() - (%s || ' minutes')::interval)",
            (
                run_id, user_id, agent_name, status,
                None if output is None else json.dumps(output),
                minutes_ago, minutes_ago, minutes_ago,
            ),
        )
    conn.commit()
    return run_id


def _questions(job_id: str, text: str, *, job_title: str = JOB_TITLE) -> dict:
    """An interviewPrep run's ``output``, in the shape the router's ``_record_run``
    persists (``InterviewPrepResult`` asdict-serialised)."""
    return {
        "jobId": job_id,
        "jobTitle": job_title,
        "predictedQuestions": [
            {
                "question": text,
                "category": "behavioural",
                "whyAsked": "The posting asks for Kubernetes at scale.",
                "suggestedStoryId": None,
                "suggestedStoryTitle": None,
                "answerSketch": None,
                "preparationNote": None,
                "guardActions": [],
            }
        ],
    }


def _prep(client, auth_headers) -> dict:
    res = client.get("/workspaces/interviews/prep", headers=auth_headers)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# D1 — a later FAILED run must not wipe a good brief
# ---------------------------------------------------------------------------


def test_a_failed_prep_run_does_not_wipe_an_earlier_successful_brief(
    client, auth_headers, user_id, db_session
):
    job_id = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    _seed_interview_application(db_session, user_id, job_id)
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(job_id, "Tell me about a platform you owned."),
        minutes_ago=30,
    )
    # The honest 503 path: the run row is `failed` with no output at all.
    _seed_prep_run(
        db_session, user_id, status="failed", output=None, minutes_ago=5
    )

    payload = _prep(client, auth_headers)
    assert payload["questions"], (
        "a failed run (LLM unavailable — output NULL) silently wiped the prep "
        "brief an earlier successful run produced"
    )
    assert payload["questions"][0]["question"] == (
        "Tell me about a platform you owned."
    )


def test_a_later_successful_run_still_wins(
    client, auth_headers, user_id, db_session
):
    """The other direction — filtering on `completed` must not pin the panel to a
    stale brief: the newest COMPLETED run for this job is what renders."""
    job_id = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    _seed_interview_application(db_session, user_id, job_id)
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(job_id, "The OLD question."), minutes_ago=30,
    )
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(job_id, "The NEW question."), minutes_ago=1,
    )

    payload = _prep(client, auth_headers)
    assert [q["question"] for q in payload["questions"]] == ["The NEW question."]


# ---------------------------------------------------------------------------
# D2 — questions predicted for another job must never render as this prep
# ---------------------------------------------------------------------------


def test_questions_predicted_for_another_job_are_not_served_as_this_prep(
    client, auth_headers, user_id, db_session
):
    """``job_id`` is an OPTIONAL agent parameter, so a prep run for job B is a
    normal thing to have. Rendering B's questions under A's session header would
    present questions predicted from a different posting as the prep for THIS
    interview."""
    job_a = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    job_b = _seed_job(db_session, user_id, title=OTHER_TITLE, company=OTHER_COMPANY)
    _seed_interview_application(db_session, user_id, job_a)
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(
            job_b, "A question about the OTHER job.", job_title=OTHER_TITLE
        ),
        minutes_ago=2,
    )

    payload = _prep(client, auth_headers)
    assert payload["session"]["role"] == JOB_TITLE
    assert payload["questions"] == [], (
        "questions predicted for a DIFFERENT job were served as this "
        f"interview's prep: {payload['questions']}"
    )
    # Never a silent drop — the payload says WHY there is nothing here.
    note = payload.get("questionsNote")
    assert note, "the drop is silent — no honest note explains it"
    assert "different job" in note.lower() or "another job" in note.lower(), note
    # And it NAMES the job whose brief is being withheld, so the withholding is
    # auditable rather than vague.
    assert OTHER_TITLE in note, note


def test_this_jobs_brief_wins_over_a_newer_brief_for_another_job(
    client, auth_headers, user_id, db_session
):
    """A newer run for an unrelated job must not hide THIS interview's own,
    correctly-attributed brief."""
    job_a = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    job_b = _seed_job(db_session, user_id, title=OTHER_TITLE, company=OTHER_COMPANY)
    _seed_interview_application(db_session, user_id, job_a)
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(job_a, "The question for THIS interview."),
        minutes_ago=20,
    )
    _seed_prep_run(
        db_session, user_id, status="completed",
        output=_questions(
            job_b, "A question about the OTHER job.", job_title=OTHER_TITLE
        ),
        minutes_ago=1,
    )

    payload = _prep(client, auth_headers)
    assert [q["question"] for q in payload["questions"]] == [
        "The question for THIS interview."
    ]
    assert not payload.get("questionsNote"), payload.get("questionsNote")


def test_a_brief_that_claims_no_job_is_still_served(
    client, auth_headers, user_id, db_session
):
    """Backwards compatibility: a completed ``%interview%`` run whose output
    carries NO ``jobId`` makes no job claim at all, so it cannot be misattributed
    — it must keep rendering rather than being dropped by the new check."""
    job_id = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    _seed_interview_application(db_session, user_id, job_id)
    _seed_prep_run(
        db_session, user_id, status="completed",
        output={"predictedQuestions": [{"question": "A job-agnostic question."}]},
        minutes_ago=2,
    )

    payload = _prep(client, auth_headers)
    assert [q["question"] for q in payload["questions"]] == [
        "A job-agnostic question."
    ]


def test_the_payload_shape_is_unchanged_for_a_user_with_no_runs(
    client, auth_headers, user_id, db_session
):
    """The additive ``questionsNote`` key must not disturb the existing contract
    (test_workspaces.py's shape test) or invent a note where none applies."""
    job_id = _seed_job(db_session, user_id, title=JOB_TITLE, company=JOB_COMPANY)
    _seed_interview_application(db_session, user_id, job_id)

    payload = _prep(client, auth_headers)
    for key in ("session", "compliance", "brief", "questions", "liveAssist", "debrief"):
        assert key in payload, key
    assert payload["questions"] == []
    assert payload.get("questionsNote") is None
