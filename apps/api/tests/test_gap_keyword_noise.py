"""BLOCKER (tailoring convergence): ``clean_gap_keywords`` does not do what its
commit claims — tokenization noise still reaches the user.

MEASURED, from the LIVE production ``aether`` schema on 2026-08-03 (every token
below was read back out of a real persisted
``Resume.sections->'tailoringSummary'->'gapKeywords'`` row, i.e. it had already
survived ``clean_gap_keywords`` in production)::

    SET search_path TO aether;
    SELECT DISTINCT jsonb_array_elements_text(
        sections->'tailoringSummary'->'gapKeywords')
    FROM "Resume" WHERE sections ? 'tailoringSummary';

    -> ... act believe yourself applicable every around nbsp county
       effective such more industry job actually information other
       between don continue behind answering biggest ...

Three distinct classes of garbage are in that list:

1. **Contraction fragments.** ``ats_engine._TOKEN_RE`` is
   ``[a-zA-Z][a-zA-Z0-9+#.\\-]*`` — the apostrophe is NOT in the character
   class, so ``don't`` tokenizes to ``don`` + ``t``. ``t`` is dropped by the
   existing ``len(token) <= 2`` rule; ``don`` is three characters and sails
   straight through. Same for ``doesn``, ``isn``, ``won``, ``couldn`` … The
   existing ``_CONTRACTION_FRAGMENTS`` set only ever listed the SUFFIX halves
   ("re", "ll", "ve"), never the ``n``-final prefix halves.

2. **Closed-class function words** — determiners, quantifiers, pronouns,
   conjunctions, prepositions, degree adverbs, modals: ``other``, ``each``,
   ``more``, ``between``, ``actually``, ``every``, ``such``, ``around``,
   ``yourself``, ``behind``. English closed classes take no new members, so no
   present or future skill can ever be one of these words — dropping them is
   safe by construction, unlike guessing at open-class vocabulary.

3. **HTML entity names** — ``nbsp`` (from ``&nbsp;`` in scraped postings).

Why this matters beyond tidiness: ``gapKeywords`` and its
``unsupportedGapKeywords`` half are (a) named verbatim in the user-facing
honesty warning ("these job-description keywords appear nowhere in your
résumé … — openai, employment, don, other, …") and (b) written into the LLM's
FORBIDDEN-keyword list in ``TailoringLoop._build_directive``. Telling a
rewrite model it must keep the word "other" or "more" out of the résumé is
noise that competes with the real prohibitions the anti-fabrication guard
depends on.

NOTHING here touches the anti-fabrication guard. ``clean_gap_keywords`` only
decides which words are worth ASKING about; every rewrite still goes through
the same unmodified entailment guard, and this change strictly shrinks the
set of words the model is nudged toward.
"""
from __future__ import annotations

import pytest

from app.services.tailoring_loop import clean_gap_keywords

#: Read back out of live production rows (see module docstring) — every one of
#: these had already passed through ``clean_gap_keywords`` in production.
PRODUCTION_NOISE = [
    # 1. contraction fragments left by the apostrophe-splitting tokenizer
    "don",
    # 2. closed-class function words
    "other",
    "actually",
    "each",
    "more",
    "between",
    "every",
    "such",
    "around",
    "yourself",
    "behind",
    # 3. HTML entity name
    "nbsp",
]

#: Real skill/keyword terms from the same production rows. These must survive —
#: a noise filter that also eats real keywords would break convergence far
#: worse than the noise does.
PRODUCTION_SIGNAL = [
    "kubernetes",
    "kafka",
    "clickhouse",
    "mongodb",
    "rust",
    "java",
    "terraform",
    "orchestration",
    "devsecops",
    "algorithms",
    "distributed",
    "scalable",
    "deployment",
]


@pytest.mark.parametrize("token", PRODUCTION_NOISE)
def test_clean_gap_keywords_strips_real_production_noise(token: str) -> None:
    """Each token is one that LEAKED in production. None may survive."""
    cleaned = clean_gap_keywords([token, "kubernetes"])
    assert token not in cleaned, (
        f"{token!r} survived clean_gap_keywords and would reach both the "
        f"user-facing honesty warning and the LLM forbidden-keyword list; "
        f"got {cleaned}"
    )


@pytest.mark.parametrize("token", PRODUCTION_SIGNAL)
def test_clean_gap_keywords_keeps_real_skill_keywords(token: str) -> None:
    """The noise filter must not eat real, checkable skill terms."""
    assert token in clean_gap_keywords([token]), (
        f"{token!r} is a real skill keyword and was wrongly dropped"
    )


def test_clean_gap_keywords_strips_every_negative_contraction_prefix() -> None:
    """``don't``/``doesn't``/``isn't``/… all tokenize to an ``n``-final prefix.

    Pinning the whole family (not just the one token observed in production)
    so the next posting that says "we won't" or "you shouldn't" cannot
    reintroduce the same class of noise.
    """
    fragments = [
        "don", "doesn", "didn", "isn", "aren", "wasn", "weren", "won",
        "couldn", "shouldn", "wouldn", "hasn", "haven", "hadn", "mustn",
        "needn", "ain",
    ]
    cleaned = clean_gap_keywords(fragments + ["kubernetes"])
    assert cleaned == ["kubernetes"], (
        f"contraction prefixes leaked through clean_gap_keywords: {cleaned}"
    )


def test_clean_gap_keywords_preserves_order_and_dedups() -> None:
    """Behaviour the loop already relies on — order-preserving, deduped."""
    assert clean_gap_keywords(
        ["Kafka", "other", "kubernetes", "kafka", "more", "Terraform"]
    ) == ["kafka", "kubernetes", "terraform"]


def test_directive_forbidden_list_carries_no_noise() -> None:
    """End of the chain: the LLM directive must not be told to avoid "other".

    ``TailoringLoop._build_directive`` splices the unsupported half of the
    cleaned gap keywords into the prompt's FORBIDDEN list. This asserts the
    cleaning actually reaches that text, rather than only the standalone
    helper being fixed.
    """
    from app.services.tailoring_loop import TailoringLoop

    loop = TailoringLoop(service=object(), ats_engine=object())
    supported, unsupported = [], clean_gap_keywords(
        ["don", "other", "more", "underwriting"]
    )
    directive = loop._build_directive(60.0, supported, unsupported)
    for noise in ("don", "other", "more"):
        assert f" {noise}," not in directive and f" {noise}." not in directive, (
            f"{noise!r} reached the LLM forbidden-keyword list: {directive}"
        )
    assert "underwriting" in directive, directive
