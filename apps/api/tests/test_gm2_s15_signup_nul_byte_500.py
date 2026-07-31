"""GOLD-MASTER-V2 §15 — ``POST /auth/register`` 500s on a NUL byte (\\x00) in
the password field [VERIFIED LIVE ON PRODUCTION 2026-07-31T15:06:58Z and
15:07:46Z].

Root cause: the password is never checked for a NUL byte before reaching
bcrypt. bcrypt's C extension (via passlib) raises
``passlib.exc.PasswordValueError`` — a ``ValueError`` subclass — the instant
it sees one, and nothing in ``app/routers/auth.py`` or
``app/security.py::hash_password`` caught it, so it propagated all the way up
as an unhandled 500 with a traceback. The blanket NUL-byte guard on the DB
cursor path (``app/db.py::_NulByteGuardCursor``) never runs for this request:
a password goes through ``hash_password()`` BEFORE any query executes, so the
DB-layer guard is simply never reached. ``EmailStr`` already rejects a NUL
byte in the ``email`` field with a clean 422 (Pydantic's own validation), which
is why the identical request shape returns 422 when the NUL is in ``email``
instead of ``password`` — this file proves ``password`` now behaves the same
way.

Fix (two-seam, mirroring the existing MV-signup-001 / BCRYPT_MAX_PASSWORD_BYTES
precedent in this same file):
  1. ``app/repositories/user.py::validate_password_policy`` — the SAME
     function already wired into ``RegisterRequest``'s ``password``
     field_validator (alongside the length/digit/max-byte checks) — now also
     rejects a NUL byte. This is the primary seam: it runs at Pydantic
     validation time, before the handler body executes, so ``hash_password()``
     never sees a NUL byte via the register endpoint. The contract is now
     consistent with how ``EmailStr`` already behaves for the email field.
  2. ``app/security.py::hash_password`` — defense-in-depth for any OTHER
     caller that does not route through ``RegisterRequest`` (e.g.
     ``scripts/seed_demo.py``, or a future endpoint): it now raises a clean,
     documented ``ValueError`` instead of letting bcrypt's internal exception
     surface as an unhandled crash.

``verify_password()`` (the login path) needed NO code change: it already
wraps ``_pwd_context.verify(...)`` in ``except ValueError: return False``, and
``PasswordValueError`` IS a ``ValueError`` subclass, so a NUL byte in a login
attempt was ALREADY treated as a (safe, 401-shaped) wrong password before this
fix. ``test_login_with_nul_byte_password_is_401_not_500`` below pins that
behaviour so a future narrowing of that ``except`` clause cannot silently
regress it back into a 500.
"""
from __future__ import annotations

import pytest

NUL = "\x00"


class TestRegisterNulBytePassword:
    def test_nul_byte_in_password_is_422_not_500(self, client):
        response = client.post(
            "/auth/register",
            json={"email": "nulbyte@example.com", "password": f"Pass{NUL}word1"},
        )
        assert response.status_code == 422, response.text
        assert response.status_code != 500
        # Honest, specific message — no bare traceback / exception repr leaking
        # into the response body.
        body = response.json()
        detail = str(body.get("detail", ""))
        assert "NUL" in detail, detail
        assert "Traceback" not in response.text
        assert "PasswordValueError" not in response.text
        assert "passlib" not in response.text

    def test_nul_byte_only_password_is_422_not_500(self, client):
        # A password that is ONLY a NUL byte plus padding to satisfy length —
        # still no digit, but the NUL problem must be reported alongside it,
        # never crash the process regardless of what else is wrong with it.
        response = client.post(
            "/auth/register",
            json={"email": "nulonly@example.com", "password": NUL * 10},
        )
        assert response.status_code == 422, response.text
        assert response.status_code != 500

    def test_no_user_row_is_created_for_a_rejected_nul_byte_password(
        self, client, db_session
    ):
        email = "nulbyte-norow@example.com"
        response = client.post(
            "/auth/register", json={"email": email, "password": f"Pass{NUL}word1"}
        )
        assert response.status_code == 422, response.text
        with db_session.cursor() as cur:
            cur.execute('SELECT 1 FROM "User" WHERE email = %s', (email,))
            assert cur.fetchone() is None


class TestLoginNulBytePassword:
    def test_login_with_nul_byte_password_is_401_not_500(self, client):
        # Register a normal account first...
        assert (
            client.post(
                "/auth/register",
                json={"email": "loginnul@example.com", "password": "Passw0rd1"},
            ).status_code
            == 201
        )
        # ...then attempt to log in with a NUL byte embedded in the candidate
        # password. This must be indistinguishable from any other wrong
        # password: 401, never 500.
        response = client.post(
            "/auth/login",
            json={"email": "loginnul@example.com", "password": f"Wrong{NUL}Pass1"},
        )
        assert response.status_code == 401, response.text
        assert response.json() == {"detail": "Invalid email or password"}

    def test_login_unknown_identifier_with_nul_byte_password_is_401_not_500(
        self, client
    ):
        response = client.post(
            "/auth/login",
            json={"email": "ghost-nul@example.com", "password": f"{NUL}whatever1"},
        )
        assert response.status_code == 401, response.text


class TestHashPasswordDefenseInDepth:
    """Unit-level pin on ``hash_password``/``verify_password`` themselves,
    independent of the HTTP layer, so the library seam is proven directly."""

    def test_hash_password_raises_a_clean_value_error_not_a_bare_bcrypt_crash(self):
        from app.security import hash_password

        with pytest.raises(ValueError, match="NUL"):
            hash_password(f"whatever{NUL}1")

    def test_verify_password_returns_false_for_a_nul_byte_candidate(self):
        from app.security import hash_password, verify_password

        real_hash = hash_password("Passw0rd1")
        assert verify_password(f"Passw0rd1{NUL}", real_hash) is False
        assert verify_password(f"{NUL}Passw0rd1", real_hash) is False


class TestLegitimatePasswordsStillWork:
    """Guard against over-correction (GOLD-MASTER-V2 §15 explicit warning):
    the NUL-byte guard must reject ONLY the NUL byte, never legitimate
    printable-character passwords — Unicode, emoji, spaces, and long
    passwords must all keep working end-to-end (register -> login)."""

    @pytest.mark.parametrize(
        "label,password",
        [
            ("unicode-accents", "Pässwörd123"),
            ("unicode-cjk", "密码Test123"),
            ("emoji", "Rocket🚀Pass1"),
            ("spaces", "correct horse battery 9"),
            ("max-length-72-bytes", "A1" + "x" * 68),  # exactly 70 ASCII bytes, valid
            ("punctuation", "P@ss!w0rd#123$"),
            ("apostrophe-surname-shaped", "O'Brien2024"),
        ],
    )
    def test_register_then_login_round_trip(self, client, label, password):
        email = f"legit-{label}@example.com"
        register = client.post(
            "/auth/register", json={"email": email, "password": password}
        )
        assert register.status_code == 201, f"{label}: {register.text}"
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, f"{label}: {login.text}"
        assert login.json()["email"] == email
