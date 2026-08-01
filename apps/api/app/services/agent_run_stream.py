"""Server-Sent Events transport for agent-run progress (GMV4-sse-001, §14.5.5).

WHAT THIS IS
------------
A read-only SSE transport over the agent-run state that **already exists**: the
persisted ``AgentRun`` row (``queued``/``running``/``completed``/``failed``,
plus ``output``/``error``/timestamps). It replaces the client-side 2-3s poll of
``GET /agents/runs/{run_id}`` with one server-side observation loop over the
SAME row, and pushes a real event only when the observed state genuinely
CHANGES.

WHAT THIS IS **NOT** — read before consuming the stream
-------------------------------------------------------
It is NOT a step-level progress feed. The GMV4 contract names a six-step
submission sequence (``scanning_queue`` -> ``computing_ats_deltas`` ->
``awaiting_approval`` -> ``submitting`` -> ``updating_kanban`` -> ``complete``).
Four of those six steps have **no backing whatsoever** in this codebase today:

* ``scanning_queue``       -- the Submission Agent's ready-to-apply scan
  (:data:`app.agents.submission_agent._READY_TO_APPLY_SQL`) really happens, but
  nothing records that it happened; it is not observable from outside the call.
* ``computing_ats_deltas`` -- the Submission Agent computes NO ATS delta at all
  (the ATS engine runs in tailoring/fit-scoring, a different run).
* ``awaiting_approval``    -- ``submission`` is deliberately NOT in
  ``app.routers.agents._APPROVAL_GATED``; a submission run has no approval gate.
* ``submitting`` / ``updating_kanban`` -- the write really happens
  (``submit_application_for_job``) but is not journalled as a step transition.

Emitting those six names on a timer would be a scripted animation with no
execution behind it (§0.5 placeholder violation), so this module does not emit
them. It emits ONLY what the persisted row actually proves:

* ``snapshot``      -- the run's real current state at connect time.
* ``status``        -- a genuine persisted status transition.
* ``kanban_updated``-- see the honesty note on :func:`_kanban_payload`.
* ``complete``      -- the run really reached ``completed``. Terminal.
* ``failed``        -- the run really reached ``failed``, carrying the real
  recorded error. Terminal. Never dressed up as ``complete``.
* ``stream_timeout`` / ``stream_error`` -- the stream ended WITHOUT a terminal
  run state, said so, and closed. Never a fabricated ``complete``, never a
  silent hang.

Giving the six steps real backing needs a per-step journal written by the agent
pipeline at genuine transition points; that is a separate, additive change and
is filed as such rather than faked here.

TRANSPORT / DEPLOYMENT NOTES
----------------------------
* ``X-Accel-Buffering: no`` is LOAD-BEARING. ``deploy/5cb5f0620.conf``'s
  ``location /api/`` has no ``proxy_buffering off``, so without this
  per-response opt-out nginx buffers the whole stream and it looks dead in
  production. No nginx change is required *because* of this header.
* Heartbeat comments (``: heartbeat``) are emitted while a run is still
  in-flight so nginx's ``proxy_read_timeout 180s`` never fires on an idle
  stream, and so intermediaries do not reap the connection.
* Every event is derived from the shared Postgres row, NOT from in-process
  state. That is deliberate: an in-process (or single-worker Redis-less) event
  bus would silently deliver nothing when the API runs with >1 uvicorn worker,
  or when the run executes in the ARQ worker process rather than the API
  process. ``start-api.sh`` runs single-process today, but this design does not
  depend on that and does not break if it changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

#: ``AgentRunStatus`` (packages/db/src/schema.prisma:62) is a closed enum.
ACTIVE_RUN_STATUSES = frozenset({"queued", "running"})
TERMINAL_RUN_STATUSES = frozenset({"completed", "failed"})

#: Response headers every SSE response on this API must carry. ``cache-control``
#: keeps proxies/browsers from caching a stream; ``x-accel-buffering`` is the
#: nginx opt-out described in the module docstring.
SSE_HEADERS: dict[str, str] = {
    "cache-control": "no-cache",
    "connection": "keep-alive",
    "x-accel-buffering": "no",
}


def _float_env(name: str, default: float, *, minimum: float) -> float:
    """An operator-tunable timing knob. A malformed value is reported and the
    default used — never silently coerced to something surprising."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number — using default %s", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%s is below the %s floor — using the floor", name, value, minimum)
        return minimum
    return value


