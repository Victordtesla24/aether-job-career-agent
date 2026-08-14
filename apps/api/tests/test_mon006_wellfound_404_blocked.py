"""MON-006 — wellfound 404s must classify as calm "blocked", not re-alarm forever.

Wellfound's discovery adapter previously classified only HTTP 403 as the calm
``SourceBlockedError`` "blocked/parked" state (RT-008). As of 2026-08-14 the
live endpoint now answers HTTP 404 on every attempt instead of 403 — Wellfound
appears to have retired the public role-feed URL entirely, not merely blocked
this server from it. A plain 404 fell through to ``AdapterFetchError``, which
the scout treats as a real, actionable error — re-alarming on every sweep
(uat/reports/evidence/orch-exec/MON-RESIDUALS-EVIDENCE-2026-08-14.md, last
seen 13:39Z) even though nothing is user-actionable: the source is gone, not
temporarily unhappy with us.

Contract: a persistent 404 from wellfound classifies EXACTLY like a 403 — the
same ``SourceBlockedError`` type the scout keys its calm "blocked" state on —
with an honest, distinct reason string disclosing that the endpoint itself is
gone (not merely refusing us).
"""
from __future__ import annotations

import pytest

from app.agents import scout_agent as scout_module
from app.agents.scout_agent import ScoutAgent
from app.services.discovery.base_adapter import AdapterFetchError, SourceBlockedError
from app.services.discovery.wellfound_adapter import WellfoundAdapter


class _FourOhFourAdapter:
    """Stand-in for the live wellfound adapter once it classifies 404s."""

    source = "wellfound"

    def fetch(self, query: str, location: str):
        raise SourceBlockedError(
            "Wellfound public listings unavailable: HTTP Error 404: Not Found "
            "(source endpoint gone (404) — source parked)"
        )


class _HealthyAdapter:
    """A second, unrelated source — proves the sweep survives the blocked one."""

    source = "greenhouse"

    def __init__(self) -> None:
        self.called = False

    def fetch(self, query: str, location: str):
        self.called = True
        return []


class TestWellfound404ClassifiesAsBlocked:
    def test_wellfound_live_adapter_raises_blocked_on_404(self, monkeypatch):
        """The real adapter must raise SourceBlockedError (not a plain
        AdapterFetchError) when its endpoint 404s — the type the scout keys on."""
        from app.services.discovery import wellfound_adapter as mod

        def _404(url, *a, **k):
            raise RuntimeError("HTTP Error 404: Not Found")

        monkeypatch.setattr(mod, "fetch_json", _404)
        with pytest.raises(SourceBlockedError):
            mod.WellfoundAdapter()._fetch_live("engineer", "Melbourne")

    def test_404_and_403_classify_to_the_exact_same_state(self, monkeypatch):
        """(1) 404 must classify as the SAME state constant/enum as 403 — not
        merely 'also blocked' via some parallel code path."""
        from app.services.discovery import wellfound_adapter as mod

        def _404(url, *a, **k):
            raise RuntimeError("HTTP Error 404: Not Found")

        monkeypatch.setattr(mod, "fetch_json", _404)
        with pytest.raises(SourceBlockedError) as exc_404:
            WellfoundAdapter()._fetch_live("engineer", "Melbourne")

        def _403(url, *a, **k):
            raise RuntimeError("HTTP Error 403: Forbidden")

        monkeypatch.setattr(mod, "fetch_json", _403)
        with pytest.raises(SourceBlockedError) as exc_403:
            WellfoundAdapter()._fetch_live("engineer", "Melbourne")

        assert type(exc_404.value) is type(exc_403.value) is SourceBlockedError

    def test_404_reason_string_is_honest(self, monkeypatch):
        """(3) the reason string must honestly say the endpoint is gone, not
        reuse the "blocked" framing that belongs to an active 403 refusal."""
        from app.services.discovery import wellfound_adapter as mod

        def _404(url, *a, **k):
            raise RuntimeError("HTTP Error 404: Not Found")

        monkeypatch.setattr(mod, "fetch_json", _404)
        with pytest.raises(SourceBlockedError) as exc_info:
            WellfoundAdapter()._fetch_live("engineer", "Melbourne")

        message = str(exc_info.value)
        assert "404" in message
        assert "source parked" in message.lower()

    def test_other_5xx_and_network_failures_stay_plain_errors(self, monkeypatch):
        """A 404 is now special-cased, but every OTHER failure mode (a real,
        transient outage) must still surface as an honest, actionable error —
        mirrors the existing 403-vs-500 contract from RT-008."""
        from app.services.discovery import wellfound_adapter as mod

        def _500(url, *a, **k):
            raise RuntimeError("HTTP Error 500: Server Error")

        monkeypatch.setattr(mod, "fetch_json", _500)
        with pytest.raises(AdapterFetchError) as exc_info:
            WellfoundAdapter()._fetch_live("engineer", "Melbourne")
        assert not isinstance(exc_info.value, SourceBlockedError)

    def test_sweep_continues_past_a_404_blocked_source(
        self, client, auth_headers, monkeypatch
    ):
        """(2) the classification must not raise, and the sweep must continue
        on to process other sources rather than aborting the whole run."""
        healthy = _HealthyAdapter()
        monkeypatch.setattr(
            scout_module,
            "ADAPTERS",
            {"wellfound": _FourOhFourAdapter, "greenhouse": lambda: healthy},
        )
        from conftest import seed_own_resume

        seed_own_resume(client, auth_headers)
        from app.security import decode_access_token

        token = auth_headers["Authorization"].removeprefix("Bearer ")
        user_id = decode_access_token(token)["userId"]

        result = ScoutAgent().run(user_id, query="engineer", location="Melbourne")

        # No exception propagated out of the run — the 404 did not abort the sweep.
        assert healthy.called, "the sweep must still reach the second source"
        per_source = {s["source"]: s for s in result.per_source}
        assert per_source["wellfound"]["status"] == "blocked"
        assert per_source["greenhouse"]["status"] == "ok"
        # A calm blocked source is excluded from the run's error list, exactly
        # like the existing 403 contract (RT-008).
        assert result.errors == []
