"""W-TAILOR-CONVERGE item 4 — persistence half of the cover-letter quality score.

MEASURED STATE before this change (production ``aether`` schema, 2026-08-02):

    SELECT column_name FROM information_schema.columns
     WHERE table_name='Application' AND table_schema='aether'
       AND column_name='coverLetterQuality';
    -- (0 rows)

    SELECT count(*) FROM "Application" WHERE "coverLetter" IS NOT NULL;
    -- 105

105 stored cover letters and nowhere to record a quality score, because
``CoverLetterRepository.create`` had no such parameter and the column did not
exist. This test pins the column, the round-trip through the REAL repository,
and — critically — that a caller which measured nothing writes SQL NULL rather
than a fabricated placeholder score.

DB-DEPENDENT, deliberately NOT the ``client``/``db_session`` fixtures: those
``TRUNCATE`` the shared ``aether_test`` schema, which collides with any other
pytest process holding ``/tmp/aether-pytest.lock``. This file makes narrow,
real INSERT/SELECT/DELETE writes through the production repositories with
``uuid4``-suffixed ids, and deletes exactly the rows it created.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.db import ensure_cover_letter_quality_columns, get_connection
from app.repositories.cover_letter import CoverLetterRepository
from app.repositories.job import JobRepository
from app.repositories.resume import ResumeRepository
from app.repositories.user import UserRepository
from app.services.cover_letter_quality import score_cover_letter

_JD = (
    "Senior Backend Engineer at Acme. You will own our Kafka pipelines and "
    "Postgres platform. Underwriting experience is highly regarded."
)
_EVIDENCE = "Built Kafka ingestion pipelines and ran a Postgres fleet for the billing team."
_LETTER = (
    "I am applying for the Senior Backend Engineer role at Acme.\n\n"
    "I built Kafka ingestion pipelines and ran a Postgres fleet for the "
    "billing team.\n\n"
    "I would welcome an interview to talk this through."
)


def _seed() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    user = UserRepository().create(
        f"wtc-cover-quality-{uuid.uuid4().hex[:12]}@example.com",
        "not-a-real-hash",
        name="Quality Persist Test",
    )
    job = JobRepository().create(
        user["id"],
        {
            "title": "Senior Backend Engineer",
            "company": "Acme",
            "description": _JD,
            "source": "wtc-test",
            "sourceUrl": f"https://example.com/wtc-{uuid.uuid4().hex[:8]}",
        },
    )
    resume = ResumeRepository().create(
        user["id"],
        {"raw_text": _EVIDENCE, "bullets": [{"text": _EVIDENCE, "evidenceRef": "bullet-0"}]},
        "wtc-format-hash",
        label="Base",
        version=1,
    )
    return user, job, resume


def _cleanup(user_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "User" WHERE "id" = %s', (user_id,))
        conn.commit()


def test_application_has_a_cover_letter_quality_column() -> None:
    ensure_cover_letter_quality_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_type FROM information_schema.columns"
                " WHERE table_name = 'Application'"
                " AND table_schema = ANY(current_schemas(false))"
                " AND column_name = 'coverLetterQuality'"
            )
            row = cur.fetchone()
    assert row is not None, "Application.coverLetterQuality was never created"
    assert row[0] == "jsonb", row


def test_quality_round_trips_through_the_real_repository() -> None:
    user, job, resume = _seed()
    try:
        quality = score_cover_letter(
            _LETTER, _JD, _EVIDENCE, job_title=job["title"], company=job["company"]
        )
        payload = {**quality.as_dict(), "initialScore": 40.0,
                   "finalScore": quality.overall, "delta": round(quality.overall - 40.0, 2)}
        stored = CoverLetterRepository().create(
            user["id"], job["id"], resume["id"], _LETTER, quality=payload
        )
        assert stored["coverLetterQuality"] is not None

        reloaded = CoverLetterRepository().get_by_id(stored["id"], user["id"])
        assert reloaded is not None
        persisted = reloaded["coverLetterQuality"]
        assert persisted["overall"] == quality.overall, persisted
        assert persisted["initialScore"] == 40.0, persisted
        assert persisted["finalScore"] == quality.overall, persisted
        # The unreachable half must survive the round trip: it is the honest
        # explanation for why an evidence-limited letter cannot score higher.
        assert "underwriting" in persisted["unreachableKeywords"], persisted
        assert persisted["reachedTarget"] == (quality.overall >= quality.target_score)
    finally:
        _cleanup(user["id"])


def test_a_letter_with_no_measured_quality_stores_null_not_a_placeholder() -> None:
    """An unmeasured letter must read back as NULL. Writing a neutral number
    would make 105 pre-existing unscored letters indistinguishable from real
    measurements."""
    user, job, resume = _seed()
    try:
        stored = CoverLetterRepository().create(
            user["id"], job["id"], resume["id"], _LETTER
        )
        assert stored["coverLetterQuality"] is None, stored["coverLetterQuality"]
        reloaded = CoverLetterRepository().get_by_id(stored["id"], user["id"])
        assert reloaded is not None
        assert reloaded["coverLetterQuality"] is None
    finally:
        _cleanup(user["id"])
