"""RFMT-2 — the employer-facing résumé download carries NO diff highlight.

THE DEFECT (MODELS-LIVE, ``uat/reports/evidence/models-live/resume-format/``).
The in-place splice draws a peach wash behind every bullet it rewords, and it
drew it *unconditionally*: ``GET /resumes/{id}/download`` — the file a
subscriber sends to an employer — shipped with the tint on. An independent peer
sweep of a live 3-page tailored download found the wash on NINE bullets across
ALL THREE pages (p1:2, p2:6, p3:1). A recruiter opening that PDF sees an
annotated draft, not a résumé.

THE RULING. The tint is a *studio* affordance: it tells the subscriber which
lines the tailoring reworded. It is not part of the document. So the render is
CLEAN by default and the tint is reachable only when a caller explicitly asks
for the preview variant (``?diff=true``), which Résumé Studio uses and the
Download button does not.

WHAT THESE TESTS PIN.

1. **Absence, not transparency.** The default render must draw NO highlight
   shape at all — zero shape objects filled with ``_HIGHLIGHT_RGB`` on ANY page.
   An opacity-0 rectangle would still put the peach fill in the bytes (and a
   future opacity change would put it back on the page); it is not a fix.
2. **Globally.** The count is taken over EVERY page, so a fix that only cleans
   page 1 (where a one-bullet fixture happens to land) fails here.
3. **The preview still works.** ``highlight=True`` / ``?diff=true`` still draws
   the peach wash, with the same colour and opacity constants as before.
4. **Nothing else moved.** The clean download is still the user's own
   two-column layout, spliced in place, pixel-identical outside the reworded
   bullets, with the tailored wording genuinely in the file and the whole
   document still present.

The acceptance in (2) is proved twice over: once structurally (no shape object
in the PDF), and once by RASTERISING EVERY PAGE and proving the clean render
adds no peach pixel anywhere that the pristine source did not already have —
the same thing a human sees when they open the file.
"""
from __future__ import annotations

import hashlib

import numpy as np
from test_u2b_fidelity_verification import (  # noqa: E402
    _bundled_pdf,
    _pdf_text,
    _user_id,
)

# --- Highlight detection ----------------------------------------------------


def _highlight_shapes_per_page(data: bytes | object) -> list[int]:
    """Per-page count of drawn shapes filled with the peach diff highlight.

    Reads the produced document's OWN drawing objects (PyMuPDF
    ``page.get_drawings()``), so this measures what is IN the file, not what a
    renderer intended. A suppression implemented as "draw it at opacity 0"
    still lands a ``_HIGHLIGHT_RGB``-filled path here and still fails.
    """
    import fitz

    from app.services.resume_pdf import _HIGHLIGHT_RGB

    doc = (
        fitz.open(stream=bytes(data), filetype="pdf")
        if isinstance(data, (bytes, bytearray))
        else fitz.open(data)
    )
    try:
        counts: list[int] = []
        for page in doc:
            found = 0
            for drawing in page.get_drawings():
                fill = drawing.get("fill")
                if fill and len(fill) == 3 and max(
                    abs(a - b) for a, b in zip(fill, _HIGHLIGHT_RGB)
                ) <= 0.004:
                    found += 1
            counts.append(found)
        return counts
    finally:
        doc.close()


def _coral_wash_shapes(data: bytes) -> int:
    """Count of shapes filled with the BRANDED renderer's coral change wash.

    The branded template is a download path too — every branch that cannot
    preserve the user's own document falls back to it — so the same rule applies
    there: unmarked by default, washed only for the preview.
    """
    import fitz

    from app.services.resume_pdf import _CHANGE_HEX

    target = (
        int(_CHANGE_HEX[1:3], 16) / 255,
        int(_CHANGE_HEX[3:5], 16) / 255,
        int(_CHANGE_HEX[5:7], 16) / 255,
    )
    doc = fitz.open(stream=bytes(data), filetype="pdf")
    try:
        return sum(
            1
            for page in doc
            for drawing in page.get_drawings()
            if drawing.get("fill")
            and len(drawing["fill"]) == 3
            and max(abs(a - b) for a, b in zip(drawing["fill"], target)) <= 0.004
        )
    finally:
        doc.close()


