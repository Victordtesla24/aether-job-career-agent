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


@dataclass(frozen=True)
class FormatFidelity:
    """What a download of this résumé version will really do to its format."""

    method: str
    confidence: str
    note: str
    preserved: bool | None

    def as_dict(self) -> dict[str, str]:
        return {"method": self.method, "confidence": self.confidence, "note": self.note}


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
                    "Only the reworded bullets are redrawn on your original PDF "
                    "— every other element is identical to the source document."
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
        stamped.append({
            **resume,
            "formatPreserved": fidelity.preserved,
            "formatFidelity": fidelity.as_dict(),
        })
    return stamped
