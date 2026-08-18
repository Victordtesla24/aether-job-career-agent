"""ARQ ``WorkerSettings`` for the aether-worker process (blueprint §4.2).

Run with: ``arq app.workers.settings.WorkerSettings`` (see ``start-worker.sh``).
The worker process loads the repo-root ``.env`` (via the wrapper) so
``AETHER_REDIS_URL`` / ``DATABASE_URL`` / credentials / budgets are present.
"""
from __future__ import annotations

import os

from app.workers.agent_directives_sweep import agent_directives_cron
from app.workers.apply_sweep import apply_sweep_cron, apply_sweep_user
from app.workers.board_sweep import board_sweep_cron, board_sweep_user
from app.workers.digest_cron import notification_digest_cron
from app.workers.discovery_sweep import discovery_sweep_cron, discovery_sweep_user
from app.workers.queue import job_timeout_seconds
from app.workers.sales_cron import sales_agent_cron
from app.workers.tasks import (
    reconcile_abandoned_agent_runs_cron,
    run_agent_job,
    sweep_stale_jobs,
)


def _redis_settings():
    """ARQ ``RedisSettings`` from ``AETHER_REDIS_URL`` with a safe localhost
    fallback so importing this module never crashes when the env is absent
    (the deployer sets the real URL in ``.env`` — §7.2)."""
    from arq.connections import RedisSettings

    dsn = os.environ.get("AETHER_REDIS_URL", "redis://127.0.0.1:6379/3")
    return RedisSettings.from_dsn(dsn)


def _cron_jobs():
    try:
        from arq import cron

        return [
            cron(sweep_stale_jobs, minute=set(range(0, 60, 5))),  # every 5 min
            # RT-007 autopilot tick — every 10 min; a no-op unless
            # AETHER_BOARD_SWEEP_ENABLED is on and users have board work.
            cron(board_sweep_cron, minute=set(range(0, 60, 10))),
            # CRITICAL-1 abandoned-AgentRun watchdog — every 5 min. Bounds how
            # long a zombie 'running' row can be shown to the owner as an ACTIVE
            # run to one cron interval; before this existed the bound was
            # "forever" (8 days observed in production).
            cron(
                reconcile_abandoned_agent_runs_cron,
                minute=set(range(2, 60, 5)),
            ),
            # FEAT-EMAIL-BRAND digest cron — once daily at 21:00 UTC, minute
            # :11. 21:00 UTC lands early-to-mid morning in Melbourne (AEST
            # UTC+10 -> 07:00; AEDT UTC+11 -> 08:00), so the Owner's digest is
            # queued before their day starts. Minute :11 is off every other
            # registered tick above/below (:00/:05.., :02/:07.., :07/:22..,
            # :15/:45) so it never contends with another autopilot for the
            # same wall-clock minute on this 2-CPU VPS. Honest no-op unless
            # AETHER_DIGEST_CRON_ENABLED is on (code default TRUE — see
            # ``digest_cron_enabled``); queues an approval per eligible user,
            # it never sends: notification_digest stays a manual-approval
            # send like every other queued email (see digest_cron.py header).
            cron(notification_digest_cron, hour={21}, minute={11}),
            # U5 NO-PREPARED-ONLY tick — every 15 min, offset off the board
            # sweep so the two autopilots never contend for this 2-CPU VM. A
            # no-op unless AETHER_APPLY_SWEEP_ENABLED is on AND the user has
            # applications sitting on an APPROVED gate with no terminal state.
            cron(apply_sweep_cron, minute=set(range(7, 60, 15))),
            # Native Sales AI — every 30 min at :15/:45, offset from discovery
            # and board-sweep. Honest no-op unless AETHER_SALES_AGENT_ENABLED
            # is on. This is the Hostinger scheduler; do not also enable the
            # Abacus-era systemd timer (double-run).
            cron(sales_agent_cron, minute={15, 45}),
            # AUD-AGENT-3 — the Stage-1 rules cadence rules_stage_evaluate
            # never had (0 AgentDirective rows ever on production; see
            # docs/delivery/evidence/RUN-20260818T0223Z/AUD-AGENT-3/). Daily
            # at 03:20 UTC (off-hour, offset from aether-backup.timer's 6h
            # cadence): the rule table is deterministic/$0/no-LLM (its own
            # docstring), so there is no cost pressure for a tighter interval.
            # A no-op unless AETHER_AGI_DIRECTIVES_ENABLED is on — see
            # agent_directives_sweep.directives_enabled for why this cadence
            # gates on that flag more conservatively than the manual endpoint.
            cron(agent_directives_cron, hour={3}, minute={20}),
            # GAP-P7-DISCOVERY-002 (R3, closes R2 delta review P0 Finding 1) —
            # the real periodic discovery mechanism restoring the Owner
            # directive: every 30 min at :03/:33 (offset from board-sweep
            # :00/10/20/30/40/50, apply-sweep :07/22/37/52, sales :15/:45, and
            # the stale-job watchdog's :00/05/10.../55). Enqueues one
            # discovery pass per eligible, not-recently-swept entitled
            # subscriber. Honest no-op unless AETHER_DISCOVERY_CRON_ENABLED is
            # on (code default ON — see discovery_sweep.py). This IS the
            # scheduler; the Abacus-era `aether-discovery.timer` systemd unit
            # this cron replaces does not exist on this host.
            cron(discovery_sweep_cron, minute={3, 33}),
        ]
    except Exception:  # noqa: BLE001 — cron optional; enqueue path is primary
        return []


