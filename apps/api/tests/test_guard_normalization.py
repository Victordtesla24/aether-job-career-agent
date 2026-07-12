"""D-0015 — evidence normalization for the tailoring fabrication guard.

The pre-fix guard required every raw token of a rewritten bullet to appear
verbatim in the resume text, so unicode punctuation variants ("end‑to‑end"
with U+2011), inflectional variants ("delivered" vs "delivery") and number
reformatting ("≈92%" vs "92%") were all treated as fabrications — the tailor
endpoint returned changes:0 for every run. These tests lock in the normalized
semantics: reworded-but-evidence-traced bullets are ACCEPTED, genuinely new
skills/tools/metrics are still REJECTED.
"""
from __future__ import annotations

from app.services.resume_tailor import (
    ResumeTailorService,
    _evidence_index,
    unsupported_tokens,
)

RESUME = (
    "Senior Program Manager\n"
    "• Led end-to-end delivery for the Kookaburras team across 5 squads\n"
    "• Reduced processing time by 92% (from 3 hours to 15 minutes) using Python\n"
    "• Managed a $2.5M budget and 10,000+ monthly transactions in Postgres\n"
)


def _novel(text: str) -> list[str]:
    stems, numbers = _evidence_index(RESUME)
    return unsupported_tokens(text, stems, numbers)


class TestAcceptsNormalizedVariants:
    def test_unicode_hyphen_and_dash_variants(self):
        # U+2011 non-breaking hyphen + U+2013 en dash trace to "end-to-end".
        assert _novel("Led end\u2011to\u2011end delivery \u2013 Kookaburras team") == []

    def test_approx_sign_and_percent_reformatting(self):
        assert _novel("Reduced processing time \u224892%") == []
        # 'cut' is generic professional vocabulary \u2014 style, not a fabricated claim.
        assert _novel("Cut processing time by 92 percent") == []

    def test_generic_professional_rewording_accepted(self):
        """Ordinary rewording must not be rejected (observed live: 8/8 bullets
        rejected over words like 'improvement'/'documentation' -> 0 changes)."""
        assert _novel("Streamlined documentation, identifying improvement opportunities") == []

    def test_number_format_equivalence(self):
        assert _novel("~3 hours reduced to 15 minutes") == []
        assert _novel("managed 10,000+ transactions monthly") == []

    def test_inflectional_variants(self):
        # delivery→delivered, managed→managing, reduced→reducing all trace back.
        assert _novel("Delivered while managing the budget") == []
        assert _novel("Reducing processing times using Python") == []

    def test_case_folding_and_stopwords(self):
        assert _novel("LED THE TEAM ACROSS SQUADS WITH PYTHON") == []


class TestStillRejectsFabrications:
    def test_new_skill_is_rejected(self):
        assert "kubernetes" in _novel("Deployed services on Kubernetes")

    def test_new_tool_is_rejected(self):
        assert "terraform" in _novel("Automated infra with Terraform and Python")

    def test_new_metric_is_rejected(self):
        assert "35" in _novel("Improved throughput by 35%")

    def test_new_employer_is_rejected(self):
        assert "google" in _novel("Led delivery at Google")


class TestValidateIntegration:
    def test_reworded_bullet_accepted_and_counted_as_change(self):
        svc = ResumeTailorService()
        raw = {
            "bullets": [
                {
                    "text": "Led end\u2011to\u2011end delivery for the Kookaburras "
                    "team, reducing processing time \u224892%",
                    "evidenceRef": "bullet-0",
                }
            ]
        }
        result = svc._validate(
            raw,
            ["Led end-to-end delivery for the Kookaburras team across 5 squads"],
            RESUME,
        )
        assert result.changes == 1
        assert result.rejected == []
        assert "Kookaburras" in result.bullets[0]["text"]

    def test_fabricated_bullet_reverts_to_original(self):
        svc = ResumeTailorService()
        original = "Led end-to-end delivery for the Kookaburras team across 5 squads"
        raw = {
            "bullets": [
                {
                    "text": "Architected Kubernetes clusters on GCP",
                    "evidenceRef": "bullet-0",
                }
            ]
        }
        result = svc._validate(raw, [original], RESUME)
        assert result.changes == 0
        assert result.rejected == ["Architected Kubernetes clusters on GCP"]
        assert result.bullets[0]["text"] == original
