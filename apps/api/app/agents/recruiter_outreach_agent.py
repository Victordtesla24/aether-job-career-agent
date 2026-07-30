"""Recruiter Outreach Agent — first-touch outbound, approval-gated (wave-4C).

HONEST SCOPE (ADR-AG-1). The card's old tip said "Planned: first-touch outbound to
a recruiter/contact with no existing thread (a future dedicated OutreachAgent)".
This is that agent, at exactly that scope and no wider:

* it drafts the FIRST message to one of the caller's own ``Contact`` rows that has
  NO ``EmailThread`` yet — the first-touch condition is DETECTED, not assumed, so
  a contact whose conversation has already started is refused with a pointer to
  the Email Agent's reply/follow-up drafting rather than opening a duplicate;
* the draft is grounded ONLY in the caller's OWN résumé plus the contact's real
  recorded fields. There is no enrichment, no scraping, no company research;
* it SENDS NOTHING. Its terminal act is a pending ``email_send``
  ApprovalRequest (the emailAgent pattern). The single point where an outbound
  email really leaves the system remains ``POST /approvals/{id}/execute``, which
  already fails with an honest 409 when Gmail is not connected;
* a contact with NO email address is blocked honestly — Aether does not guess or
  construct an address.

Guards (reused, never weakened — see ``outreach_support``): contact fields are
sanitized + fenced before entering the prompt and join the guard's corpus only in
that sanitized form; the draft is checked by the EXISTING ``FabricationGuard``
against the caller's résumé + those sanitized fields, plus both cover-letter
injection backstops. A flagged draft is WITHHELD and NO approval is created — an
email that will be sent under the user's own name is never patched up silently.

Metering: registered on the REASONING tier, so a run that reaches the model
reserves plan quota atomically BEFORE the call and refunds on honest failure like
every other metered agent. Every honest refusal above reaches no model, reports
``llm_called=False`` and is refunded by the router's backstop, so a blocked run
never costs the user a paid run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.outreach_support import (
    UNTRUSTED_CONTACT,
    UNTRUSTED_RULE,
    contact_block,
    contact_thread_ids,
    fence,
    first_touch_contacts,
    guarded_draft,
    load_contact,
    queue_email_approval,
    sanitized_corpus,
)
from app.repositories.approval import ApprovalRepository
from app.repositories.gmail_account import GmailAccountRepository
from app.services.resume_grounding import resolve_user_resume_text

#: Contacts listed back to the caller when there is nothing to draft.
_MAX_CANDIDATES = 10

SYSTEM_PROMPT = (
    "You write the FIRST outbound email from a job-seeking candidate to a "
    "professional contact they have never emailed. Use ONLY facts present in the "
    "candidate's résumé and the contact's recorded details. Never invent a shared "
    "history, a referral, a mutual connection, a prior conversation, an "
    "application, a salary expectation, or a skill or employer the résumé does "
    "not name. Do not claim to have researched the company. Keep it under 150 "
    "words, specific and plainly written, and close by asking for a short "
    f"conversation. {UNTRUSTED_RULE} Respond with JSON: "
    '{"subject": "<subject line>", "body": "<email body>"}'
)


@dataclass
class OutreachCandidate:
    contactId: str
    name: str
    company: str | None = None
    hasEmail: bool = False


@dataclass
class RecruiterOutreachResult:
    contactId: str | None = None
    contactName: str | None = None
    contactCompany: str | None = None
    requestedContactId: str | None = None
    #: How the contact was chosen: ``explicit`` (caller supplied an id) or
    #: ``firstTouch`` (the newest contact with no thread). Never a silent pick.
    contactSelection: str | None = None
    subject: str = ""
    draft: str = ""
    draftWithheld: bool = False
    flagged: list[str] = field(default_factory=list)
    #: Honest refusal flags — exactly one is True on a refused run.
    existingThread: bool = False
    existingThreadIds: list[str] = field(default_factory=list)
    contactMissingEmail: bool = False
    missingResume: bool = False
    noContacts: bool = False
    candidates: list[OutreachCandidate] = field(default_factory=list)
    approvalId: str | None = None
    approvalStatus: str | None = None
    #: Gmail connection state, reported honestly. A draft is still queued when
    #: Gmail is not connected (the approval is the deliverable); the SEND then
    #: fails with an honest 409 at ``/approvals/{id}/execute`` until it is.
    gmailConnected: bool = False
    #: Consumed by the router: False => zero-cost, no-model stamp + refund.
    llm_called: bool = False
    message: str = ""


class RecruiterOutreachAgent:
    def __init__(
        self,
        llm: Any | None = None,
        guard: Any | None = None,
        approvals: ApprovalRepository | None = None,
        credentials: GmailAccountRepository | None = None,
    ) -> None:
        self._llm = llm  # constructed lazily only when a draft is really made
        self._guard = guard
        self._approvals = approvals or ApprovalRepository()
        self._credentials = credentials or GmailAccountRepository()

    # ------------------------------------------------------------------ run
    def run(
        self, user_id: str, contact_id: str | None = None
    ) -> RecruiterOutreachResult:
        requested = (contact_id or "").strip() or None
        result = RecruiterOutreachResult(requestedContactId=requested)
        result.gmailConnected = self._credentials.is_connected(user_id)

        eligible = first_touch_contacts(user_id)
        result.candidates = [
            OutreachCandidate(
                contactId=str(c["id"]),
                name=str(c.get("name") or ""),
                company=c.get("company"),
                hasEmail=bool((c.get("email") or "").strip()),
            )
            for c in eligible[:_MAX_CANDIDATES]
        ]

        contact = self._resolve(user_id, requested, eligible, result)
        if contact is None:
            return result

        email = (contact.get("email") or "").strip()
        if not email:
            result.contactMissingEmail = True
            result.message = (
                f"{contact.get('name')} has no email address on file, so there is "
                "nothing to send to. Add one on the contact and run this again — "
                "Aether never guesses an address."
            )
            return result

        resume_text = resolve_user_resume_text(user_id, allow_operator_fallback=False)
        if not resume_text.strip():
            result.missingResume = True
            result.message = (
                "Add your résumé before drafting outbound email — an introduction "
                "is only written from your own recorded experience."
            )
            return result

        self._draft(user_id, contact, email, resume_text, result)
        return result

    # -------------------------------------------------------------- resolve
    def _resolve(
        self,
        user_id: str,
        requested: str | None,
        eligible: list[dict[str, Any]],
        result: RecruiterOutreachResult,
    ) -> dict[str, Any] | None:
        """The contact to draft for, or ``None`` after recording an honest refusal.

        An EXPLICIT id that is not the caller's own raises ``LookupError`` ->
        honest 404 (``load_contact``), never a substituted contact.
        """
        if requested is not None:
            contact = load_contact(user_id, requested)
            is_first_touch = any(
                str(c["id"]) == str(contact["id"]) for c in eligible
            )
            if not is_first_touch:
                self._stamp(result, contact, "explicit")
                result.existingThread = True
                result.existingThreadIds = contact_thread_ids(
                    user_id, str(contact["id"])
                )
                result.message = (
                    f"{contact.get('name')} already has "
                    f"{len(result.existingThreadIds)} email thread(s), so this is "
                    "not a first touch. Use the Email Agent to draft a reply or a "
                    "follow-up on the existing thread."
                )
                return None
            self._stamp(result, contact, "explicit")
            return contact

        if not eligible:
            result.noContacts = True
            result.message = (
                "No contact of yours is awaiting a first touch — every contact "
                "either has no record yet or already has an email thread. Add a "
                "contact in Networking, or use the Email Agent on an existing "
                "thread."
            )
            return None
        contact = eligible[0]
        self._stamp(result, contact, "firstTouch")
        return contact

    @staticmethod
    def _stamp(
        result: RecruiterOutreachResult, contact: dict[str, Any], selection: str
    ) -> None:
        result.contactId = str(contact["id"])
        result.contactName = contact.get("name")
        result.contactCompany = contact.get("company")
        result.contactSelection = selection

    # ---------------------------------------------------------------- draft
    def _draft(
        self,
        user_id: str,
        contact: dict[str, Any],
        email: str,
        resume_text: str,
        result: RecruiterOutreachResult,
    ) -> None:
        raw_contact = contact_block(contact)
        # The prompt gets the FENCED SANITIZED contact block; the corpus gets a
        # single sanitize pass over the SAME raw input, so both sides are
        # byte-identical sanitizations of identical text (4a9cd6c's rule).
        corpus = "\n".join([resume_text, sanitized_corpus(raw_contact)])
        result.llm_called = True
        draft = guarded_draft(
            self._llm,
            prompt_name="recruiter_outreach",
            system=SYSTEM_PROMPT,
            user_prompt=(
                f"CONTACT:\n{fence(UNTRUSTED_CONTACT, raw_contact)}\n\n"
                f"CANDIDATE RÉSUMÉ:\n{resume_text}"
            ),
            corpus=corpus,
            untrusted_raw=raw_contact,
            candidate_evidence=resume_text,
            guard=self._guard,
        )
        if draft.withheld:
            result.draftWithheld = True
            result.flagged = draft.flagged
            result.message = (
                "The introduction was withheld — the fabrication guard flagged "
                f"{draft.flagged}, which your résumé and this contact's recorded "
                "details do not support. Nothing was queued for sending."
            )
            return

        result.subject = draft.subject
        result.draft = draft.body
        approval = queue_email_approval(
            self._approvals,
            user_id,
            to=email,
            subject=draft.subject,
            body=draft.body,
            kind="recruiter_outreach",
            dedupe_key=f"recruiter_outreach:{contact['id']}",
            contact_id=str(contact["id"]),
        )
        result.approvalId = approval["id"]
        result.approvalStatus = approval["status"]
        result.message = (
            f"First-touch introduction to {contact.get('name')} drafted and queued "
            "for your approval — nothing has been sent yet."
            if result.gmailConnected
            else (
                f"First-touch introduction to {contact.get('name')} drafted and "
                "queued for your approval. Connect Gmail (Email Center) before "
                "approving — sending needs a connected account."
            )
        )
