"""CLI-005 (BE-02) — a transport failure driving the employer site must be an
honest 502 ("nothing was submitted"), never an unhandled 500 stack trace.

Live incidents 2026-08-15T02:44Z: POST /approvals/{id}/execute returned 500
with 'Exception in ASGI application' when ApplyExecutorTransportError escaped
the handler (only ManualStepRequired and ApplyExecutorGuardError were caught).
"""
from __future__ import annotations

from app.repositories.approval import ApprovalRepository
from app.security import decode_access_token
from app.services.apply_executor import ApplyExecutorTransportError


def test_transport_error_is_an_honest_502_not_a_500(client, auth_headers, monkeypatch):
    uid = decode_access_token(
        auth_headers["Authorization"].removeprefix("Bearer ")
    )["userId"]
    repo = ApprovalRepository()
    approval = repo.create(
        uid,
        "application_submit",
        {
            "kind": "submission",
            "channel": "greenhouse",
            "application_id": "app-cli005-fake",
        },
    )
    assert client.post(
        f"/approvals/{approval['id']}/approve", headers=auth_headers
    ).status_code == 200

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise ApplyExecutorTransportError(
            "transport",
            "Could not open the application page (Error) — nothing was submitted.",
        )

    monkeypatch.setattr("app.workers.apply_sweep._attempt_transmission", _boom)

    resp = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
    assert resp.status_code == 502, (
        f"expected honest 502, got {resp.status_code}: {resp.text}"
    )
    detail = resp.json()["detail"]
    assert "nothing was submitted" in detail.lower()
