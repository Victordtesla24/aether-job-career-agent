"""PROD-UAT-2026-08-03 F-04 — the "Job Probability Score" must not present a
self-referential job count as a market signal, and must not contradict the
"no market data connected" banner rendered on the SAME analytics page.

THE DEFECT (production evidence:
``uat/reports/evidence/prod-uat-2026-08-03/s13-probability-score-inconsistency.json``).
``GET /analytics/market-pulse`` returned a headline "34% — Likelihood of
landing an offer in the next 60 days" whose factor list contained::

    market_demand_factor = min(100, round(sources_total / 50 * 100))

``sources_total`` is ``COUNT(*) FROM "Job" WHERE "userId" = <me>`` — the
user's OWN saved-job count. It is not market data of any kind, it saturates
at a 50-job threshold that a single "Sync Now" blows past (the UAT account
held 1637 jobs), and it was labelled "Market demand" and averaged into the
headline percentage. The SAME response's ``marketVsYou`` panel simultaneously
reports ``marketDataConnected: false`` / "No market data source connected".

The tests below fail against that implementation and pass against an honest
one. They are deliberately written so that most of them cannot be satisfied
by a rename: the load-bearing one asserts that sourcing more jobs cannot move
the score at all.
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
    """Insert ``count`` Job rows (what a "Sync Now" produces). ``fit_score``
    None leaves ``Job.fitScore`` NULL — i.e. never scored."""
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
                VALUES (%s, %s, '{}', 'f04hash', NOW()) RETURNING "id"
                ''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
        conn.commit()
    return str(resume_id)


def _seed_applications(user_id: str, job_ids: list[str], statuses: list[str]) -> None:
    resume_id = _seed_resume(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
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


def _pulse(client, auth_headers) -> dict:
    resp = client.get("/analytics/market-pulse", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestScoreIsNotARestatementOfTheUsersOwnJobCount:
    def test_sourcing_more_jobs_cannot_move_the_headline_score(
        self, client, auth_headers, user_id
    ):
        """THE load-bearing assertion. A rename cannot satisfy this one.

        The number of jobs a user's scout agent saved is a fact about the
        user's own board, not about the market or about their chances. Adding
        200 more unscored, un-applied-to jobs changes nothing whatsoever about
        how likely this person is to land an offer, so it must not change the
        score by a single point.

        BEFORE: ``market_demand_factor`` goes from min(100, 3/50*100)=6 to a
        pinned 100, dragging the averaged headline up with it.
        """
        jobs = _seed_jobs(user_id, 3)
        _seed_applications(user_id, jobs, ["submitted", "submitted", "interview"])

        before = _pulse(client, auth_headers)["probability"]

        _seed_jobs(user_id, 200)  # one "Sync Now"

        after = _pulse(client, auth_headers)["probability"]

        assert after["score"] == before["score"], (
            "Sourcing 200 additional jobs (no new applications, no new fit "
            f"scores) moved the headline score {before['score']} -> "
            f"{after['score']}. The score is restating the user's own job "
            f"count. before_factors={before['factors']} "
            f"after_factors={after['factors']}"
        )
        assert after["factors"] == before["factors"], (
            "A probability factor changed purely because more jobs were "
            f"sourced: before={before['factors']} after={after['factors']}"
        )

    def test_no_factor_claims_market_evidence_while_no_market_source_is_connected(
        self, client, auth_headers, user_id
    ):
        """The same response cannot both claim a "Market demand" input and
        report that no market data source is connected."""
        jobs = _seed_jobs(user_id, 60)
        _seed_applications(user_id, jobs, ["submitted"])

        pulse = _pulse(client, auth_headers)
        prob = pulse["probability"]

        if pulse["marketVsYou"]["marketDataConnected"] is False:
            offenders = [
                f for f in prob["factors"] if "market" in str(f["label"]).lower()
            ]
            assert offenders == [], (
                "The probability panel presents market-evidence factors "
                f"{offenders} on the same response that reports "
                "marketDataConnected=false."
            )
            assert "market" not in str(prob.get("note", "")).lower(), prob.get("note")


class TestScoreAndBannerShareOneSourceOfTruth:
    def test_probability_panel_reports_the_same_market_data_state_as_the_banner(
        self, client, auth_headers, user_id
    ):
        """F-04 item 4: the score panel and the "no market data connected"
        banner must be driven by one flag, so they can never disagree."""
        jobs = _seed_jobs(user_id, 5)
        _seed_applications(user_id, jobs, ["submitted"])

        pulse = _pulse(client, auth_headers)
        assert "marketDataConnected" in pulse["probability"], (
            "probability payload carries no marketDataConnected flag, so the "
            "score panel and the market banner are independent surfaces that "
            "can (and did) contradict each other"
        )
        assert (
            pulse["probability"]["marketDataConnected"]
            is pulse["marketVsYou"]["marketDataConnected"]
        )


class TestZeroEvidenceDegradesInsteadOfScoringZero:
    def test_user_with_no_applications_and_no_fit_scores_gets_no_score(
        self, client, auth_headers, user_id
    ):
        """A brand-new account has nothing to measure. It must degrade to the
        product's established "not measured" state, NOT to a confident 0%
        (which reads as "zero chance") and NOT to an averaged number built
        from empty-basis factors.

        BEFORE: ``measured = [app_volume_factor, market_demand_factor]``
        unconditionally, so an empty account scored a definite 0.
        """
        pulse = _pulse(client, auth_headers)
        prob = pulse["probability"]

        assert prob["measured"] is False, prob
        assert prob["score"] is None, (
            f"empty account was given a definite score of {prob['score']}"
        )
        assert prob.get("unmeasuredReason"), (
            "a not-measured score must say why, like every other degraded "
            "score surface in this product"
        )
        for factor in prob["factors"]:
            assert factor["measured"] is False, factor
            assert factor["value"] is None, factor

    def test_sourcing_jobs_alone_still_produces_no_score(
        self, client, auth_headers, user_id
    ):
        """Clicking "Sync Now" is not evidence about the user's prospects.
        BEFORE: 60 sourced jobs alone produced market_demand=100 and a
        headline of 50%."""
        _seed_jobs(user_id, 60)

        prob = _pulse(client, auth_headers)["probability"]
        assert prob["measured"] is False, prob
        assert prob["score"] is None, (
            f"sourcing 60 jobs — and nothing else — produced a "
            f"{prob['score']}% headline. factors={prob['factors']}"
        )


class TestFactorsCarryTheirOwnProvenance:
    def test_unscored_jobs_make_skill_match_not_measured_rather_than_zero(
        self, client, auth_headers, user_id
    ):
        """BEFORE: with no fit-scored job the payload still shipped
        ``{"label": "Skill match", "value": 0}`` — indistinguishable from a
        genuinely measured zero — while quietly excluding it from the average.
        The wire must state which it is."""
        jobs = _seed_jobs(user_id, 4)  # fitScore NULL
        _seed_applications(user_id, jobs, ["submitted", "submitted"])

        factors = {
            f["label"]: f for f in _pulse(client, auth_headers)["probability"]["factors"]
        }
        skill = factors["Skill match"]
        assert skill["measured"] is False, skill
        assert skill["value"] is None, skill

    def test_scored_jobs_make_skill_match_measured(self, client, auth_headers, user_id):
        jobs = _seed_jobs(user_id, 4, fit_score=72)
        _seed_applications(user_id, jobs, ["submitted", "submitted"])

        factors = {
            f["label"]: f for f in _pulse(client, auth_headers)["probability"]["factors"]
        }
        skill = factors["Skill match"]
        assert skill["measured"] is True, skill
        assert skill["value"] == 72, skill

    def test_measured_zero_interview_conversion_is_still_counted(
        self, client, auth_headers, user_id
    ):
        """Guards the pre-existing rule this fix must not regress: 3
        applications and 0 interviews is a REAL zero and stays in the
        average — only empty-basis factors are excluded."""
        jobs = _seed_jobs(user_id, 3)
        _seed_applications(user_id, jobs, ["submitted", "submitted", "submitted"])

        prob = _pulse(client, auth_headers)["probability"]
        factors = {f["label"]: f for f in prob["factors"]}
        assert factors["Interview conversion"]["measured"] is True
        assert factors["Interview conversion"]["value"] == 0

        measured_values = [f["value"] for f in prob["factors"] if f["measured"]]
        assert 0 in measured_values
        assert prob["score"] == round(sum(measured_values) / len(measured_values)), prob


class TestHeadlineDoesNotClaimAnOfferLikelihood:
    def test_copy_does_not_promise_a_probability_of_an_offer(
        self, client, auth_headers, user_id
    ):
        """There is no offer-outcome model and no market data behind this
        number, so the surface must not describe it as the likelihood of
        landing an offer.

        BEFORE: note == "Likelihood of landing an offer in the next 60 days".
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
        assert "offer" not in prob["label"].lower(), prob["label"]

        # It must instead state what the number is, and say plainly that it is
        # not an offer-likelihood estimate.
        methodology = str(prob["methodology"]).lower()
        assert methodology, prob
        assert "not an offer-likelihood" in methodology, methodology
