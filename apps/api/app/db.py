"""Database access for the Aether API (P2-S01).

Per DECISIONS D-0013, Postgres — migrated by Prisma from
``packages/db/src/schema.prisma`` — is the single source of truth. The Python
services talk to it directly with ``psycopg2`` (no parallel ORM models), so the
runtime schema is always exactly what the migrations produced.

``get_db`` is a FastAPI dependency yielding a short-lived connection per
request. Tests override it (see ``tests/conftest.py``) to bind to the
``aether_test`` database.
"""
from __future__ import annotations

from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as PgConnection

from app.config import get_settings


def get_connection() -> PgConnection:
    """Open a new psycopg2 connection using the configured ``DATABASE_URL``."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured; cannot open a database connection"
        )
    return psycopg2.connect(settings.database_url)


def get_db() -> Iterator[PgConnection]:
    """FastAPI dependency: yield a connection and always close it afterwards."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
