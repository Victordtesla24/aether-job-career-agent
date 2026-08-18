"""I4-FE-03 — ``GET /workspaces/settings``'s ``integrations`` list must reflect
the SAME ``AETHER_ENABLE_SEEK`` compliance-gate truth
``app.services.discovery.adapter_registry.build_live_registry()`` /
``source_availability()`` compute, not a client-side ``/seek/i`` name
substring.

Seek is always present in the catalog (default-on catalog). When the gate
is off it is ``not_configured`` with an honest reason and no fabricated
"jobs discovered" detail — even when a historical ``Job`` row with
``source='seek'`` exists. When the gate flips on at call time, Seek is
``connected`` without requiring a process restart.
"""
from __future__ import annotations

import pytest

from app.db import get_connection, new_id


def _seed_seek_job(user_id: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company",
                    "description", "source", "sourceUrl", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ''',
                (new_id(), user_id, "Backend Engineer", "Acme", "desc", "seek",
                 f"https://seek.com.au/job/{new_id()}"),
            )
        conn.commit()


def _by_source(payload: dict) -> dict[str, dict]:
    return {i["source"]: i for i in payload["integrations"]}


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def test_seek_integration_not_shown_connected_when_gate_is_off(
    client, auth_headers, user_id, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    _seed_seek_job(user_id)

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    integrations = _by_source(resp.json())

    assert "seek" in integrations, "Seek must always appear in the catalog"
    seek = integrations["seek"]
    assert seek["status"] != "connected", (
        f"Seek must not read as connected while AETHER_ENABLE_SEEK is off — got {seek!r}"
    )
    assert "jobs discovered" not in seek["detail"], (
        "gated-off source must not carry a fabricated discovery-activity detail"
    )


def test_seek_integration_shows_connected_when_gate_flips_on_at_call_time(
    client, auth_headers, user_id, monkeypatch
):
    """Mirrors ``test_source_availability.py``'s call-time (not import-time)
    env-flag contract: no process restart required to see the flip."""
    _seed_seek_job(user_id)
    monkeypatch.setenv("AETHER_ENABLE_SEEK", "true")

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    integrations = _by_source(resp.json())

    seek = integrations["seek"]
    assert seek["status"] == "connected"
    assert "jobs discovered" in seek["detail"]


def test_non_gated_source_is_unaffected(client, auth_headers, user_id, monkeypatch):
    """Regression guard: a normal, non-compliance-gated source (e.g. Adzuna)
    must keep reading as connected exactly as before this fix."""
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company",
                    "description", "source", "sourceUrl", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ''',
                (new_id(), user_id, "Data Engineer", "Acme", "desc", "adzuna",
                 f"https://adzuna.com/job/{new_id()}"),
            )
        conn.commit()

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    integrations = _by_source(resp.json())
    assert integrations["adzuna"]["status"] == "connected"
    assert "jobs discovered" in integrations["adzuna"]["detail"]
