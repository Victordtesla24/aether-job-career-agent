"""Lever public-postings adapter — REAL job discovery, no API key (D11).

Fetches ``https://api.lever.co/v0/postings/<company>?mode=json`` for every
configured company. Companies are config-driven via ``AETHER_LEVER_COMPANIES``
(comma-separated) so new boards can be added without code changes. Only
companies verified to resolve (HTTP 200) are in the default list.

The posting's real ``hostedUrl`` (fallback ``applyUrl``) is stored as the
apply URL — zero fabrication.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from app.services.discovery import portals, relevance
from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)


def configured_companies() -> list[str]:
    """Curated company slugs (overridable via ``AETHER_LEVER_COMPANIES``)."""
    return portals.lever_companies()


def _posted_at(created_at_ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(created_at_ms) / 1000, tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


class LeverAdapter(BaseAdapter):
    """Live adapter over the keyless Lever postings API."""

    source = "lever"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        companies: list[dict[str, Any]] = []
        for slug in configured_companies():
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            try:
                postings = fetch_json(url)
            except Exception as exc:  # noqa: BLE001 — one bad company must not sink the run
                logger.warning("lever: company %s failed: %s", slug, exc)
                continue
            if isinstance(postings, list):
                companies.append({"company": slug, "postings": postings})
        return {"companies": companies}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for entry in payload.get("companies", []):
            slug = str(entry.get("company", ""))
            for item in entry.get("postings", []):
                categories = item.get("categories") or {}
                apply_url = str(item.get("hostedUrl") or item.get("applyUrl") or "")
                if not apply_url:
                    continue
                all_locations = categories.get("allLocations") or []
                location = ", ".join(all_locations) or str(categories.get("location") or "")
                workplace = str(item.get("workplaceType") or "").lower()
                jobs.append(
                    JobRaw(
                        title=str(item.get("text") or ""),
                        company=slug.replace("-", " ").title(),
                        location=location,
                        remote=workplace == "remote" or "remote" in location.lower(),
                        description=relevance.snippet(
                            item.get("descriptionPlain") or item.get("description")
                        ),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=_posted_at(item.get("createdAt")),
                    )
                )
        return relevance.filter_relevant(jobs)
