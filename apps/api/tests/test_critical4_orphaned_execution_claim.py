"""CRITICAL-4 — an approval could be burnt "executed" by work that never ran.

THE MECHANISM (read out of the shipped code, not hypothesised)
--------------------------------------------------------------
``POST /approvals/{id}/execute`` claims the approved request by stamping
``executedAt = NOW()`` BEFORE the side-effect runs
(``ApprovalRepository.claim_execution`` — a deliberate at-most-once guard so a
double-submit cannot fire two real Gmail sends), then either succeeds or
releases the claim in an ``except``.

An ``except`` only runs if the process is alive to run it. ``aether-api`` is a
synchronous FastAPI service under ``Restart=on-failure`` that is restarted on
every deploy, and the claimed section performs multi-second network I/O (PDF
rendering + a Gmail send). A restart, an OOM kill or a SIGKILL in that window
leaves ``executedAt`` stamped with nothing sent — and NOTHING anywhere
reconciles it. Exactly the shape of the 8-day zombie ``AgentRun``: state that
survives every restart forever because no code path revisits it.

The consequences were not cosmetic:

* the row is indistinguishable from a genuine send, so a retry answers
  409 "Approval already executed — no action taken." — the approval is burnt
  and the user's application is never sent, silently;
* ``NotificationAgent._watermark`` advances the digest window on
  ``ar."executedAt" IS NOT NULL``. An interrupted digest send therefore
  suppressed every status update and new match inside that window from every
  future digest — real notification data loss, with no way to notice.

WHAT THIS FIX DOES — AND DELIBERATELY DOES NOT DO
-------------------------------------------------
``executedAt`` now means "claimed"; the new ``executionCompletedAt`` means
"the side-effect provably finished". The two together make an interrupted
execution a distinguishable, visible state instead of a silent lie.

It does NOT auto-release an interrupted claim, and the tests below pin that
refusal. The process could have died AFTER Gmail accepted the message and
BEFORE the stamp; releasing on that evidence would send a second real
application email to a real employer. There is no evidence in the system that
can tell those two cases apart, so the honest product behaviour is to say the
outcome is UNKNOWN and let the human — who can look in their Sent folder —
decide. Stated plainly rather than half-implemented.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_connection
from app.repositories.approval import (
    EXECUTION_STATE_EXECUTED,
    EXECUTION_STATE_INTERRUPTED,
    EXECUTION_STATE_RUNNING,
    ApprovalRepository,
    execution_state,
    max_execution_seconds,
)


def _create_approved(user_id: str) -> str:
    repo = ApprovalRepository()
    row = repo.create(
        user_id=user_id,
        type_="email_send",
        payload={"to": "someone@example.com", "subject": "s", "body": "b"},
    )
    assert repo.approve(row["id"], user_id) is not None
    return row["id"]


def _age_claim(approval_id: str, seconds: float) -> None:
    """Push an existing ``executedAt`` claim ``seconds`` into the past."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "ApprovalRequest" '
                'SET "executedAt" = "executedAt" - (%s || \' seconds\')::interval '
                'WHERE "id" = %s',
                (str(seconds), approval_id),
            )
        conn.commit()


def _row(approval_id: str, user_id: str) -> dict:
    row = ApprovalRepository().get_by_id(approval_id, user_id)
    assert row is not None
    return row


class TestExecutionStateIsHonest:
    def test_an_unclaimed_approval_has_no_execution_state(
        self, client, test_user_id
    ):
        approval_id = _create_approved(test_user_id)
        assert execution_state(_row(approval_id, test_user_id)) is None

    def test_a_fresh_claim_reads_running_not_executed(self, client, test_user_id):
        approval_id = _create_approved(test_user_id)
        assert ApprovalRepository().claim_execution(approval_id, test_user_id)
        assert execution_state(_row(approval_id, test_user_id)) == (
            EXECUTION_STATE_RUNNING
        )

    def test_a_claim_older_than_the_ceiling_reads_interrupted(
        self, client, test_user_id
    ):
        approval_id = _create_approved(test_user_id)
        assert ApprovalRepository().claim_execution(approval_id, test_user_id)
        _age_claim(approval_id, max_execution_seconds() + 60)
        assert execution_state(_row(approval_id, test_user_id)) == (
            EXECUTION_STATE_INTERRUPTED
        )

    def test_a_completed_execution_reads_executed_at_any_age(
        self, client, test_user_id
    ):
        repo = ApprovalRepository()
        approval_id = _create_approved(test_user_id)
        assert repo.claim_execution(approval_id, test_user_id)
        assert repo.complete_execution(approval_id, test_user_id)
        _age_claim(approval_id, max_execution_seconds() * 10)
        assert execution_state(_row(approval_id, test_user_id)) == (
            EXECUTION_STATE_EXECUTED
        )

    def test_completing_without_a_claim_is_refused(self, client, test_user_id):
        """``executionCompletedAt`` can never precede the claim that authorises it."""
        approval_id = _create_approved(test_user_id)
        assert ApprovalRepository().complete_execution(approval_id, test_user_id) is (
            False
        )
        assert _row(approval_id, test_user_id)["executionCompletedAt"] is None

    def test_release_clears_both_stamps(self, client, test_user_id):
        repo = ApprovalRepository()
        approval_id = _create_approved(test_user_id)
        assert repo.claim_execution(approval_id, test_user_id)
        repo.release_execution(approval_id, test_user_id)
        row = _row(approval_id, test_user_id)
        assert row["executedAt"] is None
        assert row["executionCompletedAt"] is None
        # Released => claimable again, which is the whole point of releasing.
        assert repo.claim_execution(approval_id, test_user_id)


