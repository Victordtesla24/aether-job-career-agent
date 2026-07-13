"""GAP-P4-044 — master-resume bullet extraction produces complete sentences.

The bundled resume has a two-column layout. In the flat text stream that
``pdfplumber`` returns, each wrapped work bullet's continuation lines are
interleaved with unrelated left-rail content (EDUCATION / SKILLS / CONTACT), so
the line-based :func:`extract_bullets` captures only the first (marker) line of
each bullet — a truncated fragment that the tailoring LLM then "completes" into
incoherent, duplicated output. The positional :func:`extract_pdf_bullets`
rejoins each bullet from its column, restoring complete sentences.
"""
from __future__ import annotations

from app.agents.fit_scorer import get_base_resume_path
from app.services.resume_parser import parse_resume_pdf
from app.services.resume_pdf import extract_pdf_bullets
from app.services.resume_tailor import extract_bullets

_TERMINAL = (".", "!", "?")


def _fragments(bullets: list[str]) -> list[str]:
    """Bullets that end mid-sentence (no terminal punctuation)."""
    return [b for b in bullets if not b.rstrip().endswith(_TERMINAL)]


def test_positional_extraction_yields_complete_sentences() -> None:
    bullets = extract_pdf_bullets(get_base_resume_path())
    assert bullets, "no bullets extracted from the bundled resume"
    frags = _fragments(bullets)
    assert not frags, f"positional extractor produced fragmented bullets: {frags}"


def test_positional_extraction_fixes_line_based_fragmentation() -> None:
    """Regression baseline: the legacy line-based extractor fragments this
    two-column resume; the positional extractor must not."""
    path = get_base_resume_path()
    raw_text = parse_resume_pdf(path)["raw_text"]

    line_based = extract_bullets(raw_text)
    positional = extract_pdf_bullets(path)

    # The defect: the flat-text extractor truncates most bullets into fragments.
    assert _fragments(line_based), (
        "expected the line-based extractor to fragment the two-column resume "
        "(regression baseline for GAP-P4-044)"
    )
    # The fix: positional extraction rejoins every bullet.
    assert not _fragments(positional)
    # And it recovers whole bullets, not a longer list of scraps.
    assert len(positional) < len(line_based)
