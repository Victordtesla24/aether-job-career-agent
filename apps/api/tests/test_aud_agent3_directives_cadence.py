"""AUD-AGENT-3 — the scheduled cadence for ``supervisor_rules.rules_stage_evaluate``
that closed the gap the scout reproduction confirmed: 0 ``AgentDirective`` rows
EVER on production because nothing — no scheduler, no cron, not even a UI
button — ever called the sole issuance path.

Evidence trail:
  docs/delivery/evidence/RUN-20260818T0223Z/AUD-AGENT-3/01-scout-reproduction.log
  docs/delivery/evidence/RUN-20260818T0223Z/05-decision-memos/AUD-AGENT-3.md

Seeding pattern (heightened-tier metrics -> S1 rule fires) matches
``test_b1b_agent_directives.py``'s own ``_seed_submitted_applications`` helper
so this suite can never drift from what actually trips the rule table.
"""
from __future__ import annotations

import json
import uuid

from app.db import get_connection, new_id


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:24]


def _seed_agent_run(user_id: str, *, agent_name: str = "tailor") -> None:
    """A minimal, real ``AgentRun`` row so ``eligible_users()`` finds this
    user 'active' — the exact INSERT shape ``AgentRunRepository.start`` uses,
    nothing fabricated."""
    from app.repositories.agent_run import AgentRunRepository

    AgentRunRepository().start(user_id, agent_name, {"trigger": "test-seed"})


def _seed_submitted_applications(user_id: str, *, count: int, interviews: int) -> None:
    """Real ``Job`` + ``Application`` rows so ``resolve_policy_for_user``'s
    live metric read finds a genuine heightened-tier signal — same base shape
    as ``test_b1b_agent_directives.py``'s helper of the same name, PLUS a real
    ``transmittedAt`` stamp on every row: ``quality_policy.collect_policy_metrics``
    counts ``sampleSize`` only over applications with ``transmittedAt IS NOT
    NULL`` (a real send, not merely a drafted/recorded status), so without it
    every seeded row here would be invisible to the live metric read and
    ``sampleSize`` would stay 0 regardless of ``count`` — silently never
    tripping the rule this helper exists to trip.
    """
    from app.db import ensure_application_transmission_columns

    ensure_application_transmission_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO "Resume" ("id","userId","sections","formatHash","updatedAt")
                   VALUES (%s,%s,'{}','seedhash',NOW()) RETURNING "id"''',
                (new_id(), user_id),
            )
            resume_id = cur.fetchone()[0]
            for i in range(count):
                job_id = new_id()
                cur.execute(
                    '''INSERT INTO "Job"
                       ("id","userId","title","company","location","remote",
                        "description","requirements","source","sourceUrl",
                        "fitScore","updatedAt")
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
                    (
                        job_id, user_id, f"Role {i}", "Acme", "Melbourne VIC",
                        False, "Own the platform.", json.dumps([]), "adzuna",
                        f"https://example.com/{job_id}", 70.0,
                    ),
                )
                app_id = new_id()
                status = "interview" if i < interviews else "submitted"
                cur.execute(
                    '''INSERT INTO "Application"
                       ("id","userId","jobId","resumeId","status","createdAt",
                        "updatedAt","transmittedAt")
                       VALUES (%s,%s,%s,%s,%s::"ApplicationStatus",NOW(),NOW(),NOW())''',
                    (app_id, user_id, job_id, resume_id, status),
                )
        conn.commit()


class TestEligibleUsers:
    def test_finds_a_user_with_a_recent_agent_run(self, client, test_user_id, db_session):  # noqa: ARG002
        from app.workers import agent_directives_sweep

        _seed_agent_run(test_user_id)
        assert test_user_id in agent_directives_sweep.eligible_users(limit=500)

    def test_excludes_a_user_with_no_agent_run(self, client, db_session):  # noqa: ARG002
        from app.workers import agent_directives_sweep

        never_run_user = _uid()
        with db_session.cursor() as cur:
            cur.execute(
                'INSERT INTO "User" ("id","email","passwordHash","updatedAt") '
                "VALUES (%s,%s,'x',NOW())",
                (never_run_user, f"{never_run_user}@t.dev"),
            )
        db_session.commit()
        assert never_run_user not in agent_directives_sweep.eligible_users(limit=500)


