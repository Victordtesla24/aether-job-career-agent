"""SEC-422 — a 422 must never echo a credential back to the caller.

DEFECT: FastAPI's built-in ``RequestValidationError`` handler answers with
``{"detail": jsonable_encoder(exc.errors())}``, and Pydantic puts the offending
value in each error's ``input`` — for a ``missing`` error that is the ENTIRE
submitted body. So ``POST /auth/login`` with a MISSPELLED field name
(``passwrd``) mirrored the user's plaintext password straight back in the
response body, where it also lands in anything that captures response bodies.

EVIDENCE DISCIPLINE: these tests assert on the ABSENCE of a sentinel string.
They never print, log, or assert-message a credential value — a failing
assertion here prints only the boolean and the (already-redacted) body, so a
CI log can never become the new leak.

Fixed by the app-wide handler in app/main.py delegating to app/redaction.py.
"""
from __future__ import annotations

import uuid

import pytest

from app.redaction import REDACTED, redact_payload, redact_validation_errors

# A value that appears NOWHERE else in the codebase, so "not in body" is a
# meaningful assertion rather than an accident of a common substring.
SENTINEL = "Zq7x-SEC422-SENTINEL-9f2a"
#: Same shape, but violates the register password policy (no digit), so the
#: FIELD-level validator fires and Pydantic sets ``input`` to the value itself.
WEAK_SENTINEL = "zqxsecsentinelweak"


def _assert_absent(body_text: str, secret: str, context: str) -> None:
    """Assert *secret* is absent WITHOUT ever putting it in the failure text.

    The containment test is collapsed to a bool BEFORE the assert on purpose:
    ``assert secret not in body_text`` would let pytest's assertion rewriting
    print both operands — i.e. the credential — into the CI log, which is one
    of the sinks this whole fix exists to keep credentials out of. Asserting on
    a plain bool gives pytest nothing to introspect but ``True``.
    """
    leaked = secret in body_text
    assert not leaked, (
        f"{context}: response body contained the submitted credential "
        f"(value withheld from this message by design). Redacted view: "
        f"{body_text.replace(secret, '<CREDENTIAL-LEAKED-HERE>')}"
    )


# ---------------------------------------------------------------------------
# Unit — the shared redactor
# ---------------------------------------------------------------------------


class TestRedactPayload:
    def test_redacts_sensitive_keys_at_any_depth(self):
        cleaned = redact_payload(
            {
                "password": SENTINEL,
                "provider": {"api_key": SENTINEL, "deep": [{"Bearer-Token": SENTINEL}]},
                "list": [{"current_password": SENTINEL}],
            }
        )
        _assert_absent(repr(cleaned), SENTINEL, "nested redaction")
        assert cleaned["password"] == REDACTED
        assert cleaned["provider"]["api_key"] == REDACTED
        assert cleaned["provider"]["deep"][0]["Bearer-Token"] == REDACTED
        assert cleaned["list"][0]["current_password"] == REDACTED

    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "Password",
            "current_password",
            "newPassword",
            "token",
            "secret",
            "api_key",
            "apiKey",
            "API-KEY",
            "authorization",
            "clientSecret",
            "refresh_token",
        ],
    )
    def test_sensitive_name_variants(self, key):
        assert redact_payload({key: SENTINEL})[key] == REDACTED

    def test_non_sensitive_values_survive(self):
        payload = {"title": "KEEP-ME", "count": 3, "ok": True, "tags": ["a", "b"]}
        assert redact_payload(payload) == payload

    def test_depth_cap_redacts_rather_than_recursing_forever(self):
        deep: dict = {"leaf": SENTINEL}
        for _ in range(40):
            deep = {"n": deep}
        _assert_absent(repr(redact_payload(deep)), SENTINEL, "depth cap")


class TestRedactValidationErrors:
    def test_missing_credential_field_redacts_unknown_keys_too(self):
        """The reported defect: the secret arrives under a name we do not know.

        Key-name matching alone cannot save us here, so the whole batch is
        treated as credential-bearing and every string leaf goes.
        """
        errors = [
            {
                "type": "missing",
                "loc": ("body", "password"),
                "msg": "Field required",
                "input": {"email": "casey@example.com", "passwrd": SENTINEL},
            }
        ]
        cleaned = redact_validation_errors(errors)
        _assert_absent(repr(cleaned), SENTINEL, "misspelled credential key")
        # Diagnostics survive: the caller still learns which field and why, and
        # still sees the key they actually sent.
        assert cleaned[0]["loc"] == ("body", "password")
        assert cleaned[0]["msg"] == "Field required"
        assert "passwrd" in cleaned[0]["input"]

    def test_scalar_input_at_credential_loc_is_dropped(self):
        errors = [
            {
                "type": "value_error",
                "loc": ("body", "password"),
                "msg": "Value error, password must contain at least one digit",
                "input": WEAK_SENTINEL,
                "ctx": {"error": WEAK_SENTINEL},
            }
        ]
        cleaned = redact_validation_errors(errors)
        _assert_absent(repr(cleaned), WEAK_SENTINEL, "field-level credential error")
        assert cleaned[0]["input"] == REDACTED

    def test_unknown_field_value_is_never_echoed(self):
        errors = [
            {
                "type": "extra_forbidden",
                "loc": ("body", "passwrd"),
                "msg": "Extra inputs are not permitted",
                "input": SENTINEL,
            }
        ]
        cleaned = redact_validation_errors(errors)
        _assert_absent(repr(cleaned), SENTINEL, "extra_forbidden echo")

    def test_malformed_json_raw_body_is_never_echoed(self):
        """Pydantic's JSON entrypoint puts the ENTIRE raw request text in
        ``input``. FastAPI's router currently builds its own ``json_invalid``
        with an empty input, so this is the guard for any path that validates
        JSON directly — and for a FastAPI that stops being careful."""
        errors = [
            {
                "type": "json_invalid",
                "loc": (),
                "msg": "Invalid JSON: EOF while parsing an object",
                "input": '{"email":"casey@example.com","password":"' + SENTINEL + '"',
                "ctx": {"error": "EOF while parsing an object"},
            }
        ]
        cleaned = redact_validation_errors(errors)
        _assert_absent(repr(cleaned), SENTINEL, "json_invalid raw-body echo")
        assert cleaned[0]["msg"].startswith("Invalid JSON")

    def test_non_credential_batch_keeps_echoing_values(self):
        errors = [
            {
                "type": "list_type",
                "loc": ("body", "tags"),
                "msg": "Input should be a valid list",
                "input": "NOT-A-LIST",
            }
        ]
        assert redact_validation_errors(errors)[0]["input"] == "NOT-A-LIST"


