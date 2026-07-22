"""ML-agents-cred-001 (MODELS-LIVE, BLOCKER) — Anthropic credential hardening.

TDD fail-before suite for the AMENDED fix approved for
``uat/reports/evidence/models-live/catalog/ML-agents-cred-001-RCA.md`` /
``ML-agents-cred-001-plan-review.md`` (evidence dir is gitignored — the full
amended plan is restated in the docstrings below so this file stands alone).

**Bug being fixed:** ``PUT /agents/providers/anthropic/credential`` 422s a
*valid* Claude Code OAuth token in two independent ways:

1. ``_detect_anthropic_auth_mode`` (agents.py) and ``_infer_anthropic_auth_mode``
   (llm_client.py) both hardcode the EXACT literal prefix ``sk-ant-oat01-``.
   Anthropic's own CLI already issues ``sk-ant-oat02-…`` (and will keep
   incrementing), so a perfectly valid, freshly-issued token is rejected
   outright the moment Anthropic bumps the token-format version digit.
2. Neither function strips whitespace/invisible Unicode characters or a
   surrounding pair of quotes before checking the prefix, so a token copy-
   pasted with a trailing newline, an NBSP (a common "smart" clipboard
   artifact), a zero-width space, a BOM, or wrapped in quotes (e.g. pasted
   from a JSON/YAML snippet) is rejected even though the underlying secret is
   perfectly valid.

**The amended fix under test (NOT implemented by this commit):**
  - Normalize the secret at the START of validation: strip ASCII whitespace,
    Unicode whitespace/invisibles (U+00A0 NBSP, U+200B ZWSP, U+FEFF BOM/ZWNBSP,
    U+2000-U+200A general punctuation spaces), and ONE pair of matching
    surrounding quotes (`"…"` or `'…'`) — applied so that whitespace nested
    INSIDE a quoted value is also cleaned up (paste-from-JSON case).
  - Broaden the Claude-Code OAuth-token acceptance from the exact literal
    ``sk-ant-oat01-`` to the digit-versioned regex ``^sk-ant-oat\\d+-`` (accepts
    oat01/oat02/oat03/…) — authMode ``oauth_token``. This MUST still REJECT a
    bare ``sk-ant-oat-`` (no version digit at all) — the legacy in-app
    subscription-OAuth shape — which stays a 422 (ADR-P7-01 NON-goal).
  - The 422 message must de-hardcode any "only oat01" implication (a fixed
    example is fine — it just must not claim exclusivity) while still naming
    ``sk-ant-oat01-`` as a worked example, and must NEVER echo any substring of
    the value the caller submitted.
  - ``llm_client._infer_anthropic_auth_mode`` mirrors the same digit-anchored
    regex, preserving its existing 3-way bucketing (``oauth_token`` /
    ``subscription_oauth`` / ``api_key``) used by the legacy-env-fallback path
    in ``resolve_credential``.
  - The frontend's pre-send trim (``ProviderConfigModal.tsx`` ``secret.trim()``)
    is extended to the same Unicode whitespace/invisibles + quote-stripping
    set (covered by the companion vitest file, not here).

Two kinds of test live here, clearly separated (mirrors
``test_gap_p7_def_a_dual_mode.py`` convention):

  * "NEW-CONTRACT (fail-before)" — exercise behaviour that does NOT exist yet;
    MUST FAIL against current code and pass only after the fix.
  * "REGRESSION / COMPLIANCE GUARD (pass-before-and-after)" — lock in
    behaviour the fix must NOT break. These are GREEN before AND after by
    design — a broadened prefix match must never degrade into a bare
    substring/no-digit match.

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest tests/test_ml_cred_001.py -q
"""
from __future__ import annotations

import pytest

from app.services import credential_vault as vault

# ---------------------------------------------------------------------------
# Fake token constants — NEVER a real secret. Only the prefix is load-bearing.
# Same suffix shape as the existing GAP-P7-DEF-A OAT01_TOKEN/API03_KEY anchors
# (test_gap_p7_def_a_dual_mode.py) so "valid-shape" is judged consistently.
# ---------------------------------------------------------------------------
OAT01_TOKEN = "sk-ant-oat01-FAKEtestTOKENvalue0000000000deadbeef"
OAT02_TOKEN = "sk-ant-oat02-FAKEtestTOKENvalue0000000000deadbeef"
API03_KEY = "sk-ant-api03-FAKEtestCONSOLEkeyvalue0000000000"
# Bare "oat-" with NO version digit — the legacy in-app subscription-OAuth
# shape (ADR-P7-01 NON-goal). Same literal value as the P7 anchor file's
# LEGACY_SUBSCRIPTION_OAUTH constant.
LEGACY_SUBSCRIPTION_OAUTH = "sk-ant-oat-LEGACYnotOat01token"
GARBAGE_SECRET = "not-a-key"

