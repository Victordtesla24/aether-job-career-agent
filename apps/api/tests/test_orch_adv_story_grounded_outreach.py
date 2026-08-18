"""ORCH-ADV — recruiterOutreach and reference consume Story Bank evidence.

Runtime census: both agents were islands (base résumé + Contact only). The
adversarial review required them to depend on storyExtraction the same way
tailoring already does, without inventing company research.
"""
from __future__ import annotations

from conftest import JORDAN_RESUME_TEXT, seed_own_resume

from app.db import get_connection, new_id
from app.repositories.story import StoryRepository


STORY_MARKER = "Kookaburras platform migration"


class _RecordingLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.prompts.append(user)
        return {
            "subject": "Introduction",
            "body": (
                "Hello Sarah, I am writing from the experience recorded on my "
                "résumé. Could we have a short conversation?"
            ),
        }


def _seed_contact(user_id: str) -> str:
    contact_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Contact" ("id","userId","name","title","company",'
                '"email","createdAt","updatedAt")'
                " VALUES (%s,%s,%s,%s,%s,%s,now(),now())",
                (
                    contact_id,
                    user_id,
                    "Sarah Chen",
                    "Talent Partner",
                    "Atlassian",
                    "sarah.chen@example.com",
                ),
            )
        conn.commit()
    return contact_id


def _seed_story(user_id: str) -> None:
    StoryRepository().create(
        user_id,
        {
            "title": STORY_MARKER,
            "situation": "The Kookaburras estate ran on fragile virtual machines.",
            "task": "Lead the migration to a container platform.",
            "action": "Rebuilt the Kookaburras deployment pipeline in Rundeck.",
            "result": "Release reliability improved by 40 percent.",
            "tags": ["platform", "migration"],
            "metrics": {"reliability": "+40%"},
        },
    )


def test_recruiter_outreach_prompt_includes_banked_stories(client, auth_headers):
    from app.agents.recruiter_outreach_agent import RecruiterOutreachAgent
    from app.repositories.billing import ensure_user_billing
    from app.security import decode_access_token

    user_id = decode_access_token(auth_headers["Authorization"].removeprefix("Bearer "))[
        "userId"
    ]
    ensure_user_billing(user_id)
    seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    contact_id = _seed_contact(user_id)
    _seed_story(user_id)
    llm = _RecordingLLM()

    RecruiterOutreachAgent(llm=llm).run(user_id, contact_id=contact_id)

    assert llm.prompts, "the agent never called the model"
    assert STORY_MARKER in llm.prompts[0]


def test_reference_prompt_includes_banked_stories(client, auth_headers):
    from app.agents.reference_agent import ReferenceAgent
    from app.repositories.billing import ensure_user_billing
    from app.security import decode_access_token

    user_id = decode_access_token(auth_headers["Authorization"].removeprefix("Bearer "))[
        "userId"
    ]
    ensure_user_billing(user_id)
    seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    contact_id = _seed_contact(user_id)
    _seed_story(user_id)
    llm = _RecordingLLM()

    ReferenceAgent(llm=llm).run(user_id, contact_id=contact_id)

    assert llm.prompts, "the agent never called the model"
    assert STORY_MARKER in llm.prompts[0]
