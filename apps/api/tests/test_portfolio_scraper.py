"""Tests for the portfolio / GitHub scraper (P1-S05).

Runs entirely offline by injecting the deterministic `github_fixture` — no
network calls, no rate limits. The live path (`fixture=None`) is not exercised
here to keep the suite deterministic.
"""
from __future__ import annotations

import pytest
from fixtures.github_fixture import empty_github_fixture, github_fixture

from app.services.portfolio_scraper import scrape_github_profile


def test_scrape_returns_normalized_profile() -> None:
    result = scrape_github_profile("Victordtesla24", fixture=github_fixture())
    assert result["username"] == "Victordtesla24"
    assert result["name"] == "Sample User"
    assert result["public_repos"] == 3
    assert result["followers"] == 42
    assert result["profile_url"] == "https://github.com/Victordtesla24"


def test_top_repos_sorted_by_stars_desc() -> None:
    result = scrape_github_profile("Victordtesla24", fixture=github_fixture())
    top = result["top_repos"]
    assert [r["name"] for r in top] == [
        "ml-pipelines",  # 34
        "aether-core",  # 12
        "infra-templates",  # 5
    ]
    # Each repo entry exposes the fields the portfolio card needs.
    assert top[0]["stars"] == 34
    assert top[0]["language"] == "Python"
    assert top[0]["url"].endswith("/ml-pipelines")


def test_total_stars_and_top_languages_aggregated() -> None:
    result = scrape_github_profile("Victordtesla24", fixture=github_fixture())
    assert result["total_stars"] == 12 + 34 + 5
    # Python appears twice, TypeScript once → Python ranks first.
    assert result["top_languages"][0] == "Python"
    assert "TypeScript" in result["top_languages"]


def test_empty_profile_is_handled_gracefully() -> None:
    result = scrape_github_profile("ghost", fixture=empty_github_fixture("ghost"))
    assert result["username"] == "ghost"
    assert result["public_repos"] == 0
    assert result["top_repos"] == []
    assert result["top_languages"] == []
    assert result["total_stars"] == 0


def test_blank_username_raises() -> None:
    with pytest.raises(ValueError):
        scrape_github_profile("", fixture=github_fixture())
