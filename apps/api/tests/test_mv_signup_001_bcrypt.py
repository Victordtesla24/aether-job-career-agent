"""MV-signup-001 (HIGH, security) — bcrypt 72-byte truncation.

RED first (2026-07-18): before the fix, passlib/bcrypt silently truncates any
password to its first 72 bytes, so a DIFFERENT password sharing only the first
72 bytes authenticates, and registration accepts arbitrarily long passwords
with no maximum-length policy.

Fix (reject-over-72, the OWASP-standard minimal option — no hash-format
migration): registration rejects >72-byte passwords via
``validate_password_policy`` (=> 422), and ``verify_password`` refuses a
>72-byte candidate outright so a longer login attempt can never be truncated
down to match an existing hash (defense-in-depth on the login side). Exactly
72 bytes remains valid (boundary). Length is measured in UTF-8 BYTES, not
characters, because bcrypt's limit is a byte limit.
"""
from __future__ import annotations

from app.repositories.user import validate_password_policy
from app.security import hash_password, verify_password

#: A 72-byte password that satisfies the min-length + digit policy.
_PW_72 = "a" * 71 + "1"          # 72 bytes exactly
_PW_73 = "a" * 72 + "1"          # 73 bytes
_PW_91 = "x" * 90 + "1"          # 91 bytes (the finding's reproduction length)


class TestValidatePasswordPolicyMaxLength:
    def test_exactly_72_bytes_is_allowed(self):
        assert len(_PW_72.encode("utf-8")) == 72
        assert validate_password_policy(_PW_72) == []

    def test_over_72_bytes_is_rejected(self):
        assert len(_PW_73.encode("utf-8")) == 73
        problems = validate_password_policy(_PW_73)
        assert problems, "a 73-byte password must violate the max-length policy"
        assert any("72" in p for p in problems), problems

    def test_length_is_measured_in_bytes_not_characters(self):
        # 20 four-byte emoji + a digit = 21 code points (under any char cap) but
        # 81 UTF-8 bytes (over the bcrypt limit). A char-length check would miss
        # this; the byte-length check must catch it.
        pw = "\U0001F600" * 20 + "1"
        assert len(pw) == 21
        assert len(pw.encode("utf-8")) == 81
        problems = validate_password_policy(pw)
        assert problems and any("72" in p for p in problems), problems


class TestVerifyPasswordRejectsOver72:
    def test_correct_72_byte_password_verifies(self):
        assert verify_password(_PW_72, hash_password(_PW_72)) is True

    def test_variant_sharing_first_72_bytes_does_not_verify(self):
        # THE core bug: before the fix this returned True (bcrypt truncation).
        h = hash_password(_PW_72)
        variant = _PW_72 + "ZZZZZZZZZZZZZZZZZZ9"  # >72 bytes, identical first 72
        assert len(variant.encode("utf-8")) > 72
        assert verify_password(variant, h) is False

    def test_over_72_candidate_refused_against_a_short_hash(self):
        h = hash_password("short1234")  # a 9-byte real password
        assert verify_password("short1234", h) is True
        # A >72-byte candidate must never truncate-and-match anything.
        assert verify_password("short1234" + "q" * 90, h) is False


class TestRegisterRejectsOver72Endpoint:
    def test_register_over_72_byte_password_is_422(self, client):
        resp = client.post(
            "/auth/register", json={"email": "mv1@example.com", "password": _PW_91}
        )
        assert resp.status_code == 422, resp.text

    def test_variant_sharing_first_72_bytes_cannot_login(self, client):
        # Distinct email per sub-case so the identifier-keyed rate limiters
        # never produce a stray 429 that masks the intended 401.
        creds = {"email": "mv2@example.com", "password": _PW_72}
        assert client.post("/auth/register", json=creds).status_code == 201
        # The exact registered password logs in.
        assert client.post("/auth/login", json=creds).status_code == 200
        # A DIFFERENT password sharing only the first 72 bytes must NOT log in.
        variant = {
            "email": "mv2@example.com",
            "password": _PW_72 + "TOTALLY-DIFFERENT-TAIL-9",
        }
        assert client.post("/auth/login", json=variant).status_code == 401
