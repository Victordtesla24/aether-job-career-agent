"""MANUAL-VERIFICATION cluster J5 — backend correctness / validation / idempotency.

Fail-before / pass-after coverage for six independent backend defects:

* MV-agents-002       negative ?limit must be a structured 422, never a raw 500.
* MV-networking-007   an outreach task must not link a nonexistent/other-user
                      contact; deleting a contact must not leave orphan tasks.
* MV-story-bank-006   storyExtractor must ground on the user's OWN resume text,
                      not a fixed operator-configured PDF.
* MV-job-discovery-001 the ATS engine must not surface URL fragments / anti-scrape
                      honeypot gibberish / EEO boilerplate as skills, and must
                      score two contrasting jobs distinctly (non-degenerate).
* MV-approval-modal-010 /approvals/{id}/execute must be idempotent — a sequential
                      double-execute of an email_send yields exactly ONE real send.
* MV-admin-settings-002 an unauthenticated /admin/settings POST must be 401 for
                      EVERY body shape, including syntactically-broken JSON.
"""
from __future__ import annotations

import uuid

from app.db import get_connection, new_id


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _promote_admin(client) -> dict[str, str]:
    """Register + login a user and promote it to admin; return auth headers."""
    from app.repositories.admin import _ensure_admin_schema

    email = f"admin-mvj-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/auth/register", json={"email": email, "password": "Passw0rd1"})
    login = client.post("/auth/login", json={"email": email, "password": "Passw0rd1"})
    body = login.json()
    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (body["userId"],))
        conn.commit()
    return {"Authorization": f"Bearer {body['access_token']}"}


def _seed_job(user_id: str, description: str) -> str:
    job_id = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Job"
                   ("id","userId","title","company","location","remote","description",
                    "requirements","source","sourceUrl","updatedAt")
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                (job_id, user_id, "Senior Backend Engineer", "Acme", "Sydney NSW",
                 True, description, "[]", "remoteok", f"https://example.com/{job_id}"),
            )
        conn.commit()
    return job_id


# --------------------------------------------------------------------------- #
# MV-agents-002 — negative limit
# --------------------------------------------------------------------------- #
def test_agents_runs_negative_limit_is_422_not_500(client, auth_headers):
    resp = client.get("/agents/runs?limit=-5", headers=auth_headers)
    assert resp.status_code == 422, resp.text
    assert "detail" in resp.json()


def test_agents_runs_zero_and_large_limits_still_ok(client, auth_headers):
    assert client.get("/agents/runs?limit=0", headers=auth_headers).status_code == 200
    assert client.get("/agents/runs?limit=99999", headers=auth_headers).status_code == 200


