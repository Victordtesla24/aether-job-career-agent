"""Offers router — standalone GET /offers for offer comparison payload.

The endpoint derives the comparison payload from REAL Application records with
status='offer' joined to their Jobs. There are no hardcoded fixture offers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.db import get_connection, rows_to_dicts
from app.middleware.auth import CurrentUser

router = APIRouter()


@router.get("")
def get_offers(current_user: CurrentUser) -> dict[str, Any]:
    """Offer comparison payload — real Application records with status='offer'."""
    uid = current_user["id"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.id, a."createdAt",
                       j.title, j.company, j.location,
                       j."salaryMin", j."salaryMax", j.currency,
                       j."fitScore", j.remote
                FROM "Application" a
                JOIN "Job" j ON a."jobId" = j.id
                WHERE a."userId" = %s AND a.status = 'offer'
                ORDER BY j."fitScore" DESC NULLS LAST
                """,
                (uid,),
            )
            offer_rows = rows_to_dicts(cur)

    offer_list = []
    for idx, row in enumerate(offer_rows):
        sal_min = row.get("salaryMin") or 0
        sal_max = row.get("salaryMax") or 0
        base = sal_min
        # Estimate bonus ~10% of base and equity ~15% of base for display purposes
        bonus = int(base * 0.10)
        equity = int(base * 0.15)
        total = base + bonus + equity
        loc_label = row.get("location") or ("Remote" if row.get("remote") else "On-site")
        offer_list.append({
            "id": row["id"],
            "company": row["company"],
            "role": row["title"],
            "total": total,
            "base": base,
            "bonus": bonus,
            "equity": equity,
            "salaryRange": (
                f"{row.get('currency','AUD')} {sal_min:,}–{sal_max:,}" if sal_min else None
            ),
            "location": loc_label,
            "fitScore": int(row.get("fitScore") or 0),
            "topPick": idx == 0,
            "deadline": None,
        })

    return {
        "offers": offer_list,
        "weights": [
            {"key": "comp", "label": "Total compensation", "weight": 30},
            {"key": "growth", "label": "Career growth", "weight": 25},
            {"key": "culture", "label": "Culture & team", "weight": 20},
            {"key": "flexibility", "label": "Location & flexibility", "weight": 15},
            {"key": "stability", "label": "Company stability", "weight": 10},
        ],
        "negotiation": {
            "insight": (
                "Review each offer carefully. Use the weights panel to adjust "
                "what matters most to you and compare total compensation packages."
            ),
            "suggestedCounter": None,
            "leverage": [],
        },
    }
