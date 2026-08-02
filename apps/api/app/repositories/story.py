"""Story bank repository — ``StoryEntry`` table (P2-S09).

G-P4-STORY-DEDUP-004: ``create`` hashes the five STAR content fields + userId
into a ``contentHash`` and returns the existing row instead of inserting when
that hash is already present, and ``update`` refreshes the hash whenever a STAR
field changes. This stops both re-run duplicates from the story-extractor agent
and double-saves from the REST create endpoint.

``contentHash`` is INTERNAL and is deliberately ABSENT from ``_COLUMNS`` — the
single column list every read/write path returns. Never selecting it is what
keeps the insert path and the dedup-hit path returning the SAME response shape
and keeps the sha256 out of API responses at the source (the router strips it
again as defence in depth; see ``routers/stories.py::_INTERNAL_COLUMNS``).

GMV4-story-004 — ARCHIVED ROWS. A row merged away by the bulk paraphrase
de-dup sweep (``app.services.story_dedup_migration``) is no longer deleted; it
is soft-archived (``archivedAt`` set, see ``app.db.ensure_story_archive_columns``).
``list_by_user`` — the single choke point through which EVERY consumer of the
Story Bank reads (stories router list/stats, cover-letter evidence,
``tailor_agent.build_story_evidence``, ``interview_prep_agent``,
``story_extractor``) — therefore filters ``"archivedAt" IS NULL``, so merged-away
content can never resurface in the UI, in tailoring evidence selection or in
relevance scoring. ``create``'s two dedup lookups filter it too, so a new save
can never be silently folded into an invisible archived row.

``get_by_id`` deliberately does NOT filter: it is the by-explicit-id
inspection/restore surface (and is what proves an archived row still exists),
and the row belongs to the requesting user either way.

The WRITE paths (``update``, ``delete``) DO filter, and that is what makes the
archive a guarantee rather than a listing convention (GMV4-story-004 round-2
review finding 1). Without it an archived row was still reachable for writing:
``PUT /stories/{id}`` rewrote it and echoed the archived content straight back
through ``_enrich``, and ``DELETE /stories/{id}`` PHYSICALLY destroyed it —
letting an ordinary request annihilate the recoverable merge loser that the
whole archive exists to protect. Both now resolve an archived id to "not
found"; see ``update``/``delete`` for why that is the right answer.
"""
from __future__ import annotations

import json
from typing import Any

from app.db import (
    ensure_story_achievement_column,
    ensure_story_archive_columns,
    ensure_story_dedup_column,
    get_connection,
    new_id,
    rows_to_dicts,
)
from app.services.dedup import compute_story_content_hash
from app.services.story_paraphrase import CREATE_TIME_THRESHOLDS, best_paraphrase_match

#: Client-safe columns — the internal ``contentHash`` is NEVER selected.
_COLUMNS = (
    '"id", "userId", "title", "situation", "task", "action", "result", '
    '"metrics", "tags", "createdAt", "updatedAt"'
)

#: STAR fields that constitute a story's content identity (drive the hash).
_STAR_FIELDS = ("title", "situation", "task", "action", "result")


