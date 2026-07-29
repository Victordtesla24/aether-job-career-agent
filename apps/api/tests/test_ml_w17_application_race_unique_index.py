"""ML-W-17 (NTH-R10, wave35-sonnet-review-verdict.json) — a DB-level partial
unique index closes the cross-row version of the RT-004 promotion race.

The RT-004 guards in ``app.routers.applications`` (``submit_application``,
``move_application``) are check-then-act: each SELECTs for an existing
active application for the job, then promotes its OWN draft row. That
protects one row via a compare-and-swap, but two concurrent promotions of
TWO DIFFERENT drafts for the SAME job can both pass the SELECT (each reads
before the other commits) and both pass their own single-row CAS — minting
two active applications for one job, which is exactly the live "11+ cards
for one job" duplication RT-004's board-dedup was built to paper over
(wave35-sonnet-review-verdict.json, id NTH-R10, "PRE-EXISTING, not
introduced or widened").

Covers:
- fail-before / pass-after: a genuine concurrent cross-row promotion race
  (seam-injected, deterministic — no thread-timing flakiness) is caught by
  the new partial unique index and mapped to the IDENTICAL 409 the
  check-then-act guard already returns, for BOTH promotion paths
  (``submit`` and ``move``); the DB ends up with exactly one active
  application for the job.
- ``ensure_application_unique_active_index()`` actually creates the index
  when no violations exist.
- ``ensure_application_unique_active_index()`` SKIPS creation (logs a
  WARNING, does not fail the caller) when the ``Application`` table already
  has violating duplicate-active rows for some (userId, jobId) pair — the
  exact state a read-only production probe found live on 2026-07-29 (2
  violating pairs, 21 extra rows) before this fix.
"""
from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator

import pytest

#: Hardcoded (not imported from app.db) so this fixture/helper still works
#: — and the fail-before run still gets past setup to exercise the actual
#: race — against the pre-fix code, which has neither the constant nor the
#: index. Must stay in sync with ``db.APPLICATION_UNIQUE_ACTIVE_INDEX``.
_INDEX_NAME = "Application_user_job_active_key"


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


@pytest.fixture(autouse=True)
def _reset_index_state() -> Iterator[None]:
    """Every test in this file controls its own starting state for the
    lazy-DDL index: drop it (test-schema only — ``TRUNCATE`` never drops
    indexes, so a prior test/file in this shared ``aether_test`` session
    that already triggered ``ensure_application_unique_active_index()``
    would otherwise leave the real constraint in place here) and reset the
    process-wide "already ensured" guard, so each test can deterministically
    exercise whichever branch (create vs. skip) it targets.

    Deliberately tolerant of the pre-fix codebase (no
    ``ensure_application_unique_active_index``/``_application_unique_active_index_ready``
    yet) so a fail-before run reaches the real assertions instead of
    erroring in setup.
    """
    import app.db as db_module
    from app.db import get_connection

    def _reset() -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP INDEX IF EXISTS "{_INDEX_NAME}"')
            conn.commit()
        if hasattr(db_module, "_application_unique_active_index_ready"):
            db_module._application_unique_active_index_ready = False

    _reset()
    yield
    _reset()


def _index_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE tablename = 'Application'"
            " AND indexname = %s",
            (_INDEX_NAME,),
        )
        return cur.fetchone() is not None


def _seed_job(conn, user_id: str) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            "VALUES (%s,%s,'Staff Engineer','Acme','Build things.','lever',"
            "%s,'screening'::\"JobStatus\",85.0,NOW(),NOW())",
            (job_id, user_id, f"https://example.com/job/{job_id}"),
        )
    conn.commit()
    return job_id


def _seed_draft(conn, user_id: str, job_id: str) -> tuple[str, str]:
    """Seed a fully gate-compliant draft Application (tailored resume +
    cover letter, satisfying FEAT-SUBMISSION-GATE) for ``job_id``, plus its
    own tailored Resume row. Returns ``(application_id, resume_id)``.
    """
    app_id, resume_id = _uid(), _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Resume" ("id","userId","version","sections","formatHash",'
            '"sourceJobId","updatedAt") VALUES (%s,%s,1,%s,%s,%s,NOW())',
            (resume_id, user_id, json.dumps({"summary": "t"}), "h", job_id),
        )
        cur.execute(
            'INSERT INTO "Application" ("id","userId","jobId","resumeId","status",'
            '"coverLetter","createdAt","updatedAt") '
            "VALUES (%s,%s,%s,%s,'draft'::\"ApplicationStatus\",%s,NOW(),NOW())",
            (
                app_id,
                user_id,
                job_id,
                resume_id,
                "Dear hiring team,\n\nI would love to join.",
            ),
        )
    conn.commit()
    return app_id, resume_id


def _active_rows_for_job(conn, job_id: str) -> list[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "id", "status" FROM "Application" WHERE "jobId" = %s ORDER BY "id"',
            (job_id,),
        )
        rows = cur.fetchall()
    return [(r[0], r[1]) for r in rows if r[1] in
            ("submitted", "screening", "interview", "offer")]


