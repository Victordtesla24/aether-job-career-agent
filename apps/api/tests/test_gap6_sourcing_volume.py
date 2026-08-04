"""GAP-SRC-001 (gate 6) — profile-driven role-family query + portal expansion.

Fixes two volume-starving defects in the otherwise-live multi-board scout
(GAP-SRC-001/002/003, main HEAD 8c7e2da):

1. The scout query was effectively a single narrow title (the profile's
   literal ``targetRole``, "Senior Technical Program Manager") rather than
   the user's whole target role family — starving Seek/Wellfound's
   keyword-searchable results. ``query_builder.build_scout_query`` derives a
   multi-term, role-family query instead (while leaving relevance filtering,
   which decides what actually reaches the UI, untouched).
2. The curated per-company portal token lists (Greenhouse/Lever/Ashby/
   Workable) were thin. Every added token below was curled live against the
   provider's public API before being added — see ``portals.py`` docstrings
   for the per-token verification notes.

All tests here are pure/offline (no live HTTP) except where noted.
"""
from __future__ import annotations

FIXTURE_DIR = None  # not needed — this module doesn't hit fixtures/http


class TestBuildScoutQuery:
    def test_no_target_role_refuses_instead_of_inventing_one(self):
        """SUPERSEDED BY F-02 (was: "returns the full role family").

        Returning ``ROLE_FAMILY_QUERY`` for a caller with no target role is the
        substitution F-02 removed — it is how a user whose profile said nothing
        received project-management postings. The honest refusal now lives at
        the route layer (``agents.py::_resolve_scout_target`` -> 422), so an
        empty role reaching this pure function is a programming error. The
        GAP-SRC-001 behaviour this suite exists for — broadening a role the
        user DOES have — is unchanged and still asserted below.
        """
        import pytest

        from app.services.discovery.query_builder import build_scout_query

        with pytest.raises(ValueError, match="target role"):
            build_scout_query(None)

    def test_blank_target_role_refuses_the_same_way(self):
        import pytest

        from app.services.discovery.query_builder import build_scout_query

        with pytest.raises(ValueError, match="target role"):
            build_scout_query("   ")

    def test_family_member_target_role_is_broadened_not_replaced(self):
        """The bug: a profile targetRole of a single narrow title (this
        user's real saved value) must not stay a single-term query — it
        should broaden to the whole role family while keeping the user's
        own wording first."""
        from app.services.discovery.query_builder import (
            ROLE_FAMILY_TERMS,
            build_scout_query,
        )

        query = build_scout_query("Senior Technical Program Manager")
        terms = [t.strip() for t in query.split(",")]
        assert terms[0] == "Senior Technical Program Manager"
        lowered = query.lower()
        for term in ROLE_FAMILY_TERMS:
            assert term in lowered, f"{term!r} missing from broadened query: {query!r}"

    def test_non_family_target_role_passed_through_unchanged(self):
        """A future user targeting something outside this family gets their
        own profile value verbatim — this module never invents a query for
        a role nobody asked for."""
        from app.services.discovery.query_builder import build_scout_query

        assert build_scout_query("Senior Software Engineer") == "Senior Software Engineer"

    def test_already_broad_query_is_not_duplicated(self):
        from app.services.discovery.query_builder import (
            ROLE_FAMILY_QUERY,
            build_scout_query,
        )

        query = build_scout_query(ROLE_FAMILY_QUERY)
        terms = [t.strip().lower() for t in query.split(",")]
        assert len(terms) == len(set(terms)), f"duplicate terms in {query!r}"


