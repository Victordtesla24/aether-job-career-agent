"""MODELS-LIVE R-FMT — a tailored résumé is the baseline with ONLY text changed.

The mandate: *tailored = baseline with ONLY the reworded text changed, the
visual format intact.* Live production violated it — a tailored child of the
two-column baseline ``cfe7a0f…`` downloaded as a 9.4 KB single-column branded
PDF (``c12187…``) because ONE of four rewrites aimed at the left rail could not
be spliced and the whole render was dropped all-or-nothing to Aether's branded
template (``uat/reports/evidence/market-perf/resume-format/``).

This suite pins the ruling that removes that failure:

1. **The flagship** — a freshly tailored child of a bundled two-column baseline
   downloads as the SAME two-column PDF, with a ~0 pixel difference OUTSIDE the
   reworded bullet, proved by an independent rasteriser (``pdftoppm``) and a
   PyMuPDF text-span cross-check. A rewrite the splice engine cannot place keeps
   its baseline wording and is disclosed as residue — never a drop to branded.
2. **The verification harness** (``services/format_diff.py``) itself: it must
   PASS an in-place splice and FAIL a genuine re-layout (branded single-column).
3. **The fidelity contract** — an in-place render with unplaceable residue is
   ``formatPreserved: true`` (the layout is the user's own), ``confidence:
   partial``, with the residue named, and the WHOLE original document still
   present. A GENUINE content loss still falls back to the branded render (the
   U2b CRITICAL guarantee, intact).
4. **Legacy** — a résumé with no retained original is told to re-upload, not
   silently branded as "preserved".

Fixtures derive from the repository's own bundled résumé asset at run time, so
the tests exercise the real geometry that produced the live defect.
"""
from __future__ import annotations

import hashlib
from io import BytesIO

# ONE definition of the bundled-layout fixtures + "a change the splice engine
# structurally cannot apply", shared with the U2b truth-round tests.
from test_u2b_fidelity_verification import (  # noqa: E402
    _bundled_pdf,
    _pdf_text,
    _right_column_bullet,
    _seed_bundled_baseline,
    _tailor_child,
)


def _right_after(right: str) -> str:
    head, _, tail = right.partition(":")
    return f"{head}: Re-scoped for the target role, {tail.strip()}"


def _left_after(left: str) -> str:
    return f"Product and delivery leadership across regulated platforms; {left}"


def _changed_slot_boxes(before_text: str) -> dict[int, list[tuple[float, float, float, float]]]:
    """Bounding boxes (PyMuPDF points) of the work bullet whose text is ``before``.

    Read from the splice engine's OWN block detection, so the mask covers exactly
    the region the renderer redraws (plus a small pad for its peach highlight and
    any font step-down), and nothing else.
    """
    import fitz

    from app.services.resume_pdf import _RIGHT_MARGIN, _detect_blocks, _normalize

    key = _normalize(before_text)
    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    doc = fitz.open(_bundled_pdf())
    try:
        for page_index in range(len(doc)):
            for block in _detect_blocks(doc[page_index]):
                if _normalize(block["full_text"]).startswith(key[:40]) or key.startswith(
                    _normalize(block["full_text"])[:40]
                ):
                    boxes.setdefault(page_index, []).append((
                        block["x0"] - 4.0,
                        block["top"] - 4.0,
                        _RIGHT_MARGIN + 4.0,
                        block["bottom"] + 8.0,
                    ))
    finally:
        doc.close()
    return boxes


# ---------------------------------------------------------------------------
# (2) The verification harness: passes a splice, fails a re-layout
# ---------------------------------------------------------------------------


def test_harness_pdf_layout_identical_pdf_is_preserved():
    from app.services.format_diff import compare_pdf_layout

    data = _bundled_pdf().read_bytes()
    result = compare_pdf_layout(data, data)
    assert result.same_page_count and result.same_geometry
    assert result.max_diff_ratio == 0.0
    assert result.preserved is True


