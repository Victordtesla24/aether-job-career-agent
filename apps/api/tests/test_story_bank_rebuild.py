"""Story-bank rebuild — REAL, REUSABLE, source-grounded STAR stories.

Audited live on 2026-08-02 (production DB, user ``sarkar.vikram@gmail.com``):
43 live ``StoryEntry`` rows describing only ~10 distinct achievements, i.e. 33
near-duplicate re-tellings, while ~17 genuinely distinct résumé achievements
had NO story at all. Two rows carried no metric whatsoever.

The root cause is that the story extractor had NO stable identity for "the
achievement this story is about". Its only anti-duplicate signals were

* an exact sha256 of the five STAR fields (``contentHash``) — one reworded
  word defeats it, and
* a fuzzy title+achievement Jaccard pair (``story_paraphrase``) whose
  create-time preset needs title Jaccard >= 0.70, which the real production
  duplicates never reach (measured on the live rows: same-achievement pairs
  have a MEDIAN title Jaccard of 0.333).

and its metric guard validated every number against the WHOLE résumé, so a
war-room story could "evidence" a 92% figure that belongs to a completely
different bullet.

This suite pins the replacement contract:

1.  ``app.services.resume_bullets`` splits the user's OWN résumé into the
    discrete achievement bullets it actually contains (deterministic, no LLM).
2.  Every extracted story CITES one of those bullets by id. A story that cites
    an unknown bullet is dropped.
3.  Metric numbers must appear in THE CITED BULLET — not merely somewhere in
    the résumé.
4.  A bullet that contains numbers must yield a QUANTIFIED story; an
    unquantified one is dropped.
5.  Dedup is DETERMINISTIC: the achievement key is a hash of the cited bullet,
    so a reworded re-telling of the same bullet UPDATES the existing row
    instead of inserting a duplicate — regardless of how far the title drifts.
6.  The database enforces (5) with a partial unique index, so no future code
    path can reintroduce a duplicate.

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock ./scripts/run-tests.sh \
        tests/test_story_bank_rebuild.py -v
"""
from __future__ import annotations

import uuid
from typing import Any

import psycopg2
import pytest

from app.db import get_connection
from app.repositories.story import StoryRepository

# A verbatim slice of the real résumé shape this feature must handle: PDF text
# dumps put each bullet marker on its own line, hyphenate across line breaks
# ("test- evidence"), and interleave heading/skill blocks between bullets.
RESUME_TEXT = """VIKRAM
DESHPANDE
CONTACT INFO
someone@example.com
CAREER OBJECTIVE
15+ year Senior Technical Leader specializing in end-to-end program delivery
across the Financial Services sector.
WORK EXPERIENCE
Scrum Master / Project Manager
Australian Taxation Office (ATO)
•
AI/ML Solutions, LLM Pipelines (LangChain, Langfuse), Python, TypeScript,
Kubernetes, Docker, Terraform, GCP/AWS.
•
Test Automation Strategy: Architected the program's COBOL/mainframe test-
evidence automation covering 200+ SIT/E2E scenarios across all eight squads,
cutting evidence effort from ~3 hours to ~15 minutes per scenario (≈92% reduction)
with a zero-new-approvals toolchain.
•
Stakeholder Leadership: Convened a cross-discipline technical war room that
produced a binding automation recommendation in under three hours; unblocked
stalled NTP function testing through L2 environment escalation while steering
Distribution UI delivery to 95%+ completion.
•
"""


def _bullets() -> list[dict[str, str]]:
    from app.services.resume_bullets import extract_resume_bullets

    return extract_resume_bullets(RESUME_TEXT)


# ---------------------------------------------------------------------------
# 1. Deterministic bullet segmentation
# ---------------------------------------------------------------------------


