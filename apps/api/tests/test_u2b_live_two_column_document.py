"""U2b CRITICAL round 2 — the LIVE two-column résumé, byte-for-byte.

``test_u2b_render_completeness.py`` pins the whole-document contracts against a
*hand-written* line list. Review (2026-08-14) proved that list is not what
PyMuPDF actually produces for the live document: the real text layer merges the
two visual columns into single physical lines —

    ``VIKRAM                                     CAREER OBJECTIVE``
    ``DESHPANDE                            15+ year Senior Technical Leader …``
    ``     EDUCATION                         Distribution UI capabilities) …``

— so the surname fell into body prose (rendered name truncated to "VIKRAM"),
the ``EDUCATION`` banner was swallowed by a bullet buffer and then overwritten
by the 1:1 bullet substitution, and the phone number landed as the first item of
``WORK EXPERIENCE`` instead of ``CONTACT INFO``. The hand-written fixture could
not see any of it, so 51 green tests coexisted with a broken live render
(``uat/reports/evidence/agents-uplift/u2b/critical/REVIEWER-probe-*-OUTPUT-20260814.txt``).

This module therefore loads the REAL artifact text and the REAL persisted
bullets, checked in verbatim from that live evidence run, and asserts the same
contracts against them. It is the only test in the U2b set whose input is not
authored by the implementation's own author.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.routers.resumes import _branded_content
from app.services.format_verification import _normalize, extract_artifact_text
from app.services.resume_completeness import build_resume_content, verify_completeness
from app.services.resume_document import DocItem, DocSection, parse_resume_document
from app.services.resume_pdf import create_branded_resume_pdf
from app.services.resume_tailor import extract_bullets, render_tailored_raw_text

_FIXTURES = Path(__file__).parent / "fixtures" / "u2b"
#: PyMuPDF's own text layer for the live source résumé, copied verbatim from
#: ``uat/reports/evidence/agents-uplift/u2b/verify-final/baseline-original-text.txt``.
LIVE_RAW_TEXT = (_FIXTURES / "live-two-column-resume-text.txt").read_text()
#: The 25 bullets the live tailor run persisted for résumé
#: ``c12187d107bf994471844e09a`` (job ``c714727c916c40699e59662ba``).
LIVE_BULLETS = json.loads((_FIXTURES / "live-persisted-bullets.json").read_text())

FULL_NAME = "VIKRAM DESHPANDE"
CONTACT_EMAIL = "sarkar.vikram@gmail.com"
CONTACT_PHONE = "+61 433 224 556"
CONTACT_LOCATION = "Melbourne, VIC, Australia"
CONTACT_LINKEDIN = "linkedin.com/in/vikramd-profile"
CONTACT_GITHUB = "github.com/Victordtesla24"
SIDEBAR_HEADINGS = ("CONTACT INFO", "EDUCATION", "SKILLS", "CERTIFICATIONS")
BODY_HEADINGS = ("CAREER OBJECTIVE", "WORK EXPERIENCE")


def _source_resume() -> dict:
    """The stored parent record: the upload's own text plus its own bullets."""
    return {
        "id": "cfe7a0f27991821dc73f265cd",
        "label": "Vikram Deshpande — Senior Technical Program Manager",
        "sections": {
            "raw_text": LIVE_RAW_TEXT,
            "bullets": [{"text": text} for text in extract_bullets(LIVE_RAW_TEXT)],
        },
    }


def _tailored_resume() -> dict:
    """The stored tailored child, rebuilt exactly as the tailor pipeline does."""
    return {
        "id": "c12187d107bf994471844e09a",
        "label": "Tailored — Staff Software Engineer @ Canva",
        "parentId": "cfe7a0f27991821dc73f265cd",
        "sections": {
            "raw_text": render_tailored_raw_text(LIVE_RAW_TEXT, LIVE_BULLETS),
            "bullets": LIVE_BULLETS,
        },
    }


def _render(resume: dict) -> bytes:
    name, title, objective, sections, contact = _branded_content(resume)
    return create_branded_resume_pdf(
        name, title, objective, sections, None, contact=contact
    )


def _rendered_text(resume: dict) -> str:
    return _normalize(extract_artifact_text(_render(resume), "application/pdf") or "")


class TestTheLiveDocumentModel:
    """What the parser makes of the real two-column text layer."""

    def test_the_whole_name_survives_the_merged_first_lines(self) -> None:
        # "VIKRAM" and "DESHPANDE" arrive merged into two different columns'
        # lines; a résumé that goes out under half a name is a broken résumé.
        assert parse_resume_document(_source_resume()).name == FULL_NAME

    def test_every_sidebar_heading_survives(self) -> None:
        headings = parse_resume_document(_source_resume()).headings
        for heading in SIDEBAR_HEADINGS + BODY_HEADINGS:
            assert heading in headings, f"{heading} lost: {headings}"

    def test_contact_details_are_contact_details_not_work_experience(self) -> None:
        document = parse_resume_document(_source_resume())
        for field in (
            CONTACT_EMAIL,
            CONTACT_PHONE,
            CONTACT_LOCATION,
            CONTACT_LINKEDIN,
            CONTACT_GITHUB,
        ):
            assert field in document.contact, f"{field} is not a tracked contact detail"
        experience = [
            item.text
            for section in document.sections
            if section.heading == "WORK EXPERIENCE"
            for item in section.items
        ]
        assert CONTACT_PHONE not in experience

    def test_education_entries_sit_under_the_education_heading(self) -> None:
        document = parse_resume_document(_source_resume())
        education = [
            item.text
            for section in document.sections
            if section.heading == "EDUCATION"
            for item in section.items
        ]
        assert any("Master of Computer Science" in line for line in education)
        assert any("Monash University" in line for line in education)


