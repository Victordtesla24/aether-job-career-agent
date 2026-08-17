"""AUD-META-1 (cohort residual) — the policy-tier cohort widget must not call a
never-transmitted application "submitted".

Ledger requirement: *"Dashboard/Analytics label apps 'submitted/applied' when
not transmitted. FIX: expose a distinct transmitted count; copy 'prepared' vs
'sent'."* CLI-W1-C/D fixed the funnel, conversion, market-pulse and dashboard
surfaces. ``GET /analytics/agent-policy/cohorts`` was the residual: it counted
``status <> 'draft'`` rows as ``submitted`` and divided interviews by that
population, while the very metric it claimed parity with
(``quality_policy.collect_policy_metrics``, already fixed by CLI-QP) counts
ONLY jobs carrying a real ``transmittedAt``. The panel therefore drew two
charts side by side with silently different denominators, and called ~391
never-sent rows "submitted".

What this suite pins:

* The payload exposes ``prepared`` (left draft — preparation) and
  ``transmitted`` (``transmittedAt IS NOT NULL`` — a verified send) as
  DISTINCT counts, per cohort AND for the untagged bucket.
* No key anywhere in the payload is called ``submitted`` — the word is not
  applied to a population that includes never-transmitted rows.
* ``conversionRate`` divides by ``transmitted``, never by ``prepared``, and is
  withheld (``null``) until ``MIN_SAMPLE_SIZE`` VERIFIED sends exist — a tier
  with 12 prepared and 0 sent is not "0% conversion".
* The denominators match ``quality_policy.collect_policy_metrics`` exactly, so
  the two charts in the same panel cannot quote different numbers.

Seeding respects ``Application_user_job_active_key`` (at most ONE active-status
row per (user, job)) — one job per seeded application, as the sibling U-AX
suite does. Run under ``flock /tmp/aether-pytest.lock`` (shared ``aether_test``
schema).
"""
from __future__ import annotations

import json

import pytest

from app.db import get_connection, new_id


def _seed_application(
    user_id: str,
    *,
    tier: str | None,
    status: str = "submitted",
    transmitted: bool = False,
) -> str:
    """One Job + one Application under ``tier``.

    ``transmitted=True`` stamps ``transmittedAt`` — the ONLY evidence in the
    system that something verifiably left the building (it is written solely
    by the real send path, never by a status change).
    """
    from app.db import (
        ensure_application_submission_snapshot_columns,
        ensure_application_transmission_columns,
    )

    ensure_application_submission_snapshot_columns()
    ensure_application_transmission_columns()
    job_id = new_id()
    resume_id = new_id()
    app_id = new_id()
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
            cur.execute(
                '''INSERT INTO "Resume"
                   ("id","userId","version","sections","formatHash","updatedAt")
                   VALUES (%s,%s,1,%s,%s,NOW())''',
                (resume_id, user_id, json.dumps({"raw_text": "Jordan Blake"}), "hash"),
            )
            cur.execute(
                f'''INSERT INTO "Application"
                    ("id","userId","jobId","resumeId","status","createdAt","updatedAt",
                     "policyTierAtSubmission","transmittedAt")
                    VALUES (%s,%s,%s,%s,'{status}'::"ApplicationStatus",NOW(),NOW(),%s,
                            CASE WHEN %s THEN NOW() END)''',
                (app_id, user_id, job_id, resume_id, tier, transmitted),
            )
        conn.commit()
    return app_id


