"""P2-S02 — job-board adapters, persistence, and the scout agent.

RED first: adapters, JobRepository and the scout endpoint do not exist yet.
Adapters run in fixture mode — no live HTTP is performed in tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "http"


def _load_fixture(source: str) -> dict:
    return json.loads((FIXTURE_DIR / source / "jobs.json").read_text())


def _assert_job_raw_shape(jobs: list[dict], source: str) -> None:
    assert len(jobs) >= 1
    for job in jobs:
        assert job["source"] == source
        assert job["sourceUrl"].startswith("https://")
        assert job["title"].strip()
        assert job["company"].strip()
        assert isinstance(job["remote"], bool)
        assert isinstance(job["description"], str)


class TestAdapters:
    def test_seek_adapter_returns_job_list(self):
        from app.services.discovery.seek_adapter import SeekAdapter

        jobs = SeekAdapter(fixture=_load_fixture("seek")).fetch(
            query="software engineer", location="Sydney"
        )
        _assert_job_raw_shape(jobs, "seek")

    def test_linkedin_adapter_returns_job_list(self):
        from app.services.discovery.linkedin_adapter import LinkedInAdapter

        jobs = LinkedInAdapter(fixture=_load_fixture("linkedin")).fetch(
            query="software engineer", location="Sydney"
        )
        _assert_job_raw_shape(jobs, "linkedin")

    def test_indeed_adapter_returns_job_list(self):
        from app.services.discovery.indeed_adapter import IndeedAdapter

        jobs = IndeedAdapter(fixture=_load_fixture("indeed")).fetch(
            query="software engineer", location="Sydney"
        )
        _assert_job_raw_shape(jobs, "indeed")

    def test_adapter_registry_knows_all_sources(self):
        from app.services.discovery.adapter_registry import get_adapter_class
        from app.services.discovery.base_adapter import BaseAdapter

        for source in ("seek", "linkedin", "indeed"):
            adapter_cls = get_adapter_class(source)
            assert issubclass(adapter_cls, BaseAdapter)


@pytest.fixture()
def current_user_id(client, auth_headers, db_session) -> str:
    """The id of the registered fixture user (auth_headers already truncated)."""
    with db_session.cursor() as cur:
        cur.execute('SELECT "id" FROM "User" LIMIT 1')
        return cur.fetchone()[0]


class TestScoutPersistence:
    SCOUT_PARAMS = {"query": "software engineer", "location": "Sydney"}

    def test_jobs_are_persisted(self, client, auth_headers, current_user_id):
        from app.repositories.job import JobRepository

        response = client.post(
            "/agents/scout/run", json=self.SCOUT_PARAMS, headers=auth_headers
        )
        assert response.status_code == 202, response.text

        jobs = JobRepository().list_by_user(current_user_id)
        assert len(jobs) >= 1
        for job in jobs:
            assert job["status"] == "discovered"
            assert job["fitScore"] is None

    def test_duplicate_sourceUrl_not_persisted_twice(
        self, client, auth_headers, current_user_id
    ):
        from app.repositories.job import JobRepository

        for _ in range(2):
            response = client.post(
                "/agents/scout/run", json=self.SCOUT_PARAMS, headers=auth_headers
            )
            assert response.status_code == 202, response.text

        jobs = JobRepository().list_by_user(current_user_id)
        source_urls = [job["sourceUrl"] for job in jobs]
        assert len(source_urls) == len(set(source_urls)), "duplicate sourceUrls persisted"

    def test_jobs_endpoint_returns_persisted_jobs(
        self, client, auth_headers, current_user_id
    ):
        client.post("/agents/scout/run", json=self.SCOUT_PARAMS, headers=auth_headers)
        response = client.get("/jobs", headers=auth_headers)
        assert response.status_code == 200
        body = response.json()
        assert len(body) >= 1
        assert {"id", "title", "company", "source", "sourceUrl", "status"} <= set(body[0])


class TestSeekApolloParser:
    """Company/location extraction from SEEK's embedded Apollo state."""

    JOB_URL = "https://www.seek.com.au/job/12345678"

    @staticmethod
    def _page(job: dict) -> str:
        blob = {"ROOT_QUERY": {'jobDetails({"id":"12345678"})': {"job": job}}}
        return (
            "<html><body><script>window.SEEK_APOLLO_DATA = "
            + json.dumps(blob)
            + ";</script></body></html>"
        )

    def test_parses_company_location_and_posted_at(self):
        from app.services.discovery.seek_adapter import _parse_job_from_html

        job = self._page(
            {
                "title": "Senior Business Analyst",
                "advertiser": {'name({"locale":"en-AU"})': "Real Employer Pty Ltd"},
                "location": {'label({"locale":"en-AU","type":"LONG"})': "Melbourne VIC"},
                "listedAt": {"dateTimeUtc": "2026-07-02T14:19:09.265Z"},
                'content2({"zone":"anz-1"})': (
                    "<p>Great role.</p><ul><li>8+ years business analysis</li></ul>"
                ),
            }
        )
        parsed = _parse_job_from_html(job, self.JOB_URL)
        assert parsed is not None
        assert parsed["company"] == "Real Employer Pty Ltd"
        assert parsed["location"] == "Melbourne VIC"
        assert parsed["postedAt"] == "2026-07-02T14:19:09.265Z"
        assert parsed["requirements"] == ["8+ years business analysis"]
        assert "Great role." in parsed["description"]
        assert "<p>" not in parsed["description"]

    def test_returns_none_without_apollo_state(self):
        from app.services.discovery.seek_adapter import _parse_job_from_html

        assert _parse_job_from_html("<html><body>plain page</body></html>", self.JOB_URL) is None

    def test_markdown_fallback_strips_links_and_rejects_overlong_company(self):
        from app.services.discovery.seek_adapter import _parse_job_from_markdown

        md = "\n".join(
            [
                "# Delivery Manager",
                "Delivery Manager at " + "X" * 80,
                "[Melbourne VIC](https://au.seek.com/jobs/in-Melbourne-VIC-3000)",
            ]
        )
        parsed = _parse_job_from_markdown(md, self.JOB_URL)
        assert parsed is not None
        assert parsed["company"] == "Unknown"
        assert parsed["location"] == "Melbourne VIC"
