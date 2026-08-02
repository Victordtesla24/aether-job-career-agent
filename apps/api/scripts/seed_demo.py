"""Provision the platform-owner ``admin`` account.

Usage: cd apps/api && python scripts/seed_demo.py

W-CLEAN (2026-08-02) — REMOVED: the demo-funnel generator
-----------------------------------------------------------
This module used to carry a ``main()`` that "seeded the canonical demo funnel
847 → 412 → 156 → 23 → 4". What it actually did, against whichever database the
repo-root ``.env`` names — i.e. **production**, because ``main()`` loaded that
``.env`` itself:

    DELETE FROM "Application" WHERE "userId" = <the production owner>
    DELETE FROM "Job"         WHERE "userId" = <the production owner>

...followed by INSERTing 847 fabricated ``Job`` rows ("Demo-seeded job posting
for the analytics funnel.", ``https://demo.aether.dev/jobs/N``, random
companies/titles/ATS scores) and 412 fabricated ``Application`` rows with
invented statuses (4 offer / 19 interview / 133 screening / 256 submitted), plus
a "Demo seed resume" with empty sections. Its ``DEMO_EMAIL`` constant was the
production owner's real address.

So a single ``python scripts/seed_demo.py`` would have destroyed the owner's
real applications and job pipeline and replaced the dashboard, the funnel and
every analytics number with fabricated data — the precise failure mode
``scripts/run-tests.sh`` exists to prevent for the test suite. Nothing in the
app, the deploy path or the test suite ever called it; only
``seed_admin_user``/``ADMIN_EMAIL`` are imported (by ``tests/test_auth.py`` and
``tests/test_gap_p6_admin.py``). It was pure standing hazard and is deleted.

``tests/test_wclean_fixture_marker_audit.py::
test_seed_demo_has_no_fabricated_funnel_generator`` keeps it deleted.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import re

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(.*))$")


def _load_root_env_into_environ() -> None:
    """Load the repo-root ``.env`` into ``os.environ`` so ``DATABASE_URL`` (and
    the admin/demo password vars) are available when this module is run as a
    STANDALONE script (``python scripts/seed_demo.py``).

    IMPORTANT — this MUST NOT run at import time. This module exports
    ``seed_admin_user`` / ``ADMIN_EMAIL``, which the test-suite imports inside
    test functions (``tests/test_gap_p6_admin.py``, ``tests/test_auth.py``). If
    the ``.env`` were slurped into ``os.environ`` as an import side-effect, keys
    the test harness deliberately leaves UNSET — notably ``AETHER_ADMIN_EMAIL``
    / ``AETHER_ADMIN_PASSWORD_HASH`` — would leak in for the rest of the pytest
    PROCESS. Every later app construction's §14.7 ``apply_admin_rotation()``
    would then seed a phantom owner admin AFTER the per-test truncation,
    breaking downstream isolation (a stray extra ``User`` row and Jobs owned by
    it). So the load is confined to the standalone entrypoint below; importing
    the module has no environment side-effects. Only keys not already present
    are set, so an explicit env/CI value always wins.
    """
    root_env = Path(__file__).resolve().parents[3] / ".env"
    if not root_env.exists():
        return
    for line in root_env.read_text().splitlines():
        m = _ENV_LINE.match(line.strip())
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = next(g for g in m.groups()[1:] if g is not None)


from app.db import ensure_user_profile_columns, get_connection, new_id  # noqa: E402
from app.repositories.admin import _weak_password_matching  # noqa: E402
from app.security import hash_password  # noqa: E402

# Admin account seeded for the platform owner (login-by-username feature).
ADMIN_USERNAME = "admin"
ADMIN_EMAIL = "admin@aether.local"
#: An operations identity, deliberately NOT a person's name. Since W-CLEAN it is
#: also a refused signer: ``cover_letter_agent._looks_like_placeholder_name``
#: treats a bare "administrator"/"admin" token as a placeholder identity, so this
#: account cannot generate a candidate-facing cover letter at all. That is the
#: intended behaviour — 7 production letters were signed with this exact string
#: before the guard knew about it.
ADMIN_NAME = "Administrator"


def _admin_password() -> str:
    """Resolve the admin seed password from ``ADMIN_PASSWORD`` — no default.

    BLOCKER-001: this function used to fall back to a hardcoded weak literal
    when ``ADMIN_PASSWORD`` was unset. Every environment seeded by this script
    therefore shipped with the same publicly-known admin password, which is how
    production came to be reachable as ``admin`` + a guessable string. There is
    no safe default for a credential, so there is no default: an unset (or
    known-weak) ``ADMIN_PASSWORD`` aborts the seed instead of silently
    provisioning a guessable account.

    Mirrors ``_demo_password`` below, which already refused to hardcode one.
    """
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not password:
        raise SystemExit(
            "ADMIN_PASSWORD must be set (as an env var, or in the repo-root "
            ".env) to seed the admin user's password. Refusing to fall back to "
            "a hardcoded default credential (BLOCKER-001)."
        )
    if _weak_password_matching(hash_password(password)) is not None:
        raise SystemExit(
            "ADMIN_PASSWORD is on the known-weak denylist "
            "(app.repositories.admin._KNOWN_WEAK_ADMIN_PASSWORDS). Refusing to "
            "seed an admin account with a guessable password (BLOCKER-001). "
            "Choose a strong, unique password."
        )
    return password


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


def main() -> None:
    """Standalone entrypoint: provision the ``admin`` account, nothing else.

    Pulls ``DATABASE_URL`` / ``ADMIN_PASSWORD`` from the repo-root ``.env``
    (never at import time — see ``_load_root_env_into_environ``'s docstring).
    """
    _load_root_env_into_environ()
    seed_admin_user()


if __name__ == "__main__":
    main()
