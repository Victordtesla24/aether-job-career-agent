"""Seed the canonical demo funnel: 847 → 412 → 156 → 23 → 4 (P2-S10).

Creates (or reuses) a demo user and populates Jobs + Applications so the
dashboard funnel matches the approved wireframe numbers. Idempotent: existing
demo rows are wiped and re-seeded on every run.

Usage: cd apps/api && python scripts/seed_demo.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load the repo root .env so DATABASE_URL is available when run standalone.
import os
import re

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(.*))$")
_root_env = Path(__file__).resolve().parents[3] / ".env"
if _root_env.exists():
    for line in _root_env.read_text().splitlines():
        m = _ENV_LINE.match(line.strip())
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)

from app.db import ensure_user_profile_columns, get_connection, new_id  # noqa: E402
from app.repositories.user import UserRepository  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "sarkar.vikram@gmail.com"

# Admin account seeded for the platform owner (login-by-username feature).
ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@aether.local"
ADMIN_NAME = "Administrator"


def _admin_password() -> str:
    """Resolve the admin seed password.

    The owner's explicit product decision is a default of ``admin123``; it is
    read from ``ADMIN_PASSWORD`` when set so real deployments can override it,
    and this is the *only* place the default literal appears.
    """
    return os.environ.get("ADMIN_PASSWORD") or "admin123"


def seed_admin_user() -> str:
    """Idempotently upsert the ``admin`` user; return its id.

    Skips creation when an admin already exists (matched by username or email),
    so running the seed twice yields exactly one admin row. The insert also
    guards the email UNIQUE constraint with ``ON CONFLICT DO NOTHING`` to stay
    safe under a concurrent seeder.
    """
    ensure_user_profile_columns()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "id" FROM "User"'
                ' WHERE lower("username") = %s OR "email" = %s',
                (ADMIN_USERNAME, ADMIN_EMAIL),
            )
            existing = cur.fetchone()
            if existing:
                return existing[0]
            admin_id = new_id()
            cur.execute(
                'INSERT INTO "User"'
                ' ("id", "email", "username", "name", "passwordHash", "updatedAt")'
                ' VALUES (%s, %s, %s, %s, %s, NOW())'
                ' ON CONFLICT ("email") DO NOTHING RETURNING "id"',
                (
                    admin_id,
                    ADMIN_EMAIL,
                    ADMIN_USERNAME,
                    ADMIN_NAME,
                    hash_password(_admin_password()),
                ),
            )
            inserted = cur.fetchone()
        conn.commit()
    if inserted:
        print(f"seeded admin user {ADMIN_EMAIL} (username={ADMIN_USERNAME})")
        return inserted[0]
    # A concurrent seeder won the email conflict; return the existing row.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT "id" FROM "User" WHERE "email" = %s', (ADMIN_EMAIL,))
            row = cur.fetchone()
    return row[0] if row else admin_id

FUNNEL = {"jobs_found": 847, "applied": 412, "screened": 156, "interviewed": 23, "offers": 4}

COMPANIES = ["Canva", "Atlassian", "SafetyCulture", "REA Group", "Deputy", "Culture Amp",
             "Airwallex", "Linktree", "Immutable", "Octopus Deploy"]
TITLES = ["Senior Software Engineer", "Staff Engineer", "ML Engineer", "Platform Engineer",
          "Backend Engineer", "Full Stack Developer", "DevOps Engineer", "Data Engineer"]


def _demo_password() -> str:
    """Resolve the demo user's password from the environment (GAP-P4-068).

    Never hardcode a real credential in shipped tooling. Reads
    SEED_DEMO_PASSWORD first (dedicated override), falling back to
    LOGIN_PASSWORD (the same repo .env var the login flow and uat tooling
    already use) so a single `.env` is sufficient for a normal seed run.
    """
    password = os.environ.get("SEED_DEMO_PASSWORD") or os.environ.get("LOGIN_PASSWORD")
    if not password:
        raise SystemExit(
            "SEED_DEMO_PASSWORD or LOGIN_PASSWORD must be set (as an env var, or in the "
            "repo-root .env) to seed the demo user's password. Refusing to hardcode a "
            "default credential."
        )
    return password


def main() -> None:
    random.seed(42)
    # Provision the admin account first (idempotent, independent of the demo
    # funnel below) so a standard seed run always yields a usable admin login.
    seed_admin_user()
    users = UserRepository()
    user = users.get_by_email(DEMO_EMAIL)
    if user is None:
        user = users.create(DEMO_EMAIL, hash_password(_demo_password()))
        print(f"created demo user {DEMO_EMAIL}")
    user_id = user["id"]

    # Application statuses: 4 offer, 19 interview, 133 screening, 256 submitted
    statuses = (["offer"] * 4 + ["interview"] * 19 + ["screening"] * 133 + ["submitted"] * 256)
    assert len(statuses) == FUNNEL["applied"]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "Application" WHERE "userId" = %s', (user_id,))
            cur.execute('DELETE FROM "Job" WHERE "userId" = %s', (user_id,))
            cur.execute(
                'DELETE FROM "Resume" WHERE "userId" = %s AND "label" = %s',
                (user_id, "Demo seed resume"),
            )

            job_rows = []
            for i in range(FUNNEL["jobs_found"]):
                job_rows.append((
                    new_id(), user_id,
                    f"{random.choice(TITLES)}",
                    random.choice(COMPANIES),
                    "Demo-seeded job posting for the analytics funnel.",
                    random.choice(["seek", "linkedin", "indeed"]),
                    f"https://demo.aether.dev/jobs/{i}",
                    round(random.uniform(35, 95), 1),
                    random.randint(0, 85),
                ))
            cur.executemany(
                '''
                INSERT INTO "Job" ("id", "userId", "title", "company", "description",
                    "source", "sourceUrl", "atsScore", "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                        NOW() - make_interval(days => %s), NOW())
                ''',
                job_rows,
            )

            cur.execute(
                '''
                INSERT INTO "Resume"
                    ("id", "userId", "label", "sections", "formatHash", "updatedAt")
                VALUES (%s, %s, %s, '{}', 'demo-seed-hash', NOW()) RETURNING "id"
                ''',
                (new_id(), user_id, "Demo seed resume"),
            )
            resume_id = cur.fetchone()[0]

            app_rows = [
                (new_id(), user_id, job_rows[i][0], resume_id, status_,
                 random.randint(0, 85))
                for i, status_ in enumerate(statuses)
            ]
            cur.executemany(
                '''
                INSERT INTO "Application" ("id", "userId", "jobId", "resumeId", "status",
                    "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s::"ApplicationStatus",
                        NOW() - make_interval(days => %s), NOW())
                ''',
                app_rows,
            )
        conn.commit()

    print(f"seeded funnel for {DEMO_EMAIL}: {FUNNEL}")


if __name__ == "__main__":
    main()
