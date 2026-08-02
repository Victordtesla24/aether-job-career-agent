"""W-RT — one shared, user-scoped realtime channel for the whole dashboard.

WHY THIS FILE EXISTS (state of the tree before it was written, verified by grep)
-------------------------------------------------------------------------------
``grep -rn "text/event-stream" apps/api/app`` -> exactly ONE route:
``GET /agents/runs/{run_id}/stream`` (``app/routers/agents.py``). That stream is
scoped to a SINGLE agent run and emits only that run's row transitions, so it
can never tell the Jobs board that a job was discovered, or the Applications
board that a card moved, or the Story Bank that a story was written.

``grep -rn "EventSource" apps/web/src`` -> ZERO matches: no client consumes any
stream at all. Every screen refreshes by polling or not at all:

  * jobs           - ``setInterval(tick, 20_000)``      (app/dashboard/jobs/page.tsx:441)
  * applications   - ``setInterval(tick, 20_000)``      (app/dashboard/applications/page.tsx:513)
  * stories        - ``usePolling(..., 20_000)``        (app/dashboard/stories/page.tsx:69)
  * dashboard      - ``usePolling``                     (app/dashboard/page.tsx)
  * agents         - job-run poll only while a run is in flight (agents/page.tsx:229)
  * resume, cover-letters, email, networking, analytics, interviews
                   - mount-time ``useEffect`` fetch ONLY; nothing ever refreshes
                     them, so an agent writing a résumé/letter/thread/contact/
                     interview is invisible until the user reloads by hand.

These tests pin the ADDITIVE mechanism that fixes that: a single user-scoped
stream whose events are derived from REAL persisted state, reusing the existing
SSE primitives (wire format, headers, admission control) rather than inventing a
parallel transport.

HONESTY CONSTRAINTS PINNED HERE (ADR-GMV4-003, governance §5d)
--------------------------------------------------------------
* An event may only be emitted when the persisted state it names REALLY changed.
  ``test_resource_changed_only_for_resources_that_really_changed`` fails if the
  stream fans out a change to a resource whose watermark did not move — that
  would be the same class of false statement ``kanban_updated`` was withheld for.
* A stream that ends without being able to observe state must SAY SO
  (``stream_error`` / ``stream_timeout``) and close, never hang and never
  pretend the last snapshot is current.
* Admission control is SHARED with the agent-run stream (one global budget
  against the 25-connection Postgres ceiling), not a second uncapped pool.

DB-FREE BY DESIGN, exactly as ``tests/test_agent_run_sse.py`` is: each test
builds its own ``TestClient(create_app())`` and overrides ``get_current_user``,
and the watermark reader is scripted, so no table is touched and the
``/tmp/aether-pytest.lock`` truncation fixture is never involved.
"""
from __future__ import annotations

import asyncio
import json
import re
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware.auth import get_current_user

OWNER: dict[str, Any] = {"id": "rt-owner-1", "email": "owner@example.com", "isAdmin": False}


@contextmanager
def _client_as(user: dict[str, Any]) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        name: str | None = None
        data: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].strip())
        if name is None:
            continue
        raw = "\n".join(data)
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        events.append({"event": name, "data": parsed})
    return events


async def _drain(agen: Any, limit: int = 200) -> list[str]:
    frames: list[str] = []
    async for frame in agen:
        frames.append(frame)
        if len(frames) >= limit:
            break
    return frames


# ---------------------------------------------------------------------------
# 1. The resource map has to actually cover the screens it claims to serve.
# ---------------------------------------------------------------------------


def test_resource_map_covers_every_dashboard_screen() -> None:
    """Every screen listed in the module docstring must have a resource whose
    rows really back it, or the "one channel updates every screen" claim is
    false for the screens it silently omits."""
    from app.services.workspace_event_stream import REALTIME_RESOURCES

    keys = {r.key for r in REALTIME_RESOURCES}
    required = {
        "jobs",            # Jobs board
        "applications",    # Applications kanban + dashboard + analytics
        "coverLetters",    # Cover Letters screen
        "resumes",         # Resume screen
        "stories",         # Story Bank
        "emails",          # Email Center
        "contacts",        # Networking
        "interviews",      # Interviews
        "approvals",       # Approvals queue
        "agentRuns",       # Agents screen / Agent Pulse
    }
    assert required <= keys, f"resources missing for screens: {sorted(required - keys)}"

    # Each resource must name a real table with a real tenancy key, and at least
    # one real timestamp column to watermark on — no invented sources.
    for resource in REALTIME_RESOURCES:
        assert resource.table, resource.key
        assert resource.timestamp_columns, resource.key


def test_watermark_sql_is_owner_scoped_and_single_round_trip() -> None:
    """One query per poll (a UNION ALL), every branch filtered by ``userId``.

    A per-resource query would be 10+ short-lived connections per poll per
    stream against a 25-connection deployment ceiling (app/db.py:8-9)."""
    from app.services.workspace_event_stream import REALTIME_RESOURCES, watermark_sql

    sql = watermark_sql()
    assert sql.count("UNION ALL") == len(REALTIME_RESOURCES) - 1
    branches = re.split(r"\bUNION ALL\b", sql)
    assert len(branches) == len(REALTIME_RESOURCES)
    for branch in branches:
        assert '"userId" = %(user_id)s' in branch, branch


