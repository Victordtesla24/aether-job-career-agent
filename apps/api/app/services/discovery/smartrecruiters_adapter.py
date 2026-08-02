"""SmartRecruiters public postings adapter — REAL job discovery, no API key (v5).

Fetches ``https://api.smartrecruiters.com/v1/companies/<id>/postings`` for every
configured company. SmartRecruiters is one of the most AU-heavy ATSs and was not
supported at all before v5: a live probe on 2026-08-02 found 951 open roles
across 13 employer boards, including Canva, Ampol, Nearmap, Judo Bank, PEXA and
SEEK's own corporate careers board.

On ``seek``: that identifier is SEEK hiring its OWN staff via its keyless public
employer board. It is categorically different from scraping seek.com.au job
listings, which remains REFUSED under two binding risk rulings and is not done
here or anywhere else in this codebase.

Every persisted job keeps the posting's real apply URL — zero fabrication. A
company that fetches OK but has no open roles yields zero jobs honestly.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery import portals, relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)

#: SmartRecruiters caps ``limit`` at 100 per page and exposes ``offset``.
_PAGE_LIMIT = 100
#: Hard stop on pagination so one enormous board cannot stall a sweep. Recorded
#: rather than silent: exceeding it is logged (§"no silent caps").
_MAX_PAGES = 5


def configured_companies() -> list[str]:
    """Curated company identifiers (overridable via ``AETHER_SMARTRECRUITERS_COMPANIES``)."""
    return portals.smartrecruiters_companies()


class SmartRecruitersAdapter(BaseAdapter):
    """Live adapter over the keyless SmartRecruiters postings API."""

    source = "smartrecruiters"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        companies = configured_companies()
        boards: list[dict[str, Any]] = []
        failures: list[str] = []
        for company in companies:
            items: list[dict[str, Any]] = []
            try:
                for page in range(_MAX_PAGES):
                    url = (
                        f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
                        f"?limit={_PAGE_LIMIT}&offset={page * _PAGE_LIMIT}"
                    )
                    payload = fetch_json(url)
                    content = payload.get("content") or []
                    items.extend(content)
                    if len(content) < _PAGE_LIMIT:
                        break
                else:
                    logger.warning(
                        "smartrecruiters: %s hit the %d-page cap (%d postings read); "
                        "remaining postings were NOT read",
                        company,
                        _MAX_PAGES,
                        len(items),
                    )
            except Exception as exc:  # noqa: BLE001 — one bad board must not sink the run
                logger.warning("smartrecruiters: company %s failed: %s", company, exc)
                failures.append(f"{company}: {type(exc).__name__}: {exc}")
                continue
            boards.append({"company": company, "jobs": items})
        # Mirrors GAP-SRC-002 in the Greenhouse adapter: configured-but-all-failed
        # is a real outage, not an honest empty result. A board that fetched OK
        # with zero open roles keeps ``boards`` non-empty, so "fetched 0" stays ok.
        if companies and not boards:
            raise AdapterFetchError(
                f"smartrecruiters: all {len(companies)} configured company board(s) failed: "
                + "; ".join(failures)
            )
        return {"boards": boards}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for board in payload.get("boards", []):
            company_id = str(board.get("company", ""))
            for item in board.get("jobs", []):
                loc = item.get("location") or {}
                city = str(loc.get("city") or "")
                region = str(loc.get("region") or "")
                country = str(loc.get("country") or "")
                location = ", ".join(part for part in (city, region, country) if part)
                remote = bool(loc.get("remote"))

                # The postings list carries `ref` (API self-link) and the public
                # advert lives at jobs.smartrecruiters.com/<company>/<id>. Prefer
                # a real applyUrl when the payload supplies one; never invent one.
                apply_url = str(item.get("applyUrl") or "").strip()
                if not apply_url:
                    posting_id = str(item.get("id") or "").strip()
                    if not posting_id:
                        continue
                    apply_url = (
                        f"https://jobs.smartrecruiters.com/{company_id}/{posting_id}"
                    )

                company_name = str(
                    (item.get("company") or {}).get("name") or company_id.title()
                )
                jobs.append(
                    JobRaw(
                        title=str(item.get("name") or ""),
                        company=company_name,
                        location=location,
                        remote=remote or "remote" in location.lower(),
                        description=relevance.snippet(
                            (item.get("jobAd") or {})
                            .get("sections", {})
                            .get("jobDescription", {})
                            .get("text")
                            if isinstance(item.get("jobAd"), dict)
                            else None,
                            limit=relevance.DESCRIPTION_STORAGE_LIMIT,
                        ),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("releasedDate") or ""),
                    )
                )
        return relevance.filter_applicable(jobs)
