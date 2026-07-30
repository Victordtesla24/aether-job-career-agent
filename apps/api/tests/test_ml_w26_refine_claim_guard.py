"""ML-W26 — the cover-letter REFINE path never ran the §9 claim guard.

Found during W-23: ``POST /cover-letters/{id}/refine``'s local ``_draft``
closure (``apps/api/app/routers/cover_letters.py``) runs ONLY
``FabricationGuard`` — it never calls ``unsupported_claim_tokens`` (the §9
claim guard the main generation path wires through
``CoverLetterAgent._draft`` / ``run()``). ``FabricationGuard`` only flags a
candidate entity/number that is absent from its evidence corpus, and that
corpus INCLUDES the sanitized job description — so a JD-sourced noun phrase
("central repository of audit evidence artifacts", "SOC 2", "PCI DSS") is
already IN the corpus and never flagged, even when the model claims it as the
candidate's OWN personal experience with zero résumé support. This is exactly
the re-labelling class ML-W23 closed for the main generation path
(``test_ml_w23_jd_body_relabelling.py``) — refine has its own independent
draft loop and was never wired to the same guard, so a "Request Changes"
redraft can reintroduce the whole fabrication class the main path blocks.

Fix: wire the SAME claim-guard invocation shape the main path uses
(``cover_letter_agent.py``'s ``unsupported_claim_tokens(model_text,
claim_evidence, jd_risk, jd_body)`` — including the ``jd_body`` W-23 param),
with the same honest single-retry-then-reject behaviour the refine path
already has for ``FabricationGuard``.

Run under the shared test-DB lock::

    flock /tmp/aether-pytest.lock scripts/run-tests.sh \
        tests/test_ml_w26_refine_claim_guard.py -q
"""
from __future__ import annotations

from conftest import JORDAN_RESUME_TEXT, seed_own_resume

from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.services.llm_client import LLMClient

# ---------------------------------------------------------------------------
# Shared fixtures: a JD whose phrase vocabulary (audit/repository/SOC 2/
# PCI DSS) the résumé never mentions — verbatim from the ML-W23 live repro
# (test_ml_w23_jd_body_relabelling.py) so this is a proven-flaggable phrase
# channel, just exercised through the REFINE endpoint instead of unit-called.
# ---------------------------------------------------------------------------
_JD_BODY = (
    "Responsibilities Act as an information security subject matter expert "
    "during cross-functional audit engagements, representing the Security team "
    "in walkthrough meetings with auditors and regulators. Create and maintain "
    "a central repository of audit evidence artifacts required for compliance "
    "with SOC 2, PCI DSS, SOX, and other global regulatory standards. Perform "
    "security risk and control assessments against common frameworks to ensure "
    "compliance with the company's Information Security Policy and Standards."
)
_JD_TITLE = "Program Manager, Security GRC"

#: The model-authored revision a "Request Changes" redraft could plausibly
#: return: a first-person claim to have personally built the exact JD-body
#: artifact, with zero support anywhere in JORDAN_RESUME_TEXT.
_UNEVIDENCED_CLAIM_BODY = (
    "My experience architecting a central audit evidence repository for a "
    "major compliance program aligns directly with the need to create and "
    "maintain a central repository of audit evidence artifacts for the "
    "team's SOC 2 and PCI DSS obligations.\n\n"
    "I would welcome the opportunity to discuss how I can bring this "
    "experience to the team in an interview at your convenience."
)

#: An HONEST revision that only restates JORDAN_RESUME_TEXT's own evidence in
#: the first person — must survive both the FabricationGuard and the claim
#: guard, unchanged by this fix (the pin).
_HONEST_BODY = (
    "I led 6 engineers on a payments platform in Python and PostgreSQL, "
    "improving throughput 40 percent, which is a strong match for this "
    "role.\n\n"
    "I would welcome the opportunity to discuss how I can bring this "
    "experience to the team in an interview at your convenience."
)


def _seed_job(user_id: str, suffix: str, *, title: str, description: str) -> str:
    """Insert a REAL ``Job`` row with a caller-controlled description (mirrors
    the pattern in test_mv_cluster_a_cover_letter.py's ``_seed_job``)."""
    created = JobRepository().create(
        user_id,
        {
            "title": title,
            "company": "Northwind Compliance",
            "location": "Remote",
            "remote": True,
            "description": description,
            "requirements": [],
            "source": "test",
            "sourceUrl": f"https://example.test/ml-w26/{suffix}",
            "postedAt": None,
        },
    )
    return created["id"]


def _seed_letter(client, auth_headers, *, suffix: str, title: str, description: str):
    """Seed the fixture user their own résumé, a JD-controlled job, and an
    initial letter row directly (bypassing the generation agent's own LLM
    call, which is irrelevant to the REFINE path under test)."""
    resume = seed_own_resume(client, auth_headers, raw_text=JORDAN_RESUME_TEXT)
    me = client.get("/auth/me", headers=auth_headers).json()
    user_id = me["id"]
    job_id = _seed_job(user_id, suffix, title=title, description=description)
    letter = CoverLetterRepository().create(
        user_id, job_id, resume["id"], "Placeholder initial draft body."
    )
    return letter, job_id


class TestRefineClaimGuard:
    def test_refine_rejects_unevidenced_jd_sourced_claim(
        self, client, auth_headers, monkeypatch
    ):
        """FAIL-BEFORE: today the refine path ships this claim with a 200
        because only FabricationGuard runs, and the JD phrase vocabulary is
        already IN its evidence corpus (sanitized JD), so nothing is flagged.
        PASS-AFTER: the §9 claim guard treats the JD as risk vocabulary only
        (never evidence) and rejects the unsupported personal claim, 422."""
        letter, _job_id = _seed_letter(
            client, auth_headers, suffix="claim", title=_JD_TITLE, description=_JD_BODY
        )

        def _fake_complete_json(self, prompt_name, system, user, **kwargs):
            return {"body": _UNEVIDENCED_CLAIM_BODY}

        monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Make it more specific to the role."},
            headers=auth_headers,
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "fabrication guard" in detail.lower(), detail
        for term in ("repository", "audit"):
            assert term in detail, (
                f"expected the JD-sourced unsupported claim term {term!r} in "
                f"the rejection detail: {detail!r}"
            )

    def test_refine_honest_revision_still_succeeds(
        self, client, auth_headers, monkeypatch
    ):
        """PIN: an honest revision that only restates the candidate's own
        résumé evidence in the first person must be unaffected by wiring the
        claim guard in — the refine path's existing behaviour for a clean
        draft (200, new version, pending approval) is unchanged."""
        letter, job_id = _seed_letter(
            client, auth_headers, suffix="honest", title=_JD_TITLE, description=_JD_BODY
        )

        def _fake_complete_json(self, prompt_name, system, user, **kwargs):
            return {"body": _HONEST_BODY}

        monkeypatch.setattr(LLMClient, "complete_json", _fake_complete_json)

        resp = client.post(
            f"/cover-letters/{letter['id']}/refine",
            json={"instructions": "Tighten the opening."},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cover_letter_id"] != letter["id"]
        assert body["approval_status"] == "pending"
        assert "40 percent" in body["cover_letter"]
