"""Health check router (P1-S09).

Exposes an unauthenticated ``GET /health`` liveness probe returning the
canonical payload consumed by load balancers, uptime checks, and CI smoke
tests: ``{"status": "ok", "version": "<API_VERSION>"}``.

D-QDEPTH also mounts ``GET /queue/status`` here — an authenticated peek at
the ARQ worker's Redis queue depth, so the dashboard can show "N jobs
queued" without reaching into the worker's internals. Any Redis failure
resolves to an honest ``{"queuedJobs": null, "state": "unavailable"}``
rather than a fabricated ``0`` — a caller must never mistake "we couldn't
ask" for "the queue is empty".
"""
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import SettingsDep
from app.middleware.auth import CurrentUser

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Shape of the /health payload."""

    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep) -> HealthResponse:
    """Liveness probe. Always returns ``ok`` with the current API version."""
    return HealthResponse(status="ok", version=settings.api_version)


class QueueStatusResponse(BaseModel):
    """Shape of the /queue/status payload (D-QDEPTH)."""

    queuedJobs: int | None
    state: str


def _get_redis_client():
    """Seam for the status-check Redis client (patched to a fake in tests).

    Same ``AETHER_REDIS_URL`` / localhost fallback as
    ``app.workers.settings._redis_settings`` — this endpoint reads the SAME
    Redis the worker enqueues into without needing its own env var. A short
    connect/read timeout keeps a wedged Redis from stalling the request;
    the caller below treats ANY exception here as "unavailable", never lets
    one reach the client as a 500.
    """
    import redis

    url = os.environ.get("AETHER_REDIS_URL", "redis://127.0.0.1:6379/3")
    return redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)


@router.get("/queue/status", response_model=QueueStatusResponse)
def queue_status(current_user: CurrentUser) -> QueueStatusResponse:  # noqa: ARG001
    """Honest ARQ worker queue depth for any logged-in user (D-QDEPTH).

    Reads ``LLEN`` on ``arq.constants.default_queue_name`` — the queue key
    ``app.workers.settings.WorkerSettings`` uses, since it sets no
    ``queue_name`` override, so this is genuinely the worker's own queue and
    not a guessed string. ANY Redis failure (down, timeout, auth, wrong DSN)
    returns ``queuedJobs=null`` / ``state="unavailable"`` over HTTP 200 —
    never a fabricated ``0`` and never a 500 that would make an operational
    blip look like an application bug.
    """
    from arq.constants import default_queue_name

    try:
        depth = _get_redis_client().llen(default_queue_name)
        return QueueStatusResponse(queuedJobs=int(depth), state="ok")
    except Exception:  # noqa: BLE001 — any Redis failure means "unavailable"
        return QueueStatusResponse(queuedJobs=None, state="unavailable")
