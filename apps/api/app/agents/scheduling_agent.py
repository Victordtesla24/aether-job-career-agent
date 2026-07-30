"""Scheduling Agent — time-proposal reply DRAFTS, no calendar (wave-4C).

HONEST SCOPE (ADR-AG-1, verbatim: "Draft time-proposal reply text on
interview-stage threads; no calendar read/write claimed"). The card's old tip
promised "lightweight scheduling & calendar coordination". There is no calendar
integration in this product — no Google Calendar OAuth, no free/busy read, no
event write — so "coordination" was unachievable and the copy is corrected in this
same change.

What ships:

* it drafts the REPLY TEXT on a thread attached to an application that is really at
  the ``interview`` stage — the eligibility is a real join over the caller's own
  ``Application``/``Job`` rows, not an assumption;
* the times it proposes are the ones the CALLER supplies (``proposed_times``).
  With none supplied it drafts a reply that ASKS the other side for windows, and
  says so — because Aether has no way to know when the user is free;
* it writes nothing, books nothing, and sends nothing: there is no approval to
  create because there is no outbound side-effect. Sending the drafted text stays
  the Email Agent's ``send`` mode, behind its own approval gate.

THE LOAD-BEARING RAIL: no invented availability. ``FabricationGuard`` catches a
clock time or a number the corpus does not support, but it structurally does NOT
catch a bare weekday or time-of-day word — measured: ``find_unsupported_entities(
"I can do Thursday afternoon.", corpus)`` returns ``[]``. With no calendar behind
it, "I can do Thursday afternoon" is FABRICATED availability, and the user would
discover it only after the email went out. :func:`unsupported_time_expressions`
closes exactly that gap and WITHHOLDS the draft, reusing the guard's OWN
scheduling vocabulary (``_WEEKDAYS`` / ``_TIME_OF_DAY_WORDS`` / ``_CLOCK_TIME_RE``,
imported rather than re-declared) so there is one vocabulary, not two that can
drift. Nothing in the existing guard is weakened; this is strictly an additional
check on top of it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.outreach_support import (
    UNTRUSTED_RULE,
    UNTRUSTED_THREAD,
    fence,
    guarded_draft,
    latest_body,
    load_thread,
    sanitized_corpus,
    thread_block,
)
from app.db import get_connection, rows_to_dicts
from app.services.fabrication_guard import (
    _CLOCK_TIME_RE,
    _TIME_OF_DAY_WORDS,
    _WEEKDAYS,
)
from app.services.resume_grounding import resolve_user_resume_text

#: Caller-supplied availability windows are free text, so they are bounded before
#: they reach a prompt (count and length) — a huge list is a prompt-budget problem,
#: not a feature.
_MAX_PROPOSED_TIMES = 5
_MAX_TIME_LEN = 80

#: Interview-stage threads listed back when nothing was requested.
_MAX_CANDIDATES = 10

SYSTEM_PROMPT = (
    "You draft the candidate's REPLY on an email thread about scheduling an "
    "interview. You have NO access to the candidate's calendar. Therefore: propose "
    "ONLY the availability windows supplied under AVAILABILITY, verbatim; if none "
    "are supplied, propose NO specific day, date or time at all and instead ask the "
    "sender for windows that suit them. Never state or imply that a calendar was "
    "checked, that an invite was sent, or that anything is booked. Use only facts "
    "present in the thread, the candidate's résumé and AVAILABILITY. Keep it under "
    f"120 words and stay warm and brief. {UNTRUSTED_RULE} Respond with JSON: "
    '{"subject": "<subject line>", "body": "<reply body>"}'
)


def _squash(text: str) -> str:
    """Whitespace-free lowercase form, so "2 pm" and "2pm" compare equal."""
    return re.sub(r"\s+", "", text or "").lower()


def unsupported_time_expressions(text: str, corpus: str) -> list[str]:
    """Day/time expressions in ``text`` that the evidence ``corpus`` does not
    contain — i.e. availability the draft INVENTED.

    Reuses the fabrication guard's own scheduling vocabulary so the two can never
    disagree about what counts as a time expression. Deliberately narrow: an
    explicit clock time, a weekday name, or a time-of-day word. A window the caller
    supplied, or one the other side already proposed in the thread, is in the
    corpus and is therefore never flagged.
    """
    squashed_corpus = _squash(corpus)
    lower_corpus = (corpus or "").lower()
    found: list[str] = []

    def _add(token: str) -> None:
        if token and token not in found:
            found.append(token)

    for match in _CLOCK_TIME_RE.finditer(text or ""):
        token = match.group(0)
        if _squash(token) not in squashed_corpus:
            _add(token)
    for word in re.findall(r"[A-Za-z]+", text or ""):
        low = word.lower()
        if (low in _WEEKDAYS or low in _TIME_OF_DAY_WORDS) and low not in lower_corpus:
            _add(word)
    return found


@dataclass
class InterviewThread:
    threadId: str
    subject: str | None = None
    jobTitle: str | None = None
    company: str | None = None


@dataclass
class SchedulingResult:
    threadId: str | None = None
    threadSubject: str | None = None
    requestedThreadId: str | None = None
    #: ``explicit`` (caller supplied an id) or ``mostRecentInterview``.
    threadSelection: str | None = None
    jobTitle: str | None = None
    company: str | None = None
    subject: str = ""
    draft: str = ""
    draftWithheld: bool = False
    flagged: list[str] = field(default_factory=list)
    #: The windows the CALLER supplied, echoed back. Empty means the draft asks the
    #: other side for times instead of proposing any.
    proposedTimes: list[str] = field(default_factory=list)
    #: Always False, always reported: Aether reads and writes no calendar, so no
    #: run of this agent may imply otherwise.
    calendarIntegration: bool = False
    noInterviewThreads: bool = False
    notInterviewStage: bool = False
    emptyThread: bool = False
    missingResume: bool = False
    candidates: list[InterviewThread] = field(default_factory=list)
    llm_called: bool = False
    message: str = ""


#: Threads attached to an application of the CALLER'S OWN that really sits at the
#: ``interview`` stage, newest activity first. The join is what makes
#: "interview-stage thread" a fact rather than an assumption.
_INTERVIEW_THREADS_SQL = """
    SELECT et."id", et."subject", et."messages", et."applicationId",
           et."gmailThreadId", et."gmailMessageId",
           j."title" AS "jobTitle", j."company" AS "company"
    FROM "EmailThread" et
    JOIN "Application" a
      ON a."id" = et."applicationId" AND a."userId" = et."userId"
    JOIN "Job" j ON j."id" = a."jobId"
    WHERE et."userId" = %s AND a."status" = 'interview'::"ApplicationStatus"
    ORDER BY et."updatedAt" DESC, et."id" DESC
    LIMIT %s