class StoryRepository:
    def create(self, user_id: str, story: dict[str, Any]) -> dict[str, Any]:
        """The saved row, exactly as every existing caller expects it.

        Shape-identical to ``update``/``list_by_user`` rows — no extra keys —
        because ``test_story_dedup.py`` pins that the insert path, the dedup-hit
        path and the update path all return the SAME key set (a divergence
        there is how an internal column leaked into one path only). Callers
        that need to know whether the save was absorbed into an existing story
        use :meth:`create_with_outcome`.
        """
        return self.create_with_outcome(user_id, story)[0]

    def create_with_outcome(
        self, user_id: str, story: dict[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        """Insert a story, or MERGE it into an existing matching one.

        Returns ``(row, merged)``. ``merged`` is ``True`` only when this save
        REWROTE a pre-existing row with the caller's new wording — layer 0 or
        layer 2 below. GMV4-story-005 (BLOCKER): without that signal
        ``POST /stories`` answered ``201 Created`` for a save that created
        nothing and silently changed a DIFFERENT story the user already had,
        with no way for the client to tell the two apart. The flag is produced
        at the single point where the outcome is known, never re-derived
        downstream by comparing ids (which would be a guess).

        Layer 1 (identical content) deliberately reports ``merged=False``: an
        exact-hash hit is the same story submitted twice, so nothing was
        created AND nothing was altered — the returned row already holds
        precisely the text that was submitted. There is no other row for the
        user to be warned about, which is the only thing ``merged`` exists to
        warn about.

        Three dedup layers, checked in order:

        0. ACHIEVEMENT KEY (STORY-BANK-REBUILD-2026-08-02) — present only on
           stories produced by the source-grounded extractor, where
           ``story["achievementKey"]`` is a per-user hash of the RÉSUMÉ BULLET
           the story was drawn from
           (``app.services.resume_bullets.achievement_key``). This is an
           EXACT lookup on a stable identity, so it catches what the two
           layers below structurally cannot: an arbitrarily reworded
           re-telling of the same achievement. Measured on the live Story
           Bank before this layer existed, 43 rows described ~10 distinct
           achievements because same-achievement pairs there have a MEDIAN
           title Jaccard of 0.333 — far under the 0.70 the paraphrase layer
           requires. On a hit the existing row is UPDATED to the freshest
           wording and its metrics/tags REPLACED — the same bullet
           re-extracted restates the same evidence, so unioning only
           accumulated reworded duplicates of it (and a stale, wrong
           organisation tag); see ``_merge_into``.
           A partial unique index enforces the same invariant in the database
           (``app.db.ensure_story_achievement_column``).
        1. EXACT match — an identical sha256 of the five STAR fields
           (``contentHash``). NOT an error and NOT a silent drop: the caller
           gets back the row that already holds this exact content, in the
           same shape an insert returns, so ``POST /stories`` stays
           idempotent for identical content instead of growing the Story
           Bank a duplicate per double-click.
        2. PARAPHRASE match (GM2-STORY-001/002, §7.3.1) — a reworded
           re-telling of the SAME achievement (title + achievement keyword
           similarity, ``app.services.story_paraphrase``). Verified live: 34
           of the owner's 36 real stories were paraphrase re-tellings of only
           8 distinct achievements that the exact-hash check alone let
           through as brand-new rows every time. On a paraphrase match the
           EXISTING row is UPDATED to the new (freshest) wording — tags and
           metrics are MERGED (union), never dropped — and returned; nothing
           is inserted.
        """
        ensure_story_dedup_column()
        ensure_story_archive_columns()
        ensure_story_achievement_column()
        content_hash = compute_story_content_hash(
            user_id, *(story[f] for f in _STAR_FIELDS)
        )
        achievement_key = (story.get("achievementKey") or "").strip() or None
        with get_connection() as conn:
            with conn.cursor() as cur:
                if achievement_key is not None:
                    cur.execute(
                        'SELECT "id","title","situation","task","action","result",'
                        '"metrics","tags" FROM "StoryEntry" '
                        'WHERE "userId" = %s AND "achievementKey" = %s '
                        'AND "archivedAt" IS NULL LIMIT 1',
                        (user_id, achievement_key),
                    )
                    keyed = rows_to_dicts(cur)
                    if keyed:
                        rows = self._merge_into(
                            cur, user_id, keyed[0], story, achievement_key,
                            replace_evidence=True,
                        )
                        conn.commit()
                        return rows[0], True

                cur.execute(
                    'SELECT "id" FROM "StoryEntry" '
                    'WHERE "userId" = %s AND "contentHash" = %s '
                    'AND "archivedAt" IS NULL LIMIT 1',
                    (user_id, content_hash),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        f'SELECT {_COLUMNS} FROM "StoryEntry" WHERE "id" = %s',
                        (existing[0],),
                    )
                    return rows_to_dicts(cur)[0], False

                cur.execute(
                    'SELECT "id","title","situation","task","action","result",'
                    '"metrics","tags","achievementKey" FROM "StoryEntry" '
                    'WHERE "userId" = %s AND "archivedAt" IS NULL',
                    (user_id,),
                )
                candidates = rows_to_dicts(cur)
                if achievement_key is not None:
                    # A story that KNOWS which résumé bullet it came from must
                    # never be fuzzy-merged into a row that belongs to a
                    # DIFFERENT bullet: the key lookup above already answered
                    # "same achievement?" exactly, so a paraphrase hit here
                    # would be a false positive that both collapses two real
                    # achievements into one row AND silently reassigns that
                    # row's identity. Only rows with no identity of their own
                    # (pre-rebuild rows, hand-authored saves) stay eligible.
                    candidates = [c for c in candidates if not c.get("achievementKey")]
                match = best_paraphrase_match(story, candidates, CREATE_TIME_THRESHOLDS)
                if match is not None:
                    rows = self._merge_into(
                        cur, user_id, match, story, achievement_key,
                        replace_evidence=False,
                    )
                    conn.commit()
                    return rows[0], True

                cur.execute(
                    f'''
                    INSERT INTO "StoryEntry"
                        ("id", "userId", "title", "situation", "task", "action",
                         "result", "metrics", "tags", "contentHash",
                         "achievementKey", "updatedAt")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    RETURNING {_COLUMNS}
                    ''',
                    (
                        new_id(),
                        user_id,
                        story["title"],
                        story["situation"],
                        story["task"],
                        story["action"],
                        story["result"],
                        json.dumps(story.get("metrics") or {}),
                        story.get("tags") or [],
                        content_hash,
                        achievement_key,
                    ),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0], False

    def _merge_into(
        self,
        cur: Any,
        user_id: str,
        match: dict[str, Any],
        story: dict[str, Any],
        achievement_key: str | None,
        *,
        replace_evidence: bool,
    ) -> list[dict[str, Any]]:
        """Overwrite ``match`` with ``story``'s (fresher) wording, in place.

        Shared by both merge layers — the achievement-key lookup and the
        paraphrase fallback — so the two can never drift into behaving
        differently. Metrics and tags are UNIONed, never replaced: a merge is
        the point at which evidence would silently disappear otherwise, and
        losing an evidenced metric is exactly the outcome the Story Bank
        exists to prevent.

        ``achievementKey`` is written through with COALESCE semantics: a story
        arriving WITH a key stamps the surviving row (so a previously
        unkeyed row acquires its identity the first time the grounded
        extractor sees it), while a story arriving WITHOUT one — a hand
        edit through ``POST /stories`` — never erases a key the row already
        carries.
        """
        existing_metrics = match.get("metrics") or {}
        incoming_metrics = story.get("metrics") or {}
        if replace_evidence:
            # An achievement-key merge is the SAME résumé bullet re-extracted,
            # so the incoming metrics are a COMPLETE restatement of that
            # bullet's evidence — unioning them instead accumulated one
            # rewording per run. Observed live after six extractor runs: a
            # single story carrying 19 metric keys for 4 distinct facts
            # ("Reduction"/"Effort reduction"/"effort_reduction"/"Reduction in
            # effort" all = 92%). Tags go the same way and for a sharper
            # reason: unioning them kept a WRONG organisation tag written by an
            # earlier run (the independent JIRA-dashboard story still carried
            # "Australian Taxation Office (ATO)" from a superseded extraction).
            # Control flags (``__starred``) are NOT evidence and survive.
            merged_metrics = {
                **{k: v for k, v in existing_metrics.items() if str(k).startswith("__")},
                **incoming_metrics,
            }
            merged_tags = list(dict.fromkeys(story.get("tags") or []))
        else:
            merged_metrics = {**existing_metrics, **incoming_metrics}
            merged_tags = list(
                dict.fromkeys([*(match.get("tags") or []), *(story.get("tags") or [])])
            )
        merged_hash = compute_story_content_hash(
            user_id, *(story[f] for f in _STAR_FIELDS)
        )
        cur.execute(
            f'''
            UPDATE "StoryEntry" SET
                "title" = %s, "situation" = %s, "task" = %s,
                "action" = %s, "result" = %s, "metrics" = %s,
                "tags" = %s, "contentHash" = %s,
                "achievementKey" = COALESCE(%s, "achievementKey"),
                "updatedAt" = NOW()
            WHERE "id" = %s
            RETURNING {_COLUMNS}
            ''',
            (
                story["title"], story["situation"], story["task"],
                story["action"], story["result"],
                json.dumps(merged_metrics), merged_tags, merged_hash,
                achievement_key, match["id"],
            ),
        )
        return rows_to_dicts(cur)

    def live_achievement_keys(self, user_id: str) -> dict[str, Any]:
        """``{achievementKey: updatedAt}`` for every LIVE story of ``user_id``.

        The extractor reads this to order its work: résumé bullets with NO
        story yet go first (a budget-limited run should add coverage, not
        re-derive the same opening bullets), then the already-covered ones
        OLDEST-REFRESHED first, so successive runs rotate through the whole
        bank instead of re-writing the same few rows every time.

        Deliberately NOT exposed through ``list_by_user``: the key is an
        internal identity token like ``contentHash`` and must never reach a
        client (see the module docstring on ``_COLUMNS``).
        """
        ensure_story_archive_columns()
        ensure_story_achievement_column()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "achievementKey", "updatedAt" FROM "StoryEntry" '
                    'WHERE "userId" = %s AND "archivedAt" IS NULL '
                    'AND "achievementKey" IS NOT NULL',
                    (user_id,),
                )
                return {row[0]: row[1] for row in cur.fetchall()}

    def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        """Every LIVE story for ``user_id``, newest first.

        Archived rows (merged away by the bulk de-dup sweep) are excluded —
        this is the single choke point every Story Bank consumer reads
        through, so the exclusion applies to the Story Bank screen, the
        tailoring pipeline's evidence selection, story-relevance scoring,
        cover-letter evidence, interview prep and the story extractor at
        once. See the module docstring.
        """
        ensure_story_archive_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "StoryEntry" '
                    'WHERE "userId" = %s AND "archivedAt" IS NULL '
                    'ORDER BY "createdAt" DESC',
                    (user_id,),
                )
                return rows_to_dicts(cur)

    def get_by_id(self, story_id: str, user_id: str) -> dict[str, Any] | None:
        """One row by explicit id, ARCHIVED ROWS INCLUDED (deliberately).

        This is the by-id inspection/restore surface: an archived row must
        stay resolvable, otherwise a "recoverable" merge is not recoverable
        and there is no way to prove the loser's content still exists. It is
        still scoped to ``user_id``. Listing paths must use ``list_by_user``,
        which excludes archived rows.
        """
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "StoryEntry" '
                    'WHERE "id" = %s AND "userId" = %s',
                    (story_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def _get_live_by_id(self, story_id: str, user_id: str) -> dict[str, Any] | None:
        """One LIVE row by id — an archived row resolves to ``None``.

        The write-path counterpart of ``get_by_id``. ``update`` reads through
        this (never ``get_by_id``) so that neither the no-op-update early
        return nor the content-hash recomputation can pull archived content
        back into a response or into a hash.
        """
        ensure_story_archive_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'SELECT {_COLUMNS} FROM "StoryEntry" '
                    'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL',
                    (story_id, user_id),
                )
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update(self, story_id: str, user_id: str, story: dict[str, Any]) -> dict[str, Any] | None:
        """Update a LIVE story. An ARCHIVED id returns ``None`` (-> HTTP 404).

        GMV4-story-004 round-2 finding 1. An archived row is a merge loser
        held for recovery: it is absent from ``list_by_user`` and therefore
        from every listing, evidence-selection and scoring surface. Allowing a
        PUT against it re-published archived content through the response body
        (``routers/stories.py::update_story`` echoes the updated row via
        ``_enrich``) and silently mutated the very content ``restore_merged_
        stories`` would hand back, so a later restore would return text the
        user never merged.

        404 is the deliberate answer rather than 409/410: the row is not
        observable through any client-reachable surface, so "not found" is
        exactly what the client can verify, and it discloses nothing about
        another row having absorbed this one. The one legitimate operation on
        an archived row — restore — is intentionally NOT reachable from
        ordinary CRUD; it lives behind the audited, plan-gated sweep
        entrypoint (``scripts/story_dedup_sweep.py --restore``).
        """
        # The column is written below whenever a STAR field moves, so the lazy
        # DDL MUST be ensured here too — not only in ``create``. Skipping it was
        # WIP-BRANCH-AUDIT-2026-07-29 blocker #2: the first PUT on a schema that
        # had never run the DDL raised UndefinedColumn -> HTTP 500.
        ensure_story_dedup_column()
        ensure_story_archive_columns()
        allowed = ("title", "situation", "task", "action", "result", "metrics", "tags")
        sets, params = [], []
        changed: set[str] = set()
        for key in allowed:
            if key in story:
                sets.append(f'"{key}" = %s')
                value = story[key]
                params.append(json.dumps(value) if key == "metrics" else value)
                changed.add(key)
        if not sets:
            return self._get_live_by_id(story_id, user_id)
        # Refresh the content identity ONLY when a STAR field actually moved —
        # a tags/metrics-only edit is decoration and must leave the identity
        # (and therefore future dedup behaviour) untouched.
        if changed & set(_STAR_FIELDS):
            current = self._get_live_by_id(story_id, user_id)
            if current is None:
                return None
            sets.append('"contentHash" = %s')
            params.append(
                compute_story_content_hash(
                    user_id,
                    *(story.get(f, current[f]) for f in _STAR_FIELDS),
                )
            )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f'''
                    UPDATE "StoryEntry" SET {", ".join(sets)}, "updatedAt" = NOW()
                    WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL
                    RETURNING {_COLUMNS}
                    ''',
                    (*params, story_id, user_id),
                )
                rows = rows_to_dicts(cur)
            conn.commit()
        return rows[0] if rows else None

    def delete(self, story_id: str, user_id: str) -> bool:
        """Delete a LIVE story. An ARCHIVED id returns ``False`` (-> HTTP 404).

        GMV4-story-004 round-2 finding 1, and the sharper half of it: this
        DELETE is physical, so without the ``archivedAt IS NULL`` guard the
        owning user could destroy their own recoverable merge loser with one
        ordinary request — the exact unrecoverable-data outcome the archive
        was built to prevent, reachable through the plain CRUD surface that
        none of the sweep's five gates protect.

        NO purge path is exposed in its place. A user-facing hard-purge would
        re-open that hazard for no product requirement; nothing in the app
        needs archived rows physically gone, and PostgreSQL storage for a
        bounded number of merge losers is not a pressure. If a purge is ever
        genuinely required it belongs beside ``restore`` in the audited sweep
        entrypoint, with its own reviewed-plan gate — not on this method.
        """
        ensure_story_archive_columns()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM "StoryEntry" '
                    'WHERE "id" = %s AND "userId" = %s AND "archivedAt" IS NULL',
                    (story_id, user_id),
                )
                deleted = cur.rowcount
            conn.commit()
        return deleted > 0
