"""One user-scoped realtime channel for the whole dashboard (W-RT).

WHAT THIS IS
------------
A second SSE transport built on the SAME primitives as
:mod:`app.services.agent_run_stream` — same wire format (:func:`sse_event`),
same response headers (:data:`SSE_HEADERS`), same admission control
(:class:`StreamSlots`), same timing knobs. It is deliberately NOT a parallel
mechanism: it imports all of that from the agent-run module rather than
re-implementing it.

The difference is SCOPE. ``GET /agents/runs/{run_id}/stream`` watches ONE agent
run's row, so it can only ever tell a client about that run. The dashboard has
eleven screens whose data is written by agents at times no browser tab knows
about — a job discovered, an application staged or moved, a résumé tailored, a
cover letter drafted, an email thread processed, a story written, an interview
scheduled. This module watches the persisted rows BEHIND those screens, for one
user, and says which of them changed.

WHAT IT EMITS — and the evidence behind each claim
--------------------------------------------------
* ``hello``            -- the connect-time snapshot of every watched resource:
  its real row ``count`` and its real ``watermark``. Sent once, immediately, so
  a client knows what "current" meant at connect time.
* ``resource_changed`` -- a resource's persisted state genuinely moved since the
  previous observation: either its row count changed (``count_changed``) or the
  maximum row timestamp advanced (``watermark_advanced``). The payload carries
  BOTH the new and the previous observation so the claim is checkable by the
  client, and ``reason`` names which test fired.
* ``stream_timeout``   -- the stream reached its bounded lifetime. Said out loud
  and closed, so the client reconnects rather than sitting on a dead socket
  believing it is live.
* ``stream_error``     -- the persisted state could not be read. Said out loud
  and closed, carrying the real exception type/message.
* ``: heartbeat``      -- an SSE comment while nothing is happening, so nginx's
  ``proxy_read_timeout 180s`` never reaps an idle stream and the client can tell
  "quiet" from "dead".

WHAT IT DOES **NOT** EMIT — read before consuming
-------------------------------------------------
It does not claim WHAT changed inside a resource, and it never names a business
event ("a cover letter was drafted", "an application was submitted"). It only
knows that the rows behind a screen moved. That is exactly the "generic 'a run
of yours finished, you may want to refetch' signal" that ADR-GMV4-003
(``docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md`` §5d) said is legitimate to want
PROVIDED it is "named for what it is rather than borrow an event that means
something stronger". ``resource_changed`` is that name: the client's response is
to refetch the resource from its ordinary REST endpoint and render whatever the
API actually returns. No payload is ever synthesised from the stream itself.

Two consequences follow, and are stated rather than hidden:

1. The signal is a SUPERSET for a couple of resources. ``coverLetters`` watches
   ``Application`` rows that have a ``coverLetter``, so an unrelated stage move
   on such a row also fires it. The event still says something true ("the rows
   behind the Cover Letters screen changed — refetch"), and the refetch renders
   the truth. It is never a claim that a letter was written.
2. Change detection is watermark-based, so a mutation that neither changes the
   row count nor advances any of a table's timestamp columns is NOT observed.
   Every raw ``UPDATE`` in this codebase sets ``"updatedAt" = NOW()``
   (``app/routers/applications.py``, ``app/routers/jobs.py``,
   ``app/services/stage_transitions.py``, ``app/services/application_submission.py``,
   ``app/repositories/approval.py``), and the two tables without an ``updatedAt``
   column (``AgentRun``, ``ApprovalRequest``) have their transition timestamps
   watched instead — see :data:`REALTIME_RESOURCES`. Anything added later that
   updates a row WITHOUT touching a watched timestamp will be missed by this
   stream; the affected screen still has its ordinary fetch/poll path, so it
   goes stale-until-refetch rather than wrong.

COST / RESOURCE BUDGET
----------------------
One poll = ONE short-lived connection running ONE query: a UNION ALL of
per-resource aggregates, all filtered on ``"userId"``. Not one query per
resource — that would be a dozen connections per poll per stream against the
deployment-wide 25-connection ceiling (``app/db.py:8-9``).

Admission is the SHARED :class:`StreamSlots` instance on
``app.state.sse_stream_slots`` (see ``app.main.create_app``), the same object the
agent-run stream uses, so the global budget stays 8 concurrent streams across
BOTH kinds — this channel adds screens, not connections. Clients are expected to
hold exactly ONE such stream per browser tab and fan out to their screens
client-side (``apps/web/src/lib/realtime/store.ts``); the per-user cap of 3 is
what stops a client that ignores that from opening one per screen.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi.concurrency import run_in_threadpool

from app.db import get_connection, rows_to_dicts
from app.services.agent_run_stream import (
    heartbeat_seconds,
    max_stream_seconds,
    poll_seconds,
    sse_comment,
    sse_event,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResourceSource:
    """One watched resource: the real table behind a screen, and the real
    columns that move when its rows do.

    ``where`` narrows the rows to the ones a screen actually shows. It is a
    fixed SQL fragment defined in this module only — never anything derived from
    a request — so no caller can influence the statement.
    """

    key: str
    table: str
    timestamp_columns: tuple[str, ...]
    where: str = ""
    #: The dashboard screens that read these rows. Documentation for humans; the
    #: client decides its own subscriptions.
    screens: tuple[str, ...] = ()


#: Every resource behind a dashboard screen. Column choices are pinned to the
#: live schema (verified against ``information_schema.columns`` in schema
#: ``aether``), NOT to ``schema.prisma`` alone:
#:
#: * ``AgentRun`` has NO ``updatedAt``; its transitions are recorded on
#:   ``startedAt`` (queued->running) and ``completedAt`` (->completed/failed),
#:   both set by ``app/repositories/agent_run.py``.
#: * ``ApprovalRequest`` has NO ``updatedAt``; it records ``resolvedAt`` and
#:   ``executedAt``.
#: Postgres ``GREATEST`` ignores NULL arguments, so a nullable transition column
#: never blanks out a row's watermark.
REALTIME_RESOURCES: tuple[ResourceSource, ...] = (
    ResourceSource(
        key="jobs",
        table="Job",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("jobs", "dashboard", "analytics"),
    ),
    ResourceSource(
        key="applications",
        table="Application",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("applications", "dashboard", "analytics", "interviews", "offers"),
    ),
    ResourceSource(
        key="coverLetters",
        table="Application",
        timestamp_columns=("createdAt", "updatedAt"),
        where='"coverLetter" IS NOT NULL',
        screens=("cover-letters",),
    ),
    ResourceSource(
        key="resumes",
        table="Resume",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("resume", "dashboard", "analytics"),
    ),
    ResourceSource(
        key="stories",
        table="StoryEntry",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("stories",),
    ),
    ResourceSource(
        key="emails",
        table="EmailThread",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("email",),
    ),
    ResourceSource(
        key="contacts",
        table="Contact",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("networking",),
    ),
    ResourceSource(
        key="outreach",
        table="OutreachTask",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("networking",),
    ),
    ResourceSource(
        key="interviews",
        table="InterviewSchedule",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("interviews", "dashboard"),
    ),
    ResourceSource(
        key="offers",
        table="Offer",
        timestamp_columns=("createdAt", "updatedAt"),
        screens=("offers",),
    ),
    ResourceSource(
        key="approvals",
        table="ApprovalRequest",
        timestamp_columns=("createdAt", "resolvedAt", "executedAt"),
        screens=("approvals", "dashboard"),
    ),
    ResourceSource(
        key="agentRuns",
        table="AgentRun",
        timestamp_columns=("createdAt", "startedAt", "completedAt"),
        screens=("agents", "dashboard"),
    ),
)

#: Resource keys, for client-side validation and for the router's docs.
REALTIME_RESOURCE_KEYS: tuple[str, ...] = tuple(r.key for r in REALTIME_RESOURCES)


def _watermark_expression(resource: ResourceSource) -> str:
    columns = ", ".join(f'"{c}"' for c in resource.timestamp_columns)
    inner = f"GREATEST({columns})" if len(resource.timestamp_columns) > 1 else columns
    # Rendered as TEXT deliberately. The watermark is an opaque CHANGE TOKEN,
    # not a timestamp shown to anyone: the watched columns are a mix of
    # ``timestamp`` and ``timestamptz``, and casting them to a single type to
    # satisfy the UNION would apply the session time zone and put a subtly wrong
    # instant on the wire. Text preserves each column exactly as stored and
    # compares exactly, which is all change detection needs.
    return f"MAX({inner})::text"


def watermark_sql() -> str:
    """The single UNION ALL query one poll runs. Owner-scoped on every branch.

    The statement is assembled from :data:`REALTIME_RESOURCES` only — table,
    column and filter fragments are module constants; the sole runtime input is
    the bound ``%(user_id)s`` parameter.
    """
    branches = []
    for resource in REALTIME_RESOURCES:
        where = f' AND {resource.where}' if resource.where else ""
        branches.append(
            f"SELECT '{resource.key}' AS resource, "
            f"COUNT(*)::bigint AS row_count, "
            f"{_watermark_expression(resource)} AS watermark "
            f'FROM "{resource.table}" WHERE "userId" = %(user_id)s{where}'
        )
    return "\nUNION ALL\n".join(branches)


def read_watermarks(user_id: str) -> dict[str, dict[str, Any]]:
    """Observe every watched resource for one user in ONE round trip.

    Returns ``{resource_key: {"count": int, "watermark": str | None}}``. A
    resource with no rows yields ``count=0, watermark=None`` — a real
    observation of an empty resource, never a missing key.

    Exceptions are NOT swallowed: the caller turns a read failure into an
    explicit ``stream_error``/``503`` rather than a stream that silently stops
    noticing changes while still looking connected.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(watermark_sql(), {"user_id": user_id})
            rows = rows_to_dicts(cur)
    observed = {
        str(row["resource"]): {
            "count": int(row["row_count"]),
            "watermark": row["watermark"],
        }
        for row in rows
    }
    # Defensive: a branch that somehow returned no row is reported as unobserved
    # rather than silently dropped, so a diff can never read its absence as "no
    # change".
    for key in REALTIME_RESOURCE_KEYS:
        observed.setdefault(key, {"count": 0, "watermark": None})
    return observed


