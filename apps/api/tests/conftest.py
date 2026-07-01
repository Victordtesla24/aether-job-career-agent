"""Shared pytest fixtures for the Aether API test-suite (P2-S01).

These fixtures back the database-integration tests introduced in Phase 2. They
deliberately talk to a *real* Postgres test database (``aether_test``) migrated
by Prisma — per DECISIONS D-0013, Postgres (Prisma-migrated) is the single
source of truth and the Python services run raw SQL against it, so the tests
exercise the genuine schema rather than an in-memory stand-in.

Fixtures
--------
``db_session``
    A psycopg2 connection (autocommit) to the test database, handed to
    repositories for direct state assertions.
``client``
    A FastAPI ``TestClient`` whose ``get_db`` dependency is overridden to point
    at the test database, so HTTP requests and assertions share one store.
``auth_headers``
    Registers a user through the real endpoints and returns request headers
    carrying a valid Bearer JWT plus a convenience ``X-User-Id``.
``_clean_tables`` (autouse)
    Truncates all mutable tables before every test for isolation.

The connection URL is read from ``DATABASE_URL_TEST`` (falling back to the
local default) so CI can point it elsewhere without code changes.
"""
from __future__ import annotations

import os

import pytest

TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST",
    "postgresql://aether:aether@localhost:5432/aether_test",
)

# Mutable tables cleared between tests. CASCADE + RESTART IDENTITY keeps every
# test hermetic regardless of insertion order or foreign-key relationships.
_MUTABLE_TABLES = (
    '"AgentRun"',
    '"StoryEntry"',
    '"EmailThread"',
    '"Contact"',
    '"ApprovalRequest"',
    '"Application"',
    '"Resume"',
    '"JobEmbedding"',
    '"Job"',
    '"User"',
)


def _connect(*, autocommit: bool = True):
    """Open a psycopg2 connection to the test database."""
    import psycopg2

    conn = psycopg2.connect(TEST_DB_URL)
    conn.autocommit = autocommit
    return conn


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate mutable tables before each test for isolation."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"TRUNCATE {', '.join(_MUTABLE_TABLES)} RESTART IDENTITY CASCADE;"
            )
    finally:
        conn.close()
    yield


@pytest.fixture()
def db_session():
    """A direct (autocommit) connection to the test DB for assertions."""
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture()
def client():
    """A TestClient bound to the test database via a dependency override."""
    # Ensure any settings-driven code paths also see the test database.
    os.environ["DATABASE_URL"] = TEST_DB_URL
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import get_db
    from app.main import create_app

    get_settings.cache_clear()

    def _override_get_db():
        conn = _connect()
        try:
            yield conn
        finally:
            conn.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture()
def auth_headers(client):
    """Register a user via the real API and return authenticated headers.

    The returned mapping carries the ``Authorization: Bearer <jwt>`` header the
    API verifies, plus ``X-User-Id`` as a test convenience so assertions can
    look the persisted user up by id.
    """
    email = "fixture-user@aether.dev"
    password = "Passw0rd1"
    reg = client.post("/auth/register", json={"email": email, "password": password})
    user_id = reg.json()["id"]
    login = client.post("/auth/login", json={"email": email, "password": password})
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-User-Id": user_id}
