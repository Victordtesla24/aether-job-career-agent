"""ML-admin-003 (HIGH) + platform NUL-byte-in-GET-query-param sweep.

## Assignment brief claim (production evidence)

``uat/reports/evidence/gold-master-v2/screens/admin-portal-screen-test.md``
records, reproduced TWICE against the LIVE production deployment:

    GET /api/admin/users?q=foo%00bar    -> 500 Internal Server Error
    GET /api/admin/users?plan=free%00x  -> 500 Internal Server Error

and frames this as "a DIFFERENT code path from the shared guard already
shipped in apps/api/app/db.py, which covers user-supplied strings on WRITE
paths only."

## RCA against the CURRENT repository (this file's actual finding)

Reading ``apps/api/app/db.py`` shows the shared guard is NOT scoped to write
paths at all: ``get_connection()`` installs ``_NulByteGuardCursor`` as the
``cursor_factory`` on *every* connection it yields (db.py ~line 150), and
that cursor class overrides ``execute``/``executemany`` unconditionally —
the interception happens at the psycopg2-cursor layer, one seam shared by
every ``cur.execute(...)`` call in the codebase (237+ call sites per its own
docstring), on a SELECT/WHERE lookup exactly as much as an INSERT/UPDATE.
``apps/api/app/repositories/admin.py::list_users`` opens its connection via
this same ``get_connection()`` (no bypass, no second connection helper
exists anywhere in ``apps/api/app`` — verified: the only
``psycopg2.connect(`` call site in the whole app is inside ``get_connection``
itself), so a NUL byte in ``q``/``plan`` reaches the *same* guarded
``.execute()`` as everything else.

Empirically (this file, run under the repo's current HEAD against the
``aether_test`` schema): ``GET /admin/users?q=<NUL>`` and ``?plan=<NUL>``
both return a clean 422 with the shared guard's honest message — never a
500 — confirming the code-level fix already covers this path.

Cross-referencing the git history resolves the apparent contradiction: the
shared guard was committed at ``e78f51d`` ("shared NUL-byte guard,
admin/billing hardening") *before* the admin-portal screen-test that
produced the 500s in ``admin-portal-screen-test.md``. That screen-test ran
against production, which had not yet been redeployed with ``e78f51d`` at
the time — the evidence file's own language even says so explicitly:
"consistent with — and extending — the platform's already-known,
fix-verified-but-undeployed NUL-byte defect class". So ML-admin-003 as
literally described (a distinct, unguarded code path) does **not**
reproduce against the current repository: it is a DEPLOYMENT gap (an
already-committed fix not yet shipped to production), not a code gap. The
tests below are written as the honest contract the fixer/deployer must keep
true; they are expected to (and do) PASS today, and they exist to (a) lock
in the current-code-correct behaviour as a regression guard and (b) make
the "unexpected pass / already fixed, not yet deployed" finding
independently reproducible instead of asserted on trust.

## Sweep — endpoints checked

Every ``@router.get`` handler in ``apps/api/app/routers/*.py`` accepting a
free-form (unvalidated) string as a filter, discovered by grepping for
``Query(`` and bare ``str | None`` GET parameters, split into two buckets:

FREE-TEXT (reaches SQL unvalidated -> exercises the shared cursor guard;
covered below with a NUL-byte parametrized case + a non-NUL sanity case
each):
  * ``GET /admin/users?q=``            (apps/api/app/repositories/admin.py)
  * ``GET /admin/users?plan=``         (apps/api/app/repositories/admin.py)
  * ``GET /networking/contacts?company=``   (apps/api/app/routers/networking.py)
  * ``GET /networking/outreach?contact_id=`` (apps/api/app/routers/networking.py)
  * ``GET /workspaces/emails/inbox?thread_id=`` (apps/api/app/routers/workspaces.py)
  * ``GET /interviews?application_id=``      (apps/api/app/routers/interviews.py)

ENUM-VALIDATED (rejected by an application-level allowlist check BEFORE
reaching SQL at all — the same correct pattern the brief points to in
``analytics.py``'s ``_period_clause``; a NUL byte just fails the
"not in {allowed values}" test like any other bad value, so these were
never at risk of the 500 shape and are covered by ONE confirmatory test
each, not full sanity+NUL pairs):
  * ``GET /jobs?status=``                (apps/api/app/routers/jobs.py)
  * ``GET /jobs?source=``                (apps/api/app/routers/jobs.py)
  * ``GET /applications?app_status=``    (apps/api/app/routers/applications.py)
  * ``GET /interviews?app_status=``      (apps/api/app/routers/interviews.py)
  * ``GET /approvals?status=``           (apps/api/app/routers/approvals.py)
  * ``GET /networking/contacts?stage=``       (apps/api/app/routers/networking.py)
  * ``GET /networking/outreach?task_status=`` (apps/api/app/routers/networking.py)

## Sweep — NOT covered (explicit, not silently assumed closed)

  * ``apps/api/app/routers/stories.py``, ``cover_letters.py``, ``agents.py``,
    ``analytics.py`` — all on this assignment's explicit "stay out, other
    agents active" list; not touched or exercised here at all.
    ``analytics.py``'s ``?period=`` was already independently verified
    correct (422, honest message) by the assignment brief itself and is not
    re-tested here.
  * Any admin endpoint whose only query params are ``int``/``bool``
    (``/admin/audit-log?limit=&offset=``, ``/admin/health``, ``/admin/spend``)
    — a NUL byte in an int/bool-typed query param is rejected by FastAPI's
    own request validation (422) before any application code runs, so there
    is no code path to test.
  * POST/PATCH/DELETE body fields — out of scope for this GET-query-param
    finding; write-path NUL handling was already covered by the
    ML-settings-006 / ML-RESUME-001 tests referenced in db.py's own
    docstring.
"""
from __future__ import annotations

