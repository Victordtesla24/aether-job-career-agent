"""RT-008 — a source that BLOCKS this server must not scream "error" forever.

Wellfound has returned HTTP 403 Forbidden on every fetch for days (it blocks
automated/datacenter access). That is not a transient sync failure the user
can do anything about, yet the scout classified it ``status="error"`` and
appended it to ``result.errors`` on every run — a permanent red "error · just
now" chip (operator report 2026-07-24).

Contract: an upstream access-denied failure (403/Forbidden) is classified
``status="blocked"`` — disclosed per-source with its real reason, excluded
from the run's ``errors`` list — while every other adapter failure remains an
honest ``error``.
"""
from __future__ import annotations

import pytest

from app.services.discovery.base_adapter import AdapterFetchError, SourceBlockedError
from app.agents import scout_agent as scout_module
from app.agents.scout_agent import ScoutAgent


class _BlockedAdapter:
    source = "wellfound"

    def fetch(self, query: str, location: str):
        raise SourceBlockedError(
            "Wellfound public listings unavailable: HTTP Error 403: Forbidden"
        )


class _BrokenAdapter:
    source = "greenhouse"

    def fetch(self, query: str, location: str):
        # A plain AdapterFetchError — even a 403 across all boards — is an
        # honest ERROR (only an adapter-asserted SourceBlockedError is "blocked").
        raise AdapterFetchError("boards API unreachable: HTTP Error 403: Forbidden")


def _run_scout(client, auth_headers, monkeypatch, adapter_cls) -> dict:
    monkeypatch.setattr(
        scout_module, "ADAPTERS", {adapter_cls.source: adapter_cls}
    )
    from conftest import seed_own_resume

    seed_own_resume(client, auth_headers)
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    user_id = decode_access_token(token)["userId"]
    result = ScoutAgent().run(user_id, query="engineer", location="Melbourne")
    per_source = {s["source"]: s for s in result.per_source}
    return {"result": result, "src": per_source[adapter_cls.source]}


class TestBlockedClassification:
    def test_403_is_blocked_not_error(self, client, auth_headers, monkeypatch):
        out = _run_scout(client, auth_headers, monkeypatch, _BlockedAdapter)
        assert out["src"]["status"] == "blocked"
        # The real reason stays disclosed on the source row…
        assert "403" in (out["src"]["error"] or "")
        # …but a permanently blocked source is not a run ERROR.
        assert out["result"].errors == []

    def test_other_failures_stay_honest_errors(self, client, auth_headers, monkeypatch):
        out = _run_scout(client, auth_headers, monkeypatch, _BrokenAdapter)
        assert out["src"]["status"] == "error"
        assert any("403" in e for e in out["result"].errors)

    def test_wellfound_live_adapter_raises_blocked_on_403(self, monkeypatch):
        """The real wellfound adapter raises SourceBlockedError (not a plain
        AdapterFetchError) when its endpoint 403s — the type the scout keys on."""
        from app.services.discovery import wellfound_adapter as mod

        def _403(url, *a, **k):
            raise RuntimeError("HTTP Error 403: Forbidden")

        monkeypatch.setattr(mod, "fetch_json", _403)
        with pytest.raises(SourceBlockedError):
            mod.WellfoundAdapter()._fetch_live("engineer", "Melbourne")

    def test_wellfound_live_adapter_raises_plain_error_on_500(self, monkeypatch):
        from app.services.discovery import wellfound_adapter as mod

        def _500(url, *a, **k):
            raise RuntimeError("HTTP Error 500: Server Error")

        monkeypatch.setattr(mod, "fetch_json", _500)
        with pytest.raises(AdapterFetchError) as exc_info:
            mod.WellfoundAdapter()._fetch_live("engineer", "Melbourne")
        assert not isinstance(exc_info.value, SourceBlockedError)
