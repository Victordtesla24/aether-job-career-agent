"""Deterministic GitHub API fixture for the portfolio scraper (P1-S05).

This mirrors the shape of the real GitHub REST API responses for
`GET /users/{username}` and `GET /users/{username}/repos`, so the scraper can be
exercised offline without hitting the network or rate limits. The data here is
synthetic sample test data (that is the purpose of a fixture) — it is NOT scraped
from any live profile and must not be treated as real portfolio content.
"""
from __future__ import annotations

from typing import Any


def github_profile_fixture(username: str = "Victordtesla24") -> dict[str, Any]:
    """A `GET /users/{username}` shaped payload."""
    return {
        "login": username,
        "name": "Sample User",
        "bio": "Senior technical leader — sample fixture bio.",
        "public_repos": 3,
        "followers": 42,
        "following": 7,
        "html_url": f"https://github.com/{username}",
    }


def github_repos_fixture() -> list[dict[str, Any]]:
    """A `GET /users/{username}/repos` shaped payload (3 repos)."""
    return [
        {
            "name": "aether-core",
            "description": "Sample repo — core services.",
            "language": "TypeScript",
            "stargazers_count": 12,
            "forks_count": 3,
            "html_url": "https://github.com/Victordtesla24/aether-core",
            "fork": False,
            "archived": False,
        },
        {
            "name": "ml-pipelines",
            "description": "Sample repo — ML pipelines.",
            "language": "Python",
            "stargazers_count": 34,
            "forks_count": 8,
            "html_url": "https://github.com/Victordtesla24/ml-pipelines",
            "fork": False,
            "archived": False,
        },
        {
            "name": "infra-templates",
            "description": None,
            "language": "Python",
            "stargazers_count": 5,
            "forks_count": 1,
            "html_url": "https://github.com/Victordtesla24/infra-templates",
            "fork": False,
            "archived": False,
        },
    ]


def github_fixture(username: str = "Victordtesla24") -> dict[str, Any]:
    """Combined `{profile, repos}` payload consumed by `scrape_github_profile`."""
    return {
        "profile": github_profile_fixture(username),
        "repos": github_repos_fixture(),
    }


def empty_github_fixture(username: str = "ghost") -> dict[str, Any]:
    """A profile with no public repositories."""
    return {
        "profile": {
            "login": username,
            "name": None,
            "bio": None,
            "public_repos": 0,
            "followers": 0,
            "following": 0,
            "html_url": f"https://github.com/{username}",
        },
        "repos": [],
    }
