"""U2b CRITICAL — a rendered résumé must carry the WHOLE persisted document.

Live evidence (``uat/reports/evidence/agents-uplift/u2b/verify-final/``,
2026-08-14, résumé ``c12187d107bf994471844e09a``, tailor run
``c714727c916c40699e59662ba``): the reflow-template download shipped

* 17 of the résumé's 25 persisted bullets — 8 silently absent;
* NO contact block (email, phone, location, LinkedIn, GitHub), NO education,
  NO skills, NO certifications, and only the first half of the name;
* two pages whose rendered bytes were identical to each other;

while ``GET /resumes/{id}/fidelity`` reported ``changesDropped: 1`` — honest
about the ONE tracked rewrite it checked, silently false about the 32% of the
document that never made it onto the page. A subscriber approving that résumé
would have sent an employer a document with no way to contact them.

Two contracts are pinned here, and both are whole-document contracts:

1. **The renderer** rebuilds every persisted section (contact, education,
   skills, certifications, experience) and every bullet, paginating instead of
   truncating, and never emits a duplicate page.
2. **Verification** measures the whole document, not only the tracked edits: a
   render that loses ANY persisted heading, bullet or contact field is reported
   as content-incomplete, with the missing items NAMED, and the fidelity claim
   degrades accordingly.
"""
from __future__ import annotations

import hashlib

# The live résumé's shape, reproduced: a two-column PDF text layer where the
# name wraps over two lines, the headline over four, and the sidebar sections
# (contact / education / skills / certifications) are interleaved with the
# work-experience job headers exactly as PyMuPDF flattens them.
CONTACT_EMAIL = "sarkar.vikram@gmail.com"
CONTACT_PHONE = "+61 433 224 556"
CONTACT_LOCATION = "Melbourne, VIC, Australia"
CONTACT_LINKEDIN = "linkedin.com/in/vikramd-profile"
CONTACT_GITHUB = "github.com/Victordtesla24"

CONTEXT_LINES = [
    "VIKRAM",
    "DESHPANDE",
    "Senior Technical",
    "Program/Delivery",
    "Manager & AI",
    "Solutions Architect",
    "CONTACT INFO",
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_LOCATION,
    CONTACT_LINKEDIN,
    CONTACT_GITHUB,
    "EDUCATION",
    "Master of Computer Science",
    "Monash University",
    "2010",
    "Melbourne",
    "Bachelor of Engineering",
    "Computer Science",
    "University of Melbourne",
    "2007",
    "Melbourne",
    "SKILLS",
    "CAREER OBJECTIVE",
    "15+ year Senior Technical Leader and Certified Scrum Master (CSM) specializing in",
    "end-to-end program delivery, enterprise transformation, and architecting AI/ML-driven",
    "solutions across the Financial Services and Telecommunications sectors.",
    "WORK EXPERIENCE",
    "Scrum Master / Project Manager",
    "Australian Taxation Office (ATO)",
    "March 2026 - Present",
    "Melbourne, VIC",
    "Senior Delivery Lead / Technical Product Owner",
    "ANZ",
    "Sept 2017 - June 2025",
    "Melbourne, VIC",
    "Technical Program Management,",
    "Agile/Scrum/SAFe, Product",
    "Ownership, Roadmap & Backlog",
    "Management, Stakeholder",
    "Alignment, Risk & Budget",
    "Management ($5M+).",
    "CERTIFICATIONS",
    "Certified Scrum Master (CSM)",
    "Scrum Alliance",
]

#: 25 bullets at the live document's own length — more than one Letter page of
#: 9pt body copy, which is exactly the condition the shipped renderer silently
#: truncated at.
BULLETS = [
    (
        f"Bullet {i:02d}: Delivered measurable programme outcomes across the "
        f"delivery portfolio, coordinating {i + 3} squads through PI planning, "
        f"risk management and executive reporting to land capability {i} on "
        f"schedule with a {i + 10} percent efficiency gain recorded."
    )
    for i in range(25)
]

REQUIRED_HEADINGS = (
    "CONTACT INFO",
    "EDUCATION",
    "SKILLS",
    "CAREER OBJECTIVE",
    "WORK EXPERIENCE",
    "CERTIFICATIONS",
)

CONTACT_FIELDS = (
    CONTACT_EMAIL,
    CONTACT_PHONE,
    CONTACT_LOCATION,
    CONTACT_LINKEDIN,
    CONTACT_GITHUB,
)


def _raw_text() -> str:
    return "\n".join(CONTEXT_LINES + [f"• {text}" for text in BULLETS])


def _resume(**overrides):
    resume = {
        "id": "c12187d107bf994471844e09a",
        "label": "Tailored — Staff Software Engineer @ Canva",
        "parentId": "cfe7a0f27991821dc73f265cd",
        "sections": {
            "raw_text": _raw_text(),
            "bullets": [
                {"text": text, "evidenceRef": f"bullet-{i}"}
                for i, text in enumerate(BULLETS)
            ],
        },
    }
    resume.update(overrides)
    return resume


