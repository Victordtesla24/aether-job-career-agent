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


class PdfRenderError(RuntimeError):
    """A stored PDF's bytes could not be opened for an in-place tailoring splice.

    Mirrors ``resume_docx.DocxParseError``: the router treats it as an honest
    "your stored original could not be opened" fallback to the branded render,
    rather than a 500 — the bytes passed the upload gate, so this is corruption
    we did not cause.
    """


#: Unicode punctuation folded before matching a stored bullet to a PDF block,
#: so curly quotes / en-dashes in one source don't defeat an exact match.
_PUNCT_FOLD = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', " ": " ",
})


def resolve_original_pdf(format_hash: str | None) -> Path | None:
    """Return the bundled resume asset whose bytes match ``format_hash``, or
    ``None`` when no bundled asset matches.

    The ``formatHash`` on a resume record is the SHA-256 of the source PDF, so a
    bundled-derived version (the seeded base or the BA variant) matches a file on
    disk. A user-authored résumé (uploaded/ingested — its ``formatHash`` is a
    digest of the USER's own content) matches nothing, so this returns ``None``
    and the caller MUST render from the résumé's own structured content rather
    than serve another résumé's bytes: returning the bundled operator PDF here
    would leak the operator's résumé into the user's download/attachment
    (NF-final-B-005, cross-account PII).
    """
    if not format_hash:
        return None
    assets_dir = get_base_resume_path().parent
    for pdf in sorted(assets_dir.glob("*.pdf")):
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest == format_hash or digest[:16] == format_hash:
            return pdf
    return None


def bundled_format_hashes() -> set[str]:
    """Every bundled résumé asset's digest, in BOTH spellings
    :func:`resolve_original_pdf` accepts (full SHA-256 and its 16-char prefix).

    MON-011: lets a LIST response answer "would the download for this résumé
    reproduce the original document?" for many résumés with ONE pass over the
    bundled assets, instead of re-hashing them per résumé. Derived from the
    same files, by the same rule, as ``resolve_original_pdf`` — the download
    endpoint's own decision — so the honest ``formatPreserved`` flag can never
    drift from what the download actually does.
    """
    assets_dir = get_base_resume_path().parent
    digests: set[str] = set()
    for pdf in sorted(assets_dir.glob("*.pdf")):
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        digests.add(digest)
        digests.add(digest[:16])
    return digests


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


def render_tailored_pdf(
    original: Path | bytes, changes: list[tuple[str, str]]
) -> bytes:
    """Return format-preserving PDF bytes for a tailored resume.

    ``original`` is EITHER a filesystem :class:`~pathlib.Path` to a bundled seed
    asset OR the raw bytes of a user's stored PDF upload. The latter is the
    majority real-world case — a tailored child of a genuine, non-bundled PDF
    upload derives from its parent's stored bytes (``originalFile``), which never
    resolve to a bundled asset on disk (``resolve_original_pdf`` returns ``None``
    for them) and so must be spliced from the bytes directly rather than a path.
    Routing those bytes here is what keeps such a résumé on its own two-column
    layout instead of dropping to the branded template (the live cfe7a0f→c12187
    divergence, MODELS-LIVE R-FMT §1 contributing factor #4).

    ``changes`` is a list of ``(before, after)`` pairs — the original and the
    reworded text of each bullet whose text changed. Each pair is matched to a
    work bullet in the source document and that bullet is redrawn with ``after``
    in full, replacing the original text. Pairs that don't match a work bullet
    (e.g. left-rail skills, or any region this splice engine cannot place) are
    skipped, leaving the original untouched — the layout is preserved and the
    unplaced rewrite keeps its baseline wording (disclosed as residue upstream),
    NEVER a reason to abandon the user's own layout. With no matching changes the
    pristine source bytes are returned.

    ``after`` is the *complete* reworded bullet, so it replaces the whole
    bullet. The previous implementation spliced ``after`` onto the bullet's
    original continuation, which duplicated and dangled text whenever the
    rewrite already restated that continuation (GAP-P4-044).

    :raises PdfRenderError: the bytes/path could not be opened as a PDF.
    """
    try:
        if isinstance(original, (bytes, bytearray)):
            doc = fitz.open(stream=bytes(original), filetype="pdf")
        else:
            doc = fitz.open(original)
    except (RuntimeError, ValueError) as exc:  # fitz.FileDataError ⊂ RuntimeError
        raise PdfRenderError(str(exc)) from exc
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


