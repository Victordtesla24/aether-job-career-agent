"""Deterministic cover-letter quality score (W-TAILOR-CONVERGE item 4).

The résumé path has had a real, score-aware loop for a while
(:mod:`app.services.tailoring_loop`); the cover letter had NO scoring of any
kind. It was drafted, guarded, and stored — with nothing recording how good
the letter actually was, and no before/after a user could inspect.

This module supplies the missing measurement, under exactly the same honesty
rules as the ATS path:

* **It is a measurement, not an opinion.** Every component is computed from
  the finished text with deterministic code. No LLM is called, so the number
  costs nothing, never drifts between reads, and can be recomputed by anyone
  from the stored letter.
* **Nothing is clamped or rounded up.** :attr:`CoverLetterQuality.reached_target`
  is a strict ``>=`` against the real ``overall``.
* **Unreachable keywords are excluded from the denominator and REPORTED.**
  A job description routinely names skills the candidate simply does not
  have. A truthful letter can never contain them — the fabrication guard
  would (correctly) reject a draft that claimed them. Scoring the letter
  against them would therefore put a permanent, meaningless cap on an honest
  letter AND give an improvement loop a standing incentive to fabricate.
  They are dropped from the score and surfaced as
  :attr:`CoverLetterQuality.unreachable_keywords`, which is the same split
  :func:`app.services.tailoring_loop.split_gap_keywords` applies to the
  résumé.

Components and weights mirror :mod:`app.services.ats_engine` so the two
numbers a user sees side by side are built the same way:

===================  ======  ==============================================
component            weight  meaning
===================  ======  ==============================================
``jd_alignment``      40%    share of the EVIDENCE-SUPPORTED job-description
                             keywords that the letter actually contains
``grounding``         40%    share of the letter's content words backed by
                             the candidate's own evidence corpus
``structure``         20%    the §10.2 letter-format contract the run
                             already enforces (3 paragraphs, names the role
                             or company, real call-to-action, no banned
                             generic opener)
===================  ======  ==============================================

When the posting yields no evidence-supported keywords at all, alignment is
NOT measurable for this pairing — inventing a value either way would be a
fabricated metric — so the component is dropped and the remaining weights are
renormalised, with :attr:`CoverLetterQuality.jd_alignment_measured` recording
that it happened.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.ats_engine import ATSEngine
from app.services.resume_tailor import _evidence_index, _stem
from app.services.tailoring_loop import clean_gap_keywords, split_gap_keywords

#: Quality score at which a letter is "done". Deliberately the SAME number as
#: the ATS target so the two scores in the UI mean comparable things.
DEFAULT_TARGET_SCORE = 85.0

_WEIGHT_ALIGNMENT = 0.4
_WEIGHT_GROUNDING = 0.4
_WEIGHT_STRUCTURE = 0.2

#: Points deducted per §10.2 structural violation (4 violations => 0).
_STRUCTURE_PENALTY = 25.0

#: Generic openers §10.2 forbids outright (kept in sync with
#: ``cover_letter_agent._BANNED_PHRASES`` — imported there, defined here, so
#: there is exactly one copy and no import cycle).
BANNED_OPENERS = (
    "i am writing to express my interest",
    "i am writing to apply",
    "please accept this letter",
    "i would like to apply for",
)

#: Signals that a closing paragraph carries a real call-to-action (§10.2).
CTA_CUES = (
    "discuss",
    "interview",
    "conversation",
    "call",
    "meet",
    "connect",
    "welcome the opportunity",
    "look forward",
    "available",
    "speak",
)

#: Content-word tokenizer + stoplist for :func:`grounding_confidence`. Defined
#: here (and re-exported by ``cover_letter_agent``) so the Studio's displayed
#: confidence and this quality score are computed from ONE definition.
CONTENT_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*")
CONFIDENCE_STOPWORDS = frozenset(
    """
    a an and are as at be been by for from has have i in is it its my of on or
    our that the their this to was we were will with you your who what how when
    across own more most very than then also both each am me not can could would
    should into out about over under they them he she his her role letter
    """.split()
)


def split_paragraphs(body: str) -> list[str]:
    """Split a drafted body into non-empty paragraphs (blank-line delimited,
    falling back to single line breaks when the model omits blank lines)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(paras) == 1 and "\n" in body:
        paras = [p.strip() for p in body.split("\n") if p.strip()]
    return paras


def grounding_confidence(letter: str, corpus: str) -> int:
    """Share (0-100) of the letter's content words backed by the evidence corpus.

    A real, deterministic measurement of the finished artifact — never a
    fabricated or random score. A guard-passed letter, whose every entity and
    metric already traces to the corpus, sits high; a letter padded with
    unevidenced prose degrades honestly.
    """
    corpus_tokens = {t.lower() for t in CONTENT_WORD_RE.findall(corpus or "")}
    words = [
        t
        for t in CONTENT_WORD_RE.findall(letter or "")
        if len(t) >= 3 and t.lower() not in CONFIDENCE_STOPWORDS
    ]
    if not words:
        return 0
    supported = sum(1 for w in words if w.lower() in corpus_tokens)
    return round(100 * supported / len(words))


