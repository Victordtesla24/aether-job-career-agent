"""Async background-generation worker package (GAP-P7-ASYNC-001).

ARQ worker process (separate from aether-api) that drains the generation queue.
See ``docs/delivery/PHASE7-ASYNC-BLUEPRINT.md`` §4-§5. Entry point:
``arq app.workers.settings.WorkerSettings`` (via ``start-worker.sh``).
"""
