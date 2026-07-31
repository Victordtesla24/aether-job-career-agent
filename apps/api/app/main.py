"""Aether API application entrypoint (P1-S09).

Builds the FastAPI app via a ``create_app`` factory (so tests can construct an
isolated instance) and mounts the routers. The module-level ``app`` is what
``uvicorn app.main:app`` serves.
"""
from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.rate_limit import (
    SlidingWindowRateLimiter,
    build_login_rate_limiter,
    build_register_rate_limiter,
)
from app.routers import (
    admin,
    agents,
    analytics,
    applications,
    approvals,
    auth,
    billing,
    cover_letters,
    emails,
    google_oauth,
    health,
    interviews,
    jobs,
    networking,
    offers,
    resumes,
    stories,
    workspaces,
)
from app.services.llm_client import get_mode
from app.services.resume_grounding import MissingResumeError


def apply_email_domain_allowlist() -> frozenset[str]:
    """§15.2 (GAP-P7-DEF-B) — REVISED after adversarial review cycle 1
    (uat/reports/evidence/phase7/review-def-b.json, verdict FAIL).

    DESIGN-RULING HISTORY: a prior implementation of this function mutated
    the process-wide, global ``email_validator.SPECIAL_USE_DOMAIN_NAMES``
    list, discarding the bare reserved label matching each configured
    domain's suffix (e.g. ``"local"`` for ``"aether.local"``). The review
    empirically proved this opened EVERY ``*.local`` address —
    ``attacker@evil.local``, ``foo.local``, ``x@random-internal-host.local``
    all validated, not just the intended ``admin@aether.local`` — because
    ``SPECIAL_USE_DOMAIN_NAMES`` only ever contains bare TLD-like labels, so
    "discarding" it is inherently a wholesale, process-wide opening. That is
    exactly the "globally-scoped" Option 1 behaviour §15.1 explicitly
    rejected in favor of Option 3's exact-domain scoping ("removes only the
    specific domains the operator intends to allow"). fable-5 overrode
    §15.2's sample pseudocode as flawed; this function no longer touches
    ``email_validator`` global state AT ALL — it is now a pure,
    side-effect-free loader.

    Reads ``AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS`` (comma-separated,
    case-insensitive, default ``"aether.local"``) fresh from ``os.environ``
    on every call (no caching) and returns the configured domains as a
    ``frozenset`` of lowercased, whitespace-trimmed strings. Re-callable by
    design — a test (or a future admin endpoint) can monkeypatch the env var
    and call this again to see the updated set immediately.

    The actual allow/reject decision is made by
    ``app.routers.workspaces``'s custom ``SettingsProfile.email`` validator
    (``_validate_settings_email``), which calls this loader and requires an
    EXACT (case-insensitive) match against the returned set — never a
    suffix/TLD match — so ``evil.local`` (a different domain that merely
    shares the ``.local`` label with the allow-listed ``aether.local``) is
    correctly rejected while ``aether.local`` itself is accepted. See that
    module for the exact-match logic and
    ``apps/api/tests/test_gap_p7_def_b_email_validation.py::test_settings_save_nonconfigured_local_subdomain_rejected``
    for the regression test proving the scoping.
    """
    return frozenset(
        d.strip().lower()
        for d in os.environ.get("AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS", "aether.local").split(",")
        if d.strip()
    )


def _guard_production_replay_mode() -> None:
    """Fail fast if a production deploy would silently serve LLM fixtures.

    ``AETHER_LLM_MODE`` defaults to ``replay`` (see
    ``app.services.llm_client.get_mode``), which is correct for local
    dev/tests but must never reach production — it would serve canned
    fixture responses instead of real model output with no visible error
    (§REC-04). Non-production replay mode only prints a warning.
    """
    mode = get_mode()
    env = os.environ.get("AETHER_ENV", "development").strip().lower()
    if mode != "replay":
        return
    if env == "production":
        raise RuntimeError(
            "§REC-04: AETHER_LLM_MODE=replay is not permitted when "
            "AETHER_ENV=production — this would silently serve canned LLM "
            "fixtures instead of real model output. Set AETHER_LLM_MODE to "
            "'auto', 'live', or 'record' for production deploys."
        )
    print(
        "WARNING: AETHER_LLM_MODE=replay — serving canned LLM fixtures, not "
        "live model output. This is expected in development/tests only; it "
        "must never be used in production (§REC-04).",
        file=sys.stderr,
    )


