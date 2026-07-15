"""Workable public job-board adapter — REAL job discovery, no API key (P5).

Workable serves each account's published jobs from a keyless POST search:
``POST https://apply.workable.com/api/v3/accounts/<sub>/jobs`` returning
``{"total": N, "results": [...]}``. Account subdomains are config-driven (see
:mod:`app.services.discovery.portals`).

The posting's real ``url`` (fallback ``application_url``) is stored as the
apply URL — zero fabrication. A board with no currently open roles simply
yields zero jobs (surfaced honestly by the scout's per-source status), and a
board whose fetch fails is skipped so one bad account never sinks the run.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.discovery import portals, relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json_post

logger = logging.getLogger(__name__)


class WorkableAdapter(BaseAdapter):
    """Live adapter over the keyless Workable v3 account jobs search."""

    source = "workable"

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        body = {
            "query": query or "",
            "location": [],
            "department": [],
            "worktype": [],
            "remote": [],
        }
        subs = portals.workable_accounts()
        accounts: list[dict[str, Any]] = []
        failures: list[str] = []
        for sub in subs:
            url = f"https://apply.workable.com/api/v3/accounts/{sub}/jobs"
            try:
                payload = fetch_json_post(url, body)
            except Exception as exc:  # noqa: BLE001 — one bad account must not sink the run
                logger.warning("workable: account %s failed: %s", sub, exc)
                failures.append(f"{sub}: {type(exc).__name__}: {exc}")
                continue
            results = payload.get("results", []) if isinstance(payload, dict) else []
            accounts.append({"sub": sub, "name": sub, "jobs": results})
        # GAP-SRC-002: accounts configured but EVERY one failed => total outage;
        # surface it as a real per-source error instead of an empty-but-ok
        # result. An account that fetched OK but has zero open roles keeps
        # ``accounts`` non-empty, so a genuine "fetched 0 jobs" stays status=ok.
        if subs and not accounts:
            raise AdapterFetchError(
                f"workable: all {len(subs)} configured account(s) failed: "
                + "; ".join(failures)
            )
        return {"accounts": accounts}

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
        jobs: list[JobRaw] = []
        for account in payload.get("accounts", []):
            sub = str(account.get("sub", ""))
            name = str(account.get("name") or sub)
            for item in account.get("jobs", []):
                apply_url = str(
                    item.get("url")
                    or item.get("application_url")
                    or item.get("shortlink")
                    or ""
                )
                if not apply_url:
                    continue
                loc = item.get("location") or {}
                if isinstance(loc, list):
                    loc = loc[0] if loc else {}
                if isinstance(loc, dict):
                    location = ", ".join(
                        str(part)
                        for part in (loc.get("city"), loc.get("region"), loc.get("country"))
                        if part
                    )
                    workplace = str(loc.get("workplaceType") or "").lower()
                else:
                    location = str(loc)
                    workplace = ""
                remote = (
                    bool(item.get("remote"))
                    or workplace == "remote"
                    or "remote" in location.lower()
                )
                jobs.append(
                    JobRaw(
                        title=str(item.get("title") or ""),
                        company=name,
                        location=location,
                        remote=remote,
                        description=relevance.snippet(item.get("description")),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("published_on") or item.get("created_at") or ""),
                    )
                )
        return relevance.filter_relevant(jobs)
