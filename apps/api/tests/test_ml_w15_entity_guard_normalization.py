"""ML-W15 — the entity FabricationGuard rejects NUMBER-BEARING COMPOUNDS and
formatting variants of a résumé's own numbers, blocking live runs outright.

Production defect (found live during W-11 verification,
``uat/reports/evidence/models-live/ML-W11/live-proof-run1-prerefinement.json``
and ``live-proof.json``): the entity guard (``app/services/fabrication_guard.py``,
``find_unsupported_entities``) intermittently rejected:

  * ``['6-person']`` and ``['6-engineer']`` where the résumé states "Led 6
    engineers" — a faithful hyphenated-compound restatement of the SAME
    resume-evidenced number.
  * ``['200ms.']`` where the résumé states "200 ms" — a formatting variant
    (glued digits+unit vs. space-separated) of the same measurement.
  * ``['AEST']`` — a timezone abbreviation used for interview-scheduling
    logistics, not a claim about the candidate's experience.

Each of these blocked a live cover-letter run outright (``FabricationError``)
even though nothing was fabricated.

The fix is precision via NORMALIZATION, not permissiveness:

  1. A NUMBER+UNIT compound (glued/hyphenated/spaced — "200ms.", "200-ms",
     "200 ms") is canonicalized on both sides before comparison.
  2. A NUMBER+WORD hyphenated compound ("6-person", "6-engineer") is
     decomposed; the NUMBER must be resume-evidenced, and the WORD must
     either stem-match a resume word (engineer ~ engineers) or be a narrow
     generic team-size descriptor (person, team, member, ...). The compound
     is verified ONLY when both hold.
  3. A narrow, documented timezone-abbreviation allowlist (AEST, UTC, ...)
     is exempted as scheduling context, not an experience claim.

The number-integrity bar is explicitly pinned to still hold: a letter that
INFLATES or otherwise changes a résumé number (6 -> 8 engineers, 200ms ->
50ms) must still be rejected — this suite proves the fix did not become a
loophole.

Run under the shared test DB lock (no DB is actually touched by this file,
but the project-wide convention is to always run pytest this way)::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ml_w15_entity_guard_normalization.py -q
"""
from __future__ import annotations

import pytest

from app.services.fabrication_guard import FabricationGuard, find_unsupported_entities

# ---------------------------------------------------------------------------
# Shared evidence corpus — mirrors the real résumé text from the live proof
# (uat/reports/evidence/models-live/ML-W11/live-proof.json): "Led 6 engineers
# on a payments platform" + "kept P95 latency under 200 ms".
# ---------------------------------------------------------------------------

_EVIDENCE = (
    "Jordan Rivera. Senior Software Engineer. Led 6 engineers on a payments "
    "platform in Python and PostgreSQL, kept P95 latency under 200 ms while "
    "improving throughput 40 percent. Migrated services to Kubernetes and "
    "Docker. Owned sprint cadence and capacity management for delivery "
    "squads. Acme"
)


# ===========================================================================
# (a) FAIL-BEFORE — the exact live-observed rejections must now PASS
# ===========================================================================


class TestPreviouslyRejectedFormattingVariantsNowPass:
    def test_hyphenated_person_compound_of_resume_evidenced_number(self) -> None:
        """'6-person' restates the resume's '6 engineers' as a team-size
        descriptor — not a new, unevidenced claim."""
        flagged = find_unsupported_entities(
            "I led a 6-person team delivering the payments platform.", _EVIDENCE
        )
        assert "6-person" not in flagged, flagged

    def test_hyphenated_engineer_compound_of_resume_evidenced_number(self) -> None:
        """'6-engineer' restates the resume's '6 engineers' with the same
        role noun (stem-matched, singular vs. plural)."""
        flagged = find_unsupported_entities(
            "I led a 6-engineer team on a payments platform.", _EVIDENCE
        )
        assert "6-engineer" not in flagged, flagged

    def test_glued_measurement_with_trailing_punctuation(self) -> None:
        """'200ms.' (glued digits+unit, trailing sentence period) is the same
        claim as the résumé's '200 ms'."""
        flagged = find_unsupported_entities(
            "I kept P95 latency under 200ms.", _EVIDENCE
        )
        assert "200ms." not in flagged, flagged
        assert not any(f.rstrip(".").lower() == "200ms" for f in flagged), flagged

    def test_hyphenated_measurement_variant(self) -> None:
        """'200-ms' (hyphenated) is the same claim as the résumé's '200 ms'."""
        flagged = find_unsupported_entities(
            "I kept P95 latency under 200-ms.", _EVIDENCE
        )
        assert not any(f.rstrip(".").lower() == "200-ms" for f in flagged), flagged

    def test_timezone_abbreviation_is_not_a_claim(self) -> None:
        """'AEST' is interview-scheduling logistics, not an entity claim."""
        flagged = find_unsupported_entities(
            "I'm available Thursday afternoon AEST this week.", _EVIDENCE
        )
        assert "AEST" not in flagged, flagged

    def test_full_letter_body_shape_from_live_proof_produces_no_entity_flags(
        self,
    ) -> None:
        """The realistic multi-sentence draft shape observed live: measurement
        + hyphenated team-size compound + timezone, all restating the same
        résumé evidence."""
        model_text = (
            "I built dashboards that kept P95 latency under 200ms while "
            "improving throughput. I led a 6-person team on a payments "
            "platform, owning sprint cadence and capacity management. "
            "I'm available Thursday or Friday afternoon AEST this week."
        )
        assert find_unsupported_entities(model_text, _EVIDENCE) == []


