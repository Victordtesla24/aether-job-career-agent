"""GAP-E2 (HIGH) — before/after ATS conversion metrics on tailor runs.

The tailor agent must re-score the resume against the target job before and
after tailoring (deterministic ATSEngine, no extra LLM cost) and surface an
estimated interview-conversion lift derived from that delta and a
configurable population baseline rate.
"""
from __future__ import annotations

import os

from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume

from app.agents.tailor_agent import _compute_conversion_metrics


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


class TestConversionMetricsUnit:
    def test_baseline_and_tailored_scores_are_numeric_with_formatted_lift(self) -> None:
        original = "Led delivery for the Kookaburras squad. Reduced costs by 15%."
        original_bullets = [
            {"text": "Led delivery for the Kookaburras squad.", "evidenceRef": "bullet-0"},
            {"text": "Reduced costs by 15%.", "evidenceRef": "bullet-1"},
        ]
        tailored_bullets = [
            {"text": "Led delivery for the Kookaburras squad using Python.",
             "evidenceRef": "bullet-0"},
            {"text": "Reduced costs by 15% through process automation.",
             "evidenceRef": "bullet-1"},
        ]
        jd = "Looking for a Python engineer with delivery experience."
        metrics = _compute_conversion_metrics(original, original_bullets, tailored_bullets, jd)

        assert isinstance(metrics["baselineATSScore"], (int, float))
        assert isinstance(metrics["tailoredATSScore"], (int, float))
        assert 0.0 <= metrics["baselineATSScore"] <= 100.0
        assert 0.0 <= metrics["tailoredATSScore"] <= 100.0
        assert isinstance(metrics["estimatedConversionLift"], str)
        assert metrics["estimatedConversionLift"].endswith("%")
        assert metrics["estimatedConversionLift"][0] in "+-"
        assert metrics["methodology"] == (
            "Like-for-like ATS delta (shared context) × population baseline (2.5%)"
        )
        assert metrics["confidence"] == "model-estimated"

    def test_baseline_zero_does_not_divide_by_zero(self) -> None:
        # Empty original resume + a job that states a years requirement the
        # (empty) resume can never meet drives keyword/semantic/experience
        # components all to zero, so baseline == 0.0 exactly.
        original = ""
        jd = "Requires 5+ years of Python experience building distributed systems."
        original_bullets: list[dict[str, str]] = []
        tailored_bullets = [
            {"text": "Built distributed systems in Python for 6 years.",
             "evidenceRef": "bullet-0"}
        ]
        metrics = _compute_conversion_metrics(original, original_bullets, tailored_bullets, jd)

        assert metrics["baselineATSScore"] == 0.0
        # Must not raise ZeroDivisionError and must still produce a formatted
        # percentage string.
        assert isinstance(metrics["estimatedConversionLift"], str)
        assert metrics["estimatedConversionLift"].endswith("%")

    def test_env_override_of_baseline_rate_is_respected(self) -> None:
        original = "Led delivery for the Kookaburras squad."
        original_bullets = [
            {"text": "Led delivery for the Kookaburras squad.", "evidenceRef": "bullet-0"}
        ]
        tailored_bullets = [
            {"text": "Led delivery for the Kookaburras squad using Python and AWS.",
             "evidenceRef": "bullet-0"}
        ]
        jd = "Looking for a Python and AWS engineer with delivery experience."

        old = os.environ.get("AETHER_CONVERSION_BASELINE_RATE")
        try:
            os.environ["AETHER_CONVERSION_BASELINE_RATE"] = "0.025"
            low_rate = _compute_conversion_metrics(
                original, original_bullets, tailored_bullets, jd
            )
            os.environ["AETHER_CONVERSION_BASELINE_RATE"] = "0.25"
            high_rate = _compute_conversion_metrics(
                original, original_bullets, tailored_bullets, jd
            )
        finally:
            if old is None:
                os.environ.pop("AETHER_CONVERSION_BASELINE_RATE", None)
            else:
                os.environ["AETHER_CONVERSION_BASELINE_RATE"] = old

        # Same before/after scores, 10x the population rate → 10x the lift
        # magnitude (both nonzero since tailored > baseline in this fixture).
        low_lift = float(low_rate["estimatedConversionLift"].rstrip("%"))
        high_lift = float(high_rate["estimatedConversionLift"].rstrip("%"))
        assert low_rate["baselineATSScore"] == high_rate["baselineATSScore"]
        assert low_rate["tailoredATSScore"] == high_rate["tailoredATSScore"]
        assert low_lift != 0.0
        assert round(high_lift, 4) == round(low_lift * 10, 4)


class TestConversionMetricsApi:
    def test_tailor_run_response_includes_conversion_metrics(self, client, auth_headers) -> None:
        # The tailor run is an OUTBOUND generation path: it now (correctly)
        # REFUSES a user with no résumé of their own (resume_grounding;
        # NF-final-B-005) rather than tailoring the bundled operator PDF. Seed
        # the fixture user a real own résumé so the run proceeds — the replay
        # generation fixtures reference the bundled-résumé vocabulary, so
        # FIXTURE_LLM_RESUME_TEXT (non-operator identity + that vocabulary) is
        # the correct seed for an end-to-end replay generation.
        seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
        job = _seed_job(client, auth_headers)
        resp = client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert "conversionMetrics" in body
        metrics = body["conversionMetrics"]
        assert isinstance(metrics["baselineATSScore"], (int, float))
        assert isinstance(metrics["tailoredATSScore"], (int, float))
        assert isinstance(metrics["estimatedConversionLift"], str)
        assert metrics["estimatedConversionLift"].endswith("%")
        assert metrics["methodology"]
        assert metrics["confidence"] == "model-estimated"