def diff_watermarks(
    previous: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Resources whose persisted state REALLY moved, with the evidence.

    A resource present in ``current`` but not in ``previous`` is not reported —
    that is a first observation, not a change, and the ``hello`` snapshot
    already told the client about it.
    """
    changes: list[dict[str, Any]] = []
    for key, now in current.items():
        before = previous.get(key)
        if before is None:
            continue
        count_changed = before.get("count") != now.get("count")
        watermark_changed = before.get("watermark") != now.get("watermark")
        if not (count_changed or watermark_changed):
            continue
        changes.append(
            {
                "resource": key,
                "count": now.get("count"),
                "watermark": now.get("watermark"),
                "previousCount": before.get("count"),
                "previousWatermark": before.get("watermark"),
                # Both tests can fire at once; ``watermark_advanced`` is reported
                # only when the count did NOT move, so the reason always names
                # the strongest thing observed.
                "reason": "count_changed" if count_changed else "watermark_advanced",
            }
        )
    changes.sort(key=lambda c: str(c["resource"]))
    return changes


async def iter_workspace_events(
    *,
    user_id: str,
    read_watermarks: Callable[[str], dict[str, dict[str, Any]]],
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    initial: dict[str, dict[str, Any]] | None = None,
    poll_interval: float | None = None,
    heartbeat_interval: float | None = None,
    max_seconds: float | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames for one already-authenticated user's workspace.

    ``read_watermarks`` is injected (rather than imported here) so the router
    passes the owner-scoped reader and tests can script observations without
    touching Postgres. It is called with ``user_id`` and nothing else: this
    generator cannot widen scope.

    ``initial`` lets the caller reuse the observation it already made to decide
    whether to admit the stream at all, instead of paying for a second query.

    Terminates on: client disconnect, the bounded lifetime (``stream_timeout``),
    or an unreadable state (``stream_error``). There is no terminal "done" — a
    workspace is never finished — so a client is expected to reconnect after
    ``stream_timeout`` and to show a truthful disconnected state until it does.
    """
    poll = poll_seconds() if poll_interval is None else poll_interval
    beat = heartbeat_seconds() if heartbeat_interval is None else heartbeat_interval
    lifetime = max_stream_seconds() if max_seconds is None else max_seconds
    channel = f"workspace:{user_id}"

    if initial is None:
        try:
            initial = await run_in_threadpool(read_watermarks, user_id)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            logger.exception("workspace stream %s: initial read failed", channel)
            yield sse_event(
                "stream_error",
                {
                    "channel": channel,
                    "message": "Could not read your workspace state; stream closed.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            )
            return

    observed = initial
    yield sse_comment(f"workspace stream {channel}")
    yield sse_event(
        "hello",
        {
            "channel": channel,
            "resources": observed,
            "pollSeconds": poll,
            "source": "persisted_row_watermarks",
        },
    )

    deadline = time.monotonic() + lifetime
    last_beat = time.monotonic()

    while True:
        if is_disconnected is not None and await is_disconnected():
            logger.info("workspace stream %s: client disconnected", channel)
            return

        if time.monotonic() >= deadline:
            yield sse_event(
                "stream_timeout",
                {
                    "channel": channel,
                    "message": (
                        "Stream reached its bounded lifetime. Nothing is wrong with "
                        "your data — reconnect to keep receiving live updates."
                    ),
                },
            )
            return

        await asyncio.sleep(poll)

        try:
            fresh = await run_in_threadpool(read_watermarks, user_id)
        except Exception as exc:  # noqa: BLE001 — surfaced, never swallowed
            logger.exception("workspace stream %s: watermark read failed", channel)
            yield sse_event(
                "stream_error",
                {
                    "channel": channel,
                    "message": "Could not read your workspace state; stream closed.",
                    "detail": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        changes = diff_watermarks(observed, fresh)
        observed = fresh
        if changes:
            last_beat = time.monotonic()
            for change in changes:
                yield sse_event(
                    "resource_changed",
                    {
                        "channel": channel,
                        "source": "persisted_row_watermarks",
                        **change,
                    },
                )
        elif time.monotonic() - last_beat >= beat:
            last_beat = time.monotonic()
            yield sse_comment(f"heartbeat {int(time.time())}")
