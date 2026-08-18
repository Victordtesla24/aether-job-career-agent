"""SUB-010 — the SMART SHORTLIST answer pack for a manual application.

LEDGER REQUIREMENT: *"read-only ``GET /applications/{id}/answer-pack`` fusing
profile + answer bank + resume + cover for every manual job, + a 'needs your
click' filter. Buildable from existing parts. Honesty contract: never claims
applied."*

THE DEVIATION THIS FILE CLOSES. Every prepared-but-not-transmitted application
in production leaves the user to re-assemble, by hand and from four different
screens, the exact material Aether already holds for that one job: the contact
details on their résumé, the answers they have banked for the screening
questions this form will ask, the job-tailored résumé Aether generated, and
the cover letter it wrote. There was no endpoint that fused them, so there was
no one screen to copy from.

WHAT IS PINNED HERE
-------------------
1. **Fusion** — profile fields, answer-bank entries matched to the job's KNOWN
   (captured off the employer's own form) and LIKELY (the seed question set
   every ATS asks) questions, the tailored-résumé artifact reference, and the
   cover letter.
2. **Honest absence** — a missing piece is reported as absent, with a reason.
   Nothing is invented, substituted or defaulted.
3. **The honesty contract** — for a row with no transmission proof the pack
   NEVER claims the application was applied/submitted/sent. Pinned as a scan
   of every string Aether itself authored in the payload.
4. **AuthZ** — another user's application is a 404, not a leak.
5. **Read-only** — a GET mutates nothing.

Nothing in this file contacts an employer or submits anything anywhere; all
data is synthetic and lives only in the ``aether_test`` schema.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest

# --------------------------------------------------------------------------
# The claim scan (acceptance clause 3).
#
# These words are how this product has historically over-claimed: a card that
# said "Submitted" for a row with no transmittedAt, 346 times over
# (uat/reports/evidence/agents-uplift/u5d/FORENSICS.md). The pack is a NEW
# surface over exactly that population, so its own copy is held to the rule
# rather than trusted.
# --------------------------------------------------------------------------

#: A claim word Aether's OWN copy may not use about a non-transmitted row.
_CLAIM_RE = re.compile(r"\b(applied|submitted|sent)\b", re.I)

#: "transmitted" is allowed only inside a negation — the honesty block's whole
#: job is to say the application was NOT transmitted.
_TRANSMITTED_RE = re.compile(r"\btransmitted\b", re.I)
_NEGATED_TRANSMITTED_RE = re.compile(r"\b(not|never|no|nothing)\b[^.]*\btransmitted\b", re.I)

#: Keys whose string values are VERBATIM third-party content — the employer's
#: question wording, the user's own answer, their résumé label, the job title,
#: the company name, the cover letter body. Quoting those faithfully is the
#: honesty contract, not a breach of it, so the scan skips them and holds only
#: the strings AETHER wrote.
_VERBATIM_KEYS = frozenset(
    {
        "question",
        "bankedQuestion",
        "answer",
        "value",
        "text",
        "jobTitle",
        "company",
        "label",
        "applyUrl",
    }
)


def _aether_authored_strings(node: Any, key: str | None = None) -> list[str]:
    """Every string in the payload that Aether itself wrote (see above)."""
    if isinstance(node, dict):
        found: list[str] = []
        for child_key, child in node.items():
            found.extend(_aether_authored_strings(child, str(child_key)))
        return found
    if isinstance(node, list):
        found = []
        for child in node:
            found.extend(_aether_authored_strings(child, key))
        return found
    if isinstance(node, str) and key not in _VERBATIM_KEYS:
        return [node]
    return []


def _uid() -> str:
    return uuid.uuid4().hex


#: The résumé contact block a real upload carries. Used as the profile source.
_CONTACT = {
    "name": "Priya Raman",
    "title": "Staff Platform Engineer",
    "email": "priya.raman@example.com",
    "phone": "+61 400 111 222",
    "linkedin": "https://www.linkedin.com/in/priya-raman",
}


def _seed_job(conn, user_id: str, *, apply_url: str) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (
                job_id,
                user_id,
                "Staff Platform Engineer",
                "Northwind Systems",
                "Own the platform.",
                "seek",
                apply_url,
                92.0,
            ),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str, *, job_id: str | None, label: str) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","label","sections","formatHash",'
            '"sourceJobId","createdAt","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())',
            (
                resume_id,
                user_id,
                2 if job_id else 1,
                label,
                json.dumps(
                    {
                        "contact": _CONTACT,
                        "raw_text": (
                            "PRIYA RAMAN\nStaff Platform Engineer\n\n"
                            "EXPERIENCE\n  Ran the platform.\n"
                        ),
                    }
                ),
                f"hash-{resume_id[:8]}",
                job_id,
            ),
        )
    conn.commit()
    return resume_id


def _seed_application(
    conn,
    user_id: str,
    job_id: str,
    resume_id: str,
    *,
    app_status: str = "submitted",
    cover_letter: str | None = "Dear Northwind hiring team,",
    answers: dict[str, Any] | None = None,
) -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","answers","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,%s,NOW(),NOW())',
            (
                app_id,
                user_id,
                job_id,
                resume_id,
                app_status,
                cover_letter,
                json.dumps(answers) if answers is not None else None,
            ),
        )
    conn.commit()
    return app_id


def _record_employer_questions(conn, app_id: str, questions: list[dict[str, Any]]) -> None:
    """Write the questions the apply-executor captured off the employer's form."""
    from app.db import (
        ensure_application_manual_step_columns,
        ensure_application_manual_step_question_column,
    )

    ensure_application_manual_step_columns()
    ensure_application_manual_step_question_column()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE "Application" SET "manualStepReason" = %s, "manualStepDetail" = %s,'
            ' "manualStepAt" = NOW(), "manualStepQuestions" = %s WHERE "id" = %s',
            (
                "unknown_required_question",
                "This form asks something Aether has no answer for.",
                json.dumps(questions),
                app_id,
            ),
        )
    conn.commit()


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture()
def bank(user_id):
    """The user's standing Answer Bank, written through the real repository."""
    from app.repositories.answer_bank import AnswerBankRepository

    repo = AnswerBankRepository()

    def _bank(question: str, answer: str, **kwargs: Any) -> dict[str, Any] | None:
        kwargs.setdefault("provenance", "user_answered")
        return repo.upsert(user_id, question=question, answer=answer, **kwargs)

    return _bank


