"""CRITICAL-4 — discovery kept re-probing a source that had already refused us.

MEASURED IN PRODUCTION (schema ``aether``, 2026-08-03)
-------------------------------------------------------
``JobSourceStatus`` row::

    source     | status  | lastFetched |          lastSyncAt           | lastError
    wellfound  | blocked |           0 | 2026-08-03 04:36:35.242178+00 | SourceBlockedError:
                                                                        Wellfound public listings
                                                                        unavailable: HTTP Error
                                                                        403: Forbidden

``SELECT count(*) FROM "AgentRun" WHERE "agentName"='scout'`` -> **724 runs**
between 2026-07-21 and 2026-08-03.

``ScoutAgent.run`` loops over ``ADAPTERS`` and calls ``adapter_cls().fetch(...)``
for EVERY source on EVERY run. ``SourceBlockedError`` is caught and disclosed
honestly — but nothing anywhere records that the answer is already known, so
each of those 724 runs opened a fresh HTTPS request to a host that had
explicitly answered ``403 Forbidden`` to this server's IP. That is the third
incident class of this workstream verbatim: an unbounded, non-backing-off
retry against an external dependency. Repeatedly hammering a host that is
already refusing us is how a soft block becomes a hard IP ban, which would
take the source away from every user permanently.

There is a second, quieter dishonesty in the same loop. ``_record_status``
re-stamps ``lastSyncAt = now()`` on every pass, so the Jobs-page Sync Status
panel (apps/web/src/components/dashboard/sourceStatus.ts renders
``relTime(lastSyncAt)``) always read "synced moments ago" for a source that
has produced nothing for days.

WHAT THESE TESTS PIN
--------------------
1. A source whose newest recorded status is ``blocked`` is NOT re-probed while
   the backoff window is open — no ``fetch``, no socket.
2. Skipping does not re-stamp ``lastSyncAt``. This is load-bearing twice over:
   a sliding stamp would keep the window permanently open (the source could
   never be retried at all), and it would keep telling the user we checked
   when we did not.
3. Once the window expires the source IS probed again — exactly once — so a
   block that lifts upstream heals with no code change and no operator action.
4. A healthy source is never skipped.
5. The block is still DISCLOSED on every run (status ``blocked`` + the real
   upstream error), so backing off never becomes hiding.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents import scout_agent as module
from app.repositories.job_source_status import JobSourceStatusRepository
from app.services.discovery.base_adapter import SourceBlockedError

#: The verbatim production error string (see the module docstring).
BLOCK_ERROR = (
    "SourceBlockedError: Wellfound public listings unavailable: "
    "HTTP Error 403: Forbidden"
)


def _uid() -> str:
    return "u" + uuid.uuid4().hex[:24]


@pytest.fixture()
def source() -> str:
    """A source name unique to each test.

    ``JobSourceStatus`` is deliberately absent from the suite's
    ``_TABLES_TO_CLEAN`` (apps/api/tests/conftest.py) — it is an additive,
    lazily-created store with no FK to ``User``. Rows therefore survive
    between tests, and ``latest_block`` is SERVER-WIDE by design, so two tests
    sharing a source name would read each other's rows. Real sources are
    distinct per adapter, so a unique name per test reproduces production
    faithfully rather than papering over the lookup's real semantics.
    """
    return "src_" + uuid.uuid4().hex[:12]


class _JobRepoStub:
    """Minimal ``JobRepository`` surface the scout touches on a blocked run."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    def list_by_user(self, user_id: str) -> list[dict]:
        return []

    def create(self, user_id: str, payload: dict) -> dict:
        self.created.append(payload)
        return {**payload, "wasInserted": True}


def _blocking_adapter(calls: list[str]):
    class _Adapter:
        def fetch(self, query: str, location: str):
            calls.append("fetch")
            raise SourceBlockedError(
                "Wellfound public listings unavailable: HTTP Error 403: Forbidden"
            )

    return _Adapter


def _healthy_adapter(calls: list[str]):
    class _Adapter:
        def fetch(self, query: str, location: str):
            calls.append("fetch")
            return []

    return _Adapter


