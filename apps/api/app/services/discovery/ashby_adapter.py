"""Ashby public job-board adapter — REAL job discovery, no API key (P5).

Fetches ``https://api.ashbyhq.com/posting-api/job-board/<token>`` for every
configured board token (see :mod:`app.services.discovery.portals`). Board
tokens are CASE-SENSITIVE and config-driven, so new companies can be added
without a code change.

Every persisted job keeps the posting's real ``applyUrl`` (fallback
``jobUrl``) as the apply URL — zero fabrication.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery import portals, relevance
from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)


class AshbyAdapter(BaseAdapter):
    """Live adapter over the keyless Ashby posting API."""

    source = "ashby"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        boards: list[dict[str, Any]] = []
        for token in portals.ashby_boards():
            url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
            try:
                payload = fetch_json(url)
            except Exception as exc:  # noqa: BLE001 — one bad board must not sink the run
                logger.warning("ashby: board %s failed: %s", token, exc)
                continue
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
            boards.append({"token": token, "jobs": jobs})
        return {"boards": boards}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for board in payload.get("boards", []):
            token = str(board.get("token", ""))
            for item in board.get("jobs", []):
                apply_url = str(item.get("applyUrl") or item.get("jobUrl") or "")
                if not apply_url:
                    continue
                location = str(item.get("location") or "")
                remote = bool(item.get("isRemote")) or "remote" in location.lower()
                jobs.append(
                    JobRaw(
                        title=str(item.get("title") or ""),
                        # Ashby board token is the company's own slug/name.
                        company=token,
                        location=location,
                        remote=remote,
                        description=relevance.snippet(
                            item.get("descriptionPlain") or item.get("descriptionHtml")
                        ),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("publishedAt") or ""),
                    )
                )
        return relevance.filter_relevant(jobs)
