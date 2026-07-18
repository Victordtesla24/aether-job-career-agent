"""MV-application-tracker-001 guard test (redesigned after review-caught over-deletion).

BLOCKER finding: fixture-derived cover-letter text (from
``apps/api/tests/fixtures/llm/cover_letter/default.json`` and ``retry.json``)
was found in production ``Application.coverLetter`` rows, reachable by real
users. The original remediation deleted 8 rows using an over-loose numeric
fingerprint ``'%3 hours%15 minutes%'``. Adversarial review
(``uat/reports/evidence/manual-verification/fixes/cluster-C/review.json``) and
this fixer's independent reclassification
(``uat/reports/evidence/manual-verification/fixes/cluster-C/reclassification.json``)
PROVED only 4 of the 8 rows actually contained fixture cover-letter text
verbatim. The other 4 were REAL user data (one a SUBMITTED application) whose
genuine StoryEntry evidence ("...from ~3 hours to ~15 minutes per scenario
(~92% reduction)...") merely shares that short numeric metric phrase. Those 4
real rows were restored; the 4 true-fixture rows stay deleted.

Why the old fingerprint was unsound
------------------------------------
The numeric pair "3 hours" ... "15 minutes" is NOT unique to the fixtures. It
is also the real, career-specific StoryEntry evidence of the two affected users
(sarkar.vikram@gmail.com, admin@aether.local), whose "COBOL/Mainframe Test
Automation Reducing Effort by 92%" achievement legitimately reports that exact
metric. Any correctly-generated, evidence-grounded cover letter citing that
true achievement contains the same substring, so the numeric fingerprint
false-positives on genuine user content. This test therefore keys off a long,
specific span that is unique to the FIXTURE files — the fabricated-achievement
paragraph (and hook sentence) served verbatim when a fixture leaks — never the
bare numeric metric.

This test is a permanent regression guard: it connects directly to the
*production* database (bypassing the test-schema swap ``tests/conftest.py``
performs at import time) and asserts no ``Application.coverLetter`` value
contains a fixture's verbatim fabricated-achievement span. It must be re-run
after any seed/import operation that touches production data.

2026-07-18 update — restored-row-presence assertions removed
--------------------------------------------------------------
This module previously ALSO asserted that the 4 real Application rows restored
above (``c0e3601826b6258afd1ced52d``, ``c53d0b3ada038f7ce441dd018``,
``c597b074bbd6214c31dcf75ec``, ``ce01bad499189ac40e9e9c78f``) were still
present, and derived a no-false-positive check from their live cover-letter
content. Both were destroyed — along with the rest of the production
``Application``/``User``/``Job`` tables — in the 2026-07-18 prod-DB wipe
incident (``docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md``): an unrelated
deploy-process defect (sourcing prod ``.env`` into a test-suite invocation,
now closed by the MV-system-003 fail-closed truncation guard), not a defect in
this guard's own logic. The user is re-signing-up fresh, so those specific row
IDs will never exist again. Asserting specific live prod row IDs was a
one-time restore-verification, not a durable invariant, so those two
assertions were removed rather than left permanently red or perpetually
skipped. The durable invariant — zero fixture-fingerprint spans in current
production cover letters — remains enforced below, and the no-false-positive
property (fingerprint matches verbatim fixture content but not
independently-authored genuine content citing the same numeric metric) is now
proven hermetically with synthetic sample strings instead of live rows.

Design notes:
- ``conftest.py`` rewrites ``os.environ["DATABASE_URL"]`` to the TEST schema URL
  at import time, so this test re-reads the *original* ``DATABASE_URL`` straight
  out of the repo-root ``.env`` file rather than trusting ``os.environ``.
- The test is skipped (not failed) when no production DATABASE_URL is
  configured, so it stays inert in environments without prod DB access; when a
  URL *is* configured, the check is real and unconditional.
- Fingerprint spans are derived from the fixture files themselves (not
  hard-coded strings) so the guard tracks the fixture content directly; a
  minimum-length floor keeps a span long/specific enough to be fixture-unique.
- ``retry2.json`` is intentionally NOT in the fixture set: it is untracked and
  its body overlaps real user StoryEntry evidence, so fingerprinting on it would
  reintroduce false positives on genuine content.
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

#: The exact committed fixture files named in the RCA as the source of the
#: leaked content. ``retry2.json`` is deliberately excluded (see module docstring).
_FIXTURE_FILES = ("default.json", "retry.json")

#: A fingerprint span must be at least this long to be used. The fabricated
#: achievement paragraph and hook sentence are 100+ chars; this floor prevents a
#: future short/generic fixture body from producing a loose, collision-prone
#: fingerprint like the numeric-metric one this redesign removed.
_MIN_SPAN_CHARS = 80

def _load_root_env() -> dict[str, str]:
    """Parse the repo-root ``.env`` directly (mirrors conftest.py's helper).

    Deliberately independent of ``os.environ`` / ``conftest.py``'s bootstrap:
    that bootstrap overwrites ``DATABASE_URL`` to point at the TEST schema before
    any test module is imported, so reading ``os.environ`` here would silently
    check the wrong database.
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
    importing ``app.db`` would pull in ``app.main``/settings modules that have
    already bound to the conftest-swapped ``DATABASE_URL`` at import time.
    Keeping this self-contained guarantees the guard checks the real production
    URL regardless of app-module import order.
    """
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def _fixture_fingerprint_spans() -> list[str]:
    """Long, fixture-unique verbatim spans identifying a leaked cover letter.

    For each committed leaked fixture this extracts two spans directly from the
    fixture body: the fabricated-achievement paragraph (the body's first
    paragraph, before the sign-off) and the ``hook_reason`` sentence. Both are
    served VERBATIM when a fixture leaks into a real Application row, so a
    verbatim substring match on either is a precise leakage signal.

    Crucially this is NOT the numeric-metric fingerprint the original
    remediation used: "3 hours"/"15 minutes" is real StoryEntry evidence for two
    live users and collides with legitimate content. These spans are ~100-360
    chars of specific fixture prose that no genuine, independently-authored cover
    letter reproduces byte-for-byte.
    """
    spans: set[str] = set()
    for filename in _FIXTURE_FILES:
        path = FIXTURE_DIR / filename
        raw = json.loads(path.read_text())
        # The fixture's top-level "content" field is itself a JSON string (the
        # simulated LLM completion payload) with "hook_reason"/"body".
        content: dict[str, Any] = json.loads(raw["content"])
        body = content.get("body", "") or ""
        hook = content.get("hook_reason", "") or ""
        # First paragraph of the body = the fabricated-achievement span (drops
        # the generic "I would welcome the opportunity..." sign-off paragraph).
        body_para1 = body.split("\n\n", 1)[0].strip()
        for span in (body_para1, hook.strip()):
            if len(span) >= _MIN_SPAN_CHARS:
                spans.add(span)
    assert spans, "expected at least one fixture fingerprint span from the fixtures"
    return sorted(spans)


def _rows_containing_span(
    conn: "psycopg2.extensions.connection", span: str
) -> list[dict[str, Any]]:
    """Rows whose coverLetter contains ``span`` verbatim (no LIKE wildcards)."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT id, "userId", "jobId", "createdAt" FROM "Application"'
            ' WHERE position(%s in "coverLetter") > 0',
            (span,),
        )
        columns = [col.name for col in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def _offending_rows(
    conn: "psycopg2.extensions.connection", spans: list[str]
) -> list[dict[str, Any]]:
    matches: dict[str, dict[str, Any]] = {}
    for span in spans:
        for record in _rows_containing_span(conn, span):
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


def test_no_fixture_cover_letter_spans_in_production(
    production_connection: Any,
) -> None:
    """No Application.coverLetter row may contain a fixture achievement span.

    Regression guard for MV-application-tracker-001 (BLOCKER): fixture-derived
    cover-letter content previously leaked into production rows visible to real
    users. This asserts zero rows contain a fixture's verbatim
    fabricated-achievement paragraph or hook sentence, using spans derived
    directly from the committed offending fixtures (default.json, retry.json).
    """
    spans = _fixture_fingerprint_spans()
    offending = _offending_rows(production_connection, spans)

    assert offending == [], (
        f"{len(offending)} Application row(s) contain a fixture-derived cover "
        "letter span (verbatim fabricated-achievement text) and are reachable "
        "by real users. This is the exact condition described in "
        "MV-application-tracker-001. Offending row ids: "
        f"{sorted(r['id'] for r in offending)}. See "
        "uat/reports/evidence/manual-verification/fixes/cluster-C/ for context."
    )


def test_fingerprint_matches_fixture_span_but_not_synthetic_real_metric_content() -> (
    None
):
    """Hermetic no-false-positive proof for the fixture fingerprint.

    Replaces the former ``test_restored_real_application_rows_present`` and
    ``test_fingerprint_does_not_flag_legitimate_metric_content``, both of which
    depended on 4 specific production ``Application`` rows. Those rows were
    destroyed in the 2026-07-18 prod-DB-wipe incident
    (``docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md``) and will never
    exist again — the user is re-signing-up fresh — so asserting their
    presence is now permanently unsatisfiable and was removed rather than kept
    red or perpetually skipped.

    The property those tests guarded is still real and still durable: the
    fingerprint must match verbatim fixture content but NOT independently
    authored genuine content that merely cites the same colliding numeric
    metric ("3 hours" / "15 minutes"). This proves that property hermetically
    with synthetic sample strings modeled on the real collision
    (COBOL/Mainframe test-automation StoryEntry evidence, see the module
    docstring), requiring no database and no dependency on any specific row
    ever having existed.
    """
    spans = _fixture_fingerprint_spans()
    assert spans, "expected at least one fixture fingerprint span"

    # Synthetic genuine user content: independently authored prose citing the
    # same numeric metric that tripped the OLD numeric-only fingerprint, but
    # sharing none of a fixture's verbatim fabricated-achievement wording.
    synthetic_real_cover_letter = (
        "In my most recent role I redesigned our COBOL regression suite, "
        "reducing manual verification effort from roughly 3 hours to about "
        "15 minutes per scenario, a change the team adopted platform-wide."
    )
    for span in spans:
        assert span not in synthetic_real_cover_letter, (
            "FALSE POSITIVE: a fixture span matched synthetic genuine content "
            f"that merely cites the same numeric metric ({span[:60]!r}...). "
            "Tighten the span derivation."
        )

    # Synthetic leaked cover letter: a fixture span served verbatim inside
    # otherwise-ordinary letter boilerplate, as happens when a fixture leaks.
    leaked_span = spans[0]
    synthetic_leaked_cover_letter = (
        f"Dear Hiring Manager,\n\n{leaked_span}\n\nSincerely,\nA. Candidate"
    )
    assert leaked_span in synthetic_leaked_cover_letter, (
        "sanity check failed: fixture span not found in its own synthetic "
        "wrapper text"
    )
