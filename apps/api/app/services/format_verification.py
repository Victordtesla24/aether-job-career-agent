"""Post-render verification of a tailored résumé artifact (U2b truth round).

R-F4 forbids silent format claims. The first U2b round honoured that for the
paths it added (DOCX/text native renders count what they replaced) but left the
pre-existing PDF in-place splice describing itself from *metadata* — a bundled
formatHash match plus a content type — and asserting completeness it never
checked. Live production proved that claim false: a tailored résumé reported
``pdf-in-place-splice · high confidence · "every other element is identical to
the source document"`` while the downloaded PDF still carried the ORIGINAL text
of one of its four reworded bullets (the rewrite targeted a left-rail line, and
``resume_pdf._detect_blocks`` only edits right-column work bullets). Evidence:
``uat/reports/evidence/agents-uplift/u2b/verify/`` (2026-08-14).

So no caller may *assert* fidelity any more. This module re-reads the artifact
that was just produced and answers one question per requested change: is the
reworded text actually IN the file the user downloads?

Why coverage instead of a plain substring test
----------------------------------------------
A spliced PDF draws a bullet's bold lead-in and its grey body through two
different PyMuPDF ``TextWriter``s, so the extracted text stream can interleave
unrelated page content between them: a genuinely applied rewrite is then not a
contiguous substring of the extracted text. Measured on the real production
artifact above, exact-substring matching reported 2 of 3 applied changes as
missing — it would have replaced one false claim with another. Word-shingle
coverage separates the cases cleanly on that same file:

===========================  ==============  ================
change                       after-coverage  truth
===========================  ==============  ================
bullet-0 (left rail)         0.087           NOT applied
bullet-4 (bold lead-in)      0.917           applied
bullet-8 / bullet-11         1.000           applied
===========================  ==============  ================

Hence :data:`_APPLIED_COVERAGE` = 0.85, comfortably between the two clusters.
A file that cannot be re-read at all reports ``text_extracted = False`` —
honestly "unverified", never "everything was dropped".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

#: Words per shingle. Long enough that ordinary résumé phrasing ("and the
#: team") cannot match by chance, short enough that a two-writer split costs
#: only a handful of shingles.
_SHINGLE = 6

#: Fraction of a rewrite's shingles that must be present in the produced
#: artifact for it to count as genuinely applied (calibrated above).
_APPLIED_COVERAGE = 0.85

#: How many characters of a dropped rewrite are quoted back to the user.
_EXCERPT_CHARS = 160

#: Unicode punctuation folded before matching, so curly quotes / en-dashes in
#: the stored bullet don't defeat a match against the rendered glyphs. Mirrors
#: :mod:`app.services.resume_pdf`'s own fold, which the renderer matches with.
_PUNCT_FOLD = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', " ": " ",
})

_PDF_MEDIA = "application/pdf"
_DOCX_MEDIA = "wordprocessingml.document"
_TEXT_MEDIA = ("text/plain", "text/markdown")


def _normalize(text: str) -> str:
    """Lower-case, punctuation-folded, whitespace-collapsed comparison form."""
    return " ".join(text.translate(_PUNCT_FOLD).lower().split())


def extract_artifact_text(data: bytes, media_type: str) -> str | None:
    """The text layer of a produced download, or ``None`` if it cannot be read.

    ``None`` is the honest "cannot verify" answer — every failure mode (an
    unreadable package, an unknown media type, bytes that are not text at all)
    lands here instead of being mistaken for an empty document, which would
    make every change look dropped.
    """
    lowered = str(media_type or "").lower()
    try:
        if lowered.startswith(_PDF_MEDIA):
            import fitz

            doc = fitz.open(stream=data, filetype="pdf")
            try:
                return "\n".join(page.get_text() for page in doc)
            finally:
                doc.close()
        if _DOCX_MEDIA in lowered:
            from app.services.resume_docx import extract_docx_lines

            return "\n".join(extract_docx_lines(data))
        if any(lowered.startswith(prefix) for prefix in _TEXT_MEDIA):
            return data.decode("utf-8", errors="strict")
    except Exception:  # noqa: BLE001 — every reader raises its own error family
        return None
    return None


def _coverage(text: str, haystack: str) -> float:
    """Fraction of ``text``'s word shingles present in ``haystack`` (0.0–1.0)."""
    tokens = _normalize(text).split()
    if not tokens:
        return 0.0
    if len(tokens) <= _SHINGLE:
        return 1.0 if " ".join(tokens) in haystack else 0.0
    shingles = [
        " ".join(tokens[i:i + _SHINGLE]) for i in range(len(tokens) - _SHINGLE + 1)
    ]
    return sum(1 for shingle in shingles if shingle in haystack) / len(shingles)


@dataclass(frozen=True)
class ChangeOutcome:
    """One requested rewrite, measured against the artifact that was produced."""

    before: str
    after: str
    coverage: float
    applied: bool
    #: True when the ORIGINAL wording is still in the file — the signature of a
    #: rewrite the renderer skipped rather than one it mangled.
    original_remains: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "before": self.before[:_EXCERPT_CHARS],
            "after": self.after[:_EXCERPT_CHARS],
            "coverage": round(self.coverage, 3),
            "originalRemains": self.original_remains,
        }


@dataclass(frozen=True)
class RenderVerification:
    """What re-reading the produced artifact proved about the requested changes."""

    requested: int
    text_extracted: bool
    outcomes: tuple[ChangeOutcome, ...]

    @property
    def applied_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.applied)

    @property
    def dropped_count(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.applied)

    @property
    def dropped(self) -> tuple[ChangeOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if not outcome.applied)

    @property
    def complete(self) -> bool:
        """Every requested change was verified present in the artifact."""
        return self.text_extracted and self.dropped_count == 0


def verify_changes(
    data: bytes, media_type: str, changes: Sequence[tuple[str, str]]
) -> RenderVerification:
    """Check each ``(before, after)`` rewrite against the produced ``data``.

    The result is a measurement of the artifact itself — not the renderer's own
    account of what it believes it replaced — which is the whole point: the
    renderer's bookkeeping cannot notice a bullet it never looked at.
    """
    text = extract_artifact_text(data, media_type)
    if text is None:
        return RenderVerification(requested=len(changes), text_extracted=False, outcomes=())
    haystack = _normalize(text)
    outcomes: list[ChangeOutcome] = []
    for before, after in changes:
        coverage = _coverage(after, haystack)
        outcomes.append(
            ChangeOutcome(
                before=before,
                after=after,
                coverage=coverage,
                applied=coverage >= _APPLIED_COVERAGE,
                original_remains=_coverage(before, haystack) >= _APPLIED_COVERAGE,
            )
        )
    return RenderVerification(
        requested=len(changes), text_extracted=True, outcomes=tuple(outcomes)
    )
