"""Aether API application entrypoint (P1-S09).

Builds the FastAPI app via a ``create_app`` factory (so tests can construct an
isolated instance) and mounts the routers. The module-level ``app`` is what
``uvicorn app.main:app`` serves.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.rate_limit import build_login_rate_limiter, build_register_rate_limiter
from app.routers import (
    agents,
    analytics,
    applications,
    approvals,
    auth,
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


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "Aether autonomous job & career agent backend — discovery, "
            "resume tailoring, applications, and approvals."
        ),
    )

    # Per-app auth rate limiters (see app.rate_limit), keyed on the submitted
    # request identifier — never the client IP, which is untrustworthy behind
    # Envoy -> nginx -> uvicorn (ADR D-0033). Stored on app.state so each
    # constructed app owns isolated counters; the auth router reads them via the
    # guard/record/reset helpers. ``login_rate_limiter`` caps failed logins per
    # identifier; ``register_rate_limiter`` caps register attempts per email.
    app.state.login_rate_limiter = build_login_rate_limiter()
    app.state.register_rate_limiter = build_register_rate_limiter()

    # Permit the Next.js dashboard (and other same-origin tooling) to call the
    # API during development. Origins are tightened per-environment later.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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

    return app


app = create_app()