class TestResumeBulletSegmentation:
    def test_yields_only_the_real_achievement_bullets(self) -> None:
        bullets = _bullets()
        texts = [b["text"] for b in bullets]
        assert len(bullets) == 2, texts
        assert any("COBOL/mainframe" in t for t in texts)
        assert any("war room" in t for t in texts)
        # Heading blocks, the contact block and the comma-list of skills are
        # NOT achievements and must never become a story's evidence.
        assert not any("CONTACT INFO" in t for t in texts)
        assert not any("LangChain" in t for t in texts)

    def test_repairs_pdf_line_break_hyphenation(self) -> None:
        text = next(b["text"] for b in _bullets() if "COBOL" in b["text"])
        assert "test-evidence automation" in text
        assert "test- evidence" not in text

    def test_ids_are_stable_and_sequential(self) -> None:
        assert [b["id"] for b in _bullets()] == ["B1", "B2"]
        assert [b["id"] for b in _bullets()] == ["B1", "B2"]

    def test_numbers_are_scoped_to_their_own_bullet(self) -> None:
        from app.services.resume_bullets import bullet_numbers

        cobol = next(b for b in _bullets() if "COBOL" in b["text"])
        war_room = next(b for b in _bullets() if "war room" in b["text"])
        assert "92" in bullet_numbers(cobol["text"])
        # The 92% belongs to the automation bullet ONLY — the war-room bullet
        # must not be able to evidence it.
        assert "92" not in bullet_numbers(war_room["text"])
        assert "95" in bullet_numbers(war_room["text"])

    def test_number_notation_is_evidenced_not_fabricated(self) -> None:
        """Renderings of a number the bullet DOES state must pass; a number it
        does not state must still fail. Both directions were wrong live: the
        guard rejected "10,000" for a bullet saying "10k+" and rejected "3" for
        one saying "three hours" — real stories thrown away as fabrications."""
        from app.services.resume_bullets import bullet_numbers

        assert "10000" in bullet_numbers("telemetry for 10k+ device concurrency")
        assert "3" in bullet_numbers("a recommendation in under three hours")
        assert "5000000" in bullet_numbers("a portfolio valued at over $5M")
        # Still rejects what is genuinely absent.
        assert "70" not in bullet_numbers("a portfolio valued at over $5M")

    def test_identifiers_are_not_quantification(self) -> None:
        """"D3 event arcs" is not a metric. Counting it as one made the
        extractor drop good stories for "carrying no metric" when their source
        bullet had no metric to carry."""
        from app.services.resume_bullets import is_quantified

        assert not is_quantified("Developed a tool featuring D3 event arcs")
        assert not is_quantified("traceability across AC6-AC19 with STT scope")
        assert is_quantified("cutting evidence effort by 92%")

    def test_achievement_key_is_per_user_and_wording_stable(self) -> None:
        from app.services.resume_bullets import achievement_key

        cobol = next(b for b in _bullets() if "COBOL" in b["text"])
        key = achievement_key("user-a", cobol["text"])
        assert key == achievement_key("user-a", cobol["text"])
        # Punctuation/case/whitespace drift in the same bullet is the SAME
        # achievement; a different user is never the same achievement.
        assert key == achievement_key("user-a", cobol["text"].upper() + "  ")
        assert key != achievement_key("user-b", cobol["text"])


# ---------------------------------------------------------------------------
# 2-4. Extraction quality gates
# ---------------------------------------------------------------------------


