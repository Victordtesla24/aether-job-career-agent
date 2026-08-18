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
  ORCHESTRATOR RULING U5-F3 (2026-08-14): ``smartrecruiters``/``generic``
  resolve exactly as before and are ASSISTED, not automated. ``lever``
  re-entered :data:`AUTOMATABLE_CHANNELS` at SUB-011 (Track-2 U5c) once its
  own dedicated parser + fixture-backed tests existed — see
  :data:`AUTOMATABLE_CHANNELS` and :data:`ASSISTED_CHANNELS`.
* **An unresolved redirector is "unknown", never a guess.** Adzuna/CloudFront
  rate-limited this VM's egress IP with ``429 Retry-After: 3600`` during the
  scout's probe. A resolver that answered "probably Ashby" on a 429 would be
  fabricating; it answers ``unknown`` and CACHES that answer so a rate-limited
  window is not hammered further.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

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
#: ``lever``, ``smartrecruiters`` and ``generic`` were REMOVED because none of
#: them had a dedicated dialect parser (only ``apply_executor._parse_ashby`` /
#: ``_parse_greenhouse`` existed) pinned against a captured real page — every
#: other channel fell through to ``_parse_generic``'s best-effort schema, i.e.
#: an untested parser deciding what to type into, and when to click submit on,
#: a subscriber's REAL job application. That is the worst failure mode this
#: product has, so those channels went ASSISTED instead (see
#: :data:`ASSISTED_CHANNELS`). The ruling named this Track-2 slice U5c:
#: dedicated parsers + fixture-backed tests, after which a channel re-enters
#: here legitimately. ``lever`` did that at SUB-011 —
#: ``apply_executor._parse_lever`` pinned against two real captured
#: ``jobs.lever.co`` ``/apply`` pages (``tests/fixtures/apply_pages/lever_
#: application_real.html`` / ``lever_custom_question_real.html``) — and is
#: back here. ``smartrecruiters``/``generic`` still have no dedicated parser
#: and stay in :data:`ASSISTED_CHANNELS`.
#:
#: ``seek-manual`` is excluded BY RULING (ADR-SEEK-V3), ``email`` belongs to
#: the existing W-SUB Gmail path, and ``unknown`` means we honestly do not know
#: where the application goes.
#:
#: The membership rule is enforced as an INVARIANT, not by convention:
#: ``tests/test_u5_invariant_sweep.py`` fails if any member of this set is
#: parsed by the generic fallback or lacks a real-page fixture + executor
#: tests. Adding a platform here without a parser is a failing test.
AUTOMATABLE_CHANNELS = frozenset({"ashby", "greenhouse", "lever"})

#: Channels whose destination we resolved EXACTLY and deliberately do not click
#: through: Aether prepares the tailored résumé + cover letter and hands the
#: user the direct application URL ("ready to submit — this platform needs your
#: click"). Honest and complete, rather than half-automated.
ASSISTED_CHANNELS = frozenset({"smartrecruiters", "generic"})

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


# ---------------------------------------------------------------------------
# SUB-006 — Greenhouse canonicalisation.
# ---------------------------------------------------------------------------

#: The ONE Greenhouse surface that serves a real, server-rendered application
#: form. ``boards.greenhouse.io`` 301s to ``job-boards.greenhouse.io`` (live
#: 2026-08-17); both are in :data:`_ATS_HOSTS`, and the redirect is followed by
#: the fetcher, so the stored/disclosed URL stays the canonical one.
GREENHOUSE_EMBED_TEMPLATE = (
    "https://boards.greenhouse.io/embed/job_app?for={board}&token={token}"
)

#: The honest refusal when no candidate board slug produced a real form.
#: Deliberately its OWN reason code rather than being folded into
#: ``submit_control_not_found``: that code says "we filled a form and could not
#: submit it", which is a different (and, for this shape, false) story.
GREENHOUSE_UNRESOLVABLE_REASON = "greenhouse_form_unresolvable"

#: How many DISTINCT board slugs may be verified for one posting. Each costs an
#: outbound GET, and a slug we cannot derive in the first few tries is one we
#: should refuse honestly rather than brute-force against Greenhouse.
_GREENHOUSE_MAX_CANDIDATES = 3