class TestAgentDirectivesCadence:
    def test_cron_is_a_noop_when_flag_is_off(
        self, client, test_user_id, db_session, monkeypatch  # noqa: ARG002
    ):
        """Directive point 2/3: no evaluation, no policy amendment, when
        AETHER_AGI_DIRECTIVES_ENABLED is off (code default) — even for a user
        whose metrics would otherwise trip a rule."""
        import asyncio

        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.workers import agent_directives_sweep

        monkeypatch.delenv("AETHER_AGI_DIRECTIVES_ENABLED", raising=False)
        _seed_agent_run(test_user_id)
        _seed_submitted_applications(test_user_id, count=6, interviews=0)

        evaluated = asyncio.run(agent_directives_sweep.agent_directives_cron({}))

        assert evaluated == 0
        assert AgentDirectiveRepository().list_active(test_user_id) == []
        assert AgentDirectiveRepository().list_history(test_user_id, "tailor") == []

    def test_cron_evaluates_active_users_and_issues_a_real_directive(
        self, client, test_user_id, db_session, monkeypatch  # noqa: ARG002
    ):
        """Directive point 1: with the flag on, an active user whose metrics
        trip the Stage-1 heightened-tier rule gets a REAL directive row
        written by the cron — the thing that had 0 rows ever in prod."""
        import asyncio

        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.workers import agent_directives_sweep

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        _seed_agent_run(test_user_id)
        _seed_submitted_applications(test_user_id, count=6, interviews=0)

        evaluated = asyncio.run(agent_directives_sweep.agent_directives_cron({}))

        assert evaluated == 1
        active = AgentDirectiveRepository().list_active(test_user_id)
        assert active, "the seeded metrics must trip the S1 rule and issue a directive"
        for row in active:
            assert row["rationale"]
            assert row["metricsCited"]
            assert row["issuedBy"] == "supervisor-rules"

    def test_cron_is_idempotent_across_a_double_run(
        self, client, test_user_id, db_session, monkeypatch  # noqa: ARG002
    ):
        """A second tick against the SAME metric snapshot must never churn
        history — ``rules_stage_evaluate``'s own idempotence guarantee must
        survive being driven by the cron."""
        import asyncio

        from app.repositories.agent_directive import AgentDirectiveRepository
        from app.workers import agent_directives_sweep

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        _seed_agent_run(test_user_id)
        _seed_submitted_applications(test_user_id, count=6, interviews=0)

        first = asyncio.run(agent_directives_sweep.agent_directives_cron({}))
        active_after_first = AgentDirectiveRepository().list_active(test_user_id)
        assert active_after_first, "fixture metrics must trigger at least one directive"

        second = asyncio.run(agent_directives_sweep.agent_directives_cron({}))

        assert first == 1
        assert second == 1  # the user is still evaluated — issuance is what stays flat
        active_after_second = AgentDirectiveRepository().list_active(test_user_id)
        assert active_after_second == active_after_first
        for row in active_after_first:
            history = AgentDirectiveRepository().list_history(test_user_id, row["agentKey"])
            assert len(history) == 1, "re-evaluating unchanged metrics must not churn history"

    def test_cron_writes_agentrun_telemetry_for_the_evaluation_itself(
        self, client, test_user_id, db_session, monkeypatch  # noqa: ARG002
    ):
        """Directive point 2 — 'log each evaluation, write AgentRun-style
        telemetry': the cadence's own activity must land in the SAME audit
        trail every other agent run lands in, never invisible plumbing."""
        import asyncio

        from app.repositories.agent_run import AgentRunRepository
        from app.workers import agent_directives_sweep

        monkeypatch.setenv("AETHER_AGI_DIRECTIVES_ENABLED", "true")
        _seed_agent_run(test_user_id)

        before = len(AgentRunRepository().list_recent(test_user_id, limit=100))
        asyncio.run(agent_directives_sweep.agent_directives_cron({}))
        after = AgentRunRepository().list_recent(test_user_id, limit=100)

        assert len(after) == before + 1
        telemetry = [r for r in after if r["agentName"] == "agentDirectives"]
        assert telemetry, "cron must write its own AgentRun telemetry row"
        assert telemetry[0]["status"] == "completed"