def _run_scout(user_id: str, adapter, monkeypatch, source: str):
    monkeypatch.setattr(module, "ADAPTERS", {source: adapter})
    return module.ScoutAgent(repository=_JobRepoStub()).run(
        user_id, query="delivery lead", location="Melbourne, Australia"
    )


def _seed_blocked(user_id: str, source: str) -> None:
    JobSourceStatusRepository().upsert(
        user_id, source, fetched=0, persisted=0, error=BLOCK_ERROR, status="blocked"
    )


def _age_status(db_session, user_id: str, source: str, hours: float) -> None:
    """Push a recorded status row ``hours`` into the past, in the DB itself."""
    with db_session.cursor() as cur:
        cur.execute(
            'UPDATE "JobSourceStatus" SET "lastSyncAt" = now() - (%s || \' hours\')'
            '::interval WHERE "userId" = %s AND "source" = %s',
            (str(hours), user_id, source),
        )
    db_session.commit()


def _last_sync_at(db_session, user_id: str, source: str):
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "lastSyncAt" FROM "JobSourceStatus" '
            'WHERE "userId" = %s AND "source" = %s',
            (user_id, source),
        )
        row = cur.fetchone()
    return row[0] if row else None


class TestBlockedSourceBackoff:
    def test_blocked_source_is_not_re_probed_inside_the_window(
        self, client, db_session, monkeypatch, source
    ):
        user_id = _uid()
        _seed_blocked(user_id, source)
        calls: list[str] = []

        result = _run_scout(user_id, _blocking_adapter(calls), monkeypatch, source)

        assert calls == [], (
            "the scout re-opened an HTTP request to a source that already "
            f"answered 403 (calls={calls})"
        )
        # Backing off must never become hiding: the state is still disclosed.
        assert [s["status"] for s in result.per_source] == ["blocked"]
        assert "403" in (result.per_source[0]["error"] or "")

    def test_skipping_does_not_restamp_last_sync_at(
        self, client, db_session, monkeypatch, source
    ):
        user_id = _uid()
        _seed_blocked(user_id, source)
        _age_status(db_session, user_id, source, 2.0)
        before = _last_sync_at(db_session, user_id, source)

        _run_scout(user_id, _blocking_adapter([]), monkeypatch, source)

        after = _last_sync_at(db_session, user_id, source)
        assert after == before, (
            "a skipped check re-stamped lastSyncAt — the backoff window would "
            "slide forever (the source could never be retried) and the Sync "
            "Status panel would claim a check that never happened"
        )

    def test_source_is_probed_again_once_the_window_expires(
        self, client, db_session, monkeypatch, source
    ):
        user_id = _uid()
        _seed_blocked(user_id, source)
        _age_status(
            db_session, user_id, source, module.source_block_backoff_hours() + 1.0
        )
        calls: list[str] = []

        result = _run_scout(user_id, _blocking_adapter(calls), monkeypatch, source)

        assert calls == ["fetch"], "an expired backoff must re-probe exactly once"
        assert result.per_source[0]["status"] == "blocked"
        # The fresh probe DID happen, so this run legitimately re-stamps.
        assert _last_sync_at(db_session, user_id, source) is not None

    def test_healthy_source_is_never_skipped(
        self, client, db_session, monkeypatch, source
    ):
        user_id = _uid()
        JobSourceStatusRepository().upsert(
            user_id, source, fetched=3, persisted=3, error=None, status="ok"
        )
        calls: list[str] = []

        _run_scout(user_id, _healthy_adapter(calls), monkeypatch, source)

        assert calls == ["fetch"]

    def test_first_ever_run_probes_even_with_no_recorded_status(
        self, client, db_session, monkeypatch, source
    ):
        calls: list[str] = []
        _run_scout(_uid(), _healthy_adapter(calls), monkeypatch, source)
        assert calls == ["fetch"]


