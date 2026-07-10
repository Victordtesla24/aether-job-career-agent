"""Aether API application entrypoint (P1-S09).

Builds the FastAPI app via a ``create_app`` factory (so tests can construct an
isolated instance) and mounts the routers. The module-level ``app`` is what
``uvicorn app.main:app`` serves.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    agents,
    analytics,
    applications,
    approvals,
    auth,
    cover_letters,
    health,
    jobs,
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
    app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
    app.include_router(agents.router, prefix="/agents", tags=["agents"])
    app.include_router(resumes.router, prefix="/resumes", tags=["resumes"])
    app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
    app.include_router(cover_letters.router, prefix="/cover-letters", tags=["cover-letters"])
    app.include_router(stories.router, prefix="/stories", tags=["stories"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
    app.include_router(applications.router, prefix="/applications", tags=["applications"])
    app.include_router(workspaces.router, tags=["workspaces"])

    return app


app = create_app()
