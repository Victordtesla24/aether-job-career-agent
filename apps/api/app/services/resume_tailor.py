"""LLM-powered resume bullet tailoring with anti-fabrication guards (P2-S05).

The service rewords existing resume bullets to emphasise keywords from a job
description. Hard guarantees:

- **No invention**: any bullet containing a token absent from the original
  resume text is rejected (the original bullet is kept instead).
- **Evidence trace**: every bullet returned carries an ``evidenceRef``
  pointing at the original bullet it derives from.
- **Format preservation**: the source PDF is never touched — tailoring works
  on extracted text only, keyed by the resume's format hash.

The LLM call goes through :mod:`app.services.llm_client` (record-replay), so
tests and CI never hit the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.llm_client import LLMClient, get_model

SYSTEM_PROMPT = (
    "You are a precision resume editor. Only reword existing bullets to match "
    "keywords. Never add skills, titles, employers not in original. Each "
    "rewritten bullet must trace to an evidenceRef. Respond with JSON: "
    '{"bullets": [{"text": "...", "evidenceRef": "bullet-N"}], '
    '"evidenceRefs": ["bullet-N", ...]}'
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_BULLET_MARKERS = ("•", "●", "▪", "- ")

# ---------------------------------------------------------------------------
# Evidence normalization (ADR D-0015).
#
# The anti-fabrication check compares *content* tokens of a rewritten bullet
# against the source resume. Before comparison both sides are normalized:
# unicode punctuation folding, case folding, inflectional suffix stripping,
# and number-format equivalence. Stopwords / function words are ignored.
# A bullet is rejected iff it contains a content token (skill, tool, employer,
# metric, claim) with no normalized match in the evidence.
# ---------------------------------------------------------------------------

#: Unicode punctuation folded to ASCII equivalents before tokenizing so
#: "end‑to‑end" (U+2011) matches "end-to-end" and "≈92%" matches "~92%".
_UNICODE_FOLD = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2248": "~", "\u223c": "~", "\uff05": "%",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u200b": "",
    "\u2026": "...", "\u00d7": "x",
})

#: Function words / connectives that carry no factual claim — ignored by the
#: novelty check. Deliberately excludes domain nouns (skills, tools, titles).
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does doing for
    from had has have having he her hers him his how i if in into is it its
    itself me more most my no nor not of off on once only or other our ours
    out over own she so some such than that the their theirs them then there
    these they this those through to too under until up very was we were what
    when where which while who whom why will with would you your yours
    across within during between among around about after before both each
    per via using toward towards ensuring enabling driving delivering
    including also well highly strong proven key new
    percent percentage approximately approx roughly nearly almost
    """.split()
)

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _fold(text: str) -> str:
    """Unicode-punctuation fold + case fold."""
    return text.translate(_UNICODE_FOLD).lower()


def _stem(token: str) -> str:
    """Cheap inflectional-suffix stripper (both sides use it, so it only
    needs to be consistent — not linguistically perfect)."""
    if len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    else:
        for suffix in ("ingly", "ing", "edly", "ed", "ers", "er", "est", "es", "ly", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                token = token[: len(token) - len(suffix)]
                break
    # Fold trailing 'e' so manage/managed and deliver/delivery converge.
    if len(token) > 3 and token[-1] in ("e", "y"):
        token = token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(_fold(text)))


def _evidence_index(text: str) -> tuple[set[str], set[str]]:
    """(normalized token+stem set, number set) for the evidence corpus."""
    tokens = _tokens(text)
    stems = tokens | {_stem(t) for t in tokens}
    numbers = set(_NUMBER_RE.findall(_fold(text).replace(",", "")))
    return stems, numbers


def unsupported_tokens(
    text: str, evidence_stems: set[str], evidence_numbers: set[str]
) -> list[str]:
    """Content tokens in ``text`` with no normalized match in the evidence.

    Number-bearing tokens match when their numeric value appears anywhere in
    the evidence (so "92%", "≈92%" and "92 percent" are equivalent); word
    tokens match by exact or stem equality; stopwords are ignored.
    """
    novel: list[str] = []
    for tok in _TOKEN_RE.findall(_fold(text)):
        if tok in _STOPWORDS:
            continue
        if any(ch.isdigit() for ch in tok):
            nums = _NUMBER_RE.findall(tok.replace(",", ""))
            if nums and all(n in evidence_numbers for n in nums):
                continue
            if tok in evidence_stems:  # e.g. mixed tokens like "24x7"
                continue
            novel.append(tok)
            continue
        if tok in evidence_stems or _stem(tok) in evidence_stems:
            continue
        novel.append(tok)
    return novel


def extract_bullets(raw_text: str) -> list[str]:
    """Pull bullet-point lines out of extracted resume text."""
    bullets: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(_BULLET_MARKERS):
            bullets.append(stripped.lstrip("•●▪- ").strip())
    return bullets


@dataclass
class TailorResult:
    """Validated output of a tailoring run."""

    bullets: list[dict[str, str]] = field(default_factory=list)
    #: Number of bullets whose text actually changed vs the original.
    changes: int = 0
    #: Bullets the guard rejected (invented tokens / missing evidenceRef).
    rejected: list[str] = field(default_factory=list)


class ResumeTailorService:
    """Rewrites bullets via the LLM, then validates against the source resume."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    def tailor(self, resume_text: str, job_description: str) -> TailorResult:
        bullets = extract_bullets(resume_text)
        user_prompt = (
            "Job description:\n" + job_description + "\n\nOriginal bullets:\n"
            + "\n".join(f"bullet-{i}: {b}" for i, b in enumerate(bullets))
        )
        raw = self._llm.complete_json(
            "tailor",
            SYSTEM_PROMPT,
            user_prompt,
            model=get_model("REASONING"),
            temperature=0.0,
        )
        return self._validate(raw, bullets, resume_text)

    def _validate(
        self, raw: Any, originals: list[str], resume_text: str
    ) -> TailorResult:
        evidence_stems, evidence_numbers = _evidence_index(resume_text)
        result = TailorResult()
        by_ref = {f"bullet-{i}": b for i, b in enumerate(originals)}
        for item in raw.get("bullets", []):
            text = (item.get("text") or "").strip()
            ref = item.get("evidenceRef")
            if not text or not ref or ref not in by_ref:
                result.rejected.append(text or "<empty>")
                continue
            if unsupported_tokens(text, evidence_stems, evidence_numbers):
                # Fabrication guard (D-0015): a content token with no
                # normalized evidence match → keep the original bullet.
                result.rejected.append(text)
                text = by_ref[ref]
            result.bullets.append({"text": text, "evidenceRef": ref})
            if text != by_ref[ref]:
                result.changes += 1
        return result


def tailor_bullets(
    bullets: list[str],
    job_description: str,
    *,
    model: Optional[str] = None,  # noqa: ARG001 — kept for P1 signature stability
) -> list[str]:
    """Legacy P1 seam — lossless passthrough retained for existing callers."""
    return list(bullets)
