"""U5 closing round — orchestrator SHOULD-FIX 6 (round-3 re-review).

The FE's "not enabled on this deployment yet" copy (tracker-lib.ts
`notTransmittedReason` / `automaticSubmissionDisclaimer`) used to be a
hardcoded assumption with zero coupling to the real
``AETHER_APPLY_SWEEP_ENABLED`` kill-switch (``app.workers.apply_sweep.
sweep_enabled()``) — true today, false the instant an operator turns the
sweep on. This pins the live capability signal the FE now reads instead,
mirroring the precedent at ``app.workers.board_sweep.sweep_enabled()`` read
live inside ``POST /agents/board-sweep/trigger``.
"""
from __future__ import annotations


class TestApplySweepStatusEndpoint:
    def test_reports_disabled_by_default(self, client, auth_headers, monkeypatch):
        monkeypatch.delenv("AETHER_APPLY_SWEEP_ENABLED", raising=False)

        resp = client.get("/applications/apply-sweep-status", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == {"sweepEnabled": False}

    def test_reports_enabled_when_the_operator_turns_it_on(self, client, auth_headers, monkeypatch):
        monkeypatch.setenv("AETHER_APPLY_SWEEP_ENABLED", "true")

        resp = client.get("/applications/apply-sweep-status", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == {"sweepEnabled": True}

    def test_requires_authentication(self, client):
        resp = client.get("/applications/apply-sweep-status")
        assert resp.status_code in (401, 403)

    def test_route_is_registered_before_the_application_id_catch_all(self, client, auth_headers):
        """A fixed-path route registered AFTER `/{application_id}` would be
        shadowed — FastAPI would try to load an Application with id
        'apply-sweep-status' and 404 instead of answering the status. This
        guards the registration ORDER, not just the handler."""
        resp = client.get("/applications/apply-sweep-status", headers=auth_headers)
        assert resp.status_code == 200
        assert "sweepEnabled" in resp.json()
