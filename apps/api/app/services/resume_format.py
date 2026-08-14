"""Honest format-fidelity reporting for résumé downloads (U2b / R-F2 + R-F4).

ONE decision table, consumed by both the endpoint that renders a résumé
(``GET /resumes/{id}/download``) and the endpoint that describes it (``GET
/resumes``), so the claim the UI makes can never drift from what the download
actually does — the exact failure MON-011 recorded, where the Resume Studio
"Format Integrity Check" told every paying user their typography, spacing,
columns and margins were preserved for a document that was in fact re-flowed
into Aether's generic branded template.

Three honest states, end to end:

``preserved = True``   the download genuinely reproduces the user's own
                       document (their stored bytes, or a native in-document
                       edit of them) AND nothing we verified contradicts that;
``preserved = False``  the download is not a faithful rendering of this
                       version — a re-render in Aether's template, or an
                       in-document edit that re-reading the produced file
                       proved incomplete. Said plainly, with the reason;
``preserved = None``   we genuinely cannot tell (the source version could not
                       be resolved). Reported as unknown rather than guessed;
                       the Resume Studio panel already renders this third state
                       as "status is unknown" instead of an affirmative claim.

The flag is DERIVED, never carried: :func:`describe_fidelity` states what the
mechanism can do, and :func:`verified_fidelity` re-states it from what re-reading
the produced artifact actually proved. Live production shipped the alternative —
``formatPreserved: true`` next to ``changesDropped: 1`` in the same payload
(``uat/reports/evidence/agents-uplift/u2b/verify-truthround/``, 2026-08-14) —
and every consumer that branches on the boolean repeated the affirmative claim
over a report that contradicted it.

Every state also carries a ``formatFidelity`` report — ``{method, confidence,
note}`` — because a bare boolean cannot say WHY, and R-F4 forbids silent
claims: "low confidence ⇒ faithful re-render + EXPLICIT fidelity report".
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.services.resume_docx import DOCX_CONTENT_TYPE

#: Content types whose text is trivially preservable end to end (R-F4).
_TEXT_CONTENT_TYPES = ("text/plain", "text/markdown")
#: The stored upload MIME for a PDF, matched case-insensitively.
_PDF_CONTENT_TYPE = "application/pdf"

METHOD_ORIGINAL_BYTES = "original-bytes"
METHOD_PDF_SPLICE = "pdf-in-place-splice"
METHOD_DOCX_NATIVE = "docx-native"
METHOD_TEXT_NATIVE = "text-native"
METHOD_REFLOW = "reflow-template"
#: A branded re-render the user EXPLICITLY asked for (``?branded=true``), never
#: a silent fallback: an honest "re-style my résumé in the Aether template"
#: action, distinct from ``reflow-template`` (the safety fallback for an
#: unreadable / content-lost render) so an operator can tell a chosen restyle
#: from a forced one (MODELS-LIVE R-FMT binding scope item 5).
METHOD_BRANDED_OPTIN = "branded-optin"
METHOD_UNKNOWN = "unknown"


#: How a fidelity claim was established.
VERIFICATION_POST_RENDER = "post-render-text-extraction"
VERIFICATION_BYTE_IDENTITY = "byte-identity"

#: Confidence vocabulary. ``high``/``low`` describe the MECHANISM (does the
#: download reproduce the user's own document at all); ``verified``-derived
#: states describe what re-reading the produced file actually proved.
CONFIDENCE_PENDING = "unverified"
CONFIDENCE_PARTIAL = "partial"

#: The surface a rewrite has to land on, per method — used in the honest note.
_SURFACE = {
    METHOD_PDF_SPLICE: "PDF layout",
    METHOD_DOCX_NATIVE: "Word document",
    METHOD_TEXT_NATIVE: "text file",
    METHOD_REFLOW: "rendered document",
}


@dataclass(frozen=True)
class FormatFidelity:
    """What a download of this résumé version will really do to its format.

    ``verification`` and the change counts are present only once the claim has
    been checked against a produced artifact (the download / fidelity
    endpoints). A listing cannot re-render every version, so its rows carry the
    MECHANISM and say the per-change check is still pending — never a
    completeness claim nobody verified (U2b truth round).
    """

    method: str
    confidence: str
    note: str
    preserved: bool | None
    verification: str | None = None
    changes_requested: int | None = None
    changes_applied: int | None = None
    changes_dropped: int | None = None
    dropped_changes: tuple[dict[str, Any], ...] = ()
    #: Whether the WHOLE persisted résumé reached the produced file — headings,
    #: every bullet (tracked or not) and the contact details. ``None`` when no
    #: completeness measurement was made, never a guess (U2b CRITICAL round).
    content_complete: bool | None = None
    missing_content: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "method": self.method,
            "confidence": self.confidence,
            "note": self.note,
            "contentComplete": self.content_complete,
            "missingContent": list(self.missing_content),
        }
        if self.verification is not None:
            report.update({
                "verification": self.verification,
                "changesRequested": self.changes_requested,
                "changesApplied": self.changes_applied,
                "changesDropped": self.changes_dropped,
                "droppedChanges": list(self.dropped_changes),
            })
        return report


def is_docx_content_type(content_type: str | None) -> bool:
    return bool(content_type) and DOCX_CONTENT_TYPE in str(content_type)


def is_text_content_type(content_type: str | None) -> bool:
    lowered = str(content_type or "").lower()
    return any(lowered.startswith(prefix) for prefix in _TEXT_CONTENT_TYPES)


def is_pdf_content_type(content_type: str | None) -> bool:
    return str(content_type or "").lower().startswith(_PDF_CONTENT_TYPE)


def describe_fidelity(
    *,
    bundled_match: bool,
    has_original: bool,
    content_type: str | None,
    is_tailored: bool,
    source_resolved: bool = True,
) -> FormatFidelity:
    """The fidelity of ``GET /resumes/{id}/download`` for one résumé version.

    ``bundled_match`` — the version's ``formatHash`` matches a bundled asset on
    disk (the seeded operator résumés), which is the condition the download
    endpoint's own ``resolve_original_pdf`` branches on.
    ``has_original`` / ``content_type`` — describe the stored upload the render
    derives from (a tailored child derives from its PARENT's stored bytes).
    ``source_resolved`` — ``False`` when a tailored version names a parent we
    cannot read, i.e. the source document is genuinely unknown.
    """
    if not source_resolved:
        return FormatFidelity(
            method=METHOD_UNKNOWN,
            confidence="unknown",
            note=(
                "This version's source document could not be resolved, so we "
                "cannot say whether a download will match your original layout."
            ),
            preserved=None,
        )
    if bundled_match:
        if is_tailored:
            return FormatFidelity(
                method=METHOD_PDF_SPLICE,
                confidence="high",
                note=(
                    "Your original PDF is edited in place — reworded bullets are "
                    "redrawn on the page and every other element is the source "
                    "document's own."
                ),
                preserved=True,
            )
        return FormatFidelity(
            method=METHOD_ORIGINAL_BYTES,
            confidence="high",
            note="Downloads return your original document's own bytes, unmodified.",
            preserved=True,
        )
    if has_original and is_pdf_content_type(content_type):
        # A genuine user PDF upload (its ``formatHash`` is a digest of the user's
        # OWN bytes, so ``resolve_original_pdf`` returns ``None`` and the download
        # splices the stored ``originalFile`` bytes directly). MODELS-LIVE R-FMT
        # binding scope item 5: this is preserved, NOT re-flowed — a base returns
        # its exact bytes; a tailored child is edited in place. Before this slice
        # the router never routed the stored PDF bytes into the splice at all, so
        # every real PDF upload dropped to the branded template (finding ML-RFMT
        # PDF splice gap).
        if is_tailored:
            return FormatFidelity(
                method=METHOD_PDF_SPLICE,
                confidence="high",
                note=(
                    "Your original PDF is edited in place — reworded bullets are "
                    "redrawn on the page and every other element is the source "
                    "document's own. A rewrite the layout cannot place keeps its "
                    "original wording and is listed as not applied, so your PDF's "
                    "layout is preserved rather than dropped to a re-render."
                ),
                preserved=True,
            )
        return FormatFidelity(
            method=METHOD_ORIGINAL_BYTES,
            confidence="high",
            note="Downloads return your original PDF's own bytes, unmodified.",
            preserved=True,
        )
    if has_original and is_docx_content_type(content_type):
        return FormatFidelity(
            method=METHOD_DOCX_NATIVE,
            confidence="high",
            note=(
                "Preserved via native document editing — your original Word "
                "structure, fonts and styles are kept exactly, and only the "
                "reworded bullets are rewritten. If a reworded line cannot be "
                "located in the document, Aether re-renders in its own template "
                "rather than shipping a partially tailored file."
            ),
            preserved=True,
        )
    if has_original and is_text_content_type(content_type):
        return FormatFidelity(
            method=METHOD_TEXT_NATIVE,
            confidence="high",
            note=(
                "Plain-text résumé — downloads return your original file with "
                "only the reworded lines changed."
            ),
            preserved=True,
        )
    if has_original:
        return FormatFidelity(
            method=METHOD_REFLOW,
            confidence="low",
            note=(
                "Rendered in the Aether template; original layout preservation "
                "is not yet available for this upload type. Your uploaded file "
                "itself is kept unchanged and can be downloaded from Settings."
            ),
            preserved=False,
        )
    return FormatFidelity(
        method=METHOD_REFLOW,
        confidence="low",
        note=(
            "No original document is stored for this version (it was typed or "
            "ingested as text, or uploaded before Aether kept original files), "
            "so downloads are rendered in the Aether template. Re-upload your "
            "résumé (PDF, or a .docx for byte-identical preservation) to enable "
            "format-preserving tailoring."
        ),
        preserved=False,
    )


def pending_fidelity(base: FormatFidelity) -> FormatFidelity:
    """The honest listing state for a tailored version: mechanism, not outcome.

    ``GET /resumes`` describes many versions at once and cannot re-render each
    one, so it must not repeat the completeness claim that live production
    falsified ("every other element is identical to the source document" for a
    splice that had silently skipped a rewrite). It states the mechanism and
    points at the per-document verification instead.
    """
    return FormatFidelity(
        method=base.method,
        confidence=CONFIDENCE_PENDING,
        note=(
            f"{base.note} Each reworded bullet is verified against the file "
            "itself when this version is rendered — open it to see the "
            "verified report."
        ),
        preserved=base.preserved,
    )


def native_fallback_fidelity(
    *,
    unreadable: bool = False,
    stored_original: bool = True,
    content_incomplete: bool = False,
) -> FormatFidelity:
    """The honest report when an in-document rewrite could not complete.

    The user's own document IS the preferred surface, but a rewrite Aether
    cannot place in it (or a stored file that no longer opens) must not ship as
    a half-tailored copy of their résumé. The download falls back to the
    branded template, which is built from the version's own tailored text — and
    says exactly that, rather than reusing the generic "not yet available for
    this upload type" copy, which would be false for these versions.

    The note stops at what is known HERE: the branded render is verified like
    every other artifact (:func:`verified_fidelity` re-reads it and appends the
    real counts), so this text must not pre-claim completeness on its behalf.
    ``stored_original`` is ``False`` when the version is backed by a bundled
    asset rather than a file the user uploaded, so the "download your original
    from Settings" pointer is dropped instead of promising a file that may not
    exist.
    """
    if unreadable:
        reason = (
            "Your stored original file could not be opened, so this download is "
            "rendered in the Aether template"
        )
    elif content_incomplete:
        # U2b CRITICAL: an in-document render that re-reading proved had lost
        # part of the user's own résumé (a section, a bullet, their contact
        # details) is worse than an honest re-format, so it is never shipped.
        reason = (
            "Part of your résumé was missing from the tailored copy of your own "
            "document, so this download is rendered in the Aether template"
        )
    else:
        reason = (
            "A reworded line could not be located in your original document, "
            "so this download is rendered in the Aether template"
        )
    pointer = (
        " The file you uploaded is unchanged and can still be downloaded from Settings."
        if stored_original
        else ""
    )
    return FormatFidelity(
        method=METHOD_REFLOW,
        confidence="low",
        note=(
            f"{reason} from this version's own tailored text, rather than a "
            f"partially tailored copy of your own document.{pointer}"
        ),
        preserved=False,
    )


def branded_optin_fidelity() -> FormatFidelity:
    """The honest report for a branded render the user EXPLICITLY requested.

    MODELS-LIVE R-FMT binding scope item 5: the branded template is a user
    choice ("re-style my résumé in the Aether template", ``?branded=true``), not
    a silent fallback. It is a genuine re-format — a fresh single-column design,
    not the uploaded document's own layout — so it is reported ``preserved:
    False`` and points the user back at the format-preserving download, never
    dressed up as preservation it did not do. Completeness is still verified by
    :func:`verified_fidelity` (this is the LAST render, so a loss here is
    reported, not routed around).
    """
    return FormatFidelity(
        method=METHOD_BRANDED_OPTIN,
        confidence="high",
        note=(
            "Re-rendered in the Aether template at your request. This is a fresh "
            "single-column design, not your uploaded document's own layout — "
            "download without the branded option (or use “Download original”) to "
            "keep your résumé's own format."
        ),
        preserved=False,
    )


#: How many missing items the honest note names before it summarises the rest.
_NAMED_MISSING = 3


def _with_completeness(report: FormatFidelity, completeness: Any) -> FormatFidelity:
    """Re-state ``report`` from what the WHOLE-document check proved (U2b CRITICAL).

    The per-change verifier can only see the rewrites it asked for. Live
    production shipped a download whose every tracked claim was true and which
    was still missing a third of the user's own résumé — contact block,
    education, skills, certifications and 8 untracked bullets — while the report
    beside it read as an assurance
    (``uat/reports/evidence/agents-uplift/u2b/verify-final/``, 2026-08-14).

    So a render that lost persisted content is not a faithful rendering of the
    version, whatever the mechanism could do in principle and however many
    tracked edits landed: ``preserved`` becomes ``False``, confidence drops to
    ``partial``, and the note NAMES what is gone. A file that could not be
    re-read makes no completeness claim in either direction.
    """
    if completeness is None:
        return report
    if not getattr(completeness, "text_extracted", False):
        return report
    missing = tuple(completeness.missing)
    if not missing:
        return replace(report, content_complete=True, missing_content=())
    named = ", ".join(missing[:_NAMED_MISSING])
    remainder = len(missing) - _NAMED_MISSING
    if remainder > 0:
        named += f", and {remainder} more item{'s' if remainder != 1 else ''}"
    return replace(
        report,
        confidence=CONFIDENCE_PARTIAL,
        preserved=False,
        note=(
            f"{report.note} Part of your résumé is missing from the file this "
            f"download produces — {named}. The complete text is on this version "
            "in Resume Studio; do not send this file until it is fixed."
        ),
        content_complete=False,
        missing_content=missing,
    )


def verified_fidelity(
    base: FormatFidelity,
    verification: Any,
    *,
    byte_identical: bool = False,
    completeness: Any = None,
    partial_preserves_format: bool = False,
) -> FormatFidelity:
    """``base``, re-stated from what re-reading the produced artifact proved.

    ``verification`` is a
    :class:`app.services.format_verification.RenderVerification`. Three honest
    outcomes:

    * **byte-identical / nothing to verify** — the download is the user's own
      stored document; the claim is byte identity, not an inference.
    * **every change present** — the mechanism claim stands, and the note says
      how many rewrites were checked in the file itself.
    * **a change is missing** — confidence drops to ``partial`` and the note
      NAMES the rewrite that could not be applied. What ``preserved`` becomes
      then depends on ``partial_preserves_format``:

      - default (``False``) — ``preserved`` becomes ``False`` whatever the
        mechanism claimed, because the alternative is handing the user a
        document that is neither their baseline nor their tailored résumé while
        telling them it is complete (the DOCX/text branded-fallback contract).
      - ``True`` — an IN-PLACE render on the user's OWN document (PDF splice /
        DOCX-native / text-native), where a rewrite that could not be placed
        keeps its ORIGINAL wording. The downloaded file is genuinely the
        baseline with the placeable rewrites applied and the rest left as the
        user wrote them, so the FORMAT is preserved (``preserved`` stays the
        mechanism's value); the unplaced rewrites are disclosed as residue, not
        hidden. This is the MODELS-LIVE R-FMT ruling: preserve the layout, name
        the rewrites that could not land, and NEVER drop the whole document to
        the branded template over one out-of-scope region. The caller only
        passes this once a content-loss check (:func:`build_applied_content`)
        has proved the render kept the WHOLE original document.

    An artifact that cannot be re-read reports ``unverified`` — never a
    guess in either direction, so the mechanism's own ``preserved`` value
    stands there with the caveat spelled out in the note.
    """
    if byte_identical:
        return _with_completeness(
            FormatFidelity(
                method=base.method,
                confidence=base.confidence,
                note=base.note,
                preserved=base.preserved,
                verification=VERIFICATION_BYTE_IDENTITY,
                changes_requested=0,
                changes_applied=0,
                changes_dropped=0,
            ),
            completeness,
        )
    requested = int(getattr(verification, "requested", 0))
    if not getattr(verification, "text_extracted", False):
        return _with_completeness(
            FormatFidelity(
                method=base.method,
                confidence=CONFIDENCE_PENDING,
                note=(
                    f"{base.note} Aether could not re-read the produced file to "
                    "check the tailored wording, so this download is reported as "
                    "unverified rather than assumed correct."
                ),
                preserved=base.preserved,
                verification=VERIFICATION_POST_RENDER,
                changes_requested=requested,
                changes_applied=0,
                changes_dropped=0,
            ),
            completeness,
        )
    applied = int(verification.applied_count)
    dropped = verification.dropped
    surface = _SURFACE.get(base.method, "rendered document")
    if not dropped:
        checked = (
            f" All {requested} tailored change{'s' if requested != 1 else ''} "
            "were verified present in the file you download."
            if requested
            else ""
        )
        return _with_completeness(
            FormatFidelity(
                method=base.method,
                confidence=base.confidence,
                note=f"{base.note}{checked}",
                preserved=base.preserved,
                verification=VERIFICATION_POST_RENDER,
                changes_requested=requested,
                changes_applied=applied,
                changes_dropped=0,
            ),
            completeness,
        )
    excerpt = str(dropped[0].after).strip()
    if len(excerpt) > 120:
        excerpt = f"{excerpt[:117]}…"
    if partial_preserves_format:
        # In-place render on the user's OWN document: an unplaceable rewrite
        # keeps its ORIGINAL wording, so the file IS the baseline with the
        # placeable rewrites applied — the FORMAT is preserved and the residue
        # is disclosed. ``preserved`` stays the mechanism's value; the caller
        # has already proved (via the applied-only completeness contract) that
        # the whole original document survived.
        return _with_completeness(FormatFidelity(
            method=base.method,
            confidence=CONFIDENCE_PARTIAL,
            note=(
                f"{base.note} {len(dropped)} of {requested} reworded "
                f"{'bullet' if len(dropped) == 1 else 'bullets'} could not be "
                f"placed in the {surface} and keep the original wording — your "
                "document's layout is preserved and the full tailored text is in "
                "this version's change summary in Resume Studio. Not applied: "
                f"“{excerpt}”."
            ),
            preserved=base.preserved,
            verification=VERIFICATION_POST_RENDER,
            changes_requested=requested,
            changes_applied=applied,
            changes_dropped=len(dropped),
            dropped_changes=tuple(outcome.as_dict() for outcome in dropped),
        ), completeness)
    return _with_completeness(FormatFidelity(
        method=base.method,
        confidence=CONFIDENCE_PARTIAL,
        note=(
            f"{base.note} {len(dropped)} of {requested} tailoring changes could "
            f"not be applied to the {surface} — the full tailored wording is in "
            "this version's text (Resume Studio's change summary), not in the "
            f"downloaded file. Not applied: “{excerpt}”."
        ),
        # DERIVED, not carried: whatever the mechanism could do in principle,
        # a file we just re-read and found a tailored change missing from is
        # not a faithful rendering of this version. Consumers branch on this
        # boolean, so it may not disagree with the counts beside it.
        preserved=False,
        verification=VERIFICATION_POST_RENDER,
        changes_requested=requested,
        changes_applied=applied,
        changes_dropped=len(dropped),
        dropped_changes=tuple(outcome.as_dict() for outcome in dropped),
    ), completeness)


def stamp_fidelity(
    resumes: list[dict[str, Any]],
    bundled_hashes: set[str],
    original_meta: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Add ``formatPreserved`` + ``formatFidelity`` to every résumé in a listing.

    ``original_meta`` maps résumé id → ``{"hasOriginal": bool,
    "originalContentType": str | None}`` for the SAME user (no bytes are
    loaded). A tailored version is described by the document it derives from —
    its parent — exactly as the download endpoint resolves it.
    """
    by_id = {resume["id"]: resume for resume in resumes}
    stamped: list[dict[str, Any]] = []
    for resume in resumes:
        parent_id = resume.get("parentId")
        parent = by_id.get(parent_id) if parent_id else None
        source = parent or resume
        source_resolved = parent is not None or not parent_id
        format_hash = source.get("formatHash") or resume.get("formatHash")
        meta = original_meta.get(source["id"], {}) if source_resolved else {}
        fidelity = describe_fidelity(
            bundled_match=bool(format_hash) and format_hash in bundled_hashes,
            has_original=bool(meta.get("hasOriginal")),
            content_type=meta.get("originalContentType"),
            is_tailored=parent_id is not None,
            source_resolved=source_resolved,
        )
        if parent_id is not None and fidelity.preserved is True:
            # A tailored version's preservation claim depends on whether every
            # rewrite could actually be placed in the user's own document — a
            # question only the render itself can answer (U2b truth round).
            fidelity = pending_fidelity(fidelity)
        stamped.append({
            **resume,
            "formatPreserved": fidelity.preserved,
            "formatFidelity": fidelity.as_dict(),
        })
    return stamped
