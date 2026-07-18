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
import uuid
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

# LLM calls replay committed fixtures during tests (matches CI): a developer
# ``.env`` with AETHER_LLM_MODE=auto must never make the suite hit the live
# backend — rate limits / truncation would make results nondeterministic.
# Suites that exercise live/auto behaviour construct LLMClient(mode=...) or
# monkeypatch the env explicitly.
os.environ["AETHER_LLM_MODE"] = "replay"

# The paid-subscription entitlement gate (GAP-P6-PAYWALL) defaults ON in
# production. The bulk of the suite exercises the freemium (Free-tier) agent-run
# paths, so pin the gate OFF here — exactly like AETHER_LLM_MODE above. The
# dedicated gate suite (test_gap_p6_paywall) sets the flag EXPLICITLY per test.
os.environ["AETHER_REQUIRE_PAID_SUBSCRIPTION"] = "false"

# ---------------------------------------------------------------------------
# MV-system-003 — fail-closed guard against truncating the PRODUCTION schema.
#
# INCIDENT (2026-07-18, docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md):
# ``DATABASE_URL`` and ``DATABASE_URL_TEST`` point at the SAME Postgres
# host+database and differ ONLY by a ``?schema=`` query param
# (``aether`` vs. ``aether_test``). psycopg2 does not understand Prisma's
# ``schema=`` param at all — it only honours ``search_path`` via the
# connection's ``options=``. ``_truncate_tables()`` used to open its
# connection via ``app.db.get_connection()``, which derives its
# ``search_path`` from whatever ``DATABASE_URL`` happens to be in the
# process environment *at connection time*. If anything causes that to be
# the production DSN (e.g. a deploy script that sources the repo-root
# ``.env`` into the pytest process) the swap at the top of this file never
# ran, and the ``TRUNCATE ... CASCADE`` below lands on the production
# ``aether`` schema.
#
# The fix below is defense-in-depth and does not rely on the swap above at
# all:
#   1. The truncation connection is built ONLY from ``DATABASE_URL_TEST``,
#      parsed independently, with ``search_path`` pinned via ``options=``
#      (mirrors ``app/db.py``'s own Prisma-URL translation). It can
#      therefore never resolve to any schema other than the one named in
#      ``DATABASE_URL_TEST``.
#   2. Before truncating (and once, session-wide, before any fixture runs
#      at all), a LIVE ``SELECT current_schema()`` against that exact
#      connection is compared against the required ``aether_test`` name.
#      Anything else — including a legitimate-looking connection that
#      somehow still resolves to ``aether`` — aborts the whole session
#      (``pytest.exit(..., returncode=2)``) before any destructive SQL runs.
#   3. An explicit escape hatch, ``AETHER_ALLOW_PROD_TRUNCATE=1``, lets a
#      developer consciously override the guard (e.g. a differently-named
#      test schema). It must NEVER be set in CI/deploy — see
#      docs/delivery/DEPLOYMENT-RUNBOOK.md.
# ---------------------------------------------------------------------------


class ProdTruncationGuardError(RuntimeError):
    """Raised when the destructive test-truncation path would not be
    confined to the isolated ``aether_test`` schema. Fail-closed: this is
    raised (and the pytest session aborted) whenever safety cannot be
    POSITIVELY proven, not only when it is positively disproven.
    """


#: The only schema name ``_truncate_tables`` is ever allowed to target.
_REQUIRED_TEST_SCHEMA = "aether_test"

#: Explicit, never-in-CI escape hatch (see module docstring above).
_ALLOW_PROD_TRUNCATE_ENV = "AETHER_ALLOW_PROD_TRUNCATE"


def _resolve_truncation_dsn() -> tuple[str, str, str]:
    """Compute the exact ``(dsn, options, schema)`` the truncation
    connection will use, derived ONLY from ``DATABASE_URL_TEST`` — never
    from ``DATABASE_URL`` — so this pin holds even if the module-level swap
    above never ran (``DATABASE_URL_TEST`` unset, or something imported
    ``app.db`` before this module).

    Raises :class:`ProdTruncationGuardError` if ``DATABASE_URL_TEST`` is
    missing or carries no ``schema=`` param: an un-derivable target is
    treated as unsafe, not defaulted.
    """
    test_url = os.environ.get("DATABASE_URL_TEST") or _root_env.get("DATABASE_URL_TEST")
    if not test_url:
        raise ProdTruncationGuardError(
            "DATABASE_URL_TEST is not set; refusing to run destructive test "
            "fixtures with no verifiable test-schema target "
            "(see docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md)."
        )

    from app.db import _translate_prisma_url

    dsn, schema = _translate_prisma_url(test_url)
    if not schema:
        raise ProdTruncationGuardError(
            "DATABASE_URL_TEST has no '?schema=' query param; refusing to "
            "run destructive test fixtures with no verifiable test-schema "
            "target (see docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md)."
        )
    return dsn, f"-csearch_path={schema}", schema


def _assert_schema_is_safe_test_schema(
    resolved_schema: str | None, *, allow_override: bool = False
) -> None:
    """Pure guard logic — no DB I/O, no filesystem, no environment reads.

    Raises :class:`ProdTruncationGuardError` unless ``resolved_schema`` is
    exactly ``"aether_test"``. This is the function the MV-system-003
    regression test exercises directly with synthetic values (including a
    simulated ``"aether"`` production resolution) so the guard's decision
    logic is proven without ever opening a real connection.
    """
    if allow_override:
        return
    if resolved_schema != _REQUIRED_TEST_SCHEMA:
        raise ProdTruncationGuardError(
            "REFUSING TO RUN: test truncation would target schema "
            f"{resolved_schema!r}, not {_REQUIRED_TEST_SCHEMA!r}. "
            "See docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md. Set "
            f"{_ALLOW_PROD_TRUNCATE_ENV}=1 to consciously override "
            "(NEVER in CI/deploy)."
        )


