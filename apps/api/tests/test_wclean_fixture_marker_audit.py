"""W-CLEAN — regression guard: no fixture / test / probe / placeholder residue
may exist in user-visible columns.

Written RED against HEAD on 2026-08-02, reproducing four classes of
contamination found at rest in the production ``aether`` schema:

1. ``Application.coverLetter`` — 7 rows, all ``submitted``, whose letter body
   is genuine but whose sign-off reads ``Administrator``: the name
   ``scripts/seed_demo.ADMIN_NAME`` gives the bootstrap admin account. The
   shipped BLOCKER-002 guard (``_looks_like_placeholder_name``) did NOT catch
   it — it only knows the tokens ``test``/``probe``/``gap`` and 8+ digit runs —
   so the write-time refusal, the stored-body read-time refusal, and the PDF
   export gate all waved a fictional signatory through onto a document meant
   for a real employer.
2. ``EmailThread`` — harness rows in the real user's Email Center
   ("GOLD-MASTER-V4 TEST DRAFT - safe to delete …").
3. ``ApprovalRequest.payload`` — a row whose own preview says
   ``SYNTHETIC TEST DATA (models-live qa)``, rendered on Approvals as a real
   decision awaiting the user.
4. ``User`` — 14 QA accounts on RFC-2606 reserved domains.
5. ``AgentRun.output.cover_letter`` — 2 completed cover-letter runs, rendered in
   the run-detail drawer on /dashboard/agents, whose letters sign off
   ``GAP-P7-DEF-B Probe 1785452243543`` (the original BLOCKER-002 fixture
   identity). The BLOCKER-002 remediation repaired ``Application`` rows but
   never looked at the agent-run outputs that produced them.
6. ``BackgroundJob.result`` — the same two letters again, in the async job
   record that ``GET /agents/jobs/{id}`` returns verbatim to the client.

The whole difficulty here is DISCRIMINATION, not detection. The production
owner is a Business Analyst whose genuine résumés, STAR stories and cover
letters are saturated with legitimate uses of the very words a naive scanner
looks for ("Test Automation Strategy", "test-evidence automation covering 200+
SIT/E2E scenarios", "a classifier trained on synthetic test cases"). A naive
substring scan over production returned 1,356 hits, 1,343 of which were real
user work. ``FALSE_POSITIVE_CORPUS`` below is lifted verbatim from those rows
and is part of the contract: any rule that flags one of those strings is a
defect in the rule.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.agents.cover_letter_agent import (
    _looks_like_placeholder_name,
    stored_letter_has_placeholder_signer,
    stored_signoff_name,
)
from app.services.fixture_marker_audit import scan_connection, scan_text

# ===========================================================================
# 1. The signer guard must reject a SYSTEM identity, not just a QA identity.
# ===========================================================================

#: Verbatim tail of production ``Application`` ``caca313cde4e68f4fae2f0015``
#: (status ``submitted``, created 2026-07-21). The body is the real user's real
#: evidence; only the signatory is fictional.
PRODUCTION_ADMINISTRATOR_LETTER = (
    "21 July 2026\n\n"
    "Hiring Team\nPlenti\nRe: Senior Product Manager, Strategic Origination "
    "Platforms\n\n"
    "Dear Hiring Team at Plenti,\n\n"
    "My background as a Business Analyst is a direct match for the Senior "
    "Product Manager, Strategic Origination Platforms role at Plenti. At ANZ, "
    "as Technical Product Owner, I defined the technical vision and backlog "
    "for major platform modernisations.\n\n"
    "I would welcome the chance to discuss how my platform strategy can "
    "support Plenti's growth. I am available for a call at your convenience.\n\n"
    "Sincerely,\nAdministrator\n"
)

#: The same letter as it must read after repair.
REPAIRED_LETTER = PRODUCTION_ADMINISTRATOR_LETTER.replace(
    "Sincerely,\nAdministrator", "Sincerely,\nVikram Deshpande"
)

SYSTEM_IDENTITIES_MUST_BE_REFUSED = [
    "Administrator",
    "administrator",
    "ADMIN",
    "Admin User",
    "aether admin",
]

#: Real human names that must survive the widened rule. The last two are the
#: substring traps the widened tokens introduce: "Badminton" contains "admin"
#: and "Admira" starts with "admi" — whole-token discrimination is the only
#: thing keeping them out.
REAL_NAMES_MUST_STILL_BE_ACCEPTED = [
    "Vikram Deshpande",
    "MV Tester",
    "Sarah Probert",
    "Marco Testa",
    "田中健一",
    "Helen Badminton",
    "Admira Kovač",
]


@pytest.mark.parametrize("name", SYSTEM_IDENTITIES_MUST_BE_REFUSED)
def test_system_identity_is_flagged_as_placeholder_name(name):
    """A bootstrap/system account identity is not a person. Signing a
    third-party-visible cover letter with it is the BLOCKER-002 defect with a
    different literal, and must be refused by the SAME shipped rule."""
    assert _looks_like_placeholder_name(name), (
        f"{name!r} is a system/bootstrap account identity (seed_demo.ADMIN_NAME "
        "is literally 'Administrator'), not a human name — it must never reach "
        "the letterhead or sign-off of a document an employer reads."
    )


@pytest.mark.parametrize("name", REAL_NAMES_MUST_STILL_BE_ACCEPTED)
def test_real_human_name_is_not_flagged(name):
    """Widening the true-positive surface must not widen the false-positive
    surface: refusing a real customer their own letter is a worse defect."""
    assert not _looks_like_placeholder_name(name), (
        f"{name!r} is a real human name and must NOT be refused."
    )


def test_stored_letter_signed_administrator_is_flagged():
    """The read-time counterpart: a letter ALREADY AT REST signed
    ``Administrator`` must be refused by the export/submit gates
    (``routers/cover_letters.py`` :711/:1033, ``routers/jobs.py`` :562)."""
    assert stored_signoff_name(PRODUCTION_ADMINISTRATOR_LETTER) == "Administrator"
    assert stored_letter_has_placeholder_signer(PRODUCTION_ADMINISTRATOR_LETTER), (
        "the production letter signed 'Administrator' must be caught by the "
        "stored-body guard — it was exported as a clean PDF for 7 rows."
    )


def test_repaired_letter_passes_every_signer_gate():
    """The repair (sign-off corrected to the account's real ``User.name``,
    body untouched) must clear the guard — otherwise the fix would lock the
    user out of their own 7 letters."""
    assert stored_signoff_name(REPAIRED_LETTER) == "Vikram Deshpande"
    assert not stored_letter_has_placeholder_signer(REPAIRED_LETTER)
    assert scan_text(REPAIRED_LETTER, "letter") == []


# ===========================================================================
# 2. The detector: true positives (every marker class seen in production).
# ===========================================================================

TRUE_POSITIVE_CASES = [
    # (kind, text, expected marker)
    ("letter", PRODUCTION_ADMINISTRATOR_LETTER, "placeholder-signer"),
    ("name", "Gold Master V2 Test User", "placeholder-name"),
    ("name", "GM2 Signup Test", "placeholder-name"),
    ("email", "gm2-signup-1785488210@example.com", "reserved-email-domain"),
    ("email", "not-a-real-recipient@example.invalid", "reserved-email-domain"),
    ("email", "someone@qa.test", "reserved-email-domain"),
    ("email", "root@localhost", "reserved-email-domain"),
    (
        "prose",
        "MODELS-LIVE QA synthetic test row — deliberately missing recipient so "
        "approve cannot send a real email.",
        "self-declared-synthetic",
    ),
    ("prose", 'SYNTHETIC TEST DATA (models-live qa) — no "to" field on purpose.',
     "self-declared-synthetic"),
    ("prose", "MODELS-LIVE QA synthetic — do not send", "self-declared-synthetic"),
    (
        "prose",
        "GOLD-MASTER-V4 TEST DRAFT - safe to delete <script>alert(1)</script>",
        "self-declared-synthetic",
    ),
    (
        "prose",
        "GOLD-MASTER-V4 TEST DRAFT - safe to delete <script>alert(1)</script>",
        "harness-run-label",
    ),
    ("prose", "Adversarial draft test: <script>alert(2)</script>", "harness-run-label"),
    ("prose", "GAP-P7-DEF-B Probe 1785452243543", "harness-run-label"),
    (
        "prose",
        "…observability vision at Grafana Labs.\n\nSincerely,\n"
        "GAP-P7-DEF-B Probe 1785452243543\n",
        "harness-run-label",
    ),
    ("prose", "Demo-seeded job posting for the analytics funnel.", "demo-seed"),
    ("prose", "Demo seed resume", "demo-seed"),
    ("url", "https://demo.aether.dev/jobs/417", "demo-seed"),
    ("url", "http://localhost:3000/jobs/1", "non-routable-url"),
    ("url", "https://example.com/careers/42", "non-routable-url"),
    ("prose", "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
     "lorem-ipsum"),
    ("prose", "This section is placeholder text pending review.",
     "self-declared-synthetic"),
    ("prose", "dummy data for the funnel", "self-declared-synthetic"),
]


@pytest.mark.parametrize("kind,text,marker", TRUE_POSITIVE_CASES)
def test_detector_catches_production_marker(kind, text, marker):
    found = {name for name, _match, _ctx in scan_text(text, kind)}
    assert marker in found, (
        f"{marker!r} must be detected in {text!r} (kind={kind}); got {found or 'nothing'}"
    )


# ===========================================================================
# 3. The detector: false positives. Verbatim real production content.
# ===========================================================================

FALSE_POSITIVE_CORPUS = [
    # Résumé bullets (Resume.sections, user c6c8d016…)
    ("prose", "Test Automation Strategy: Architected the program's COBOL/mainframe "
              "test-evidence harness across 8 squads."),
    ("prose", "Authored the executive change request re-baselining Payday Super "
              "test capacity from 30 to up to 90 person-days."),
    ("prose", "Distributed PEM keys for fleet API signing, achieving 100% test "
              "coverage (Mocha/Chai)."),
    # STAR stories (StoryEntry)
    ("prose", "Executive Re-Baselining of Test Capacity for Payday Super"),
    ("prose", "COBOL/Mainframe Test Automation for 200+ Scenarios"),
    ("prose", "I implemented hallucination scoring via a fine-tuned classifier "
              "trained on synthetic test cases; I configured automated alerts."),
    # Cover-letter prose (Application.coverLetter)
    ("letter", "At the ATO, I architected the Payday Super program's test-evidence "
               "automation covering 200+ SIT/E2E scenarios.\n\nSincerely,\n"
               "Vikram Deshpande\n"),
    # Job descriptions (Job.description)
    ("prose", "Own end-to-end testing for credit automation workstreams, embedding "
              "test coverage into delivery plans."),
    ("prose", "Publishing a test integration the way a Partner would, and sourcing "
              "and wiring one the way a customer would."),
    ("prose", "Pressure test and continuously improve existing processes."),
    # Real job links (Job.sourceUrl) — long numeric ids are normal here
    ("url", "https://job-boards.greenhouse.io/netlify/jobs/8603630002"),
    ("url", "https://jobs.smartrecruiters.com/canva/6000000001274821"),
    ("url", "https://jobs.lever.co/mable/cc885c74-6ac9-4c0c-97fc-e69876379089"),
    # Real inbound email bodies (EmailThread.messages)
    ("prose", "Invoice number 5643538926 | Payments profile ID 5719-3106-9745"),
    ("prose", "Gemini 2.5 Flash Lite — gen-lang-client-0019917043"),
    ("prose", "You can verify domains, configure a supported identity provider, "
              "test the connection, and activate it."),
    ("prose", "4 x Senior Business Analysts & 2 x Senior Test Analysts — "
              "TLS Consulting Pty Ltd"),
    # Real people / companies
    ("name", "Vikram Deshpande"),
    ("prose", "Senior Test Analyst"),
    ("email", "sarkar.vikram@gmail.com"),
    ("email", "careers@plenti.com.au"),
    # ``test``/``invalid``/``localhost`` are reserved TLDs, not substrings:
    # test.com and protest.com are ordinary registrable domains a real employer
    # could own, and testing.io is a real company.
    ("email", "careers@test.com"),
    ("email", "hr@protest.com"),
    ("email", "talent@testing.io"),
    ("url", "https://careers.test.com/jobs/12"),
]


@pytest.mark.parametrize("kind,text", FALSE_POSITIVE_CORPUS)
def test_real_production_content_is_never_flagged(kind, text):
    """Every string here is REAL user work copied out of the production
    database. Flagging any of them would mean the audit proposes destroying or
    rewriting genuine content — a worse outcome than the residue it hunts."""
    hits = scan_text(text, kind)
    assert hits == [], (
        f"real production content wrongly flagged as fixture data "
        f"({kind}): {text!r} -> {hits}"
    )


# ===========================================================================
# 4. Whole-database scan — the regression guard proper.
# ===========================================================================

#: ``User`` is excluded from the DB-level scan: the pytest ``auth_headers``
#: fixture deliberately registers accounts at ``…@example.com`` (an isolated
#: test schema SHOULD use a reserved domain), so that table is permanently and
#: correctly "contaminated" here. Production coverage of ``User`` comes from
#: ``scripts/audit_fixture_markers.py``, which scans every table including it.
_CONTENT_TABLES = [
    "AgentRun",
    "Application",
    "ApprovalRequest",
    "BackgroundJob",
    "Contact",
    "EmailThread",
    "InterviewSchedule",
    "Job",
    "Offer",
    "OutreachTask",
    "Resume",
    "StoryEntry",
]


def _insert_realistic_clean_rows(conn, user_id: str) -> tuple[str, str, set[str]]:
    """Seed one job + résumé + application + story + email thread whose text is
    verbatim real production content (the hazardous kind), so a zero-finding
    result is a meaningful statement and not an empty-table tautology.

    Returns ``(job_id, resume_id, every_clean_row_id)``.
    """
    job_id = uuid.uuid4().hex[:25]
    resume_id = uuid.uuid4().hex[:25]
    application_id = uuid.uuid4().hex[:25]
    story_id = uuid.uuid4().hex[:25]
    thread_id = uuid.uuid4().hex[:25]
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description",'
            '"source","sourceUrl","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,now())',
            (
                job_id,
                user_id,
                "Senior Test Analyst",
                "TLS Consulting Pty Ltd",
                "Own end-to-end testing for credit automation workstreams, "
                "embedding test coverage into delivery plans.",
                "greenhouse",
                "https://job-boards.greenhouse.io/netlify/jobs/8603630002",
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","label","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,%s,%s::jsonb,%s,now())',
            (
                resume_id,
                user_id,
                "Uploaded — Vik_Resume_Final",
                json.dumps(
                    {
                        "bullets": [
                            {
                                "text": "Test Automation Strategy: Architected "
                                "the program's COBOL/mainframe test-evidence "
                                "harness across 8 squads."
                            }
                        ]
                    }
                ),
                "sha-real",
            ),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,now())',
            (
                application_id,
                user_id,
                job_id,
                resume_id,
                "submitted",
                "At the ATO, I architected the Payday Super program's "
                "test-evidence automation covering 200+ SIT/E2E scenarios.\n\n"
                "Sincerely,\nVikram Deshpande\n",
            ),
        )
        cur.execute(
            'INSERT INTO "StoryEntry" ("id","userId","title","situation","task",'
            '"action","result","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,now())',
            (
                story_id,
                user_id,
                "COBOL/Mainframe Test Automation for 200+ Scenarios",
                "The SIT timeline was infeasible.",
                "Re-baseline test capacity.",
                "I implemented hallucination scoring via a classifier trained "
                "on synthetic test cases.",
                "Cut per-scenario effort by 92%.",
            ),
        )
        cur.execute(
            'INSERT INTO "EmailThread" ("id","userId","subject","messages",'
            '"classification","updatedAt") VALUES (%s,%s,%s,%s::jsonb,%s,now())',
            (
                thread_id,
                user_id,
                "4 x Senior Business Analysts & 2 x Senior Test Analysts",
                json.dumps(
                    [{"role": "inbound", "body": "Invoice number 5643538926"}]
                ),
                "auto",
            ),
        )
    conn.commit()
    return job_id, resume_id, {
        job_id, resume_id, application_id, story_id, thread_id,
    }


def test_clean_content_tables_yield_no_findings(client, auth_headers, db_session):
    """A realistic, entirely genuine dataset must produce ZERO findings.

    Scoped to the rows this test creates: ``aether_test`` is a SHARED schema and
    several of the tables scanned here (``BackgroundJob``, ``Offer``,
    ``OutreachTask``, ``InterviewSchedule``) are deliberately NOT in
    ``conftest._TABLES_TO_CLEAN``, so a global zero-assertion would be a flake
    on another suite's residue rather than a statement about this code.
    """
    user_id = client._test_user_id
    _job_id, _resume_id, clean_ids = _insert_realistic_clean_rows(db_session, user_id)
    findings = scan_connection(
        db_session, schema="aether_test", tables=_CONTENT_TABLES
    )
    wrongly_flagged = [f.as_dict() for f in findings if f.row_id in clean_ids]
    assert wrongly_flagged == [], (
        "clean production-shaped content produced findings — the audit would "
        f"propose destroying real user work: {wrongly_flagged}"
    )


def test_reintroduced_fixture_rows_are_caught_by_the_db_scan(
    client, auth_headers, db_session
):
    """The guard proper: re-insert the exact rows found in production on
    2026-08-02 and prove the scan names every one of them."""
    user_id = client._test_user_id
    job_id, _resume_id, clean_ids = _insert_realistic_clean_rows(db_session, user_id)
    thread_id = uuid.uuid4().hex[:25]
    approval_id = uuid.uuid4().hex[:25]
    resume_id = uuid.uuid4().hex[:25]
    application_id = uuid.uuid4().hex[:25]
    agent_run_id = uuid.uuid4().hex[:25]
    background_job_id = uuid.uuid4().hex[:25]
    probe_letter = (
        "…observability vision at Grafana Labs. I am available for a call at "
        "your convenience.\n\nSincerely,\nGAP-P7-DEF-B Probe 1785452243543\n"
    )
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "BackgroundJob" ("id","userId","agentKey","status","result")'
            " VALUES (%s,%s,%s,%s,%s::jsonb)",
            (
                background_job_id,
                user_id,
                "coverLetter",
                "completed",
                json.dumps({"cover_letter": probe_letter, "costUsd": 0.006816}),
            ),
        )
        cur.execute(
            'INSERT INTO "AgentRun" ("id","userId","agentName","status","output")'
            " VALUES (%s,%s,%s,%s::\"AgentRunStatus\",%s::jsonb)",
            (
                agent_run_id,
                user_id,
                "coverLetter",
                "completed",
                json.dumps({"cover_letter": probe_letter, "costUsd": 0.006816}),
            ),
        )
        cur.execute(
            'INSERT INTO "EmailThread" ("id","userId","subject","messages",'
            '"classification","updatedAt") VALUES (%s,%s,%s,%s::jsonb,%s,now())',
            (
                thread_id,
                user_id,
                "GOLD-MASTER-V4 TEST DRAFT - safe to delete <script>alert(1)</script>",
                json.dumps(
                    [
                        {
                            "role": "draft",
                            "body": "To: not-a-real-recipient@example.invalid\n\n"
                            "Adversarial draft test: <script>alert(2)</script>",
                        }
                    ]
                ),
                "auto",
            ),
        )
        cur.execute(
            'INSERT INTO "ApprovalRequest" ("id","userId","type","status",'
            '"payload") VALUES (%s,%s,%s,%s,%s::jsonb)',
            (
                approval_id,
                user_id,
                "email_send",
                "approved",
                json.dumps(
                    {
                        "why": "MODELS-LIVE QA synthetic test row — deliberately "
                        "missing recipient so approve cannot send a real email.",
                        "body": "synthetic test body, no recipient set",
                        "preview": 'SYNTHETIC TEST DATA (models-live qa) — no "to" '
                        "field on purpose.",
                        "subject": "MODELS-LIVE QA synthetic — do not send",
                    }
                ),
            ),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","label","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,%s,%s::jsonb,%s,now())',
            (resume_id, user_id, "Demo seed resume", "{}", "demo-seed-hash"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,now())',
            (
                application_id,
                user_id,
                job_id,
                resume_id,
                "submitted",
                PRODUCTION_ADMINISTRATOR_LETTER,
            ),
        )
    db_session.commit()

    findings = scan_connection(
        db_session, schema="aether_test", tables=_CONTENT_TABLES
    )
    caught = {(f.table, f.row_id, f.marker) for f in findings}

    assert ("EmailThread", thread_id, "harness-run-label") in caught
    assert ("EmailThread", thread_id, "self-declared-synthetic") in caught
    assert ("ApprovalRequest", approval_id, "self-declared-synthetic") in caught
    assert ("ApprovalRequest", approval_id, "harness-run-label") in caught
    assert ("Resume", resume_id, "demo-seed") in caught
    assert ("AgentRun", agent_run_id, "harness-run-label") in caught, (
        "a stored agent-run output signed with the BLOCKER-002 probe identity "
        f"must be reported; got {sorted(caught)}"
    )
    assert ("BackgroundJob", background_job_id, "harness-run-label") in caught, (
        "GET /agents/jobs/{id} returns BackgroundJob.result verbatim, so a "
        f"probe-signed letter there must be reported too; got {sorted(caught)}"
    )
    assert ("Application", application_id, "placeholder-signer") in caught, (
        "a cover letter signed 'Administrator' must be reported by the "
        f"whole-database audit; got {sorted(caught)}"
    )

    # …and the genuine rows seeded alongside them must NOT appear. (Scoped to
    # this test's own rows: ``aether_test`` is shared and several scanned tables
    # are not truncated between tests — see
    # ``test_clean_content_tables_yield_no_findings``.)
    flagged = {f.row_id for f in findings}
    assert flagged & clean_ids == set(), (
        "the scan flagged genuine rows seeded alongside the contaminated ones: "
        f"{sorted(flagged & clean_ids)}"
    )


# ===========================================================================
# 5. The demo-funnel seeder must not exist as a runnable production hazard.
# ===========================================================================


def test_seed_demo_has_no_fabricated_funnel_generator():
    """``scripts/seed_demo.py`` used to carry a ``main()`` that DELETEd every
    ``Application``/``Job`` row belonging to the production owner's email and
    replaced them with 847 fabricated jobs and 412 fabricated applications —
    a one-command production data-loss + fixture-injection tool, wired to the
    repo-root ``.env`` (i.e. the production DSN) by its own env loader.

    Nothing imports it but ``seed_admin_user``; the funnel generator is pure
    hazard and must stay deleted."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        'DELETE FROM "Application"',
        'DELETE FROM "Job"',
        "Demo-seeded job posting",
        "demo.aether.dev",
        "demo-seed-hash",
        "Demo seed resume",
        "FUNNEL",
    ):
        assert forbidden not in source, (
            f"scripts/seed_demo.py must not contain {forbidden!r}: the demo-funnel "
            "generator injects fabricated Jobs/Applications into — and deletes the "
            "real rows of — whichever database the repo-root .env points at."
        )
