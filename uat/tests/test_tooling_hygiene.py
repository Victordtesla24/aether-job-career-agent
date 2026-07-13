"""Regression guards for GAP-P4-051 (C-32 / C-34), scoped to git-tracked
uat/*.py tooling (the shipped/canonical scripts) — untracked scratch scripts
under uat/ are scout-stage debris outside this ledger entry's scope.

C-32: shipped uat tooling must never hardcode the demo password in plaintext;
it must read LOGIN_EMAIL/LOGIN_PASSWORD from the repo .env, like
uat/api_sweep.py's load_env().

C-34: shipped uat tooling must never navigate a browser directly (GET) to the
POST-only /api/auth/login endpoint — that produces a real 405 the FastAPI
backend correctly returns, which Chromium surfaces as a console error. Sweeps
must authenticate via a REST POST (see api_login() in uat/phase4_sweep.py) and
inject the resulting token, never `page.goto(".../api/auth/login")`.

Note on test_no_browser_navigation_to_login_api_in_tracked_uat_scripts: this
guard is preventive-only. The real C-34 offender that reproduced the 405
(uat/phase4_interact.py) was never git-tracked, so this test has no genuine
"red on main" state to point to — none of main's tracked uat/*.py scripts
navigate a browser to /api/auth/login. It exists to stop that class of bug
from being (re)introduced into shipped tooling going forward, not to prove a
historical regression was fixed.

Run: python3 -m pytest uat/tests -q
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UAT_DIR = REPO_ROOT / "uat"

HARDCODED_PASSWORD_RE = re.compile(r"""AetherDemo1""")
GOTO_LOGIN_API_RE = re.compile(
    r"""goto\(\s*f?["'][^"']*\{?[A-Za-z_]*\}?/api/auth/login["']"""
)


SELF_PATH = Path(__file__).resolve()


def _tracked_uat_scripts() -> list[Path]:
    """Git-tracked uat/*.py files — the shipped, canonical tooling.

    Excludes this guard test's own file: its source necessarily *contains*
    both search literals (the plaintext password regex source, and the
    docstring's `page.goto(".../api/auth/login")` example) as data, which
    would otherwise make the test flag itself as an offender the moment it
    is git-added. The guard's job is to police shipped product tooling, not
    itself.
    """
    out = subprocess.run(
        ["git", "ls-files", "uat/*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        REPO_ROOT / line
        for line in out.splitlines()
        if line and (REPO_ROOT / line).resolve() != SELF_PATH
    )


def test_no_hardcoded_demo_password_in_tracked_uat_scripts():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _tracked_uat_scripts()
        if HARDCODED_PASSWORD_RE.search(p.read_text())
    ]
    assert offenders == [], (
        "Tracked uat/*.py tooling must read LOGIN_PASSWORD from the repo .env, "
        f"never hardcode it (matches api_sweep.py's load_env() pattern). Offenders: {offenders}"
    )


def test_no_browser_navigation_to_login_api_in_tracked_uat_scripts():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _tracked_uat_scripts()
        if GOTO_LOGIN_API_RE.search(p.read_text())
    ]
    assert offenders == [], (
        "Navigating a browser page directly to the POST-only /api/auth/login "
        "endpoint (page.goto(...)) issues a GET and produces a real 405 that "
        "Chromium logs as a console error (C-34). Authenticate via a REST POST "
        f"(see api_login() in uat/phase4_sweep.py) instead. Offenders: {offenders}"
    )
