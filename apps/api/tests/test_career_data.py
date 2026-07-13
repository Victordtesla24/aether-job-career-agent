"""Career-data consolidation tests (GAP-P4-047 · ADR D-0031).

Covers real-shape parsing, per-source ingestion with honest error/empty
states, persistence + corpus assembly, and the proof that ingested GitHub /
portfolio signal widens the tailoring & cover-letter anti-fabrication corpus.

Network is mocked **only in tests** (injected ``*_fetch`` callables or
monkeypatched module globals); production code performs real fetches.
"""
from __future__ import annotations

import urllib.error

import pytest
from fixtures.github_fixture import github_fixture
from fixtures.portfolio_fixture import PORTFOLIO_HTML, portfolio_html_fixture

from app.repositories.career_profile import CareerProfileRepository
from app.services import career_data
from app.services.career_data import (
    build_career_corpus,
    ingest_github,
    ingest_linkedin,
    ingest_portfolio,
    parse_portfolio_html,
    refresh_career_data,
    summarize_github,
    summarize_portfolio,
)
from app.services.resume_tailor import _evidence_index, unsupported_tokens

# ---------------------------------------------------------------------------
# Portfolio HTML parsing (pure, offline)
# ---------------------------------------------------------------------------


def test_parse_portfolio_extracts_title_description_person():
    parsed = parse_portfolio_html(PORTFOLIO_HTML, "https://example.test")
    assert parsed["title"] == "Sample Candidate — Delivery Lead & Solutions Architect"
    assert parsed["description"] == "Delivery lead and solutions architect based in Melbourne."
    assert parsed["person"]["name"] == "Sample Candidate"
    assert parsed["person"]["jobTitle"] == "Delivery Lead"
    assert parsed["person"]["worksFor"] == "Sample Org"
    assert parsed["url"] == "https://example.test"


def test_parse_portfolio_strips_scripts_and_styles():
    parsed = parse_portfolio_html(PORTFOLIO_HTML)
    text = parsed["text"]
    # Real visible copy is captured…
    assert "Delivery lead and solutions architect" in text
    assert "Kubernetes" in text
    # …but script/style/noscript contents never leak into the corpus.
    assert "should-not-appear" not in text
    assert "color:red" not in text
    assert "Enable JavaScript" not in text


def test_summarize_portfolio_is_readable_evidence():
    summary = summarize_portfolio(parse_portfolio_html(PORTFOLIO_HTML))
    assert "Portfolio:" in summary
    assert "Sample Candidate — Delivery Lead at Sample Org." in summary
    assert "Kubernetes" in summary


# ---------------------------------------------------------------------------
# GitHub summary + ingestion
# ---------------------------------------------------------------------------


def test_summarize_github_lists_languages_and_repos():
    profile = career_data.scrape_github_profile(
        "Victordtesla24", fixture=github_fixture()
    )
    summary = summarize_github(profile)
    assert "GitHub profile:" in summary
    assert "Python" in summary  # top language
    assert "ml-pipelines" in summary  # top repo by stars


def test_ingest_github_success_via_injected_fetch():
    res = ingest_github("Victordtesla24", fetch=lambda u: github_fixture(u))
    assert res["status"] == "ok"
    assert res["url"] == "https://github.com/Victordtesla24"
    assert res["error"] is None
    assert res["content"]["username"] == "Victordtesla24"
    assert "ml-pipelines" in res["summary"]


def test_ingest_github_missing_username_is_empty_not_error():
    res = ingest_github("")
    assert res["status"] == "empty"
    assert res["summary"] is None
    assert "No GitHub username" in res["error"]


def test_ingest_github_surfaces_fetch_failure_honestly():
    def boom(_username):
        raise urllib.error.HTTPError("u", 404, "Not Found", None, None)

    res = ingest_github("ghost-user", fetch=boom)
    assert res["status"] == "error"
    assert res["summary"] is None  # no fabricated content on failure
    assert "not found" in res["error"].lower()


def test_ingest_github_rate_limit_message():
    def limited(_username):
        raise urllib.error.HTTPError("u", 403, "rate limited", None, None)

    res = ingest_github("someone", fetch=limited)
    assert res["status"] == "error"
    assert "rate limit" in res["error"].lower()


