"""The ONE assembly of the cover-letter guard corpora (U-STORY-1 ruling E3).

Two code paths produce a customer-facing cover letter: ``CoverLetterAgent.run``
generates one, and ``POST /cover-letters/{id}/refine`` revises one — re-composing
the revision, storing it as a brand-new row and opening a fresh approval. Both
run the same two guards over their output:

* the **FabricationGuard** (``fabrication_guard.find_unsupported_entities``),
  whose corpus answers "is this ENTITY known to exist in this context at all?" —
  so it legitimately includes the target role, the company, the letter date, the
  signer, and the SANITIZED job description alongside the candidate's evidence;
* the **§9 claim guard** (``resume_tailor.unsupported_claim_tokens``), whose
  evidence answers the much stricter "does the CANDIDATE actually have this?" —
  so the job description is never part of it (GAP-P6-COV-001/ML-W23: a claim
  backed only by the posting is a fabrication about the candidate), and the
  company NAME is, purely so naming the employer is not itself flagged.

They forked. ``career_corpus`` — the consolidated GitHub / portfolio / LinkedIn
evidence (ADR D-0031) — was in the generation path's FabricationGuard corpus and
NOT in the refine path's, a difference recorded in code as a known residual
rather than silently patched. The user-visible consequence was one-directional
and bad: a system name, employer or metric that only the candidate's ingested
career evidence proves passed generation, was accepted by the human, and was
then flagged as an unsupported ENTITY the moment they asked the Studio to refine
that same letter. The candidate's own, already-approved, evidenced claim read as
a fabrication.

ML-W26's rule is that the refine path must mirror the generation path's evidence
semantics EXACTLY, "never fork them". A comment cannot enforce that; a shared
function can. Both paths now call :func:`build_guard_corpora`, so widening or
narrowing either corpus is necessarily a change to both.

This module contains no guard logic and makes no judgement. It only decides
which text is handed to which guard — a strict, symmetric widening with the
candidate's OWN evidence that the neighbouring guard already trusted. An entity
NOTHING supports is still flagged, unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardCorpora:
    """The two evidence texts one cover-letter draft is adjudicated against."""

    #: FabricationGuard corpus — "does this entity exist in this context?"
    #: Candidate evidence + system/profile ground truth + the SANITIZED posting.
    fabrication_corpus: str
    #: §9 claim-guard evidence — "does the CANDIDATE have this?" The candidate's
    #: own evidence plus their identity and the target company's name ONLY.
    claim_evidence: str


def build_guard_corpora(
    *,
    resume_text: str,
    job_title: str,
    company: str,
    sanitized_description: str,
    letter_date: str,
    signer: str,
    position: str,
    career_corpus: str = "",
    story_evidence: str = "",
    corpus_evidence: str = "",
    company_facts: str = "",
) -> GuardCorpora:
    """Assemble both corpora for one cover-letter draft.

    ``sanitized_description`` must already be the SANITIZED form of the posting
    (``prompt_safety.sanitize_untrusted_text``): the job description is
    attacker-controlled, and a redacted injection clause must never be able to
    "ground" an injected token past the FabricationGuard
    (MV-cover-letter-studio-003). It is passed in rather than sanitized here so
    each caller keeps using the single sanitized value it also feeds to the
    prompt and to the §9 risk vocabulary — one sanitization, one string.

    ``company_facts`` (AUD-COV-3, optional): the SANITIZED text of a real,
    fetched company fact (``app.services.company_facts.fetch_company_facts``)
    the letter may cite. Treated EXACTLY like ``sanitized_description`` — it
    answers "does this entity exist in this context?" for the
    FabricationGuard (so a cited fact is not flagged as fabricated) but is
    never §9 claim evidence, same reasoning as the job description: a fact
    ABOUT THE COMPANY is not evidence the CANDIDATE personally has anything,
    and a personal claim grounded only in fetched company vocabulary is a
    fabrication about the candidate exactly like one grounded only in JD
    vocabulary.

    The three evidence units are optional because they genuinely can be empty:
    a user with no ingested career data, no Story Bank entries or no evidence
    corpus contributes nothing, and empty units are DROPPED rather than joined
    as blanks — an empty string is an absence, not evidence.
    """
    evidence_units = [
        unit for unit in (career_corpus, story_evidence, corpus_evidence) if unit
    ]
    fabrication_corpus = " ".join(
        part
        for part in (
            [
                resume_text,
                job_title,
                company,
                sanitized_description,
                company_facts,
                letter_date,
                signer,
                position,
            ]
            + evidence_units
        )
        if part
    )
    claim_evidence = " ".join(
        part
        for part in ([resume_text] + evidence_units + [signer, position, company])
        if part
    )
    return GuardCorpora(
        fabrication_corpus=fabrication_corpus, claim_evidence=claim_evidence
    )
