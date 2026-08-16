"""LLM-assisted résumé bullet extraction, gated against fabrication (RT-004).

The LLM half of the pair; :mod:`app.services.resume_bullets` is the
DETERMINISTIC half and stays that way ("Nothing here invents content" — it is
imported by the Story Bank's identity/dedup path and by ``app.db``, neither of
which may acquire an LLM dependency). Kept in a separate module for exactly
that reason, and because the guarantees differ: that module's output is a
verbatim slice of the résumé BY CONSTRUCTION, this one's is verbatim only
because :func:`llm_extract_bullets` verifies it afterwards.

WHY THIS EXISTS. BOTH shipped extractors are deterministic line/segment state
machines — ``resume_tailor.extract_bullets`` latches onto marker lines ("•",
"-"), all-caps banners and job-header lines, and ``resume_bullets
.extract_resume_bullets`` segments on the same family of signals. That is
exactly right for the résumés they were built for and costs nothing — but a
DESIGNED, multi-column PDF whose text layer carries no markers yields **zero**
bullets from either (measured: both return ``[]`` for the production text
shape) while its ``raw_text`` is complete and correct. Production, owner
résumé v2 (``Vik_Resume_BA.pdf``, 3.4 KB of good text): ``sections.bullets ==
[]``, and with RT-002 in place every tailor run against it now refuses
honestly. Honest, but a dead end — this module is the way out.

WHAT IT IS ALLOWED TO DO. Exactly one thing: SELECT. The model is shown the
user's own résumé text and asked to return the achievement bullets **verbatim**.
It may not rewrite, merge, summarise, correct or invent, and it is not trusted
to obey that instruction: :func:`llm_extract_bullets` REJECTS, in code, every
returned bullet whose text is not a substring of ``raw_text`` after whitespace
normalisation. A model that paraphrases produces fewer bullets, never a
fabricated career history — which matters more here than anywhere else in the
product, because the output is persisted as the user's own experience and
becomes the anti-fabrication evidence corpus every later tailoring guard
adjudicates against. Fabrication admitted HERE would be laundered into
"evidence" downstream.

Normalisation is whitespace + case ONLY (``" ".join(text.split()).casefold()``).
A PDF text layer wraps a single bullet across several lines, so a genuinely
verbatim copy differs from the source in whitespace; and re-casing a fragment's
first letter is not a claim about the candidate. Word ORDER and word CHOICE are
not normalised, so a "rewrite" assembled entirely from words the résumé
contains is still rejected — the gate is substring, never bag-of-words.

COST. One ``complete_json`` call on the STRUCTURED tier (the same tier the
story extractor uses; deliberately NOT user-overridable — this is structured
extraction, not generation). The caller is responsible for metering it: the
endpoint runs through ``_record_run`` exactly like every other genuine LLM
call, so the run is reserved atomically BEFORE this function is entered and
refunded if it fails.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You extract the achievement / experience BULLET POINTS from a resume.\n"
    "Copy each bullet VERBATIM from the resume text you are given — character "
    "for character, in the order it appears. Never rewrite, reword, shorten, "
    "merge, translate, correct or embellish a bullet, and never invent one. A "
    "bullet you cannot copy exactly must be left out.\n"
    "Exclude section headings, contact details, employer/title/date header "
    "lines, education entries and bare skill keyword lists.\n"
    "If the resume states no achievement bullets, return an empty list.\n"
    'Reply with JSON only: {"bullets": ["<verbatim sentence>", ...]}'
)

#: Leading list glyphs / dashes a model may re-emit in front of an otherwise
#: verbatim copy. Stripped before the substring gate (and before storage) so a
#: cosmetic marker is not mistaken for altered content.
_LEADING_MARKERS = " \t•▪◦‣·*-–—"


def _normalise(text: str) -> str:
    """Whitespace-collapsed, case-folded form used for the substring gate."""
    return " ".join(text.split()).casefold()


def _candidate_text(item: Any) -> str:
    """The text of one returned bullet, whatever shape the model wrapped it in."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("text") or "")
    return ""


def llm_extract_bullets(raw_text: str, llm: Any | None = None) -> list[str]:
    """The résumé's achievement bullets, copied verbatim out of ``raw_text``.

    Returns bullets in the order the model returned them, de-duplicated, with
    every entry guaranteed to be present in ``raw_text`` (whitespace/case
    normalised). Returns ``[]`` for empty text or a malformed response — never
    a guess, and never partially-invented content.

    ``llm`` is an injection seam for tests; production passes nothing and gets
    the shared :class:`~app.services.llm_client.LLMClient`.
    """
    text = raw_text or ""
    if not text.strip():
        return []

    from app.services.llm_client import LLMClient, get_model

    client = llm if llm is not None else LLMClient()
    raw = client.complete_json(
        "resume_bullets",
        _SYSTEM_PROMPT,
        "Resume text:\n" + text,
        model=get_model("STRUCTURED"),
        temperature=0.0,
    )
    candidates = raw.get("bullets") if isinstance(raw, dict) else None
    if not isinstance(candidates, list):
        logger.warning(
            "bullet extraction returned no usable 'bullets' list (%s) — "
            "reporting zero rather than guessing",
            type(raw).__name__,
        )
        return []

    haystack = _normalise(text)
    kept: list[str] = []
    seen: set[str] = set()
    rejected = 0
    for item in candidates:
        candidate = _candidate_text(item).strip().lstrip(_LEADING_MARKERS).strip()
        if not candidate:
            continue
        needle = _normalise(candidate)
        if needle not in haystack:
            # THE anti-fabrication gate. Not a warning about a stylistic
            # liberty — a bullet that is not in the résumé is not the user's
            # experience, and persisting it would seed the evidence corpus
            # every downstream guard trusts.
            rejected += 1
            continue
        if needle in seen:
            continue
        seen.add(needle)
        kept.append(candidate)
    if rejected:
        logger.warning(
            "bullet extraction dropped %d of %d returned bullet(s): not present "
            "verbatim in the resume text",
            rejected, len(candidates),
        )
    return kept
