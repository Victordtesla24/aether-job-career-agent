"""AGT-OFFER — Offer Comparison endpoint tests (GET /offers).

The offer-comparison screen is fixture-backed per TRACEABILITY row 15
(offer-stage DB tooling deferred), served through the authenticated workspaces
router — same sanctioned pattern as /analytics/market-pulse. These tests assert
the contract the frontend (fetchOffers → OffersPayload) depends on.
"""
from __future__ import annotations


def test_offers_requires_auth(client) -> None:
    """/offers is auth-guarded — no anonymous access."""
    res = client.get("/offers")
    assert res.status_code == 401


def test_offers_payload_shape(client, auth_headers) -> None:
    res = client.get("/offers", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"offers", "weights", "negotiation"}

    # Exactly the three canonical offers, Canva as the single top pick.
    offers = body["offers"]
    assert len(offers) == 3
    companies = [o["company"] for o in offers]
    assert companies == ["Canva", "Atlassian", "ANZ"]
    top = [o for o in offers if o["topPick"]]
    assert len(top) == 1 and top[0]["company"] == "Canva"

    offer_keys = {"id", "company", "role", "total", "base", "bonus", "equity",
                  "location", "fitScore", "topPick", "deadline"}
    for o in offers:
        assert offer_keys <= set(o)
        assert isinstance(o["total"], int) and o["total"] > 0
        assert 0 <= o["fitScore"] <= 100


def test_offers_canonical_figures(client, auth_headers) -> None:
    """Canonical comp + fit figures shown in the wireframe stay stable."""
    offers = {o["company"]: o for o in client.get("/offers", headers=auth_headers).json()["offers"]}
    assert offers["Canva"]["total"] == 248000
    assert offers["Atlassian"]["total"] == 235000
    assert offers["ANZ"]["total"] == 212000
    assert offers["Canva"]["fitScore"] == 91
    assert offers["Atlassian"]["fitScore"] == 84
    assert offers["ANZ"]["fitScore"] == 79


def test_offers_weights_sum_to_100(client, auth_headers) -> None:
    weights = client.get("/offers", headers=auth_headers).json()["weights"]
    assert len(weights) == 5
    assert sum(w["weight"] for w in weights) == 100
    for w in weights:
        assert {"key", "label", "weight"} <= set(w)


def test_offers_negotiation_block(client, auth_headers) -> None:
    neg = client.get("/offers", headers=auth_headers).json()["negotiation"]
    assert {"insight", "suggestedCounter", "leverage"} <= set(neg)
    assert isinstance(neg["suggestedCounter"], int) and neg["suggestedCounter"] > 0
    assert isinstance(neg["leverage"], list) and neg["leverage"]
