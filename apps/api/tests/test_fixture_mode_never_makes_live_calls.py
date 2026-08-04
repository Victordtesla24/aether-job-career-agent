"""Fixture mode must be ABSOLUTE — a missing fixture may never become a live call.

``tests/conftest.py`` sets ``AETHER_DISCOVERY_FIXTURE_DIR`` at import time, and
``app.main._guard_production_discovery_fixtures`` prints, on every suite start,
that "job-board discovery adapters will serve canned HTTP fixtures instead of
making live calls" (§REC-05). ``base_adapter``'s own module docstring makes the
same promise: fixture mode does "No network I/O".

That promise was not kept. ``BaseAdapter._resolve_payload`` fell through to
``_fetch_live`` whenever the source had no recorded payload, so the v5
SmartRecruiters adapter — registered as a live source but shipped without a
fixture — issued real ``api.smartrecruiters.com`` list + detail GETs on every
scout run in the suite. Measured 2026-08-04 before the fix: 13 live boards, 352
live postings, 120 live detail GETs per call, ~14s of wall clock, and a board
whose contents (and therefore whose fit scores and swimlane statuses) changed
with a third party's data and a randomised per-sweep detail budget.

Two guards here:

1. the fall-through itself is gone — a missing fixture raises, loudly and by
   name, and ``_fetch_live`` is never reached;
2. every source in the live adapter registry actually HAS a recorded fixture,
   so the next adapter to be registered without one fails here instead of
   silently joining the suite over the network.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app.services.discovery.adapter_registry import build_live_registry
from app.services.discovery.base_adapter import AdapterFetchError, BaseAdapter, JobRaw

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "http"


class _NeverLiveAdapter(BaseAdapter):
    """An adapter whose live path is a test failure if it is ever reached."""

    source = "source-with-no-recorded-fixture"

    def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:  # pragma: no cover
        raise AssertionError("_parse must not be reached")

    def _fetch_live(self, query: str, location: str) -> dict[str, Any]:
        raise AssertionError(
            "LIVE HTTP was attempted while AETHER_DISCOVERY_FIXTURE_DIR was set"
        )


def test_missing_fixture_raises_instead_of_going_live(monkeypatch, tmp_path):
    monkeypatch.setenv("AETHER_DISCOVERY_FIXTURE_DIR", str(tmp_path))
    with pytest.raises(AdapterFetchError) as excinfo:
        _NeverLiveAdapter().fetch("business analyst", "Melbourne")
    message = str(excinfo.value)
    assert _NeverLiveAdapter.source in message
    assert "jobs.json" in message


def test_an_explicit_fixture_argument_still_wins(monkeypatch, tmp_path):
    """Passing ``fixture=`` is a legitimate fixture-mode entry point and must
    keep working — the refusal is only for "fixture mode on, nothing recorded"."""
    monkeypatch.setenv("AETHER_DISCOVERY_FIXTURE_DIR", str(tmp_path))

    class _Echo(_NeverLiveAdapter):
        def _parse(self, payload: dict[str, Any]) -> list[JobRaw]:
            return []

    assert _Echo(fixture={"boards": []}).fetch("q", "l") == []


def test_live_mode_is_untouched_when_fixture_mode_is_off(monkeypatch):
    """With no fixture dir configured the adapter must still go live — the fix
    must not turn production discovery into a refusal."""
    monkeypatch.delenv("AETHER_DISCOVERY_FIXTURE_DIR", raising=False)
    with pytest.raises(AssertionError, match="LIVE HTTP was attempted"):
        _NeverLiveAdapter().fetch("business analyst", "Melbourne")


def test_every_registered_live_source_has_a_recorded_fixture():
    assert os.environ.get("AETHER_DISCOVERY_FIXTURE_DIR"), (
        "the suite is expected to run in fixture mode"
    )
    missing = sorted(
        source
        for source in build_live_registry()
        if not (FIXTURE_ROOT / source / "jobs.json").exists()
    )
    assert not missing, (
        f"registered live discovery source(s) with no recorded fixture: {missing} — "
        "the suite would have to make live third-party HTTP calls to exercise them"
    )
