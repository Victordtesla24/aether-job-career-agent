"""MV-email-center — real emailAgent intelligence surfaced by the inbox.

These tests reproduce the Stage-1 findings BEFORE the fix (fail-before):

- MV-email-center-001: GET /workspaces/emails/inbox hardcoded ``score:0`` for
  every message; after wiring, the list ``score`` reflects the REAL per-thread
  triage score (and is honest ``null`` before any triage runs — never a fake 0).
- REV-B1 (reviewer BLOCKING): triage must NEVER fabricate a score for a thread
  the LLM did not actually score — the ``aiScore`` column stays NULL, not 0.
- MV-email-center-005: "This Week's Stats" hardcoded to zero; after wiring the
  recruiter-email + sent-approved counters reflect REAL per-user data.
- REV-B2 (reviewer BLOCKING): every stats aggregate is scoped to the calling
  user — one user's activity never leaks into another user's stats panel.
"""
from __future__ import annotations

import json as _json
import uuid

from app.agents.email_agent import EmailAgent


def _make_draft(client, auth_headers, subject: str) -> str:
    resp = client.post(
        "/emails/draft",
        json={"subject": subject, "body": f"Body for {subject}"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _inbox(client, auth_headers) -> dict:
    resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- 001
def test_inbox_score_is_null_before_triage(client, auth_headers):
    """Honest: a thread that has never been triaged has NO score — the inbox
    must return ``score: null``, not a fabricated 0 that looks like a real
    'irrelevant' verdict."""
    _make_draft(client, auth_headers, "Untriaged recruiter")
    data = _inbox(client, auth_headers)
    msg = next(m for m in data["messages"] if m["subject"] == "Untriaged recruiter")
    assert msg["score"] is None


def test_inbox_surfaces_real_triage_score(client, auth_headers):
    """After the emailAgent triages the inbox, the list ``score`` is the REAL
    per-thread score the triage LLM produced (fixture: 88 / 60) — never the old
    hardcoded 0."""
    _make_draft(client, auth_headers, "Recruiter One")
    _make_draft(client, auth_headers, "Recruiter Two")
    triage = client.post(
        "/agents/email/run", json={"mode": "triage"}, headers=auth_headers
    )
    assert triage.status_code == 200, triage.text

    data = _inbox(client, auth_headers)
    scores = {m["score"] for m in data["messages"] if m["subject"].startswith("Recruiter")}
    # Real scores from the email_triage fixture, not 0/None.
    assert scores == {88, 60}, scores
    assert 0 not in scores and None not in scores


# --------------------------------------------------------------------- REV-B1
def test_triage_never_fabricates_score_for_unscored_thread(db_session, test_user_id):
    """The triage LLM may return an item with no score, or omit a thread's index
    entirely. Neither may be persisted as a fabricated ``aiScore = 0`` — it must
    stay NULL (the honest 'not scored' state)."""
    import time as _t

    # Three threads with strictly-decreasing createdAt so _threads()'s DESC
    # ordering is deterministic: newest → index 0, oldest → index 2.
    ids = [f"mv-b1-{uuid.uuid4().hex[:8]}-{i}" for i in range(3)]
    with db_session.cursor() as cur:
        for offset, tid in enumerate(ids):
            cur.execute(
                'INSERT INTO "EmailThread" '
                '("id","userId","subject","messages","createdAt","updatedAt") '
                "VALUES (%s,%s,%s,%s::jsonb, now() - (%s || ' seconds')::interval, now())",
                (tid, test_user_id, f"B1 thread {offset}",
                 _json.dumps([{"role": "recruiter", "body": "hi"}]), offset * 30),
            )
    db_session.commit()
    _ = _t  # (kept for clarity; timing is via SQL interval above)

    class _FakeLLM:
        def complete_json(self, *_a, **_k):
            # index 0 → real score; index 1 → item present but NO score;
            # index 2 → omitted entirely.
            return {"items": [
                {"index": 0, "category": "priority", "score": 88},
                {"index": 1, "category": "all"},
            ]}

    EmailAgent(llm=_FakeLLM())._triage(test_user_id)

    with db_session.cursor() as cur:
        cur.execute(
            'SELECT id, "aiScore", "classification" FROM "EmailThread" '
            'WHERE "userId" = %s AND id = ANY(%s)',
            (test_user_id, ids),
        )
        rows = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # ids[0] = newest = triage index 0 → real score 88.
    assert rows[ids[0]][0] == 88
    # ids[1] = index 1 → item had no score → aiScore MUST be NULL, not 0.
    assert rows[ids[1]][0] is None
    # ids[2] = index 2 → omitted → aiScore MUST be NULL, not 0.
    assert rows[ids[2]][0] is None
    # classification still falls back to the 'all' catch-all bucket (acceptable).
    assert rows[ids[0]][1] == "priority"
    assert rows[ids[1]][1] == "all"
    assert rows[ids[2]][1] == "all"


# --------------------------------------------------------------------------- 005
def test_inbox_recruiter_stat_reflects_classification(client, auth_headers):
    """stats.recruiterEmails counts the priority/followup threads (real), not a
    hardcoded 0."""
    _make_draft(client, auth_headers, "Recruiter One")
    _make_draft(client, auth_headers, "Recruiter Two")
    client.post("/agents/email/run", json={"mode": "triage"}, headers=auth_headers)
    data = _inbox(client, auth_headers)
    # fixture → one priority + one followup = 2 recruiter-relevant threads.
    assert data["stats"]["recruiterEmails"] == 2


def _seed_email_send_approval(cur, user_id: str) -> None:
    cur.execute(
        'INSERT INTO "ApprovalRequest" ("id","userId","type","status","payload","createdAt")'
        " VALUES (%s,%s,'email_send'::\"ApprovalType\",'approved'::\"ApprovalStatus\","
        "%s::jsonb, now())",
        (f"appr-{uuid.uuid4().hex[:10]}", user_id, _json.dumps({"to": "r@x.com"})),
    )


def _seed_draft_reply_run(cur, user_id: str) -> None:
    cur.execute(
        'INSERT INTO "AgentRun" ("id","userId","agentName","status","input","createdAt","completedAt")'
        " VALUES (%s,%s,'emailAgent','completed'::\"AgentRunStatus\",%s::jsonb, now(), now())",
        (f"run-{uuid.uuid4().hex[:10]}", user_id, _json.dumps({"mode": "draft_reply"})),
    )


def test_inbox_sent_approved_stat_is_real(client, auth_headers, test_user_id, db_session):
    """stats.sentApproved reflects a REAL approved email_send ApprovalRequest for
    this user, not a hardcoded 0."""
    with db_session.cursor() as cur:
        _seed_email_send_approval(cur, test_user_id)
        _seed_draft_reply_run(cur, test_user_id)
    db_session.commit()
    data = _inbox(client, auth_headers)
    assert data["stats"]["sentApproved"] >= 1
    assert data["stats"]["autoDrafted"] >= 1


# --------------------------------------------------------------------- REV-B2
def test_inbox_stats_are_user_scoped(client, auth_headers, test_user_id, db_session):
    """A second user's approved sends / draft runs must NEVER appear in this
    user's stats panel (cross-tenant isolation)."""
    # Register a real second user (FK-valid) and seed THEIR activity.
    email_b = f"mv-b2-{uuid.uuid4().hex[:8]}@example.com"
    reg = client.post("/auth/register", json={"email": email_b, "password": "Sup3rSecret"})
    assert reg.status_code == 201, reg.text
    login = client.post("/auth/login", json={"email": email_b, "password": "Sup3rSecret"})
    user_b = login.json()  # not needed further; fetch id via /auth/me
    me_b = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    user_b_id = me_b.json()["id"]
    assert user_b_id != test_user_id
    _ = user_b

    with db_session.cursor() as cur:
        # Seed 2 approved sends + 2 draft runs for user B ONLY.
        for _ in range(2):
            _seed_email_send_approval(cur, user_b_id)
            _seed_draft_reply_run(cur, user_b_id)
    db_session.commit()

    data = _inbox(client, auth_headers)  # inbox for user A
    # User A has no activity of their own → their stats must be 0, unaffected by B.
    assert data["stats"]["sentApproved"] == 0
    assert data["stats"]["autoDrafted"] == 0
