"""Offer Comparison service (MV-offer-comparison-001/002/006).

Two offer sources feed the comparison payload:

* DERIVED offers — ``Application(status='offer')`` JOIN ``Job`` (read-only,
  unchanged behaviour). Carry a real ``fitScore`` and rank; the top one is the
  "Top pick".
* MANUAL offers — user-entered rows in the additive ``"Offer"`` table, created
  via ``POST /workspaces/offers`` and removable via
  ``DELETE /workspaces/offers/{id}``. No ``fitScore`` (shown as "Pending"),
  never a top pick.

There is no migration runner (ADR-TR-1); the ``"Offer"`` table is created by the
lazy, advisory-locked idempotent DDL in :func:`_ensure_offers_table` — the sole
mechanism that provisions it in production. Additive only: ``CREATE TABLE/INDEX
IF NOT EXISTS``. No FK to ``"User"`` (matches ``AdminAuditLog``/``UsageQuota``
TRUNCATE-safety in the shared test schema).

The suggested counter is COMPUTED from the user's real offer bases and disclosed
in the insight text as a heuristic anchor — it is never a fabricated figure and
falls back to ``None`` (honest "add an offer" state) when there is no base to
anchor on.
"""
from __future__ import annotations

from typing import Any

from app.db import get_connection, new_id, rows_to_dicts

#: Distinct table-DDL advisory-lock id. Registry lives in
#: ``app/repositories/background_jobs.py`` (grep ``pg_advisory_xact_lock``).
#: 7420240724 is the next genuinely-free id: 711–722 are in use, and 723 is held
#: by gmail_service's EmailThread aiScore DDL on current main — so 724 collides
#: with nothing on either this base or main. (Registry comment left to its owner
#: to advance to 725, to avoid editing a file this branch does not otherwise
#: touch and that main has already advanced past this base.)
_OFFERS_LOCK = 7420240724

#: Guard so the DDL only runs once per worker process.
_offers_table_ready = False


def _ensure_offers_table() -> None:
    """Idempotently create the ``"Offer"`` table on first use.

    Mirrors ``networking._ensure_outreach_tables`` / ``db.ensure_*_columns``: a
    lock-free existence fast-path, then a transaction-scoped advisory lock
    serialising concurrent first-hit callers around ``CREATE TABLE IF NOT
    EXISTS``. ``TRUNCATE`` never drops tables, so this survives the test-suite
    teardown.
    """
    global _offers_table_ready
    if _offers_table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'Offer'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _offers_table_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_OFFERS_LOCK,))
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS "Offer" (
                    "id"        text PRIMARY KEY,
                    "userId"    text        NOT NULL,
                    "company"   text        NOT NULL,
                    "role"      text,
                    "base"      integer     NOT NULL,
                    "bonus"     integer     NOT NULL DEFAULT 0,
                    "equity"    integer     NOT NULL DEFAULT 0,
                    "location"  text        NOT NULL,
                    "currency"  text        NOT NULL DEFAULT 'AUD',
                    "createdAt" timestamptz NOT NULL DEFAULT now(),
                    "updatedAt" timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_offer_userId" ON "Offer" ("userId")'
            )
        conn.commit()
    _offers_table_ready = True


#: Default priority-weight rows. Returned for backward compatibility only — the
#: UI no longer renders a weights panel (MV-offer-comparison-004: the weights
#: never fed any score, and there is no honest per-dimension data source for
#: growth/culture/stability, so fabricating a "weighted score" is not an option).
_WEIGHTS: list[dict[str, Any]] = [
    {"key": "comp", "label": "Total compensation", "weight": 30},
    {"key": "growth", "label": "Career growth", "weight": 25},
    {"key": "culture", "label": "Culture & team", "weight": 20},
    {"key": "flexibility", "label": "Location & flexibility", "weight": 15},
    {"key": "stability", "label": "Company stability", "weight": 10},
]