def test_harness_pdf_layout_flags_a_branded_relayout_as_not_preserved():
    """A single-column branded re-render of the same résumé must FAIL the gate.

    This is the live failure mode: same words, wholly different layout. If the
    harness passed it, the harness would be useless.
    """
    from app.services.format_diff import compare_pdf_layout
    from app.services.resume_pdf import create_branded_resume_pdf, extract_pdf_bullets

    baseline = _bundled_pdf().read_bytes()
    bullets = extract_pdf_bullets(_bundled_pdf())
    branded = create_branded_resume_pdf(
        "VIKRAM DESHPANDE",
        "Senior Technical Program/Delivery Manager",
        "",
        [{"heading": "WORK EXPERIENCE", "bullets": bullets}],
        None,
    )
    result = compare_pdf_layout(baseline, branded)
    assert result.preserved is False, (
        "a single-column branded re-render is NOT the two-column original — the "
        f"harness must reject it, got {result!r}"
    )


def test_harness_masks_exclude_the_reworded_slot():
    """The pixel diff of a real splice is ~0 OUTSIDE the reworded bullet's mask."""
    from app.services.format_diff import compare_pdf_layout
    from app.services.resume_pdf import render_tailored_pdf

    right = _right_column_bullet()
    spliced = render_tailored_pdf(_bundled_pdf(), [(right, _right_after(right))])
    boxes = _changed_slot_boxes(right)
    assert boxes, "fixture sanity: the reworded bullet must be locatable in the layout"

    masked = compare_pdf_layout(_bundled_pdf().read_bytes(), spliced, change_boxes=boxes)
    assert masked.same_page_count and masked.same_geometry
    assert masked.preserved is True, (
        f"outside the reworded slot the splice must be pixel-identical, got {masked!r}"
    )

    # Without the mask, the reworded slot itself IS a difference — proving the
    # mask is doing real work rather than the diff being trivially empty.
    unmasked = compare_pdf_layout(_bundled_pdf().read_bytes(), spliced)
    assert unmasked.max_diff_ratio > masked.max_diff_ratio


def test_harness_pdf_text_span_crosscheck_matches_outside_masks():
    from app.services.format_diff import compare_pdf_text_spans
    from app.services.resume_pdf import render_tailored_pdf

    right = _right_column_bullet()
    spliced = render_tailored_pdf(_bundled_pdf(), [(right, _right_after(right))])
    diff = compare_pdf_text_spans(
        _bundled_pdf().read_bytes(), spliced, change_boxes=_changed_slot_boxes(right)
    )
    assert diff.identical, (
        "every text span outside the reworded slot must sit at the same "
        f"position, font and size: {diff!r}"
    )


# ---------------------------------------------------------------------------
# (1) THE FLAGSHIP — the two-column baseline and its tailored child both
#     download as the same two-column PDF, ~0 diff outside the reworded bullet
# ---------------------------------------------------------------------------


def test_flagship_tailored_child_downloads_as_the_two_column_layout(client, auth_headers):
    """The exact live failure, reversed: cfe7a0f→child stays two-column.

    A right-column bullet is reworded (the splice CAN place it) and a left-rail
    line is reworded (the splice CANNOT). Under the old all-or-nothing gate this
    produced the single-column branded PDF; now the download is the preserved
    two-column splice with the left-rail rewrite disclosed as residue.
    """
    from app.services.format_diff import compare_pdf_layout, compare_pdf_text_spans

    baseline, left, right = _seed_bundled_baseline(client, auth_headers)
    left_after, right_after = _left_after(left), _right_after(right)
    child = _tailor_child(
        client, auth_headers, baseline, {"bullet-0": left_after, "bullet-1": right_after}
    )

    fidelity = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers).json()
    assert fidelity["method"] == "pdf-in-place-splice", fidelity
    assert fidelity["verification"] == "post-render-text-extraction", fidelity
    assert fidelity["changesRequested"] == 2, fidelity
    assert fidelity["changesApplied"] == 1, fidelity
    assert fidelity["changesDropped"] == 1, fidelity
    assert fidelity["formatPreserved"] is True, (
        "the two-column layout IS the user's own document — format is preserved "
        f"even though one out-of-scope rewrite could not be placed: {fidelity}"
    )
    assert fidelity["confidence"] == "partial", fidelity
    note = fidelity["note"].lower()
    assert "layout is preserved" in note, note
    assert "aether template" not in note, note

    base_dl = client.get(f"/resumes/{baseline['id']}/download", headers=auth_headers)
    child_dl = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert base_dl.status_code == 200 and child_dl.status_code == 200
    assert child_dl.headers["X-Aether-Format-Method"] == "pdf-in-place-splice"
    assert child_dl.headers["X-Aether-Changes-Applied"] == "1"
    assert child_dl.headers["X-Aether-Changes-Dropped"] == "1"

    # The child must be the SAME two-column layout as the baseline — same page
    # count and geometry, ~0 pixel diff outside the one reworded work bullet.
    boxes = _changed_slot_boxes(right)
    assert boxes, "fixture sanity: the reworded work bullet must be locatable"
    layout = compare_pdf_layout(base_dl.content, child_dl.content, change_boxes=boxes)
    assert layout.same_page_count, layout
    assert layout.same_geometry, layout
    assert layout.preserved is True, (
        "the tailored child must be the two-column baseline with ONLY the "
        f"reworded bullet changed: {layout!r}"
    )
    spans = compare_pdf_text_spans(base_dl.content, child_dl.content, change_boxes=boxes)
    assert spans.identical, spans

    # The unplaceable left-rail rewrite keeps its ORIGINAL wording (residue),
    # and the placeable right-column rewrite is really applied.
    text = " ".join(_pdf_text(child_dl.content).split())
    assert left in text, "the unplaceable rewrite must keep the baseline wording"
    assert right_after.partition(":")[2].strip()[:50] in text, text[:400]


