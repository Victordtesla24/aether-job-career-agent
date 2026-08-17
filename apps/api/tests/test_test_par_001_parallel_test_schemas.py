"""TEST-PAR-1 — parallel test-gate isolation via per-wave Postgres schemas.

PROBLEM (throughput, PROGRAM-INFRA — no web-app behaviour change):
every agent in every remediation wave serialises its pytest battery behind
``flock /tmp/aether-pytest.lock`` because the whole program shares ONE
``aether_test`` schema: two concurrent runs' ``TRUNCATE ... CASCADE``
fixtures delete each other's rows mid-test (documented non-deterministic
failures). Batteries take 10-20 minutes, so waves queue single-file.

The DB role has no ``CREATEDB``, so per-database isolation is impossible —
but it CAN ``CREATE SCHEMA``. This suite pins the contract that makes
per-wave schema isolation real *without* loosening the MV-system-003
production-wipe guard:

  (a) ``conftest._assert_schema_is_safe_test_schema`` accepts any schema
      matching ``^aether_test([_a-z0-9]+)?$`` — the legacy shared
      ``aether_test`` AND per-wave ``aether_test_<wave>`` — and still
      hard-refuses production (``aether``), ``public``, ``None`` and every
      look-alike that is not that exact shape.
  (b) ``scripts/run-tests.sh`` parses the DSN's ``schema=`` query param
      properly (not by substring) and refuses anything outside that
      pattern, refuses a missing ``DATABASE_URL_TEST``, and names the
      schema it actually resolved.
  (c) ``scripts/test-schema.sh provision|drop <suffix>`` exists, is
      executable, and refuses any target outside ``aether_test_*`` —
      including the legacy shared ``aether_test`` and production
      ``aether`` — before touching the database at all.
  (d) The per-wave lockfile/schema convention is documented in
      ``run-tests.sh``'s header so future waves self-isolate.

Hermetic: the guard tests call the pure decision function directly, and the
shell tests run the scripts in a subprocess with synthetic DSNs pointed at
``127.0.0.1:1`` (connection-refused, instantly) or with the name-validation
tripping before any DSN is resolved. No test here opens a real database
connection, and none of them can reach production.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import conftest as ct
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUN_TESTS_SH = REPO_ROOT / "scripts" / "run-tests.sh"
TEST_SCHEMA_SH = REPO_ROOT / "scripts" / "test-schema.sh"

#: A syntactically valid DSN whose host refuses connections immediately, so a
#: subprocess that gets PAST the schema gate dies in milliseconds instead of
#: hanging on a network timeout. Never resolvable to any real database.
_DEAD_HOST = "postgresql://role:pw@127.0.0.1:1/testdb"


def _dsn(schema_query: str) -> str:
    return f"{_DEAD_HOST}?{schema_query}&connect_timeout=1"


# ---------------------------------------------------------------------------
# (a) conftest guard — per-wave schemas allowed, production still refused.
# ---------------------------------------------------------------------------


def test_guard_allows_the_legacy_shared_schema():
    """Unchanged legacy behaviour: the default shared schema still passes."""
    ct._assert_schema_is_safe_test_schema("aether_test")  # must not raise


@pytest.mark.parametrize(
    "schema",
    [
        "aether_test_pa",
        "aether_test_pb",
        "aether_test_wave3",
        "aether_test_r1_integrity",
        "aether_test_2",
    ],
)
def test_guard_allows_per_wave_schemas(schema: str):
    """The whole point of TEST-PAR-1: a wave-private schema is a legitimate,
    isolated truncation target. Before this fix the guard hard-coded equality
    with ``aether_test`` and aborted the entire session (returncode 2) for
    any of these, which is why every wave had to share one schema.
    """
    ct._assert_schema_is_safe_test_schema(schema)  # must not raise


@pytest.mark.parametrize("schema", ["aether", "public", "postgres", None, ""])
def test_guard_still_refuses_production_and_non_test_schemas(schema):
    """MV-system-003 must NOT be weakened by the parallelisation: production
    (``aether``), ``public`` and an un-derivable schema stay fail-closed.
    """
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._assert_schema_is_safe_test_schema(schema)


@pytest.mark.parametrize(
    "schema",
    [
        "aether_test-pa",  # hyphen — not in the allowed character class
        "aether_test pa",  # whitespace
        "aether_testPA",  # uppercase
        "aether_test;drop",  # SQL punctuation
        "xaether_test",  # not anchored at the start
        "public_aether_test",  # not anchored at the start
        "aether_test.pa",  # schema-qualified look-alike
        'aether_test"pa',  # quote
    ],
)
def test_guard_refuses_lookalike_schema_names(schema: str):
    """The widened pattern is anchored and character-class restricted: a name
    that merely *contains* or *resembles* ``aether_test`` is still refused.
    """
    with pytest.raises(ct.ProdTruncationGuardError):
        ct._assert_schema_is_safe_test_schema(schema)


def test_guard_refusal_tells_the_operator_how_to_provision_a_wave_schema():
    """An UNPROVISIONED wave schema is the most likely operator mistake once
    waves pick their own schema names: Postgres resolves
    ``-csearch_path=aether_test_typo`` to ``current_schema() IS NULL``
    (verified against the hosted test DB), which lands in exactly this
    refusal. The message must name the provisioning helper rather than
    dead-end the operator on "schema None".
    """
    with pytest.raises(ct.ProdTruncationGuardError) as excinfo:
        ct._assert_schema_is_safe_test_schema(None)
    assert "scripts/test-schema.sh provision" in str(excinfo.value)


def test_guard_override_still_works_for_wave_schemas():
    """The explicit escape hatch is untouched."""
    ct._assert_schema_is_safe_test_schema("aether", allow_override=True)


def test_resolve_truncation_dsn_pins_a_per_wave_schema(monkeypatch):
    """``_resolve_truncation_dsn`` must pin ``search_path`` to the wave schema
    named in ``DATABASE_URL_TEST`` — that pin is what keeps two concurrent
    runs' truncations off each other's rows.
    """
    monkeypatch.setenv("DATABASE_URL_TEST", _dsn("schema=aether_test_pa"))
    dsn, options, schema = ct._resolve_truncation_dsn()
    assert schema == "aether_test_pa"
    assert options == "-csearch_path=aether_test_pa"
    assert "schema=" not in dsn


# ---------------------------------------------------------------------------
# (b) scripts/run-tests.sh — proper schema-param parsing, still fail-closed.
# ---------------------------------------------------------------------------


def _run_tests_sh(
    test_url: str | None,
    *,
    tmp_path: Path | None = None,
    schema_override: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke ``scripts/run-tests.sh`` with a synthetic ``DATABASE_URL_TEST``.

    When ``tmp_path`` is given the script is copied into an isolated tree with
    NO repo-root ``.env``, so the "missing DATABASE_URL_TEST" branch can be
    exercised without depending on (or reading) the real ``.env``.

    ``cwd`` sets the working directory the script starts in — used by the
    pathname-expansion tests below, where the gate's decision must not depend
    on what files happen to sit next to the caller.
    """
    script = RUN_TESTS_SH
    if tmp_path is not None:
        (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
        script = tmp_path / "scripts" / "run-tests.sh"
        shutil.copy2(RUN_TESTS_SH, script)

    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "DATABASE_URL_TEST"}}
    env.pop("AETHER_TEST_SCHEMA", None)
    if test_url is not None:
        env["DATABASE_URL_TEST"] = test_url
    if schema_override is not None:
        env["AETHER_TEST_SCHEMA"] = schema_override
    # A pytest arg that would exit immediately IF the gate ever let it through;
    # the schema gate is expected to decide long before pytest starts.
    return subprocess.run(
        ["bash", str(script), "--version"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        timeout=180,
    )


def test_run_tests_sh_refuses_when_database_url_test_is_missing(tmp_path: Path):
    result = _run_tests_sh(None, tmp_path=tmp_path)
    assert result.returncode != 0
    assert "REFUSING TO RUN" in result.stderr
    assert "DATABASE_URL_TEST is not set" in result.stderr


@pytest.mark.parametrize(
    "schema_query",
    [
        "schema=aether",  # PRODUCTION — the 2026-07-18 wipe
        "schema=public",
        "schema=postgres",
        "schema=",  # empty
        "connect_timeout=15",  # no schema param at all
    ],
)
def test_run_tests_sh_refuses_non_test_schemas(schema_query: str):
    result = _run_tests_sh(f"{_DEAD_HOST}?{schema_query}")
    assert result.returncode != 0, result.stdout
    assert "REFUSING TO RUN" in result.stderr


@pytest.mark.parametrize(
    "schema_query",
    [
        # Substring-matching accepted every one of these before TEST-PAR-1:
        "schema=aether&fallback_application_name=schema=aether_test",
        "schema=aether_testPA",
        "schema=aether_test-pa",
        "schema=aether_test%20pa",
        "options=-csearch_path%3Daether_test&schema=aether",
    ],
)
def test_run_tests_sh_refuses_schema_lookalikes(schema_query: str):
    """The gate must parse the real ``schema=`` query parameter, not scan the
    DSN for a substring: a production DSN that merely *mentions*
    ``aether_test`` elsewhere is the exact shape of the incident DSN.
    """
    result = _run_tests_sh(f"{_DEAD_HOST}?{schema_query}")
    assert result.returncode != 0, result.stdout
    assert "REFUSING TO RUN" in result.stderr


@pytest.mark.parametrize("schema", ["aether_test", "aether_test_pa", "aether_test_pb"])
def test_run_tests_sh_accepts_and_names_the_resolved_schema(schema: str):
    """Accepted schemas must be *named* in the confirmation line: with waves
    running in different schemas concurrently, a hard-coded "aether_test"
    banner would misreport which schema a battery actually hit.
    """
    result = _run_tests_sh(_dsn(f"schema={schema}"))
    banner = [ln for ln in result.stdout.splitlines() if ln.startswith("[run-tests.sh]")]
    assert banner, f"no [run-tests.sh] banner emitted; stdout={result.stdout!r}"
    assert any(f"schema={schema}" in ln for ln in banner), banner
    # The script's OWN gate must not have refused it (the child pytest still
    # aborts on the unreachable host — that is the in-process guard, not this
    # gate — so only the gate's own refusal is asserted absent here).
    assert "REFUSING TO RUN: DATABASE_URL_TEST" not in result.stderr


@pytest.mark.parametrize(
    "schema_value",
    [
        "aether_test*",  # glob that a sibling file can complete to `aether_test`
        "aether_tes?",
        "aether_test[_]pa",
    ],
)
def test_run_tests_sh_does_not_glob_expand_the_schema_param(tmp_path: Path, schema_value: str):
    """The DSN's query string must be split, never GLOBBED.

    Word-splitting an unquoted ``$query`` on ``IFS='&'`` also subjects each
    pair to pathname expansion. A caller whose working directory happens to
    contain a file named ``schema=aether_test`` would make the pair
    ``schema=aether_test*`` expand to ``schema=aether_test`` — so the gate
    would ACCEPT a DSN whose real ``schema=`` value is not a schema name at
    all, and the banner would then report a schema the pytest child never
    uses (the exported DSN still carries the literal glob). That is a
    fail-OPEN gate whose verdict depends on the caller's cwd, which is
    exactly what MV-system-003 forbids: the target must be POSITIVELY proven.
    """
    (tmp_path / "schema=aether_test").write_text("")
    (tmp_path / "schema=aether_test_pa").write_text("")
    result = _run_tests_sh(f"{_DEAD_HOST}?schema={schema_value}", cwd=tmp_path)
    assert result.returncode != 0, result.stdout
    assert "REFUSING TO RUN" in result.stderr
    assert schema_value in result.stderr, (
        "the refusal must quote the LITERAL schema value from the DSN, not a "
        f"glob-expanded one; stderr={result.stderr!r}"
    )


def test_run_tests_sh_schema_override_retargets_the_run():
    """A wave must be able to retarget its battery WITHOUT handling the raw
    (secret-bearing) DSN: ``AETHER_TEST_SCHEMA=aether_test_pa`` rewrites the
    resolved DSN's schema param, and the banner reports the schema actually
    used — not the one the .env happened to name.
    """
    result = _run_tests_sh(_dsn("schema=aether_test"), schema_override="aether_test_pa")
    banner = [ln for ln in result.stdout.splitlines() if ln.startswith("[run-tests.sh]")]
    assert banner, f"no banner; stdout={result.stdout!r}"
    assert any("schema=aether_test_pa" in ln for ln in banner), banner
    assert not any("schema=aether_test " in ln for ln in banner), banner


@pytest.mark.parametrize("override", ["aether", "public", "aether_test-pa", "AETHER"])
def test_run_tests_sh_schema_override_is_gated_too(override: str):
    """The override goes through the SAME fail-closed gate — it is not a way
    around it. A production override must refuse even when the .env DSN is a
    perfectly legitimate test DSN.
    """
    result = _run_tests_sh(_dsn("schema=aether_test"), schema_override=override)
    assert result.returncode != 0, result.stdout
    assert "REFUSING TO RUN" in result.stderr


# ---------------------------------------------------------------------------
# (d) The per-wave convention is documented where operators will read it.
# ---------------------------------------------------------------------------


def test_run_tests_sh_documents_the_per_wave_lock_and_schema_convention():
    header = RUN_TESTS_SH.read_text()
    assert "/tmp/aether-pytest-<wave>.lock" in header, (
        "run-tests.sh must document the per-wave lockfile convention so future "
        "waves self-isolate instead of serialising on /tmp/aether-pytest.lock"
    )
    assert "aether_test_<wave>" in header
    assert "scripts/test-schema.sh" in header


# ---------------------------------------------------------------------------
# (c) scripts/test-schema.sh — provisioning helper, fail-closed on names.
# ---------------------------------------------------------------------------


def _test_schema_sh(
    *args: str,
    test_url: str | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "DATABASE_URL_TEST"}}
    # Deliberately unreachable: every assertion below must be decided by name
    # validation BEFORE any connection is attempted.
    env["DATABASE_URL_TEST"] = test_url if test_url is not None else _dsn("schema=aether_test")
    return subprocess.run(
        ["bash", str(TEST_SCHEMA_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        timeout=120,
    )


def test_test_schema_helper_exists_and_is_executable():
    assert TEST_SCHEMA_SH.is_file(), f"{TEST_SCHEMA_SH} is missing"
    assert os.access(TEST_SCHEMA_SH, os.X_OK), f"{TEST_SCHEMA_SH} is not executable"


def test_test_schema_helper_usage_names_both_verbs():
    result = _test_schema_sh()
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "provision" in combined and "drop" in combined


@pytest.mark.parametrize("verb", ["provision", "drop"])
@pytest.mark.parametrize(
    "suffix",
    [
        "PA",  # uppercase
        "p-a",  # hyphen
        "p a",  # whitespace
        "pa;DROP SCHEMA aether CASCADE",  # injection
        "../aether",
        'pa"',
        "",  # empty suffix would target the legacy shared schema
    ],
)
def test_test_schema_helper_refuses_invalid_suffixes(verb: str, suffix: str):
    result = _test_schema_sh(verb, suffix)
    assert result.returncode != 0, (verb, suffix, result.stdout)
    assert "REFUSING" in (result.stdout + result.stderr)


@pytest.mark.parametrize("verb", ["provision", "drop"])
@pytest.mark.parametrize("target", ["aether", "public", "aether_test", "postgres"])
def test_test_schema_helper_refuses_non_wave_schema_names(verb: str, target: str):
    """A full schema name may be passed instead of a suffix, but production
    (``aether``), ``public`` and the legacy SHARED ``aether_test`` must never
    be droppable or re-provisionable through this helper.
    """
    result = _test_schema_sh(verb, target)
    assert result.returncode != 0, (verb, target, result.stdout)
    combined = result.stdout + result.stderr
    assert "REFUSING" in combined
    assert target in combined


@pytest.mark.parametrize("verb", ["provision", "drop"])
def test_test_schema_helper_does_not_glob_expand_the_dsn_schema_param(verb: str, tmp_path: Path):
    """Same fail-open as ``run-tests.sh``: this helper validates the DSN's
    ``schema=`` param before using its credentials to CREATE or DROP schemas,
    and that validation must not be completable by a file sitting in the
    caller's working directory. ``schema=aether*`` is not an isolated test
    schema no matter what ``ls`` says.
    """
    (tmp_path / "schema=aether_test").write_text("")
    result = _test_schema_sh(
        verb,
        "pa",
        test_url=f"{_DEAD_HOST}?schema=aether*&connect_timeout=1",
        cwd=tmp_path,
    )
    assert result.returncode != 0, (verb, result.stdout)
    combined = result.stdout + result.stderr
    assert "REFUSING" in combined
    assert "aether*" in combined, combined
