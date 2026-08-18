"""Persistent admin-owned copy, footer and footnote overrides for branded documents.

The renderer owns presentation; this repository owns only the small editable
text surface.  Its table is provisioned lazily and additively because this
project intentionally has no migration runner.
"""
from __future__ import annotations

import re
from typing import Any

from app.db import get_connection, new_id, rows_to_dicts
from app.services.brand_documents import DOCUMENT_KINDS
from app.services.stripe_gateway import app_base_url

_EDITABLE_KIND = "auto_reply"
# Absolute HTTPS endpoint that visibly carries the unsubscribe action. This is
# deliberately stricter than an instruction word: an admin can preserve the
# ratified identity while still providing a working opt-out destination.
_UNSUBSCRIBE_URL = re.compile(
    r"https://[^\s<>\"']+/[^\s<>\"']*unsubscribe[^\s<>\"']*", re.IGNORECASE
)


def _is_editable_kind(kind: str) -> bool:
    return kind == _EDITABLE_KIND


_ADVISORY_LOCK = 7420240730
_ready = False


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK,))
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS "BrandDocumentTemplate" (
                    "id" text PRIMARY KEY,
                    "kind" text NOT NULL UNIQUE,
                    "body" text NOT NULL,
                    "footnote" text NOT NULL,
                    "footer" text NOT NULL,
                    "updatedAt" timestamptz NOT NULL DEFAULT NOW()
                )
                '''
            )
        conn.commit()
    _ready = True


def default_template(kind: str) -> dict[str, str]:
    """Safe, non-fabricated editable defaults for a registered kind."""
    if kind not in DOCUMENT_KINDS:
        raise KeyError(kind)
    title = DOCUMENT_KINDS[kind]["title"]
    return {
        "body": f"{title}\n\n{{{{name}}}}",
        "footnote": (
            "Merge fields are filled from the relevant customer or billing record "
            "at issue time."
        ),
        "footer": (
            "Aether Career Job Agent — Operated by Vikram Sarkar\n"
            f"{app_base_url()}/unsubscribe"
        ),
    }


def _valid_footer(footer: str) -> bool:
    normalized = (footer or "").strip()
    return bool(normalized) and "Aether Career Job Agent" in normalized and bool(
        _UNSUBSCRIBE_URL.search(normalized)
    )


class BrandTemplateRepository:
    def __init__(self) -> None:
        _ensure_table()

    def list_templates(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM "BrandDocumentTemplate" ORDER BY "kind"')
                stored = {row["kind"]: row for row in rows_to_dicts(cur)}
        return [
            {**stored[kind], "isDefault": False}
            if kind in stored
            else {"kind": kind, **default_template(kind), "updatedAt": None, "isDefault": True}
            for kind in DOCUMENT_KINDS
        ]

    def get(self, kind: str) -> dict[str, Any]:
        if kind not in DOCUMENT_KINDS:
            raise KeyError(kind)
        for row in self.list_templates():
            if row["kind"] == kind:
                return {key: value for key, value in row.items() if key != "isDefault"}
        raise AssertionError("registered kind was not listed")

    def get_stored(self, kind: str) -> dict[str, Any] | None:
        if kind not in DOCUMENT_KINDS:
            raise KeyError(kind)
        if not _is_editable_kind(kind):
            return None
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT * FROM "BrandDocumentTemplate" WHERE "kind"=%s', (kind,))
                rows = rows_to_dicts(cur)
        return rows[0] if rows else None

    def update(
        self, kind: str, *, body: str, footnote: str, footer: str, cur: Any
    ) -> dict[str, Any]:
        if kind not in DOCUMENT_KINDS:
            raise KeyError(kind)
        if not _is_editable_kind(kind):
            raise ValueError(
                "Only auto_reply supports persistent body, footnote, and footer "
                "overrides."
            )
        if not body.strip() or not footnote.strip():
            raise ValueError("body and footnote must not be empty")
        if not _valid_footer(footer):
            raise ValueError(
                "footer must retain exact Aether Career Job Agent identity and an "
                "absolute HTTPS unsubscribe URL"
            )
        cur.execute(
            '''
            INSERT INTO "BrandDocumentTemplate" ("id","kind","body","footnote","footer")
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT ("kind") DO UPDATE SET
              "body"=EXCLUDED."body", "footnote"=EXCLUDED."footnote",
              "footer"=EXCLUDED."footer", "updatedAt"=NOW()
            RETURNING *
            ''',
            (new_id(), kind, body.strip(), footnote.strip(), footer.strip()),
        )
        return rows_to_dicts(cur)[0]


__all__ = ["BrandTemplateRepository"]
