"""Job-discovery tests (P2-S02) — RED first.

Covers the source adapters (Seek/LinkedIn), the Scout agent run endpoint, and
idempotent persistence of discovered jobs. Adapter unit tests parse *fixture*
HTML (representative mirrors of the live search DOM — live capture is blocked
from CI; see ``tests/fixtures/http/*/search.html``) so no network is required.

Acceptance (spec P2-S02): when the Scout agent queries ≥2 adapters, ``Job``
rows are persisted with ``source``, ``fitScore = null``, ``status = discovered``
and a unique ``sourceUrl`` each.
"""
from __future__ import annotations

import time
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "http"
SEEK_FIXTURE = (_FIXTURE_DIR / "seek" / "search.html").read_text(encoding="utf-8")
LINKEDIN_FIXTURE = (_FIXTURE_DIR / "linkedin" / "search.html").read_text(encoding="utf-8")
INDEED_FIXTURE = (_FIXTURE_DIR / "indeed" / "search.html").read_text(encoding="utf-8")


def test_seek_adapter_returns_job_list(mock_http):
    from app.services.discovery.seek_adapter import SeekAdapter

    jobs = SeekAdapter(fixture=SEEK_FIXTURE).fetch(query="Software Engineer", location="Sydney")
    assert len(jobs) >= 1
    assert all(j["source"] == "seek" for j in jobs)
    assert all(j["sourceUrl"].startswith("https://") for j in jobs)
    assert all(j["title"] for j in jobs)
    assert all(j["company"] for j in jobs)


def test_linkedin_adapter_returns_job_list(mock_http):
    from app.services.discovery.linkedin_adapter import LinkedInAdapter

    jobs = LinkedInAdapter(fixture=LINKEDIN_FIXTURE).fetch(query="Backend Engineer", location="Melbourne")
    assert len(jobs) >= 1
    assert all(j["source"] == "linkedin" for j in jobs)


def test_indeed_adapter_returns_job_list(mock_http):
    from app.services.discovery.indeed_adapter import IndeedAdapter

    jobs = IndeedAdapter(fixture=INDEED_FIXTURE).fetch(query="Python Developer", location="Sydney")
    assert len(jobs) >= 1
    assert all(j["source"] == "indeed" for j in jobs)
    assert all(j["sourceUrl"].startswith("https://") for j in jobs)


def test_jobs_are_persisted(client, auth_headers, db_session):
    r = client.post(
        "/agents/scout/run",
        headers=auth_headers,
        json={"query": "Software Engineer", "location": "Sydney"},
    )
    assert r.status_code == 202  # accepted, async
    time.sleep(0.5)  # tiny sync for in-process execution in tests

    from app.repositories.job import JobRepository

    jobs = JobRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    assert len(jobs) >= 1
    assert all(j.status == "discovered" for j in jobs)
    assert all(j.fit_score is None for j in jobs)  # scoring is a later slice


def test_duplicate_sourceUrl_is_not_persisted_twice(client, auth_headers, db_session):
    payload = {"query": "Python Developer", "location": "Sydney"}
    client.post("/agents/scout/run", headers=auth_headers, json=payload)
    client.post("/agents/scout/run", headers=auth_headers, json=payload)  # second run

    from app.repositories.job import JobRepository

    jobs = JobRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    urls = [j.source_url for j in jobs]
    assert len(urls) == len(set(urls))  # idempotent — no duplicates
