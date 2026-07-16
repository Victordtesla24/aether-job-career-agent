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
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)


class AshbyAdapter(BaseAdapter):
    """Live adapter over the keyless Ashby posting API."""

    source = "ashby"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        tokens = portals.ashby_boards()
        boards: list[dict[str, Any]] = []
        failures: list[str] = []
        for token in tokens:
            url = f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false"
            try:
                payload = fetch_json(url)
            except Exception as exc:  # noqa: BLE001 — one bad board must not sink the run
                logger.warning("ashby: board %s failed: %s", token, exc)
                failures.append(f"{token}: {type(exc).__name__}: {exc}")
                continue
            jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
            boards.append({"token": token, "jobs": jobs})
        # GAP-SRC-002: if boards were configured but EVERY one failed to fetch,
        # this is a total outage — surface it as a real per-source error rather
        # than returning an empty-but-ok result the scout records as status=ok.
        # A board that fetched OK but has zero open roles keeps ``boards``
        # non-empty, so a genuine "fetched 0 jobs" stays a legitimate status=ok.
        if tokens and not boards:
            raise AdapterFetchError(
                f"ashby: all {len(tokens)} configured board(s) failed: "
                + "; ".join(failures)
            )
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
                            item.get("descriptionPlain") or item.get("descriptionHtml"),
                            limit=relevance.DESCRIPTION_STORAGE_LIMIT,
                        ),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("publishedAt") or ""),
                    )
                )
        return relevance.filter_relevant(jobs)
