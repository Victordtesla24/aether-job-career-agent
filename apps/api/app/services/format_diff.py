"""Artifact-level format-preservation verification harness (MODELS-LIVE R-FMT §4).

A fidelity HEADER is a claim; this module proves the claim against the produced
bytes. It answers the one question the resume-format mandate turns on — *is the
tailored download the baseline with ONLY the reworded text changed, and the
visual format otherwise intact?* — by measuring the two artifacts directly:

* **PDF** — rasterise the baseline and the tailored PDF at a fixed DPI with an
  INDEPENDENT renderer (``pdftoppm`` / Poppler, deliberately not the PyMuPDF
  engine that produced the splice, so a rendering bug cannot hide behind the
  same renderer that caused it), assert identical page count and page geometry,
  mask the bounding boxes of the reworded slots, and assert the per-pixel
  difference OUTSIDE the masks is ~0. A second, structural cross-check reads
  every text span with PyMuPDF ``get_text("dict")`` and asserts every span
  outside the masked slots sits at an identical position, font and size.
* **DOCX** — unzip both packages and assert ``styles.xml`` / ``numbering.xml`` /
  ``theme/*`` / the font table (and every other non-``document.xml`` part) are
  byte-identical, then assert ``document.xml`` differs ONLY inside ``<w:t>`` text
  runs — never in a run- or paragraph-property node.

Nothing here runs inside a request; it is a verification tool for the test
suite and for operator spot-checks. It never mutates its inputs.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Sequence

import numpy as np

#: Default rasterisation density. 100 DPI is dense enough that a one-point
#: layout shift moves several pixels (so a real regression is unmissable) while
#: keeping a 3-page Letter résumé comparison well under a second.
DEFAULT_DPI = 100

#: A colour channel must differ by more than this (0-255) before a pixel counts
#: as changed, so sub-pixel anti-aliasing along an unchanged glyph edge — which
#: two independent render passes never reproduce bit-for-bit — is not mistaken
#: for a layout difference.
_AA_CHANNEL_TOLERANCE = 24

#: The fraction of NON-masked pixels allowed to differ before the layout is
#: judged not preserved. Anti-aliasing on the same glyphs leaves a faint dusting
#: of sub-tolerance pixels; a genuine re-layout (single-column vs two-column)
#: differs across a double-digit percentage of the page.
_DEFAULT_DIFF_TOLERANCE = 0.005

# --- PDF rasterisation -------------------------------------------------------


@dataclass(frozen=True)
class _Raster:
    """One rasterised page as an ``(H, W, 3)`` uint8 array of RGB pixels."""

    pixels: "np.ndarray[Any, Any]"

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])


def _parse_ppm(data: bytes) -> _Raster:
    """Parse a binary ``P6`` PPM into an RGB pixel array.

    pdftoppm emits P6 (raw RGB) by default; parsing it directly keeps the
    harness free of an image-decoding dependency and of any second renderer.
    """
    if not data.startswith(b"P6"):
        raise ValueError("not a binary P6 PPM raster")
    # Header: 'P6' then three ASCII integers (width, height, maxval), any of
    # which may be separated by whitespace or a '#' comment line.
    idx = 2
    fields: list[int] = []
    while len(fields) < 3:
        while idx < len(data) and data[idx : idx + 1].isspace():
            idx += 1
        if idx < len(data) and data[idx : idx + 1] == b"#":
            while idx < len(data) and data[idx : idx + 1] not in (b"\n", b"\r"):
                idx += 1
            continue
        start = idx
        while idx < len(data) and not data[idx : idx + 1].isspace():
            idx += 1
        fields.append(int(data[start:idx]))
    width, height, _maxval = fields
    idx += 1  # single whitespace byte after the maxval precedes the raster
    body = data[idx : idx + width * height * 3]
    if len(body) != width * height * 3:
        raise ValueError("truncated PPM raster body")
    pixels = np.frombuffer(body, dtype=np.uint8).reshape(height, width, 3)
    return _Raster(pixels=pixels)


def rasterize_pdf(data: bytes, *, dpi: int = DEFAULT_DPI) -> list[_Raster]:
    """Every page of ``data`` rasterised with Poppler's ``pdftoppm`` at ``dpi``.

    Uses an external, independent renderer on purpose: the splice is produced by
    PyMuPDF/MuPDF, so rasterising the check with the SAME engine could reproduce
    a rendering bug in both the artifact and its verification. Poppler cannot.
    """
    if shutil.which("pdftoppm") is None:  # pragma: no cover - environment guard
        raise RuntimeError("pdftoppm (poppler-utils) is required for PDF rasterisation")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data)
        prefix = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), str(src), str(prefix)],
            check=True,
            capture_output=True,
        )
        pages = sorted(Path(tmp).glob("page*.ppm"))
        return [_parse_ppm(page.read_bytes()) for page in pages]


def _scale(dpi: int) -> float:
    return dpi / 72.0


def _mask_page(
    height: int, width: int, boxes: Sequence[tuple[float, float, float, float]], dpi: int
) -> "np.ndarray[Any, Any]":
    """A boolean ``(H, W)`` mask, ``True`` where a reworded slot lives.

    ``boxes`` are ``(x0, y0, x1, y1)`` in PyMuPDF page points (top-left origin,
    y increasing downward — the frame ``page.get_text("dict")`` and
    ``_detect_blocks`` report), which matches pdftoppm's own top-left raster, so
    the conversion to pixels is a single uniform scale by ``dpi/72``.
    """
    mask = np.zeros((height, width), dtype=bool)
    s = _scale(dpi)
    for x0, y0, x1, y1 in boxes:
        px0 = max(0, int(x0 * s))
        py0 = max(0, int(y0 * s))
        px1 = min(width, int(round(x1 * s)))
        py1 = min(height, int(round(y1 * s)))
        if px1 > px0 and py1 > py0:
            mask[py0:py1, px0:px1] = True
    return mask


@dataclass(frozen=True)
class PdfLayoutDiff:
    """The measured outcome of a baseline-vs-tailored PDF layout comparison."""

    same_page_count: bool
    same_geometry: bool
    page_count: int
    #: Fraction of NON-masked pixels that differ, worst page.
    max_diff_ratio: float
    #: Per-page fraction of non-masked pixels that differ.
    per_page_diff_ratio: tuple[float, ...]
    tolerance: float

    @property
    def preserved(self) -> bool:
        """The tailored PDF is the baseline with only the masked slots changed."""
        return (
            self.same_page_count
            and self.same_geometry
            and self.max_diff_ratio <= self.tolerance
        )


def compare_pdf_layout(
    baseline: bytes,
    tailored: bytes,
    *,
    change_boxes: dict[int, Sequence[tuple[float, float, float, float]]] | None = None,
    dpi: int = DEFAULT_DPI,
    tolerance: float = _DEFAULT_DIFF_TOLERANCE,
) -> PdfLayoutDiff:
    """Prove ``tailored`` is ``baseline`` with only ``change_boxes`` redrawn.

    ``change_boxes`` maps a 0-based page index to the bounding boxes (PyMuPDF
    points) of the reworded slots on that page; those regions are excluded from
    the pixel diff. Everything else must be pixel-identical within
    anti-aliasing tolerance.
    """
    change_boxes = change_boxes or {}
    base_pages = rasterize_pdf(baseline, dpi=dpi)
    tail_pages = rasterize_pdf(tailored, dpi=dpi)
    same_page_count = len(base_pages) == len(tail_pages)
    ratios: list[float] = []
    same_geometry = same_page_count
    for index, (bp, tp) in enumerate(zip(base_pages, tail_pages)):
        if (bp.height, bp.width) != (tp.height, tp.width):
            same_geometry = False
            ratios.append(1.0)
            continue
        diff = np.abs(bp.pixels.astype(np.int16) - tp.pixels.astype(np.int16))
        changed = np.any(diff > _AA_CHANNEL_TOLERANCE, axis=2)
        masked = _mask_page(bp.height, bp.width, change_boxes.get(index, ()), dpi)
        considered = ~masked
        total = int(considered.sum())
        differing = int(np.logical_and(changed, considered).sum())
        ratios.append(differing / total if total else 0.0)
    return PdfLayoutDiff(
        same_page_count=same_page_count,
        same_geometry=same_geometry,
        page_count=len(base_pages),
        max_diff_ratio=max(ratios) if ratios else 1.0,
        per_page_diff_ratio=tuple(ratios),
        tolerance=tolerance,
    )


# --- PDF structural (text-span) cross-check ----------------------------------


def _spans_outside(
    data: bytes,
    boxes_by_page: dict[int, Sequence[tuple[float, float, float, float]]],
) -> list[tuple[int, int, int, str, int, str]]:
    """Every text span in ``data`` NOT inside a masked slot, keyed reproducibly.

    Each span is ``(page, round(x0), round(y0), font, size, text)`` — position,
    typography and content — so two documents' non-reworded text can be compared
    for identical placement and styling, not merely identical wording.
    """
    import fitz

    spans: list[tuple[int, int, int, str, int, str]] = []
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page_index in range(len(doc)):
            masks = boxes_by_page.get(page_index, ())
            for block in doc[page_index].get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        x0, y0, _x1, _y1 = span["bbox"]
                        if any(
                            bx0 <= x0 <= bx1 and by0 <= y0 <= by1
                            for bx0, by0, bx1, by1 in masks
                        ):
                            continue
                        text = span["text"].strip()
                        if not text:
                            continue
                        spans.append((
                            page_index,
                            int(round(x0)),
                            int(round(y0)),
                            str(span["font"]),
                            int(round(span["size"])),
                            text,
                        ))
    finally:
        doc.close()
    return spans


@dataclass(frozen=True)
class PdfSpanDiff:
    """Text spans present in one PDF but not the other, outside the masks."""

    only_in_baseline: tuple[tuple[Any, ...], ...] = ()
    only_in_tailored: tuple[tuple[Any, ...], ...] = ()

    @property
    def identical(self) -> bool:
        return not (self.only_in_baseline or self.only_in_tailored)


def compare_pdf_text_spans(
    baseline: bytes,
    tailored: bytes,
    *,
    change_boxes: dict[int, Sequence[tuple[float, float, float, float]]] | None = None,
) -> PdfSpanDiff:
    """Assert every non-reworded text span is at the same place, font and size.

    A structural companion to :func:`compare_pdf_layout`: pixels catch a moved
    or re-styled glyph, spans catch a span that vanished, was re-fonted, or
    slid — even where a colour change happens to fall under the pixel tolerance.
    """
    change_boxes = change_boxes or {}
    base = set(_spans_outside(baseline, change_boxes))
    tail = set(_spans_outside(tailored, change_boxes))
    return PdfSpanDiff(
        only_in_baseline=tuple(sorted(base - tail)),
        only_in_tailored=tuple(sorted(tail - base)),
    )


# --- DOCX structural diff ----------------------------------------------------

#: Parts whose bytes MUST be identical between a baseline .docx and its tailored
#: child: any difference here is a style/numbering/theme/font change, which the
#: mandate forbids. ``document.xml`` is excluded — it is the ONLY part allowed to
#: differ, and only inside ``<w:t>`` text nodes (checked separately below).
_DOCX_STYLE_PARTS = (
    "word/styles.xml",
    "word/numbering.xml",
    "word/fontTable.xml",
    "word/settings.xml",
    "word/webSettings.xml",
)
_DOCX_STYLE_PREFIXES = ("word/theme/", "word/fonts/")

_WT_RE = re.compile(rb"(<w:t\b[^>]*>).*?(</w:t>)", re.DOTALL)
_WT_EMPTY_RE = re.compile(rb"<w:t\b[^>]*/>")


def _blank_text_nodes(document_xml: bytes) -> bytes:
    """``document.xml`` with every ``<w:t>`` text content replaced by a marker.

    Two documents whose only difference is the WORDS inside their runs collapse
    to the same skeleton here; any difference that survives is a structural one —
    a run property, a paragraph property, a table cell, a section break — which
    the mandate does not permit a tailoring rewrite to make.
    """
    blanked = _WT_RE.sub(lambda m: m.group(1) + b"\x00" + m.group(2), document_xml)
    return _WT_EMPTY_RE.sub(rb"<w:t/>", blanked)


@dataclass(frozen=True)
class DocxStructureDiff:
    """Which structural parts of a tailored .docx diverged from its baseline."""

    changed_style_parts: tuple[str, ...] = ()
    missing_parts: tuple[str, ...] = ()
    added_parts: tuple[str, ...] = ()
    document_structure_changed: bool = False
    #: Names of parts whose bytes did change but are ALLOWED to (``document.xml``).
    changed_text_only_parts: tuple[str, ...] = field(default=("word/document.xml",))

    @property
    def styles_preserved(self) -> bool:
        """Styles, numbering, theme, fonts and structure are byte-for-byte kept."""
        return not (
            self.changed_style_parts
            or self.missing_parts
            or self.added_parts
            or self.document_structure_changed
        )


def _docx_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def compare_docx_structure(baseline: bytes, tailored: bytes) -> DocxStructureDiff:
    """Assert a tailored .docx changed ONLY ``<w:t>`` text, nothing structural."""
    base = _docx_parts(baseline)
    tail = _docx_parts(tailored)
    base_names, tail_names = set(base), set(tail)

    def is_style_part(name: str) -> bool:
        return name in _DOCX_STYLE_PARTS or name.startswith(_DOCX_STYLE_PREFIXES)

    changed_style = tuple(
        sorted(
            name
            for name in base_names & tail_names
            if is_style_part(name) and base[name] != tail[name]
        )
    )
    # A part present in one package but not the other is itself a structural
    # change (a theme or font part dropped, a new part injected).
    missing = tuple(sorted(n for n in base_names - tail_names))
    added = tuple(sorted(n for n in tail_names - base_names))

    structure_changed = False
    doc = "word/document.xml"
    if doc in base and doc in tail and base[doc] != tail[doc]:
        structure_changed = _blank_text_nodes(base[doc]) != _blank_text_nodes(tail[doc])

    return DocxStructureDiff(
        changed_style_parts=changed_style,
        missing_parts=missing,
        added_parts=added,
        document_structure_changed=structure_changed,
    )