# ===========================================================================
# (b) NUMBER-INTEGRITY BAR — inflation/deflation must still be REJECTED
# ===========================================================================


class TestNumberIntegrityStillEnforced:
    def test_inflated_team_size_compound_is_still_rejected(self) -> None:
        """The résumé says 6 engineers; a letter claiming an 8-person team is
        a fabricated (inflated) number and must still be rejected."""
        flagged = find_unsupported_entities(
            "I led an 8-person team on a payments platform.", _EVIDENCE
        )
        assert "8-person" in flagged, flagged

    def test_inflated_role_noun_compound_is_still_rejected(self) -> None:
        """Likewise for the role-noun form: '8-engineer' is not evidenced."""
        flagged = find_unsupported_entities(
            "I led an 8-engineer team on a payments platform.", _EVIDENCE
        )
        assert "8-engineer" in flagged, flagged

    def test_deflated_latency_measurement_is_still_rejected(self) -> None:
        """The résumé says 200 ms; a letter claiming 50ms is a fabricated
        (deflated) number and must still be rejected."""
        flagged = find_unsupported_entities(
            "I kept P95 latency under 50ms.", _EVIDENCE
        )
        assert any(f.rstrip(".").lower() == "50ms" for f in flagged), flagged

    def test_inflated_latency_measurement_hyphenated_is_still_rejected(self) -> None:
        flagged = find_unsupported_entities(
            "I kept P95 latency under 500-ms.", _EVIDENCE
        )
        assert any(f.rstrip(".").lower() == "500-ms" for f in flagged), flagged

    def test_unevidenced_noun_paired_with_a_real_number_is_still_rejected(self) -> None:
        """A hyphenated compound pairing a genuinely resume-evidenced number
        with a completely unrelated, unevidenced noun must still be rejected
        — the fix must not become 'any number unlocks any noun'."""
        flagged = find_unsupported_entities(
            "I hold 6-patent recognition for this work.", _EVIDENCE
        )
        assert "6-patent" in flagged, flagged


# ===========================================================================
# (c) Regression pins — ordinary entity/metric detection is unchanged
# ===========================================================================


class TestExistingGuardBehaviourUnchanged:
    def test_unsupported_capitalized_entity_and_metric_still_flagged(self) -> None:
        guard = FabricationGuard()
        corpus = "delivery leadership python program management"
        flagged = guard.check("I worked at Google and increased revenue 300%", corpus)
        assert "Google" in flagged
        assert any("300" in f for f in flagged)

    def test_supported_text_still_passes(self) -> None:
        guard = FabricationGuard()
        corpus = "delivery leadership Python program management at Canva"
        assert guard.check("My delivery leadership at Canva used Python", corpus) == []

    def test_bare_number_with_no_word_part_still_flagged_when_unevidenced(self) -> None:
        """A bare fabricated metric (no unit/word suffix) is untouched by the
        new decomposition path — it simply has nothing to decompose."""
        flagged = find_unsupported_entities(
            "I increased throughput by 99.99%.", "delivery leadership"
        )
        assert any("99.99" in f for f in flagged), flagged


@pytest.mark.parametrize(
    "sentence,evidence",
    [
        ("A 3-year veteran of the industry.", "Led 6 engineers. 3 years experience."),
    ],
)
def test_evidenced_hyphenated_compound_with_directly_matching_noun_passes(
    sentence: str, evidence: str
) -> None:
    """Sanity check: when BOTH the number and the exact (stem-matched) noun
    are resume-evidenced, the hyphenated compound passes."""
    assert find_unsupported_entities(sentence, evidence) == []
