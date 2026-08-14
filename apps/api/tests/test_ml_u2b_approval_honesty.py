"""ML-U2B-approval-honesty — the tailoring approval card's reasoning must
never assert layout preservation as an unconditional "Verified" check.

Sonnet coherence re-review (uat/reports/evidence/agents-uplift/u2b/
SONNET-COHERENCE-REREVIEW-20260814.md, finding F4) sampled the 3 most recent
real ``resume_tailor`` approvals against their résumé's own real fidelity:
2 of 3 showed the user a green "Verified: Original layout preserved" claim
for a résumé whose real download is ``formatPreserved: false`` (a re-flowed
Aether-template render). The hardcoded reasoning item at
``tailor_agent.py:266-272`` took no fidelity input at all and could not vary
by outcome — it was TRUE for 1 of 3 sampled live approvals and FALSE for the
other 2.

ORCHESTRATOR RULING (U2b approval-honesty, 2026-08-14):
1. ``build_tailor_approval_extras`` must derive its layout-preservation
   reasoning line from the run's REAL fidelity report (the same
   ``describe_fidelity``/``pending_fidelity`` decision table ``GET /resumes``
   already stamps every version with) — honest wording per state, never an
   unconditional claim. Locked here.
2. PENDING ``resume_tailor`` approvals render fidelity LIVE from the
   résumé's own fidelity data where the reasoning is displayed (frozen line
   superseded on display), and a FAILED live-fidelity fetch renders an
   honest-unknown warning rather than letting the frozen claim stand
   (MF-1, round-4 re-review) — the pure supersession logic is locked in
   apps/web/src/components/approvals/__tests__/lib.test.ts, and the
   component-level wiring (the effect fires for the right kind/status, is
   keyed by payload.resume_id, supersedes the rendered DOM on success,
   degrades honestly on fetch failure, and never fires for resolved/other
   approvals) is locked in
   apps/web/src/components/approvals/__tests__/live-fidelity.test.tsx.
3. The 199 historical RESOLVED rows stay frozen (not rewritten) — see this
   slice's evidence note documenting the era boundary.

These tests lock ruling (1): ``build_tailor_approval_extras`` takes a
``FormatFidelity`` argument and its one "layout" reasoning item is provably
conditioned on it — including the ``formatPreserved: false`` case the review
sampled live in production (a reflow-template, low-confidence base), and the
end-to-end path through ``TailoringAgent.run()`` that actually computes it.
"""
from __future__ import annotations

from typing import Any

from app.agents.tailor_agent import TailoringAgent, build_tailor_approval_extras
from app.services.ats_engine import ATSScore
from app.services.resume_format import (
    METHOD_PDF_SPLICE,
    METHOD_REFLOW,
    describe_fidelity,
)
from app.services.resume_tailor import TailorResult

_JOB = {"title": "Backend Engineer", "company": "Acme"}
_JD = "Backend Engineer. Requirements: Python, PostgreSQL."
_RESUME = (
    "JANE DOE\nSenior Backend Engineer\n\nSKILLS\nPython, PostgreSQL\n\n"
    "EXPERIENCE\nAcme Corp\n2019 - 2024 | Sydney\n- Built things.\n"
)
_ORIGINAL_BULLETS = [{"text": "Built things.", "evidenceRef": "bullet-0"}]


def _changed_result() -> TailorResult:
    bullets = [{"text": "Built scalable things.", "evidenceRef": "bullet-0"}]
    return TailorResult(bullets=bullets, originals=_ORIGINAL_BULLETS, changes=1, rejected=[])


def _layout_item(extras: dict[str, Any]) -> dict[str, Any]:
    items = [r for r in extras["reasoning"] if "layout" in r["text"].lower()]
    assert len(items) == 1, extras["reasoning"]
    return items[0]


# --- 1. the generator must vary its claim by the base document's real fidelity


def test_reasoning_check_when_mechanism_supports_preservation() -> None:
    """A bundled-PDF base (native in-place splice, high confidence) may
    honestly show a "check" — but the note must name that verification is
    per-document/on-render, never a bare unconditional "Verified" claim
    independent of the mechanism."""
    fidelity = describe_fidelity(
        bundled_match=True, has_original=True, content_type="application/pdf",
        is_tailored=True,
    )
    assert fidelity.method == METHOD_PDF_SPLICE and fidelity.preserved is True

    extras = build_tailor_approval_extras(_changed_result(), _JOB, "", fidelity)
    item = _layout_item(extras)
    assert item["kind"] == "check", item
    assert fidelity.note in item["text"], item


def test_reasoning_never_claims_preservation_for_a_reflow_base() -> None:
    """THE regression case: 2/3 live-sampled approvals were for a
    ``reflow-template``/low-confidence/``formatPreserved: false`` base, yet
    the old hardcoded string told the user "Original layout preserved"
    regardless. A reflow base must produce a WARNING and must never assert
    the résumé's layout is preserved.
    """
    fidelity = describe_fidelity(
        bundled_match=False, has_original=True, content_type="application/pdf",
        is_tailored=True,
    )
    assert fidelity.method == METHOD_REFLOW and fidelity.preserved is False

    extras = build_tailor_approval_extras(_changed_result(), _JOB, "", fidelity)
    item = _layout_item(extras)
    assert item["kind"] == "warning", (
        f"a reflow base must not be reported as a passed check: {item}"
    )
    assert "original layout preserved" not in item["text"].lower(), item
    assert fidelity.note in item["text"], item


