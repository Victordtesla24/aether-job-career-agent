"""GMV4-sse-001 (BLOCKER) — no SSE layer exists (§22 STEP 2, GOLD-MASTER-V4).

Confirmed by grep before writing these tests:
  - ``grep -rn "text/event-stream" apps/api/app`` -> zero matches.
  - ``grep -rn "EventSource" apps/web/src`` -> zero matches.
  - ``grep -n 'runs/{' apps/api/app/routers/agents.py`` -> only
    ``GET /runs/{run_id}`` (a plain JSON poll, ``routers/agents.py:2150``); no
    ``/stream`` route registered anywhere.
So every request below currently 404s at FastAPI's own route-matching layer,
before any application code runs.

DB-FREE BY DESIGN. Each test builds its OWN ``TestClient(create_app())``
(never the ``client``/``db_session`` pytest fixtures, which call
``_truncate_tables()`` — the task brief flagged this as unsafe to run
alongside the separately-running full-suite pytest process holding
``/tmp/aether-pytest.lock``) and overrides ``get_current_user`` via
``app.dependency_overrides`` — FastAPI calls the override directly and never
resolves the original callable's own sub-dependencies (the bearer-token
parsing), so no real JWT/DB user lookup happens. Ownership-scoped tests
monkeypatch ``AgentRunRepository.get_by_id`` at the class level instead of
inserting real rows, so the run/ownership scenario is fully scripted and
reproducible with zero Postgres I/O — verified: a live run of this whole
file touches no table (see the "no DB" check baked into
``test_file_makes_no_db_connection`` below is intentionally NOT added —
instead this is asserted by construction: no test here imports
``get_connection``/uses ``client``/``db_session``).

Failure-mode discipline (task-brief requirement: "avoid tests that would
pass on any 404-returning route"): a bare ``status_code in (403, 404)``
assertion would trivially pass today because EVERY unmatched route 404s.
Every test below is therefore anchored on the POSITIVE case first (the
owning user's own, well-formed request must produce a real
``text/event-stream``) so the assertion that actually fails is diagnostic of
"the SSE layer does not exist" specifically — not merely "some 404
happened". ``test_sse_run_not_found_returns_404`` is the one exception
by necessity (it has no positive case) and is deliberately written to
distinguish the app's OWN "Agent run not found" 404 body (mirroring the
existing ``GET /runs/{run_id}`` handler, ``routers/agents.py:2150-2154``)
from FastAPI's generic unmatched-route ``{"detail": "Not Found"}`` body —
so it cannot pass merely because the route is missing.

No ``Workspace`` model exists in this codebase (``packages/db/src/schema.prisma``
has no such model — confirmed via ``grep -n '^model ' schema.prisma``); every
table's tenancy/isolation key is ``userId``. ``test_sse_emits_kanban_updated_on_channel``
therefore treats the owning user's id as the ``{workspace_id}`` in
``jobs:{workspace_id}`` (§14.5.5/§15.1) — documented ASSUMPTION, not verified
against a spec doc, since this repo has no separate workspace concept to
verify against.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware.auth import get_current_user
from app.repositories.agent_run import AgentRunRepository

OWNER_USER: dict[str, Any] = {"id": "sse-owner-1", "email": "owner@example.com", "isAdmin": False}
OTHER_USER: dict[str, Any] = {"id": "sse-other-1", "email": "other@example.com", "isAdmin": False}

#: §14.5.5/§15.1 — the documented ordered step sequence for a submission run.
EXPECTED_STEP_SEQUENCE = [
    "scanning_queue",
    "computing_ats_deltas",
    "awaiting_approval",
    "submitting",
    "updating_kanban",
    "complete",
]


@contextmanager
def _client_as(user: dict[str, Any]) -> Iterator[TestClient]:
    """A TestClient bound to a fresh app instance with ``get_current_user``
    overridden to ``user`` — no JWT, no DB user lookup, no truncation."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """Parses ``event: X\\ndata: {...}\\n\\n`` blocks into an ordered list of
    ``{"event": X, "data": <parsed JSON or raw text>}``, preserving order."""
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        event_name: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_name is None:
            continue
        raw_data = "\n".join(data_lines)
        try:
            data: Any = json.loads(raw_data) if raw_data else {}
        except json.JSONDecodeError:
            data = raw_data
        events.append({"event": event_name, "data": data})
    return events


# --- 1. endpoint existence + SSE headers -------------------------------------


def test_sse_endpoint_exists_and_sets_event_stream_content_type() -> None:
    """``GET /agents/runs/{id}/stream`` must exist and set the SSE headers.
    Today the route is unregistered, so this 404s before any header is set."""
    with _client_as(OWNER_USER) as client:
        resp = client.get("/agents/runs/some-run-id/stream")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    content_type = resp.headers.get("content-type", "")
    assert content_type.startswith("text/event-stream"), content_type
    assert resp.headers.get("cache-control") == "no-cache", resp.headers.get("cache-control")


# --- 2. ordered step events ---------------------------------------------------


def test_sse_stream_emits_progress_events_in_order() -> None:
    """The documented step sequence must arrive IN ORDER — asserts the full
    ordered list, not merely that each name appears somewhere in the body."""
    with _client_as(OWNER_USER) as client:
        resp = client.get("/agents/runs/some-run-id/stream")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    events = _parse_sse_events(resp.text)
    event_names = [e["event"] for e in events]
    assert event_names == EXPECTED_STEP_SEQUENCE, event_names


# --- 3. ownership boundary -----------------------------------------------------


def test_sse_stream_is_scoped_to_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run belonging to another user must never be streamable — 403/404,
    never a leaked event. Anchored on the POSITIVE (owner) case FIRST so this
    cannot pass merely because every unmatched route already 404s."""
    owner_run_id = "owned-run-1"

    def _fake_get_by_id(self: AgentRunRepository, run_id: str, user_id: str) -> dict[str, Any] | None:
        if run_id == owner_run_id and user_id == OWNER_USER["id"]:
            return {"id": owner_run_id, "userId": OWNER_USER["id"], "status": "completed"}
        return None  # a non-owner lookup resolves to "not found" — never leaks the row

    monkeypatch.setattr(AgentRunRepository, "get_by_id", _fake_get_by_id)

    with _client_as(OWNER_USER) as owner_client:
        resp_owner = owner_client.get(f"/agents/runs/{owner_run_id}/stream")
    # This is the assertion that actually fails today (right reason: no SSE
    # layer exists yet for ANYONE, owner included).
    assert resp_owner.status_code == 200, f"expected 200, got {resp_owner.status_code}: {resp_owner.text}"
    assert resp_owner.headers.get("content-type", "").startswith("text/event-stream")
    owner_events = _parse_sse_events(resp_owner.text)
    assert owner_events and owner_events[-1]["event"] == "complete", owner_events

    with _client_as(OTHER_USER) as other_client:
        resp_other = other_client.get(f"/agents/runs/{owner_run_id}/stream")
    assert resp_other.status_code in (403, 404), resp_other.status_code
    assert "text/event-stream" not in resp_other.headers.get("content-type", "")
    assert "event:" not in resp_other.text, "non-owner response must never leak SSE payload"


