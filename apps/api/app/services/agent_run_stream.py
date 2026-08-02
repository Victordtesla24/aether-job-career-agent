"""Server-Sent Events transport for agent-run progress (GMV4-sse-001, §14.5.5).

WHAT THIS IS
------------
A read-only SSE transport over the agent-run state that **already exists**: the
persisted ``AgentRun`` row (``queued``/``running``/``completed``/``failed``,
plus ``output``/``error``/timestamps). It replaces the client-side poll of
``GET /agents/runs/{run_id}`` with one server-side observation loop over the
SAME row, and pushes a real event only when the observed state genuinely
CHANGES. The real client poll is **3000ms**
(``apps/web/src/lib/api/agents.ts:57``, ``JOB_POLL_INTERVAL_MS``), so the
default server poll below is 3.0s — the same cadence, not a tighter one. An
earlier revision defaulted to 1.0s while claiming to replace a "2-3s poll";
that was 3x MORE database load than the mechanism it replaced (GMV4-sse-005,
governance §5e).

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
* ``kanban_updated``-- ONLY when the run's own persisted ``output`` records a
  real board-affecting write. A run that never touched the board (tailoring,
  cover-letter) does NOT emit it: the event NAME asserts a kanban change, so
  emitting it with an empty ``changes`` list would still be false to every
  connected client (ADR-GMV4-003, governance §5d). See :func:`_kanban_payload`.
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

RESOURCE LIMITS -- why :class:`StreamSlots` exists (GMV4-sse-005, §5e)
---------------------------------------------------------------------
Every poll opens a short-lived UNPOOLED connection (``app.db.get_connection``),
against a hosted-Postgres ceiling of **25 concurrent connections for the whole
deployment** (``app/db.py:8-9``). An uncapped stream count is therefore a real
DoS surface: enough open browser tabs would starve every other endpoint of
connections. :class:`StreamSlots` bounds admissions per user AND globally, and
a refused stream gets an explicit HTTP status with a real reason -- never a
silent hang and never an empty 200 pretending to be a live stream. See
:data:`DEFAULT_MAX_CONCURRENT_STREAMS` for the arithmetic against the 25.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
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
    """How often the persisted run row is re-read: one primary-key single-row
    SELECT per interval per open stream, each on its own short-lived
    connection.

    The default is 3.0s because that is EXACTLY the cadence of the client poll
    this stream replaces (``apps/web/src/lib/api/agents.ts:57``,
    ``JOB_POLL_INTERVAL_MS = 3000``) — so the transport is a swap, not an
    increase, in database load (governance §5e). §14.5.5 asks for a kanban
    change to be visible within 1s; with this default the observed latency
    floor is the poll interval, i.e. up to 3s, NOT 1s. That is a deliberate,
    stated trade against the 25-connection ceiling rather than a silent miss:
    an operator who wants the tighter latency can lower
    ``AETHER_SSE_POLL_SECONDS``, at a directly proportional cost in
    connections-per-second, and should lower
    ``AETHER_SSE_MAX_CONCURRENT_STREAMS`` to match."""
    return _float_env("AETHER_SSE_POLL_SECONDS", 3.0, minimum=0.05)


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
# Admission control (GMV4-sse-005, governance §5e)
# ---------------------------------------------------------------------------

#: Global concurrent-stream ceiling, derived from the 25-connection hard limit
#: documented at ``app/db.py:8-9``. NOT tuned to any test; the arithmetic is:
#:
#:     25  hosted-Postgres ceiling for the ENTIRE deployment
#:    - 8  ordinary API request traffic (uvicorn runs SINGLE-process —
#:         ``start-api.sh`` passes no ``--workers`` — and each in-flight
#:         handler holds at most one short-lived connection)
#:    - 6  the ARQ worker process (``aether-worker.service``), a separate
#:         process running agent pipelines against the same database
#:    - 2  ad-hoc/ops: ``psql``, the lazy DDL bootstraps in ``app/db.py``,
#:         the discovery timer
#:    ----
#:    =  9  unallocated; take 8 and leave 1 permanently spare so the budget
#:          never sits exactly ON the ceiling.
#:
#: A stream holds a connection ONLY during a poll (``get_connection`` opens,
#: reads one row by primary key, closes), so 8 admitted streams occupy at most
#: 8 connections at the worst-case instant where every poll lands together, and
#: approximately zero between polls. 8 < 25, with 17 connections of headroom.
DEFAULT_MAX_CONCURRENT_STREAMS = 8

#: Per-user ceiling. The reviewer's stated threat model is "a few users with
#: 2-3 open tabs each", so 3 covers a real user's tabs while ensuring no single
#: account can take more than 3/8 of the global budget — at least two distinct
#: users can always hold their full allowance at once.
DEFAULT_MAX_STREAMS_PER_USER = 3

#: Leak backstop. A slot is reclaimed only once it has outlived the stream's
#: OWN hard lifetime bound (:func:`max_stream_seconds`) by this much, past
#: which no correctly-behaving generator can still be running. Explicit release
#: remains the primary path (see :func:`release_slot_when_done`); this exists
#: so a slot that somehow never gets released — e.g. a response dropped before
#: its body iterator was ever started, where no ``finally`` can run — self-heals
#: instead of permanently shrinking capacity. Its only imprecision is briefly
#: admitting one extra stream if a poll is genuinely wedged in the DB driver
#: past the grace; with 17 connections of headroom that is bounded and harmless.
SLOT_LEAK_GRACE_SECONDS = 60.0


def _int_env(name: str, default: int, *, minimum: int) -> int:
    """An operator-tunable integer cap. A malformed value is reported and the
    default used — never silently coerced to something surprising."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer — using default %s", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s=%s is below the %s floor — using the floor", name, value, minimum)
        return minimum
    return value


