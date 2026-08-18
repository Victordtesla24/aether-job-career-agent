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
goes through the EXISTING W-SUB Gmail path untouched; a channel with a
dedicated, tested form parser goes to the site apply-executor; every other
resolved platform is ASSISTED (prepared artifacts + the direct link + "this
platform needs your click", ORCHESTRATOR RULING U5-F3); Seek never goes
anywhere (ADR-SEEK-V3).

Two bounds make this safe to point at the real 339-row backlog:

* **Stale approvals are never executed.** An approval older than
  ``AETHER_APPROVAL_MAX_AGE_DAYS`` (default 7) is not acted on; it is
  surfaced for a one-click re-confirmation instead
  (:func:`_expire_stale_approval` → ``POST /applications/{id}/reconfirm-submission``).
  A weeks-old click is not consent to send an application today.
* **Every pass is one bounded batch**, ``AETHER_APPLY_SWEEP_BATCH`` (default
  10), taken OLDEST APPROVAL FIRST, and the summary/log states how many
  applications remain queued — counted for real after the pass, not inferred.

THE USER'S OWN SETTINGS GATE EVERY AUTONOMOUS FIRE (audit wf_9a87f76f-eaa,
D1+D2). ``agentConfig.autoApply`` must be true before a user is swept at all —
the cron lists only opted-in users (:func:`users_with_pending_transmissions`)
and the job re-checks at execution time (:func:`sweep_user_if_opted_in`); the
``AETHER_APPLY_SWEEP_ENABLED`` env var stays the operator kill-switch ON TOP.
And within a pass, ``agentConfig.matchThreshold`` (default 80, AUD-UX-1) bars any
application whose job scores below it — or has no ``fitScore`` at all — from
being auto-transmitted: an honest, non-terminal ``skippedBelowThreshold``,
never a burned approval or a fabricated manual step. The user's explicit
approve-and-execute path bypasses the threshold by design.

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

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
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


def sweep_batch_size() -> int:
    """Transmissions attempted per pass (``AETHER_APPLY_SWEEP_BATCH``, default 10).

    Small on purpose: each attempt drives a real browser on a 2-CPU VM and puts
    a real application in front of a real employer. Throughput is not the goal
    — eventually reaching a terminal state for every approved row is, from the
    OLDEST approval first, one bounded batch at a time.

    ``AETHER_APPLY_SWEEP_MAX_APPLICATIONS`` (this module's original name for
    the same bound) is still honoured when an operator has set it, as an
    ADDITIONAL ceiling: a bound must never grow silently because it was
    renamed.
    """
    batch = _positive_int_env("AETHER_APPLY_SWEEP_BATCH", 10) or 10
    legacy = _positive_int_env("AETHER_APPLY_SWEEP_MAX_APPLICATIONS", None)
    return batch if legacy is None else min(batch, legacy)


def approval_max_age_days() -> float:
    """How old an approval may be and still be auto-executed (default 7 days).

    "The user approved this" is a fact with a shelf life. Production carries
    339 approved ``application_submit`` approvals that nothing has ever
    executed (scout, 2026-08-13); the oldest of them predate the product's
    current behaviour entirely. Turning the sweep on must NOT fire a weeks-old
    confirmation at a real employer — the user may have applied themselves,
    taken another job, or simply forgotten. An approval past this age is
    surfaced for a fresh, one-click confirmation instead
    (:func:`_expire_stale_approval`). ``AETHER_APPROVAL_MAX_AGE_DAYS`` tunes it
    without a redeploy; a malformed value falls back to the default rather than
    disabling the guard.
    """
    raw = (os.environ.get("AETHER_APPROVAL_MAX_AGE_DAYS") or "").strip()
    if not raw:
        return 7.0
    try:
        value = float(raw)
    except ValueError:
        return 7.0
    return value if value > 0 else 7.0


def _positive_int_env(name: str, default: int | None) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


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


