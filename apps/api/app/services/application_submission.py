"""W-SUB — REAL application submission: derive a recipient, then transmit.

WHAT WAS WRONG (verified live against the production ``aether`` schema on
2026-08-02, before this module existed):

* ``ApprovalRequest.executedAt`` was NULL on ALL 133 rows — no approval had
  ever produced a side-effect;
* ``POST /approvals/{id}/execute`` returned ``{"status": "executed"}`` for
  every ``application_submit`` approval WITHOUT doing anything;
* ``Job`` had no employer/recruiter/apply address column, so there was
  nowhere to send an application even in principle;
* no resume was ever attached to anything;
* 86 ``Application`` rows read ``submitted`` to the user regardless.

WHAT THIS MODULE DOES, AND WHAT IT REFUSES TO DO.

The recipient is DERIVED FROM REAL POSTING DATA ONLY — an address the
employer published in the posting body itself. There is deliberately no
"guess the careers address from the company name" fallback: synthesising
``careers@<company>.com`` would be fabricated data aimed at a real third
party, and a bounced or misdirected job application is a real harm to the
user. A job with no derivable address is NOT auto-submittable and says so;
that is currently EVERY job in production (a live probe on 2026-08-02 found 0
of 66 stored descriptions containing an address), and reporting that honestly
is the correct behaviour, not a gap to paper over.

Transmission itself reuses the shipped machinery rather than reinventing it
(§13.1): ``app.services.email_attachments.resolve_email_attachments`` renders
the tailored résumé and the cover letter through the SAME in-process download
handlers the user's own download buttons call (so the employer receives
byte-identical PDFs, and the BLOCKER-002 placeholder-sign-off guard inside
``export_cover_letter_pdf`` still refuses a contaminated letter), and
``app.services.gmail_service.GmailService.send`` is the single outbound seam.

THE APPROVAL GATE IS NOT OPTIONAL. Nothing here sends without either
(a) an ``ApprovalRequest`` the user personally moved to ``approved``, whose
single-shot ``executedAt`` claim makes a double-send impossible, or (b) the
user's own explicit autonomous opt-in (``agentConfig.autoApply`` true AND
``agentConfig.approvalGate`` false), which is still recorded as an approval
row with ``payload.autonomous = true`` so the audit trail names the mode that
authorised it. Both defaults are the safe ones (``autoApply`` false,
``approvalGate`` true).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.db import (
    ensure_application_transmission_columns,
    ensure_job_apply_contact_columns,
    get_connection,
    rows_to_dicts,
)

logger = logging.getLogger(__name__)

#: Channel recorded on a transmitted application. One value today (the only
#: outbound transport this product has); the column exists so a second one can
#: be added without the UI having to infer it.
CHANNEL_GMAIL = "gmail"

#: Public submission states. ``not_transmitted`` is the honest state of every
#: application Aether did not actually send — including all 86 pre-existing
#: 'submitted' rows.
STATE_TRANSMITTED = "transmitted"
STATE_NOT_TRANSMITTED = "not_transmitted"

#: RFC-ish address matcher, deliberately conservative: it must not swallow
#: trailing punctuation/markup from a scraped HTML description.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

#: ``mailto:`` link in the posting body — the strongest signal available,
#: because the employer explicitly published it AS the way to apply.
_MAILTO_RE = re.compile(r"mailto:\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", re.I)

#: Local-parts that are provably NOT an application destination. Sending a
#: real application to any of these guarantees it is never read — an honest
#: "no recipient" beats a delivered-to-nobody send.
_NON_RECIPIENT_LOCALPARTS = frozenset(
    {
        "noreply",
        "no-reply",
        "no_reply",
        "donotreply",
        "do-not-reply",
        "unsubscribe",
        "bounce",
        "bounces",
        "mailer-daemon",
        "postmaster",
        "abuse",
        "privacy",
        "legal",
        "webmaster",
        "info",
        "sales",
        "marketing",
        "press",
        "media",
        "billing",
        "accounts",
        "security",
    }
)

#: Domains belonging to aggregators / the product itself rather than to an
#: employer. An address here is never the employer's application inbox.
_NON_RECIPIENT_DOMAIN_SUFFIXES = (
    "example.com",
    "example.org",
    "aether.dev",
    "sentry.io",
    "google.com",
    "gstatic.com",
    "schema.org",
    "w3.org",
)

#: Local-part SUBSTRINGS that mark an address as a legally-mandated support
#: channel, not an application inbox. LIVE EVIDENCE (2026-08-02, the first
#: dry-run of ``scripts/backfill_job_apply_email.py`` over the 66 production
#: job rows): the ONLY four addresses published in any stored description were
#: ``hiringaccommodation@mozilla.com``, ``accommodations@netlify.com`` and
#: ``applicantaccommodations@onepeloton.com`` (twice) — every one of them a
#: DISABILITY-ACCOMMODATION request line sitting inside the employer's EEO
#: boilerplate ("Please contact us at … to request accommodation"). Emailing a
#: job application to an accessibility support desk would misdirect the
#: application AND misuse a channel reserved for disabled applicants. They are
#: hard-excluded.
_NON_RECIPIENT_LOCALPART_SUBSTRINGS = (
    "accommodation",
    "accessib",
    "disabilit",
    "eeo",
    "equalopportunity",
    "privacy",
    "dataprotection",
    "gdpr",
    "compliance",
    "whistle",
    "fraud",
)

#: Words that, when they appear immediately around an address in the posting
#: text, make it an APPLICATION destination rather than an incidental contact
#: (a privacy officer, a support desk, an author byline). Used only for the
#: weaker ``description_text`` source; ``mailto:`` needs no corroboration.
_APPLY_CONTEXT_RE = re.compile(
    r"(apply|application|applications|resume|résumé|cv|cover letter|"
    r"send your|email your|expressions? of interest|eoi|recruit|hiring|"
    r"careers?|talent)",
    re.I,
)

#: Context that DISQUALIFIES a nearby address regardless of how it was found
#: — including a ``mailto:``. These paragraphs are boilerplate obligations
#: (accommodation, EEO, privacy, anti-scam notices) whose contact address is
#: emphatically not where an application goes. This check runs FIRST and
#: overrides ``_APPLY_CONTEXT_RE``, because the accommodation boilerplate
#: itself contains the words "job application" and "applicant" and would
#: otherwise read as apply-intent (which is exactly how the four production
#: accommodation addresses were first misclassified).
_DISQUALIFYING_CONTEXT_RE = re.compile(
    r"(accommodation|reasonable adjustment|accessib|disabilit|"
    r"equal opportunit|equal employment|affirmative action|eeo\b|"
    r"privacy (policy|notice)|data protection|gdpr|"
    r"recruitment (fraud|scam)|report (a )?(fraud|scam))",
    re.I,
)

#: How much text either side of a bare address is inspected for the
#: apply-context words above.
_CONTEXT_WINDOW = 180


def _is_plausible_recipient(email: str) -> bool:
    """False for addresses that provably cannot be an application inbox."""
    email = email.strip().strip(".,;:<>()[]\"'").lower()
    if "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if local in _NON_RECIPIENT_LOCALPARTS:
        return False
    normalized_local = local.replace(".", "").replace("-", "").replace("_", "")
    if any(token in normalized_local for token in _NON_RECIPIENT_LOCALPART_SUBSTRINGS):
        return False
    if any(domain == d or domain.endswith("." + d) for d in _NON_RECIPIENT_DOMAIN_SUFFIXES):
        return False
    return True


def _context_window(text: str, start: int, end: int) -> str:
    return text[max(0, start - _CONTEXT_WINDOW) : end + _CONTEXT_WINDOW]


def derive_apply_recipient(description: str | None) -> dict[str, str] | None:
    """Derive an application recipient from a posting's OWN text, or ``None``.

    Two accepted sources, strongest first:

    ``description_mailto``
        a ``mailto:`` link the employer put in the posting — an unambiguous
        published instruction to email the application.
    ``description_text``
        a bare address in the posting body that sits within
        :data:`_CONTEXT_WINDOW` characters of apply-intent wording ("send your
        CV to …", "applications to …"). The corroboration requirement is what
        stops an incidental privacy/support address being treated as the
        application inbox.

    Anything else returns ``None`` — including a description containing only
    a ``no-reply@``/``privacy@`` style address. There is NO fallback that
    invents an address from the company name.
    """
    text = description or ""
    if not text.strip():
        return None
    for match in _MAILTO_RE.finditer(text):
        candidate = match.group(1).strip().strip(".,;:<>()[]\"'")
        if not _is_plausible_recipient(candidate):
            continue
        if _DISQUALIFYING_CONTEXT_RE.search(
            _context_window(text, match.start(), match.end())
        ):
            continue
        return {"email": candidate.lower(), "source": "description_mailto"}
    for match in _EMAIL_RE.finditer(text):
        candidate = match.group(0).strip().strip(".,;:<>()[]\"'")
        if not _is_plausible_recipient(candidate):
            continue
        window = _context_window(text, match.start(), match.end())
        if _DISQUALIFYING_CONTEXT_RE.search(window):
            continue
        if _APPLY_CONTEXT_RE.search(window):
            return {"email": candidate.lower(), "source": "description_text"}
    return None


def resolve_job_apply_recipient(
    user_id: str, job_id: str, *, refresh: bool = False
) -> dict[str, str] | None:
    """Return ``{"email", "source"}`` for a job, deriving + caching on first use.

    Owner-scoped. The derived answer (including the negative one) is persisted
    on the ``Job`` row so the UI can distinguish "never checked" from "checked,
    nothing published" — and so a later transmission uses the same address the
    approval card showed the user.
    """
    ensure_job_apply_contact_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "description", "applyEmail", "applyEmailSource", '
                '"applyContactCheckedAt" FROM "Job" '
                'WHERE "id" = %s AND "userId" = %s',
                (job_id, user_id),
            )
            rows = rows_to_dicts(cur)
            if not rows:
                return None
            job = rows[0]
            if job["applyContactCheckedAt"] is not None and not refresh:
                if job["applyEmail"]:
                    return {
                        "email": job["applyEmail"],
                        "source": job["applyEmailSource"] or "stored",
                    }
                return None
            derived = derive_apply_recipient(job.get("description"))
            cur.execute(
                'UPDATE "Job" SET "applyEmail" = %s, "applyEmailSource" = %s, '
                '"applyContactCheckedAt" = NOW() WHERE "id" = %s AND "userId" = %s',
                (
                    derived["email"] if derived else None,
                    derived["source"] if derived else None,
                    job_id,
                    user_id,
                ),
            )
        conn.commit()
    return derived


def is_autonomous_submission_enabled(user_id: str) -> bool:
    """True only when the user EXPLICITLY opted out of the approval gate.

    Reads the same ``User.agentConfig`` blob the Settings screen writes
    (``app.routers.workspaces``). Both defaults are safe: a user who has never
    touched the setting has ``autoApply`` false and ``approvalGate`` true, so
    this returns False and nothing can be sent without a human decision.
    """
    from app.db import ensure_user_profile_columns

    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "agentConfig" FROM "User" WHERE "id" = %s', (user_id,))
            row = cur.fetchone()
    config = (row[0] if row else None) or {}
    if not isinstance(config, dict):
        return False
    return bool(config.get("autoApply")) and not bool(config.get("approvalGate", True))


def _load_user(user_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id", "email", "name" FROM "User" WHERE "id" = %s', (user_id,)
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def _load_application(user_id: str, application_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT a."id", a."jobId", a."resumeId", a."status", a."coverLetter", '
                'j."title" AS "jobTitle", j."company" '
                'FROM "Application" a JOIN "Job" j ON j."id" = a."jobId" '
                'WHERE a."id" = %s AND a."userId" = %s',
                (application_id, user_id),
            )
            rows = rows_to_dicts(cur)
    return rows[0] if rows else None


def build_submission_message(
    user: dict[str, Any], application: dict[str, Any]
) -> tuple[str, str]:
    """``(subject, body)`` for the outgoing application email.

    The body is the user's OWN cover letter text — this function writes no
    prose on the user's behalf and adds no claim about the applicant. The only
    appended line is the factual note that the résumé and letter are attached.
    """
    applicant = str(user.get("name") or "").strip() or str(user.get("email") or "")
    title = str(application.get("jobTitle") or "the role").strip()
    company = str(application.get("company") or "").strip()
    subject = f"Application: {title}"
    if company:
        subject = f"{subject} — {company}"
    if applicant:
        subject = f"{subject} ({applicant})"
    letter = str(application.get("coverLetter") or "").strip()
    parts = [letter] if letter else []
    parts.append("Attached: résumé and cover letter (PDF).")
    return subject, "\n\n".join(parts)


def is_site_apply_payload(payload: dict[str, Any]) -> bool:
    """Whether an approval payload is a U5d-2 SITE-APPLY card.

    ONE definition, imported by every consumer (the execute router's dispatch
    and the repository's tracker-promotion guard), because the two must agree
    exactly: a card the router will drive through a browser is precisely the
    card whose approval must NOT pre-stamp the tracker as submitted.

    Both conditions are required — ``kind == "submission"`` with no
    ``recipient``, AND a ``channel`` Aether actually drives — so neither a
    legacy card (no ``channel`` key at all; that is all 556 production rows)
    nor a card naming a channel we refuse to drive can ever match.
    """
    from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

    if payload.get("kind") != "submission" or payload.get("recipient"):
        return False
    return str(payload.get("channel") or "") in AUTOMATABLE_CHANNELS


def queue_submission_approval(
    user_id: str,
    job_id: str,
    application_id: str,
    resume_id: str | None = None,
    *,
    channel: str | None = None,
    apply_url: str | None = None,
) -> dict[str, Any] | None:
    """Queue an approval to SUBMIT this application, or ``None`` if impossible.

    ``None`` (no card, no promise) whenever there is no destination Aether can
    honestly act on. The returned row is ``pending``: it transmits nothing on
    its own. Executing it is a separate, explicitly-approved step
    (``POST /approvals/{id}/execute``).

    U5d-2 — CHANNEL AWARENESS. Until this slice the only approval this function
    could raise was an EMAIL one, and ``applyEmail`` is set on 0 of 9 954
    production jobs (``FORENSICS.md`` §4.2), so the gate could never fire and
    the U5 browser engine had no way to be reached from anywhere but the OFF
    sweep worker. ``channel`` (resolved by
    ``apply_channel_resolver.resolve_apply_channel``, never guessed here) now
    selects the payload shape:

    * ``None`` / ``"email"`` — the EXISTING W-SUB email path, byte-for-byte
      unchanged, including its refusal when no address was published. Every
      pre-U5d-2 caller passes no ``channel`` and is therefore unaffected.
    * a member of ``AUTOMATABLE_CHANNELS`` (``ashby``/``greenhouse`` — the only
      two with a dedicated, tested form parser, ORCHESTRATOR RULING U5-F3) — a
      SITE payload carrying the channel and the real apply URL, which
      ``POST /approvals/{id}/execute`` routes into the U5 apply engine.
    * anything else — ``None``. A channel Aether will not drive must never get
      an approval card, because a card implies a submission the product would
      then refuse to make.

    The two payload shapes are distinguished by ``recipient``: present means
    email, absent means site. That is the discriminator the execute router
    reads, so a site card can never be mistaken for an email one.
    """
    from app.services.apply_channel_resolver import AUTOMATABLE_CHANNELS

    resolved_channel = (channel or "email").strip() or "email"
    if resolved_channel != "email" and resolved_channel not in AUTOMATABLE_CHANNELS:
        return None
    recipient = (
        resolve_job_apply_recipient(user_id, job_id)
        if resolved_channel == "email"
        else None
    )
    if resolved_channel == "email" and recipient is None:
        return None
    application = _load_application(user_id, application_id)
    if application is None:
        return None
    from app.repositories.approval import ApprovalRepository

    autonomous = is_autonomous_submission_enabled(user_id)
    payload: dict[str, Any] = {
        "kind": "submission",
        "job_id": job_id,
        "application_id": application_id,
        "attach_resume_id": resume_id or application.get("resumeId"),
        "attach_cover_letter_id": application_id,
        "job_title": application.get("jobTitle"),
        "company": application.get("company"),
        "autonomous": autonomous,
        "preview": (application.get("coverLetter") or "")[:4000],
    }
    if recipient is not None:
        payload["recipient"] = recipient["email"]
        payload["recipient_source"] = recipient["source"]
        payload["channel"] = "email"
    else:
        payload["channel"] = resolved_channel
        payload["apply_url"] = apply_url
    return ApprovalRepository().create(
        user_id, "application_submit", payload, application_id=application_id
    )


def maybe_autonomous_transmit(
    user_id: str, approval: dict[str, Any]
) -> dict[str, Any] | None:
    """Send immediately IFF the user explicitly turned the approval gate off.

    Returns ``None`` when the user has NOT opted in — the approval simply
    stays pending and nothing is sent, which is the default for every account.

    When they HAVE opted in (``autoApply`` true AND ``approvalGate`` false in
    their own Settings), the authorisation is still WRITTEN DOWN before the
    send: the approval is resolved to ``approved`` with
    ``payload.autonomous = true``, and the single-shot ``executedAt`` claim is
    taken exactly as the human path takes it. So "no approval recorded" and
    "sent twice" both remain impossible, and the audit trail names which mode
    authorised the message.

    Never raises: a refusal or a provider failure is returned as an honest
    ``{"queued": ...}``-shaped error dict, because an outbound-mail problem
    must not fail the user's Apply click and must not be reported as a send.
    """
    if not is_autonomous_submission_enabled(user_id):
        return None
    from app.repositories.approval import ApprovalRepository

    repo = ApprovalRepository()
    # ``approve`` is the same compare-and-set the human Approvals screen uses
    # (scoped to userId AND status='pending'), so a card the user resolved
    # themselves in the meantime is never re-resolved here.
    resolved = repo.approve(approval["id"], user_id)
    if resolved is None:
        return {
            "transmitted": False,
            "reason": "approval_unavailable",
            "message": "Autonomous send could not record its approval — nothing was sent.",
        }
    if not repo.claim_execution(approval["id"], user_id):
        return {
            "transmitted": False,
            "reason": "already_executed",
            "message": "This application was already sent — nothing was sent again.",
        }
    user = _load_user(user_id)
    if user is None:
        repo.release_execution(approval["id"], user_id)
        return {
            "transmitted": False,
            "reason": "user_not_found",
            "message": "Nothing was sent.",
        }
    try:
        sent = transmit_application(user, resolved)
    except (SubmissionRefused, SubmissionTransportError) as exc:
        repo.release_execution(approval["id"], user_id)
        return {"transmitted": False, "reason": exc.reason, "message": exc.message}
    # CRITICAL-4: the send provably returned. Until this stamp lands the row
    # only records that a claim was MADE, which cannot be distinguished from a
    # process that died mid-send — see repositories.approval.execution_state.
    repo.complete_execution(approval["id"], user_id)
    return sent


class SubmissionRefused(Exception):
    """No transmission is possible; ``reason`` is a machine code, ``message``
    is the sentence shown to the user. Raised INSTEAD of sending — never
    swallowed into a fake success."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class SubmissionTransportError(Exception):
    """The recipient and documents were fine but the provider failed. Nothing
    was sent; the caller releases the execution claim so the user can retry."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


def transmit_application(
    current_user: dict[str, Any], approval: dict[str, Any]
) -> dict[str, Any]:
    """Actually send the application email behind an APPROVED approval.

    Preconditions the caller must already have enforced: the approval is the
    caller's own, is ``approved`` (or carries the user's explicit autonomous
    opt-in) and has won the single-shot ``executedAt`` claim.

    Raises :class:`SubmissionRefused` (nothing sendable — no recipient, no
    application, no Gmail) or :class:`SubmissionTransportError` (provider
    failure). Both mean NOTHING was transmitted.
    """
    user_id = current_user["id"]
    payload = approval.get("payload") or {}
    if not payload.get("autonomous") and approval.get("status") != "approved":
        raise SubmissionRefused(
            "not_approved",
            "This application has not been approved for sending — nothing was sent.",
        )
    application_id = payload.get("application_id") or approval.get("applicationId")
    job_id = payload.get("job_id")
    if not application_id or not job_id:
        raise SubmissionRefused(
            "incomplete_request",
            "This approval does not identify an application to send — nothing was sent.",
        )
    application = _load_application(user_id, str(application_id))
    if application is None:
        raise SubmissionRefused(
            "application_not_found",
            "The application behind this approval no longer exists — nothing was sent.",
        )
    # Re-derive from the JOB row at send time: the address the employer
    # published is the source of truth, not a stale copy in the payload.
    recipient = resolve_job_apply_recipient(user_id, str(job_id))
    if recipient is None:
        raise SubmissionRefused(
            "no_recipient",
            (
                "This posting publishes no application email address, so Aether "
                "cannot submit it for you. Nothing was sent — apply on the "
                "employer's site and mark the application as submitted."
            ),
        )
    user = _load_user(user_id) or dict(current_user)
    from app.repositories.gmail_account import GmailAccountRepository

    if not GmailAccountRepository().is_connected(user_id):
        raise SubmissionRefused(
            "no_email_provider_connected",
            (
                "No Gmail account connected — connect Gmail to send applications. "
                "No email has been sent."
            ),
        )
    # Attachments are rendered by the REAL download handlers (byte-identical to
    # what the user downloads). A dangling reference or a contaminated cover
    # letter raises HERE, before anything leaves the system.
    from app.services.email_attachments import resolve_email_attachments

    resume_id = payload.get("attach_resume_id") or application.get("resumeId")
    attachments = resolve_email_attachments(
        current_user,
        resume_id=str(resume_id) if resume_id else None,
        cover_letter_id=str(application_id),
    )
    if not attachments:
        raise SubmissionRefused(
            "no_documents",
            "No résumé or cover letter could be attached — nothing was sent.",
        )
    subject, body = build_submission_message(user, application)
    from app.services.gmail_service import (
        GmailAuthError,
        GmailError,
        GmailNotConnectedError,
        GmailService,
    )

    try:
        sent = GmailService(user_id).send(
            to=recipient["email"],
            subject=subject,
            body=body,
            attachments=attachments,
        )
    except (GmailAuthError, GmailNotConnectedError):
        raise SubmissionTransportError(
            "gmail_auth_failed",
            "Gmail authorization expired — reconnect Gmail. No email has been sent.",
        ) from None
    except GmailError:
        raise SubmissionTransportError(
            "gmail_send_failed",
            (
                "Gmail could not send this application right now — no email was "
                "sent. Please try again."
            ),
        ) from None
    record_transmission(
        user_id,
        str(application_id),
        recipient=recipient["email"],
        channel=CHANNEL_GMAIL,
        ref=str(sent.get("id") or ""),
    )
    return {
        "status": STATE_TRANSMITTED,
        "approval_id": approval["id"],
        "type": approval["type"],
        "applicationId": str(application_id),
        "to": recipient["email"],
        "recipientSource": recipient["source"],
        "attachments": [name for name, _data, _mime in attachments],
        "gmailMessageId": sent.get("id"),
    }


def record_transmission(
    user_id: str,
    application_id: str,
    *,
    recipient: str,
    channel: str,
    ref: str,
) -> None:
    """Stamp the transmission facts and advance the stage — in ONE statement.

    The stage advance is deliberately conditional on the row still being a
    ``draft``: a transmitted application must READ as submitted, but an
    application the user has already moved further (screening/interview/offer)
    is never regressed. The transmission columns are written unconditionally,
    because they record something that demonstrably happened.

    U-AX: the statement additionally returns the row's PRE-update status via a
    locked self-join, so the status event recorded below states the transition
    that was OBSERVED rather than the one assumed from the CASE expression. The
    join keeps it a single atomic statement — a separate SELECT-then-UPDATE
    could read 'draft', lose a race, and then record a transition that another
    writer had already made.
    """
    from app.db import ensure_application_submission_truth_columns
    from app.services.submission_truth import STATE_RECORDED_NOT_TRANSMITTED

    ensure_application_transmission_columns()
    ensure_application_submission_truth_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                '''
                UPDATE "Application" AS a
                SET "transmittedAt" = NOW(),
                    "transmittedTo" = %s,
                    "transmissionChannel" = %s,
                    "transmissionRef" = %s,
                    -- U5d-2: the write-time "recorded, no evidence" marker
                    -- stops being true at this exact statement. Cleared only
                    -- for that value; the retrospective pre-fix backfill state
                    -- is left intact.
                    "submissionTruthState" = CASE
                        WHEN a."submissionTruthState" = %s THEN NULL
                        ELSE a."submissionTruthState" END,
                    "submissionTruthAt" = CASE
                        WHEN a."submissionTruthState" = %s THEN NULL
                        ELSE a."submissionTruthAt" END,
                    "status" = CASE
                        WHEN a."status" = 'draft'::"ApplicationStatus"
                            THEN 'submitted'::"ApplicationStatus"
                        ELSE a."status" END,
                    "updatedAt" = NOW()
                FROM (
                    SELECT "id", "status"::text AS "prevStatus"
                    FROM "Application"
                    WHERE "id" = %s AND "userId" = %s
                    FOR UPDATE
                ) AS prev
                WHERE a."id" = prev."id" AND a."userId" = %s
                RETURNING a."jobId", a."resumeId", prev."prevStatus"
                ''',
                (
                    recipient, channel, ref,
                    STATE_RECORDED_NOT_TRANSMITTED, STATE_RECORDED_NOT_TRANSMITTED,
                    application_id, user_id, user_id,
                ),
            )
            stamped = cur.fetchone()
        conn.commit()
    if stamped is not None and stamped[2] == "draft":
        # A REAL transmission promoted this draft. The guard on the observed
        # previous status means an application the user had already advanced
        # records no phantom draft->submitted transition.
        from app.repositories.application_status_event import (
            record_status_event_best_effort,
        )
        from app.services.submission_snapshot import record_submission_snapshot

        record_status_event_best_effort(
            application_id, "draft", "submitted", f"transmission.{channel}"
        )
        if stamped[0]:
            record_submission_snapshot(
                user_id,
                application_id,
                str(stamped[0]),
                str(stamped[1]) if stamped[1] else None,
            )


def submission_view(row: dict[str, Any]) -> dict[str, Any]:
    """Truthful submission fields for an ``Application`` API row.

    The stored ``status`` is NEVER rewritten — history stays exactly as it was
    recorded. What changes is that the response now also carries whether
    Aether actually transmitted anything, so the UI can stop implying a send
    that never happened:

    * ``transmitted`` — did a message actually leave the system?
    * ``submissionState`` — ``transmitted`` / ``not_transmitted``.
    * ``transmittedTo`` / ``transmittedAt`` / ``transmissionRef`` — checkable
      evidence for a positive claim (the message id is findable in the user's
      own Gmail Sent folder).
    * ``autoSubmittable`` — whether the posting publishes an address Aether
      could send to at all.
    * ``applyChannel`` / ``manualStepReason`` / ``manualStepDetail`` /
      ``manualStepAt`` — U5's other half of the NO-PREPARED-ONLY invariant
      (written by ``apply_channel_resolver`` / ``apply_executor.record_
      manual_step``). Named here EXPLICITLY, not left to ride through on
      ``row`` untouched by this function's own return dict: a caller that
      ever rebuilds its response from ``submission_view()``'s return value
      alone (instead of ``dict.update``-ing it onto the raw SELECT row, as
      ``applications._with_submission`` does today) must not silently drop
      them the way the pre-refix ``_COLUMNS`` gap did for the whole read
      path (see ``applications.py`` ``_ensure_read_columns`` docstring).
    * ``submissionTruthState`` / ``submissionTruthNote`` — U5d. The honest
      reclassification of a row that CLAIMED a submission before the fix and
      has no transmission evidence to show for it (346 such rows in
      production). ``submissionTruthNote`` is the single user-facing sentence,
      resolved from the state here so no surface invents its own wording.
    """
    from app.services.submission_truth import submission_note_for

    transmitted_at = row.get("transmittedAt")
    transmitted = transmitted_at is not None
    truth_state = row.get("submissionTruthState")
    return {
        "submissionTruthState": truth_state,
        "submissionTruthNote": submission_note_for(truth_state),
        "submissionTruthAt": row.get("submissionTruthAt"),
        "transmitted": transmitted,
        "submissionState": STATE_TRANSMITTED if transmitted else STATE_NOT_TRANSMITTED,
        "transmittedAt": transmitted_at,
        "transmittedTo": row.get("transmittedTo"),
        "transmissionChannel": row.get("transmissionChannel"),
        "transmissionRef": row.get("transmissionRef"),
        "autoSubmittable": bool(row.get("applyEmail")),
        "applyChannel": row.get("applyChannel"),
        "manualStepReason": row.get("manualStepReason"),
        "manualStepDetail": row.get("manualStepDetail"),
        "manualStepAt": row.get("manualStepAt"),
        "applyEmail": row.get("applyEmail"),
        "applyEmailSource": row.get("applyEmailSource"),
    }