def _peach_masks(data: bytes | object, zoom: float = 2.0) -> list[np.ndarray]:
    """Per-page boolean raster masks of pixels that READ as the peach highlight.

    Two targets are matched: the fill colour itself, and the colour it
    composites to over white at ``_HIGHLIGHT_OPACITY`` (what the wash actually
    looks like on the page). Page order is preserved and every page is scanned,
    so this is page-count-independent by construction.
    """
    import fitz

    from app.services.resume_pdf import _HIGHLIGHT_OPACITY, _HIGHLIGHT_RGB

    pure = np.array([round(c * 255) for c in _HIGHLIGHT_RGB], dtype=np.int16)
    over_white = np.array(
        [
            round((1.0 - _HIGHLIGHT_OPACITY) * 255 + _HIGHLIGHT_OPACITY * c * 255)
            for c in _HIGHLIGHT_RGB
        ],
        dtype=np.int16,
    )

    doc = (
        fitz.open(stream=bytes(data), filetype="pdf")
        if isinstance(data, (bytes, bytearray))
        else fitz.open(data)
    )
    try:
        masks: list[np.ndarray] = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            arr = (
                np.frombuffer(pix.samples, dtype=np.uint8)
                .reshape(pix.height, pix.width, pix.n)[:, :, :3]
                .astype(np.int16)
            )
            mask = np.zeros(arr.shape[:2], dtype=bool)
            for target in (pure, over_white):
                mask |= np.abs(arr - target).max(axis=2) <= 4
            masks.append(mask)
        return masks
    finally:
        doc.close()


# --- Fixtures: a rewrite on EVERY page of the bundled two-column résumé ------


def _bullet_per_page() -> list[str]:
    """One right-column work bullet from EACH page of the bundled résumé.

    Read through the splice engine's own block detection, so every returned
    bullet is one the engine can genuinely place — a rewrite of all three lands
    a highlight on all three pages under the old unconditional draw, which is
    exactly the multi-page condition the peer sweep found live.
    """
    import fitz

    from app.services.resume_pdf import _detect_blocks

    doc = fitz.open(_bundled_pdf())
    try:
        picked: list[str] = []
        for index in range(len(doc)):
            blocks = [
                b for b in _detect_blocks(doc[index])
                if len(b["full_text"].strip()) > 60
            ]
            assert blocks, f"fixture sanity: page {index} must carry a work bullet"
            picked.append(" ".join(blocks[0]["full_text"].split()))
    finally:
        doc.close()
    assert len(picked) >= 3, "fixture sanity: the bundled résumé is multi-page"
    return picked


def _bundled_name() -> str:
    """The person's OWN name, read off the bundled résumé's header.

    The completeness contract requires the produced file to still carry the
    name (U2b round-2: the live render shipped "VIKRAM" with the surname eaten),
    so a fixture baseline has to declare the name the document actually shows —
    read from the document rather than hard-coded, like every other fixture here.
    """
    import fitz

    from app.services.resume_pdf import _RIGHT_COL_MIN_X

    doc = fitz.open(_bundled_pdf())
    try:
        rows: list[tuple[float, str]] = []
        for block in doc[0].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                if not spans or min(s["bbox"][0] for s in spans) >= _RIGHT_COL_MIN_X:
                    continue
                text = " ".join("".join(s["text"] for s in spans).split())
                if text:
                    rows.append((line["bbox"][1], text))
    finally:
        doc.close()
    rows.sort()
    parts = [text for _y, text in rows[:2] if text.isupper() and len(text) <= 20]
    assert len(parts) == 2, f"fixture sanity: expected a two-line name header, got {rows[:2]}"
    return " ".join(parts)