class TestSubmitCrossRowPromotionRace:
    def test_concurrent_submit_of_two_drafts_for_one_job_is_blocked(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        """Seam-injected, deterministic race (mirrors
        ``test_submit_double_submit_race_second_caller_takes_idempotent_path``
        in test_applications_tracker.py): draft A's submit request is
        in-flight, PAST its own RT-004 guard SELECT (which found no other
        active application because draft B was still 'draft' at read time),
        when "another request" fully promotes draft B to submitted between
        that guard and A's own CAS UPDATE.

        FAIL-BEFORE this fix: A's UPDATE had no cross-row guard and
        succeeded unconditionally, minting a SECOND active application for
        the job (200, not 409; two active rows in the DB).
        PASS-AFTER: the partial unique index rejects A's UPDATE and the
        router maps the UniqueViolation to the identical 409 the
        check-then-act guard already returns.
        """
        job = _seed_job(db_session, user_id)
        draft_a, _ = _seed_draft(db_session, user_id, job)
        draft_b, resume_b = _seed_draft(db_session, user_id, job)

        import app.routers.applications as applications_module

        fired = {"done": False}

        class _RaceInjectingDatetime(applications_module.datetime):
            @classmethod
            def now(cls, tz=None):
                if not fired["done"]:
                    fired["done"] = True
                    with db_session.cursor() as race_cur:
                        race_cur.execute(
                            """
                            UPDATE "Application"
                            SET "status" = 'submitted'::"ApplicationStatus",
                                "resumeId" = %s,
                                "answers" = COALESCE("answers", '{}'::jsonb) || %s::jsonb,
                                "updatedAt" = NOW()
                            WHERE "id" = %s AND "userId" = %s
                              AND "status" = 'draft'::"ApplicationStatus"
                            """,
                            (
                                resume_b,
                                json.dumps(
                                    {
                                        "appliedUrl": "https://race-winner.example.com/apply",
                                        "submittedAt": "2026-01-01T00:00:00+00:00",
                                    }
                                ),
                                draft_b,
                                user_id,
                            ),
                        )
                    db_session.commit()
                return super().now(tz)

        monkeypatch.setattr(applications_module, "datetime", _RaceInjectingDatetime)

        resp = client.post(
            f"/applications/{draft_a}/submit",
            json={"applied_url": "https://race-loser.example.com/apply"},
            headers=auth_headers,
        )

        assert resp.status_code == 409, resp.text
        assert "already has an active application" in resp.json()["detail"]

        active = _active_rows_for_job(db_session, job)
        assert len(active) == 1, active
        assert active[0] == (draft_b, "submitted")

        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Application" WHERE "id" = %s', (draft_a,))
            # Draft A's failed UPDATE never committed — it stays 'draft',
            # exactly like the pre-existing single-row guard path.
            assert cur.fetchone()[0] == "draft"


class _CursorSpy:
    """Wraps a real psycopg2 cursor (which cannot itself be monkeypatched —
    it is an immutable C-extension type) so a specific SQL fragment can be
    matched and react exactly once, deterministically injecting a
    "concurrent" commit between ``move_application``'s guard SELECT and its
    own UPDATE — no thread-timing flakiness.
    """

    def __init__(self, real_cursor, wrapper: "_ConnSpy"):
        self._real = real_cursor
        self._wrapper = wrapper

    def execute(self, query, params=None):
        result = (
            self._real.execute(query)
            if params is None
            else self._real.execute(query, params)
        )
        if not self._wrapper.fired and self._wrapper.match in query:
            self._wrapper.fired = True
            self._wrapper.on_match()
        return result

    def fetchone(self):
        return self._real.fetchone()

    def __getattr__(self, name):
        # Passthrough for everything this spy doesn't itself define (e.g.
        # ``description``/``fetchall``, used by ``get_application`` /
        # ``rows_to_dicts`` when the promotion endpoint falls through to its
        # own success-path read using the SAME patched ``get_connection``).
        return getattr(self._real, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)


class _ConnSpy:
    """Plain-Python stand-in for the real ``get_connection()`` result,
    forwarding everything except ``cursor()`` (which returns a
    :class:`_CursorSpy`). ``move_application`` only ever calls
    ``cursor()``/``commit()``/``rollback()`` on the connection it gets.
    """

    def __init__(self, real_conn, match: str, on_match):
        self._real = real_conn
        self.match = match
        self.on_match = on_match
        self.fired = False

    def cursor(self, *a, **kw):
        return _CursorSpy(self._real.cursor(*a, **kw), self)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()

    def close(self):
        return self._real.close()


class TestMoveCrossRowPromotionRace:
    def test_concurrent_move_of_two_drafts_for_one_job_is_blocked(
        self, db_session, user_id, client, auth_headers, monkeypatch
    ):
        """Same cross-row race, via the ``/move`` promotion path.
        Deterministically injects the "concurrent" full promotion of draft B
        immediately after ``move_application``'s own guard SELECT runs (a
        SQL fragment unique to that query) but before its UPDATE — proving
        the ``UniqueViolation`` catch added to ``move_application`` (not
        just ``submit_application``) actually fires on a real DB conflict,
        rather than being dead code.
        """
        job = _seed_job(db_session, user_id)
        draft_a, _ = _seed_draft(db_session, user_id, job)
        draft_b, resume_b = _seed_draft(db_session, user_id, job)

        import app.routers.applications as applications_module

        real_get_connection = applications_module.get_connection

        def _promote_b_concurrently() -> None:
            with db_session.cursor() as race_cur:
                race_cur.execute(
                    """
                    UPDATE "Application"
                    SET "status" = 'submitted'::"ApplicationStatus",
                        "resumeId" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                      AND "status" = 'draft'::"ApplicationStatus"
                    """,
                    (resume_b, draft_b, user_id),
                )
            db_session.commit()

        @contextlib.contextmanager
        def _patched_get_connection():
            with real_get_connection() as real_conn:
                yield _ConnSpy(
                    real_conn,
                    match='"id" <> %s AND "status" IN',
                    on_match=_promote_b_concurrently,
                )

        monkeypatch.setattr(applications_module, "get_connection", _patched_get_connection)

        resp = client.post(
            f"/applications/{draft_a}/move",
            json={"to_stage": "submitted"},
            headers=auth_headers,
        )

        assert resp.status_code == 409, resp.text
        assert "already has an active application" in resp.json()["detail"]

        active = _active_rows_for_job(db_session, job)
        assert len(active) == 1, active
        assert active[0] == (draft_b, "submitted")

        with db_session.cursor() as cur:
            cur.execute('SELECT "status" FROM "Application" WHERE "id" = %s', (draft_a,))
            assert cur.fetchone()[0] == "draft"


class TestEnsureIndexCreation:
    def test_creates_index_when_no_violations_exist(self, db_session, user_id, client, auth_headers):
        from app.db import ensure_application_unique_active_index

        job = _seed_job(db_session, user_id)
        # One compliant active row — no violation anywhere in the table.
        _seed_draft(db_session, user_id, job)
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "status" = \'submitted\'::"ApplicationStatus"'
                ' WHERE "jobId" = %s',
                (job,),
            )
        db_session.commit()

        assert not _index_exists(db_session)
        ensure_application_unique_active_index()
        assert _index_exists(db_session)

    def test_submit_endpoint_creates_index_as_a_side_effect(
        self, db_session, user_id, client, auth_headers
    ):
        """Exercises the real wiring (not just calling the db.py function
        directly): the FIRST submit/move call in a clean process creates the
        index lazily, per ADR-TR-1.
        """
        job = _seed_job(db_session, user_id)
        draft, _ = _seed_draft(db_session, user_id, job)

        assert not _index_exists(db_session)
        resp = client.post(f"/applications/{draft}/submit", json={}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert _index_exists(db_session)


class TestEnsureIndexSkipsOnExistingViolations:
    def test_skips_creation_and_logs_warning_when_violations_already_exist(
        self, db_session, user_id, client, auth_headers, caplog
    ):
        """Reproduces the exact state a read-only production probe found
        live on 2026-07-29 (2 violating (userId, jobId) pairs, 21 extra
        rows) — multiple ACTIVE Application rows already exist for one job,
        seeded directly (bypassing the app's own guards, modeling
        historical/legacy data or a race that happened before this fix
        shipped). ``ensure_application_unique_active_index()`` must not
        raise and must not create the index; it must log an honest WARNING
        so ops can find and clean these up.
        """
        from app.db import ensure_application_unique_active_index

        job = _seed_job(db_session, user_id)
        _seed_draft(db_session, user_id, job)
        _seed_draft(db_session, user_id, job)
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "status" = \'submitted\'::"ApplicationStatus"'
                ' WHERE "jobId" = %s',
                (job,),
            )
        db_session.commit()

        with caplog.at_level(logging.WARNING, logger="app.db"):
            ensure_application_unique_active_index()  # must not raise

        assert not _index_exists(db_session)
        assert any(
            "violate the one-active-application-per-job invariant" in r.message
            for r in caplog.records
        ), [r.message for r in caplog.records]

    def test_promotion_endpoints_stay_healthy_when_violations_already_exist(
        self, db_session, user_id, client, auth_headers
    ):
        """The skip branch must not break the promotion endpoints for OTHER
        jobs/users just because some unrelated job already violates the
        invariant: a normal, single-draft submit for a different job still
        succeeds 200 even though the index was never created this run.
        """
        violating_job = _seed_job(db_session, user_id)
        _seed_draft(db_session, user_id, violating_job)
        _seed_draft(db_session, user_id, violating_job)
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Application" SET "status" = \'submitted\'::"ApplicationStatus"'
                ' WHERE "jobId" = %s',
                (violating_job,),
            )
        db_session.commit()

        clean_job = _seed_job(db_session, user_id)
        clean_draft, _ = _seed_draft(db_session, user_id, clean_job)

        resp = client.post(
            f"/applications/{clean_draft}/submit", json={}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "submitted"
        assert not _index_exists(db_session)
