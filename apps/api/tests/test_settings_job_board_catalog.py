"""Settings Job Board Integrations — default-on catalog for every account.

The integrations list on ``GET /workspaces/settings`` must be a catalog of
every known discovery adapter (from ``adapter_registry``), not a projection of
which ``Job.source`` values already exist for the user. Live adapters are
``connected`` by default for paid AND unpaid users with zero Job rows.
Compliance-gated / fixture-only adapters stay visible but honest
(``not_configured``). Inbox alert provenance (``seek-alert``, …) never becomes
a board row.
"""
from __future__ import annotations

from app.db import get_connection, new_id
from app.repositories.billing import ensure_user_billing
from app.services.discovery.adapter_registry import _ALL_ADAPTERS

EXPECTED_SOURCES = frozenset(_ALL_ADAPTERS.keys())

LIVE_DEFAULT = frozenset({
    "greenhouse", "lever", "ashby", "workable", "smartrecruiters",
    "adzuna", "remotive", "remoteok", "wellfound",
})


def _integrations_by_source(payload: dict) -> dict[str, dict]:
    rows = payload["integrations"]
    by_source = {row["source"]: row for row in rows}
    assert len(by_source) == len(rows), "duplicate source ids in integrations"
    return by_source


def _seed_job(user_id: str, source: str, *, title: str = "Role") -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company",
                    "description", "source", "sourceUrl", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                ''',
                (
                    new_id(),
                    user_id,
                    title,
                    "Acme",
                    "desc",
                    source,
                    f"https://example.test/{source}/{new_id()}",
                ),
            )
        conn.commit()


def _set_plan(user_id: str, plan_id: str, status: str) -> None:
    ensure_user_billing(user_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE "Subscription" SET "planId"=%s,"status"=%s,"updatedAt"=now() '
                'WHERE "userId"=%s',
                (plan_id, status, user_id),
            )
        conn.commit()


def test_zero_job_user_gets_full_registry_catalog(
    client, auth_headers, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_source = _integrations_by_source(resp.json())
    assert set(by_source) == EXPECTED_SOURCES


def test_live_sources_default_on_with_zero_jobs(
    client, auth_headers, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_source = _integrations_by_source(resp.json())
    for src in LIVE_DEFAULT:
        row = by_source[src]
        assert row["status"] == "connected", src
        assert row["detail"] == "Default on · 0 jobs discovered", src
        assert "source" in row and row["source"] == src


def test_unpaid_and_paid_see_same_live_connected_set(
    client, auth_headers, test_user_id, monkeypatch
):
    """Catalog is not subscription-gated — unpaid sees the same live boards."""
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    monkeypatch.setenv("AETHER_REQUIRE_PAID_SUBSCRIPTION", "true")

    _set_plan(test_user_id, "free", "active")
    unpaid = client.get("/workspaces/settings", headers=auth_headers)
    assert unpaid.status_code == 200, unpaid.text
    unpaid_live = {
        s: r["status"]
        for s, r in _integrations_by_source(unpaid.json()).items()
        if s in LIVE_DEFAULT
    }

    _set_plan(test_user_id, "pro", "active")
    paid = client.get("/workspaces/settings", headers=auth_headers)
    assert paid.status_code == 200, paid.text
    paid_live = {
        s: r["status"]
        for s, r in _integrations_by_source(paid.json()).items()
        if s in LIVE_DEFAULT
    }

    assert unpaid_live == paid_live
    assert set(unpaid_live) == LIVE_DEFAULT
    assert all(status == "connected" for status in unpaid_live.values())


def test_job_count_overlays_live_source_detail(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    _seed_job(test_user_id, "adzuna")
    _seed_job(test_user_id, "adzuna", title="Role 2")

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    adzuna = _integrations_by_source(resp.json())["adzuna"]
    assert adzuna["status"] == "connected"
    assert "2 jobs discovered" in adzuna["detail"]
    assert "last sync" in adzuna["detail"]


def test_seek_visible_not_connected_when_gate_off_without_jobs(
    client, auth_headers, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    seek = _integrations_by_source(resp.json())["seek"]
    assert seek["status"] != "connected"
    assert "jobs discovered" not in seek["detail"]
    assert "AETHER_ENABLE_SEEK" in seek["detail"] or "compliance" in seek["detail"].lower()


def test_seek_connected_when_gate_on_without_jobs(
    client, auth_headers, monkeypatch
):
    monkeypatch.setenv("AETHER_ENABLE_SEEK", "true")
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    seek = _integrations_by_source(resp.json())["seek"]
    assert seek["status"] == "connected"
    assert seek["detail"] == "Default on · 0 jobs discovered"


def test_linkedin_and_indeed_visible_not_connected(
    client, auth_headers, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_source = _integrations_by_source(resp.json())
    for src in ("linkedin", "indeed"):
        row = by_source[src]
        assert row["status"] != "connected", src
        assert "jobs discovered" not in row["detail"], src
        assert "no live" in row["detail"].lower(), src


def test_seek_alert_job_does_not_add_board_row(
    client, auth_headers, test_user_id, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    _seed_job(test_user_id, "seek-alert")

    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_source = _integrations_by_source(resp.json())
    assert "seek-alert" not in by_source
    assert set(by_source) == EXPECTED_SOURCES


def test_display_names_are_not_naive_capitalize(
    client, auth_headers, monkeypatch
):
    monkeypatch.delenv("AETHER_ENABLE_SEEK", raising=False)
    resp = client.get("/workspaces/settings", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    by_source = _integrations_by_source(resp.json())
    assert by_source["remoteok"]["name"] == "RemoteOK"
    assert by_source["smartrecruiters"]["name"] == "SmartRecruiters"
    assert by_source["seek"]["name"] == "Seek"
    assert by_source["linkedin"]["name"] == "LinkedIn"
    assert by_source["wellfound"]["name"] == "Wellfound"
