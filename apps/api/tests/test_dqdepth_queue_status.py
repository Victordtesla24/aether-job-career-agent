"""D-QDEPTH — GET /queue/status: honest ARQ worker queue depth (RED first).

Exercises the three contractual states the ticket names:
  1. an anonymous caller gets 401 (auth required, like every other resource);
  2. a healthy Redis reply returns the EXACT ``LLEN`` count read off the
     ARQ default queue key;
  3. ANY Redis failure (down, timeout, wrong DSN, ...) degrades to an honest
     ``{"queuedJobs": null, "state": "unavailable"}`` over HTTP 200 — never a
     fabricated ``0`` and never a 500 that would make an operational blip
     look like an application bug.
"""
from __future__ import annotations

import app.routers.health as health_module


class _FakeRedisOk:
    """Stand-in for ``redis.Redis`` that answers ``LLEN`` with a fixed count."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.llen_calls: list[str] = []

    def llen(self, key: str) -> int:
        self.llen_calls.append(key)
        return self._count


class _FakeRedisBroken:
    """Stand-in for ``redis.Redis`` whose ``LLEN`` always raises."""

    def llen(self, key: str) -> int:  # noqa: ARG002
        raise ConnectionError("redis unavailable")


def test_queue_status_requires_auth(client) -> None:
    resp = client.get("/queue/status")
    assert resp.status_code == 401


def test_queue_status_returns_exact_llen_count(client, auth_headers, monkeypatch) -> None:
    fake = _FakeRedisOk(count=7)
    monkeypatch.setattr(health_module, "_get_redis_client", lambda: fake)

    resp = client.get("/queue/status", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"queuedJobs": 7, "state": "ok"}
    # Reads the ARQ worker's actual default queue key — not a guessed string.
    from arq.constants import default_queue_name

    assert fake.llen_calls == [default_queue_name]


def test_queue_status_zero_depth_is_still_ok(client, auth_headers, monkeypatch) -> None:
    fake = _FakeRedisOk(count=0)
    monkeypatch.setattr(health_module, "_get_redis_client", lambda: fake)

    resp = client.get("/queue/status", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"queuedJobs": 0, "state": "ok"}


def test_queue_status_redis_error_is_honest_unavailable_not_fabricated_zero(
    client, auth_headers, monkeypatch
) -> None:
    monkeypatch.setattr(health_module, "_get_redis_client", lambda: _FakeRedisBroken())

    resp = client.get("/queue/status", headers=auth_headers)

    # Never a 500 for an operational Redis blip — and never a silent 0 that
    # would look identical to "queue genuinely empty".
    assert resp.status_code == 200
    assert resp.json() == {"queuedJobs": None, "state": "unavailable"}
