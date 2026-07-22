"""ML-adv-002 (MODELS-LIVE, LOW) — the Anthropic OAuth EXCHANGE endpoint must
map an upstream CODE-REJECTION to a client 4xx (422), not a 502.

**Bug being fixed:** ``POST /agents/providers/anthropic/oauth/exchange`` maps
EVERY ``anthropic_oauth.OAuthExchangeError`` — regardless of cause — to
``HTTP_502_BAD_GATEWAY`` (``app/routers/agents.py`` lines ~2717-2724). When the
Anthropic token endpoint honestly REJECTS the pasted authorization code
(upstream HTTP 400, e.g. ``invalid_grant``), the app's own JSON detail is
accurate (``"Anthropic rejected the authorization code — restart Connect with
Anthropic."``) but Cloudflare (sitting in front of the production origin)
intercepts ANY 502 and replaces the body with its own generic
``"error code: 502"`` HTML page — 4xx JSON responses pass through Cloudflare
untouched. The operator therefore never sees the actionable detail for the
single most common failure mode (a stale/mistyped/expired pasted code).

**The fix under test (NOT implemented by this commit):** distinguish, inside
``anthropic_oauth._post_token`` / the router's exception handling, between:

  1. Anthropic's token endpoint responding with a non-2xx status that means
     "your code/grant was rejected" (a genuine HTTP response was received,
     e.g. 400/401/403) — this is a CLIENT error (the operator's pasted code
     was bad) and must surface as 422 with the SAME honest detail text.
  2. A genuine network/gateway failure to reach Anthropic at all (DNS, TCP
     connect refused, timeout — ``httpx.HTTPError`` with NO response) — this
     stays 502 (a real gateway failure, not a rejected code).

Both scenarios are exercised here at the ``httpx.post`` boundary (NOT the
higher-level ``_post_token`` monkeypatch seam other cred-002 tests use) so
these tests exercise whatever real distinguishing logic the fixer writes
inside ``_post_token`` itself, rather than assuming its shape.

FAIL-BEFORE (WHY): the router currently catches ``OAuthExchangeError``
unconditionally and always raises ``HTTP_502_BAD_GATEWAY`` — see
``agents.py`` ``anthropic_oauth_exchange()``. The rejected-code scenario
below therefore currently returns 502, not 422.

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest \
        tests/test_ml_adv_002_oauth_exchange_status.py -q
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.services import credential_vault as vault

# ---------------------------------------------------------------------------
# Fixtures — mirrors test_ml_cred_002_anthropic_oauth.py conventions (same
# tables, same self-clean requirement: none of ProviderCredential /
# AnthropicOAuthState / AnthropicOAuthToken carry an FK to User, so conftest's
# per-test ``_truncate_tables`` never touches them).
# ---------------------------------------------------------------------------


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
def _clean_anthropic_oauth_state():
    from app.db import get_connection
    from app.repositories import provider_credential as pc_module
    from app.repositories import user_provider_credential as upc_module

    yield
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('DROP TABLE IF EXISTS "ProviderCredential"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthState"')
            cur.execute('DROP TABLE IF EXISTS "AnthropicOAuthToken"')
            cur.execute('DROP TABLE IF EXISTS "UserProviderCredential"')
        conn.commit()
    pc_module._table_ready = False
    upc_module._reset_ready_for_tests()


def _extract_state_from_authorize_url(authorize_url: str) -> str:
    qs = parse_qs(urlsplit(authorize_url).query)
    assert "state" in qs, f"authorizeUrl carries no state param: {authorize_url}"
    return qs["state"][0]


def _start_flow(client, auth_headers) -> str:
    """Real ``/oauth/start`` call — returns the persisted single-use state."""
    start = client.post("/agents/providers/anthropic/oauth/start", headers=auth_headers)
    assert start.status_code == 200, start.text
    return _extract_state_from_authorize_url(start.json()["authorizeUrl"])


class _FakeHttpxResponse:
    """Minimal stand-in for ``httpx.Response`` — only what ``_post_token``
    touches (``.status_code`` and ``.json()``)."""

    def __init__(self, status_code: int, json_data: dict) -> None:
        self.status_code = status_code
        self._json_data = json_data

    def json(self) -> dict:
        return self._json_data


# ===========================================================================
# 1. Upstream REJECTS the code (Anthropic responds HTTP 400 invalid_grant) —
#    must be a 4xx (422), the honest detail must survive, NEVER 502.
# FAIL-BEFORE (WHY): currently 502 for ANY OAuthExchangeError.
# ===========================================================================


def test_exchange_rejected_code_returns_422_not_502(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    state = _start_flow(client, auth_headers)

    def _fake_httpx_post(url, json=None, timeout=None, **kwargs):
        # Real Anthropic-shaped OAuth error body for a rejected/invalid code.
        return _FakeHttpxResponse(
            400, {"error": "invalid_grant", "error_description": "authorization code is invalid"}
        )

    monkeypatch.setattr(httpx, "post", _fake_httpx_post)

    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"BADCODEVALUE#{state}"},
        headers=auth_headers,
    )

    assert resp.status_code != 502, (
        "an upstream CODE-REJECTION (Anthropic HTTP 400) must not be reported "
        f"as a 502 (Cloudflare replaces 502 bodies with a generic page): {resp.text}"
    )
    assert resp.status_code == 422, resp.text

    body = resp.json()
    detail = body.get("detail", "")
    assert detail, "the 4xx response must carry the honest detail message"
    assert "restart connect with anthropic" in detail.lower(), (
        f"the honest, actionable detail must survive at 4xx (this is the whole "
        f"point of the fix — Cloudflare only mangles 502 bodies): {detail!r}"
    )
    # No secret / raw upstream body ever echoed.
    assert "invalid_grant" not in resp.text

    # Nothing is stored on a rejected exchange.
    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("anthropic") is None


# ===========================================================================
# 2. Genuine network/gateway failure (no HTTP response at all reaches us) —
#    stays 502. Regression guard: this scenario is DISTINCT from #1 and must
#    NOT be swept into the new 4xx bucket.
# This scenario is expected to ALREADY pass (the router already 502s every
# OAuthExchangeError today) — it pins that the fix must not OVER-CORRECT and
# turn a real gateway failure into a 4xx too.
# ===========================================================================


def test_exchange_genuine_network_failure_still_502(
    client, auth_headers, monkeypatch, _clean_anthropic_oauth_state
):
    state = _start_flow(client, auth_headers)

    def _fake_httpx_post(url, json=None, timeout=None, **kwargs):
        raise httpx.ConnectError("Name or service not known")

    monkeypatch.setattr(httpx, "post", _fake_httpx_post)

    resp = client.post(
        "/agents/providers/anthropic/oauth/exchange",
        json={"pastedCode": f"SOMECODE#{state}"},
        headers=auth_headers,
    )

    assert resp.status_code == 502, (
        f"a genuine network/gateway failure to reach Anthropic (no HTTP response "
        f"at all) must stay 502 — only a real upstream REJECTION becomes 4xx: "
        f"{resp.text}"
    )
    body = resp.json()
    assert body.get("detail"), "even a 502 must carry an honest (non-empty) detail"

    from app.repositories.provider_credential import ProviderCredentialRepository

    assert ProviderCredentialRepository().get_secret("anthropic") is None