# ---------------------------------------------------------------------------
# 2. Emission semantics — the core honesty property.
# ---------------------------------------------------------------------------


def test_hello_frame_carries_the_real_connect_time_snapshot() -> None:
    from app.services.workspace_event_stream import iter_workspace_events

    snapshot = {
        "jobs": {"count": 3, "watermark": "2026-08-02 01:00:00"},
        "applications": {"count": 1, "watermark": "2026-08-02 00:30:00"},
    }

    def reader(user_id: str) -> dict[str, dict[str, Any]]:
        assert user_id == OWNER["id"]
        return snapshot

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=reader,
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=0.05,
            )
        )
    )
    events = _parse_sse("".join(frames))
    assert events[0]["event"] == "hello"
    assert events[0]["data"]["channel"] == f"workspace:{OWNER['id']}"
    assert events[0]["data"]["resources"] == snapshot
    assert events[0]["data"]["source"] == "persisted_row_watermarks"


def test_resource_changed_only_for_resources_that_really_changed() -> None:
    """THE anti-fabrication property of this stream.

    Two resources are observed; only ``jobs`` moves. A ``resource_changed`` for
    ``applications`` would tell every connected client that its applications
    data is out of date when the persisted rows say it is not."""
    from app.services.workspace_event_stream import iter_workspace_events

    states = [
        {
            "jobs": {"count": 3, "watermark": "2026-08-02 01:00:00"},
            "applications": {"count": 1, "watermark": "2026-08-02 00:30:00"},
        },
        {
            "jobs": {"count": 5, "watermark": "2026-08-02 01:05:00"},
            "applications": {"count": 1, "watermark": "2026-08-02 00:30:00"},
        },
    ]
    calls = {"n": 0}

    def reader(_user_id: str) -> dict[str, dict[str, Any]]:
        idx = min(calls["n"], len(states) - 1)
        calls["n"] += 1
        return states[idx]

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=reader,
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=0.2,
            )
        )
    )
    events = _parse_sse("".join(frames))
    changed = [e for e in events if e["event"] == "resource_changed"]
    assert [e["data"]["resource"] for e in changed] == ["jobs"], changed
    assert changed[0]["data"]["count"] == 5
    assert changed[0]["data"]["previousCount"] == 3
    assert changed[0]["data"]["watermark"] == "2026-08-02 01:05:00"
    assert changed[0]["data"]["channel"] == f"workspace:{OWNER['id']}"


def test_status_only_change_still_emits_when_watermark_moves() -> None:
    """A row that is UPDATED (count unchanged) must still be broadcast — that is
    the applications-kanban stage move and the agent-run status transition."""
    from app.services.workspace_event_stream import iter_workspace_events

    states = [
        {"applications": {"count": 2, "watermark": "2026-08-02 01:00:00"}},
        {"applications": {"count": 2, "watermark": "2026-08-02 01:00:09"}},
    ]
    calls = {"n": 0}

    def reader(_user_id: str) -> dict[str, dict[str, Any]]:
        idx = min(calls["n"], len(states) - 1)
        calls["n"] += 1
        return states[idx]

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=reader,
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=0.2,
            )
        )
    )
    changed = [e for e in _parse_sse("".join(frames)) if e["event"] == "resource_changed"]
    assert len(changed) == 1
    assert changed[0]["data"]["reason"] == "watermark_advanced"


def test_quiet_stream_emits_heartbeats_and_no_events() -> None:
    from app.services.workspace_event_stream import iter_workspace_events

    state = {"jobs": {"count": 1, "watermark": "2026-08-02 01:00:00"}}
    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=lambda _u: state,
                poll_interval=0.001,
                heartbeat_interval=0.005,
                max_seconds=0.08,
            )
        )
    )
    body = "".join(frames)
    assert "event: resource_changed" not in body
    assert ": heartbeat" in body


def test_stream_says_so_when_state_cannot_be_read() -> None:
    """An unreadable database closes the stream with an explicit ``stream_error``.
    It must never keep the connection open implying the last snapshot is live."""
    from app.services.workspace_event_stream import iter_workspace_events

    calls = {"n": 0}

    def reader(_user_id: str) -> dict[str, dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"jobs": {"count": 1, "watermark": "w1"}}
        raise RuntimeError("connection refused")

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=reader,
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=5.0,
            )
        )
    )
    events = _parse_sse("".join(frames))
    assert events[-1]["event"] == "stream_error"
    assert "RuntimeError" in events[-1]["data"]["detail"]


def test_stream_closes_with_timeout_at_its_bounded_lifetime() -> None:
    from app.services.workspace_event_stream import iter_workspace_events

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=lambda _u: {"jobs": {"count": 0, "watermark": None}},
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=0.03,
            )
        )
    )
    events = _parse_sse("".join(frames))
    assert events[-1]["event"] == "stream_timeout"
    assert "reconnect" in events[-1]["data"]["message"].lower()


