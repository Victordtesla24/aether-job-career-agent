"""AUD-COV-2 — auto-GENERATION of cover letters is gated on real fit.

Ledger requirement (verbatim): *don't ship 'direct match' letters for
genuinely poor-fit roles. FIX: gate auto-generation/auto-apply on real fit.*

The auto-APPLY half was already enforced (``application_submission``'s D2
``matchThreshold`` gate bars every autonomous transmission). The
auto-GENERATION half was open: the board-sweep autopilot walked EVERY eligible
job — a job scoring 12/100 against the user's own profile included — and had
``coverLetterAgent`` write it a letter whose deterministic §10.2 hook opens
"My background … is a direct match for the <role> role at <company>". Nobody
asked for that letter, and its opening sentence is false.

This module pins BOTH halves of the fix:

* the AUTOMATED paths (board sweep + the pipeline's matcher-chosen job) do not
  auto-generate a cover letter for a job below the user's own
  ``agentConfig.matchThreshold``, or for an unscored one, and the skip is
  RECORDED as an honest, visible ``boardSweep`` AgentRun rather than silent;
* the EXPLICIT, user-initiated path stays fully available, and the letter it
  returns carries an honest low-fit DISCLOSURE alongside it.

Deliberately says nothing about the "direct match" opener wording itself —
that is AUD-COV-1's separate wave. This wave only decides WHO gets a letter
written for them without asking.
"""
from __future__ import annotations

import json
import time
import uuid

import pytest
from conftest import FIXTURE_LLM_RESUME_TEXT, seed_own_resume

from app.workers import board_sweep


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


@pytest.fixture()
def user_id(auth_headers) -> str:
    from app.security import decode_access_token

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    return decode_access_token(token)["userId"]


def _seed_job(
    conn,
    user_id: str,
    *,
    status: str = "screening",
    fit: float | None = 80.0,
    title: str = "Engineer",
) -> str:
    job_id = _uid()
    with conn.cursor() as cur:
        cur.execute(
            'INSERT INTO "Job" ("id","userId","title","company","description","source",'
            '"sourceUrl","status","fitScore","createdAt","updatedAt") '
            'VALUES (%s,%s,%s,%s,%s,%s,%s,%s::"JobStatus",%s,NOW(),NOW())',
            (job_id, user_id, title, "Acme", "Build.", "greenhouse",
             f"https://example.com/job/{job_id}", status, fit),
        )
    conn.commit()
    return job_id


def _set_match_threshold(conn, user_id: str, threshold: int) -> None:
    """Write the SAME ``agentConfig.matchThreshold`` the Settings screen writes."""
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE "User" SET "agentConfig" = %s WHERE "id" = %s',
            (json.dumps({"matchThreshold": threshold}), user_id),
        )
    conn.commit()


def _clear_agent_config(conn, user_id: str) -> None:
    """Force ``agentConfig`` to genuinely NULL — the "user never configured
    this" state ``user_match_threshold``'s 50-fallback (D2, audit
    wf_9a87f76f-eaa) actually documents.

    The freshly-cloned test schema carries a LIVE, out-of-band column default
    for ``"User"."agentConfig"`` (``information_schema.columns.column_default``
    = ``{"matchThreshold": 80, ...}``, no matching migration file), so a row
    inserted without an explicit value is no longer NULL — it silently already
    has a threshold. Without this, tests aimed at the missing-config fallback
    path exercise the schema's default instead of the code's.
    """
    with conn.cursor() as cur:
        cur.execute('UPDATE "User" SET "agentConfig" = NULL WHERE "id" = %s', (user_id,))
    conn.commit()


def _skip_runs(conn, user_id: str) -> list[dict]:
    """Every honest low-fit skip row this user's autopilot recorded."""
    with conn.cursor() as cur:
        cur.execute(
            'SELECT "jobId", "output", "status", "costUsd" FROM "AgentRun" '
            'WHERE "userId" = %s AND "agentName" = \'boardSweep\' '
            "AND \"output\"->>'reason' = 'below_match_threshold' "
            'ORDER BY "createdAt" ASC',
            (user_id,),
        )
        return [
            {"jobId": r[0], "output": r[1], "status": r[2], "costUsd": r[3]}
            for r in cur.fetchall()
        ]


def _far_deadline() -> float:
    return time.monotonic() + 3600.0


