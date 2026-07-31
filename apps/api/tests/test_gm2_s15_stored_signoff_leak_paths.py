"""GOLD-MASTER-V2 §15 / BLOCKER-002 — the two OPEN leak paths for an
ALREADY-CONTAMINATED stored cover-letter body.

[VERIFIED live on production 2026-07-31T11:26:25Z] Evidence:
``uat/reports/evidence/gold-master-v2/waves/blocker002-remediation-plan.md``
(§3.3/§3.4/§3.6) and ``blocker002-live-pdf-probe-20260731T1126Z.txt``.

All three shipped placeholder-signer guards test the LIVE PROFILE NAME at
call time; NOT ONE inspects the stored letter body. Two consequences, both
verified against production:

d1 — ``GET /cover-letters/{id}/pdf`` and ``POST /cover-letters/{id}/refine``
     read the stored body verbatim. Correcting ``User.name`` at
     2026-07-31T01:12:27Z therefore *unblocked* the export for 8 already
     contaminated letters: three PDFs were pulled off production at HTTP 200
     showing a CLEAN live letterhead ("Vikram Deshpande") over a
     CONTAMINATED stored sign-off ("GAP-P7-DEF-B Probe 1785452243543"),
     served as ``attachment; filename="cover-letter-<company>.pdf"``.

d2 — ``POST /jobs/{id}/apply`` copies/promotes a draft body into a submitted
     row with raw SQL, no LLM call and NO guard at all, so a contaminated
     draft mints a fresh contaminated submitted row. Both contaminated
     drafts are currently the selected copy source (``pick_rank = 1``).

There are TWO fixture variants in production (5 rows + 3 rows), so nothing
here is keyed to a single literal.

The letters are seeded directly with SQL — the contamination under test is a
STORED-DATA state that the (working) generation-time guard makes
unreachable through the API, which is precisely why these paths need their
own guard.
"""
from __future__ import annotations

import json

import pytest
from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume

from app.db import get_connection, new_id

#: Both production fixture variants (remediation plan §1.2).
FIXTURE_VARIANTS = [
    "GAP-P7-DEF-B Probe 1785452243543",
    "GAP-P7-DEF-B Probe 1784823962960",
]

#: Legitimate prose that trips every raw signal the name rule looks for — a
#: bare "test" token, a bare "gap" token and an 8+ digit run. Present in EVERY
#: seeded letter, clean and contaminated alike, so any guard that scans the
#: whole body instead of the sign-off line fails the clean-path tests here.
HAZARDOUS_PROSE = (
    "I led testing for three squads and closed the capability gap between "
    "platform and product. In one gap analysis I ran a test of the ingestion "
    "pipeline that processed 12345678 events without a dropped record."
)


def _letter_body(signer: str, company: str = "Grafana Labs") -> str:
    """A §10.2-shaped letter exactly as ``compose_letter`` emits it."""
    return (
        "31 July 2026\n\n"
        f"Hiring Team\n{company}\nRe: Senior Product Manager\n\n"
        f"Dear Hiring Team at {company},\n\n"
        f"{HAZARDOUS_PROSE}\n\n"
        f"Sincerely,\n{signer}\n"
    )


def _make_job(user_id: str, company: str = "Grafana Labs") -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Product Manager", company, "Sydney NSW",
                    False, "Own the platform observability roadmap.", json.dumps([]),
                    "seek", f"https://example.com/{job_id}", 88.0,
                ),
            )
        conn.commit()
    return job_id


def _make_resume(user_id: str, *, source_job_id: str | None = None) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","sourceJobId","updatedAt")
                   VALUES (%s,%s,1,%s,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Experienced product manager"}),
                 "hash", source_job_id),
            )
        conn.commit()
    return resume_id


