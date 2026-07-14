"""Resolve resume / cover-letter PDFs into Gmail attachments — in-process.

The Email Agent's approval-gated send can carry a resume and/or a cover letter
to attach. Rather than an HTTP self-call (blueprint §2), we invoke the same
shipped route handlers *in-process*: they return a FastAPI ``Response`` whose
``.body`` is the real PDF bytes served by ``GET /resumes/{id}/download`` and
``GET /cover-letters/{id}/pdf``. Reusing the handlers means the attachment is
byte-identical to the download endpoints with zero duplicated PDF logic and no
network hop.

A missing/unauthorized resume or letter raises the handler's own
``HTTPException`` (404), so an approved send with a dangling attachment fails
honestly *before* any email leaves the system — never a partial send.
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
    """Return ``[(filename, pdf_bytes, mimetype)]`` for the requested documents.

    Empty list when neither id is supplied (a plain-text send). The bytes are
    produced by the real download handlers, called in-process.
    """
    attachments: list[tuple[str, bytes, str]] = []
    total = 0
    if resume_id:
        from app.routers.resumes import download_resume

        resp = download_resume(resume_id, current_user)
        data = bytes(resp.body)
        total += len(data)
        attachments.append((f"resume-{resume_id[:8]}.pdf", data, _MIME_PDF))
    if cover_letter_id:
        from app.routers.cover_letters import export_cover_letter_pdf

        resp = export_cover_letter_pdf(cover_letter_id, current_user)
        data = bytes(resp.body)
        total += len(data)
        attachments.append((f"cover-letter-{cover_letter_id[:8]}.pdf", data, _MIME_PDF))
    if total > _MAX_ATTACH_BYTES:
        raise ValueError("Attachments exceed Gmail's 25 MB limit.")
    return attachments
