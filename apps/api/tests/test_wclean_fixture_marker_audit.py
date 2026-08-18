"""W-CLEAN — regression guard: no fixture / test / probe / placeholder residue
may exist in user-visible columns.

Written RED against HEAD on 2026-08-02, reproducing six classes of
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

import ast
import importlib.util
import json
import uuid
from pathlib import Path

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

#: Verbatim tail of production ``Job`` ``c40c7085c424bd1870f70065e`` (Airtasker,
#: "Media Coordinator", source ``ashby``,
#: ``https://jobs.ashbyhq.com/airtasker/704c39fd-…/application``) — a real
#: employer's real posting fetched from a real board.
#:
#: This is the false-positive class that made ``scripts/audit_fixture_markers.py``
#: report contamination against the LIVE database on 2026-08-03: the
#: ``self-declared-synthetic`` rule carried a bare ``do not send`` alternative,
#: meant for a QA row that labels itself "MODELS-LIVE QA synthetic — do not
#: send". "Do not send" is also, and far more commonly, ordinary recruitment-
#: agency boilerplate addressed to staffing suppliers, and it appeared in 7 real
#: Airtasker postings. Every one was reported as fixture residue.
#:
#: The discriminator is grammatical, not lexical: the harness directive has no
#: object — the phrase ENDS the line ("… synthetic — do not send"). The agency
#: clause always names what must not be sent ("do not send resumes directly to
#: managers"). A rule that flags this string proposes deleting a real job the
#: user could apply to.
PRODUCTION_AGENCY_CLAUSE = (
    "To all recruitment agencies and talent suppliers: Airtasker does not "
    "accept unsolicited resumes. Airtasker is not responsible for any fees "
    "related to unsolicited resumes. Please do not forward resumes to our job "
    "postings or directly to our managers. If you are on our supplier list and "
    "have terms in place, ensure you work alongside our internal TA team and "
    "do not send resumes directly to managers. #LI-TR1 #LI-Hybrid"
)

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
    # The recruitment-agency clause (see PRODUCTION_AGENCY_CLAUSE below).
    ("prose", PRODUCTION_AGENCY_CLAUSE),
    ("prose", "Please do not send unsolicited resumes to our hiring managers."),
    ("prose", "Agencies: do not send CVs without a signed agreement in place."),
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


def test_recruitment_agency_clause_is_not_a_synthetic_self_declaration():
    """The exact false positive ``scripts/audit_fixture_markers.py`` reported
    against the LIVE database (7 × ``Job.description``, all real Airtasker
    postings sourced from Ashby).

    Both halves are the contract: the agency clause must be clean, and the
    harness directive the rule exists for must still be caught — the fix is a
    narrowing of the rule, never its removal."""
    assert scan_text(PRODUCTION_AGENCY_CLAUSE, "prose") == [], (
        "a real employer's agency clause was reported as fixture residue; the "
        "audit would propose deleting 7 genuine jobs the user can apply to"
    )
    harness_markers = {
        name
        for name, _match, _context in scan_text(
            "MODELS-LIVE QA synthetic — do not send", "prose"
        )
    }
    assert "self-declared-synthetic" in harness_markers, (
        "narrowing the rule must not disarm it: an objectless 'do not send' "
        "directive that ends the line is still a harness self-declaration"
    )


# ===========================================================================
# 4. Whole-database scan — the regression guard proper.
# ===========================================================================

#: ``User`` is excluded from the DB-level scan: the pytest ``auth_headers``
#: fixture deliberately registers accounts at ``…@example.com`` (an isolated
#: test schema SHOULD use a reserved domain), so that table is permanently and
#: correctly "contaminated" here. Production coverage of ``User`` comes from
#: ``scripts/audit_fixture_markers.py``, which scans every table including it.
def _live_schema(conn) -> str:
    """The schema the test connection is ACTUALLY pinned to.

    TEST-PAR-1: a battery may run in the legacy shared ``aether_test`` or in
    a per-wave ``aether_test_<wave>`` schema. Hard-coding ``aether_test``
    here would make this audit scan a schema the rows were never written to
    — silently vacuous in one direction and a false failure in the other.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        return cur.fetchone()[0]


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
                "embedding test coverage into delivery plans.\n\n"
                + PRODUCTION_AGENCY_CLAUSE,
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

    Scoped to the rows this test creates: the test schema is shared (legacy
    ``aether_test``) or wave-private (``aether_test_<wave>``), and
    several of the tables scanned here (``BackgroundJob``, ``Offer``,
    ``OutreachTask``, ``InterviewSchedule``) are deliberately NOT in
    ``conftest._TABLES_TO_CLEAN``, so a global zero-assertion would be a flake
    on another suite's residue rather than a statement about this code.
    """
    user_id = client._test_user_id
    _job_id, _resume_id, clean_ids = _insert_realistic_clean_rows(db_session, user_id)
    findings = scan_connection(
        db_session, schema=_live_schema(db_session), tables=_CONTENT_TABLES
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
    _clean_job_id, _resume_id, clean_ids = _insert_realistic_clean_rows(
        db_session, user_id
    )
    thread_id = uuid.uuid4().hex[:25]
    approval_id = uuid.uuid4().hex[:25]
    resume_id = uuid.uuid4().hex[:25]
    application_id = uuid.uuid4().hex[:25]
    # The contaminated Application needs a job of its OWN: ``db.py``'s
    # ``Application_user_job_active_key`` partial unique index allows exactly one
    # ACTIVE ('submitted'/'screening'/'interview'/'offer') application per
    # (userId, jobId), and the clean row above is already a 'submitted' one on
    # the clean job. Reusing it raised UniqueViolation the moment that index
    # existed in ``aether_test`` — the index is created lazily on first use, so
    # this test only ever passed in a session that had not yet created it.
    job_id = uuid.uuid4().hex[:25]
    agent_run_id = uuid.uuid4().hex[:25]
    background_job_id = uuid.uuid4().hex[:25]
    probe_letter = (
        "…observability vision at Grafana Labs. I am available for a call at "
        "your convenience.\n\nSincerely,\nGAP-P7-DEF-B Probe 1785452243543\n"
    )
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description",'
            '"source","sourceUrl","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,now())',
            (
                job_id,
                user_id,
                "Senior Product Manager, Strategic Origination Platforms",
                "Plenti",
                "Own the origination platform roadmap end to end.",
                "greenhouse",
                "https://job-boards.greenhouse.io/plenti/jobs/4471003",
            ),
        )
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
        db_session, schema=_live_schema(db_session), tables=_CONTENT_TABLES
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
#
# Scope note (2026-08-03). The first version of this guard scanned the RAW
# SOURCE TEXT of ``scripts/seed_demo.py`` for the forbidden literals. That
# self-triggered: the module docstring is the written record of what the
# deleted generator did and necessarily quotes ``DELETE FROM "Application"``,
# so the guard failed against the very state it exists to accept. The rewrite
# (2b7dc6b) fixed the false positive by parsing the module and inspecting only
# executable code — but in doing so it NARROWED the true-positive surface to
# ``ast.Assign`` targets and bare ``ast.Constant`` strings, which is a small
# fraction of the ways the generator can come back:
#
#     FUNNEL: dict[str, int] = {...}        # AnnAssign  — not an Assign
#     FUNNEL, TITLES = _load_demo()         # Tuple target — not an ast.Name
#     def FUNNEL(): ...                     # a def binds the name too
#     from demo_data import funnel as FUNNEL
#     cur.execute(f'DELETE FROM "Application" WHERE "userId" = {uid}')   # JoinedStr
#     cur.execute('DELETE FROM ' + '"Application"')                      # BinOp
#
# Every one of those slipped through. The analysis below restores full
# coverage: ALL binding forms the language has, and static string values folded
# through f-strings and ``+`` concatenation — while still excluding docstrings,
# so the deletion record above stays legal.


#: SQL and content literals that only the deleted demo-funnel generator emits.
_FORBIDDEN_SEED_LITERALS = (
    'DELETE FROM "Application"',
    'DELETE FROM "Job"',
    'INSERT INTO "Job"',
    'INSERT INTO "Application"',
    "Demo-seeded job posting",
    "demo.aether.dev",
    "demo-seed-hash",
    "Demo seed resume",
)

#: Module-level names that only the generator defines.
_FORBIDDEN_SEED_NAMES = {"FUNNEL", "COMPANIES", "TITLES", "DEMO_EMAIL"}


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    """``id()`` of every string Constant that is a docstring.

    Docstrings are prose ABOUT the code, and this module's docstring documents
    the deleted generator verbatim. Only code can reintroduce the hazard, so
    only code is inspected.
    """
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _static_string(node: ast.AST, docstring_ids: set[int]) -> str | None:
    """The statically-known string value of ``node``, or ``None``.

    Folds the three ways a literal can be spelled without changing what the
    database receives:

    * ``ast.Constant``  — a plain (or implicitly concatenated) literal;
    * ``ast.JoinedStr`` — an f-string, whose interpolations are rendered back
      to source so ``f'DELETE FROM "Application" WHERE id={x}'`` still reads as
      the forbidden statement;
    * ``ast.BinOp``/``Add`` — ``'DELETE FROM ' + '"Application"'``.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return None if id(node) in docstring_ids else node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                try:
                    parts.append(ast.unparse(value.value))
                except Exception:  # pragma: no cover - unparse is total in 3.12
                    parts.append("")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left, docstring_ids)
        right = _static_string(node.right, docstring_ids)
        if left is not None and right is not None:
            return left + right
    return None


