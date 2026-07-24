"""Indeed discovery adapter (P2-S02)."""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery.base_adapter import BaseAdapter, JobRaw
from app.services.discovery.linkedin_adapter import _extract_requirements

logger = logging.getLogger(__name__)


class IndeedAdapter(BaseAdapter):
    """Parses Indeed's search payload (``results`` array)."""

    source = "indeed"

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("results", []):
            try:
                remote_text = (item.get("remoteWorkModel") or {}).get("text", "")
                description = item.get("snippet", "")
                source_url = item.get("url", "")
                if not source_url:
                    logger.warning(
                        "indeed: job skipped — empty url (title=%r company=%r)",
                        item.get("jobtitle", "")[:80],
                        item.get("company", "")[:80],
                    )
                    continue
                jobs.append(
                    JobRaw(
                        title=item.get("jobtitle", ""),
                        company=item.get("company", ""),
                        location=item.get("formattedLocation"),
                        remote=remote_text.strip().lower() == "remote",
                        description=description,
                        requirements=_extract_requirements(description),
                        source=self.source,
                        sourceUrl=source_url,
                        postedAt=item.get("pubDate"),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — log + skip bad item, don't fail whole source
                logger.warning(
                    "indeed: parse error on item (title=%r): %s",
                    item.get("jobtitle", "")[:80], exc,
                )
        return jobs