class TestTheTailoredChild:
    """The record the subscriber actually downloads after a tailor run."""

    def test_the_tailored_child_keeps_every_heading(self) -> None:
        headings = parse_resume_document(_tailored_resume()).headings
        for heading in SIDEBAR_HEADINGS + BODY_HEADINGS:
            assert heading in headings, f"{heading} lost: {headings}"

    def test_every_persisted_bullet_reaches_the_document_model(self) -> None:
        document = parse_resume_document(_tailored_resume())
        rendered = {" ".join(text.lower().split()) for text in document.bullets}
        for bullet in LIVE_BULLETS:
            assert " ".join(bullet["text"].lower().split()) in rendered


class TestTheRenderedArtifact:
    """The produced PDF — measured, not assumed."""

    def test_the_render_carries_the_whole_name(self) -> None:
        assert _normalize(FULL_NAME) in _rendered_text(_tailored_resume())

    def test_the_render_carries_every_heading_and_contact_field(self) -> None:
        text = _rendered_text(_tailored_resume())
        for heading in SIDEBAR_HEADINGS + BODY_HEADINGS:
            assert _normalize(heading) in text, f"{heading} absent from the render"
        for field in (CONTACT_EMAIL, CONTACT_PHONE, CONTACT_LINKEDIN, CONTACT_GITHUB):
            assert _normalize(field) in text, f"{field} absent from the render"

    def test_completeness_reports_the_live_render_complete(self) -> None:
        resume = _tailored_resume()
        result = verify_completeness(
            _render(resume), "application/pdf", build_resume_content(resume)
        )
        assert result.missing == ()
        assert result.complete is True


class TestTheCompletenessContract:
    """The contract must be able to FAIL on the losses that actually happened."""

    def test_the_name_is_part_of_the_contract(self) -> None:
        content = build_resume_content(_tailored_resume())
        assert content.name == FULL_NAME

    def test_a_truncated_name_is_reported_missing(self) -> None:
        # Exactly the live defect: the render goes out as "VIKRAM".
        resume = _tailored_resume()
        content = build_resume_content(resume)
        name, title, objective, sections, contact = _branded_content(resume)
        truncated = create_branded_resume_pdf(
            name.split()[0], title, objective, sections, None, contact=contact
        )
        result = verify_completeness(truncated, "application/pdf", content)
        assert result.complete is False
        assert any(FULL_NAME in item for item in result.missing)

    def test_a_lost_education_heading_is_reported_missing(self) -> None:
        resume = _tailored_resume()
        content = build_resume_content(resume)
        name, title, objective, sections, contact = _branded_content(resume)
        stripped = [
            section for section in sections if section["heading"] != "EDUCATION"
        ]
        result = verify_completeness(
            create_branded_resume_pdf(
                name, title, objective, stripped, None, contact=contact
            ),
            "application/pdf",
            content,
        )
        assert result.complete is False
        assert any("EDUCATION" in item for item in result.missing)


class TestPositionalBulletSubstitution:
    """A persisted bullet must never be written into another job's slot."""

    def test_a_misaligned_one_to_one_map_is_refused(self) -> None:
        from app.services.resume_document import _substitute_bullets

        sections = [
            DocSection("JOB A", (DocItem("bullet", "Alpha work delivered."),)),
            DocSection("JOB B", (DocItem("bullet", "Beta work delivered."),)),
        ]
        # Same two bullets, opposite order: a positional zip would move Beta's
        # bullet under JOB A and Alpha's under JOB B.
        out = _substitute_bullets(
            sections, ["Beta work delivered.", "Alpha work delivered."]
        )
        assert out[0].bullets == ("Alpha work delivered.",)
        assert out[1].bullets == ("Beta work delivered.",)
        assert len(out) == 2

    def test_an_aligned_rewrite_still_lands_in_its_own_slot(self) -> None:
        from app.services.resume_document import _substitute_bullets

        sections = [
            DocSection("JOB A", (DocItem("bullet", "Alpha work delivered."),)),
            DocSection("JOB B", (DocItem("bullet", "Beta work delivered."),)),
        ]
        out = _substitute_bullets(
            sections, ["Alpha work delivered, with 30% lift.", "Beta work delivered."]
        )
        assert out[0].bullets == ("Alpha work delivered, with 30% lift.",)
        assert out[1].bullets == ("Beta work delivered.",)
