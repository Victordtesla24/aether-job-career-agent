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

* the person's own name, in full,
* every section heading the résumé states,
* every bullet it holds — the tailored ones AND the untouched ones,
* every line of prose under those headings (an education entry is not a
  bullet, and the live document lost an entire second degree),
* every contact detail, which is the employer's only way back to the user.

And for a TAILORED version that whole résumé is the PARENT's, with only the
approved rewrites mapped in (:func:`baseline_record`) — never the child's own
parse, which by then may already have lost the content being checked for.

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
from typing import Any, Sequence

from app.services.format_verification import (
    _APPLIED_COVERAGE,
    _coverage,
    _normalize,
    extract_artifact_text,
)
from app.services.resume_document import (
    _persisted_bullets,
    merge_persisted_bullets,
    parse_resume_document,
)

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
    #: Every line of prose the résumé states under a heading — an education
    #: entry, a job title, a company, a date, a summary paragraph. Added in the
    #: U2b round-3 review: the live document lost an ENTIRE second degree
    #: ("Bachelor of Engineering / University of Melbourne / 2007"), which was
    #: never a bullet, so no field of this contract could name it.
    lines: tuple[str, ...] = ()
    #: The person's own name. Added in the U2b round-2 review: the live render
    #: went out as "VIKRAM" with the surname parsed into body prose, and no
    #: field of this contract could ever have flagged it, so a name regression
    #: was structurally invisible to verification.
    name: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.headings or self.bullets or self.contact or self.lines)


@dataclass(frozen=True)
class CompletenessVerification:
    """What re-reading the produced artifact proved about the whole document."""

    text_extracted: bool
    missing_headings: tuple[str, ...] = ()
    missing_bullets: tuple[str, ...] = ()
    missing_contact: tuple[str, ...] = ()
    #: Section prose the produced file does not carry (the lost second degree).
    missing_lines: tuple[str, ...] = ()
    #: The persisted name, when the produced file does not carry all of it.
    missing_name: str = ""

    @property
    def complete(self) -> bool:
        """Nothing the résumé persists is absent from the produced file."""
        return self.text_extracted and not (
            self.missing_headings
            or self.missing_bullets
            or self.missing_contact
            or self.missing_lines
            or self.missing_name
        )

    @property
    def missing(self) -> tuple[str, ...]:
        """Every absent item, NAMED — never a bare count."""
        return (
            ((f"name “{self.missing_name}”",) if self.missing_name else ())
            + tuple(f"section “{item}”" for item in self.missing_headings)
            + tuple(f"contact detail “{item}”" for item in self.missing_contact)
            + tuple(f"bullet “{_excerpt(item)}”" for item in self.missing_bullets)
            + tuple(f"line “{_excerpt(item)}”" for item in self.missing_lines)
        )


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _EXCERPT_CHARS else f"{flat[:_EXCERPT_CHARS - 1]}…"


def baseline_bullets(
    resume: dict[str, Any], parent: dict[str, Any]
) -> list[str]:
    """Every bullet a tailored download owes the user, in the résumé's order.

    The PARENT's full inventory, with each slot the tailoring actually rewrote
    holding the approved AFTER text and every untouched original held verbatim —
    :func:`~app.services.resume_document.merge_persisted_bullets`, which routes
    the before → after mapping through the same slot-claiming pass the renderer
    and ``rebuild_raw_text`` use.

    Until round 5 this was simply the CHILD's persisted list. That list is what
    one tailoring run produced, not what the résumé holds: a bullet nobody
    selected for rewrite could be absent from it, and then it was absent from
    the ground truth too — invisible to :func:`verify_completeness`, to
    ``GET /resumes/{id}/fidelity``, to the download's verification header, and
    to the repair census that decides which stored versions are damaged.
    """
    return merge_persisted_bullets(
        _persisted_bullets(parent.get("sections") or {}),
        _persisted_bullets(resume.get("sections") or {}),
    )


def baseline_record(
    resume: dict[str, Any], parent: dict[str, Any]
) -> dict[str, Any]:
    """The PARENT's own document with THIS version's rewrites mapped into it.

    The parent supplies every heading, every line, every contact detail and
    every bullet — including the ones nobody asked to rewrite (see
    :func:`baseline_bullets`). The child supplies only the tailored bullet
    texts, which :func:`~app.services.resume_document._substitute_bullets` then
    puts back into the slots they rewrote, by content. The result is the ground
    truth a tailored download owes the user: their résumé, plus the edits they
    approved — never less of their résumé than they uploaded.
    """
    payload = dict(parent.get("sections") or {})
    payload["bullets"] = [
        {"text": text} for text in baseline_bullets(resume, parent)
    ]
    return {**parent, "sections": payload}


