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
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

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
#: Fallback sizes tried, largest-first, when reworded text would overflow a
#: bullet's slot. The line pitch scales with the chosen size (see
#: :func:`_fit_text`) so stepping the font down also tightens the leading and
#: frees the vertical room a fixed pitch could not — this is what keeps a
#: longer rewrite from spilling onto the next bullet (GAP-P4-046).
_FIT_SIZES = (8.7, 8.4, 8.1, 7.8, 7.5, 7.2, 6.9, 6.6)

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
            "full_text": _join_wrapped([ln["text"] for ln in kept]),
            "prefix": _normalize(prefix),
            "x0": min(ln["x0"] for ln in kept),
            "top": min(mtop, first["top"]),
            "bottom": kept[-1]["bottom"],
            "baseline": first["baseline"],
            "next_top": nxt,
        })
    return blocks


def _join_wrapped(parts: list[str]) -> str:
    """Join a bullet's wrapped visual lines into one sentence.

    A line that wraps at a hyphenated compound leaves the hyphen dangling
    ("COBOL/mainframe test-" / "evidence automation"); rejoining those with a
    space corrupts the word ("test- evidence"). So when a part ends in a hyphen
    the next part is appended without a separator ("test-evidence"), exactly as
    the flat-text reconstruction in
    :func:`app.services.resume_tailor.extract_bullets` does; every other break
    is a single space. This is the only join defect in the positional path — the
    two-column de-interleave itself is already correct (GAP-P5-PDF).
    """
    out = ""
    for part in parts:
        if not part:
            continue
        if out.endswith("-"):
            out += part
        elif out:
            out = f"{out} {part}"
        else:
            out = part
    return out


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