class TestLatestBlockLookup:
    """``latest_block`` is deliberately SERVER-WIDE, not per-user.

    ``SourceBlockedError`` means "this source refuses automated access from
    this server" (an IP-level 403), so the answer is identical for every user
    and one user's probe is enough for all of them. Scoping the lookup per
    user would multiply the same refused request by the user count.
    """

    def test_returns_the_block_when_it_is_the_newest_row(
        self, client, db_session, source
    ):
        repo = JobSourceStatusRepository()
        repo.upsert(
            _uid(), source, fetched=0, persisted=0,
            error=BLOCK_ERROR, status="blocked",
        )
        block = repo.latest_block(source)
        assert block is not None
        assert block["status"] == "blocked"
        assert block["lastError"] == BLOCK_ERROR
        assert float(block["ageSeconds"]) >= 0.0

    def test_returns_none_when_a_newer_row_is_healthy(
        self, client, db_session, source
    ):
        repo = JobSourceStatusRepository()
        blocked_user, ok_user = _uid(), _uid()
        repo.upsert(
            blocked_user, source, fetched=0, persisted=0,
            error=BLOCK_ERROR, status="blocked",
        )
        _age_status(db_session, blocked_user, source, 1.0)
        repo.upsert(ok_user, source, fetched=5, persisted=5, error=None, status="ok")
        assert repo.latest_block(source) is None

    def test_one_users_block_backs_the_whole_server_off(
        self, client, db_session, monkeypatch, source
    ):
        """The 403 is IP-level, so user B must not repeat user A's refused call."""
        _seed_blocked(_uid(), source)
        calls: list[str] = []
        _run_scout(_uid(), _blocking_adapter(calls), monkeypatch, source)
        assert calls == []

    def test_returns_none_for_an_unknown_source(self, client, db_session, source):
        assert JobSourceStatusRepository().latest_block(source) is None


class TestBackoffWindowConfig:
    def test_window_is_env_tunable_and_floored(self, monkeypatch):
        monkeypatch.setenv("AETHER_DISCOVERY_BLOCK_BACKOFF_HOURS", "12")
        assert module.source_block_backoff_hours() == 12.0
        # A zero/negative/garbage value must not disable the backoff — that
        # would silently restore the 724-request hammering this fixes.
        for bad in ("0", "-5", "abc", ""):
            monkeypatch.setenv("AETHER_DISCOVERY_BLOCK_BACKOFF_HOURS", bad)
            assert module.source_block_backoff_hours() > 0

    def test_default_window(self, monkeypatch):
        monkeypatch.delenv("AETHER_DISCOVERY_BLOCK_BACKOFF_HOURS", raising=False)
        assert module.source_block_backoff_hours() == module.BLOCK_BACKOFF_HOURS


class TestBackoffFailsOpen:
    def test_a_status_store_error_never_stops_discovery(
        self, client, monkeypatch, source
    ):
        """The lookup is an optimisation, not a gate — a blip must not black
        out the user's board."""

        class _ExplodingStatusRepo:
            def latest_block(self, src):
                raise RuntimeError("status store unavailable")

            def upsert(self, *a, **k):
                return {}

        calls: list[str] = []
        monkeypatch.setattr(module, "ADAPTERS", {source: _healthy_adapter(calls)})
        module.ScoutAgent(
            repository=_JobRepoStub(), status_repository=_ExplodingStatusRepo()
        ).run(_uid(), query="delivery lead", location="Melbourne, Australia")
        assert calls == ["fetch"]


@pytest.mark.parametrize("status", ["ok", "error", "skipped"])
def test_non_blocked_statuses_never_trigger_a_backoff(
    client, db_session, monkeypatch, source, status
):
    """Only ``blocked`` backs off.

    An ``error`` is frequently transient (a 500, a timeout) and IS worth
    retrying next run; a ``skipped`` source has no live mode at all and costs
    no request. Widening the backoff to those would stop discovery for
    recoverable reasons.
    """
    user_id = _uid()
    JobSourceStatusRepository().upsert(
        user_id, source, fetched=0, persisted=0,
        error="boom" if status == "error" else None, status=status,
    )
    calls: list[str] = []
    _run_scout(user_id, _healthy_adapter(calls), monkeypatch, source)
    assert calls == ["fetch"]
