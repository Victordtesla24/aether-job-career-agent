"""The dashboard's single realtime channel (W-RT).

``GET /events/stream`` is ONE authenticated, user-scoped SSE connection that
reports which of the caller's persisted resources changed. The client holds one
of these per browser tab and fans it out to every open screen
(``apps/web/src/lib/realtime/store.ts``) instead of opening a stream — or a
poll loop — per screen.

Everything transport-level here is the agent-run stream's, reused rather than
duplicated: :data:`SSE_HEADERS`, :class:`StreamSlots` admission control (the
SAME instance, so the global budget covers both stream kinds together),
:func:`release_slot_when_done`, and the shared timing knobs. The only new thing
is what is observed; see :mod:`app.services.workspace_event_stream` for exactly
what the events do and do not claim.

FAILURE MODES ARE EXPLICIT — never a hang, never an empty 200 dressed up as a
live stream:

* ``429`` -- this account already holds its allowance of live streams.
* ``503`` -- the server is at its global stream capacity, OR the caller's
  workspace state could not be read at connect time.
* ``401``/``403`` -- unauthenticated. This stream is a firehose of one user's
  data and is never anonymous.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.middleware.auth import CurrentUser
from app.services.agent_run_stream import (
    SSE_HEADERS,
    StreamCapExceeded,
    StreamSlots,
    release_slot_when_done,
)
from app.services.workspace_event_stream import (
    REALTIME_RESOURCE_KEYS,
    iter_workspace_events,
    read_watermarks,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/resources")
def list_realtime_resources(current_user: CurrentUser) -> dict[str, Any]:
    """The resource keys this channel can report on.

    Lets a client validate its subscriptions against the server instead of
    hardcoding a list that can silently drift out of date.
    """
    return {"resources": list(REALTIME_RESOURCE_KEYS)}


@router.get("/stream")
async def stream_workspace_events(
    request: Request, current_user: CurrentUser
) -> StreamingResponse:
    """Live workspace changes for the authenticated caller.

    Admission is taken BEFORE any database work so a refused request costs
    nothing, and is released on every exit path — the pre-stream unwind below
    and :func:`release_slot_when_done` around the generator. ``release`` is
    idempotent, so the two can never double-free.
    """
    slots: StreamSlots = request.app.state.sse_stream_slots
    try:
        token = slots.acquire(current_user["id"])
    except StreamCapExceeded as exc:
        logger.warning(
            "workspace stream refused (%s cap %s) user=%s",
            exc.scope, exc.limit, current_user["id"],
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS
            if exc.scope == "user"
            else status.HTTP_503_SERVICE_UNAVAILABLE,
            exc.message,
            headers={"Retry-After": "5"},
        ) from None

    try:
        # Observe once up front. This both proves the state is readable — so a
        # broken database is an honest 503 instead of a 200 stream that never
        # reports anything — and becomes the ``hello`` snapshot, so connecting
        # costs exactly one query rather than two.
        initial = await run_in_threadpool(read_watermarks, current_user["id"])
    except BaseException as exc:
        slots.release(token)
        if isinstance(exc, HTTPException):
            raise
        logger.exception("workspace stream: initial read failed for %s", current_user["id"])
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not open the live update stream: your workspace state is "
            "temporarily unreadable. Your data is unaffected — the screens still "
            "load normally; retry in a few seconds.",
            headers={"Retry-After": "5"},
        ) from None

    return StreamingResponse(
        release_slot_when_done(
            iter_workspace_events(
                user_id=current_user["id"],
                read_watermarks=read_watermarks,
                is_disconnected=request.is_disconnected,
                initial=initial,
            ),
            lambda: slots.release(token),
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
