"""ARQ ``WorkerSettings`` for the aether-worker process (blueprint §4.2).

Run with: ``arq app.workers.settings.WorkerSettings`` (see ``start-worker.sh``).
The worker process loads the repo-root ``.env`` (via the wrapper) so
``AETHER_REDIS_URL`` / ``DATABASE_URL`` / credentials / budgets are present.
"""
from __future__ import annotations

import os

from app.workers.board_sweep import board_sweep_cron, board_sweep_user
from app.workers.tasks import run_agent_job, sweep_stale_jobs


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
        ]
    except Exception:  # noqa: BLE001 — cron optional; enqueue path is primary
        return []


def _sweep_func():
    """Register the sweep with a timeout ABOVE the global 600s: a stretch may
    legitimately start its last tailor near the 540s mark and needs headroom
    for that step to finish rather than being killed mid-generation."""
    try:
        from arq.worker import func

        return func(board_sweep_user, timeout=900)
    except Exception:  # noqa: BLE001 — fall back to the plain coroutine
        return board_sweep_user


class WorkerSettings:
    functions = [run_agent_job, _sweep_func()]
    cron_jobs = _cron_jobs()
    redis_settings = _redis_settings()
    max_jobs = 3        # 2 vCPU / ~2.5 GB free -> modest concurrency
    job_timeout = 600   # > largest worker LLM budget so ARQ never kills mid-run
    keep_result = 300   # Postgres BackgroundJob is authoritative anyway
    max_tries = 3       # applies only to re-raised transient errors
