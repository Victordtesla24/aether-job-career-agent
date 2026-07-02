"""Resume parsing with a format-preserving hash (P1-S04).

`compute_format_hash` returns the SHA-256 of the *raw PDF bytes*. It is the
identity of a resume's exact layout/format: as long as the source file is byte
-for-byte identical, the hash is identical, and it changes only if the file
itself changes. This lets the tailoring pipeline guarantee it never mutates the
user's original formatting — it keys every generated variant off this hash.

`parse_resume_pdf` extracts the text and a few reliable contact fields from the
PDF using `pdfplumber`. It does **not** fabricate content — every field is read
straight from the document, and callers get the raw text to work with too.

The bundled asset `assets/resume/Vik_Resume_Final.pdf` is READ-ONLY and is
never written to by this module.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional, TypedDict, Union

import pdfplumber

PathLike = Union[str, Path]

# Canonical section headings we recognise in a resume. Detection is presence
# based (does the heading appear in the extracted text?) which is robust to the
# multi-column layouts that make positional section-splitting unreliable.
KNOWN_SECTION_HEADINGS = (
    "CAREER OBJECTIVE",
    "CONTACT INFO",
    "WORK EXPERIENCE",
    "EDUCATION",
    "SKILLS",
    "CERTIFICATIONS",
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_GITHUB_RE = re.compile(r"github\.com/[\w.-]+", re.IGNORECASE)
_LINKEDIN_RE = re.compile(r"linkedin\.com/in/[\w.-]+", re.IGNORECASE)
# A phone number: optional country code then three groups of digits separated
# by spaces or hyphens (e.g. "+61 433 224 556"). Requires enough digits that it
# won't match years or metrics elsewhere in the document.
_PHONE_RE = re.compile(r"\+?\d{1,3}[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{3}")


class ContactInfo(TypedDict):
    email: Optional[str]
    phone: Optional[str]
    linkedin: Optional[str]
    github: Optional[str]


class ParsedResume(TypedDict):
    page_count: int
    raw_text: str
    char_count: int
    contact: ContactInfo
    sections: dict[str, bool]
    format_hash: str


def _resolve(path: PathLike) -> Path:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Resume PDF not found: {p}")
    return p


def compute_format_hash(pdf_path: PathLike) -> str:
    """Return the SHA-256 hex digest of the raw PDF bytes (format identity)."""
    p = _resolve(pdf_path)
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _extract_contact(text: str) -> ContactInfo:
    email = _EMAIL_RE.search(text)
    github = _GITHUB_RE.search(text)
    linkedin = _LINKEDIN_RE.search(text)
    phone = _PHONE_RE.search(text)
    return ContactInfo(
        email=email.group(0) if email else None,
        phone=phone.group(0).strip() if phone else None,
        linkedin=linkedin.group(0) if linkedin else None,
        github=github.group(0) if github else None,
    )


def _detect_sections(text: str) -> dict[str, bool]:
    """Return only the known headings that actually appear in the text."""
    upper = text.upper()
    return {heading: True for heading in KNOWN_SECTION_HEADINGS if heading in upper}


def parse_resume_pdf(pdf_path: PathLike) -> ParsedResume:
    """Parse a resume PDF into text, contact fields, and detected sections.

    The returned ``sections`` maps each known heading to whether it was found;
    ``format_hash`` is the same value as :func:`compute_format_hash`.
    """
    p = _resolve(pdf_path)

    pages_text: list[str] = []
    with pdfplumber.open(p) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")

    raw_text = "\n".join(pages_text)

    return ParsedResume(
        page_count=page_count,
        raw_text=raw_text,
        char_count=len(raw_text),
        contact=_extract_contact(raw_text),
        sections=_detect_sections(raw_text),
        format_hash=hashlib.sha256(p.read_bytes()).hexdigest(),
    )
