"""ARQ cron — the daily notification digest (FEAT-EMAIL-BRAND, RUN-20260818T0223Z).

GAP CLOSED: ``NotificationAgent.run()`` (the "daily job-application summary")
has always existed and always composed a correctly BRANDED email
(``approvals.py`` renders ``kind="notification_digest"`` through
``email_branding.build_notification_digest_bodies``) — but NOTHING ever
triggered it automatically. It only ran when a human POSTed
``/agents/run mode=notification``. This module is the trigger: one ARQ cron
tick, once a day, that runs the SAME code path for every user who could
possibly receive a digest.

HONEST SCOPE — this cron closes the "nothing schedules it" gap. It does NOT,
and must NOT, make the digest email actually LEAVE the building on its own:
``NotificationAgent.run()`` queues a ``kind="notification_digest"``
``ApprovalRequest`` (``outreach_support.queue_email_approval`` — "nothing is
sent here"), and that approval sits PENDING until the user (or an admin)
calls ``POST /approvals/{id}/execute``. There is no auto-approve / auto-send
setting anywhere in the approvals system for any kind, and this cron does not
invent one — that would be a policy decision for the product owner, not
something a scheduler should silently assume. So today, this cron makes the
digest get COMPOSED and QUEUED automatically, every day, for every eligible
user; the send itself remains a one-click manual approval, exactly as it is
for a manually-triggered run.

Mirrors the manual trigger EXACTLY (``app.routers.agents``, mode
``"notification"``): same callable resolution, same pause check
(``AgentConfig.enabled`` for the ``notification`` card —
``_agent_paused_by_user`` inside ``_dispatch``), same GAP-P6-PAYWALL
subscription gate (``notification`` is NOT in ``_SYSTEM_RUN_EXEMPT_AGENTS``,
so ``system_run=True`` does not bypass it — an unentitled user gets the same
honest 402 a manual click would). Called directly as a Python function
(``app.routers.agents._dispatch``), never over HTTP — same idiom as
``board_sweep._run_agent``.

Cadence: daily at 21:00 UTC, minute :11. 21:00 UTC is early-to-mid morning in
Melbourne (AEST UTC+10 -> 07:00; AEDT UTC+11 -> 08:00), so the Owner's digest
is waiting when their day starts. Minute :11 is deliberately off every other
registered tick (`:00/:05/...`, `:02/:07/...`, `:07/:22/...`, `:15/:45`) so
this cron never contends with another autopilot for the same wall-clock
minute on this 2-CPU VPS.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("aether.worker.digest")

#: Env values (case-insensitive) that DISABLE the cron. Code default ON — the
#: whole point of this module is that the digest stops being manual-trigger
#: -only; an operator who needs to kill it sets this rather than deleting the
#: registration.
_DIGEST_CRON_OFF = frozenset({"false", "0", "no", "off"})


def digest_cron_enabled() -> bool:
    """Kill-switch: ``AETHER_DIGEST_CRON_ENABLED`` (default TRUE).

    Read via ``os.environ`` on every call — no value is baked into source, so
    an operator can flip it live without a redeploy, same convention as every
    other cron's enable flag in this module (``sweep_enabled``,
    ``sales_agent_enabled``).
    """
    return os.environ.get(
        "AETHER_DIGEST_CRON_ENABLED", "true"
    ).strip().lower() not in _DIGEST_CRON_OFF


def _eligible_user_ids() -> list[str]:
    """Users the cron will attempt a digest for: everyone with a connected
    Gmail account. See :meth:`GmailAccountRepository.list_connected_user_ids`
    for why this — and only this — is the bound."""
    from app.repositories.gmail_account import GmailAccountRepository

    return GmailAccountRepository().list_connected_user_ids()


def _run_notification_for_user(user_id: str) -> dict[str, Any]:
    """Run the notification agent for one user through the EXACT seam
    ``POST /agents/run mode=notification`` uses (``_dispatch`` ->
    ``_record_run`` -> ``NotificationAgent().run(user_id)``), called directly
    as a Python function — never an HTTP self-call. ``system_run=True`` marks
    the AgentRun's billing audit honestly (``systemRun: true``); it does NOT
    bypass the subscription gate for ``notification`` (only
    ``_SYSTEM_RUN_EXEMPT_AGENTS`` — scout/fitScorer — get that exemption), so
    an unentitled user is refused with the identical 402 a manual click would
    get. ``skip_quota=True`` mirrors the board-sweep's automated-system-run
    convention; it is a no-op for this specific agent (``notification`` is
    deterministic/unmetered — no LLM call is ever made, so no run-count quota
    is reserved either way), kept for consistency with every other automated
    dispatch in this codebase rather than for any functional effect here.
    """
    from app.routers.agents import _dispatch

    return _dispatch(user_id, "notification", {}, system_run=True, skip_quota=True)


def _skip_reason(exc: "Exception") -> str:
    """Honest, stable label for a per-user refusal — never swallowed, always
    counted under a name that says what actually happened.

    ``_dispatch``'s own pause pre-check raises a PLAIN-STRING 409
    (``"agent_paused: notification is stopped..."``); the (defense-in-depth,
    normally unreachable here) ``_execute_reserved_run`` pause guard and the
    GAP-P6-PAYWALL subscription gate both raise a DICT detail
    (``{"code": "agent_paused", ...}`` / ``{"error": "subscription_required",
    ...}``). All three shapes are read here so the label is right regardless
    of which layer actually fired.
    """
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
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
    return f"error_{type(exc).__name__}"


async def notification_digest_cron(ctx: Any) -> dict[str, Any]:
    """ARQ cron: run one notification-digest attempt per Gmail-connected user,
    once a day (21:00 UTC — see module docstring for the offset rationale).

    Honest per-user outcomes, never silently dropped:
    * ``enqueued`` — a real ``notification_digest`` approval was queued (or
      refreshed, if one was already pending) for the user to send;
    * ``no_activity`` — the agent ran and genuinely found nothing new since
      the user's last SENT digest (``NotificationAgent`` itself refuses to
      queue an empty "update" email — that would be fabricated activity);
    * ``gmail_disconnected`` — the user disconnected Gmail between the
      eligibility read and the run (a real race, not an error);
    * any other reason (``paused``, ``subscription_required``, an HTTP status,
      or an exception class name) is counted under its own honest label —
      never merged into a generic "failed" bucket that would hide WHY.

    A single user's failure never aborts the tick for every other user
    (mirrors ``board_sweep_cron``'s per-user isolation) — one broken account
    must not silence everyone else's digest.
    """
    import asyncio

    _ = ctx
    if not digest_cron_enabled():
        logger.info("digest cron: disabled (AETHER_DIGEST_CRON_ENABLED=false)")
        return {"ran": False, "reason": "disabled"}

    users = _eligible_user_ids()
    enqueued = 0
    outcomes: dict[str, int] = {}

    def _tally(label: str) -> None:
        outcomes[label] = outcomes.get(label, 0) + 1

    for user_id in users:
        try:
            result = await asyncio.to_thread(_run_notification_for_user, user_id)
        except Exception as exc:  # noqa: BLE001 — one user must not sink the tick
            reason = _skip_reason(exc)
            _tally(reason)
            if reason.startswith("error_"):
                logger.exception("digest cron %s: unexpected failure", user_id)
            else:
                logger.info("digest cron %s: skipped (%s)", user_id, reason)
            continue
        if result.get("approvalId"):
            enqueued += 1
            _tally("enqueued")
        elif result.get("nothingToReport"):
            _tally("no_activity")
        elif not result.get("gmailConnected"):
            _tally("gmail_disconnected")
        else:  # pragma: no cover — defensive: every known return shape is above
            _tally("queued_without_approval")

    logger.info(
        "digest cron: %d user(s) eligible, %d enqueued (%s)",
        len(users), enqueued,
        ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items())) or "no outcomes",
    )
    return {"eligible": len(users), "enqueued": enqueued, "outcomes": outcomes}
