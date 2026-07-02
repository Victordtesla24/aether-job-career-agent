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

from app.db import get_connection, new_id  # noqa: E402
from app.repositories.user import UserRepository  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@aether.dev"
DEMO_PASSWORD = "AetherDemo1"

FUNNEL = {"jobs_found": 847, "applied": 412, "screened": 156, "interviewed": 23, "offers": 4}

COMPANIES = ["Canva", "Atlassian", "SafetyCulture", "REA Group", "Deputy", "Culture Amp",
             "Airwallex", "Linktree", "Immutable", "Octopus Deploy"]
TITLES = ["Senior Software Engineer", "Staff Engineer", "ML Engineer", "Platform Engineer",
          "Backend Engineer", "Full Stack Developer", "DevOps Engineer", "Data Engineer"]


def main() -> None:
    random.seed(42)
    users = UserRepository()
    user = users.get_by_email(DEMO_EMAIL)
    if user is None:
        user = users.create(DEMO_EMAIL, hash_password(DEMO_PASSWORD))
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