import json
import uuid

import pytest

from app.db import get_connection


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _register(client, email: str, password: str = "Passw0rd1") -> tuple[str, str]:
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code in (201, 409), r.text
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return body["access_token"], body["userId"]


def _promote_to_admin(user_id: str) -> None:
    """Give a fixture-registered user isAdmin=true directly via SQL — never
    depends on the seeded 'admin' identifier (BLOCKER-001 is about to revoke
    isAdmin from the owner account and make that identifier 401)."""
    from app.repositories.admin import _ensure_admin_schema

    _ensure_admin_schema()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "User" SET "isAdmin"=true WHERE "id"=%s', (user_id,))
        conn.commit()


def _admin_headers(client) -> tuple[dict[str, str], str]:
    token, uid = _register(client, f"admin-mladmin003-{uuid.uuid4().hex[:8]}@example.com")
    _promote_to_admin(uid)
    return {"Authorization": f"Bearer {token}"}, uid


def _assert_honest_422(resp, *, endpoint: str) -> None:
    assert resp.status_code == 422, (
        f"{endpoint}: expected an honest 422 for a NUL byte in a filter "
        f"value, got {resp.status_code}: {resp.text}"
    )
    assert resp.status_code != 500, f"{endpoint}: bare 500 (ML-admin-003 shape)"
    body = resp.json()
    detail = str(body.get("detail", ""))
    # No leaked traceback / internals — matches the guard's own contract
    # (db.py's _NUL_BYTE_USER_MESSAGE) and the brief's "no traceback/internals
    # leaked in the response body" observation.
    for leak_marker in ("Traceback", "psycopg2", "File \"", "raise "):
        assert leak_marker not in resp.text, (
            f"{endpoint}: response body leaked internals ({leak_marker!r}): {resp.text}"
        )
    assert detail, f"{endpoint}: 422 with an empty/missing detail message: {resp.text}"


NUL = "\x00"


# --------------------------------------------------------------------------- #
# FREE-TEXT filters — NUL byte must 422, never 500 (parametrized sweep)
# --------------------------------------------------------------------------- #