def _fit_text(
    font: Any, words: list[str], width: float, available: float
) -> tuple[float, float, list[str]]:
    """Pick the largest body size (and its proportional line pitch) whose
    wrapped text fits ``available`` vertical points.

    The pitch scales with the font size (``_LINE_PITCH`` is the pitch at
    ``_BODY_SIZE``), so a reworded bullet that runs longer than the original is
    stepped down until it fits its slot instead of overrunning the next bullet
    (GAP-P4-046). If nothing in the ladder fits, the smallest size is returned —
    the tightest available packing.
    """
    size = _FIT_SIZES[-1]
    pitch = _LINE_PITCH * (size / _BODY_SIZE)
    lines: list[str] = []
    for candidate in _FIT_SIZES:
        size = candidate
        pitch = _LINE_PITCH * (candidate / _BODY_SIZE)
        lines = _wrap(font, candidate, words, width)
        if (len(lines) - 1) * pitch + size <= available:
            break
    return size, pitch, lines


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
    on the original baseline. If it would overflow the bullet's vertical slot
    the font size (and its proportional line pitch) is stepped down until it
    fits, so it never renders on top of the next bullet and nothing below
    shifts.
    """
    x0 = block["x0"]
    width = _RIGHT_MARGIN - x0
    prefix = block["prefix"]
    if not (prefix and _normalize(new_full).startswith(prefix)):
        prefix = ""
    # Split the *rendered* text so bold covers exactly the lead-in characters.
    prefix_len = len(prefix)

    # Constrain the rewrite to the space the ORIGINAL bullet occupied. Using the
    # next bullet's marker (``next_top``) overshoots for the last bullet of a
    # job group — the next job's title/company/date sits in that gap — so a long
    # rewrite would render on top of it (GAP-P4-046). The original bullet fit its
    # own box without overlapping anything, so a rewrite that also fits that box
    # is guaranteed not to overlap and not to shift anything below it.
    available = block["bottom"] - block["top"]
    size, pitch, lines = _fit_text(font_reg, new_full.split(), width, available)

    bottom = block["baseline"] + (len(lines) - 1) * pitch + size * 0.3
    highlight.draw_rect(fitz.Rect(x0 - 2, block["top"] - 1.5, _RIGHT_MARGIN + 1, bottom))

    consumed = 0
    for row, line in enumerate(lines):
        y = block["baseline"] + row * pitch
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


def extract_pdf_bullets(pdf_path: Path | str) -> list[str]:
    """Reconstruct the complete work-experience bullets of a resume PDF.

    The line-based :func:`app.services.resume_tailor.extract_bullets` reads the
    flat text stream; this prefers *positional* detection (the same column-aware
    block detection the renderer uses) so a bullet that wraps across several
    visual lines — with continuation lines interleaved with unrelated left-rail
    content — is rejoined into one complete sentence instead of being truncated
    to its first-line fragment (GAP-P4-044). Bullets come back in page /
    top-to-bottom order, with the left rail (skills / contact) excluded.

    Positional detection keys on the base resume's coral ``•`` glyph and body
    geometry. A resume drawn with different markers (e.g. the BA variant, whose
    bullets are black) yields no positional blocks; rather than return an empty
    list, this falls back to the shared flat-text reconstruction, which now
    rejoins wrapped bullets on any resume. So this never regresses to zero
    bullets for a resume that plainly has them.
    """
    doc = fitz.open(pdf_path)
    try:
        bullets: list[str] = []
        for page_index in range(len(doc)):
            for block in _detect_blocks(doc[page_index]):
                text = block["full_text"].strip()
                if text:
                    bullets.append(text)
        if bullets:
            return bullets
        flat_text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()

    # No coral/base-geometry bullets on any page — reconstruct from flat text.
    from app.services.resume_tailor import extract_bullets

    return extract_bullets(flat_text)


def render_tailored_pdf(original_path: Path, changes: list[tuple[str, str]]) -> bytes:
    """Return format-preserving PDF bytes for a tailored resume.

    ``changes`` is a list of ``(before, after)`` pairs — the original and the
    reworded text of each bullet whose text changed. Each pair is matched to a
    work bullet in ``original_path`` and that bullet is redrawn with ``after``
    in full, replacing the original text. Pairs that don't match a work bullet
    (e.g. left-rail skills) are skipped, leaving the original untouched. With no
    matching changes the pristine source bytes are returned.

    ``after`` is the *complete* reworded bullet, so it replaces the whole
    bullet. The previous implementation spliced ``after`` onto the bullet's
    original continuation, which duplicated and dangled text whenever the
    rewrite already restated that continuation (GAP-P4-044).
    """
    doc = fitz.open(original_path)
    try:
        # Index every work bullet by BOTH its full text and its first line, so a
        # stored bullet matches whether it holds the complete sentence (current
        # pipeline) or a legacy first-line fragment (pre-fix tailored data).
        index: dict[str, tuple[int, dict[str, Any]]] = {}
        for page_index in range(len(doc)):
            for block in _detect_blocks(doc[page_index]):
                index.setdefault(_normalize(block["full_text"]), (page_index, block))
                index.setdefault(_normalize(block["first_line"]), (page_index, block))

        # Resolve each change to a (page, block, after_text) edit.
        edits: dict[int, list[tuple[dict[str, Any], str]]] = {}
        edited_blocks: set[int] = set()
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
            if id(block) in edited_blocks:
                continue  # one edit per physical bullet
            edited_blocks.add(id(block))
            edits.setdefault(page_index, []).append((block, after))

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


# --- Branded two-page template (reportlab) ----------------------------------
# A from-scratch renderer for when the source PDF isn't on hand: it redraws the
# same visual language — peach title panel, coral accents, a two-column grid —
# on a blank Letter page from structured resume content. Page 1 shows the base
# bullets; page 2 the tailored ones with a coral wash behind each changed line.
# Geometry/palette are the measurements read off Vik_Resume_Final.pdf (top-
# origin points; reportlab's origin is bottom-left, so a top ``y`` maps to
# ``_PAGE_H - y``).
_PANEL_HEX = "#FCD9CF"   # peach title panel
_ACCENT_HEX = "#F4715C"  # coral accent rule along the left rail
_CHANGE_HEX = "#FF6B35"  # coral wash behind a changed bullet
_INK_HEX = "#2B2B2B"     # near-black headings / body ink
_MUTE_HEX = "#4D4D4D"    # muted grey sub-text

_PAGE_W, _PAGE_H = 612.0, 792.0
_L_X, _L_W = 36.0, 154.0           # left rail:   x 36 -> 190
_R_X, _R_MAX = 230.0, 576.0        # right column: x 230 -> 576
_PANEL_TOP, _PANEL_H = 98.0, 82.0  # peach panel: (36, 98) 154 x 82
_BULLET_LEAD = 12.0                # 9pt body line pitch
_CHANGE_ALPHA = 0.22               # coral wash kept light so text stays legible


def _wrap_rl(text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word-wrap ``text`` to ``width`` at ``size`` using font metrics."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or stringWidth(trial, font, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _draw_left_rail(c: Any, name: str, title: str) -> None:
    """Peach title panel (name + role) with a coral accent rule at its foot."""
    panel_y = _PAGE_H - _PANEL_TOP - _PANEL_H
    c.setFillColor(HexColor(_PANEL_HEX))
    c.rect(_L_X, panel_y, _L_W, _PANEL_H, fill=1, stroke=0)

    pad = 12.0
    inner = _L_W - 2 * pad
    size = 20.0
    while size > 12.0 and stringWidth(name, "Helvetica-Bold", size) > inner:
        size -= 0.5
    c.setFillColor(HexColor(_INK_HEX))
    c.setFont("Helvetica-Bold", size)
    name_base = panel_y + _PANEL_H - pad - size * 0.8
    c.drawString(_L_X + pad, name_base, name)

    c.setFont("Helvetica", 12.0)
    c.setFillColor(HexColor(_MUTE_HEX))
    ty = name_base - 20.0
    for line in _wrap_rl(title, "Helvetica", 12.0, inner)[:2]:
        c.drawString(_L_X + pad, ty, line)
        ty -= 14.0

    c.setFillColor(HexColor(_ACCENT_HEX))
    c.rect(_L_X, 44.0, _L_W, 3.0, fill=1, stroke=0)


def _draw_bullet(c: Any, base: str, y: float, swaps: dict[str, str]) -> float:
    """Draw one bullet at baseline ``y``; wash + swap it if it was reworded."""
    marker_x, text_x = _R_X, _R_X + 12.0
    text_w = _R_MAX - text_x
    replacement = swaps.get(_normalize(base))
    text = base if replacement is None else replacement
    lines = _wrap_rl(text, "Helvetica", 9.0, text_w)

    if replacement is not None:
        block_h = len(lines) * _BULLET_LEAD
        wash_x = marker_x - 3.0
        c.setFillColor(HexColor(_CHANGE_HEX))
        c.setFillAlpha(_CHANGE_ALPHA)
        c.rect(wash_x, y + 9.0 - block_h, (_R_MAX + 2.0) - wash_x,
               block_h + 2.0, fill=1, stroke=0)
        c.setFillAlpha(1.0)

    c.setFont("Helvetica", 9.0)
    c.setFillColor(HexColor(_ACCENT_HEX))
    c.drawString(marker_x, y, "•")
    c.setFillColor(HexColor(_INK_HEX))
    for line in lines:
        c.drawString(text_x, y, line)
        y -= _BULLET_LEAD
    return y


def _draw_right_column(
    c: Any, objective: str, sections: list[dict[str, Any]], swaps: dict[str, str]
) -> None:
    """Career-objective header, then each section's heading and bullets."""
    width = _R_MAX - _R_X
    y = _PAGE_H - 52.0

    c.setFillColor(HexColor(_INK_HEX))
    c.setFont("Helvetica-Bold", 12.0)
    c.drawString(_R_X, y, "Career Objective")
    c.setFillColor(HexColor(_ACCENT_HEX))
    c.rect(_R_X, y - 5.0, width, 1.2, fill=1, stroke=0)
    y -= 18.0
    if objective.strip():
        c.setFont("Helvetica", 9.0)
        c.setFillColor(HexColor(_MUTE_HEX))
        for line in _wrap_rl(objective, "Helvetica", 9.0, width):
            c.drawString(_R_X, y, line)
            y -= _BULLET_LEAD
    y -= 8.0

    for section in sections:
        if y < 70.0:
            break
        heading = str(section.get("heading", "")).strip()
        if heading:
            c.setFont("Helvetica-Bold", 10.5)
            c.setFillColor(HexColor(_INK_HEX))
            c.drawString(_R_X, y, heading)
            y -= _BULLET_LEAD + 2.0
        for bullet in section.get("bullets", []):
            if y < 60.0:
                break
            if not str(bullet).strip():
                continue
            y = _draw_bullet(c, str(bullet), y, swaps)
        y -= 6.0


