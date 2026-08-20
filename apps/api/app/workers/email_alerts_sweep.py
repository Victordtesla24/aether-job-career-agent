"""EMAIL-CENTER -> JOBS automation (RUN-20260818T0223Z).

GAP CLOSED: Owner directive — inbox job-ad emails (Seek/LinkedIn/etc.) must
automatically become Job cards. The parse pipeline has always been fully
wired: ``EmailAgent._job_alerts`` (``apps/api/app/agents/email_agent.py``)
reads every connected mailbox, ``app.services.job_alert_parser`` extracts
each posting deterministically (regex/HTML, never an LLM — an LLM guessing
an employer name out of an email is exactly the fabrication this product
refuses), and every posting lands through the EXISTING
``JobRepository.create`` path (``apps/api/app/repositories/job.py``) so the
usual ``(userId, sourceUrl)`` upsert / dedup / ``lastSeenAt`` logic applies
and the job appears on the web board through the unchanged
``routers/jobs.py`` read path. BUT ``apps/api/app/workers/settings.py`` never
registered a cron for it — the ONLY trigger was the manual "Scan Job Alerts"
button (``apps/web/src/app/dashboard/email/page.tsx``, ``mode: "job_alerts"``).
Nothing ever ran it automatically. This module is the missing trigger; the
parse pipeline itself is untouched.

Follows the EXACT house pattern of ``apps/api/app/workers/discovery_sweep.py``'s
``discovery_sweep_cron`` / ``discovery_sweep_user`` split: the cron tick only
reads eligibility + the recency guard and ENQUEUES one per-user ARQ job
(``_job_id=f"email-alerts:<user_id>"``, the same idempotent-dedup idiom
board-sweep/discovery-sweep use so overlapping ticks can never stack a
concurrent pass for the same user), and the per-user job
(``email_alerts_user``) does the actual dispatch off the event loop via
``asyncio.to_thread``.

ELIGIBILITY: ``GmailAccountRepository.list_connected_user_ids`` — the SAME
primitive ``digest_cron.py`` uses for its own Gmail-dependent automated
trigger. It already joins ``User`` and excludes suspended
(``COALESCE(u."suspended", false) = false``) and soft-deleted
(``u."deletedAt" IS NULL``) accounts (see that method's docstring for the
adversarial-review history behind those two clauses) — this cron invents no
new eligibility rule and inherits that exclusion for free. A user with no
connected Gmail account has no mailbox to scan and is never even attempted.

DISPATCH: the per-user job calls ``app.routers.agents._dispatch(user_id,
"emailAgent", {"mode": "job_alerts"}, system_run=True, skip_quota=True)``
directly, in-process — no HTTP self-call, so no ``X-Aether-System-Run``
secret is needed from inside the worker. This is the SAME seam
``POST /agents/run`` (mode ``job_alerts``, the manual button) uses, so the
worker path and the manual path can never diverge in what "scan my job-alert
mail" means. ``job_alerts`` is a provably zero-LLM mode
(``_EMAIL_AGENT_NO_LLM_MODES`` in ``routers/agents.py`` — deterministic
regex/HTML parsing only), so ``skip_quota=True`` costs nothing functionally
here; it is kept for consistency with every other automated dispatch in this
codebase. ``system_run=True`` does NOT bypass the GAP-P6-PAYWALL gate for
``emailAgent`` (only ``scout``/``fitScorer`` are exempt —
``_SYSTEM_RUN_EXEMPT_AGENTS``), so an unentitled user is refused the same
honest 402 a manual click would get, and a user who paused the Email Agent
via Agent Controls is refused the same honest 409 — both are recorded on the
per-user result row, never bypassed.

CADENCE: every 30 minutes, at minute :18 and :48 — the cadence recorded for
this unit in the pre-implementation interdependency remediation plan
(docs/delivery/evidence/RUN-20260818T0223Z/INTERDEP/01-remediation-plan.md,
"Unit 1"), chosen to be distinct from every other cron on this worker,
including the lightweight watchdog ticks: ``board_sweep_cron``
:00/10/20/30/40/50, ``apply_sweep_cron`` :07/22/37/52, ``sales_agent_cron``
:15/:45, ``discovery_sweep_cron`` :03/:33, ``notification_digest_cron`` daily
21:11, ``reconcile_abandoned_agent_runs_cron``'s every-5-minute :02/07/.../57,
and ``sweep_stale_jobs``'s every-5-minute :00/05/.../55 — :18 and :48 land on
none of them (18 mod 5 = 3, 48 mod 5 = 3; neither watchdog uses that
remainder). It also stays clear of :24/:54, reserved in the same plan for the
sibling Unit 2 (networking-refresh cron), which is explicitly out of scope
for this fix. Registered in ``apps/api/app/workers/settings.py::_cron_jobs()``.

RECENCY GUARD (``AETHER_EMAIL_ALERTS_MIN_INTERVAL_SECONDS``, default 1500s =
25 min, floored at 60s): the minimum time since a user's last ``emailAgent``
``AgentRun`` with ``input.mode`` in ``job_alerts``/``job-alerts`` before the
cron will enqueue them again. Protects against a user who just clicked "Scan
Job Alerts" moments before the next tick fires being re-enqueued for a
duplicate, cost-free-but-wasteful mailbox re-scan. Mirrors
``discovery_sweep``'s own recency guard exactly, including its R4 discipline
(closes that module's R3 delta review P1 Finding 2): a transient DB fault on
ONE user's recency read is caught PER USER inside the loop and fails toward
NOT skipping — a fault can never silently abort enqueueing for every
later-ordered eligible user in the same tick.

KILL-SWITCH: ``AETHER_EMAIL_ALERTS_CRON_ENABLED`` (default TRUE) — the Owner
directive is that connected inboxes get real automatic job-alert intake
without an operator opt-in, exactly the same default-on posture
``discovery_sweep.py`` documents for the identical reason. The switch still
lets an operator turn it off (incident response, a bad deploy) without a code
change.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

#: ``AgentRun.input->>'mode'`` values that count as a job-alerts run for the
#: recency guard — mirrors ``EmailAgent.run``'s own alias handling
#: (``mode in ("job_alerts", "job-alerts")``) so a run dispatched either way
#: is recognised.
_JOB_ALERT_MODES = ("job_alerts", "job-alerts")


def email_alerts_cron_enabled() -> bool:
    """Kill-switch: ``AETHER_EMAIL_ALERTS_CRON_ENABLED`` (default TRUE — see
    module docstring for why this cron is default-on rather than opt-in)."""
    return os.environ.get("AETHER_EMAIL_ALERTS_CRON_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def email_alerts_min_interval_seconds() -> float:
    """Recency guard (env-tunable, default 1500s = 25 min): the minimum time
    since a user's last ``job_alerts`` ``AgentRun`` before the cron will
    enqueue them again. Floored at 60s so a bad value can never make the
    guard a no-op."""
    try:
        seconds = float(
            os.environ.get("AETHER_EMAIL_ALERTS_MIN_INTERVAL_SECONDS", "1500")
        )
    except ValueError:
        seconds = 1500.0
    return max(60.0, seconds)


def _eligible_user_ids() -> list[str]:
    """Users the cron will attempt a job-alerts pass for: everyone with at
    least one connected Gmail account (and, via the join inside
    ``list_connected_user_ids``, a still-live, non-suspended ``User`` row).
    See that method's docstring — SAME primitive ``digest_cron.py`` uses."""
    from app.repositories.gmail_account import GmailAccountRepository

    return GmailAccountRepository().list_connected_user_ids()