def test_admin_users_q_nul_byte_returns_422_not_500(client):
    headers, _ = _admin_headers(client)
    resp = client.get("/admin/users", params={"q": f"foo{NUL}bar"}, headers=headers)
    _assert_honest_422(resp, endpoint="GET /admin/users?q=<NUL>")


def test_admin_users_plan_nul_byte_returns_422_not_500(client):
    headers, _ = _admin_headers(client)
    resp = client.get("/admin/users", params={"plan": f"free{NUL}x"}, headers=headers)
    _assert_honest_422(resp, endpoint="GET /admin/users?plan=<NUL>")


def test_networking_contacts_company_nul_byte_returns_422_not_500(client, auth_headers):
    resp = client.get(
        "/networking/contacts", params={"company": f"Acme{NUL}Corp"}, headers=auth_headers
    )
    _assert_honest_422(resp, endpoint="GET /networking/contacts?company=<NUL>")


def test_networking_outreach_contact_id_nul_byte_returns_422_not_500(client, auth_headers):
    resp = client.get(
        "/networking/outreach", params={"contact_id": f"abc{NUL}def"}, headers=auth_headers
    )
    _assert_honest_422(resp, endpoint="GET /networking/outreach?contact_id=<NUL>")


def test_workspaces_emails_inbox_thread_id_nul_byte_returns_422_not_500(client, auth_headers):
    resp = client.get(
        "/workspaces/emails/inbox", params={"thread_id": f"abc{NUL}def"}, headers=auth_headers
    )
    _assert_honest_422(resp, endpoint="GET /workspaces/emails/inbox?thread_id=<NUL>")


def test_interviews_application_id_nul_byte_returns_422_not_500(client, auth_headers):
    resp = client.get(
        "/interviews", params={"application_id": f"abc{NUL}def"}, headers=auth_headers
    )
    _assert_honest_422(resp, endpoint="GET /interviews?application_id=<NUL>")


# --------------------------------------------------------------------------- #
# Non-NUL sanity cases — guard against an over-broad fix breaking real
# filtering (one per FREE-TEXT endpoint above).
# --------------------------------------------------------------------------- #