def build_applied_content(
    parent: dict[str, Any], applied_changes: Sequence[tuple[str, str]]
) -> ResumeContent:
    """The completeness contract for an IN-PLACE render (MODELS-LIVE R-FMT §2/§3).

    An in-place splice / native rewrite starts from the user's WHOLE original
    document (the ``parent``) and edits only the reworded slots it could place.
    A rewrite it could NOT place keeps the parent's original wording — which is
    still the user's own résumé content — so the render is content-complete as
    long as it still carries the whole original document with the placed rewrites
    substituted. Measuring such a render against the fully-tailored target
    (:func:`build_resume_content`) would flag the ORIGINAL wording of an
    unplaceable rewrite as "missing content" and force the whole layout to be
    dropped to the branded template over a single out-of-scope region — the
    exact all-or-nothing failure this slice removes.

    So the contract is the parent's own document with ONLY the rewrites that
    ACTUALLY landed mapped in (``applied_changes`` — the ``(before, after)``
    pairs the post-render verifier confirmed present). A genuine content loss —
    a dropped heading, a vanished contact line, an eaten untracked bullet — is
    still caught, because it is neither in the parent's document as-is nor a
    placed rewrite, and still routes to the content-complete branded render.
    """
    from app.services.format_verification import _normalize as _fold

    applied = {_fold(before): after for before, after in applied_changes if before}
    document = parse_resume_document(parent)

    def _sub(text: str) -> str:
        return applied.get(_fold(text), text)

    return ResumeContent(
        headings=document.headings,
        bullets=tuple(_sub(bullet) for bullet in document.bullets),
        contact=document.contact,
        lines=tuple(_sub(line) for line in document.lines),
        name=document.name,
    )


def build_resume_content(
    resume: dict[str, Any], parent: dict[str, Any] | None = None
) -> ResumeContent:
    """The completeness contract for one stored résumé record.

    Derived from the same document model the branded renderer draws, so the
    verifier can never be measuring a different résumé from the one the
    renderer was asked to produce.

    For a TAILORED version the contract is built from its ``parent`` — the
    baseline the user uploaded — with only the tailoring rewrites mapped
    before → after. Measuring a tailored child against its own parse is what
    made the live content loss invisible: the child's ``raw_text`` had already
    lost two skills bullets and an entire academic degree, so its own parse no
    longer contained them and there was nothing left to report missing. A
    verifier that certifies a lossy record against itself certifies nothing
    (U2b round-2 review, 2026-08-14). A baseline résumé has no parent and is
    measured against itself, which for it IS the ground truth.
    """
    source = resume if parent is None else baseline_record(resume, parent)
    document = parse_resume_document(source)
    return ResumeContent(
        headings=document.headings,
        bullets=document.bullets,
        contact=document.contact,
        lines=document.lines,
        name=document.name,
    )


def _is_present(item: str, haystack: str) -> bool:
    normalized = _normalize(item)
    if not normalized:
        return True
    if normalized in haystack:
        return True
    return _coverage(item, haystack) >= _PRESENT_COVERAGE


def _name_is_present(name: str, haystack: str) -> bool:
    """True when EVERY part of the person's name is somewhere in the artifact.

    Checked word by word rather than as one string: a format-preserving
    download keeps the source layout, where a two-column header prints the
    given name and the surname on separate lines, so requiring them adjacent
    would report a correct file as broken. A dropped surname — the live U2b
    defect — still fails, because the word is simply not there.
    """
    parts = [_normalize(part) for part in name.split()]
    return all(not part or part in haystack for part in parts)


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
        missing_name=(
            "" if _name_is_present(content.name, haystack) else content.name
        ),
        missing_headings=tuple(
            item for item in content.headings if not _is_present(item, haystack)
        ),
        missing_bullets=tuple(
            item for item in content.bullets if not _is_present(item, haystack)
        ),
        missing_contact=tuple(
            item for item in content.contact if not _is_present(item, haystack)
        ),
        missing_lines=tuple(
            item for item in content.lines if not _is_present(item, haystack)
        ),
    )
