"""Credential vault — Fernet symmetric encryption for provider secrets (ADR-PC-3).

Provider API keys / OAuth tokens are encrypted at rest with a single
deployment-wide key read from the ``AETHER_CREDENTIAL_KEY`` environment
variable (a urlsafe-base64 32-byte Fernet key, generated once at deploy and
appended to the server ``.env``).

Honesty contract (ADR-PC-3):
- If the key is MISSING, ``encrypt``/``decrypt`` raise :class:`CredentialVaultError`
  (a ``RuntimeError``) with an explicit message. The caller surfaces this as an
  honest 503 — a credential is NEVER stored or served in the clear as a
  "fake success" path.
- Reads that only need the masked hint (never the plaintext) can call
  :func:`key_present` first and degrade gracefully when the key is absent.

Nothing here ever logs or returns more than the last four characters of a
secret (:func:`secret_hint`).
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

#: Env var holding the deployment-wide Fernet key.
KEY_ENV = "AETHER_CREDENTIAL_KEY"

#: Single ellipsis character prefixed to every masked hint (e.g. ``…4Qz``).
_ELLIPSIS = "…"


class CredentialVaultError(RuntimeError):
    """Raised when encryption/decryption cannot be performed honestly.

    A ``RuntimeError`` subclass so existing ``except RuntimeError`` guards keep
    treating a missing/invalid key as an outage rather than a success.
    """


def key_present() -> bool:
    """True when a non-empty ``AETHER_CREDENTIAL_KEY`` is configured."""
    return bool(os.environ.get(KEY_ENV))


def _fernet() -> Fernet:
    raw = os.environ.get(KEY_ENV)
    if not raw:
        raise CredentialVaultError(
            f"{KEY_ENV} is not configured — credential encryption is unavailable. "
            "Generate a key with credential_vault.generate_key() and set it in the "
            "server environment before storing provider credentials."
        )
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except (ValueError, TypeError) as exc:
        raise CredentialVaultError(
            f"{KEY_ENV} is not a valid urlsafe-base64 32-byte Fernet key."
        ) from exc


def generate_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key (used at deploy / in tests)."""
    return Fernet.generate_key().decode()


def encrypt(secret: str) -> str:
    """Encrypt ``secret`` -> ciphertext token. Raises if the key is missing."""
    if not isinstance(secret, str) or not secret:
        raise CredentialVaultError("Refusing to encrypt an empty secret.")
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored token back to the plaintext secret.

    Raises :class:`CredentialVaultError` when the key is missing or does not
    match the token (e.g. the key was rotated) — never returns garbage.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise CredentialVaultError(
            f"Stored credential could not be decrypted with the current {KEY_ENV} "
            "(wrong or rotated key)."
        ) from exc


def secret_hint(secret: str) -> str:
    """Masked hint: an ellipsis followed by at most the last 4 chars.

    e.g. ``secret_hint('sk-ant-api-...4Qz') == '…4Qz'``. Never exposes more.
    """
    tail = secret[-4:] if secret else ""
    return f"{_ELLIPSIS}{tail}"
