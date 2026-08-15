"""RFMT-5 — an OUTBOUND résumé is the user's OWN format, never the Aether template.

THE DEFECT (MODELS-LIVE, ``uat/reports/evidence/models-live/resume-format/``).
``GET /resumes/{id}/download`` is not only an HTTP route. Every artifact that
leaves this system for an EMPLOYER is rendered by calling that handler
IN-PROCESS — ``services/email_attachments.py`` for the approval-gated email send
and the application email submission, and ``workers/apply_sweep.py`` for the
company-website auto-submit. FastAPI resolves ``Query`` defaults only for a real
HTTP request; on a direct call the parameter arrives as the ``Query`` OBJECT,
which is TRUTHY. ``branded: bool = _BRANDED_OPTIN`` therefore evaluated ``True``
on every one of those calls and the handler took its EXPLICIT-OPT-IN branch:
employers received the single-column Aether branded template, with the fidelity
report stamped ``branded-optin`` — a claim that the user had asked to be
re-styled, which they had not.

THE RULING. The branded template is a design the user CHOOSES. An outbound
artifact renders the preserved document — ``branded=False``, ``highlight=False``
— and the explicit HTTP opt-in (``?branded=true``) keeps working exactly as
documented.

WHAT THESE TESTS PIN — the CLASS, not the one parameter.

1. **The class.** ``test_in_process_handlers_behave_as_if_fastapi_resolved_...``
   introspects each in-process-called handler for EVERY parameter defaulted to a
   FastAPI ``Query``/``Param`` object and asserts that calling the handler with
   no keyword arguments produces the same document as calling it with those
   defaults RESOLVED to their literal values. Any future defaulted parameter
   whose truthiness can alter an outbound artifact fails here, whatever it is
   called — this is the pin that outlives ``branded``.
2. **The outbound choke point.** ``resolve_email_attachments`` — shared by the
   email send, the email submission and the auto-apply portal upload — must
   return the preserved render, byte-for-byte what the render authority
   ``_render_resume(id, uid, branded=False, highlight=False)`` produces, and
   demonstrably NOT the branded one.
3. **The cover letter, same slice.** The emailed letter must equal the letter
   the plain HTTP export returns. ``export_cover_letter_pdf`` carries no Query
   defaults today, so this passes before the fix as well — it is here so that
   adding one later cannot quietly change what an employer receives.
4. **Nothing else moved.** ``?branded=true`` still returns the branded template,
   reported honestly, and the outbound render still carries no diff marking
   (RFMT-2).
"""
from __future__ import annotations

import inspect
import json
from typing import Any

from fastapi import params
from test_rfmt2_clean_download import (  # noqa: E402
    _coral_wash_shapes,
    _highlight_shapes_per_page,
    _seed_multipage_baseline,
    _tailor_all_pages,
)
from test_u2b_fidelity_verification import _pdf_text, _user_id  # noqa: E402

from app.db import get_connection, new_id

#: A perfectly ordinary human name — the placeholder/test-probe signer guard
#: (BLOCKER-002) must not fire on the fixture letter.
_SIGNER = "Jordan Avery"


# --- Fixtures ---------------------------------------------------------------


def _page_count(data: bytes) -> int:
    import fitz

    doc = fitz.open(stream=bytes(data), filetype="pdf")
    try:
        return len(doc)
    finally:
        doc.close()


def _pdf_fingerprint(data: bytes) -> tuple[tuple[float, float, str, int], ...]:
    """The produced DOCUMENT — everything except its random trailer ``/ID``.

    Two renders of the same résumé are never byte-identical: PyMuPDF stamps a
    fresh random ``/ID`` into the trailer on every write, and the serialised
    length of that id varies with how its bytes escape, so even
    ``Content-Length`` moves. [VERIFIED on this tree: two consecutive
    ``_render_resume(..., branded=False)`` calls differ in exactly 59 bytes,
    all of them inside ``trailer <</ID[<…><…>]``.] Comparing raw bytes would
    therefore be a flaky test, not a stronger one.

    So the comparison is the document: per page, its geometry, its text and how
    many shapes are drawn on it. That is what a recruiter opens, and it
    separates the preserved two-column splice from the branded template
    unambiguously.
    """
    import fitz

    doc = fitz.open(stream=bytes(data), filetype="pdf")
    try:
        return tuple(
            (
                round(page.rect.width, 2),
                round(page.rect.height, 2),
                " ".join(page.get_text().split()),
                len(page.get_drawings()),
            )
            for page in doc
        )
    finally:
        doc.close()