"""


class SchedulingAgent:
    def __init__(self, llm: Any | None = None, guard: Any | None = None) -> None:
        self._llm = llm
        self._guard = guard

    # ------------------------------------------------------------------ run
    def run(
        self,
        user_id: str,
        thread_id: str | None = None,
        proposed_times: list[str] | None = None,
    ) -> SchedulingResult:
        requested = (thread_id or "").strip() or None
        result = SchedulingResult(requestedThreadId=requested)
        result.proposedTimes = self._clean_times(proposed_times)

        eligible = self._interview_threads(user_id)
        result.candidates = [
            InterviewThread(
                threadId=str(t["id"]),
                subject=t.get("subject"),
                jobTitle=t.get("jobTitle"),
                company=t.get("company"),
            )
            for t in eligible
        ]

        thread = self._resolve(user_id, requested, eligible, result)
        if thread is None:
            return result

        if not latest_body(thread).strip():
            result.emptyThread = True
            result.message = (
                "That thread carries no message text, so there is nothing to reply "
                "to yet."
            )
            return result

        resume_text = resolve_user_resume_text(user_id, allow_operator_fallback=False)
        if not resume_text.strip():
            result.missingResume = True
            result.message = (
                "Add your résumé before drafting a reply — outbound text is only "
                "written from your own recorded experience."
            )
            return result

        self._draft(thread, resume_text, result)
        return result

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _clean_times(proposed_times: list[str] | None) -> list[str]:
        """The caller's OWN availability windows, bounded and de-duplicated. These
        are the user's own input, so they are legitimate evidence — but they are
        still bounded before entering a prompt."""
        cleaned: list[str] = []
        for value in proposed_times or []:
            if not isinstance(value, (str, int, float)):
                continue
            text = str(value).strip()[:_MAX_TIME_LEN]
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= _MAX_PROPOSED_TIMES:
                break
        return cleaned

    @staticmethod
    def _interview_threads(user_id: str) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(_INTERVIEW_THREADS_SQL, (user_id, _MAX_CANDIDATES))
                return rows_to_dicts(cur)

    def _resolve(
        self,
        user_id: str,
        requested: str | None,
        eligible: list[dict[str, Any]],
        result: SchedulingResult,
    ) -> dict[str, Any] | None:
        """The thread to reply on, or ``None`` after recording an honest refusal."""
        if requested is not None:
            # LookupError -> honest 404 for a thread that is not the caller's.
            thread = load_thread(user_id, requested)
            match = next(
                (t for t in eligible if str(t["id"]) == str(thread["id"])), None
            )
            if match is None:
                result.threadId = str(thread["id"])
                result.threadSubject = thread.get("subject")
                result.threadSelection = "explicit"
                result.notInterviewStage = True
                result.message = (
                    "That thread is not attached to an application at the interview "
                    "stage, so there is no interview to propose times for. Move the "
                    "application to Interview first, or use the Email Agent to draft "
                    "an ordinary reply."
                )
                return None
            self._stamp(result, match, "explicit")
            return match

        if not eligible:
            result.noInterviewThreads = True
            result.message = (
                "No email thread of yours is attached to an application at the "
                "interview stage, so there is nothing to schedule. Aether reads no "
                "calendar and never invents an interview."
            )
            return None
        thread = eligible[0]
        self._stamp(result, thread, "mostRecentInterview")
        return thread

    @staticmethod
    def _stamp(
        result: SchedulingResult, thread: dict[str, Any], selection: str
    ) -> None:
        result.threadId = str(thread["id"])
        result.threadSubject = thread.get("subject")
        result.threadSelection = selection
        result.jobTitle = thread.get("jobTitle")
        result.company = thread.get("company")

    # ---------------------------------------------------------------- draft
    def _draft(
        self,
        thread: dict[str, Any],
        resume_text: str,
        result: SchedulingResult,
    ) -> None:
        raw_thread = thread_block(thread)
        availability = (
            "\n".join(f"- {t}" for t in result.proposedTimes)
            if result.proposedTimes
            else "(none supplied — do NOT propose any specific day, date or time)"
        )
        # The caller's own windows are legitimate evidence and join the corpus
        # verbatim; the thread joins it only in its SANITIZED form (the same text
        # the model was shown).
        corpus = "\n".join(
            [resume_text, sanitized_corpus(raw_thread), *result.proposedTimes]
        )
        result.llm_called = True
        draft = guarded_draft(
            self._llm,
            prompt_name="scheduling_reply",
            system=SYSTEM_PROMPT,
            user_prompt=(
                f"THREAD:\n{fence(UNTRUSTED_THREAD, raw_thread)}\n\n"
                f"AVAILABILITY (the candidate's own, use verbatim):\n{availability}\n\n"
                f"CANDIDATE RÉSUMÉ:\n{resume_text}"
            ),
            corpus=corpus,
            untrusted_raw=raw_thread,
            candidate_evidence=resume_text,
            guard=self._guard,
            fixture_key="proposed" if result.proposedTimes else "default",
        )
        flagged = list(draft.flagged)
        if not draft.withheld:
            # The additional no-invented-availability rail. Runs only once the
            # existing guard has passed, so BOTH must hold for a draft to ship.
            flagged.extend(
                unsupported_time_expressions(f"{draft.subject}\n{draft.body}", corpus)
            )
        if flagged:
            result.draftWithheld = True
            result.flagged = flagged
            result.message = (
                "The reply was withheld — it used "
                f"{flagged}, which neither the thread, your résumé nor the "
                "availability you supplied supports. Aether reads no calendar, so it "
                "never proposes a time you did not give it."
            )
            return

        result.subject = draft.subject
        result.draft = draft.body
        if result.proposedTimes:
            result.message = (
                f"Reply drafted proposing the {len(result.proposedTimes)} window(s) "
                "you supplied. Nothing is booked and nothing was sent — Aether reads "
                "and writes no calendar. Send it from the Email Center when you are "
                "happy with it."
            )
        else:
            result.message = (
                "Reply drafted asking the sender for windows that suit them. You "
                "supplied no availability and Aether reads no calendar, so it "
                "proposes no times of its own. Nothing is booked and nothing was "
                "sent."
            )
