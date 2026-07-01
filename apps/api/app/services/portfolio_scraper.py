"""Portfolio / GitHub profile scraper (P1-S05 — MVP).

`scrape_github_profile` normalises a GitHub profile into the compact shape the
Aether portfolio card needs: identity, headline counts, the top-starred repos,
and the most-used languages.

Two modes:
* **Fixture mode** (`fixture=` provided) — deterministic, offline, used by tests.
* **Live mode** (`fixture=None`) — fetches from the public GitHub REST API using
  only the standard library (`urllib`), so this slice adds no new dependency
  ahead of the FastAPI/httpx slice. Live calls are unauthenticated and therefore
  subject to GitHub's rate limits; callers should cache results.
"""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from typing import Any, Optional, TypedDict

GITHUB_API = "https://api.github.com"
_USER_AGENT = "aether-portfolio-scraper/0.1"
_TOP_REPO_LIMIT = 5
_TOP_LANGUAGE_LIMIT = 5


class RepoCard(TypedDict):
    name: str
    description: Optional[str]
    language: Optional[str]
    stars: int
    forks: int
    url: str


class GitHubProfile(TypedDict):
    username: str
    name: Optional[str]
    bio: Optional[str]
    public_repos: int
    followers: int
    profile_url: str
    total_stars: int
    top_languages: list[str]
    top_repos: list[RepoCard]


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _fetch_live(username: str) -> dict[str, Any]:
    profile = _fetch_json(f"{GITHUB_API}/users/{username}")
    repos = _fetch_json(
        f"{GITHUB_API}/users/{username}/repos?per_page=100&sort=updated"
    )
    return {"profile": profile, "repos": repos}


def _to_repo_card(repo: dict[str, Any]) -> RepoCard:
    return RepoCard(
        name=repo.get("name", ""),
        description=repo.get("description"),
        language=repo.get("language"),
        stars=int(repo.get("stargazers_count", 0) or 0),
        forks=int(repo.get("forks_count", 0) or 0),
        url=repo.get("html_url", ""),
    )


def scrape_github_profile(
    username: str,
    fixture: Optional[dict[str, Any]] = None,
) -> GitHubProfile:
    """Return a normalised GitHub profile.

    Pass ``fixture`` (a ``{"profile": {...}, "repos": [...]}`` dict) to run
    offline; otherwise the public GitHub API is queried for ``username``.
    """
    if not username or not username.strip():
        raise ValueError("username must be a non-empty string")

    data = fixture if fixture is not None else _fetch_live(username)
    profile: dict[str, Any] = data.get("profile", {})
    repos: list[dict[str, Any]] = data.get("repos", []) or []

    cards = [_to_repo_card(r) for r in repos]
    cards.sort(key=lambda c: c["stars"], reverse=True)

    language_counts = Counter(
        c["language"] for c in cards if c["language"]
    )
    top_languages = [lang for lang, _ in language_counts.most_common(_TOP_LANGUAGE_LIMIT)]

    return GitHubProfile(
        username=profile.get("login") or username,
        name=profile.get("name"),
        bio=profile.get("bio"),
        public_repos=int(profile.get("public_repos", len(cards)) or 0),
        followers=int(profile.get("followers", 0) or 0),
        profile_url=profile.get("html_url") or f"https://github.com/{username}",
        total_stars=sum(c["stars"] for c in cards),
        top_languages=top_languages,
        top_repos=cards[:_TOP_REPO_LIMIT],
    )
