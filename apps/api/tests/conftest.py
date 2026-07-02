"""Shared pytest fixtures for the Aether API test-suite (P2-S01+).

Key responsibilities:
- Point the app at the TEST database (``DATABASE_URL_TEST`` → ``aether_test``
  schema) *before* the app/settings modules are imported.
- Provide a ``client`` (FastAPI TestClient), a ``db_session`` (raw psycopg2
  connection with per-test table cleanup), and ``auth_headers`` (a registered
  and logged-in test user's Authorization header).
"""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap — must run at import time, before ``app.*`` imports.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "http"

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(.*))$")


def _load_root_env() -> dict[str, str]:
    """Parse the repo-root ``.env`` without requiring python-dotenv."""
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if match:
            key = match.group(1)
            value = next(g for g in match.groups()[1:] if g is not None)
            values[key] = value
    return values


_root_env = _load_root_env()

# Tests must never touch the real ``aether`` schema: swap in the test URL.
_test_url = os.environ.get("DATABASE_URL_TEST") or _root_env.get("DATABASE_URL_TEST")
if _test_url:
    os.environ["DATABASE_URL"] = _test_url
    os.environ["DATABASE_URL_TEST"] = _test_url

# A deterministic JWT secret for the suite (falls back if .env lacks one).
os.environ.setdefault("NEXTAUTH_SECRET", _root_env.get("NEXTAUTH_SECRET", "test-secret"))

# Discovery adapters run in fixture mode during tests: no live HTTP.
os.environ["AETHER_DISCOVERY_FIXTURE_DIR"] = str(FIXTURE_DIR)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Tables owned by the suites that write to the DB, truncated between tests.
_TABLES_TO_CLEAN = (
    '"AgentRun"',
    '"ApprovalRequest"',
    '"Application"',
    '"StoryEntry"',
    '"Resume"',
    '"Job"',
    '"User"',
)


def _truncate_tables() -> None:
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {', '.join(_TABLES_TO_CLEAN)} CASCADE")
        conn.commit()


@pytest.fixture()
def db_session() -> Iterator:
    """A raw psycopg2 connection to the TEST database.

    Cleanup note: table truncation happens in the ``client`` fixture (which
    every DB-touching test uses) so that ``db_session`` can be requested
    *after* ``auth_headers`` without wiping the just-registered user.
    """
    from app.db import get_connection

    with get_connection() as conn:
        yield conn


@pytest.fixture()
def client() -> Iterator:
    """FastAPI TestClient bound to a fresh app instance and a clean DB."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    _truncate_tables()
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client) -> dict[str, str]:
    """Register + login a test user; return the Authorization header."""
    credentials = {"email": "fixture-user@example.com", "password": "Sup3rSecret"}
    register = client.post("/auth/register", json=credentials)
    assert register.status_code == 201, register.text
    login = client.post("/auth/login", json=credentials)
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
