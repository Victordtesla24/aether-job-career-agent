"""CLI-004 + CLI-006 — sales-agent overview metrics honesty.

CLI-004 (MET-F-01, updated ADM-004): ``replyRate`` is null only when no
distinct sent email thread exists — there is then no denominator. Once a
real send is on the books, inbound reply detection writes ``outcome='replied'``
rows, so a numeric rate (including 0.0) is a measurement, not a fabrication.
The module contract remains: null, not 0, when the rate is genuinely not
observable.

CLI-006 (MET-F-03): ``signups`` must count the same population as
/admin/metrics/executive (non-deleted, non-admin) — the overview previously
included admin accounts, so two admin screens disagreed (6 vs 5) about the
same number.
"""
from __future__ import annotations

import uuid

from app.repositories.sales import SalesRepository


def test_reply_rate_is_numeric_once_a_real_send_exists(repo_factory=None):
    repo = SalesRepository()
    thread = f"t-cli004-{uuid.uuid4().hex[:12]}"
    repo.record_outreach(
        channel="email",
        outcome="sent",
        gmail_thread_id=thread,
        gmail_message_id=f"m-{uuid.uuid4().hex[:12]}",
        recipient=f"cli004-{uuid.uuid4().hex[:8]}@example.com",
    )
    data = repo.overview()
    assert data["emailsSent"] >= 1
    assert data["replyRate"] is not None, (
        "replyRate must be measurable once a sent thread exists — "
        "ADM-004 observes replies, so 0.0 is a real zero, not a guess"
    )
    assert 0.0 <= float(data["replyRate"]) <= 1.0


def test_signups_excludes_admin_accounts_matching_executive_metrics(
    client, auth_headers, promote_user_to_admin
):
    repo = SalesRepository()
    before = int(repo.overview()["signups"])

    # Register a fresh user → +1 signup.
    email = f"cli006-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "Cli006Test1!", "name": "CLI 006"},
    )
    assert r.status_code in (200, 201), r.text
    uid = r.json().get("user", {}).get("id") or r.json().get("id")
    assert uid
    assert int(repo.overview()["signups"]) == before + 1

    # Promote them to admin → they are staff now, not a signup.
    promote_user_to_admin(uid)
    assert int(repo.overview()["signups"]) == before, (
        "admin accounts must not be counted as signups — the executive "
        "dashboard already excludes them and the two screens must agree"
    )