def test_flagship_render_harness_gate_without_the_api(client, auth_headers):
    """The §4 acceptance gate, expressed directly on the render + harness.

    Independent of the endpoint: splice the bundled two-column PDF and assert the
    harness certifies it as the same layout outside the reworded slot. This is
    the gate the brief says FAILS today (a branded single-column render).
    """
    from app.services.format_diff import compare_pdf_layout
    from app.services.resume_pdf import render_tailored_pdf

    right = _right_column_bullet()
    spliced = render_tailored_pdf(_bundled_pdf(), [(right, _right_after(right))])
    result = compare_pdf_layout(
        _bundled_pdf().read_bytes(), spliced, change_boxes=_changed_slot_boxes(right)
    )
    assert result.page_count >= 1
    assert result.preserved is True, result


# ---------------------------------------------------------------------------
# (3) The fidelity contract for an in-place render with residue
# ---------------------------------------------------------------------------


def test_verified_fidelity_partial_preserves_format_keeps_preserved_true():
    """An unplaceable rewrite that keeps the original wording preserves format."""
    from app.services.format_verification import ChangeOutcome, RenderVerification
    from app.services.resume_format import describe_fidelity, verified_fidelity

    base = describe_fidelity(
        bundled_match=True, has_original=False, content_type=None, is_tailored=True
    )
    verification = RenderVerification(
        requested=2,
        text_extracted=True,
        outcomes=(
            ChangeOutcome("b0", "a0", coverage=1.0, applied=True, original_remains=False),
            ChangeOutcome(
                "b1 left rail skills line here",
                "a1 reworded skills that could not be placed in the left rail",
                coverage=0.05,
                applied=False,
                original_remains=True,
            ),
        ),
    )
    report = verified_fidelity(base, verification, partial_preserves_format=True)
    assert report.method == "pdf-in-place-splice"
    assert report.changes_applied == 1
    assert report.changes_dropped == 1
    assert report.confidence == "partial"
    assert report.preserved is True, (
        "the layout is the user's own document; the residue is disclosed, not a "
        f"reason to deny preservation: {report!r}"
    )
    assert "original wording" in report.note.lower()
    assert "layout is preserved" in report.note.lower()

    # The default (branded-fallback) contract is UNCHANGED — a dropped change
    # there is still not preserved (U2b honesty machinery, untouched).
    default = verified_fidelity(base, verification)
    assert default.preserved is False


def test_build_applied_content_keeps_original_wording_for_a_dropped_rewrite():
    from app.services.resume_completeness import build_applied_content

    parent = {
        "sections": {
            "raw_text": (
                "JANE SMITH\n"
                "EXPERIENCE\n"
                "• Delivered the payments platform migration on schedule.\n"
                "• Owned the incident response runbook programme end to end."
            ),
            "bullets": [
                {"text": "Delivered the payments platform migration on schedule."},
                {"text": "Owned the incident response runbook programme end to end."},
            ],
        }
    }
    applied = [("Delivered the payments platform migration on schedule.", "AFTER placed")]
    content = build_applied_content(parent, applied)
    joined = " ".join(content.bullets).lower()
    assert "after placed" in joined, "a PLACED rewrite is substituted into the contract"
    assert "incident response runbook" in joined, (
        "a DROPPED rewrite keeps the parent's ORIGINAL wording in the contract, "
        "so the in-place render that still carries it is not falsely 'incomplete'"
    )