def _live_resolved_schema(dsn: str, options: str) -> str | None:
    """Open a short-lived connection with the given pinned ``options`` and
    return what Postgres itself reports via ``SELECT current_schema()``.

    This is the ONLY place that performs real DB I/O for the guard; kept
    separate from :func:`_assert_schema_is_safe_test_schema` so the decision
    logic stays unit-testable without a network call.
    """
    import psycopg2

    conn = psycopg2.connect(dsn, options=options)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_schema()")
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _run_prod_truncate_guard() -> None:
    """Session-start guard: resolve the truncation target and verify (live)
    that it is the isolated ``aether_test`` schema, aborting the pytest
    session otherwise. Fails closed — any error resolving the DSN,
    connecting, or querying is treated as "not proven safe".
    """
    allow_override = os.environ.get(_ALLOW_PROD_TRUNCATE_ENV) == "1"
    if allow_override:
        return
    try:
        dsn, options, _schema_from_url = _resolve_truncation_dsn()
        resolved = _live_resolved_schema(dsn, options)
    except ProdTruncationGuardError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed on ANY error
        raise ProdTruncationGuardError(
            "REFUSING TO RUN: could not verify the test-truncation target "
            f"is the isolated 'aether_test' schema ({exc!r}). Failing "
            "closed per docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md."
        ) from exc
    _assert_schema_is_safe_test_schema(resolved, allow_override=allow_override)


def pytest_configure(config: pytest.Config) -> None:  # noqa: ARG001
    """Runs once, before collection and before any fixture executes. Aborts
    the ENTIRE pytest session (exit code 2) if the truncation guard cannot
    prove the destructive fixtures are confined to ``aether_test``.
    MV-system-003 (BLOCKER) — see docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md.
    """
    try:
        _run_prod_truncate_guard()
    except ProdTruncationGuardError as exc:
        pytest.exit(f"REFUSING TO RUN: {exc}", returncode=2)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: Tables owned by the suites that write to the DB, truncated between tests.
#: Includes tables from Prisma schema; additive tables (OutreachTask, InterviewSchedule)
#: are created lazily and not truncated.
_TABLES_TO_CLEAN = (
    '"AgentRun"',
    '"ApprovalRequest"',
    '"Application"',
    '"StoryEntry"',
    '"Resume"',
    '"Job"',
    '"User"',
    '"EmailThread"',
    '"Contact"',
    # AdminSetting (signup toggle etc.) is created lazily; truncating it between
    # tests keeps the signup-enabled default (true) isolated per test. Append-only
    # AdminAuditLog is deliberately NOT truncated (tests filter by actor id).
    '"AdminSetting"',
    # '"OutreachTask"',  # created lazily; may not exist yet
    # '"InterviewSchedule"',  # created lazily; may not exist yet
)


def _truncate_tables() -> None:
    """Truncate the suite's tables — ONLY ever on the pinned ``aether_test``
    connection built by :func:`_resolve_truncation_dsn`.

    Deliberately does NOT use ``app.db.get_connection()`` (which derives its
    search_path from whatever ``DATABASE_URL`` is currently in the process
    environment): this connection's target is derived exclusively from
    ``DATABASE_URL_TEST`` and re-verified live before every truncation, so it
    cannot be redirected to production by an environment mistake. See the
    MV-system-003 guard block above and
    docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md.
    """
    import psycopg2

    dsn, options, _schema_from_url = _resolve_truncation_dsn()
    allow_override = os.environ.get(_ALLOW_PROD_TRUNCATE_ENV) == "1"
    conn = psycopg2.connect(dsn, options=options)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_schema()")
            resolved = cur.fetchone()[0]
            _assert_schema_is_safe_test_schema(resolved, allow_override=allow_override)

            # Truncate only tables that exist (ignore missing ones).
            # This avoids errors with lazily-created tables.
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = ANY(current_schemas(false))
                  AND table_name = ANY(%s)
                """,
                ([t.strip('"') for t in _TABLES_TO_CLEAN],),
            )
            existing = [f'"{row[0]}"' for row in cur.fetchall()]
            if existing:
                cur.execute(f"TRUNCATE TABLE {', '.join(existing)} CASCADE")
        conn.commit()
    finally:
        conn.close()


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
    """Register + login a test user; return the Authorization header.

    Also stashes the user id on the client object so the ``test_user_id``
    fixture can retrieve it without a second API round-trip.
    """
    email = f"fixture-user-{uuid.uuid4().hex[:8]}@example.com"
    credentials = {"email": email, "password": "Sup3rSecret"}
    register = client.post("/auth/register", json=credentials)
    if register.status_code == 409:
        # Already exists; try login directly
        login = client.post("/auth/login", json=credentials)
        assert login.status_code == 200, login.text
    else:
        assert register.status_code == 201, register.text
        login = client.post("/auth/login", json=credentials)
        assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Stash user id for the test_user_id fixture
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    client._test_user_id = me.json()["id"]
    return headers


@pytest.fixture()
def test_user_id(client, auth_headers) -> str:
    """The user id of the fixture user created by ``auth_headers``.

    Use this in test files that need the user id for DB seeding or
    agent runs.  It avoids the stale-email-lookup pattern that broke
    when conftest switched to random UUID emails.
    """
    return client._test_user_id