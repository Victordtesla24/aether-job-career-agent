"""User repository — raw SQL over the Prisma-migrated schema (P2-S01).

Per DECISIONS D-0013 the Python layer owns no ORM models; it reads and writes
the ``User`` table produced by Prisma directly. Ids are generated with the same
``cuid`` scheme Prisma uses (``@default(cuid())`` is applied client-side, not by
the database), and ``updatedAt`` is set explicitly since ``@updatedAt`` is also
a client-side concern.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from cuid import cuid
from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import RealDictCursor


@dataclass(frozen=True)
class User:
    """A user row. ``password_hash`` mirrors the ``passwordHash`` column."""

    id: str
    email: str
    name: Optional[str]
    password_hash: Optional[str]
    created_at: datetime
    updated_at: datetime


def _row_to_user(row: dict) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        password_hash=row["passwordHash"],
        created_at=row["createdAt"],
        updated_at=row["updatedAt"],
    )


class UserRepository:
    """Data-access for user identity, backing register/login."""

    def __init__(self, conn: PgConnection):
        self._conn = conn

    def create(
        self, email: str, password_hash: str, name: Optional[str] = None
    ) -> User:
        """Insert a new user and return it. Commits on success."""
        now = datetime.now(timezone.utc)
        user_id = cuid()
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO "User" ("id", "email", "name", "passwordHash",
                                    "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING "id", "email", "name", "passwordHash",
                          "createdAt", "updatedAt";
                """,
                (user_id, email, name, password_hash, now, now),
            )
            row = cur.fetchone()
        self._conn.commit()
        return _row_to_user(row)

    def get_by_email(self, email: str) -> Optional[User]:
        """Return the user with this email, or ``None``."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT "id", "email", "name", "passwordHash",
                       "createdAt", "updatedAt"
                FROM "User" WHERE "email" = %s;
                """,
                (email,),
            )
            row = cur.fetchone()
        return _row_to_user(row) if row else None

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Return the user with this id, or ``None``."""
        with self._conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT "id", "email", "name", "passwordHash",
                       "createdAt", "updatedAt"
                FROM "User" WHERE "id" = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
        return _row_to_user(row) if row else None
