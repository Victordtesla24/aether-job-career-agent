"""GOLD-MASTER-V2 §8.1 (GOV-003) — canonical PATCH /applications/{id}/stage.

Ground truth (this run, orchestrator ruling GOV-003): the board already has a
fully keyboard-operable "Move to..." menu wired to the LEGACY
``POST /applications/{id}/move`` / ``POST /applications/pipeline/{job_id}/move``
endpoints (app/routers/applications.py:255,323) — that part is NOT broken.
§8.1 names a DIFFERENT, currently-nonexistent endpoint —
``PATCH /applications/{id}/stage`` — as the canonical stage-move contract; the
existing POST .../move handlers are to be refactored to DELEGATE to one shared
transition service (§13.1 forbids a second independent implementation).

Legal transition matrix (discovered from apps/web/src/components/applications/
tracker-lib.ts + app/routers/applications.py, both read this run):
  - Application-fed stages: ready(draft) / submitted / in-review(screening) /
    interview / offer. ANY transition between these five is legal, forward or
    backward (move_application docstring: "the user is the source of truth for
    their own pipeline"); same-stage is an idempotent no-op.
  - Job-fed stages (discovered / evaluating / tailoring) are a DISJOINT set —
    an application card moving to one of these is illegal (422, "Job-status-fed").
  - An application in a CLOSED status (rejected / withdrawn) cannot move at all
    (422) — _CLOSED_STATUSES in applications.py.
  - Unknown stage keys are 422.
  - A move that would create a second ACTIVE application for the same job is a
    409 conflict (RT-004 promotion guard + the partial unique index
    ``Application_user_job_active_key``), not covered by this file (already
    exercised for the legacy endpoint in test_applications_move.py; the
    canonical endpoint inherits it once it delegates to the shared service).

These tests target the endpoint the spec names. It does not exist yet, so
EVERY test below is expected to fail against current code — for the reason
recorded in each assertion message, not a stray 500/import error.
"""
from __future__ import annotations

import pytest
from test_applications_tracker import _seed_application, _uid


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _patch_stage(client, headers, app_id: str, from_stage: str, to_stage: str):
    return client.patch(
        f"/applications/{app_id}/stage",
        headers=headers,
        json={"from_stage": from_stage, "to_stage": to_stage},
    )


def _audit_rows(db_session, actor: str, action: str) -> list[tuple]:
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "targetType", "targetId", "detailJson" FROM "AdminAuditLog" '
            'WHERE "actorUserId" = %s AND "action" = %s ORDER BY "createdAt" DESC',
            (actor, action),
        )
        return cur.fetchall()


