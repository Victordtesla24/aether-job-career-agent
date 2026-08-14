"""The persisted résumé as ONE document model — shared by render and verification.

CRITICAL (U2b completeness round, 2026-08-14). The reflow-template download
shipped a résumé that was missing a third of its own content: 17 of 25 bullets,
no contact block, no education, no skills, no certifications, and the surname
clipped off the name — while the fidelity report, which only ever looked at the
tailoring-loop's tracked rewrites, called the document 9-of-10 complete
(``uat/reports/evidence/agents-uplift/u2b/verify-final/CRITICAL-FINDING-content-loss.json``).
A subscriber approving that résumé would have sent an employer a document with
no way to reply to them.

The loss came from the renderer inventing its own, much smaller, idea of what a
résumé is: ``routers/resumes.py::_branded_content`` mapped a stored résumé onto
``(first raw line, "", "", [{"heading": "Experience", "bullets": [...]}])`` and
threw away every other line of ``raw_text``. Nothing downstream could notice,
because verification also only knew about the bullets it had asked to rewrite.

So the persisted record is parsed ONCE, here, into the whole document —
name, headline, contact details, every section heading, every section line and
every bullet, in the order the user's own résumé states them. The renderer
draws this model; the completeness verifier measures the produced artifact
against this same model. Neither can silently disagree with the other about
what the résumé contains, because there is only one answer.

Bullet lines are recognised with the SAME line-walk the ingestion pipeline uses
(:mod:`app.services.resume_tailor`), so a bullet is never both dropped from the
prose and absent from the bullet list: whatever ``extract_bullets`` claimed is
exactly what this model reserves a slot for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The ingestion pipeline's own line classification. Imported rather than
# re-implemented: this model must reserve a bullet slot for exactly the lines
# ``extract_bullets`` consumed, or the render would either duplicate a bullet
# (once as prose, once from the bullet list) or lose one.
from app.services.resume_tailor import (
    _ends_bullet,
    _is_bullet_marker,
    _is_section_banner,
    _job_header_indices,
    deinterleave_columns,
)

#: Section banners a résumé actually uses. Only these end the name block at the
#: top of the document — a bare all-caps line is not enough, because a surname
#: ("DESHPANDE") is all-caps too and losing it is precisely the live defect.
_KNOWN_BANNER_WORDS = (
    "CONTACT", "PROFILE", "SUMMARY", "OBJECTIVE", "CAREER", "EXPERIENCE",
    "EMPLOYMENT", "HISTORY", "EDUCATION", "SKILL", "CERTIFICATION", "PROJECT",
    "AWARD", "ACHIEVEMENT", "PUBLICATION", "LANGUAGE", "REFEREN", "INTEREST",
    "VOLUNTEER", "TRAINING", "QUALIFICATION", "ACCOMPLISHMENT", "EXPERTISE",
    "COMPETENC", "TECHNOLOG", "TOOLS", "WORK",
)

#: Longest line still treatable as part of a name / headline block.
_MAX_NAME_LINE = 40
_MAX_TITLE_LINE = 80
#: A name is at most this many wrapped lines ("VIKRAM" / "DESHPANDE").
_MAX_NAME_LINES = 3

#: Contact keys that are NOT contact details (they name the person/role).
_NON_CONTACT_KEYS = ("name", "title", "headline", "role")

_MARKER_CHARS = "•●▪- \t"

_WORD_RE = re.compile(r"[0-9a-z]+")

#: How much wording a rewritten bullet must still share with the bullet it
#: replaces before it may take that slot. A tailoring rewrite keeps the same
#: evidence — the same employer, numbers and nouns — so it stays well above
#: this; an unrelated bullet does not, and is added to the document rather than
#: written over someone else's job.
_REWRITE_OVERLAP = 0.35


@dataclass(frozen=True)
class DocItem:
    """One drawable line of the résumé: ``kind`` is ``"line"`` or ``"bullet"``."""

    kind: str
    text: str


@dataclass(frozen=True)
class DocSection:
    """A section banner and everything the user wrote under it."""

    heading: str
    items: tuple[DocItem, ...]

    @property
    def bullets(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.items if item.kind == "bullet")

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(item.text for item in self.items if item.kind == "line")


@dataclass(frozen=True)
class ResumeDocument:
    """Everything the stored résumé record says the document contains."""

    name: str
    title: str
    objective: str
    contact: tuple[str, ...]
    sections: tuple[DocSection, ...]

    @property
    def headings(self) -> tuple[str, ...]:
        return tuple(section.heading for section in self.sections if section.heading)

    @property
    def bullets(self) -> tuple[str, ...]:
        return tuple(
            item.text
            for section in self.sections
            for item in section.items
            if item.kind == "bullet" and item.text.strip()
        )

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(
            item.text
            for section in self.sections
            for item in section.items
            if item.kind == "line" and item.text.strip()
        )


def _is_caps(line: str) -> bool:
    return line.upper() == line and any(ch.isalpha() for ch in line)


def _is_known_banner(line: str) -> bool:
    upper = line.upper()
    return _is_section_banner(line) and any(w in upper for w in _KNOWN_BANNER_WORDS)


def _split_merged_banner(line: str) -> tuple[str, str]:
    """Split a two-column line that merged the name into the first banner.

    PyMuPDF flattens a two-column résumé line by line, so the very first line of
    the live document is ``"VIKRAM        CAREER OBJECTIVE"`` — the name and the
    first section banner in one string. Returning ``("VIKRAM", "CAREER
    OBJECTIVE")`` keeps the person's own name in the header instead of
    surrendering it to a heading, without inventing anything: both halves are
    the user's own text, in their own order.
    """
    words = line.split()
    for index, word in enumerate(words):
        if index and any(w in word.upper() for w in _KNOWN_BANNER_WORDS):
            return " ".join(words[:index]), " ".join(words[index:])
    return "", line


def _bullet_head(line: str) -> str:
    return line.lstrip(_MARKER_CHARS).strip()


def _parse_header(raw_lines: list[str]) -> tuple[str, str, int]:
    """``(name, title, index of the first body line)``.

    The name is the leading run of short all-caps lines (a surname on its own
    line is normal in a two-column résumé); a first line that is not all-caps is
    the whole name on its own. Everything after it, up to the first section
    banner, is the headline.
    """
    index = 0
    name_lines: list[str] = []
    while index < len(raw_lines) and len(name_lines) < _MAX_NAME_LINES:
        line = raw_lines[index]
        if _is_known_banner(line) or _is_bullet_marker(line) or len(line) > _MAX_NAME_LINE:
            break
        if name_lines and not _is_caps(line):
            break
        name_lines.append(line)
        index += 1
        if not _is_caps(line):
            break
    if not name_lines and raw_lines:
        # A merged two-column first line: recover the name, leave the banner.
        head, _rest = _split_merged_banner(raw_lines[0])
        if head:
            name_lines.append(head)
            raw_lines[0] = _rest

    title_lines: list[str] = []
    while index < len(raw_lines):
        line = raw_lines[index]
        if (
            _is_section_banner(line)
            or _is_bullet_marker(line)
            or len(line) > _MAX_TITLE_LINE
        ):
            break
        title_lines.append(line)
        index += 1
    return " ".join(name_lines), " ".join(title_lines), index


def _parse_sections(raw_lines: list[str], start: int) -> list[DocSection]:
    """Walk the résumé body into sections of lines and bullet slots.

    A bullet's wrapped continuation lines are folded into the bullet itself
    (identically to ``resume_tailor.extract_bullets``), so they are never drawn
    twice — once as loose prose and once inside the bullet.
    """
    header_indices = _job_header_indices(raw_lines)
    sections: list[DocSection] = []
    heading = ""
    items: list[DocItem] = []
    buffer: list[str] | None = None

    def close_bullet() -> None:
        nonlocal buffer
        if buffer is not None:
            text = " ".join(part for part in buffer if part).strip()
            if text:
                items.append(DocItem("bullet", text))
        buffer = None

    def close_section() -> None:
        close_bullet()
        if heading or items:
            sections.append(DocSection(heading=heading, items=tuple(items)))

    for i in range(start, len(raw_lines)):
        line = raw_lines[i]
        if _is_bullet_marker(line):
            close_bullet()
            head = _bullet_head(line)
            buffer = [head] if head else []
            if head and _ends_bullet(head):
                close_bullet()
            continue
        if _is_section_banner(line):
            close_section()
            heading, items = line, []
            continue
        if buffer is not None:
            if i in header_indices:
                close_bullet()
                items.append(DocItem("line", line))
                continue
            if buffer and buffer[-1].endswith("-"):
                buffer[-1] += line
            else:
                buffer.append(line)
            if _ends_bullet(line):
                close_bullet()
            continue
        items.append(DocItem("line", line))
    close_section()
    return sections


def _substitute_bullets(
    sections: list[DocSection], persisted: list[str]
) -> list[DocSection]:
    """Put the PERSISTED bullet text into the slot it BELONGS to, by content.

    A tailored version stores its rewritten bullets in ``sections.bullets`` and
    regenerates ``raw_text`` from them, so the two normally line up exactly.
    They are nevertheless matched by CONTENT, never by position: a positional
    ``zip`` writes whatever the counts happen to allow, so one mis-parsed line
    silently moves a bullet under another job's heading — a résumé that reads
    as a lie about where the person did the work — and nothing downstream can
    see it, because a completeness check only asks whether the text is present
    somewhere (U2b review, 2026-08-14).

    An unchanged bullet claims its own slot outright; a rewritten one claims
    the slot whose wording it most closely rewrites. A persisted bullet that
    matches no slot is appended rather than dropped, and a slot that matches no
    persisted bullet keeps its own prose: losing a bullet is the failure this
    module exists to prevent, so every ambiguous case resolves towards keeping
    more of the user's text.
    """
    slots = [
        (s_index, i_index)
        for s_index, section in enumerate(sections)
        for i_index, item in enumerate(section.items)
        if item.kind == "bullet"
    ]
    rebuilt = [list(section.items) for section in sections]
    slot_text = [rebuilt[s_index][i_index].text for s_index, i_index in slots]
    claimed, extra = _claim_slots(slot_text, persisted)
    for index, text in claimed.items():
        s_index, i_index = slots[index]
        rebuilt[s_index][i_index] = DocItem("bullet", text)
    out = [
        DocSection(heading=section.heading, items=tuple(rebuilt[index]))
        for index, section in enumerate(sections)
    ]
    if extra:
        # No invented heading: a heading this résumé never stated would become
        # part of the completeness contract the produced file is measured
        # against, i.e. a fabricated requirement. The bullets simply follow the
        # document they belong to.
        out.append(
            DocSection(
                heading="",
                items=tuple(DocItem("bullet", text) for text in extra),
            )
        )
    return out


def _claim_slots(
    slot_text: list[str], persisted: list[str]
) -> tuple[dict[int, str], list[str]]:
    """``({slot index: persisted text}, unmatched persisted text)``.

    Two passes, strongest evidence first: an identical bullet is the same
    bullet, and a rewrite is the bullet it shares the most wording with. A
    rewrite that shares almost nothing with any remaining slot is NOT forced
    into one — it is returned unmatched, so it is added to the document instead
    of overwriting a bullet it has nothing to do with.
    """
    by_fold: dict[str, list[int]] = {}
    for index, text in enumerate(slot_text):
        by_fold.setdefault(_fold(text), []).append(index)

    claimed: dict[int, str] = {}
    pending: list[str] = []
    for text in persisted:
        pool = by_fold.get(_fold(text))
        if pool:
            claimed[pool.pop(0)] = text
        else:
            pending.append(text)

    free = [index for index in range(len(slot_text)) if index not in claimed]
    unmatched: list[str] = []
    for text in pending:
        best, score = None, 0.0
        for index in free:
            overlap = _overlap(text, slot_text[index])
            if overlap > score:
                best, score = index, overlap
        if best is None or score < _REWRITE_OVERLAP:
            unmatched.append(text)
            continue
        claimed[best] = text
        free.remove(best)
    return claimed, unmatched


def _overlap(left: str, right: str) -> float:
    """Word overlap of two bullets (0.0–1.0), used to pair a rewrite with the
    bullet it rewrote."""
    left_words, right_words = _words(left), _words(right)
    if not left_words or not right_words:
        return 0.0
    return len(left_words & right_words) / len(left_words | right_words)


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _fold(text: str) -> str:
    return " ".join(text.lower().split())


def _contact_details(
    contact: dict[str, Any], sections: list[DocSection]
) -> tuple[str, ...]:
    """Every contact detail the record holds, from BOTH places it can live.

    JSON-ingested résumés carry a ``contact`` map; a PDF/DOCX upload carries the
    same details as the lines of its own contact section. Both are the user's
    only channel back from an employer, so both are tracked.
    """
    details: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        text = value.strip()
        if text and _fold(text) not in seen:
            seen.add(_fold(text))
            details.append(text)

    for key, value in contact.items():
        if str(key).lower() in _NON_CONTACT_KEYS:
            continue
        if isinstance(value, (str, int, float)):
            add(str(value))
    for section in sections:
        if "CONTACT" in section.heading.upper():
            for item in section.items:
                add(item.text)
    return tuple(details)


def parse_resume_document(resume: dict[str, Any]) -> ResumeDocument:
    """The whole persisted résumé: header, contact, every section, every bullet."""
    payload = resume.get("sections") or {}
    contact = payload.get("contact") or {}
    if not isinstance(contact, dict):
        contact = {}
    # Two-column pages arrive with the sidebar welded onto the body, one line
    # per printed line; read them back as the two columns they are BEFORE the
    # header/section walk, which assumes one logical line per line.
    raw_lines = [
        line.strip()
        for line in deinterleave_columns(
            str(payload.get("raw_text", "") or "")
        ).splitlines()
        if line.strip()
    ]
    persisted = [
        str(bullet.get("text", "")).strip()
        for bullet in (payload.get("bullets") or [])
        if isinstance(bullet, dict) and str(bullet.get("text", "")).strip()
    ]

    name, title, start = _parse_header(raw_lines)
    sections = _substitute_bullets(_parse_sections(raw_lines, start), persisted)

    name = str(contact.get("name") or name or resume.get("label") or "Resume")
    title = str(contact.get("title") or contact.get("headline") or title or "")
    objective = str(payload.get("objective") or payload.get("summary") or "")
    return ResumeDocument(
        name=name,
        title=title,
        objective=objective,
        contact=_contact_details(contact, sections),
        sections=tuple(sections),
    )
