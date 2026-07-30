"""Sentiment Analysis Agent — tone of one inbound thread (wave-4C).

HONEST SCOPE (ADR-AG-1). The card promised "tone & sentiment scoring of replies",
which IS achievable — the product already holds real inbound ``EmailThread`` rows
and already reasons over them on the triage LLM path. This agent is the thin,
honest agent over exactly that:

* it classifies ONE thread per run (the caller's own), on the same REASONING tier
  the Email Agent's triage uses, and REPORTS which thread it picked;
* with no thread at all it returns an honest empty result and calls NO model;
* a thread with no message body is refused rather than "classified" — scoring an
  empty body would be a verdict about nothing;
* it writes nothing. The triage ``classification``/``aiScore`` columns belong to
  the Email Agent's own triage run and are never overwritten from here.

Fabrication discipline, split by what CAN be fabricated:

* ``tone`` is drawn from a CLOSED vocabulary and ``score`` is a clamped 0-100 int
  (``coerce_score``) that stays ``None`` when the model returned no genuine
  number — never a fabricated 0, which would read as a real "hostile" verdict. A
  label outside the vocabulary becomes ``unclassified`` and the raw label is
  reported, rather than being silently rounded to the nearest real verdict.
* ``rationale``/``signals`` are FREE TEXT and therefore fabricable, so they go
  through the EXISTING ``FabricationGuard`` against the SANITIZED thread text plus
  both cover-letter injection backstops. A hit WITHHOLDS them (reported as
  ``rationaleWithheld`` + ``flagged``) while the structurally-constrained tone and
  score survive — there is nothing for a guard to catch in a closed-vocabulary
  label, and dropping a legitimate classification because its prose was flagged
  would be a worse outcome than dropping the prose.

The thread is UNTRUSTED external text (a stranger wrote it), so it is sanitized +
fenced before entering the prompt and joins the guard's corpus only in that
sanitized form.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.outreach_support import (
    UNTRUSTED_RULE,
    UNTRUSTED_THREAD,
    coerce_score,
    fence,
    injection_leaks,
    latest_body,
    load_thread,
    sanitized_corpus,
    thread_block,
)
from app.db import get_connection, rows_to_dicts
from app.services.fabrication_guard import FabricationGuard
from app.services.llm_client import LLMClient, get_model

#: The CLOSED tone vocabulary. A label outside it is reported as unrecognised
#: rather than mapped to the nearest real verdict.
TONES = ("positive", "neutral", "negative", "mixed")

UNCLASSIFIED = "unclassified"

SYSTEM_PROMPT = (
    "You classify the TONE of one email a job-seeking candidate received. Judge "
    "only the supplied message — never the candidate, never anything outside it. "
    "Pick exactly one tone from [positive, neutral, negative, mixed], give an "
    "integer 0-100 for how POSITIVE the message is toward the candidate (100 = "
    "warmest), list the concrete phrases that drove the call, and explain in one "
    "or two sentences. Quote or paraphrase only what the message actually says: "
    "never infer an outcome, a decision, a salary, or a next step it does not "
    f"state. {UNTRUSTED_RULE} Respond with JSON: "
    '{"tone": "positive", "score": 0-100, "signals": ["..."], '
    '"rationale": "..."}'
)


@dataclass
class SentimentResult:
    threadId: str | None = None
    threadSubject: str | None = None
    requestedThreadId: str | None = None
    #: ``explicit`` (caller supplied an id) or ``mostRecent``. Never a silent pick.
    threadSelection: str | None = None
    #: The Email Agent's own persisted triage category for this thread, when it
    #: has been triaged. Read-only context — never written from here.
    triageCategory: str | None = None
    tone: str | None = None
    #: The raw label when the model answered outside :data:`TONES`.
    rawTone: str | None = None
    toneUnrecognized: bool = False
    #: ``None`` when the model returned no genuine number — never a fabricated 0.
    score: int | None = None
    signals: list[str] = field(default_factory=list)
    rationale: str | None = None
    rationaleWithheld: bool = False
    flagged: list[str] = field(default_factory=list)
    noThreads: bool = False
    emptyThread: bool = False
    threadsAvailable: int = 0
    llm_called: bool = False
    message: str = ""


class SentimentAnalysisAgent:
    def __init__(self, llm: Any | None = None, guard: FabricationGuard | None = None) -> None:
        self._llm = llm  # constructed lazily only when a model is really reached
        self._guard = guard or FabricationGuard()

    # ------------------------------------------------------------------ run
    def run(self, user_id: str, thread_id: str | None = None) -> SentimentResult:
        requested = (thread_id or "").strip() or None
        result = SentimentResult(requestedThreadId=requested)

        if requested is not None:
            thread = load_thread(user_id, requested)  # LookupError -> honest 404
            result.threadSelection = "explicit"
            result.threadsAvailable = self._thread_count(user_id)
        else:
            recent = self._most_recent(user_id)
            result.threadsAvailable = self._thread_count(user_id)
            if recent is None:
                result.noThreads = True
                result.message = (
                    "No email threads yet — connect Gmail in the Email Center and "
                    "run the Email Agent's triage to sync your inbox, then there is "
                    "a real message to read the tone of."
                )
                return result
            thread = recent
            result.threadSelection = "mostRecent"

        result.threadId = str(thread["id"])
        result.threadSubject = thread.get("subject")
        result.triageCategory = thread.get("classification")

        body = latest_body(thread)
        if not body.strip():
            result.emptyThread = True
            result.message = (
                "That thread carries no message text, so there is no tone to read. "
                "Nothing is inferred from an empty message."
            )
            return result

        self._classify(thread, result)
        return result

    # ----------------------------------------------------------- thread reads
    @staticmethod
    def _thread_count(user_id: str) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COUNT(*) FROM "EmailThread" WHERE "userId" = %s',
                    (user_id,),
                )
                return int(cur.fetchone()[0])

    @staticmethod
    def _most_recent(user_id: str) -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "id", "subject", "messages", "classification"'
                    ' FROM "EmailThread" WHERE "userId" = %s'
                    ' ORDER BY "createdAt" DESC, "id" DESC LIMIT 1',
                    (user_id,),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    # -------------------------------------------------------------- classify
    def _classify(self, thread: dict[str, Any], result: SentimentResult) -> None:
        raw_thread = thread_block(thread)
        corpus = sanitized_corpus(raw_thread)
        result.llm_called = True
        raw = (self._llm or LLMClient()).complete_json(
            "email_sentiment",
            SYSTEM_PROMPT,
            f"MESSAGE:\n{fence(UNTRUSTED_THREAD, raw_thread)}",
            model=get_model("REASONING"),
            temperature=0.0,
        )

        label = str(raw.get("tone") or "").strip().lower()
        if label in TONES:
            result.tone = label
        else:
            result.tone = UNCLASSIFIED
            result.toneUnrecognized = True
            result.rawTone = str(raw.get("tone") or "") or None
        result.score = coerce_score(raw.get("score"))

        signals = [
            str(s).strip()
            for s in (raw.get("signals") or [])
            if isinstance(s, (str, int, float)) and str(s).strip()
        ][:6]
        rationale = str(raw.get("rationale") or "").strip()

        # Free text is the only fabricable part — guard it against the SANITIZED
        # message the model was actually shown, plus both injection backstops.
        prose = "\n".join([rationale, *signals])
        flagged = list(self._guard.check(prose, corpus)) if prose else []
        for token in injection_leaks(prose, raw_thread, ""):
            if token not in flagged:
                flagged.append(token)
        if flagged:
            result.rationaleWithheld = True
            result.flagged = flagged
        else:
            result.signals = signals
            result.rationale = rationale or None

        result.message = self._message(result)

    @staticmethod
    def _message(result: SentimentResult) -> str:
        parts = []
        if result.toneUnrecognized:
            parts.append(
                "The model answered with a tone outside the supported set, so the "
                f"call is reported as {UNCLASSIFIED} (its raw answer is in rawTone) "
                "rather than mapped to the nearest verdict."
            )
        else:
            score = "no usable score" if result.score is None else f"score {result.score}"
            parts.append(f"Tone of this message reads {result.tone} ({score}).")
        if result.rationaleWithheld:
            parts.append(
                "The explanation was withheld — the fabrication guard flagged "
                f"{result.flagged}, which the message itself does not support. The "
                "tone and score above come from a fixed vocabulary and a clamped "
                "number, so they stand on their own."
            )
        parts.append("This reads one message; it is not a verdict on the employer.")
        return " ".join(parts)