def _make_draft_letter(
    user_id: str, job_id: str, resume_id: str, signer: str, *, age_minutes: int = 0
) -> str:
    """A stored draft ``Application`` carrying a cover letter signed ``signer``."""
    letter_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter",
                    "createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,
                           NOW() - (%s * INTERVAL '1 minute'), NOW())''',
                (letter_id, user_id, job_id, resume_id, _letter_body(signer), age_minutes),
            )
        conn.commit()
    return letter_id


def _seed_stored_letter(user_id: str, signer: str) -> tuple[str, str]:
    job_id = _make_job(user_id)
    resume_id = _make_resume(user_id, source_job_id=job_id)
    return _make_draft_letter(user_id, job_id, resume_id, signer), job_id


def _job_status(job_id: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            return cur.fetchone()[0]


def _application_statuses(job_id: str) -> list[str]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "status" FROM "Application" WHERE "jobId" = %s ORDER BY "createdAt"',
                (job_id,),
            )
            return [r[0] for r in cur.fetchall()]


# ===========================================================================
# d1 — PDF export must inspect the STORED sign-off
# ===========================================================================


@pytest.mark.parametrize("fixture_name", FIXTURE_VARIANTS)
def test_pdf_export_refuses_contaminated_stored_signoff(
    client, auth_headers, test_user_id, fixture_name
):
    """The exact live defect: profile name is CLEAN, stored sign-off is not.
    The export must refuse instead of shipping a submission-ready PDF."""
    letter_id, _ = _seed_stored_letter(test_user_id, fixture_name)

    resp = client.get(f"/cover-letters/{letter_id}/pdf", headers=auth_headers)

    assert resp.status_code == 422, (
        "PDF export must refuse a letter whose STORED sign-off is a "
        f"placeholder/test artefact ({fixture_name!r}) even though the live "
        "profile name is clean — this is the exact HTTP 200 verified on "
        f"production 2026-07-31T11:26:25Z. Got {resp.status_code}."
    )
    detail = str(resp.json().get("detail", ""))
    assert "sign-off" in detail.lower(), (
        f"the 422 must name the real cause (the stored sign-off), got {detail!r}"
    )
    assert fixture_name.lower() not in resp.text.lower(), (
        "the raw placeholder string must never leak into the error response"
    )


def test_pdf_export_still_serves_a_clean_letter(client, auth_headers, test_user_id):
    """False-positive guard: the guard now runs over MODEL-GENERATED PROSE.
    A clean letter whose BODY says "led testing"/"capability gap" and quotes
    an 8-digit figure must still export — refusing it denies a paying user
    their own document."""
    letter_id, _ = _seed_stored_letter(test_user_id, "Jordan Rivera")

    resp = client.get(f"/cover-letters/{letter_id}/pdf", headers=auth_headers)

    assert resp.status_code == 200, (
        "a legitimately-signed letter must still export; body prose "
        f"containing 'test'/'gap'/digits must not trip the guard. {resp.text[:500]!r}"
    )
    assert resp.content.startswith(b"%PDF")
    assert "attachment; filename=" in resp.headers["content-disposition"]


@pytest.mark.parametrize("signer", ["MV Tester", "Sarah Probert"])
def test_pdf_export_serves_a_letter_signed_by_a_real_person(
    client, auth_headers, test_user_id, signer
):
    """A real human whose surname merely looks test-ish must not be locked
    out of their own letters (the FP class commit 1f6f6a5 already fixed once
    for the profile-name path — it must not come back through the body)."""
    letter_id, _ = _seed_stored_letter(test_user_id, signer)

    resp = client.get(f"/cover-letters/{letter_id}/pdf", headers=auth_headers)

    assert resp.status_code == 200, (
        f"a letter signed by {signer!r} (a real name) must export. {resp.text[:500]!r}"
    )


# ===========================================================================
# d1 — refine must inspect the STORED sign-off it is about to re-compose
# ===========================================================================


@pytest.mark.parametrize("fixture_name", FIXTURE_VARIANTS)
def test_refine_refuses_contaminated_stored_letter(
    client, auth_headers, test_user_id, fixture_name
):
    """Refine re-composes a NEW stored row from the letter it is handed. A
    contaminated source must be refused, not silently laundered into a fresh
    row — and refusing costs nothing because the guard fires before any LLM
    call (``_record_run`` refunds the reserved quota)."""
    seed_own_resume(client, auth_headers)
    letter_id, _ = _seed_stored_letter(test_user_id, fixture_name)

    resp = client.post(
        f"/cover-letters/{letter_id}/refine",
        json={"instructions": "Sharpen the closing."},
        headers=auth_headers,
    )

    assert resp.status_code == 422, (
        "refine must refuse a stored letter whose sign-off is a "
        f"placeholder/test artefact ({fixture_name!r}). Got "
        f"{resp.status_code}: {resp.text[:500]!r}"
    )
    detail = str(resp.json().get("detail", ""))
    assert "sign-off" in detail.lower(), (
        f"the 422 must name the real cause (the stored sign-off), got {detail!r}"
    )
    assert fixture_name.lower() not in resp.text.lower()


def test_refine_still_works_on_a_clean_generated_letter(client, auth_headers):
    """False-positive guard on the refine path, end-to-end through real
    (replay) generation: a normally generated letter must still be
    refinable."""
    seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
    scout = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert scout.status_code == 202, scout.text
    job = client.get("/jobs", headers=auth_headers).json()[0]
    gen = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
    )
    assert gen.status_code == 200, gen.text

    resp = client.post(
        f"/cover-letters/{gen.json()['cover_letter_id']}/refine",
        json={"instructions": "Sharpen the closing."},
        headers=auth_headers,
    )

    assert resp.status_code == 200, (
        f"a cleanly generated letter must stay refinable. {resp.text[:500]!r}"
    )


# ===========================================================================
# d2 — the apply-copy path (raw SQL, no LLM, no guard today)
# ===========================================================================


@pytest.mark.parametrize("fixture_name", FIXTURE_VARIANTS)
def test_apply_refuses_to_submit_a_contaminated_draft(
    client, auth_headers, test_user_id, fixture_name
):
    """Applying must not mint a submitted application carrying a QA fixture
    as the signer, and must leave the job un-applied so the failure is
    honest rather than optimistic."""
    letter_id, job_id = _seed_stored_letter(test_user_id, fixture_name)
    before_status = _job_status(job_id)

    resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)

    assert resp.status_code == 422, (
        "apply must refuse when the draft it would submit carries a "
        f"placeholder sign-off ({fixture_name!r}). Got {resp.status_code}: "
        f"{resp.text[:500]!r}"
    )
    detail = str(resp.json().get("detail", ""))
    assert "sign-off" in detail.lower(), (
        f"the 422 must name the real cause (the stored sign-off), got {detail!r}"
    )
    assert fixture_name.lower() not in resp.text.lower()
    assert _job_status(job_id) == before_status, (
        "a refused apply must NOT mark the job applied"
    )
    assert _application_statuses(job_id) == ["draft"], (
        "a refused apply must neither mint a new submitted row nor promote "
        f"the contaminated draft; got {_application_statuses(job_id)}"
    )
    assert letter_id  # the seeded draft row is the one that must stay a draft


def test_apply_refuses_rather_than_silently_substituting_an_older_clean_draft(
    client, auth_headers, test_user_id
):
    """Decision under test: REFUSE, never silently swap the copy source.
    The Studio shows the NEWEST draft; submitting a different, older body
    than the one the user is looking at is a silent substitution."""
    job_id = _make_job(test_user_id)
    resume_id = _make_resume(test_user_id, source_job_id=job_id)
    _make_draft_letter(test_user_id, job_id, resume_id, "Jordan Rivera", age_minutes=60)
    _make_draft_letter(test_user_id, job_id, resume_id, FIXTURE_VARIANTS[0], age_minutes=0)

    resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)

    assert resp.status_code == 422, (
        "with a contaminated NEWEST draft, apply must refuse — silently "
        "falling back to the older clean draft would submit a body the user "
        f"never saw. Got {resp.status_code}: {resp.text[:500]!r}"
    )
    assert _application_statuses(job_id) == ["draft", "draft"]
    assert _job_status(job_id) != "applied"


def test_apply_still_works_for_a_clean_draft(client, auth_headers, test_user_id):
    """False-positive guard on the apply path: the seeded letter's PROSE
    carries "testing"/"gap"/an 8-digit run, so a body-wide scan would block a
    legitimate application."""
    letter_id, job_id = _seed_stored_letter(test_user_id, "Jordan Rivera")

    resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)

    assert resp.status_code == 200, (
        f"a clean draft must still be applyable. {resp.text[:500]!r}"
    )
    assert resp.json()["applicationId"]
    assert _job_status(job_id) == "applied"
    assert _application_statuses(job_id) == ["submitted"], (
        "the clean draft must be promoted/copied to submitted exactly once"
    )
    assert letter_id


def test_apply_still_works_for_a_draft_signed_by_a_real_person(
    client, auth_headers, test_user_id
):
    letter_id, job_id = _seed_stored_letter(test_user_id, "Sarah Probert")

    resp = client.post(f"/jobs/{job_id}/apply", headers=auth_headers)

    assert resp.status_code == 200, (
        f"'Sarah Probert' is a real name; apply must succeed. {resp.text[:500]!r}"
    )
    assert _job_status(job_id) == "applied"
    assert letter_id
