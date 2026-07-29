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

WAVE-3.5 ADVERSARIAL RE-FIX (uat/reports/evidence/models-live/
wave35-sonnet-review-verdict.json, MF-3/NTH-R11/NTH-R12): the reviewer's own
attack probe (``wave35-review-w15-attack-probe.py``) proved the first version
of this fix checked the NUMBER and the WORD as two INDEPENDENT membership
tests over the whole corpus, so ANY number anywhere in the résumé unlocked
ANY evidenced noun — '40-person' was ACCEPTED against a résumé whose only
"40" was "improving throughput 40 percent" (truth: 6 engineers). The
``TestAdversarialWave35Probes`` class below pins every probe from that
attack file permanently. The fix: every verification path now requires the
number and the word to have occurred TOGETHER in the evidence (a pair, not
independent membership) — see ``_evidence_number_word_index`` /
``_verified_number_word_compound`` in ``fabrication_guard.py``. The timezone
allowlist is now context-gated on a weekday/time-of-day word in the SAME
sentence (NTH-R11: "EST Holdings" / "at CET" no longer slip through), and the
plural stemmer got an orthographic guard so it no longer collapses unrelated
words like "cares"->"car" or "bus"->"bu" (NTH-R12).

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


# ===========================================================================
# (d) WAVE-3.5 ADVERSARIAL RE-FIX — MF-3 / NTH-R11 / NTH-R12 permanent pins
#
# Every sentence below is taken verbatim from the reviewer's own attack probe
# (uat/reports/evidence/models-live/wave35-review-w15-attack-probe.py) and
# ACCEPTED (slipped through) against the pre-re-fix guard. Each must now be
# REJECTED (flagged), except the explicit "must still pass" controls.
# ===========================================================================

#: The probe's own fixture, verbatim — proves 6 engineers / 40 percent are
#: BOTH evidenced, but never together.
_PROBE_EVIDENCE = _EVIDENCE

#: BOTH parts evidenced, but never together (truth: 2 patents, not 6).
_PROBE_EVIDENCE_PATENT = "Led 6 engineers on a payments platform. Filed 2 patents."


class TestAdversarialWave35NumberNounAssociation:
    """MF-3: the NUMBER and the WORD must have occurred TOGETHER in the
    evidence — an evidenced number reused from an unrelated sentence must
    not unlock an evidenced (or generic size) noun."""

    def test_inflated_team_size_built_from_an_unrelated_evidenced_percentage(
        self,
    ) -> None:
        """'40-person' rides in on 'improving throughput 40 percent' — the
        résumé's real team size is 6, not 40."""
        flagged = find_unsupported_entities(
            "I led a 40-person team on a payments platform.", _PROBE_EVIDENCE
        )
        assert "40-person" in flagged, flagged

    def test_inflated_role_noun_built_from_an_unrelated_evidenced_percentage(
        self,
    ) -> None:
        """Same attack via the stem-matched role-noun path (bypasses
        _SIZE_NOUNS entirely, so it must be caught by the pairing check on
        the specific-noun branch)."""
        flagged = find_unsupported_entities(
            "I led a 40-engineer team on a payments platform.", _PROBE_EVIDENCE
        )
        assert "40-engineer" in flagged, flagged

    def test_control_8_person_absent_entirely_still_rejected(self) -> None:
        flagged = find_unsupported_entities(
            "I led an 8-person team on a payments platform.", _PROBE_EVIDENCE
        )
        assert "8-person" in flagged, flagged

    def test_6_patent_when_both_parts_evidenced_but_never_together(self) -> None:
        """Résumé proves '6 engineers' AND '2 patents' — but never '6
        patents'. Truth is 2 patents; '6-patent' must still be rejected."""
        flagged = find_unsupported_entities(
            "I hold 6-patent recognition for this work.", _PROBE_EVIDENCE_PATENT
        )
        assert "6-patent" in flagged, flagged

    def test_6_person_still_passes_when_genuinely_paired(self) -> None:
        """Control for the fix itself: '6-person' must still PASS against
        the résumé's 'Led 6 engineers' — the pairing requirement must not
        become so strict that the original defect regresses."""
        flagged = find_unsupported_entities(
            "I led a 6-person team on a payments platform.", _PROBE_EVIDENCE
        )
        assert "6-person" not in flagged, flagged


