"""GAP-P6-AUTH-002 / GAP-P6-TAIL-002 — production authenticity.

Two live-production defects (uat/reports/evidence/phase6/qa-prod-craft.json):

AUTH-002 (CRITICAL, §0.5/§8 zero-tolerance authenticity): in ``auto`` mode the
LLM client silently served a RECORDED TEST FIXTURE as if it were a real, live
generation whenever the live call failed / hit the wall-clock budget. A paying
user hitting the timeout received a stale, generic fixture as their "tailored"
résumé / cover letter, with ZERO signal in the response. Fixtures may be served
ONLY in explicit ``replay`` mode (the test harness); an ``auto``/``live``
failure must raise an honest error so the run is recorded failed and the
reserved quota is refunded — never faked as a 200-with-canned-content.

TAIL-002 (HIGH, tailoring authenticity):
 1. cross-context keyword bleed — a keyword proven only by evidence about ONE
    employer/program (e.g. the Payday-Super *payments* story) was attributed to
    a DIFFERENT employer's bullet (Telstra) that no evidence supports. The guard
    must be CONTEXT-SCOPED: reject cross-context attribution even when the token
    exists somewhere in the candidate's overall evidence.
 2. the persisted résumé ``raw_text`` was never regenerated from the tailored
    bullets, so an independent ``GET /resumes/{id}/ats`` reverted to the stale
    BASELINE score. Regenerate it from the tailored sections.
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest

from app.services.llm_client import LLMClient, LLMUnavailableError, get_budget_seconds


# ===========================================================================
# GAP-P6-AUTH-002 — no fixture fallback on auto/live FAILURE
# ===========================================================================
class TestAutoModeNeverServesFixtureOnFailure:
    """(a) An ``auto``-mode live failure raises an honest error and does NOT
    return the recorded fixture content — even when a fixture is present."""

    def _fixture(self, tmp_path) -> str:
        f = tmp_path / "tailor" / "default.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"content": "STALE FIXTURE CONTENT"}))
        return "STALE FIXTURE CONTENT"

    def test_live_failure_raises_and_does_not_return_fixture(self, tmp_path, monkeypatch):
        canned = self._fixture(tmp_path)
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient,
            "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 503")),
        )
        with pytest.raises(LLMUnavailableError):
            llm.complete("tailor", "sys", "usr")
        # The fixture must NEVER be silently served as a live result.
        assert canned == "STALE FIXTURE CONTENT"  # sanity — the fixture exists

    def test_budget_exhausted_raises_even_with_fixture_present(self, tmp_path, monkeypatch):
        self._fixture(tmp_path)
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        llm._deadline = time.monotonic() - 1  # budget already spent

        def _never(self, *a, **k):
            raise AssertionError("live call attempted after budget exhausted")

        monkeypatch.setattr(LLMClient, "_call_live", _never)
        with pytest.raises(LLMUnavailableError):
            llm.complete("tailor", "sys", "usr")

    def test_malformed_live_json_raises_even_with_fixture_present(self, tmp_path, monkeypatch):
        f = tmp_path / "story" / "default.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"content": '{"stories": ["canned"]}'}))
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: '{"stories": [{"trunc'
        )
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("story", "sys", "usr")

    def test_default_budget_raised_for_multi_call_generation(self, monkeypatch):
        """Removing the fallback must not just turn fixtures into errors: the
        default wall-clock budget is raised so genuine multi-call generations
        complete (QA saw 58-62s runs hitting the old 60s cap)."""
        monkeypatch.delenv("AETHER_LLM_BUDGET_SECONDS", raising=False)
        assert get_budget_seconds() >= 180.0


class TestReplayModeStillServesFixtures:
    """(b) Replay mode (the test harness) is UNCHANGED — it legitimately serves
    fixtures with no network I/O."""

    def test_replay_returns_fixture(self, tmp_path):
        f = tmp_path / "tailor" / "default.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"content": "replayed"}))
        llm = LLMClient(mode="replay", fixture_dir=tmp_path)
        assert llm.complete("tailor", "sys", "usr") == "replayed"

    def test_replay_complete_json_parses_fixture(self, tmp_path):
        f = tmp_path / "story" / "default.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps({"content": '{"stories": []}'}))
        llm = LLMClient(mode="replay", fixture_dir=tmp_path)
        assert llm.complete_json("story", "sys", "usr") == {"stories": []}


# ===========================================================================
# GAP-P6-TAIL-002.1 — context-scoped anti-fabrication guard
# ===========================================================================
# A realistic two-employer résumé: an ATO / Payday-Super role and an unrelated
# Telstra role. The seeded "payments" story is evidence ABOUT the Payday-Super
# program only — nothing establishes Telstra ran a payment platform.
_RESUME_MULTI = (
    "WORK EXPERIENCE\n"
    "Scrum Master, Australian Taxation Office (ATO)\n"
    "March 2026 - Present | Melbourne\n"
    "• Lead end-to-end delivery for the Agile Kookaburras squad on the "
    "Payday Super reform program (NTP & Distribution UI capabilities).\n"
    "Business Analyst, Telstra\n"
    "Nov 2014 - Oct 2015 | Melbourne\n"
    "• Developed customer journey scorecards and streamlined JIRA "
    "requirements for core delivery teams, improving delivery efficiency by 20%.\n"
)
_MULTI_BULLETS = [
    {
        "text": "Lead end-to-end delivery for the Agile Kookaburras squad on the "
        "Payday Super reform program (NTP & Distribution UI capabilities).",
        "evidenceRef": "bullet-0",
    },
    {
        "text": "Developed customer journey scorecards and streamlined JIRA "
        "requirements for core delivery teams, improving delivery efficiency by 20%.",
        "evidenceRef": "bullet-1",
    },
]
# The real seeded Payday-Super payments story (uat evidence). Establishes the
# candidate's "payments" experience — but ONLY in the ATO / Payday-Super context.
_PAYMENTS_STORY = (
    "Delivering Test Evidence for the Payday Super Payment Reform Program. "
    "Payments Infrastructure Regulatory Compliance. The Payday Super reform "
    "requires employers to remit employee superannuation payments at each "
    "payday. As delivery lead for the Agile Kookaburras squad I owned the "
    "test-evidence strategy proving the new payment-reform capabilities across "
    "the ATO NTP & Distribution UI capabilities and eight delivery squads."
)
# JD is about payments, so the LLM mirrors "payment" from the posting.
_PAY_JD = (
    "Program Manager, Payments. Requirements: payments, payment platform, "
    "portfolio intake, stakeholder management."
)


def _tailor(rewrites: list[dict[str, str]]):
    from app.services.resume_tailor import ResumeTailorService

    class _StubLLM:
        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            return {"bullets": rewrites, "evidenceRefs": [r["evidenceRef"] for r in rewrites]}

    return ResumeTailorService(llm=_StubLLM()).tailor(
        _RESUME_MULTI, _PAY_JD, originals=_MULTI_BULLETS, evidence_extra=_PAYMENTS_STORY
    )


def test_cross_context_keyword_rejected_on_wrong_employer():
    """"payment" (proven only by the Payday-Super story) attributed to the
    Telstra bullet is a cross-context fabrication and MUST be rejected — even
    though the token exists in the candidate's overall evidence corpus."""
    result = _tailor(
        [
            {
                "text": "Developed customer journey scorecards and streamlined JIRA "
                "requirements for payment delivery teams, improving "
                "delivery efficiency by 20%.",
                "evidenceRef": "bullet-1",
            }
        ]
    )
    telstra = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert telstra["text"] == _MULTI_BULLETS[1]["text"], "cross-context bleed not rejected"
    assert result.changes == 0
    assert result.rejected


