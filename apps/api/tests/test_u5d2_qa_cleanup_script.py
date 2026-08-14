"""U5d-2 — the QA test-row cleanup one-shot, exercised end to end.

The script (``scripts/qa_cleanup_u5d2_test_rows.py``) runs against PRODUCTION at
land time, on two rows named by id, so its guarantees are pinned here rather
than trusted:

* **dry run writes nothing** — the default mode is SELECT-only;
* **it issues no raw destructive SQL** — asserted over the script's own source,
  so a future edit that reaches for ``DELETE FROM``/``DROP``/``TRUNCATE`` fails
  this test, and no ``Application`` is ever deleted;
* **it refuses a row carrying transmission proof** — real evidence of a real
  submission is never reverted or retired, and the process exits non-zero;
* **every transition it makes is a REAL ``ApplicationStatusEvent``** with
  ``source='qa-cleanup'``, so the cleanup is attributable forever;
* **it is idempotent** — a second run reports already-clean and writes no
  duplicate event.

The two production ids are used verbatim: the test seeds rows WITH THOSE IDS in
the ``aether_test`` schema, which is the only way to exercise the real
id-scoped statements. Nothing here touches production.
"""
from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "qa_cleanup_u5d2_test_rows.py"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("u5d2_qa_cleanup", _SCRIPT)
    assert spec and spec.loader, f"no import spec for {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed(conn, user_id: str, application_id: str, status: str) -> str:
    job_id = "c" + uuid.uuid4().hex[:24]
    resume_id = "c" + uuid.uuid4().hex[:24]
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, "QA Row", "Example Co", "d", "lever",
             f"https://careers.example.com/qa/{job_id}", "ready", 50.0),
        )
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,%s,%s,%s,%s,NOW())',
            (resume_id, user_id, 1, json.dumps({"raw_text": "cv"}), "h", job_id),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",%s,NOW(),NOW())',
            (application_id, user_id, job_id, resume_id, status, "letter"),
        )
    conn.commit()
    return job_id