def _executable_string_literals(tree: ast.Module) -> list[str]:
    """Every statically-known string value in EXECUTABLE code."""
    docstring_ids = _docstring_node_ids(tree)
    values: list[str] = []
    for node in ast.walk(tree):
        text = _static_string(node, docstring_ids)
        if text is not None:
            values.append(text)
    return values


def _target_names(node: ast.AST | None) -> set[str]:
    """Names bound by an assignment target (recursing into tuple/list/starred).

    ``a.b = …`` and ``a[0] = …`` bind nothing at module level, so Attribute and
    Subscript targets yield nothing.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(e) for e in node.elts)) if node.elts else set()
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return set()


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name BOUND anywhere in ``tree``, by any construct the language has.

    Checking ``ast.Assign`` alone (the 2b7dc6b guard) misses annotated and
    augmented assignment, tuple unpacking, walrus, loop and ``with``/``except``
    targets, comprehensions, ``def``/``class``, imports, parameters and match
    captures — each of which can reintroduce ``FUNNEL``/``COMPANIES``/
    ``TITLES``/``DEMO_EMAIL`` just as effectively as ``FUNNEL = {...}``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                names |= _target_names(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            names |= _target_names(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            names |= _target_names(node.target)
        elif isinstance(node, ast.withitem):
            names |= _target_names(node.optional_vars)
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)):
            if node.name:
                names.add(node.name)
        elif isinstance(node, ast.MatchMapping):
            if node.rest:
                names.add(node.rest)
    return names


def seed_demo_reintroductions(source: str) -> tuple[list[str], set[str]]:
    """``(offending literals, reintroduced names)`` for a ``seed_demo`` source.

    Empty + empty means the demo-funnel generator is absent. This is the whole
    guard, exposed as a function so it can be exercised against synthesised
    re-additions as well as against the real file.
    """
    tree = ast.parse(source)
    literals = _executable_string_literals(tree)
    offending = [
        text
        for forbidden in _FORBIDDEN_SEED_LITERALS
        for text in literals
        if forbidden in text
    ]
    return offending, _bound_names(tree) & _FORBIDDEN_SEED_NAMES


def _seed_demo_source() -> str:
    return (
        Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py"
    ).read_text(encoding="utf-8")


def test_seed_demo_has_no_fabricated_funnel_generator():
    """``scripts/seed_demo.py`` used to carry a ``main()`` that DELETEd every
    ``Application``/``Job`` row belonging to the production owner's email and
    replaced them with 847 fabricated jobs and 412 fabricated applications —
    a one-command production data-loss + fixture-injection tool, wired to the
    repo-root ``.env`` (i.e. the production DSN) by its own env loader.

    Nothing imports it but ``seed_admin_user``; the funnel generator is pure
    hazard and must stay deleted."""
    literals, names = seed_demo_reintroductions(_seed_demo_source())
    assert literals == [], (
        "scripts/seed_demo.py executes a statement containing a demo-funnel "
        "literal: the generator injects fabricated Jobs/Applications into — and "
        "deletes the real rows of — whichever database the repo-root .env "
        f"points at. Offending literal(s): {literals}"
    )
    assert names == set(), (
        f"scripts/seed_demo.py re-defines {sorted(names)} — the fabricated "
        "demo-funnel constants (847/412 counts, fake companies/titles, and the "
        "production owner's email as DEMO_EMAIL)."
    )


#: Every way the deleted generator can come back. ``ast.Assign``-only analysis
#: catches exactly ONE of these (the first); the rest are the coverage that was
#: lost when the guard stopped reading source text.
_REINTRODUCTION_FORMS = [
    ("plain assignment", 'FUNNEL = {"sourced": 847, "applied": 412}\n'),
    ("annotated assignment", 'FUNNEL: dict[str, int] = {"sourced": 847}\n'),
    ("annotated declaration only", "COMPANIES: list[str]\n"),
    ("augmented assignment", 'TITLES = []\nTITLES += ["Data Analyst"]\n'),
    ("tuple unpacking", "FUNNEL, _rest = _load_demo()\n"),
    ("starred unpacking", "_head, *COMPANIES = _load_demo()\n"),
    ("walrus", "if (DEMO_EMAIL := _owner_email()):\n    pass\n"),
    ("for-loop target", "for TITLES in _rows():\n    pass\n"),
    ("with-statement target", "with _open() as COMPANIES:\n    pass\n"),
    ("except-clause target", "try:\n    pass\nexcept OSError as FUNNEL:\n    pass\n"),
    ("comprehension target", "_x = [FUNNEL for FUNNEL in _rows()]\n"),
    ("import alias", "from demo_data import funnel as FUNNEL\n"),
    ("plain import", "import COMPANIES\n"),
    ("function definition", "def FUNNEL():\n    return 847\n"),
    ("class definition", "class TITLES:\n    pass\n"),
    ("function parameter", "def _seed(DEMO_EMAIL='owner@example.com'):\n    pass\n"),
    ("global rebind in a function", "def _seed():\n    global FUNNEL\n    FUNNEL = {}\n"),
    (
        "match capture",
        "match _rows():\n    case {'funnel': FUNNEL}:\n        pass\n",
    ),
]


@pytest.mark.parametrize("label,snippet", _REINTRODUCTION_FORMS)
def test_guard_catches_every_form_of_name_reintroduction(label, snippet):
    """A re-added generator must be caught however it binds its constants.

    The 2026-08-02 rewrite checked ``ast.Assign`` targets only, so anything in
    this list but the first line slipped through silently — the guard reported
    GREEN on a file that had the hazard back."""
    _literals, names = seed_demo_reintroductions(
        '"""Provision the platform-owner admin account."""\n' + snippet
    )
    assert names, (
        f"a {label} reintroducing a demo-funnel constant was NOT caught: "
        f"{snippet!r}"
    )


#: The same, for the SQL the generator executes.
_REINTRODUCTION_STATEMENTS = [
    ("plain literal", "_cur.execute('DELETE FROM \"Application\" WHERE 1=1')\n"),
    (
        "implicit concatenation",
        "_cur.execute('DELETE FROM ' \"\\\"Job\\\" WHERE 1=1\")\n",
    ),
    (
        "explicit concatenation",
        "_cur.execute('DELETE FROM ' + '\"Application\" WHERE 1=1')\n",
    ),
    (
        "f-string",
        "_cur.execute(f'DELETE FROM \"Application\" WHERE \"userId\" = {_uid}')\n",
    ),
    (
        "f-string insert",
        "_cur.execute(f'INSERT INTO \"Job\" (id) VALUES ({_jid})')\n",
    ),
    (
        "content literal in an f-string",
        "_desc = f'Demo-seeded job posting for {_n}'\n",
    ),
    ("url literal", "_url = 'https://demo.aether.dev/jobs/417'\n"),
]


@pytest.mark.parametrize("label,snippet", _REINTRODUCTION_STATEMENTS)
def test_guard_catches_every_form_of_sql_reintroduction(label, snippet):
    """The destructive statements must be caught however the string is built."""
    literals, _names = seed_demo_reintroductions(
        '"""Provision the platform-owner admin account."""\n' + snippet
    )
    assert literals, (
        f"a {label} reintroducing the demo-funnel SQL/content was NOT caught: "
        f"{snippet!r}"
    )


def test_guard_does_not_self_trigger_on_the_deletion_record():
    """The false positive that motivated the 2026-08-02 rewrite must stay dead.

    ``seed_demo``'s module docstring quotes the deleted SQL verbatim — that is
    the record of the removal, and it must remain legal to write it down.
    Function and class docstrings get the same treatment."""
    source = (
        '"""Removed: the generator ran DELETE FROM "Application" and '
        'DELETE FROM "Job", then INSERT INTO "Job" 847 rows described as '
        '"Demo-seeded job posting for the analytics funnel." at '
        'https://demo.aether.dev/jobs/N, plus a "Demo seed resume" '
        '(formatHash demo-seed-hash) and INSERT INTO "Application" 412 rows.\n'
        'Its constants were FUNNEL, COMPANIES, TITLES and DEMO_EMAIL."""\n'
        "\n"
        "def seed_admin_user():\n"
        '    """Upserts the admin row with INSERT INTO "User" — not a funnel."""\n'
        "    return None\n"
    )
    literals, names = seed_demo_reintroductions(source)
    assert (literals, names) == ([], set()), (
        "the guard fired on prose that merely RECORDS the deletion: "
        f"literals={literals} names={sorted(names)}"
    )


