"""STORY-NARRATIVE-GROUNDING-2026-08-03 — the guard must inspect the PROSE.

WHY (audited live on the production DB, user ``sarkar.vikram@gmail.com``)
-----------------------------------------------------------------------
``story_extractor._reject_reason`` validated ONLY the ``metrics`` dict. The
tailoring agent and the cover-letter agent do not read ``metrics``; they read
the STAR prose (``build_story_evidence`` / the cover-letter evidence block).
So every check the Story Bank had was pointed at a field the downstream
consumers ignore.

Measured on the 17 live stories with ``scripts/story_narrative_audit.py``:

* 15 of 17 carried at least one number in situation/task/action/result that
  their OWN cited résumé bullet does not evidence;
* 7 of 17 carried a number that appears NOWHERE in the résumé at all —
  "MTTR from 4.2 hours to 3.8 hours", "234 architectural decisions",
  "120+ regulatory obligations", "37 missing controls". Pure fabrication,
  sitting in the evidence pool that writes the user's cover letters.

The organisation check had the same shape of hole: ``organisation.lower() not
in resume_lower`` is a substring test over the WHOLE résumé, so any employer
the candidate ever had (or any word inside one) "evidences" any bullet. Live,
the Independent-consulting LLM-evaluation project carried the tag
``Australian Taxation Office (ATO)``.

WHAT THIS SUITE PINS
--------------------
1. Each extracted bullet knows the EMPLOYER(S) whose résumé section contains
   it, and the organisation check is bound to that — not to the whole résumé.
2. A number in the narrative that appears nowhere in the résumé is
   FABRICATION: the story is rejected outright.
3. A number in the narrative that is real but belongs to a DIFFERENT bullet is
   BORROWED: the sentence carrying it is stripped, and the story is rejected
   if what is left is too thin to be usable.
4. A title cannot be stripped sentence-wise, so an unevidenced number in the
   title rejects the story.
5. None of this may reject a story whose prose is genuinely evidenced by its
   own bullet.

Every rule here TIGHTENS the anti-fabrication guard. Nothing in this file
permits a claim the user's own résumé does not already make.

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock ./scripts/run-tests.sh \
        tests/test_story_narrative_grounding.py -q -p no:randomly
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.db import get_connection
from app.repositories.story import StoryRepository

#: Two employers, each with a real date range, in the layout a PDF text dump
#: actually produces: role line, employer line, date range, location, then the
#: bullets, with heading/skill blocks interleaved between the groups.
RESUME_TEXT = """VIKRAM
DESHPANDE
CONTACT INFO
someone@example.com
WORK EXPERIENCE
Scrum Master / Project Manager
Australian Taxation Office (ATO)
March 2026 - Present
Melbourne, VIC
•
Test Automation Strategy: Architected the program's COBOL/mainframe test-
evidence automation covering 200+ SIT/E2E scenarios across all eight squads,
cutting evidence effort from ~3 hours to ~15 minutes per scenario (≈92% reduction)
with a zero-new-approvals toolchain.
•
Delivery Recovery: Converted a mathematically infeasible SIT window — 75+ hours
of manual evidence per team against 64 available hours — into an achievable plan
through a six-day tiered harness build with a formal go/no-go gate.
•
SKILLS
Senior Delivery Lead / Technical Product Owner
ANZ
Sept 2017 - June 2025
Melbourne, VIC
•
Delivery Leadership: Directed a program portfolio valued at over $5M, leading 5+
cross-functional squads (up to 40 resources, including offshore teams) to deliver
on-time, high-quality releases.
•
"""


def _bullets() -> list[dict[str, Any]]:
    from app.services.resume_bullets import extract_resume_bullets

    return extract_resume_bullets(RESUME_TEXT)


# ---------------------------------------------------------------------------
# 1. The cited bullet knows its own employer
# ---------------------------------------------------------------------------


class TestBulletEmployerBinding:
    def test_each_bullet_carries_the_employer_of_its_own_section(self) -> None:
        bullets = _bullets()
        assert [b["id"] for b in bullets] == ["B1", "B2", "B3"], bullets
        assert bullets[0]["employers"] == ["Australian Taxation Office (ATO)"]
        assert bullets[1]["employers"] == ["Australian Taxation Office (ATO)"]
        assert bullets[2]["employers"] == ["ANZ"]

    def test_employer_headers_are_read_from_the_date_ranges(self) -> None:
        from app.services.resume_bullets import resume_employers

        assert resume_employers(RESUME_TEXT) == [
            "Australian Taxation Office (ATO)",
            "ANZ",
        ]

    def test_a_resume_with_no_date_ranges_binds_no_employer(self) -> None:
        """Honest degradation: when the layout gives no employer structure the
        bullets say so (empty list) rather than guessing an employer."""
        from app.services.resume_bullets import extract_resume_bullets

        text = "WORK EXPERIENCE\nAcme\n•\n" + (
            "Built a deployment pipeline for the whole platform team so that "
            "releases stopped needing a manual approval step.\n•\n"
        )
        bullets = extract_resume_bullets(text)
        assert bullets and bullets[0]["employers"] == []


# ---------------------------------------------------------------------------
# 2-5. The extractor guard, pointed at the prose
# ---------------------------------------------------------------------------


class _StubLLM:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.user_prompt = ""

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        self.user_prompt = user
        return self._payload


def _story(**over: Any) -> dict[str, Any]:
    """A story that is FULLY evidenced by bullet B1 — the control case."""
    story = {
        "sourceBulletId": "B1",
        "organisation": "Australian Taxation Office (ATO)",
        "title": "COBOL/mainframe test-evidence automation across eight squads",
        "situation": (
            "Eight squads on the program each produced SIT and E2E test evidence "
            "by hand for a COBOL/mainframe estate, and the manual effort made the "
            "planned test window impossible to hold."
        ),
        "task": (
            "I owned the program's test automation strategy and had to remove the "
            "manual evidence bottleneck without buying new tooling or waiting on "
            "any new approvals."
        ),
        "action": (
            "I architected an evidence-automation harness covering 200+ SIT/E2E "
            "scenarios across all eight squads, built entirely on the "
            "zero-new-approvals toolchain already licensed on the mainframe."
        ),
        "result": (
            "Evidence effort per scenario fell from roughly 3 hours to roughly 15 "
            "minutes — a 92% reduction — and all eight squads adopted the harness."
        ),
        "metrics": {"Evidence effort per scenario": "3 hours to 15 minutes", "Reduction": "92%"},
        "tags": ["test-automation", "mainframe"],
    }
    story.update(over)
    return story


@pytest.fixture()
def extractor(monkeypatch: pytest.MonkeyPatch):
    from app.agents import story_extractor as module

    def build(stories: list[dict[str, Any]]):
        monkeypatch.setattr(
            module.StoryExtractorAgent,
            "_resolve_resume_text",
            staticmethod(lambda _user_id: RESUME_TEXT),
        )
        llm = _StubLLM({"stories": stories})
        return module.StoryExtractorAgent(llm=llm), llm

    return build


@pytest.fixture()
def user_id():
    uid = f"t{uuid.uuid4().hex[:24]}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","name","updatedAt")'
                " VALUES (%s,%s,%s,%s,NOW())",
                (uid, f"{uid}@story-narrative.test", "x", "Story Narrative"),
            )
        conn.commit()
    yield uid
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (uid,))
        conn.commit()


class TestNarrativeGrounding:
    def test_fully_evidenced_story_still_passes(self, extractor, user_id) -> None:
        """The guard must not reject prose the cited bullet DOES evidence."""
        agent, _ = extractor([_story()])
        result = agent.run(user_id)
        assert result.created == 1, result.dropped

    def test_narrative_number_absent_from_the_whole_resume_is_rejected(
        self, extractor, user_id
    ) -> None:
        """The live failure: "reduced MTTR from 4.2 hours to 3.8 hours" —
        numbers the résumé states nowhere, in the prose the cover-letter agent
        quotes. The metrics dict was clean, so the old guard passed it."""
        agent, _ = extractor(
            [
                _story(
                    result=(
                        "Evidence effort per scenario fell from roughly 3 hours to "
                        "roughly 15 minutes, and defect leakage into UAT dropped by "
                        "47% across the eight squads over the same window."
                    )
                )
            ]
        )
        result = agent.run(user_id)
        assert result.created == 0, result.dropped
        assert any("47" in reason for reason in result.dropped), result.dropped

    def test_narrative_number_from_a_different_bullet_is_stripped(
        self, extractor, user_id
    ) -> None:
        """64 and 75 are REAL — they belong to bullet B2, not to B1. The
        sentence carrying them is removed; the evidenced remainder survives."""
        agent, _ = extractor(
            [
                _story(
                    situation=(
                        "Eight squads on the program each produced SIT and E2E test "
                        "evidence by hand for a COBOL/mainframe estate. The window "
                        "demanded 75 hours of manual evidence per team against only "
                        "64 available hours, which no amount of overtime could close."
                    )
                )
            ]
        )
        result = agent.run(user_id)
        assert result.created == 1, result.dropped
        row = StoryRepository().get_by_id(result.story_ids[0], user_id)
        assert row is not None
        assert "64" not in row["situation"] and "75" not in row["situation"]
        assert "COBOL/mainframe estate" in row["situation"]
        assert any("64" in note or "75" in note for note in result.stripped), result.stripped

    def test_story_is_rejected_when_stripping_guts_a_field(
        self, extractor, user_id
    ) -> None:
        agent, _ = extractor(
            [
                _story(
                    task=(
                        "I had to close a gap of 75 hours of manual evidence per "
                        "team against the 64 hours the window actually allowed."
                    )
                )
            ]
        )
        result = agent.run(user_id)
        assert result.created == 0, result.dropped
        assert any("task" in reason for reason in result.dropped), result.dropped

    def test_unevidenced_number_in_the_title_rejects_the_story(
        self, extractor, user_id
    ) -> None:
        """A title is one unit — there is no sentence to strip, so a borrowed
        number there is fatal."""
        agent, _ = extractor(
            [_story(title="Closing a 75-hour SIT evidence gap for eight squads")]
        )
        result = agent.run(user_id)
        assert result.created == 0, result.dropped
        assert any("title" in reason for reason in result.dropped), result.dropped


class TestRemediationVerdicts:
    """``scripts/story_narrative_audit.py`` must classify a STORED row exactly
    the way the live guard classifies a generated one — otherwise remediation
    leaves the bank in a state the extractor would refuse to produce."""

    @staticmethod
    def _row(**over: Any) -> dict[str, Any]:
        story = _story()
        row = {
            "id": "row-1",
            "title": story["title"],
            "situation": story["situation"],
            "task": story["task"],
            "action": story["action"],
            "result": story["result"],
            "metrics": story["metrics"],
            "tags": ["test-automation", "Australian Taxation Office (ATO)"],
        }
        row.update(over)
        return row

    @staticmethod
    def _finding(row: dict[str, Any]) -> dict[str, Any]:
        from scripts.story_narrative_audit import _finding
        from app.services.resume_bullets import bullet_numbers, resume_employers

        bullet = _bullets()[0]
        return _finding(
            row, bullet, bullet_numbers(RESUME_TEXT), resume_employers(RESUME_TEXT)
        )

    def test_a_grounded_row_is_left_alone(self) -> None:
        assert self._finding(self._row())["verdict"] == "clean"

    def test_a_row_with_an_invented_number_is_archived(self) -> None:
        finding = self._finding(
            self._row(
                result=(
                    "Evidence effort fell from roughly 3 hours to roughly 15 "
                    "minutes and defect leakage dropped by 47% for the squads."
                )
            )
        )
        assert finding["verdict"] == "archive"
        assert finding["fabricated"] == {"result": ["47"]}

    def test_a_row_with_a_borrowed_number_is_stripped(self) -> None:
        finding = self._finding(
            self._row(
                situation=(
                    "Eight squads on the program each produced SIT and E2E test "
                    "evidence by hand for a COBOL/mainframe estate. The window "
                    "demanded 75 hours of manual evidence per team against only "
                    "64 available hours, which no overtime could close."
                )
            )
        )
        assert finding["verdict"] == "strip"
        assert finding["borrowed"] == {"situation": ["75", "64"]}
        assert not finding["fabricated"]

    def test_a_tag_naming_another_employer_is_flagged(self) -> None:
        finding = self._finding(self._row(tags=["mainframe", "ANZ"]))
        assert finding["foreign_employer_tags"] == ["ANZ"]
        assert finding["verdict"] == "strip"

    def test_an_unevidenced_metric_is_flagged(self) -> None:
        finding = self._finding(self._row(metrics={"Reduction": "92%", "Uptime": "99%"}))
        assert finding["unevidenced_metrics"] == {"Uptime": ["99"]}
        assert finding["verdict"] == "strip"


class TestOrganisationBinding:
    def test_organisation_of_a_different_employer_is_rejected(
        self, extractor, user_id
    ) -> None:
        """ANZ is a real employer on this résumé — but not for bullet B1. The
        whole-résumé substring check accepted exactly this."""
        agent, _ = extractor([_story(organisation="ANZ")])
        result = agent.run(user_id)
        assert result.created == 0, result.dropped
        assert any("ANZ" in reason for reason in result.dropped), result.dropped

    def test_the_bullets_own_employer_is_accepted_by_short_name(
        self, extractor, user_id
    ) -> None:
        agent, _ = extractor([_story(organisation="ATO")])
        result = agent.run(user_id)
        assert result.created == 1, result.dropped

    def test_an_organisation_absent_from_the_resume_is_still_rejected(
        self, extractor, user_id
    ) -> None:
        agent, _ = extractor([_story(organisation="Globex Corporation")])
        result = agent.run(user_id)
        assert result.created == 0, result.dropped
        assert any("Globex" in reason for reason in result.dropped), result.dropped