# ---------------------------------------------------------------------------
# Portfolio + LinkedIn ingestion
# ---------------------------------------------------------------------------


def test_ingest_portfolio_success_via_injected_fetch():
    res = ingest_portfolio("https://example.test", fetch=lambda u: PORTFOLIO_HTML)
    assert res["status"] == "ok"
    assert res["url"] == "https://example.test"
    assert "Kubernetes" in res["summary"]


def test_ingest_portfolio_fetch_failure_is_error():
    def boom(_url):
        raise urllib.error.URLError("dns failure")

    res = ingest_portfolio("https://bad.test", fetch=boom)
    assert res["status"] == "error"
    assert res["summary"] is None
    assert "bad.test" in res["error"]


def test_ingest_portfolio_missing_url_is_empty():
    res = ingest_portfolio(None)
    assert res["status"] == "empty"
    assert "No portfolio URL" in res["error"]


def test_ingest_linkedin_workspace_paste_ok():
    res = ingest_linkedin("Seasoned delivery lead across finance and government.")
    assert res["status"] == "ok"
    assert "delivery lead" in res["summary"]


def test_ingest_linkedin_empty_states_honest_limitation():
    res = ingest_linkedin("")
    assert res["status"] == "empty"
    assert res["summary"] is None
    assert "no public profile api" in res["error"].lower()


# ---------------------------------------------------------------------------
# Persistence + corpus assembly + re-use of stored values (DB-backed)
# ---------------------------------------------------------------------------


def test_refresh_persists_all_sources_and_builds_corpus(client, test_user_id):
    results = refresh_career_data(
        test_user_id,
        github_username="Victordtesla24",
        portfolio_url="https://example.test",
        linkedin_summary="Delivery lead across finance and telecommunications.",
        github_fetch=lambda u: github_fixture(u),
        portfolio_fetch=lambda u: PORTFOLIO_HTML,
    )
    assert results["github"]["status"] == "ok"
    assert results["portfolio"]["status"] == "ok"
    assert results["linkedin"]["status"] == "ok"

    # Rows are persisted and re-readable.
    stored = {r["source"]: r for r in CareerProfileRepository().list_by_user(test_user_id)}
    assert set(stored) == {"github", "portfolio", "linkedin"}
    assert stored["github"]["content"]["username"] == "Victordtesla24"

    corpus = build_career_corpus(test_user_id)
    assert "ml-pipelines" in corpus  # github
    assert "Kubernetes" in corpus  # portfolio
    assert "telecommunications" in corpus  # linkedin


def test_corpus_excludes_non_ok_sources(client, test_user_id):
    # Portfolio fails, github ok, linkedin not provided → only github in corpus.
    def boom(_url):
        raise urllib.error.URLError("unreachable")

    refresh_career_data(
        test_user_id,
        github_username="Victordtesla24",
        portfolio_url="https://bad.test",
        linkedin_summary="",
        github_fetch=lambda u: github_fixture(u),
        portfolio_fetch=boom,
    )
    corpus = build_career_corpus(test_user_id)
    assert "ml-pipelines" in corpus
    assert "Kubernetes" not in corpus  # failed portfolio contributes nothing


def test_bare_refresh_reuses_stored_values(client, test_user_id):
    refresh_career_data(
        test_user_id,
        github_username="Victordtesla24",
        portfolio_url="https://example.test",
        github_fetch=lambda u: github_fixture(u),
        portfolio_fetch=lambda u: PORTFOLIO_HTML,
    )
    # A second refresh with no inputs must re-sync the stored username/url.
    results = refresh_career_data(
        test_user_id,
        github_fetch=lambda u: github_fixture(u),
        portfolio_fetch=lambda u: PORTFOLIO_HTML,
    )
    assert results["github"]["status"] == "ok"
    assert results["github"]["url"] == "https://github.com/Victordtesla24"
    assert results["portfolio"]["status"] == "ok"
    assert results["portfolio"]["url"] == "https://example.test"


def test_career_corpus_empty_for_fresh_user(client, test_user_id):
    assert build_career_corpus(test_user_id) == ""


