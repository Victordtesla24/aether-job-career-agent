"""Reference Agent — reference-request drafting, approval-gated (wave-4C).

HONEST SCOPE (ADR-AG-1). The card's old tip promised it "manages reference
requests & reminders". There is no reminder scheduler in this product, so the
"& reminders" half was unachievable and the copy is corrected in this same change.
What ships is the half that is real: it drafts the reference REQUEST to one of the
caller's own ``Contact`` rows and queues it behind the human approval gate.

* grounded ONLY in the caller's OWN résumé plus the contact's real recorded
  fields — no invented shared history, no invented referral;
* it SENDS NOTHING: the terminal act is a pending ``email_send``
  ApprovalRequest (the emailAgent pattern), and the one place an outbound email
  really leaves the system stays ``POST /approvals/{id}/execute``, which fails
  with an honest 409 while Gmail is not connected;
* a contact with no email address is blocked honestly;
* prior reference requests for that contact are REPORTED (read off the approval
  requests this agent itself raised) so a repeat run is a visible re-draft rather
  than a silent second ask. A still-pending request is REFRESHED with the newest
  draft instead of stacking a duplicate pending send.

WHY NO NEW SCHEMA. The brief allowed an additive stage/purpose value "if needed".
It is not needed, and the obvious shape would have been unsafe: ``Contact.stage``
is the Postgres ``ContactStage`` enum, so widening it means ``ALTER TYPE ... ADD
VALUE`` — outside the additive-only DDL this project permits (ADR-TR-1 covers
``ADD COLUMN``/``CREATE TABLE``/``CREATE INDEX`` IF NOT EXISTS). A new column
would also be a column nothing renders. The state that matters — "has a reference
request been raised for this contact, and where did it get to?" — is already
carried by the ``ApprovalRequest`` rows this agent creates, which the approvals
queue already shows the user. So the agent reads real state instead of inventing a
place to keep it, and it never writes a stage transition it did not observe.

Metering: REASONING tier, metered like every LLM agent; every honest refusal
reaches no model, reports ``llm_called=False``, and is refunded by the router's
backstop so a blocked run costs no paid run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.outreach_support import (
    UNTRUSTED_CONTACT,
    UNTRUSTED_RULE,
    contact_block,
    fence,
    guarded_draft,
    list_contacts,
    load_contact,
    queue_email_approval,
    sanitized_corpus,
)
from app.db import get_connection, rows_to_dicts
from app.repositories.approval import ApprovalRepository
from app.repositories.gmail_account import GmailAccountRepository
from app.services.resume_grounding import resolve_user_resume_text

#: The approval ``kind`` this agent raises. Also the marker it reads back to
#: report prior requests, so the two can never disagree.
REFERENCE_KIND = "reference_request"

#: Contacts listed back when there is nothing to draft.
_MAX_CANDIDATES = 10

SYSTEM_PROMPT = (
    "You write a short, courteous email in which a job-seeking candidate ASKS a "
    "professional contact to act as a reference. Use ONLY facts present in the "
    "candidate's résumé and the contact's recorded details. Never invent a shared "
    "employer, a shared project, a prior conversation, a job title, a date, or a "
    "specific role the candidate is applying for. Make it easy to decline, and say "
    "the role details and timing will follow before the contact is named. Keep it "
    f"under 130 words. {UNTRUSTED_RULE} Respond with JSON: "
    '{"subject": "<subject line>", "body": "<email body>"}'
)


@dataclass
class ReferenceCandidate:
    contactId: str
    name: str
    company: str | None = None
    hasEmail: bool = False


@dataclass
class PriorRequest:
    approvalId: str
    status: str
    createdAt: str | None = None


@dataclass
class ReferenceResult:
    contactId: str | None = None
    contactName: str | None = None
    contactCompany: str | None = None
    requestedContactId: str | None = None
    #: ``explicit`` (caller supplied an id) or ``mostRecentWithEmail``. Never a
    #: silent pick.
    contactSelection: str | None = None
    subject: str = ""
    draft: str = ""
    draftWithheld: bool = False
    flagged: list[str] = field(default_factory=list)
    contactMissingEmail: bool = False
    missingResume: bool = False
    noContacts: bool = False
    candidates: list[ReferenceCandidate] = field(default_factory=list)
    #: Reference requests this agent has already raised for this contact — real
    #: rows, reported so a repeat run is visible rather than a silent second ask.
    priorRequests: list[PriorRequest] = field(default_factory=list)
    approvalId: str | None = None
    approvalStatus: str | None = None
    gmailConnected: bool = False
    llm_called: bool = False
    message: str = ""


class ReferenceAgent:
    def __init__(
        self,
        llm: Any | None = None,
        guard: Any | None = None,
        approvals: ApprovalRepository | None = None,
        credentials: GmailAccountRepository | None = None,
    ) -> None:
        self._llm = llm
        self._guard = guard
        self._approvals = approvals or ApprovalRepository()
        self._credentials = credentials or GmailAccountRepository()

    # ------------------------------------------------------------------ run
    def run(self, user_id: str, contact_id: str | None = None) -> ReferenceResult:
        requested = (contact_id or "").strip() or None
        result = ReferenceResult(requestedContactId=requested)
        result.gmailConnected = self._credentials.is_connected(user_id)

        contacts = list_contacts(user_id)
        result.candidates = [
            ReferenceCandidate(
                contactId=str(c["id"]),
                name=str(c.get("name") or ""),
                company=c.get("company"),
                hasEmail=bool((c.get("email") or "").strip()),
            )
            for c in contacts[:_MAX_CANDIDATES]
        ]

        if requested is not None:
            contact = load_contact(user_id, requested)
            selection = "explicit"
        else:
            with_email = [c for c in contacts if (c.get("email") or "").strip()]
            if not with_email:
                result.noContacts = True
                result.message = (
                    "No contact of yours has an email address on file, so there is "
                    "no one to ask. Add a contact with an email in Networking and "
                    "run this again."
                    if contacts
                    else "No contacts yet — add one in Networking, then ask them here."
                )
                return result
            contact = with_email[0]
            selection = "mostRecentWithEmail"

        result.contactId = str(contact["id"])
        result.contactName = contact.get("name")
        result.contactCompany = contact.get("company")
        result.contactSelection = selection
        result.priorRequests = self._prior_requests(user_id, str(contact["id"]))

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
                "Add your résumé before drafting a reference request — the ask is "
                "only written from your own recorded experience."
            )
            return result

        self._draft(user_id, contact, email, resume_text, result)
        return result

    # ------------------------------------------------------- prior requests
    @staticmethod
    def _prior_requests(user_id: str, contact_id: str) -> list[PriorRequest]:
        """Reference requests already raised for this contact — real
        ``ApprovalRequest`` rows, scoped to the caller and to this agent's own
        ``kind`` so another family's approval can never be reported as one."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id", "status", "createdAt" FROM "ApprovalRequest"'
                    ' WHERE "userId" = %s AND "type" = \'email_send\'::"ApprovalType"'
                    ' AND "payload"->>\'kind\' = %s'
                    ' AND "payload"->>\'contact_id\' = %s'
                    ' ORDER BY "createdAt" DESC LIMIT 20',
                    (user_id, REFERENCE_KIND, contact_id),
                )
                rows = rows_to_dicts(cur)
        return [
            PriorRequest(
                approvalId=str(r["id"]),
                status=str(r["status"]),
                createdAt=(
                    r["createdAt"].isoformat()
                    if hasattr(r.get("createdAt"), "isoformat")
                    else None
                ),
            )
            for r in rows
        ]

    # ---------------------------------------------------------------- draft
    def _draft(
        self,
        user_id: str,
        contact: dict[str, Any],
        email: str,
        resume_text: str,
        result: ReferenceResult,
    ) -> None:
        raw_contact = contact_block(contact)
        corpus = "\n".join([resume_text, sanitized_corpus(raw_contact)])
        result.llm_called = True
        draft = guarded_draft(
            self._llm,
            prompt_name="reference_request",
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
                "The reference request was withheld — the fabrication guard flagged "
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
            kind=REFERENCE_KIND,
            dedupe_key=f"{REFERENCE_KIND}:{contact['id']}",
            contact_id=str(contact["id"]),
        )
        result.approvalId = approval["id"]
        result.approvalStatus = approval["status"]
        # ``priorRequests`` is the state BEFORE this run. When the id we just got
        # back is one of them, the still-pending request was REFRESHED with this
        # newer draft rather than duplicated — say so, rather than implying a
        # second ask is now queued.
        parts = [
            f"Reference request to {contact.get('name')} "
            + (
                "re-drafted; the request already awaiting your approval now carries "
                "this newer draft"
                if any(p.approvalId == approval["id"] for p in result.priorRequests)
                else "drafted and queued for your approval"
            )
            + " — nothing has been sent yet."
        ]
        if not result.gmailConnected:
            parts.append(
                "Connect Gmail (Email Center) before approving — sending needs a "
                "connected account."
            )
        if result.priorRequests:
            parts.append(
                f"{len(result.priorRequests)} earlier request(s) for this contact "
                "are listed in priorRequests."
            )
        result.message = " ".join(parts)
