"""GMV4-sse-005 (BLOCKER) — SSE connection-ceiling DoS (§22 STEP 2, GOLD-MASTER-V4).

Binding ruling: ``docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md`` §5e.

Context verified before writing these tests:
  - ``apps/api/app/db.py:8-9`` documents a **25-connection hard ceiling** for
    the whole app (hosted Postgres).
  - ``AgentRunRepository.get_by_id`` (``apps/api/app/repositories/agent_run.py``)
    opens an UNPOOLED connection via ``get_connection()`` on every call, and
    ``app.services.agent_run_stream.iter_agent_run_events`` calls it once per
    poll (default ``AETHER_SSE_POLL_SECONDS=1.0``) for up to
    ``AETHER_SSE_MAX_STREAM_SECONDS`` (default 600s, floored at 5s) per open
    stream.
  - ``grep -n "concurrent\\|semaphore\\|Semaphore" apps/api/app/routers/agents.py
    apps/api/app/services/agent_run_stream.py`` -> zero matches: nothing caps
    concurrent streams, per-user or globally.
  - ``apps/api/app/rate_limit.py`` covers only login/register (identifier-keyed
    ``SlidingWindowRateLimiter``); it is never imported by
    ``apps/api/app/routers/agents.py``.
  - The real browser client polls every 3000ms
    (``apps/web/src/lib/api/agents.ts:57``, ``JOB_POLL_INTERVAL_MS``), so the
    1.0s SSE default is 3x MORE database load than the polling it claims to
    replace.

DB-FREE BY DESIGN, same discipline as ``test_agent_run_sse.py``: every test
here builds its own ``TestClient(create_app())`` and monkeypatches
``AgentRunRepository.get_by_id`` at the class level -- never the shared
``client``/``db_session`` fixtures, never ``app.db.get_connection`` for real.
No test in this file opens a real Postgres connection.

Design note (task-brief requirement): these tests pin BEHAVIOUR -- "a cap
exists", "the default is >= 3.0s", "rejection is honest and fast", "polling
stops promptly on disconnect" -- not a specific mechanism. A semaphore, a
pooled connection, or a rate limiter all satisfy them equally; none of the
assertions below inspect internal state, only externally observable HTTP
status/body/timing.

Concurrency mechanics (verified empirically before committing to this
design, not assumed): a SINGLE shared ``TestClient`` instance, hit from
multiple Python threads, genuinely serves requests concurrently (measured:
N truly-concurrent blocking requests, each bounded by the SAME
``AETHER_SSE_MAX_STREAM_SECONDS`` deadline, return together at ~that
deadline rather than serially at N times it). The GLOBAL-cap test varies the
authenticated user PER REQUEST via a ``Request``-based
``get_current_user`` override reading an ``X-Test-User-Id`` header, so many
distinct simulated users share ONE app/client instance -- deliberately
bypassing any PER-USER cap so what is actually being exercised is a GLOBAL
one.
"""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware.auth import get_current_user
from app.repositories.agent_run import AgentRunRepository
from app.services import agent_run_stream

OWNER_USER: dict[str, Any] = {"id": "sse-limits-owner-1", "email": "owner@example.com", "isAdmin": False}