class TestAdversarialWave35TimezoneContextGating:
    """NTH-R11: the timezone allowlist must be gated on scheduling context
    (a weekday / time-of-day word in the SAME sentence), not a blanket
    exemption that lets a real employer name slip through."""

    def test_company_named_cet_in_an_employment_claim_is_rejected(self) -> None:
        flagged = find_unsupported_entities(
            "I spent four years at CET building payments systems.", _PROBE_EVIDENCE
        )
        assert "CET" in flagged, flagged

    def test_company_named_est_holdings_is_rejected(self) -> None:
        flagged = find_unsupported_entities(
            "I was a principal engineer at EST Holdings.", _PROBE_EVIDENCE
        )
        assert "EST" in flagged, flagged

    def test_control_ordinary_unevidenced_employer_still_rejected(self) -> None:
        flagged = find_unsupported_entities(
            "I spent four years at Netflix.", _PROBE_EVIDENCE
        )
        assert any("netflix" in f.lower() for f in flagged), flagged

    def test_aest_in_genuine_scheduling_context_still_passes(self) -> None:
        """The original ML-W11 defect must not regress: a timezone
        abbreviation alongside a weekday/time-of-day word is still exempt."""
        flagged = find_unsupported_entities(
            "I'm available Thursday afternoon AEST this week.", _PROBE_EVIDENCE
        )
        assert "AEST" not in flagged, flagged


class TestAdversarialWave35StemLooseness:
    """NTH-R12: the plural stemmer must not collapse unrelated words —
    every candidate below is a real widening of the accept surface under
    the old unconditional strip-trailing-s stemmer."""

    @pytest.mark.parametrize(
        "sentence,evidence,target",
        [
            (
                "I shipped a 6-cares programme.",
                "Led 6 engineers. Owned the car fleet.",
                "6-cares",
            ),
            (
                "I ran 6-processes end to end.",
                "Led 6 engineers. Owned processes.",
                "6-processes",
            ),
            (
                "I delivered 6-series of launches.",
                "Led 6 engineers. Owned a series.",
                "6-series",
            ),
            (
                "I owned 6-bu units.",
                "Led 6 engineers. Managed the bus fleet.",
                "6-bu",
            ),
        ],
    )
    def test_stem_looseness_probe_is_rejected(
        self, sentence: str, evidence: str, target: str
    ) -> None:
        flagged = find_unsupported_entities(sentence, evidence)
        assert target in flagged, flagged

    def test_stem_still_folds_genuine_plural_both_directions(self) -> None:
        """NTH-R12 must not overcorrect: 'engineer'~'engineers' (the fix's
        own reason for existing) still matches in both directions."""
        assert (
            find_unsupported_entities(
                "I led a 6-engineer team.", "Led 6 engineers on a payments platform."
            )
            == []
        )
        assert (
            find_unsupported_entities(
                "I led 6-engineers on the platform.", "Led 6 engineer on a payments platform."
            )
            == []
        )


class TestAdversarialWave35UnitHandlingUnaffected:
    """The reviewer confirmed the NUMBER+UNIT branch was already correct —
    pinned here so the MF-3 pairing fix does not regress it."""

    def test_cross_unit_equivalence_not_inferred(self) -> None:
        flagged = find_unsupported_entities(
            "I kept P95 latency under 0.2s.", _PROBE_EVIDENCE
        )
        assert any(f.rstrip(".").lower() == "0.2s" for f in flagged), flagged

    def test_evidenced_number_with_wrong_unit_still_rejected(self) -> None:
        """'40' is evidenced only as 'improving throughput 40 percent' — an
        unrelated unit ('40ms') must not be verified by it."""
        flagged = find_unsupported_entities(
            "I kept P95 latency under 40ms.", _PROBE_EVIDENCE
        )
        assert any(f.rstrip(".").lower() == "40ms" for f in flagged), flagged
