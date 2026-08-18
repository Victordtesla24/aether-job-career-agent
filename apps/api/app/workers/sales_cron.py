"""ARQ cron for the native Sales AI agent.

Hostinger production has no ``aether-sales-agent.timer`` (that unit targeted
the decommissioned Abacus VM). The production scheduler is this cron on
``aether-prod-worker``, every 30 minutes at :15 and :45, offset from the
board-sweep ticks. The agent's own DB idempotency still applies; do not also
enable the systemd timer on this VPS.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("aether.worker.sales")


async def sales_agent_cron(ctx: Any) -> dict[str, Any]:
    """One pipeline run, or an honest no-op when the feature flag is off."""
    from app.agents.sales_agent import run_sales_agent, sales_agent_enabled
    from app.repositories.sales import SalesRepository

    _ = ctx
    if not sales_agent_enabled():
        return {"ran": False, "reason": "disabled"}
    try:
        # Operator-copyable artefacts must carry the live origin before a LIVE
        # tick can send them. Historical sent/dry_run rows stay as mailed.
        SalesRepository().rewrite_retired_product_hosts()
        return await asyncio.to_thread(run_sales_agent, "timer")
    except Exception as exc:  # noqa: BLE001 — a cron tick must not kill the worker
        logger.exception("sales agent cron failed")
        return {"ran": False, "fatal": type(exc).__name__}
