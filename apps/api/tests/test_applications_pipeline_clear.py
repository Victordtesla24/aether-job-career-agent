"""FEAT-CLEAR — POST /applications/pipeline/clear.

Clear Pipeline archives every agent-pipeline job card (the first 3 board
columns: Discovered / Evaluating / Tailoring, fed by Job.status in discovered /
screening / matched / tailoring) that has NO application yet, in one audited
transaction. Soft-archive only — jobs are never destroyed (mirrors
DELETE /jobs/{id}). Jobs that already have an application are untouched: they
left the pipeline half when the application was created. Idempotent on an
empty pipeline.
"""
from __future__ import annotations

import pytest
from test_applications_move import _seed_job
from test_applications_tracker import _seed_application, _uid


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _clear(client, headers, *, confirm: bool = True):
    return client.post(
        "/applications/pipeline/clear", headers=headers, json={"confirm": confirm}
    )


def _audit_rows(db_session, actor: str):
    with db_session.cursor() as cur:
        cur.execute(
            'SELECT "targetType", "detailJson" FROM "AdminAuditLog" '
            'WHERE "actorUserId" = %s AND "action" = %s '
            "ORDER BY \"createdAt\" DESC",
            (actor, "job.pipeline_clear"),
        )
        return cur.fetchall()


class TestClearPipeline:
    def test_requires_auth(self, client):
        resp = client.post(
            "/applications/pipeline/clear", json={"confirm": True}
        )
        assert resp.status_code == 401

    def test_confirm_false_is_400(self, client, auth_headers):
        resp = _clear(client, auth_headers, confirm=False)
        assert resp.status_code == 400
        assert "confirmation" in resp.json()["detail"].lower()

    def test_empty_pipeline_is_idempotent_200(self, client, auth_headers):
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json() == {"archived": 0, "jobIds": []}

    @pytest.mark.parametrize(
        "status", ["discovered", "screening", "matched", "tailoring"]
    )
    def test_archives_pipeline_job_in_each_stage(
        self, client, auth_headers, user_id, db_session, status
    ):
        job_id = _seed_job(db_session, user_id, status=status)
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 1
        assert resp.json()["jobIds"] == [job_id]
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            assert cur.fetchone()[0] == "archived"

    def test_archives_all_pipeline_jobs_in_one_call(
        self, client, auth_headers, user_id, db_session
    ):
        ids = [
            _seed_job(db_session, user_id, status="discovered"),
            _seed_job(db_session, user_id, status="screening"),
            _seed_job(db_session, user_id, status="matched"),
            _seed_job(db_session, user_id, status="tailoring"),
        ]
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 4
        assert sorted(resp.json()["jobIds"]) == sorted(ids)

    def test_job_with_application_is_untouched(
        self, client, auth_headers, user_id, db_session
    ):
        # A job that already has an application left the pipeline half —
        # clearing must NOT archive it (it lives on the application-fed side).
        app_id, job_id = _seed_application(db_session, user_id, app_status="draft")
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 0
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            # _seed_application inserts the job as 'discovered' — it would be
            # a pipeline candidate if it had no application. It has one, so it
            # must stay 'discovered' (not archived).
            assert cur.fetchone()[0] == "discovered"

    def test_applied_job_is_untouched(
        self, client, auth_headers, user_id, db_session
    ):
        # 'applied' / 'archived' / 'rejected' statuses are not pipeline-stage
        # statuses — they must never be touched.
        job_id = _seed_job(db_session, user_id, status="applied")
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 0
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (job_id,))
            assert cur.fetchone()[0] == "applied"

    def test_foreign_user_jobs_are_untouched(
        self, client, auth_headers, db_session
    ):
        other = {"email": "other-clear@example.com", "password": "Sup3rSecret"}
        assert client.post("/auth/register", json=other).status_code == 201
        from app.repositories.user import UserRepository

        other_id = UserRepository().get_by_email("other-clear@example.com")["id"]
        foreign_job = _seed_job(db_session, other_id, status="discovered")
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 0
        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Job" WHERE "id" = %s', (foreign_job,))
            assert cur.fetchone()[0] == "discovered"

    def test_writes_audit_row(
        self, client, auth_headers, user_id, db_session
    ):
        _seed_job(db_session, user_id, status="discovered")
        _seed_job(db_session, user_id, status="tailoring")
        assert _clear(client, auth_headers).status_code == 200
        rows = _audit_rows(db_session, user_id)
        assert rows, "expected a job.pipeline_clear audit row"
        target_type, detail = rows[0]
        assert target_type == "job"
        assert detail["archived_count"] == 2  # type: ignore[index]
        assert len(detail["job_ids"]) == 2

    def test_no_audit_row_on_empty_pipeline(
        self, client, auth_headers, user_id, db_session
    ):
        # An empty pipeline is a 200 no-op — no audit row, no false signal.
        assert _clear(client, auth_headers).status_code == 200
        assert _audit_rows(db_session, user_id) == []

    def test_board_lists_no_pipeline_jobs_after_clear(
        self, client, auth_headers, user_id, db_session
    ):
        # End-to-end: after clearing, GET /jobs returns no pipeline-stage
        # jobs for this user (they are all archived now).
        _seed_job(db_session, user_id, status="discovered")
        _seed_job(db_session, user_id, status="tailoring")
        assert _clear(client, auth_headers).status_code == 200
        jobs = client.get("/jobs", headers=auth_headers).json()
        for j in jobs:
            if j["userId"] == user_id:
                assert j["status"] != "discovered"
                assert j["status"] != "screening"
                assert j["status"] != "matched"
                assert j["status"] != "tailoring"

    def test_idempotent_second_call_archives_zero(
        self, client, auth_headers, user_id, db_session
    ):
        _seed_job(db_session, user_id, status="discovered")
        assert _clear(client, auth_headers).status_code == 200
        # Second call — pipeline is now empty.
        resp = _clear(client, auth_headers)
        assert resp.status_code == 200
        assert resp.json()["archived"] == 0
