"""RemoteOK public API adapter — REAL remote job discovery, no API key (D11).

Fetches ``https://remoteok.com/api``. The first array element is a legal
notice, not a job — it is skipped. The posting's real ``url`` is stored as
the apply URL — zero fabrication.
"""
from __future__ import annotations

from typing import Any

from app.services.discovery import relevance
from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json


class RemoteOkAdapter(BaseAdapter):
    """Live adapter over the keyless RemoteOK API."""

    source = "remoteok"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        payload = fetch_json("https://remoteok.com/api")
        return {"jobs": payload} if isinstance(payload, list) else {"jobs": []}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("jobs", []):
            # The API's first element is a legal/ToS notice without a position.
            if not isinstance(item, dict) or not item.get("position"):
                continue
            apply_url = str(item.get("url") or "")
            if not apply_url:
                continue
            jobs.append(
                JobRaw(
                    title=str(item.get("position") or ""),
                    company=str(item.get("company") or ""),
                    location=str(item.get("location") or "").strip().rstrip(",") or "Remote",
                    remote=True,
                    description=relevance.snippet(
                        item.get("description"), limit=relevance.DESCRIPTION_STORAGE_LIMIT
                    ),
                    requirements=[],
                    source=self.source,
                    sourceUrl=apply_url,
                    postedAt=str(item.get("date") or ""),
                )
            )
        return relevance.filter_relevant(jobs)
