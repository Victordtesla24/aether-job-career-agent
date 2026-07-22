"""ML-signup-001 (MODELS-LIVE, HIGH) — non-atomic billing provisioning races
a 500 on a brand-new user's first dashboard load.

**Bug being tested (NOT fixed by this commit):**
``GET /billing/entitlement`` (and ``GET /billing/subscription``, and every
other authed billing read) calls ``ensure_user_billing(user_id)``
(``apps/api/app/repositories/billing.py:256``) to lazily provision a Free
``Subscription`` + ``UsageQuota`` row for a user who has none yet — the common
case for a user who just completed ``/signup`` and is hitting the dashboard
for the very first time.

``ensure_user_billing._run`` (billing.py:268-290) provisions with a
check-then-insert pattern:

    INSERT INTO "Subscription" (...)
    SELECT %s, 'free', 'active', NULL, now(), now()
    WHERE NOT EXISTS (SELECT 1 FROM "Subscription" WHERE "userId" = %s)

and the equivalent for ``UsageQuota``. Both tables carry a
``UNIQUE INDEX ON ("userId")`` (billing.py:132-135, 160-163). Under Postgres's
default READ COMMITTED isolation, the ``WHERE NOT EXISTS`` subquery does NOT
see another transaction's UNCOMMITTED insert for the same user — so two
overlapping calls (a genuinely concurrent second request, OR a request that
races an in-flight provisioning attempt from the browser's own duplicate
dashboard fetch) can both evaluate "not exists" as true. The second writer
then blocks on the unique-index entry held by the first (in-progress)
writer's row and, the instant the first commits, raises
``psycopg2.errors.UniqueViolation`` (an ``IntegrityError``) — there is no
``ON CONFLICT DO NOTHING`` and no ``try/except IntegrityError`` anywhere on
this path. FastAPI has no handler for it, so it surfaces as a plain 500,
which the dashboard's ``subscription-gate.tsx`` renders as "We could not
verify your subscription" instead of the paywall.

**Reproduction strategy (deterministic, not a timing gamble):** rather than
hoping two Python threads happen to race, one thread holds a REAL uncommitted
``Subscription``/``UsageQuota`` insert open on its own connection (using
``ensure_user_billing``'s own ``cur=`` escape hatch to run the exact
production INSERTs without letting it auto-commit) — this simulates a
concurrent/duplicate provisioning attempt that is genuinely in flight. A
second thread then calls the real, unmodified ``ensure_user_billing`` (and,
separately, hits the real ``GET /billing/entitlement`` endpoint). Because the
holder's row is uncommitted, the second caller's own ``WHERE NOT EXISTS``
also reads "not exists" and it attempts its own INSERT, which the Postgres
unique index forces to block on the holder's in-flight row. Only once the
holder commits does the second caller's blocked statement resolve — and it
resolves with a unique-violation IntegrityError, exactly the production
symptom. No fix is applied here — only proof of the defect.

Evidence: ``uat/reports/evidence/models-live/screens/public-auth/
TESTING-OUTCOME-REPORT.md`` (2/4 fresh signups hit the 500 on first load).
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import psycopg2
import pytest
from starlette.testclient import TestClient

from app.db import _translate_prisma_url, get_database_url, new_id
from app.repositories.billing import (
    SubscriptionRepository,
    UsageQuotaRepository,
    ensure_user_billing,
)


def _raw_connection() -> "psycopg2.extensions.connection":
    """A hand-managed psycopg2 connection whose commit point WE control (the
    app's own ``get_connection()`` is a context manager that always closes on
    exit — unusable here since we need the transaction to stay open across a
    thread boundary while a second, independent caller races it)."""
    dsn, schema = _translate_prisma_url(get_database_url())
    options = f"-csearch_path={schema}" if schema else None
    return psycopg2.connect(dsn, options=options)


def _seed_bare_user() -> str:
    """A brand-new ``User`` row with NO billing rows yet — mirrors a user who
    just completed ``/signup`` and has never had ``ensure_user_billing`` run
    for them (auth registration does not call it; confirmed no reference to
    ``ensure_user_billing``/``billing`` in ``app/routers/auth.py``)."""
    user_id = new_id()
    with _raw_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","updatedAt") '
                "VALUES (%s,%s,'x',NOW())",
                (user_id, f"ml-signup-001-{uuid.uuid4().hex[:8]}@example.com"),
            )
        conn.commit()
    return user_id


# ---------------------------------------------------------------------------
# Repository-level: ensure_user_billing must be safe against a concurrent /
# duplicate provisioning attempt for the SAME fresh user (idempotent, no
# IntegrityError). Pins the atomicity contract directly (task brief §a).
# ---------------------------------------------------------------------------


def test_ensure_user_billing_does_not_raise_when_racing_a_concurrent_insert(client):
    """FAILS NOW: a second, independent ``ensure_user_billing`` call for a
    user whose provisioning is already in flight (uncommitted) on another
    connection raises ``IntegrityError`` instead of no-op'ing idempotently."""
    user_id = _seed_bare_user()

    # Thread A: start "concurrent" provisioning for this user and leave it
    # UNCOMMITTED — simulates a real overlapping request that is mid-flight.
    # ``cur=`` makes ensure_user_billing run its INSERTs on OUR connection
    # without committing (the function only commits when it opens its own).
    holder_conn = _raw_connection()
    holder_cur = holder_conn.cursor()
    ensure_user_billing(user_id, cur=holder_cur)  # rows inserted, NOT committed

    result: dict[str, Any] = {}

    def _victim() -> None:
        try:
            ensure_user_billing(user_id)  # the REAL, unmodified call under test
        except Exception as exc:  # noqa: BLE001 — capturing for assertion below
            result["error"] = exc

    victim_thread = threading.Thread(target=_victim)
    victim_thread.start()
    # Give the victim's INSERT time to reach Postgres and block on the
    # holder's in-flight (uncommitted) unique-index entry before we release
    # it. This is a setup-ordering aid, not the mechanism of the race itself
    # — the race is forced deterministically by holding the transaction open,
    # not by hoping two threads happen to overlap.
    time.sleep(1.0)
    holder_conn.commit()
    holder_conn.close()
    victim_thread.join(timeout=15)

    assert not victim_thread.is_alive(), "victim thread deadlocked/never returned"
    assert "error" not in result, (
        "ensure_user_billing raised on a concurrent/duplicate provisioning "
        f"attempt (non-atomic INSERT...WHERE NOT EXISTS race): {result.get('error')!r}"
    )

    # Post-condition (would hold once fixed): exactly ONE Subscription + ONE
    # UsageQuota row for this user — no duplicate/partial provisioning.
    with _raw_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "Subscription" WHERE "userId" = %s', (user_id,))
            sub_count = cur.fetchone()[0]
            cur.execute('SELECT count(*) FROM "UsageQuota" WHERE "userId" = %s', (user_id,))
            quota_count = cur.fetchone()[0]
    assert sub_count == 1, f"expected exactly 1 Subscription row, found {sub_count}"
    assert quota_count == 1, f"expected exactly 1 UsageQuota row, found {quota_count}"