def test_same_context_keyword_still_accepted():
    """The guard must not over-reject: "payments" surfaced on the Payday-Super
    bullet the story actually supports is legitimate and MUST be accepted, so a
    genuine ATS lift is still achievable."""
    result = _tailor(
        [
            {
                "text": "Lead end-to-end delivery for the Agile Kookaburras squad on "
                "the Payday Super payments reform program (NTP & Distribution UI "
                "capabilities).",
                "evidenceRef": "bullet-0",
            }
        ]
    )
    payday = next(b for b in result.bullets if b["evidenceRef"] == "bullet-0")
    assert "payment" in payday["text"].lower(), result.rejected
    assert result.changes == 1


def test_both_together_scopes_by_context():
    """One run rewriting BOTH bullets: the Payday one keeps "payments"; the
    Telstra one is reverted. Proves the scoping is per-context, not global."""
    result = _tailor(
        [
            {
                "text": "Lead end-to-end delivery for the Agile Kookaburras squad on "
                "the Payday Super payments reform program (NTP & Distribution UI "
                "capabilities).",
                "evidenceRef": "bullet-0",
            },
            {
                "text": "Developed customer journey scorecards and streamlined JIRA "
                "requirements for payment delivery teams, improving "
                "delivery efficiency by 20%.",
                "evidenceRef": "bullet-1",
            },
        ]
    )
    by_ref = {b["evidenceRef"]: b["text"] for b in result.bullets}
    assert "payment" in by_ref["bullet-0"].lower()  # in-context: accepted
    assert by_ref["bullet-1"] == _MULTI_BULLETS[1]["text"]  # cross-context: reverted
    assert result.changes == 1


