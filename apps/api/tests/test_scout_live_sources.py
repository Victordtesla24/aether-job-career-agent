"""Real job discovery — live-source adapters, relevance filter, dedupe, submit.

Phase-2 audit defect D11: the scout only ever produced demo-seeded jobs. These
tests cover the new keyless live sources (Greenhouse, Lever, Remotive,
RemoteOK). All adapter tests run in fixture mode — no live HTTP in tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "http"

LIVE_SOURCES = ("greenhouse", "lever", "remotive", "remoteok")


def _load_fixture(source: str) -> dict:
    return json.loads((FIXTURE_DIR / source / "jobs.json").read_text())


def _adapter(source: str):
    from app.services.discovery.adapter_registry import get_adapter_class

    return get_adapter_class(source)


class TestLiveSourceAdapters:
    @pytest.mark.parametrize("source", LIVE_SOURCES)
    def test_registry_knows_live_sources(self, source):
        from app.services.discovery.base_adapter import BaseAdapter

        assert issubclass(_adapter(source), BaseAdapter)

    @pytest.mark.parametrize("source", LIVE_SOURCES)
    def test_adapter_yields_real_relevant_jobs(self, source):
        jobs = _adapter(source)(fixture=_load_fixture(source)).fetch(
            query="delivery lead, product owner, business analyst",
            location="Melbourne, Australia",
        )
        assert len(jobs) >= 1
        for job in jobs:
            assert job["source"] == source
            # Real, absolute apply URL — never a demo/fabricated one.
            assert job["sourceUrl"].startswith("http")
            assert "demo.aether.dev" not in job["sourceUrl"]
            assert job["title"].strip()
            assert job["company"].strip()
            assert isinstance(job["remote"], bool)
            assert isinstance(job["description"], str)

    @pytest.mark.parametrize("source", LIVE_SOURCES)
    def test_adapter_filters_out_irrelevant_roles(self, source):
        """Each fixture includes engineering/blocked-region noise to drop."""
        jobs = _adapter(source)(fixture=_load_fixture(source)).fetch(
            query="delivery lead", location="Melbourne, Australia"
        )
        for job in jobs:
            assert "engineer" not in job["title"].lower()


class TestRelevance:
    def test_target_roles_match(self):
        from app.services.discovery.relevance import is_target_role

        for title in (
            "Senior Technical Delivery Lead",
            "Product Owner",
            "Lead Business Analyst",
            "Program Manager, Intake & Portfolio Management",
            "Scrum Master",
            "Agile Coach",
            "Technical Program Manager",
        ):
            assert is_target_role(title), title

    def test_non_target_roles_rejected(self):
        from app.services.discovery.relevance import is_target_role

        for title in (
            "Senior Software Engineer",
            "Staff Backend Engineer",
            "Account Executive",
            "Data Scientist",
        ):
            assert not is_target_role(title), title

    def test_location_scoring(self):
        from app.services.discovery.relevance import location_score

        assert location_score("Melbourne, Australia", remote=False) == 2
        assert location_score("Sydney NSW", remote=False) == 2
        assert location_score("Remote", remote=True) == 1
        # Region-locked remote roles are dropped for an AU candidate.
        assert location_score("Remote - US only", remote=True) == 0
        assert location_score("London, UK", remote=False) == 0

    def test_snippet_strips_html_and_truncates(self):
        from app.services.discovery.relevance import snippet

        text = snippet("<p>Lead the &amp; delivery.</p>" + "x" * 1000)
        assert "<p>" not in text
        assert "&amp;" not in text
        assert "Lead the & delivery." in text
        assert len(text) <= 501  # 500 chars + ellipsis


class TestScoutDedupe:
    def test_cross_source_duplicates_persisted_once(self, monkeypatch):
        from app.agents import scout_agent as module

        job = {
            "title": "Delivery Lead",
            "company": "Acme",
            "location": "Melbourne",
            "remote": False,
            "description": "Lead delivery.",
            "requirements": [],
            "source": "a",
            "sourceUrl": "https://acme.example/jobs/1",
            "postedAt": None,
        }

        class FakeAdapter:
            def fetch(self, query: str, location: str):
                return [dict(job), dict(job)]  # duplicate within one source

        class FakeRepo:
            def __init__(self) -> None:
                self.created: list[dict] = []

            def create(self, user_id: str, payload: dict) -> None:
                self.created.append(payload)

        monkeypatch.setattr(
            module, "ADAPTERS", {"a": FakeAdapter, "b": FakeAdapter}
        )
        repo = FakeRepo()
        result = module.ScoutAgent(repository=repo).run(
            "user-1", query="delivery lead", location="Melbourne"
        )
        assert result.persisted == 1
        assert len(repo.created) == 1

    def test_upsert_refresh_counts_as_updated_not_persisted(self, monkeypatch):
        """A re-discovered job (upsert hit an existing row) must not be
        reported as a new discovery — the dashboard feed renders ``persisted``
        as "discovered N new roles"."""
        from app.agents import scout_agent as module

        class FakeAdapter:
            def fetch(self, query: str, location: str):
                return [
                    {
                        "title": "Delivery Lead",
                        "company": "Acme",
                        "location": "Melbourne",
                        "remote": False,
                        "description": "Lead delivery.",
                        "requirements": [],
                        "source": "a",
                        "sourceUrl": "https://acme.example/jobs/1",
                        "postedAt": None,
                    },
                    {
                        "title": "Program Manager",
                        "company": "Beta",
                        "location": "Melbourne",
                        "remote": False,
                        "description": "Run programs.",
                        "requirements": [],
                        "source": "a",
                        "sourceUrl": "https://beta.example/jobs/2",
                        "postedAt": None,
                    },
                ]

        class FakeRepo:
            def create(self, user_id: str, payload: dict) -> dict:
                # First URL already exists (upsert refresh), second is new.
                inserted = payload["sourceUrl"].endswith("/jobs/2")
                return {**payload, "wasInserted": inserted}

        monkeypatch.setattr(module, "ADAPTERS", {"a": FakeAdapter})
        result = module.ScoutAgent(repository=FakeRepo()).run(
            "user-1", query="delivery lead", location="Melbourne"
        )
        assert result.persisted == 1
        assert result.updated == 1


class TestApplicationSubmit:
    def _seed_draft_application(self, client, auth_headers) -> str:
        run = client.post(
            "/agents/scout/run",
            json={"query": "delivery lead", "location": "Melbourne"},
            headers=auth_headers,
        )
        assert run.status_code == 202
        job = client.get("/jobs", headers=auth_headers).json()[0]
        resp = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["cover_letter_id"]

    def test_submit_marks_application_submitted_with_apply_url(
        self, client, auth_headers
    ):
        app_id = self._seed_draft_application(client, auth_headers)
        before = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert before["status"] == "draft"

        resp = client.post(
            f"/applications/{app_id}/submit",
            json={"applied_url": "https://jobs.example.com/apply/123"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "submitted"
        # Detail exposes the real apply URL for the tracker UI.
        assert "applyUrl" in body

    def test_submit_is_idempotent(self, client, auth_headers):
        app_id = self._seed_draft_application(client, auth_headers)
        first = client.post(
            f"/applications/{app_id}/submit", json={}, headers=auth_headers
        )
        assert first.status_code == 200
        second = client.post(
            f"/applications/{app_id}/submit", json={}, headers=auth_headers
        )
        assert second.status_code == 200
        assert second.json()["status"] == "submitted"

    def test_submit_unknown_application_404(self, client, auth_headers):
        resp = client.post(
            "/applications/does-not-exist/submit", json={}, headers=auth_headers
        )
        assert resp.status_code == 404


class TestTitleRegionLock:
    def test_remote_job_with_region_locked_title_is_dropped(self):
        from app.services.discovery.relevance import is_relevant

        emea = {
            "title": "Engagement Manager - EMEA",
            "company": "GitLab",
            "location": "Remote",
            "remote": True,
            "description": "",
        }
        assert not is_relevant(emea)
        # But an AU-located job with a region word elsewhere still passes.
        au = {**emea, "title": "Engagement Manager", "location": "Sydney"}
        assert is_relevant(au)
