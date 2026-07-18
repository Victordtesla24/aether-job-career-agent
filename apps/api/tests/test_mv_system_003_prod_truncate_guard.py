"""Regression test for MV-system-003 (BLOCKER).

Proves the fail-closed guard in ``apps/api/tests/conftest.py`` that stops the
test suite's destructive ``TRUNCATE ... CASCADE`` from ever hitting the
production ``aether`` schema. See
``docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`` for the incident this
guards against.

Hermetic by design: every test here calls the guard's PURE decision function
(``_assert_schema_is_safe_test_schema``) or the DSN-derivation function
(``_resolve_truncation_dsn``) directly with synthetic/monkeypatched inputs.
None of these tests open a real database connection, let alone a production
one — the live-connecting helper (``_live_resolved_schema``) is exercised
only indirectly, and only against ``DATABASE_URL_TEST`` (never production),
by the ordinary test suite's ``client``/``db_session`` fixtures elsewhere.
"""
from __future__ import annotations

import conftest as ct
import pytest

# ---------------------------------------------------------------------------
# (a) A resolution of "aether" (production-shaped) must be REJECTED.
# ---------------------------------------------------------------------------


def test_guard_rejects_prod_schema_resolution():
    """Simulates the exact incident: the truncation connection's live
    ``current_schema()`` resolves to ``aether`` (production). The guard must
    raise, unconditionally, with no DB I/O involved.
    """
    with pytest.raises(ct.ProdTruncationGuardError, match="aether"):
        ct._assert_schema_is_safe_test_schema("aether")


def test_guard_rejects_none_resolution():
    """No schema at all (e.g. a query returned nothing) is also unsafe."""
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._assert_schema_is_safe_test_schema(None)


def test_guard_rejects_any_other_schema_name():
    """Anything that isn't literally 'aether_test' is refused — not just the
    known production name. An unrecognized schema is unsafe by default.
    """
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._assert_schema_is_safe_test_schema("public")


# ---------------------------------------------------------------------------
# (b) A resolution of "aether_test" must PROCEED (no exception).
# ---------------------------------------------------------------------------


def test_guard_allows_test_schema_resolution():
    """The one and only schema the guard allows through."""
    ct._assert_schema_is_safe_test_schema("aether_test")  # must not raise


# ---------------------------------------------------------------------------
# Explicit escape hatch: AETHER_ALLOW_PROD_TRUNCATE=1 (never in CI/deploy).
# ---------------------------------------------------------------------------


def test_guard_override_bypasses_rejection():
    """The escape hatch, when explicitly requested by the caller, allows
    even an 'aether' resolution through. This proves the override is real
    and the guard is therefore deterministic/testable, per the brief.
    """
    ct._assert_schema_is_safe_test_schema("aether", allow_override=True)  # must not raise


def test_run_prod_truncate_guard_short_circuits_on_env_override(monkeypatch):
    """``_run_prod_truncate_guard`` must skip its (live) resolution path
    entirely when ``AETHER_ALLOW_PROD_TRUNCATE=1`` is set — proven here by
    making the DSN-resolution step blow up and asserting it's never reached.
    """
    monkeypatch.setenv(ct._ALLOW_PROD_TRUNCATE_ENV, "1")

    def _boom():
        raise AssertionError("must not be called when override is set")

    monkeypatch.setattr(ct, "_resolve_truncation_dsn", _boom)
    ct._run_prod_truncate_guard()  # must not raise


def test_run_prod_truncate_guard_fails_closed_when_dsn_unresolvable(monkeypatch):
    """Without the override, if the DSN can't even be resolved (e.g.
    DATABASE_URL_TEST unset/malformed), the guard still refuses — it does
    not silently skip the check.
    """
    monkeypatch.delenv(ct._ALLOW_PROD_TRUNCATE_ENV, raising=False)

    def _raise_guard_error():
        raise ct.ProdTruncationGuardError("DATABASE_URL_TEST is not set")

    monkeypatch.setattr(ct, "_resolve_truncation_dsn", _raise_guard_error)
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._run_prod_truncate_guard()