# ===========================================================================
# GAP-P6-TAIL-002.2 — persisted raw_text regenerated from tailored bullets
# ===========================================================================
_RESUME = (
    "JANE DOE\n"
    "Senior Backend Engineer\n"
    "\n"
    "SKILLS\n"
    "Python, PostgreSQL, REST\n"
    "\n"
    "EXPERIENCE\n"
    "Acme Corp\n"
    "2019 - 2024 | Sydney\n"
    "• Built backend services handling 2000000 requests per day, cutting latency by 40%.\n"
    "• Led a team of 5 engineers delivering payment features.\n"
)
_ORIGINAL_BULLETS = [
    {
        "text": "Built backend services handling 2000000 requests per day, cutting latency by 40%.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led a team of 5 engineers delivering payment features.", "evidenceRef": "bullet-1"},
]
_TAILORED_BULLETS = [
    {
        "text": "Built backend services on Kubernetes with Kafka streaming, handling "
        "2000000 requests per day, cutting latency by 40%.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led a team of 5 engineers delivering payment features.", "evidenceRef": "bullet-1"},
]
_JD = "Senior Backend Engineer. Requirements: Python, PostgreSQL, REST, Kubernetes, Kafka, backend services."


def test_persisted_raw_text_reflects_tailored_bullets():
    """The tailored version's persisted ``raw_text`` must be regenerated from
    the TAILORED bullets, not reuse the parent's — so an independent
    ``GET /resumes/{id}/ats`` reflects the tailored (higher) score, not the
    stale baseline."""
    from app.agents.tailor_agent import TailoringAgent
    from app.services.ats_engine import ATSEngine
    from app.services.resume_tailor import TailorResult

    captured: dict[str, Any] = {}

    class _StubService:
        def tailor(self, resume_text, jd, originals=None, evidence_extra=""):  # noqa: ANN001
            return TailorResult(
                bullets=list(_TAILORED_BULLETS),
                originals=list(_ORIGINAL_BULLETS),
                changes=1,
            )

    class _StubResumes:
        def get_by_id(self, resume_id, user_id):  # noqa: ANN001
            return {
                "id": "base-1",
                "formatHash": "hash",
                "sections": {"raw_text": _RESUME, "bullets": _ORIGINAL_BULLETS},
            }

        def create(self, user_id, sections, format_hash, **kwargs):  # noqa: ANN001
            captured["sections"] = sections
            return {"id": "child-1"}

        def next_version(self, user_id):  # noqa: ANN001
            return 2

    class _StubJobs:
        def get_by_id(self, job_id, user_id):  # noqa: ANN001
            return {"title": "Backend Engineer", "company": "Acme", "description": _JD}

    class _StubStories:
        def list_by_user(self, user_id):  # noqa: ANN001
            return []

    TailoringAgent(
        resumes=_StubResumes(), jobs=_StubJobs(), service=_StubService(), stories=_StubStories()
    ).run("user-1", "job-1", resume_id="base-1")

    raw = captured["sections"]["raw_text"]
    # Regenerated from the tailored bullets — carries the surfaced keywords the
    # parent raw_text never had.
    assert "Kubernetes" in raw and "Kafka" in raw, raw
    assert "Kubernetes" not in _RESUME  # proves it is NOT the parent's raw_text
    # A later independent ATS re-read now reflects the tailored (higher) score.
    tailored_ats = ATSEngine().score(raw, _JD).overall
    baseline_ats = ATSEngine().score(_RESUME, _JD).overall
    assert tailored_ats > baseline_ats, (tailored_ats, baseline_ats)