# --------------------------------------------------------------------------- #
# MV-networking-007 — outreach FK / cascade
# --------------------------------------------------------------------------- #
def test_outreach_rejects_nonexistent_contact(client, auth_headers):
    resp = client.post(
        "/networking/outreach",
        json={"contact_id": "does-not-exist-mv-j5", "type": "message", "message": "hi"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text
    # Honest structured error, never a raw psycopg FK-violation string.
    assert "psycopg" not in resp.text.lower()
    assert "foreign key" not in resp.text.lower()


def test_outreach_rejects_other_users_contact(client, auth_headers):
    other = {"email": f"other-{uuid.uuid4().hex[:8]}@example.com", "password": "Passw0rd1"}
    assert client.post("/auth/register", json=other).status_code == 201
    otok = client.post("/auth/login", json=other).json()["access_token"]
    oheaders = {"Authorization": f"Bearer {otok}"}
    c = client.post("/networking/contacts", json={"name": "Foreign"}, headers=oheaders)
    assert c.status_code == 201
    foreign_id = c.json()["id"]
    resp = client.post(
        "/networking/outreach",
        json={"contact_id": foreign_id, "type": "message"},
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_delete_contact_leaves_no_orphan_outreach(client, auth_headers):
    c = client.post("/networking/contacts", json={"name": "Cascade"}, headers=auth_headers)
    assert c.status_code == 201
    cid = c.json()["id"]
    t = client.post(
        "/networking/outreach",
        json={"contact_id": cid, "type": "message", "message": "hi"},
        headers=auth_headers,
    )
    assert t.status_code == 201, t.text
    assert client.delete(f"/networking/contacts/{cid}", headers=auth_headers).status_code == 204
    remaining = client.get("/networking/outreach", headers=auth_headers).json()
    assert all(o["contactId"] != cid for o in remaining), remaining


# --------------------------------------------------------------------------- #
# MV-story-bank-006 — extraction grounds on the user's OWN resume
# --------------------------------------------------------------------------- #
def test_story_extractor_grounds_on_user_resume(client, auth_headers, test_user_id):
    from app.agents.story_extractor import StoryExtractorAgent
    from app.repositories.resume import ResumeRepository

    marker = "ZZUNIQUEUSERRESUMEMARKERJ5"
    ResumeRepository().create(
        test_user_id,
        {"raw_text": f"{marker}\nLed a team and improved delivery by 20 percent.",
         "bullets": [], "contact": {}},
        "hashj5",
    )
    captured: dict[str, str] = {}

    class _FakeLLM:
        def complete_json(self, prompt_name, system, user, **kwargs):  # noqa: ANN001
            captured["user"] = user
            return {"stories": []}

    StoryExtractorAgent(llm=_FakeLLM()).run(test_user_id)
    assert marker in captured.get("user", ""), (
        "storyExtractor did not ground on the user's own resume text"
    )


# --------------------------------------------------------------------------- #
# MV-job-discovery-001 — ATS engine garbage-token filtering + score distinctness
# --------------------------------------------------------------------------- #
def test_ats_engine_drops_garbage_tokens():
    from app.services.ats_engine import ATSEngine

    resume = "Senior Python engineer. Django, PostgreSQL, AWS, FastAPI. 6 years."
    jd = (
        "Senior Python Engineer. Required: Python, Django, PostgreSQL, FastAPI. "
        "See cdn.openai.com for details. tag RMjA4LjEyMi44LjEx when applying. "
        "We provide accommodations for applicants with a disability."
    )
    score = ATSEngine().score(resume, jd)
    all_kw = {k.lower() for k in (score.matched_keywords + score.missing_keywords)}
    assert "cdn.openai.com" not in all_kw
    assert "rmja4ljeymi44ljex" not in all_kw
    assert "accommodations" not in all_kw
    assert "disability" not in all_kw
    # Real skills survive the filter.
    assert all_kw & {"python", "django", "postgresql", "fastapi"}


def test_ats_noise_filter_preserves_versioned_tech():
    # Regression guard: legitimate versioned/abbreviated tech tokens must NOT be
    # mistaken for gibberish by the digit-run heuristic.
    from app.services.ats_engine import _is_noise_token

    good_tokens = (
        "python3", "log4j", "log4j2", "oauth2", "k8s", "i18n", "a11y", "node.js", "asp.net",
    )
    for good in good_tokens:
        assert not _is_noise_token(good), good
    for junk in ("cdn.openai.com", "rmja4ljeymi44ljex", "foo.bar.baz.io"):
        assert _is_noise_token(junk), junk


def test_fit_scores_are_distinct_for_contrasting_jobs():
    from app.services.ats_engine import ATSEngine

    resume = "Senior Python backend engineer. Django, FastAPI, PostgreSQL, AWS. 7 years."
    jd_match = "Senior Python Backend Engineer. Python, Django, FastAPI, PostgreSQL, AWS."
    jd_other = "Pastry chef. Croissants, viennoiserie, bakery inventory, front-of-house."
    engine = ATSEngine()
    s_match = engine.score(resume, jd_match).overall
    s_other = engine.score(resume, jd_other).overall
    assert s_match > s_other, (s_match, s_other)
    assert s_match >= 60.0
    assert s_other <= 40.0


def test_insights_skillgap_not_garbage(client, auth_headers, test_user_id):
    jid = _seed_job(
        test_user_id,
        "Python and Django backend role. See cdn.openai.com for details. "
        "tag RMjA4LjEyMi44LjEx when applying. Accommodations for disability.",
    )
    body = client.get(f"/jobs/{jid}/insights", headers=auth_headers).json()
    assert body["scored"] is True, body
    displayed = [s.lower() for s in body["missingSkills"] + body["matchedSkills"]]
    for junk in ("cdn.openai.com", "rmja4ljeymi44ljex", "accommodations"):
        assert junk not in displayed, (junk, displayed)
    assert (body["skillGap"] or "").lower() not in (
        "cdn.openai.com", "rmja4ljeymi44ljex", "accommodations",
    )


# --------------------------------------------------------------------------- #
# MV-approval-modal-010 — execute idempotency (exactly-one real send)
# --------------------------------------------------------------------------- #
def test_execute_email_send_is_idempotent(client, auth_headers, test_user_id, monkeypatch):
    from app.repositories.gmail_account import GmailAccountRepository

    repo = GmailAccountRepository()
    repo.upsert_account(
        test_user_id, account_email="me@gmail.com", refresh_token="r-xyz", scopes="gmail.send"
    )
    calls = {"n": 0}

    def _fake_send(self, **kwargs):  # noqa: ANN001
        calls["n"] += 1
        return {"id": f"gmail-msg-{calls['n']}", "threadId": "T"}

    monkeypatch.setattr("app.services.gmail_service.GmailService.send", _fake_send)
    try:
        run = client.post(
            "/agents/email/run",
            json={"mode": "send", "to": "recruiter@acme.com", "subject": "S", "body": "B"},
            headers=auth_headers,
        )
        assert run.status_code == 200, run.text
        approval_id = run.json()["approval_id"]
        assert client.post(
            f"/approvals/{approval_id}/approve", headers=auth_headers
        ).status_code == 200
        first = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "sent"
        second = client.post(f"/approvals/{approval_id}/execute", headers=auth_headers)
        assert second.status_code == 409, second.text
        assert calls["n"] == 1, f"email was sent {calls['n']} times, expected exactly 1"
    finally:
        repo.disconnect(test_user_id)


def test_execute_non_email_approval_still_succeeds_once(client, auth_headers):
    from app.repositories.approval import ApprovalRepository
    from app.security import decode_access_token

    uid = decode_access_token(auth_headers["Authorization"].removeprefix("Bearer "))["userId"]
    approval = ApprovalRepository().create(uid, "application_submit", {"kind": "test"})
    assert client.post(
        f"/approvals/{approval['id']}/approve", headers=auth_headers
    ).status_code == 200
    first = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "executed"
    second = client.post(f"/approvals/{approval['id']}/execute", headers=auth_headers)
    assert second.status_code == 409, second.text


# --------------------------------------------------------------------------- #
# MV-admin-settings-002 — auth gates before body parsing for any body shape
# --------------------------------------------------------------------------- #
def test_admin_settings_malformed_json_unauth_is_401(client):
    resp = client.post(
        "/admin/settings",
        content="not-json-at-all",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401, resp.text


def test_admin_settings_wrong_type_unauth_is_401(client):
    resp = client.post(
        "/admin/settings",
        json={"signupEnabled": "not-a-bool-xyz"},
    )
    assert resp.status_code == 401, resp.text


def test_admin_settings_valid_body_ok_for_admin(client):
    headers = _promote_admin(client)
    resp = client.post("/admin/settings", json={"signupEnabled": True}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["signupEnabled"] is True


def test_admin_settings_malformed_json_authed_is_422(client):
    headers = _promote_admin(client)
    resp = client.post(
        "/admin/settings",
        content="not-json-at-all",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert resp.status_code == 422, resp.text
