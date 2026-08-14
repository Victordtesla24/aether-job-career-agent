"""U2c — the REFINE path is gated too, or the gate is a formality.

``CoverLetterAgent.run`` now scores its letter, spends a bounded number of
improvement passes closing any dimension below the 80% floor, and stamps the
verdict on the artifact and its approval — so a below-floor letter can only be
approved through an explicit "Approve anyway — N dimensions below floor".

``POST /cover-letters/{id}/refine`` produces a customer-facing letter through
its own independent draft loop, stores it as a brand-new row and opens a fresh
approval. It never scored the result at all. That makes refine a LAUNDERING
path, and the sequence is one an ordinary user would stumble into without ever
intending to game anything:

    generate  ->  below floor, acknowledgement required to approve
    refine    ->  no verdict computed, nothing to acknowledge
    approve   ->  ships unflagged

The letter that reaches the employer is the refined one. A gate the user can
step around by clicking "Request Changes" is not a gate, and — worse — the
second letter is silently presented as unproblematic when nobody measured it.
This is exactly the "never silently passed" rule the slice exists to enforce,
so the refine path gets the SAME treatment, through the SAME functions:

* ``score_cover_letter`` — the same scorer, over the same dimension set;
* ``needs_gate_pass`` / ``gate_improvement_instruction`` /
  ``accept_gate_candidate`` / ``gate_pass_labels`` — the agent's own gate
  helpers, imported rather than re-implemented, so the two paths cannot fork;
* ``build_letter_quality`` — the same stored record shape;
* the same env-capped attempt budget and the same per-pass budget check.

And the same cardinal-sin rule: the guards adjudicate every gate pass, and a
candidate that scores higher by claiming something the evidence does not prove
is DISCARDED. That is pinned here on the refine path in its own right.

Run under the shared test-DB lock::

    nice flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_u2c_refine_gate.py -p no:randomly -q
"""
from __future__ import annotations

from typing import Any

from conftest import JORDAN_RESUME_TEXT, seed_own_resume

from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.services.cover_letter_quality import CoverLetterQuality
from app.services.llm_client import LLMClient

_JD_TITLE = "Platform Engineer"
_JD_BODY = (
    "We are looking for a platform engineer to lead a payments platform team, "
    "working in Python and PostgreSQL, with a focus on throughput and "
    "reliability."
)

#: Restates the fixture résumé's own evidence in the first person — clean
#: against the FabricationGuard, the §9 claim guard and the §10.2 structure
#: contract, so the GATE is what the assertions are about.
_HONEST_BODY = (
    "I led 6 engineers on a payments platform in Python and PostgreSQL, "
    "improving throughput 40 percent, which is a strong match for this "
    "role.\n\n"
    "I would welcome the opportunity to discuss how I can bring this "
    "experience to the team in an interview at your convenience."
)


def _quality(
    *,
    overall: float,
    grounding: float,
    alignment: float = 90.0,
    structure: float = 100.0,
    measured: bool = True,
) -> CoverLetterQuality:
    return CoverLetterQuality(
        overall=overall,
        jd_alignment=alignment,
        grounding=grounding,
        structure=structure,
        reached_target=overall >= 85.0,
        jd_alignment_measured=measured,
        missing_keywords=["postgresql"],
        unreachable_keywords=[],
    )


def _seed_letter(client: Any, auth_headers: Any, suffix: str) -> tuple[dict, str]:
    resume = seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    user_id = client.get("/auth/me", headers=auth_headers).json()["id"]
    job = JobRepository().create(
        user_id,
        {
            "title": _JD_TITLE,
            "company": "Northwind Platforms",
            "location": "Remote",
            "remote": True,
            "description": _JD_BODY,
            "requirements": [],
            "source": "test",
            "sourceUrl": f"https://example.test/u2c-refine/{suffix}",
            "postedAt": None,
        },
    )
    letter = CoverLetterRepository().create(
        user_id, job["id"], resume["id"], "Placeholder initial draft body."
    )
    return letter, user_id


def _script_scorer(monkeypatch: Any, qualities: list[CoverLetterQuality]) -> list[int]:
    """Script ``score_cover_letter`` AS THE ROUTER SEES IT.

    The scorer's own arithmetic is pinned in ``test_cover_letter_quality.py``;
    what is under test here is whether the refine path consults it at all and
    what it does with the answer.
    """
    calls: list[int] = []

    def _score(*a: Any, **k: Any) -> CoverLetterQuality:
        index = min(len(calls), len(qualities) - 1)
        calls.append(index)
        return qualities[index]

    monkeypatch.setattr("app.routers.cover_letters.score_cover_letter", _score)
    return calls


def _stub_llm(monkeypatch: Any, bodies: list[str]) -> list[str]:
    """Return each body in turn (last repeats) and record every paid call."""
    seen: list[str] = []

    def _complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        body = bodies[min(len(seen), len(bodies) - 1)]
        seen.append(str(kwargs.get("fixture_key") or "default"))
        return {"body": body}

    monkeypatch.setattr(LLMClient, "complete_json", _complete_json)
    return seen


