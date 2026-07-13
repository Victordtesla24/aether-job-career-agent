"""GAP-P4-044 — bullet extraction reconstructs complete sentences.

The bundled resumes are two-column, so PyMuPDF's flat text stream breaks every
wrapped work bullet across several lines and interleaves job headers between
bullet groups. The legacy line-based extractor captured only each bullet's
truncated first line — a fragment the tailoring LLM then "completed" into
incoherent, duplicated output.

The fix is at the root: :func:`extract_bullets` (the shared utility every
ingestion path uses — base bootstrap, ``POST /resumes``, ``POST
/resumes/upload``) now rejoins each bullet from its marker line through its
wrapped continuation lines. It must produce complete bullets for BOTH bundled
resumes, not just the main one. The positional :func:`extract_pdf_bullets`
stays the higher-fidelity path when the base resume's coral geometry is present,
and falls back to the same text reconstruction otherwise.
"""
from __future__ import annotations

import re

import fitz

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_tailor import extract_bullets

# The two bundled resumes, both built in the same two-column visual format.
_MAIN_PDF = get_base_resume_path()
_BA_PDF = _MAIN_PDF.parent / "Vik_Resume_BA_Final.pdf"

_TERMINAL = (".", "!", "?")
#: A "Month YYYY - Month YYYY | City" (or "YYYY - YYYY | City") run — the
#: signature of a job header that a run-away bullet would swallow.
_HEADER_RUNON = re.compile(
    r"(?:19|20)\d{2}\s*[-–—]\s*(?:Present|[A-Z][a-z]+\s+)?(?:19|20)?\d{2,4}\s*\|"
)


def _flat_text(pdf_path) -> str:
    doc = fitz.open(pdf_path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _fragments(bullets: list[str]) -> list[str]:
    """Work bullets ending mid-sentence — i.e. truncated wrapped bullets.

    Skills / certification lines legitimately lack terminal punctuation, so a
    bullet is only counted as a fragment if it *starts* like a work bullet
    ("Lead-in:") yet ends without terminal punctuation.
    """
    return [
        b
        for b in bullets
        if ":" in b[:60] and not b.rstrip().rstrip(")\"']").endswith(_TERMINAL)
    ]


class TestFlatTextReconstruction:
    """The shared flat-text utility used by every ingestion path."""

    def test_main_resume_bullets_are_complete(self) -> None:
        bullets = extract_bullets(_flat_text(_MAIN_PDF))
        assert bullets, "no bullets extracted from the main resume"
        assert not _fragments(bullets), f"fragmented work bullets: {_fragments(bullets)}"

    def test_ba_resume_bullets_are_complete(self) -> None:
        """The BA variant is ingested via ``POST /resumes`` from this exact flat
        text, so it must reconstruct just as cleanly as the main resume."""
        bullets = extract_bullets(_flat_text(_BA_PDF))
        assert bullets, "no bullets extracted from the BA resume"
        assert not _fragments(bullets), f"fragmented work bullets: {_fragments(bullets)}"

    def test_wrapped_bullet_is_rejoined_whole(self) -> None:
        """A four-line wrapped bullet must come back as one complete sentence,
        never truncated to its first line (the GAP-P4-044 defect)."""
        for pdf in (_MAIN_PDF, _BA_PDF):
            bullets = extract_bullets(_flat_text(pdf))
            agile = [b for b in bullets if b.startswith("Agile Delivery Leadership")]
            assert len(agile) == 1, f"{pdf.name}: expected one Agile bullet, got {agile}"
            # Complete: keeps both the lead-in AND the final wrapped clause.
            assert agile[0].rstrip().endswith("executive status reporting.")
            # The truncated first-line fragment must not survive on its own.
            assert not any(
                b.rstrip().endswith("Agile Kookaburras squad") for b in bullets
            )

    def test_last_bullet_of_group_does_not_swallow_next_job_header(self) -> None:
        """A bullet without terminal punctuation (e.g. a certification) must not
        run on through the following job's title / company / date line."""
        for pdf in (_MAIN_PDF, _BA_PDF):
            bullets = extract_bullets(_flat_text(pdf))
            runons = [b for b in bullets if _HEADER_RUNON.search(b)]
            assert not runons, f"{pdf.name}: bullet swallowed a job header: {runons}"


class TestPositionalExtraction:
    """The base-resume positional path, with a text fallback for other formats."""

    def test_main_resume_positional_bullets_are_complete(self) -> None:
        from app.services.resume_pdf import extract_pdf_bullets

        bullets = extract_pdf_bullets(_MAIN_PDF)
        assert bullets, "no positional bullets from the main resume"
        assert not _fragments(bullets)

    def test_ba_resume_falls_back_instead_of_returning_zero(self) -> None:
        """The BA resume has no coral base geometry, so positional detection
        finds nothing; the fallback must still return its complete bullets
        rather than an empty list."""
        from app.services.resume_pdf import _detect_blocks, extract_pdf_bullets

        doc = fitz.open(_BA_PDF)
        try:
            positional = sum(len(_detect_blocks(doc[p])) for p in range(len(doc)))
        finally:
            doc.close()
        assert positional == 0, "BA resume unexpectedly matched base geometry"

        bullets = extract_pdf_bullets(_BA_PDF)
        assert bullets, "fallback returned no bullets for the BA resume"
        assert not _fragments(bullets)