# --- Branded template (reportlab) -------------------------------------------
# A from-scratch renderer for when the source PDF isn't on hand: it redraws the
# same visual language — peach title panel, coral accents — on blank Letter
# pages from the WHOLE persisted résumé (app/services/resume_document.py):
# name, headline, contact details, every section heading, every section line and
# every bullet, flowing onto as many pages as the document needs.
#
# CRITICAL (2026-08-14). Two defects lived in the previous version of this
# renderer and shipped to a paying subscriber
# (``uat/reports/evidence/agents-uplift/u2b/verify-final/``):
#
# * it drew a FIXED pair of pages and ``break``ed out of its draw loop when the
#   vertical cursor ran low, so a résumé longer than one page lost its tail
#   silently — 8 of 25 bullets, plus every section the caller never mapped
#   (contact, education, skills, certifications);
# * page 2 re-drew page 1 with a ``swaps`` map keyed on the BASELINE wording,
#   while the sections handed to it already held the TAILORED wording — so no
#   swap ever fired and the download carried two byte-identical pages.
#
# Both are structural, so the fix is structural: one flowing document, drawn
# once, paginated by content, with the tailored lines washed in coral where the
# tailoring diff says a line was reworded.
#
# Geometry/palette are the measurements read off Vik_Resume_Final.pdf (top-
# origin points; reportlab's origin is bottom-left, so a top ``y`` maps to
# ``_PAGE_H - y``). The layout is single-column by design: a sidebar sharing
# baselines with the body is flattened by every PDF text extractor into
# interleaved lines (that is exactly how the source résumé's own text layer
# reads), which would break a bullet apart in the very verification that has to
# prove the bullet survived.
_PANEL_HEX = "#FCD9CF"   # peach title panel
_ACCENT_HEX = "#F4715C"  # coral accent rule under the title panel
_CHANGE_HEX = "#FF6B35"  # coral wash behind a tailored bullet
_INK_HEX = "#2B2B2B"     # near-black headings / body ink
_MUTE_HEX = "#4D4D4D"    # muted grey sub-text

_PAGE_W, _PAGE_H = 612.0, 792.0
_M_X, _M_MAX = 36.0, 576.0         # content band: x 36 -> 576
_TOP_Y, _BOTTOM_Y = 748.0, 54.0    # first baseline, and the last usable one
_BULLET_LEAD = 12.0                # 9pt body line pitch
_BULLET_INDENT = 14.0              # text indent of a bullet's wrapped lines
_CHANGE_ALPHA = 0.22               # coral wash kept light so text stays legible
_BODY_PT = 9.0
_HEADING_PT = 10.5


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


class _Flow:
    """A paginating cursor over the branded template's single content column.

    Every draw call goes through :meth:`reserve`, which starts a new page when
    the block would not fit rather than dropping it — the previous renderer's
    ``break`` is the reason a subscriber's contact details, education, skills
    and eight bullets never reached the page. Pages carry NO repeated text
    chrome: a running header or footer would land between the halves of a
    bullet that spans a page break and split it in the extracted text layer,
    defeating the very completeness check that has to prove it survived.
    """

    def __init__(self, canvas_obj: Any) -> None:
        self.c = canvas_obj
        self.y = _TOP_Y
        self._paint_page()

    def _paint_page(self) -> None:
        self.c.setFillColor(HexColor("#FFFFFF"))
        self.c.rect(0, 0, _PAGE_W, _PAGE_H, fill=1, stroke=0)

    def new_page(self) -> None:
        self.c.showPage()
        self.y = _TOP_Y
        self._paint_page()

    def reserve(self, height: float) -> None:
        """Make room for a ``height``-tall block, starting a page if needed."""
        if self.y - height < _BOTTOM_Y and self.y < _TOP_Y:
            self.new_page()

    def text_block(
        self, lines: list[str], *, font: str, size: float, colour: str, x: float
    ) -> None:
        for line in lines:
            self.reserve(size)
            self.c.setFont(font, size)
            self.c.setFillColor(HexColor(colour))
            self.c.drawString(x, self.y, line)
            self.y -= size + 3.0

    def gap(self, height: float) -> None:
        self.y -= height


