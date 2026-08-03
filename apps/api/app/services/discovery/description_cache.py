"""Reuse of advert text this system has ALREADY fetched and persisted.

WHY THIS EXISTS (BLOCKER-SR-DETAIL)
-----------------------------------
Some ATS APIs (SmartRecruiters is the worst offender) omit the advert text from
the postings LIST, so the real description only exists behind one extra HTTP GET
per posting. That is a hard budget: a sweep cannot afford hundreds of blocking
requests, so some postings go un-enriched on any given sweep.

The un-enriched ones must not be RE-fetched forever while others starve. This
module answers the only question that makes the budget converge: *which of these
postings do we already hold the real advert text for?* The answer comes from the
``Job`` table — text that was genuinely fetched from the source on an earlier
sweep and persisted. Nothing here invents, guesses or paraphrases a description:
a URL with no persisted text simply does not appear in the result, and the
caller then spends real budget on it.

The lookup is deliberately NOT scoped to one user. A job advert is public text
belonging to the posting, not to a user; a second user discovering the same
posting gets the text that was already paid for rather than a starved 0-char row
(and no user data crosses accounts — only ``Job.description``, which is the
employer's own published advert).
"""
from __future__ import annotations

import logging
from typing import Iterable

from app.db import get_connection
from app.services.dedup import normalize_source_url

logger = logging.getLogger(__name__)

#: Safety bound on one IN-list. A sweep offers a few hundred URLs at most; this
#: exists so a pathological caller cannot build a multi-megabyte query.
MAX_URLS_PER_LOOKUP = 2000


def known_descriptions(source: str, urls: Iterable[str]) -> dict[str, str]:
    """Map each apply URL that ALREADY has a real persisted description to it.

    Keys are the URLs exactly as passed in (matching is done on the same
    normalised form the repository stores). URLs with no row, or whose only rows
    carry an empty description — precisely the starved rows this exists to fix —
    are absent from the result.

    Raises on a database failure; callers treat the lookup as an optimisation
    and degrade to fetching, never to a dead sweep.
    """
    by_normalized: dict[str, list[str]] = {}
    for url in urls:
        normalized = normalize_source_url(url)
        if normalized:
            by_normalized.setdefault(normalized, []).append(url)
    if not by_normalized:
        return {}

    keys = list(by_normalized)
    if len(keys) > MAX_URLS_PER_LOOKUP:
        logger.warning(
            "description_cache: %d URLs offered for %s, looking up the first %d",
            len(keys), source, MAX_URLS_PER_LOOKUP,
        )
        keys = keys[:MAX_URLS_PER_LOOKUP]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT DISTINCT ON ("sourceUrl") "sourceUrl", "description" '
                'FROM "Job" '
                'WHERE "source" = %s AND "sourceUrl" = ANY(%s) '
                "AND length(btrim(\"description\")) > 0 "
                'ORDER BY "sourceUrl", "updatedAt" DESC',
                (source, keys),
            )
            rows = cur.fetchall()

    found: dict[str, str] = {}
    for normalized, description in rows:
        for original in by_normalized.get(normalized, ()):
            found[original] = description
    return found