def _apply_sweep_func():
    """Register the apply sweep with headroom above the global 600s timeout.

    One attempt drives a real browser twice (fetch the live form, then fill and
    submit it) against an employer's site, so a pass of several applications
    can legitimately outlast a normal job while still being bounded by
    ``AETHER_APPLY_SWEEP_STRETCH_SECONDS``.
    """
    try:
        from arq.worker import func

        return func(apply_sweep_user, timeout=900)
    except Exception:  # noqa: BLE001 — fall back to the plain coroutine
        return apply_sweep_user


def _sweep_func():
    """Register the sweep with a timeout ABOVE the global 600s: a stretch may
    legitimately start its last tailor near the 540s mark and needs headroom
    for that step to finish rather than being killed mid-generation."""
    try:
        from arq.worker import func

        return func(board_sweep_user, timeout=900)
    except Exception:  # noqa: BLE001 — fall back to the plain coroutine
        return board_sweep_user


async def _on_startup(ctx) -> None:
    """Reconcile every AgentRun this worker orphaned when it died (CRITICAL-1).

    A worker restart kills whatever it was executing mid-flight, leaving the
    ``AgentRun`` row at ``status='running'`` with nobody behind it — that is
    exactly how the observed 8-day zombie was created (``aether-worker`` was
    restarted 2026-08-03 00:17). Running this on EVERY start means a restart
    cleans up after itself instead of leaving the owner staring at a run that
    will never finish. Uses the tighter startup heartbeat threshold; a run being
    executed right now by a sibling process is still stamping and is untouched.
    """
    from app.services.agent_run_watchdog import reconcile_on_startup

    reconcile_on_startup("worker-startup")


class WorkerSettings:
    functions = [run_agent_job, _sweep_func(), _apply_sweep_func(), discovery_sweep_user]
    cron_jobs = _cron_jobs()
    on_startup = _on_startup
    redis_settings = _redis_settings()
    max_jobs = 3        # 2 vCPU / ~2.5 GB free -> modest concurrency
    # > largest worker LLM budget AND > the measured worst-case discovery pass,
    # so ARQ never kills a healthy run mid-flight. Sourced from ONE authority
    # (workers.queue.job_timeout_seconds) that the stale-job watchdog also
    # derives from — see that function for the measurement behind the default.
    job_timeout = job_timeout_seconds()
    keep_result = 300   # Postgres BackgroundJob is authoritative anyway
    max_tries = 3       # applies only to re-raised transient errors