def test_admin_users_q_sanity_normal_filter_still_works(client):
    headers, admin_id = _admin_headers(client)
    distinctive = f"findme{uuid.uuid4().hex[:8]}"
    _, other_uid = _register(client, f"{distinctive}@example.com")

    resp = client.get("/admin/users", params={"q": distinctive}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = {u["id"] for u in resp.json()["users"]}
    assert ids == {other_uid}, (ids, admin_id, other_uid)


def test_admin_users_plan_sanity_normal_filter_still_works(client):
    from app.repositories.billing import ensure_user_billing

    headers, admin_id = _admin_headers(client)
    ensure_user_billing(admin_id)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE "Subscription" SET "planId"=%s WHERE "userId"=%s', ("pro", admin_id))
        conn.commit()

    resp = client.get("/admin/users", params={"plan": "pro"}, headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["users"]
    assert any(u["id"] == admin_id for u in rows), rows
    assert all(u["plan"] == "pro" for u in rows), rows


def test_networking_contacts_company_sanity_normal_filter_still_works(client, auth_headers):
    distinctive_company = f"Acme{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/networking/contacts",
        json={"name": "Jamie Lee", "company": distinctive_company},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    other = client.post(
        "/networking/contacts",
        json={"name": "Alex Kim", "company": "SomeOtherCo"},
        headers=auth_headers,
    )
    assert other.status_code == 201, other.text

    resp = client.get(
        "/networking/contacts", params={"company": distinctive_company}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["company"] == distinctive_company, rows


def test_networking_outreach_contact_id_sanity_normal_filter_still_works(client, auth_headers):
    contact = client.post(
        "/networking/contacts", json={"name": "Sam Rivers"}, headers=auth_headers
    )
    assert contact.status_code == 201, contact.text
    contact_id = contact.json()["id"]
    task = client.post(
        "/networking/outreach", json={"contact_id": contact_id, "type": "message"},
        headers=auth_headers,
    )
    assert task.status_code == 201, task.text

    resp = client.get(
        "/networking/outreach", params={"contact_id": contact_id}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["contactId"] == contact_id, rows


def test_workspaces_emails_inbox_thread_id_sanity_normal_filter_still_works(client, auth_headers):
    draft = client.post(
        "/emails/draft",
        json={"subject": "Re: Staff Engineer role", "body": "Following up."},
        headers=auth_headers,
    )
    assert draft.status_code == 201, draft.text
    thread_id = draft.json()["id"]

    resp = client.get(
        "/workspaces/emails/inbox", params={"thread_id": thread_id}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {m["id"] for m in body.get("messages", [])}
    assert thread_id in ids, body


def test_interviews_application_id_sanity_normal_filter_still_works(client, auth_headers, db_session, test_user_id):
    job_id, resume_id, app_id = uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex
    with db_session.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,%s,%s,%s,'discovered'::\"JobStatus\",%s,NOW(),NOW())",
            (job_id, test_user_id, "Staff Engineer", "Stripe", "Build things.", "seek",
             f"https://example.com/job/{job_id}", 91.0),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"updatedAt") VALUES (%s,%s,1,%s,%s,NOW())',
            (resume_id, test_user_id, json.dumps({"summary": "test"}), "hash-test"),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"answers","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (app_id, test_user_id, job_id, resume_id, "interview", None),
        )
    db_session.commit()

    created = client.post(
        "/interviews",
        json={
            "application_id": app_id,
            "type": "video",
            "scheduled_at": "2026-08-01T15:00:00Z",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text

    resp = client.get("/interviews", params={"application_id": app_id}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1 and rows[0]["application_id"] == app_id, rows


# --------------------------------------------------------------------------- #
# ENUM-VALIDATED filters — confirmatory only (already safe by a DIFFERENT,
# pre-existing mechanism: an allowlist check runs BEFORE any SQL, so a NUL
# byte never reaches psycopg2 at all here — same correct pattern as
# analytics.py's ?period=). One test each; no separate sanity case needed
# since these already have dedicated coverage elsewhere in the suite.
# --------------------------------------------------------------------------- #


def test_jobs_status_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/jobs", params={"status": f"active{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /jobs?status=<NUL>")


def test_jobs_source_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/jobs", params={"source": f"seek{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /jobs?source=<NUL>")


def test_applications_app_status_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/applications", params={"app_status": f"applied{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /applications?app_status=<NUL>")


def test_interviews_app_status_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/interviews", params={"app_status": f"scheduled{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /interviews?app_status=<NUL>")


def test_approvals_status_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/approvals", params={"status": f"pending{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /approvals?status=<NUL>")


def test_networking_contacts_stage_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/networking/contacts", params={"stage": f"identified{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /networking/contacts?stage=<NUL>")


def test_networking_outreach_task_status_nul_byte_returns_422_via_allowlist_not_500(client, auth_headers):
    resp = client.get("/networking/outreach", params={"task_status": f"pending{NUL}"}, headers=auth_headers)
    _assert_honest_422(resp, endpoint="GET /networking/outreach?task_status=<NUL>")


@pytest.mark.parametrize("case", ["q", "plan"])
def test_admin_users_nul_byte_recovers_for_next_normal_request(client, case):
    """Matches the brief's own observation: 'Endpoint recovers immediately
    for the next normal request (not a lasting outage)' — the guard raises a
    per-request HTTPException, it does not poison the connection pool or
    process state."""
    headers, admin_id = _admin_headers(client)
    bad = client.get("/admin/users", params={case: f"x{NUL}y"}, headers=headers)
    assert bad.status_code == 422, bad.text

    good = client.get("/admin/users", headers=headers)
    assert good.status_code == 200, good.text
    ids = {u["id"] for u in good.json()["users"]}
    assert admin_id in ids, ids