class TestTheRefinedLetterCarriesAVerdict:
    def test_a_clean_refinement_stores_and_publishes_its_gate_verdict(
        self, client: Any, auth_headers: Any, monkeypatch: Any
    ) -> None:
        """The refined letter is a customer-facing artifact in its own right,
        so it carries its own measured verdict — on the stored row AND on the
        approval the reviewer opens."""
        letter, _ = _seed_letter(client, auth_headers, "clean")
        _script_scorer(monkeypatch, [_quality(overall=92.0, grounding=91.0)])
        _stub_llm(monkeypatch, [_HONEST_BODY])

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Tighten the opening."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        stored = CoverLetterRepository().get_by_id(
            resp.json()["cover_letter_id"],
            client.get("/auth/me", headers=auth_headers).json()["id"],
        )
        quality = stored["coverLetterQuality"]
        assert quality is not None, "the refine path measured nothing"
        assert quality["qualityGate"]["passed"] is True
        assert quality["belowQualityFloor"] is False

        approval = client.get(
            f"/approvals/{resp.json()['approval_id']}", headers=auth_headers
        ).json()
        assert approval["payload"]["qualityGate"]["passed"] is True

    def test_a_below_floor_refinement_cannot_be_approved_unacknowledged(
        self, client: Any, auth_headers: Any, monkeypatch: Any
    ) -> None:
        """THE LAUNDERING PIN. A refined letter that sits below the floor must
        reach the reviewer wearing the same acknowledgement gate the generated
        one wears — otherwise 'Request Changes' is a bypass."""
        letter, _ = _seed_letter(client, auth_headers, "below")
        # Every attempt scores the same: the gate spends its budget and then
        # terminates honestly rather than pretending.
        _script_scorer(monkeypatch, [_quality(overall=88.0, grounding=61.0)])
        _stub_llm(monkeypatch, [_HONEST_BODY])

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it warmer."},
            headers=auth_headers,
        )
        # The artifact is DELIVERED — never withheld, never blocked-with-no-output.
        assert resp.status_code == 200, resp.text
        assert resp.json()["cover_letter"]

        approval_id = resp.json()["approval_id"]
        gate = client.get(
            f"/approvals/{approval_id}", headers=auth_headers
        ).json()["payload"]["qualityGate"]
        assert gate["passed"] is False
        assert gate["failingLabels"] == ["Evidence Grounding"]

        refused = client.post(f"/approvals/{approval_id}/approve", headers=auth_headers)
        assert refused.status_code == 409, refused.text
        assert "Evidence Grounding" in refused.json()["detail"]

        accepted = client.post(
            f"/approvals/{approval_id}/approve",
            json={"acknowledge_below_floor": True},
            headers=auth_headers,
        )
        assert accepted.status_code == 200, accepted.text


class TestTheRefineGateIsBoundedAndGuarded:
    def test_it_spends_bounded_extra_passes_and_stops_when_the_gate_closes(
        self, client: Any, auth_headers: Any, monkeypatch: Any
    ) -> None:
        """One below-floor draft, then a clean one that clears every dimension:
        the loop must stop the moment the gate passes, not keep spending."""
        from app.agents.cover_letter_agent import gate_pass_labels

        letter, _ = _seed_letter(client, auth_headers, "bounded")
        _script_scorer(
            monkeypatch,
            [_quality(overall=88.0, grounding=61.0), _quality(overall=92.0, grounding=91.0)],
        )
        seen = _stub_llm(monkeypatch, [_HONEST_BODY])

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Improve the evidence."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        # Initial draft + exactly ONE gate pass, even though the budget allows
        # more — a closed gate buys nothing further.
        assert len(seen) == 2, seen
        assert seen[1] == gate_pass_labels()[0]

    def test_a_higher_scoring_but_unclean_gate_pass_is_discarded(
        self, client: Any, auth_headers: Any, monkeypatch: Any
    ) -> None:
        """THE CARDINAL SIN, on the refine path. The improvement pass returns a
        draft that would clear the floor but claims experience the candidate's
        evidence does not prove. It must be thrown away and the truthful,
        lower-scoring letter must ship — never the fabricated higher score."""
        letter, _ = _seed_letter(client, auth_headers, "cardinal")
        unsupported = (
            "I personally architected the central repository of audit evidence "
            "artifacts for SOC 2 and PCI DSS compliance across the "
            "organisation.\n\n"
            "I would welcome the opportunity to discuss this work with your "
            "team at your convenience."
        )
        # The unclean candidate would score higher — the ONLY thing that may
        # reject it is the guards.
        _script_scorer(
            monkeypatch,
            [_quality(overall=88.0, grounding=61.0), _quality(overall=99.0, grounding=99.0)],
        )
        _stub_llm(monkeypatch, [_HONEST_BODY, unsupported])

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Add more evidence."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        shipped = resp.json()["cover_letter"]
        assert "40 percent" in shipped, "the truthful letter was not the one shipped"
        assert "audit evidence" not in shipped.lower(), (
            "a fabricated claim bought a higher score — the cardinal sin"
        )

        stored = CoverLetterRepository().get_by_id(
            resp.json()["cover_letter_id"],
            client.get("/auth/me", headers=auth_headers).json()["id"],
        )
        # The HONEST verdict is what is recorded: the discarded draft's score
        # never becomes the letter's score.
        assert stored["coverLetterQuality"]["belowQualityFloor"] is True
