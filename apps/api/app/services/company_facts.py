"""Bounded, cached company-facts fetch for cover-letter generation (AUD-COV-3).

DECISION (docs/delivery/evidence/RUN-20260818T0223Z/05-decision-memos/
AUD-COV-3.md): the cover-letter opener asserted a persuasive, company-specific
tone with zero real company research behind it — every "company-specific"
sentence was actually a restatement of the job posting's own language back at
the poster (AUD-COV-3/01-scout-reproduction.log). This module closes that gap
the reuse-over-rebuild way, per the memo's decision:

* the LIVE web fetch reuses the SAME Firecrawl credential/endpoint pattern
  ``app.services.discovery.seek_adapter`` already uses in production for job
  discovery (``ABACUS_API_KEY`` / ``FIRECRAWL_API_URL``) — no new integration;
* the fetched text is treated as UNTRUSTED external content and goes through
  the exact same sanitize/wrap/guard pipeline the job description already
  does in ``cover_letter_agent.py`` (sanitize_untrusted_text,
  wrap_untrusted_block, FabricationGuard corpus widening, the phrasing-based
  and phrasing-independent injection defenses) — never a weaker, bespoke
  guard for this one new input;
* a TTL cache (:mod:`app.repositories.company_facts`) means the SAME company
  is fetched live at most once per TTL window, not once per applicant;
* a HARD, tightly-bounded fetch timeout, and calling this BEFORE the cover
  agent opens its own dedicated LLM ``shared_budget`` window
  (``cover_letter_agent.get_cover_budget_seconds()``, ~88s of the ~100s HTTP
  edge — see cover_letter_agent.py run(), around the
  ``with shared_budget(...)`` block), means a slow or hanging fetch can NEVER
  eat into the LLM generation budget: the LLM window starts counting only
  after this step has already returned (successfully or not).

HONEST FALLBACK: any failure at any stage — the feature flag is off, no
Firecrawl credentials are configured, the live call errors or times out, or
the response carries nothing usable — returns ``None``. The caller
(``CoverLetterAgent.run``) never treats ``None`` as an error: with no facts,
the letter simply falls back to the JD-grounded ``hook_reason`` opener the
AUD-COV-1 fix already produces, with zero fabricated company claims. This
module never raises past :func:`fetch_company_facts` for exactly that reason.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.repositories.company_facts import CompanyFactsRepository
from app.services.discovery.seek_adapter import _get_abacus_credentials

logger = logging.getLogger(__name__)

#: Feature flag. Default ON — the memo requires "default ON only if
#: budget-safe", and the hard fetch timeout below (run entirely OUTSIDE the
#: cover-letter LLM budget window) is what makes it budget-safe by
#: construction, not by tuning. Set to "0"/"false"/"off" to disable.
_ENABLED_ENV = "AETHER_COVER_LETTER_RESEARCH_ENABLED"

#: Hard wall-clock ceiling for the LIVE fetch (network round trip only). Kept
#: small and deliberately separate from every LLM budget constant in
#: ``llm_client.py`` — this is not an LLM call and must never be confused with
#: one. Env-overridable; a bad value falls back to the default rather than
#: disabling the ceiling.
_ENV_TIMEOUT_SECONDS = "AETHER_COMPANY_FACTS_TIMEOUT_SECONDS"
_DEFAULT_TIMEOUT_SECONDS = 4.0

#: How long a cached company's facts stay fresh before a re-fetch is due.
_ENV_TTL_SECONDS = "AETHER_COMPANY_FACTS_TTL_SECONDS"
_DEFAULT_TTL_SECONDS = float(7 * 24 * 3600)  # 7 days

#: Fetched text is truncated to this many characters before it ever reaches
#: the cache, the prompt, or any guard — an unbounded scrape result must never
#: blow the prompt budget the way ``company_research_agent._MAX_NARRATIVE_
#: POSTINGS`` bounds postings for the same reason.
_MAX_FACTS_CHARS = 2000


@dataclass(frozen=True)
class CompanyFacts:
    """One company's researched facts, ready to enter the cover-letter prompt
    as untrusted context. ``source_url`` is what makes a citation traceable
    back to the fetch that produced it."""

    company: str
    facts: str
    source_url: str | None
    from_cache: bool


def research_enabled() -> bool:
    """Whether the bounded company-research fetch step is turned on at all."""
    return os.environ.get(_ENABLED_ENV, "1").strip().lower() not in (
        "0", "false", "off", "no",
    )


def _fetch_timeout_seconds() -> float:
    try:
        seconds = float(os.environ.get(_ENV_TIMEOUT_SECONDS, str(_DEFAULT_TIMEOUT_SECONDS)))
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    return seconds if seconds > 0 else _DEFAULT_TIMEOUT_SECONDS


def _ttl_seconds() -> float:
    try:
        seconds = float(os.environ.get(_ENV_TTL_SECONDS, str(_DEFAULT_TTL_SECONDS)))
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return seconds if seconds > 0 else _DEFAULT_TTL_SECONDS


def _scrape_company_facts(
    api_key: str, firecrawl_url: str, company: str, timeout: float
) -> tuple[str, str | None] | None:
    """One bounded live call to the SAME Firecrawl service seek_adapter.py
    uses (``/v1/search``, which returns a scraped result for a query — no new
    endpoint, no new credential). Returns ``(facts_text, source_url)`` or
    ``None`` on ANY failure — network error, timeout, non-2xx, malformed body,
    or an empty/unusable result. Never raises past this function; the hard
    ``timeout`` is passed straight to the transport so a hung upstream cannot
    hold the caller hostage past the budget the caller chose.
    """
    import httpx

    try:
        response = httpx.post(
            f"{firecrawl_url}/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "query": f"{company} company overview",
                "limit": 1,
                "scrapeOptions": {"formats": ["markdown"]},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.info("company_facts: live fetch failed for %r", company, exc_info=True)
        return None

    results = (payload or {}).get("data") or []
    if not results or not isinstance(results, list):
        return None
    top = results[0] or {}
    markdown = str(top.get("markdown") or top.get("description") or "").strip()
    if not markdown:
        return None
    source_url = str(top.get("url") or "").strip() or None
    return markdown[:_MAX_FACTS_CHARS], source_url


def fetch_company_facts(
    company: str, *, cache: CompanyFactsRepository | None = None
) -> CompanyFacts | None:
    """Bounded, cached fetch of real facts about ``company``.

    Order of checks, cheapest/safest first: the feature flag, then the TTL
    cache (no network at all on a warm hit), then live credentials, then the
    one bounded live call. Returns ``None`` at the first point the answer is
    "no facts available" — disabled, cold cache + no credentials, or a failed/
    empty live fetch — which is exactly the caller's honest-fallback signal.
    """
    company = (company or "").strip()
    if not company or not research_enabled():
        return None

    repo = cache or CompanyFactsRepository()
    cached = repo.get_fresh(company, ttl_seconds=_ttl_seconds())
    if cached is not None:
        return CompanyFacts(
            company=company,
            facts=str(cached.get("facts") or ""),
            source_url=cached.get("sourceUrl"),
            from_cache=True,
        )

    api_key, firecrawl_url = _get_abacus_credentials()
    if not api_key or not firecrawl_url:
        return None

    fetched = _scrape_company_facts(api_key, firecrawl_url, company, _fetch_timeout_seconds())
    if fetched is None:
        return None
    facts, source_url = fetched
    if not facts:
        return None
    repo.upsert(company, facts=facts, source_url=source_url)
    return CompanyFacts(company=company, facts=facts, source_url=source_url, from_cache=False)
