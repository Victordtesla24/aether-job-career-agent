"""BLOCKER-001 / GOLD-MASTER-V2 §0.5 — the degraded-admin-credential diagnostic
must never write the plaintext password (or any denylist entry) to the process
log, on every boot.

Context. ``_audit_admin_credential`` (``app/repositories/admin.py``) names the
MATCHED ``_KNOWN_WEAK_ADMIN_PASSWORDS`` entry in its CRITICAL diagnostic so an
operator knows which default they left in place. That message is written by
``_record_admin_credential_state`` to ``logger.critical(...)`` AND ``stderr``
on EVERY API boot while the credential stays unrotated
(``/var/log/aether/api.log`` in production). On a degraded deploy the matched
entry IS the live password, so this writes a COMPLETE, WORKING credential pair
(operator email + plaintext password) to disk on every restart. Today that
value happens to be the already-public ``admin123``, but the moment the
operator rotates to a real, strong, unique password this same code path would
log the NEW secret in plaintext forever after — a latent leak of a real secret
introduced by a security fix.

§0.5 forbids secrets being "printed, logged, committed, or echoed" — full
stop, not "unless the value happens to already be public". This module pins
that the diagnostic never contains the plaintext value, regardless of what it
is, while still being actionable (names the env var + the nature of the
problem).

Quoted-value detection convention matches the existing pinned test
``tests/test_blocker001_restart_safety.py::
test_degraded_state_is_surfaced_on_admin_health_without_leaking_secrets``,
which uses the same ``f"'{weak}'"`` / ``f'"{weak}"'`` check for exactly this
reason: several denylist entries (``"admin"``, ``"password"``, ``"secret"``,
``"aether"``) are also ordinary English words that legitimately appear inside
safe vocabulary the diagnostic must keep using (``AETHER_ADMIN_PASSWORD_HASH``,
"a strong, unique password", "restart aether-api") — a bare substring check
would false-positive on those and hide the actual regression this test exists
to catch: the CREDENTIAL-SHAPED, quoted occurrence  (``'admin123'``) that
``_audit_admin_credential`` used to interpolate via ``f"{weak!r}"``.
"""
from __future__ import annotations

import logging
import uuid

from app.repositories.admin import (
    _KNOWN_WEAK_ADMIN_PASSWORDS,
    _audit_admin_credential,
    _record_admin_credential_state,
    _reset_admin_credential_state_for_tests,
)
from app.security import hash_password


def _assert_no_quoted_denylist_entry(text: str) -> None:
    for weak in _KNOWN_WEAK_ADMIN_PASSWORDS:
        assert f"'{weak}'" not in text, (
            "BLOCKER-001/§0.5 VIOLATION: diagnostic quotes a known-weak "
            f"password value ({weak!r}) — this is the exact shape a live "
            f"plaintext credential would take once rotated. Text: {text!r}"
        )
        assert f'"{weak}"' not in text, (
            "BLOCKER-001/§0.5 VIOLATION: diagnostic double-quotes a "
            f"known-weak password value ({weak!r}). Text: {text!r}"
        )


def test_weak_credential_diagnostic_names_no_denylist_entry():
    """The pure ``_audit_admin_credential`` string must never quote the
    matched (or any) denylist entry — this is the exact text that reaches the
    CRITICAL log banner on every boot."""
    email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    for weak in _KNOWN_WEAK_ADMIN_PASSWORDS:
        problem = _audit_admin_credential(email, hash_password(weak))
        assert problem is not None, f"{weak!r} should have been flagged as weak"
        _assert_no_quoted_denylist_entry(problem)
        # Still actionable: names the exact env var to rotate.
        assert "AETHER_ADMIN_PASSWORD_HASH" in problem
        assert "BLOCKER-001" in problem


def test_degraded_boot_banner_never_writes_plaintext_password_to_the_log(
    monkeypatch, caplog, capsys
):
    """End-to-end through the exact call ``apply_admin_rotation`` makes on
    every boot: ``_record_admin_credential_state`` logs at CRITICAL *and*
    prints to stderr (the channel ``scripts/start-api.sh`` pipes into
    ``/var/log/aether/api.log``). Neither must ever contain the plaintext
    password."""
    email = f"owner-{uuid.uuid4().hex[:8]}@aether.io"
    weak_hash = hash_password("admin123")
    try:
        with caplog.at_level(logging.CRITICAL, logger="app.repositories.admin"):
            problem = _audit_admin_credential(email, weak_hash)
            _record_admin_credential_state(problem)

        logged = "\n".join(r.getMessage() for r in caplog.records)
        printed = capsys.readouterr().err

        for channel_name, text in (("logger.critical", logged), ("stderr", printed)):
            assert "AETHER_ADMIN_PASSWORD_HASH" in text, (
                f"{channel_name} lost the actionable env-var name: {text!r}"
            )
            _assert_no_quoted_denylist_entry(text)
    finally:
        _reset_admin_credential_state_for_tests()
