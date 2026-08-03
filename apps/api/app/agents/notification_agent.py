"""Notification Agent — REAL email digests, approval-gated (wave-4C).

HONEST SCOPE (ADR-AG-1, verbatim: "Real email digests (status changes, new
matches) to the user via their CONNECTED GMAIL (GmailService.send, approval-gated
like emailAgent); honest 409 when Gmail not connected"). The card's old tip said it
"monitors status changes and pushes timely alerts" — there is no push channel in
this product (no web-push, no SMS, no mobile app), so "pushes" was unachievable and
the copy is corrected in this same change. The channel that DOES exist is the user's
own connected Gmail.

What ships:

* a DETERMINISTIC digest composed from the user's OWN rows — no model is called, so
  the run is unmetered and costs nothing;
* "since last digest" is a REAL watermark: the window starts at the ``windowEnd`` of
  the most recent digest whose approval was actually EXECUTED. A digest the user
  rejected, or never approved, therefore does NOT swallow its items — they appear
  again in the next one;
* NOTHING is fabricated. With no real activity in the window the agent says so and
  creates NO approval: an empty "here's your update" email is exactly the fake
  activity ADR-AG-1 forbids;
* the recipient is the user's OWN connected Gmail address. With no Gmail connected
  there IS no such address, so no approval is created — the digest is still computed
  and returned so the user sees the real data in-app, and the message says what to
  connect. Once queued, the send remains gated: ``POST /approvals/{id}/execute``
  fails with an honest 409 ("no_email_provider_connected") if Gmail is disconnected
  before approval, and no email is sent.

WHAT "STATUS CHANGES" HONESTLY MEANS. Aether keeps no application status-history
table, so a specific TRANSITION ("screening -> interview") is not observable. The
digest therefore reports applications whose record CHANGED inside the window
together with their CURRENT status, and the email says exactly that. Inventing the
"from" side of a transition would be fabricated activity.

WHAT "NEW MATCHES" HONESTLY MEANS. A posting that has never been scored is a
discovery, not a match, so only postings with a real ``fitScore`` count as matches.
Postings discovered but not yet scored are reported as a separate COUNT
(``unscoredDiscoveries``) rather than being silently promoted to "matches" or
silently dropped.

Storage: one additive table, created by lazy idempotent DDL under a transaction
-scoped advisory lock (ADR-TR-1) — ``CREATE TABLE IF NOT EXISTS`` /
``CREATE INDEX IF NOT EXISTS`` only, and deliberately NO foreign key to ``User``
(mirroring ``GmailAccount``/``AgentConfig``) so the shared test-suite's
``TRUNCATE "User"`` never trips over it. A digest row whose approval row is gone
simply yields no watermark, which is the safe direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.agents.cover_letter_agent import sanitize_untrusted_text
from app.agents.outreach_support import queue_email_approval
from app.db import ensure_approval_columns, get_connection, new_id, rows_to_dicts
from app.repositories.approval import ApprovalRepository
from app.repositories.gmail_account import GmailAccountRepository

#: Distinct advisory-lock id (AgentConfig 711 … GmailAccount 718 …
#: NotificationDigest 726).
_DIGEST_LOCK = 7420240726

#: One digest per user awaiting approval — a repeat run refreshes it.
DIGEST_KIND = "notification_digest"
DIGEST_DEDUPE_KEY = "notification_digest"

#: Bounded so a long-neglected account cannot produce an unbounded email.
_MAX_STATUS_UPDATES = 25
_MAX_NEW_MATCHES = 15

_table_ready = False


def ensure_notification_digest_table() -> None:
    """Idempotently create ``NotificationDigest`` (ADR-TR-1 lazy DDL).

    Additive only: ``CREATE TABLE IF NOT EXISTS`` + ``CREATE INDEX IF NOT EXISTS``,
    serialized by a transaction-scoped advisory lock so concurrent first hits
    cannot race on Postgres's ``pg_type`` index.
    """
    global _table_ready
    if _table_ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables"
                " WHERE table_name = 'NotificationDigest'"
                " AND table_schema = ANY(current_schemas(false))"
            )
            row = cur.fetchone()
            if row and row[0] == 1:
                _table_ready = True
                return
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_DIGEST_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "NotificationDigest" (
                    "id"            text PRIMARY KEY,
                    "userId"        text NOT NULL,
                    "approvalId"    text,
                    "windowStart"   timestamptz,
                    "windowEnd"     timestamptz NOT NULL,
                    "statusUpdates" integer NOT NULL DEFAULT 0,
                    "newMatches"    integer NOT NULL DEFAULT 0,
                    "createdAt"     timestamptz NOT NULL DEFAULT now(),
                    "updatedAt"     timestamptz NOT NULL DEFAULT now()
                )
                '''
            )
            cur.execute(
                'CREATE INDEX IF NOT EXISTS "idx_notificationdigest_userId"'
                ' ON "NotificationDigest" ("userId")'
            )
        conn.commit()
    _table_ready = True


@dataclass
class StatusUpdate:
    applicationId: str
    jobTitle: str
    company: str
    status: str
    updatedAt: str | None = None


@dataclass
class NewMatch:
    jobId: str
    title: str
    company: str
    fitScore: float | None = None
    location: str | None = None
    remote: bool = False
    sourceUrl: str | None = None


@dataclass
class NotificationResult:
    #: Start of the reporting window: the last EXECUTED digest's end, or None for
    #: a first digest ("everything so far").
    windowStart: str | None = None
    windowEnd: str | None = None
    firstDigest: bool = True
    statusUpdates: list[StatusUpdate] = field(default_factory=list)
    newMatches: list[NewMatch] = field(default_factory=list)
    #: Postings discovered in the window with NO fit score yet — counted, never
    #: promoted to "matches" and never silently dropped.
    unscoredDiscoveries: int = 0
    nothingToReport: bool = False
    gmailConnected: bool = False
    recipient: str | None = None
    subject: str = ""
    body: str = ""
    approvalId: str | None = None
    approvalStatus: str | None = None
    digestId: str | None = None
    message: str = ""


class NotificationAgent:
    def __init__(
        self,
        approvals: ApprovalRepository | None = None,
        credentials: GmailAccountRepository | None = None,
    ) -> None:
        self._approvals = approvals or ApprovalRepository()
        self._credentials = credentials or GmailAccountRepository()

    # ------------------------------------------------------------------ run
    def run(self, user_id: str) -> NotificationResult:
        ensure_notification_digest_table()
        ensure_approval_columns()  # ``executedAt`` backs the watermark below

        now = self._db_now()
        watermark = self._watermark(user_id)
        result = NotificationResult(
            windowStart=_iso(watermark),
            windowEnd=_iso(now),
            firstDigest=watermark is None,
        )
        result.statusUpdates = self._status_updates(user_id, watermark, now)
        result.newMatches, result.unscoredDiscoveries = self._new_matches(
            user_id, watermark, now
        )

        if not result.statusUpdates and not result.newMatches:
            result.nothingToReport = True
            result.gmailConnected = self._credentials.is_connected(user_id)
            result.message = (
                "Nothing new since your last digest"
                if watermark is not None
                else "No application activity or scored matches yet"
            ) + (
                f" — {result.unscoredDiscoveries} discovered posting(s) are still "
                "unscored, so run Match Scoring to turn them into matches."
                if result.unscoredDiscoveries
                else ". No digest was queued: an update email with nothing in it "
                "would be fake activity."
            )
            return result

        result.subject = self._subject(result)
        result.body = self._body(result)

        account = self._credentials.public_view(user_id)
        recipient = ((account or {}).get("googleEmail") or "").strip()
        result.gmailConnected = bool(recipient) and self._credentials.is_connected(
            user_id
        )
        if not result.gmailConnected:
            result.message = (
                f"Digest ready: {len(result.statusUpdates)} status update(s) and "
                f"{len(result.newMatches)} new match(es). No Gmail account is "
                "connected, so there is no address of yours to send it to and "
                "nothing was queued — connect Gmail in the Email Center, then run "
                "this again. The digest above is the real data either way."
            )
            return result

        result.recipient = recipient
        approval = queue_email_approval(
            self._approvals,
            user_id,
            to=recipient,
            subject=result.subject,
            body=result.body,
            kind=DIGEST_KIND,
            dedupe_key=DIGEST_DEDUPE_KEY,
        )
        result.approvalId = approval["id"]
        result.approvalStatus = approval["status"]
        result.digestId = self._record_digest(user_id, result, watermark, now)
        result.message = (
            f"Digest queued for your approval: {len(result.statusUpdates)} status "
            f"update(s) and {len(result.newMatches)} new match(es), addressed to "
            f"{recipient}. Nothing has been sent yet, and the window only advances "
            "once you actually send it."
        )
        return result

    # ------------------------------------------------------------ watermark
    @staticmethod
    def _db_now() -> datetime:
        """One clock for the whole run — the DATABASE's, so the window end and the
        row filters below cannot disagree by any client/server skew."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT now()")
                return cur.fetchone()[0]

    @staticmethod
    def _watermark(user_id: str) -> datetime | None:
        """End of the last digest the user ACTUALLY SENT, or ``None``.

        Keyed on the approval being approved AND executed, so a digest that was
        rejected — or is still sitting pending — never suppresses its own items.

        CRITICAL-4: "executed" here requires ``executionCompletedAt``, not just
        the ``executedAt`` claim. ``claim_execution`` stamps ``executedAt``
        BEFORE the send runs, so keying on it alone meant a process killed
        mid-send still advanced this window — permanently suppressing every
        status update and new match inside it from every future digest, with
        no way for the user to notice the loss. The window may only move on a
        send that provably completed.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT nd."windowEnd" FROM "NotificationDigest" nd'
                    ' JOIN "ApprovalRequest" ar'
                    '   ON ar."id" = nd."approvalId" AND ar."userId" = nd."userId"'
                    ' WHERE nd."userId" = %s'
                    '   AND ar."status" = \'approved\'::"ApprovalStatus"'
                    '   AND ar."executionCompletedAt" IS NOT NULL'
                    ' ORDER BY nd."windowEnd" DESC LIMIT 1',
                    (user_id,),
                )
                row = cur.fetchone()
        return row[0] if row else None

    def _record_digest(
        self,
        user_id: str,
        result: NotificationResult,
        watermark: datetime | None,
        now: datetime,
    ) -> str:
        """Persist (or refresh) the digest row backing the watermark.

        A repeat run REFRESHES the row tied to the same still-pending approval —
        mirroring the approval dedupe — so re-running never stacks rows, and the
        window that eventually advances is the one the user actually sent.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'UPDATE "NotificationDigest" SET "windowStart" = %s,'
                    ' "windowEnd" = %s, "statusUpdates" = %s, "newMatches" = %s,'
                    ' "updatedAt" = now() WHERE "id" = ('
                    '   SELECT "id" FROM "NotificationDigest"'
                    '   WHERE "userId" = %s AND "approvalId" = %s'
                    '   ORDER BY "createdAt" DESC LIMIT 1'
                    ') RETURNING "id"',
                    (
                        watermark, now, len(result.statusUpdates),
                        len(result.newMatches), user_id, result.approvalId,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    digest_id = new_id()
                    cur.execute(
                        'INSERT INTO "NotificationDigest" ("id","userId","approvalId",'
                        '"windowStart","windowEnd","statusUpdates","newMatches")'
                        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            digest_id, user_id, result.approvalId, watermark, now,
                            len(result.statusUpdates), len(result.newMatches),
                        ),
                    )
                else:
                    digest_id = str(row[0])
            conn.commit()
        return digest_id

    # ------------------------------------------------------------- gathering
    @staticmethod
    def _status_updates(
        user_id: str, watermark: datetime | None, now: datetime
    ) -> list[StatusUpdate]:
        """Applications of the caller's whose record changed inside the window,
        with their CURRENT status. ``draft`` is excluded: an untouched draft is not
        an update worth emailing about."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT a."id", a."status"::text AS "status", a."updatedAt",'
                    ' j."title", j."company" FROM "Application" a'
                    ' JOIN "Job" j ON j."id" = a."jobId"'
                    ' WHERE a."userId" = %s'
                    '   AND a."status" <> \'draft\'::"ApplicationStatus"'
                    '   AND a."updatedAt" <= %s'
                    '   AND (%s::timestamptz IS NULL OR a."updatedAt" > %s::timestamptz)'
                    ' ORDER BY a."updatedAt" DESC LIMIT %s',
                    (user_id, now, watermark, watermark, _MAX_STATUS_UPDATES),
                )
                rows = rows_to_dicts(cur)
        return [
            StatusUpdate(
                applicationId=str(r["id"]),
                jobTitle=_clean(r.get("title")),
                company=_clean(r.get("company")),
                status=str(r["status"]),
                updatedAt=_iso(r.get("updatedAt")),
            )
            for r in rows
        ]

    @staticmethod
    def _new_matches(
        user_id: str, watermark: datetime | None, now: datetime
    ) -> tuple[list[NewMatch], int]:
        """(scored matches discovered in the window, count of unscored discoveries).

        A posting with no ``fitScore`` has never been matched, so it is COUNTED
        rather than reported as a match — and never silently dropped either.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT j."id", j."title", j."company", j."location", j."remote",'
                    ' j."fitScore", j."sourceUrl" FROM "Job" j'
                    ' WHERE j."userId" = %s AND j."fitScore" IS NOT NULL'
                    '   AND j."createdAt" <= %s'
                    '   AND (%s::timestamptz IS NULL OR j."createdAt" > %s::timestamptz)'
                    ' ORDER BY j."fitScore" DESC, j."createdAt" DESC LIMIT %s',
                    (user_id, now, watermark, watermark, _MAX_NEW_MATCHES),
                )
                rows = rows_to_dicts(cur)
                cur.execute(
                    'SELECT COUNT(*) FROM "Job" j WHERE j."userId" = %s'
                    '   AND j."fitScore" IS NULL AND j."createdAt" <= %s'
                    '   AND (%s::timestamptz IS NULL OR j."createdAt" > %s::timestamptz)',
                    (user_id, now, watermark, watermark),
                )
                unscored = int(cur.fetchone()[0])
        matches = [
            NewMatch(
                jobId=str(r["id"]),
                title=_clean(r.get("title")),
                company=_clean(r.get("company")),
                fitScore=float(r["fitScore"]) if r.get("fitScore") is not None else None,
                location=_clean(r.get("location")) or None,
                remote=bool(r.get("remote")),
                sourceUrl=r.get("sourceUrl"),
            )
            for r in rows
        ]
        return matches, unscored

    # ------------------------------------------------------------ composition
    @staticmethod
    def _subject(result: NotificationResult) -> str:
        return (
            f"Aether digest — {len(result.statusUpdates)} status update(s), "
            f"{len(result.newMatches)} new match(es)"
        )

    @staticmethod
    def _body(result: NotificationResult) -> str:
        """The digest email, composed entirely from the rows above.

        Every line is a value read out of the user's own tables — nothing is
        generated, so there is nothing here for a fabrication guard to check. The
        wording is deliberately explicit about what the numbers mean.
        """
        window = (
            f"since your last digest ({result.windowStart})"
            if result.windowStart
            else "covering everything so far"
        )
        lines = [f"Your Aether digest, {window}.", ""]
        if result.statusUpdates:
            lines.append(
                f"APPLICATIONS UPDATED ({len(result.statusUpdates)}) — Aether keeps "
                "no status history, so each line shows the CURRENT status of an "
                "application whose record changed in this window:"
            )
            for update in result.statusUpdates:
                lines.append(
                    f"- {update.jobTitle} at {update.company}: {update.status} "
                    f"(updated {update.updatedAt})"
                )
            lines.append("")
        if result.newMatches:
            lines.append(f"NEW SCORED MATCHES ({len(result.newMatches)}):")
            for match in result.newMatches:
                score = "unscored" if match.fitScore is None else f"fit {match.fitScore}"
                where = f" — {match.location}" if match.location else ""
                lines.append(f"- {match.title} at {match.company}{where} ({score})")
                if match.sourceUrl:
                    lines.append(f"  {match.sourceUrl}")
            lines.append("")
        if result.unscoredDiscoveries:
            lines.append(
                f"{result.unscoredDiscoveries} further posting(s) were discovered in "
                "this window but have no fit score yet, so they are not counted as "
                "matches. Run Match Scoring to score them."
            )
            lines.append("")
        lines.append(
            "This digest was assembled from your own Aether data. Nothing in it is "
            "inferred or estimated."
        )
        return "\n".join(lines)


def _clean(value: Any) -> str:
    """Scraped external text (job title/company/location) on its way into an email.

    Sanitized with the EXISTING untrusted-text redactor: these strings come from
    job boards, and a posting-embedded directive has no business appearing in the
    user's own digest. A normal title passes through unchanged.
    """
    return sanitize_untrusted_text(str(value or "")).strip()


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None