@dataclass(frozen=True)
class CoverLetterQuality:
    """A deterministic 0-100 quality breakdown of one finished letter."""

    overall: float
    jd_alignment: float
    grounding: float
    structure: float
    target_score: float = DEFAULT_TARGET_SCORE
    #: Strict ``overall >= target_score``. Never a rounded or clamped claim.
    reached_target: bool = False
    #: False when the posting yielded no evidence-supported keywords, so the
    #: alignment component could not be measured and was excluded.
    jd_alignment_measured: bool = True
    #: Evidence-supported JD keywords the letter does NOT yet contain — the
    #: genuinely closable gap an improvement pass should target.
    missing_keywords: list[str] = field(default_factory=list)
    #: JD keywords the candidate's evidence does not support at all. Excluded
    #: from the score; no truthful letter can ever contain them.
    unreachable_keywords: list[str] = field(default_factory=list)
    #: §10.2 violations found, in the wording the corrective loop feeds back.
    structural_issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable form persisted on the Application row."""
        return {
            "overall": self.overall,
            "jdAlignment": self.jd_alignment,
            "grounding": self.grounding,
            "structure": self.structure,
            "targetScore": self.target_score,
            "reachedTarget": self.reached_target,
            "jdAlignmentMeasured": self.jd_alignment_measured,
            "missingKeywords": self.missing_keywords,
            "unreachableKeywords": self.unreachable_keywords,
            "structuralIssues": self.structural_issues,
        }


def structural_issues(
    body: str, job_title: str | None = None, company: str | None = None
) -> list[str]:
    """§10.2 letter-format violations of ``body`` (same checks, same wording as
    ``CoverLetterAgent._structural_issues``).

    ``job_title``/``company`` are optional: the "opening must name the role or
    company" check is simply not applied when the caller has not supplied
    them, rather than being guessed at.
    """
    issues: list[str] = []
    lower = (body or "").lower()
    for phrase in BANNED_OPENERS:
        if phrase in lower:
            issues.append(f'the generic opener "{phrase}" is forbidden')
    paras = split_paragraphs(body or "")
    if len(paras) != 3:
        issues.append(
            "the letter body must have exactly 3 paragraphs (an opening "
            "naming the role, an evidence paragraph, and a closing "
            f"call-to-action); it has {len(paras)}"
        )
    hook = paras[0].lower() if paras else ""
    if job_title or company:
        title_head = re.split(r"\s+[-–—/|(]\s*", job_title or "")[0].strip().lower()
        company_l = (company or "").lower()
        names_role = bool(title_head and title_head in hook)
        names_company = bool(company_l and company_l in hook)
        if not names_role and not names_company:
            issues.append("the opening paragraph must name the exact role or company")
    closing = paras[-1].lower() if paras else ""
    if not any(cue in closing for cue in CTA_CUES):
        issues.append(
            "the closing paragraph must include a specific call-to-action "
            "(invite an interview or conversation)"
        )
    return issues


def score_cover_letter(
    letter: str,
    job_description: str,
    evidence_corpus: str,
    *,
    job_title: str | None = None,
    company: str | None = None,
    target_score: float = DEFAULT_TARGET_SCORE,
) -> CoverLetterQuality:
    """Score one finished letter. Deterministic; makes no LLM call.

    ``letter`` should be the letter BODY (the composed letterhead/sign-off
    adds no quality signal and would dilute the grounding ratio with the
    candidate's own contact details).
    """
    body = (letter or "").strip()
    if not body:
        # No letter exists. Every component is genuinely zero — emitting a
        # neutral placeholder here would be exactly the kind of fabricated
        # metric this module exists to avoid.
        return CoverLetterQuality(
            overall=0.0,
            jd_alignment=0.0,
            grounding=0.0,
            structure=0.0,
            target_score=target_score,
            reached_target=False,
            jd_alignment_measured=False,
            structural_issues=["no letter body was produced"],
        )

    keywords = clean_gap_keywords(ATSEngine()._extract_keywords(job_description or ""))
    supported, unsupported = split_gap_keywords(keywords, evidence_corpus or "")

    letter_stems, _numbers = _evidence_index(body)
    present = [
        kw for kw in supported if kw in letter_stems or _stem(kw) in letter_stems
    ]
    missing = [kw for kw in supported if kw not in present]

    measured = bool(supported)
    alignment = 100.0 * len(present) / len(supported) if measured else 0.0
    grounding = float(grounding_confidence(body, evidence_corpus or ""))
    issues = structural_issues(body, job_title, company)
    structure = max(0.0, 100.0 - _STRUCTURE_PENALTY * len(issues))

    if measured:
        overall = (
            _WEIGHT_ALIGNMENT * alignment
            + _WEIGHT_GROUNDING * grounding
            + _WEIGHT_STRUCTURE * structure
        )
    else:
        # Alignment is not measurable for this pairing — renormalise the two
        # components that ARE measurements rather than inventing a value.
        total = _WEIGHT_GROUNDING + _WEIGHT_STRUCTURE
        overall = (_WEIGHT_GROUNDING * grounding + _WEIGHT_STRUCTURE * structure) / total

    overall = round(max(0.0, min(100.0, overall)), 2)
    return CoverLetterQuality(
        overall=overall,
        jd_alignment=round(alignment, 2),
        grounding=round(grounding, 2),
        structure=round(structure, 2),
        target_score=target_score,
        reached_target=overall >= target_score,
        jd_alignment_measured=measured,
        missing_keywords=missing,
        unreachable_keywords=unsupported,
        structural_issues=issues,
    )