# Unicode whitespace / invisible characters the normalizer must strip.
NBSP = " "       # no-break space (common "smart paste" artifact)
ZWSP = "​"       # zero-width space
FEFF = "﻿"       # BOM / zero-width no-break space
EM_SPACE = " "   # general-punctuation space (U+2000-U+200A range)


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env`` during
    tests — default the oauth_token sync target to a per-test tmp file."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture()
def _clean_provider_credentials():
    """ProviderCredential has no FK to User, so conftest never truncates it —
    self-clean it and reset the repo's process-level table-ready cache."""
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
        conn.commit()
    pc_module._table_ready = False


def _clear_anthropic_env(monkeypatch):
    """Remove every env var that could resolve an Anthropic credential so the
    stored DB row (or its absence) / the explicitly-set env var under test is
    the ONLY source under test."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "ABACUS_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


# ===========================================================================
# NEW-CONTRACT (fail-before) — digit-versioned oat\d+ acceptance (§ regex)
# ===========================================================================


def test_oat02_token_accepted_as_oauth_token(
    client, auth_headers, _clean_provider_credentials
):
    """A ``sk-ant-oat02-`` token (Anthropic's next token-format version) must
    be ACCEPTED (200) and stored with server-derived authMode ``oauth_token``.

    FAIL-BEFORE (WHY): ``_detect_anthropic_auth_mode`` checks the EXACT literal
    ``secret.startswith("sk-ant-oat01-")`` — an ``oat02`` token does not match
    that literal, so ``detected`` is ``None`` and the endpoint 422s.
    """
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT02_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    assert OAT02_TOKEN not in put.text  # plaintext never echoed

    providers = client.get("/agents/providers", headers=auth_headers)
    assert providers.status_code == 200, providers.text
    anthropic = next(p for p in providers.json() if p["id"] == "anthropic")
    assert anthropic["authMode"] == "oauth_token"
    assert anthropic["status"] == "connected"


# ===========================================================================
# REGRESSION GUARD (pass-before-and-after) — oat01 keeps working
# ===========================================================================


def test_oat01_token_still_accepted_as_oauth_token(
    client, auth_headers, _clean_provider_credentials
):
    """REGRESSION: the original ``sk-ant-oat01-`` shape must keep working
    byte-for-byte once the acceptance is broadened to ``oat\\d+``."""
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": OAT01_TOKEN},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    anthropic = next(
        p for p in client.get("/agents/providers", headers=auth_headers).json()
        if p["id"] == "anthropic"
    )
    assert anthropic["authMode"] == "oauth_token"


# ===========================================================================
# COMPLIANCE GUARD (pass-before-and-after) — no-digit "oat-" must STILL 422.
# Written so it PASSES against current code (exact-literal match already
# rejects it) and would FAIL if the fix is (mis)implemented as a bare
# substring/prefix check (e.g. ``"sk-ant-oat" in secret`` or
# ``secret.startswith("sk-ant-oat")`` without requiring a digit before the
# trailing hyphen) instead of the required ``^sk-ant-oat\\d+-`` regex.
# ===========================================================================


def test_bare_oat_no_digit_still_rejected_as_oauth_token(
    client, auth_headers, _clean_provider_credentials
):
    """A bare ``sk-ant-oat-`` (NO version digit) declared as ``oauth_token``
    must 422 both now and after the fix — it is the legacy in-app
    subscription-OAuth shape (ADR-P7-01 NON-goal), not a Claude Code token.

    Guards against a broadened-but-sloppy fix that accepts ANY ``sk-ant-oat``
    prefix regardless of a version digit being present.
    """
    res = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": LEGACY_SUBSCRIPTION_OAUTH},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text
    assert LEGACY_SUBSCRIPTION_OAUTH not in res.text


def test_legacy_subscription_oauth_label_still_rejected(
    client, auth_headers, _clean_provider_credentials
):
    """REGRESSION (ADR-P7-01 NON-goal): the in-app OAuth *authorize* label
    ``subscription_oauth`` (declared authMode) with a non-versioned
    ``sk-ant-oat`` secret stays a 422 on the write path."""
    res = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "subscription_oauth", "secret": LEGACY_SUBSCRIPTION_OAUTH},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text


# ===========================================================================
# NEW-CONTRACT (fail-before) — whitespace/invisible/quote normalization
# ===========================================================================


@pytest.mark.parametrize(
    "wrapped,label",
    [
        (f"{NBSP}{API03_KEY}{NBSP}", "nbsp-wrapped"),
        (f"{ZWSP}{API03_KEY}{ZWSP}", "zwsp-wrapped"),
        (f"{FEFF}{API03_KEY}", "leading-bom"),
        (f"{EM_SPACE}{API03_KEY}{EM_SPACE}", "em-space-wrapped"),
        (f'"{API03_KEY}"', "double-quote-wrapped"),
        (f"'{API03_KEY}'", "single-quote-wrapped"),
    ],
)
def test_api03_key_wrapped_in_invisible_chars_or_quotes_accepted(
    client, auth_headers, _clean_provider_credentials, wrapped, label
):
    """An otherwise-valid Console API key wrapped in NBSP / ZWSP / BOM / a
    general-punctuation space / a single matching pair of quotes must be
    ACCEPTED (200) as ``api_key`` once normalized.

    FAIL-BEFORE (WHY): ``_detect_anthropic_auth_mode`` calls only
    ``secret.startswith(...)`` on the RAW secret — none of these wrapper
    characters are stripped first, so ``wrapped.startswith("sk-ant-api")`` is
    False for every case here and the endpoint 422s.
    """
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": wrapped},
        headers=auth_headers,
    )
    assert put.status_code == 200, f"[{label}] expected 200, got: {put.text}"
    anthropic = next(
        p for p in client.get("/agents/providers", headers=auth_headers).json()
        if p["id"] == "anthropic"
    )
    assert anthropic["authMode"] == "api_key", label


def test_oat01_token_nested_whitespace_inside_quotes_accepted(
    client, auth_headers, _clean_provider_credentials
):
    """A token pasted from a JSON/YAML snippet — a quoted value with ASCII
    whitespace INSIDE the quotes, e.g. ``"  sk-ant-oat01-x  "`` — must
    normalize down to the bare token and be ACCEPTED as ``oauth_token``. This
    proves the normalizer strips whitespace found INSIDE the stripped quote
    pair, not just at the outermost edges of the raw input.

    FAIL-BEFORE (WHY): no normalization exists at all today; the raw value
    (leading ``"``) does not match ``startswith("sk-ant-oat01-")`` → 422.
    """
    raw = f'"  {OAT01_TOKEN}  "'
    put = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "oauth_token", "secret": raw},
        headers=auth_headers,
    )
    assert put.status_code == 200, put.text
    anthropic = next(
        p for p in client.get("/agents/providers", headers=auth_headers).json()
        if p["id"] == "anthropic"
    )
    assert anthropic["authMode"] == "oauth_token"


# ===========================================================================
# REGRESSION / COMPLIANCE GUARD — 422 message contract (pass-before-and-after)
# ===========================================================================


def test_garbage_credential_still_422_message_never_echoes_secret(
    client, auth_headers, _clean_provider_credentials
):
    """An unrecognised secret is still a 422 whose body names the
    ``sk-ant-oat01-`` example (kept as a worked example post-fix) and NEVER
    contains any substring of the submitted value. This must hold both before
    and after the fix — it is the message-safety invariant the amendment must
    preserve while de-hardcoding the "only oat01" implication.
    """
    res = client.put(
        "/agents/providers/anthropic/credential",
        json={"authMode": "api_key", "secret": GARBAGE_SECRET},
        headers=auth_headers,
    )
    assert res.status_code == 422, res.text
    body = res.text
    assert "sk-ant-oat01-" in body, "example format must still be named"
    assert GARBAGE_SECRET not in body, "the submitted value must never be echoed"


# ===========================================================================
# NEW-CONTRACT (fail-before) — llm_client env-fallback mirrors the same regex
# ===========================================================================


def test_llm_client_env_fallback_oat02_resolves_as_oauth_token(monkeypatch):
    """The legacy env-fallback path in ``resolve_credential('anthropic')``
    must classify an ``oat02`` token from ``ANTHROPIC_API_KEY`` as
    ``oauth_token`` (a SUPPORTED resolution), mirroring the digit-anchored
    regex used on the write path.

    FAIL-BEFORE (WHY): ``_infer_anthropic_auth_mode`` checks the exact literal
    ``sk-ant-oat01-`` first, then falls back to the bare ``sk-ant-oat`` check
    which classifies ANY other oat-prefixed value (including ``oat02``) as
    ``subscription_oauth``. ``_resolution_is_supported`` then rejects that
    mode, so ``resolve_credential`` returns ``None`` instead of a usable
    ``oauth_token`` resolution — a valid oat02 token silently fails to resolve.
    """
    from app.services.llm_client import resolve_credential

    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", OAT02_TOKEN)

    resolution = resolve_credential("anthropic")
    assert resolution is not None, (
        "resolve_credential returned None: the oat02 env token was classified "
        "as an unsupported mode (subscription_oauth) instead of oauth_token"
    )
    assert resolution.auth_mode == "oauth_token"
    assert resolution.secret == OAT02_TOKEN
    assert resolution.source == "environment"


def test_llm_client_env_fallback_bare_oat_no_digit_stays_subscription_oauth(
    monkeypatch,
):
    """COMPLIANCE GUARD (pass-before-and-after): a bare ``sk-ant-oat-`` (no
    version digit) env value must still classify as ``subscription_oauth``
    (unsupported) — ``resolve_credential`` must keep returning ``None`` for it,
    never silently promoting it to a usable ``oauth_token`` resolution."""
    from app.services.llm_client import resolve_credential

    _clear_anthropic_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", LEGACY_SUBSCRIPTION_OAUTH)

    resolution = resolve_credential("anthropic")
    assert resolution is None
