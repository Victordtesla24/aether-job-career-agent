"""Seek.com.au discovery adapter (P2-S02)."""
from __future__ import annotations

from typing import Any

from app.services.discovery.base_adapter import BaseAdapter, JobRaw

_REMOTE_MARKERS = ("remote", "work from home", "wfh")


class SeekAdapter(BaseAdapter):
    """Parses Seek's search payload (``data`` array) into ``JobRaw``."""

    source = "seek"

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("data", []):
            arrangement = (item.get("workArrangements") or {}).get("displayText", "")
            requirements = [b for b in item.get("bulletPoints", []) if b]
            jobs.append(
                JobRaw(
                    title=item.get("title", ""),
                    company=(item.get("advertiser") or {}).get("description", ""),
                    location=item.get("location"),
                    remote=arrangement.lower() in _REMOTE_MARKERS,
                    description=item.get("teaser", ""),
                    requirements=requirements,
                    source=self.source,
                    sourceUrl=item.get("shareLink", ""),
                    postedAt=item.get("listingDate"),
                )
            )
        return jobs
