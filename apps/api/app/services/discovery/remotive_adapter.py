"""Remotive public API adapter — REAL remote job discovery, no API key (D11).

Fetches ``https://remotive.com/api/remote-jobs?limit=…`` (the ``search``
parameter proved unreliable — the API frequently ignores it — so filtering
is done locally with the shared relevance module). The posting's real
``url`` is stored as the apply URL — zero fabrication.
"""
from __future__ import annotations

import os
from typing import Any

from app.services.discovery import relevance
from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

#: Remotive's entire live remote-jobs board currently sits well under this
#: (see gap-6 sourcing notes) — set generously above today's total so a
#: future-larger board isn't silently truncated (GAP-SRC-001 pagination
#: depth). ``search`` is unreliable so this is a plain higher ceiling, not a
#: filter.
_DEFAULT_LIMIT = "250"


class RemotiveAdapter(BaseAdapter):
    """Live adapter over the keyless Remotive remote-jobs API."""

    source = "remotive"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        limit = os.environ.get("AETHER_REMOTIVE_LIMIT", _DEFAULT_LIMIT)
        payload = fetch_json(f"https://remotive.com/api/remote-jobs?limit={limit}")
        return payload if isinstance(payload, dict) else {"jobs": []}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("jobs", []):
            apply_url = str(item.get("url") or "")
            if not apply_url:
                continue
            jobs.append(
                JobRaw(
                    title=str(item.get("title") or ""),
                    company=str(item.get("company_name") or ""),
                    location=str(item.get("candidate_required_location") or "Remote"),
                    remote=True,
                    description=relevance.snippet(item.get("description")),
                    requirements=[],
                    source=self.source,
                    sourceUrl=apply_url,
                    postedAt=str(item.get("publication_date") or ""),
                )
            )
        return relevance.filter_relevant(jobs)