def _entry(pack: dict[str, Any], needle: str) -> dict[str, Any]:
    """The one answer entry whose question contains ``needle``."""
    matches = [
        item
        for item in pack["answers"]["entries"]
        if needle.lower() in str(item["question"]).lower()
    ]
    assert matches, f"no answer-pack entry for {needle!r}"
    return matches[0]


def _field(pack: dict[str, Any], key: str) -> dict[str, Any]:
    matches = [item for item in pack["profile"]["fields"] if item["key"] == key]
    assert matches, f"no profile field {key!r}"
    return matches[0]


class TestAnswerPackFusion:
    """Clause 1 — one screen fusing profile + bank + résumé + cover letter."""

    def test_pack_fuses_every_part_for_a_manual_application(
        self, client, auth_headers, user_id, db_session, bank
    ):
        job_id = _seed_job(
            db_session, user_id, apply_url="https://www.seek.com.au/job/8811"
        )
        base_id = _seed_resume(db_session, user_id, job_id=None, label="Base résumé")
        tailored_id = _seed_resume(
            db_session, user_id, job_id=job_id, label="Northwind — tailored"
        )
        app_id = _seed_application(
            db_session,
            user_id,
            job_id,
            base_id,
            answers={"screeningAnswers": {"Why Northwind Systems?": "Your platform work."}},
        )
        _record_employer_questions(
            db_session,
            app_id,
            [
                {
                    "name": "why_us",
                    "label": "Why Northwind Systems?",
                    "kind": "textarea",
                    "required": True,
                }
            ],
        )
        bank(
            "Are you legally entitled to work in the country you are applying in?",
            "Yes — Australian citizen, full working rights.",
        )

        response = client.get(f"/applications/{app_id}/answer-pack", headers=auth_headers)
        assert response.status_code == 200, response.text
        pack = response.json()

        assert pack["applicationId"] == app_id
        assert pack["jobId"] == job_id
        assert pack["jobTitle"] == "Staff Platform Engineer"
        assert pack["company"] == "Northwind Systems"

        # -- profile ----------------------------------------------------
        email = _field(pack, "email")
        assert email["present"] is True
        assert "@" in email["value"]
        phone = _field(pack, "phone")
        assert phone["present"] is True
        assert phone["value"] == _CONTACT["phone"]
        linkedin = _field(pack, "linkedin")
        assert linkedin["present"] is True
        assert linkedin["value"] == _CONTACT["linkedin"]
        github = _field(pack, "github")
        assert github["present"] is False
        assert github["value"] is None
        assert github["absence"]

        # -- answer bank ------------------------------------------------
        employer_q = _entry(pack, "Why Northwind Systems?")
        assert employer_q["questionSource"] == "employer_form"
        assert employer_q["answered"] is True
        assert employer_q["answer"] == "Your platform work."
        assert employer_q["answerSource"] == "this_application"

        work_rights = _entry(pack, "legally entitled to work")
        assert work_rights["questionSource"] == "likely_for_any_application"
        assert work_rights["answered"] is True
        assert work_rights["answer"] == "Yes — Australian citizen, full working rights."
        assert work_rights["answerSource"] == "answer_bank"
        assert work_rights["matchConfidence"] >= 0.8
        assert work_rights["bankedQuestion"]

        # A likely question nobody has answered is reported honestly, with no
        # invented answer and no suggestion.
        salary = _entry(pack, "salary expectations")
        assert salary["answered"] is False
        assert salary["answer"] is None
        assert salary["absence"]
        assert pack["answers"]["unansweredCount"] >= 1

        # -- résumé + cover letter --------------------------------------
        assert pack["resume"]["present"] is True
        assert pack["resume"]["resumeId"] == tailored_id
        assert pack["resume"]["tailoredToThisJob"] is True
        assert pack["resume"]["downloadPath"] == f"/resumes/{tailored_id}/download"
        assert pack["coverLetter"]["present"] is True
        assert pack["coverLetter"]["text"] == "Dear Northwind hiring team,"

    def test_a_judgement_answer_is_shown_but_never_marked_auto_sendable(
        self, client, auth_headers, user_id, db_session, bank
    ):
        """The bank's transmission gate is reported, never quietly widened."""
        job_id = _seed_job(db_session, user_id, apply_url="https://jobs.lever.co/nw/1")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(db_session, user_id, job_id, resume_id)
        bank("What are your salary expectations?", "AUD 210,000 base plus super.")

        pack = client.get(
            f"/applications/{app_id}/answer-pack", headers=auth_headers
        ).json()
        salary = _entry(pack, "salary expectations")
        assert salary["answered"] is True
        assert salary["answer"] == "AUD 210,000 base plus super."
        # Judgement class: user-gated until the user opts THAT item in.
        assert salary["wouldAutoSend"] is False
        assert salary["gateReason"]


