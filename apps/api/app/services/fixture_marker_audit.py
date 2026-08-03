"""W-CLEAN — detect fixture / test / probe / placeholder residue that has
leaked into USER-VISIBLE production columns.

Why this module exists
----------------------
Every user-visible string in this product is either something the user wrote
or something an agent generated from the user's own evidence. Anything else —
a QA harness row, a seeded demo funnel, a signature left over from a bootstrap
admin account — is a *false statement to the user*, and in the case of a cover
letter, a false statement to a third-party employer. The 2026-08-02 production
audit found four such classes at rest (see ``AUDIT-2026-08-02`` in
``docs/delivery/``):

  * 7 ``Application.coverLetter`` rows signed ``Administrator`` — the name
    ``scripts/seed_demo.ADMIN_NAME`` gives the bootstrap admin account. Genuine
    letter bodies about the real user, ending in a fictional signatory.
  * 2 ``EmailThread`` rows created by a UI test harness ("GOLD-MASTER-V4 TEST
    DRAFT - safe to delete", "sanity check no nul") sitting in the real user's
    Email Center, with no ``gmailThreadId`` because no such email exists.
  * 1 ``ApprovalRequest`` whose own payload says
    ``"SYNTHETIC TEST DATA (models-live qa)"``, rendered on the Approvals
    screen as if it were a real decision awaiting the user.
  * 14 ``User`` rows on RFC-2606 reserved domains (``@example.com``) created by
    QA runs, inflating every account-level count in the admin panel.

Design constraint: DISCRIMINATE, DO NOT PATTERN-MATCH
-----------------------------------------------------
The naive rule ("flag any row containing the word *test*") is worse than
useless here. The real user is a Business Analyst whose genuine résumé,
stories and cover letters are *full* of legitimate occurrences — "Test
Automation Strategy", "test-evidence automation covering 200+ SIT/E2E
scenarios", "re-baselining Payday Super test capacity". A first pass of that
naive rule over production returned 1,356 hits of which 1,343 were real user
work. Flagging those would either destroy genuine content or train everyone to
ignore the audit.

So every rule below is anchored on something a *genuine* row structurally
cannot contain:

  * ``placeholder-signer``   — scoped to the sign-off LINE of a letter, reusing
                               the one shipped implementation of the
                               BLOCKER-002 name rule (never a second copy).
  * ``reserved-email-domain`` — scoped to email-typed columns. ``example.com``/
                               ``.invalid`` are reserved by RFC 2606/6761 and
                               can never receive mail, so a row addressed there
                               is definitionally synthetic.
  * ``self-declared-synthetic`` — the text says so itself ("SYNTHETIC TEST
                               DATA", "safe to delete", a line ending in the
                               objectless directive "do not send").
  * ``harness-run-label``    — a QA campaign label (GOLD-MASTER-Vn, MODELS-LIVE
                               QA, GAP-P7-DEF-x) that only a test harness emits.
  * ``demo-seed``            — the literal strings the demo-funnel seeder wrote.
  * ``lorem-ipsum``          — placeholder copy.
  * ``non-routable-url``     — a job link pointing at localhost/example/demo.

The false-positive corpus in
``apps/api/tests/test_wclean_fixture_marker_audit.py`` is taken verbatim from
real production rows and is part of the contract: a rule that flags any string
in it is a defect, not a finding.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from app.agents.cover_letter_agent import (
    _looks_like_placeholder_name,
    stored_letter_has_placeholder_signer,
    stored_signoff_name,
)

# ---------------------------------------------------------------------------
# Column inventory — what a user can actually READ in the product.
# ---------------------------------------------------------------------------

#: Free-text / JSON columns rendered somewhere in the dashboard, grouped by the
#: KIND of value they hold. The kind selects which rules apply, which is what
#: keeps the email/name rules from being unleashed on model-generated prose.
#:
#: ``prose``   — model- or user-authored narrative text (and JSON blobs of it)
#: ``email``   — an RFC-5322 address the product would actually send to
#: ``name``    — a human identity string
#: ``url``     — an external link the user is invited to follow
USER_VISIBLE_COLUMNS: dict[str, dict[str, str]] = {
    # Rendered in the run detail drawer on /dashboard/agents.
    "AgentRun": {"input": "prose", "output": "prose", "error": "prose"},
    # ``GET /agents/jobs/{id}`` returns ``result``/``error`` verbatim to the
    # polling client (routers/agents.py ``_job_status_payload``), so an async
    # run's stored result is every bit as user-visible as ``AgentRun.output``
    # — and in production carried the same contaminated letters.
    "BackgroundJob": {"params": "prose", "result": "prose", "error": "prose"},
    "Application": {
        "coverLetter": "letter",
        "answers": "prose",
        # Written by the submission path once an application is really sent —
        # a fabricated "reference" here would be the product's worst possible
        # lie, so they are audited even while they are all still NULL.
        "transmittedTo": "email",
        "transmissionChannel": "prose",
        "transmissionRef": "prose",
    },
    "ApprovalRequest": {"payload": "prose"},
    "Contact": {
        "name": "name",
        "title": "prose",
        "company": "prose",
        "email": "email",
        "linkedinUrl": "url",
    },
    "EmailThread": {
        "subject": "prose",
        "messages": "prose",
        "draftReply": "prose",
    },
    "InterviewSchedule": {
        "location": "prose",
        "meetingLink": "url",
        "notes": "prose",
        "contactName": "name",
        "contactEmail": "email",
    },
    "Job": {
        "title": "prose",
        "company": "prose",
        "location": "prose",
        "description": "prose",
        "requirements": "prose",
        "sourceUrl": "url",
        "applyEmail": "email",
    },
    "Offer": {"company": "prose", "role": "prose", "location": "prose"},
    "OutreachTask": {"message": "prose"},
    "Resume": {"label": "prose", "sections": "prose"},
    "StoryEntry": {
        "title": "prose",
        "situation": "prose",
        "task": "prose",
        "action": "prose",
        "result": "prose",
        "metrics": "prose",
    },
    "User": {"email": "email", "name": "name", "targetRole": "prose"},
}

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

#: Domains reserved by RFC 2606 / RFC 6761. Mail to them is undeliverable by
#: definition, so any stored address on one was invented by a harness.
#: ``test``/``invalid``/``localhost`` are reserved as TOP-LEVEL domains, so they
#: are only a marker when nothing follows them — ``@test.com`` is an ordinary
#: registrable domain a real employer could own and must not be flagged, while
#: ``@example.invalid`` and ``@qa.test`` must.
_RESERVED_EMAIL_DOMAIN_RE = re.compile(
    r"@(?:"
    r"(?:[A-Za-z0-9-]+\.)*example\.(?:com|org|net)\b"
    r"|(?:[A-Za-z0-9-]+\.)*(?:test|invalid|localhost)(?![A-Za-z0-9.-])"
    r")",
    re.I,
)

#: Text that declares its own synthetic nature. Deliberately whole phrases —
#: "synthetic" alone appears in the user's real story about "a classifier
#: trained on synthetic test cases".
#:
#: ``do not send`` is anchored to the END OF ITS LINE (2026-08-03). The rule was
#: written for a harness row whose own subject reads "MODELS-LIVE QA synthetic —
#: do not send": an instruction to the operator, with no object, terminating the
#: text. Unanchored it also matched ordinary recruitment-agency boilerplate —
#: "…work alongside our internal TA team and do not send resumes directly to
#: managers" — and reported 7 genuine Airtasker postings in the live database as
#: fixture residue, which is the audit proposing the destruction of real jobs.
#: A real clause always names what must not be sent (resumes / CVs / candidates),
#: so it never ends the line there; the harness directive always does.
_SELF_DECLARED_RE = re.compile(
    r"(?:"
    r"synthetic test (?:data|row|body)"
    r"|test (?:data|fixture|row)\s*[—-]\s*do not"
    r"|safe to delete"
    r"|do not send[.!]?(?=[ \t]*(?:\r?\n|$))"
    r"|deliberately missing recipient"
    r"|not-a-real-recipient"
    r"|this is (?:a|only a) test\b"
    r"|placeholder (?:text|value|content|copy)"
    r"|dummy (?:data|value|text|record)"
    r")",
    re.I,
)

#: QA-campaign labels. Every one of these is a run identifier this repo's own
#: verification harnesses stamp onto rows they create; no employer, job board
#: or human ever writes one into a job, résumé or email.
_HARNESS_LABEL_RE = re.compile(
    r"(?:"
    r"GOLD[-\s]?MASTER[-\s]?V\d"
    r"|MODELS[-\s]?LIVE\s+QA"
    r"|GAP-P\d+-[A-Z]+-[A-Z0-9]+"
    r"|BLOCKER-\d{3}\b"
    r"|\bGM[24]-(?:phase|signup|probe|nul|nonadmin|legitcheck|report)"
    r"|adversarial (?:draft|probe) test"
    r")",
    re.I,
)

#: Literal artefacts of ``scripts/seed_demo.py``'s demo-funnel generator.
_DEMO_SEED_RE = re.compile(
    r"(?:Demo-seeded job posting|Demo seed resume|demo-seed-hash|demo\.aether\.dev)",
    re.I,
)

_LOREM_RE = re.compile(r"lorem\s+ipsum", re.I)

#: A link the user is invited to click that cannot leave the machine.
_NON_ROUTABLE_URL_RE = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|"
    r"(?:[A-Za-z0-9-]+\.)*(?:example\.(?:com|org|net)|invalid|test))(?:[:/]|$)",
    re.I,
)


@dataclass(frozen=True)
class Finding:
    """One fixture marker at one location."""

    table: str
    row_id: str
    column: str
    marker: str
    match: str
    context: str
    path: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "table": self.table,
            "row_id": self.row_id,
            "column": self.column,
            "path": self.path,
            "marker": self.marker,
            "match": self.match,
            "context": self.context,
        }


@dataclass(frozen=True)
class _Rule:
    name: str
    kinds: frozenset[str]
    pattern: re.Pattern[str] | None = None
    predicate: Callable[[str], "re.Match[str] | None"] | None = None


def _placeholder_signer_hit(text: str) -> re.Match[str] | None:
    """Delegate to the SHIPPED BLOCKER-002 rule, then locate the offending
    sign-off name inside the letter so the finding can quote it."""
    if not stored_letter_has_placeholder_signer(text):
        return None
    signer = stored_signoff_name(text)
    return re.search(re.escape(signer), text) if signer else None


def _placeholder_name_hit(text: str) -> re.Match[str] | None:
    """The same rule applied to a whole column that IS a name."""
    stripped = text.strip()
    if not stripped or not _looks_like_placeholder_name(stripped):
        return None
    return re.search(re.escape(stripped), text)


_RULES: tuple[_Rule, ...] = (
    _Rule("placeholder-signer", frozenset({"letter"}), predicate=_placeholder_signer_hit),
    _Rule("placeholder-name", frozenset({"name"}), predicate=_placeholder_name_hit),
    _Rule("reserved-email-domain", frozenset({"email"}), pattern=_RESERVED_EMAIL_DOMAIN_RE),
    _Rule(
        "self-declared-synthetic",
        frozenset({"letter", "prose", "name", "url", "email"}),
        pattern=_SELF_DECLARED_RE,
    ),
    _Rule(
        "harness-run-label",
        frozenset({"letter", "prose", "name", "url", "email"}),
        pattern=_HARNESS_LABEL_RE,
    ),
    _Rule(
        "demo-seed",
        frozenset({"letter", "prose", "name", "url", "email"}),
        pattern=_DEMO_SEED_RE,
    ),
    _Rule("lorem-ipsum", frozenset({"letter", "prose", "name", "url", "email"}), pattern=_LOREM_RE),
    _Rule("non-routable-url", frozenset({"url", "prose", "letter"}), pattern=_NON_ROUTABLE_URL_RE),
)


def _context(text: str, match: re.Match[str], width: int = 70) -> str:
    start = max(0, match.start() - width)
    end = min(len(text), match.end() + width)
    return text[start:end].replace("\n", " | ").strip()


def scan_text(text: str, kind: str = "prose") -> list[tuple[str, str, str]]:
    """Every ``(marker, matched_text, context)`` in ``text`` for a column of
    ``kind``. Empty list means the value is clean."""
    if not text:
        return []
    hits: list[tuple[str, str, str]] = []
    for rule in _RULES:
        if kind not in rule.kinds:
            continue
        if rule.pattern is not None:
            match = rule.pattern.search(text)
        elif rule.predicate is not None:
            match = rule.predicate(text)
        else:  # pragma: no cover - a rule with neither is a construction bug
            raise ValueError(f"rule {rule.name!r} has no pattern and no predicate")
        if match is not None:
            hits.append((rule.name, match.group(0), _context(text, match)))
    return hits


def _walk(value: Any, prefix: str = "") -> Iterator[tuple[str, str]]:
    """Yield ``(json_path, string)`` for every string inside a JSON value."""
    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{prefix}[{index}]")


def _strings_of(value: Any) -> list[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        return [("", value)]
    if isinstance(value, (dict, list)):
        return list(_walk(value))
    if isinstance(value, (bytes, bytearray)):
        return [("", value.decode("utf-8", "replace"))]
    return []


def scan_row(table: str, row_id: str, values: dict[str, Any]) -> list[Finding]:
    """Scan one row's user-visible columns. ``values`` maps column -> value."""
    kinds = USER_VISIBLE_COLUMNS.get(table, {})
    findings: list[Finding] = []
    for column, value in values.items():
        kind = kinds.get(column)
        if kind is None:
            continue
        for path, text in _strings_of(value):
            for marker, matched, context in scan_text(text, kind):
                findings.append(
                    Finding(
                        table=table,
                        row_id=row_id,
                        column=column,
                        path=path,
                        marker=marker,
                        match=matched,
                        context=context,
                    )
                )
    return findings