# ---------------------------------------------------------------------------
# Endpoint-level: GET /billing/entitlement must be 200 (never 500) on a brand
# new user's first dashboard load, even when a concurrent provisioning
# attempt for the same user is in flight. Reproduces the tester's exact
# symptom (public-auth TESTING-OUTCOME-REPORT.md).
# ---------------------------------------------------------------------------


def test_entitlement_endpoint_200s_even_when_a_concurrent_insert_is_in_flight(
    client, auth_headers, test_user_id
):
    """FAILS NOW: GET /billing/entitlement 500s (instead of 200) for a
    brand-new user whose billing provisioning races an in-flight concurrent
    insert — the exact 'We could not verify your subscription' symptom.

    Uses a SEPARATE client with ``raise_server_exceptions=False`` (same
    underlying app/DB as the shared ``client`` fixture) so an unhandled
    IntegrityError surfaces as the real HTTP 500 response a production
    uvicorn deployment would send — not a raised Python exception, which is
    only how the DEFAULT ``TestClient`` (``raise_server_exceptions=True``,
    used everywhere else in this suite) chooses to re-surface it in-process.
    """
    # auth_headers/test_user_id register+login a fresh user; /auth/register
    # never calls ensure_user_billing, so this user has NO billing rows yet —
    # exactly the just-signed-up state from the finding.
    holder_conn = _raw_connection()
    holder_cur = holder_conn.cursor()
    ensure_user_billing(test_user_id, cur=holder_cur)  # in-flight, uncommitted

    prod_like_client = TestClient(client.app, raise_server_exceptions=False)
    result: dict[str, Any] = {}

    def _hit_entitlement() -> None:
        try:
            result["response"] = prod_like_client.get(
                "/billing/entitlement", headers=auth_headers
            )
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc

    request_thread = threading.Thread(target=_hit_entitlement)
    request_thread.start()
    time.sleep(1.0)
    holder_conn.commit()
    holder_conn.close()
    request_thread.join(timeout=15)

    assert not request_thread.is_alive(), "entitlement request deadlocked/never returned"
    assert "error" not in result, f"entitlement request raised: {result.get('error')!r}"
    response = result["response"]
    assert response.status_code == 200, (
        "GET /billing/entitlement must never 500 on a brand-new user's first "
        f"dashboard load, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["active_paid"] is False
    assert body["plan"]["id"] == "free"


# ---------------------------------------------------------------------------
# Guard-rail: the SEQUENTIAL (non-overlapping / already-committed) case must
# already behave correctly today — this passes now and must keep passing
# after the fix, distinguishing "non-atomic under concurrency" from a
# blanket "provisioning is broken" claim.
# ---------------------------------------------------------------------------


def test_ensure_user_billing_is_idempotent_for_sequential_non_overlapping_calls():
    user_id = _seed_bare_user()
    ensure_user_billing(user_id)  # first, real provisioning — committed
    ensure_user_billing(user_id)  # second, sequential call — must no-op

    sub = SubscriptionRepository().get_by_user(user_id)
    quota = UsageQuotaRepository().get_by_user(user_id)
    assert sub is not None and sub["planId"] == "free"
    assert quota is not None and quota["planId"] == "free"