# ---------------------------------------------------------------------------
# The consolidated signal actually widens the tailoring evidence corpus
# ---------------------------------------------------------------------------


def test_github_and_portfolio_signal_join_tailor_evidence(client, test_user_id):
    base_resume = "• Led delivery across squads\n• Reduced costs by 15%\n"
    # Without career data these tokens are unsupported fabrications.
    stems, numbers = _evidence_index(base_resume)
    assert unsupported_tokens("Shipped platforms on Kubernetes", stems, numbers)
    assert unsupported_tokens("Maintained ml-pipelines in Python", stems, numbers)

    refresh_career_data(
        test_user_id,
        github_username="Victordtesla24",
        portfolio_url="https://example.test",
        github_fetch=lambda u: github_fixture(u),
        portfolio_fetch=lambda u: PORTFOLIO_HTML,
    )
    corpus = build_career_corpus(test_user_id)
    aug_stems, aug_numbers = _evidence_index(base_resume + "\n" + corpus)
    # Now the same claims trace to real ingested evidence.
    assert not unsupported_tokens("Shipped platforms on Kubernetes", aug_stems, aug_numbers)
    assert not unsupported_tokens("Maintained ml-pipelines in Python", aug_stems, aug_numbers)


# ---------------------------------------------------------------------------
# HTTP surface: refresh + read + settings portfolio block (network monkeypatched)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _mock_network(monkeypatch):
    """Route the production fetch path through offline fixtures."""
    from app.services.portfolio_scraper import scrape_github_profile as real_scrape

    monkeypatch.setattr(
        career_data,
        "scrape_github_profile",
        lambda username, fixture=None: real_scrape(username, fixture=github_fixture(username)),
    )
    monkeypatch.setattr(career_data, "_fetch_html", lambda url: portfolio_html_fixture())


def test_refresh_endpoint_persists_and_reads_back(client, auth_headers, _mock_network):
    resp = client.post(
        "/workspaces/career-data/refresh",
        json={
            "githubUsername": "Victordtesla24",
            "portfolioUrl": "https://example.test",
            "linkedinSummary": "Delivery lead across finance.",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    by_source = {s["source"]: s for s in resp.json()["sources"]}
    assert by_source["github"]["status"] == "ok"
    assert by_source["portfolio"]["status"] == "ok"
    assert by_source["linkedin"]["status"] == "ok"
    assert by_source["github"]["url"] == "https://github.com/Victordtesla24"

    # GET reflects the just-persisted state.
    read = client.get("/workspaces/career-data", headers=auth_headers).json()
    read_sources = {s["source"]: s for s in read["sources"]}
    assert read_sources["portfolio"]["url"] == "https://example.test"
    assert read_sources["portfolio"]["lastSynced"]
    assert "no public profile api" in read["linkedinNote"].lower()


def test_settings_portfolio_block_reflects_real_url(client, auth_headers, _mock_network):
    # Before any refresh the portfolio block is honestly null.
    before = client.get("/workspaces/settings", headers=auth_headers).json()
    assert before["portfolio"]["url"] is None
    assert before["portfolio"]["status"] == "not_configured"

    client.post(
        "/workspaces/career-data/refresh",
        json={"portfolioUrl": "https://example.test"},
        headers=auth_headers,
    )
    after = client.get("/workspaces/settings", headers=auth_headers).json()
    assert after["portfolio"]["url"] == "https://example.test"
    assert after["portfolio"]["status"] == "ok"
    assert after["portfolio"]["lastSynced"]


def test_refresh_endpoint_reports_github_error_state(client, auth_headers, monkeypatch):
    def boom(username, fixture=None):
        raise urllib.error.HTTPError("u", 404, "Not Found", None, None)

    monkeypatch.setattr(career_data, "scrape_github_profile", boom)
    resp = client.post(
        "/workspaces/career-data/refresh",
        json={"githubUsername": "definitely-not-a-real-user-xyz"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    gh = next(s for s in resp.json()["sources"] if s["source"] == "github")
    assert gh["status"] == "error"
    assert "not found" in gh["error"].lower()
    assert gh["summary"] is None
