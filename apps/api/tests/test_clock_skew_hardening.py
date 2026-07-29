"""Clock-skew hardening — the two shortlisted items from the 2026-07-29 sweep.

Source: ``uat/reports/evidence/models-live/clock-skew-sweep-2026-07-29.md``
(hosted Postgres observed running ~3s AHEAD of the app server). The sweep found
no HIGH/MED crossings, and shortlisted exactly two cheap hardenings:

1. ``routers/agents.py::_apply_stale_watchdog`` (finding #4) — an age computed
   as ``app_now - DB_anchor`` can go NEGATIVE. Clamp it at zero (never
   ``abs()``, which would make the watchdog fire on a brand-new job).
2. ``repositories/user_provider_credential.py::AgentQuotaBlockRepository``
   (finding #3) — the ONLY finding where write and read clocks are reversed:
   an APP-clock-minted ``expiresAt`` is filtered by ``get_active``'s DB-side
   ``"expiresAt" > now()``. Mint it with ``now() + interval`` instead so both
   sides of that filter run on one clock and the crossing disappears.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import get_connection

# ---------------------------------------------------------------------------
# 1. Stale-job watchdog — negative age clamp (sweep finding #4)
# ---------------------------------------------------------------------------


class TestJobAgeClamp:
    def test_age_is_clamped_to_zero_for_a_future_db_anchor(self):
        """A DB clock running AHEAD of the app clock must not yield a negative age."""
        from app.routers.agents import _job_age_seconds

        future_anchor = datetime.now(timezone.utc) + timedelta(seconds=30)
        assert _job_age_seconds(future_anchor) == 0.0

    def test_age_measures_real_elapsed_time_for_a_past_anchor(self):
        """The clamp must not distort a normal, genuinely-elapsed age."""
        from app.routers.agents import _job_age_seconds

        past_anchor = datetime.now(timezone.utc) - timedelta(seconds=120)
        assert 118.0 <= _job_age_seconds(past_anchor) <= 122.0

    def test_naive_anchor_is_read_as_utc(self):
        """psycopg2 can hand back a naive timestamp — treat it as UTC, as before."""
        from app.routers.agents import _job_age_seconds

        naive_past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=90
        )
        assert 88.0 <= _job_age_seconds(naive_past) <= 92.0


class _RefuseToFailRepo:
    def mark_failed(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError(
            "the watchdog must never fail a job whose anchor is in the future"
        )


class _RecordingRepo:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.refunded: list[str] = []

    def mark_failed(self, job_id: str, _message: str) -> bool:
        self.failed.append(job_id)
        return True

    def refund_single_reservation(self, job_id: str) -> None:
        self.refunded.append(job_id)

    def get_for_user(self, job_id: str, _user_id: str) -> dict:
        return {"id": job_id, "userId": "u1", "status": "failed"}


class TestStaleWatchdogBehaviourUnchanged:
    """Regression pins — these hold before AND after the clamp (the sweep rated
    finding #4 LOW precisely because a negative age is already below every
    staleness limit). They exist so the clamp cannot be "fixed" into an
    ``abs()`` that would make the watchdog fire on brand-new jobs."""

    def test_future_anchored_job_is_never_flagged_stale(self):
        from app.routers.agents import _apply_stale_watchdog

        job = {
            "id": "job-future",
            "userId": "u1",
            "status": "enqueued",
            "createdAt": datetime.now(timezone.utc) + timedelta(seconds=30),
        }
        assert _apply_stale_watchdog(job, _RefuseToFailRepo()) is job

    def test_genuinely_stale_job_is_still_flagged_and_refunded(self):
        from app.routers.agents import _apply_stale_watchdog

        repo = _RecordingRepo()
        job = {
            "id": "job-stale",
            "userId": "u1",
            "status": "enqueued",
            "createdAt": datetime.now(timezone.utc) - timedelta(hours=3),
        }
        out = _apply_stale_watchdog(job, repo)
        assert repo.failed == ["job-stale"]
        assert repo.refunded == ["job-stale"]
        assert out["status"] == "failed"


# ---------------------------------------------------------------------------
# 2. AgentQuotaBlock.expiresAt minted by the DB clock (sweep finding #3)
# ---------------------------------------------------------------------------


def _skewed_now(offset: timedelta):
    """A stand-in app clock, deliberately offset from the DB clock."""

    def _now() -> datetime:
        return datetime.now(timezone.utc) + offset

    return _now


def _stored_remaining_seconds(user_id: str, provider: str) -> float:
    """Lifetime left on the stored block AS THE DATABASE SEES IT."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT EXTRACT(EPOCH FROM ("expiresAt" - now())) '
                'FROM "AgentQuotaBlock" WHERE "userId" = %s AND "provider" = %s',
                (user_id, provider),
            )
            row = cur.fetchone()
    assert row is not None, "no AgentQuotaBlock row was written"
    return float(row[0])


