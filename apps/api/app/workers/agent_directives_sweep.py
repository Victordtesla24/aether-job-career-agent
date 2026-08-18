"""AUD-AGENT-3 — the scheduled cadence ``rules_stage_evaluate`` never had
(ORCH-B1-BLUEPRINT-2026-08-14.md §6.3, ADR-AGI-2 P1).

Scout reproduction (docs/delivery/evidence/RUN-20260818T0223Z/AUD-AGENT-3/
01-scout-reproduction.log) confirmed the AgentDirective table carried 0 rows
EVER on production: ``supervisor_rules.rules_stage_evaluate`` (the SOLE
issuance path — its own docstring calls it that) had no caller anywhere —
not a scheduler, not a cron, not even a UI button. The binding decision
(05-decision-memos/AUD-AGENT-3.md, point 3) is BUILD the real cadence: a
scheduled invoker calling ``rules_stage_evaluate(user_id)`` for every active
user, following the repo's OWN existing pattern for per-active-user cadenced
work rather than inventing a new one.

That existing pattern is the ARQ periodic-cron idiom already used for
``board_sweep_cron`` / ``apply_sweep_cron`` (apps/api/app/workers/
board_sweep.py, apply_sweep.py): an ``X_enabled()`` kill-switch gate, an
``eligible_users()`` query, and a cron function registered in
``app.workers.settings._cron_jobs()`` that runs inside the ALREADY-DEPLOYED
``aether-worker.service`` (deploy/aether-worker.service) — so shipping this
needs no new systemd unit file, only the code change plus flipping the flag
in prod's ``.env`` at the next deploy (see the module-level docstring on
``directives_enabled`` for exactly which flag and why).

Unlike board/apply sweep, ``rules_stage_evaluate`` does no LLM call and no
browser automation — its own docstring says "Deterministic, $0, no LLM
call" — so this cron does the evaluation DIRECTLY inside the cron tick
(the same shape as ``tasks.reconcile_abandoned_agent_runs_cron``) rather
than fanning out a per-user ARQ job.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: How far back an ``AgentRun`` counts a user as "active" for this cadence's
#: purposes — a user who has not touched any agent in this window gets no
#: directive evaluation, matching the audit's own framing ("per active
#: user"), not literally every registered account ever.
DIRECTIVES_LOOKBACK_DAYS = 30

#: Ceiling on how many active users one cron tick evaluates, so a burst of
#: signups (or a very active user base) can never turn one tick into an
#: unbounded DB scan — the same shape as ``board_sweep.sweep_user_cap()``.
DIRECTIVES_USER_CAP = 500


def directives_enabled() -> bool:
    """Whether the AUD-AGENT-3 cadence runs at all this tick.

    Reuses the SAME flag ``routers.agents.agent_directives_enabled`` reads
    (``AETHER_AGI_DIRECTIVES_ENABLED``, code default OFF) — deliberately ONE
    switch for "is the directive loop live in this environment", not two.
    That function's own docstring is explicit that the flag gates
    APPLICATION only (an issued directive still gets written to history even
    when it is off, because the manual ``POST /agents/directives/evaluate``
    endpoint always evaluates regardless of the flag). This SCHEDULED,
    unattended cadence is deliberately MORE conservative than that manual
    endpoint: an automated job that nobody is watching must not start
    writing directive history — real INSERTs a human would then have to
    reason about — in an environment nobody has explicitly turned this
    feature on for, even though the row itself would be harmless. See the
    AUD-AGENT-3 decision memo, point 3 ("Flip AETHER_AGI_DIRECTIVES_ENABLED
    ... as part of the deploy") — the same flag, flipped once, both allows
    the cadence to run AND lets issued directives amend policy.
    """
    from app.routers.agents import agent_directives_enabled

    return agent_directives_enabled()


def eligible_users(limit: int | None = None) -> list[str]:
    """User ids with any ``AgentRun`` in the trailing
    ``DIRECTIVES_LOOKBACK_DAYS`` — "active" for this cadence's purposes,
    oldest-last-active first so a large backlog drains fairly across ticks
    instead of the same handful of users always winning the cap (the same
    ordering rationale as ``board_sweep.eligible_users``).

    Excludes this cadence's OWN ``agentName = 'agentDirectives'`` telemetry
    rows from what counts as "active": without this, ``evaluate_user_directives``
    writing its own AgentRun row every tick would perpetually re-stamp
    ``startedAt`` and keep a genuinely dormant user "active" forever, which
    would defeat the whole point of scoping this cadence to active users
    rather than every account that ever registered.
    """
    from app.db import get_connection

    limit = limit or DIRECTIVES_USER_CAP
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT "userId", MAX("startedAt") AS last_run
                FROM "AgentRun"
                WHERE "startedAt" >= NOW() - (%s * INTERVAL '1 day')
                  AND "agentName" != 'agentDirectives'
                GROUP BY "userId"
                ORDER BY last_run ASC
                LIMIT %s
                ''',
                (DIRECTIVES_LOOKBACK_DAYS, limit),
            )
            return [row[0] for row in cur.fetchall()]


def evaluate_user_directives(user_id: str) -> dict[str, Any]:
    """One cadence tick's work for one user.

    Calls the ONLY issuance path (``supervisor_rules.rules_stage_evaluate``)
    and brackets it with a real ``AgentRun`` telemetry row — "log each
    evaluation, write AgentRun-style telemetry" (AUD-AGENT-3 directive point
    2) — so the cadence's own activity is visible in the SAME audit trail
    every other agent run lands in (``GET /agents/runs``, the orchestration
    map's node state), rather than being invisible plumbing nobody can see
    ran at all. A single user's failure is logged and reported, never
    allowed to abort the tick for every OTHER active user.
    """
    from app.repositories.agent_run import AgentRunRepository
    from app.services.supervisor_rules import rules_stage_evaluate

    runs = AgentRunRepository()
    run = runs.start(user_id, "agentDirectives", {"trigger": "cron"})
    try:
        result = rules_stage_evaluate(user_id)
    except Exception as exc:  # noqa: BLE001 — one user must never abort the tick
        logger.exception(
            "agent-directives cron: evaluation crashed for user=%s", user_id
        )
        runs.finish(run["id"], "failed", error=str(exc))
        return {
            "userId": user_id,
            "evaluated": False,
            "issued": [],
            "retired": [],
            "error": str(exc),
        }

    runs.finish(
        run["id"],
        "completed",
        output={
            "issued": result["issued"],
            "retired": result["retired"],
            "evaluated": result["evaluated"],
        },
    )
    logger.info(
        "agent-directives cron: user=%s evaluated=%s issued=%d retired=%d",
        user_id, result["evaluated"], len(result["issued"]), len(result["retired"]),
    )
    return {"userId": user_id, **result}


async def agent_directives_cron(ctx: Any) -> int:  # noqa: ARG001 -- ARQ cron signature
    """ARQ cron: evaluate the Stage-1 rule table for every active user.

    Honest no-op (directive point 2) when ``directives_enabled()`` is off —
    returns 0 immediately, touches no user, writes no row, exactly like
    ``board_sweep_cron`` / ``apply_sweep_cron`` do for their own flags.
    Register in ``app.workers.settings._cron_jobs()`` on whatever interval
    Ops chooses (daily is the decision memo's suggested cadence for a
    deterministic, $0 rule table with no urgency); the flag — not the
    interval — is what makes an unconfigured environment safe.
    """
    import asyncio

    if not directives_enabled():
        return 0

    users = await asyncio.to_thread(eligible_users)
    evaluated = 0
    for user_id in users:
        try:
            await asyncio.to_thread(evaluate_user_directives, user_id)
        except Exception:  # noqa: BLE001 — a cron tick must not kill the worker
            logger.exception(
                "agent-directives cron: user %s crashed the tick", user_id
            )
            continue
        evaluated += 1
    if users:
        logger.info(
            "agent-directives cron: %d user(s) active, %d evaluated",
            len(users), evaluated,
        )
    return evaluated