def _normalize(text: str) -> str:
    from app.services.format_verification import _normalize as fold

    return fold(text)


def _rendered_text(pdf_bytes: bytes) -> str:
    from app.services.format_verification import extract_artifact_text

    text = extract_artifact_text(pdf_bytes, "application/pdf")
    assert text is not None, "the produced PDF must be re-readable"
    return _normalize(text)


def _render(resume) -> bytes:
    from app.routers.resumes import _branded_content
    from app.services.resume_pdf import create_branded_resume_pdf

    name, title, objective, sections, contact = _branded_content(resume)
    return create_branded_resume_pdf(
        name, title, objective, sections, None, contact=contact
    )


# ---------------------------------------------------------------------------
# (1) The renderer keeps the WHOLE document
# ---------------------------------------------------------------------------


def test_branded_render_carries_every_persisted_bullet():
    """All 25 persisted bullets, not the 17 that fit on one page.

    Expected RED: ``_draw_right_column`` ``break``s out of its loop when it
    runs out of vertical space on the single page pair it draws, so the tail of
    a long résumé is discarded without a trace.
    """
    text = _rendered_text(_render(_resume()))
    missing = [b for b in BULLETS if _normalize(b) not in text]
    assert not missing, (
        f"{len(missing)} of {len(BULLETS)} persisted bullets never reached the "
        f"rendered document — first missing: {missing[0]!r}"
    )


def test_branded_render_carries_every_persisted_section_heading():
    """Contact / education / skills / certifications are part of the résumé."""
    text = _rendered_text(_render(_resume()))
    missing = [h for h in REQUIRED_HEADINGS if _normalize(h) not in text]
    assert not missing, (
        f"persisted section headings absent from the rendered document: {missing}"
    )


def test_branded_render_carries_contact_fields_and_the_full_name():
    """A résumé an employer cannot reply to is worse than no résumé at all."""
    text = _rendered_text(_render(_resume()))
    missing = [f for f in CONTACT_FIELDS if _normalize(f) not in text]
    assert not missing, f"contact fields absent from the rendered document: {missing}"
    assert _normalize("VIKRAM DESHPANDE") in text, (
        "the rendered document must carry the whole name, not its first line"
    )


def test_branded_render_carries_education_and_skills_detail():
    """The sidebar's own lines, not just its headings."""
    text = _rendered_text(_render(_resume()))
    for line in (
        "Master of Computer Science",
        "Monash University",
        "Bachelor of Engineering",
        "University of Melbourne",
        "Certified Scrum Master (CSM)",
        "Technical Program Management,",
    ):
        assert _normalize(line) in text, f"persisted line lost in the render: {line!r}"


def test_branded_render_emits_no_duplicate_page():
    """The live artifact's two pages were byte-identical to each other."""
    import fitz

    pdf_bytes = _render(_resume())
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        digests = [
            hashlib.sha256(page.get_text().encode("utf-8")).hexdigest() for page in doc
        ]
        page_count = len(doc)
    finally:
        doc.close()
    assert page_count >= 1
    assert len(set(digests)) == page_count, (
        "a downloaded résumé must not repeat a page — duplicate page digests "
        f"across {page_count} pages: {digests}"
    )


# ---------------------------------------------------------------------------
# (2) Verification measures the WHOLE document, not only the tracked edits
# ---------------------------------------------------------------------------


def test_completeness_verification_passes_on_a_complete_render():
    from app.services.resume_completeness import (
        build_resume_content,
        verify_completeness,
    )

    resume = _resume()
    content = build_resume_content(resume)
    result = verify_completeness(_render(resume), "application/pdf", content)
    assert result.text_extracted is True
    assert result.complete is True, f"unexpectedly incomplete: {result.missing}"
    assert result.missing == ()


def test_completeness_verification_names_what_a_lossy_render_dropped():
    """The old renderer's output, measured: the report must NAME the loss."""
    from app.services.resume_completeness import (
        build_resume_content,
        verify_completeness,
    )
    from app.services.resume_pdf import create_branded_resume_pdf

    resume = _resume()
    content = build_resume_content(resume)
    # The live artifact's own damage, rebuilt through the renderer's public API:
    # the name's first line only, no contact/education/skills/certifications,
    # everything under one "Experience" heading, and — as the shipped file
    # measured — the first 17 of the résumé's 25 bullets, the rest cut off the
    # end of the page (verify-final/CRITICAL-FINDING-content-loss.json).
    lossy = create_branded_resume_pdf(
        "VIKRAM", "", "", [{"heading": "Experience", "bullets": list(BULLETS[:17])}], None
    )
    result = verify_completeness(lossy, "application/pdf", content)
    assert result.complete is False
    named = " ".join(result.missing).lower()
    assert "contact" in named or CONTACT_EMAIL.lower() in named, (
        f"the report must name the missing contact information, got {result.missing}"
    )
    assert any("education" in item.lower() for item in result.missing), (
        f"the report must name the missing education section, got {result.missing}"
    )
    assert result.missing_bullets, (
        "the truncated tail of the bullet list must be reported as missing"
    )


