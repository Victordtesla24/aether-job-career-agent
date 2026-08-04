"""POST /resumes/upload — file ingestion + OPT-IN story extraction (SC-ST-03).

F-03 (PROD-UAT-2026-08-03): extraction used to be dispatched unconditionally,
so an upload silently spent a metered agent run. It is now opt-in via the
``extract_stories`` form flag (default off) — see
``apps/api/app/routers/resumes.py`` and
``tests/test_f03_upload_silent_quota_spend.py``, which owns the quota
assertions. The GAP-P6-RESFIX cases below are re-pointed at the path that
still dispatches (``extract_stories=true``) so every one of their original
assertions keeps its full force.
"""
from __future__ import annotations

RESUME_TEXT = """VIKRAM DESHPANDE
Senior Technical Program Manager — Melbourne, VIC, Australia

EXPERIENCE
- Led a portfolio of delivery programs across banking platforms with 100% compliance.
- Automated a COBOL/mainframe regression harness, lifting test efficiency by 92%.
- Coached three agile squads through a cloud migration with zero missed releases.
"""


def _upload(
    client,
    auth_headers,
    filename: str,
    content: bytes,
    mime: str,
    *,
    extract_stories: bool = False,
):
    return client.post(
        "/resumes/upload",
        files={"file": (filename, content, mime)},
        data={"extract_stories": "true" if extract_stories else "false"},
        headers=auth_headers,
    )


def test_upload_text_resume_creates_root_without_running_extraction(
    client, auth_headers
):
    before = client.get("/resumes", headers=auth_headers).json()
    res = _upload(client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 201
    body = res.json()
    assert body["label"].startswith("Uploaded — vik_resume")
    assert body["parentId"] is None
    assert body["sections"]["raw_text"].startswith("VIKRAM DESHPANDE")
    assert len(body["sections"]["bullets"]) >= 3
    # F-03: extraction is opt-in, so a plain upload runs none and says so.
    assert body["storyExtractionRequested"] is False
    assert body["storyExtraction"] is None
    after = client.get("/resumes", headers=auth_headers).json()
    assert len(after) == len(before) + 1


def test_upload_rejects_too_short_content(client, auth_headers):
    res = _upload(client, auth_headers, "empty.txt", b"too short", "text/plain")
    assert res.status_code == 422


def test_upload_rejects_unparseable_pdf(client, auth_headers):
    res = _upload(client, auth_headers, "broken.pdf", b"%PDF-1.4 garbage", "application/pdf")
    assert res.status_code == 422


def test_upload_requires_auth(client):
    res = _upload(client, {}, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# GAP-P6-RESFIX: the storyExtractor auto-trigger must not bury a 402
# subscription-required entitlement error inside a 200 response (the extractor
# call runs through app.routers.agents._dispatch -> _record_run, which raises
# HTTPException BEFORE the extraction ever executes). Only genuine extractor
# failures for an entitled subscriber may be swallowed into storyExtraction.error.
# ---------------------------------------------------------------------------


def _set_plan(user_id: str, plan_id: str, status: str) -> None:
    """Force the user's Subscription row to (plan_id, status) with a matching
    UsageQuota ceiling — mirrors the helper in test_gap_p6_paywall.py."""
    from app.db import get_connection
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (plan_id, status, user_id),
            )
            cur.execute(
                'UPDATE "UsageQuota" SET "planId"=%s,"runsAllowed"=100,'
                '"updatedAt"=now() WHERE "userId"=%s',
                (plan_id, user_id),
            )
        conn.commit()


def test_upload_propagates_402_for_non_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A non-subscriber's resume upload must surface the real 402 — not a
    200 with the paywall error buried in storyExtraction.error."""
    from app.repositories.billing import ensure_user_billing

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    ensure_user_billing(test_user_id)  # Free/active by default -> NOT paid
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 402, res.text
    body = res.json()
    assert body["detail"]["error"] == "subscription_required"
    assert body["detail"]["upgradeUrl"] == "/pricing"


def test_upload_still_succeeds_for_paid_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A paid subscriber's opt-in upload is unaffected — it still succeeds with
    a real storyExtraction result (no entitlement error to swallow)."""
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["storyExtractionRequested"] is True
    extraction = body["storyExtraction"]
    assert extraction is not None
    assert "error" not in extraction


def test_upload_still_swallows_genuine_extractor_error_for_subscriber(
    client, auth_headers, test_user_id, monkeypatch
):
    """A real (non-HTTPException) extractor failure for an entitled
    subscriber must still be swallowed into storyExtraction.error — the
    upload itself must not fail."""
    from app.agents.story_extractor import StoryExtractorAgent

    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")
    _set_plan(test_user_id, "pro", "active")

    def _boom(self, user_id):
        raise RuntimeError("synthetic extractor failure")

    monkeypatch.setattr(StoryExtractorAgent, "run", _boom)
    res = _upload(
        client, auth_headers, "vik_resume.txt", RESUME_TEXT.encode(), "text/plain",
        extract_stories=True,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["storyExtraction"]["error"] == "synthetic extractor failure"
