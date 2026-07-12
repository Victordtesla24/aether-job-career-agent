"""AGT-STORY — Story Bank display enrichment + stats + starred persistence.

The Story Bank screen needs derived display attributes (category, impact,
starred) and an aggregate stats endpoint, all computed from the persisted row.
Invented display metrics (voice match, usage counts) were removed — the API
must NOT return them, and the impact badge may only derive from metrics that
are actually percentages. ``starred`` is the one mutable display flag and is
persisted inside the ``metrics`` JSON under a reserved key.
"""
from __future__ import annotations

FABRICATED_KEYS = ("voiceMatch", "usedInResumes", "interviewAnswers", "usedThisMonth")


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
        for key in ("category", "impact", "starred"):
            assert key in story, f"missing enrichment key {key}"
        assert story["category"] in {"Delivery", "Leadership", "Technical", "Risk & Compliance"}
        assert story["impact"] == "92% impact"
        assert story["starred"] is False

    def test_no_fabricated_display_metrics(self, client, auth_headers):
        """Voice match / usage counts had no data source — they must be gone."""
        _make_story(client, auth_headers)
        story = client.get("/stories", headers=auth_headers).json()[0]
        for key in FABRICATED_KEYS:
            assert key not in story, f"fabricated metric {key} leaked back into the API"

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

    def test_impact_ignores_non_percent_metrics(self, client, auth_headers):
        """A $5M or 75-hour metric must never render as 'N% impact'."""
        story = _make_story(
            client,
            auth_headers,
            title="Recovered an infeasible SIT window",
            metrics={"portfolio_value": "$5M", "sit_window_hours": "75"},
        )
        assert story["impact"] is None

    def test_stats_endpoint(self, client, auth_headers):
        _make_story(client, auth_headers)
        _make_story(client, auth_headers, title="No-metric story", metrics={})
        stats = client.get("/stories/stats", headers=auth_headers).json()
        assert stats["total"] >= 2
        assert stats["quantified"] >= 1  # at least the metric-bearing story
        assert stats["starred"] == 0
        assert stats["categories"] >= 1
        for key in ("usedThisMonth", "voiceMatchAvg"):
            assert key not in stats, f"fabricated stat {key} leaked back into the API"

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