def _guard_production_discovery_fixtures() -> None:
    """Fail fast if a production deploy would serve discovery fixtures.

    ``AETHER_DISCOVERY_FIXTURE_DIR`` is a test/dev env var that redirects
    ALL job-board discovery adapters to serve pre-canned HTTP fixtures
    (``apps/api/tests/fixtures/http/<source>/jobs.json``) instead of making
    live HTTP calls. It is set by ``tests/conftest.py`` at import time and
    must NEVER be present in a production environment — it would silently
    serve stale fixture data as if it were live job listings, with no
    visible error and no audit trail (§REC-05).

    This guard is a pure env-var check (no file I/O, no imports) so it is
    safe to call early in ``create_app()`` before settings/DB are wired.
    Non-production deployments with the fixture dir set print a warning
    (it is expected in tests and offline development).
    """
    fixture_dir = os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR", "").strip()
    if not fixture_dir:
        return
    env = os.environ.get("AETHER_ENV", "development").strip().lower()
    if env == "production":
        raise RuntimeError(
            "§REC-05: AETHER_DISCOVERY_FIXTURE_DIR is set while "
            "AETHER_ENV=production — this would silently serve canned job "
            "discovery fixtures instead of live job-board data. Unset "
            "AETHER_DISCOVERY_FIXTURE_DIR for production deploys."
        )
    print(
        "WARNING: AETHER_DISCOVERY_FIXTURE_DIR is set — job-board discovery "
        "adapters will serve canned HTTP fixtures instead of making live "
        "calls. This is expected in development/tests only; it must never "
        "be used in production (§REC-05).",
        file=sys.stderr,
    )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply §14.7 admin-credential rotation on app load (GAP-P6-SEC-001).

    Reclaims the reserved demo username, demotes the seeded demo credential to
    non-admin and then either grants the configured operator admin
    (``AETHER_ADMIN_EMAIL``/``AETHER_ADMIN_PASSWORD_HASH``) or, if that
    credential is known-weak, malformed or self-cancelling, REVOKES ``isAdmin``
    from it and keeps serving.

    STARTUP MUST NOT FAIL FOR A CREDENTIAL PROBLEM (BLOCKER-001; binding ruling
    in ``docs/delivery/ADR-BLOCKER-001-ADMIN-CREDENTIAL.md``, condition C1).
    An earlier draft re-raised ``AdminCredentialSecurityError`` here. Because
    ``aether-api.service`` sets ``Restart=on-failure``/``RestartSec=5`` and the
    check is deterministic, that turned an unrotated production credential into
    a permanent crash loop on the next restart — converting a confidentiality
    problem into a total availability loss (ADR §2).

    WHY THIS DIFFERS FROM ``_guard_production_replay_mode`` ABOVE — do not
    "helpfully" make it fail-closed again. That guard aborts on a
    MISCONFIGURATION the operator sets deliberately in the deploy environment
    (``AETHER_LLM_MODE=replay``): refusing to start costs nothing, because a
    deploy in that state should never go live at all. This one reacts to a LIVE
    CREDENTIAL the operator has not rotated YET — a condition that is already
    true of the running production environment, that only a human can clear,
    and that is re-evaluated on EVERY start. Aborting would take the site down
    for every paying customer to punish a state the restart cannot fix, while
    achieving nothing extra: by the time rotation returns, the privilege has
    already been revoked in the database (and ``isAdmin`` is re-read per
    request, so live sessions lose admin immediately too).

    The two admin exceptions are therefore caught and logged, never re-raised.
    ``apply_admin_rotation`` no longer raises them at all; the handler is kept
    as a standing guarantee that a future edit which reintroduces a raise still
    cannot crash-loop production. Any other exception is an INFRASTRUCTURE
    failure (e.g. the DB is briefly unavailable at boot) and stays best-effort.
    """
    from app.repositories.admin import (
        AdminCredentialSecurityError,
        AdminRotationConfigError,
        apply_admin_rotation,
    )

    try:
        apply_admin_rotation()
    except (AdminCredentialSecurityError, AdminRotationConfigError) as exc:
        # Loud, unmissable, and NOT fatal (condition C1). The detail line (which
        # may name the matched denylist entry) goes to the process log only —
        # never to an HTTP response. GET /admin/health carries a value-free
        # boolean + remediation string for the same condition.
        print(
            "CRITICAL: §14.7 admin credential rotation refused the configured "
            "operator admin and did not complete — the API is starting anyway "
            "(availability). Administrator privilege must be assumed NOT "
            f"applied. Operator action required: {exc}",
            file=sys.stderr,
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001 — infra hiccups must not break boot
        print(
            f"WARNING: §14.7 admin credential rotation skipped at startup: {exc}",
            file=sys.stderr,
        )
    yield


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    _guard_production_replay_mode()
    _guard_production_discovery_fixtures()
    # NOTE (§15.2, GAP-P7-DEF-B, revised cycle 2): apply_email_domain_allowlist()
    # is a pure loader with no global state to prime — it is called directly,
    # per-request, by app.routers.workspaces's SettingsProfile.email
    # validator, so no startup call is needed here.
    settings = get_settings()

    # W-E prod hygiene (spec §7.3): interactive schema explorers (/docs,
    # /redoc, /openapi.json) are debug surfaces that enumerate every endpoint
    # for anonymous visitors — never serve them when AETHER_ENV=production.
    is_production = (
        os.environ.get("AETHER_ENV", "development").strip().lower() == "production"
    )

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "Aether autonomous job & career agent backend — discovery, "
            "resume tailoring, applications, and approvals."
        ),
        lifespan=_lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # Per-app auth rate limiters (see app.rate_limit), keyed on the submitted
    # request identifier — never the client IP, which is untrustworthy behind
    # Envoy -> nginx -> uvicorn (ADR D-0033). Stored on app.state so each
    # constructed app owns isolated counters; the auth router reads them via the
    # guard/record/reset helpers. ``login_rate_limiter`` caps failed logins per
    # identifier; ``register_rate_limiter`` caps register attempts per email.
    app.state.login_rate_limiter = build_login_rate_limiter()
    app.state.register_rate_limiter = build_register_rate_limiter()
    # Billing limiters, keyed by user id (per-worker): checkout 5/hr, portal
    # 10/hr — blunt double-click session minting / portal abuse (billing §3).
    app.state.checkout_rate_limiter = SlidingWindowRateLimiter(
        max_calls=5, window_seconds=60 * 60.0
    )
    app.state.portal_rate_limiter = SlidingWindowRateLimiter(
        max_calls=10, window_seconds=60 * 60.0
    )

    # Permit the Next.js dashboard (and other same-origin tooling) to call the
    # API during development. Origins are tightened per-environment later.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # OUTBOUND generation paths (cover letter, email draft, refine, tailor) raise
    # MissingResumeError when the caller has no résumé of their own. Surface it as
    # an honest 422 — never a 500, and never by grounding on the bundled operator
    # résumé (NF-final-B-001/005).
    @app.exception_handler(MissingResumeError)
    async def _missing_resume_handler(  # pyright: ignore[reportUnusedFunction]
        _request: Request, exc: MissingResumeError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": str(exc) or "Add your resume before generating this."},
        )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(google_oauth.router, prefix="/auth", tags=["auth"])
    app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
    app.include_router(agents.router, prefix="/agents", tags=["agents"])
    app.include_router(resumes.router, prefix="/resumes", tags=["resumes"])
    app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
    app.include_router(cover_letters.router, prefix="/cover-letters", tags=["cover-letters"])
    app.include_router(stories.router, prefix="/stories", tags=["stories"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
    app.include_router(applications.router, prefix="/applications", tags=["applications"])
    app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
    app.include_router(interviews.router, prefix="/interviews", tags=["interviews"])
    app.include_router(emails.router, prefix="/emails", tags=["emails"])
    app.include_router(networking.router, prefix="/networking", tags=["networking"])
    app.include_router(offers.router, prefix="/offers", tags=["offers"])
    app.include_router(billing.router, prefix="/billing", tags=["billing"])
    app.include_router(admin.router, prefix="/admin", tags=["admin"])

    return app


app = create_app()
