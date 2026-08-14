"""Whole-document completeness of a produced résumé download (U2b CRITICAL).

:mod:`app.services.format_verification` answers ONE question — did each
tailoring rewrite land in the file? — and answers it well. Live production
proved that question is not enough on its own: a download reported
``changesRequested: 10 · changesApplied: 9 · changesDropped: 1`` while the file
the subscriber would have sent an employer was missing 8 of the résumé's 25
bullets, its entire contact block, its education, its skills and its
certifications, and repeated one page twice
(``uat/reports/evidence/agents-uplift/u2b/verify-final/CRITICAL-FINDING-content-loss.json``,
2026-08-14). Every tracked claim in that report was true. The document was
still unusable, and the report's silence about the other 32% read as assurance.

So the artifact is now measured against the WHOLE persisted résumé
(:mod:`app.services.resume_document`), not only against the edits:

* every section heading the résumé states,
* every bullet it holds — the tailored ones AND the untouched ones,
* every contact detail, which is the employer's only way back to the user.

Anything missing is NAMED. A caller with a content-complete alternative render
(``routers/resumes.py`` — the branded template) uses it instead of shipping the
loss, exactly as the DOCX/text/splice branches already do for a dropped
rewrite; where there is no alternative, the fidelity report degrades and says
what is gone rather than reporting only the part it happened to track.

An artifact that cannot be re-read reports ``text_extracted = False`` and makes
NO completeness claim in either direction — the same honesty rule the
per-change verifier follows.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.format_verification import (
    _APPLIED_COVERAGE,
    _coverage,
    _normalize,
    extract_artifact_text,
)
from app.services.resume_document import parse_resume_document

#: How much of a long item's wording must be present before it counts as
#: rendered. Shared with the per-change verifier, and for the same reason: a PDF
#: text layer can interleave unrelated spans into a line, so exact-substring
#: matching alone would report present content as missing.
_PRESENT_COVERAGE = _APPLIED_COVERAGE

#: How many characters of a missing item are quoted back to the user.
_EXCERPT_CHARS = 90


@dataclass(frozen=True)
class ResumeContent:
    """What the persisted résumé says the download must contain."""

    headings: tuple[str, ...] = ()
    bullets: tuple[str, ...] = ()
    contact: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.headings or self.bullets or self.contact)


@dataclass(frozen=True)
class CompletenessVerification:
    """What re-reading the produced artifact proved about the whole document."""

    text_extracted: bool
    missing_headings: tuple[str, ...] = ()
    missing_bullets: tuple[str, ...] = ()
    missing_contact: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Nothing the résumé persists is absent from the produced file."""
        return self.text_extracted and not (
            self.missing_headings or self.missing_bullets or self.missing_contact
        )

    @property
    def missing(self) -> tuple[str, ...]:
        """Every absent item, NAMED — never a bare count."""
        return (
            tuple(f"section “{item}”" for item in self.missing_headings)
            + tuple(f"contact detail “{item}”" for item in self.missing_contact)
            + tuple(f"bullet “{_excerpt(item)}”" for item in self.missing_bullets)
        )


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else f"{flat[:_EXCERPT_CHARS - 1]}…"


def build_resume_content(resume: dict[str, Any]) -> ResumeContent:
    """The completeness contract for one stored résumé record.

    Derived from the same document model the branded renderer draws, so the
    verifier can never be measuring a different résumé from the one the
    renderer was asked to produce.
    """
    document = parse_resume_document(resume)
    return ResumeContent(
        headings=document.headings,
        bullets=document.bullets,
        contact=document.contact,
    )


def _is_present(item: str, haystack: str) -> bool:
    normalized = _normalize(item)
    if not normalized:
        return True
    if normalized in haystack:
        return True
    return _coverage(item, haystack) >= _PRESENT_COVERAGE


def verify_completeness(
    data: bytes, media_type: str, content: ResumeContent
) -> CompletenessVerification:
    """Measure the produced artifact against the whole persisted résumé."""
    if content.is_empty:
        # Nothing is persisted to lose; claiming a check we did not run would be
        # its own fabrication, so this reports the artifact as read and complete
        # only when it can actually be read.
        text = extract_artifact_text(data, media_type)
        return CompletenessVerification(text_extracted=text is not None)
    text = extract_artifact_text(data, media_type)
    if text is None:
        return CompletenessVerification(text_extracted=False)
    haystack = _normalize(text)
    return CompletenessVerification(
        text_extracted=True,
        missing_headings=tuple(
            item for item in content.headings if not _is_present(item, haystack)
        ),
        missing_bullets=tuple(
            item for item in content.bullets if not _is_present(item, haystack)
        ),
        missing_contact=tuple(
            item for item in content.contact if not _is_present(item, haystack)
        ),
    )
