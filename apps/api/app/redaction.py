"""Shared redaction for any payload echoed back to a client or a log sink.

INCIDENT (SEC-422): ``POST /auth/login`` with a MISSPELLED field name
(``{"email": ..., "passwrd": "<the user's real password>"}``) hit FastAPI's
built-in ``RequestValidationError`` handler, whose body is
``{"detail": jsonable_encoder(exc.errors())}``. For a ``missing`` error
Pydantic sets ``input`` to the ENTIRE submitted body, so the response echoed
the plaintext password straight back to the caller — and into anything that
captures response bodies (proxies, browser devtools, error monitors, support
screenshots). A second vector: ``POST /auth/register`` with a policy-violating
password produces a FIELD-level ``value_error`` whose ``input`` IS the
plaintext password.

This module is the ONE place that decides what may be echoed. It is wired into
the app-wide ``RequestValidationError`` handler (app/main.py) so every current
AND future route inherits the guarantee, and into the hand-rolled
``ValidationError`` echoes in app/routers/admin.py.

Two layers, because key-name matching alone is provably insufficient:

* **Layer 1 — key/location names.** Any mapping key (at any depth) or any
  ``loc`` element whose normalized name matches a credential-ish token is
  redacted. This covers the honest case: the credential arrived under its
  real name (``password``, ``api_key``, ``authorization``, ...).

* **Layer 2 — credential-bearing batches.** Layer 1 cannot help when the
  credential arrived under a name we do not recognise — which is EXACTLY the
  reported defect (``passwrd``). So: when any error in the batch points at a
  credential field, every *string* leaf of that batch's echoed container
  inputs is redacted. Rationale: the request was supposed to carry a secret,
  the secret is missing from where it belongs, therefore any string in that
  body may be the secret. Structure and keys survive, so the shape of what was
  sent is still visible.

Usability is deliberately preserved: ``type``, ``loc``, ``msg`` and ``url`` are
never touched, and on non-credential endpoints values are echoed as before. A
caller still learns exactly which field failed and why.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: What replaces a redacted value. A fixed, non-reversible marker — never a
#: masked prefix/length hint, which would leak information about the secret.
REDACTED = "[redacted]"

#: Maximum structural depth we will walk. Beyond it the whole subtree is
#: redacted rather than echoed: an attacker-controlled body must not be able to
#: force unbounded recursion, and an un-walked subtree is un-vetted by
#: definition, so echoing it would be exactly the bug this module exists to fix.
_MAX_DEPTH = 12

#: Substring matches on the normalized key. Broad on purpose — over-redacting a
#: field named ``tokenCount`` in an ERROR ECHO costs a caller nothing, while
#: under-redacting costs a credential.
_SENSITIVE_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "apikey",
    "credential",
    "privatekey",
    "accesskey",
    "authorization",
    "bearer",
    "cookie",
    "sessionid",
)

#: Exact matches on the normalized key. These are too short to use as
#: substrings without absurd false positives (``key`` would swallow
#: ``keywords``, ``pin`` would swallow ``pinned``).
_SENSITIVE_EXACT: frozenset[str] = frozenset(
    {
        "pwd",
        "pin",
        "otp",
        "auth",
        "key",
        "keys",
        "sig",
        "signature",
        "salt",
        "hash",
        "code",
        "nonce",
    }
)

#: Error types whose ``input`` is, by construction, un-vetted caller text:
#:
#: * ``extra_forbidden`` — a value submitted under a name the model does not
#:   declare, so we cannot reason about what it holds.
#: * ``json_invalid`` / ``json_type`` — Pydantic's own JSON entrypoint
#:   (``model_validate_json``) sets ``input`` to the ENTIRE raw request text,
#:   credentials and all. FastAPI's router happens to build its ``json_invalid``
#:   with ``input: {}``, so this is defence in depth for any code path that
#:   validates JSON directly (and for a future FastAPI that stops doing that).
_NEVER_ECHO_INPUT_TYPES: frozenset[str] = frozenset(
    {"extra_forbidden", "json_invalid", "json_type"}
)


def _normalize_key(key: Any) -> str:
    """Lowercase, alphanumerics only — so ``API_Key``/``api-key``/``apiKey`` all
    collapse to ``apikey`` and match one token."""
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def is_sensitive_name(key: Any) -> bool:
    """True when *key* names something credential-bearing."""
    normalized = _normalize_key(key)
    if not normalized:
        return False
    if normalized in _SENSITIVE_EXACT:
        return True
    return any(token in normalized for token in _SENSITIVE_SUBSTRINGS)


def redact_payload(
    value: Any, *, redact_all_strings: bool = False, _depth: int = 0
) -> Any:
    """Return *value* with credential-bearing leaves replaced by :data:`REDACTED`.

    Nested-safe: mappings and sequences are walked recursively, so
    ``{"provider": {"api_key": "..."}}`` and ``[{"token": "..."}]`` are both
    covered.

    ``redact_all_strings`` is Layer 2 (see the module docstring): every string
    leaf goes, regardless of its key. Keys, structure, and non-string scalars
    (ints, bools, ``None``) survive so the caller can still see the shape of
    what they sent.
    """
    if _depth >= _MAX_DEPTH:
        return REDACTED
    if isinstance(value, Mapping):
        return {
            key: (
                REDACTED
                if is_sensitive_name(key)
                else redact_payload(
                    item, redact_all_strings=redact_all_strings, _depth=_depth + 1
                )
            )
            for key, item in value.items()
        }
    # str/bytes are Sequences — check them before the generic sequence branch.
    if isinstance(value, (str, bytes)):
        return REDACTED if redact_all_strings else value
    if isinstance(value, Sequence):
        return [
            redact_payload(item, redact_all_strings=redact_all_strings, _depth=_depth + 1)
            for item in value
        ]
    if isinstance(value, (set, frozenset)):
        return [
            redact_payload(item, redact_all_strings=redact_all_strings, _depth=_depth + 1)
            for item in value
        ]
    if redact_all_strings and not isinstance(value, (bool, int, float, type(None))):
        # Layer 2, non-JSON scalars: a Pydantic ``ctx`` can hold the validator's
        # own exception object, which ``jsonable_encoder`` renders via ``str()``
        # — i.e. an arbitrary string we have not vetted. Only true numeric /
        # boolean / null leaves are safe to echo unexamined.
        return REDACTED
    return value


def _loc_is_sensitive(loc: Any) -> bool:
    """True when any element of a Pydantic ``loc`` tuple names a credential."""
    if isinstance(loc, (str, bytes)):
        return is_sensitive_name(loc)
    if isinstance(loc, Sequence):
        return any(
            is_sensitive_name(part) for part in loc if isinstance(part, (str, bytes))
        )
    return False


def batch_targets_credential(errors: Sequence[Mapping[str, Any]]) -> bool:
    """True when ANY error in the batch points at a credential field.

    That is the signal that the request was *supposed* to carry a secret, which
    is what arms Layer 2 for the whole batch.
    """
    return any(_loc_is_sensitive(error.get("loc")) for error in errors)


def redact_validation_errors(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Sanitize a Pydantic/FastAPI ``errors()`` list for client consumption.

    ``type``, ``loc``, ``msg`` and ``url`` pass through untouched — they carry
    all of the diagnostic value and none of the secret. ``input`` and ``ctx``
    are redacted per the two layers described in the module docstring.
    """
    all_strings = batch_targets_credential(errors)
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        cleaned = {key: value for key, value in error.items() if key not in ("input", "ctx")}
        # A field-level failure ON a credential, or a value submitted under a
        # field the model does not declare: never echo the value at all.
        blanket = _loc_is_sensitive(error.get("loc")) or (
            str(error.get("type", "")) in _NEVER_ECHO_INPUT_TYPES
        )
        if "input" in error:
            # A blanket case whose input is a CONTAINER keeps its keys and its
            # shape (values redacted) rather than collapsing to a bare marker:
            # on the misspelled-field case that is what tells the caller they
            # sent ``passwrd`` when the model wants ``password``. A blanket
            # SCALAR is the credential itself, so it collapses.
            raw_input = error["input"]
            is_container = isinstance(raw_input, (Mapping, list, tuple, set, frozenset))
            if blanket and not is_container:
                cleaned["input"] = REDACTED
            else:
                cleaned["input"] = redact_payload(
                    raw_input, redact_all_strings=all_strings or blanket
                )
        if "ctx" in error:
            # ``ctx`` carries constraint metadata (limits, patterns) but for
            # ``value_error`` it carries the validator's exception, whose text a
            # custom validator could interpolate the input into.
            cleaned["ctx"] = (
                REDACTED
                if blanket
                else redact_payload(error["ctx"], redact_all_strings=all_strings)
            )
        sanitized.append(cleaned)
    return sanitized
