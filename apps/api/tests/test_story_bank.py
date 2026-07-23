"""P2-S09 — Story bank tests (STAR extraction + evidence-backed metrics)."""
from __future__ import annotations

import re

from conftest import seed_own_resume

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import parse_resume_pdf

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

STAR_FIELDS = ("title", "situation", "task", "action", "result")


def _extract(client, auth_headers) -> list[dict]:
    # Story extraction grounds ONLY on the CALLING user's own résumé, never
    # the operator's bundled one (ML-audit-story-leak-001) — a user with no
    # résumé of their own now honestly extracts zero stories. Seed the test
    # user their OWN copy of the base résumé (the very corpus the
    # metrics-not-invented assertion below validates against) via the
    # established per-user seeding helper before running extraction.
    seed_own_resume(
        client, auth_headers,
        raw_text=parse_resume_pdf(get_base_resume_path())["raw_text"],
    )
    resp = client.post("/agents/story-extractor/run", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] >= 1
    return client.get("/stories", headers=auth_headers).json()


class TestStoryBank:
    def test_story_extraction_produces_star_structure(self, client, auth_headers):
        stories = _extract(client, auth_headers)
        assert stories
        for story in stories:
            for field in STAR_FIELDS:
                assert story[field] and isinstance(story[field], str)
            assert isinstance(story["tags"], list)

    def test_story_metrics_not_invented(self, client, auth_headers):
        stories = _extract(client, auth_headers)
        resume_numbers = set(
            _NUMBER_RE.findall(parse_resume_pdf(get_base_resume_path())["raw_text"])
        )
        for story in stories:
            for value in (story.get("metrics") or {}).values():
                for number in _NUMBER_RE.findall(str(value)):
                    assert number in resume_numbers, (
                        f"metric number {number} not evidenced in resume"
                    )

    def test_story_crud(self, client, auth_headers):
        created = client.post(
            "/stories",
            json={
                "title": "Manual story",
                "situation": "S",
                "task": "T",
                "action": "A",
                "result": "R",
                "tags": ["manual"],
            },
            headers=auth_headers,
        )
        assert created.status_code == 201
        story_id = created.json()["id"]

        updated = client.put(
            f"/stories/{story_id}", json={"title": "Renamed"}, headers=auth_headers
        )
        assert updated.status_code == 200
        assert updated.json()["title"] == "Renamed"

        deleted = client.delete(f"/stories/{story_id}", headers=auth_headers)
        assert deleted.status_code == 204
        remaining = client.get("/stories", headers=auth_headers).json()
        assert all(s["id"] != story_id for s in remaining)
