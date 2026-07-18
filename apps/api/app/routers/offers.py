"""Offers router — standalone, READ-ONLY GET /offers for the comparison payload.

Deliberately read-only/legacy. The Offer Comparison UI talks to
``/workspaces/offers`` (GET/POST/DELETE); this ``/offers`` router is a
separately-tested duplicate GET that shares the exact same payload builder
(``app.services.offers.fetch_offers_payload``) so the two can never diverge. Do
NOT add write endpoints here — persistence lives on ``/workspaces/offers``.

The payload combines REAL ``Application(status='offer')`` records (joined to
their Jobs) with the user's persisted manual offers. There are no hardcoded
fixture offers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.middleware.auth import CurrentUser
from app.services.offers import fetch_offers_payload

router = APIRouter()


@router.get("")
def get_offers(current_user: CurrentUser) -> dict[str, Any]:
    """Offer comparison payload — derived + persisted offers for the caller."""
    return fetch_offers_payload(current_user["id"])
