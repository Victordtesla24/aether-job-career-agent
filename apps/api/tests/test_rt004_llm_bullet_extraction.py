"""RT-004 — a DISCLOSED, METERED, anti-fabrication-gated bullet extractor.

RT-002 makes a bullet-less résumé refuse honestly instead of blaming the model.
That is the truth, but it is a dead end: the owner's real résumé (a designed
multi-column PDF whose flat text layer carries no bullet markers) still cannot
be tailored at all, because the heuristic ``extract_bullets`` state machine has
no marker lines to latch onto.

RT-004 gives that résumé a way out that does not weaken a single guard:

* ``services.resume_bullets_llm.llm_extract_bullets`` — ONE ``complete_json`` call
  on the STRUCTURED tier that copies the achievement bullets VERBATIM out of
  ``raw_text``. Anti-fabrication is enforced IN CODE, not by asking nicely: a
  returned bullet whose text is not a substring of ``raw_text`` (after
  whitespace normalisation) is REJECTED. The model may only select, never write.
* ``POST /resumes/{id}/extract-bullets`` — owner-scoped, and METERED through
  the very same ``_record_run`` rail every other genuine LLM call uses
  (atomic reserve BEFORE the call, refund on honest failure, AgentRun audit
  row). Exempting it would recreate F-03's silent-spend hole in reverse:
  unmetered, unbounded LLM capacity, one free run per résumé.
* Upload/ingest DISCLOSURE — a résumé that parsed 0 bullets says so in its own
  create response (``tailorableBullets: 0`` + a warning naming the remedy)
  instead of looking healthy right up until the first tailor run fails. The
  upload deliberately does NOT auto-run the extractor: F-03 (PROD-UAT-2026-08-03)
  settled that a metered LLM run must be the caller's explicit, pre-disclosed
  choice.

Fail-before (unfixed tree): ``app.services.resume_bullets_llm`` does not exist,
``POST /resumes/{id}/extract-bullets`` 404s/405s, and the create/upload
responses carry no ``tailorableBullets`` key at all.
"""
from __future__ import annotations

import uuid

import pytest

#: Same production shape RT-002 uses: complete text, ZERO marker lines, so the
#: heuristic extractor finds nothing and the LLM extractor is the only route.
BULLETLESS_RESUME_TEXT = """VIKRAM SARKAR    Melbourne VIC    vik@example.com
Business Analyst
PROFILE
Business analyst with fifteen years across banking and government platforms.
EXPERIENCE
Australian Taxation Office    Business Analyst    2021 to 2024
Delivered the Payday Super discovery across eight agency stakeholders.
Reduced manual reconciliation effort by 92 percent with an automated harness.
Telstra    Senior Analyst    2018 to 2021
Mapped the order to activate journey for the enterprise fibre portfolio.
EDUCATION
Master of Business Systems, Monash University, 2010
"""

#: Exactly what ``tests/fixtures/llm/resume_bullets/default.json`` replays.
FIXTURE_BULLETS = [
    "Delivered the Payday Super discovery across eight agency stakeholders.",
    "Reduced manual reconciliation effort by 92 percent with an automated harness.",
    "Mapped the order to activate journey for the enterprise fibre portfolio.",
]