def test_fidelity_report_degrades_and_names_the_loss_when_content_is_dropped():
    from app.services.format_verification import RenderVerification
    from app.services.resume_completeness import CompletenessVerification
    from app.services.resume_format import METHOD_REFLOW, describe_fidelity, verified_fidelity

    base = describe_fidelity(
        bundled_match=False, has_original=True, content_type="application/pdf",
        is_tailored=True,
    )
    assert base.method == METHOD_REFLOW
    complete_changes = RenderVerification(requested=0, text_extracted=True, outcomes=())
    report = verified_fidelity(
        base,
        complete_changes,
        completeness=CompletenessVerification(
            text_extracted=True,
            missing_headings=("EDUCATION",),
            missing_bullets=("Bullet 24: …",),
            missing_contact=(CONTACT_EMAIL,),
        ),
    )
    assert report.preserved is False, (
        "a render that lost part of the user's own résumé is not a faithful one"
    )
    assert report.confidence == "partial"
    assert report.content_complete is False
    note = report.note.lower()
    assert "education" in note, f"the note must name the missing section: {report.note}"
    assert "contact" in note or CONTACT_EMAIL.lower() in note, report.note
    payload = report.as_dict()
    assert payload["contentComplete"] is False
    assert payload["missingContent"], "the API payload must carry what is missing"


def test_fidelity_report_records_content_completeness_when_nothing_was_lost():
    from app.services.format_verification import RenderVerification
    from app.services.resume_completeness import CompletenessVerification
    from app.services.resume_format import describe_fidelity, verified_fidelity

    base = describe_fidelity(
        bundled_match=False, has_original=False, content_type=None, is_tailored=True,
    )
    report = verified_fidelity(
        base,
        RenderVerification(requested=0, text_extracted=True, outcomes=()),
        completeness=CompletenessVerification(text_extracted=True),
    )
    assert report.content_complete is True
    assert report.as_dict()["contentComplete"] is True
    assert report.as_dict()["missingContent"] == []


# ---------------------------------------------------------------------------
# (3) End to end: the download endpoint itself
# ---------------------------------------------------------------------------


def test_download_of_a_tailored_reflow_resume_is_content_complete(client, auth_headers):
    """The live failure, through the real endpoint pair.

    A text-ingested résumé has no bundled source PDF and no stored upload, so
    its tailored child takes the reflow-template branch — the branch that
    shipped the incomplete document. The download must carry the whole résumé,
    and ``/fidelity`` must say so from the artifact, not from metadata.
    """
    from app.repositories.resume import ResumeRepository

    me = client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200, me.text
    user_id = me.json()["id"]

    repo = ResumeRepository()
    raw = _raw_text()
    format_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    baseline_sections = {
        "raw_text": raw,
        "bullets": [
            {"text": text, "evidenceRef": f"bullet-{i}"} for i, text in enumerate(BULLETS)
        ],
    }
    baseline = repo.create(
        user_id,
        baseline_sections,
        format_hash,
        label="Baseline",
        version=repo.next_version(user_id),
    )
    child_sections = {
        "raw_text": raw,
        "bullets": [
            {"text": text, "evidenceRef": f"bullet-{i}"} for i, text in enumerate(BULLETS)
        ],
    }
    child = repo.create(
        user_id,
        child_sections,
        format_hash,
        label="Tailored — Staff Software Engineer @ Canva",
        version=repo.next_version(user_id),
        parent_id=baseline["id"],
    )

    download = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert download.status_code == 200, download.text
    text = _rendered_text(download.content)
    missing_bullets = [b for b in BULLETS if _normalize(b) not in text]
    assert not missing_bullets, (
        f"{len(missing_bullets)} bullets missing from the downloaded résumé"
    )
    missing_headings = [h for h in REQUIRED_HEADINGS if _normalize(h) not in text]
    assert not missing_headings, f"sections missing from the download: {missing_headings}"
    missing_contact = [f for f in CONTACT_FIELDS if _normalize(f) not in text]
    assert not missing_contact, f"contact fields missing from the download: {missing_contact}"

    fidelity = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers)
    assert fidelity.status_code == 200, fidelity.text
    payload = fidelity.json()
    assert payload["contentComplete"] is True, (
        f"the fidelity report must confirm whole-document completeness: {payload}"
    )
    assert payload["missingContent"] == []
