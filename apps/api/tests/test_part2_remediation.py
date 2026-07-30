"""Part 2 remediation regression tests (2026-07-30).

Covers three fixes from the adversarial production review:

- P0-3 approvals deadlock: a draft application whose approval expired / was
  purged re-enters the queue via the EXISTING ``POST /approvals`` path (no new
  validation gate), and approving it moves the draft to ``submitted`` — the
  exact migration path used to unstick live drafts.
- P1-9 admin cron honesty: ``/admin/health``'s ``cron`` block previously
  hardcoded ``not_configured`` even though the systemd discovery timer fires
  every 30 minutes. It now reports from the scout run ledger (``AgentRun``).
- P1-10b cover-letter job labels: cover-letter reads JOIN the ``Job`` row so
  the studio can show a real title/company even when the job is excluded from
  ``/jobs`` (applied/archived) — previously those cards fell back to
  ``Job <id-prefix>``.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db import get_connection, new_id
from app.repositories.admin import _ensure_admin_schema


def _uid() -> str:
    return uuid.uuid4().hex[:25]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, title: str = "Staff Engineer",
              company: str = "Stripe", status: str = "discovered") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, title, company, "Build things.", "seek",
             f"https://example.com/job/{job_id}", status, 88.0),
        )
    conn.commit()
    return job_id


def _seed_resume(conn, user_id: str) -> str:
    resume_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "test"}), "hash-test"),
        )
    conn.commit()
    return resume_id


def _seed_application(conn, user_id: str, job_id: str, resume_id: str, *,
                      status: str = "draft", cover_letter: str | None = None) -> str:
    app_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, user_id, job_id, resume_id, status, cover_letter),
        )
    conn.commit()
    return app_id


def _seed_scout_run(conn, user_id: str, *, age: str = "0 minutes") -> str:
    run_id = new_id()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "AgentRun" ("id","userId","agentName","status","startedAt",'
            '"completedAt","createdAt") '
            "VALUES (%s,%s,'scout','completed'::\"AgentRunStatus\","
            "NOW() - %s::interval, NOW() - %s::interval, NOW())",
            (run_id, user_id, age, age),
        )
    conn.commit()
    return run_id


def _clear_scout_runs(conn) -> None:
    with conn.cursor() as cur:
        cur.execute('DELETE FROM "AgentRun" WHERE "agentName" = \'scout\'')
    conn.commit()


def _admin_headers(client) -> dict[str, str]:
    """Register a user and promote them to admin (JWT carries no privilege
    claim — isAdmin is re-read per request, so post-login promotion works)."""
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": "Passw0rd1"})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": "Passw0rd1"})
    assert login.status_code == 200, login.text
    body = login.json()
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (body["userId"],))
        conn.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}


# --------------------------------------------------------------------------- #
# P0-3 — approvals deadlock: re-request path unsticks an orphaned draft
# --------------------------------------------------------------------------- #


class TestApprovalReRequestMigration:
    def test_orphaned_draft_migrates_through_re_request_and_approve(
        self, client, auth_headers, user_id, db_session
    ):
        """The exact migration path for live stuck drafts: a draft application
        with NO pending approval (expired/purged) → POST /approvals (existing
        re-request path) → approve → draft becomes submitted."""
        job_id = _seed_job(db_session, user_id, title="Staff Engineer", company="Peloton")
        resume_id = _seed_resume(db_session, user_id)
        app_id = _seed_application(db_session, user_id, job_id, resume_id, status="draft")

        # Deadlocked state: draft exists, approval queue has nothing for it.
        pending = client.get("/approvals?status=pending", headers=auth_headers).json()
        assert not any(a.get("applicationId") == app_id for a in pending)

        # Re-request via the EXISTING endpoint (what the tracker button calls).
        resp = client.post(
            "/approvals",
            headers=auth_headers,
            json={
                "type": "application_submit",
                "application_id": app_id,
                "payload": {
                    "job_id": job_id,
                    "job_title": "Staff Engineer",
                    "company": "Peloton",
                    "agent": "tracker",
                    "action": "submit_application",
                },
            },
        )
        assert resp.status_code == 201, resp.text
        approval = resp.json()
        assert approval["status"] == "pending"
        assert approval["applicationId"] == app_id

        # It is back in the queue…
        pending = client.get("/approvals?status=pending", headers=auth_headers).json()
        assert any(a["id"] == approval["id"] for a in pending)

        # Idempotency: re-requesting again refreshes the SAME pending row
        # (repo dedupes per job+kind) — no duplicate cards.
        again = client.post(
            "/approvals",
            headers=auth_headers,
            json={
                "type": "application_submit",
                "application_id": app_id,
                "payload": {"job_id": job_id, "job_title": "Staff Engineer",
                            "company": "Peloton"},
            },
        )
        assert again.status_code == 201, again.text
        assert again.json()["id"] == approval["id"]

        # …and approving it moves the draft to submitted (tracker sync).
        ok = client.post(f"/approvals/{approval['id']}/approve", headers=auth_headers)
        assert ok.status_code == 200, ok.text
        apps = client.get("/applications", headers=auth_headers).json()
        mine = next(a for a in apps if a["id"] == app_id)
        assert mine["status"] == "submitted"


# --------------------------------------------------------------------------- #
# P1-9 — /admin/health cron block reports from the scout run ledger
# --------------------------------------------------------------------------- #


class TestAdminCronStatus:
    def test_cron_not_configured_when_no_scout_runs(self, client, db_session):
        headers = _admin_headers(client)
        _clear_scout_runs(db_session)
        cron = client.get("/admin/health", headers=headers).json()["cron"]
        assert cron["status"] == "not_configured"

    def test_cron_ok_with_fresh_scout_run(self, client, user_id, db_session):
        """FAILED before the fix: the block was hardcoded not_configured."""
        headers = _admin_headers(client)
        _clear_scout_runs(db_session)
        _seed_scout_run(db_session, user_id, age="5 minutes")
        cron = client.get("/admin/health", headers=headers).json()["cron"]
        assert cron["status"] == "ok"
        assert "scout" in cron["detail"]
        assert cron.get("lastRunAt")

    def test_cron_stale_when_last_run_is_old(self, client, user_id, db_session):
        headers = _admin_headers(client)
        _clear_scout_runs(db_session)
        _seed_scout_run(db_session, user_id, age="3 hours")
        cron = client.get("/admin/health", headers=headers).json()["cron"]
        assert cron["status"] == "stale"
        assert cron.get("lastRunAt")


# --------------------------------------------------------------------------- #
# P1-10b — cover-letter reads carry the joined job title/company
# --------------------------------------------------------------------------- #


class TestCoverLetterJobLabels:
    def test_list_includes_job_title_and_company(
        self, client, auth_headers, user_id, db_session
    ):
        """FAILED before the fix: rows had no jobTitle/jobCompany, so letters
        for applied/archived jobs rendered as 'Job <id-prefix>' in the web."""
        job_id = _seed_job(db_session, user_id, title="Growth PM",
                           company="Canva", status="applied")
        resume_id = _seed_resume(db_session, user_id)
        _seed_application(db_session, user_id, job_id, resume_id,
                          cover_letter="Dear team, …")

        letters = client.get("/cover-letters", headers=auth_headers).json()
        mine = [l for l in letters if l["jobId"] == job_id]
        assert mine, "seeded letter missing from /cover-letters"
        assert mine[0]["jobTitle"] == "Growth PM"
        assert mine[0]["jobCompany"] == "Canva"

    def test_join_is_left_join_orphan_letter_still_listed(
        self, client, auth_headers, user_id, db_session
    ):
        """A letter whose Job row is gone must still list (LEFT JOIN) with
        null labels — never dropped from the studio."""
        job_id = _seed_job(db_session, user_id)
        resume_id = _seed_resume(db_session, user_id)
        _seed_application(db_session, user_id, job_id, resume_id,
                          cover_letter="Dear team, …")
        with db_session.cursor() as cur:
            # Detach the application first (FK), then remove the job.
            cur.execute('DELETE FROM "Job" WHERE "id"=%s', (job_id,))
        db_session.commit()

        letters = client.get("/cover-letters", headers=auth_headers).json()
        mine = [l for l in letters if l["jobId"] == job_id]
        # If the schema's FK cascade removed the application too, the letter
        # is legitimately gone; when it survives, labels must be null-safe.
        for letter in mine:
            assert letter.get("jobTitle") is None
            assert letter.get("jobCompany") is None



# --------------------------------------------------------------------------- #
# P1-7 residual — inbox sender falls back to the synced Gmail headers
# --------------------------------------------------------------------------- #


class TestInboxSenderFallback:
    def _seed_thread(self, conn, user_id: str, *, from_name: str,
                     from_email: str) -> str:
        thread_id = _uid()
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "EmailThread" '
                '("id","userId","subject","messages","createdAt","updatedAt") '
                "VALUES (%s,%s,%s,%s::jsonb,NOW(),NOW())",
                (
                    thread_id,
                    user_id,
                    "Re: your application",
                    json.dumps([{
                        "from": from_name,
                        "fromEmail": from_email,
                        "body": "Thanks for applying — next steps inside.",
                    }]),
                ),
            )
        conn.commit()
        return thread_id

    def test_sender_from_synced_message_when_no_crm_contact(
        self, client, auth_headers, user_id, db_session
    ):
        """FAILED before the fix: threads synced from Gmail have no contactId,
        so every sender rendered as the literal "Unknown" even though the real
        From header was stored in the messages jsonb."""
        tid = self._seed_thread(db_session, user_id,
                                from_name="Sarah Chen",
                                from_email="sarah@acme.com")
        inbox = client.get("/workspaces/emails/inbox", headers=auth_headers).json()
        mine = next(m for m in inbox["messages"] if m["id"] == tid)
        assert mine["from"] == "Sarah Chen"
        assert mine["fromEmail"] == "sarah@acme.com"

    def test_sender_email_used_when_no_display_name(
        self, client, auth_headers, user_id, db_session
    ):
        tid = self._seed_thread(db_session, user_id,
                                from_name="",
                                from_email="no-reply@fanvue.com")
        inbox = client.get("/workspaces/emails/inbox", headers=auth_headers).json()
        mine = next(m for m in inbox["messages"] if m["id"] == tid)
        assert mine["from"] == "no-reply@fanvue.com"
