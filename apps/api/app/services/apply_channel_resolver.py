"""U5a — apply-channel resolution: HOW can this posting actually be applied to?

Ground truth this module is built on (submission-flow-automation-feasibility
scout, 2026-08-13, evidence ``uat/reports/evidence/agents-uplift/discovery/
submission-flow-domain-histogram-2026-08-13.json``): of 512 production
``Application`` rows, 102 point at ``jobs.ashbyhq.com``, 99 at a Greenhouse
board embedded on the employer's own domain (``?gh_jid=``), 42 at
``jobs.lever.co``, 39 at ``jobs.smartrecruiters.com`` — 55% direct ATS forms,
usually with no login. 199 point at Adzuna's own click-tracking redirector
(``/land/ad/*`` and ``/details/*``), which has to be followed once to learn the
real destination, and 24 are Seek postings.

Two rules are absolute here:

* **Seek is never automated.** ``docs/delivery/ADR-SEEK-V3.md`` (RULING:
  REFUSED, un-superseded, re-verified live 2026-08-13) found seek.com.au's
  robots.txt names an ``anthropic-ai`` user-agent group and Disallows
  ``*/job/`` by name. A Seek URL therefore resolves to ``seek-manual``, which
  is deliberately NOT in :data:`AUTOMATABLE_CHANNELS`.
* **A platform with no dedicated parser is never auto-submitted.**
  ORCHESTRATOR RULING U5-F3 (2026-08-14): ``lever``/``smartrecruiters``/
  ``generic`` resolve exactly as before, but they are ASSISTED, not automated —
  see :data:`AUTOMATABLE_CHANNELS` and :data:`ASSISTED_CHANNELS`.
* **An unresolved redirector is "unknown", never a guess.** Adzuna/CloudFront
  rate-limited this VM's egress IP with ``429 Retry-After: 3600`` during the
  scout's probe. A resolver that answered "probably Ashby" on a 429 would be
  fabricating; it answers ``unknown`` and CACHES that answer so a rate-limited
  window is not hammered further.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable
from urllib.parse import urlparse

from app.db import ensure_application_apply_channel_column, get_connection

logger = logging.getLogger(__name__)

#: Every channel this resolver can produce.
CHANNELS = frozenset(
    {
        "email",
        "ashby",
        "greenhouse",
        "lever",
        "smartrecruiters",
        "generic",
        "seek-manual",
        "unknown",
    }
)

#: Channels the apply-executor is allowed to drive a browser against.
#:
#: ORCHESTRATOR RULING U5-F3 (2026-08-14, binding, ``ORCHESTRATOR-RULING-U5-F3.md``):
#: ``lever``, ``smartrecruiters`` and ``generic`` were REMOVED. Only ``ashby``
#: and ``greenhouse`` have a dedicated dialect parser
#: (``apply_executor._parse_ashby`` / ``_parse_greenhouse``) pinned against a
#: captured real page; every other channel fell through to
#: ``_parse_generic``'s best-effort schema — i.e. an untested parser deciding
#: what to type into, and when to click submit on, a subscriber's REAL job
#: application. That is the worst failure mode this product has, so those
#: channels are ASSISTED instead (see :data:`ASSISTED_CHANNELS`). Dedicated
#: parsers + tests land in Track-2 slice U5c, after which they re-enter here
#: legitimately.
#:
#: ``seek-manual`` is excluded BY RULING (ADR-SEEK-V3), ``email`` belongs to
#: the existing W-SUB Gmail path, and ``unknown`` means we honestly do not know
#: where the application goes.
#:
#: The membership rule is enforced as an INVARIANT, not by convention:
#: ``tests/test_u5_invariant_sweep.py`` fails if any member of this set is
#: parsed by the generic fallback or lacks a real-page fixture + executor
#: tests. Adding a platform here without a parser is a failing test.
AUTOMATABLE_CHANNELS = frozenset({"ashby", "greenhouse"})

#: Channels whose destination we resolved EXACTLY and deliberately do not click
#: through: Aether prepares the tailored résumé + cover letter and hands the
#: user the direct application URL ("ready to submit — this platform needs your
#: click"). Honest and complete, rather than half-automated.
ASSISTED_CHANNELS = frozenset({"lever", "smartrecruiters", "generic"})

#: Channels that submit nothing here BY DEFINITION: ``email`` is the existing
#: W-SUB Gmail path's, ``seek-manual`` is refused by ADR-SEEK-V3, and
#: ``unknown`` means we could not resolve a destination at all. Split out so
#: the three dispositions PARTITION :data:`CHANNELS` — a new channel added
#: without a decision about how it is submitted fails the invariant sweep
#: instead of silently inheriting the "we don't know where this goes" copy.
TERMINAL_NON_SUBMITTING_CHANNELS = frozenset({"email", "seek-manual", "unknown"})

#: The platform's own name, for copy addressed to the user about where they
#: have to click. Never fabricates a name for an unrecognised code.
_PLATFORM_LABELS: dict[str, str] = {
    "ashby": "Ashby",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "smartrecruiters": "SmartRecruiters",
    "generic": "this employer's own form",
}


def platform_label(channel: str) -> str:
    """Human name of the platform behind ``channel`` (mirrors the FE's
    ``tracker-lib.ts`` ``platformLabel``)."""
    return _PLATFORM_LABELS.get(channel, "this employer's own form")

#: Hosts that ARE the final application system (the scout's live first-hop
#: resolution confirmed these shapes carry no redirector in front of them).
_ATS_HOSTS: tuple[tuple[str, str], ...] = (
    ("jobs.ashbyhq.com", "ashby"),
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("boards.eu.greenhouse.io", "greenhouse"),
    ("job-boards.eu.greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("jobs.eu.lever.co", "lever"),
    ("jobs.smartrecruiters.com", "smartrecruiters"),
    ("careers.smartrecruiters.com", "smartrecruiters"),
)

#: Seek hosts — matched on the registrable domain so every subdomain
#: (``au.seek.com``, ``www.seek.com.au``) is covered by the one refusal.
_SEEK_DOMAINS = ("seek.com.au", "seek.com", "seek.co.nz")

#: Adzuna's click-tracking redirector: the stored ``sourceUrl`` is Adzuna's
#: own link, not the employer's. Only these two path shapes are followed.
_ADZUNA_DOMAINS = ("adzuna.com.au", "adzuna.com", "adzuna.co.uk")
_ADZUNA_REDIRECT_PREFIXES = ("/land/ad", "/details")


def resolver_cache_ttl_seconds() -> float:
    """How long a redirector resolution (success OR failure) is trusted.

    ``AETHER_APPLY_RESOLVER_TTL_SECONDS`` tunes it without a redeploy; default
    6 hours. Long by design: a job posting's destination does not move, and the
    whole point of the cache is to stop us re-hitting a host that has already
    told us to back off.
    """
    raw = (os.environ.get("AETHER_APPLY_RESOLVER_TTL_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else 21600.0
    except ValueError:
        value = 21600.0
    return max(60.0, value)


def resolver_min_interval_seconds() -> float:
    """Minimum wall-clock gap between two OUTBOUND redirector fetches.

    Rate-consciousness at the process level, on top of the per-URL cache:
    resolving a backlog of 199 Adzuna links must not turn into 199 requests in
    one second against a host that already 429'd us once.
    ``AETHER_APPLY_RESOLVER_MIN_INTERVAL_SECONDS``, default 2s.
    """
    raw = (os.environ.get("AETHER_APPLY_RESOLVER_MIN_INTERVAL_SECONDS") or "").strip()
    try:
        value = float(raw) if raw else 2.0
    except ValueError:
        value = 2.0
    return max(0.0, value)


# ---------------------------------------------------------------------------
# Redirector resolution cache (process-local, TTL'd).
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
#: ``url -> (expires_at_monotonic, {"channel": str, "applyUrl": str | None})``
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_last_fetch_at: float = 0.0


def _cache_get(url: str) -> dict[str, Any] | None:
    with _cache_lock:
        entry = _cache.get(url)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            _cache.pop(url, None)
            return None
        return dict(value)


def _cache_put(url: str, value: dict[str, Any], ttl: float) -> None:
    with _cache_lock:
        _cache[url] = (time.monotonic() + max(1.0, ttl), dict(value))


def reset_resolution_cache() -> None:
    """Drop every cached redirector resolution (ops/test helper)."""
    with _cache_lock:
        _cache.clear()


def _default_http_get(url: str) -> dict[str, Any]:
    """One un-followed GET, used ONLY to read a redirector's ``Location``.

    Returns ``{"status": int, "location": str | None, "retry_after": int |
    None}``. Never raises: a transport failure is reported as status 0, which
    the caller turns into an honest ``unknown``.
    """
    global _last_fetch_at
    interval = resolver_min_interval_seconds()
    if interval:
        with _cache_lock:
            wait = _last_fetch_at + interval - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, interval))
    try:
        import httpx

        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": (
                        "AetherJobAgent/1.0 (+https://aether.jobs; applying on "
                        "behalf of the account owner)"
                    )
                },
            )
        retry_after_raw = response.headers.get("retry-after")
        try:
            retry_after = int(retry_after_raw) if retry_after_raw else None
        except ValueError:
            retry_after = None
        return {
            "status": int(response.status_code),
            "location": response.headers.get("location"),
            "retry_after": retry_after,
        }
    except Exception as exc:  # noqa: BLE001 — a transport failure is data, not a crash
        logger.info("apply-channel redirector fetch failed for %s: %s", url, type(exc).__name__)
        return {"status": 0, "location": None, "retry_after": None}
    finally:
        with _cache_lock:
            _last_fetch_at = time.monotonic()


# ---------------------------------------------------------------------------
# Classification.
# ---------------------------------------------------------------------------


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def _is_adzuna_redirector(url: str) -> bool:
    host = _host_of(url)
    if not any(_domain_matches(host, domain) for domain in _ADZUNA_DOMAINS):
        return False
    path = urlparse(url).path or ""
    return path.startswith(_ADZUNA_REDIRECT_PREFIXES)


def classify_url(url: str) -> str:
    """The channel a FINAL (already-resolved) posting URL belongs to.

    Never returns ``email`` (that is decided by the Job row, not the URL) and
    never follows anything — pure string classification.
    """
    if not url:
        return "unknown"
    host = _host_of(url)
    if not host:
        return "unknown"
    if any(_domain_matches(host, domain) for domain in _SEEK_DOMAINS):
        # ADR-SEEK-V3: REFUSED. Terminal classification, never automated.
        return "seek-manual"
    for ats_host, channel in _ATS_HOSTS:
        if _domain_matches(host, ats_host):
            return channel
    query = (urlparse(url).query or "").lower()
    if "gh_jid=" in query or "gh_src=" in query:
        # Greenhouse embedded on the employer's own domain — 99/512 of the
        # production histogram lives in this shape.
        return "greenhouse"
    if "/ashby_jid=" in query or "ashby_jid=" in query:
        return "ashby"
    return "generic"


def resolve_apply_channel(
    job: dict[str, Any], *, http_get: Callable[[str], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """``{"channel": …, "applyUrl": …}`` for one Job-row-shaped dict.

    Channel precedence (U-PLAN "U5 MANDATE SHARPENED" rule 2):

    1. ``job["applyEmail"]`` — the employer published an address, so the
       EXISTING W-SUB email path owns this application and this resolver does
       not re-derive anything.
    2. the stored ``sourceUrl``, classified by host; an Adzuna redirector is
       followed exactly ONCE (cached, rate-limited) and the destination is
       classified by the same rules.
    3. no URL and no address — ``unknown``. Honest, and actionable: the UI can
       tell the user this posting gives Aether nothing to submit to.
    """
    apply_email = (job.get("applyEmail") or "").strip() if job.get("applyEmail") else ""
    source_url = (job.get("sourceUrl") or "").strip() if job.get("sourceUrl") else ""
    if apply_email:
        return {"channel": "email", "applyUrl": source_url or None}
    if not source_url:
        return {"channel": "unknown", "applyUrl": None}
    if _is_adzuna_redirector(source_url):
        return _resolve_redirector(source_url, http_get=http_get)
    return {"channel": classify_url(source_url), "applyUrl": source_url}


def _resolve_redirector(
    url: str, *, http_get: Callable[[str], dict[str, Any]] | None
) -> dict[str, Any]:
    cached = _cache_get(url)
    if cached is not None:
        return cached
    fetch = http_get or _default_http_get
    try:
        response = fetch(url) or {}
    except Exception as exc:  # noqa: BLE001 — an injected fetcher must not crash a sweep
        logger.info("apply-channel redirector fetch raised for %s: %s", url, type(exc).__name__)
        response = {"status": 0, "location": None, "retry_after": None}
    status = int(response.get("status") or 0)
    location = response.get("location") or None
    ttl = resolver_cache_ttl_seconds()
    result: dict[str, Any]
    if status in (301, 302, 303, 307, 308) and location:
        result = {"channel": classify_url(str(location)), "applyUrl": str(location)}
        _cache_put(url, result, ttl)
        return result
    # 429 / 5xx / a 200 that never redirected: we do NOT know where this
    # posting actually lives. Say so, and remember saying so — re-asking a
    # host that just rate-limited us makes the rate limit worse.
    retry_after = response.get("retry_after")
    if status == 429 and isinstance(retry_after, (int, float)) and retry_after > 0:
        ttl = max(ttl, float(retry_after))
    result = {"channel": "unknown", "applyUrl": None}
    _cache_put(url, result, ttl)
    return result


def resolve_and_persist_apply_channel(
    user_id: str,
    application_id: str,
    job: dict[str, Any],
    *,
    http_get: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """:func:`resolve_apply_channel`, with the answer written onto the row.

    ``Application.applyChannel`` is what the sweep reads to decide which
    transmission path (if any) owns an approved application, so it is stored
    rather than recomputed per read — and it is stored exactly as computed,
    including ``unknown``.
    """
    result = resolve_apply_channel(job, http_get=http_get)
    ensure_application_apply_channel_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "applyChannel" = %s, "updatedAt" = NOW() '
                'WHERE "id" = %s AND "userId" = %s',
                (result["channel"], application_id, user_id),
            )
        conn.commit()
    return result