#: The queue, written ONCE: approved gate, no ``transmittedAt``, no
#: ``manualStepReason``, newest approval per application. ``approvedAt`` is the
#: DECISION time (``resolvedAt``, falling back to ``createdAt`` for rows that
#: predate that column being stamped) — the clock the stale-approval guard
#: reads and the key the backlog drains by. ``fitScore`` rides along (LEFT
#: JOIN, so the selection itself is unchanged even for an application whose
#: Job row is gone) for the D2 match-threshold gate; NULL means "unscored",
#: which the gate treats as below every threshold.
_PENDING_SELECT = '''
    SELECT DISTINCT ON (a."id")
           a."id" AS "applicationId",
           ar."id" AS "approvalId",
           COALESCE(ar."resolvedAt", ar."createdAt") AS "approvedAt",
           j."fitScore" AS "fitScore"
    FROM "Application" a
    JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
    LEFT JOIN "Job" j ON j."id" = a."jobId"
    WHERE a."userId" = %s
      AND ar."userId" = %s
      AND ar."type" = 'application_submit'::"ApprovalType"
      AND ar."status" = 'approved'::"ApprovalStatus"
      AND a."transmittedAt" IS NULL
      AND a."manualStepReason" IS NULL
    ORDER BY a."id", ar."createdAt" DESC
'''


def pending_transmissions(user_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    """Approved-but-non-terminal applications, OLDEST APPROVAL FIRST.

    Ordering is part of the contract, not an implementation detail: the
    measured backlog is 339 rows deep, and a sweep that took an arbitrary slice
    each pass could starve the oldest approvals indefinitely. ``limit`` is
    applied in SQL so a bounded pass never materialises the whole backlog.
    """
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    sql = f'SELECT * FROM ({_PENDING_SELECT}) q ORDER BY q."approvedAt" ASC, q."applicationId"'
    params: tuple[Any, ...] = (user_id, user_id)
    if limit is not None:
        sql += " LIMIT %s"
        params = (*params, max(0, int(limit)))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return rows_to_dicts(cur)


def count_pending_transmissions(user_id: str) -> int:
    """How many approved applications are STILL queued, counted for real.

    Re-counted after a pass rather than derived as ``total - processed``: an
    attempt that fails in transport leaves its row queued, and a summary that
    quietly subtracted it would under-report the backlog on every tick.
    """
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*) FROM ({_PENDING_SELECT}) q', (user_id, user_id)
            )
            row = cur.fetchone()
    return int(row[0]) if row else 0


def users_with_pending_transmissions(limit: int | None = None) -> list[str]:
    """OPTED-IN users who own at least one approved-but-non-terminal row.

    D1 (audit wf_9a87f76f-eaa): the sweep honours the per-user
    ``agentConfig.autoApply`` toggle, so this lists ONLY users whose own
    Settings carry ``autoApply: true`` — a missing config, a missing key, or
    ``false`` all mean "do not sweep me". The Settings API writes the field as
    a JSON boolean, which ``->>`` reads back as the text ``'true'`` (the same
    truth ``application_submission.auto_apply_enabled`` computes in Python).
    The ``AETHER_APPLY_SWEEP_ENABLED`` env var remains the operator
    kill-switch ON TOP of this — both must be on before anyone is swept.
    """
    ensure_application_transmission_columns()
    ensure_application_manual_step_columns()
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                SELECT DISTINCT a."userId"
                FROM "Application" a
                JOIN "ApprovalRequest" ar ON ar."applicationId" = a."id"
                JOIN "User" u ON u."id" = a."userId"
                WHERE ar."type" = 'application_submit'::"ApprovalType"
                  AND ar."status" = 'approved'::"ApprovalStatus"
                  AND a."transmittedAt" IS NULL
                  AND a."manualStepReason" IS NULL
                  AND (u."agentConfig"->>'autoApply') = 'true'
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


#: Contact facts we can read off the user's OWN résumé text. Strictly
#: extractive — every value is a literal token the user themselves typed into
#: their document (an email, a phone number, a LinkedIn/GitHub URL). Nothing is
#: derived from the job, the employer, or a model; if a token is not physically
#: present in the text, the key is simply absent (never guessed, never asked
#: for when it IS present).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{7,}\d)(?!\w)")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/[^\s|,;]+", re.I)
_GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[^\s|,;]+", re.I)
_URL_RE = re.compile(r"https?://[^\s|,;]+", re.I)


