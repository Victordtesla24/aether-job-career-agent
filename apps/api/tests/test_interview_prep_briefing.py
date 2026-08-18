"""Interview prep briefing must come from the email trail and the candidate's own evidence.

The attached-style brief (logistics, traps, questions to ask, conversion
guidelines) is assembled deterministically from the trail + résumé + stories +
ingested career data. It must never invent a company fact that is not in those
sources, and it must surface unanswered recruiter questions.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.interview_prep_briefing import (
    default_guidelines,
    default_questions_to_ask,
    detect_prep_traps,
)

_MEL = ZoneInfo("Australia/Melbourne")

RESUME = (
    "Vikram Deshpande. TruEnergy, Mar-Aug 2025, retail systems on Tally and "
    "Gentrack. ATO: March 2026 – Present. ANZ core banking transformation."
)
THREAD = (
    "John Black: When did you finish with the ATO?\n"
    "Adan Micallef will meet face to face tomorrow at 10:00am at Docklands "
    "for Project Manager at Next Business Energy. Gentrack vs Tally tender."
)


def test_unanswered_recruiter_question_is_a_trap():
    traps = detect_prep_traps(
        resume_text=RESUME,
        thread_text=THREAD,
        unanswered_questions=["When did you finish with the ATO?"],
        job_text="Project Manager — Retail Systems Transformation",
    )
    joined = " ".join(t["detail"] for t in traps).lower()
    assert "ato" in joined
    assert any("unanswered" in t["title"].lower() for t in traps)


def test_truenergy_and_energyaustralia_in_evidence_is_flagged_without_inventing_dates():
    traps = detect_prep_traps(
        resume_text=RESUME + " EnergyAustralia billing platform.",
        thread_text=THREAD,
        unanswered_questions=[],
        job_text="energy retailer",
    )
    joined = " ".join(t["detail"] for t in traps).lower()
    assert "truenergy" in joined
    assert "2012" not in joined  # never invent the rebrand year


def test_onsite_guidelines_name_the_evidenced_place_and_time():
    from app.services.interview_thread_parser import InterviewOffer

    when = datetime(2026, 8, 19, 10, 0, tzinfo=_MEL)
    offer = InterviewOffer(
        is_interview=True,
        interview_type="onsite",
        location="Docklands office",
        scheduled_at=when,
        unanswered_questions=("When did you finish with the ATO?",),
    )
    lines = default_guidelines(offer)
    blob = " ".join(lines).lower()
    assert "face" in blob or "onsite" in blob or "docklands" in blob
    assert "10" in blob
    assert "ato" in blob


def test_tender_tokens_in_the_trail_produce_questions_to_ask():
    qs = default_questions_to_ask(
        thread_text=THREAD,
        job_text="12-month FTC replacing the billing platform",
    )
    blob = " ".join(qs).lower()
    assert "tender" in blob
    assert "twelve months" in blob or "12-month" in blob or "month twelve" in blob


def test_prep_agent_attaches_deterministic_briefing(
    db_session, test_user_id, monkeypatch
):
    from app.agents.interview_prep_agent import InterviewPrepAgent
    from app.repositories.career_profile import CareerProfileRepository
    from app.repositories.story import StoryRepository

    job_id, resume_id, app_id, thread_id = (
        uuid.uuid4().hex,
        uuid.uuid4().hex,
        uuid.uuid4().hex,
        uuid.uuid4().hex,
    )
    trail = [
        {
            "from": "John Black",
            "fromEmail": "john.black@robertwalters.com.au",
            "role": "received",
            "createdAt": "2026-08-06T14:00:00+10:00",
            "body": (
                "I've spoken with Adan Micallef at Next Business Energy. "
                "Phone interview tomorrow at 10:00am.\n"
                "When did you finish with the ATO?"
            ),
        },
        {
            "from": "Adan Micallef",
            "fromEmail": "adan@nextbusinessenergy.com.au",
            "role": "received",
            "createdAt": "2026-08-18T16:00:00+10:00",
            "body": (
                "Confirming we will meet face to face tomorrow morning at "
                "10:00am at our Docklands office. Gentrack vs Tally tender."
            ),
        },
    ]
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                test_user_id,
                "Project Manager — Retail Systems Transformation",
                "Next Business Energy",
                "Billing platform tender covering Gentrack and Tally.",
                "email",
                f"https://example.com/job/{job_id}",
                80.0,
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections",'
            '"formatHash","updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (
                resume_id,
                test_user_id,
                json.dumps({"raw_text": RESUME, "summary": RESUME}),
                "hash-brief",
            ),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW())',
            (app_id, test_user_id, job_id, resume_id, "interview"),
        )
        cur.execute(
            'INSERT INTO "EmailThread" ("id","userId","applicationId","subject",'
            '"messages","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s::jsonb,NOW(),NOW())",
            (
                thread_id,
                test_user_id,
                app_id,
                "Next Business Energy — Project Manager interview",
                json.dumps(trail),
            ),
        )
    db_session.commit()
    StoryRepository().create(
        test_user_id,
        {
            "title": "Energy retail billing on Tally and Gentrack",
            "situation": "TruEnergy retail billing ran on Tally and Gentrack.",
            "task": "I owned vendor accountability for the billing stack.",
            "action": "I ran cutover rehearsals and a revenue-assurance gate.",
            "result": "Billing ran parallel for two cycles with no deferred invoices.",
            "metrics": {},
            "tags": ["Tally", "Gentrack"],
        },
    )
    CareerProfileRepository().upsert(
        test_user_id,
        "github",
        status="ok",
        url="https://github.com/example",
        content={"top_repos": [{"name": "billing-cutover", "description": "Tally"}]},
        summary="GitHub: billing-cutover — Tally/Gentrack cutover notes.",
    )

    class _LLM:
        def complete_json(self, *_a, **_k):  # noqa: ANN001
            return {
                "questions": [
                    {
                        "question": "Tell me about your Gentrack and Tally experience.",
                        "category": "technical",
                        "whyAsked": "The posting covers Gentrack and Tally.",
                        "suggestedStoryId": "S1",
                        "answerSketch": {
                            "situation": "TruEnergy retail billing ran on Tally and Gentrack.",
                            "task": "I owned vendor accountability for the billing stack.",
                            "action": "I ran cutover rehearsals and a revenue-assurance gate.",
                            "result": "Billing ran parallel for two cycles with no deferred invoices.",
                            "reflection": "I would lock the reconciliation gate earlier.",
                        },
                    }
                ],
                "questionsToAsk": [
                    "Where has the tender actually got to — still going to market, or a shortlist?"
                ],
                "guidelines": [
                    "Ask about next steps before you hang up."
                ],
            }

    result = InterviewPrepAgent(llm=_LLM()).run(test_user_id, job_id=job_id)
    assert result.predictedQuestions
    assert "gentrack" in result.predictedQuestions[0].question.lower()
    briefing = result.briefing
    assert briefing["traps"]
    trap_blob = " ".join(
        f"{t.get('title', '')} {t.get('detail', '')}" for t in briefing["traps"]
    ).lower()
    assert "ato" in trap_blob
    assert result.careerSourcesUsed >= 1
    assert briefing["questionsToAsk"]
    assert briefing["guidelines"]
    assert briefing["documentMarkdown"]
    assert "Next Business Energy" in briefing["documentMarkdown"]