def test_genuine_content_loss_still_falls_back_to_branded(client, auth_headers):
    """A splice that LOST original content is NOT shipped (U2b CRITICAL intact).

    Modelled at the seam the router uses: when the applied-only completeness
    check reports a missing heading/contact/bullet, the in-place render must be
    refused in favour of the content-complete branded render.
    """
    from app.services.resume_completeness import CompletenessVerification

    # A render that genuinely dropped a whole section is content-incomplete even
    # under the lenient applied-only contract, so `.complete` is False and the
    # router routes to branded — the guarantee we must not weaken.
    lossy = CompletenessVerification(
        text_extracted=True, missing_headings=("EDUCATION",), missing_contact=("a@b.com",)
    )
    assert lossy.complete is False


# ---------------------------------------------------------------------------
# (4) Legacy — no retained original ⇒ re-upload, never silent "preserved"
# ---------------------------------------------------------------------------


def test_legacy_no_original_row_is_told_to_reupload(client, auth_headers):
    from app.repositories.resume import ResumeRepository

    me = client.get("/auth/me", headers=auth_headers).json()
    repo = ResumeRepository()
    repo.create(
        me["id"],
        {"raw_text": "TYPED RESUME\nEXPERIENCE\n• A typed bullet with no file.", "bullets": []},
        hashlib.sha256(b"not-a-bundled-asset").hexdigest(),
        label="Ingested — no original",
        version=repo.next_version(me["id"]),
    )
    listing = client.get("/resumes", headers=auth_headers).json()
    row = next(r for r in listing if r["label"] == "Ingested — no original")
    assert row["formatPreserved"] is False
    assert "re-upload" in row["formatFidelity"]["note"].lower(), row["formatFidelity"]


# ---------------------------------------------------------------------------
# (5) DOCX — the clean flagship: true in-place <w:t> substitution, with
#     styles.xml / numbering.xml / theme / fonts byte-identical (SYNTHESIS §4)
# ---------------------------------------------------------------------------

_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
#: A genuinely STYLED résumé — a Title, a Subtitle, a Heading and three
#: ``List Bullet`` paragraphs — so the package carries a real ``styles.xml``,
#: ``numbering.xml``, ``theme`` and font table for the structural diff to guard.
#: A plain-text-only fixture could pass "styles preserved" by accident.
_DOCX_PARAGRAPHS = [
    ("Title", "JORDAN AKINYEMI"),
    ("Subtitle", "Senior Platform Engineer — Perth, WA, Australia"),
    ("Heading 1", "EXPERIENCE"),
    ("List Bullet", "Operated a Kubernetes fleet serving 12 million requests per day."),
    ("List Bullet", "Cut deploy lead time by 47 percent through pipeline automation."),
    ("List Bullet", "Mentored six engineers across two on-call rotations."),
]
_DOCX_ORIGINAL_BULLET = "Cut deploy lead time by 47 percent through pipeline automation."
_DOCX_TAILORED_BULLET = (
    "Cut deploy lead time by 47 percent through Docker-based container pipeline automation."
)


def _make_styled_docx(paragraphs: list[tuple[str, str]]) -> bytes:
    from docx import Document

    doc = Document()
    for style, text in paragraphs:
        p = doc.add_paragraph(style=style if style != "Title" else None)
        run = p.add_run(text)
        if style == "Title":
            run.bold = True
        if style == "Subtitle":
            run.italic = True
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_harness_docx_structure_passes_a_true_inplace_rewrite():
    """The DOCX §4 assertion: a real in-place rewrite leaves every structural
    part (styles/numbering/theme/fonts) byte-identical and touches ONLY <w:t>.
    """
    from app.services.format_diff import _docx_parts, compare_docx_structure
    from app.services.resume_docx import render_tailored_docx

    original = _make_styled_docx(_DOCX_PARAGRAPHS)
    tailored = render_tailored_docx(
        original, [(_DOCX_ORIGINAL_BULLET, _DOCX_TAILORED_BULLET)]
    )
    assert tailored != original, "a genuine rewrite must change the bytes"

    diff = compare_docx_structure(original, tailored)
    assert diff.styles_preserved is True, (
        "styles.xml / numbering.xml / theme / fonts must be byte-identical and "
        f"the non-text skeleton unchanged: {diff!r}"
    )
    assert diff.changed_style_parts == () and diff.missing_parts == () and diff.added_parts == ()
    assert diff.document_structure_changed is False
    # document.xml IS allowed to differ — but only inside its <w:t> text runs.
    parts_before, parts_after = _docx_parts(original), _docx_parts(tailored)
    assert parts_before["word/document.xml"] != parts_after["word/document.xml"], (
        "the reworded text must actually change document.xml"
    )
    assert "word/document.xml" in diff.changed_text_only_parts


