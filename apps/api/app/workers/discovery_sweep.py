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


def rotation_pool_size() -> int:
    """How many eligible users the cron reads EACH TICK to compute a fair
    rotation order (R4, closes R3 delta review P2 Finding 3) — env-tunable,
    default 500.

    Independent of ``AETHER_DISCOVERY_SWEEP_USER_CAP``, which still bounds
    how many of THOSE are actually enqueued per tick (the pre-existing
    per-request cost bound the manual endpoint also uses, unchanged). Must be
    >= the enqueue cap to have any rotation effect at all —
    ``discovery_sweep_cron`` takes the larger of the two defensively.
    """
    try:
        return max(1, int(os.environ.get("AETHER_DISCOVERY_SWEEP_ROTATION_POOL_SIZE", "500")))
    except (TypeError, ValueError):
        return 500


def _last_scout_run_at(user_ids: list[str]) -> dict[str, Any]:
    """``{user_id: most recent scout AgentRun.createdAt}`` for the given ids.

    A user absent from the mapping has never run scout. ONE bulk, set-wise
    statement (the same idiom ``board_sweep._letterless_counts`` uses for the
    same MON-001 reason) rather than a per-user read — used only to compute
    :func:`_rotate_least_recently_swept`'s ordering, never as the
    enqueue/skip gate itself (``_recently_swept`` remains the single
    authority for that, re-derived fresh immediately before each enqueue).
    """
    from app.db import get_connection

    if not user_ids:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT "userId", MAX("createdAt")
                FROM "AgentRun"
                WHERE "agentName" = 'scout' AND "userId" = ANY(%s)
                GROUP BY "userId"
                ''',
                (user_ids,),
            )
            return {row[0]: row[1] for row in cur.fetchall()}


def _rotate_least_recently_swept(
    users: list[dict[str, str]], cap: int
) -> list[dict[str, str]]:
    """Reorder the eligible pool so the cron's per-tick selection prioritises
    users who have gone LONGEST without a scout run (or never run one at
    all) — not merely the oldest ACCOUNTS (R4, closes R3 delta review P2
    Finding 3).

    THE STARVATION THIS CLOSES: ``_sweep_eligible_users`` (shared verbatim
    with the manual ``POST /agents/discovery/sweep`` endpoint — its own
    ``ORDER BY "createdAt" ASC`` is UNCHANGED here and nowhere in this
    module) always returns the SAME oldest-N accounts first. Feeding that
    order directly to a per-tick ``LIMIT cap`` enqueue means that once the
    eligible population exceeds the cap, the identical oldest accounts win
    every single tick forever and every other eligible, equally-entitled
    subscriber is never automatically searched — a durable, silent
    starvation once population exceeds ``AETHER_DISCOVERY_SWEEP_USER_CAP``
    (default 25). This reorders a WIDER pool
    (:func:`rotation_pool_size`, independent of the per-tick enqueue cap) by
    least-recently-swept BEFORE truncating to ``cap``, so every eligible
    subscriber's priority strictly increases every tick they are not
    selected — no one can be starved past one full rotation of the pool.

    Deliberately a NO-OP (returns ``users`` unchanged) when the pool already
    fits inside ``cap`` — the common case at today's scale (a handful of
    users, per the environment manifest), where rotation has nothing to
    accomplish and the extra bulk read would be pure overhead.

    A read (or sort) fault degrades HONESTLY to the pre-rotation behaviour
    (the pool's own natural, oldest-account order, truncated at ``cap``)
    rather than aborting the tick — fairness is a best-effort refinement on
    top of a working cron, not a safety property this must crash to protect.
    """
    if len(users) <= cap:
        return users
    try:
        last_run = _last_scout_run_at([str(u["id"]) for u in users])
        ordered = sorted(
            users,
            key=lambda u: (
                last_run.get(str(u["id"])) is not None,
                last_run.get(str(u["id"])) or 0,
            ),
        )
    except Exception:
        logger.warning(
            "discovery-sweep cron: rotation-ordering read failed — falling "
            "back to the pool's natural (oldest-account) order for this tick",
            exc_info=True,
        )
        return users[:cap]
    return ordered[:cap]


def _recently_swept(user_id: str) -> bool:
    """Whether this user's discovery already ran inside the recency-guard
    window, from ANY trigger (this cron, a manual Sync click, or an
    operator's manual sweep re-run) — see
    :func:`discovery_sweep_min_interval_seconds`.

    Raises on a DB read fault — this function makes NO fault-handling
    decision itself. ``discovery_sweep_cron`` (R4, closes R3 delta review P1
    Finding 2) is the ONE caller and catches this PER USER, inside its loop,
    failing toward NOT skipping (i.e. treating the fault as "not recently
    swept" for that one user) so a transient fault on ANY one user's read can
    never abort enqueueing for every later-ordered eligible user in the same
    tick — see that function's docstring for the full contract.
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
    subscriber, fairly rotated across ticks once population exceeds the cap.

    Eligibility is ``app.routers.agents._sweep_eligible_users`` VERBATIM — the
    identical entitled + real-``targetRole`` population
    ``POST /agents/discovery/sweep`` already served; this function invents no
    new membership rule (the manual endpoint's own call — a SEPARATE call,
    with its own ``limit`` — is untouched by this cron's wider read).
    ``_job_id=f"discovery-sweep:<user_id>"`` makes the enqueue idempotent
    while a user's pass is queued or running (ARQ dedups on job id), so
    overlapping ticks can never stack concurrent passes for the same user —
    the same idiom ``board_sweep_cron`` uses.

    R4 (closes R3 delta review P2 Finding 3): reads a WIDER pool
    (:func:`rotation_pool_size`) than it enqueues (``cap``,
    ``AETHER_DISCOVERY_SWEEP_USER_CAP``), then applies
    :func:`_rotate_least_recently_swept` before truncating — see that
    function for why the raw ``ORDER BY createdAt`` pool alone would starve
    every subscriber past the cap forever.

    R4 (closes R3 delta review P1 Finding 2): the per-user
    :func:`_recently_swept` read is now INSIDE a per-iteration ``try/except``
    — a transient DB fault on ONE user's read no longer aborts the coroutine
    (and with it, this function's own advertised summary log line) before
    every LATER-ordered eligible user in the same tick is even considered. A
    fault is treated as "not recently swept" (fails toward NOT skipping real
    eligible work — the discipline this module's own ``_recently_swept``
    docstring already claimed, now actually enforced by the caller) and
    tallied honestly in the summary line rather than silently swallowed.

    Honest, non-secret logging: one summary line ALWAYS fires (moved out of
    the loop's failure path entirely) naming the pool size, how many were
    considered this tick after rotation, how many were actually enqueued, how
    many were skipped as already recently swept, and how many per-user
    recency-check faults were absorbed.
    """
    if not discovery_cron_enabled():
        logger.info(
            "discovery-sweep cron: disabled (AETHER_DISCOVERY_CRON_ENABLED=false)"
        )
        return 0
    from app.routers.agents import _positive_int_env, _sweep_eligible_users

    cap = _positive_int_env("AETHER_DISCOVERY_SWEEP_USER_CAP", 25)
    pool = _sweep_eligible_users(max(cap, rotation_pool_size()))
    users = _rotate_least_recently_swept(pool, cap)
    enqueued = 0
    skipped_recent = 0
    recency_check_faults = 0
    for user in users:
        user_id = str(user["id"])
        try:
            recently = _recently_swept(user_id)
        except Exception:
            recency_check_faults += 1
            recently = False
            logger.warning(
                "discovery-sweep cron: recency check failed for user %s — "
                "failing toward NOT skipping (proceeding to enqueue)",
                user_id, exc_info=True,
            )
        if recently:
            skipped_recent += 1
            continue
        job = await ctx["redis"].enqueue_job(
            "discovery_sweep_user", user_id, _job_id=f"discovery-sweep:{user_id}"
        )
        if job is not None:
            enqueued += 1
    if pool:
        logger.info(
            "discovery-sweep cron: %d user(s) eligible (pool), %d considered "
            "this tick, %d enqueued, %d skipped (recently swept), %d "
            "recency-check fault(s) (failed toward not-skipping)",
            len(pool), len(users), enqueued, skipped_recent, recency_check_faults,
        )
    return enqueued