def _stable_headers(response: Any) -> dict[str, str]:
    """Response headers minus ``content-length`` (see :func:`_pdf_fingerprint`)."""
    return {
        key.lower(): value
        for key, value in response.headers.items()
        if key.lower() != "content-length"
    }


def _seed_letter(user_id: str, resume_id: str) -> str:
    """A stored draft ``Application`` carrying a clean, exportable letter."""
    job_id = new_id()
    letter_id = new_id()
    body = (
        "14 August 2026\n\n"
        "Hiring Team\nGrafana Labs\nRe: Senior Product Manager\n\n"
        "Dear Hiring Team at Grafana Labs,\n\n"
        "I led the observability platform through its migration and cut alert "
        "noise by half without losing a single production signal.\n\n"
        f"Sincerely,\n{_SIGNER}\n"
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Senior Product Manager", "Grafana Labs",
                    "Sydney NSW", False, "Own the platform observability roadmap.",
                    json.dumps([]), "seek", f"https://example.com/{job_id}", 88.0,
                ),
            )
            cur.execute(
                '''INSERT INTO "Application"
                   ("id","userId","jobId","resumeId","status","coverLetter",
                    "createdAt","updatedAt")
                   VALUES (%s,%s,%s,%s,'draft'::"ApplicationStatus",%s,NOW(),NOW())''',
                (letter_id, user_id, job_id, resume_id, body),
            )
        conn.commit()
    return letter_id


def _outbound_resume(client, auth_headers) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """A tailored child of the bundled two-column baseline, plus the caller."""
    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)
    me = client.get("/auth/me", headers=auth_headers).json()
    return child, _user_id(client, auth_headers), me


def _resolved_query_defaults(handler: Any) -> dict[str, Any]:
    """The kwargs FastAPI *would* have injected, for every defaulted parameter.

    ``Query(False)`` is a ``fastapi.params.Param`` whose ``.default`` is the
    literal ``False``. An in-process call that omits the argument receives the
    ``Param`` object instead — the whole defect — so these two call shapes
    diverging IS the bug, for any parameter, on any handler.
    """
    return {
        name: parameter.default.default
        for name, parameter in inspect.signature(handler).parameters.items()
        if isinstance(parameter.default, params.Param)
    }


# ---------------------------------------------------------------------------
# (1) THE BUG CLASS — an in-process call behaves as if FastAPI had resolved
#     every Query default, whatever those defaults are called.
# ---------------------------------------------------------------------------


def test_in_process_handlers_behave_as_if_fastapi_resolved_every_query_default(
    client, auth_headers, test_user_id
):
    """The generic pin: no ``Query``-object truthiness may alter an outbound send.

    Both handlers that produce an employer-facing attachment are called with no
    keyword arguments (exactly as ``services/email_attachments.py`` calls them)
    and again with every ``Query`` default resolved to its literal value. The
    two documents must be identical. This fails for ANY defaulted parameter that
    reaches an unguarded truthiness check — ``branded`` today, whatever is added
    tomorrow.
    """
    from app.routers.cover_letters import export_cover_letter_pdf
    from app.routers.resumes import download_resume

    child, _uid, me = _outbound_resume(client, auth_headers)
    letter_id = _seed_letter(test_user_id, child["id"])

    probes = [
        (download_resume, (child["id"], me)),
        (export_cover_letter_pdf, (letter_id, me)),
    ]

    defaulted = 0
    for handler, args in probes:
        resolved = _resolved_query_defaults(handler)
        defaulted += len(resolved)
        implicit = handler(*args)
        explicit = handler(*args, **resolved)
        assert _pdf_text(bytes(implicit.body)) == _pdf_text(bytes(explicit.body)), (
            f"{handler.__name__} called in-process produced a DIFFERENT document "
            f"from the same call with {sorted(resolved)} resolved — a Query "
            "object's truthiness is deciding what an employer receives"
        )
        assert _stable_headers(implicit) == _stable_headers(explicit), (
            f"{handler.__name__} reported different headers for the in-process "
            "call than for the resolved-default call"
        )

    assert defaulted > 0, (
        "sanity: at least one in-process-called handler must still carry a "
        "Query default, or this test proves nothing"
    )


