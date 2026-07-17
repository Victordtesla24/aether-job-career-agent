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