class TestQuotaBlockExpiryUsesTheDbClock:
    @pytest.mark.parametrize("skew_seconds", [45, -45])
    def test_intended_cooldown_survives_an_app_db_clock_offset(
        self, client, test_user_id, monkeypatch, skew_seconds,
    ):
        """The stored expiry must encode the intended DURATION, not an
        app-clock instant that the DB then re-interprets on its own clock.

        ``llm_client._quota_block_expiry`` mints ``app_now + N`` and the row is
        later filtered by ``"expiresAt" > now()`` — the DB's clock. Storing the
        app-clock instant verbatim means the cooldown is silently shortened (DB
        ahead) or lengthened (DB behind) by the full offset. Here the app clock
        is skewed by a large, unmistakable margin so the two implementations
        cannot be confused: storing verbatim yields 60 +/- 45 seconds of real
        cooldown, minting DB-side yields the intended 60 either way.
        """
        import app.repositories.user_provider_credential as upc

        app_now = _skewed_now(timedelta(seconds=skew_seconds))
        monkeypatch.setattr(upc, "_utc_now", app_now, raising=False)

        intended = timedelta(seconds=60)
        upc.AgentQuotaBlockRepository().set_block(
            test_user_id,
            "openrouter",
            # The caller mints the expiry on the SAME skewed app clock, exactly
            # as ``llm_client._quota_block_expiry`` does.
            expires_at=app_now() + intended,
            reason="subscription_quota_exceeded",
        )

        remaining = _stored_remaining_seconds(test_user_id, "openrouter")
        assert 55.0 <= remaining <= 65.0, (
            "the stored expiry must be minted by the DB clock so the intended "
            f"60s cooldown is preserved; got {remaining:.1f}s with a "
            f"{skew_seconds}s app-clock offset"
        )

    def test_active_block_is_still_returned_and_expired_one_is_not(
        self, client, test_user_id,
    ):
        """Regression pin — the read path is unchanged for real callers."""
        from app.repositories.user_provider_credential import (
            AgentQuotaBlockRepository,
        )

        repo = AgentQuotaBlockRepository()
        repo.set_block(
            test_user_id, "anthropic",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
            reason="subscription_quota_exceeded",
        )
        block = repo.get_active(test_user_id, "anthropic")
        assert block is not None
        assert block["reason"] == "subscription_quota_exceeded"
        assert block["expiresAt"] > datetime.now(timezone.utc)

        # An already-past expiry (upsert on the same user+provider) is inactive.
        repo.set_block(
            test_user_id, "anthropic",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            reason="subscription_quota_exceeded",
        )
        assert repo.get_active(test_user_id, "anthropic") is None

    def test_full_length_cooldown_is_preserved(self, client, test_user_id):
        """A real 5-hour block stores ~5 hours of DB-side lifetime."""
        from app.repositories.user_provider_credential import (
            AgentQuotaBlockRepository,
        )

        AgentQuotaBlockRepository().set_block(
            test_user_id, "openrouter",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=5),
            reason="subscription_quota_exceeded",
        )
        remaining = _stored_remaining_seconds(test_user_id, "openrouter")
        assert 17940.0 <= remaining <= 18060.0
