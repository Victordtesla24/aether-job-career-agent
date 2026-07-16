"""GAP-P6-TAIL-004 — restore genuine tailoring lift while keeping zero fabrication.

Live production QA (uat/reports/evidence/phase6/qa-prod-craft3.json) confirmed the
GAP-P6-TAIL-003 entailment pass makes tailoring FABRICATION-FREE (zero fabrication
survived across 33 attempts, the 'for financial institutions'/InfoCentric class was
live-reproduced and reverted) — but it produced ZERO ATS lift (tailoredATS ==
baseline in 17/17 completions). Two root causes, both fixed here:

**FIX 1 — entailment verifier budget starvation.** The tailor GENERATION call and
the entailment VERIFICATION call shared the single ``AETHER_LLM_BUDGET_SECONDS``
wall-clock budget. A slow tailor generation ate ~all of it, leaving the verifier
0-9s; it timed out and its conservative fail-safe reverted EVERY changed bullet —
including genuinely-supported ones. The verifier now gets its OWN dedicated budget
reservation (``AETHER_LLM_ENTAILMENT_BUDGET_SECONDS``, default 20s), applied as a
fresh :func:`shared_budget` window around the call, independent of and not
consumable by the tailor generation.

**FIX 2 — anchor-collision false-positive.** ``proper_noun_anchors`` treated
generic capitalised words ("Business", "BI", "SQL", "Data") as context anchors, so
a story's own evidence was excluded from its home bullet (reproduced live: run8
bullet-10, NAB/SQL transplant flagged ['sql','reached']). Only GENUINE proper nouns
(employer/program/product names) count now, and a bullet with NO genuine anchors of
its own uses the FULL evidence corpus. Cross-context fabrication is still caught by
the semantic entailment pass.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.tailor_agent import _compute_conversion_metrics
from app.services import llm_client
from app.services.llm_client import LLMClient
from app.services.resume_tailor import ResumeTailorService, proper_noun_anchors


class _ScriptedLLM:
    """Answers the ``tailor`` and ``tailor_entailment`` prompts distinctly."""

    def __init__(self, tailor_raw: dict[str, Any], entailment_raw: dict[str, Any] | None = None) -> None:
        self.tailor_raw = tailor_raw
        self.entailment_raw = entailment_raw if entailment_raw is not None else {"results": []}

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        if prompt_name == "tailor_entailment":
            return self.entailment_raw
        return self.tailor_raw


# ===========================================================================
# FIX 1 (test a) — the entailment verifier gets its OWN reserved budget even
# when the tailor generation is slow (not starved to 0-9s).
# ===========================================================================


def test_entailment_verifier_gets_dedicated_budget_not_starved(monkeypatch) -> None:
    """A slow tailor generation must NOT starve the entailment verifier. The
    verifier runs inside its own fresh ~20s budget window regardless of how much
    of the shared budget the tailor call consumed."""
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "20")
    monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "60")

    clock = {"t": 1000.0}
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: clock["t"])
    observed: dict[str, float] = {}

    class _SlowTailorLLM(LLMClient):
        def __init__(self) -> None:
            super().__init__(mode="auto")

        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            observed[prompt_name] = self._remaining_budget()
            if prompt_name == "tailor":
                # Tailor generation "consumes" almost the entire 60s shared budget.
                clock["t"] += 58.0
                return {
                    "bullets": [
                        {"text": "Led delivery across squads end to end", "evidenceRef": "bullet-0"}
                    ],
                    "evidenceRefs": ["bullet-0"],
                }
            return {"results": [{"ref": "bullet-0", "entailed": True, "reason": "ok"}]}

    svc = ResumeTailorService(llm=_SlowTailorLLM())
    with llm_client.shared_budget(60):
        result = svc.tailor(
            "• Lead delivery across squads end to end",
            "delivery leadership",
            originals=[{"text": "Lead delivery across squads end to end", "evidenceRef": "bullet-0"}],
        )

    # Sanity: the tailor call saw the full shared budget.
    assert observed["tailor"] >= 55.0, observed
    # The fix: the entailment verifier gets its OWN ~20s window, NOT the ~2s
    # crumbs the slow tailor left (60 - 58). Without the fix this was ~2s and
    # the verifier timed out -> reverted every edit.
    assert observed["tailor_entailment"] >= 15.0, observed
    # The genuinely-supported cosmetic edit survives (not reverted by starvation).
    assert result.changes == 1
    assert result.bullets[0]["text"] == "Led delivery across squads end to end"


def test_entailment_budget_env_default_and_floor(monkeypatch) -> None:
    monkeypatch.delenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", raising=False)
    assert llm_client.get_entailment_budget_seconds() == 20.0
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "not-a-number")
    assert llm_client.get_entailment_budget_seconds() == 20.0
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "2")  # below the floor
    assert llm_client.get_entailment_budget_seconds() == llm_client._MIN_ATTEMPT_SECONDS
    monkeypatch.setenv("AETHER_LLM_ENTAILMENT_BUDGET_SECONDS", "15")
    assert llm_client.get_entailment_budget_seconds() == pytest.approx(15.0)


# ===========================================================================
# FIX 2 (test d) — generic capitalised words are NOT context anchors, and a
# bullet with no genuine anchors uses the FULL evidence corpus.
# ===========================================================================


def test_generic_capitalized_words_are_not_context_anchors() -> None:
    """"Business", "BI", "SQL", "Data" are generic vocabulary, not employer /
    program / product names — they must NOT scope the anti-fabrication corpus."""
    anchors = proper_noun_anchors(
        "Delivered analytics and Business Intelligence (BI) reports for the Data team"
    )
    for generic in ("business", "bi", "intelligence", "data", "team"):
        assert generic not in anchors, (generic, anchors)


def test_genuine_proper_nouns_remain_context_anchors() -> None:
    """Real names (employer acronyms, product names) MUST stay anchors so genuine
    cross-context scoping is preserved."""
    assert "nab" in proper_noun_anchors("Reconciliation at NAB warehouse")
    assert "ato" in proper_noun_anchors("Delivery for the ATO reform program")
    assert "jira" in proper_noun_anchors("Streamlined JIRA requirements")


# A résumé where bullet-0 carries GENERIC capitalised words ("Business",
# "Intelligence", "BI", "Data") and bullet-1 (the NAB home bullet) carries NO
# genuine anchors of its own — employer name lives in a header, not the bullet.
_RESUME_ANCHOR = (
    "EXPERIENCE\n"
    "Analyst\n"
    "2019 - 2024 | Sydney\n"
    "• Delivered analytics and Business Intelligence (BI) across the Data platform.\n"
    "• Led reconciliation work across regulatory streams.\n"
)
_ORIG_ANCHOR = [
    {
        "text": "Delivered analytics and Business Intelligence (BI) across the Data platform.",
        "evidenceRef": "bullet-0",
    },
    {"text": "Led reconciliation work across regulatory streams.", "evidenceRef": "bullet-1"},
]
# The seeded NAB story: its ONLY genuine anchor is "NAB" (a header-only employer),
# so before the fix it was mis-scoped to bullet-0 via the shared generic "Data"
# anchor and WRONGLY excluded from its own home bullet-1.
_STORY_ANCHOR = (
    "SQL-Based Regulatory Data Reconciliation at NAB. "
    "Built SQL reconciliation against a Postgres warehouse that caught 3 "
    "discrepancies before they reached regulator-facing reports."
)
_JD_ANCHOR = "SQL Analyst. Requirements: SQL, reconciliation, regulatory, Postgres warehouse."
_REWRITE_ANCHOR = {
    "bullets": [
        {
            "text": "Led SQL reconciliation work across regulatory streams using a "
            "Postgres warehouse that caught 3 discrepancies.",
            "evidenceRef": "bullet-1",
        }
    ],
    "evidenceRefs": ["bullet-1"],
}


def test_no_anchor_bullet_uses_full_evidence_corpus() -> None:
    """The evidence-backed NAB/SQL transplant onto its home bullet (which has no
    genuine anchors of its own) must PASS the static guard now — its story's
    evidence is in scope (full corpus), so 'SQL'/'Postgres'/'3' are supported."""
    llm = _ScriptedLLM(_REWRITE_ANCHOR)  # entailment rejects nothing
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME_ANCHOR, _JD_ANCHOR, originals=_ORIG_ANCHOR, evidence_extra=_STORY_ANCHOR
    )
    kept = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert "SQL" in kept["text"], result.rejected  # evidence-backed edit survived
    assert "Postgres" in kept["text"]
    assert result.changes == 1
    assert not result.rejected


def test_evidence_backed_edit_lifts_ats_strictly() -> None:
    """FIX outcome (test b): the previously-starved/over-reverted edit now
    survives AND yields a STRICT tailoredATS > baselineATS."""
    llm = _ScriptedLLM(_REWRITE_ANCHOR)
    result = ResumeTailorService(llm=llm).tailor(
        _RESUME_ANCHOR, _JD_ANCHOR, originals=_ORIG_ANCHOR, evidence_extra=_STORY_ANCHOR
    )
    assert result.changes == 1
    metrics = _compute_conversion_metrics(
        _RESUME_ANCHOR, result.originals, result.bullets, _JD_ANCHOR
    )
    assert metrics["tailoredATSScore"] > metrics["baselineATSScore"], metrics
    assert metrics["estimatedConversionLift"].startswith("+")
    assert metrics["estimatedConversionLift"] != "+0.0%", metrics


# ===========================================================================
# FIX no-regression (test c) — fabrication is STILL reverted (§9 zero-tolerance).
# ===========================================================================

_RESUME_FAB = (
    "EXPERIENCE\n"
    "NAB\n"
    "2015 - 2018 | Melbourne\n"
    "• Led regulatory reporting for financial institutions across banking systems.\n"
    "InfoCentric\n"
    "2011 - 2014 | Sydney\n"
    "• Delivered analytics and Business Intelligence projects, boosting engagement by 20%.\n"
)
_ORIG_FAB = [
    {
        "text": "Led regulatory reporting for financial institutions across banking systems.",
        "evidenceRef": "bullet-0",
    },
    {
        "text": "Delivered analytics and Business Intelligence projects, boosting engagement by 20%.",
        "evidenceRef": "bullet-1",
    },
]


def test_fabrication_still_reverted_with_dedicated_budget() -> None:
    """The exact qa-prod-craft3 defect class: 'for financial institutions' bled
    onto InfoCentric (an employer the evidence never ties to finance). Its words
    all appear in the corpus (on the NAB bullet) so the static guard passes it —
    the entailment pass must STILL revert it (no §9 regression)."""
    rewrite = {
        "bullets": [
            {
                "text": "Delivered analytics and Business Intelligence projects for "
                "financial institutions, boosting engagement by 20%.",
                "evidenceRef": "bullet-1",
            }
        ],
        "evidenceRefs": ["bullet-1"],
    }
    entail = {
        "results": [
            {"ref": "bullet-1", "entailed": False, "reason": "InfoCentric not tied to finance."}
        ]
    }
    result = ResumeTailorService(llm=_ScriptedLLM(rewrite, entail)).tailor(
        _RESUME_FAB, "Business Analyst, financial institutions", originals=_ORIG_FAB
    )
    reverted = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert "for financial institutions" not in reverted["text"]
    assert reverted["text"] == _ORIG_FAB[1]["text"]
    assert result.changes == 0
    assert any("financial institutions" in r for r in result.rejected)


def test_anchor_narrowing_preserves_cross_context_rejection() -> None:
    """Narrowing generic anchors must NOT re-open cross-context bleed: a keyword
    proven only in the Payday-Super story is still rejected on the Telstra bullet,
    which carries its own genuine anchor ('JIRA')."""
    resume = (
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
    originals = [
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
    story = (
        "Delivering Test Evidence for the Payday Super Payment Reform Program. "
        "The Payday Super reform requires employers to remit employee "
        "superannuation payments at each payday, delivered by the Agile "
        "Kookaburras squad across the ATO NTP & Distribution UI capabilities."
    )
    # LLM tries to bleed 'payment' (proven only for Payday-Super) onto Telstra.
    rewrite = {
        "bullets": [
            {
                "text": "Developed customer journey scorecards and streamlined JIRA "
                "requirements for payment delivery teams, improving delivery efficiency by 20%.",
                "evidenceRef": "bullet-1",
            }
        ],
        "evidenceRefs": ["bullet-1"],
    }
    result = ResumeTailorService(llm=_ScriptedLLM(rewrite)).tailor(
        resume, "Program Manager, Payments. Requirements: payments, payment platform.",
        originals=originals, evidence_extra=story,
    )
    telstra = next(b for b in result.bullets if b["evidenceRef"] == "bullet-1")
    assert telstra["text"] == originals[1]["text"], "cross-context bleed not rejected"
    assert result.changes == 0
    assert result.rejected