def _rewrite(text: str) -> str:
    """A reworded bullet that keeps the original's bold lead-in structure."""
    head, sep, tail = text.partition(":")
    if sep:
        return f"{head}: Re-scoped for the target role, {tail.strip()}"
    return f"Re-scoped for the target role, {text}"


def _all_page_changes() -> list[tuple[str, str]]:
    return [(bullet, _rewrite(bullet)) for bullet in _bullet_per_page()]


def _seed_multipage_baseline(client, auth_headers) -> tuple[dict, list[str]]:
    """A baseline whose formatHash matches the bundled PDF, one bullet per page."""
    from app.repositories.resume import ResumeRepository

    bullets = _bullet_per_page()
    name = _bundled_name()
    user_id = _user_id(client, auth_headers)
    repo = ResumeRepository()
    baseline = repo.create(
        user_id,
        {
            "raw_text": "\n".join([name, *bullets]),
            "bullets": [
                {"text": text, "evidenceRef": f"bullet-{i}"}
                for i, text in enumerate(bullets)
            ],
            "contact": {"name": name},
        },
        hashlib.sha256(_bundled_pdf().read_bytes()).hexdigest(),
        label="Baseline — bundled layout (all pages)",
        version=repo.next_version(user_id),
    )
    return baseline, bullets


def _tailor_all_pages(client, auth_headers, baseline: dict, bullets: list[str]) -> dict:
    from app.repositories.resume import ResumeRepository

    user_id = _user_id(client, auth_headers)
    repo = ResumeRepository()
    sections = dict(baseline["sections"])
    sections["bullets"] = [
        {"text": _rewrite(text), "evidenceRef": f"bullet-{i}"}
        for i, text in enumerate(bullets)
    ]
    return repo.create(
        user_id,
        sections,
        baseline["formatHash"],
        label="Tailored — every page reworded",
        version=repo.next_version(user_id),
        parent_id=baseline["id"],
    )


# ---------------------------------------------------------------------------
# (a) The default render draws NO highlight shape — on ANY page
# ---------------------------------------------------------------------------


def test_pristine_source_carries_no_highlight_shape():
    """Control: the untouched résumé has no peach wash, so a hit is the splice's."""
    assert _highlight_shapes_per_page(_bundled_pdf()) == [0, 0, 0]


def test_default_tailored_render_draws_no_highlight_shape_on_any_page():
    """The DOWNLOAD render must not draw the wash at all — absence, not opacity 0."""
    from app.services.resume_pdf import render_tailored_pdf

    changes = _all_page_changes()
    clean = render_tailored_pdf(_bundled_pdf(), changes)

    # Not vacuous: the splice really did rewrite bullets on every page.
    text = " ".join(_pdf_text(clean).split())
    for _before, after in changes:
        assert after.partition(":")[2].strip()[:45] in text, (
            "fixture sanity: every rewrite must actually be spliced in"
        )

    per_page = _highlight_shapes_per_page(clean)
    assert per_page == [0] * len(per_page), (
        "the employer-facing render must contain NO highlight shape on any page; "
        f"found {per_page}"
    )


def test_default_tailored_render_adds_no_peach_pixel_on_any_page():
    """ACCEPTANCE: rasterise EVERY page — no peach pixel the source did not have."""
    from app.services.resume_pdf import render_tailored_pdf

    changes = _all_page_changes()
    clean = render_tailored_pdf(_bundled_pdf(), changes)

    source_masks = _peach_masks(_bundled_pdf())
    clean_masks = _peach_masks(clean)
    assert len(clean_masks) == len(source_masks) == 3

    for index, (source, rendered) in enumerate(zip(source_masks, clean_masks)):
        added = int(np.count_nonzero(rendered & ~source))
        assert added == 0, (
            f"page {index + 1} of the employer-facing download carries {added} "
            "peach-tinted pixels the pristine résumé does not have"
        )


