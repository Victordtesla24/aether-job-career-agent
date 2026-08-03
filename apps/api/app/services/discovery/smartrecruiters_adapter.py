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

Advert text lives behind a second request per posting (``/postings/{id}``), so
it is fetched under ONE per-sweep budget with bounded concurrency, spent first on
postings that do not already have their real description persisted — see
``_enrich_with_real_adverts`` (BLOCKER-SR-DETAIL). A posting the budget cannot
reach still persists, honestly, with no description.
"""
from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.services.discovery import description_cache, portals, relevance
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw
from app.services.discovery.live_http import fetch_json

logger = logging.getLogger(__name__)

SOURCE = "smartrecruiters"

#: SmartRecruiters caps ``limit`` at 100 per page and exposes ``offset``.
_PAGE_LIMIT = 100
#: Hard stop on pagination so one enormous board cannot stall a sweep. Recorded
#: rather than silent: exceeding it is logged (§"no silent caps").
_MAX_PAGES = 5

# --- per-posting DETAIL fetches (BLOCKER-SR-DETAIL) -------------------------
#
# The postings LIST carries no description at all (verified live 2026-08-02:
# list keys are name/location/company/ref/... with no jobAd), so the real text
# only exists on ``/postings/{id}``. Without it a SmartRecruiters row persists a
# 0-char description and the fit scorer's evidence gate (correctly) refuses to
# rank it — that row is invisible to the user forever.
#
# The first implementation capped detail fetches at 40 PER COMPANY and walked
# the API's own stable order, which starved everything past position 40 on every
# single sweep (Canva alone returns 133 applicable postings) and cost up to 160
# sequential blocking GETs (~116s) per sweep. Both properties are fixed here:
#
# * ONE budget for the whole sweep, spent first on postings whose description is
#   NOT already persisted, so successive sweeps converge to full coverage;
# * bounded concurrency plus a wall-clock deadline, so the cost is a handful of
#   seconds rather than two minutes;
# * randomised order within each priority bucket, so a posting that misses out
#   this sweep is not the same posting that misses out next sweep.
#
#: Company boards listed concurrently. Independent endpoints, one GET per page.
_BOARD_CONCURRENCY = 6
#: Detail GETs allowed per SWEEP across ALL boards (was 40 per company).
_DETAIL_BUDGET_PER_SWEEP = 120
#: Concurrent detail GETs. urllib releases the GIL while waiting on the socket.
_DETAIL_CONCURRENCY = 8
#: Wall-clock ceiling for the whole detail phase; postings not reached in time
#: persist without a description and are picked up on a later sweep.
_DETAIL_DEADLINE_SECONDS = 45.0
#: Per-request timeout for a detail GET — tighter than the 15s default so one
#: hung socket cannot eat the sweep deadline.
_DETAIL_TIMEOUT_SECONDS = 10

#: Key under which a posting carries advert text this system ALREADY fetched and
#: persisted on an earlier sweep (``description_cache``). It is REAL source text
#: — never generated, never a placeholder — and exists so that skipping a
#: redundant HTTP fetch does not re-persist the row with an empty description.
_PERSISTED_AD_KEY = "_aetherPersistedAdText"

#: Posting ids whose detail payload was fetched and genuinely had NO advert.
#: Process-local and best-effort (cleared on restart): it only DEPRIORITISES
#: those postings behind ones never tried, so budget is not spent re-reading
#: empty adverts while other postings have never been read at all. They are
#: still retried once the never-tried ones are done, because an employer can
#: publish the advert body later.
_NO_AD_POSTINGS: set[str] = set()
_NO_AD_MEMO_LIMIT = 5000


def _location_of(item: dict[str, Any]) -> str:
    loc = item.get("location") or {}
    return ", ".join(
        str(part)
        for part in (loc.get("city"), loc.get("region"), loc.get("country"))
        if part
    )


def configured_companies() -> list[str]:
    """Curated company identifiers (overridable via ``AETHER_SMARTRECRUITERS_COMPANIES``)."""
    return portals.smartrecruiters_companies()


def _ad_text(item: dict[str, Any]) -> str | None:
    """Real advert text from the DETAIL payload's jobAd sections.

    Joins the sections that describe the ROLE. Returns None when the ad is
    genuinely absent — an empty description is surfaced honestly and is then
    refused by the fit scorer's evidence gate rather than scored on nothing.
    """
    ad = item.get("jobAd")
    if not isinstance(ad, dict):
        return None
    sections = ad.get("sections") or {}
    parts = [
        (sections.get(name) or {}).get("text")
        for name in ("jobDescription", "qualifications", "additionalInformation")
    ]
    joined = "\n".join(p for p in parts if isinstance(p, str) and p.strip())
    return joined or None


def _persisted_ad_text(item: dict[str, Any]) -> str | None:
    """Advert text previously fetched from SmartRecruiters and persisted.

    Used ONLY when this sweep did not (re)fetch the posting's detail payload.
    Real source text, carried forward — the alternative is re-persisting the row
    with an empty description and undoing an earlier sweep's work.
    """
    text = item.get(_PERSISTED_AD_KEY)
    return text if isinstance(text, str) and text.strip() else None


def posting_apply_url(company_id: str, item: dict[str, Any]) -> str | None:
    """The posting's REAL apply URL, or None when it has no id to build one.

    The postings list carries ``ref`` (an API self-link); the public advert lives
    at ``jobs.smartrecruiters.com/<company>/<id>``. An explicit ``applyUrl`` in
    the payload always wins. A posting with neither is dropped rather than given
    a fabricated link.
    """
    apply_url = str(item.get("applyUrl") or "").strip()
    if apply_url:
        return apply_url
    posting_id = str(item.get("id") or "").strip()
    if not posting_id:
        return None
    return f"https://jobs.smartrecruiters.com/{company_id}/{posting_id}"


def _list_board(company: str) -> tuple[str, list[dict[str, Any]], str | None]:
    """Read one company's postings LIST (all pages).

    Returns ``(company, postings, error)``. A board that fails returns its error
    instead of raising, so one bad board never sinks the run and the failure is
    still reported per company (GAP-SRC-002).
    """
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
        return company, [], f"{type(exc).__name__}: {exc}"
    return company, items, None


def _rotate(entries: list[tuple[str, dict[str, Any]]]) -> None:
    """Randomise order so the postings that miss out on this sweep's budget are
    not the same postings that miss out on the next one."""
    random.shuffle(entries)


def _remember_no_ad(posting_id: str) -> None:
    if len(_NO_AD_POSTINGS) >= _NO_AD_MEMO_LIMIT:
        _NO_AD_POSTINGS.clear()
    _NO_AD_POSTINGS.add(posting_id)


def _fetch_details(queue: list[tuple[str, dict[str, Any]]]) -> tuple[int, int, int]:
    """Fetch ``/postings/{id}`` for each queued posting, concurrently.

    Merges the REAL ``jobAd`` into the posting in place. Returns
    ``(enriched, skipped_past_deadline, errors)``. A posting whose detail payload
    has no advert is left with none — never filled in from anywhere else.
    """
    if not queue:
        return 0, 0, 0
    deadline = time.monotonic() + _DETAIL_DEADLINE_SECONDS

    def _one(
        entry: tuple[str, dict[str, Any]],
    ) -> tuple[tuple[str, dict[str, Any]], Any, str]:
        company, item = entry
        if time.monotonic() >= deadline:
            return entry, None, "deadline"
        posting_id = str(item.get("id") or "").strip()
        try:
            detail = fetch_json(
                f"https://api.smartrecruiters.com/v1/companies/{company}"
                f"/postings/{posting_id}",
                timeout=_DETAIL_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — one posting must not sink the board
            logger.warning(
                "smartrecruiters: detail fetch failed for %s/%s: %s",
                company, posting_id, exc,
            )
            return entry, None, "error"
        ad = detail.get("jobAd") if isinstance(detail, dict) else None
        return entry, ad, "ok"

    enriched = skipped = errors = 0
    workers = max(1, min(_DETAIL_CONCURRENCY, len(queue)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sr-detail") as pool:
        for (_company, item), ad, outcome in pool.map(_one, queue):
            posting_id = str(item.get("id") or "").strip()
            if ad:
                item["jobAd"] = ad
            # A jobAd whose sections are all empty is still NO advert: it counts
            # as read-and-empty, not as enriched.
            if _ad_text(item):
                _NO_AD_POSTINGS.discard(posting_id)
                enriched += 1
            elif outcome == "ok":
                _remember_no_ad(posting_id)
            elif outcome == "deadline":
                skipped += 1
            else:
                errors += 1
    if skipped:
        logger.info(
            "smartrecruiters: %d detail fetch(es) skipped at the %.0fs sweep "
            "deadline — those postings persist without a description and are "
            "re-offered next sweep",
            skipped, _DETAIL_DEADLINE_SECONDS,
        )
    return enriched, skipped, errors


def _enrich_with_real_adverts(boards: list[dict[str, Any]]) -> None:
    """Give as many postings as the sweep budget allows their REAL advert text.

    Budget priority, highest first:

    1. postings with no description anywhere and never yet read;
    2. postings previously read whose advert was genuinely empty (an employer can
       publish the body later, so they are retried — just behind the untried).

    A posting whose real text is ALREADY persisted is never re-fetched: it is
    handed that text (``_PERSISTED_AD_KEY``) so re-persisting the row cannot wipe
    it, and it stops competing for budget. That is what makes coverage CONVERGE
    — each sweep spends the whole budget on postings that still have none — and
    it is what makes a converged board almost free to re-sweep.
    """
    targets: list[tuple[str, dict[str, Any], str]] = []
    for board in boards:
        company = str(board.get("company", ""))
        for item in board.get("jobs", []):
            if _ad_text(item):
                continue  # payload already carries the real advert
            url = posting_apply_url(company, item)
            if not url or not str(item.get("id") or "").strip():
                continue
            targets.append((company, item, url))
    if not targets:
        return

    persisted: dict[str, str] = {}
    try:
        persisted = description_cache.known_descriptions(
            SOURCE, [url for _company, _item, url in targets]
        )
    except Exception as exc:  # noqa: BLE001 — the lookup is an optimisation, not a gate
        logger.warning(
            "smartrecruiters: persisted-description lookup failed (%s: %s) — this "
            "sweep re-fetches instead of reusing",
            type(exc).__name__, exc,
        )

    never_read: list[tuple[str, dict[str, Any]]] = []
    read_but_empty: list[tuple[str, dict[str, Any]]] = []
    already_have = 0
    for company, item, url in targets:
        text = persisted.get(url)
        if text:
            item[_PERSISTED_AD_KEY] = text
            already_have += 1
        elif str(item.get("id") or "").strip() in _NO_AD_POSTINGS:
            read_but_empty.append((company, item))
        else:
            never_read.append((company, item))
    for bucket in (never_read, read_but_empty):
        _rotate(bucket)

    queue = (never_read + read_but_empty)[:_DETAIL_BUDGET_PER_SWEEP]
    fetched, _skipped, errors = _fetch_details(queue)

    still_empty = sum(
        1
        for _company, item, _url in targets
        if not _ad_text(item) and not _persisted_ad_text(item)
    )
    logger.info(
        "smartrecruiters: adverts — %d posting(s) needed text; %d served from "
        "already-persisted text (0 HTTP); %d fetched now (%d detail GET(s), %d "
        "failed); %d still have NO description and persist unranked",
        len(targets), already_have, fetched, len(queue), errors, still_empty,
    )


class SmartRecruitersAdapter(BaseAdapter):
    """Live adapter over the keyless SmartRecruiters postings API."""

    source = SOURCE

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        companies = configured_companies()
        boards: list[dict[str, Any]] = []
        failures: list[str] = []
        if not companies:
            return {"boards": []}
        # Boards are independent, so list them concurrently: 13 sequential board
        # listings cost ~11s of every sweep. ``pool.map`` preserves the
        # configured order, and each board still reports its OWN failure.
        workers = max(1, min(_BOARD_CONCURRENCY, len(companies)))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sr-board") as pool:
            listings = list(pool.map(_list_board, companies))
        for company, items, error in listings:
            if error is not None:
                logger.warning("smartrecruiters: company %s failed: %s", company, error)
                failures.append(f"{company}: {error}")
                continue
            # The list has no description. Keep ONLY postings a Melbourne
            # candidate could actually take, so no detail budget is spent on
            # roles that will be discarded anyway.
            applicable = [
                item
                for item in items
                if relevance.location_score(
                    _location_of(item), bool((item.get("location") or {}).get("remote"))
                )
                > 0
            ]
            boards.append({"company": company, "jobs": applicable})
        # Mirrors GAP-SRC-002 in the Greenhouse adapter: configured-but-all-failed
        # is a real outage, not an honest empty result. A board that fetched OK
        # with zero open roles keeps ``boards`` non-empty, so "fetched 0" stays ok.
        if companies and not boards:
            raise AdapterFetchError(
                f"smartrecruiters: all {len(companies)} configured company board(s) failed: "
                + "; ".join(failures)
            )
        # Descriptions are fetched for the WHOLE sweep at once, so the budget can
        # go to the postings that still lack one instead of the same first N of
        # every board (BLOCKER-SR-DETAIL).
        _enrich_with_real_adverts(boards)
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

                apply_url = posting_apply_url(company_id, item)
                if not apply_url:
                    continue

                company_name = str(
                    (item.get("company") or {}).get("name") or company_id.title()
                )
                jobs.append(
                    JobRaw(
                        title=str(item.get("name") or ""),
                        company=company_name,
                        location=location,
                        remote=remote or "remote" in location.lower(),
                        # Real advert from THIS sweep's detail fetch, else the
                        # real advert an earlier sweep already persisted for the
                        # same posting, else nothing at all — a posting whose ad
                        # is genuinely absent stays empty and unranked.
                        description=relevance.snippet(
                            _ad_text(item) or _persisted_ad_text(item),
                            limit=relevance.DESCRIPTION_STORAGE_LIMIT,
                        ),
                        requirements=[],
                        source=self.source,
                        sourceUrl=apply_url,
                        postedAt=str(item.get("releasedDate") or ""),
                    )
                )
        return relevance.filter_applicable(jobs)
