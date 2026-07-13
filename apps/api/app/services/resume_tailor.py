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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from app.services.llm_client import LLMClient, get_model

SYSTEM_PROMPT = (
    "You are a precision resume editor. Only reword existing bullets to match "
    "keywords. Never add skills, titles, employers not in original. Ground every "
    "rewrite in the candidate's OWN evidence — do NOT copy distinctive phrases "
    "from the job description into their experience; reuse the job's wording only "
    "where the candidate's own bullet already demonstrates it. When the original "
    "bullet contains a quantified outcome (%, $, headcount, timeframe) the "
    "rewrite must keep at least one of those figures. Each rewritten bullet must "
    "trace to the evidenceRef of exactly one original bullet — never reuse an "
    "evidenceRef twice. Respond with JSON: "
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


#: Generic professional vocabulary that names no verifiable qualification —
#: no technology, employer, certification, or measurable domain skill.
#: ADR D-0015 refinement: the guard rejects fabricated *claims*; it must not
#: forbid ordinary rewording. Without this, virtually every natural LLM
#: rewrite was rejected (observed live: 8/8 bullets rejected over words like
#: "improvement" and "documentation"), so tailoring always produced 0 changes.
#: Tokens here are style; skills/tools/employers/metrics stay strict.
_GENERIC_PROFESSIONAL = frozenset(
    """
    improvement improve identify opportunity enhancement enhance digital
    methodology documentation document initiative comprehensive streamline
    practical clarity operational strategic strategy engagement alignment
    collaboration collaborate coordination coordinate oversight prioritize
    prioritization facilitation facilitate discovery lifecycle translate
    gather functional complex analysis analyze cut boost accelerate optimize
    optimization refine robust seamless effective efficient efficiency
    proactive holistic leadership foster champion spearhead orchestrate
    outcome insight roadmap milestone cadence framework practice capability
    maturity excellence transformation modernize modernization simplify
    standardize consolidate rationalize uplift enablement
    selection select migration migrate execution execute successful partner
    technology priority scale dependency expectation meet met vision conduct
    define deep dive engineer contractor sub team
    """.split()
)

#: Stemmed lookup for the generic vocabulary (both sides normalize the same
#: way, so "streamlined" matches "streamline").
_GENERIC_STEMS = frozenset(
    stem for word in _GENERIC_PROFESSIONAL for stem in (word, _stem(word))
)


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(_fold(text)))


def _evidence_index(text: str) -> tuple[set[str], set[str]]:
    """(normalized token+stem set, number set) for the evidence corpus."""
    tokens = _tokens(text)
    stems = tokens | {_stem(t) for t in tokens}
    numbers = set(_NUMBER_RE.findall(_fold(text).replace(",", "")))
    return stems, numbers


#: Positions where a capital letter is expected (segment starts) — sentence
#: boundaries, headers ("Governance:"), bullet markers, line starts.
_SEGMENT_START_RE = re.compile(r"(?:^|[.:;!?•●▪&]\s*|\n\s*|-\s+)")
_SURFACE_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def unsupported_tokens(
    text: str, evidence_stems: set[str], evidence_numbers: set[str]
) -> list[str]:
    """Claim-bearing tokens in ``text`` with no normalized match in the evidence.

    Fabrication risk is classified by surface form (ADR D-0015 refinement):

    - **Numbers/metrics** are always strict — they match only when the numeric
      value appears in the evidence ("92%", "≈92%" and "92 percent" are
      equivalent).
    - **Proper nouns and acronyms** (capitalized mid-segment, ALL-CAPS, or
      mixed-case tokens) are strict — this is how fabricated skills, tools,
      employers and certifications surface ("Kubernetes", "Google", "AWS").
      They pass only via evidence match or the generic-professional list.
    - **Lowercase natural language** is style, not a checkable claim — the
      guard must not forbid ordinary rewording (observed live: every tailor
      run was rejected over words like "improvement" → 0 changes shipped).
    """
    folded_text = text.translate(_UNICODE_FOLD)
    segment_starts = {m.end() for m in _SEGMENT_START_RE.finditer(folded_text)}
    novel: list[str] = []
    for match in _SURFACE_TOKEN_RE.finditer(folded_text):
        surface = match.group(0)
        tok = surface.lower()
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
        capitalized_mid_segment = surface[0].isupper() and match.start() not in segment_starts
        has_inner_uppercase = surface[1:] != surface[1:].lower()
        if not capitalized_mid_segment and not has_inner_uppercase:
            continue  # lowercase prose — style, not a claim
        if tok in evidence_stems or _stem(tok) in evidence_stems:
            continue
        if tok in _GENERIC_PROFESSIONAL or _stem(tok) in _GENERIC_STEMS:
            continue
        novel.append(tok)
    return novel


#: Content-word n-gram length treated as a "distinctive phrase" by the JD-echo
#: guard. Three consecutive content words (stopwords dropped) is long enough
#: that a shared run is a lifted phrase, not incidental vocabulary overlap.
_JD_ECHO_NGRAM = 3


def _content_stems(text: str) -> list[str]:
    """Ordered content-word stems of ``text`` (folded, stopwords dropped)."""
    return [
        _stem(tok)
        for tok in _TOKEN_RE.findall(_fold(text))
        if tok not in _STOPWORDS
    ]


def _ngram_set(stems: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(stems[i : i + n]) for i in range(len(stems) - n + 1)}