@contextmanager
def _client_fixed_user(user: dict[str, Any]) -> Iterator[TestClient]:
    """ONE app/client for the whole ``with`` block, bound to a single fixed
    simulated user -- used so multiple threads share one app instance
    (and therefore whatever process/app-level cap state a real
    implementation would use) rather than each minting a fresh one."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    with TestClient(app) as client:
        yield client


@contextmanager
def _client_multi_user() -> Iterator[TestClient]:
    """ONE app/client whose simulated user varies PER REQUEST via the
    ``X-Test-User-Id`` header, read through a real FastAPI ``Request``
    dependency override. Lets many DISTINCT users share one app/client
    instance, deliberately bypassing any PER-USER cap so a GLOBAL cap is
    what actually gets exercised."""
    app = create_app()

    def _user_from_header(request: Request) -> dict[str, Any]:
        uid = request.headers.get("x-test-user-id") or "anon-test-user"
        return {"id": uid, "email": f"{uid}@example.com", "isAdmin": False}

    app.dependency_overrides[get_current_user] = _user_from_header
    with TestClient(app) as client:
        yield client


def _always_running(self: AgentRunRepository, run_id: str, user_id: str) -> dict[str, Any]:
    """A run that is real, owned, and NEVER reaches a terminal status --
    keeps ``iter_agent_run_events`` polling (and therefore the stream
    genuinely open) until ``AETHER_SSE_MAX_STREAM_SECONDS`` elapses, a
    rejection happens, or the client disconnects."""
    return {"id": run_id, "userId": user_id, "status": "running"}


def _fire_concurrent(
    client: TestClient, requests: list[tuple[str, dict[str, str]]], *, join_timeout: float
) -> tuple[list[tuple[int, int, float, str]], list[int]]:
    """Fire every ``(path, headers)`` pair as a real blocking GET from its
    own thread, all started before any is joined, so they genuinely overlap
    in time. Returns ``(results, hung_indices)`` where ``results`` is
    ``(index, status_code, elapsed_seconds, body_text)`` and ``hung_indices``
    lists any request whose thread was still alive after ``join_timeout`` --
    i.e. a real hang, never silently dropped."""
    results: list[tuple[int, int, float, str]] = []
    lock = threading.Lock()

    def worker(i: int, path: str, headers: dict[str, str]) -> None:
        t0 = time.monotonic()
        resp = client.get(path, headers=headers)
        elapsed = time.monotonic() - t0
        with lock:
            results.append((i, resp.status_code, elapsed, resp.text))

    threads = [
        threading.Thread(target=worker, args=(i, path, headers), daemon=True)
        for i, (path, headers) in enumerate(requests)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=join_timeout)
    hung = [i for i, t in enumerate(threads) if t.is_alive()]
    return results, hung


# --- 1/2. concurrent-stream caps -----------------------------------------------


def test_concurrent_streams_are_capped_per_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beyond some per-user cap, an additional stream for the SAME user must
    be rejected. MUST FAIL today: no per-user cap exists, so all N
    concurrent streams for one user succeed."""
    monkeypatch.setenv("AETHER_SSE_POLL_SECONDS", "0.1")
    monkeypatch.setenv("AETHER_SSE_MAX_STREAM_SECONDS", "5")
    monkeypatch.setattr(AgentRunRepository, "get_by_id", _always_running)

    n = 8  # comfortably above any sane per-user cap
    with _client_fixed_user(OWNER_USER) as client:
        requests = [(f"/agents/runs/cap-user-run-{i}/stream", {}) for i in range(n)]
        results, hung = _fire_concurrent(client, requests, join_timeout=20.0)

    assert not hung, (
        f"{len(hung)} of {n} same-user concurrent streams never returned at "
        f"all within the bounded join (real hang), indices={hung}"
    )
    assert len(results) == n, f"expected {n} results, got {len(results)}: {results}"
    statuses = [r[1] for r in results]
    rejected = [r for r in results if r[1] in (429, 503)]
    assert rejected, (
        f"none of {n} concurrent streams opened by the SAME user were "
        f"rejected -- no per-user concurrent-stream cap exists yet "
        f"(GMV4-sse-005, BLOCKER, §5e); statuses={statuses}"
    )


def test_concurrent_streams_are_capped_globally(monkeypatch: pytest.MonkeyPatch) -> None:
    """A GLOBAL cap must exist, sitting below the app-wide 25-connection
    ceiling WITH HEADROOM, independent of per-user identity. MUST FAIL
    today: no global cap exists, so all N distinct-user streams succeed
    simultaneously."""
    monkeypatch.setenv("AETHER_SSE_POLL_SECONDS", "0.1")
    monkeypatch.setenv("AETHER_SSE_MAX_STREAM_SECONDS", "5")
    monkeypatch.setattr(AgentRunRepository, "get_by_id", _always_running)

    n = 24  # near the 25-connection ceiling; each request is a DISTINCT user
    with _client_multi_user() as client:
        requests = [
            (f"/agents/runs/cap-global-run-{i}/stream", {"x-test-user-id": f"cap-global-user-{i}"})
            for i in range(n)
        ]
        results, hung = _fire_concurrent(client, requests, join_timeout=25.0)

    assert not hung, (
        f"{len(hung)} of {n} distinct-user concurrent streams never "
        f"returned at all within the bounded join (real hang), indices={hung}"
    )
    assert len(results) == n, f"expected {n} results, got {len(results)}: {results}"
    statuses = [r[1] for r in results]
    rejected = [r for r in results if r[1] in (429, 503)]
    assert rejected, (
        f"{n} concurrent streams from {n} DISTINCT users (deliberately "
        f"bypassing any per-user cap) all succeeded -- no GLOBAL "
        f"concurrent-stream cap exists yet (GMV4-sse-005, BLOCKER, §5e); "
        f"statuses={statuses}"
    )
    accepted = [r for r in results if r[1] == 200]
    assert len(accepted) <= 20, (
        f"{len(accepted)} of {n} distinct-user streams were accepted "
        f"simultaneously -- §5e requires the global cap sit below the "
        f"app-wide 25-connection ceiling WITH HEADROOM (>=5 free); "
        f"accepted={len(accepted)}"
    )


# --- 3. rejection must be honest, never a silent hang --------------------------


