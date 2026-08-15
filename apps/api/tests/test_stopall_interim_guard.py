"""INTERIM Stop-All guard at ``_dispatch`` (SEV-1 2026-08-14).

The owner pressed "Stop All Agents" at 12:31Z; all 22 ``AgentConfig`` rows read
``enabled = false``, yet the board sweep dispatched 168 runs ($1.91) over the
following nine hours because NO dispatch path read the flag. These tests pin
the interim chokepoint guard: a paused agent is refused at ``_dispatch`` BEFORE
any side effect (no ``AgentRun`` row, no quota reserve, nothing to refund).

Superseded by ML-STOPALL-001 (permanent enforcement at
``_execute_reserved_run``) — these tests pin the same agreed semantics so the
behaviour does not flip when it lands: absent row = enabled; a backend shared
by several UI cards (``fitScorer`` has three) is paused only when EVERY card is
disabled; a read error fails open.
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

import app.routers.agents as agents


class _Cur:
    def __init__(self, rows: list[tuple[str, bool]]):
        self._rows = rows
        self.queried_keys: list[str] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, _sql: str, params: tuple[Any, ...]) -> None:
        self.queried_keys = list(params[1])

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows: list[tuple[str, bool]]):
        self._cur = _Cur(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cur


def _with_rows(monkeypatch: Any, rows: list[tuple[str, bool]]) -> None:
    monkeypatch.setattr(agents, "get_connection", lambda: _Conn(rows))


class TestPausedResolution:
    def test_stop_all_pauses_a_single_card_backend(self, monkeypatch: Any) -> None:
        _with_rows(monkeypatch, [("resumeTailoring", False)])
        assert agents._agent_paused_by_user("u1", "tailor") is True

    def test_stop_all_pauses_a_shared_backend_when_all_cards_disabled(
        self, monkeypatch: Any
    ) -> None:
        _with_rows(
            monkeypatch,
            [("atsOptimization", False), ("matchScoring", False), ("skillGap", False)],
        )
        assert agents._agent_paused_by_user("u1", "fitScorer") is True

    def test_one_enabled_card_keeps_a_shared_backend_running(
        self, monkeypatch: Any
    ) -> None:
        # The user stopped two of the three fitScorer cards but deliberately
        # left Match Scoring on — the backend must still run for it.
        _with_rows(
            monkeypatch,
            [("atsOptimization", False), ("matchScoring", True), ("skillGap", False)],
        )
        assert agents._agent_paused_by_user("u1", "fitScorer") is False

    def test_absent_rows_default_to_enabled(self, monkeypatch: Any) -> None:
        _with_rows(monkeypatch, [])
        assert agents._agent_paused_by_user("u1", "tailor") is False

    def test_partially_absent_rows_default_to_enabled(self, monkeypatch: Any) -> None:
        # Only one of the three fitScorer cards has a row (disabled): the other
        # two default to enabled, so the backend is not paused.
        _with_rows(monkeypatch, [("skillGap", False)])
        assert agents._agent_paused_by_user("u1", "fitScorer") is False

    def test_read_error_fails_open(self, monkeypatch: Any) -> None:
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(agents, "get_connection", _boom)
        assert agents._agent_paused_by_user("u1", "tailor") is False

    def test_unknown_backend_is_never_paused(self, monkeypatch: Any) -> None:
        _with_rows(monkeypatch, [])
        assert agents._agent_paused_by_user("u1", "no-such-backend") is False


class TestDispatchRefusal:
    def test_paused_agent_is_refused_before_any_side_effect(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(agents, "_agent_paused_by_user", lambda *_: True)

        def _must_not_run(*_a: Any, **_k: Any) -> None:
            raise AssertionError("side effect reached despite paused agent")

        monkeypatch.setattr(agents, "_with_quality_policy", _must_not_run)
        monkeypatch.setattr(agents, "_agent_callable", _must_not_run)
        monkeypatch.setattr(agents, "_record_run", _must_not_run)

        with pytest.raises(HTTPException) as exc:
            agents._dispatch("u1", "coverLetter", {}, system_run=True, skip_quota=True)
        assert exc.value.status_code == 409
        assert str(exc.value.detail).startswith("agent_paused")

    def test_enabled_agent_dispatches_normally(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(agents, "_agent_paused_by_user", lambda *_: False)
        monkeypatch.setattr(
            agents, "_with_quality_policy", lambda _u, p, **_k: p
        )
        monkeypatch.setattr(
            agents, "_agent_callable", lambda _u, n, _p: (n, lambda: None)
        )
        sentinel = {"ok": True}
        monkeypatch.setattr(agents, "_record_run", lambda *_a, **_k: sentinel)
        assert agents._dispatch("u1", "tailor", {}) is sentinel


class TestAsyncEnqueueSeamRefusal:
    """The async seam (GAP-P7-ASYNC-001) bypasses ``_dispatch`` — the worker
    body calls ``_execute_reserved_run`` directly — so the guard must ALSO sit
    at ``_enqueue_single_agent``. Proven live 21:56Z: with the _dispatch-only
    guard deployed and every AgentConfig row disabled, POST /agents/tailor/run
    (async, AETHER_ASYNC_GENERATION=true in prod) still enqueued, executed
    221s on the worker and billed $0.048.
    """

    def test_paused_agent_is_refused_before_paywall_reserve_or_queue(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(agents, "_agent_paused_by_user", lambda *_: True)

        def _must_not_run(*_a: Any, **_k: Any) -> None:
            raise AssertionError("async seam side effect reached despite pause")

        for seam in (
            "_require_active_subscription",
            "_with_quality_policy",
            "_billing_audit",
        ):
            monkeypatch.setattr(agents, seam, _must_not_run)

        with pytest.raises(HTTPException) as exc:
            agents._enqueue_single_agent("u1", "tailor", {"job_id": "j1"})
        assert exc.value.status_code == 409
        assert str(exc.value.detail).startswith("agent_paused")

    def test_enabled_agent_passes_the_guard_into_the_seam(
        self, monkeypatch: Any
    ) -> None:
        monkeypatch.setattr(agents, "_agent_paused_by_user", lambda *_: False)

        class _ReachedPaywall(Exception):
            pass

        def _paywall_probe(*_a: Any, **_k: Any) -> None:
            raise _ReachedPaywall

        monkeypatch.setattr(agents, "_require_active_subscription", _paywall_probe)
        with pytest.raises(_ReachedPaywall):
            agents._enqueue_single_agent("u1", "tailor", {"job_id": "j1"})
