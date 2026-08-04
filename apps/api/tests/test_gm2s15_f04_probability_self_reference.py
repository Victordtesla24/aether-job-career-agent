"""GOLD-MASTER-V2 §15 STEP 2 — F-04: the "Job Probability Score" is inflated
by a self-referential "market demand" factor.

THE DEFECT (current code, apps/api/app/routers/analytics.py, read 2026-08-04):

    line 386:  cur.execute('SELECT COUNT(*) FROM "Job" WHERE "userId" = %s', ...)
               sources_total = int(cur.fetchone()[0])
    line 589:  market_demand_factor = min(100, round(sources_total / 50 * 100)) if sources_total else 0
    line 594:  {"label": "Market demand", "value": market_demand_factor},
    line 601:  measured: list[int] = [app_volume_factor, market_demand_factor]  # UNCONDITIONAL
    line 606:  prob_score = round(sum(measured) / len(measured)) if measured else 0
    line 694:  "note": "Likelihood of landing an offer in the next 60 days",

``sources_total`` is ``COUNT(*) FROM "Job" WHERE "userId" = <caller>`` — the
user's OWN saved-job count, produced entirely client-side by their own Scout
agent runs ("Sync Now"). It is not market data of any kind (no external
market-data provider is wired anywhere in this module —
``_MARKET_DATA_SOURCE_CONNECTED = False``, line 255), it saturates at a
50-job threshold a single sync blows past, it is labelled "Market demand"
and averaged unconditionally into the headline "Job Probability Score", and
that headline is captioned as an "offer" likelihood despite there being no
offer-outcome model anywhere in this codebase.

This is a genuinely self-referential term: the score is presented as
evidence ABOUT the user's chances, built in part from a number that is
purely a fact about how many jobs their own agent has sourced — an input
with zero informational content about outcome likelihood, that a single
button click can drive to its ceiling.

Fail-before (current code, 2026-08-04): tests 1 and 2 fail — sourcing more
jobs (no new applications, no new fit scores) moves the headline score, and
the note still claims an offer-likelihood estimate. Test 3 (real, non-self-
referential signals still move the score) is pinned here so a fix cannot
satisfy this file by freezing the score entirely.

CORRECTION (2026-08-04, WC-INTERVIEW-SEED-001 class): test 3 originally
claimed to "already pass", but that was never observable — it died in its own
arrange step with ``UniqueViolation`` on ``Application_user_job_active_key``
because it seeded four ``submitted`` rows and then four ``interview`` rows on
the SAME four jobs, and the partial unique index (``app/db.py``,
``ensure_application_unique_active_index``) permits at most ONE active-status
Application per (userId, jobId). The anti-over-correction guard was therefore
vacuous: it never reached its score comparison. Recording an interview outcome
in production PROMOTES the existing application (``move_application``) rather
than inserting a second active row, so test 3 now does exactly that — the same
end state it always intended (interviewed jobs 0 -> 4 on an unchanged
application volume), reached the only way the database permits.
"""
from __future__ import annotations

import pytest

from app.db import get_connection, new_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_jobs(user_id: str, count: int, *, fit_score: float | None = None) -> list[str]:
    """Insert ``count`` Job rows — exactly what clicking "Sync Now" produces.
    ``fit_score=None`` leaves ``Job.fitScore`` NULL (never scored)."""
    ids: list[str] = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            for _ in range(count):
                jid = new_id()
                ids.append(jid)
                cur.execute(
                    '''
                    INSERT INTO "Job" ("id", "userId", "title", "company",
                        "description", "source", "sourceUrl", "fitScore",
                        "createdAt", "updatedAt")
                    VALUES (%s, %s, 'Delivery Manager', 'Acme', 'desc', 'seek',
                        %s, %s, NOW(), NOW())
                    ''',
                    (jid, user_id, f"https://example.com/{jid}", fit_score),
                )
        conn.commit()
    return ids


def _seed_resume(user_id: str) -> str:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "Resume" ("id", "userId", "sections", "formatHash", "updatedAt")
                VALUES (%s, %s, '{}', 'gm2s15f04hash', NOW()) RETURNING "id"
                ''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
        conn.commit()
    return str(resume_id)


#: Mirrors ``app.db.APPLICATION_ACTIVE_STATUSES`` exactly. A partial UNIQUE
#: index (``Application_user_job_active_key``, see
#: ``app.db.ensure_application_unique_active_index``) forbids more than one
#: Application row in any of these statuses for the same (userId, jobId).
#: Same invariant, same constant and same fail-loud guard as
#: ``tests/test_wc_interview_conversion_rate.py`` (WC-INTERVIEW-SEED-001) —
#: a seed that puts two active statuses on ONE job is a data-integrity
#: violation the production DB itself refuses to store, so a test built on it
#: dies in its arrange step and never reaches its assertion.
_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")