def _existing_columns(cursor: Any, schema: str, table: str) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    )
    return {row[0] for row in cursor.fetchall()}


def scan_connection(
    connection: Any,
    schema: str = "aether",
    tables: Iterable[str] | None = None,
) -> list[Finding]:
    """Scan every user-visible column of every row reachable on ``connection``.

    Tables or columns that do not exist in ``schema`` are skipped rather than
    raising — the same audit must run against a production schema and a test
    schema whose additive migrations may lag.
    """
    wanted = list(tables) if tables is not None else list(USER_VISIBLE_COLUMNS)
    findings: list[Finding] = []
    with connection.cursor() as cursor:
        for table in wanted:
            columns = USER_VISIBLE_COLUMNS.get(table, {})
            if not columns:
                continue
            present = _existing_columns(cursor, schema, table)
            if not present:
                continue  # table absent in this schema
            selected = [c for c in columns if c in present]
            if not selected or "id" not in present:
                continue
            projection = ", ".join(f'"{c}"' for c in selected)
            cursor.execute(f'SELECT "id", {projection} FROM "{schema}"."{table}"')
            for row in cursor.fetchall():
                row_id, rest = row[0], row[1:]
                # jsonb columns arrive already decoded by psycopg2; a plain
                # text column that happens to hold JSON is scanned as text.
                values: dict[str, Any] = {
                    column: (
                        bytes(raw).decode("utf-8", "replace")
                        if isinstance(raw, (bytes, bytearray, memoryview))
                        else raw
                    )
                    for column, raw in zip(selected, rest)
                }
                findings.extend(scan_row(table, str(row_id), values))
    return findings


def findings_to_json(findings: list[Finding]) -> str:
    return json.dumps([f.as_dict() for f in findings], indent=2, ensure_ascii=False)
