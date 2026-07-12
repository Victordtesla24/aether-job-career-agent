"""Format-preserving resume PDF generation (P3).

The base resume (``assets/resume/Vik_Resume_Final.pdf``) has a bespoke
two-column layout: a peach title panel and coral section-header icons on a
left contact/skills rail, with wrapping work-experience bullets on the right.
Reproducing that from scratch (Story/reportlab) can never be pixel-exact — the
embedded ``HelveticaNeue`` subset, the drawn icons, and the panel geometry are
impossible to reconstruct faithfully.

So a tailored PDF is produced by **editing the original document in place**
with PyMuPDF instead of rebuilding it:

- Everything except the reworded bullets — name, panel, icons, contact rail,
  skills, section headers, job titles, companies, dates, and every *unchanged*
  bullet — is never touched, so it stays byte-for-byte identical to the source.
- For each *changed* work bullet we redact only that bullet's text box (the
  coral ``•`` marker and all surrounding chrome are left intact), then
  re-render the reworded text at the exact same origin, size, leading and
  bold-lead-in/grey-body structure, with a subtle peach highlight behind it.

The measurements below (``_RIGHT_MARGIN``, ``_LINE_PITCH``, the colour tuples,
the body-line font-size band) were read straight off the source PDF with
``page.get_text("dict")`` — see the module tests for the calibration.

The source file itself is READ-ONLY and never written to: all edits happen on
an in-memory copy whose bytes are streamed back to the caller.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from app.agents.fit_scorer import get_base_resume_path

# --- Layout constants, measured from Vik_Resume_Final.pdf --------------------
#: Right content edge for the work-experience column (page width 612 − 36pt
#: margin). Bullet text wraps here.
_RIGHT_MARGIN = 576.0
#: Baseline-to-baseline pitch of wrapped bullet lines.
_LINE_PITCH = 13.5
#: Left x below which spans are chrome / the left rail, never a work bullet.
_RIGHT_COL_MIN_X = 225.0
#: Bullet body text starts at this indent (marker sits ~10pt to its left).
_BODY_X_MIN, _BODY_X_MAX = 238.0, 247.0
#: Body font size (both bold lead-in and grey body render at this size).
_BODY_SIZE = 8.7
#: Fallback sizes tried when reworded text would overflow a bullet's slot.
_FIT_SIZES = (8.7, 8.4, 8.1, 7.8, 7.5)

#: Coral bullet marker colour (rgb ≈ 244,113,92) and match tolerance.
_CORAL = (0.957, 0.443, 0.361)
_CORAL_TOL = 0.08
#: Bold lead-in colour (≈ #2B2B2B) and grey body colour (≈ #4D4D4D).
_BOLD_RGB = (0.169, 0.169, 0.169)
_BODY_RGB = (0.302, 0.302, 0.302)
#: Subtle peach wash drawn behind a changed bullet.
_HIGHLIGHT_RGB = (0.996, 0.906, 0.875)
_HIGHLIGHT_OPACITY = 0.55

_MARKERS = ("•", "●", "▪")
#: Unicode punctuation folded before matching a stored bullet to a PDF block,
#: so curly quotes / en-dashes in one source don't defeat an exact match.
_PUNCT_FOLD = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', " ": " ",
})


def resolve_original_pdf(format_hash: str | None) -> Path:
    """Return the bundled resume asset whose bytes match ``format_hash``.

    The ``formatHash`` on a resume record is the SHA-256 of the source PDF, so
    it uniquely identifies which bundled asset (the main resume vs the BA
    variant) a version derives from. Falls back to the canonical base resume
    when the hash matches nothing on disk (e.g. an externally-ingested variant
    with no bundled file).
    """
    default = get_base_resume_path()
    if not format_hash:
        return default
    assets_dir = default.parent
    for pdf in sorted(assets_dir.glob("*.pdf")):
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest == format_hash or digest[:16] == format_hash:
            return pdf
    return default


def _normalize(text: str) -> str:
    """Collapse whitespace and fold punctuation for tolerant text matching."""
    return " ".join(text.translate(_PUNCT_FOLD).split())


def _is_coral(color: int) -> bool:
    r, g, b = fitz.sRGB_to_pdf(color)
    return (
        abs(r - _CORAL[0]) < _CORAL_TOL
        and abs(g - _CORAL[1]) < _CORAL_TOL
        and abs(b - _CORAL[2]) < _CORAL_TOL
    )


def _detect_blocks(page: Any) -> list[dict[str, Any]]:
    """Detect right-column work-experience bullet blocks on ``page``.

    Each block is a coral ``•`` marker plus its wrapped body lines. Left-rail
    list items, section headers, job titles, companies and date lines are all
    excluded by column (x ≥ 225) and by the body font-size band, so the marker
    and every non-bullet element stay untouched.
    """
    marker_tops: list[float] = []
    text_lines: list[dict[str, Any]] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            if not spans:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            if x0 < _RIGHT_COL_MIN_X:
                continue
            raw = "".join(s["text"] for s in spans)
            top = min(s["bbox"][1] for s in spans)
            if raw.strip() in _MARKERS and _is_coral(spans[0]["color"]):
                marker_tops.append(top)
                continue
            size = max(s["size"] for s in spans)
            if not (_BODY_SIZE - 0.3 <= size <= _BODY_SIZE + 0.3):
                continue
            if not (_BODY_X_MIN <= x0 <= _BODY_X_MAX):
                continue
            text_lines.append({
                "x0": x0,
                "top": top,
                "bottom": max(s["bbox"][3] for s in spans),
                "baseline": spans[0]["origin"][1],
                "text": " ".join(raw.split()),
                "spans": spans,
            })
    marker_tops.sort()
    text_lines.sort(key=lambda ln: ln["top"])

    blocks: list[dict[str, Any]] = []
    for i, mtop in enumerate(marker_tops):
        nxt = marker_tops[i + 1] if i + 1 < len(marker_tops) else 1e9
        group = [ln for ln in text_lines if mtop - 4 <= ln["top"] < nxt - 4]
        if not group:
            continue
        # Stop at a large vertical gap so the final bullet of a job group can't
        # bleed into the next job's title/company/date.
        kept = [group[0]]
        for ln in group[1:]:
            if ln["top"] - kept[-1]["bottom"] > 12:
                break
            kept.append(ln)
        first = kept[0]
        prefix = ""
        for span in first["spans"]:
            if "Bold" in span["font"]:
                prefix += span["text"]
            else:
                break
        blocks.append({
            "first_line": first["text"],
            "full_text": " ".join(ln["text"] for ln in kept),
            "prefix": _normalize(prefix),
            "x0": min(ln["x0"] for ln in kept),
            "top": min(mtop, first["top"]),
            "bottom": kept[-1]["bottom"],
            "baseline": first["baseline"],
            "next_top": nxt,
        })
    return blocks


def _wrap(font: Any, size: float, words: list[str], width: float) -> list[str]:
    """Greedy word-wrap ``words`` to ``width`` at ``size`` using ``font``."""
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or font.text_length(trial, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _render_block(
    block: dict[str, Any],
    new_full: str,
    *,
    reg: Any,
    bold: Any,
    highlight: Any,
    font_reg: Any,
    font_bold: Any,
) -> None:
    """Draw ``new_full`` into ``block``'s slot with a highlight behind it.

    The reworded text keeps the original bold lead-in ("Prefix:") in the dark
    weight and the remainder in grey, wrapped at the original width and placed
    on the original baseline/pitch. If it would overflow the bullet's vertical
    slot the font is stepped down so nothing below shifts.
    """
    x0 = block["x0"]
    width = _RIGHT_MARGIN - x0
    prefix = block["prefix"]
    if not (prefix and _normalize(new_full).startswith(prefix)):
        prefix = ""
    # Split the *rendered* text so bold covers exactly the lead-in characters.
    prefix_len = len(prefix)

    available = block["next_top"] - 4 - block["top"]
    lines: list[str] = []
    size = _BODY_SIZE
    for size in _FIT_SIZES:
        lines = _wrap(font_reg, size, new_full.split(), width)
        if (len(lines) - 1) * _LINE_PITCH + size <= available:
            break

    bottom = block["baseline"] + (len(lines) - 1) * _LINE_PITCH + size * 0.3
    highlight.draw_rect(fitz.Rect(x0 - 2, block["top"] - 1.5, _RIGHT_MARGIN + 1, bottom))

    consumed = 0
    for row, line in enumerate(lines):
        y = block["baseline"] + row * _LINE_PITCH
        x = x0
        line_start, line_end = consumed, consumed + len(line)
        if prefix_len > line_start:
            split = min(prefix_len, line_end) - line_start
            head, tail = line[:split], line[split:]
            if head:
                bold.append((x, y), head, font=font_bold, fontsize=size)
                x += font_bold.text_length(head, size)
            if tail:
                reg.append((x, y), tail, font=font_reg, fontsize=size)
        else:
            reg.append((x, y), line, font=font_reg, fontsize=size)
        consumed = line_end + 1  # +1 for the single space dropped by wrapping


def render_tailored_pdf(original_path: Path, changes: list[tuple[str, str]]) -> bytes:
    """Return format-preserving PDF bytes for a tailored resume.

    ``changes`` is a list of ``(before, after)`` pairs — the original and
    reworded first-line fragment of each bullet whose text changed. Each pair
    is matched to a work bullet in ``original_path`` by its first line; the
    reworded fragment is spliced onto the bullet's original continuation, and
    only that bullet is redrawn. Pairs that don't match a work bullet (e.g.
    left-rail skills, or bullets mangled by two-column text extraction) are
    skipped, leaving the original untouched. With no matching changes the
    pristine source bytes are returned.
    """
    doc = fitz.open(original_path)
    try:
        # Index every work bullet by its normalized first line.
        index: dict[str, tuple[int, dict[str, Any]]] = {}
        for page_index in range(len(doc)):
            for block in _detect_blocks(doc[page_index]):
                index.setdefault(_normalize(block["first_line"]), (page_index, block))

        # Resolve each change to a (page, block, new_full_text) edit.
        edits: dict[int, list[tuple[dict[str, Any], str]]] = {}
        for before, after in changes:
            key = _normalize(before)
            match = index.get(key)
            if match is None:
                match = next(
                    (v for k, v in index.items()
                     if len(key) >= 20 and (k.startswith(key) or key.startswith(k))),
                    None,
                )
            if match is None:
                continue
            page_index, block = match
            new_full = after + block["full_text"][len(block["first_line"]):]
            edits.setdefault(page_index, []).append((block, new_full))

        for page_index, page_edits in edits.items():
            page = doc[page_index]
            for block, _ in page_edits:
                page.add_redact_annot(
                    fitz.Rect(block["x0"] - 1, block["top"] - 1.5,
                              _RIGHT_MARGIN + 1, block["bottom"] + 2),
                    fill=(1, 1, 1),
                )
            page.apply_redactions()

            highlight = page.new_shape()
            reg = fitz.TextWriter(page.rect, color=_BODY_RGB)
            bold = fitz.TextWriter(page.rect, color=_BOLD_RGB)
            font_reg, font_bold = fitz.Font("helv"), fitz.Font("hebo")
            for block, new_full in page_edits:
                _render_block(
                    block, new_full,
                    reg=reg, bold=bold, highlight=highlight,
                    font_reg=font_reg, font_bold=font_bold,
                )
            highlight.finish(fill=_HIGHLIGHT_RGB, color=None, fill_opacity=_HIGHLIGHT_OPACITY)
            highlight.commit(overlay=True)  # over the redacted white, under text
            reg.write_text(page)
            bold.write_text(page)

        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
