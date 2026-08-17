"""Email Agent — first-class in-app agent backed by real Gmail (P4).

Modes (``run(user_id, mode=...)``):

- ``triage``    — sync career/job-search/interview threads from every connected
                  mailbox (personal mail is hidden, never LLM-labelled), ingest
                  evidenced interview invites into ``Application.status``, then
                  classify remaining threads into the inbox categories the UI
                  filters on (priority / followup / auto / all). For a bounded
                  set of priority/follow-up recruiter threads it also persists
                  a fabrication-guarded draft reply for human review. It never
                  sends.
- ``draft_reply`` — draft a reply grounded ONLY in the candidate's resume + the
                  incoming thread, checked by :class:`FabricationGuard` so it
                  never invents facts about the candidate.
- ``draft_follow_up`` — draft a silence-triggered outbound nudge on an existing
                  thread (subsumes the retired standalone Follow-up agent). Same
                  evidence grounding + FabricationGuard as ``draft_reply``.
- ``job_alerts`` — scan EVERY connected mailbox for the candidate's own
                  automated job-alert emails (SEEK, LinkedIn, Indeed, Workforce
                  Australia, recruitment agencies — including Trash via
                  ``in:anywhere``, because Gmail's default scope hides most
                  alerts), extract the individual
                  postings out of them and persist each one as a real ``Job``
                  row through ``JobRepository.create``. Fully deterministic —
                  no LLM call at all (``llm_called=False``). See
                  :mod:`app.services.job_alert_parser` for the anti-fabrication
                  rules; this mode never writes a posting whose title, company
                  and apply URL were not all genuinely read out of the email.
- ``insights``  — produce the AI-intelligence view-model (score + breakdown +
                  summary) the Email Center's intelligence panel renders.
- ``apply_labels`` — apply/remove Gmail labels on a thread's latest message.
- ``send``      — NEVER sends directly: it creates a *pending* ``email_send``
                  ApprovalRequest. The human approves, then the approvals
                  ``/execute`` route performs the real Gmail send.

Everything degrades honestly when Gmail is not connected: nothing is fabricated,
and the result carries ``connected``/``degraded`` flags plus a plain message.
Gmail client construction is lazy so importing this module never requires the
google libraries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.db import get_connection, rows_to_dicts
from app.repositories.approval import ApprovalRepository
from app.repositories.gmail_account import (
    GmailAccountRepository,
    mask_account_email,
)
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, LLMFixtureMissingError, get_model
from app.services.resume_grounding import resolve_user_resume_text

logger = logging.getLogger(__name__)

#: Inbox categories the Email Center filters on (see apps/web email/page.tsx).
_CATEGORIES = ("priority", "followup", "auto", "all")

#: Cron/triage may auto-DRAFT (never send) this many priority/follow-up
#: recruiter threads per run. Bounds LLM cost on the 10-minute timer.
_AUTO_DRAFT_LIMIT = 3

_TRIAGE_SYSTEM = (
    "You triage a job-seeker's CAREER inbox — recruiter mail, interview invites, "
    "application receipts, and job alerts only. Personal mail has already been "
    "removed. For each numbered email, assign exactly one category from "
    "[priority, followup, auto, all], an integer score 0-100 for how much the "
    "candidate should care, and a one-line reason. "
    "priority = a recruiter/hiring manager or interview invite needing a timely "
    "response; followup = the candidate owes a follow-up; auto = automated "
    "job-alert/no-reply; all = other professional/career mail. Never invent "
    "facts. Respond with JSON: {\"items\": [{\"index\": 0, \"category\": "
    "\"priority\", \"score\": 80, \"reason\": \"...\"}]}"
)

_REPLY_SYSTEM = (
    "You write a truthful, concise email reply for the candidate. Use ONLY facts "
    "present in the candidate's resume and the incoming email. Never invent "
    "skills, employers, titles, metrics, or availability. Keep it professional "
    "and specific. No subject line, body only. Respond with JSON: "
    '{"body": "<reply>"}'
)

_INSIGHTS_SYSTEM = (
    "You analyze one recruiter email for the candidate. Score recruiter "
    "engagement, role fit signals, and urgency. Respond with JSON: "
    '{"score": 0-100, "breakdown": [{"label": "Recruiter Engagement", "value": '
    '0-100}, {"label": "Role Fit Signals", "value": 0-100}, {"label": '
    '"Urgency", "value": 0-100}], "summary": "<one or two sentences>"}'
)


@dataclass
class EmailAgentResult:
    mode: str
    connected: bool
    degraded: bool = False
    #: Whether this run actually invoked the LLM. Defaults True (the metered
    #: modes — triage-classify / draft / insights — all reach the model), and is
    #: set False by a genuine zero-LLM-call path so the router prices it at zero
    #: rather than off request payload size (ML-email-001): an early-return triage
    #: with nothing to classify, and the two modes that never construct an LLM
    #: call at all (``send`` queues an approval, ``apply_labels`` mutates Gmail
    #: labels — ML-W4C). The router reads + strips this flag.
    llm_called: bool = True
    message: str = ""
    synced: int = 0
    triaged: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    draft: str = ""
    thread_id: Optional[str] = None
    insights: Optional[dict[str, Any]] = None
    labels_applied: list[str] = field(default_factory=list)
    approval_id: Optional[str] = None
    approval_status: Optional[str] = None
    flagged: list[str] = field(default_factory=list)
    #: Recruiter threads that received a persisted review-only draft this run.
    #: Never a send count — outbound mail stays behind the approval gate.
    drafted: int = 0


@dataclass
class JobAlertIntakeResult:
    """Outcome of one ``job_alerts`` run — every number is a real count.

    A separate dataclass (not extra fields on :class:`EmailAgentResult`) so the
    six existing modes' output shape is untouched. ``_to_output`` in the agents
    router serialises any dataclass, so this appears in AgentRun history exactly
    like every other agent's output.
    """

    mode: str = "job_alerts"
    connected: bool = False
    degraded: bool = False
    #: ALWAYS False — the parser is regex + HTML, never a model call. The router
    #: reads and strips this flag to price the run at zero.
    llm_called: bool = False
    message: str = ""
    #: Mailboxes actually scanned.
    accounts_scanned: int = 0
    #: Messages whose From/Subject were examined.
    messages_scanned: int = 0
    #: Messages recognised as genuine job alerts.
    alert_emails: int = 0
    #: Individual postings read out of those alerts.
    postings_extracted: int = 0
    #: Postings deliberately DROPPED because a required field (title, company or
    #: a real apply URL) was not present — never back-filled.
    postings_skipped: int = 0
    #: New ``Job`` rows written.
    jobs_created: int = 0
    #: Already-known listings re-confirmed (``lastSeenAt`` refreshed).
    jobs_updated: int = 0
    #: ``{platform: alert_email_count}``.
    platforms: dict[str, int] = field(default_factory=dict)
    #: Per-mailbox breakdown, including honest per-account errors.
    per_account: list[dict[str, Any]] = field(default_factory=list)
    #: Plain-English notes (why an alert produced nothing, per platform).
    notes: list[str] = field(default_factory=list)


class EmailAgentError(ValueError):
    """A mode-specific precondition failed (e.g. missing thread_id or unknown
    mode). Subclasses ``ValueError`` so the /agents/email/run endpoint maps it
    to a 422 (its existing ``except ValueError`` branch)."""


class EmailAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        guard: FabricationGuard | None = None,
        approvals: ApprovalRepository | None = None,
        credentials: GmailAccountRepository | None = None,
        gmail: Any = None,
        jobs: Any = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._guard = guard or FabricationGuard()
        self._approvals = approvals or ApprovalRepository()
        self._credentials = credentials or GmailAccountRepository()
        #: Optional injected GmailService (tests pass a fake); resolved lazily
        #: in production so importing this module needs no google libs.
        self._gmail = gmail
        #: Job store used by ``job_alerts``. Injectable for tests; resolved
        #: lazily so the six pre-existing modes never construct it.
        self._jobs = jobs

    # ------------------------------------------------------------------ util
    def _gmail_for(self, user_id: str, account_id: str | None = None) -> Any:
        if self._gmail is not None:
            # An injected client may be per-account (a factory) or a single
            # object; support both so a test can fake either shape.
            if account_id is not None and callable(getattr(self._gmail, "for_account", None)):
                return self._gmail.for_account(account_id)
            return self._gmail
        from app.services.gmail_service import GmailService

        return GmailService(user_id, account_id=account_id)

    def _job_repository(self) -> Any:
        if self._jobs is None:
            from app.repositories.job import JobRepository

            self._jobs = JobRepository()
        return self._jobs

    def _is_connected(self, user_id: str) -> bool:
        return self._credentials.is_connected(user_id)

    def _threads(self, user_id: str) -> list[dict[str, Any]]:
        from app.services.gmail_service import (
            ensure_email_thread_agent_columns,
            ensure_email_thread_last_message_column,
        )

        ensure_email_thread_last_message_column()
        ensure_email_thread_agent_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, subject, messages, classification,'
                    ' "gmailThreadId", "lastMessageAt", "createdAt",'
                    ' "draftReply" FROM "EmailThread"'
                    ' WHERE "userId" = %s'
                    " AND COALESCE(classification, '') <> 'personal'"
                    ' ORDER BY COALESCE("lastMessageAt", "createdAt") DESC LIMIT 200',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def _thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, subject, messages, "gmailThreadId", "gmailMessageId"'
                    ' FROM "EmailThread" WHERE id = %s AND "userId" = %s',
                    (thread_id, user_id),
                )
                rows = rows_to_dicts(cur)
        if not rows:
            # LookupError → the endpoint's `except LookupError` maps this to 404.
            raise LookupError(f"Email thread {thread_id} not found for user")
        return rows[0]

    @staticmethod
    def _latest_body(thread: dict[str, Any]) -> str:
        msgs = thread.get("messages") or []
        if isinstance(msgs, list) and msgs:
            return str(msgs[-1].get("body") or "")
        return ""

    #: Roles that mark a message as the candidate's OWN outbound text
    #: (gmail_service._normalize_thread marks real inbound Gmail mail
    #: "received"; routers/emails.py reply_to_thread/create_draft mark the
    #: candidate's own text "reply"/"draft").
    _OWN_MESSAGE_ROLES = frozenset({"reply", "draft"})

    @classmethod
    def _latest_counterparty_body(cls, thread: dict[str, Any]) -> str:
        """The newest message that is NOT the candidate's own outbound text.

        GM2-EMAIL-002: a reply/follow-up draft must be grounded on the
        COUNTERPARTY's last message, never on the candidate's own prior
        reply — even when that own reply is the newest message on the
        thread. Walks back from the newest message and skips any whose
        ``role`` marks it as the candidate's own ("reply"/"draft"). A
        message with no ``role`` at all predates that field and is treated
        as inbound, matching historical single-message-thread behaviour.
        Returns "" when every message on the thread is the candidate's own.
        """
        msgs = thread.get("messages") or []
        if not isinstance(msgs, list):
            return ""
        for msg in reversed(msgs):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") in cls._OWN_MESSAGE_ROLES:
                continue
            return str(msg.get("body") or "")
        return ""

    @staticmethod
    def _coerce_score(value: Any) -> Optional[int]:
        """Parse a triage score into an int clamped to 0-100, or ``None`` when the
        LLM did not return a genuine number for this thread (missing index, null,
        or non-numeric). NEVER coalesces a missing score to 0 — an un-scored
        thread has NO score, so its ``aiScore`` stays NULL rather than a
        fabricated 0 that would read as a real 'irrelevant' verdict."""
        if isinstance(value, bool):  # bool is an int subclass — reject explicitly
            return None
        if isinstance(value, (int, float)):
            return max(0, min(100, int(value)))
        if isinstance(value, str):
            s = value.strip()
            if s.lstrip("-").isdigit():
                return max(0, min(100, int(s)))
        return None

    def _resume_text(self, user_id: str) -> str:
        """The CALLER's own base resume text for an OUTBOUND draft — never the
        bundled operator resume (NF-final-B-001). Empty when the user has no
        resume so the draft path refuses rather than leaking operator content."""
        return resolve_user_resume_text(user_id, allow_operator_fallback=False)

    # ---------------------------------------------------------------- run
    def run(
        self, user_id: str, mode: str = "triage", **params: Any
    ) -> "EmailAgentResult | JobAlertIntakeResult":
        if mode == "triage":
            return self._triage(user_id)
        if mode in ("job_alerts", "job-alerts"):
            return self._job_alerts(user_id, params)
        if mode == "draft_reply":
            return self._compose_draft(user_id, params, mode="draft_reply")
        if mode == "draft_follow_up":
            return self._compose_draft(user_id, params, mode="draft_follow_up")
        if mode == "insights":
            return self._insights(user_id, params)
        if mode == "apply_labels":
            return self._apply_labels(user_id, params)
        if mode == "send":
            return self._send(user_id, params)
        raise EmailAgentError(f"Unknown email agent mode '{mode}'")

    # --------------------------------------------------------------- triage
    def _sync_career_mailboxes(self, user_id: str) -> int:
        """Pull career/job-search threads from every connected inbox.

        Uses ``sync_threads_to_db(query=..., max_results=50)`` — the method
        test fakes already implement — never a new Gmail method name. One
        mailbox failing must not abort the others.
        """
        from app.services.career_email_filter import CAREER_GMAIL_QUERY

        accounts = self._connected_accounts(user_id)
        targets: list[str | None]
        if accounts:
            targets = [acc.get("id") for acc in accounts]
        else:
            targets = [None]

        synced = 0
        errors: list[str] = []
        for acc_id in targets:
            try:
                synced += int(
                    self._gmail_for(user_id, account_id=acc_id).sync_threads_to_db(
                        user_id, query=CAREER_GMAIL_QUERY, max_results=50
                    )
                    or 0
                )
            except Exception as exc:  # noqa: BLE001 — continue remaining inboxes
                errors.append(str(exc))
        if errors and synced == 0:
            raise RuntimeError(errors[-1])
        return synced

    def _triage(self, user_id: str) -> EmailAgentResult:
        from app.services.career_email_filter import (
            classify_thread,
            should_auto_draft_reply,
        )
        from app.services.interview_ingest import ingest_inbound_for_user

        connected = self._is_connected(user_id)
        synced = 0
        if connected:
            try:
                synced = self._sync_career_mailboxes(user_id)
            except Exception as exc:  # noqa: BLE001 — degrade, never crash triage
                connected = False
                # Zero-LLM-call no-op: sync failed before any classification.
                return EmailAgentResult(
                    mode="triage",
                    connected=False,
                    degraded=True,
                    llm_called=False,
                    message=f"Gmail sync failed — reconnect your account. ({exc})",
                )
        threads = self._threads(user_id)
        ingest_inbound_for_user(user_id, threads, force_calendar=True)
        kept: list[dict[str, Any]] = []
        hidden_ids: list[str] = []
        for t in threads:
            if classify_thread(t).keep:
                kept.append(t)
            elif t.get("id"):
                hidden_ids.append(str(t["id"]))
        if hidden_ids:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'UPDATE "EmailThread" SET classification = %s'
                        ' WHERE "userId" = %s AND id = ANY(%s)'
                        " AND COALESCE(classification, '') <> 'personal'",
                        ("personal", user_id, hidden_ids),
                    )
                conn.commit()
        threads = kept[:50]
        if not threads:
            # Zero-LLM-call no-op: nothing to classify (Gmail not connected, or
            # connected with an empty inbox), so the triage prompt is never sent —
            # this run must be priced at zero, not off payload size (ML-email-001).
            return EmailAgentResult(
                mode="triage",
                connected=connected,
                degraded=not connected,
                llm_called=False,
                synced=synced,
                message=(
                    "No emails to triage yet."
                    if connected
                    else "Connect Gmail to triage your recruiter inbox."
                ),
            )
        listing = "\n".join(
            f"{i}. Subject: {t.get('subject') or '(no subject)'} | "
            f"Body: {self._latest_body(t)[:400]}"
            for i, t in enumerate(threads)
        )
        try:
            raw = self._llm.complete_json(
                "email_triage",
                _TRIAGE_SYSTEM,
                f"Emails:\n{listing}",
                model=get_model("REASONING"),
                temperature=0.0,
            )
        except LLMFixtureMissingError as exc:
            raise EmailAgentError("triage model unavailable") from exc
        items = {int(it.get("index", -1)): it for it in raw.get("items", [])}
        # Additive aiScore column (MV-email-center-001) — created on demand so a
        # never-triaged DB still gets it; nullable, so an un-scored thread stays
        # NULL (never a fabricated 0).
        from app.services.gmail_service import ensure_email_thread_ai_columns

        ensure_email_thread_ai_columns()
        categories: dict[str, int] = {}
        triaged = 0
        auto_draft_targets: list[tuple[str, str]] = []
        with get_connection() as conn:
            with conn.cursor() as cur:
                for i, t in enumerate(threads):
                    item = items.get(i, {})
                    category = str(item.get("category", "all")).strip().lower()
                    if category not in _CATEGORIES:
                        category = "all"
                    verdict = classify_thread(t)
                    if verdict.category == "auto":
                        # Job alerts / robots stay Auto — the LLM must not
                        # promote GitHub CI or LinkedIn alerts into Priority
                        # and then auto-draft a recruiter reply.
                        category = "auto"
                    elif verdict.is_interview_invite:
                        category = "priority"
                    categories[category] = categories.get(category, 0) + 1
                    # Persist the REAL per-thread score the LLM returned. When the
                    # model gave no genuine number for this index, aiScore is left
                    # NULL — an un-scored thread has no score, never a fake 0.
                    score = self._coerce_score(item.get("score"))
                    if score is None:
                        cur.execute(
                            'UPDATE "EmailThread" SET "classification" = %s'
                            ' WHERE id = %s AND "userId" = %s',
                            (category, t["id"], user_id),
                        )
                    else:
                        cur.execute(
                            'UPDATE "EmailThread" SET "classification" = %s,'
                            ' "aiScore" = %s'
                            ' WHERE id = %s AND "userId" = %s',
                            (category, score, t["id"], user_id),
                        )
                    triaged += 1
                    latest = t.get("messages") or []
                    latest_msg = latest[-1] if isinstance(latest, list) and latest else {}
                    if not isinstance(latest_msg, dict):
                        latest_msg = {}
                    if (
                        category in ("priority", "followup")
                        and t.get("gmailThreadId")
                        and not str(t.get("draftReply") or "").strip()
                        and should_auto_draft_reply(
                            verdict,
                            sender=str(latest_msg.get("from") or ""),
                            sender_email=str(latest_msg.get("fromEmail") or ""),
                        )
                    ):
                        auto_draft_targets.append((str(t["id"]), category))
            conn.commit()
        drafted = self._auto_draft_recruiter_threads(user_id, auto_draft_targets)
        message = f"Triaged {triaged} emails into {len(categories)} categories."
        if drafted:
            message += (
                f" Auto-drafted {drafted} recruiter "
                f"{'reply' if drafted == 1 else 'replies'} for review — nothing was sent."
            )
        return EmailAgentResult(
            mode="triage",
            connected=connected,
            degraded=not connected,
            synced=synced,
            triaged=triaged,
            drafted=drafted,
            categories=categories,
            message=message,
        )

    def _auto_draft_recruiter_threads(
        self, user_id: str, targets: list[tuple[str, str]]
    ) -> int:
        """Persist review-only drafts for a bounded set of recruiter threads.

        Never calls ``send``. A missing résumé, missing counterparty message,
        or missing LLM fixture skips that thread so triage itself still
        succeeds. Local compose drafts (no ``gmailThreadId``) are not targets.
        """
        drafted = 0
        for thread_id, category in targets[:_AUTO_DRAFT_LIMIT]:
            mode = "draft_follow_up" if category == "followup" else "draft_reply"
            try:
                self._compose_draft(user_id, {"thread_id": thread_id}, mode=mode)
            except (EmailAgentError, LLMFixtureMissingError, LookupError):
                continue
            except Exception:  # noqa: BLE001 — one draft failure must not fail triage
                continue
            else:
                drafted += 1
        return drafted

    # ----------------------------------------------------------- job_alerts
    #: Bounds on the scan window and the per-mailbox message budget. Deliberate
    #: ceilings: one agent run must never turn into an unbounded Gmail crawl.
    _ALERT_DEFAULT_DAYS = 7
    _ALERT_MAX_DAYS = 30
    _ALERT_DEFAULT_MAX_MESSAGES = 200
    _ALERT_MAX_MESSAGES = 500

    @staticmethod
    def _bounded_int(value: Any, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(low, min(parsed, high))

    def _job_alerts(self, user_id: str, params: dict[str, Any]) -> JobAlertIntakeResult:
        """Turn the candidate's OWN job-alert emails into real ``Job`` rows.

        Reads every connected mailbox (not just the primary — the operator has
        two, and the alerts land in the secondary one), recognises the automated
        alert senders, extracts each individual posting, and persists it through
        the EXISTING :meth:`JobRepository.create` path so sourceUrl
        normalisation, the ``(userId, sourceUrl)`` upsert, ``dedupHash``,
        ``contentHash`` and ``lastSeenAt`` all apply exactly as they do for a
        board adapter.

        Everything degrades honestly: a mailbox whose grant has expired is
        recorded as a per-account error and the other mailbox still runs; an
        alert that yields nothing records WHY. Nothing is ever invented — the
        anti-fabrication rules live in :mod:`app.services.job_alert_parser`.
        """
        from app.services.job_alert_parser import (
            detect_alert_platform,
            parse_job_alert,
        )

        days = self._bounded_int(
            params.get("days"), self._ALERT_DEFAULT_DAYS, 1, self._ALERT_MAX_DAYS
        )
        budget = self._bounded_int(
            params.get("max_messages"),
            self._ALERT_DEFAULT_MAX_MESSAGES,
            1,
            self._ALERT_MAX_MESSAGES,
        )
        result = JobAlertIntakeResult(connected=self._is_connected(user_id))
        accounts = self._connected_accounts(user_id, params.get("account_id"))
        if not accounts:
            result.degraded = True
            result.message = (
                "Connect Gmail to read your job-alert emails — no mailbox is "
                "connected, so there is nothing to scan."
            )
            return result

        jobs = self._job_repository()
        # GAP-EMAIL-05: Gmail's default scope excludes TRASH/SPAM; ~95% of the
        # operator's job-alert mail lived in Trash. Mining uses in:anywhere.
        # The human-facing inbox sync stays Inbox-scoped (CAREER_GMAIL_QUERY
        # does not add in:anywhere) so Trash never pollutes Email Center.
        query = (
            f"in:anywhere newer_than:{days}d "
            "(from:seek.com.au OR from:linkedin.com OR from:indeed.com "
            "OR from:workforceaustralia.gov.au OR from:jobactive.gov.au "
            "OR from:michaelpage.com.au OR subject:\"new jobs\" "
            "OR subject:\"job alert\")"
        )
        for account in accounts:
            account_id = account.get("id")
            summary: dict[str, Any] = {
                "accountId": account_id,
                # MASKED: this summary is persisted durably in AgentRun.output,
                # which admin surfaces can read. The account id already
                # identifies the mailbox unambiguously for the owner.
                "email": mask_account_email(account.get("accountEmail")),
                "messagesScanned": 0,
                "alertEmails": 0,
                "postingsExtracted": 0,
                "postingsSkipped": 0,
                "jobsCreated": 0,
                "jobsUpdated": 0,
                "error": None,
            }
            result.accounts_scanned += 1
            gmail = self._gmail_for(user_id, account_id=account_id)
            try:
                headers = gmail.list_message_headers(query=query, max_results=budget)
            except Exception as exc:  # noqa: BLE001 — one dead mailbox must not kill the scan
                summary["error"] = f"{type(exc).__name__}: {exc}"
                result.per_account.append(summary)
                continue

            for header in headers:
                summary["messagesScanned"] += 1
                result.messages_scanned += 1
                platform = detect_alert_platform(
                    header.get("from", ""), header.get("subject", "")
                )
                if platform is None:
                    continue
                summary["alertEmails"] += 1
                result.alert_emails += 1
                result.platforms[platform] = result.platforms.get(platform, 0) + 1
                try:
                    body = gmail.get_message_bodies(header["id"])
                except Exception as exc:  # noqa: BLE001 — skip this message, keep going
                    result.notes.append(
                        f"{platform}: could not read message body ({exc})."
                    )
                    continue
                parsed = parse_job_alert(
                    from_header=body.get("from") or header.get("from", ""),
                    subject=body.get("subject") or header.get("subject", ""),
                    text=body.get("text") or None,
                    html=body.get("html") or None,
                )
                summary["postingsExtracted"] += len(parsed.postings)
                summary["postingsSkipped"] += parsed.skipped
                result.postings_extracted += len(parsed.postings)
                result.postings_skipped += parsed.skipped
                if parsed.reason and not parsed.postings:
                    result.notes.append(parsed.reason)
                for posting in parsed.postings:
                    try:
                        row = jobs.create(user_id, posting.to_job_raw())
                    except Exception as exc:  # noqa: BLE001 — one bad row never fails the run
                        result.notes.append(
                            f"{posting.source_url}: could not be persisted ({exc})."
                        )
                        continue
                    if isinstance(row, dict) and row.get("wasInserted") is False:
                        summary["jobsUpdated"] += 1
                        result.jobs_updated += 1
                    else:
                        summary["jobsCreated"] += 1
                        result.jobs_created += 1
            result.per_account.append(summary)

        errored = [a for a in result.per_account if a.get("error")]
        result.degraded = bool(errored)
        if result.alert_emails == 0:
            result.message = (
                f"Scanned {result.messages_scanned} message(s) across "
                f"{result.accounts_scanned} mailbox(es) from the last {days} "
                "day(s) — no job-alert emails were found."
            )
        else:
            result.message = (
                f"Read {result.alert_emails} job-alert email(s) across "
                f"{result.accounts_scanned} mailbox(es): {result.postings_extracted} "
                f"posting(s) extracted, {result.jobs_created} new job(s) added, "
                f"{result.jobs_updated} already known, {result.postings_skipped} "
                "skipped for missing data."
            )
        if errored:
            result.message += (
                f" {len(errored)} mailbox(es) could not be read — reconnect them."
            )
        return result

    def _connected_accounts(
        self, user_id: str, account_id: Any = None
    ) -> list[dict[str, Any]]:
        """Every connected mailbox for ``user_id`` (or just the named one).

        Falls back to the single-account ``get()`` shape when the injected
        credential store predates ``list_accounts`` (test fakes).
        """
        lister = getattr(self._credentials, "list_accounts", None)
        accounts: list[dict[str, Any]] = []
        if callable(lister):
            accounts = list(lister(user_id) or [])
        elif callable(getattr(self._credentials, "get", None)):
            row = self._credentials.get(user_id)
            accounts = [row] if row else []
        if account_id:
            accounts = [a for a in accounts if a.get("id") == account_id]
        return accounts

    # ------------------------------------------------ draft_reply / follow_up
    def _compose_draft(
        self, user_id: str, params: dict[str, Any], *, mode: str
    ) -> EmailAgentResult:
        """Shared draft path for ``draft_reply`` and ``draft_follow_up``.

        Both ground the draft in ONLY the candidate's resume + the thread and run
        the :class:`FabricationGuard`; they differ only in intent (respond vs.
        nudge) and the honest status message.
        """
        thread_id = params.get("thread_id")
        if not thread_id:
            raise EmailAgentError(f"{mode} requires thread_id")
        thread = self._thread(user_id, thread_id)
        # GOLD-MASTER-V2 §15: résumé grounding is an ACCOUNT-LEVEL precondition
        # (the candidate has no evidence corpus for ANY thread), so it is
        # checked BEFORE the thread-specific counterparty-message check below —
        # the same precedence CoverLetterAgent.run() already uses (résumé
        # before its own thread/content-specific PlaceholderSignerError). A
        # user with no résumé gets the one refusal that is actionable for
        # every thread they could ever draft against; a thread-specific
        # refusal for that same user would tell them nothing about the
        # blocker that actually applies universally, and would flip on/off
        # per-thread depending on message shape — never a fix they can act on.
        resume_text = self._resume_text(user_id)
        if not resume_text.strip():
            raise EmailAgentError("Add your resume before drafting a reply.")
        messages = thread.get("messages") or []
        incoming = self._latest_counterparty_body(thread)
        if isinstance(messages, list) and messages and not incoming:
            # GM2-EMAIL-002: every message on this thread is the candidate's
            # own outbound text — fail honestly rather than grounding the
            # draft on the candidate's own words presented as the "incoming"
            # email (the exact direction-reversal defect).
            raise EmailAgentError(
                f"Cannot draft a {mode.replace('_', ' ')} — this thread has "
                "no message from the other party to respond to."
            )
        # The incoming email's own text (names, company, role) is legitimate
        # evidence, so it joins the corpus the guard checks against — only
        # claims about the *candidate* that aren't in the resume get flagged.
        corpus = " ".join([resume_text, thread.get("subject") or "", incoming])
        if mode == "draft_follow_up":
            prompt = (
                "Write a brief, polite follow-up nudge for a thread the candidate "
                "has had no reply on. Reference the prior message without repeating "
                "it in full, and add NO new claims about the candidate.\n\n"
                f"Previous email:\nSubject: {thread.get('subject')}\n{incoming}\n\n"
                f"Candidate resume:\n{resume_text}"
            )
            message = "Follow-up draft ready — review and approve before sending."
        else:
            prompt = (
                f"Incoming email:\nSubject: {thread.get('subject')}\n{incoming}\n\n"
                f"Candidate resume:\n{resume_text}"
            )
            message = "Draft ready — review and approve before sending."
        draft, flagged = self._draft_once(prompt, corpus, "default")
        if flagged:
            retry_prompt = (
                f"{prompt}\n\nIMPORTANT: your previous draft used terms with no "
                f"evidence in the resume or the incoming email: {flagged}. Rewrite "
                "using ONLY words that appear in the resume or the incoming email."
            )
            try:
                draft, flagged = self._draft_once(retry_prompt, corpus, "retry")
            except LLMFixtureMissingError:
                pass  # keep the first draft; flagged is surfaced honestly below
        try:
            from app.services.gmail_service import persist_email_thread_draft

            persist_email_thread_draft(user_id, str(thread_id), draft)
        except Exception:  # noqa: BLE001 — a persist hiccup must not drop the draft
            logger.exception(
                "email_agent_draft_persist_failed user_id=%s thread_id=%s",
                user_id,
                thread_id,
            )
        return EmailAgentResult(
            mode=mode,
            connected=self._is_connected(user_id),
            thread_id=thread_id,
            draft=draft,
            flagged=flagged,
            drafted=1 if draft else 0,
            message=message,
        )

    def _draft_once(
        self, prompt: str, corpus: str, fixture_key: str
    ) -> tuple[str, list[str]]:
        raw = self._llm.complete_json(
            "email_reply",
            _REPLY_SYSTEM,
            prompt,
            model=get_model("REASONING"),
            temperature=0.0,
            fixture_key=fixture_key,
        )
        draft = str(raw.get("body") or "").strip()
        return draft, self._guard.check(draft, corpus)

    # ------------------------------------------------------------- insights
    def _insights(self, user_id: str, params: dict[str, Any]) -> EmailAgentResult:
        thread_id = params.get("thread_id")
        if not thread_id:
            raise EmailAgentError("insights requires thread_id")
        thread = self._thread(user_id, thread_id)
        body = self._latest_body(thread)
        raw = self._llm.complete_json(
            "email_insights",
            _INSIGHTS_SYSTEM,
            f"Subject: {thread.get('subject')}\n\n{body}",
            model=get_model("REASONING"),
            temperature=0.0,
        )
        # NEVER fabricate a score: when the LLM returns no genuine numeric score,
        # `score` is null (the client renders an honest "no usable score" state)
        # rather than a fake 0 that would read as a real 'irrelevant' verdict —
        # the same discipline as the triage aiScore path (MV-email-center-001).
        insights = {
            "score": self._coerce_score(raw.get("score")),
            "breakdown": raw.get("breakdown", []),
            "summary": str(raw.get("summary", "")),
        }
        try:
            from app.services.gmail_service import persist_email_thread_insights

            persist_email_thread_insights(user_id, str(thread_id), insights)
        except Exception:  # noqa: BLE001 — insights still return even if persist fails
            logger.exception(
                "email_agent_insights_persist_failed user_id=%s thread_id=%s",
                user_id,
                thread_id,
            )
        return EmailAgentResult(
            mode="insights",
            connected=self._is_connected(user_id),
            thread_id=thread_id,
            insights=insights,
            message="Intelligence computed.",
        )

    # --------------------------------------------------------- apply_labels
    def _apply_labels(self, user_id: str, params: dict[str, Any]) -> EmailAgentResult:
        if not self._is_connected(user_id):
            return EmailAgentResult(
                mode="apply_labels",
                connected=False,
                degraded=True,
                llm_called=False,
                message="Connect Gmail to manage labels.",
            )
        thread_id = params.get("thread_id")
        add_names = params.get("add") or []
        remove_ids = params.get("remove") or []
        thread = self._thread(user_id, thread_id) if thread_id else {}
        message_id = params.get("message_id") or thread.get("gmailMessageId")
        if not message_id:
            raise EmailAgentError("apply_labels requires message_id or a synced thread")
        gmail = self._gmail_for(user_id)
        add_ids = [gmail.ensure_label(name) for name in add_names]
        gmail.modify_labels(message_id, add=add_ids, remove=remove_ids)
        return EmailAgentResult(
            mode="apply_labels",
            connected=True,
            llm_called=False,  # a Gmail label mutation — no model involved
            thread_id=thread_id,
            labels_applied=list(add_names),
            message=f"Applied {len(add_names)} label(s).",
        )

    # ------------------------------------------------------------------ send
    def _send(self, user_id: str, params: dict[str, Any]) -> EmailAgentResult:
        to = params.get("to")
        subject = params.get("subject")
        body = params.get("body")
        if not (to and subject and body):
            raise EmailAgentError("send requires to, subject and body")
        payload = {
            "kind": "email",
            "to": to,
            "subject": subject,
            "body": body,
            "thread_id": params.get("thread_id"),
            "gmail_thread_id": params.get("gmail_thread_id"),
            "in_reply_to": params.get("in_reply_to"),
            # Optional resume / cover-letter PDFs to attach — resolved in-process
            # at execute time (approvals._execute_email_send). Never the bytes,
            # only the ids, so the approval card stays small.
            "attach_resume_id": params.get("attach_resume_id"),
            "attach_cover_letter_id": params.get("attach_cover_letter_id"),
        }
        approval = self._approvals.create(user_id, "email_send", payload)
        return EmailAgentResult(
            mode="send",
            connected=self._is_connected(user_id),
            llm_called=False,  # queuing an approval reaches no model

            thread_id=params.get("thread_id"),
            approval_id=approval["id"],
            approval_status=approval["status"],
            message="Send queued for your approval — nothing has been sent yet.",
        )