def _recorder(monkeypatch) -> list[tuple[str, str]]:
    """Replace the sweep's ONE agent-dispatch seam with a recorder.

    Recording (rather than raising) is deliberate: ``sweep_user_stretch`` has a
    broad ``except Exception`` that would absorb a raised assertion into its
    ``failures`` counter, quietly turning a real gate violation into a passing
    test. The call list is checked directly instead."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        board_sweep,
        "_run_agent",
        lambda uid, agent, params: calls.append((agent, params["job_id"])) or {},
    )
    return calls


# ---------------------------------------------------------------------------
# 1. The automated sweep must not auto-generate letters for poor-fit roles
# ---------------------------------------------------------------------------


class TestSweepGatesAutoGenerationOnFit:
    def test_below_threshold_job_gets_no_auto_generated_cover(
        self, db_session, user_id, monkeypatch
    ):
        """A job scoring below the user's bar is never auto-tailored or
        auto-lettered — no agent is dispatched for it at all."""
        job = _seed_job(db_session, user_id, fit=12.0)
        calls = _recorder(monkeypatch)

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert calls == [], "an agent was dispatched for a poor-fit job"
        assert summary["covers"] == 0 and summary["tailored"] == 0
        assert summary["processed"] == 0 and summary["failures"] == 0
        assert summary["skipped_low_fit"] == 1
        assert summary["reason"] == "skipped-low-fit"
        # The gate lives in target SELECTION, so the job is never even offered
        # to the stretch loop — it cannot burn an attempt or a job-cap slot.
        assert board_sweep._next_target(user_id, set()) is None
        assert job is not None

    def test_unscored_cover_only_job_gets_no_auto_generated_cover(
        self, db_session, user_id, monkeypatch
    ):
        """An UNSCORED job has no proven fit, so the autopilot cannot honestly
        assert one — it is skipped exactly like a below-threshold job. This is
        the cover-only completion path (``status='tailoring'``), which used to
        be swept regardless of whether the job had ever been scored."""
        _seed_job(db_session, user_id, status="tailoring", fit=None)
        calls = _recorder(monkeypatch)

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert calls == [], "an unscored job was auto-lettered"
        assert summary["covers"] == 0
        assert summary["skipped_low_fit"] == 1
        assert summary["reason"] == "skipped-low-fit"

    def test_job_at_or_above_threshold_is_still_swept(
        self, db_session, user_id, monkeypatch
    ):
        """The gate is a floor, not a freeze: a genuinely well-fitting job is
        still fully auto-tailored + auto-lettered, and the inclusive ``>=``
        boundary job (exactly at the bar) clears it."""
        _set_match_threshold(db_session, user_id, 60)
        good = _seed_job(db_session, user_id, fit=90.0)
        boundary = _seed_job(db_session, user_id, fit=60.0)
        poor = _seed_job(db_session, user_id, fit=59.0)
        calls = _recorder(monkeypatch)

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert summary["covers"] == 2 and summary["tailored"] == 2
        assert summary["skipped_low_fit"] == 1
        assert [jid for _, jid in calls] == [good, good, boundary, boundary]
        assert poor not in [jid for _, jid in calls]

    def test_the_users_own_threshold_is_what_binds(
        self, db_session, user_id, monkeypatch
    ):
        """The bar is the USER's ``agentConfig.matchThreshold``, not a constant:
        a job that clears the 50 fallback is still skipped when the user set 90."""
        _set_match_threshold(db_session, user_id, 90)
        _seed_job(db_session, user_id, fit=80.0)
        calls = _recorder(monkeypatch)

        summary = board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert calls == []
        assert summary["skipped_low_fit"] == 1
        assert summary["covers"] == 0


# ---------------------------------------------------------------------------
# 2. The skip is RECORDED and VISIBLE, never silent
# ---------------------------------------------------------------------------


class TestLowFitSkipIsRecordedAndVisible:
    def test_skip_is_persisted_as_an_honest_zero_cost_agent_run(
        self, db_session, user_id, monkeypatch
    ):
        # This test's intent is the code's documented missing-config fallback
        # (50, not the live schema's out-of-band column default of 80) — make
        # that state explicit rather than relying on how "User" rows happen to
        # be inserted (see ``_clear_agent_config``).
        _clear_agent_config(db_session, user_id)
        job = _seed_job(db_session, user_id, fit=12.0)
        _recorder(monkeypatch)

        board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        rows = _skip_runs(db_session, user_id)
        assert len(rows) == 1, "the skip went unrecorded — autopilot went quiet"
        row = rows[0]
        assert row["jobId"] == job, "the row must name the job it skipped"
        assert float(row["costUsd"] or 0) == 0.0, "a skip costs no money"
        out = row["output"]
        assert out["skipped"] is True
        assert float(out["fitScore"]) == 12.0
        assert float(out["matchThreshold"]) == 50.0
        # The user-facing sentence must state BOTH numbers, so the reason is
        # legible without reading JSON.
        assert "12" in out["message"] and "50" in out["message"]

    def test_repeated_ticks_do_not_flood_the_audit_trail(
        self, db_session, user_id, monkeypatch
    ):
        """The autopilot ticks every ~10 minutes forever. Re-recording the same
        unchanged skip each tick is the exact 76-rows-per-job-per-day pathology
        ML-W-19 removed, so the row is written once per (fit, threshold) state."""
        _seed_job(db_session, user_id, fit=12.0)
        _recorder(monkeypatch)

        for _ in range(3):
            board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        assert len(_skip_runs(db_session, user_id)) == 1

    def test_a_changed_threshold_records_a_fresh_skip(
        self, db_session, user_id, monkeypatch
    ):
        """Idempotence must not become amnesia: when the user RAISES their bar
        the skip is a new, differently-justified fact and is recorded again."""
        _seed_job(db_session, user_id, fit=60.0)
        _set_match_threshold(db_session, user_id, 70)
        _recorder(monkeypatch)
        board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        _set_match_threshold(db_session, user_id, 90)
        board_sweep.sweep_user_stretch(user_id, deadline=_far_deadline())

        rows = _skip_runs(db_session, user_id)
        assert len(rows) == 2
        assert [float(r["output"]["matchThreshold"]) for r in rows] == [70.0, 90.0]


# ---------------------------------------------------------------------------
# 3. The EXPLICIT path stays open — with an honest disclosure
# ---------------------------------------------------------------------------


class TestExplicitGenerationStaysAllowedWithDisclosure:
    def test_user_initiated_low_fit_letter_is_produced_and_disclosed(
        self, client, auth_headers, db_session, user_id
    ):
        """A user who explicitly asks for a letter on a poor-fit role still
        gets one — Aether does not decide for them — but the response carries
        an honest low-fit disclosure naming the score and their own bar."""
        seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
        _set_match_threshold(db_session, user_id, 75)
        run = client.post(
            "/agents/scout/run",
            json={"query": "python engineer", "location": "Sydney"},
            headers=auth_headers,
        )
        assert run.status_code == 202
        job = client.get("/jobs", headers=auth_headers).json()[0]
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Job" SET "fitScore" = 21 WHERE "id" = %s', (job["id"],)
            )
        db_session.commit()

        resp = client.post(
            "/agents/cover-letter/run",
            json={"job_id": job["id"]},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["cover_letter_id"], "the explicit path must still generate"
        disclosure = body["fit_disclosure"]
        assert disclosure, "a low-fit letter shipped with no disclosure at all"
        assert "21" in disclosure and "75" in disclosure
        # The disclosure is METADATA about the letter, never smuggled into the
        # letter a real employer reads.
        assert disclosure not in body["cover_letter"]

    def test_a_well_fitting_letter_carries_no_disclosure(
        self, client, auth_headers, db_session, user_id
    ):
        """No noise on a genuinely good match: the disclosure is empty when the
        job clears the user's own bar."""
        seed_own_resume(client, auth_headers, raw_text=FIXTURE_LLM_RESUME_TEXT)
        _set_match_threshold(db_session, user_id, 40)
        run = client.post(
            "/agents/scout/run",
            json={"query": "python engineer", "location": "Sydney"},
            headers=auth_headers,
        )
        assert run.status_code == 202
        job = client.get("/jobs", headers=auth_headers).json()[0]
        with db_session.cursor() as cur:
            cur.execute(
                'UPDATE "Job" SET "fitScore" = 88 WHERE "id" = %s', (job["id"],)
            )
        db_session.commit()

        resp = client.post(
            "/agents/cover-letter/run",
            json={"job_id": job["id"]},
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["fit_disclosure"] == ""


# ---------------------------------------------------------------------------
# 4. The pipeline's matcher-chosen job obeys the same gate
# ---------------------------------------------------------------------------


class TestPipelineGatesAutoGenerationOnFit:
    def test_pipeline_skips_the_cover_step_for_a_poor_fit_top_job(
        self, db_session, user_id, monkeypatch
    ):
        """``_pipeline_core`` picks the job itself (matcher's top match), so its
        cover step is auto-generation too — and must obey the same bar."""
        from dataclasses import asdict, is_dataclass

        from app.routers import agents as agents_router

        job = _seed_job(db_session, user_id, fit=15.0)
        dispatched: list[str] = []

        def _spy_dispatch(uid, name, params=None, **kwargs):
            dispatched.append(name)
            if name == "coverLetter":
                raise AssertionError(
                    "the pipeline auto-generated a letter for a poor-fit role"
                )
            if name == "tailor":
                return {"resume_id": "r1", "changes": ["x"], "rejected": []}
            return {}

        def _spy_record_run(uid, name, params, fn, **kwargs):
            """The real audit/metering wrapper is out of scope here; keep its
            ONE contract — run ``fn``, return its dict-shaped output."""
            result = fn()
            out = (
                asdict(result)
                if is_dataclass(result) and not isinstance(result, type)
                else result
            )
            return {**(out or {}), "run_id": "stub-run"}

        monkeypatch.setattr(agents_router, "_dispatch", _spy_dispatch)
        monkeypatch.setattr(agents_router, "_record_run", _spy_record_run)

        out = agents_router._pipeline_core(
            user_id, {"query": "engineer", "location": "Sydney"}
        )

        assert "coverLetter" not in dispatched
        assert out["approvalRequired"] is False
        step = next(s for s in out["steps"] if s["agent"] == "coverLetter")
        assert step["output"]["skipped"] is True
        assert step["output"]["reason"] == "below_match_threshold"
        assert out["top_job_id"] == job
