"""Résumé → discrete achievement bullets, and the achievement identity a Story
Bank entry is keyed on.

WHY THIS EXISTS (audited live on the production DB, 2026-08-02)
--------------------------------------------------------------
The owner's Story Bank held 43 live ``StoryEntry`` rows describing only ~10
distinct achievements — 33 near-duplicate re-tellings — while ~17 genuinely
distinct résumé achievements had no story at all, and two rows carried no
metric whatsoever. Sample of the duplication, all four of these are the SAME
résumé bullet:

    "JIRA Analytics Dashboard for Agile Insight Generation"
    "JIRA Analytics Dashboard for Sprint Velocity & LLM-Powered Retrospectives"
    "JIRA Analytics Dashboard for Agile Team Visibility"
    "Analytics Dashboard for Sprint Velocity & LLM-Retrospectives"

The extractor had no stable notion of *which achievement* a story is about. It
deduped on (a) an exact sha256 of the five STAR fields — one reworded word
defeats it — and (b) a fuzzy title+achievement Jaccard pair whose create-time
preset requires title Jaccard >= 0.70. Measured over all 903 pairs of the live
rows, same-achievement pairs have a MEDIAN title Jaccard of 0.333 and a 90th
percentile of 0.625: the live duplicates sit almost entirely BELOW the
threshold, which is exactly why they accumulated.

No threshold tweak fixes that, because paraphrase drift is unbounded. The fix
is to stop guessing from prose and anchor every story to the one thing that is
both stable and real: **the résumé bullet the story is drawn from**.

WHAT THIS MODULE PROVIDES
-------------------------
* :func:`extract_resume_bullets` — deterministic (no LLM) segmentation of the
  user's OWN résumé text into the achievement bullets it actually contains,
  each with a stable ``B<n>`` handle. The extractor prompt hands the model
  these bullets and requires each story to cite one by id, so the story's
  evidence is a real, addressable slice of the user's own résumé rather than
  an unverifiable claim about it.
* :func:`bullet_numbers` — the numeric tokens THAT bullet evidences. The old
  metric guard validated a story's numbers against the WHOLE résumé, so a
  war-room story could "evidence" the 92% that belongs to a different bullet
  entirely. Scoping the check to the cited bullet closes that hole.
* :func:`achievement_key` — the per-user identity of an achievement: a sha256
  over the bullet's normalized text. Two stories citing the same bullet share
  a key no matter how far their wording drifts, which turns dedup from a
  similarity heuristic into an exact lookup (and into a database uniqueness
  guarantee — see ``app.db.ensure_story_achievement_column``).

Nothing here invents content. Every bullet returned is a verbatim slice of the
user's own résumé (whitespace-normalized and de-hyphenated across the PDF line
breaks that split words such as ``"test- evidence"``).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

#: A bullet marker sitting alone on its own line. Some PDF text extractions
#: (see ``app.services.resume_parser``) emit the glyph and its content on
#: separate lines, which makes this the cleanest record separator available.
_BULLET_SEPARATOR = re.compile(r"(?m)^[ \t]*[•●▪‣⁃*\-·]+[ \t]*$")

#: The same glyphs ANYWHERE in the text. Multi-column résumé layouts (the
#: operator's own bundled PDF is one) extract with the marker inline and the
#: side column interleaved between lines, so no own-line separator exists at
#: all. Verified: the own-line pattern finds 0 bullets in that layout while
#: this one finds all of them. Only unambiguous bullet glyphs are listed —
#: "-" and "*" occur inside ordinary prose and would shred it.
_INLINE_BULLET = re.compile(r"[•●▪‣⁃]")

#: Below this many bullets, the own-line split is assumed not to be the
#: document's real structure and the inline split is tried as well.
_SPARSE_SPLIT = 3

#: Section headings. A segment containing one is résumé chrome (contact block,
#: skills column, certifications list), never a single achievement.
_SECTION_HEADING = re.compile(
    r"\b(CONTACT INFO|CONTACT|EDUCATION|SKILLS|CERTIFICATIONS?|WORK EXPERIENCE|"
    r"EXPERIENCE|CAREER OBJECTIVE|OBJECTIVE|PROJECTS?|PROFESSIONAL SUMMARY|"
    r"SUMMARY|REFERENCES|HONORS|HONOURS|AWARDS|PUBLICATIONS|INTERESTS|"
    r"LANGUAGES|VOLUNTEER)\b"
)

#: Prose function words. A comma-separated skills column ("Enterprise
#: Architecture, Data Architecture, MLOps, CI/CD, DevOps, …") contains none of
#: these; a sentence describing an achievement always contains several. This
#: is what separates the two WITHOUT a hand-maintained skills blocklist.
_FUNCTION_WORD = re.compile(
    r"\b(the|to|a|an|of|for|with|that|through|by|from|into|across|"
    r"which|while|after|before|when)\b",
    re.IGNORECASE,
)

#: A word split across a PDF line break: "test- evidence" -> "test-evidence".
_SOFT_HYPHEN_BREAK = re.compile(r"(?<=[A-Za-z])-\s+(?=[a-z])")

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

#: A digit run NOT glued to a preceding letter OR digit — a measurement
#: rather than an identifier ("D3", "AC6-AC19", "log4j", ".NET"). The digit
#: exclusion matters: without it "AC19" still "quantified" a bullet via its
#: trailing 9, whose predecessor is a digit rather than the letter that
#: started the token. Same rule as ``story_extractor._NUMBER_RE``.
_STANDALONE_NUMBER = re.compile(r"(?<![A-Za-z0-9])\d")

#: Magnitude suffixes a résumé writes numbers with ("10k+", "$5M", "2bn").
_MAGNITUDES = {"k": 1_000, "m": 1_000_000, "bn": 1_000_000_000, "b": 1_000_000_000}
_MAGNITUDE = re.compile(r"\s?(bn|[kmb])\b")

#: Spelled-out small numbers a résumé uses in prose ("in under three hours").
_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12",
}

#: Segmentation gates. Deliberately shape-based (length / word count / prose
#: density), never keyword-based, so they generalise to any user's résumé.
_MIN_CHARS = 60
_MAX_CHARS = 1200
_MIN_WORDS = 10
_MIN_FUNCTION_WORDS = 2


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonicalize_bullet(text: str) -> str:
    """A bullet's display form: whitespace collapsed, PDF hyphenation repaired.

    This is the exact text handed to the model and stored as the story's
    evidence, so it must stay a verbatim (if re-whitespaced) slice of the
    user's own résumé — never a rewrite.
    """
    return _SOFT_HYPHEN_BREAK.sub("-", _normalize_whitespace(text))


def _is_achievement(text: str) -> bool:
    if _SECTION_HEADING.search(text):
        return False
    if not (_MIN_CHARS <= len(text) <= _MAX_CHARS):
        return False
    if len(text.split()) < _MIN_WORDS:
        return False
    return len(_FUNCTION_WORD.findall(text)) >= _MIN_FUNCTION_WORDS


def extract_resume_bullets(resume_text: str) -> list[dict[str, str]]:
    """The achievement bullets in ``resume_text``, in document order.

    Returns ``[{"id": "B1", "text": "<verbatim bullet>"}, ...]``. Ids are
    positional and therefore stable for a given résumé text, which is what
    lets the model cite one and lets the caller verify the citation.

    Three splitting strategies are tried, best-first, because résumé PDFs do
    not extract uniformly: own-line bullet markers (cleanest), inline bullet
    glyphs (multi-column layouts), then paragraphs (no glyphs at all). The
    strategy that yields the most achievement bullets wins, so a document is
    never reduced to "no evidence" by a layout quirk.
    """
    text = resume_text or ""

    def _kept(segments: list[str]) -> list[str]:
        return [s for s in (canonicalize_bullet(x) for x in segments) if _is_achievement(s)]

    kept = _kept(_BULLET_SEPARATOR.split(text))
    if len(kept) < _SPARSE_SPLIT:
        inline = _kept(_INLINE_BULLET.split(text))
        if len(inline) > len(kept):
            kept = inline
    if not kept:
        kept = _kept(re.split(r"\n\s*\n", text))
    return [{"id": f"B{i}", "text": t} for i, t in enumerate(kept, start=1)]


def bullet_numbers(text: str) -> set[str]:
    """Numeric tokens evidenced by THIS bullet.

    Every value here is something the bullet ITSELF states — the set is the
    bullet's own claims written the several ways a writer may legitimately
    render them, never an inference, an estimate or a round-up:

    * thousands separators dropped ("$5,000" evidences "5000");
    * a decimal evidenced whole and split, so "3.5 hours" may be written
      "3.5", "3" or "5";
    * MAGNITUDE SUFFIXES expanded — a bullet saying "10k+ device concurrency"
      evidences "10000" (and "10,000" once separators are stripped), and "$5M"
      evidences "5000000". "10k" and "10,000" are the same claim in different
      notation; rejecting the second as fabricated was a FALSE POSITIVE
      (observed live: a real WebSocket story rejected for writing "10,000+");
    * SPELLED-OUT small numbers — "in under three hours" evidences "3". The
      résumé says three; a story writing "3 hours" has invented nothing.

    Both expansions only ever ADD renderings of numbers the bullet already
    states. A number the bullet does not state in ANY form is still rejected,
    which is the entire point of the check.
    """
    numbers: set[str] = set()

    def _add(value: str) -> None:
        plain = value.replace(",", "")
        numbers.add(plain)
        if "." in plain:
            numbers.add(plain.rstrip("0").rstrip("."))
            whole, _, frac = plain.partition(".")
            numbers.add(whole)
            numbers.add(frac)

    lowered = (text or "").lower()
    for match in _NUMBER.finditer(text or ""):
        _add(match.group())
        suffix = _MAGNITUDE.match(lowered[match.end():])
        if suffix:
            scaled = float(match.group().replace(",", "")) * _MAGNITUDES[
                suffix.group(1).lower()
            ]
            _add(f"{scaled:.0f}" if scaled == int(scaled) else str(scaled))
    for word, digit in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            numbers.add(digit)
    return {n for n in numbers if n}


def is_quantified(text: str) -> bool:
    """True when the bullet states a real quantity a story must carry.

    A digit glued to letters is an IDENTIFIER, not a measurement — "D3 event
    arcs", "AC6-AC19", "log4j", ".NET", "PI 47-48". Counting those as
    quantification made the extractor drop perfectly good stories for
    "carrying no metric" when their source bullet had no metric to carry
    (observed live: the D3 visualisation bullet). Only a digit run that does
    not begin immediately after a letter counts.
    """
    return bool(_STANDALONE_NUMBER.search(text or ""))


def _identity_text(text: str) -> str:
    """Wording-stable identity of a bullet: lowercased alphanumerics only.

    Case, punctuation and whitespace drift between two renderings of the same
    résumé bullet must not create a second achievement; a genuinely different
    bullet must not collide. Digits are KEPT — "30 to 90 person-days" and
    "30 to 120 person-days" are different claims.
    """
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def achievement_key(user_id: str, bullet_text: str) -> str:
    """Per-user identity of the achievement ``bullet_text`` describes.

    Scoped by ``user_id`` so two users whose résumés share a boilerplate line
    can never collide into one row, and truncated to 32 hex chars (128 bits) —
    collision-free at any plausible Story Bank size while staying comfortably
    inside an index.
    """
    digest = hashlib.sha256(
        f"{user_id}\x1f{_identity_text(bullet_text)}".encode()
    ).hexdigest()
    return digest[:32]


def find_bullet(bullets: list[dict[str, Any]], bullet_id: Any) -> dict[str, Any] | None:
    """The bullet with ``bullet_id`` (case/whitespace tolerant), or ``None``."""
    wanted = str(bullet_id or "").strip().upper()
    if not wanted:
        return None
    for bullet in bullets:
        if str(bullet["id"]).upper() == wanted:
            return bullet
    return None