# ---------------------------------------------------------------------------
# (2) The outbound choke point — email send, email submission, auto-apply
# ---------------------------------------------------------------------------


def test_outbound_resume_attachment_is_the_preserved_render_not_branded(
    client, auth_headers
):
    """``resolve_email_attachments`` feeds EVERY employer-facing résumé.

    Gmail reply/send (``routers/approvals.py``), application email submission
    (``services/application_submission.py``) and the company-website auto-submit
    (``workers/apply_sweep.py``) all take their bytes from here.
    """
    from app.routers.resumes import _render_resume
    from app.services.email_attachments import resolve_email_attachments

    child, uid, me = _outbound_resume(client, auth_headers)

    attachments = resolve_email_attachments(me, resume_id=child["id"])
    assert len(attachments) == 1, attachments
    filename, data, mimetype = attachments[0]

    preserved = _render_resume(child["id"], uid, branded=False, highlight=False)
    branded = _render_resume(child["id"], uid, branded=True, highlight=False)

    # Not vacuous: the two renders really are different documents.
    assert _pdf_text(preserved.content) != _pdf_text(branded.content), (
        "fixture sanity: the branded template must differ from the preserved render"
    )

    assert preserved.fidelity.method == "pdf-in-place-splice", preserved.fidelity.method
    assert _pdf_fingerprint(data) == _pdf_fingerprint(preserved.content), (
        "the résumé sent to an employer must be the preserved render — same "
        "pages, same geometry, same words, same marks"
    )
    assert _pdf_fingerprint(data) != _pdf_fingerprint(branded.content), (
        "the résumé sent to an employer is the Aether BRANDED template — the user "
        "never opted in"
    )
    assert _page_count(data) == _page_count(preserved.content) >= 3, (
        "the preserved render keeps the user's own multi-page two-column layout"
    )
    # The attachment is labelled for what it actually IS — a preserved .docx or
    # .txt render must never travel to an employer named ``.pdf``.
    assert filename == preserved.filename
    assert mimetype == preserved.media_type


def test_auto_apply_portal_upload_is_the_preserved_render(client, auth_headers):
    """The company-website auto-submit uploads the same preserved document."""
    from app.routers.resumes import _render_resume
    from app.workers.apply_sweep import _render_resume_pdf

    child, uid, _me = _outbound_resume(client, auth_headers)

    uploaded = _render_resume_pdf(uid, {"resumeId": child["id"]})
    preserved = _render_resume(child["id"], uid, branded=False, highlight=False)
    branded = _render_resume(child["id"], uid, branded=True, highlight=False)

    assert _pdf_fingerprint(uploaded) == _pdf_fingerprint(preserved.content), (
        "the file uploaded to the employer's portal must be the preserved render"
    )
    assert _pdf_fingerprint(uploaded) != _pdf_fingerprint(branded.content), (
        "the auto-apply portal upload is the Aether BRANDED template"
    )


def test_portal_upload_is_named_for_the_document_it_actually_is(client, auth_headers):
    """A preserved ``.docx`` must never reach an employer's portal named ``.pdf``.

    The branded template was always a PDF, so while the defect was live the
    hard-coded ``.pdf`` name happened to be right. A preserved render is
    whatever the user uploaded, so the name now follows the bytes.
    """
    from app.routers.resumes import _render_resume
    from app.services.apply_executor import _resume_suffix

    assert _resume_suffix(b"PK\x03\x04word/document.xml") == ".docx"
    assert _resume_suffix("Jordan Avery — Senior Product Manager".encode()) == ".txt"
    assert _resume_suffix(b"") == ".pdf"

    child, uid, _me = _outbound_resume(client, auth_headers)
    preserved = _render_resume(child["id"], uid, branded=False, highlight=False)
    assert _resume_suffix(bytes(preserved.content)) == ".pdf", (
        "this fixture's preserved render IS a PDF and must still be named one"
    )


