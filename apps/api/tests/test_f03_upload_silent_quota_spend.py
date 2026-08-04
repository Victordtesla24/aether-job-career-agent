"""F-03 — uploading a résumé must not silently spend a metered agent run.

PROD-UAT-2026-08-03 finding F-03 (MAJOR), reproduced live against
https://5cb5f0620.abacusai.cloud: ``POST /api/resumes/upload`` auto-dispatched
the LLM-metered ``storyExtractor`` agent. One deliberate user action (upload)
therefore produced an unrequested agent run with ``costUsd 0.0010`` and
``billingAudit.quotaPath "metered_api"``, and moved ``runsUsed`` by one — 20%
of the Free tier's five monthly runs, with no warning before the fact and no
opt-out.

Story extraction IS a genuine LLM call (``StoryExtractorAgent.run`` →
``LLMClient.complete_json`` on the STRUCTURED tier, one call per four résumé
bullets), so the honest remedy is NOT to exempt it from metering — that would
create an unmetered, unbounded LLM-spend path (upload N files, get N free LLM
runs) and would contradict the existing exemption seam, which exempts only
calls that reach NO model (``_DETERMINISTIC_BACKENDS`` /
``_OPTIONAL_LLM_BY_BACKEND``). The remedy is that the spend must be the user's
own explicit, pre-disclosed choice: upload alone consumes nothing, and
extraction runs only when the caller asks for it.

Fail-before (at 0ac3e82): tests 1-3 fail — the upload dispatches unconditionally,
so ``runsUsed`` advances, a ``storyExtractor`` AgentRun row appears, and the
response reports an extraction the user never requested.
"""
from __future__ import annotations

import pytest

RESUME_TEXT = """VIKRAM DESHPANDE
Senior Technical Program Manager — Melbourne, VIC, Australia

EXPERIENCE
- Led a portfolio of delivery programs across banking platforms with 100% compliance.
- Automated a COBOL/mainframe regression harness, lifting test efficiency by 92%.
- Coached three agile squads through a cloud migration with zero missed releases.
"""


def _upload(client, auth_headers, *, data: dict[str, str] | None = None):
    return client.post(
        "/resumes/upload",
        files={"file": ("vik_resume.txt", RESUME_TEXT.encode(), "text/plain")},
        data=data or {},
        headers=auth_headers,
    )


def _runs_used(user_id: str) -> int:
    from app.repositories.billing import UsageQuotaRepository

    row = UsageQuotaRepository().get_by_user(user_id)
    return int(row["runsUsed"]) if row else 0


def _story_runs(client, auth_headers) -> list[dict]:
    res = client.get("/agents/runs", headers=auth_headers)
    assert res.status_code == 200, res.text
    return [r for r in res.json() if r["agentName"] == "storyExtractor"]


@pytest.fixture()
def billing_seeded(test_user_id):
    """Materialise the quota row so ``runsUsed`` is a real number rather than an
    absent row that would make the assertions vacuous."""
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(test_user_id)
    return test_user_id


# ---------------------------------------------------------------------------
# 1-3: uploading, on its own, spends nothing and claims nothing
# ---------------------------------------------------------------------------


def test_upload_alone_consumes_no_plan_quota(client, auth_headers, billing_seeded):
    """THE defect. Uploading a file is not an agent run; it must not move the
    user's metered run allowance."""
    before = _runs_used(billing_seeded)
    res = _upload(client, auth_headers)
    assert res.status_code == 201, res.text
    assert _runs_used(billing_seeded) == before, (
        "uploading a résumé consumed a metered agent run the user never "
        "requested (F-03) — on Free that is 1 of 5 monthly runs"
    )