def _cohorts(client, auth_headers) -> dict:
    resp = client.get("/analytics/agent-policy/cohorts", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestCohortPayloadNeverCallsAPhantomSubmitted:
    def test_payload_exposes_prepared_and_transmitted_and_no_submitted_key(
        self, client, auth_headers, test_user_id
    ):
        """The ledger's two halves, on the wire: a DISTINCT transmitted count,
        and the preparation population named ``prepared`` rather than
        ``submitted`` — a word this payload had no evidence for."""
        for _ in range(6):
            _seed_application(test_user_id, tier="standard", transmitted=True)
        for _ in range(4):
            _seed_application(test_user_id, tier="standard", transmitted=False)
        _seed_application(test_user_id, tier=None, transmitted=False)

        body = _cohorts(client, auth_headers)
        cohort = next(c for c in body["cohorts"] if c["tier"] == "standard")
        assert cohort["prepared"] == 10, cohort
        assert cohort["transmitted"] == 6, cohort
        assert "submitted" not in cohort, (
            "a cohort bucket that includes never-transmitted rows may not be "
            f"called 'submitted' (AUD-META-1): {sorted(cohort)}"
        )
        assert "submitted" not in body["untagged"], sorted(body["untagged"])
        assert body["untagged"]["prepared"] == 1
        assert body["untagged"]["transmitted"] == 0

    def test_conversion_rate_divides_by_verified_sends_not_by_prepared(
        self, client, auth_headers, test_user_id
    ):
        """1 interview over 6 verified sends is 16.67%, not 6.25% over 16
        prepared rows — the phantom denominator is exactly the fabrication
        CLI-QP removed from the policy loop."""
        for _ in range(5):
            _seed_application(test_user_id, tier="heightened", transmitted=True)
        _seed_application(
            test_user_id, tier="heightened", status="interview", transmitted=True
        )
        for _ in range(10):
            _seed_application(test_user_id, tier="heightened", transmitted=False)

        cohort = next(
            c for c in _cohorts(client, auth_headers)["cohorts"]
            if c["tier"] == "heightened"
        )
        assert cohort["prepared"] == 16
        assert cohort["transmitted"] == 6
        assert cohort["interviewed"] == 1
        assert cohort["conversionRate"] == pytest.approx(16.67, abs=0.01)
        assert cohort["sufficientSample"] is True
        assert cohort["meetsTarget"] is False
        assert cohort["gapPoints"] == pytest.approx(3.33, abs=0.01)

    def test_a_tier_with_prepared_rows_but_no_verified_send_reports_no_rate(
        self, client, auth_headers, test_user_id
    ):
        """12 prepared applications that never left the building are not "0%
        conversion" — and the tier still appears, with its honest counts,
        rather than being dropped."""
        for _ in range(12):
            _seed_application(test_user_id, tier="standard", transmitted=False)

        cohort = next(
            c for c in _cohorts(client, auth_headers)["cohorts"]
            if c["tier"] == "standard"
        )
        assert cohort["prepared"] == 12
        assert cohort["transmitted"] == 0
        assert cohort["conversionRate"] is None
        assert cohort["sufficientSample"] is False
        assert cohort["meetsTarget"] is None
        assert cohort["gapPoints"] is None

    def test_drafts_count_as_neither_prepared_nor_transmitted(
        self, client, auth_headers, test_user_id
    ):
        _seed_application(test_user_id, tier="heightened", status="draft")
        body = _cohorts(client, auth_headers)
        assert body["cohorts"] == []
        assert body["untagged"]["prepared"] == 0
        assert body["untagged"]["transmitted"] == 0

    def test_denominator_matches_the_policy_metric_drawn_beside_it(
        self, client, auth_headers, test_user_id
    ):
        """The endpoint's docstring claims parity with
        ``quality_policy.collect_policy_metrics``; this pins it. Both charts
        live in the same panel, so a divergence here is two different truths
        on one screen."""
        from app.services.quality_policy import collect_policy_metrics

        for _ in range(7):
            _seed_application(test_user_id, tier="standard", transmitted=True)
        _seed_application(
            test_user_id, tier="standard", status="interview", transmitted=True
        )
        for _ in range(9):
            _seed_application(test_user_id, tier="standard", transmitted=False)

        metrics = collect_policy_metrics(test_user_id)
        cohort = next(
            c for c in _cohorts(client, auth_headers)["cohorts"]
            if c["tier"] == "standard"
        )
        assert metrics["sampleSize"] == cohort["transmitted"] == 8
        assert metrics["interviewCount"] == cohort["interviewed"] == 1
        assert round(metrics["conversionRate"] * 100, 2) == cohort["conversionRate"]


class TestSankeyNeverCallsAPreparedApplicationApplied:
    """The other analytics payload builder that still shipped the word to the
    screen: ``GET /applications/funnel/sankey`` renders SERVER-SUPPLIED node
    labels and insight prose verbatim (``SankeyFlow.tsx``), and labelled its
    left-draft count "Applied" with no transmission evidence behind it.

    Same treatment as the funnel/conversion surfaces: the node keeps its
    ``applied`` KEY (FE stage identity, dropoff wiring), the label tells the
    truth, and the verified-send count travels with the payload.
    """

    def test_stage_label_says_prepared_and_payload_carries_verified_sends(
        self, client, auth_headers, test_user_id
    ):
        for _ in range(3):
            _seed_application(test_user_id, tier=None, transmitted=False)
        _seed_application(test_user_id, tier=None, transmitted=True)

        body = client.get(
            "/applications/funnel/sankey", headers=auth_headers
        ).json()
        stage = next(s for s in body["stages"] if s["key"] == "applied")
        assert stage["value"] == 4, stage
        assert stage["label"] == "Prepared", (
            "an unverified left-draft count may not be labelled 'Applied' "
            f"(AUD-META-1): {stage}"
        )
        assert body["transmitted"] == 1, sorted(body)

    def test_insight_prose_separates_prepared_from_verified_sends(
        self, client, auth_headers, test_user_id
    ):
        for _ in range(3):
            _seed_application(test_user_id, tier=None, transmitted=False)
        _seed_application(test_user_id, tier=None, transmitted=True)

        insight = client.get(
            "/applications/funnel/sankey", headers=auth_headers
        ).json()["insight"]
        assert "4 applications prepared" in insight, insight
        assert "1 verifiably sent" in insight, insight
        assert "4 applied" not in insight, insight


class TestEmployerActivityNeedsTransmissionEvidence:
    """Market Pulse's "Employer activity" feed turned an application STATUS
    into an employer ACTION: a row sitting at ``submitted`` was announced as
    "Received your application" — the employer's receipt asserted from a
    status the user (or an approval) set, with nothing transmitted. Same
    fabrication class as the cohort bucket, one panel over.
    """

    def _events(self, client, auth_headers) -> list[dict]:
        resp = client.get("/analytics/market-pulse", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["employerActivity"]

    def test_receipt_is_claimed_only_with_a_verified_send(
        self, client, auth_headers, test_user_id
    ):
        _seed_application(test_user_id, tier=None, transmitted=True)
        events = self._events(client, auth_headers)
        assert [e["event"] for e in events] == ["Received your application"], events

    def test_a_prepared_application_never_claims_the_employer_received_it(
        self, client, auth_headers, test_user_id
    ):
        _seed_application(test_user_id, tier=None, transmitted=False)
        events = self._events(client, auth_headers)
        assert len(events) == 1, events
        event = events[0]["event"]
        assert "Received your application" not in event, event
        assert "prepared" in event.lower(), event
        assert "aether" in event.lower(), event

    def test_employer_side_outcomes_are_untouched_by_the_transmission_gate(
        self, client, auth_headers, test_user_id
    ):
        """An interview or an offer is an event the employer really produced —
        the user may have applied by hand. Those keep their meaning even with
        no Aether transmission; only the "we sent it / they received it" claim
        needs proof."""
        _seed_application(
            test_user_id, tier=None, status="interview", transmitted=False
        )
        events = self._events(client, auth_headers)
        assert [e["event"] for e in events] == ["Moved you to interview stage"], events


class TestProgressMethodologyDescribesWhatItActuallyCounts:
    """The last surface the AUD-META-1 sweep turned up: the Analytics page's
    "Job Search Progress" panel.

    Its "Application volume" factor is computed from
    ``get_application_counts(...)["total"]`` — EVERY ``Application`` row for
    the user, drafts included and transmission irrelevant — but the
    methodology copy the panel renders (served from the API so the FE cannot
    drift from it) told the reader it measures "applications you have
    submitted". A user whose tracker holds nothing but drafts was therefore
    told the panel was scoring submissions, which is both the wrong word for
    the population AND the exact fabrication class the ledger names.

    The count itself is deliberately unchanged — ``total`` is the honest
    basis for a *volume of work* signal, and narrowing it would silently
    restate a metric six consumers already read. What changes is the copy:
    it now names the population it really counts.
    """

    def _probability(self, client, auth_headers) -> dict:
        resp = client.get("/analytics/market-pulse", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["probability"]

    def test_methodology_never_calls_the_volume_basis_submitted(
        self, client, auth_headers, test_user_id
    ):
        """Two drafts and one never-transmitted row: nothing here was sent,
        so no copy on this panel may say the score measures submissions."""
        _seed_application(test_user_id, tier=None, status="draft")
        _seed_application(test_user_id, tier=None, status="draft")
        _seed_application(test_user_id, tier=None, status="submitted", transmitted=False)

        methodology = self._probability(client, auth_headers)["methodology"]
        lowered = methodology.lower()
        assert "you have submitted" not in lowered, methodology
        assert "applications you have sent" not in lowered, methodology
        assert "applied" not in lowered, methodology

    def test_methodology_names_the_population_the_volume_factor_counts(
        self, client, auth_headers, test_user_id
    ):
        """Positive half — the copy must still SAY what the factor measures,
        not merely drop the false word: every application in the tracker,
        drafts explicitly included."""
        _seed_application(test_user_id, tier=None, status="draft")

        methodology = self._probability(client, auth_headers)["methodology"].lower()
        assert "drafts included" in methodology, methodology
        assert "tracker" in methodology, methodology

    def test_the_volume_factor_itself_is_unchanged_by_the_copy_fix(
        self, client, auth_headers, test_user_id
    ):
        """Guard against a copy fix quietly becoming a metric change: the
        factor still scores every application row (3 of the 30-application
        reference == 10), drafts included, exactly as before."""
        _seed_application(test_user_id, tier=None, status="draft")
        _seed_application(test_user_id, tier=None, status="draft")
        _seed_application(test_user_id, tier=None, status="submitted", transmitted=False)

        factors = self._probability(client, auth_headers)["factors"]
        volume = next(f for f in factors if f["label"] == "Application volume")
        assert volume["value"] == 10, volume
        assert volume["measured"] is True, volume