#: Minimum number of VISIBLE (non-hidden) controls a ``<form>`` must contain
#: before this module will call it an application form.
#:
#: Calibrated on measurements, not taste (live probe 2026-08-17,
#: ``uat/reports/evidence/models-live/sub-006-gh-canonical/
#: live-probe-2026-08-17.json``): the real Databricks embed form carries 35
#: visible controls (36 in the 2026-08-13 capture), a wrong board slug answers
#: 404 with 0 forms, and the employer microsite serves 0 forms. The floor sits
#: above the marketing-widget shape (a one-input search or newsletter box) so
#: a stray form on an error page can never be mistaken for an application.
_GREENHOUSE_MIN_FORM_CONTROLS = 3

#: Subdomain labels that name the careers SITE, not the employer, and so must
#: be stripped before the host is used as a board-slug candidate.
_CAREERS_SUBDOMAIN_LABELS = frozenset(
    {"www", "www2", "careers", "career", "jobs", "job", "apply", "boards", "hire", "hiring"}
)

#: Hosts that ARE Greenhouse. A URL already on one of these needs no
#: canonicalisation (and must not be fetched to discover that).
_GREENHOUSE_HOSTS = tuple(host for host, channel in _ATS_HOSTS if channel == "greenhouse")

#: Prefix for the resolution cache so a canonicalisation can never collide with
#: a redirector resolution stored under the same posting URL.
_GREENHOUSE_CACHE_PREFIX = "gh-canonical:"

#: Cap on how much of a candidate page is read. The real embed form is ~91KB;
#: 2MB is generous for it and still bounded against a pathological response.
_GREENHOUSE_MAX_BYTES = 2_000_000


def _is_greenhouse_host(host: str) -> bool:
    return any(_domain_matches(host, domain) for domain in _GREENHOUSE_HOSTS)


def greenhouse_token(url: str) -> str | None:
    """The Greenhouse job token in ``url``, or ``None``.

    Three real shapes: ``?gh_jid=<token>`` (the employer-embedded posting —
    99/512 production rows), ``?token=<token>`` on an embed URL, and
    ``/<board>/jobs/<token>`` on a Greenhouse board. Never invented: a URL that
    carries no token gets ``None``, which the caller turns into an honest
    refusal rather than a guess.
    """
    if not url:
        return None
    parsed = urlparse(url)
    params = parse_qs(parsed.query or "")
    for key in ("gh_jid", "token"):
        for raw in params.get(key, []):
            candidate = (raw or "").strip()
            if candidate:
                return candidate
    match = re.search(r"/jobs/(\d+)", parsed.path or "")
    if match:
        return match.group(1)
    return None


def _board_from_embed_config(page_html: str | None) -> str | None:
    """The board slug an employer page's own Greenhouse embed declares.

    Authoritative when present — it is the employer telling us which board the
    posting lives on. Absent for a page whose embed is injected client-side
    (the live Databricks probe carried only the ``div#grnhse_app`` mount point
    and no slug at all), which is exactly why a fallback candidate exists.
    """
    if not page_html:
        return None
    match = re.search(
        r"job_board/js\?[^\"'<>]*\bfor=([A-Za-z0-9_-]+)", page_html
    )
    if match:
        return match.group(1)
    match = re.search(
        r"grnhse_settings\s*=\s*\{[^}]*?['\"]for['\"]\s*:\s*['\"]([A-Za-z0-9_-]+)",
        page_html,
    )
    if match:
        return match.group(1)
    return None


def _board_candidates(url: str, page_html: str | None) -> tuple[str, ...]:
    """Board slugs worth VERIFYING for ``url``, best-evidence first.

    Order is evidence quality, not convenience: an explicit ``for=`` on the
    posting URL, then the employer page's own embed config, then a guess
    derived from the employer's host. The guess is only ever a CANDIDATE — it
    reaches the plan only if fetching its embed URL shows a real form.
    """
    candidates: list[str] = []

    def add(value: str | None) -> None:
        slug = (value or "").strip().lower()
        if slug and slug not in candidates:
            candidates.append(slug)

    parsed = urlparse(url)
    for raw in parse_qs(parsed.query or "").get("for", []):
        add(raw)
    add(_board_from_embed_config(page_html))

    host = _host_of(url)
    labels = [label for label in host.split(".") if label]
    while labels and labels[0] in _CAREERS_SUBDOMAIN_LABELS:
        labels.pop(0)
    if len(labels) >= 2:
        # The registrable label: `databricks.com` -> `databricks`. Greenhouse
        # board slugs are overwhelmingly the company's own name, which is why
        # this is worth ONE verified attempt — and why it is never trusted.
        add(labels[0])
        if "-" in labels[0]:
            add(labels[0].replace("-", ""))
    return tuple(candidates[:_GREENHOUSE_MAX_CANDIDATES])


