"""W-TAILOR-CONVERGE item 4 — the cover letter needs a REAL, persisted quality
score, scored by the same honest rules as the résumé's ATS loop.

MEASURED STATE before this change: ``CoverLetterAgent.run`` had NO scoring of
any kind. It drafted, ran the fabrication/claim/structural guards, and stored
the letter. Nothing recorded how good the letter was, nothing compared a first
draft to a final one, and ``Application`` had no column in which such a number
could live — so the Cover Letter Studio had no before/after to show.

The score here is DETERMINISTIC and derived only from the finished text:
  * JD alignment — coverage of the job-description keywords the candidate's
    own evidence supports (the unsupported ones are excluded from the
    denominator, exactly as ``tailoring_loop.split_gap_keywords`` does for the
    résumé, because no truthful letter can ever contain them);
  * grounding — the existing ``grounding_confidence`` evidence measurement;
  * structure — the §10.2 letter-format contract, already enforced by the run.

No LLM is involved in scoring, so the number costs nothing and cannot drift.
"""
from __future__ import annotations

_JD = (
    "Senior Backend Engineer at Acme. You will own our Kafka pipelines and "
    "Kubernetes platform, and you will work with Postgres at scale. "
    "Experience with underwriting and reinsurance is highly regarded."
)
_EVIDENCE = (
    "JANE DOE. Backend engineer. Built Kafka ingestion pipelines and ran a "
    "Postgres fleet for the billing team. Comfortable with Kubernetes."
)
_LETTER_STRONG = (
    "I am applying for the Senior Backend Engineer role at Acme.\n\n"
    "I built Kafka ingestion pipelines and ran a Postgres fleet for the "
    "billing team, and I am comfortable operating Kubernetes.\n\n"
    "I would welcome an interview to talk this through."
)
_LETTER_WEAK = (
    "I am applying for the Senior Backend Engineer role at Acme.\n\n"
    "I have built things for the billing team.\n\n"
    "I would welcome an interview to talk this through."
)


def test_quality_score_is_a_real_measurement_of_the_letter() -> None:
    from app.services.cover_letter_quality import score_cover_letter

    strong = score_cover_letter(_LETTER_STRONG, _JD, _EVIDENCE)
    weak = score_cover_letter(_LETTER_WEAK, _JD, _EVIDENCE)

    assert 0.0 <= weak.overall <= 100.0
    assert 0.0 <= strong.overall <= 100.0
    assert strong.overall > weak.overall, (strong, weak)
    assert strong.jd_alignment > weak.jd_alignment, (strong, weak)


def test_unsupported_jd_keywords_are_excluded_from_the_denominator() -> None:
    """"underwriting"/"reinsurance" appear in the posting but nowhere in the
    candidate's evidence. A truthful letter can NEVER contain them, so scoring
    the letter against them would permanently cap an honest letter and push
    every improvement pass toward fabrication. They must be reported as
    unreachable instead."""
    from app.services.cover_letter_quality import score_cover_letter

    result = score_cover_letter(_LETTER_STRONG, _JD, _EVIDENCE)
    assert "underwriting" in result.unreachable_keywords, result
    assert "reinsurance" in result.unreachable_keywords, result
    assert "kafka" not in result.unreachable_keywords, result
    # Every supported keyword IS present in the strong letter, so alignment is
    # a genuine 100 — not a clamp, and not inflated by dropping hard words:
    # the missing list is empty for exactly that reason.
    assert result.missing_keywords == [], result
    assert result.jd_alignment == 100.0, result


def test_structure_component_reflects_the_letter_format_contract() -> None:
    from app.services.cover_letter_quality import score_cover_letter

    broken = "I am applying.\n\nI built Kafka pipelines."  # no CTA, 2 paragraphs
    good = score_cover_letter(_LETTER_STRONG, _JD, _EVIDENCE)
    bad = score_cover_letter(broken, _JD, _EVIDENCE)
    assert good.structure == 100.0, good
    assert bad.structure < 100.0, bad


def test_score_never_exceeds_one_hundred_or_reports_a_false_pass() -> None:
    from app.services.cover_letter_quality import DEFAULT_TARGET_SCORE, score_cover_letter

    weak = score_cover_letter(_LETTER_WEAK, _JD, _EVIDENCE)
    assert weak.overall < DEFAULT_TARGET_SCORE or weak.reached_target
    # reached_target must be a strict >= comparison against the real score —
    # never a rounded-up or clamped claim.
    assert weak.reached_target == (weak.overall >= DEFAULT_TARGET_SCORE)


def test_empty_letter_scores_zero_not_a_neutral_placeholder() -> None:
    from app.services.cover_letter_quality import score_cover_letter

    result = score_cover_letter("", _JD, _EVIDENCE)
    assert result.overall == 0.0, result
    assert result.grounding == 0.0, result