def _seed_applications(user_id: str, job_ids: list[str], statuses: list[str]) -> None:
    """Seed one Application row per entry of ``statuses``, round-robin across
    ``job_ids``.

    Guards WC-INTERVIEW-SEED-001 across BOTH the rows this call adds and the
    rows already stored for the same jobs — the failure this guard exists for
    was a SECOND call landing a second active status on jobs seeded by the
    first. Callers recording a later outcome on an already-active application
    must use :func:`_promote_applications` instead.
    """
    resume_id = _seed_resume(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            active_per_job: dict[str, list[str]] = {}
            cur.execute(
                '''
                SELECT "jobId", "status"::text FROM "Application"
                WHERE "userId" = %s AND "jobId" = ANY(%s)
                  AND "status"::text = ANY(%s)
                ''',
                (user_id, list(job_ids), list(_ACTIVE_STATUSES)),
            )
            for job_id, existing in cur.fetchall():
                active_per_job.setdefault(str(job_id), []).append(str(existing))
            for i, status in enumerate(statuses):
                if status in _ACTIVE_STATUSES:
                    active_per_job.setdefault(job_ids[i % len(job_ids)], []).append(status)
            for job_id, active in active_per_job.items():
                assert len(active) <= 1, (
                    f"seed puts {len(active)} active-status rows ({active!r}) on "
                    f"job {job_id} — violates the real "
                    f"Application_user_job_active_key partial unique index (at "
                    f"most one of {_ACTIVE_STATUSES} per job). Use 'draft' for "
                    f"the non-final rows, or _promote_applications() to record a "
                    f"later outcome on an existing application."
                )
            for i, status in enumerate(statuses):
                cur.execute(
                    '''
                    INSERT INTO "Application" ("id", "userId", "jobId", "resumeId",
                        "status", "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s::"ApplicationStatus", NOW(), NOW())
                    ''',
                    (new_id(), user_id, job_ids[i % len(job_ids)], resume_id, status),
                )
        conn.commit()


def _promote_applications(user_id: str, job_ids: list[str], status: str) -> None:
    """Move each job's existing ACTIVE application to ``status`` — the way an
    outcome is actually recorded in production (``move_application``), and the
    only way the one-active-application-per-job index permits it."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "Application" SET "status" = %s::"ApplicationStatus",
                    "updatedAt" = NOW()
                WHERE "userId" = %s AND "jobId" = ANY(%s)
                  AND "status"::text = ANY(%s)
                ''',
                (status, user_id, list(job_ids), list(_ACTIVE_STATUSES)),
            )
            assert cur.rowcount == len(job_ids), (
                f"expected one active application per job to promote to "
                f"{status!r}; updated {cur.rowcount} row(s) for "
                f"{len(job_ids)} job(s)"
            )
        conn.commit()


def _pulse(client, auth_headers) -> dict:
    resp = client.get("/analytics/market-pulse", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_1_sourcing_more_jobs_alone_must_not_move_the_headline_score(
    client, auth_headers, user_id
):
    """THE load-bearing assertion. The number of jobs a user's Scout agent
    has saved is a fact about their own board, not about the market or their
    chances — adding 200 more unscored, un-applied-to jobs changes nothing
    about how likely this person is to land an offer, so it must not move
    the score by even one point.

    FAILS TODAY: seeding 3 jobs (2 submitted, 1 interview) then sourcing 200
    more moves ``market_demand_factor`` from ``min(100, round(3/50*100))=6``
    toward a pinned ``100`` (measured before this file's first run), dragging
    the averaged headline up with it even though no new evidence about this
    user's prospects was added.
    """
    jobs = _seed_jobs(user_id, 3)
    _seed_applications(user_id, jobs, ["submitted", "submitted", "interview"])

    before = _pulse(client, auth_headers)["probability"]

    _seed_jobs(user_id, 200)  # one more "Sync Now" — no new applications, no new fit scores

    after = _pulse(client, auth_headers)["probability"]

    assert after["score"] == before["score"], (
        f"sourcing 200 additional jobs moved the headline score "
        f"{before['score']} -> {after['score']} with no new applications or "
        f"fit scores. before_factors={before['factors']} "
        f"after_factors={after['factors']}"
    )
    assert after["factors"] == before["factors"], (
        f"a probability factor changed purely from sourcing more jobs: "
        f"before={before['factors']} after={after['factors']}"
    )


def test_2_headline_does_not_claim_an_offer_likelihood(client, auth_headers, user_id):
    """There is no offer-outcome model and no external market-data provider
    anywhere in this codebase (``_MARKET_DATA_SOURCE_CONNECTED = False``), so
    the surface must not describe its number as the likelihood of landing an
    offer — that framing is what makes a self-referential input inside it
    read as meaningful signal to a user.

    FAILS TODAY: ``note == "Likelihood of landing an offer in the next 60 days"``.
    """
    jobs = _seed_jobs(user_id, 3, fit_score=60)
    _seed_applications(user_id, jobs, ["submitted", "interview"])

    prob = _pulse(client, auth_headers)["probability"]
    headline = f"{prob['label']} {prob['note']}".lower()

    for claim in (
        "likelihood of landing an offer",
        "likelihood of an offer",
        "probability of landing",
        "chance of landing",
    ):
        assert claim not in headline, f"{claim!r} still claimed in {headline!r}"


def test_3_a_genuine_signal_change_still_moves_the_score(client, auth_headers, user_id):
    """Pin, the other direction: the fix must not satisfy this file by
    freezing the score against EVERYTHING. Interview conversion is a real
    signal derived from the user's own outcomes, not from their own job
    count — it must still move the score. Must keep passing after the fix
    (guards against an over-broad "never change" patch).

    The four submitted applications are PROMOTED to interview rather than
    duplicated (WC-INTERVIEW-SEED-001 — see the module docstring): the
    application volume is deliberately left unchanged, so the only thing that
    can move the score here is the genuine interview-conversion signal."""
    jobs = _seed_jobs(user_id, 4, fit_score=50)
    _seed_applications(user_id, jobs, ["submitted", "submitted", "submitted", "submitted"])
    before = _pulse(client, auth_headers)["probability"]

    _promote_applications(user_id, jobs, "interview")
    after = _pulse(client, auth_headers)["probability"]

    assert after["score"] != before["score"], (
        "adding 4 genuine interview outcomes did not move the score at all — "
        f"before={before} after={after}"
    )