class _StubLLM:
    """A stand-in ``LLMClient`` that returns a fixed ``complete_json`` payload."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple] = []

    def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
        self.calls.append((prompt_name, kwargs.get("model")))
        return self.payload


def _create_resume(client, auth_headers, raw_text=BULLETLESS_RESUME_TEXT, label="Vik BA"):
    res = client.post(
        "/resumes", json={"label": label, "raw_text": raw_text}, headers=auth_headers
    )
    assert res.status_code == 201, res.text
    return res.json()


def _runs_used(user_id: str) -> int:
    from app.repositories.billing import UsageQuotaRepository

    row = UsageQuotaRepository().get_by_user(user_id)
    return int(row["runsUsed"]) if row else 0


@pytest.fixture()
def billing_seeded(test_user_id):
    from app.repositories.billing import ensure_user_billing

    ensure_user_billing(test_user_id)
    return test_user_id


# ---------------------------------------------------------------------------
# 1-3: the service — one STRUCTURED call, verbatim copy, nothing invented
# ---------------------------------------------------------------------------
class TestExtractionService:
    def test_happy_path_returns_the_bullets_verbatim(self):
        """Replay mode + the committed fixture: the real call shape, no network."""
        from app.services.resume_bullets_llm import llm_extract_bullets

        bullets = llm_extract_bullets(BULLETLESS_RESUME_TEXT)
        assert bullets == FIXTURE_BULLETS, bullets
        for b in bullets:
            assert b in BULLETLESS_RESUME_TEXT

    def test_it_runs_on_the_structured_tier_in_exactly_one_call(self):
        from app.services.llm_client import get_model
        from app.services.resume_bullets_llm import llm_extract_bullets

        stub = _StubLLM({"bullets": FIXTURE_BULLETS})
        llm_extract_bullets(BULLETLESS_RESUME_TEXT, llm=stub)
        assert len(stub.calls) == 1, stub.calls
        assert stub.calls[0][1] == get_model("STRUCTURED")

    def test_a_bullet_not_present_in_the_resume_is_rejected(self):
        """THE anti-fabrication gate. The model is a SELECTOR here; anything it
        authors rather than copies is dropped, not stored as the user's own
        career history."""
        from app.services.resume_bullets_llm import llm_extract_bullets

        stub = _StubLLM(
            {
                "bullets": [
                    "Delivered the Payday Super discovery across eight agency "
                    "stakeholders.",
                    "Led a 40-person engineering organisation to a $12M revenue "
                    "record.",  # nowhere in the résumé — invented
                ]
            }
        )
        bullets = llm_extract_bullets(BULLETLESS_RESUME_TEXT, llm=stub)
        assert bullets == [
            "Delivered the Payday Super discovery across eight agency stakeholders."
        ], bullets

    def test_line_wrapped_bullets_survive_whitespace_normalisation(self):
        """A verbatim copy of text the PDF layer wrapped differs only in
        whitespace — that is not fabrication and must not be rejected."""
        from app.services.resume_bullets_llm import llm_extract_bullets

        raw = "EXPERIENCE\nDelivered the Payday Super\ndiscovery across eight\nstakeholders.\n"
        stub = _StubLLM(
            {"bullets": ["Delivered the Payday Super discovery across eight stakeholders."]}
        )
        assert llm_extract_bullets(raw, llm=stub) == [
            "Delivered the Payday Super discovery across eight stakeholders."
        ]

    def test_a_reworded_bullet_is_rejected_even_though_every_word_is_present(self):
        """Substring, not bag-of-words: reordering the user's own words into a
        claim they never made is still fabrication."""
        from app.services.resume_bullets_llm import llm_extract_bullets

        stub = _StubLLM(
            {"bullets": ["Reduced reconciliation effort by 92 percent across eight agencies."]}
        )
        assert llm_extract_bullets(BULLETLESS_RESUME_TEXT, llm=stub) == []


# ---------------------------------------------------------------------------
# 4-7: the endpoint — owner-scoped, metered exactly like other LLM work
# ---------------------------------------------------------------------------
class TestExtractBulletsEndpoint:
    def test_it_replaces_the_stored_bullets_and_reports_the_count_honestly(
        self, client, auth_headers, billing_seeded
    ):
        resume = _create_resume(client, auth_headers)
        assert resume["sections"]["bullets"] == []

        res = client.post(
            f"/resumes/{resume['id']}/extract-bullets", headers=auth_headers
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["bulletsExtracted"] == len(FIXTURE_BULLETS)

        stored = client.get(f"/resumes/{resume['id']}", headers=auth_headers).json()
        texts = [b["text"] for b in stored["sections"]["bullets"]]
        assert texts == FIXTURE_BULLETS
        refs = [b["evidenceRef"] for b in stored["sections"]["bullets"]]
        assert refs == [f"bullet-{i}" for i in range(len(FIXTURE_BULLETS))]

    def test_it_consumes_exactly_one_metered_run_and_leaves_an_audit_row(
        self, client, auth_headers, billing_seeded
    ):
        """Mirrors ``test_f03_upload_silent_quota_spend`` — genuine LLM work is
        metered on the same rail, never exempted."""
        resume = _create_resume(client, auth_headers)
        before = _runs_used(billing_seeded)

        res = client.post(
            f"/resumes/{resume['id']}/extract-bullets", headers=auth_headers
        )
        assert res.status_code == 200, res.text
        assert _runs_used(billing_seeded) == before + 1

        runs = client.get("/agents/runs", headers=auth_headers).json()
        mine = [r for r in runs if r["agentName"] == "bulletExtractor"]
        assert len(mine) == 1, runs
        assert mine[0]["status"] == "completed"

    def test_bullet_extraction_is_a_metered_structured_backend(self):
        """Pins WHY the endpoint is not exempt: it really does call a model."""
        from app.routers.agents import (
            _DETERMINISTIC_BACKENDS,
            _LLM_TIER_BY_BACKEND,
            _call_is_metered,
        )

        assert _LLM_TIER_BY_BACKEND["bulletExtractor"] == "STRUCTURED"
        assert "bulletExtractor" not in _DETERMINISTIC_BACKENDS
        assert _call_is_metered("bulletExtractor", {}) is True

    def test_another_users_resume_is_not_extractable(
        self, client, auth_headers, billing_seeded
    ):
        resume = _create_resume(client, auth_headers)

        email = f"other-{uuid.uuid4().hex[:8]}@example.com"
        creds = {"email": email, "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=creds).status_code == 201
        token = client.post("/auth/login", json=creds).json()["access_token"]
        other = {"Authorization": f"Bearer {token}"}

        res = client.post(f"/resumes/{resume['id']}/extract-bullets", headers=other)
        assert res.status_code == 404, res.text

    def test_unauthenticated_callers_are_refused(self, client, auth_headers):
        resume = _create_resume(client, auth_headers)
        res = client.post(f"/resumes/{resume['id']}/extract-bullets")
        assert res.status_code in (401, 403), res.text


# ---------------------------------------------------------------------------
# 8-10: upload/ingest disclosure — say it up front, never spend silently
# ---------------------------------------------------------------------------
class TestZeroBulletDisclosure:
    def test_ingest_of_a_bulletless_resume_discloses_zero_and_warns(
        self, client, auth_headers
    ):
        body = _create_resume(client, auth_headers)
        assert body["tailorableBullets"] == 0, body
        warning = body.get("tailoringWarning") or ""
        assert "tailor" in warning.lower(), warning
        assert "extract" in warning.lower(), warning

    def test_a_resume_with_real_bullets_reports_its_real_count_and_no_warning(
        self, client, auth_headers
    ):
        text = (
            "VIKRAM SARKAR\nBusiness Analyst\nEXPERIENCE\n"
            "- Delivered the Payday Super discovery across eight agencies.\n"
            "- Reduced manual reconciliation effort by 92 percent.\n"
        )
        body = _create_resume(client, auth_headers, raw_text=text, label="With bullets")
        assert body["tailorableBullets"] == 2, body
        assert body.get("tailoringWarning") is None, body

    def test_upload_discloses_zero_without_running_the_metered_extractor(
        self, client, auth_headers, billing_seeded
    ):
        """F-03's rule, upheld: disclosure is free, extraction is a choice."""
        before = _runs_used(billing_seeded)
        res = client.post(
            "/resumes/upload",
            files={
                "file": (
                    "Vik_Resume_BA.txt",
                    BULLETLESS_RESUME_TEXT.encode(),
                    "text/plain",
                )
            },
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["tailorableBullets"] == 0, body
        assert body.get("tailoringWarning"), body
        assert _runs_used(billing_seeded) == before, (
            "the upload silently spent a metered LLM run (F-03 regression)"
        )
        runs = client.get("/agents/runs", headers=auth_headers).json()
        assert [r for r in runs if r["agentName"] == "bulletExtractor"] == []

    def test_upload_never_fails_just_because_no_bullets_were_parsed(
        self, client, auth_headers
    ):
        res = client.post(
            "/resumes/upload",
            files={
                "file": (
                    "Vik_Resume_BA.txt",
                    BULLETLESS_RESUME_TEXT.encode(),
                    "text/plain",
                )
            },
            headers=auth_headers,
        )
        assert res.status_code == 201, res.text
        assert res.json()["sections"]["raw_text"].strip(), "the text must be kept"
