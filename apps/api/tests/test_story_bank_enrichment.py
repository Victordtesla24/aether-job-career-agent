"""AGT-STORY — Story Bank display enrichment + stats + starred persistence.

The Story Bank screen needs derived display attributes (category, impact,
voice-match, usage) and an aggregate stats endpoint. These are computed from the
persisted row (stable, never mock). ``starred`` is the one mutable display flag
and is persisted inside the ``metrics`` JSON under a reserved key.
"""
from __future__ import annotations


def _make_story(client, auth_headers, **overrides) -> dict:
    payload = {
        "title": "Reduced ATO test automation effort by 92%",
        "situation": "Manual regression suite, ~3 weeks per release.",
        "task": "Lead automation strategy across 5 squads.",
        "action": "Built a CI-driven framework and upskilled 40 engineers.",
        "result": "92% effort reduction, releases cut to 2 days.",
        "metrics": {"effortReductionPercent": 92},
        "tags": ["Delivery", "Automation"],
    }
    payload.update(overrides)
    resp = client.post("/stories", json=payload, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestStoryEnrichment:
    def test_list_stories_are_enriched(self, client, auth_headers):
        _make_story(client, auth_headers)
        stories = client.get("/stories", headers=auth_headers).json()
        assert stories
        story = stories[0]
        for key in (
            "category",
            "impact",
            "voiceMatch",
            "usedInResumes",
            "interviewAnswers",
            "starred",
        ):
            assert key in story, f"missing enrichment key {key}"
        assert story["category"] in {"Delivery", "Leadership", "Technical", "Risk & Compliance"}
        assert 85 <= story["voiceMatch"] <= 98
        assert story["impact"] == "92% impact"
        assert story["starred"] is False

    def test_category_and_impact_derivation(self, client, auth_headers):
        risk = _make_story(
            client,
            auth_headers,
            title="Led risk & compliance uplift at NAB",
            tags=["Risk", "Compliance"],
            metrics={"adherencePercent": 100},
        )
        # Enrichment is on the create response too.
        assert risk["category"] == "Risk & Compliance"
        assert risk["impact"] == "100% impact"

    def test_enrichment_is_stable_across_requests(self, client, auth_headers):
        _make_story(client, auth_headers)
        first = client.get("/stories", headers=auth_headers).json()[0]
        second = client.get("/stories", headers=auth_headers).json()[0]
        assert first["voiceMatch"] == second["voiceMatch"]
        assert first["usedInResumes"] == second["usedInResumes"]

    def test_stats_endpoint(self, client, auth_headers):
        _make_story(client, auth_headers)
        _make_story(client, auth_headers, title="No-metric story", metrics={})
        stats = client.get("/stories/stats", headers=auth_headers).json()
        assert stats["total"] >= 2
        assert stats["quantified"] >= 1  # at least the metric-bearing story
        assert 0 <= stats["voiceMatchAvg"] <= 100
        assert "usedThisMonth" in stats

    def test_star_persists_via_metrics(self, client, auth_headers):
        story = _make_story(client, auth_headers)
        story_id = story["id"]
        # Toggle star on by writing the reserved control key into metrics.
        merged = {**story["metrics"], "__starred": True}
        updated = client.put(
            f"/stories/{story_id}", json={"metrics": merged}, headers=auth_headers
        )
        assert updated.status_code == 200
        assert updated.json()["starred"] is True
        # Control flag must not leak into the exposed evidence metrics.
        assert "__starred" not in updated.json()["metrics"]
        # Survives a fresh read.
        again = client.get("/stories", headers=auth_headers).json()
        starred = next(s for s in again if s["id"] == story_id)
        assert starred["starred"] is True
        assert "__starred" not in starred["metrics"]
        # Evidence metric preserved.
        assert starred["metrics"].get("effortReductionPercent") == 92
