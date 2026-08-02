"""v5 BLOCKER — `executedAt` must mean "we transmitted", never "we looked at it".

The whole submission workstream exists because 133 ApprovalRequests carried
`executedAt` while ZERO transmissions had ever occurred, and 86 Applications
told the user "submitted". The v5 adversarial review found that state
reintroduced: `claim_execution` stamps `executedAt = NOW()` BEFORE any work, so
any path that falls through to the non-transmitting branch left the row reading
executed with nothing sent.

These tests pin the invariant so it cannot come back a third time.
"""
from __future__ import annotations


def _seed_document_approval(user_id: str, kind: str = "application_submit") -> str:
    """Insert a real APPROVED approval that transmits NOTHING.

    Default is ``application_submit`` with an EMPTY payload — precisely the path
    the v5 review found reintroducing the lie: it has no ``kind="submission"``
    payload, so it falls through to the non-transmitting branch while
    ``claim_execution`` has already stamped ``executedAt``."""
    import uuid

    from app.db import get_connection
    from app.repositories.approval import ensure_approval_columns

    ensure_approval_columns()
    approval_id = uuid.uuid4().hex[:25]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "ApprovalRequest" '
                '("id","userId","type","status","payload","createdAt") '
                "VALUES (%s,%s,%s::\"ApprovalType\",'approved','{}'::jsonb,NOW())",
                (approval_id, user_id, kind),
            )
        conn.commit()
    return approval_id


def _executed_at(approval_id: str, user_id: str):
    """Read the column straight from the table — the repository's row mapper
    does not expose executedAt, and this invariant is about the STORED state."""
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "executedAt" FROM "ApprovalRequest" WHERE "id"=%s AND "userId"=%s',
                (approval_id, user_id),
            )
            row = cur.fetchone()
    assert row is not None, "approval row vanished"
    return row[0]


def test_non_transmitting_execute_releases_the_executed_claim(
    client, auth_headers, test_user_id
):
    """A document approval transmits nothing, so it must NOT stay stamped."""
    approval_id = _seed_document_approval(test_user_id)

    res = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["transmitted"] is False
    assert body["status"] != "executed"
    assert _executed_at(approval_id, test_user_id) is None, (
        "executedAt is stamped but nothing was transmitted — the exact state "
        "that made 133 approvals look actioned while 0 were ever sent"
    )


def test_a_released_approval_stays_retryable(client, auth_headers, test_user_id):
    """Nothing fired, so nothing was consumed — it must not 409 on retry."""
    approval_id = _seed_document_approval(test_user_id)

    assert client.post(f"/approvals/{approval_id}/execute", headers=auth_headers).status_code == 200
    second = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    assert second.status_code == 200, second.text
    assert second.json()["transmitted"] is False
    assert _executed_at(approval_id, test_user_id) is None


def test_stamp_is_set_iff_a_transmission_happened(client, auth_headers, test_user_id):
    approval_id = _seed_document_approval(test_user_id)
    res = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
    transmitted = res.json()["transmitted"]
    assert (_executed_at(approval_id, test_user_id) is not None) == transmitted


def test_production_invariant_no_stamped_row_without_a_transmission():
    """Whole-table invariant: no ApprovalRequest may carry executedAt unless it
    recorded a real transmission."""
    from app.db import get_connection

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "ApprovalRequest" '
                "WHERE \"executedAt\" IS NOT NULL "
                "AND COALESCE(payload->>'transmitted','false') <> 'true'"
            )
            stamped_without_send = cur.fetchone()[0]
    assert stamped_without_send == 0, (
        f"{stamped_without_send} approval(s) claim execution without a recorded transmission"
    )