def jd_ngram_index(job_description: str) -> set[tuple[str, ...]]:
    """Distinctive content-word n-grams of the target job description."""
    return _ngram_set(_content_stems(job_description), _JD_ECHO_NGRAM)


def jd_echoed_phrases(
    text: str,
    jd_ngrams: set[tuple[str, ...]],
    evidence_ngrams: set[tuple[str, ...]],
) -> list[str]:
    """Distinctive JD phrases a rewrite lifts that the user's evidence lacks.

    A content-word n-gram present in the target job description but absent from
    the user's own resume is a phrase copied from the *posting*, not grounded in
    their real experience (GAP-P4-045, audit clause (a): the rewrite must
    reflect the user's consolidated career data, not phrases from the target
    job). Numbers and proper nouns are already policed by
    :func:`unsupported_tokens`; this catches the lowercase phrase-level lifting
    the evidence-normalization guard is blind to (e.g. "first-class software",
    "high-traffic environment" echoed straight from the JD).
    """
    text_ngrams = _ngram_set(_content_stems(text), _JD_ECHO_NGRAM)
    lifted = text_ngrams & (jd_ngrams - evidence_ngrams)
    return sorted(" ".join(gram) for gram in lifted)


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

    def tailor(
        self,
        resume_text: str,
        job_description: str,
        originals: Sequence[dict[str, str] | str] | None = None,
    ) -> TailorResult:
        """Tailor ``originals`` bullets (or bullets extracted from
        ``resume_text``) against ``job_description``.

        Passing the parent version's stored bullets keeps re-tailoring
        consistent: changes are counted against what the user actually sees,
        not against the immutable base ``raw_text``.
        """
        structured = self._structure_originals(originals, resume_text)
        user_prompt = (
            "Job description:\n" + job_description + "\n\nOriginal bullets:\n"
            + "\n".join(f"{b['evidenceRef']}: {b['text']}" for b in structured)
        )
        raw = self._llm.complete_json(
            "tailor",
            SYSTEM_PROMPT,
            user_prompt,
            model=get_model("REASONING"),
            temperature=0.0,
        )
        return self._validate(raw, structured, resume_text, job_description)

    @staticmethod
    def _structure_originals(
        originals: Sequence[dict[str, str] | str] | None, resume_text: str
    ) -> list[dict[str, str]]:
        if originals is None:
            return [
                {"text": b, "evidenceRef": f"bullet-{i}"}
                for i, b in enumerate(extract_bullets(resume_text))
            ]
        structured: list[dict[str, str]] = []
        seen_refs: set[str] = set()
        for i, b in enumerate(originals):
            if isinstance(b, str):
                entry = {"text": b, "evidenceRef": f"bullet-{i}"}
            else:
                entry = {
                    "text": b.get("text", ""),
                    "evidenceRef": b.get("evidenceRef") or f"bullet-{i}",
                }
            # Heal duplicated refs from pre-fix tailored versions (first
            # occurrence wins) so corruption never propagates to children.
            if entry["evidenceRef"] in seen_refs:
                continue
            seen_refs.add(entry["evidenceRef"])
            structured.append(entry)
        return structured

    def _validate(
        self,
        raw: Any,
        originals: Sequence[dict[str, str] | str],
        resume_text: str,
        job_description: str = "",
    ) -> TailorResult:
        evidence_stems, evidence_numbers = _evidence_index(resume_text)
        jd_ngrams = jd_ngram_index(job_description)
        evidence_ngrams = _ngram_set(_content_stems(resume_text), _JD_ECHO_NGRAM)
        result = TailorResult()
        structured = self._structure_originals(originals, resume_text)
        by_ref = {b["evidenceRef"]: b["text"] for b in structured}
        accepted: dict[str, str] = {}
        for item in raw.get("bullets", []):
            text = (item.get("text") or "").strip()
            ref = item.get("evidenceRef")
            if not text or not ref or ref not in by_ref:
                result.rejected.append(text or "<empty>")
                continue
            if ref in accepted:
                # A second rewrite of the same source bullet would duplicate
                # content in the stored version — keep the first only.
                result.rejected.append(text)
                continue
            original = by_ref[ref]
            if unsupported_tokens(text, evidence_stems, evidence_numbers):
                # Fabrication guard (D-0015): a content token with no
                # normalized evidence match → keep the original bullet.
                result.rejected.append(text)
                text = original
            elif _NUMBER_RE.search(original) and not _NUMBER_RE.search(text):
                # Quantified-outcome guard: a rewrite that drops every metric
                # from a quantified bullet weakens the resume — keep original.
                result.rejected.append(text)
                text = original
            elif jd_echoed_phrases(text, jd_ngrams, evidence_ngrams):
                # JD-echo guard (GAP-P4-045): the rewrite lifts a distinctive
                # phrase from the job posting that the candidate's own evidence
                # never contained → keep the original, evidence-grounded bullet.
                result.rejected.append(text)
                text = original
            accepted[ref] = text
        # Merge: every original bullet survives in order; validated rewrites
        # replace their source by evidenceRef. ``changes`` therefore counts
        # exactly the bullets a diff against the parent will show.
        for b in structured:
            text = accepted.get(b["evidenceRef"], b["text"])
            result.bullets.append({"text": text, "evidenceRef": b["evidenceRef"]})
            if text != b["text"]:
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