def compute_suggested_counter(offers: list[dict[str, Any]]) -> int | None:
    """A disclosed ~10% anchor above the strongest base offer, rounded (half-up)
    to the nearest $1,000. Returns ``None`` when no offer carries a positive base
    — the UI then shows an honest "add an offer" state rather than ``$0``."""
    bases = [int(o["base"]) for o in offers if o.get("base")]
    if not bases:
        return None
    top = max(bases)
    return int((top * 1.10 + 500) // 1000) * 1000


def _derived_offers(cur: Any, uid: str) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT a.id, j.title, j.company, j.location,
               j."salaryMin", j."salaryMax", j.currency, j."fitScore", j.remote
        FROM "Application" a
        JOIN "Job" j ON a."jobId" = j.id
        WHERE a."userId" = %s AND a.status = 'offer'
        ORDER BY j."fitScore" DESC NULLS LAST
        """,
        (uid,),
    )
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows_to_dicts(cur)):
        sal_min = row.get("salaryMin") or 0
        sal_max = row.get("salaryMax") or 0
        base = sal_min
        bonus = int(base * 0.10)   # ~10% of base for display
        equity = int(base * 0.15)  # ~15% of base for display
        cur_code = row.get("currency") or "AUD"
        loc = row.get("location") or ("Remote" if row.get("remote") else "On-site")
        out.append({
            "id": row["id"],
            "company": row["company"],
            "role": row["title"],
            "total": base + bonus + equity,
            "base": base,
            "bonus": bonus,
            "equity": equity,
            "currency": cur_code,
            "salaryRange": f"{cur_code} {sal_min:,}–{sal_max:,}" if sal_min else None,
            "location": loc,
            "fitScore": int(row.get("fitScore") or 0),
            "topPick": idx == 0,
            "deadline": None,
            "source": "application",
        })
    return out


def _manual_offers(cur: Any, uid: str) -> list[dict[str, Any]]:
    cur.execute(
        'SELECT "id","company","role","base","bonus","equity","location","currency"'
        ' FROM "Offer" WHERE "userId" = %s ORDER BY "createdAt" DESC',
        (uid,),
    )
    out: list[dict[str, Any]] = []
    for row in rows_to_dicts(cur):
        out.append(_offer_view(
            offer_id=row["id"],
            company=row["company"],
            role=row["role"],
            base=int(row["base"] or 0),
            bonus=int(row["bonus"] or 0),
            equity=int(row["equity"] or 0),
            location=row["location"],
            currency=row["currency"] or "AUD",
        ))
    return out


def _offer_view(
    *, offer_id: str, company: str, role: str | None, base: int, bonus: int,
    equity: int, location: str, currency: str,
) -> dict[str, Any]:
    """Serialise a MANUAL offer into the comparison-payload shape."""
    return {
        "id": offer_id,
        "company": company,
        "role": role or "—",
        "total": base + bonus + equity,
        "base": base,
        "bonus": bonus,
        "equity": equity,
        "currency": currency,
        "salaryRange": None,
        "location": location,
        "fitScore": None,
        "topPick": False,
        "deadline": None,
        "source": "manual",
    }


def _negotiation(offers: list[dict[str, Any]]) -> dict[str, Any]:
    counter = compute_suggested_counter(offers)
    if counter is None:
        return {
            "insight": (
                "Add an offer with a base salary and Aether will suggest a counter "
                "anchored on your strongest offer."
            ),
            "suggestedCounter": None,
            "leverage": [],
        }
    top = max(int(o["base"]) for o in offers if o.get("base"))
    count = len(offers)
    leverage = (
        [f"You hold {count} active offers — competing offers are your strongest leverage."]
        if count >= 2
        else []
    )
    return {
        "insight": (
            f"Your strongest base offer is ${top:,}. Anchoring a counter near "
            f"${counter:,} (about 10% above) leaves room to negotiate — adjust to "
            f"your own target and market research."
        ),
        "suggestedCounter": counter,
        "leverage": leverage,
    }


def fetch_offers_payload(uid: str) -> dict[str, Any]:
    """Build the full Offer Comparison payload for ``uid`` — derived offers +
    the user's persisted manual offers, plus weights and a computed negotiation
    block. Shared by both ``GET /workspaces/offers`` and ``GET /offers`` so they
    can never diverge."""
    _ensure_offers_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            offers = _derived_offers(cur, uid) + _manual_offers(cur, uid)
    return {
        "offers": offers,
        "weights": [dict(w) for w in _WEIGHTS],
        "negotiation": _negotiation(offers),
    }


def create_offer(
    uid: str, *, company: str, role: str | None, base: int, bonus: int,
    equity: int, location: str, currency: str,
) -> dict[str, Any]:
    """Persist a user-entered offer and return it in comparison-payload shape."""
    _ensure_offers_table()
    offer_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "Offer" ("id","userId","company","role","base",'
                '"bonus","equity","location","currency","createdAt","updatedAt")'
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now())",
                (offer_id, uid, company, role, base, bonus, equity, location, currency),
            )
        conn.commit()
    return _offer_view(
        offer_id=offer_id, company=company, role=role, base=base, bonus=bonus,
        equity=equity, location=location, currency=currency,
    )


def delete_offer(uid: str, offer_id: str) -> bool:
    """Delete the caller's own manual offer. Returns ``False`` when no row was
    owned by ``uid`` with that id (derived/application offers are not in this
    table, so they correctly cannot be deleted here)."""
    _ensure_offers_table()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM "Offer" WHERE "id" = %s AND "userId" = %s',
                (offer_id, uid),
            )
            deleted = cur.rowcount
        conn.commit()
    return deleted > 0
