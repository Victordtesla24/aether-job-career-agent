"""CLI — the apply sweep must run its (sync-Playwright) body OFF the event loop.

Root cause of prod's 1-of-687 auto-apply rate: ``apply_sweep_user`` (an async
arq job) called ``sweep_pending_transmissions`` — which drives a real browser
via Playwright's SYNC API — directly on the worker's asyncio loop. The sync API
raises inside a running loop, so every browser submission failed with a bare
``playwright...Error`` surfaced as ``ApplyExecutorTransportError`` ("Could not
open the application page (Error)"). The fix mirrors ``board_sweep_user``:
``await asyncio.to_thread(sweep_pending_transmissions, ...)``.

This pins the invariant directly: the sweep body must observe NO running event
loop (i.e. it runs in a worker thread) — the exact condition Playwright's sync
API requires. Tests wrap the async job with ``asyncio.run`` (the repo's
convention for the arq sweep jobs; pytest-asyncio is not installed).
"""
from __future__ import annotations

import asyncio


def test_apply_sweep_user_runs_body_off_the_event_loop(monkeypatch):
    from app.workers import apply_sweep

    monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")

    seen = {}

    def _fake_sweep(user_id, deadline=None):  # noqa: ANN001
        # Playwright sync API works ONLY where there is no running loop.
        try:
            asyncio.get_running_loop()
            seen["running_loop"] = True
        except RuntimeError:
            seen["running_loop"] = False
        return {"processed": 0, "transmitted": 0, "userId": user_id}

    monkeypatch.setattr(apply_sweep, "sweep_pending_transmissions", _fake_sweep)

    result = asyncio.run(apply_sweep.apply_sweep_user({}, "user-1"))

    assert result["userId"] == "user-1"
    assert seen.get("running_loop") is False, (
        "apply sweep body ran ON the event loop — Playwright's sync browser "
        "API cannot run there; it must be dispatched via asyncio.to_thread"
    )


def test_apply_sweep_user_is_still_an_honest_noop_when_disabled(monkeypatch):
    from app.workers import apply_sweep

    monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)
    called = {"n": 0}
    monkeypatch.setattr(
        apply_sweep,
        "sweep_pending_transmissions",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )
    result = asyncio.run(apply_sweep.apply_sweep_user({}, "user-1"))
    assert result == {"skipped": "disabled", "userId": "user-1"}
    assert called["n"] == 0
