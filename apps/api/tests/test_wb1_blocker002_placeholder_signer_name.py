"""BLOCKER-002 (GOLD-MASTER-V2 W-B wave 1) — cover-letter generation signs a
customer-facing document with a leftover test-probe / placeholder identity
string instead of failing honestly.

[VERIFIED-WITH-SOURCE] Evidence:
``uat/reports/evidence/gold-master-v2/adversarial/AI-AGENT-QUALITY-ASSESSMENT.md``
-- live on production, ``GET /api/auth/me`` on the OWNER account returned
``"name": "GAP-P7-DEF-B Probe 1785452243543"`` (contamination from a past
adversarial test probe), and the cover-letter PDF letterhead AND sign-off
both rendered that exact string as the sender's name.

Root cause (confirmed against this worktree):
``apps/api/app/agents/cover_letter_agent.py`` ``CoverLetterAgent.run()``
(~line 1215) does ``signer = str(user.get("name") or "")`` with NO check
that the stored name looks like a real human name before splicing it into
``compose_letter()``'s sign-off (``"Sincerely,\\n{signer}\\n"``, ~line 800)
and into the PDF letterhead's ``_sender_block()``
(``apps/api/app/routers/cover_letters.py`` ~line 903). Any string in
``User.name`` -- including obvious test-artifact contamination -- ships
verbatim onto a document a real employer will read.

Test-author's chosen detection rule (the finding text explicitly invites
this: "Choose a defensible detection rule and assert it"): a signer name is
placeholder-looking if it contains the case-insensitive substrings "probe"
or "test", OR the literal marker "GAP-", OR a run of 8+ consecutive digits
(a strong signal of an auto-generated/timestamped test identity — no real
human name contains an 8+ digit run). This rule is deliberately narrow: it
must reject the three variants below while leaving ordinary human names
(including hyphenated / apostrophe'd ones) untouched -- see
``test_cover_letter_accepts_normal_human_name`` below, the false-positive
guard the finding explicitly asks for.

Intended behaviour under test: cover-letter generation must refuse (422,
mirroring the SAME honest-rejection shape ``_guard_rejection_http_error``
already uses for FabricationError/StructuralError in
``apps/api/app/routers/agents.py``) with an explicit, actionable detail
telling the user to set their real name -- and must never let the raw
placeholder string reach the response body. Today it does neither: the run
succeeds (200) and the placeholder string is emitted verbatim.
"""
from __future__ import annotations

import uuid

import pytest
from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume


def _set_profile_name(client, auth_headers, full_name: str) -> None:
    resp = client.put(
        "/workspaces/settings",
        json={
            "profile": {
                "fullName": full_name,
                "email": f"wb1-blocker002-{uuid.uuid4().hex[:8]}@example.com",
                "targetRole": "Software Engineer",
                "location": "Remote",
            },
            "agentConfig": {"autoApply": False, "approvalGate": True, "matchThreshold": 80},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def _seed_job(client, auth_headers) -> dict:
    seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202, run.text
    jobs = client.get("/jobs", headers=auth_headers).json()
    assert jobs, "scout run produced no jobs to draft a letter against"
    return jobs[0]


#: The exact production-contaminated value, plus two synthetic variants
#: covering the other cues the finding names ("test" keyword, "probe"
#: keyword + a long digit run).
PLACEHOLDER_NAMES = [
    "GAP-P7-DEF-B Probe 1785452243543",
    "QA Test Runner 445566778899",
    "probe_user_20260731093000",
]


@pytest.mark.parametrize("placeholder_name", PLACEHOLDER_NAMES)
def test_cover_letter_refuses_placeholder_signer_name(client, auth_headers, placeholder_name):
    _set_profile_name(client, auth_headers, placeholder_name)
    job = _seed_job(client, auth_headers)

    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
    )

    assert resp.status_code == 422, (
        "cover-letter generation must FAIL HONESTLY (422) when the profile "
        f"name looks like a placeholder/test artefact ({placeholder_name!r}) "
        "instead of emitting it onto a customer-facing document. Got "
        f"{resp.status_code}: {resp.text[:2000]!r}"
    )
    detail = str(resp.json().get("detail", "")).lower()
    assert "name" in detail, (
        f"422 detail must actionably tell the user to set their real name, got: {detail!r}"
    )
    assert placeholder_name.lower() not in resp.text.lower(), (
        "the raw placeholder string must never leak into the error response body"
    )


def test_cover_letter_accepts_normal_human_name(client, auth_headers):
    """False-positive guard (explicitly required by the finding): a real
    human name must NOT be rejected, and must render correctly in the
    sign-off. This id is expected to PASS both before and after a fix --
    it exists to stop an over-broad placeholder rule from shipping."""
    _set_profile_name(client, auth_headers, "Jordan Rivera")
    job = _seed_job(client, auth_headers)

    resp = client.post(
        "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "Sincerely,\nJordan Rivera" in body["cover_letter"], (
        "a normal human name must render correctly in the sign-off"
    )