def test_run_prod_truncate_guard_fails_closed_on_connection_error(monkeypatch):
    """Any error while resolving the DSN or querying the live schema (e.g. a
    network blip) is treated as "not proven safe", never as "assume safe".
    """
    monkeypatch.delenv(ct._ALLOW_PROD_TRUNCATE_ENV, raising=False)
    monkeypatch.setattr(
        ct, "_resolve_truncation_dsn", lambda: ("postgresql://x/y", "-csearch_path=z", "z")
    )

    def _boom(dsn, options):
        raise OSError("could not connect to server")

    monkeypatch.setattr(ct, "_live_resolved_schema", _boom)
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._run_prod_truncate_guard()


def test_run_prod_truncate_guard_proceeds_for_real_test_schema(monkeypatch):
    """Positive path: when the (mocked) live resolution reports
    'aether_test', the guard proceeds without raising.
    """
    monkeypatch.delenv(ct._ALLOW_PROD_TRUNCATE_ENV, raising=False)
    monkeypatch.setattr(
        ct,
        "_resolve_truncation_dsn",
        lambda: ("postgresql://x/y", "-csearch_path=aether_test", "aether_test"),
    )
    monkeypatch.setattr(ct, "_live_resolved_schema", lambda dsn, options: "aether_test")
    ct._run_prod_truncate_guard()  # must not raise


# ---------------------------------------------------------------------------
# ``_resolve_truncation_dsn`` — derives ONLY from DATABASE_URL_TEST, pins
# search_path via options=, and fails closed when it can't be derived.
# ---------------------------------------------------------------------------


def test_resolve_truncation_dsn_pins_search_path_from_database_url_test(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL_TEST",
        "postgresql://role:pw@db-fdc4e11da.example.internal:5432/fdc4e11da"
        "?schema=aether_test&connect_timeout=15",
    )
    dsn, options, schema = ct._resolve_truncation_dsn()
    assert schema == "aether_test"
    assert options == "-csearch_path=aether_test"
    # The dsn must not carry the (psycopg2-ignored) schema= param anymore,
    # and must point at the SAME host+db DATABASE_URL_TEST named — this pin
    # is derived from DATABASE_URL_TEST, never from DATABASE_URL.
    assert "schema=" not in dsn
    assert "db-fdc4e11da.example.internal" in dsn


def test_resolve_truncation_dsn_ignores_database_url_entirely(monkeypatch):
    """Even if ``DATABASE_URL`` is production-shaped (schema=aether) in the
    environment, the resolved truncation DSN/schema must come from
    ``DATABASE_URL_TEST`` alone — this is the core of the fix: the incident
    happened because the truncation path trusted ``DATABASE_URL``.
    """
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://role:pw@db-fdc4e11da.example.internal:5432/fdc4e11da?schema=aether",
    )
    monkeypatch.setenv(
        "DATABASE_URL_TEST",
        "postgresql://role:pw@db-fdc4e11da.example.internal:5432/fdc4e11da?schema=aether_test",
    )
    _dsn, options, schema = ct._resolve_truncation_dsn()
    assert schema == "aether_test"
    assert options == "-csearch_path=aether_test"


def test_resolve_truncation_dsn_fails_closed_when_test_url_missing(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_TEST", raising=False)
    # Also neutralize the root-.env fallback so this test is hermetic and
    # deterministic regardless of what the local checkout's .env contains.
    monkeypatch.setattr(ct, "_root_env", {})
    with pytest.raises(ct.ProdTruncationGuardError, match="DATABASE_URL_TEST is not set"):
        ct._resolve_truncation_dsn()


def test_resolve_truncation_dsn_fails_closed_when_schema_param_missing(monkeypatch):
    """A DATABASE_URL_TEST with NO schema= param at all is un-derivable and
    must be refused, not silently defaulted to some schema.
    """
    monkeypatch.setenv(
        "DATABASE_URL_TEST",
        "postgresql://role:pw@db-fdc4e11da.example.internal:5432/fdc4e11da",
    )
    with pytest.raises(ct.ProdTruncationGuardError, match="schema"):
        ct._resolve_truncation_dsn()


# ---------------------------------------------------------------------------
# Sanity: the real DATABASE_URL_TEST in this checkout's own environment (as
# conftest.py bootstrapped it at import time) resolves to aether_test, never
# aether. This is a static/string check only — no connection is opened.
# ---------------------------------------------------------------------------


def test_real_environment_database_url_test_schema_is_test_not_prod():
    dsn, options, schema = ct._resolve_truncation_dsn()
    assert schema == "aether_test"
    assert options == "-csearch_path=aether_test"
    assert dsn  # non-empty, sanity check