def greenhouse_form_present(html: str) -> bool:
    """Whether ``html`` really contains a Greenhouse application form.

    THE VERIFICATION GATE. Structural, not textual: at least one ``<form>``
    holding at least :data:`_GREENHOUSE_MIN_FORM_CONTROLS` visible controls.
    A 404 board page, an error page and the employer's own formless microsite
    all fail it, which is the entire point — this function is what stands
    between "we derived a URL" and "we will type a real person's application
    into it".
    """
    if not html or "<form" not in html.lower():
        return False
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for form in soup.find_all("form"):
        controls = [
            control
            for control in form.find_all(["input", "select", "textarea"])
            if str(control.get("type") or "").lower() != "hidden"
        ]
        if len(controls) >= _GREENHOUSE_MIN_FORM_CONTROLS:
            return True
    return False


def _default_greenhouse_fetch_html(url: str) -> dict[str, Any]:
    """One bounded, READ-ONLY GET of a Greenhouse embed URL.

    Returns ``{"status": int, "html": str}``. Never raises and never submits:
    it opens a public job-application page, reads at most
    :data:`_GREENHOUSE_MAX_BYTES` of it and closes. Redirects ARE followed
    (``boards.greenhouse.io`` 301s to ``job-boards.greenhouse.io``) but only
    within Greenhouse's own hosts — a redirect that leaves Greenhouse is
    reported as status 0, i.e. unverified, rather than read.
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

        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": (
                        "AetherJobAgent/1.0 (+https://aether.jobs; applying on "
                        "behalf of the account owner)"
                    )
                },
            )
        final_host = (response.url.host or "").lower() if response.url else ""
        if not _is_greenhouse_host(final_host):
            logger.info(
                "greenhouse canonicalisation left greenhouse (%s) — not read", final_host
            )
            return {"status": 0, "html": ""}
        return {
            "status": int(response.status_code),
            "html": response.text[:_GREENHOUSE_MAX_BYTES],
        }
    except Exception as exc:  # noqa: BLE001 — a transport failure is data, not a crash
        logger.info(
            "greenhouse canonicalisation fetch failed for %s: %s", url, type(exc).__name__
        )
        return {"status": 0, "html": ""}
    finally:
        with _cache_lock:
            _last_fetch_at = time.monotonic()


def resolve_greenhouse_apply_url(
    url: str,
    *,
    page_html: str | None = None,
    fetch_html: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a Greenhouse posting URL to the form that actually exists.

    SUB-006. The stored ``sourceUrl`` for 99/512 production applications is the
    EMPLOYER's own page carrying ``?gh_jid=<token>``. Live probe 2026-08-17
    (read-only GET, evidence
    ``uat/reports/evidence/models-live/sub-006-gh-canonical/
    live-probe-2026-08-17.json``): that page answers 200 with 700,675 bytes and
    **zero ``<form>`` elements** — the application UI is a ``div#grnhse_app``
    that Greenhouse's JS mounts client-side. Navigating a browser there can end
    exactly one way: ``submit_control_not_found``. Meanwhile
    ``boards.greenhouse.io/embed/job_app?for=<board>&token=<token>`` serves the
    real server-rendered form (1 form / 35 visible controls).

    So this function derives ``<board>``, and then — because a wrong slug
    answers 404 (also measured) — it VERIFIES the candidate by fetching it and
    requiring a real form before returning it. Nothing is navigated on faith.

    Returns::

        {"originalUrl", "resolvedUrl" | None, "board" | None, "token" | None,
         "verified": bool, "reason": None | GREENHOUSE_UNRESOLVABLE_REASON,
         "detail": str, "candidates": tuple[str, ...]}

    ``reason`` set means REFUSE: the caller must record the manual step and
    must not open a browser. ``resolvedUrl`` equal to ``originalUrl`` with
    ``verified`` false means "already a Greenhouse-hosted URL, nothing to
    canonicalise" — no fetch is performed for that case.
    """
    original = (url or "").strip()
    base: dict[str, Any] = {
        "originalUrl": original,
        "resolvedUrl": None,
        "board": None,
        "token": None,
        "verified": False,
        "reason": None,
        "detail": "",
        "candidates": (),
    }
    if not original:
        return {
            **base,
            "reason": GREENHOUSE_UNRESOLVABLE_REASON,
            "detail": (
                "This application has no posting URL, so Aether could not find "
                "a Greenhouse application form for it. Nothing was submitted."
            ),
        }
    if _is_greenhouse_host(_host_of(original)):
        return {
            **base,
            "resolvedUrl": original,
            "token": greenhouse_token(original),
            "detail": "Already a Greenhouse-hosted URL — no canonicalisation needed.",
        }

    cache_key = _GREENHOUSE_CACHE_PREFIX + original
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    token = greenhouse_token(original)
    if not token:
        result = {
            **base,
            "reason": GREENHOUSE_UNRESOLVABLE_REASON,
            "detail": (
                f"This posting ({original}) carries no Greenhouse job token, so "
                "Aether could not find the real application form for it and did "
                "not submit anything. Open the posting and apply there."
            ),
        }
        _cache_put(cache_key, result, resolver_cache_ttl_seconds())
        return result

    candidates = _board_candidates(original, page_html)
    fetch = fetch_html or _default_greenhouse_fetch_html
    for board in candidates:
        candidate_url = GREENHOUSE_EMBED_TEMPLATE.format(board=board, token=token)
        try:
            response = fetch(candidate_url) or {}
        except Exception as exc:  # noqa: BLE001 — an injected fetcher must not crash a sweep
            logger.info(
                "greenhouse canonicalisation fetch raised for %s: %s",
                candidate_url,
                type(exc).__name__,
            )
            continue
        status = int(response.get("status") or 0)
        html = str(response.get("html") or "")
        if status == 200 and greenhouse_form_present(html):
            result = {
                **base,
                "resolvedUrl": candidate_url,
                "board": board,
                "token": token,
                "verified": True,
                "candidates": candidates,
                "detail": (
                    f"Resolved {original} to the Greenhouse application form at "
                    f"{candidate_url} (verified: the page really serves a form)."
                ),
            }
            _cache_put(cache_key, result, resolver_cache_ttl_seconds())
            return result
        logger.info(
            "greenhouse candidate %s rejected by the form gate (status=%s)",
            candidate_url,
            status,
        )

    result = {
        **base,
        "token": token,
        "candidates": candidates,
        "reason": GREENHOUSE_UNRESOLVABLE_REASON,
        "detail": (
            f"This Greenhouse posting ({original}) hosts no application form of "
            "its own, and Aether could not verify which Greenhouse board it "
            "belongs to, so it did not submit anything. Open the posting and "
            "apply there."
        ),
    }
    _cache_put(cache_key, result, resolver_cache_ttl_seconds())
    return result