def test_reasoning_is_a_warning_for_unresolved_fidelity() -> None:
    """An unresolvable source document (``preserved is None``) must not be
    reported as a passed check either — "unknown" is not "verified"."""
    fidelity = describe_fidelity(
        bundled_match=False, has_original=False, content_type=None,
        is_tailored=True, source_resolved=False,
    )
    assert fidelity.preserved is None

    extras = build_tailor_approval_extras(_changed_result(), _JOB, "", fidelity)
    item = _layout_item(extras)
    assert item["kind"] == "warning", item
    assert "original layout preserved" not in item["text"].lower(), item


# --- 2. TailoringAgent.run() must compute and wire a REAL fidelity report ---


class _StubJobs:
    def get_by_id(self, job_id: str, user_id: str) -> dict[str, Any]:  # noqa: ANN001
        return dict(_JOB, description=_JD)

    def advance_status(self, *a: Any, **k: Any) -> None:  # noqa: ANN401
        pass


class _StubStories:
    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:  # noqa: ANN001
        return []


class _StubApprovals:
    def __init__(self) -> None:
        self.captured: dict[str, Any] | None = None

    def create(self, user_id: str, kind: str, extras: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        self.captured = extras
        return {"id": "appr-1", "status": "pending"}


class _ScriptedService:
    def tailor(
        self, resume_text: str, jd: str, originals: Any = None, evidence_extra: str = ""
    ) -> TailorResult:
        base = list(originals or _ORIGINAL_BULLETS)
        rewritten = [
            {"text": f"{b['text']} tailored.", "evidenceRef": b.get("evidenceRef", f"bullet-{i}")}
            for i, b in enumerate(base)
        ]
        return TailorResult(bullets=rewritten, originals=base, changes=len(rewritten), rejected=[])


class _ScriptedATSEngine:
    def score(self, resume_text: str, job_description: str) -> ATSScore:
        return ATSScore(
            overall=90.0,
            keyword_match=90.0,
            semantic_similarity=90.0,
            experience_gap=100.0,
            matched_keywords=[],
            missing_keywords=[],
            requires_review=False,
        )


class _StubResumesNoOriginal:
    """Base résumé with NO stored original file — mirrors 2/3 of the
    live-sampled ``reflow-template`` approvals from the coherence review."""

    def get_by_id(self, resume_id: str, user_id: str) -> dict[str, Any]:  # noqa: ANN001
        return {
            "id": "base-1",
            "formatHash": "hash-1",
            "sections": {"raw_text": _RESUME, "bullets": _ORIGINAL_BULLETS},
        }

    def create(self, user_id: str, sections: dict[str, Any], *a: Any, **k: Any) -> dict[str, Any]:  # noqa: ANN401
        return {"id": "child-1", **sections}

    def next_version(self, user_id: str) -> int:  # noqa: ANN001
        return 2

    def original_meta_by_user(self, user_id: str) -> dict[str, dict[str, Any]]:  # noqa: ANN001
        return {"base-1": {"hasOriginal": False, "originalContentType": None}}


class _StubResumesLegacyNoMetaMethod:
    """Every OTHER pre-existing test double for this agent in the suite
    (test_tailor_response_contract.py, test_gap_p6_tailoring_ats.py,
    test_gap_p6_authenticity.py, test_tailor_persistence_db.py,
    test_tailor_score_persistence_e2e.py) predates this fix and never
    implements ``original_meta_by_user`` — the fix must degrade honestly for
    them, never crash."""

    def get_by_id(self, resume_id: str, user_id: str) -> dict[str, Any]:  # noqa: ANN001
        return {
            "id": "base-1",
            "formatHash": "hash-1",
            "sections": {"raw_text": _RESUME, "bullets": _ORIGINAL_BULLETS},
        }

    def create(self, user_id: str, sections: dict[str, Any], *a: Any, **k: Any) -> dict[str, Any]:  # noqa: ANN401
        return {"id": "child-1", **sections}

    def next_version(self, user_id: str) -> int:  # noqa: ANN001
        return 2


def test_run_reports_honest_not_preserved_for_a_reflow_base() -> None:
    approvals = _StubApprovals()
    agent = TailoringAgent(
        resumes=_StubResumesNoOriginal(),
        jobs=_StubJobs(),
        service=_ScriptedService(),
        stories=_StubStories(),
        approvals=approvals,
        ats_engine=_ScriptedATSEngine(),
    )
    agent.run("user-1", "job-1", resume_id="base-1")
    assert approvals.captured is not None
    item = _layout_item(approvals.captured)
    assert item["kind"] == "warning", item
    assert "original layout preserved" not in item["text"].lower(), item


def test_run_degrades_honestly_without_crashing_for_a_legacy_stub() -> None:
    approvals = _StubApprovals()
    agent = TailoringAgent(
        resumes=_StubResumesLegacyNoMetaMethod(),
        jobs=_StubJobs(),
        service=_ScriptedService(),
        stories=_StubStories(),
        approvals=approvals,
        ats_engine=_ScriptedATSEngine(),
    )
    agent.run("user-1", "job-1", resume_id="base-1")  # must not raise
    assert approvals.captured is not None
    item = _layout_item(approvals.captured)
    # No metadata available -> honest "unknown/not confirmed", never an
    # affirmative preservation claim.
    assert item["kind"] == "warning", item
    assert "original layout preserved" not in item["text"].lower(), item
