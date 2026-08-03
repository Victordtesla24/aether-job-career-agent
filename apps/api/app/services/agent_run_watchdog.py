"""Abandoned-``AgentRun`` reconciliation + worker heartbeat (CRITICAL-1).

THE INCIDENT THIS EXISTS FOR
----------------------------
Measured in production on 2026-08-03: one ``tailor`` AgentRun had been
``status='running'`` since 2026-07-26 03:41:20 UTC — **192.6 hours (8 days)**.
No process was attached to it. ``aether-worker`` had been restarted at
2026-08-03 00:17, which would have killed any real job. Nothing in the codebase
ever reconciled a ``running`` AgentRun row, so it survived every restart
forever, and the dashboard kept presenting it as an ACTIVE run — the product
concealed a week of total inactivity instead of surfacing it.

``BackgroundJob`` already had a watchdog (``workers.tasks.sweep_stale_jobs``).
``AgentRun`` — the row the UI actually renders — had none. This module is that
missing half.

WHY A HEARTBEAT AND NOT JUST AN AGE LIMIT
-----------------------------------------
Timing a run out on age alone would murder a legitimately long run. So the
worker/API stamps ``AgentRun.heartbeatAt`` every
``AETHER_AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS`` while the run executes (see
:func:`agent_run_heartbeat`, wired into ``routers.agents._execute_reserved_run``
— the ONE seam both the sync HTTP path and the ARQ worker share). Reconciliation
then splits into two disjoint cases:

* **Heartbeat present but stale** → the owning process proved it was alive and
  then stopped proving it. Reconciled after
  ``AETHER_AGENT_RUN_HEARTBEAT_STALE_SECONDS``, regardless of total age. A live
  run keeps stamping and is therefore untouchable no matter how long it runs.
* **No heartbeat ever** → the row predates this watchdog, or the process died
  before execution began. No liveness evidence exists either way, so the
  generous wall-clock ceiling ``AETHER_AGENT_RUN_MAX_SECONDS`` applies.

DEFAULTS DERIVED FROM REAL OBSERVED DURATIONS (not guessed)
-----------------------------------------------------------
Query run against production (schema ``aether``) on 2026-08-03::

    SELECT "agentName", count(*) n,
           percentile_cont(0.95) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM ("completedAt"-"startedAt"))) p95_s,
           max(EXTRACT(EPOCH FROM ("completedAt"-"startedAt"))) max_s
    FROM "AgentRun"
    WHERE status='completed' AND "completedAt" IS NOT NULL
      AND "startedAt" IS NOT NULL
    GROUP BY 1 ORDER BY max_s DESC;

Result (top rows, seconds)::

    agentName        n      p95_s    max_s
    fitScorer      733        8.1    403.4   <- global maximum ever completed
    scout          722       58.4    381.6
    tailor         256      289.7    312.9
    coverLetter   2053       44.3    301.9
    storyExtractor  47       67.2     75.6
    emailAgent      50       53.9     62.6

So across 3 984 completed runs the WORST case ever observed is 403.4 s and the
worst p95 is 289.7 s (tailor). The process-level ceilings are ARQ's own:
``job_timeout = 600`` for a single job and ``timeout=900`` for the board sweep
(``app/workers/settings.py``) — nothing can legitimately still be executing
past 900 s, because ARQ kills it.

``_MAX_RUN_SECONDS_DEFAULT = 1800`` (30 min) is therefore **4.5x the longest run
ever completed** and **2x ARQ's largest hard timeout** — generous enough that it
can only ever fire on a genuinely dead row, tight enough that an abandoned run
surfaces within half an hour instead of eight days.

``_HEARTBEAT_STALE_SECONDS_DEFAULT = 300`` (5 min) is 10 consecutive missed
30 s stamps. ``_STARTUP_STALE_SECONDS_DEFAULT = 120`` is the tighter threshold
used at process startup, when the point is to reconcile the runs THIS restart
just orphaned; it is still 4 consecutive missed stamps, so a run being executed
by a sibling process is never reaped by it.

SCOPE — WHAT THIS DELIBERATELY DOES NOT DO
------------------------------------------
It does not refund plan quota. Quota refunds are performed by
``routers.agents._execute_reserved_run`` (sync) and by the atomic
first-terminal-wins ``BackgroundJob`` transition in ``workers.tasks``
(async), and ``UsageQuotaRepository.refund_run`` is a per-user counter
decrement with no per-run idempotency key — refunding from here would risk
double-refunding a run one of those paths already refunded. Reconciliation is
therefore confined to the audit row's own truthfulness. Stated plainly rather
than half-implemented.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.repositories.agent_run import AgentRunRepository

#: See the module docstring for the production query these come from.
_MAX_RUN_SECONDS_DEFAULT = 1800.0
_MAX_RUN_SECONDS_FLOOR = 900.0  # ARQ's largest hard job timeout
_HEARTBEAT_STALE_SECONDS_DEFAULT = 300.0
_HEARTBEAT_INTERVAL_SECONDS_DEFAULT = 30.0
_STARTUP_STALE_SECONDS_DEFAULT = 120.0


def _env_float(name: str, default: float, floor: float) -> float:
    """Read a positive float from the environment, clamped at ``floor``.

    The clamp is a safety guard, not politeness: a ceiling configured below
    ARQ's own job timeout would let the watchdog fail runs that are still
    legitimately executing, which is exactly the failure mode this whole module
    exists to avoid. A malformed value falls back to the default rather than
    taking a process down at import time.
    """
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return max(value, floor)


def get_max_run_seconds() -> float:
    """Wall-clock ceiling for a run that never produced a single heartbeat."""
    return _env_float(
        "AETHER_AGENT_RUN_MAX_SECONDS",
        _MAX_RUN_SECONDS_DEFAULT,
        _MAX_RUN_SECONDS_FLOOR,
    )


def get_heartbeat_stale_seconds() -> float:
    """How long a heartbeat may go unstamped before the owner is presumed dead."""
    return _env_float(
        "AETHER_AGENT_RUN_HEARTBEAT_STALE_SECONDS",
        _HEARTBEAT_STALE_SECONDS_DEFAULT,
        # Never below 4 stamp intervals: 3 missed stamps must not be fatal.
        4 * get_heartbeat_interval_seconds(),
    )


def get_heartbeat_interval_seconds() -> float:
    """How often an executing run stamps ``heartbeatAt``."""
    return _env_float(
        "AETHER_AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS",
        _HEARTBEAT_INTERVAL_SECONDS_DEFAULT,
        1.0,
    )


def get_startup_stale_seconds() -> float:
    """Heartbeat-staleness threshold used at API/worker startup.

    Tighter than the steady-state one so a restart reconciles the runs it just
    orphaned promptly, but still 4 consecutive missed 30 s stamps — a run being
    executed right now by a sibling process is never reaped by somebody else's
    boot.
    """
    return _env_float(
        "AETHER_AGENT_RUN_STARTUP_STALE_SECONDS",
        _STARTUP_STALE_SECONDS_DEFAULT,
        4 * get_heartbeat_interval_seconds(),
    )


@dataclass
class ReconcileOutcome:
    """Evidence, not vibes: counts before and after, and what was touched."""

    reason: str
    before: int = 0
    after: int = 0
    reconciled: int = 0
    max_run_seconds: float = 0.0
    heartbeat_stale_seconds: float = 0.0
    run_ids: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"agent-run watchdog [{self.reason}]: abandoned before={self.before} "
            f"reconciled={self.reconciled} after={self.after} "
            f"(ceiling={self.max_run_seconds:.0f}s, "
            f"heartbeatStale={self.heartbeat_stale_seconds:.0f}s)"
        )


def _honest_error(row: dict) -> str:
    """The message the owner sees. It names the real cause and nothing else."""
    agent = row.get("agentName") or "agent"
    age_h = float(row.get("ageSeconds") or 0.0) / 3600.0
    hb_age = row.get("heartbeatAgeSeconds")
    if hb_age is None:
        return (
            f"Run abandoned — no worker heartbeat was ever recorded for this "
            f"{agent} run and it exceeded the {get_max_run_seconds():.0f}s "
            f"wall-clock ceiling (it had been marked running for {age_h:.1f} "
            "hours). The process that owned it died or was restarted; no "
            "result was produced and no work is in progress. Re-run the agent "
            "to try again."
        )
    return (
        f"Run abandoned — no worker heartbeat for {float(hb_age) / 60.0:.1f} "
        f"minutes on this {agent} run (it had been marked running for "
        f"{age_h:.1f} hours). The process that owned it died or was restarted; "
        "no result was produced and no work is in progress. Re-run the agent "
        "to try again."
    )


def reconcile_abandoned_agent_runs(
    *,
    reason: str = "periodic",
    heartbeat_stale_seconds: float | None = None,
) -> ReconcileOutcome:
    """Fail every ``running`` AgentRun that no live process owns.

    Never deletes a row, never writes ``completed``, and never touches a run
    whose heartbeat is fresh. Safe to call concurrently from the API, the
    worker and the cron: each row is transitioned by a single atomic
    first-terminal-wins UPDATE.
    """
    repo = AgentRunRepository()
    stale = (
        get_heartbeat_stale_seconds()
        if heartbeat_stale_seconds is None
        else float(heartbeat_stale_seconds)
    )
    ceiling = get_max_run_seconds()
    outcome = ReconcileOutcome(
        reason=reason, max_run_seconds=ceiling, heartbeat_stale_seconds=stale
    )
    outcome.before = repo.count_abandoned(stale, ceiling)
    for row in repo.list_abandoned(stale, ceiling):
        if repo.fail_abandoned(row["id"], _honest_error(row)):
            outcome.reconciled += 1
            outcome.run_ids.append(row["id"])
    outcome.after = repo.count_abandoned(stale, ceiling)
    return outcome


def reconcile_on_startup(reason: str) -> ReconcileOutcome | None:
    """Best-effort startup reconciliation, with the tighter startup threshold.

    BEST-EFFORT ON PURPOSE, exactly like the other startup chores in
    ``app.main._lifespan``: both ``aether-api.service`` and
    ``aether-worker.service`` run with ``Restart=on-failure``, so raising here
    would convert a transient DB hiccup into a crash loop — turning a
    data-hygiene problem into a total outage. Failures are logged loudly.
    """
    import sys

    try:
        outcome = reconcile_abandoned_agent_runs(
            reason=reason, heartbeat_stale_seconds=get_startup_stale_seconds()
        )
    except Exception as exc:  # noqa: BLE001 — never take a process down for this
        print(
            "WARNING: abandoned-AgentRun reconciliation did not run at "
            f"startup ({reason}); zombie 'running' rows may still be shown as "
            f"active: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None
    if outcome.before or outcome.reconciled:
        print(outcome.summary(), file=sys.stderr, flush=True)
    return outcome


@contextmanager
def agent_run_heartbeat(
    run_id: str, interval_seconds: float | None = None
) -> Iterator[None]:
    """Stamp ``AgentRun.heartbeatAt`` for as long as the body executes.

    A daemon thread does the stamping so a blocking multi-minute LLM call in
    the calling thread cannot starve it, and so a hung stamp can never hold the
    process open at shutdown. Every stamp is best-effort: a database blip must
    never fail an otherwise-successful run. The loop self-terminates as soon as
    the run leaves ``running`` (``AgentRunRepository.heartbeat`` returns False),
    so it cannot outlive the run it belongs to.
    """
    interval = (
        get_heartbeat_interval_seconds()
        if interval_seconds is None
        else max(float(interval_seconds), 0.01)
    )
    stop = threading.Event()
    repo = AgentRunRepository()

    def _loop() -> None:
        while True:
            try:
                if not repo.heartbeat(run_id):
                    return  # terminal (or gone) — nothing left to stamp
            except Exception:  # noqa: BLE001 — liveness stamping is best-effort
                pass
            if stop.wait(interval):
                return

    thread = threading.Thread(
        target=_loop, name=f"agent-run-heartbeat-{run_id[:8]}", daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2.0)
