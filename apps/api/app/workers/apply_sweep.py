"""U5 — the NO-PREPARED-ONLY sweep: nothing the user approved stays stuck.

U-PLAN "U5 MANDATE SHARPENED", binding rule 1 (verbatim): *"every application
the user approves must reach a TERMINAL state: TRANSMITTED (email or web-form,
with evidence screenshot + transmittedAt/channel) or an HONEST ACTIONABLE
state … never silently stuck in prepared; a sweep job re-drives non-terminal
applications."*

That rule exists because of a measured production defect, not a hypothetical:
the submission scout found **339 approved ``application_submit`` approvals with
``executedAt = NULL``** and ``Application.transmittedAt`` NULL on all 512 rows
(2026-08-13). Real users approved real sends that nothing ever performed,
because the only transmission path in the product needed an ``applyEmail`` and
0 of 7760 Job rows have one.

This module is the thing that drives them. Every pass:

* selects ONLY applications whose own ``ApprovalRequest(type=
  'application_submit')`` is ``approved`` — a pending gate is never touched,
  because approval-gating is an absolute, not a heuristic;
* skips anything already terminal (``transmittedAt`` set, or a manual-step
  reason recorded), so a completed submission is never re-driven and no
  employer receives the same application twice;
* counts a :class:`ManualStepRequired` as DRIVEN, not skipped: the row now
  carries an honest, actionable obstacle (the employer's real question, a
  CAPTCHA, a login wall), which is exactly what the invariant accepts in place
  of a transmission;
* counts an :class:`ApplyExecutorGuardError` as skipped: the approval was
  already executed or is no longer approved — someone else's terminal outcome,
  not ours to redo.

Channel precedence is the mandate's: a posting that publishes an apply address
goes through the EXISTING W-SUB Gmail path untouched; everything else goes to
the site apply-executor; Seek never goes anywhere (ADR-SEEK-V3).

KNOWN BOUND, stated rather than hidden: a TRANSPORT failure (the browser could
not open the page, the site timed out) is counted ``failed`` and the row stays
eligible for the next pass instead of being written down as a manual step.
That is deliberate — telling a user "go apply yourself" because our browser
blipped would be a false claim about their application — but it does mean such
a row is non-terminal BETWEEN passes, and a permanently unreachable site would
be retried each tick. A persistent per-application failure counter (the
``board_sweep`` backoff pattern) is the honest fix and belongs to the next
slice; until then the failures are logged, every pass is bounded, and nothing
is ever recorded as sent.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from app.db import (
    ensure_application_apply_channel_column,
    ensure_application_manual_step_columns,
    ensure_application_transmission_columns,
    ensure_user_profile_columns,
    get_connection,
    rows_to_dicts,
)

logger = logging.getLogger(__name__)


def sweep_enabled() -> bool:
    """Kill-switch: ``AETHER_APPLY_SWEEP_ENABLED`` (code default OFF).

    OFF by default because this is the one background job in the product that
    can put a document in front of a real employer. It is turned on
    deliberately, in the deployment's ``.env``, exactly like the board sweep.
    """
    return os.environ.get("AETHER_APPLY_SWEEP_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def sweep_stretch_seconds() -> float:
    """Wall-clock budget for one user's sweep pass (default 480s, floor 60s)."""
    try:
        seconds = float(os.environ.get("AETHER_APPLY_SWEEP_STRETCH_SECONDS", "480"))
    except ValueError:
        seconds = 480.0
    return max(60.0, seconds)


def sweep_max_applications() -> int:
    """Applications attempted per pass (default 5).

    Small on purpose: each attempt drives a real browser on a 2-CPU VM and puts
    a real application in front of a real employer. Throughput is not the goal
    — eventually reaching a terminal state for every approved row is.
    """
    try:
        return max(1, int(os.environ.get("AETHER_APPLY_SWEEP_MAX_APPLICATIONS", "5")))
    except (TypeError, ValueError):
        return 5


def sweep_user_cap() -> int:
    """Users enqueued per cron tick (default 20)."""
    try:
        return max(1, int(os.environ.get("AETHER_APPLY_SWEEP_MAX_USERS", "20")))
    except (TypeError, ValueError):
        return 20


def evidence_root() -> str:
    """Where confirmation screenshots are persisted.

    ``AETHER_APPLY_EVIDENCE_DIR``; defaults inside the repo's evidence tree so
    a submission's proof lives next to every other piece of run evidence.
    """
    return (
        os.environ.get("AETHER_APPLY_EVIDENCE_DIR")
        or "/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/"
        "agents-uplift/u5/submissions"
    )


# ---------------------------------------------------------------------------
# Row selection.
# ---------------------------------------------------------------------------