def _recently_ran_job_alerts(user_id: str) -> bool:
    """Whether this user's ``job_alerts`` mode already ran inside the
    recency-guard window, from ANY trigger (this cron or a manual "Scan Job
    Alerts" click) — see :func:`email_alerts_min_interval_seconds`.

    Raises on a DB read fault — this function makes NO fault-handling
    decision itself. ``email_alerts_cron`` is the ONE caller and catches this
    PER USER, inside its loop, failing toward NOT skipping (treating the
    fault as "not recently run" for that one user) so a transient fault on
    any one user's read can never abort enqueueing for every later-ordered
    eligible user in the same tick — same discipline as
    ``discovery_sweep._recently_swept``.
    """
    from app.db import get_connection

    window = email_alerts_min_interval_seconds()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT 1 FROM "AgentRun"
                WHERE "userId" = %s AND "agentName" = 'emailAgent'
                  AND "input"->>'mode' = ANY(%s)
                  AND "createdAt" >= NOW() - make_interval(secs => %s)
                LIMIT 1
                ''',
                (user_id, list(_JOB_ALERT_MODES), window),
            )
            return cur.fetchone() is not None


def _skip_reason(exc: "Any") -> str:
    """Honest, stable label for a per-user refusal raised out of ``_dispatch``.

    Mirrors ``digest_cron._skip_reason`` exactly: ``_dispatch``'s own pause
    pre-check raises a PLAIN-STRING 409 (``"agent_paused: emailAgent is
    stopped..."``); the (defense-in-depth) ``_execute_reserved_run`` pause
    guard and the GAP-P6-PAYWALL subscription gate both raise a DICT detail
    (``{"code": "agent_paused", ...}`` / ``{"error": "subscription_required",
    ...}``). All three shapes are read here so the label is right regardless
    of which layer actually fired.
    """
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("error")
        if code:
            return str(code)
    elif isinstance(detail, str) and detail.startswith("agent_paused"):
        return "paused"
    if exc.status_code == 409:
        return "paused"
    if exc.status_code == 402:
        return "subscription_required"
    return f"http_{exc.status_code}"


def _run_job_alerts_for_user(user_id: str) -> dict[str, Any]:
    """One user's ``job_alerts`` intake pass, through the SAME
    ``app.routers.agents._dispatch`` the manual "Scan Job Alerts" button uses
    — an honest per-user result row. Never raises: every failure (a paused
    Email Agent, no active subscription, a dead mailbox reported inside
    ``JobAlertIntakeResult.per_account``) is caught and reported on the row
    instead of aborting the caller.
    """
    from fastapi import HTTPException

    from app.routers.agents import _dispatch

    row: dict[str, Any] = {
        "userId": user_id, "status": "ok", "jobsCreated": 0, "jobsUpdated": 0,
        "alertEmails": 0, "error": None,
    }
    try:
        result = _dispatch(
            user_id, "emailAgent", {"mode": "job_alerts"},
            system_run=True, skip_quota=True,
        )
        row["jobsCreated"] = int(result.get("jobs_created") or 0)
        row["jobsUpdated"] = int(result.get("jobs_updated") or 0)
        row["alertEmails"] = int(result.get("alert_emails") or 0)
        if result.get("degraded"):
            row["degraded"] = True
    except HTTPException as exc:
        row["status"] = "error"
        row["error"] = _skip_reason(exc)
        logger.info(
            "email-alerts sweep: user %s skipped (%s)", user_id, row["error"],
        )
    except Exception as exc:  # noqa: BLE001 — one user must not crash the ARQ job
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "email-alerts sweep: user %s failed: %s", user_id, row["error"],
        )
    return row


async def email_alerts_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ task: run one user's ``job_alerts`` intake pass off the event loop.

    Called directly, in-process, by the cron below — no HTTP self-call, no
    ``X-Aether-System-Run`` secret needed. Mirrors
    ``discovery_sweep.discovery_sweep_user``'s ``asyncio.to_thread`` shape.
    """
    import asyncio

    _ = ctx
    return await asyncio.to_thread(_run_job_alerts_for_user, user_id)


async def email_alerts_cron(ctx: Any) -> int:
    """ARQ cron: enqueue one ``job_alerts`` intake pass per Gmail-connected,
    not-recently-run user, every 30 minutes (see module docstring for the
    cadence rationale).

    Honest, non-secret logging: one summary line ALWAYS fires (never only on
    a failure path) naming how many users were eligible, how many were
    enqueued, how many were skipped as already recently run, and how many
    per-user recency-check faults were absorbed (failed toward not-skipping).
    """
    if not email_alerts_cron_enabled():
        logger.info(
            "email-alerts cron: disabled (AETHER_EMAIL_ALERTS_CRON_ENABLED=false)"
        )
        return 0
    users = _eligible_user_ids()
    enqueued = 0
    skipped_recent = 0
    recency_check_faults = 0
    for user_id in users:
        try:
            recently = _recently_ran_job_alerts(user_id)
        except Exception:
            recency_check_faults += 1
            recently = False
            logger.warning(
                "email-alerts cron: recency check failed for user %s — "
                "failing toward NOT skipping (proceeding to enqueue)",
                user_id, exc_info=True,
            )
        if recently:
            skipped_recent += 1
            continue
        job = await ctx["redis"].enqueue_job(
            "email_alerts_user", user_id, _job_id=f"email-alerts:{user_id}"
        )
        if job is not None:
            enqueued += 1
    if users:
        logger.info(
            "email-alerts cron: %d user(s) eligible, %d enqueued, %d skipped "
            "(recently ran job_alerts), %d recency-check fault(s) (failed "
            "toward not-skipping)",
            len(users), enqueued, skipped_recent, recency_check_faults,
        )
    return enqueued