def _draw_branded_page(
    c: Any,
    name: str,
    title: str,
    objective: str,
    sections: list[dict[str, Any]],
    swaps: dict[str, str],
) -> None:
    """Paint one full page; ``swaps`` is empty for the base page."""
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, _PAGE_W, _PAGE_H, fill=1, stroke=0)
    _draw_left_rail(c, name, title)
    _draw_right_column(c, objective, sections, swaps)


def create_branded_resume_pdf(
    name: str,
    title: str,
    objective: str,
    sections: list[dict[str, Any]],
    changes: list[tuple[str, str]] | None = None,
) -> bytes:
    """Return a two-page branded resume PDF rendered from structured content.

    Unlike :func:`render_tailored_pdf`, which edits the source document in
    place, this rebuilds the resume from scratch with reportlab — for when the
    original PDF isn't available. Both pages share one layout: a peach title
    panel carrying the name and role on the left rail, a coral accent rule at
    its foot, and a right column that opens with the career objective and then
    lists each section's bullets.

    - **Page 1** renders ``sections`` verbatim (the base resume).
    - **Page 2** renders the same layout with every bullet whose text matches a
      change's *before* swapped for its *after*, over a light coral ``#FF6B35``
      wash so the reworded lines stand out.

    ``sections`` is a list of ``{"heading": str, "bullets": list[str]}``;
    ``changes`` a list of ``(before, after)`` bullet-text pairs.
    """
    swaps = {
        _normalize(before): after
        for before, after in (changes or [])
        if before and after
    }

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(_PAGE_W, _PAGE_H))
    _draw_branded_page(c, name, title, objective, sections, {})
    c.showPage()
    _draw_branded_page(c, name, title, objective, sections, swaps)
    c.showPage()
    c.save()
    return buffer.getvalue()