class TestHonestAbsence:
    """Clause 1 — missing pieces reported as absent, never fabricated."""

    def test_missing_resume_and_cover_letter_are_reported_absent(
        self, client, auth_headers, user_id, db_session
    ):
        job_id = _seed_job(db_session, user_id, apply_url="https://jobs.lever.co/nw/2")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, cover_letter=None
        )

        pack = client.get(
            f"/applications/{app_id}/answer-pack", headers=auth_headers
        ).json()

        assert pack["resume"]["present"] is False
        assert pack["resume"]["resumeId"] is None
        assert pack["resume"]["downloadPath"] is None
        assert pack["resume"]["absence"]
        assert pack["coverLetter"]["present"] is False
        assert pack["coverLetter"]["text"] is None
        assert pack["coverLetter"]["absence"]

    def test_an_empty_bank_answers_nothing_and_says_so(
        self, client, auth_headers, user_id, db_session
    ):
        job_id = _seed_job(db_session, user_id, apply_url="https://jobs.lever.co/nw/3")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        pack = client.get(
            f"/applications/{app_id}/answer-pack", headers=auth_headers
        ).json()

        entries = pack["answers"]["entries"]
        assert entries, "the likely-question set must still be listed"
        assert all(item["answered"] is False for item in entries)
        assert all(item["answer"] is None for item in entries)
        assert pack["answers"]["answeredCount"] == 0
        assert pack["answers"]["unansweredCount"] == len(entries)


