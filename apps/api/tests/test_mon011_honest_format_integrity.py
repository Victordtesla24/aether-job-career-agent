"""MON-011 (MONITORING-LEDGER.md) — Resume Studio's "Format Integrity Check"
claims layout preservation while EVERY real user upload re-flows into the
generic branded template.

RCA: ``GET /resumes/{id}/download`` (apps/api/app/routers/resumes.py) only
byte-preserves a résumé when ``resolve_original_pdf(formatHash)``
(apps/api/app/services/resume_pdf.py) finds a BUNDLED asset on disk whose
SHA-256 matches — that is true for exactly the two seeded operator PDFs
(``assets/resume/*.pdf``). A real upload's ``formatHash`` is the SHA-256 of
the UPLOADED FILE's own bytes (``upload_resume``) or of its raw extracted
text (``create_resume``'s JSON-ingest path) — it can never collide with a
bundled asset, so ``resolve_original_pdf`` returns ``None`` and the download
falls through to ``create_branded_resume_pdf`` (the generic re-flowed
template).

The frontend's "Format Integrity Check" panel (apps/web/src/app/dashboard/
resume/page.tsx) does not know any of this: it derives its claim purely from
``selected.formatHash === baseHash`` — comparing a résumé's format hash to
ITS OWN base's format hash. For the base résumé itself this is a TRIVIAL
self-comparison (always true) and says nothing about whether the download
path can actually reproduce the original bytes/layout. So every real user
sees "Layout hash matches the base — typography, spacing, columns & margins
preserved" for a résumé that will, in fact, download as the generic
re-flowed template — a shipped honesty defect (HIGH).

Fix contract: the API must expose an explicit ``formatPreserved`` boolean —
true iff ``resolve_original_pdf`` would find a bundled match for this résumé
(mirroring the download endpoint's own decision), false otherwise — so the
frontend can render an honest claim instead of inferring one from an
unrelated self-comparison. This suite pins the BACKEND half of that contract
on the endpoint the frontend actually consumes for the résumé list
(``GET /resumes``, via ``lib/api/resumes.ts fetchResumes()``).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _seed_resume_with_explicit_hash(client, auth_headers, *, format_hash: str,
                                     label: str = "Bundled-backed resume") -> dict:
    resp = client.post(
        "/resumes",
        json={
            "label": label,
            "raw_text": (
                "Jordan Rivera. Senior Program Manager with a decade of "
                "cross-functional delivery experience across payments and "
                "platform modernisation initiatives, partnering with "
                "engineering and product to ship measurable outcomes."
            ),
            "format_hash": format_hash,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_uploaded_resume_reports_format_not_preserved(client, auth_headers):
    """FAILS on the pre-fix API: a real (non-bundled-hash) résumé has no
    ``formatPreserved`` key at all today. Once added, it must be explicitly
    ``False`` — this is exactly the case whose download re-flows into the
    generic branded template, so the API must not stay silent about it.
    """
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)

    listing = client.get("/resumes", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    resumes = listing.json()
    assert resumes, "expected the seeded resume to be listed"

    resume = resumes[0]
    assert "formatPreserved" in resume, (
        "GET /resumes must expose an explicit `formatPreserved` boolean per "
        "resume (MON-011) — got keys: " + ", ".join(sorted(resume.keys()))
    )
    assert resume["formatPreserved"] is False, (
        "a resume ingested via raw_text (no bundled PDF backing it) must "
        f"report formatPreserved=False, got {resume['formatPreserved']!r}"
    )


def test_bundled_seed_pdf_resume_reports_format_preserved(client, auth_headers):
    """Anti-regression: a résumé whose formatHash genuinely matches a bundled
    asset (the seed/BA PDFs — the ONLY résumés that are byte-preserved end to
    end) must keep reporting ``formatPreserved=True``. Computed the same way
    ``resolve_original_pdf`` matches, so this test can never silently drift
    from the real matching rule.
    """
    from app.agents.fit_scorer import get_base_resume_path

    assets_dir = get_base_resume_path().parent
    bundled_pdfs = sorted(assets_dir.glob("*.pdf"))
    if not bundled_pdfs:
        pytest.skip("no bundled résumé assets on disk in this environment")
    bundled_hash = hashlib.sha256(Path(bundled_pdfs[0]).read_bytes()).hexdigest()[:16]

    _seed_resume_with_explicit_hash(client, auth_headers, format_hash=bundled_hash)

    listing = client.get("/resumes", headers=auth_headers)
    assert listing.status_code == 200, listing.text
    resumes = listing.json()
    assert resumes, "expected the seeded resume to be listed"

    resume = resumes[0]
    assert "formatPreserved" in resume, (
        "GET /resumes must expose an explicit `formatPreserved` boolean per resume"
    )
    assert resume["formatPreserved"] is True, (
        "a resume whose formatHash matches a bundled asset must report "
        f"formatPreserved=True, got {resume['formatPreserved']!r}"
    )
