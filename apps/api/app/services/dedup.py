"""Job deduplication utilities (Phase 2A — NULL sourceUrl dedup fix).

The Prisma schema has @@unique([userId, sourceUrl]) but sourceUrl is nullable.
In PostgreSQL NULL != NULL, so the unique constraint DOES NOT PREVENT duplicates
with NULL sourceUrl. This module provides application-level dedup signals:

1. URL normalization — sourceUrl normalized before insert.
2. NULL-sourceUrl hash — composite hash closes the NULL != NULL gap.
3. Description-content hash — secondary dedup from first 500 chars.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "utm_reader", "fbclid", "igshid",
        "ref", "referrer", "referral",
        "gclid", "gclsrc", "msclkid", "dclid", "twclid",
        "mc_cid", "mc_eid", "oly_enc_id", "oly_anon_id",
        "_ga", "_gl",
        "source", "trk", "trkCampaign", "trackingId", "campaignId", "cmpid",
    }
)

_WWW_PREFIX = re.compile(r"^www\.", re.IGNORECASE)


def normalize_source_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return url.lower().strip()
    qsl = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    new_query = urlencode(qsl)
    hostname = (parsed.hostname or "").lower()
    hostname = _WWW_PREFIX.sub("", hostname)
    path = parsed.path.rstrip("/") or "/"
    scheme = parsed.scheme.lower() or "https"
    normalized = urlunparse((scheme, hostname, path, parsed.params, new_query, ""))
    return normalized.lower()


def compute_null_source_url_hash(
    user_id: str, title: str, company: str, location: str | None,
) -> str:
    key = (
        f"{user_id}|"
        f"{title.lower().strip()}|"
        f"{company.lower().strip()}|"
        f"{(location or '').lower().strip()}"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def compute_description_hash(description: str) -> str:
    normalized = description.strip()[:500]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