def resolve_ingest_redirect(
    url: str, *, http_get: Callable[[str], dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """Ingest-time redirect-follow for a raw Adzuna redirector URL (SUB-009).

    Adzuna's live API has NO direct-employer-URL field — every result carries
    only ``redirect_url``, Adzuna's own click-tracking link (verified live,
    ``docs/delivery/evidence/RUN-20260818T0223Z/SUB-009/adzuna_live_call.json``:
    27,445 live results, every one missing a ``url`` field). Until now
    ``adzuna_adapter._parse`` had no choice but to store that redirector
    verbatim as ``Job.sourceUrl`` — there was no resolution anywhere in
    ingest, so the 429-prone redirector was the ONLY URL ever handed to the
    apply path.

    This is the scout's ingest-time entry point into resolution. It reuses
    THIS module's cache and rate-limiting (:func:`_resolve_redirector`) —
    there is deliberately no second cache, no second resolver, no second
    rate limit to keep in sync with this one.

    Returns ``None`` for a URL that is not an Adzuna redirector shape (nothing
    to do) OR whose resolution attempt did not land on a real destination —
    429, timeout, or a response that never redirected. The caller MUST NOT
    invent a fallback value in that case (NON-NEGOTIABLE-CONSTRAINTS rule 1):
    the job is ingested with its honest, unresolved ``sourceUrl`` and no
    resolution columns are written. On a genuine resolution it returns
    ``{"resolvedApplyUrl": str, "resolvedApplyUrlSource":
    "adzuna_redirect_follow"}``, ready to merge onto the ``JobRaw`` before it
    is persisted — never onto ``sourceUrl`` itself, so the original posting
    link is never overwritten by its own resolution.
    """
    if not _is_adzuna_redirector(url):
        return None
    outcome = _resolve_redirector(url, http_get=http_get)
    resolved_url = outcome.get("applyUrl")
    if outcome.get("channel") == "unknown" or not resolved_url:
        return None
    return {
        "resolvedApplyUrl": str(resolved_url),
        "resolvedApplyUrlSource": "adzuna_redirect_follow",
    }


#: A ``jobs.lever.co`` posting's own "Apply for this job" button (SUB-011
#: scout evidence, confirmed against two live captures) points at exactly
#: ``<posting>/apply`` — never anywhere else. Matched against the URL's PATH
#: only (an optional trailing slash tolerated) so a ``sourceUrl`` that is
#: ALREADY the apply page is recognised regardless of its query string.
_LEVER_APPLY_SUFFIX = re.compile(r"/apply/?$")


def _derive_apply_url(channel: str, url: str) -> str:
    """The URL the automation actually opens, per channel quirks.

    Lever's own bare posting page (``jobs.lever.co/<company>/<uuid>``, no
    ``/apply`` suffix) carries NO ``<form>`` at all (SUB-011 scout evidence,
    confirmed live: ``grep -o '<form[^>]*>' base.html`` -> no output) — it is
    a description/marketing page only. A ``Job.sourceUrl`` that is the bare
    posting URL is the COMMON case (that is what a job board or an employer
    link normally points at), so handing it straight to the executor would
    make :func:`app.services.apply_executor.parse_form_schema` read a page
    with no form on it at all. Appended here, once, for every caller —
    idempotent: a URL that already carries an ``/apply`` path segment (the
    less common case — the sourceUrl already IS the apply page) is returned
    unchanged, so a correct URL is never doubled up into
    ``.../apply/apply``.
    """
    if channel != "lever" or not url:
        return url
    if _LEVER_APPLY_SUFFIX.search(urlparse(url).path or ""):
        return url
    return url.rstrip("/") + "/apply"


def resolve_apply_channel(
    job: dict[str, Any], *, http_get: Callable[[str], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """``{"channel": …, "applyUrl": …}`` for one Job-row-shaped dict.

    Channel precedence (U-PLAN "U5 MANDATE SHARPENED" rule 2, extended by
    SUB-009 rule 2 below):

    1. ``job["applyEmail"]`` — the employer published an address, so the
       EXISTING W-SUB email path owns this application and this resolver does
       not re-derive anything.
    2. ``job["resolvedApplyUrl"]`` — an ingest-time resolution already
       recorded on the row (:func:`resolve_ingest_redirect`, called from the
       scout's ingest loop). Classified directly, with NO live hop: the whole
       point of resolving a redirector once at ingest is that the apply path
       — the moment a real submission is being prepared — never has to pay
       that redirector's rate limit again for a posting already resolved.
    3. the stored ``sourceUrl``, classified by host; an Adzuna redirector that
       was NOT already resolved at ingest is followed exactly ONCE here
       (cached, rate-limited) and the destination is classified by the same
       rules.
    4. no URL and no address — ``unknown``. Honest, and actionable: the UI can
       tell the user this posting gives Aether nothing to submit to.
    """
    apply_email = (job.get("applyEmail") or "").strip() if job.get("applyEmail") else ""
    source_url = (job.get("sourceUrl") or "").strip() if job.get("sourceUrl") else ""
    resolved_url = (
        (job.get("resolvedApplyUrl") or "").strip() if job.get("resolvedApplyUrl") else ""
    )
    if apply_email:
        return {"channel": "email", "applyUrl": source_url or None}
    if resolved_url:
        return {"channel": classify_url(resolved_url), "applyUrl": resolved_url}
    if not source_url:
        return {"channel": "unknown", "applyUrl": None}
    if _is_adzuna_redirector(source_url):
        return _resolve_redirector(source_url, http_get=http_get)
    channel = classify_url(source_url)
    return {"channel": channel, "applyUrl": _derive_apply_url(channel, source_url)}


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
        resolved_channel = classify_url(str(location))
        result = {
            "channel": resolved_channel,
            "applyUrl": _derive_apply_url(resolved_channel, str(location)),
        }
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
