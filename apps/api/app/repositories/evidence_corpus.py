"""EvidenceCorpusItem persistence — the provenance-tagged evidence store (U2c-0).

One row per ``(userId, itemId)`` evidence item: a single atomic CLAIM about the
candidate plus the provenance that makes it citable — which source it came
from (their baseline résumé, their portfolio site, one of their GitHub repos),
the exact URL, whether the source STATES it or it is INFERRED from the source,
how confident that inference is, when it was retrieved, and any caveat the
ingestion recorded.

Why a table and not the JSON file: the corpus is per-user career evidence that
the tailoring and cover-letter guards read on every run, it is refreshed on a
schedule (each refresh replaces a source's items wholesale), and every claim
must stay individually addressable so the UI can cite it. A file on disk in the
API image would be none of those things — it would be operator data baked into
a release, identical for every user. The U2c-0 snapshot
(``uat/reports/evidence/agents-uplift/u2c-0/corpus.json``) is therefore an
IMPORT INPUT (see ``app/services/evidence_corpus.py``), not the store.

Additive and FK-free, mirroring ``CareerProfile``: the shared test-suite's
``TRUNCATE "User"`` never trips over it, and first-hit creation is serialized
by a transaction-scoped advisory lock so concurrent ``CREATE TABLE IF NOT
EXISTS`` cannot race on Postgres's ``pg_type`` index (ADR-TR-1 lazy DDL — there
is no migration runner).
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.db import get_connection, rows_to_dicts

#: Distinct advisory-lock id (see CareerProfile / AgentConfig bootstraps).
_CORPUS_TABLE_LOCK = 7420260814

_SELECT_COLS = (
    '"userId", "itemId", "claim", "category", "source", "sourceUrl", '
    '"statedOrInferred", "confidence", "note", "asOf", "updatedAt"'
)

#: Guard so table creation only runs once per worker process.
_table_ready = False


class EvidenceCorpusRepository:
    """Read/write access to the ``EvidenceCorpusItem`` store."""

    def ensure_table(self) -> None:
        """Public bootstrap for the lazy, idempotent DDL.

        Every method here bootstraps itself, so callers normally never need
        this. The exception is a caller using the ``*_with_cursor`` seams below
        from inside its OWN transaction (the story de-dup sweep): the DDL takes
        an advisory-locked connection of its own and must run BEFORE that
        transaction opens, never nested inside it.
        """
        self._ensure_table()

    def _ensure_table(self) -> None:
        global _table_ready
        if _table_ready:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (_CORPUS_TABLE_LOCK,))
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS "EvidenceCorpusItem" (
                        "userId"           text NOT NULL,
                        "itemId"           text NOT NULL,
                        "claim"            text NOT NULL,
                        "category"         text,
                        "source"           text,
                        "sourceUrl"        text,
                        "statedOrInferred" text,
                        "confidence"       text,
                        "note"             text,
                        "asOf"             timestamptz,
                        "updatedAt"        timestamptz NOT NULL DEFAULT NOW(),
                        PRIMARY KEY ("userId", "itemId")
                    )
                    '''
                )
                cur.execute(
                    'CREATE INDEX IF NOT EXISTS "EvidenceCorpusItem_user_source_idx" '
                    'ON "EvidenceCorpusItem" ("userId", "source")'
                )
            conn.commit()
        _table_ready = True

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """Every stored evidence item for ``user_id``, newest retrieval first.

        An empty list is the honest state for a user whose corpus has never
        been ingested — callers must degrade to résumé-only evidence, never
        synthesise items.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_SELECT_COLS} FROM "EvidenceCorpusItem" '
                    'WHERE "userId" = %s ORDER BY "asOf" DESC NULLS LAST, "itemId"',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def upsert_many(self, user_id: str, items: Sequence[dict[str, Any]]) -> int:
        """Insert-or-replace ``items`` for ``user_id``; returns the row count.

        Keyed on the item's own stable id, so re-importing the same snapshot is
        idempotent and a refreshed snapshot updates a claim in place instead of
        duplicating it. Items with no id or no claim are skipped — a corpus row
        with nothing to cite is not evidence.
        """
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                written = self.upsert_many_with_cursor(cur, user_id, items)
            conn.commit()
        return written

    def upsert_many_with_cursor(
        self, cur: Any, user_id: str, items: Sequence[dict[str, Any]]
    ) -> int:
        """:meth:`upsert_many`'s body, executed on a CALLER-OWNED cursor.

        Exists so a writer that already runs inside its own audited, all-or-
        nothing transaction — the story de-dup sweep's archive/restore
        (``services/story_dedup_migration.py``) — can reconcile this mirror
        WITHOUT opening a second connection that would commit independently of
        the story rows it mirrors. A rolled-back merge must leave the evidence
        exactly as it was; a mirror write on its own connection would survive
        the rollback and delete evidence for a merge that never happened.

        The caller is responsible for :meth:`ensure_table` (the lazy DDL takes
        its own advisory-locked connection and must not run inside their
        transaction) and for the commit.
        """
        rows = [
            (
                user_id,
                str(item["id"]),
                str(item["claim"]),
                item.get("category"),
                item.get("source"),
                item.get("sourceUrl"),
                item.get("stated_or_inferred") or item.get("statedOrInferred"),
                item.get("confidence"),
                item.get("note"),
                item.get("asOf"),
            )
            for item in items
            if str(item.get("id") or "").strip() and str(item.get("claim") or "").strip()
        ]
        if not rows:
            return 0
        cur.executemany(
            '''
            INSERT INTO "EvidenceCorpusItem"
                ("userId", "itemId", "claim", "category", "source",
                 "sourceUrl", "statedOrInferred", "confidence", "note",
                 "asOf", "updatedAt")
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT ("userId", "itemId") DO UPDATE SET
                "claim"            = EXCLUDED."claim",
                "category"         = EXCLUDED."category",
                "source"           = EXCLUDED."source",
                "sourceUrl"        = EXCLUDED."sourceUrl",
                "statedOrInferred" = EXCLUDED."statedOrInferred",
                "confidence"       = EXCLUDED."confidence",
                "note"             = EXCLUDED."note",
                "asOf"             = EXCLUDED."asOf",
                "updatedAt"        = NOW()
            ''',
            rows,
        )
        return len(rows)

    def delete_items(self, user_id: str, item_ids: Iterable[str]) -> int:
        """Drop specific items of ``user_id`` by their own ids.

        The single-row counterpart of :meth:`delete_sources`, added for the
        Story Bank mirror (U-STORY-1 step 5): deleting ONE story must retract
        exactly that story's evidence, while ``delete_sources`` would retract
        every story the user has. Retraction has to be as precise as the write,
        or a deleted story stays citable.
        """
        ids = [i for i in item_ids if i]
        if not ids:
            return 0
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                deleted = self.delete_items_with_cursor(cur, user_id, ids)
            conn.commit()
        return deleted

    def delete_items_with_cursor(
        self, cur: Any, user_id: str, item_ids: Iterable[str]
    ) -> int:
        """:meth:`delete_items` on a CALLER-OWNED cursor — see
        :meth:`upsert_many_with_cursor` for why this seam exists."""
        ids = [i for i in item_ids if i]
        if not ids:
            return 0
        cur.execute(
            'DELETE FROM "EvidenceCorpusItem" '
            'WHERE "userId" = %s AND "itemId" = ANY(%s)',
            (user_id, ids),
        )
        return cur.rowcount or 0

    def delete_sources(self, user_id: str, sources: Iterable[str]) -> int:
        """Drop a user's items for the named sources (a refresh's first half).

        A scheduled re-ingestion replaces a source wholesale, so a claim the
        source no longer supports (a repo the user deleted, a portfolio section
        they removed) stops being citable instead of lingering as stale
        evidence the fabrication guard would still honour.
        """
        source_list = [s for s in sources if s]
        if not source_list:
            return 0
        self._ensure_table()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "EvidenceCorpusItem" '
                    'WHERE "userId" = %s AND "source" = ANY(%s)',
                    (user_id, source_list),
                )
                deleted = cur.rowcount or 0
            conn.commit()
        return deleted
