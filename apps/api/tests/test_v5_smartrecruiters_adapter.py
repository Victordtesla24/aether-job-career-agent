"""v5 — SmartRecruiters adapter (new portal).

SmartRecruiters was not supported at all before v5 despite being one of the most
AU-heavy ATSs: a live probe on 2026-08-02 found 951 open roles across 13 employer
boards (Canva, Ampol, Nearmap, Judo Bank, PEXA, SEEK's own corporate careers
board, ...).

No live HTTP here — ``_parse`` is exercised directly against a payload shaped
like the real ``/v1/companies/<id>/postings`` response.
"""
from __future__ import annotations

import pytest


def _adapter():
    from app.services.discovery.adapter_registry import get_adapter_class

    return get_adapter_class("smartrecruiters")


def _payload(**overrides):
    posting = {
        "id": "743999999999999",
        "name": "Senior Business Analyst",
        "company": {"name": "Canva"},
        "location": {"city": "Melbourne", "region": "VIC", "country": "au", "remote": False},
        "releasedDate": "2026-07-30T04:00:00.000Z",
        "jobAd": {
            "sections": {
                "jobDescription": {"text": "<p>Own delivery of the payments platform.</p>"}
            }
        },
    }
    posting.update(overrides)
    return {"boards": [{"company": "canva", "jobs": [posting]}]}


def test_smartrecruiters_is_registered_as_a_live_source():
    from app.services.discovery.adapter_registry import build_live_registry

    assert "smartrecruiters" in build_live_registry()


def test_parses_a_real_posting_into_the_common_shape():
    jobs = _adapter()()._parse(_payload())
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Senior Business Analyst"
    assert job["company"] == "Canva"
    assert job["location"] == "Melbourne, VIC, au"
    assert job["source"] == "smartrecruiters"
    assert job["postedAt"] == "2026-07-30T04:00:00.000Z"
    assert "payments platform" in job["description"]


def test_apply_url_is_derived_from_the_real_posting_id_never_invented():
    """No applyUrl in the payload -> the canonical public advert URL, built from
    the posting's REAL id. A posting with no id is dropped rather than given a
    fabricated link."""
    jobs = _adapter()()._parse(_payload())
    assert jobs[0]["sourceUrl"] == "https://jobs.smartrecruiters.com/canva/743999999999999"

    explicit = _adapter()()._parse(
        _payload(applyUrl="https://careers.canva.com/jobs/abc")
    )
    assert explicit[0]["sourceUrl"] == "https://careers.canva.com/jobs/abc"

    dropped = _adapter()()._parse(_payload(id=""))
    assert dropped == []


def test_remote_flag_is_honoured_from_the_location_object():
    jobs = _adapter()()._parse(
        _payload(location={"city": "", "region": "", "country": "au", "remote": True})
    )
    assert jobs and jobs[0]["remote"] is True


def test_irrelevant_roles_are_filtered_out_not_persisted():
    """The adapter applies relevance.filter_relevant like every other adapter:
    a non-target role in an unrelated location must not reach the board."""
    jobs = _adapter()()._parse(
        _payload(
            name="Line Cook",
            location={"city": "Austin", "region": "TX", "country": "us", "remote": False},
        )
    )
    assert jobs == []


def test_all_companies_failing_raises_rather_than_reporting_an_honest_empty(monkeypatch):
    """Mirrors GAP-SRC-002 in the Greenhouse adapter: configured-but-all-failed is
    a real outage, and must NOT be recorded by the scout as status=ok/0 jobs."""
    from app.services.discovery import smartrecruiters_adapter as mod
    from app.services.discovery.base_adapter import AdapterFetchError

    monkeypatch.setattr(mod, "configured_companies", lambda: ["canva", "ampol"])

    def _boom(url):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(mod, "fetch_json", _boom)

    with pytest.raises(AdapterFetchError) as exc:
        mod.SmartRecruitersAdapter()._fetch_live("Business Analyst", "Melbourne")
    assert "all 2 configured company board(s) failed" in str(exc.value)


def test_seek_entry_is_the_employer_board_not_the_job_marketplace():
    """`seek` in SMARTRECRUITERS_COMPANIES is SEEK hiring its OWN staff via a
    keyless public employer board. It must never cause a request to seek.com.au,
    which remains ToS-refused."""
    from app.services.discovery import portals

    assert "seek" in portals.smartrecruiters_companies()

    from pathlib import Path

    src = Path(portals.__file__).with_name("smartrecruiters_adapter.py").read_text()
    assert "seek.com.au" not in src.replace("scraping seek.com.au", "")
