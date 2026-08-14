"""U-AX round-3 — the two undelivered spec surfaces (R-06).

U-PLAN.md "U-AX BUILD SPEC ADDITIONS":

* item 2(c) — "**trend of policy tier over time vs the metrics it responds
  to**". Round 2 shipped only the CURRENT tier (``GET /analytics/agent-policy``)
  while the panel's own comment claimed to cover 2(c). This file pins the real
  surface: ``GET /analytics/agent-policy/history``, derived from the already-
  instrumented ``AgentRun.policyTier`` + ``AgentRun.metricSnapshot`` columns —
  no new write path, no back-stamping of runs that predate the loop.
* item 3 — "**interview-conversion threshold progress visible per cohort
  (applications under each policy tier)**". ``Application.policyTierAtSubmission``
  was write-only after round 2 (nothing read it). This file pins
  ``GET /analytics/agent-policy/cohorts``.

HONESTY CONTRACT (what makes these surfaces worth shipping):

* A tier the loop never recorded is never invented. Runs with ``policyTier``
  NULL (every run predating the instrumentation) are EXCLUDED and counted, not
  back-filled.
* A cohort whose sample is below ``quality_policy.MIN_SAMPLE_SIZE`` reports
  ``conversionRate: null`` — the raw counts are shown instead. A 0/1 cohort is
  not "0% conversion"; it is one application.
* Applications submitted before the policy existed form their own explicitly
  labelled ``untagged`` bucket rather than being folded into a real tier.

Run under ``flock /tmp/aether-pytest.lock`` (shared ``aether_test`` schema).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_connection, new_id


def _seed_job(user_id: str) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","fitScore","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (
                    job_id, user_id, "Delivery Lead", "ExampleCorp", "Melbourne VIC",
                    False, "Own delivery of the platform program.", json.dumps([]),
                    "greenhouse", f"https://example.com/{job_id}", 71.0,
                ),
            )
        conn.commit()
    return job_id


def _seed_agent_run(
    user_id: str,
    *,
    tier: str | None,
    conversion: float,
    sample_size: int,
    triggers: list[str] | None = None,
    created_at: datetime,
) -> str:
    """One historical AgentRun carrying the policy it obeyed, exactly as
    ``AgentRunRepository.start`` records it."""
    from app.repositories.agent_run import (
        ensure_agent_run_link_columns,
        ensure_agent_run_policy_columns,
    )

    ensure_agent_run_link_columns()
    ensure_agent_run_policy_columns()
    run_id = new_id()
    snapshot = (
        None
        if tier is None
        else {
            "tier": tier,
            "triggers": triggers or [],
            "knobs": {"maxIterations": 5, "targetScore": 85.0, "coverLetterRetries": 2},
            "metrics": {
                "available": True,
                "sampleSize": sample_size,
                "conversionRate": conversion,
                "interviewCount": int(round(conversion * sample_size)),
                "dimensionScores": {"cultureFit": 72.5},
                "dimensionSampleSize": sample_size,
            },
            "thresholds": {
                "interviewConversionTarget": 0.20,
                "dimensionFloor": 80.0,
                "minSampleSize": 5,
            },
        }
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "AgentRun"
                   ("id","userId","agentName","status","input","createdAt",
                    "startedAt","policyTier","metricSnapshot")
                   VALUES (%s,%s,%s,'completed'::"AgentRunStatus",%s,%s,%s,%s,%s)''',
                (
                    run_id, user_id, "tailor", json.dumps({"job_id": "x"}),
                    created_at, created_at, tier,
                    json.dumps(snapshot) if snapshot else None,
                ),
            )
        conn.commit()
    return run_id


def _seed_resume(user_id: str) -> str:
    resume_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","updatedAt")
                   VALUES (%s,%s,1,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake"}), "hash"),
            )
        conn.commit()
    return resume_id


def _seed_submitted_application(
    user_id: str, *, tier: str | None, status: str = "submitted"
) -> str:
    from app.db import ensure_application_submission_snapshot_columns

    ensure_application_submission_snapshot_columns()
    job_id = _seed_job(user_id)
    resume_id = _seed_resume(user_id)
    app_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'''INSERT INTO "Application"
                    ("id","userId","jobId","resumeId","status","createdAt","updatedAt",
                     "policyTierAtSubmission")
                    VALUES (%s,%s,%s,%s,'{status}'::"ApplicationStatus",NOW(),NOW(),%s)''',
                (app_id, user_id, job_id, resume_id, tier),
            )
        conn.commit()
    return app_id


def _t(minutes_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)


class TestPolicyTierHistoryEndpoint:
    """U-AX item 2(c) — tier over time vs the metrics it responds to."""

    def test_requires_authentication(self, client):
        assert client.get("/analytics/agent-policy/history").status_code == 401

    def test_honest_empty_state_when_no_run_ever_recorded_a_tier(
        self, client, auth_headers, test_user_id
    ):
        _seed_agent_run(
            test_user_id, tier=None, conversion=0.0, sample_size=0, created_at=_t(60)
        )
        resp = client.get("/analytics/agent-policy/history", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["points"] == []
        assert body["available"] is False
        assert body["reason"]
        # The un-instrumented runs are COUNTED, not silently dropped.
        assert body["runsWithoutPolicy"] == 1

    def test_points_carry_the_tier_and_the_metrics_that_forced_it(
        self, client, auth_headers, test_user_id
    ):
        _seed_agent_run(
            test_user_id, tier="heightened", conversion=0.0, sample_size=40,
            triggers=["interview conversion 0.0% is below the 20% target"],
            created_at=_t(30),
        )
        body = client.get(
            "/analytics/agent-policy/history", headers=auth_headers
        ).json()
        assert body["available"] is True
        assert len(body["points"]) == 1
        point = body["points"][0]
        assert point["tier"] == "heightened"
        # Percent for display, matching GET /analytics/agent-policy.
        assert point["conversionRate"] == 0.0
        assert point["sampleSize"] == 40
        assert point["triggers"] == [
            "interview conversion 0.0% is below the 20% target"
        ]
        assert point["at"]

    def test_points_are_chronological_and_collapse_unchanged_repeats(
        self, client, auth_headers, test_user_id
    ):
        """A user who runs the tailor 30 times under one unchanged tier must not
        get 30 identical 'trend' points — that is noise, not a trend. Repeats
        collapse into one point that reports how many runs it covers."""
        _seed_agent_run(
            test_user_id, tier="insufficient_data", conversion=0.0, sample_size=2,
            created_at=_t(90),
        )
        _seed_agent_run(
            test_user_id, tier="heightened", conversion=0.0, sample_size=40,
            created_at=_t(60),
        )
        _seed_agent_run(
            test_user_id, tier="heightened", conversion=0.0, sample_size=40,
            created_at=_t(50),
        )
        _seed_agent_run(
            test_user_id, tier="heightened", conversion=0.10, sample_size=50,
            created_at=_t(20),
        )
        body = client.get(
            "/analytics/agent-policy/history", headers=auth_headers
        ).json()
        tiers = [p["tier"] for p in body["points"]]
        assert tiers == ["insufficient_data", "heightened", "heightened"]
        assert [p["runs"] for p in body["points"]] == [1, 2, 1]
        ats = [p["at"] for p in body["points"]]
        assert ats == sorted(ats), "oldest first — a trend reads forwards in time"
        assert body["points"][-1]["conversionRate"] == 10.0

    def test_thresholds_travel_with_the_series(
        self, client, auth_headers, test_user_id
    ):
        """The metrics are only legible against the targets they are judged by."""
        _seed_agent_run(
            test_user_id, tier="standard", conversion=0.25, sample_size=20,
            created_at=_t(10),
        )
        body = client.get(
            "/analytics/agent-policy/history", headers=auth_headers
        ).json()
        assert body["thresholds"]["interviewConversionTarget"] == 20.0
        assert body["thresholds"]["dimensionFloor"] == 80.0
        assert body["thresholds"]["minSampleSize"] == 5


class TestPolicyCohortEndpoint:
    """U-AX item 3 — interview-conversion progress per policy-tier cohort,
    reading the previously write-only ``Application.policyTierAtSubmission``."""

    def test_requires_authentication(self, client):
        assert client.get("/analytics/agent-policy/cohorts").status_code == 401

    def test_groups_applications_by_the_tier_they_were_submitted_under(
        self, client, auth_headers, test_user_id
    ):
        for _ in range(5):
            _seed_submitted_application(test_user_id, tier="standard")
        _seed_submitted_application(test_user_id, tier="standard", status="interview")
        for _ in range(6):
            _seed_submitted_application(test_user_id, tier="heightened")

        resp = client.get("/analytics/agent-policy/cohorts", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        by_tier = {c["tier"]: c for c in body["cohorts"]}
        assert by_tier["standard"]["submitted"] == 6
        assert by_tier["standard"]["interviewed"] == 1
        assert by_tier["standard"]["conversionRate"] == pytest.approx(16.67, abs=0.01)
        assert by_tier["standard"]["meetsTarget"] is False
        assert by_tier["heightened"]["submitted"] == 6
        assert by_tier["heightened"]["interviewed"] == 0
        assert by_tier["heightened"]["conversionRate"] == 0.0

    def test_a_cohort_below_the_minimum_sample_withholds_the_rate(
        self, client, auth_headers, test_user_id
    ):
        """1 application is not a 0% conversion rate — it is one application."""
        _seed_submitted_application(test_user_id, tier="heightened")

        body = client.get(
            "/analytics/agent-policy/cohorts", headers=auth_headers
        ).json()
        cohort = next(c for c in body["cohorts"] if c["tier"] == "heightened")
        assert cohort["submitted"] == 1
        assert cohort["sufficientSample"] is False
        assert cohort["conversionRate"] is None
        assert cohort["meetsTarget"] is None

    def test_pre_instrumentation_applications_are_their_own_labelled_bucket(
        self, client, auth_headers, test_user_id
    ):
        """Folding them into a real tier would attribute outcomes to a policy
        that was not running when they were sent."""
        for _ in range(3):
            _seed_submitted_application(test_user_id, tier=None)
        for _ in range(5):
            _seed_submitted_application(test_user_id, tier="heightened")

        body = client.get(
            "/analytics/agent-policy/cohorts", headers=auth_headers
        ).json()
        assert {c["tier"] for c in body["cohorts"]} == {"heightened"}
        assert body["untagged"]["submitted"] == 3
        assert body["untagged"]["reason"]

    def test_drafts_are_not_counted_as_submitted(
        self, client, auth_headers, test_user_id
    ):
        _seed_submitted_application(test_user_id, tier="heightened", status="draft")
        body = client.get(
            "/analytics/agent-policy/cohorts", headers=auth_headers
        ).json()
        assert body["cohorts"] == []
        assert body["untagged"]["submitted"] == 0

    def test_target_and_gap_are_stated_so_the_number_is_actionable(
        self, client, auth_headers, test_user_id
    ):
        for _ in range(10):
            _seed_submitted_application(test_user_id, tier="heightened")
        _seed_submitted_application(test_user_id, tier="heightened", status="offer")

        body = client.get(
            "/analytics/agent-policy/cohorts", headers=auth_headers
        ).json()
        assert body["target"] == 20.0
        assert body["minSampleSize"] == 5
        cohort = next(c for c in body["cohorts"] if c["tier"] == "heightened")
        # offer counts as an interview reached, same semantics as
        # quality_policy.collect_policy_metrics / analytics conversion.
        assert cohort["interviewed"] == 1
        assert cohort["conversionRate"] == pytest.approx(9.09, abs=0.01)
        assert cohort["gapPoints"] == pytest.approx(10.91, abs=0.01)
