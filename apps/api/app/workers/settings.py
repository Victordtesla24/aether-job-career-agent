"""ARQ ``WorkerSettings`` for the aether-worker process (blueprint §4.2).

Run with: ``arq app.workers.settings.WorkerSettings`` (see ``start-worker.sh``).
The worker process loads the repo-root ``.env`` (via the wrapper) so
``AETHER_REDIS_URL`` / ``DATABASE_URL`` / credentials / budgets are present.
"""
from __future__ import annotations

import os

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

        return [cron(sweep_stale_jobs, minute=set(range(0, 60, 5)))]  # every 5 min
    except Exception:  # noqa: BLE001 — cron optional; enqueue path is primary
        return []


class WorkerSettings:
    functions = [run_agent_job]
    cron_jobs = _cron_jobs()
    redis_settings = _redis_settings()
    max_jobs = 3        # 2 vCPU / ~2.5 GB free -> modest concurrency
    job_timeout = 600   # > largest worker LLM budget so ARQ never kills mid-run
    keep_result = 300   # Postgres BackgroundJob is authoritative anyway
    max_tries = 3       # applies only to re-raised transient errors
