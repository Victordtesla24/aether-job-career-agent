"""MV-offer-comparison-001/002/006 — offer persistence + honest negotiation.

Adds a real additive persistence path for the Offer Comparison screen:
``POST /workspaces/offers`` and ``DELETE /workspaces/offers/{id}`` backed by the
new lazily-created ``Offer`` table (user-scoped), plus a suggested counter that
is COMPUTED from the user's real offer bases (never a fabricated ``$0``).

These tests fail against the pre-fix code (no write endpoint; suggestedCounter
hardcoded ``None``) and pass once the fix lands.
"""
from __future__ import annotations

import uuid


VALID = {
    "company": "Persisted Co",
    "role": "Staff Engineer",
    "base": 200000,
    "bonus": 20000,
    "equity": 30000,
    "location": "Sydney · Hybrid",
    "currency": "AUD",
}


def _register_second_user(client) -> dict[str, str]:
    """Register + login a *second* user; return their Authorization header."""
    creds = {"email": f"offer-user-{uuid.uuid4().hex[:8]}@example.com", "password": "Sup3rSecret"}
    reg = client.post("/auth/register", json=creds)
    assert reg.status_code in (201, 409), reg.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #

def test_post_offer_requires_auth(client) -> None:
    assert client.post("/workspaces/offers", json=VALID).status_code == 401


def test_delete_offer_requires_auth(client) -> None:
    assert client.delete("/workspaces/offers/anything").status_code == 401


# --------------------------------------------------------------------------- #
# Persistence (MV-001)
# --------------------------------------------------------------------------- #

def test_post_persists_and_survives_get(client, auth_headers) -> None:
    created = client.post("/workspaces/offers", headers=auth_headers, json=VALID)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["company"] == "Persisted Co"
    assert body["total"] == 250000
    assert body["fitScore"] is None
    assert body["topPick"] is False
    assert body["source"] == "manual"
    assert body["currency"] == "AUD"
    offer_id = body["id"]

    # A fresh GET on BOTH offer endpoints must return the persisted offer.
    for path in ("/workspaces/offers", "/offers"):
        offers = client.get(path, headers=auth_headers).json()["offers"]
        match = [o for o in offers if o["id"] == offer_id]
        assert match, f"{path} did not return the persisted offer"
        assert match[0]["company"] == "Persisted Co"
        assert match[0]["source"] == "manual"
        assert match[0]["fitScore"] is None


def test_post_validation(client, auth_headers) -> None:
    def post(**over):
        return client.post("/workspaces/offers", headers=auth_headers, json={**VALID, **over})

    assert post(company="").status_code == 422
    assert post(company="   ").status_code == 422
    assert post(base=0).status_code == 422
    assert post(base=-5).status_code == 422
    assert post(bonus=-1).status_code == 422
    assert post(equity=-1).status_code == 422
    assert post(location="").status_code == 422


def test_offers_are_user_scoped(client, auth_headers) -> None:
    mine = client.post("/workspaces/offers", headers=auth_headers, json=VALID).json()["id"]
    other = _register_second_user(client)
    other_offers = client.get("/workspaces/offers", headers=other).json()["offers"]
    assert all(o["id"] != mine for o in other_offers)


# --------------------------------------------------------------------------- #
# Delete (MV-005 mitigation for the now-permanent write)
# --------------------------------------------------------------------------- #

def test_delete_removes_own_offer(client, auth_headers) -> None:
    offer_id = client.post("/workspaces/offers", headers=auth_headers, json=VALID).json()["id"]
    resp = client.delete(f"/workspaces/offers/{offer_id}", headers=auth_headers)
    assert resp.status_code in (200, 204), resp.text
    remaining = client.get("/workspaces/offers", headers=auth_headers).json()["offers"]
    assert all(o["id"] != offer_id for o in remaining)


def test_delete_other_users_offer_is_404(client, auth_headers) -> None:
    offer_id = client.post("/workspaces/offers", headers=auth_headers, json=VALID).json()["id"]
    other = _register_second_user(client)
    assert client.delete(f"/workspaces/offers/{offer_id}", headers=other).status_code == 404
    # still there for the owner
    remaining = client.get("/workspaces/offers", headers=auth_headers).json()["offers"]
    assert any(o["id"] == offer_id for o in remaining)


def test_delete_unknown_offer_is_404(client, auth_headers) -> None:
    assert client.delete("/workspaces/offers/does-not-exist", headers=auth_headers).status_code == 404


# --------------------------------------------------------------------------- #
# Suggested counter (MV-002) — computed, never fabricated
# --------------------------------------------------------------------------- #

def test_suggested_counter_is_none_when_no_offers(client, auth_headers) -> None:
    neg = client.get("/workspaces/offers", headers=auth_headers).json()["negotiation"]
    assert neg["suggestedCounter"] is None
    assert neg["leverage"] == []


def test_suggested_counter_computed_from_single_offer(client, auth_headers) -> None:
    client.post("/workspaces/offers", headers=auth_headers, json={**VALID, "base": 185000})
    neg = client.get("/workspaces/offers", headers=auth_headers).json()["negotiation"]
    # round-half-up(185000 * 1.10) to nearest $1,000 = 204000
    assert neg["suggestedCounter"] == 204000
    assert "185,000" in neg["insight"]
    # a single offer is not "competing offers" leverage
    assert neg["leverage"] == []


def test_suggested_counter_uses_top_base_with_multiple_offers(client, auth_headers) -> None:
    client.post("/workspaces/offers", headers=auth_headers, json={**VALID, "company": "A", "base": 185000})
    client.post("/workspaces/offers", headers=auth_headers, json={**VALID, "company": "B", "base": 210000})
    neg = client.get("/workspaces/offers", headers=auth_headers).json()["negotiation"]
    # top base = 210000 -> 231000
    assert neg["suggestedCounter"] == 231000
    assert any("2" in point for point in neg["leverage"])  # competing-offer count surfaced