def _extract_contact_from_text(raw_text: str) -> dict[str, Any]:
    """Pull the standard contact fields out of a résumé's raw text.

    PDF/DOCX and legacy text-only résumés keep contact facts as the lines of
    their own CONTACT block, not as a pre-structured ``contact`` map — so the
    facts the user already gave us live here and nowhere else. This reads them
    back verbatim so a form fill never asks for what the résumé already states.
    """
    text = raw_text or ""
    if not text.strip():
        return {}
    out: dict[str, Any] = {}
    m = _EMAIL_RE.search(text)
    if m:
        out["email"] = m.group(0).strip().rstrip(".")
    m = _PHONE_RE.search(text)
    if m:
        digits = re.sub(r"[^\d+]", "", m.group(1))
        # A real phone number, not a year/postcode/section number that happens
        # to sit near the top: require enough digits to be a phone.
        if len(re.sub(r"\D", "", digits)) >= 8:
            out["phone"] = m.group(1).strip()
    m = _LINKEDIN_RE.search(text)
    if m:
        out["linkedin"] = m.group(0).strip().rstrip("/.")
    m = _GITHUB_RE.search(text)
    if m:
        out["github"] = m.group(0).strip().rstrip("/.")
    for url in _URL_RE.finditer(text):
        u = url.group(0)
        if "linkedin.com" in u.lower() or "github.com" in u.lower():
            continue
        out["website"] = u.strip().rstrip("/.")
        break
    return out