def test_harness_docx_structure_flags_a_structural_change():
    """If a rewrite altered a run/paragraph property — not just the words — the
    harness MUST reject it. Here the bullets lose their ``List Bullet`` numbering
    (a pPr/numbering change), which the mandate forbids a tailoring edit to make.
    """
    from app.services.format_diff import compare_docx_structure

    original = _make_styled_docx(_DOCX_PARAGRAPHS)
    destyled = _make_styled_docx(
        [("Normal" if style == "List Bullet" else style, text) for style, text in _DOCX_PARAGRAPHS]
    )
    diff = compare_docx_structure(original, destyled)
    assert diff.styles_preserved is False, (
        "a numbering/paragraph-property change is a structural change the harness "
        f"must catch, not a permitted <w:t> text edit: {diff!r}"
    )
    assert diff.document_structure_changed is True


def test_flagship_docx_child_downloads_docx_native_with_styles_byte_identical(
    client, auth_headers,
):
    """DOCX end-to-end: an uploaded styled .docx tailored for a job downloads as
    a .docx (never the branded PDF), byte-identical outside the one reworded run.

    ``item 4`` of the mandate — "prefer DOCX preservation when the original is
    DOCX" — proved on the produced artifacts with the §4 structural diff.
    """
    from app.repositories.resume import ResumeRepository
    from app.services.format_diff import compare_docx_structure

    me = client.get("/auth/me", headers=auth_headers).json()
    upload = client.post(
        "/resumes/upload",
        files={"file": ("jordan_resume.docx", _make_styled_docx(_DOCX_PARAGRAPHS), _DOCX_CONTENT_TYPE)},
        data={"extract_stories": "false"},
        headers=auth_headers,
    )
    assert upload.status_code == 201, upload.text
    baseline = upload.json()
    assert any(
        b["text"].strip() == _DOCX_ORIGINAL_BULLET for b in baseline["sections"]["bullets"]
    ), baseline["sections"]["bullets"]

    repo = ResumeRepository()
    child_sections = dict(baseline["sections"])
    child_sections["bullets"] = [
        {
            "text": _DOCX_TAILORED_BULLET
            if b["text"].strip() == _DOCX_ORIGINAL_BULLET
            else b["text"],
            "evidenceRef": b.get("evidenceRef"),
        }
        for b in baseline["sections"]["bullets"]
    ]
    child = repo.create(
        me["id"],
        child_sections,
        baseline["formatHash"],
        label="Tailored — Platform Engineer @ Atlassian",
        version=repo.next_version(me["id"]),
        parent_id=baseline["id"],
    )

    fidelity = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers).json()
    assert fidelity["method"] == "docx-native", fidelity
    assert fidelity["formatPreserved"] is True, fidelity

    base_dl = client.get(f"/resumes/{baseline['id']}/download", headers=auth_headers)
    child_dl = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert base_dl.status_code == 200 and child_dl.status_code == 200
    assert child_dl.headers["content-type"].startswith(_DOCX_CONTENT_TYPE)
    assert child_dl.headers["X-Aether-Format-Method"] == "docx-native"

    # The base download is the user's own stored .docx, verbatim.
    assert base_dl.content == _make_styled_docx(_DOCX_PARAGRAPHS)

    # The child is that same package with ONLY the reworded run's <w:t> changed:
    # styles / numbering / theme / fonts byte-identical, structure untouched.
    diff = compare_docx_structure(base_dl.content, child_dl.content)
    assert diff.styles_preserved is True, diff
    assert diff.document_structure_changed is False, diff

    from docx import Document

    text = "\n".join(p.text for p in Document(BytesIO(child_dl.content)).paragraphs)
    assert _DOCX_TAILORED_BULLET in text
    assert _DOCX_ORIGINAL_BULLET not in text