class TestStagePatchEndpointExists:
    """The endpoint itself: §8.1 names PATCH /applications/{id}/stage as the
    canonical contract. A 404 here means the route is unimplemented — that IS
    the finding this file exists to reproduce."""

    def test_requires_auth(self, client):
        resp = client.patch(
            "/applications/x/stage",
            json={"from_stage": "ready", "to_stage": "submitted"},
        )
        assert resp.status_code == 401, (
            "PATCH /applications/{id}/stage should require auth (401) like "
            f"every other mutation endpoint; got {resp.status_code} {resp.text}. "
            "A route that does not exist at all answers with a generic 404 "
            "before auth is even evaluated (FastAPI resolves routing before "
            "dependencies) -- this failure is the §8.1 canonical-endpoint gap, "
            "not an auth defect."
        )

    def test_legal_move_succeeds_and_persists(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        resp = _patch_stage(client, auth_headers, app_id, "ready", "submitted")
        assert resp.status_code == 200, (
            "expected 200 from the canonical PATCH stage endpoint (§8.1); got "
            f"{resp.status_code} {resp.text} -- PATCH /applications/{{id}}/stage "
            "does not exist yet (GOV-003)."
        )
        assert resp.json()["status"] == "submitted"
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert detail["status"] == "submitted", "stage move did not persist"

    @pytest.mark.parametrize(
        ("from_status", "from_stage", "to_stage"),
        [
            ("draft", "ready", "submitted"),
            ("submitted", "submitted", "in-review"),
            ("screening", "in-review", "interview"),
            ("interview", "interview", "offer"),
            # Backward corrections are legal per the discovered matrix.
            ("offer", "offer", "in-review"),
            ("submitted", "submitted", "ready"),
        ],
    )
    def test_legal_moves_between_app_stages(
        self,
        client,
        auth_headers,
        user_id,
        db_session,
        from_status,
        from_stage,
        to_stage,
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status=from_status)
        resp = _patch_stage(client, auth_headers, app_id, from_stage, to_stage)
        assert resp.status_code == 200, (
            f"legal move {from_stage} -> {to_stage} should be a 200; got "
            f"{resp.status_code} {resp.text}"
        )

    def test_illegal_job_fed_target_is_422_with_honest_message(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="submitted")
        resp = _patch_stage(client, auth_headers, app_id, "submitted", "discovered")
        assert resp.status_code == 422, (
            "an application card moving to a job-fed stage must be rejected "
            f"with an honest 422; got {resp.status_code} {resp.text}"
        )
        detail = resp.json().get("detail", "")
        assert "job" in str(detail).lower() or "discovered" in str(detail).lower(), (
            f"422 detail should honestly name the illegal target; got {detail!r}"
        )

    def test_closed_application_cannot_move(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="rejected")
        resp = _patch_stage(client, auth_headers, app_id, "ready", "submitted")
        assert resp.status_code == 422, (
            "a closed (rejected/withdrawn) application must not be movable via "
            f"the canonical endpoint; got {resp.status_code} {resp.text}"
        )

    def test_audit_logs_actor_from_to_timestamp(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="submitted")
        resp = _patch_stage(client, auth_headers, app_id, "submitted", "interview")
        assert resp.status_code == 200, resp.text
        rows = _audit_rows(db_session, user_id, "application.stage_move")
        assert rows, (
            "expected an application.stage_move audit row (actor/from/to/"
            "timestamp) written by the canonical PATCH endpoint"
        )
        target_type, target_id, detail = rows[0]
        assert target_type == "application"
        assert target_id == app_id
        assert detail["from"] == "submitted"
        assert detail["to"] == "interview"

    def test_owner_scoped_foreign_application_is_honest_404(
        self, client, auth_headers, db_session
    ):
        """Distinguish REAL owner-scoping from a bare 'route does not exist'
        404: a genuinely-implemented endpoint answers with the SAME
        'Application not found' detail every other application endpoint uses
        (see get_application/move_application); an unmatched route answers
        with Starlette's generic 'Not Found'."""
        other = {"email": f"other-user-{_uid()}@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        from app.repositories.user import UserRepository

        other_id = UserRepository().get_by_email(other["email"])["id"]
        foreign_app, _ = _seed_application(db_session, other_id, app_status="submitted")

        resp = _patch_stage(client, auth_headers, foreign_app, "submitted", "interview")
        assert resp.status_code == 404
        assert resp.json().get("detail") == "Application not found", (
            f"got detail={resp.json().get('detail')!r} — if this is the generic "
            "Starlette 'Not Found' the route does not exist yet at all, which "
            "is NOT the same finding as a real owner-scope check (§8.1 requires "
            "the latter: 'another user's application -> 404/403, never a silent "
            "success')."
        )


class TestLegacyMoveBackwardCompatibility:
    """§13.1 forbids a second independent implementation: once the PATCH
    endpoint exists, the legacy POST .../move routes must DELEGATE to the same
    shared transition service and keep behaving identically for their live
    callers. This is a regression guard, not a "should currently fail" test —
    the legacy endpoint already works (ground truth, this run) so it is
    expected to PASS both before and after the refactor."""

    def test_post_move_still_works_today(
        self, client, auth_headers, user_id, db_session
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status="draft")
        resp = client.post(
            f"/applications/{app_id}/move",
            headers=auth_headers,
            json={"to_stage": "submitted"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "submitted"
