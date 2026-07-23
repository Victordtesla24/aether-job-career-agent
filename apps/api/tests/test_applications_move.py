"""FEAT-B2 — Move applications (and pipeline jobs) between kanban stages.

Board contract (apps/web tracker-lib.ts): 8 columns; the first 3 are
Job-status-fed (discovered / evaluating / tailoring), the last 5 are
Application-status-fed (ready→draft, submitted→submitted, in-review→screening,
interview→interview, offer→offer). The move endpoints enforce that split
SERVER-SIDE with honest 422s and audit every transition (who/when/from→to).
"""
from __future__ import annotations

import pytest
from test_applications_tracker import _seed_application, _uid


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(conn, user_id: str, *, status: str = "discovered") -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "Platform Engineer", "Atlassian", "Build.", "seek",
             f"https://example.com/job/{job_id}", status, 88.0),
        )
    conn.commit()
    return job_id


def _move(client, headers, app_id: str, to_stage: str):
    return client.post(
        f"/applications/{app_id}/move", headers=headers, json={"to_stage": to_stage}
    )


def _audit_rows(db_session, actor: str, action: str) -> list[tuple]:
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "targetType", "targetId", "detailJson" FROM "AdminAuditLog" '
            'WHERE "actorUserId" = %s AND "action" = %s ORDER BY "createdAt" DESC',
            (actor, action),
        )
        return cur.fetchall()


class TestApplicationMove:
    def test_requires_auth(self, client):
        resp = client.post("/applications/x/move", json={"to_stage": "interview"})
        assert resp.status_code == 401

    def test_unknown_id_404(self, client, auth_headers):
        resp = _move(client, auth_headers, "does-not-exist", "interview")
        assert resp.status_code == 404

    def test_foreign_row_404(self, client, auth_headers, db_session):
        other = {"email": "other-user@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        from app.repositories.user import UserRepository

        other_id = UserRepository().get_by_email("other-user@example.com")["id"]
        foreign_app, _ = _seed_application(db_session, other_id, app_status="submitted")
        resp = _move(client, auth_headers, foreign_app, "interview")
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        ("from_status", "to_stage", "expected_status"),
        [
            ("draft", "submitted", "submitted"),
            ("submitted", "in-review", "screening"),
            ("screening", "interview", "interview"),
            ("interview", "offer", "offer"),
            # Backward corrections are legal too — user is the source of truth.
            ("offer", "in-review", "screening"),
            ("submitted", "ready", "draft"),
        ],
    )
    def test_legal_moves_between_app_stages(
        self, client, auth_headers, user_id, db_session, from_status, to_stage, expected_status
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status=from_status)
        resp = _move(client, auth_headers, app_id, to_stage)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == expected_status
        # Persisted — a fresh read agrees.
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert detail["status"] == expected_status

    def test_same_stage_is_idempotent_noop(self, client, auth_headers, user_id, db_session):
        app_id, _ = _seed_application(db_session, user_id, app_status="interview")
        resp = _move(client, auth_headers, app_id, "interview")
        assert resp.status_code == 200
        assert resp.json()["status"] == "interview"

    @pytest.mark.parametrize("to_stage", ["discovered", "evaluating", "tailoring"])
    def test_job_fed_target_is_422(self, client, auth_headers, user_id, db_session, to_stage):
        app_id, _ = _seed_application(db_session, user_id, app_status="submitted")
        resp = _move(client, auth_headers, app_id, to_stage)
        assert resp.status_code == 422
        assert "Job" in resp.json()["detail"]
        # Status untouched.
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert detail["status"] == "submitted"

    def test_unknown_stage_is_422(self, client, auth_headers, user_id, db_session):
        app_id, _ = _seed_application(db_session, user_id, app_status="submitted")
        resp = _move(client, auth_headers, app_id, "bogus-stage")
        assert resp.status_code == 422

    @pytest.mark.parametrize("closed", ["rejected", "withdrawn"])
    def test_closed_application_cannot_move(
        self, client, auth_headers, user_id, db_session, closed
    ):
        app_id, _ = _seed_application(db_session, user_id, app_status=closed)
        resp = _move(client, auth_headers, app_id, "interview")
        assert resp.status_code == 422
        detail = client.get(f"/applications/{app_id}", headers=auth_headers).json()
        assert detail["status"] == closed

    def test_move_writes_audit_row(self, client, auth_headers, user_id, db_session):
        app_id, _ = _seed_application(db_session, user_id, app_status="submitted")
        assert _move(client, auth_headers, app_id, "interview").status_code == 200
        rows = _audit_rows(db_session, user_id, "application.stage_move")
        assert rows, "expected an application.stage_move audit row"
        target_type, target_id, detail = rows[0]
        assert target_type == "application"
        assert target_id == app_id
        assert detail["from"] == "submitted"
        assert detail["to"] == "interview"
        assert detail["to_stage"] == "interview"

    def test_funnel_sankey_stays_consistent_after_moves(
        self, client, auth_headers, user_id, db_session
    ):
        a1, _ = _seed_application(db_session, user_id, app_status="submitted")
        a2, _ = _seed_application(db_session, user_id, app_status="submitted")
        assert _move(client, auth_headers, a1, "interview").status_code == 200
        assert _move(client, auth_headers, a2, "offer").status_code == 200

        sankey = client.get("/applications/funnel/sankey", headers=auth_headers).json()
        values = {s["key"]: s["value"] for s in sankey["stages"]}
        # Cumulative model: no double counting, no orphans.
        assert values["applied"] == 2
        assert values["screened"] == 2
        assert values["interviewed"] == 2
        assert values["offers"] == 1
        for dropoff in sankey["dropoffs"]:
            assert dropoff["count"] >= 0, dropoff


