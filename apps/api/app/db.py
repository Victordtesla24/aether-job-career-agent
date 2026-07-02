"""Raw psycopg2 access to the Prisma-managed PostgreSQL database (P2-S01).

The schema itself is owned by Prisma (``packages/db/src/schema.prisma``); the
API reads/writes it with plain SQL. Prisma-style URLs carry a ``?schema=``
query parameter that psycopg2 does not understand, so it is translated into a
``search_path`` option here.

The hosted PostgreSQL caps concurrent connections at 25 and kills idle
transactions, so connections are short-lived: open, use, close.
"""
from __future__ import annotations

import os
import secrets
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extras


def _translate_prisma_url(url: str) -> tuple[str, str | None]:
    """Strip Prisma's ``schema`` query param; return (dsn, schema)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    schema_values = params.pop("schema", None)
    schema = schema_values[0] if schema_values else None
    query = urlencode({k: v[0] for k, v in params.items()})
    dsn = urlunparse(parsed._replace(query=query))
    return dsn, schema


def get_database_url() -> str:
    """Resolve the database URL from the environment (test-swappable)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a short-lived psycopg2 connection with the right search_path."""
    dsn, schema = _translate_prisma_url(get_database_url())
    options = f"-csearch_path={schema}" if schema else None
    conn = psycopg2.connect(dsn, options=options)
    try:
        yield conn
    finally:
        conn.close()


def new_id() -> str:
    """Generate a cuid-shaped identifier compatible with Prisma's ids."""
    return "c" + secrets.token_hex(12)


def rows_to_dicts(cursor: Any) -> list[dict[str, Any]]:
    """Materialize all rows of a cursor as column-name dicts."""
    columns = [col.name for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
