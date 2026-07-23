"""Backend-derived source availability (Workstream A ledger close, 2026-07-23).

Covers three MODELS-LIVE ledger rows in one coherent design:

- ML-prodverify-low1-allsources: ``GET /jobs?source=<unavailable>`` must be
  HONEST — a 4xx with the real reason (the app's existing convention for an
  invalid filter value is a 422 HTTPException with ``detail``, see the
  ``status`` filter in ``routers/jobs.py``) — never a silent 200/empty.
- ML-audit-seek-fe-hardcode-001: availability must be env/backend-derived
  (AETHER_ENABLE_SEEK), exposed via ``GET /agents/scout/sources/availability``
  so the FE never hardcodes availability strings.
- ML-audit-allsources-deadcode-001: the dead ``all_sources()`` is hard-deleted
  and superseded by the consumed ``source_availability()`` primitive.
"""
from __future__ import annotations

import pytest


class TestSourceAvailabilityPrimitive:
    def test_all_sources_is_hard_deleted(self):
        """ML-audit-allsources-deadcode-001: zero-caller helper must be gone."""
        from app.services.discovery import adapter_registry

        assert not hasattr(adapter_registry, "all_sources")

    def test_known_live_sources_are_available(self):
        from app.services.discovery.adapter_registry import source_availability

        rows = {r["source"]: r for r in source_availability()}
        for src in ("greenhouse", "lever", "ashby", "workable", "adzuna",
                    "remotive", "remoteok", "wellfound"):
            assert rows[src]["available"] is True
            assert rows[src]["reason"] is None

    def test_fixture_only_sources_are_unavailable_with_honest_reason(self):
        from app.services.discovery.adapter_registry import source_availability

        rows = {r["source"]: r for r in source_availability()}
        for src in ("linkedin", "indeed"):
            assert rows[src]["available"] is False
            assert "no live" in rows[src]["reason"].lower()

    def test_seek_gated_off_by_default(self, monkeypatch):
        monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
        from app.services.discovery.adapter_registry import source_availability

        rows = {r["source"]: r for r in source_availability()}
        assert rows["seek"]["available"] is False
        assert "AETHER_ENABLE_SEEK" in rows["seek"]["reason"]

    def test_seek_env_gate_flips_availability_at_call_time(self, monkeypatch):
        """ML-audit-seek-fe-hardcode-001: availability is env-derived, not frozen."""
        monkeypatch.setenv("AETHER_ENABLE_SEEK", "true")
        from app.services.discovery.adapter_registry import source_availability

        rows = {r["source"]: r for r in source_availability()}
        assert rows["seek"]["available"] is True
        assert rows["seek"]["reason"] is None


class TestAvailabilityEndpoint:
    def test_requires_auth(self, client):
        response = client.get("/agents/scout/sources/availability")
        assert response.status_code == 401

    def test_returns_per_source_availability(self, client, auth_headers):
        response = client.get(
            "/agents/scout/sources/availability", headers=auth_headers
        )
        assert response.status_code == 200
        rows = {r["source"]: r for r in response.json()}
        assert rows["greenhouse"] == {
            "source": "greenhouse", "available": True, "reason": None,
        }
        assert rows["linkedin"]["available"] is False
        assert rows["linkedin"]["reason"]
        assert rows["seek"]["available"] is False
        assert "AETHER_ENABLE_SEEK" in rows["seek"]["reason"]


class TestJobsSourceFilterHonesty:
    """ML-prodverify-low1-allsources: no silent 200/empty for dead sources."""

    def test_unavailable_source_rejected_422_with_honest_reason(
        self, client, auth_headers
    ):
        response = client.get("/jobs?source=linkedin", headers=auth_headers)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "linkedin" in detail
        assert "unavailable" in detail.lower()

    def test_gated_seek_rejected_422_by_default(self, client, auth_headers, monkeypatch):
        monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
        response = client.get("/jobs?source=seek", headers=auth_headers)
        assert response.status_code == 422
        assert "seek" in response.json()["detail"]

    def test_unknown_source_rejected_422(self, client, auth_headers):
        response = client.get("/jobs?source=bogusboard", headers=auth_headers)
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "bogusboard" in detail
        assert "greenhouse" in detail  # honest disclosure of the known set

    def test_available_source_still_200(self, client, auth_headers):
        response = client.get("/jobs?source=greenhouse", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_historical_rows_reachable_via_include_stale(self, client, auth_headers):
        """History is never deleted (GAP-P6-DATA-001): the sanctioned
        historical view may still be filtered by a currently-unavailable
        source, and the rejection detail points at it."""
        response = client.get(
            "/jobs?source=seek&include_stale=true", headers=auth_headers
        )
        assert response.status_code == 200

        rejected = client.get("/jobs?source=seek", headers=auth_headers)
        assert rejected.status_code == 422
        assert "include_stale" in rejected.json()["detail"]

    def test_enabled_seek_becomes_filterable(self, client, auth_headers, monkeypatch):
        monkeypatch.setenv("AETHER_ENABLE_SEEK", "true")
        response = client.get("/jobs?source=seek", headers=auth_headers)
        assert response.status_code == 200


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
