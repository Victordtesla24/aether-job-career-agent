"""MV-application-tracker-001 guard test.

BLOCKER finding: fixture-derived cover-letter text (from
``apps/api/tests/fixtures/llm/cover_letter/default.json`` and ``retry.json``)
was found in 8 production ``Application.coverLetter`` rows. RCA (see
``uat/reports/evidence/manual-verification/fixes/MV-application-tracker-001/RCA.json``,
verdict ``stale-seed-data``, confidence HIGH) established this was NOT a live
code bug — production runs ``AETHER_LLM_MODE=auto``, which never serves
fixtures — but stale seed/test data that leaked into the real database and
was reachable by real users (sarkar.vikram@gmail.com, admin@aether.local).

This test is a permanent regression guard: it connects directly to the
*production* database (bypassing the test-schema swap that
``tests/conftest.py`` performs at import time) and asserts that no
``Application.coverLetter`` value contains any of the known fixture
fingerprint phrases. It must be re-run after any seed/import operation that
touches production data.

Design notes:
- ``conftest.py`` rewrites ``os.environ["DATABASE_URL"]`` to the TEST schema
  URL at import time (see its top-level bootstrap), so this test re-reads the
  *original* ``DATABASE_URL`` straight out of the repo-root ``.env`` file
  rather than trusting ``os.environ``.
- The test is skipped (not failed) when no production DATABASE_URL is
  configured, so it stays inert in environments without prod DB access; when
  a URL *is* configured, the check is real and unconditional.
- Fingerprint patterns are derived from the fixture files themselves (not
  hard-coded strings) so the guard tracks the fixture content directly. See
  ``_fixture_fingerprint_patterns`` for why a numeric-pair fingerprint is
  used instead of a full-sentence match (paraphrased duplicates survive
  numbers, not prose).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import psycopg2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "llm" / "cover_letter"

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(.*))$")

#: The exact fixture files named in the RCA as the source of the leaked
#: content (RCA.json -> fixture_fingerprints.fixture_files).
_FIXTURE_FILES = ("default.json", "retry.json")


def _load_root_env() -> dict[str, str]:
    """Parse the repo-root ``.env`` directly (mirrors conftest.py's helper).

    Deliberately independent of ``os.environ`` / ``conftest.py``'s bootstrap:
    that bootstrap overwrites ``DATABASE_URL`` to point at the TEST schema
    before any test module is imported, so reading ``os.environ`` here would
    silently check the wrong database.
    """
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


def _production_database_url() -> str | None:
    return _load_root_env().get("DATABASE_URL")


def _translate_prisma_url(url: str) -> tuple[str, str | None]:
    """Strip Prisma's ``schema`` query param; return (dsn, schema).

    Duplicated from ``app.db._translate_prisma_url`` rather than imported:
    importing ``app.db`` would pull in ``app.main``/settings modules that
    have already bound to the conftest-swapped ``DATABASE_URL`` at import
    time. Keeping this self-contained guarantees the guard checks the real
    production URL regardless of app-module import order.
    """
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def _fixture_fingerprint_patterns() -> list[str]:
    """Derive ILIKE patterns from the numeric "evidence effort" metric.

    Both known-bad fixtures (``default.json``, ``retry.json``) describe the
    same fabricated achievement: an evidence/test process cut from N hours to
    M minutes. Inspecting the actual 8 offending production rows (see
    ``deleted-rows-backup.json``) showed most were NOT byte-identical to
    either fixture's ``body`` text — an upstream agent had paraphrased the
    surrounding prose (e.g. "compressed a critical evidence process from 3
    hours to just 15 minutes" vs. the fixture's "cut evidence effort from
    roughly 3 hours to about 15 minutes"). The one thing every offending row
    kept verbatim was the numeric metric itself, in the same order: "3
    hours" ... "15 minutes". That is exactly the heuristic the RCA used to
    find all 8 rows (query: ``coverLetter ILIKE '%3 hours%15 minutes%'``).

    This extracts that same ordered numeric-pair fingerprint dynamically
    from the fixture body text (rather than hard-coding "3 hours"/"15
    minutes"), so the guard tracks the fixtures directly and stays correct
    if their numbers ever change. A pure full-sentence match was tried first
    and rejected: it only caught 3 of the 8 known-offending rows.
    """
    patterns: set[str] = set()
    for filename in _FIXTURE_FILES:
        path = FIXTURE_DIR / filename
        raw = json.loads(path.read_text())
        # The fixture's top-level "content" field is itself a JSON string
        # (the simulated LLM completion payload) with "hook_reason"/"body".
        content: dict[str, Any] = json.loads(raw["content"])
        body = content["body"]
        quantities = re.findall(r"\d+\s*(?:hours?|hrs?|minutes?|mins?)", body, re.I)
        for earlier, later in zip(quantities, quantities[1:]):
            patterns.add(f"%{earlier}%{later}%")
    assert patterns, "expected at least one fingerprint pattern from the fixtures"
    return sorted(patterns)


def _rows_matching_fingerprints(
    conn: "psycopg2.extensions.connection", patterns: list[str]
) -> list[dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    with conn.cursor() as cur:
        for pattern in patterns:
            cur.execute(
                'SELECT id, "userId", "jobId", "createdAt" FROM "Application"'
                ' WHERE "coverLetter" ILIKE %s',
                (pattern,),
            )
            columns = [col.name for col in cur.description]
            for row in cur.fetchall():
                record = dict(zip(columns, row))
                matches[record["id"]] = record
    return list(matches.values())


@pytest.fixture(scope="module")
def production_connection() -> Any:
    url = _production_database_url()
    if not url:
        pytest.skip("no production DATABASE_URL configured in repo-root .env")
    dsn, schema = _translate_prisma_url(url)
    options = f"-csearch_path={schema}" if schema else None
    try:
        conn = psycopg2.connect(dsn, options=options, connect_timeout=10)
    except psycopg2.OperationalError as exc:  # pragma: no cover - env-dependent
        pytest.skip(f"production database unreachable: {exc}")
    try:
        yield conn
    finally:
        conn.close()


def test_no_fixture_cover_letter_fingerprints_in_production(
    production_connection: Any,
) -> None:
    """No Application.coverLetter row may contain known fixture text.

    Regression guard for MV-application-tracker-001 (BLOCKER): stale seed
    data previously left 8 rows in production carrying fixture-derived
    cover-letter content, visible to real users. This asserts zero such rows
    exist, using fingerprints derived directly from the offending fixtures
    (default.json, retry.json) rather than hard-coded strings.
    """
    patterns = _fixture_fingerprint_patterns()
    offending = _rows_matching_fingerprints(production_connection, patterns)

    assert offending == [], (
        f"{len(offending)} Application row(s) contain fixture-derived cover "
        "letter text (fixture fingerprint match) and are reachable by real "
        "users. This is the exact condition described in "
        "MV-application-tracker-001 (verdict: stale-seed-data). Offending "
        f"row ids: {sorted(r['id'] for r in offending)}. See RCA at "
        "uat/reports/evidence/manual-verification/fixes/"
        "MV-application-tracker-001/RCA.json for remediation steps."
    )
