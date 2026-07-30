"""Wave-4A — Salary Intelligence Agent (ADR-AG-1 honest scope).

HONEST SCOPE: aggregates the salary ranges that the user's OWN discovered
postings actually DISCLOSED, grouped by role family / location / currency, and
reports "N of M disclosed". It NEVER imputes a missing bound, never estimates a
range from a comparable posting, and never merges two currencies. Deterministic,
unmetered.

Fail-before: ``app.agents.salary_intelligence_agent`` does not exist and
``POST /agents/salaryIntelligence/run`` 404s.
"""
from __future__ import annotations

import uuid

import pytest


def _uid() -> str:
    return uuid.uuid4().hex


def _seed_job(
    conn,
    user_id: str,
    *,
    title: str,
    company: str = "Acme",
    location: str | None = "Melbourne, Australia",
    remote: bool = False,
    salary_min: int | None = None,
    salary_max: int | None = None,
    currency: str | None = None,
    description: str = "Deliver outcomes.",
    source: str = "seek",
) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","location","remote",'
            '"salaryMin","salaryMax","currency","description","source","sourceUrl",'
            '"status","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'
            "'discovered'::\"JobStatus\",NOW(),NOW())",
            (
                job_id, user_id, title, company, location, remote,
                salary_min, salary_max, currency, description, source,
                f"https://example.com/job/{job_id}",
            ),
        )
    conn.commit()
    return job_id


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _run(client, headers, params: dict | None = None):
    return client.post(
        "/agents/salaryIntelligence/run", json=params or {}, headers=headers
    )


def _group(body: dict, role_family: str, location: str, currency: str) -> dict:
    return next(
        g for g in body["groups"]
        if g["roleFamily"] == role_family
        and g["location"] == location
        and g["currency"] == currency
    )


# ---------------------------------------------------------------------------
# Real aggregation
# ---------------------------------------------------------------------------


