"""Atomic writer for the operator-facing ``CLAUDE_CODE_OAUTH_TOKEN`` env var
(GAP-P7-DEF-A §3.3).

When a Claude Code OAuth token (``sk-ant-oat01-…``) is stored as an
``oauth_token`` credential, the server transparently syncs it into the
repo-root ``.env`` as ``CLAUDE_CODE_OAUTH_TOKEN=<token>`` so the async worker
and a process restart can source it. The encrypted DB row is the immediate live
source (no restart needed); the ``.env`` write is for restart-survival and the
worker (see blueprint §9). The write is atomic (temp file → ``fchmod 600`` →
``os.replace`` in the same directory) and the token is NEVER logged, echoed, or
returned.

Path resolution: ``AETHER_ENV_FILE_PATH`` when set, else the repo-root ``.env``
computed from this file's location (portable; resolves to the production repo
path in prod). ``.env`` is gitignored, so the secret never enters git.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_OAUTH_TOKEN_ENV_KEY = "CLAUDE_CODE_OAUTH_TOKEN"


def get_env_file_path() -> Path:
    """The env file to sync into: ``AETHER_ENV_FILE_PATH`` or the repo-root ``.env``."""
    override = os.environ.get("AETHER_ENV_FILE_PATH")
    if override:
        return Path(override)
    # apps/api/app/services/env_file_writer.py → parents[4] == repo root.
    return Path(__file__).resolve().parents[4] / ".env"


def write_oauth_token_env(token: str) -> None:
    """Atomically upsert ``CLAUDE_CODE_OAUTH_TOKEN=<token>`` into the env file.

    Replaces an existing line or appends one; collapses any duplicates to a
    single line. Raises on I/O failure (the caller decides whether to degrade).
    The token value is never logged.
    """
    path = get_env_file_path()
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    existing: list[str] = []
    if path.exists():
        existing = path.read_text().splitlines()

    new_line = f"{_OAUTH_TOKEN_ENV_KEY}={token}"
    out: list[str] = []
    replaced = False
    for line in existing:
        if line.startswith(f"{_OAUTH_TOKEN_ENV_KEY}="):
            if not replaced:
                out.append(new_line)
                replaced = True
            # else: drop the duplicate token line
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)
    content = "\n".join(out) + "\n"

    # Temp file in the SAME directory so os.replace is an atomic same-fs rename;
    # chmod 600 BEFORE the rename so the final file is never briefly world-readable.
    fd, tmp = tempfile.mkstemp(dir=str(directory))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync_oauth_token_env(token: str) -> bool:
    """Best-effort :func:`write_oauth_token_env`.

    Returns ``True`` on success. On failure logs a NON-secret warning (exception
    type only) and returns ``False`` — the encrypted DB row is the source of
    truth, so a ``.env`` sync failure must not fail the credential save.
    """
    try:
        write_oauth_token_env(token)
        return True
    except Exception as exc:  # noqa: BLE001 — DB row is the source of truth
        logger.warning(
            "CLAUDE_CODE_OAUTH_TOKEN .env sync failed (%s); the encrypted DB "
            "row remains the live source.", type(exc).__name__,
        )
        return False
