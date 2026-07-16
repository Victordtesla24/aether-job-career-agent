"""Adzuna AU licensed-aggregator adapter — REAL job discovery (GAP-P6-SRC-001).

Adzuna is a licensed job aggregator with explicit Australia support
(seek-tos-check.md Part 4, VERIFIED-WITH-SOURCE) — the ToS-compliant way to
reach AU listings that Seek scraping is prohibited from providing (ADR-P6-SEEK).

Auth is a free-tier ``app_id`` + ``app_key`` read from the environment
(``ADZUNA_APP_ID`` / ``ADZUNA_APP_KEY``) — never hardcoded. When the credentials
are ABSENT the adapter honestly degrades: ``_fetch_live`` raises
``NotImplementedError`` so the scout records the source as a benign ``skipped``
(surfaced in per-source status), and volume falls back to the keyless ATS +
public-API sources. It NEVER fabricates jobs to cover a missing key.

When the credentials ARE present the adapter paginates
``/v1/api/jobs/au/search/<page>`` to exhaustion (or a sane page cap), applies
the shared relevance filter, and keeps each posting's real ``redirect_url`` as
the apply URL — zero fabrication. A first-page fetch failure raises
``AdapterFetchError`` so a real outage is surfaced per-source rather than
swallowed as an empty-but-ok result (GAP-P6-SRC-002); a genuine empty result
stays a legitimate ``status=ok`` zero.
"""
from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import quote_plus

from app.services.discovery import relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)

_API_BASE = "https://api.adzuna.com/v1/api/jobs"
_REMOTE_MARKERS = ("remote", "work from home", "wfh", "hybrid", "anywhere")


def _credentials() -> tuple[str | None, str | None]:
    """Adzuna app_id/app_key from the environment (os.environ only)."""
    return (
        (os.environ.get("ADZUNA_APP_ID") or "").strip() or None,
        (os.environ.get("ADZUNA_APP_KEY") or "").strip() or None,
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class AdzunaAdapter(BaseAdapter):
    """Live adapter over the licensed Adzuna AU search API."""

    source = "adzuna"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        app_id, app_key = _credentials()
        if not app_id or not app_key:
            # Honest degrade: no live mode without licensed credentials. The
            # scout treats this as a benign skip (never fabricated data).
            raise NotImplementedError(
                "Adzuna AU live mode requires ADZUNA_APP_ID and ADZUNA_APP_KEY "
                "(free-tier developer credentials); absent — source skipped, "
                "volume relies on the keyless ATS + public-API sources."
            )

        country = (os.environ.get("AETHER_ADZUNA_COUNTRY", "au") or "au").strip().lower()
        results_per_page = _int_env("AETHER_ADZUNA_RESULTS_PER_PAGE", 50)
        max_pages = _int_env("AETHER_ADZUNA_MAX_PAGES", 5)
        max_days_old = _int_env("AETHER_ADZUNA_MAX_DAYS_OLD", 30)
        max_jobs = _int_env("AETHER_ADZUNA_MAX_JOBS", 200)

        # OR-search across the whole target-role family so a broadened scout
        # query (GAP-SRC-001) is honoured rather than AND-ing every term.
        what_or = " ".join(term.strip() for term in query.split(",") if term.strip())
        where = location or "Australia"

        results: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            url = (
                f"{_API_BASE}/{country}/search/{page}"
                f"?app_id={quote_plus(app_id)}&app_key={quote_plus(app_key)}"
                f"&results_per_page={results_per_page}"
                f"&what_or={quote_plus(what_or)}"
                f"&where={quote_plus(where)}"
                f"&max_days_old={max_days_old}"
                "&sort_by=date&content-type=application/json"
            )
            try:
                payload = fetch_json(url)
            except Exception as exc:  # noqa: BLE001 — surface a real outage honestly
                if page == 1:
                    logger.warning("adzuna: search failed on page 1: %s", exc)
                    raise AdapterFetchError(
                        f"Adzuna AU search failed: {type(exc).__name__}: {exc}"
                    ) from exc
                logger.warning("adzuna: page %d failed: %s", page, exc)
                break
            batch = payload.get("results", []) if isinstance(payload, dict) else []
            results.extend(batch)
            # Exhausted (short page) or hit the sane job cap.
            if len(batch) < results_per_page or len(results) >= max_jobs:
                break
        return {"results": results[:max_jobs]}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for item in payload.get("results", []):
            apply_url = str(item.get("redirect_url") or "")
            if not apply_url:
                continue
            company = str((item.get("company") or {}).get("display_name") or "")
            location = str((item.get("location") or {}).get("display_name") or "")
            title = str(item.get("title") or "")
            remote = any(
                m in f"{title} {location}".lower() for m in _REMOTE_MARKERS
            )
            salary_min = item.get("salary_min")
            salary_max = item.get("salary_max")
            jobs.append(
                JobRaw(
                    title=title,
                    company=company,
                    location=location or None,
                    remote=remote,
                    description=relevance.snippet(
                        item.get("description"), limit=relevance.DESCRIPTION_STORAGE_LIMIT
                    ),
                    requirements=[],
                    source=self.source,
                    sourceUrl=apply_url,
                    postedAt=str(item.get("created") or "") or None,
                    salaryMin=int(salary_min) if salary_min is not None else None,
                    salaryMax=int(salary_max) if salary_max is not None else None,
                    currency="AUD" if (salary_min is not None or salary_max is not None) else None,
                )
            )
        return relevance.filter_relevant(jobs)