def test_aggregates_disclosed_ranges_by_role_family_and_location(
    client, auth_headers, user_id, db_session
):
    _seed_job(
        db_session, user_id, title="Senior Program Manager",
        location="Melbourne, Australia",
        salary_min=160000, salary_max=190000, currency="AUD",
    )
    _seed_job(
        db_session, user_id, title="Program Manager, Payments",
        location="Melbourne, Australia",
        salary_min=140000, salary_max=170000, currency="AUD",
    )
    _seed_job(
        db_session, user_id, title="Program Manager (Cloud)",
        location="Melbourne, Australia",
        currency="AUD",  # DISCLOSED nothing — must not be imputed
    )
    _seed_job(
        db_session, user_id, title="Business Analyst",
        location="Sydney, Australia",
        salary_min=120000, salary_max=135000, currency="AUD",
    )

    resp = _run(client, auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["postings"] == 4
    assert body["disclosed"] == 3
    assert body["disclosureRate"] == 0.75

    pm = _group(body, "program manager", "Melbourne, Australia", "AUD")
    assert pm["postings"] == 3
    assert pm["disclosed"] == 2
    # Real aggregates over ONLY the two postings that disclosed.
    assert pm["salaryMin"] == {
        "disclosed": 2, "low": 140000, "high": 160000, "median": 150000.0
    }
    assert pm["salaryMax"] == {
        "disclosed": 2, "low": 170000, "high": 190000, "median": 180000.0
    }

    ba = _group(body, "business analyst", "Sydney, Australia", "AUD")
    assert ba["postings"] == 1 and ba["disclosed"] == 1
    assert ba["salaryMin"]["median"] == 120000.0

    # Groups are ordered by real volume, deterministically.
    assert body["groups"][0]["postings"] >= body["groups"][-1]["postings"]
    assert "no imputation" in body["method"].lower()


def test_never_imputes_a_missing_bound(client, auth_headers, user_id, db_session):
    """A posting that discloses ONLY a maximum contributes to the max stats and
    leaves the min stats genuinely empty — the min is never derived from it."""
    _seed_job(
        db_session, user_id, title="Delivery Manager",
        location="Remote", salary_max=180000, currency="AUD",
    )
    body = _run(client, auth_headers).json()
    grp = _group(body, "delivery manager", "Remote", "AUD")
    assert grp["disclosed"] == 1
    assert grp["salaryMin"] == {
        "disclosed": 0, "low": None, "high": None, "median": None
    }
    assert grp["salaryMax"] == {
        "disclosed": 1, "low": 180000, "high": 180000, "median": 180000.0
    }


def test_currencies_are_never_merged(client, auth_headers, user_id, db_session):
    _seed_job(
        db_session, user_id, title="Product Owner", location="Melbourne, Australia",
        salary_min=150000, salary_max=170000, currency="AUD",
    )
    _seed_job(
        db_session, user_id, title="Product Owner", location="Melbourne, Australia",
        salary_min=110000, salary_max=130000, currency="USD",
    )
    body = _run(client, auth_headers).json()
    assert body["currencies"] == {"AUD": 1, "USD": 1}
    aud = _group(body, "product owner", "Melbourne, Australia", "AUD")
    usd = _group(body, "product owner", "Melbourne, Australia", "USD")
    assert aud["salaryMin"]["low"] == 150000
    assert usd["salaryMin"]["low"] == 110000
    assert len([g for g in body["groups"] if g["roleFamily"] == "product owner"]) == 2


def test_undeclared_currency_is_labelled_not_assumed(
    client, auth_headers, user_id, db_session
):
    _seed_job(
        db_session, user_id, title="Scrum Master", location=None,
        salary_min=130000, salary_max=140000, currency=None,
    )
    body = _run(client, auth_headers).json()
    grp = _group(body, "scrum master", "unspecified", "unspecified")
    assert grp["disclosed"] == 1
    assert body["currencies"] == {"unspecified": 1}


def test_title_outside_the_known_family_is_grouped_honestly(
    client, auth_headers, user_id, db_session
):
    _seed_job(
        db_session, user_id, title="Quantum Blacksmith", location="Perth",
        salary_min=99000, currency="AUD",
    )
    body = _run(client, auth_headers).json()
    grp = _group(body, "unclassified", "Perth", "AUD")
    assert grp["postings"] == 1
    assert grp["titles"] == ["Quantum Blacksmith"]


# ---------------------------------------------------------------------------
# Honest empty states
# ---------------------------------------------------------------------------


def test_honest_empty_state_with_no_postings(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["postings"] == 0
    assert body["disclosed"] == 0
    assert body["disclosureRate"] is None
    assert body["groups"] == []
    assert "no discovered postings" in body["message"].lower()


def test_honest_zero_disclosure_state(client, auth_headers, user_id, db_session):
    for i in range(3):
        _seed_job(db_session, user_id, title=f"Agile Coach {i}", location="Brisbane")
    body = _run(client, auth_headers).json()
    assert body["postings"] == 3
    assert body["disclosed"] == 0
    assert body["disclosureRate"] == 0.0
    grp = _group(body, "agile coach", "Brisbane", "unspecified")
    assert grp["salaryMin"]["median"] is None
    assert grp["salaryMax"]["median"] is None
    assert "0 of 3" in body["message"]


def test_is_scoped_to_the_caller(client, auth_headers, user_id, db_session):
    other = _uid()
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "User" ("id","email","name","passwordHash","updatedAt") '
            "VALUES (%s,%s,'Other','x',NOW())",
            (other, f"other-{other[:8]}@example.com"),
        )
    db_session.commit()
    _seed_job(
        db_session, other, title="Program Manager", salary_min=1, salary_max=2,
        currency="AUD",
    )
    body = _run(client, auth_headers).json()
    assert body["postings"] == 0


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_run_is_audited_unmetered_and_zero_cost(client, auth_headers):
    body = _run(client, auth_headers).json()
    assert body["model"] is None
    assert body["costUsd"] == 0.0
    runs = client.get("/agents/runs", headers=auth_headers).json()
    row = next(r for r in runs if r["agentName"] == "salaryIntelligence")
    assert row["status"] == "completed"


def test_backend_is_not_metered():
    from app.routers.agents import _DETERMINISTIC_BACKENDS, _LLM_TIER_BY_BACKEND

    assert "salaryIntelligence" not in _LLM_TIER_BY_BACKEND
    assert "salaryIntelligence" in _DETERMINISTIC_BACKENDS
