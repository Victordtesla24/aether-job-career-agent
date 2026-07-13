"""GAP-P4-044 / GAP-P4-046 — tailored-PDF layout integrity.

Two properties of the format-preserving renderer:

- **No duplicated/dangling text (GAP-P4-044):** ``after`` is the complete
  reworded bullet and replaces the whole bullet. The previous renderer spliced
  ``after`` onto the original bullet's continuation, dangling and duplicating
  text.
- **No cross-bullet overlap (GAP-P4-046):** a rewrite that runs longer than the
  original must be stepped down to fit the original bullet's box, never render
  on top of the next bullet or job header.
"""
from __future__ import annotations

from typing import Any

import fitz

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_pdf import _detect_blocks, render_tailored_pdf

_RIGHT_COL_MIN_X = 225.0


def _rendered_rows(page: Any) -> list[dict[str, float]]:
    """Group right-column text spans into visual rows keyed by baseline.

    The renderer draws a bullet's bold lead-in and grey body as two separate
    text objects sharing one baseline, so span-level ``get_text`` reports them
    as distinct "lines"; regrouping by baseline reconstructs true visual rows
    for an honest top/bottom overlap check.
    """
    spans = [
        s
        for block in page.get_text("dict")["blocks"]
        for line in block.get("lines", [])
        for s in line["spans"]
        if s["bbox"][0] >= _RIGHT_COL_MIN_X and s["text"].strip()
    ]
    spans.sort(key=lambda s: (round(s["origin"][1], 1), s["bbox"][0]))
    rows: list[dict[str, float]] = []
    for s in spans:
        baseline = s["origin"][1]
        if rows and abs(rows[-1]["baseline"] - baseline) <= 2.5:
            rows[-1]["top"] = min(rows[-1]["top"], s["bbox"][1])
            rows[-1]["bottom"] = max(rows[-1]["bottom"], s["bbox"][3])
            rows[-1]["text"] = str(rows[-1]["text"]) + s["text"]
        else:
            rows.append(
                {
                    "baseline": baseline,
                    "top": s["bbox"][1],
                    "bottom": s["bbox"][3],
                    "text": s["text"],
                }
            )
    rows.sort(key=lambda r: r["top"])
    return rows


def test_rewrite_replaces_bullet_without_dangling_continuation() -> None:
    path = get_base_resume_path()
    doc = fitz.open(path)
    try:
        target = next(
            b for b in _detect_blocks(doc[1]) if "offshore" in b["full_text"]
        )
    finally:
        doc.close()

    before = target["full_text"]
    # A complete rewrite that deliberately omits the original's "offshore teams"
    # continuation. Pre-fix, that continuation was spliced back on and dangled.
    after = (
        "Delivery Leadership: Directed a $5M program portfolio, leading five "
        "delivery squads to ship high-quality releases."
    )
    pdf_bytes = render_tailored_pdf(path, [(before, after)])

    rendered = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        text = rendered[1].get_text()
    finally:
        rendered.close()

    assert "Directed a $5M program portfolio" in text
    assert text.count("Directed a $5M program portfolio") == 1
    # The dropped original continuation must not reappear (GAP-P4-044).
    assert "offshore" not in text


def test_tailored_pdf_has_no_cross_bullet_overlap() -> None:
    path = get_base_resume_path()
    doc = fitz.open(path)
    try:
        changes: list[tuple[str, str]] = []
        for page_index in range(len(doc)):
            for block in _detect_blocks(doc[page_index]):
                # Reword to a full sentence that runs LONGER than the original,
                # forcing the fit/pitch logic to keep it inside the bullet box.
                after = (
                    block["full_text"].rstrip(". ")
                    + ", delivering measurable outcomes for the business."
                )
                changes.append((block["full_text"], after))
    finally:
        doc.close()

    pdf_bytes = render_tailored_pdf(path, changes)

    rendered = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        overlaps: list[tuple[int, str, str]] = []
        for page_index in range(len(rendered)):
            rows = _rendered_rows(rendered[page_index])
            for upper, lower in zip(rows, rows[1:]):
                # A tolerance absorbs descender/ascender slack between adjacent
                # lines; a real overlap is ~10pt, far above it.
                if upper["bottom"] > lower["top"] + 1.5:
                    overlaps.append(
                        (page_index, str(upper["text"])[:40], str(lower["text"])[:40])
                    )
    finally:
        rendered.close()

    assert not overlaps, f"overlapping bullet rows in tailored PDF: {overlaps}"
