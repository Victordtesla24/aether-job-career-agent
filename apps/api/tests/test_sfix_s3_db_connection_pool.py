"""S-3 — the API must never exceed its slice of the hosted 25-connection cap.

Before this, ``app.db.get_connection`` dialled a FRESH ``psycopg2.connect`` on
every use and closed it afterwards, with no pool and no limiter: sync FastAPI
route handlers run on anyio's ~40-thread default executor, so ~40 simultaneous
connections were reachable from one uvicorn process against a database that
refuses the 26th. These tests pin the three properties that fix requires:

1. concurrent open connections are BOUNDED by the configured pool max;
2. exceeding it fails HONESTLY and PROMPTLY (503, never an unbounded hang);
3. connections are returned to the pool — including when the caller's block
   raises — so a burst of sequential requests never leaks the pool empty.
"""
from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi import HTTPException

import app.db as db


@pytest.fixture()
def tiny_pool(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A 2-connection pool with a 0.25s acquire timeout, torn down cleanly."""
    monkeypatch.setenv("AETHER_DB_POOL_MAX", "2")
    monkeypatch.setenv("AETHER_DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "0.25")
    db.reset_pool()
    try:
        yield
    finally:
        db.reset_pool()


def test_pool_caps_concurrent_connections_and_503s_instead_of_hanging(tiny_pool):
    """The (max+1)th simultaneous connection is refused, fast and honestly."""
    with db.get_connection() as first, db.get_connection() as second:
        assert first is not second
        stats = db.pool_stats()
        assert stats["max"] == 2
        assert stats["leased"] == 2
        assert stats["open"] == 2

        started = time.monotonic()
        with pytest.raises(HTTPException) as exc:
            with db.get_connection():
                pytest.fail("a third connection must not be handed out")
        waited = time.monotonic() - started

    assert exc.value.status_code == 503
    # Bounded wait: it gave up near its own timeout, it did not hang the caller.
    assert waited < 5.0, f"acquire waited {waited:.2f}s — must be bounded"
    # Still capped while the failure happened: never a 3rd real connection.
    assert db.pool_stats()["open"] <= 2


def test_connections_are_released_back_to_the_pool(tiny_pool):
    """Sequential use never leaks: leased returns to 0 and open stays capped."""
    for _ in range(6):
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
        stats = db.pool_stats()
        assert stats["leased"] == 0
        assert stats["open"] <= 2


def test_connection_is_released_when_the_caller_raises(tiny_pool):
    """An exception inside the ``with`` block must not strand a connection."""
    with pytest.raises(ValueError):
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            raise ValueError("caller blew up")
    assert db.pool_stats()["leased"] == 0
    # The pool is still usable afterwards.
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1


def test_uncommitted_work_is_rolled_back_before_reuse(tiny_pool):
    """A pooled connection must never hand the next borrower an open txn."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE _sfix_s3_probe (v int)")
            cur.execute("INSERT INTO _sfix_s3_probe VALUES (1)")
        # deliberately NOT committed
    with db.get_connection() as conn:
        assert (
            conn.get_transaction_status()
            == db.psycopg2.extensions.TRANSACTION_STATUS_IDLE
        )


def test_pool_max_is_configurable_and_defaults_within_the_hosted_cap():
    """The default slice leaves headroom under the hosted 25-connection cap."""
    assert db._DEFAULT_POOL_MAX == 12
    assert db._DEFAULT_POOL_MAX < 25