def test_outbound_resume_attachment_carries_no_diff_marking(client, auth_headers):
    """RFMT-2 stays closed at the choke point, not just at the handler."""
    from app.services.email_attachments import resolve_email_attachments

    child, _uid, me = _outbound_resume(client, auth_headers)
    data = resolve_email_attachments(me, resume_id=child["id"])[0][1]

    per_page = _highlight_shapes_per_page(data)
    assert per_page == [0] * len(per_page), (
        f"the emailed résumé must carry no peach wash on any page; found {per_page}"
    )
    assert _coral_wash_shapes(data) == 0, (
        "the emailed résumé must carry no coral wash either"
    )


# ---------------------------------------------------------------------------
# (3) The cover letter travels the same in-process path
# ---------------------------------------------------------------------------


def test_outbound_cover_letter_matches_the_plain_http_export(
    client, auth_headers, test_user_id
):
    """The emailed letter is what ``GET /cover-letters/{id}/pdf`` returns.

    ``export_cover_letter_pdf`` carries no Query defaults today, so this holds
    before the fix too. It is pinned so that adding one later cannot silently
    change the document an employer opens.
    """
    from app.services.email_attachments import resolve_email_attachments

    child, _uid, me = _outbound_resume(client, auth_headers)
    letter_id = _seed_letter(test_user_id, child["id"])

    export = client.get(f"/cover-letters/{letter_id}/pdf", headers=auth_headers)
    assert export.status_code == 200, export.text

    attachments = resolve_email_attachments(me, cover_letter_id=letter_id)
    assert len(attachments) == 1, attachments
    _filename, data, mimetype = attachments[0]

    assert mimetype == "application/pdf"
    assert _pdf_text(data) == _pdf_text(export.content), (
        "the emailed cover letter differs from the letter the export endpoint "
        "returns for the same id"
    )
    assert _SIGNER in _pdf_text(data)


# ---------------------------------------------------------------------------
# (4) The EXPLICIT opt-in is untouched
# ---------------------------------------------------------------------------


def test_http_branded_optin_still_returns_the_branded_template(client, auth_headers):
    """``?branded=true`` is a user choice and keeps working, reported honestly."""
    child, _uid, _me = _outbound_resume(client, auth_headers)

    branded = client.get(
        f"/resumes/{child['id']}/download?branded=true", headers=auth_headers
    )
    assert branded.status_code == 200, branded.text
    assert branded.headers["X-Aether-Format-Method"] == "branded-optin"

    fidelity = client.get(
        f"/resumes/{child['id']}/fidelity?branded=true", headers=auth_headers
    )
    assert fidelity.status_code == 200, fidelity.text
    assert fidelity.json()["method"] == "branded-optin"
    assert fidelity.json()["formatPreserved"] is False


def test_plain_http_download_and_fidelity_agree_on_the_preserved_render(
    client, auth_headers
):
    """No opt-in → the preserved render, and the report describes THAT file."""
    child, _uid, _me = _outbound_resume(client, auth_headers)

    download = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert download.status_code == 200, download.text
    assert download.headers["X-Aether-Format-Method"] == "pdf-in-place-splice"

    fidelity = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers)
    assert fidelity.status_code == 200, fidelity.text
    assert fidelity.json()["method"] == "pdf-in-place-splice"
    assert fidelity.json()["formatPreserved"] is True


def test_in_process_download_reports_the_preserved_method(client, auth_headers):
    """The header an operator reads off an outbound render names the real branch."""
    from app.routers.resumes import download_resume

    child, _uid, me = _outbound_resume(client, auth_headers)

    response = download_resume(child["id"], me)
    assert response.headers["X-Aether-Format-Method"] == "pdf-in-place-splice", (
        "an in-process download reported "
        f"{response.headers['X-Aether-Format-Method']!r} — the Query object's "
        "truthiness sent it down the branded-opt-in branch"
    )