class TestHonestyContract:
    """Clause 3 — the pack never claims this application went anywhere."""

    def test_a_prepared_row_never_reads_as_applied(
        self, client, auth_headers, user_id, db_session, bank
    ):
        job_id = _seed_job(db_session, user_id, apply_url="https://www.seek.com.au/job/99")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        # The exact production shape: status 'submitted', transmittedAt NULL.
        app_id = _seed_application(
            db_session, user_id, job_id, resume_id, app_status="submitted"
        )
        bank("What is your notice period?", "Four weeks.")

        pack = client.get(
            f"/applications/{app_id}/answer-pack", headers=auth_headers
        ).json()

        assert pack["honesty"]["transmitted"] is False
        assert pack["honesty"]["claim"] == "prepared"
        assert pack["honesty"]["statement"]
        assert pack["honesty"]["readOnly"] is True

        offenders = [
            text for text in _aether_authored_strings(pack) if _CLAIM_RE.search(text)
        ]
        assert not offenders, f"the pack claims a submission: {offenders}"

        unnegated = [
            text
            for text in _aether_authored_strings(pack)
            if _TRANSMITTED_RE.search(text) and not _NEGATED_TRANSMITTED_RE.search(text)
        ]
        assert not unnegated, f"unnegated transmission claim: {unnegated}"

    def test_the_pack_is_read_only(self, client, auth_headers, user_id, db_session):
        job_id = _seed_job(db_session, user_id, apply_url="https://www.seek.com.au/job/98")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        def _row() -> tuple:
            with db_session.cursor() as cur:
                cur.execute(
                    'SELECT "status"::text, "updatedAt", "transmittedAt", "coverLetter" '
                    'FROM "Application" WHERE "id" = %s',
                    (app_id,),
                )
                return cur.fetchone()

        before = _row()
        assert (
            client.get(
                f"/applications/{app_id}/answer-pack", headers=auth_headers
            ).status_code
            == 200
        )
        db_session.commit()
        assert _row() == before


class TestAuthorization:
    """Clause 4 — the pack is scoped to the owning user."""

    def test_a_foreign_user_cannot_read_the_pack(
        self, client, auth_headers, user_id, db_session
    ):
        job_id = _seed_job(db_session, user_id, apply_url="https://www.seek.com.au/job/97")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        credentials = {
            "email": f"sub010-other-{uuid.uuid4().hex[:8]}@example.com",
            "password": "Sup3rSecret",
        }
        assert client.post("/auth/register", json=credentials).status_code == 201
        token = client.post("/auth/login", json=credentials).json()["access_token"]
        foreign = {"Authorization": f"Bearer {token}"}

        response = client.get(f"/applications/{app_id}/answer-pack", headers=foreign)
        assert response.status_code == 404
        assert app_id not in response.text

    def test_an_unauthenticated_request_is_rejected(
        self, client, auth_headers, user_id, db_session
    ):
        job_id = _seed_job(db_session, user_id, apply_url="https://www.seek.com.au/job/96")
        resume_id = _seed_resume(db_session, user_id, job_id=None, label="Base")
        app_id = _seed_application(db_session, user_id, job_id, resume_id)

        assert client.get(f"/applications/{app_id}/answer-pack").status_code in (401, 403)

    def test_an_unknown_application_is_a_404(self, client, auth_headers):
        response = client.get(f"/applications/{_uid()}/answer-pack", headers=auth_headers)
        assert response.status_code == 404
