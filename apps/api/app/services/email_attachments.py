"""Resolve resume / cover-letter documents into Gmail attachments — in-process.

This is the CHOKE POINT for every résumé and cover letter that leaves the
system for an employer: the Email Agent's approval-gated send
(``routers/approvals.py``), the application email submission
(``services/application_submission.py``) and the company-website auto-submit
(``workers/apply_sweep.py``) all take their bytes from here. Rather than an HTTP
self-call (blueprint §2), the shipped rendering code is invoked *in-process*, so
an attachment is the same document the user's own Download button produces, with
zero duplicated PDF logic and no network hop.

RFMT-5 — WHY THE RÉSUMÉ GOES STRAIGHT TO THE RENDER AUTHORITY. This module used
to call the ROUTE HANDLER ``download_resume(resume_id, current_user)``. FastAPI
resolves ``Query`` defaults only for a real HTTP request; on a direct call the
parameter arrives as the ``Query`` OBJECT, which is TRUTHY — so
``branded: bool = _BRANDED_OPTIN`` evaluated ``True`` and every outbound résumé
was rendered in the single-column Aether branded template, reported
``branded-optin``, as though the user had asked to be re-styled. The handler now
guards that parameter (``_branded_requested``), and this module additionally
calls the render authority ``_render_resume`` with LITERAL arguments, so no
parameter-resolution rule anywhere can decide what an employer opens:
``branded=False, highlight=False`` — the user's own preserved document, with no
diff marking (RFMT-2).

The attachment is also labelled for what it ACTUALLY is. The preserved render is
whatever the user uploaded — a spliced PDF, a natively rewritten ``.docx``, a
``.txt`` — so the filename and mimetype come from the render itself rather than
being hard-coded to PDF, which would send an employer a Word document named
``.pdf``.

A missing/unauthorized resume or letter raises the shipped ``HTTPException``
(404), so an approved send with a dangling attachment fails honestly *before*
any email leaves the system — never a partial send.
"""
from __future__ import annotations

from typing import Any

_MIME_PDF = "application/pdf"

#: Gmail's message ceiling is 25 MB (enforced again in GmailService); resume/CL
#: PDFs are a few KB, but we validate the aggregate honestly all the same.
_MAX_ATTACH_BYTES = 25 * 1024 * 1024


def resolve_email_attachments(
    current_user: dict[str, Any],
    *,
    resume_id: str | None = None,
    cover_letter_id: str | None = None,
) -> list[tuple[str, bytes, str]]:
    """Return ``[(filename, bytes, mimetype)]`` for the requested documents.

    Empty list when neither id is supplied (a plain-text send). The résumé is
    the format-PRESERVING render of the user's own document — explicitly
    ``branded=False, highlight=False``, never the Aether template and never diff
    marking, whatever a caller or a parameter default might otherwise imply
    (RFMT-5 / RFMT-2). The cover letter is the same PDF ``GET
    /cover-letters/{id}/pdf`` returns, including its placeholder-signer refusal.
    """
    attachments: list[tuple[str, bytes, str]] = []
    total = 0
    if resume_id:
        from app.routers.resumes import _render_resume

        # The render authority, with LITERAL options: an outbound artifact can
        # never be re-styled or diff-marked by a Query object's truthiness.
        rendered = _render_resume(
            resume_id, current_user["id"], branded=False, highlight=False
        )
        data = bytes(rendered.content)
        total += len(data)
        attachments.append((rendered.filename, data, rendered.media_type))
    if cover_letter_id:
        from app.routers.cover_letters import export_cover_letter_pdf

        # Verified RFMT-5: this handler declares NO defaulted ``Query``
        # parameter, so an in-process call is identical to the plain HTTP export
        # and there is nothing here for a ``Query`` object to flip. Pinned by
        # ``tests/test_rfmt5_outbound_preserved_format.py``, which fails if one
        # is ever added without a ``_*_requested`` guard.
        resp = export_cover_letter_pdf(cover_letter_id, current_user)
        data = bytes(resp.body)
        total += len(data)
        attachments.append((f"cover-letter-{cover_letter_id[:8]}.pdf", data, _MIME_PDF))
    if total > _MAX_ATTACH_BYTES:
        raise ValueError("Attachments exceed Gmail's 25 MB limit.")
    return attachments
