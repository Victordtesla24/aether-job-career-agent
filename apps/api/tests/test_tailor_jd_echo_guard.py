"""GAP-P4-045 — tailoring must ground rewrites in the user's evidence, not the JD.

The evidence-normalization guard (D-0015) only polices proper nouns and
numbers, so it was blind to lowercase *phrase-level* lifting: rewrites echoed
distinctive job-description phrases ("first-class software", "high-traffic
environment") as the candidate's own experience. The JD-echo guard rejects any
rewrite that introduces a content-word n-gram present in the JD but absent from
the candidate's real resume, and keeps the original evidence-grounded bullet.
"""
from __future__ import annotations

from app.services.resume_tailor import (
    _JD_ECHO_NGRAM,
    ResumeTailorService,
    _content_stems,
    _ngram_set,
    jd_echoed_phrases,
    jd_ngram_index,
)

_RESUME = "Led delivery for the Kookaburras squad across eight squads. Reduced costs by 15%."
_JD = "We deliver first-class software in high-traffic environments for millions of customers."


def _evidence_ngrams(text: str) -> set[tuple[str, ...]]:
    return _ngram_set(_content_stems(text), _JD_ECHO_NGRAM)


def test_jd_verbatim_phrase_is_rejected() -> None:
    svc = ResumeTailorService()
    originals = [
        {"text": "Led delivery for the Kookaburras squad across eight squads.",
         "evidenceRef": "bullet-0"},
    ]
    raw = {
        "bullets": [
            {"text": "Led delivery driving first-class software outcomes in a "
                     "high-traffic environment.", "evidenceRef": "bullet-0"},
        ],
        "evidenceRefs": ["bullet-0"],
    }
    result = svc._validate(raw, originals, _RESUME, _JD)

    # The rewrite lifts "first-class software" / "high-traffic environment" from
    # the JD, phrases the candidate never wrote → original kept, no change.
    assert result.bullets[0]["text"] == originals[0]["text"]
    assert result.changes == 0
    assert result.rejected


def test_evidence_grounded_rewrite_is_accepted() -> None:
    svc = ResumeTailorService()
    originals = [{"text": "Reduced costs by 15%.", "evidenceRef": "bullet-1"}]
    raw = {
        "bullets": [
            {"text": "Reduced costs by 15% across eight squads.",
             "evidenceRef": "bullet-1"},
        ],
        "evidenceRefs": ["bullet-1"],
    }
    result = svc._validate(raw, originals, _RESUME, _JD)

    # Every word is drawn from the candidate's own resume — the guard leaves it.
    assert result.bullets[0]["text"] == "Reduced costs by 15% across eight squads."
    assert result.changes == 1
    assert not result.rejected


def test_jd_echoed_phrases_flags_lifted_ngram() -> None:
    jd_ngrams = jd_ngram_index("Deliver first-class software in high-traffic environments.")
    evidence = _evidence_ngrams("Managed the delivery of core banking platforms.")
    lifted = jd_echoed_phrases(
        "Drove first-class software in a high-traffic environment.",
        jd_ngrams,
        evidence,
    )
    assert lifted, "expected the lifted JD phrase to be detected"


def test_jd_echoed_phrases_ignores_evidence_grounded_phrase() -> None:
    # A phrase the candidate actually wrote is never flagged, even when the JD
    # repeats it — grounding beats overlap.
    evidence_text = "Built a high-traffic payments platform handling millions of transactions."
    jd_ngrams = jd_ngram_index("We run a high-traffic payments platform.")
    lifted = jd_echoed_phrases(
        "Scaled the high-traffic payments platform for continued growth.",
        jd_ngrams,
        _evidence_ngrams(evidence_text),
    )
    assert not lifted
