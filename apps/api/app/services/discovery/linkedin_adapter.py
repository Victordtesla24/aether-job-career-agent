"""LinkedIn Jobs discovery adapter (P2-S02)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.discovery.base_adapter import BaseAdapter, JobRaw


class LinkedInAdapter(BaseAdapter):
    """Parses LinkedIn's job-postings payload (``elements`` array)."""

    source = "linkedin"

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("elements", []):
            listed_at = item.get("listedAt")
            posted_at = (
                datetime.fromtimestamp(listed_at / 1000, tz=timezone.utc).isoformat()
                if isinstance(listed_at, (int, float))
                else None
            )
            description = (item.get("description") or {}).get("text", "")
            jobs.append(
                JobRaw(
                    title=item.get("title", ""),
                    company=(item.get("companyDetails") or {}).get("name", ""),
                    location=item.get("formattedLocation"),
                    remote=(item.get("workplaceType") or "").lower() == "remote",
                    description=description,
                    requirements=_extract_requirements(description),
                    source=self.source,
                    sourceUrl=item.get("jobPostingUrl", ""),
                    postedAt=posted_at,
                )
            )
        return jobs


def _extract_requirements(description: str) -> list[str]:
    """Pull the sentence following a 'Requirements:' marker, split on commas."""
    lowered = description.lower()
    marker = "requirements:"
    if marker not in lowered:
        return []
    start = lowered.index(marker) + len(marker)
    clause = description[start:].split(".")[0]
    return [part.strip() for part in clause.split(",") if part.strip()]