# ---------------------------------------------------------------------------
# Integration — the live routes
# ---------------------------------------------------------------------------


class TestLoginDoesNotEchoCredentials:
    def test_misspelled_password_field_422_does_not_echo_credential(self, client):
        """RED before the fix: the 422 body contained SENTINEL verbatim."""
        response = client.post(
            "/auth/login",
            json={"email": "casey@example.com", "passwrd": SENTINEL},
        )
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/login misspelled field")

    def test_missing_email_422_does_not_echo_credential(self, client):
        response = client.post("/auth/login", json={"password": SENTINEL})
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/login missing email")

    def test_wrong_typed_password_422_does_not_echo_credential(self, client):
        response = client.post(
            "/auth/login", json={"email": "casey@example.com", "password": [SENTINEL]}
        )
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/login wrong type")

    def test_422_still_names_the_field_and_the_reason(self, client):
        """Redaction must not cost the caller the diagnosis."""
        response = client.post("/auth/login", json={"email": "casey@example.com"})
        assert response.status_code == 422, response.status_code
        detail = response.json()["detail"]
        assert any(
            "password" in [str(part) for part in item["loc"]] and item["msg"]
            for item in detail
        ), detail

    def test_malformed_json_422_does_not_echo_credential(self, client):
        response = client.post(
            "/auth/login",
            content='{"email":"casey@example.com","password":"' + SENTINEL + '"',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/login malformed JSON")

    def test_valid_shape_wrong_password_401_does_not_echo_credential(self, client):
        response = client.post(
            "/auth/login",
            json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.com", "password": SENTINEL},
        )
        assert response.status_code == 401, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/login 401")


class TestRegisterDoesNotEchoCredentials:
    def test_policy_violating_password_422_does_not_echo_credential(self, client):
        """The register validator rejects the password, and Pydantic's ``input``
        for a field-level error IS the plaintext password."""
        response = client.post(
            "/auth/register",
            json={"email": f"sec422-{uuid.uuid4().hex[:8]}@example.com", "password": WEAK_SENTINEL},
        )
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, WEAK_SENTINEL, "POST /auth/register weak password")
        # The policy reason itself is still delivered — that is the whole point
        # of the message, and it names no secret.
        assert "digit" in response.text

    def test_misspelled_password_field_422_does_not_echo_credential(self, client):
        response = client.post(
            "/auth/register",
            json={"email": f"sec422-{uuid.uuid4().hex[:8]}@example.com", "passwrd": SENTINEL},
        )
        assert response.status_code == 422, response.status_code
        _assert_absent(response.text, SENTINEL, "POST /auth/register misspelled field")


class TestNonCredentialRoutesKeepEchoingInput:
    def test_story_422_still_echoes_the_offending_value(self, client, auth_headers):
        """Usability guard: a non-credential endpoint must be as informative as
        it was before the fix."""
        response = client.post(
            "/stories",
            headers=auth_headers,
            json={
                "title": "Led a migration",
                "situation": "s",
                "task": "t",
                "action": "a",
                "result": "r",
                "tags": "NOT-A-LIST-SEC422",
            },
        )
        assert response.status_code == 422, response.text
        assert "NOT-A-LIST-SEC422" in response.text, response.text


class TestAdminHandRolledEchoIsRedacted:
    """``/admin/settings`` parses its body INSIDE the handler (auth-before-body),
    so it never reaches the app-wide handler and must call the shared sanitizer
    itself."""

    def test_admin_settings_422_redacts_nested_credentials(
        self, client, auth_headers, promote_user_to_admin
    ):
        promote_user_to_admin(client._test_user_id)
        response = client.post(
            "/admin/settings",
            headers=auth_headers,
            json={"emailVerificationEnabled": {"api_key": SENTINEL}},
        )
        assert response.status_code == 422, response.text
        _assert_absent(response.text, SENTINEL, "POST /admin/settings")