def _draw_title_panel(flow: _Flow, name: str, title: str, contact: list[str]) -> None:
    """Peach panel with the WHOLE name and headline, then the contact details.

    The live defect shipped a résumé headed ``VIKRAM`` with no surname and no
    way to contact its author, because the panel drew one unwrapped line at a
    fixed size and the contact block was never mapped onto the template at all.
    Both now wrap inside the content band, so no part of either is clipped.
    """
    width = _M_MAX - _M_X
    pad = 12.0
    inner = width - 2 * pad
    size = 22.0
    while size > 13.0 and stringWidth(name, "Helvetica-Bold", size) > inner:
        size -= 0.5
    name_lines = _wrap_rl(name, "Helvetica-Bold", size, inner)
    title_lines = _wrap_rl(title, "Helvetica", 11.0, inner) if title.strip() else []
    panel_h = pad * 2 + len(name_lines) * (size + 4.0) + len(title_lines) * 14.0

    flow.reserve(panel_h + 6.0)
    top = flow.y
    flow.c.setFillColor(HexColor(_PANEL_HEX))
    flow.c.rect(_M_X, top - panel_h, width, panel_h, fill=1, stroke=0)

    y = top - pad - size * 0.85
    flow.c.setFillColor(HexColor(_INK_HEX))
    flow.c.setFont("Helvetica-Bold", size)
    for line in name_lines:
        flow.c.drawString(_M_X + pad, y, line)
        y -= size + 4.0
    flow.c.setFont("Helvetica", 11.0)
    flow.c.setFillColor(HexColor(_MUTE_HEX))
    for line in title_lines:
        flow.c.drawString(_M_X + pad, y, line)
        y -= 14.0

    flow.c.setFillColor(HexColor(_ACCENT_HEX))
    flow.c.rect(_M_X, top - panel_h - 3.0, width, 3.0, fill=1, stroke=0)
    flow.y = top - panel_h - 14.0

    if contact:
        flow.text_block(
            _wrap_rl(
                "  •  ".join(contact), "Helvetica", _BODY_PT, width - 2.0
            ),
            font="Helvetica",
            size=_BODY_PT,
            colour=_MUTE_HEX,
            x=_M_X,
        )
        flow.gap(4.0)


def _draw_heading(flow: _Flow, heading: str) -> None:
    flow.reserve(_HEADING_PT + 12.0)
    flow.c.setFont("Helvetica-Bold", _HEADING_PT)
    flow.c.setFillColor(HexColor(_INK_HEX))
    flow.c.drawString(_M_X, flow.y, heading)
    flow.c.setFillColor(HexColor(_ACCENT_HEX))
    flow.c.rect(_M_X, flow.y - 5.0, _M_MAX - _M_X, 1.2, fill=1, stroke=0)
    flow.y -= _HEADING_PT + 8.0


def _draw_flow_bullet(flow: _Flow, text: str, *, tailored: bool) -> None:
    """One bullet, kept whole: washed in coral when the tailoring reworded it."""
    text_x = _M_X + _BULLET_INDENT
    lines = _wrap_rl(text, "Helvetica", _BODY_PT, _M_MAX - text_x)
    block_h = len(lines) * _BULLET_LEAD
    # Keep a bullet on one page when it can fit on one; a bullet longer than a
    # whole page still flows rather than being truncated.
    if block_h <= _TOP_Y - _BOTTOM_Y:
        flow.reserve(block_h)
    if tailored:
        flow.c.setFillColor(HexColor(_CHANGE_HEX))
        flow.c.setFillAlpha(_CHANGE_ALPHA)
        flow.c.rect(
            _M_X - 3.0,
            flow.y + _BODY_PT - block_h,
            (_M_MAX + 2.0) - (_M_X - 3.0),
            block_h + 2.0,
            fill=1,
            stroke=0,
        )
        flow.c.setFillAlpha(1.0)
    flow.c.setFont("Helvetica", _BODY_PT)
    flow.c.setFillColor(HexColor(_ACCENT_HEX))
    flow.c.drawString(_M_X, flow.y, "•")
    flow.c.setFillColor(HexColor(_INK_HEX))
    for line in lines:
        flow.reserve(_BODY_PT)
        flow.c.setFont("Helvetica", _BODY_PT)
        flow.c.setFillColor(HexColor(_INK_HEX))
        flow.c.drawString(text_x, flow.y, line)
        flow.y -= _BULLET_LEAD