def _status(conn, application_id: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "status"::text FROM "Application" WHERE "id" = %s',
            (application_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _events(conn, application_id: str, source: str) -> int:
    from app.repositories.application_status_event import (
        ensure_application_status_event_table,
    )

    ensure_application_status_event_table()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT count(*) FROM "ApplicationStatusEvent" '
            'WHERE "applicationId" = %s AND "source" = %s',
            (application_id, source),
        )
        return int(cur.fetchone()[0])


class TestQaCleanupScript:
    def test_source_issues_no_raw_destructive_sql(self):
        """The script may retire rows through product semantics; it may never
        reach for destructive SQL of its own."""
        source = _SCRIPT.read_text().upper()
        for statement in ("DELETE FROM", "DROP TABLE", "DROP COLUMN", "TRUNCATE"):
            assert statement not in source, f"{statement} appears in the script"
        # …and it never writes a positive submission claim.
        assert "TRANSMITTEDAT\" = " not in source

    def test_dry_run_reports_the_change_and_writes_nothing(self, db_session, user_id):
        script = _load_script()
        _seed(db_session, user_id, script.REVERT_TO_DRAFT_ID, "submitted")
        _seed(db_session, user_id, script.WITHDRAW_ID, "submitted")

        revert = script.revert_to_draft(apply=False)
        withdraw = script.withdraw_probe_row(apply=False)

        assert revert["result"] == "would-revert"
        assert withdraw["result"] == "would-withdraw"
        assert _status(db_session, script.REVERT_TO_DRAFT_ID) == "submitted"
        assert _status(db_session, script.WITHDRAW_ID) == "submitted"
        assert _events(db_session, script.REVERT_TO_DRAFT_ID, script.SOURCE) == 0

    def test_apply_reverts_and_withdraws_with_attributable_history(
        self, db_session, user_id
    ):
        script = _load_script()
        _seed(db_session, user_id, script.REVERT_TO_DRAFT_ID, "submitted")
        _seed(db_session, user_id, script.WITHDRAW_ID, "submitted")

        revert = script.revert_to_draft(apply=True)
        withdraw = script.withdraw_probe_row(apply=True)

        assert revert["result"] == "reverted"
        assert withdraw["result"] == "withdrawn"
        assert _status(db_session, script.REVERT_TO_DRAFT_ID) == "draft"
        assert _status(db_session, script.WITHDRAW_ID) == "withdrawn"
        assert _events(db_session, script.REVERT_TO_DRAFT_ID, script.SOURCE) == 1
        assert _events(db_session, script.WITHDRAW_ID, script.SOURCE) == 1
        # Neither row was deleted — the audit trail survives.
        assert _status(db_session, script.WITHDRAW_ID) is not None

    def test_is_idempotent(self, db_session, user_id):
        script = _load_script()
        _seed(db_session, user_id, script.REVERT_TO_DRAFT_ID, "submitted")
        _seed(db_session, user_id, script.WITHDRAW_ID, "submitted")

        script.revert_to_draft(apply=True)
        script.withdraw_probe_row(apply=True)
        second_revert = script.revert_to_draft(apply=True)
        second_withdraw = script.withdraw_probe_row(apply=True)

        assert second_revert["result"] == "already-clean"
        assert second_withdraw["result"] == "already-clean"
        assert _events(db_session, script.REVERT_TO_DRAFT_ID, script.SOURCE) == 1
        assert _events(db_session, script.WITHDRAW_ID, script.SOURCE) == 1

    def test_refuses_a_row_carrying_transmission_proof(self, db_session, user_id):
        from app.db import ensure_application_transmission_columns

        script = _load_script()
        _seed(db_session, user_id, script.REVERT_TO_DRAFT_ID, "submitted")
        ensure_application_transmission_columns()
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "transmittedAt" = NOW() WHERE "id" = %s',
                (script.REVERT_TO_DRAFT_ID,),
            )
        db_session.commit()

        result = script.revert_to_draft(apply=True)

        assert result["result"] == "REFUSED"
        assert _status(db_session, script.REVERT_TO_DRAFT_ID) == "submitted"

    def test_disarms_an_approval_left_armed_by_the_probe(self, db_session, user_id):
        from app.repositories.approval import ApprovalRepository

        script = _load_script()
        job_id = _seed(db_session, user_id, script.WITHDRAW_ID, "submitted")
        approval = ApprovalRepository().create(
            user_id,
            "application_submit",
            {"kind": "submission", "channel": "ashby", "job_id": job_id,
             "application_id": script.WITHDRAW_ID, "apply_url": "https://x.example"},
            application_id=script.WITHDRAW_ID,
        )
        ApprovalRepository().approve(approval["id"], user_id)

        result = script.withdraw_probe_row(apply=True)

        assert approval["id"] in result["approvalsDisarmed"]
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT "status","executedAt" FROM "ApprovalRequest" WHERE "id" = %s',
                (approval["id"],),
            )
            row = cur.fetchone()
        assert row is None, "an armed probe approval must not be left live"
        # Attributability survives the removal: the AdminAuditLog names it.
        with db_session.cursor() as cur:
            cur.execute(
                'SELECT count(*) FROM "AdminAuditLog" '
                "WHERE \"targetId\" = %s AND \"action\" = 'approval.delete'",
                (approval["id"],),
            )
            assert int(cur.fetchone()[0]) == 1

    def test_absent_rows_are_reported_not_invented(self, db_session, user_id):
        script = _load_script()

        assert script.revert_to_draft(apply=True)["result"] == "absent"
        assert script.withdraw_probe_row(apply=True)["result"] == "absent"

    def test_missing_database_url_is_refused(self, monkeypatch, capsys):
        script = _load_script()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setattr("sys.argv", ["qa_cleanup_u5d2_test_rows.py"])

        assert script.main() == 2
        assert "REFUSING TO RUN" in capsys.readouterr().err