class _StubLLM:
    """Returns a canned extractor payload; records the user prompt it saw."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.user_prompt = ""

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        self.user_prompt = user
        return self._payload


def _story(**over: Any) -> dict[str, Any]:
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
        "tags": ["test-automation", "mainframe", "delivery"],
    }
    story.update(over)
    return story


@pytest.fixture()
def extractor(monkeypatch: pytest.MonkeyPatch):
    """Factory: build a StoryExtractorAgent whose LLM returns ``stories``."""
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


def _new_user() -> str:
    """A real User row — StoryEntry.userId is a FK."""
    user_id = f"t{uuid.uuid4().hex[:24]}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","name","updatedAt")'
                " VALUES (%s,%s,%s,%s,NOW())",
                (user_id, f"{user_id}@story-rebuild.test", "x", "Story Rebuild"),
            )
        conn.commit()
    return user_id


@pytest.fixture()
def user_id() -> str:
    uid = _new_user()
    yield uid
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (uid,))
        conn.commit()


class TestExtractionQualityGates:
    def test_the_prompt_carries_the_numbered_real_bullets(self, extractor, user_id) -> None:
        agent, llm = extractor([_story()])
        agent.run(user_id)
        assert "B1:" in llm.user_prompt
        assert "COBOL/mainframe test-evidence automation" in llm.user_prompt

    def test_story_citing_an_unknown_bullet_is_dropped(self, extractor, user_id) -> None:
        agent, _ = extractor([_story(sourceBulletId="B99")])
        result = agent.run(user_id)
        assert result.created == 0
        assert any("B99" in reason or "source" in reason.lower() for reason in result.dropped)

    def test_metric_number_from_a_different_bullet_is_rejected(
        self, extractor, user_id
    ) -> None:
        """The whole-résumé metric guard's blind spot: 92% is REAL, but it
        belongs to the automation bullet, not the war-room one."""
        war_room = _story(
            sourceBulletId="B2",
            title="Cross-discipline technical war room unblocking NTP testing",
            situation=(
                "NTP function testing was stalled across the program and no single "
                "discipline owned the blockage, so delivery of the Distribution UI "
                "capability was slipping."
            ),
            task=(
                "I had to produce a binding, cross-discipline recommendation fast "
                "enough that the squads could keep testing in the same week."
            ),
            action=(
                "I convened a cross-discipline technical war room, escalated the "
                "environment issue to L2 and ran targeted SME enablement for the "
                "squads blocked on NTP functions."
            ),
            result=(
                "The war room produced a binding automation recommendation in under "
                "three hours and Distribution UI delivery reached 95%+ completion."
            ),
            metrics={"Effort reduction": "92%"},
        )
        agent, _ = extractor([war_room])
        result = agent.run(user_id)
        assert result.created == 0
        assert any("92" in reason for reason in result.dropped)

    def test_unquantified_story_from_a_quantified_bullet_is_dropped(
        self, extractor, user_id
    ) -> None:
        agent, _ = extractor([_story(metrics={})])
        result = agent.run(user_id)
        assert result.created == 0
        assert any("metric" in reason.lower() for reason in result.dropped)

    def test_thin_star_fields_are_dropped(self, extractor, user_id) -> None:
        agent, _ = extractor([_story(result="Went well.")])
        result = agent.run(user_id)
        assert result.created == 0

    def test_organisation_absent_from_the_resume_is_dropped(
        self, extractor, user_id
    ) -> None:
        agent, _ = extractor([_story(organisation="Globex Corporation")])
        result = agent.run(user_id)
        assert result.created == 0
        assert any("Globex" in reason for reason in result.dropped)

    def test_a_valid_story_is_created_and_carries_its_evidence(
        self, extractor, user_id
    ) -> None:
        from app.services.resume_bullets import achievement_key, extract_resume_bullets

        agent, _ = extractor([_story()])
        result = agent.run(user_id)
        assert result.created == 1, result.dropped
        row = StoryRepository().get_by_id(result.story_ids[0], user_id)
        assert row is not None
        assert row["metrics"]["Reduction"] == "92%"
        bullet = extract_resume_bullets(RESUME_TEXT)[0]
        assert _stored_key(result.story_ids[0]) == achievement_key(user_id, bullet["text"])


def _stored_key(story_id: str) -> str | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "achievementKey" FROM "StoryEntry" WHERE "id" = %s', (story_id,)
            )
            row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 5-6. Deterministic, reusable dedup
# ---------------------------------------------------------------------------


class TestDeterministicDedup:
    def test_reworded_retelling_updates_the_same_row(self, extractor, user_id) -> None:
        """The exact live failure: the same achievement, retold with a drifted
        title, produced a brand-new row on every extractor re-run."""
        agent, _ = extractor([_story()])
        first = agent.run(user_id)
        assert first.created == 1, first.dropped

        reworded = _story(
            title="Slashing SIT evidence effort by 92% with a mainframe harness",
            situation=(
                "Manual SIT and E2E evidence capture across a COBOL estate was "
                "consuming hours per scenario for every one of the eight squads on "
                "the program, putting the test window out of reach."
            ),
            action=(
                "Designed and rolled out a tiered evidence-capture harness spanning "
                "200+ scenarios, reusing only tooling already approved on the "
                "mainframe so nothing needed a new approval."
            ),
            result=(
                "Per-scenario evidence time dropped from about 3 hours to about 15 "
                "minutes, a 92% reduction adopted by all eight squads."
            ),
            tags=["automation", "ato"],
        )
        agent2, _ = extractor([reworded])
        second = agent2.run(user_id)

        live = StoryRepository().list_by_user(user_id)
        assert len(live) == 1, [s["title"] for s in live]
        assert second.story_ids == first.story_ids
        assert live[0]["title"] == reworded["title"]
        assert live[0]["metrics"]["Reduction"] == "92%"
        assert live[0]["tags"] == [
            "automation", "ato", "Australian Taxation Office (ATO)"
        ], live[0]["tags"]

    def test_re_extraction_does_not_accumulate_reworded_metrics(
        self, extractor, user_id
    ) -> None:
        """Live after six extractor runs, ONE story carried 19 metric keys for
        4 facts ("Reduction"/"Effort reduction"/"effort_reduction"/"Reduction
        in effort" all = 92%), because every merge unioned the new wording onto
        the old. The same bullet re-extracted restates the same evidence."""
        agent, _ = extractor([_story()])
        agent.run(user_id)

        renamed = _story(
            metrics={"Effort reduction": "92%", "effort_reduction": "92%"},
            tags=["mainframe"],
        )
        agent2, _ = extractor([renamed])
        agent2.run(user_id)

        row = StoryRepository().list_by_user(user_id)[0]
        assert set(row["metrics"]) == {"Effort reduction", "effort_reduction"}
        # A stale organisation tag from a superseded extraction must not linger.
        assert row["tags"] == ["mainframe", "Australian Taxation Office (ATO)"]

    def test_two_different_bullets_stay_two_stories(self, extractor, user_id) -> None:
        war_room = _story(
            sourceBulletId="B2",
            title="Cross-discipline technical war room unblocking NTP testing",
            situation=(
                "NTP function testing was stalled across the program and no single "
                "discipline owned the blockage, so Distribution UI delivery slipped."
            ),
            task=(
                "I had to produce a binding, cross-discipline recommendation fast "
                "enough that the squads could keep testing in the same week."
            ),
            action=(
                "I convened a cross-discipline technical war room, escalated the "
                "environment issue to L2 and ran targeted SME enablement."
            ),
            result=(
                "A binding automation recommendation landed in under three hours and "
                "Distribution UI delivery reached 95%+ completion."
            ),
            metrics={"Distribution UI completion": "95%"},
        )
        agent, _ = extractor([_story(), war_room])
        result = agent.run(user_id)
        assert result.created == 2, result.dropped
        assert len(StoryRepository().list_by_user(user_id)) == 2

    def test_database_rejects_a_duplicate_live_achievement_key(self, user_id) -> None:
        """The guarantee must not depend on application code remembering to
        check — a second LIVE row with the same key must be impossible."""
        from app.db import ensure_story_achievement_column
        from app.services.resume_bullets import achievement_key

        ensure_story_achievement_column()
        key = achievement_key(user_id, "some real bullet text")
        insert = (
            'INSERT INTO "StoryEntry" ("id","userId","title","situation",'
            '"task","action","result","metrics","tags","achievementKey",'
            '"updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())'
        )

        def _params() -> tuple[Any, ...]:
            return (
                uuid.uuid4().hex[:25], user_id, "t", "s", "t", "a", "r",
                "{}", [], key,
            )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(insert, _params())
                # Postgres rejects the SECOND row at execute time — the index
                # is what stops it, no application check involved.
                with pytest.raises(psycopg2.errors.UniqueViolation):
                    cur.execute(insert, _params())
            conn.rollback()