# --- 4. kanban_updated broadcast ----------------------------------------------


def test_sse_emits_kanban_updated_on_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    """A kanban advance during the run must emit ``kanban_updated`` carrying
    the workspace scope (``channel: "jobs:{workspace_id}"``) — see module
    docstring for the documented ``workspace_id == owning user id`` mapping
    (this codebase has no separate Workspace model)."""
    run_id = "run-kanban-1"
    monkeypatch.setattr(
        AgentRunRepository,
        "get_by_id",
        lambda self, rid, uid: {"id": run_id, "userId": OWNER_USER["id"], "status": "completed"},
    )

    with _client_as(OWNER_USER) as client:
        resp = client.get(f"/agents/runs/{run_id}/stream")

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    events = _parse_sse_events(resp.text)
    kanban_events = [e for e in events if e["event"] == "kanban_updated"]
    assert kanban_events, f"no 'kanban_updated' event in stream; events were {events}"
    channel = kanban_events[0]["data"].get("channel") if isinstance(kanban_events[0]["data"], dict) else None
    assert channel == f"jobs:{OWNER_USER['id']}", channel


# --- 5. terminates on complete -------------------------------------------------


def test_sse_stream_terminates_on_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stream must close after ``complete`` rather than hanging forever —
    bounded read PLUS an explicit "last event is complete" check (a bounded
    read alone would trivially pass on today's instant 404)."""
    run_id = "run-terminate-1"
    monkeypatch.setattr(
        AgentRunRepository,
        "get_by_id",
        lambda self, rid, uid: {"id": run_id, "userId": OWNER_USER["id"], "status": "completed"},
    )

    start = time.monotonic()
    with _client_as(OWNER_USER) as client:
        resp = client.get(f"/agents/runs/{run_id}/stream")
    elapsed = time.monotonic() - start

    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert elapsed < 10, f"stream took {elapsed:.1f}s — looks hung, never terminated"
    events = _parse_sse_events(resp.text)
    assert events, "no events parsed from the stream"
    assert events[-1]["event"] == "complete", events[-1]
    assert sum(1 for e in events if e["event"] == "complete") == 1, "complete must be terminal, not repeated"


# --- 6. unknown run id ---------------------------------------------------------


def test_sse_run_not_found_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown run id must produce the APP's own honest 404
    (``"Agent run not found"``, mirroring ``GET /runs/{run_id}`` at
    ``routers/agents.py:2150-2154``) — NOT merely FastAPI's generic
    unmatched-route ``{"detail": "Not Found"}``, which is what today's
    absent-route 404 actually returns. A bare status-code-only assertion
    would trivially pass today; the body-content assertion below is what
    actually distinguishes "route missing" from "run missing" and is what
    fails for the right reason."""
    monkeypatch.setattr(AgentRunRepository, "get_by_id", lambda self, rid, uid: None)

    with _client_as(OWNER_USER) as client:
        resp = client.get("/agents/runs/does-not-exist/stream")

    assert resp.status_code == 404, resp.status_code
    body = resp.json()
    assert body.get("detail") == "Agent run not found", (
        f"got FastAPI's generic unmatched-route 404 body {body!r} — the "
        "SSE route does not exist yet, so this is NOT the app's own "
        "'Agent run not found' handler"
    )
