"""Indeed discovery adapter (P2-S02)."""
from __future__ import annotations

from typing import Any

from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.linkedin_adapter import _extract_requirements


class IndeedAdapter(BaseAdapter):
    """Parses Indeed's search payload (``results`` array)."""

    source = "indeed"

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("results", []):
            remote_text = (item.get("remoteWorkModel") or {}).get("text", "")
            description = item.get("snippet", "")
            jobs.append(
                JobRaw(
                    title=item.get("jobtitle", ""),
                    company=item.get("company", ""),
                    location=item.get("formattedLocation"),
                    remote=remote_text.strip().lower() == "remote",
                    description=description,
                    requirements=_extract_requirements(description),
                    source=self.source,
                    sourceUrl=item.get("url", ""),
                    postedAt=item.get("pubDate"),
                )
            )
        return jobs