def test_the_raster_acceptance_would_catch_the_tint():
    """The scan is not trivially empty: the preview variant DOES light it up."""
    from app.services.resume_pdf import render_tailored_pdf

    changes = _all_page_changes()
    tinted = render_tailored_pdf(_bundled_pdf(), changes, highlight=True)

    source_masks = _peach_masks(_bundled_pdf())
    tinted_masks = _peach_masks(tinted)
    for index, (source, rendered) in enumerate(zip(source_masks, tinted_masks)):
        added = int(np.count_nonzero(rendered & ~source))
        assert added > 500, (
            f"page {index + 1} of the PREVIEW variant must carry the peach wash; "
            f"only {added} tinted pixels found"
        )


# ---------------------------------------------------------------------------
# (b) The preview variant KEEPS the highlight
# ---------------------------------------------------------------------------


def test_preview_render_still_draws_the_highlight_with_the_same_palette():
    from app.services.resume_pdf import _HIGHLIGHT_OPACITY, _HIGHLIGHT_RGB, render_tailored_pdf

    tinted = render_tailored_pdf(_bundled_pdf(), _all_page_changes(), highlight=True)
    per_page = _highlight_shapes_per_page(tinted)
    assert sum(per_page) > 0, per_page
    assert all(count > 0 for count in per_page), (
        f"every page with a rewrite keeps its wash in preview mode: {per_page}"
    )

    # The palette itself is untouched — this slice changes WHEN the wash is
    # drawn, never what it looks like.
    assert _HIGHLIGHT_RGB == (0.996, 0.906, 0.875)
    assert _HIGHLIGHT_OPACITY == 0.55


def test_branded_render_is_clean_by_default_and_washed_on_request():
    """The branded fallback is a download path too — it must obey the same rule."""
    from app.services.resume_pdf import create_branded_resume_pdf

    before = "Delivered the payments platform migration on schedule."
    after = "Delivered the payments platform migration two weeks early."
    args = (
        "JANE SMITH",
        "Delivery Manager",
        "",
        [{"heading": "WORK EXPERIENCE", "bullets": [after]}],
        [(before, after)],
    )

    clean = create_branded_resume_pdf(*args)
    tinted = create_branded_resume_pdf(*args, highlight=True)

    assert _coral_wash_shapes(clean) == 0, "the branded download must carry no coral wash"
    assert _coral_wash_shapes(tinted) > 0, "the branded preview must keep the coral wash"


# ---------------------------------------------------------------------------
# (a+b) End to end: /download is clean, ?diff=true is the preview
# ---------------------------------------------------------------------------


def test_download_endpoint_is_clean_on_every_page(client, auth_headers):
    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)

    download = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert download.status_code == 200, download.text
    assert download.headers["X-Aether-Format-Method"] == "pdf-in-place-splice"

    per_page = _highlight_shapes_per_page(download.content)
    assert per_page == [0] * len(per_page), (
        f"GET /resumes/{{id}}/download must ship a tint-free file; found {per_page}"
    )

    source_masks = _peach_masks(_bundled_pdf())
    for index, (source, rendered) in enumerate(
        zip(source_masks, _peach_masks(download.content))
    ):
        assert int(np.count_nonzero(rendered & ~source)) == 0, (
            f"page {index + 1} of the download raster carries the peach wash"
        )


def test_in_process_attachment_render_carries_no_diff_marking(client, auth_headers):
    """The résumé EMAILED to an employer goes through this very handler.

    ``services/email_attachments.py`` calls ``download_resume(resume_id, user)``
    IN PROCESS — no FastAPI dependency resolution — so a query parameter arrives
    as its ``Query`` object, which is TRUTHY. A naive ``highlight=diff`` would
    therefore turn the diff preview ON for every emailed / auto-submitted
    résumé: the one document with the least excuse for carrying diff marking,
    since the recipient is the employer and the subscriber never sees it.
    """
    from app.routers.resumes import download_resume

    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)
    me = client.get("/auth/me", headers=auth_headers).json()

    attachment = bytes(download_resume(child["id"], me).body)
    per_page = _highlight_shapes_per_page(attachment)
    assert per_page == [0] * len(per_page), (
        f"the emailed résumé must carry no peach wash on any page; found {per_page}"
    )
    assert _coral_wash_shapes(attachment) == 0, (
        "the emailed résumé must carry no coral wash either"
    )