class TestInterruptedClaimsAreSurfaced:
    def test_interrupted_claims_are_listed(self, client, test_user_id):
        repo = ApprovalRepository()
        interrupted = _create_approved(test_user_id)
        assert repo.claim_execution(interrupted, test_user_id)
        _age_claim(interrupted, max_execution_seconds() + 60)

        fresh = _create_approved(test_user_id)
        assert repo.claim_execution(fresh, test_user_id)

        done = _create_approved(test_user_id)
        assert repo.claim_execution(done, test_user_id)
        assert repo.complete_execution(done, test_user_id)
        _age_claim(done, max_execution_seconds() + 60)

        ids = {r["id"] for r in repo.list_interrupted_executions()}
        assert interrupted in ids
        assert fresh not in ids, "a claim still inside the ceiling is not orphaned"
        assert done not in ids, "a completed execution is never orphaned"

    def test_reporting_never_releases_the_claim(self, client, test_user_id):
        """NO AUTO-RETRY. See the module docstring: the process may have died
        after Gmail accepted the message, and re-executing would send a second
        real application email to a real employer."""
        repo = ApprovalRepository()
        approval_id = _create_approved(test_user_id)
        assert repo.claim_execution(approval_id, test_user_id)
        _age_claim(approval_id, max_execution_seconds() + 60)
        before = _row(approval_id, test_user_id)["executedAt"]

        outcome = repo.report_interrupted_executions()

        assert outcome["interrupted"] == 1
        after = _row(approval_id, test_user_id)
        assert after["executedAt"] == before, "an interrupted claim must NOT be released"
        assert after["executionCompletedAt"] is None
        assert execution_state(after) == EXECUTION_STATE_INTERRUPTED

    def test_the_api_row_exposes_the_state(self, client, auth_headers, test_user_id):
        approval_id = _create_approved(test_user_id)
        assert ApprovalRepository().claim_execution(approval_id, test_user_id)
        _age_claim(approval_id, max_execution_seconds() + 60)

        body = client.get(f"/approvals/{approval_id}", headers=auth_headers).json()
        assert body["executionState"] == EXECUTION_STATE_INTERRUPTED
        assert body["executedAt"] is not None
        assert body["executionCompletedAt"] is None


class TestDigestWatermarkNeedsProof:
    """The digest window may only advance on a send that provably happened.

    ``NotificationAgent._watermark`` keyed on ``executedAt IS NOT NULL``, so an
    interrupted claim advanced the window and permanently suppressed every
    status update and new match inside it — notification data loss the user
    could never detect.
    """

    def _seed_digest(self, user_id: str, approval_id: str, window_end: datetime):
        from app.agents.notification_agent import ensure_notification_digest_table
        from app.db import new_id

        ensure_notification_digest_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'INSERT INTO "NotificationDigest"'
                    ' ("id","userId","approvalId","windowStart","windowEnd",'
                    '  "statusUpdates","newMatches")'
                    " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        new_id(), user_id, approval_id,
                        window_end - timedelta(hours=1), window_end, 1, 1,
                    ),
                )
            conn.commit()

    def test_an_interrupted_send_does_not_advance_the_window(
        self, client, test_user_id
    ):
        from app.agents.notification_agent import NotificationAgent

        repo = ApprovalRepository()
        approval_id = _create_approved(test_user_id)
        assert repo.claim_execution(approval_id, test_user_id)
        _age_claim(approval_id, max_execution_seconds() + 60)
        self._seed_digest(
            test_user_id, approval_id, datetime.now(timezone.utc) - timedelta(hours=2)
        )

        assert NotificationAgent()._watermark(test_user_id) is None, (
            "an execution that never completed advanced the digest watermark — "
            "every update inside that window is suppressed forever"
        )

    def test_a_completed_send_does_advance_the_window(self, client, test_user_id):
        from app.agents.notification_agent import NotificationAgent

        repo = ApprovalRepository()
        approval_id = _create_approved(test_user_id)
        assert repo.claim_execution(approval_id, test_user_id)
        assert repo.complete_execution(approval_id, test_user_id)
        window_end = datetime.now(timezone.utc) - timedelta(hours=2)
        self._seed_digest(test_user_id, approval_id, window_end)

        watermark = NotificationAgent()._watermark(test_user_id)
        assert watermark is not None


class TestMaxExecutionSecondsConfig:
    def test_env_tunable_with_a_floor(self, monkeypatch):
        monkeypatch.setenv("AETHER_APPROVAL_MAX_EXECUTION_SECONDS", "900")
        assert max_execution_seconds() == 900.0
        # A too-small ceiling would declare a live, legitimately slow send
        # (PDF rendering + a Gmail upload) "interrupted" while it is still
        # running, so the value is floored rather than trusted.
        for bad in ("1", "0", "-30", "abc", ""):
            monkeypatch.setenv("AETHER_APPROVAL_MAX_EXECUTION_SECONDS", bad)
            assert max_execution_seconds() >= 300.0


@pytest.mark.parametrize("stamp", [None, ""])
def test_execution_state_tolerates_a_row_without_the_columns(stamp):
    """Callers holding a legacy row (selected before these columns existed)
    must degrade to "unknown", never raise into an approvals response."""
    assert execution_state({"executedAt": stamp}) is None