def test_client_disconnect_ends_the_stream() -> None:
    from app.services.workspace_event_stream import iter_workspace_events

    async def disconnected() -> bool:
        return True

    frames = asyncio.run(
        _drain(
            iter_workspace_events(
                user_id=OWNER["id"],
                read_watermarks=lambda _u: {"jobs": {"count": 0, "watermark": None}},
                is_disconnected=disconnected,
                poll_interval=0.001,
                heartbeat_interval=1000.0,
                max_seconds=5.0,
            )
        )
    )
    body = "".join(frames)
    assert "event: hello" in body
    assert "stream_timeout" not in body


# ---------------------------------------------------------------------------
# 3. The HTTP surface.
# ---------------------------------------------------------------------------


def test_route_serves_text_event_stream_with_the_nginx_optout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routers.events as events_router

    monkeypatch.setattr(
        events_router,
        "read_watermarks",
        lambda _user_id: {"jobs": {"count": 2, "watermark": "w1"}},
    )
    monkeypatch.setenv("AETHER_SSE_MAX_STREAM_SECONDS", "5")
    monkeypatch.setenv("AETHER_SSE_POLL_SECONDS", "0.05")

    with _client_as(OWNER) as client:
        with client.stream("GET", "/events/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            # X-Accel-Buffering is load-bearing behind the production nginx.
            assert response.headers.get("x-accel-buffering") == "no"
            first = next(response.iter_lines())
            assert "hello" in first or first.startswith(":")


def test_route_requires_authentication() -> None:
    """No dependency override -> the real bearer-token guard runs. A workspace
    stream is a firehose of one user's data; it must never be anonymous."""
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/events/stream")
    assert response.status_code in (401, 403), response.status_code


def test_admission_control_is_shared_with_the_agent_run_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-user cap must come from the SAME ``StreamSlots`` the agent-run
    stream uses, so N screens cannot open N uncapped connections."""
    import app.routers.events as events_router
    from app.services.agent_run_stream import StreamCapExceeded

    monkeypatch.setattr(
        events_router,
        "read_watermarks",
        lambda _user_id: {"jobs": {"count": 0, "watermark": None}},
    )

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: OWNER

    slots = app.state.sse_stream_slots

    def refuse(_user_id: str) -> int:
        raise StreamCapExceeded(
            scope="user",
            limit=3,
            message="Too many live streams open for this account.",
        )

    monkeypatch.setattr(slots, "acquire", refuse)

    with TestClient(app) as client:
        response = client.get("/events/stream")
    assert response.status_code == 429
    assert "Too many live streams" in response.text
    assert response.headers.get("Retry-After") == "5"


def test_cap_message_does_not_misdescribe_which_streams_are_open() -> None:
    """``StreamSlots`` is now SHARED between the agent-run stream and this one.

    Its refusal text was written when agent-run streams were the only kind, so
    it says "agent-run streams" and points the caller at
    ``GET /agents/runs/{run_id}``. Told to a dashboard user whose live-update
    stream was refused, both statements are false: they may have started no
    agent run at all, and that endpoint cannot tell them anything about the
    resources they were watching. Verified live against a real deployment on
    2026-08-02 — the 429 body carried exactly that wrong text.
    """
    from app.services.agent_run_stream import (
        StreamCapExceeded,
        StreamSlots,
        max_concurrent_streams,
        max_streams_per_user,
    )

    slots = StreamSlots()
    for _ in range(max_streams_per_user()):
        slots.acquire("cap-user")
    with pytest.raises(StreamCapExceeded) as user_exc:
        slots.acquire("cap-user")
    assert user_exc.value.scope == "user"
    assert "agent-run" not in user_exc.value.message
    assert "/agents/runs/" not in user_exc.value.message

    fresh = StreamSlots()
    for index in range(max_concurrent_streams()):
        fresh.acquire(f"user-{index}")
    with pytest.raises(StreamCapExceeded) as global_exc:
        fresh.acquire("one-more")
    assert global_exc.value.scope == "global"
    assert "agent-run" not in global_exc.value.message
    assert "/agents/runs/" not in global_exc.value.message


def test_unreadable_state_at_connect_is_an_honest_503_not_an_empty_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routers.events as events_router

    def boom(_user_id: str) -> dict[str, Any]:
        raise RuntimeError("db down")

    monkeypatch.setattr(events_router, "read_watermarks", boom)

    with _client_as(OWNER) as client:
        response = client.get("/events/stream")
    assert response.status_code == 503
    assert "stream" in response.text.lower()


def test_refused_stream_does_not_leak_an_admission_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.routers.events as events_router

    monkeypatch.setattr(
        events_router, "read_watermarks", lambda _u: (_ for _ in ()).throw(RuntimeError("x"))
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: OWNER
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get("/events/stream").status_code == 503
    assert app.state.sse_stream_slots.active_count() == 0
