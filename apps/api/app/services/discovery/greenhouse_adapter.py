"""Greenhouse public-boards adapter — REAL job discovery, no API key (D11).

Fetches ``https://boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true``
for every configured board token. Board tokens are config-driven via the
``AETHER_GREENHOUSE_BOARDS`` env var (comma-separated) so new companies can be
added without code changes. Only boards verified to return HTTP 200 with real
jobs are in the default list.

Every persisted job keeps the posting's real ``absolute_url`` as the apply
URL — zero fabrication.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery import portals, relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)


def configured_boards() -> list[str]:
    """Curated board tokens (overridable via ``AETHER_GREENHOUSE_BOARDS``)."""
    return portals.greenhouse_boards()


class GreenhouseAdapter(BaseAdapter):
    """Live adapter over the keyless Greenhouse boards API."""

    source = "greenhouse"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        tokens = configured_boards()
        boards: list[dict[str, Any]] = []
        failures: list[str] = []
        for token in tokens:
            url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
            try:
                payload = fetch_json(url)
            except Exception as exc:  # noqa: BLE001 — one bad board must not sink the run
                logger.warning("greenhouse: board %s failed: %s", token, exc)
                failures.append(f"{token}: {type(exc).__name__}: {exc}")
                continue
            boards.append({"token": token, "jobs": payload.get("jobs", [])})
        # GAP-SRC-002: if boards were configured but EVERY one failed to fetch,
        # this is a total outage — surface it as a real per-source error rather
        # than returning an empty-but-ok result the scout records as status=ok.
        # A board that fetched OK but has zero open roles keeps ``boards``
        # non-empty, so a genuine "fetched 0 jobs" stays a legitimate status=ok.
        if tokens and not boards:
            raise AdapterFetchError(
                f"greenhouse: all {len(tokens)} configured board(s) failed: "
                + "; ".join(failures)
            )
        return {"boards": boards}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for board in payload.get("boards", []):
            token = str(board.get("token", ""))
            for item in board.get("jobs", []):
                location = str((item.get("location") or {}).get("name") or "")
                apply_url = str(item.get("absolute_url") or "")
                if not apply_url:
                    continue
                jobs.append(
                    JobRaw(
                        title=str(item.get("title") or ""),
                        company=str(item.get("company_name") or token.title()),
                        location=location,
                        remote="remote" in location.lower(),
                        description=relevance.snippet(item.get("content")),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("updated_at") or ""),
                    )
                )
        return relevance.filter_relevant(jobs)
