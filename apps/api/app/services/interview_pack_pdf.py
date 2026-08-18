"""Aether-branded interview-pack PDFs (obsidian + gilt, AB Marquee / AB Sans).

These documents are Aether-OWNED (the candidate takes them to the interview).
They embed the faces from ``design/aether-design-system/fonts`` via PyMuPDF,
which loads the CFF/OTTO files reportlab cannot.

Employer-facing résumé and cover-letter bytes are NEVER rendered here — those
stay the existing format-preserving / business-letter exporters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import logging
import unicodedata

import fitz

# Tokens from design/aether-design-system/tokens/colors.css — lowercase hex
# matches email_branding.PALETTE and the tests that compare literally.
INK_0 = "#08080a"
GOLD = "#c9a84c"
GOLD_PALE = "#e8d5a3"
GOLD_DARK = "#b0923f"
SAPPHIRE = "#3e5a8c"
SAPPHIRE_LIGHT = "#8fa8ce"
FG = "#f5f1e8"
NEUTRAL = "#8c8a82"

_FONTS = (
    Path(__file__).resolve().parents[4]
    / "design"
    / "aether-design-system"
    / "fonts"
)
_DISPLAY_FILE = _FONTS / "AB-Marquee-Bold.ttf"
_BODY_FILE = _FONTS / "AB-Sans-Regular.ttf"
_BODY_BOLD_FILE = _FONTS / "AB-Sans-Bold.ttf"

_DISPLAY = "abdisplay"
_BODY = "abbody"
_BODY_BOLD = "abbodyb"

# AB faces cover ASCII plus en/em dash and curly quotes only (82 glyphs).
_ALLOWED = set(range(32, 127)) | {0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D}
_REPLACE = {
    "·": "\u2014",
    "•": "\u2014",
    "…": "...",
    "×": "x",
    "→": "->",
    "\n": " ",
    "\r": " ",
    "\t": " ",
}

logger = logging.getLogger(__name__)
_font_cache: dict[str, fitz.Font] = {}


def _rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _safe(text: str) -> str:
    folded = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", str(text or ""))
        if not unicodedata.combining(ch)
    )
    out: list[str] = []
    for ch in folded:
        if ch in _REPLACE:
            out.append(_REPLACE[ch])
        elif ord(ch) in _ALLOWED:
            out.append(ch)
        elif ch == "\u00a0":
            out.append(" ")
    return "".join(out)


def _font_obj(kind: str) -> fitz.Font | None:
    if kind in _font_cache:
        return _font_cache[kind]
    path = {"display": _DISPLAY_FILE, "body": _BODY_FILE, "body_b": _BODY_BOLD_FILE}[kind]
    if not path.is_file():
        return None
    font = fitz.Font(fontfile=str(path))
    _font_cache[kind] = font
    return font


def _width(text: str, kind: str, size: float) -> float:
    font = _font_obj(kind)
    if font is None:
        return 0.5 * size * len(text)
    return float(font.text_length(_safe(text), fontsize=size))


def _wrap(text: str, kind: str, size: float, width: float) -> list[str]:
    words = _safe(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or _width(trial, kind, size) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _bind_fonts(page: fitz.Page) -> None:
    for name, path in (
        (_DISPLAY, _DISPLAY_FILE),
        (_BODY, _BODY_FILE),
        (_BODY_BOLD, _BODY_BOLD_FILE),
    ):
        if path.is_file():
            page.insert_font(fontname=name, fontfile=str(path))
        else:
            logger.warning("Design-system font missing: %s", path)


def render_prep_pdf(
    *,
    title: str,
    company: str,
    briefing: dict[str, Any],
    questions: list[dict[str, Any]] | None = None,
) -> bytes:
    """Multi-page portrait brief (logistics, traps, STAR, questions to ask)."""
    doc = fitz.open()
    page: fitz.Page | None = None
    y = 0.0
    page_w, page_h = fitz.paper_size("a4")
    margin = 36.0
    usable = page_w - 2 * margin

    def new_page() -> fitz.Page:
        created = doc.new_page(width=page_w, height=page_h)
        _bind_fonts(created)
        return created

    def paint() -> float:
        nonlocal page
        assert page is not None
        return _paint_chrome(page, page_w, page_h, title, company)

    def ensure(need: float) -> None:
        nonlocal page, y
        if page is None or y + need > page_h - 48:
            page = new_page()
            y = paint()

    def heading(label: str) -> None:
        nonlocal y
        ensure(28)
        assert page is not None
        page.insert_text(
            (margin, y),
            _safe(label.upper()),
            fontsize=11,
            fontname=_DISPLAY,
            color=_rgb(GOLD),
        )
        y += 6
        page.draw_line(
            (margin, y),
            (margin + 48, y),
            color=_rgb(GOLD_DARK),
            width=0.6,
        )
        y += 16

    def bullets(items: Iterable[str], *, colour: str = FG) -> None:
        nonlocal y
        assert page is not None
        for item in items:
            wrapped = _wrap(str(item), "body", 9.5, usable - 14)
            ensure(12 * len(wrapped) + 4)
            page.draw_circle(
                (margin + 3, y - 3),
                1.6,
                color=None,
                fill=_rgb(GOLD),
            )
            for line in wrapped:
                page.insert_text(
                    (margin + 12, y),
                    line,
                    fontsize=9.5,
                    fontname=_BODY,
                    color=_rgb(colour),
                )
                y += 12
            y += 4

    ensure(40)
    logistics = briefing.get("logistics") or []
    heading("Logistics")
    bullets(logistics or ["Time and place were not evidenced in the trail."])

    traps = briefing.get("traps") or []
    heading("Traps to avoid")
    if traps:
        for trap in traps:
            title_t = str(trap.get("title") or "Trap")
            detail = str(trap.get("detail") or "")
            bullets([f"{title_t}. {detail}"])
    else:
        bullets(["None evidenced in the trail or your résumé."])

    heading("Company (from your own postings)")
    bullets(briefing.get("companyNotes") or ["No in-app company brief."])

    heading("Interviewer")
    bullets(briefing.get("interviewerNotes") or ["No interviewer named in the trail."])

    heading("Questions they are likely to ask")
    if questions:
        for q in questions[:12]:
            q_lines = _wrap(str(q.get("question") or ""), "body_b", 10, usable)
            ensure(36)
            assert page is not None
            for line in q_lines:
                ensure(14)
                page.insert_text(
                    (margin, y),
                    line,
                    fontsize=10,
                    fontname=_BODY_BOLD,
                    color=_rgb(GOLD_PALE),
                )
                y += 13
            why = str(q.get("whyAsked") or "")
            if why:
                for line in _wrap(why, "body", 8, usable):
                    ensure(11)
                    page.insert_text(
                        (margin, y),
                        line,
                        fontsize=8,
                        fontname=_BODY,
                        color=_rgb(SAPPHIRE_LIGHT),
                    )
                    y += 11
            sketch = q.get("answerSketch") or {}
            if isinstance(sketch, dict) and sketch.get("situation"):
                star = (
                    f"S: {sketch.get('situation')}  T: {sketch.get('task')}  "
                    f"A: {sketch.get('action')}  R: {sketch.get('result')}"
                )
                for line in _wrap(star, "body", 8.5, usable):
                    ensure(11)
                    page.insert_text(
                        (margin, y),
                        line,
                        fontsize=8.5,
                        fontname=_BODY,
                        color=_rgb(FG),
                    )
                    y += 11
            y += 8
    else:
        bullets(["STAR questions were not drafted — the live model was unavailable."])

    heading("Questions to ask")
    bullets(briefing.get("questionsToAsk") or [])
    heading("Guidelines")
    bullets(briefing.get("guidelines") or [])
    heading("Close")
    bullets(briefing.get("closing") or [])

    return bytes(doc.tobytes())


def render_slides_pdf(
    *,
    title: str,
    company: str,
    briefing: dict[str, Any],
    questions: list[dict[str, Any]] | None = None,
) -> bytes:
    """Four landscape slides for the table: logistics, traps, STAR, ask/close."""
    page_w, page_h = fitz.paper_size("a4-l")
    doc = fitz.open()
    slides = [
        ("Logistics", list(briefing.get("logistics") or [])),
        (
            "Traps and company notes",
            [
                *[
                    f"{t.get('title')}: {t.get('detail')}"
                    for t in (briefing.get("traps") or [])
                ],
                *list(briefing.get("companyNotes") or []),
                *list(briefing.get("interviewerNotes") or []),
            ],
        ),
        ("STAR pitches", _star_slide_lines(questions or [])),
        (
            "Ask and close",
            [
                *list(briefing.get("questionsToAsk") or []),
                *list(briefing.get("guidelines") or []),
                *list(briefing.get("closing") or []),
            ],
        ),
    ]
    for heading, lines in slides:
        page = doc.new_page(width=page_w, height=page_h)
        _bind_fonts(page)
        _paint_slide(page, page_w, page_h, title, company, heading, lines)
    return bytes(doc.tobytes())


def _star_slide_lines(questions: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for q in questions[:4]:
        sketch = q.get("answerSketch") if isinstance(q, dict) else None
        prompt = str((q or {}).get("question") or "")
        if prompt:
            lines.append(prompt)
        if isinstance(sketch, dict) and sketch.get("result"):
            lines.append(
                f"{sketch.get('situation')} → {sketch.get('action')} → {sketch.get('result')}"
            )
    return lines or ["No story-grounded STAR pitch is on file yet."]


def _centred(page: fitz.Page, y: float, text: str, *, kind: str, size: float, colour: str) -> None:
    name = {"display": _DISPLAY, "body": _BODY, "body_b": _BODY_BOLD}[kind]
    safe = _safe(text)
    x = (page.rect.width - _width(safe, kind, size)) / 2
    page.insert_text((x, y), safe, fontsize=size, fontname=name, color=_rgb(colour))


def _paint_chrome(
    page: fitz.Page, page_w: float, page_h: float, title: str, company: str
) -> float:
    page.draw_rect(page.rect, color=None, fill=_rgb(INK_0))
    page.draw_rect(fitz.Rect(0, 0, page_w, 4), color=None, fill=_rgb(GOLD))
    page.draw_rect(
        fitz.Rect(0, page_h - 3, page_w, page_h), color=None, fill=_rgb(GOLD_DARK)
    )
    _centred(page, 28, "AETHER", kind="display", size=9, colour=GOLD)
    headline = f"{(title or 'INTERVIEW').upper()}  —  {(company or '').upper()}"
    _centred(page, 52, headline[:90], kind="display", size=16, colour=GOLD_PALE)
    page.draw_line(
        (page_w / 2 - 22, 62),
        (page_w / 2 + 22, 62),
        color=_rgb(GOLD),
        width=0.8,
    )
    _centred(
        page,
        page_h - 18,
        "Aether CareerAI Agent  —  grounded in your own data  —  not live web research",
        kind="body",
        size=7,
        colour=NEUTRAL,
    )
    return 80.0


def _paint_slide(
    page: fitz.Page,
    page_w: float,
    page_h: float,
    title: str,
    company: str,
    heading: str,
    lines: list[str],
) -> None:
    page.draw_rect(page.rect, color=None, fill=_rgb(INK_0))
    page.draw_rect(fitz.Rect(0, 0, 8, page_h), color=None, fill=_rgb(SAPPHIRE))
    page.draw_rect(fitz.Rect(0, 0, page_w, 6), color=None, fill=_rgb(GOLD))
    page.insert_text(
        (32, 36), "AETHER", fontsize=10, fontname=_DISPLAY, color=_rgb(GOLD)
    )
    right = _safe(f"{title}  —  {company}")
    page.insert_text(
        (page_w - 28 - _width(right, "body", 8), 36),
        right,
        fontsize=8,
        fontname=_BODY,
        color=_rgb(NEUTRAL),
    )
    page.insert_text(
        (32, 78),
        _safe(heading.upper()),
        fontsize=22,
        fontname=_DISPLAY,
        color=_rgb(GOLD_PALE),
    )
    y = 110.0
    usable = page_w - 64
    for item in lines[:12]:
        wrapped = _wrap(str(item), "body", 12, usable - 16)
        if y + 16 * len(wrapped) > page_h - 36:
            break
        page.draw_circle((40, y - 4), 2.2, color=None, fill=_rgb(GOLD))
        for line in wrapped:
            page.insert_text(
                (52, y), line, fontsize=12, fontname=_BODY, color=_rgb(FG)
            )
            y += 16
        y += 8
