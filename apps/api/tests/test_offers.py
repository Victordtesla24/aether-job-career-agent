"""AGT-OFFER — Offer Comparison endpoint tests (GET /offers).

``GET /offers`` derives the comparison payload from REAL ``Application``
records with ``status='offer'`` joined to their Jobs — there are no fixture
offers. An empty pipeline yields an empty offers list, and comp figures are
computed from the job's salary band (base = salaryMin, bonus = 10% of base,
equity = 15% of base).
"""
from __future__ import annotations

import json
import uuid


def _uid() -> str:
    return uuid.uuid4().hex[:25]


def _seed_offer(
    conn,
    user_id: str,
    *,
    company: str,
    title: str,
    salary_min: int,
    salary_max: int,
    fit_score: float,
) -> str:
    """Insert Job + Resume + Application(status='offer'); return the app id."""
    job_id, resume_id, app_id = _uid(), _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","salaryMin","salaryMax","currency","fitScore",'
            '"createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,%s,'AUD',%s,NOW(),NOW())",
            (job_id, user_id, title, company, "Real offer-stage role.", "seek",
             f"https://example.com/job/{job_id}", salary_min, salary_max, fit_score),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), f"hash-{resume_id}"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,'offer'::\"ApplicationStatus\",NOW(),NOW())",
            (app_id, user_id, job_id, resume_id),
        )
    conn.commit()
    return app_id


def _current_user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def test_offers_requires_auth(client) -> None:
    """/offers is auth-guarded — no anonymous access."""
    res = client.get("/offers")
    assert res.status_code == 401


def test_offers_payload_shape_empty_pipeline(client, auth_headers) -> None:
    """With no offer-stage applications the payload is honestly empty."""
    res = client.get("/offers", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert set(body) >= {"offers", "weights", "negotiation"}
    assert body["offers"] == []


def test_offers_reflect_real_offer_applications(client, auth_headers, db_session) -> None:
    """Offers come from Application(status='offer') with figures computed
    from the job's real salary band, ranked by fit score."""
    uid = _current_user_id(auth_headers)
    _seed_offer(db_session, uid, company="Real Co A", title="Delivery Manager",
                salary_min=180000, salary_max=200000, fit_score=88.0)
    _seed_offer(db_session, uid, company="Real Co B", title="Product Owner",
                salary_min=160000, salary_max=175000, fit_score=72.0)

    offers = client.get("/offers", headers=auth_headers).json()["offers"]
    assert [o["company"] for o in offers] == ["Real Co A", "Real Co B"]

    top = offers[0]
    assert top["topPick"] is True
    assert offers[1]["topPick"] is False
    assert top["base"] == 180000
    assert top["bonus"] == 18000            # 10% of base
    assert top["equity"] == 27000           # 15% of base
    assert top["total"] == 180000 + 18000 + 27000
    assert top["fitScore"] == 88

    offer_keys = {"id", "company", "role", "total", "base", "bonus", "equity",
                  "location", "fitScore", "topPick", "deadline"}
    for o in offers:
        assert offer_keys <= set(o)


def test_offers_weights_sum_to_100(client, auth_headers) -> None:
    weights = client.get("/offers", headers=auth_headers).json()["weights"]
    assert len(weights) == 5
    assert sum(w["weight"] for w in weights) == 100
    for w in weights:
        assert {"key", "label", "weight"} <= set(w)


def test_offers_negotiation_block(client, auth_headers) -> None:
    neg = client.get("/offers", headers=auth_headers).json()["negotiation"]
    assert {"insight", "suggestedCounter", "leverage"} <= set(neg)
    assert isinstance(neg["insight"], str) and neg["insight"].strip()
    assert neg["suggestedCounter"] is None or isinstance(neg["suggestedCounter"], int)
    assert isinstance(neg["leverage"], list)
