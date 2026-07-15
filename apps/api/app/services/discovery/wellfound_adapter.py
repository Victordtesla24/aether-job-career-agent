"""Wellfound (ex-AngelList) public listings adapter (P5).

Wellfound is a keyword-searchable source: it queries by the user's target
role. Wellfound serves listings from a Cloudflare-protected endpoint with no
supported keyless public API, so the live fetch attempts the public role feed
and, when Wellfound blocks it, raises :class:`AdapterFetchError` so the failure
is surfaced honestly per GAP-SRC-002 — never fabricated. If Wellfound restores
a public JSON feed this adapter starts returning jobs with no further changes.

The posting's real ``url`` is stored as the apply URL — zero fabrication.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery import relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)


class WellfoundAdapter(BaseAdapter):
    """Live adapter over Wellfound's public role listings."""

    source = "wellfound"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        role = (query or "software").split(",")[0].strip().lower().replace(" ", "-")
        url = f"https://wellfound.com/role/l/{role}"
        try:
            payload = fetch_json(url)
        except Exception as exc:  # noqa: BLE001 — surface honestly, don't fabricate
            raise AdapterFetchError(
                f"Wellfound public listings unavailable: {exc}"
            ) from exc
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        return {"jobs": jobs}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("jobs", []):
            company = item.get("company") or {}
            company_name = (
                str(company.get("name") or "")
                if isinstance(company, dict)
                else str(company)
            )
            apply_url = str(item.get("url") or "")
            if not apply_url and item.get("id"):
                apply_url = f"https://wellfound.com/jobs/{item.get('id')}"
            if not apply_url:
                continue
            locations = item.get("locations") or []
            location = ", ".join(
                str(loc.get("name") if isinstance(loc, dict) else loc)
                for loc in locations
            ) or str(item.get("location") or "")
            jobs.append(
                JobRaw(
                    title=str(item.get("title") or ""),
                    company=company_name,
                    location=location or "Remote",
                    remote=bool(item.get("remote")),
                    description=relevance.snippet(item.get("description")),
                    requirements=[],
                    source=self.source,
                    sourceUrl=apply_url,
                    postedAt=str(item.get("liveStartAt") or item.get("createdAt") or ""),
                )
            )
        return relevance.filter_relevant(jobs)