class TestPortalsVolume:
    """The per-company portal lists are well-formed, non-empty, and every
    token is unique within its list (dedup — no accidental repeats when the
    list grows)."""

    def test_all_board_lists_well_formed_and_non_empty(self):
        from app.services.discovery import portals

        for boards in (
            portals.greenhouse_boards(),
            portals.lever_companies(),
            portals.ashby_boards(),
            portals.workable_accounts(),
        ):
            assert len(boards) >= 3
            assert all(isinstance(t, str) and t.strip() for t in boards)
            assert len(boards) == len(set(boards)), f"duplicate token in {boards!r}"

    def test_gate6_volume_tokens_present(self):
        """Anchors the gate-6 expansion: every token asserted here was
        curled live (200, real board) against the provider's public API
        before being added — see portals.py docstrings.

        Re-anchored 2026-08-04 (docs/delivery/BACKEND-RED-TESTS-2026-08-03.md
        RULING 2): a live 2026-08-02 re-probe found all five previous
        Workable accounts (veriff, canva, deputy, safetyculture, airwallex)
        returning ZERO jobs, so ``airwallex`` was deliberately removed from
        ``WORKABLE_ACCOUNTS`` (portals.py). It remains a live, verified Ashby
        board token, so the anchor moves there. ``WORKABLE_ACCOUNTS`` is kept
        non-empty with its real, currently-verified members instead of
        pinning the retired token.
        """
        from app.services.discovery import portals

        assert "datadog" in portals.greenhouse_boards()
        assert "mongodb" in portals.greenhouse_boards()
        assert "okta" in portals.greenhouse_boards()
        assert "palantir" in portals.lever_companies()
        assert "openai" in portals.ashby_boards()
        assert "airwallex" in portals.ashby_boards()

        workable = portals.workable_accounts()
        assert workable, "WORKABLE_ACCOUNTS must not be emptied outright"
        for expected in ("propeller", "rokt", "bupa"):
            assert expected in workable, workable


class TestScoutRunBroadensQuery:
    """Integration check on the actual choke point: whatever query
    ``/agents/scout/run`` receives (this is exactly what
    ``scripts/discovery_cron.sh`` sends — the profile's literal, narrow
    ``targetRole``) must reach ``ScoutAgent.run`` already broadened to the
    role family, not passed through verbatim."""

    def test_narrow_profile_title_reaches_scout_agent_broadened(
        self, client, auth_headers, monkeypatch
    ):
        from app.agents import scout_agent as module

        captured: dict[str, str] = {}

        class _RecordingScoutAgent:
            def run(self, user_id, query, location):
                captured["query"] = query
                captured["location"] = location
                return module.ScoutResult()

        monkeypatch.setattr("app.routers.agents.ScoutAgent", _RecordingScoutAgent)

        response = client.post(
            "/agents/scout/run",
            json={"query": "Senior Technical Program Manager", "location": "Melbourne, AU"},
            headers=auth_headers,
        )
        assert response.status_code == 202, response.text

        assert captured["query"] != "Senior Technical Program Manager"
        assert captured["query"].startswith("Senior Technical Program Manager,")
        for term in ("business analyst", "product owner", "scrum master", "agile coach"):
            assert term in captured["query"].lower()


class TestSeekRelevanceFilterApplied:
    """RED before this fix: SeekAdapter._parse returned every Seek result
    unfiltered, relying solely on Seek's own fuzzy keyword search to be
    on-target. Broadening the query (GAP-SRC-001 above) makes that upstream
    fuzziness a real flood risk, so Seek must run the same
    ``relevance.filter_relevant`` every other live adapter already applies."""

    def test_seek_drops_irrelevant_titles_even_when_upstream_returns_them(self):
        from app.services.discovery.base_adapter import JobRaw
        from app.services.discovery.seek_adapter import SeekAdapter

        payload = {
            "data": [
                {
                    "title": "Senior Software Engineer",
                    "company": "Acme",
                    "location": "Melbourne VIC",
                    "sourceUrl": "https://www.seek.com.au/job/1",
                },
                {
                    "title": "Senior Business Analyst",
                    "company": "Real Employer",
                    "location": "Melbourne VIC",
                    "sourceUrl": "https://www.seek.com.au/job/2",
                },
            ]
        }
        jobs: list[JobRaw] = SeekAdapter()._parse(payload)
        titles = {j["title"] for j in jobs}
        assert "Senior Business Analyst" in titles
        assert "Senior Software Engineer" not in titles
