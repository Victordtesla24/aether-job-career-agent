"""Email Agent — first-class in-app agent backed by real Gmail (P4).

Modes (``run(user_id, mode=...)``):

- ``triage``    — sync recent Gmail threads (when connected) and classify every
                  ``EmailThread`` into the inbox categories the UI filters on
                  (priority / followup / auto / all), persisting the label.
- ``draft_reply`` — draft a reply grounded ONLY in the candidate's resume + the
                  incoming thread, checked by :class:`FabricationGuard` so it
                  never invents facts about the candidate.
- ``draft_follow_up`` — draft a silence-triggered outbound nudge on an existing
                  thread (subsumes the retired standalone Follow-up agent). Same
                  evidence grounding + FabricationGuard as ``draft_reply``.
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

from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.fit_scorer import get_base_resume_path
from app.db import get_connection, rows_to_dicts
from app.repositories.approval import ApprovalRepository
from app.repositories.gmail_account import GmailAccountRepository
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, LLMFixtureMissingError, get_model
from app.services.resume_parser import parse_resume_pdf

#: Inbox categories the Email Center filters on (see apps/web email/page.tsx).
_CATEGORIES = ("priority", "followup", "auto", "all")

_TRIAGE_SYSTEM = (
    "You triage a job-seeker's recruiter inbox. For each numbered email, assign "
    "exactly one category from [priority, followup, auto, all], an integer score "
    "0-100 for how much the candidate should care, and a one-line reason. "
    "priority = a recruiter/hiring manager needing a timely response; followup = "
    "the candidate owes a follow-up; auto = automated/no-reply/newsletter; all = "
    'anything else. Respond with JSON: {"items": [{"index": 0, "category": '
    '"priority", "score": 80, "reason": "..."}]}'
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
    ) -> None:
        self._llm = llm or LLMClient()
        self._guard = guard or FabricationGuard()
        self._approvals = approvals or ApprovalRepository()
        self._credentials = credentials or GmailAccountRepository()
        #: Optional injected GmailService (tests pass a fake); resolved lazily
        #: in production so importing this module needs no google libs.
        self._gmail = gmail

    # ------------------------------------------------------------------ util
    def _gmail_for(self, user_id: str) -> Any:
        if self._gmail is not None:
            return self._gmail
        from app.services.gmail_service import GmailService

        return GmailService(user_id)

    def _is_connected(self, user_id: str) -> bool:
        return self._credentials.is_connected(user_id)

    def _threads(self, user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, subject, messages, classification FROM "EmailThread"'
                    ' WHERE "userId" = %s ORDER BY "createdAt" DESC LIMIT 50',
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

    def _resume_text(self) -> str:
        return parse_resume_pdf(get_base_resume_path())["raw_text"]

    # ---------------------------------------------------------------- run
    def run(self, user_id: str, mode: str = "triage", **params: Any) -> EmailAgentResult:
        if mode == "triage":
            return self._triage(user_id)
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
    def _triage(self, user_id: str) -> EmailAgentResult:
        connected = self._is_connected(user_id)
        synced = 0
        if connected:
            try:
                synced = self._gmail_for(user_id).sync_threads_to_db(user_id)
            except Exception as exc:  # noqa: BLE001 — degrade, never crash triage
                connected = False
                return EmailAgentResult(
                    mode="triage",
                    connected=False,
                    degraded=True,
                    message=f"Gmail sync failed — reconnect your account. ({exc})",
                )
        threads = self._threads(user_id)
        if not threads:
            return EmailAgentResult(
                mode="triage",
                connected=connected,
                degraded=not connected,
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
        with get_connection() as conn:
            with conn.cursor() as cur:
                for i, t in enumerate(threads):
                    item = items.get(i, {})
                    category = str(item.get("category", "all")).strip().lower()
                    if category not in _CATEGORIES:
                        category = "all"
                    categories[category] = categories.get(category, 0) + 1
                    # Persist the REAL per-thread score the LLM returned. When the
                    # model gave no genuine number for this index, aiScore is left
                    # NULL — an un-scored thread has no score, never a fake 0.
                    score = self._coerce_score(item.get("score"))
                    if score is None:
                        cur.execute(
                            'UPDATE "EmailThread" SET "classification" = %s,'
                            ' "updatedAt" = now() WHERE id = %s AND "userId" = %s',
                            (category, t["id"], user_id),
                        )
                    else:
                        cur.execute(
                            'UPDATE "EmailThread" SET "classification" = %s,'
                            ' "aiScore" = %s, "updatedAt" = now()'
                            ' WHERE id = %s AND "userId" = %s',
                            (category, score, t["id"], user_id),
                        )
                    triaged += 1
            conn.commit()
        return EmailAgentResult(
            mode="triage",
            connected=connected,
            degraded=not connected,
            synced=synced,
            triaged=triaged,
            categories=categories,
            message=f"Triaged {triaged} emails into {len(categories)} categories.",
        )

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
        incoming = self._latest_body(thread)
        resume_text = self._resume_text()
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
        return EmailAgentResult(
            mode=mode,
            connected=self._is_connected(user_id),
            thread_id=thread_id,
            draft=draft,
            flagged=flagged,
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
        insights = {
            "score": int(raw.get("score", 0) or 0),
            "breakdown": raw.get("breakdown", []),
            "summary": str(raw.get("summary", "")),
        }
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
            thread_id=params.get("thread_id"),
            approval_id=approval["id"],
            approval_status=approval["status"],
            message="Send queued for your approval — nothing has been sent yet.",
        )