def pending_transmissions(user_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Approved-but-non-terminal applications, newest approval per application.

    This query IS the invariant's definition, written once: approved gate,
    no ``transmittedAt``, no ``manualStepReason``.
    """
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT DISTINCT ON (a."id")
                       a."id" AS "applicationId",
                       ar."id" AS "approvalId"
                FROM "Application" a
                JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
                WHERE a."userId" = %s
                  AND ar."userId" = %s
                  AND ar."type" = 'application_submit'::"ApprovalType"
                  AND ar."status" = 'approved'::"ApprovalStatus"
                  AND a."transmittedAt" IS NULL
                  AND a."manualStepReason" IS NULL
                ORDER BY a."id", ar."createdAt" DESC
                ''',
                (user_id, user_id),
            )
            rows = rows_to_dicts(cur)
    if limit is not None:
        return rows[:limit]
    return rows


def users_with_pending_transmissions(limit: int | None = None) -> list[str]:
    """Users who currently own at least one approved-but-non-terminal row."""
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT DISTINCT a."userId"
                FROM "Application" a
                JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
                WHERE ar."type" = 'application_submit'::"ApprovalType"
                  AND ar."status" = 'approved'::"ApprovalStatus"
                  AND a."transmittedAt" IS NULL
                  AND a."manualStepReason" IS NULL
                ORDER BY a."userId"
                ''',
            )
            user_ids = [row[0] for row in cur.fetchall()]
    return user_ids[:limit] if limit is not None else user_ids


# ---------------------------------------------------------------------------
# The per-application attempt (the seam the sweep tests monkeypatch).
# ---------------------------------------------------------------------------


def _load_application(user_id: str, application_id: str) -> dict[str, Any] | None:
    ensure_application_apply_channel_column()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT a."id", a."jobId", a."resumeId", a."coverLetter", a."applyChannel", '
                'a."answers", j."sourceUrl", j."applyEmail", j."title", j."company" '
                'FROM "Application" a JOIN "Job" j ON j."id" = a."jobId" '
                'WHERE a."id" = %s AND a."userId" = %s',
                (application_id, user_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _load_user(user_id: str) -> dict[str, Any] | None:
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "email", "name", "location", "agentConfig" '
                'FROM "User" WHERE "id" = %s',
                (user_id,),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _resume_contact(user_id: str, resume_id: str | None) -> dict[str, Any]:
    """Contact facts the user already gave us, off their own résumé row.

    Read-only and strictly factual: these are values the user typed into their
    own document, which is why they are safe to put into an employer's form.
    Nothing is derived or guessed.
    """
    if not resume_id:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "sections" FROM "Resume" WHERE "id" = %s AND "userId" = %s',
                (resume_id, user_id),
            )
            row = cur.fetchone()
    sections = row[0] if row else None
    if not isinstance(sections, dict):
        return {}
    contact = sections.get("contact")
    return contact if isinstance(contact, dict) else {}


def build_apply_profile(
    user_id: str,
    resume_id: str | None,
    application_answers: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The user's own facts, assembled for a form fill — nothing invented.

    Sources, in order of authority: answers recorded against THIS application
    (``Application.answers.screeningAnswers`` — what the user typed after a
    manual step told them exactly which question was blocking it), then the
    ``applyProfile`` block they maintain in their agent settings (including
    account-wide ``customAnswers``), then their account record, then the
    contact block of their own résumé. Every one of those is something the
    user themselves wrote down; nothing here is derived from the job ad, the
    employer, or a model.
    """
    user = _load_user(user_id) or {}
    config = user.get("agentConfig")
    config = config if isinstance(config, dict) else {}
    apply_profile = config.get("applyProfile")
    apply_profile = apply_profile if isinstance(apply_profile, dict) else {}
    contact = _resume_contact(user_id, resume_id)
    profile: dict[str, Any] = {
        "name": apply_profile.get("name") or user.get("name") or contact.get("name") or "",
        "email": apply_profile.get("email") or user.get("email") or contact.get("email") or "",
        "phone": apply_profile.get("phone") or contact.get("phone") or "",
        "location": apply_profile.get("location")
        or user.get("location")
        or contact.get("location")
        or "",
        "country": apply_profile.get("country") or "",
        "linkedin": apply_profile.get("linkedin") or contact.get("linkedin") or "",
        "website": apply_profile.get("website") or contact.get("website") or "",
    }
    for optional in ("firstName", "lastName", "preferredName"):
        if apply_profile.get(optional):
            profile[optional] = apply_profile[optional]
    answers = apply_profile.get("customAnswers")
    custom: dict[str, Any] = dict(answers) if isinstance(answers, dict) else {}
    per_application = (application_answers or {}).get("screeningAnswers")
    if isinstance(per_application, dict):
        custom.update(per_application)
    profile["customAnswers"] = custom
    return profile


def _transmit_by_email(user_id: str, application: dict[str, Any], approval_id: str) -> None:
    """Hand this application to the EXISTING W-SUB Gmail path, unchanged.

    The claim/release/complete sequence mirrors
    ``application_submission.maybe_autonomous_transmit`` exactly (same
    repository methods, same order) so the email path keeps its single-shot
    guarantee and this module adds no second implementation of it.
    """
    from app.repositories.approval import ApprovalRepository
    from app.services.application_submission import (
        SubmissionRefused,
        SubmissionTransportError,
        transmit_application,
    )
    from app.services.apply_executor import ApplyExecutorGuardError, ManualStepRequired

    repo = ApprovalRepository()
    approval = repo.get_by_id(approval_id, user_id)
    if approval is None or approval.get("status") != "approved":
        raise ApplyExecutorGuardError(
            "not_approved", "This application is no longer approved for sending."
        )
    if not repo.claim_execution(approval_id, user_id):
        raise ApplyExecutorGuardError(
            "already_executed", "This application was already sent."
        )
    user = _load_user(user_id)
    if user is None:
        repo.release_execution(approval_id, user_id)
        raise ApplyExecutorGuardError("user_not_found", "Nothing was sent.")
    try:
        transmit_application(user, approval)
    except SubmissionRefused as exc:
        repo.release_execution(approval_id, user_id)
        from app.services.apply_executor import record_manual_step

        record_manual_step(user_id, application["id"], exc.reason, exc.message)
        raise ManualStepRequired(exc.reason, exc.message) from exc
    except SubmissionTransportError:
        repo.release_execution(approval_id, user_id)
        raise
    repo.complete_execution(approval_id, user_id)


def _attempt_transmission(user_id: str, application_id: str, approval_id: str) -> None:
    """Drive ONE approved application to a terminal state.

    Returns normally only when something was really transmitted. Raises
    :class:`ManualStepRequired` when the honest outcome is an actionable
    obstacle (already persisted on the row by the executor), or
    :class:`ApplyExecutorGuardError` when the approval is no longer ours to
    execute. This is the seam the sweep's orchestration tests replace.
    """
    from app.services.apply_channel_resolver import (
        AUTOMATABLE_CHANNELS,
        resolve_and_persist_apply_channel,
    )
    from app.services.apply_executor import (
        ManualStepRequired,
        execute_site_application,
        fetch_apply_page,
        record_manual_step,
    )

    application = _load_application(user_id, application_id)
    if application is None:
        raise ManualStepRequired(
            "application_missing",
            "The application behind this approval no longer exists.",
        )
    job_row = {
        "sourceUrl": application.get("sourceUrl"),
        "applyEmail": application.get("applyEmail"),
    }
    resolved = resolve_and_persist_apply_channel(user_id, application_id, job_row)
    channel = str(resolved["channel"])
    if channel == "email":
        _transmit_by_email(user_id, application, approval_id)
        return
    if channel not in AUTOMATABLE_CHANNELS:
        reason, message = _no_channel_reason(channel, application)
        record_manual_step(user_id, application_id, reason, message)
        raise ManualStepRequired(reason, message)
    apply_url = str(resolved.get("applyUrl") or "")
    if not apply_url:
        # Defensive: an automatable channel is only ever derived FROM a URL, so
        # this cannot normally happen — and if it ever did, the executor would
        # fall into its replay mode and record a submission that never left the
        # building. Refuse instead, honestly.
        reason, message = _no_channel_reason("unknown", application)
        record_manual_step(user_id, application_id, reason, message)
        raise ManualStepRequired(reason, message)
    answers = application.get("answers")
    profile = build_apply_profile(
        user_id,
        application.get("resumeId"),
        answers if isinstance(answers, dict) else None,
    )
    resume_pdf = _render_resume_pdf(user_id, application)
    page_html = fetch_apply_page(apply_url)
    execute_site_application(
        user_id,
        application_id,
        approval_id,
        page_html=page_html,
        channel=channel,
        profile=profile,
        resume_pdf_bytes=resume_pdf,
        cover_letter_text=str(application.get("coverLetter") or ""),
        evidence_dir=evidence_root(),
        apply_url=apply_url,
    )


def _no_channel_reason(channel: str, application: dict[str, Any]) -> tuple[str, str]:
    if channel == "seek-manual":
        return (
            "seek_manual_only",
            (
                "This role is posted on Seek, which prohibits automated access "
                "(ADR-SEEK-V3). Aether will not scrape or submit there — open "
                f"the posting and apply yourself: {application.get('sourceUrl') or ''}"
            ).strip(),
        )
    return (
        "no_automatable_channel",
        (
            "Aether could not determine where this posting's application "
            "actually goes (the link is an aggregator redirect that would not "
            "resolve, or the posting gives no application destination), so it "
            "submitted nothing. Open the posting and apply yourself: "
            f"{application.get('sourceUrl') or ''}"
        ).strip(),
    )


def _render_resume_pdf(user_id: str, application: dict[str, Any]) -> bytes:
    """This application's OWN tailored résumé, through the real download path.

    ``resolve_email_attachments`` is the same in-process call the W-SUB email
    path uses, which is itself the same handler behind the user's own Download
    button — so the employer receives byte-identically what the user can see.
    """
    from app.services.email_attachments import resolve_email_attachments

    user = _load_user(user_id) or {"id": user_id}
    resume_id = application.get("resumeId")
    if not resume_id:
        return b""
    attachments = resolve_email_attachments(user, resume_id=str(resume_id))
    return attachments[0][1] if attachments else b""


# ---------------------------------------------------------------------------
# The sweep itself.
# ---------------------------------------------------------------------------


def sweep_pending_transmissions(
    user_id: str, *, deadline: float | None = None
) -> dict[str, Any]:
    """Drive every approved-but-non-terminal application for one user.

    Idempotent by construction: the selection query excludes anything already
    terminal, so a second pass over a board the first pass finished does no
    work at all and touches nothing.
    """
    from app.services.apply_executor import ApplyExecutorGuardError, ManualStepRequired

    rows = pending_transmissions(user_id, limit=sweep_max_applications())
    summary: dict[str, Any] = {
        "processed": 0,
        "transmitted": 0,
        "manual_step": 0,
        "skipped": 0,
        "failed": 0,
        "userId": user_id,
    }
    for row in rows:
        if deadline is not None and time.monotonic() >= deadline:
            logger.info(
                "apply sweep for user %s stopped at the wall-clock deadline "
                "with %d application(s) still pending — the next pass resumes "
                "exactly where this one stopped",
                user_id, len(rows) - summary["processed"],
            )
            break
        application_id = str(row["applicationId"])
        approval_id = str(row["approvalId"])
        summary["processed"] += 1
        try:
            _attempt_transmission(user_id, application_id, approval_id)
        except ManualStepRequired as exc:
            # DRIVEN, not skipped: the executor has already written the honest
            # obstacle onto the row, so the application is no longer "prepared
            # only" even though nothing was sent.
            summary["manual_step"] += 1
            logger.info(
                "apply sweep: application %s needs a manual step (%s)",
                application_id, exc.reason,
            )
            continue
        except ApplyExecutorGuardError as exc:
            summary["skipped"] += 1
            logger.info(
                "apply sweep: application %s skipped (%s) — already someone "
                "else's terminal outcome",
                application_id, exc.reason,
            )
            continue
        except Exception as exc:  # noqa: BLE001 — one bad row must not end the pass
            summary["failed"] += 1
            logger.warning(
                "apply sweep: application %s attempt failed (%s: %s) — nothing "
                "was submitted for it and it stays eligible for the next pass",
                application_id, type(exc).__name__, exc,
            )
            continue
        summary["transmitted"] += 1
    return summary


async def apply_sweep_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ job: one bounded sweep pass for one user."""
    if not sweep_enabled():
        return {"skipped": "disabled", "userId": user_id}
    deadline = time.monotonic() + sweep_stretch_seconds()
    return sweep_pending_transmissions(user_id, deadline=deadline)


async def apply_sweep_cron(ctx: Any) -> int:
    """ARQ cron tick: enqueue a sweep pass per user with pending work.

    A no-op unless ``AETHER_APPLY_SWEEP_ENABLED`` is on, mirroring
    ``board_sweep_cron``'s shape so the two autopilots are operated the same
    way.
    """
    if not sweep_enabled():
        return 0
    try:
        user_ids = users_with_pending_transmissions(limit=sweep_user_cap())
    except Exception as exc:  # noqa: BLE001 — a cron tick must not kill the worker
        logger.warning("apply sweep cron could not list users: %s", type(exc).__name__)
        return 0
    redis = ctx.get("redis") if isinstance(ctx, dict) else None
    if redis is None:
        logger.warning(
            "apply sweep cron has no redis in its context — %d user(s) with "
            "pending transmissions were NOT enqueued",
            len(user_ids),
        )
        return 0
    enqueued = 0
    for user_id in user_ids:
        try:
            await redis.enqueue_job("apply_sweep_user", user_id)
            enqueued += 1
        except Exception as exc:  # noqa: BLE001 — one bad enqueue is not a dead tick
            logger.warning(
                "apply sweep cron could not enqueue user %s: %s", user_id, type(exc).__name__
            )
    return enqueued
