"""Job deduplication utilities (Phase 2A — NULL sourceUrl dedup fix).

The Prisma schema has @@unique([userId, sourceUrl]) but sourceUrl is nullable.
In PostgreSQL NULL != NULL, so the unique constraint DOES NOT PREVENT duplicates
with NULL sourceUrl. This module provides application-level dedup signals:

1. **URL normalization** — sourceUrl is normalized (strip tracking params,
   lowercase, remove trailing slashes, strip www. prefix) before insert so
   the DB-level unique constraint catches more cases.

2. **NULL-sourceUrl hash** — jobs without sourceUrl get a composite hash of
   (userId + title + company + location). This hash is stored in the
   ``dedupHash`` column on the Job table, and we check for duplicates before
   inserting, closing the NULL != NULL gap.

3. **Description-content hash** — a secondary dedup signal computed from the
   first 500 characters of the description. Stored in ``contentHash`` to
   catch minor title/description variations of the same job.

Both ``dedupHash`` and ``contentHash`` are additive columns introduced via
lazy DDL (ADR-TR-1) — no migration runner is needed.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Tracking / analytics query parameters to strip during URL normalization.
# These are purely for click tracking and don't identify the job uniquely.
# ---------------------------------------------------------------------------
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        # Google Analytics / UTM
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_reader",
        # Facebook / Instagram
        "fbclid",
        "igshid",
        # Other common tracking
        "ref",
        "referrer",
        "referral",
        "gclid",       # Google Ads
        "gclsrc",      # Google Ads source
        "msclkid",     # Microsoft Ads
        "dclid",       # Display & Video 360
        "twclid",      # Twitter Ads
        "mc_cid",      # Mailchimp campaign ID
        "mc_eid",      # Mailchimp email ID
        "oly_enc_id",  # Omeda
        "oly_anon_id", # Omeda
        "_ga",         # Google Analytics
        "_gl",         # Google Analytics cross-domain
        # Generic tracking
        "source",
        "trk",
        "trkCampaign",
        "trackingId",
        "campaignId",
        "cmpid",
    }
)

#: Common www-prefix pattern for URL normalization.
_WWW_PREFIX = re.compile(r"^www\.", re.IGNORECASE)


def normalize_source_url(url: str | None) -> str | None:
    """Normalize a sourceUrl for dedup.

    Transformations applied:
    1. Strip tracking query parameters (utm_*, fbclid, ref, etc.)
    2. Lowercase the entire URL
    3. Remove trailing slashes from the path
    4. Strip ``www.`` prefix from the hostname

    Returns None if the input is None or empty.
    """
    if not url:
        return None

    url = url.strip()
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return url.lower().strip()

    # Strip tracking query params
    qsl = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    new_query = urlencode(qsl)

    # Normalize hostname: lowercase and strip www.
    hostname = (parsed.hostname or "").lower()
    hostname = _WWW_PREFIX.sub("", hostname)

    # Normalize path: remove trailing slash unless it's just "/"
    path = parsed.path.rstrip("/") or "/"

    # Reconstruct the URL (always use https for consistency; source adapters
    # should already provide https URLs)
    scheme = parsed.scheme.lower() or "https"

    normalized = urlunparse(
        (scheme, hostname, path, parsed.params, new_query, "")
    )
    return normalized.lower()


def compute_null_source_url_hash(
    user_id: str,
    title: str,
    company: str,
    location: str | None,
) -> str:
    """Compute a dedup hash for jobs that lack a source URL.

    The hash is sha256 of the normalized composite key:
    ``userId | title_lower_stripped | company_lower_stripped | location_lower_stripped``

    Two jobs from the same user with the same title, company, and location
    will produce the same hash, closing the NULL != NULL gap in the DB-level
    unique constraint.
    """
    key = (
        f"{user_id}|"
        f"{title.lower().strip()}|"
        f"{company.lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compute_description_hash(description: str) -> str:
    """Compute a secondary dedup hash from the job description.

    Uses the first 500 characters (after stripping whitespace) so minor
    variations in the full description text still produce the same hash.
    This catches near-duplicate postings that may have slightly different
    titles or locations.
    """
    normalized = description.strip()[:500]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