def _resume_contact(user_id: str, resume_id: str | None) -> dict[str, Any]:
    """Contact facts the user already gave us, off their own résumé row.

    Read-only and strictly factual: these are values the user typed into their
    own document, which is why they are safe to put into an employer's form.
    Nothing is derived or guessed. Resolves the user's baseline résumé when no
    id is supplied, and — because the structured ``contact`` map is empty for
    every PDF/DOCX and legacy upload — falls back to reading the contact block
    straight out of the résumé's own text so the agent never asks for a phone,
    email, or profile URL that is sitting in the résumé it already holds.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            if resume_id:
                cur.execute(
                    'SELECT "sections" FROM "Resume" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (resume_id, user_id),
                )
            else:
                # No résumé pinned to this application — use the candidate's
                # baseline (or most recent) résumé; its contact facts are still
                # the candidate's own facts.
                cur.execute(
                    'SELECT "sections" FROM "Resume" WHERE "userId" = %s '
                    'ORDER BY ("parentId" IS NULL) DESC, "createdAt" DESC '
                    'LIMIT 1',
                    (user_id,),
                )
            row = cur.fetchone()
    sections = row[0] if row else None
    if not isinstance(sections, dict):
        return {}
    contact = sections.get("contact")
    contact = dict(contact) if isinstance(contact, dict) else {}
    # Backfill anything the structured map is missing from the résumé's own
    # text (the usual case: PDF/DOCX/legacy résumés carry it only as text).
    raw_text = sections.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        for key, value in _extract_contact_from_text(raw_text).items():
            if not contact.get(key):
                contact[key] = value
    return contact


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
        "github": apply_profile.get("github") or contact.get("github") or "",
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
    # U5d-3: the per-application answers are ALSO carried unmerged, keyed by
    # the employer's QUESTION TEXT rather than a field name. ``customAnswers``
    # is looked up by field name, so a question-keyed entry can never match
    # there; the Answer Bank resolver matches on the question itself, which is
    # what makes an in-card answer usable on the very next attempt.
    profile["screeningAnswers"] = (
        dict(per_application) if isinstance(per_application, dict) else {}
    )
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
        record_apply_url_resolution,
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
    apply_url = str(resolved.get("applyUrl") or application.get("sourceUrl") or "")
    if channel == "email":
        _transmit_by_email(user_id, application, approval_id)
        return
    if channel not in AUTOMATABLE_CHANNELS:
        reason, message = no_channel_reason(channel, application, apply_url)
        record_manual_step(user_id, application_id, reason, message)
        raise ManualStepRequired(reason, message)
    if not apply_url:
        # Defensive: an automatable channel is only ever derived FROM a URL, so
        # this cannot normally happen — and if it ever did, the executor would
        # fall into its replay mode and record a submission that never left the
        # building. Refuse instead, honestly.
        reason, message = no_channel_reason("unknown", application, "")
        record_manual_step(user_id, application_id, reason, message)
        raise ManualStepRequired(reason, message)
    if channel == "greenhouse":
        # SUB-006. The stored URL for a Greenhouse posting is usually the
        # EMPLOYER's own `?gh_jid=` page, which hosts NO application form at
        # all (live probe 2026-08-17: HTTP 200, 700,675 bytes, zero <form>
        # elements — the form is mounted client-side into `div#grnhse_app`).
        # Opening a browser there produces exactly one outcome,
        # `submit_control_not_found`, after a full page render. Resolve to the
        # canonical `embed/job_app` form FIRST — through a gate that fetches
        # the candidate and requires a real form before trusting it — and
        # refuse honestly when no candidate verifies, rather than navigating a
        # page we already know cannot accept an application.
        from app.services.apply_channel_resolver import resolve_greenhouse_apply_url

        resolution = resolve_greenhouse_apply_url(apply_url)
        if resolution["reason"]:
            reason = str(resolution["reason"])
            message = str(resolution["detail"])
            record_manual_step(user_id, application_id, reason, message)
            raise ManualStepRequired(reason, message)
        resolved_url = str(resolution.get("resolvedUrl") or "")
        if resolved_url and resolved_url != apply_url:
            # DISCLOSED, not silent: the row records both URLs before anything
            # is driven, so "we applied here, not where the posting pointed" is
            # auditable from the application itself.
            record_apply_url_resolution(
                user_id,
                application_id,
                original_url=apply_url,
                resolved_url=resolved_url,
            )
            apply_url = resolved_url
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
        # U5d-3: the employer and the job this attempt is for, so a
        # company-scoped banked answer applies only where the user scoped it
        # and every usage audit row names the job it was used on.
        company=str(application.get("company") or "") or None,
        job_id=str(application.get("jobId") or "") or None,
    )


def no_channel_reason(
    channel: str, application: dict[str, Any], apply_url: str = ""
) -> tuple[str, str]:
    """``(reason_code, user-facing message)`` for a channel we do not drive.

    Three DISTINCT honest states, never blurred into one: Seek is refused by
    ruling; an ASSISTED platform is fully prepared and waiting for the user's
    click; an unresolved posting is one whose destination we genuinely could
    not determine. Telling a user "we could not determine where this goes"
    about a Lever posting we resolved perfectly well would be a false claim.
    """
    from app.services.apply_channel_resolver import ASSISTED_CHANNELS, platform_label

    destination = apply_url or str(application.get("sourceUrl") or "")
    if channel == "seek-manual":
        return (
            "seek_manual_only",
            (
                "This role is posted on Seek, which prohibits automated access "
                "(ADR-SEEK-V3). Aether will not scrape or submit there — open "
                f"the posting and apply yourself: {destination}"
            ).strip(),
        )
    if channel in ASSISTED_CHANNELS:
        # ORCHESTRATOR RULING U5-F3: no dedicated parser exists for this
        # platform, so Aether will not click submit on the user's behalf here.
        # Everything else IS done — say exactly that, and hand over the link.
        return (
            "assisted_manual_submit",
            (
                "Your tailored résumé and cover letter are ready to submit — "
                f"{platform_label(channel)} needs your click. Aether does not "
                "auto-submit on this platform, so open the posting and send "
                f"them there: {destination}"
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


#: U5d-2 — the Submission Agent reaches the SAME copy through the SAME
#: function. Kept as an alias rather than a second definition so the sweep and
#: the agent can never tell a user two different stories about one posting;
#: the private name stays valid for this module's existing call sites and tests.
_no_channel_reason = no_channel_reason


def approval_age_days(approved_at: Any, now: datetime | None = None) -> float | None:
    """Age of an approval decision in days, or ``None`` if it has no stamp.

    Pure, so the guard's arithmetic is testable without a database, and
    tz-defensive: a naive stamp out of Postgres is read as UTC rather than
    crashing a sweep pass on a timezone comparison.
    """
    if not isinstance(approved_at, datetime):
        return None
    stamped = (
        approved_at.replace(tzinfo=timezone.utc)
        if approved_at.tzinfo is None
        else approved_at
    )
    now = now or datetime.now(timezone.utc)
    return (now - stamped).total_seconds() / 86400.0


def _expire_stale_approval(
    user_id: str, application_id: str, approved_at: Any
) -> bool:
    """``True`` (and the row is marked) if this approval is too old to execute.

    An approval with NO decision stamp at all is left alone rather than
    expired: we do not know when the user confirmed it, and inventing an age
    would be the same class of fabrication as inventing a form answer. Such a
    row keeps going through the normal path, where every other guard still
    applies.
    """
    from app.services.apply_executor import record_manual_step

    max_age = approval_max_age_days()
    age = approval_age_days(approved_at)
    if age is None or age <= max_age:
        return False
    # Rounded, not truncated: the stamp comes from the DATABASE clock and the
    # age is computed against this PROCESS's clock, so a genuinely 9-day-old
    # approval measures 8.99997 days whenever the two differ by a second — and
    # telling the user "8 days ago" about a 9-day-old approval is a small lie
    # this guard has no reason to tell.
    whole_days = max(1, round(age))
    record_manual_step(
        user_id,
        application_id,
        "approval_expired",
        (
            f"You approved this application {whole_days} day"
            f"{'' if whole_days == 1 else 's'} ago. Aether does not submit an "
            f"approval older than {max_age:g} days without a fresh "
            "confirmation — nothing was sent. Reconfirm to submit it, or leave "
            "it if you have moved on."
        ),
    )
    logger.info(
        "apply sweep: application %s has a %.1f-day-old approval (max %.1f) — "
        "nothing was submitted; it now asks the user to reconfirm",
        application_id, age, max_age,
    )
    return True


def _render_resume_pdf(user_id: str, application: dict[str, Any]) -> bytes:
    """This application's OWN tailored résumé, through the real download path.

    ``resolve_email_attachments`` is the same in-process call the W-SUB email
    path uses, which renders through the same authority as the user's own
    Download button — so the employer receives byte-identically what the user
    can see: their PRESERVED document, never the Aether branded template
    (RFMT-5) and never diff-marked (RFMT-2).

    The bytes are not necessarily a PDF — a preserved render is whatever the
    user uploaded — so the executor names the uploaded file from the bytes
    themselves (``apply_executor._resume_suffix``) rather than assuming one.
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

    D2 (audit wf_9a87f76f-eaa) — THE MATCH THRESHOLD IS REAL HERE. Within a
    pass, an application whose job's ``fitScore`` is below the user's
    ``agentConfig.matchThreshold`` (default 80, AUD-UX-1) is NOT auto-transmitted. The
    skip is honest and NON-terminal: it is counted as
    ``skippedBelowThreshold`` in the summary and logged, the approval is NOT
    burned, and NO manual step is stamped — the row simply stays queued. A
    NULL ``fitScore`` (including an application whose Job row is gone) is
    below EVERY threshold: an unscored job is never auto-fired. The user may
    still execute such an application explicitly from the UI — the explicit
    approve-and-execute path deliberately BYPASSES the threshold, because a
    personal decision on a specific application outranks the account-wide
    bar. KNOWN BOUND, stated rather than hidden: below-threshold rows keep
    their place in the oldest-first batch, so a backlog whose oldest rows all
    sit under the bar re-reads (and re-skips) them each pass rather than
    reaching past them.

    The per-user ``autoApply`` toggle is enforced one level up
    (:func:`sweep_user_if_opted_in` for the job path,
    :func:`users_with_pending_transmissions` for the cron path); this function
    is the raw "drive this user's queue" primitive.
    """
    from app.services.application_submission import (
        meets_match_threshold,
        user_match_threshold,
    )
    from app.services.apply_executor import ApplyExecutorGuardError, ManualStepRequired

    batch = sweep_batch_size()
    rows = pending_transmissions(user_id, limit=batch)
    user = _load_user(user_id) or {}
    threshold = user_match_threshold(user.get("agentConfig"))
    summary: dict[str, Any] = {
        "processed": 0,
        "transmitted": 0,
        "manual_step": 0,
        "stale_approval": 0,
        "skippedBelowThreshold": 0,
        "skipped": 0,
        "failed": 0,
        "remaining": 0,
        "batch": batch,
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
        if _expire_stale_approval(user_id, application_id, row.get("approvedAt")):
            # The user's confirmation is too old to act on. The row is NOT
            # transmitted and NOT silently left prepared: it now carries an
            # honest, actionable state with a one-click way back.
            summary["stale_approval"] += 1
            continue
        fit_score = row.get("fitScore")
        if not meets_match_threshold(fit_score, threshold):
            # D2: below the user's bar (or unscored) — nothing is fired,
            # nothing is burned, nothing is stamped. The row stays queued and
            # the user can still submit it explicitly from the board.
            summary["skippedBelowThreshold"] += 1
            logger.info(
                "apply sweep: application %s skipped — fitScore %s is below "
                "the user's match threshold %s; the approval is untouched and "
                "the user can still submit it explicitly",
                application_id,
                "unscored" if fit_score is None else fit_score,
                threshold,
            )
            continue
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
    summary["remaining"] = count_pending_transmissions(user_id)
    logger.info(
        "apply sweep for user %s: processed %d of a %d-application batch "
        "(transmitted %d, manual step %d, expired approval %d, below "
        "match-threshold %d, skipped %d, failed %d) — %d application(s) "
        "still queued for the next pass",
        user_id, summary["processed"], batch, summary["transmitted"],
        summary["manual_step"], summary["stale_approval"],
        summary["skippedBelowThreshold"], summary["skipped"],
        summary["failed"], summary["remaining"],
    )
    return summary


def sweep_user_if_opted_in(
    user_id: str, *, deadline: float | None = None
) -> dict[str, Any]:
    """One user's sweep pass, behind their OWN ``autoApply`` toggle.

    D1 (audit wf_9a87f76f-eaa): the cron path already enqueues only opted-in
    users (:func:`users_with_pending_transmissions` filters in SQL), but a
    sweep job can also be enqueued directly — so the toggle is re-checked
    here, at execution time, against the user's CURRENT Settings. A user whose
    ``agentConfig.autoApply`` is not true (missing config, missing key, or
    ``false``) is not swept, and the skip is reported honestly
    (``{"skipped": "autoApply_off"}``) rather than as an empty pass.

    A ``user_id`` with NO ``User`` row at all is NOT treated as opted-out: it
    owns nothing the sweep could ever send (the selection query joins
    ``Application`` on ``userId``), so the pass runs and honestly reports an
    empty board. The guard exists to protect real accounts that have not
    opted in, not to change the no-op result for an id that does not exist.

    Synchronous on purpose — it runs inside the worker thread
    :func:`apply_sweep_user` dispatches, so its own DB reads also stay off
    the event loop.
    """
    from app.services.application_submission import auto_apply_enabled

    user = _load_user(user_id)
    if user is not None and not auto_apply_enabled(user.get("agentConfig")):
        logger.info(
            "apply sweep: user %s has autoApply off — not swept; their "
            "approved applications stay queued for their own explicit "
            "submission",
            user_id,
        )
        return {"skipped": "autoApply_off", "userId": user_id}
    return sweep_pending_transmissions(user_id, deadline=deadline)


async def apply_sweep_user(ctx: Any, user_id: str) -> dict[str, Any]:
    """ARQ job: one bounded sweep pass for one user, RUN OFF THE EVENT LOOP.

    ``sweep_pending_transmissions`` drives a REAL browser via Playwright's
    **sync** API (``apply_executor.fetch_apply_page`` / ``execute_site_application``).
    The sync API refuses to run inside a live asyncio loop — it raises a bare
    ``playwright...Error`` ("Sync API inside the asyncio loop"), which the
    executor wraps as ``ApplyExecutorTransportError`` ("Could not open the
    application page (Error)"). Called directly on the arq worker's loop, that
    meant EVERY browser submission failed (prod: 1 of 687 transmitted). Running
    it in a worker thread — exactly as ``board_sweep_user`` already does with
    ``asyncio.to_thread(sweep_user_stretch, ...)`` — gives the sync browser code
    a thread with no running loop, so it works.

    Two switches gate the pass, in order: the operator env kill-switch
    (``AETHER_APPLY_SWEEP_ENABLED``), then the user's own ``autoApply`` toggle
    (:func:`sweep_user_if_opted_in`, D1 audit wf_9a87f76f-eaa).
    """
    if not sweep_enabled():
        return {"skipped": "disabled", "userId": user_id}
    deadline = time.monotonic() + sweep_stretch_seconds()
    return await asyncio.to_thread(
        sweep_user_if_opted_in, user_id, deadline=deadline
    )


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
