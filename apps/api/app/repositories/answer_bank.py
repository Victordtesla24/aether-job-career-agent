"""U5d-3 Pillar 1 — AnswerBankItem / AnswerBankUsage persistence.

TWO tables, both additive and FK-free (mirroring ``EvidenceCorpusItem`` and
``CareerProfile``): the shared test-suite's ``TRUNCATE "User"`` never trips
over them, and first-hit creation is serialised by a transaction-scoped
advisory lock so concurrent ``CREATE TABLE IF NOT EXISTS`` cannot race on
Postgres's ``pg_type`` index. Lazy DDL per ADR-TR-1 — there is no migration
runner.

``AnswerBankItem`` — the memory
    One row per ``(userId, semanticKey, scope, scopeValue)``: the canonical
    question as first asked, the semantic key the matcher retrieves by, the
    user's OWN answer stored verbatim, the scope it applies to, how it got
    there (provenance), its sensitivity class, its staleness policy, and the
    ``timesUsed``/``lastUsedAt`` counters the ADR asks for.

    The uniqueness key is the QUESTION CLASS, not the question string. Two
    employers wording the same question differently must update ONE answer, not
    accumulate a row each — otherwise editing "my notice period" in the UI would
    silently leave a dozen stale copies behind for the agent to pick from.

``AnswerBankUsage`` — the audit
    One row per auto-answer, written by the apply-executor. ADR honesty floor
    3: *"every auto-answer is auditable (which banked answer, which match
    confidence…)"*. That is exactly this table's three load-bearing columns —
    ``itemId``, ``matchConfidence``, ``questionAsSeen`` — plus the application
    it happened on, which is what makes the Answer Bank UI's "where used"
    a read of recorded fact rather than a guess.

WHY ``questionAsSeen`` IS STORED AND NOT DERIVED. The audit's whole value is
that a later reader can judge whether the match was right. A stored
``itemId`` + confidence with no record of what the employer actually asked
would be un-auditable: there would be nothing to compare the banked question
against.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from app.db import get_connection, new_id, rows_to_dicts
from app.services.answer_bank import (
    SENSITIVITY_SENSITIVE,
    classify_sensitivity,
    coerce_provenance,
    coerce_scope,
    normalize_question,
    semantic_key,
    stale_days_for,
)

#: Distinct advisory-lock id (see EvidenceCorpusItem / CareerProfile).
_ANSWER_BANK_TABLE_LOCK = 7420260821

_ITEM_COLS = (
    '"id", "userId", "questionText", "semanticKey", "answer", "scope", '
    '"scopeValue", "provenance", "provenanceDetail", "sensitivity", '
    '"staleDays", "expiresAt", "autoAnswerOptIn", "timesUsed", "lastUsedAt", '
    '"createdAt", "updatedAt"'
)

_USAGE_COLS = (
    '"id", "userId", "itemId", "applicationId", "jobId", "questionAsSeen", '
    '"matchConfidence", "matchMethod", "usedAt"'
)

#: Guard so table creation only runs once per worker process.
_tables_ready = False


class AnswerBankRepository:
    """Read/write access to the Answer Bank and its usage audit."""

    # -- schema ----------------------------------------------------------

    def _ensure_tables(self) -> None:
        global _tables_ready
        if _tables_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(%s)", (_ANSWER_BANK_TABLE_LOCK,)
                )
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "AnswerBankItem" (
                        "id"               text PRIMARY KEY,
                        "userId"           text NOT NULL,
                        "questionText"     text NOT NULL,
                        "semanticKey"      text NOT NULL,
                        "answer"           text NOT NULL,
                        "scope"            text NOT NULL DEFAULT 'global',
                        "scopeValue"       text NOT NULL DEFAULT '',
                        "provenance"       text NOT NULL,
                        "provenanceDetail" text,
                        "sensitivity"      text NOT NULL DEFAULT 'factual',
                        "staleDays"        integer,
                        "expiresAt"        timestamptz,
                        "autoAnswerOptIn"  boolean NOT NULL DEFAULT false,
                        "timesUsed"        integer NOT NULL DEFAULT 0,
                        "lastUsedAt"       timestamptz,
                        "createdAt"        timestamptz NOT NULL DEFAULT NOW(),
                        "updatedAt"        timestamptz NOT NULL DEFAULT NOW()
                    )
                    '''
                )
                cur.execute(
                    'CREATE UNIQUE INDEX IF NOT EXISTS "AnswerBankItem_key_idx" '
                    'ON "AnswerBankItem" '
                    '("userId", "semanticKey", "scope", "scopeValue")'
                )
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "AnswerBankUsage" (
                        "id"              text PRIMARY KEY,
                        "userId"          text NOT NULL,
                        "itemId"          text NOT NULL,
                        "applicationId"   text,
                        "jobId"           text,
                        "questionAsSeen"  text NOT NULL,
                        "matchConfidence" double precision NOT NULL,
                        "matchMethod"     text NOT NULL,
                        "usedAt"          timestamptz NOT NULL DEFAULT NOW()
                    )
                    '''
                )
                cur.execute(
                    'CREATE INDEX IF NOT EXISTS "AnswerBankUsage_item_idx" '
                    'ON "AnswerBankUsage" ("userId", "itemId", "usedAt" DESC)'
                )
            conn.commit()
        _tables_ready = True

    # -- reads -----------------------------------------------------------

    def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Every banked answer for ``user_id``, most recently touched first.

        An empty list is the honest state for a user who has answered nothing
        yet — callers must fall back to an honest manual step, never to a
        default answer.
        """
        self._ensure_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_ITEM_COLS} FROM "AnswerBankItem" '
                    'WHERE "userId" = %s ORDER BY "updatedAt" DESC, "id"',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def get(self, user_id: str, item_id: str) -> dict[str, Any] | None:
        """One item, scoped to its owner. ``None`` for anyone else's."""
        self._ensure_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_ITEM_COLS} FROM "AnswerBankItem" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (item_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    # -- writes ----------------------------------------------------------

    def upsert(
        self,
        user_id: str,
        *,
        question: str,
        answer: str,
        provenance: str,
        provenance_detail: str | None = None,
        scope: str = "global",
        scope_value: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Bank one answer — the user's words, unchanged — or refuse.

        Returns ``None`` (banking nothing) for a blank question or a blank
        answer: a bank row with no answer in it is not a memory, and a later
        matcher hitting it would have to invent something to send.

        The sensitivity class and the staleness policy are DERIVED from the
        question here rather than accepted from the caller, so a client cannot
        talk a sensitive question into a soft class by sending one.
        """
        text = str(question or "").strip()
        value = str(answer or "").strip()
        if not text or not value:
            return None
        self._ensure_tables()
        moment = now or datetime.now(timezone.utc)
        key = semantic_key(text)
        stale_days = stale_days_for(text)
        expires_at = moment + timedelta(days=stale_days) if stale_days else None
        sensitivity = classify_sensitivity(text)
        resolved_scope = coerce_scope(scope)
        resolved_scope_value = (
            normalize_question(scope_value or "") if resolved_scope != "global" else ""
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "AnswerBankItem" (
                        "id", "userId", "questionText", "semanticKey", "answer",
                        "scope", "scopeValue", "provenance", "provenanceDetail",
                        "sensitivity", "staleDays", "expiresAt",
                        "autoAnswerOptIn", "timesUsed", "lastUsedAt",
                        "createdAt", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            false, 0, NULL, NOW(), NOW())
                    ON CONFLICT ("userId", "semanticKey", "scope", "scopeValue")
                    DO UPDATE SET
                        "questionText"     = EXCLUDED."questionText",
                        "answer"           = EXCLUDED."answer",
                        "provenance"       = EXCLUDED."provenance",
                        "provenanceDetail" = EXCLUDED."provenanceDetail",
                        "sensitivity"      = EXCLUDED."sensitivity",
                        "staleDays"        = EXCLUDED."staleDays",
                        "expiresAt"        = EXCLUDED."expiresAt",
                        -- A re-answer of a SENSITIVE question can never leave an
                        -- opt-in behind: the class gate is absolute, so the flag
                        -- is forced off rather than carried over.
                        "autoAnswerOptIn"  = CASE
                            WHEN EXCLUDED."sensitivity" = %s THEN false
                            ELSE "AnswerBankItem"."autoAnswerOptIn" END,
                        "updatedAt"        = NOW()
                    RETURNING {_ITEM_COLS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        text,
                        key,
                        value,
                        resolved_scope,
                        resolved_scope_value,
                        coerce_provenance(provenance),
                        provenance_detail,
                        sensitivity,
                        stale_days,
                        expires_at,
                        SENSITIVITY_SENSITIVE,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def update(
        self,
        user_id: str,
        item_id: str,
        *,
        answer: str | None = None,
        scope: str | None = None,
        scope_value: str | None = None,
        auto_answer_opt_in: bool | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Edit one item the user owns. ``None`` if it is not theirs.

        Editing the ANSWER restarts its staleness clock — the user has just
        confirmed it, so the expiry that would have re-asked them is reset from
        this moment rather than from when the answer was first given.

        ``auto_answer_opt_in`` is honoured ONLY for a non-sensitive item. A
        sensitive answer stays user-gated whatever the request says; that is
        the honesty floor, and it is enforced here as well as in the matcher so
        neither layer alone can be the hole.
        """
        existing = self.get(user_id, item_id)
        if existing is None:
            return None
        moment = now or datetime.now(timezone.utc)
        new_answer = existing["answer"]
        expires_at = existing["expiresAt"]
        if answer is not None:
            stripped = str(answer).strip()
            if not stripped:
                return existing
            new_answer = stripped
            stale_days = existing["staleDays"]
            expires_at = moment + timedelta(days=stale_days) if stale_days else None
        new_scope = coerce_scope(scope) if scope is not None else existing["scope"]
        if scope is not None or scope_value is not None:
            raw_scope_value = (
                scope_value if scope_value is not None else existing["scopeValue"]
            )
            new_scope_value = (
                normalize_question(raw_scope_value or "") if new_scope != "global" else ""
            )
        else:
            new_scope_value = existing["scopeValue"]
        opt_in = existing["autoAnswerOptIn"]
        if auto_answer_opt_in is not None:
            opt_in = bool(auto_answer_opt_in) and (
                existing["sensitivity"] != SENSITIVITY_SENSITIVE
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "AnswerBankItem"
                    SET "answer" = %s,
                        "scope" = %s,
                        "scopeValue" = %s,
                        "expiresAt" = %s,
                        "autoAnswerOptIn" = %s,
                        "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_ITEM_COLS}
                    ''',
                    (
                        new_answer,
                        new_scope,
                        new_scope_value,
                        expires_at,
                        opt_in,
                        item_id,
                        user_id,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def expire(
        self, user_id: str, item_id: str, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """Retire an answer WITHOUT deleting it.

        The row and its usage history stay readable — "this answer was sent to
        these four employers, and I have since retired it" is a true and useful
        thing for the user to be able to see. The matcher skips it from this
        moment on because its expiry is in the past.
        """
        self._ensure_tables()
        moment = now or datetime.now(timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "AnswerBankItem"
                    SET "expiresAt" = %s, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s
                    RETURNING {_ITEM_COLS}
                    ''',
                    (moment, item_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def delete(self, user_id: str, item_id: str) -> bool:
        """Erase an answer and its usage audit. ``True`` iff something went.

        The usage rows go with it deliberately: the ADR promises *"the bank is
        user-deletable"*, and leaving behind an audit trail naming a question
        the user asked us to forget would not honour that.
        """
        self._ensure_tables()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "AnswerBankItem" WHERE "id" = %s AND "userId" = %s',
                    (item_id, user_id),
                )
                deleted = cur.rowcount > 0
                if deleted:
                    cur.execute(
                        'DELETE FROM "AnswerBankUsage" '
                        'WHERE "itemId" = %s AND "userId" = %s',
                        (item_id, user_id),
                    )
            conn.commit()
        return deleted

    # -- audit -----------------------------------------------------------

    def record_usage(
        self,
        user_id: str,
        item_id: str,
        *,
        application_id: str | None,
        job_id: str | None,
        question_as_seen: str,
        confidence: float,
        method: str,
    ) -> dict[str, Any] | None:
        """Record ONE auto-answer, and advance the item's counters.

        Writes nothing at all if the item is not this user's — a usage row
        pointing at someone else's answer would be a fabricated audit entry,
        which is worse than no entry.
        """
        self._ensure_tables()
        if not item_id or self.get(user_id, item_id) is None:
            return None
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    INSERT INTO "AnswerBankUsage" (
                        "id", "userId", "itemId", "applicationId", "jobId",
                        "questionAsSeen", "matchConfidence", "matchMethod",
                        "usedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING {_USAGE_COLS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        item_id,
                        application_id,
                        job_id,
                        str(question_as_seen or ""),
                        float(confidence),
                        str(method or ""),
                    ),
                )
                rows = rows_to_dicts(cur)
                cur.execute(
                    'UPDATE "AnswerBankItem" '
                    'SET "timesUsed" = "timesUsed" + 1, "lastUsedAt" = NOW() '
                    'WHERE "id" = %s AND "userId" = %s',
                    (item_id, user_id),
                )
            conn.commit()
        return rows[0] if rows else None

    def usage_for_items(
        self, user_id: str, item_ids: Sequence[str], *, limit_per_item: int = 25
    ) -> dict[str, list[dict[str, Any]]]:
        """Where each item was used, newest first — recorded fact only.

        Every requested id appears in the result, mapping to an empty list when
        it has never been used. An id with no usage is a real, honest answer
        ("banked, never needed yet"), not a gap to be filled in.
        """
        self._ensure_tables()
        wanted = [str(item_id) for item_id in item_ids if str(item_id or "").strip()]
        result: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in wanted}
        if not wanted:
            return result
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_USAGE_COLS} FROM "AnswerBankUsage" '
                    'WHERE "userId" = %s AND "itemId" = ANY(%s) '
                    'ORDER BY "usedAt" DESC',
                    (user_id, wanted),
                )
                for row in rows_to_dicts(cur):
                    bucket = result.setdefault(str(row["itemId"]), [])
                    if len(bucket) < limit_per_item:
                        bucket.append(row)
        return result