def test_stream_rejection_is_honest_not_a_silent_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the cap is exceeded, rejection must be an explicit 429/503 with a
    real message, returned FAST -- never a hang, never an empty 200 stream
    pretending to be a real success. MUST FAIL today: with no cap, nothing
    is ever rejected, so the honesty invariant has nothing to check against."""
    monkeypatch.setenv("AETHER_SSE_POLL_SECONDS", "0.1")
    monkeypatch.setenv("AETHER_SSE_MAX_STREAM_SECONDS", "5")
    monkeypatch.setattr(AgentRunRepository, "get_by_id", _always_running)

    n = 8
    with _client_fixed_user(OWNER_USER) as client:
        requests = [(f"/agents/runs/honest-run-{i}/stream", {}) for i in range(n)]
        results, hung = _fire_concurrent(client, requests, join_timeout=20.0)

    # The single strongest assertion this test makes: a real hang (a request
    # that never comes back at all) is the worst failure mode here.
    assert not hung, (
        f"{len(hung)} of {n} oversubscribed same-user streams NEVER "
        f"returned within the bounded join -- a silent hang is the worst "
        f"failure mode for a rejection path (§5e); indices={hung}"
    )
    assert len(results) == n, f"expected {n} results, got {len(results)}: {results}"

    for i, status, _elapsed, body in results:
        assert status in (200, 429, 503), f"unexpected status {status} for request {i}: {body[:200]!r}"
        if status == 200:
            assert body.strip(), (
                f"request {i} returned 200 with an EMPTY stream body -- a "
                f"silently-empty stream is as dishonest as a hang"
            )

    rejected = [r for r in results if r[1] in (429, 503)]
    assert rejected, (
        f"no request was rejected among {n} oversubscribed concurrent "
        f"streams for one user -- no connection-ceiling cap exists yet "
        f"(GMV4-sse-005, BLOCKER); statuses={[r[1] for r in results]}"
    )
    for i, status, elapsed, body in rejected:
        assert body.strip(), (
            f"rejected request {i} (status {status}) returned an EMPTY "
            f"body -- rejection must carry a real, honest message"
        )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        message = payload.get("detail") if isinstance(payload, dict) else None
        assert message, f"rejected request {i} (status {status}) has no real 'detail' message; body={body!r}"
        assert elapsed < 2.0, (
            f"rejected request {i} took {elapsed:.2f}s to come back -- a "
            f"rejection must be fast/upfront, not something that lingers "
            f"before finally saying no"
        )


# --- 4. default poll interval must not out-poll the client ---------------------


def test_default_poll_interval_is_not_more_aggressive_than_the_client_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5e binding requirement: the default ``AETHER_SSE_POLL_SECONDS`` must
    be >= 3.0s, matching the real client poll
    (``apps/web/src/lib/api/agents.ts:57``, ``JOB_POLL_INTERVAL_MS = 3000``).
    MUST FAIL today: the coded default is 1.0s."""
    monkeypatch.delenv("AETHER_SSE_POLL_SECONDS", raising=False)
    value = agent_run_stream.poll_seconds()
    assert value >= 3.0, (
        f"AETHER_SSE_POLL_SECONDS default resolved to {value}s -- MORE "
        f"aggressive than the real client poll of 3000ms "
        f"(apps/web/src/lib/api/agents.ts:57); §5e requires the default be "
        f">= 3.0s."
    )


# --- 5. disconnect must not leak polling/connections ----------------------------


def test_stream_releases_its_db_connection_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disconnected stream must stop polling (and therefore stop opening
    new DB connections -- every poll opens one, ``app/db.py:145-154``)
    promptly, not continue in the background for the rest of its bounded
    lifetime. Each poll is its own short-lived ``get_connection()`` call
    (``AgentRunRepository.get_by_id``), so "no further polls after
    disconnect" is the observable proxy for "no further connections opened
    after disconnect" in this codebase."""
    monkeypatch.setenv("AETHER_SSE_POLL_SECONDS", "0.1")
    monkeypatch.setenv("AETHER_SSE_MAX_STREAM_SECONDS", "10")
    call_count = {"n": 0}
    lock = threading.Lock()

    def _counting_running(self: AgentRunRepository, run_id: str, user_id: str) -> dict[str, Any]:
        with lock:
            call_count["n"] += 1
        return {"id": run_id, "userId": user_id, "status": "running"}

    monkeypatch.setattr(AgentRunRepository, "get_by_id", _counting_running)

    with _client_fixed_user(OWNER_USER) as client:
        with client.stream("GET", "/agents/runs/run-disconnect-1/stream") as resp:
            assert resp.status_code == 200, resp.status_code
            for line in resp.iter_lines():
                if line.startswith("event: snapshot"):
                    break
        # Context-manager exit == the client disconnects mid-stream, before
        # the run ever reaches a terminal status.
        n_at_close = call_count["n"]
        time.sleep(1.0)  # >> several poll intervals (poll=0.1s)
        n_after_wait = call_count["n"]

    assert n_after_wait <= n_at_close + 1, (
        "polling continued well after the client disconnected -- at most "
        f"ONE in-flight poll should complete post-disconnect; saw "
        f"{n_at_close} calls at close, {n_after_wait} calls 1s later "
        f"(GMV4-sse-005 leak: a stream left open in the background keeps "
        f"opening DB connections nobody is reading)."
    )