def test_upload_alone_creates_no_story_extractor_run(
    client, auth_headers, billing_seeded
):
    """The audit-trail half: no unrequested ``storyExtractor`` row may appear in
    the user's own run history off the back of an upload."""
    before = len(_story_runs(client, auth_headers))
    res = _upload(client, auth_headers)
    assert res.status_code == 201, res.text
    assert len(_story_runs(client, auth_headers)) == before, (
        "an unrequested storyExtractor run appeared in GET /agents/runs after a "
        "plain résumé upload"
    )


def test_upload_response_states_that_no_extraction_ran(
    client, auth_headers, billing_seeded
):
    """The response must say plainly that extraction did NOT run, so the UI copy
    built from it cannot claim otherwise."""
    body = _upload(client, auth_headers).json()
    assert body["storyExtractionRequested"] is False
    assert body["storyExtraction"] is None


# ---------------------------------------------------------------------------
# 4-6: the capability is preserved — opt in and it runs, metered exactly once
# ---------------------------------------------------------------------------


def test_opt_in_upload_runs_extraction_and_charges_exactly_one_run(
    client, auth_headers, billing_seeded
):
    """The other direction: the rail must not be weakened into "extraction is
    free". A caller that explicitly asks for extraction gets it, metered exactly
    as ``POST /agents/story-extractor/run`` is."""
    before = _runs_used(billing_seeded)
    before_runs = len(_story_runs(client, auth_headers))
    res = _upload(client, auth_headers, data={"extract_stories": "true"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["storyExtractionRequested"] is True
    assert body["storyExtraction"] is not None
    assert _runs_used(billing_seeded) == before + 1
    assert len(_story_runs(client, auth_headers)) == before_runs + 1


def test_opt_in_is_the_only_thing_that_triggers_extraction(
    client, auth_headers, billing_seeded
):
    """An explicit ``false`` behaves exactly like an absent flag — no accidental
    truthiness ("false" is a non-empty string) may re-open the silent path."""
    before = _runs_used(billing_seeded)
    body = _upload(client, auth_headers, data={"extract_stories": "false"}).json()
    assert body["storyExtractionRequested"] is False
    assert body["storyExtraction"] is None
    assert _runs_used(billing_seeded) == before


def test_opt_in_upload_still_propagates_402_for_a_non_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """GAP-P6-RESFIX, preserved on the path that still dispatches: the paywall
    402 must surface as the response status, never be buried in
    ``storyExtraction.error``."""
    from app.repositories.billing import ensure_user_billing

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
    res = _upload(client, auth_headers, data={"extract_stories": "true"})
    assert res.status_code == 402, res.text
    assert res.json()["detail"]["error"] == "subscription_required"


def test_plain_upload_is_not_an_agent_run_and_so_is_not_paywalled(
    client, auth_headers, test_user_id, monkeypatch
):
    """The deliberate, disclosed consequence of the fix: with extraction opted
    out, an upload makes no LLM call and reserves nothing, so the agent-run
    entitlement gate no longer applies to it — matching every other
    non-agent resume endpoint (``POST /resumes``, ``GET /resumes``)."""
    from app.repositories.billing import ensure_user_billing

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)
    res = _upload(client, auth_headers)
    assert res.status_code == 201, res.text
    assert res.json()["storyExtraction"] is None


# ---------------------------------------------------------------------------
# 7: the fact this fix rests on — extraction is genuinely metered LLM work
# ---------------------------------------------------------------------------


def test_story_extractor_remains_a_metered_llm_backend():
    """Pins WHY option (a) (exempt it from quota) was rejected: storyExtractor
    really does call a model, so exempting it would hand out unmetered LLM
    capacity per uploaded file."""
    from app.routers.agents import (
        _DETERMINISTIC_BACKENDS,
        _LLM_TIER_BY_BACKEND,
        _call_is_metered,
    )

    assert _LLM_TIER_BY_BACKEND["storyExtractor"] == "STRUCTURED"
    assert "storyExtractor" not in _DETERMINISTIC_BACKENDS
    assert _call_is_metered("storyExtractor", {}) is True