def _section_items(section: dict[str, Any]) -> list[tuple[str, str]]:
    """``[(kind, text)]`` for a template section, in the document's own order.

    Accepts the whole-document shape (``items``) and the older
    ``{"heading", "bullets"}`` shape, so a caller that only has bullets still
    renders.
    """
    items = section.get("items")
    if items:
        return [
            (str(item.get("kind", "line")), str(item.get("text", "")))
            for item in items
            if str(item.get("text", "")).strip()
        ]
    return [
        ("line", str(line))
        for line in section.get("lines", [])
        if str(line).strip()
    ] + [
        ("bullet", str(bullet))
        for bullet in section.get("bullets", [])
        if str(bullet).strip()
    ]


def create_branded_resume_pdf(
    name: str,
    title: str,
    objective: str,
    sections: list[dict[str, Any]],
    changes: list[tuple[str, str]] | None = None,
    *,
    contact: list[str] | tuple[str, ...] | None = None,
) -> bytes:
    """Render the WHOLE résumé in the Aether template, over as many pages as it needs.

    Unlike :func:`render_tailored_pdf`, which edits the source document in
    place, this rebuilds the résumé from scratch with reportlab — for when the
    original document isn't available, or when an in-place rewrite could not be
    completed. It is the fallback every other branch falls back TO, so it must
    be the one render that can never lose content: everything the caller passes
    is drawn, and the page count follows the document rather than the document
    being cut to fit a fixed page count.

    ``sections`` is a list of ``{"heading": str, "items": [{"kind", "text"}]}``
    (``kind`` is ``"line"`` or ``"bullet"``); the older ``{"heading",
    "bullets"}`` shape is still accepted. ``contact`` carries the contact
    details. ``changes`` is the tailoring diff as ``(before, after)`` pairs: a
    line matching either half is drawn over a light coral ``#FF6B35`` wash so
    the reworded lines stand out, and a section still holding the BASELINE
    wording is swapped for the tailored wording.
    """
    swaps = {
        _normalize(before): after
        for before, after in (changes or [])
        if before and after
    }
    # Both halves of the diff mark a line as tailored. A tailored version stores
    # the REWRITTEN text, so keying only on ``before`` (what the previous
    # renderer did) matched nothing at all and produced a second page identical
    # to the first.
    tailored = {_normalize(after) for _before, after in (changes or []) if after}

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=(_PAGE_W, _PAGE_H))
    flow = _Flow(c)
    _draw_title_panel(flow, name, title, [str(item) for item in (contact or [])])

    if objective.strip():
        _draw_heading(flow, "Career Objective")
        flow.text_block(
            _wrap_rl(objective, "Helvetica", _BODY_PT, _M_MAX - _M_X),
            font="Helvetica",
            size=_BODY_PT,
            colour=_MUTE_HEX,
            x=_M_X,
        )
        flow.gap(6.0)

    for section in sections:
        heading = str(section.get("heading", "")).strip()
        if heading:
            _draw_heading(flow, heading)
        for kind, text in _section_items(section):
            if kind == "bullet":
                drawn = swaps.get(_normalize(text), text)
                _draw_flow_bullet(
                    flow,
                    drawn,
                    tailored=_normalize(drawn) in tailored
                    or _normalize(text) in swaps,
                )
            else:
                flow.text_block(
                    _wrap_rl(text, "Helvetica", _BODY_PT, _M_MAX - _M_X),
                    font="Helvetica",
                    size=_BODY_PT,
                    colour=_MUTE_HEX,
                    x=_M_X,
                )
        flow.gap(6.0)

    c.showPage()
    c.save()
    return buffer.getvalue()