class TestJobPipelineMove:
    """Job cards (the first 3 columns) move via /applications/pipeline/{job_id}/move."""

    def _move_job(self, client, headers, job_id: str, to_stage: str):
        return client.post(
            f"/applications/pipeline/{job_id}/move",
            headers=headers,
            json={"to_stage": to_stage},
        )

    def test_requires_auth(self, client):
        resp = client.post(
            "/applications/pipeline/x/move", json={"to_stage": "evaluating"}
        )
        assert resp.status_code == 401

    def test_unknown_job_404(self, client, auth_headers):
        resp = self._move_job(client, auth_headers, "nope", "evaluating")
        assert resp.status_code == 404

    @pytest.mark.parametrize(
        ("to_stage", "expected_job_status"),
        [("evaluating", "screening"), ("tailoring", "tailoring"), ("discovered", "discovered")],
    )
    def test_legal_job_stage_moves(
        self, client, auth_headers, user_id, db_session, to_stage, expected_job_status
    ):
        job_id = _seed_job(db_session, user_id, status="discovered")
        resp = self._move_job(client, auth_headers, job_id, to_stage)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == expected_job_status
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            assert cur.fetchone()[0] == expected_job_status

    @pytest.mark.parametrize("to_stage", ["ready", "submitted", "in-review", "interview", "offer"])
    def test_app_fed_target_is_422(self, client, auth_headers, user_id, db_session, to_stage):
        job_id = _seed_job(db_session, user_id)
        resp = self._move_job(client, auth_headers, job_id, to_stage)
        assert resp.status_code == 422

    def test_job_with_application_is_409(self, client, auth_headers, user_id, db_session):
        # A job that already has an application is no longer a pipeline card.
        _, job_id = _seed_application(db_session, user_id, app_status="submitted")
        resp = self._move_job(client, auth_headers, job_id, "evaluating")
        assert resp.status_code == 409

    def test_job_move_writes_audit_row(self, client, auth_headers, user_id, db_session):
        job_id = _seed_job(db_session, user_id, status="discovered")
        assert self._move_job(client, auth_headers, job_id, "tailoring").status_code == 200
        rows = _audit_rows(db_session, user_id, "job.stage_move")
        assert rows, "expected a job.stage_move audit row"
        target_type, target_id, detail = rows[0]
        assert target_type == "job"
        assert target_id == job_id
        assert detail["from"] == "discovered"
        assert detail["to"] == "tailoring"
