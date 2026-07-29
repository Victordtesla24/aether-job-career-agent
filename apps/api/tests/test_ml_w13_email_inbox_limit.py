"""W-13 (QA #2, wave-3.5): GET /workspaces/emails/inbox returned EVERY thread
with its FULL latest-message body on every load — measured 723KB / ~148
threads, 5.62s cold. The list view never needs more than a snippet per
thread and never needs more than a bounded, most-recent page.

Fail-before / pass-after tests for the fix:
  - default (no query params) bounds to the 50 most-recently-updated threads
    and truncates each message's ``body`` to the same snippet already used
    for ``preview`` (no unbounded full-body fan-out).
  - ``limit`` query param controls the page size (default 50, max 200);
    out-of-range values are rejected (422), never silently clamped or
    silently serving something else.
  - ``stats.received`` / ``stats.recruiterEmails`` still reflect the REAL
    total across the whole mailbox, not just the bounded page (never a
    regression that undercounts a large inbox).
  - the detail path is NOT broken: ``?thread_id=<id>`` still returns that
    thread's real, full, untruncated body — scoped to the calling user only.
"""
from __future__ import annotations

import json as _json
import uuid


def _seed_thread(cur, user_id: str, thread_id: str, *, body: str, seconds_ago: int) -> None:
    cur.execute(
        'INSERT INTO "EmailThread" '
        '("id","userId","subject","messages","createdAt","updatedAt") '
        "VALUES (%s,%s,%s,%s::jsonb, "
        "now() - (%s || ' seconds')::interval, now() - (%s || ' seconds')::interval)",
        (
            thread_id,
            user_id,
            f"Subject {thread_id}",
            _json.dumps([{"role": "recruiter", "body": body}]),
            seconds_ago,
            seconds_ago,
        ),
    )


def test_inbox_default_bounds_to_50_most_recent_with_truncated_body(
    client, auth_headers, test_user_id, db_session
):
    """55 threads exist; the default response must contain only the 50 most
    recently updated ones, each with `body` truncated to the `preview`
    snippet length (never the full stored body)."""
    long_body = "X" * 500
    ids = [f"w13-bulk-{uuid.uuid4().hex[:8]}-{i}" for i in range(55)]
    with db_session.cursor() as cur:
        for offset, tid in enumerate(ids):
            # offset 0 -> most recent (0s ago); offset 54 -> oldest (54*10s ago).
            _seed_thread(cur, test_user_id, tid, body=long_body, seconds_ago=offset * 10)
    db_session.commit()

    resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["messages"]) == 50, (
        f"expected the default page bounded to 50, got {len(data['messages'])}"
    )

    returned_ids = {m["id"] for m in data["messages"]}
    expected_most_recent_50 = set(ids[:50])
    assert returned_ids == expected_most_recent_50, (
        "default page must be the 50 MOST RECENTLY UPDATED threads, not an "
        "arbitrary/oldest slice"
    )

    for m in data["messages"]:
        assert len(m["body"]) <= 120, (
            f"list-view body must be truncated to a snippet, got {len(m['body'])} chars"
        )
        assert m["body"] == m["preview"], "list body must match the existing preview snippet"

    # The real total across the WHOLE mailbox, not just the bounded page.
    assert data["stats"]["received"] == 55, data["stats"]


def test_inbox_limit_param_is_honored_and_bounded(client, auth_headers, test_user_id, db_session):
    ids = [f"w13-lim-{uuid.uuid4().hex[:8]}-{i}" for i in range(10)]
    with db_session.cursor() as cur:
        for offset, tid in enumerate(ids):
            _seed_thread(cur, test_user_id, tid, body="short body", seconds_ago=offset * 5)
    db_session.commit()

    resp = client.get("/workspaces/emails/inbox?limit=3", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["messages"]) == 3

    # Out-of-range limit is rejected, never silently coerced.
    too_high = client.get("/workspaces/emails/inbox?limit=201", headers=auth_headers)
    assert too_high.status_code == 422, too_high.text

    too_low = client.get("/workspaces/emails/inbox?limit=0", headers=auth_headers)
    assert too_low.status_code == 422, too_low.text

    # limit=200 (the max) is accepted.
    at_max = client.get("/workspaces/emails/inbox?limit=200", headers=auth_headers)
    assert at_max.status_code == 200, at_max.text


def test_inbox_thread_id_returns_full_untruncated_body(
    client, auth_headers, test_user_id, db_session
):
    """The detail path must not be broken by the list bound: fetching one
    thread by id returns its REAL, full body — never the truncated snippet."""
    full_body = "Recruiter message. " * 30  # > 120 chars
    tid = f"w13-detail-{uuid.uuid4().hex[:8]}"
    with db_session.cursor() as cur:
        _seed_thread(cur, test_user_id, tid, body=full_body, seconds_ago=0)
    db_session.commit()

    # Default list call: this thread's body comes back truncated.
    listed = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    listed_msg = next(m for m in listed.json()["messages"] if m["id"] == tid)
    assert listed_msg["body"] != full_body
    assert len(listed_msg["body"]) <= 120

    # Detail fetch by thread_id: full, untruncated content.
    detail = client.get(f"/workspaces/emails/inbox?thread_id={tid}", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    detail_data = detail.json()
    assert len(detail_data["messages"]) == 1
    assert detail_data["messages"][0]["id"] == tid
    assert detail_data["messages"][0]["body"] == full_body


def test_inbox_thread_id_is_scoped_to_the_calling_user(client, auth_headers, db_session):
    """A thread_id belonging to a DIFFERENT user must never leak into this
    user's detail fetch (cross-tenant isolation)."""
    other_user_id = f"w13-other-{uuid.uuid4().hex[:8]}"
    tid = f"w13-secret-{uuid.uuid4().hex[:8]}"
    with db_session.cursor() as cur:
        # Insert a real user row so the FK on EmailThread.userId is satisfiable.
        cur.execute(
            'INSERT INTO "User" ("id","email","passwordHash","createdAt","updatedAt") '
            "VALUES (%s,%s,%s, now(), now())",
            (other_user_id, f"{other_user_id}@example.com", "not-a-real-hash"),
        )
        _seed_thread(cur, other_user_id, tid, body="secret recruiter body", seconds_ago=0)
    db_session.commit()

    resp = client.get(f"/workspaces/emails/inbox?thread_id={tid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["messages"] == []


def test_inbox_full_param_returns_untruncated_bodies_for_the_bounded_set(
    client, auth_headers, test_user_id, db_session
):
    """The `full=1` escape hatch returns untruncated bodies without needing a
    specific thread_id."""
    full_body = "Recruiter message. " * 30
    tid = f"w13-full-{uuid.uuid4().hex[:8]}"
    with db_session.cursor() as cur:
        _seed_thread(cur, test_user_id, tid, body=full_body, seconds_ago=0)
    db_session.commit()

    resp = client.get("/workspaces/emails/inbox?full=1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    msg = next(m for m in resp.json()["messages"] if m["id"] == tid)
    assert msg["body"] == full_body


def test_inbox_no_params_shape_is_backward_compatible(client, auth_headers):
    """No query params -> identical top-level shape to before the fix."""
    resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in ("accounts", "stats", "followUps", "messages", "recruiterProfile"):
        assert key in data
    for key in ("received", "recruiterEmails", "autoDrafted", "sentApproved", "followUpsSent", "avgResponseHrs"):
        assert key in data["stats"]