def test_guard_accepts_the_real_seed_demo_and_rejects_its_ancestor():
    """Both directions against real sources: the file as shipped is clean, and
    the same analysis applied to a module that genuinely carries the generator
    reports it."""
    assert seed_demo_reintroductions(_seed_demo_source()) == ([], set())

    ancestor = (
        '"""Seed the canonical demo funnel."""\n'
        "FUNNEL = {'sourced': 847, 'applied': 412}\n"
        "COMPANIES: list[str] = ['Northwind', 'Initech']\n"
        "TITLES, DEMO_EMAIL = ['Data Analyst'], 'owner@example.com'\n"
        "\n"
        "def main():\n"
        '    _cur.execute(\'DELETE FROM "Application" WHERE "userId" = %s\', (_u,))\n'
        "    _cur.execute(f'INSERT INTO \"Job\" (id, description) VALUES "
        "({_i}, \\'Demo-seeded job posting for the analytics funnel.\\')')\n"
    )
    literals, names = seed_demo_reintroductions(ancestor)
    assert names == _FORBIDDEN_SEED_NAMES, sorted(names)
    assert literals, "the ancestor's destructive SQL was not reported"


# ===========================================================================
# 6. The shipped audit SCRIPT must actually run against the live database.
# ===========================================================================


def _audit_script_module():
    """Import ``scripts/audit_fixture_markers.py`` as a module.

    The script is what an operator (and any deploy gate) actually runs, so its
    connection handling is production code and belongs under test — that it was
    not is precisely why it could sit broken.
    """
    path = Path(__file__).resolve().parents[1] / "scripts" / "audit_fixture_markers.py"
    spec = importlib.util.spec_from_file_location("_audit_fixture_markers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


#: The shape of the real production ``DATABASE_URL``: Prisma writes a
#: ``?schema=`` query parameter, which libpq does not accept.
_PRISMA_STYLE_DSN = (
    "postgresql://role:pw@db-fdc4e11da.db005.hosteddb.reai.io:5432/"
    "fdc4e11da?schema=aether&connect_timeout=15"
)


def test_audit_script_dsn_is_accepted_by_psycopg2():
    """The audit exited 1 against production without scanning a single row:

        psycopg2.ProgrammingError: invalid dsn:
            invalid URI query parameter: "schema"

    It passed ``get_database_url()`` straight to ``psycopg2.connect``, but every
    DSN in this repo is Prisma-style. ``app.db`` has translated that param into
    a ``search_path`` option since P2-S01; the script simply never used it."""
    import psycopg2.extensions

    module = _audit_script_module()
    dsn, schema = module.resolve_connection_target(_PRISMA_STYLE_DSN)

    assert schema == "aether"
    parsed = psycopg2.extensions.parse_dsn(dsn)  # raised ProgrammingError before
    assert "schema" not in parsed
    assert parsed["dbname"] == "fdc4e11da"
    assert parsed["connect_timeout"] == "15"


def test_audit_script_schema_override_wins_over_the_dsn():
    """``--schema aether_test`` must still be honoured."""
    module = _audit_script_module()
    _dsn, schema = module.resolve_connection_target(
        _PRISMA_STYLE_DSN, schema_override="aether_test"
    )
    assert schema == "aether_test"


def test_audit_script_defaults_the_schema_when_the_dsn_omits_it():
    module = _audit_script_module()
    _dsn, schema = module.resolve_connection_target(
        "postgresql://role:pw@host:5432/db"
    )
    assert schema == "aether"
