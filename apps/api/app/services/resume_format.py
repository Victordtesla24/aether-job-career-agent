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
                       edit of them);
``preserved = False``  the download is a re-render in Aether's template — said
                       plainly, with the reason;
``preserved = None``   we genuinely cannot tell (the source version could not
                       be resolved). Reported as unknown rather than guessed;
                       the Resume Studio panel already renders this third state
                       as "status is unknown" instead of an affirmative claim.

Every state also carries a ``formatFidelity`` report — ``{method, confidence,
note}`` — because a bare boolean cannot say WHY, and R-F4 forbids silent
claims: "low confidence ⇒ faithful re-render + EXPLICIT fidelity report".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.resume_docx import DOCX_CONTENT_TYPE

#: Content types whose text is trivially preservable end to end (R-F4).
_TEXT_CONTENT_TYPES = ("text/plain", "text/markdown")

METHOD_ORIGINAL_BYTES = "original-bytes"
METHOD_PDF_SPLICE = "pdf-in-place-splice"
METHOD_DOCX_NATIVE = "docx-native"
METHOD_TEXT_NATIVE = "text-native"
METHOD_REFLOW = "reflow-template"
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

    def as_dict(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "method": self.method,
            "confidence": self.confidence,
            "note": self.note,
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
            "so downloads are rendered in the Aether template."
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


def native_fallback_fidelity(*, unreadable: bool = False) -> FormatFidelity:
    """The honest report when a native in-document rewrite could not complete.

    The user's own document IS the preferred surface, but a rewrite Aether
    cannot place in it (or a stored file that no longer opens) must not ship as
    a half-tailored copy of their résumé. The download falls back to the
    branded template, which renders the version's complete tailored content —
    and says exactly that, rather than reusing the generic "not yet available
    for this upload type" copy, which would be false for these versions.
    """
    reason = (
        "Your stored original file could not be opened, so this download is "
        "rendered in the Aether template"
        if unreadable
        else "A reworded line could not be located in your original document, "
        "so this download is rendered in the Aether template"
    )
    return FormatFidelity(
        method=METHOD_REFLOW,
        confidence="low",
        note=(
            f"{reason} with your complete tailored content, rather than a "
            "partially tailored copy of your own file. The file you uploaded "
            "is unchanged and can still be downloaded from Settings."
        ),
        preserved=False,
    )


def verified_fidelity(
    base: FormatFidelity, verification: Any, *, byte_identical: bool = False
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
      NAMES the rewrite that could not be applied, because the alternative is
      handing the user a document that is neither their baseline nor their
      tailored résumé while telling them it is complete.

    An artifact that cannot be re-read reports ``unverified`` — never a
    guess in either direction.
    """
    if byte_identical:
        return FormatFidelity(
            method=base.method,
            confidence=base.confidence,
            note=base.note,
            preserved=base.preserved,
            verification=VERIFICATION_BYTE_IDENTITY,
            changes_requested=0,
            changes_applied=0,
            changes_dropped=0,
        )
    requested = int(getattr(verification, "requested", 0))
    if not getattr(verification, "text_extracted", False):
        return FormatFidelity(
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
        return FormatFidelity(
            method=base.method,
            confidence=base.confidence,
            note=f"{base.note}{checked}",
            preserved=base.preserved,
            verification=VERIFICATION_POST_RENDER,
            changes_requested=requested,
            changes_applied=applied,
            changes_dropped=0,
        )
    excerpt = str(dropped[0].after).strip()
    if len(excerpt) > 120:
        excerpt = f"{excerpt[:117]}…"
    return FormatFidelity(
        method=base.method,
        confidence=CONFIDENCE_PARTIAL,
        note=(
            f"{base.note} {len(dropped)} of {requested} tailoring changes could "
            f"not be applied to the {surface} — the full tailored wording is in "
            "this version's text (Resume Studio's change summary), not in the "
            f"downloaded file. Not applied: “{excerpt}”."
        ),
        preserved=base.preserved,
        verification=VERIFICATION_POST_RENDER,
        changes_requested=requested,
        changes_applied=applied,
        changes_dropped=len(dropped),
        dropped_changes=tuple(outcome.as_dict() for outcome in dropped),
    )


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
