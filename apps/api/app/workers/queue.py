"""ARQ pool/enqueue seam (GAP-P7-ASYNC-001, blueprint §3.2/§4).

The API's run handlers are synchronous ``def`` (FastAPI runs them on its anyio
threadpool). ARQ's ``enqueue_job`` is a coroutine, so the sync handler bridges
via ``asyncio.run`` around ``_get_arq_pool().enqueue_job(...)``.

To keep the redis connection bound to exactly one event loop, ``_ArqEnqueuer``
opens a short-lived pool INSIDE the same coroutine as the enqueue and closes it
in ``finally`` — so each ``asyncio.run(...)`` bridge is fully self-contained.
Enqueue volume is low (result bodies live in Postgres, not Redis), so per-call
pool setup is cheap. Tests substitute a ``FakeArqPool`` at the
``agents._get_arq_pool`` seam, so this module is never imported under test.
"""
from __future__ import annotations

import os


def redis_settings():
    """Build ARQ ``RedisSettings`` from ``AETHER_REDIS_URL`` (set at deploy)."""
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(os.environ["AETHER_REDIS_URL"])


class _ArqEnqueuer:
    """Sync-bridgeable ARQ enqueuer matching the ``FakeArqPool`` test double:
    an object exposing ``async enqueue_job(func_name, *args)`` that returns a
    job carrying a ``.job_id``."""

    async def enqueue_job(self, function_name: str, *args, **kwargs):
        from arq import create_pool

        pool = await create_pool(redis_settings())
        try:
            return await pool.enqueue_job(function_name, *args, **kwargs)
        finally:
            await pool.close()


def get_arq_pool() -> _ArqEnqueuer:
    return _ArqEnqueuer()


#: Fallback ARQ per-job execution ceiling, in seconds.
#:
#: MON-020 raised this from 600s. 600s predated background discovery: the
#: production discovery cron's own log (``/var/log/aether/discovery.log``,
#: 1318 recorded scout runs) measures a full scout pass at 255-473s in the
#: current window with a 968s worst case, so a 600s ceiling would kill a
#: genuinely HEALTHY discovery run part-way through — and ARQ's retry would
#: then redo work that was already half done. 1200s clears the measured worst
#: case with headroom while staying bounded.
_DEFAULT_JOB_TIMEOUT_SECONDS = 1200


def job_timeout_seconds() -> int:
    """The worker's per-job execution ceiling (``AETHER_WORKER_JOB_TIMEOUT_SECONDS``).

    Read from the environment on every call — no value is baked into source, so
    an operator retunes it in ``.env`` without a code change. Floored at 60s so
    a malformed value can never produce a worker that kills every job instantly.

    This is the single authority on that ceiling: the ARQ ``WorkerSettings`` sets
    ``job_timeout`` from it, and ``routers.agents._job_stale_thresholds`` derives
    the "processing" staleness window from it, which is what keeps the watchdog
    structurally unable to fail a job the worker is still allowed to be running.
    """
    try:
        seconds = int(
            os.environ.get(
                "AETHER_WORKER_JOB_TIMEOUT_SECONDS", str(_DEFAULT_JOB_TIMEOUT_SECONDS)
            )
        )
    except ValueError:
        seconds = _DEFAULT_JOB_TIMEOUT_SECONDS
    return max(60, seconds)
