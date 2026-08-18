"""GAP-P7-DISCOVERY-002 — real periodic discovery on the live worker.

R3 fix for the R2 delta review's P0 Finding 1
(docs/delivery/evidence/RUN-20260818T0223Z/FEAT-JOBBOARD/10-r2-delta-review.md):
Settings told entitled subscribers their boards were "searched automatically
every 30 minutes on the discovery schedule" citing an Abacus-era
``aether-discovery.timer`` systemd unit that does NOT exist on the live host —
the migration to the Hostinger ARQ-cron scheduler (``apps/api/app/workers/
settings.py``) never ported discovery/scout into that new cron table, so
NOTHING searched any job board automatically for any subscriber, paying or
not. This module is the real mechanism: an ARQ cron on the SAME worker
process that already runs ``board_sweep_cron`` / ``apply_sweep_cron`` /
``sales_agent_cron``.

CADENCE: every 30 minutes, at minute :03 and :33 — chosen to be distinct from
every other registered cron on this worker (``sweep_stale_jobs`` */5,
``board_sweep_cron`` :00/10/20/30/40/50, ``reconcile_abandoned_agent_runs_cron``
:02/07/12.../57, ``apply_sweep_cron`` :07/22/37/52, ``sales_agent_cron``
:15/:45). Registered in ``apps/api/app/workers/settings.py::_cron_jobs()``.

ELIGIBILITY AND DISPATCH: reuses ``app.routers.agents._sweep_eligible_users``
(entitled + real ``targetRole`` on file, exactly the population
``POST /agents/discovery/sweep`` already served) and
``app.routers.agents._execute_discovery_for_user`` (the same scout+fitScorer
dispatch that endpoint uses) VERBATIM — no reimplementation, no new bypass of
the entitlement/pause/quota guards those functions already enforce. The
per-user dispatch runs DIRECTLY, in-process — no HTTP self-call, so it needs
no ``X-Aether-System-Run`` secret from inside the worker.

Follows the EXACT house pattern of ``apps/api/app/workers/board_sweep.py``'s
``board_sweep_cron`` / ``board_sweep_user`` split: the cron tick only reads
eligibility and ENQUEUES one per-user ARQ job (``_job_id=f"discovery-sweep:
<user_id>"``, the same idempotent-dedup idiom board-sweep uses), and the
per-user job (``discovery_sweep_user``) does the actual dispatch off the
event loop via ``asyncio.to_thread``.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def discovery_cron_enabled() -> bool:
    """Kill-switch: ``AETHER_DISCOVERY_CRON_ENABLED``.

    Code default ON — unlike the sibling autopilots (``board_sweep``'s
    ``AETHER_BOARD_SWEEP_ENABLED`` and ``apply_sweep``'s
    ``AETHER_APPLY_SWEEP_ENABLED``, both code-default OFF and turned on only
    by the production ``.env``), the Owner directive behind this fix is
    explicitly that entitled subscribers get real automatic discovery WITHOUT
    an operator having to opt in separately (docs/delivery/evidence/
    RUN-20260818T0223Z/FEAT-JOBBOARD/10-r2-delta-review.md, mandatory check 6).
    The switch still exists so an operator CAN turn it off (incident response,
    an Adzuna budget emergency, a bad deploy) without a code change.
    """
    return os.environ.get("AETHER_DISCOVERY_CRON_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def discovery_sweep_min_interval_seconds() -> float:
    """Recency guard (env-tunable, default 1500s = 25 min): the minimum time
    since a user's last ``scout`` ``AgentRun`` before the cron will enqueue
    them again.

    DEDUP/OVERLAP SAFETY: the ARQ ``_job_id`` dedup below only protects
    against two CRON ticks racing each other — it cannot see a user who was
    swept moments earlier by an unrelated trigger (a manual Sync/Sync All
    click, or an operator's manual ``POST /agents/discovery/sweep`` re-run).
    Without this guard a user who just clicked Sync at :32 would be
    re-enqueued one minute later by the :33 tick — a real, billed duplicate
    scout+fitScorer pass for no new information. Floored just under the
    30-minute cadence so a user is never skipped past their own next
    scheduled tick.
    """
    try:
        seconds = float(
            os.environ.get("AETHER_DISCOVERY_SWEEP_MIN_INTERVAL_SECONDS", "1500")
        )
    except ValueError:
        seconds = 1500.0
    return max(60.0, seconds)


def _recently_swept(user_id: str) -> bool:
    """Whether this user's discovery already ran inside the recency-guard
    window, from ANY trigger (this cron, a manual Sync click, or an
    operator's manual sweep re-run) — see
    :func:`discovery_sweep_min_interval_seconds`.

    A read fault is NOT treated as "recently swept": the exception propagates
    so the caller can decide (fail toward NOT skipping real eligible work,
    same discipline ``_spend_cap_breach`` documents for its own read fault).
    """
    from app.db import get_connection

    window = discovery_sweep_min_interval_seconds()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT 1 FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" = 'scout'
                  AND "createdAt" >= NOW() - make_interval(secs => %s)
                LIMIT 1
                ''',
                (user_id, window),
            )
            return cur.fetchone() is not None


async def discovery_sweep_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ task: run one subscriber's discovery pass (scout + fitScorer) off
    the event loop.

    Delegates to ``app.routers.agents._execute_discovery_for_user`` — the
    SAME function ``POST /agents/discovery/sweep`` calls per user — so this
    worker path and the HTTP path can never diverge in what "discovery for
    one user" means. Called directly, in-process: no HTTP self-call, no
    ``X-Aether-System-Run`` secret needed.
    """
    import asyncio

    from app.routers.agents import _execute_discovery_for_user

    return await asyncio.to_thread(_execute_discovery_for_user, user_id)


async def discovery_sweep_cron(ctx: Any) -> int:
    """ARQ cron: enqueue one discovery pass per eligible, not-recently-swept
    subscriber.

    Eligibility is ``app.routers.agents._sweep_eligible_users`` VERBATIM — the
    identical entitled + real-``targetRole`` population
    ``POST /agents/discovery/sweep`` already served; this function invents no
    new membership rule. ``_job_id=f"discovery-sweep:<user_id>"`` makes the
    enqueue idempotent while a user's pass is queued or running (ARQ dedups on
    job id), so overlapping ticks can never stack concurrent passes for the
    same user — the same idiom ``board_sweep_cron`` uses.

    Honest, non-secret logging: one summary line naming how many users were
    eligible, how many were actually enqueued, and how many were skipped as
    already recently swept — never a silent no-op with no trace.
    """
    if not discovery_cron_enabled():
        logger.info(
            "discovery-sweep cron: disabled (AETHER_DISCOVERY_CRON_ENABLED=false)"
        )
        return 0
    from app.routers.agents import _positive_int_env, _sweep_eligible_users

    cap = _positive_int_env("AETHER_DISCOVERY_SWEEP_USER_CAP", 25)
    users = _sweep_eligible_users(cap)
    enqueued = 0
    skipped_recent = 0
    for user in users:
        user_id = str(user["id"])
        if _recently_swept(user_id):
            skipped_recent += 1
            continue
        job = await ctx["redis"].enqueue_job(
            "discovery_sweep_user", user_id, _job_id=f"discovery-sweep:{user_id}"
        )
        if job is not None:
            enqueued += 1
    if users:
        logger.info(
            "discovery-sweep cron: %d user(s) eligible, %d enqueued, "
            "%d skipped (recently swept)",
            len(users), enqueued, skipped_recent,
        )
    return enqueued