def test_download_diff_query_returns_the_preview_variant(client, auth_headers):
    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)

    preview = client.get(
        f"/resumes/{child['id']}/download?diff=true", headers=auth_headers
    )
    assert preview.status_code == 200, preview.text
    per_page = _highlight_shapes_per_page(preview.content)
    assert sum(per_page) > 0, (
        f"?diff=true is the Studio preview affordance and must keep the wash: {per_page}"
    )


# ---------------------------------------------------------------------------
# (c) Format preservation, redaction and completeness are UNCHANGED
# ---------------------------------------------------------------------------


def test_clean_download_still_preserves_the_two_column_layout(client, auth_headers):
    """The tint is removed; nothing else about the splice is.

    Same page count, same geometry, pixel-identical outside the reworded
    bullets, tailored wording genuinely in the file, whole document present.
    """
    import fitz

    from app.services.format_diff import compare_pdf_layout, compare_pdf_text_spans
    from app.services.resume_pdf import _RIGHT_MARGIN, _detect_blocks, _normalize

    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)

    base_dl = client.get(f"/resumes/{baseline['id']}/download", headers=auth_headers)
    child_dl = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert base_dl.status_code == 200 and child_dl.status_code == 200

    keys = {_normalize(b) for b in bullets}
    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    doc = fitz.open(_bundled_pdf())
    try:
        for index in range(len(doc)):
            for block in _detect_blocks(doc[index]):
                if _normalize(block["full_text"]) in keys:
                    boxes.setdefault(index, []).append((
                        block["x0"] - 4.0,
                        block["top"] - 4.0,
                        _RIGHT_MARGIN + 4.0,
                        block["bottom"] + 8.0,
                    ))
    finally:
        doc.close()
    assert len(boxes) == 3, f"fixture sanity: a reworded slot on every page: {boxes}"

    layout = compare_pdf_layout(base_dl.content, child_dl.content, change_boxes=boxes)
    assert layout.same_page_count and layout.same_geometry, layout
    assert layout.preserved is True, layout
    spans = compare_pdf_text_spans(
        base_dl.content, child_dl.content, change_boxes=boxes
    )
    assert spans.identical, spans

    text = " ".join(_pdf_text(child_dl.content).split())
    for bullet in bullets:
        assert _rewrite(bullet).partition(":")[2].strip()[:45] in text, text[:400]

    fidelity = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers).json()
    assert fidelity["formatPreserved"] is True, fidelity
    assert fidelity["changesApplied"] == 3, fidelity
    assert fidelity["changesDropped"] == 0, fidelity
    assert child_dl.headers["X-Aether-Content-Complete"] != "false", child_dl.headers


def test_fidelity_report_describes_the_file_download_actually_ships(
    client, auth_headers
):
    """The report and the file cannot disagree: both default to the clean render."""
    baseline, bullets = _seed_multipage_baseline(client, auth_headers)
    child = _tailor_all_pages(client, auth_headers, baseline, bullets)

    report = client.get(f"/resumes/{child['id']}/fidelity", headers=auth_headers)
    download = client.get(f"/resumes/{child['id']}/download", headers=auth_headers)
    assert report.status_code == 200 and download.status_code == 200
    body = report.json()
    assert body["changesApplied"] == int(download.headers["X-Aether-Changes-Applied"])
    assert body["changesDropped"] == int(download.headers["X-Aether-Changes-Dropped"])
    assert body["method"] == download.headers["X-Aether-Format-Method"]