def max_concurrent_streams() -> int:
    """Global cap on simultaneously-open agent-run streams in this process."""
    return _int_env(
        "AETHER_SSE_MAX_CONCURRENT_STREAMS", DEFAULT_MAX_CONCURRENT_STREAMS, minimum=1
    )


def max_streams_per_user() -> int:
    """Per-user cap on simultaneously-open agent-run streams."""
    return _int_env(
        "AETHER_SSE_MAX_STREAMS_PER_USER", DEFAULT_MAX_STREAMS_PER_USER, minimum=1
    )


class StreamCapExceeded(Exception):
    """Raised by :meth:`StreamSlots.acquire` when admitting one more stream
    would breach a cap.

    Carries the honest, user-facing reason. The caller turns this into a real
    HTTP status whose ``detail`` IS :attr:`message` — it is never swallowed,
    never retried behind the user's back, and never degraded into an empty 200
    stream or a hang."""

    def __init__(self, *, scope: str, limit: int, message: str) -> None:
        super().__init__(message)
        self.scope = scope
        self.limit = limit
        self.message = message


@dataclass(frozen=True)
class _Slot:
    user_id: str
    #: ``time.monotonic()`` deadline past which this slot is treated as leaked.
    expires_at: float


class StreamSlots:
    """Bounded admission control for concurrent SSE streams (§5e).

    One instance lives on ``app.state.sse_stream_slots`` (see
    ``app.main.create_app``), matching the existing per-app rate-limiter
    convention in ``app.rate_limit``: each constructed app — and therefore each
    test — owns isolated counters, while the single long-lived production app
    shares them across every request to that worker. Production runs ONE
    uvicorn process (``start-api.sh`` passes no ``--workers``), so "per
    process" IS global there; were the deployment ever to run N workers the
    effective ceiling would become ``N * AETHER_SSE_MAX_CONCURRENT_STREAMS``
    and that env var would have to be divided down. Stated, not assumed away.

    Guarded by a plain :class:`threading.Lock` that is never held across an
    ``await``, so it is correct whether called from the event loop or from a
    threadpool worker.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: dict[int, _Slot] = {}
        self._tokens = itertools.count(1)

    def _reap_locked(self, now: float) -> None:
        """Reclaim slots that outlived their stream's own hard bound. Caller
        holds ``self._lock``. Every reclamation is logged as the anomaly it is
        — a reaped slot means some exit path failed to release."""
        for token in [t for t, s in self._slots.items() if s.expires_at <= now]:
            slot = self._slots.pop(token)
            logger.warning(
                "SSE admission slot %s (user %s) outlived its stream's bounded "
                "lifetime by %.0fs — reclaiming it as leaked",
                token, slot.user_id, now - slot.expires_at,
            )

    def acquire(self, user_id: str) -> int:
        """Reserve a slot, returning the token that releases it.

        :raises StreamCapExceeded: when a cap would be breached. The caller
            MUST surface that as an explicit HTTP rejection.
        """
        global_limit = max_concurrent_streams()
        user_limit = max_streams_per_user()
        lifetime = max_stream_seconds() + SLOT_LEAK_GRACE_SECONDS
        with self._lock:
            now = time.monotonic()
            self._reap_locked(now)
            if len(self._slots) >= global_limit:
                raise StreamCapExceeded(
                    scope="global",
                    limit=global_limit,
                    # W-RT: this budget is now SHARED between the agent-run
                    # stream and the workspace realtime channel, so the wording
                    # must fit both. It used to say "agent-run stream capacity"
                    # and point at GET /agents/runs/{run_id}; told to a
                    # dashboard user whose live-update stream was refused, both
                    # were false — they may have started no run at all.
                    message=(
                        f"The server is at its live-stream capacity "
                        f"({global_limit} concurrent streams) — a deliberate cap "
                        f"protecting the database's connection ceiling. Retry in a "
                        f"few seconds. Nothing is wrong with your data: every "
                        f"screen still loads and refreshes normally without the "
                        f"live stream."
                    ),
                )
            mine = sum(1 for slot in self._slots.values() if slot.user_id == user_id)
            if mine >= user_limit:
                raise StreamCapExceeded(
                    scope="user",
                    limit=user_limit,
                    # Same W-RT correction as the global message above.
                    message=(
                        f"Too many live streams open for this account "
                        f"({user_limit} at a time). Close another open tab or retry "
                        f"in a few seconds. Nothing is wrong with your data: every "
                        f"screen still loads and refreshes normally without the "
                        f"live stream."
                    ),
                )
            token = next(self._tokens)
            self._slots[token] = _Slot(user_id=user_id, expires_at=now + lifetime)
            return token

    def release(self, token: int) -> None:
        """Give a slot back. IDEMPOTENT: releasing an unknown or
        already-released token is a no-op, so the several exit paths that all
        release (the generator's ``finally``, the pre-stream failure unwind)
        can never double-free and can never free another stream's slot."""
        with self._lock:
            self._slots.pop(token, None)

    def active_count(self) -> int:
        """Slots currently held (after reaping) — for logging/diagnostics."""
        with self._lock:
            self._reap_locked(time.monotonic())
            return len(self._slots)


async def release_slot_when_done(
    frames: AsyncIterator[str], release: Callable[[], None]
) -> AsyncIterator[str]:
    """Wrap a frame stream so its admission slot is released on EVERY exit path
    the generator can take: normal completion, ``stream_timeout``,
    ``stream_error``, client disconnect (Starlette closes the body iterator,
    throwing ``GeneratorExit`` into this ``try``), and any exception.

    ``release`` is synchronous and idempotent, so it is safe to run during
    ``GeneratorExit``/cancellation — an ``await`` there would itself raise and
    lose the slot."""
    try:
        async for frame in frames:
            yield frame
    finally:
        release()


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
    """The ``kanban_updated`` broadcast (§14.5.5) and the evidence for whether
    it may be sent at all.

    ``basis`` is the caller's admission test — see :func:`_terminal_frames`:

    * ``basis="run_output"`` -- the run's own persisted ``output`` records the
      board-affecting write (the Submission Agent returns ``jobId`` /
      ``applicationId``), so ``changes`` carries those REAL ids. This is the
      ONLY case in which the event is emitted.
    * ``basis="run_completed"`` -- the run completed but recorded no
      board-level detail, i.e. there is no evidence the board changed. The
      event is WITHHELD; this payload is never put on the wire.

    ADR-GMV4-003 (``docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md`` §5d). An
    earlier revision emitted the event for every completed run and relied on
    the disclosed ``basis``/empty ``changes`` to keep it honest. That was
    overruled: the event NAME asserts the kanban changed, so firing it after a
    tailoring or cover-letter run that never touched the board is a false
    statement to every connected client no matter what the payload says. A
    generic "a run of yours finished, you may want to refetch" signal is a
    legitimate thing to want, but it must be named for what it is rather than
    borrow an event that means something stronger; nothing in this codebase
    consumes such a signal today, so none is invented here.

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
        frames: list[str] = []
        # ADR-GMV4-003 (§5d): ``kanban_updated`` is emitted ONLY when the run's
        # persisted output is real evidence that the board changed. Anything
        # weaker (``basis == "run_completed"``) means we have no such evidence,
        # and an event whose NAME claims a board change must not be sent on no
        # evidence. ``_kanban_payload`` already computes that basis.
        kanban = _kanban_payload(run, user_id)
        if kanban["basis"] == "run_output":
            frames.append(sse_event("kanban_updated", kanban))
        frames.append(sse_event("complete", payload))
        return frames
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