def poll_seconds() -> float:
    """How often the persisted run row is re-read. §14.5.5 wants a kanban change
    visible on connected tabs within 1s, so the floor is the poll interval. One
    primary-key single-row SELECT per interval per open stream — this REPLACES
    the client's existing 2-3s poll of the same row rather than adding to it."""
    return _float_env("AETHER_SSE_POLL_SECONDS", 1.0, minimum=0.05)


def heartbeat_seconds() -> float:
    """Idle keepalive cadence — must stay well under nginx's 180s
    ``proxy_read_timeout`` (deploy/5cb5f0620.conf)."""
    return _float_env("AETHER_SSE_HEARTBEAT_SECONDS", 15.0, minimum=1.0)


def max_stream_seconds() -> float:
    """Bounded stream lifetime. A run that never reaches a terminal status must
    not hold a connection open forever; at the bound the stream says so
    (``stream_timeout``) and closes so the client can reconnect."""
    return _float_env("AETHER_SSE_MAX_STREAM_SECONDS", 600.0, minimum=5.0)


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------


def sse_event(event: str, data: dict[str, Any]) -> str:
    """One ``event:``/``data:`` SSE frame. ``default=str`` renders the row's
    ``datetime``/``Decimal`` columns instead of raising mid-stream."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def sse_comment(text: str) -> str:
    """An SSE comment line — traffic on the wire that is not an event."""
    return f": {text}\n\n"


# ---------------------------------------------------------------------------
# Payloads derived from the persisted row (nothing invented)
# ---------------------------------------------------------------------------


def _status_of(run: dict[str, Any]) -> str:
    return str(run.get("status") or "")


def _run_payload(run: dict[str, Any]) -> dict[str, Any]:
    """The honest projection of the persisted row that the UI needs. ``source``
    names the provenance so a consumer can never mistake this for step-level
    telemetry."""
    return {
        "runId": run.get("id"),
        "agentName": run.get("agentName"),
        "status": _status_of(run),
        "startedAt": run.get("startedAt"),
        "completedAt": run.get("completedAt"),
        "source": "agent_run_row",
    }


def _kanban_payload(run: dict[str, Any], user_id: str) -> dict[str, Any]:
    """The ``kanban_updated`` broadcast (§14.5.5).

    HONESTY NOTE. This is a scope-level CACHE-INVALIDATION signal — "a run you
    own finished, the board you are showing may be stale, re-read it" — not a
    claim that a specific card moved. Its provenance is stated on the wire:

    * ``basis="run_output"`` -- the run's own persisted ``output`` records the
      board-affecting write (the Submission Agent returns ``jobId`` /
      ``applicationId``), so ``changes`` carries those REAL ids.
    * ``basis="run_completed"`` -- the run completed but recorded no
      board-level detail, so ``changes`` is empty and the consumer is told
      exactly that. Nothing is guessed to fill it.

    ``channel`` is the tenancy scope. This codebase has no ``Workspace`` model
    (``packages/db/src/schema.prisma`` has none); ``userId`` is every table's
    isolation key, so the workspace scope IS the owning user id.
    """
    changes: list[dict[str, Any]] = []
    basis = "run_completed"
    output = run.get("output")
    if isinstance(output, dict):
        job_id = output.get("jobId")
        application_id = output.get("applicationId")
        if job_id or application_id:
            changes = [{"jobId": job_id, "applicationId": application_id}]
            basis = "run_output"
    return {
        "channel": f"jobs:{user_id}",
        "runId": run.get("id"),
        "agentName": run.get("agentName"),
        "basis": basis,
        "changes": changes,
        "reason": "agent_run_completed",
    }


def _terminal_frames(run: dict[str, Any], user_id: str) -> list[str]:
    """The closing frames for a run that reached a terminal persisted status."""
    status_value = _status_of(run)
    if status_value == "completed":
        payload = _run_payload(run)
        payload["output"] = run.get("output")
        return [
            sse_event("kanban_updated", _kanban_payload(run, user_id)),
            sse_event("complete", payload),
        ]
    # ``failed`` — surfaced as a failure carrying the REAL recorded error. A
    # failed run must never be reported as ``complete``.
    payload = _run_payload(run)
    payload["error"] = run.get("error")
    return [sse_event("failed", payload)]


# ---------------------------------------------------------------------------
# The stream
# ---------------------------------------------------------------------------


async def iter_agent_run_events(
    *,
    run: dict[str, Any],
    run_id: str,
    user_id: str,
    reload_run: Callable[[str, str], dict[str, Any] | None],
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for one already-authorised agent run.

    ``run`` is the row the caller ALREADY fetched under the owner-scoped
    ownership check, so this generator never re-authorises and never widens
    scope: every reload goes back through the same owner-scoped
    ``reload_run(run_id, user_id)``, which returns ``None`` for anyone but the
    owner.

    Terminates on: terminal run status, client disconnect, the bounded stream
    lifetime, or an unreadable run — each with an explicit closing frame except
    disconnect (where there is no one left to tell).
    """
    yield sse_comment(f"agent-run stream {run_id}")
    yield sse_event("snapshot", _run_payload(run))

    poll = poll_seconds()
    beat = heartbeat_seconds()
    deadline = time.monotonic() + max_stream_seconds()
    last_beat = time.monotonic()
    current = _status_of(run)

    while current not in TERMINAL_RUN_STATUSES:
        if current not in ACTIVE_RUN_STATUSES:
            # Not active and not terminal: an unrecognised status. Say so and
            # close rather than spin until the timeout on a state we cannot
            # reason about.
            logger.warning(
                "agent-run stream %s: unrecognised status %r — closing stream",
                run_id, current,
            )
            yield sse_event(
                "stream_error",
                {
                    "runId": run_id,
                    "status": current,
                    "message": "Run is in an unrecognised state; stream closed.",
                },
            )
            return

        if is_disconnected is not None and await is_disconnected():
            logger.info("agent-run stream %s: client disconnected", run_id)
            return

        if time.monotonic() >= deadline:
            yield sse_event(
                "stream_timeout",
                {
                    "runId": run_id,
                    "status": current,
                    "message": (
                        "Stream reached its bounded lifetime before the run "
                        "finished. The run is still in progress — reconnect to "
                        "keep watching."
                    ),
                },
            )
            return

        await asyncio.sleep(poll)

        try:
            fresh = await run_in_threadpool(reload_run, run_id, user_id)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            logger.exception("agent-run stream %s: reload failed", run_id)
            yield sse_event(
                "stream_error",
                {
                    "runId": run_id,
                    "status": current,
                    "message": "Could not read the run's current state; stream closed.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        if fresh is None:
            # The row vanished (or stopped being readable by its owner) mid
            # stream. Honest close — not a fabricated completion.
            yield sse_event(
                "stream_error",
                {
                    "runId": run_id,
                    "status": current,
                    "message": "Run is no longer readable; stream closed.",
                },
            )
            return

        run = fresh
        new_status = _status_of(fresh)
        if new_status != current:
            current = new_status
            last_beat = time.monotonic()
            yield sse_event("status", _run_payload(fresh))
        elif time.monotonic() - last_beat >= beat:
            last_beat = time.monotonic()
            yield sse_comment(f"heartbeat {int(time.time())}")

    for frame in _terminal_frames(run, user_id):
        yield frame
