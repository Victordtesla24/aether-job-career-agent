"""USER-SCOPE "Connect with Anthropic" subscription-token mint (UPO-1).

The deployment-wide flow (``/agents/providers/anthropic/oauth/*``,
ML-agents-cred-002) is OPERATOR-ONLY: its exchange overwrites the shared
``ProviderCredential('anthropic')`` row every bare ``claude-*`` run bills
against, so F-01 / ADR-F01-PROVIDER-CREDENTIAL-AUTHZ gates all three routes
behind ``AdminUser``. An ordinary customer therefore had NO way to obtain a
Claude subscription token in-app — the per-user provider dialog offered only a
manual paste of a token the customer had to mint themselves with
``claude setup-token`` on their own machine.

This suite pins the per-user twin of that flow:

    POST /agents/user/providers/anthropic/oauth/mint/start
        -> 200 {"authorizeUrl": str}. Any AUTHENTICATED user (no admin).
    POST /agents/user/providers/anthropic/oauth/mint/exchange  {"pastedCode": str}
        -> 200 {"token", "authMode", "secretHint", "expiresAt", "scope"}

RUN-20260818T0223Z merge note (FEAT-PROVIDER deploy-merge): mounted under
``.../oauth/mint/...`` (one extra path segment vs. the pre-merge
``.../oauth/{start,exchange}``) because GAP-PROVIDER-OAUTH-1 independently
claimed the literal ``/agents/user/providers/{provider}/oauth/{start,
exchange}`` path for a different (auto-persist) contract for the same
provider id, and FastAPI/Starlette can only route one handler per literal
path. Every assertion below is unchanged from the pre-merge version of this
file — only the two path constants moved.

**Mint-and-fill, not store.** The exchange MINTS the caller's own subscription
token and returns it ONCE to the caller who just authenticated, so the dialog
can populate its OAuth-token field; the customer then clicks Save, which stores
it through the EXISTING ``PUT /agents/user/providers/anthropic/credential``
write path. That single-write-path property is what keeps this from being a
privilege escalation, and the two tests below are its regression guards:

  * ``test_user_exchange_does_not_write_deployment_credential`` — a non-admin
    completing this flow must NOT touch the shared ``ProviderCredential`` row.
    If it did, any customer could silently re-bill the whole deployment
    (including cron) to their own Claude account — the exact attack F-01's
    admin gate exists to prevent.
  * ``test_user_exchange_does_not_write_anthropic_oauth_token_row`` — it must
    not write the per-user ``AnthropicOAuthToken`` store either. That table
    backs the operator's auto-refresh hook; a mint that populated it would make
    ``refresh_if_needed`` start rotating a token this flow never owns.

Fail-before: every test 404s against the current tree (neither route exists).

Run under the shared test DB lock (schema=aether_test ONLY):
    flock /tmp/aether-pytest.lock python3 -m pytest \
        tests/test_user_anthropic_oauth_mint.py -q
"""
from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import credential_vault as vault

START = "/agents/user/providers/anthropic/oauth/mint/start"
EXCHANGE = "/agents/user/providers/anthropic/oauth/mint/exchange"

#: Fake token material — NEVER a real secret. Shape mirrors the real
#: ``claude setup-token`` output anchors (ADR-ML-2 ruling #4).
FAKE_ACCESS = "sk-ant-oat01-FAKEuserMINTaccess000000000000deadbeef"
FAKE_REFRESH = "sk-ant-ort01-FAKEuserMINTrefresh00000000000deadbeef"


@pytest.fixture(autouse=True)
def _vault_key(monkeypatch):
    """Deterministic Fernet key so encrypt/decrypt agree within a test."""
    monkeypatch.setenv("AETHER_CREDENTIAL_KEY", vault.generate_key())


@pytest.fixture(autouse=True)
def _isolate_env_file(monkeypatch, tmp_path):
    """A credential save must NEVER touch the real repo-root ``.env``."""
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(tmp_path / "default.env"))


@pytest.fixture(autouse=True)
def _no_ambient_anthropic_env(monkeypatch):
    """Remove every env var that could resolve an Anthropic credential, so the
    stored row (or its absence) is the ONLY source these tests observe."""
    for var in (
        "ANTHROPIC_API_KEY", "AETHER_LLM_API_KEY", "AETHER_LLM_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN", "AETHER_ANTHROPIC_OAUTH_AUTHORIZE_URL",
        "AETHER_ANTHROPIC_OAUTH_CLIENT_ID", "AETHER_ANTHROPIC_OAUTH_SCOPE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _clean_oauth_tables():
    """None of ProviderCredential / AnthropicOAuthState / AnthropicOAuthToken /
    UserProviderCredential carry an FK to ``User``, so conftest's per-test
    ``_truncate_tables`` never touches them. Self-clean after each test so rows
    from one test never leak into the next."""
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


def _fake_token_response(*, expires_in: int = 31536000) -> dict:
    """A well-formed token-endpoint JSON body — the shape ``_post_token``
    returns on 2xx, and the single seam the happy paths monkeypatch."""
    return {
        "access_token": FAKE_ACCESS,
        "refresh_token": FAKE_REFRESH,
        "expires_in": expires_in,
        "scope": "user:inference",
    }


def _patch_token_endpoint(monkeypatch, response: dict) -> list[dict]:
    """Monkeypatch the ONE network seam; return the list of bodies POSTed."""
    from app.services import anthropic_oauth

    sent: list[dict] = []

    def _fake_post(body: dict) -> dict:
        sent.append(body)
        return response

    monkeypatch.setattr(anthropic_oauth, "_post_token", _fake_post)
    return sent


def _start_and_get_state(client, headers) -> str:
    resp = client.post(START, headers=headers)
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorizeUrl"]
    qs = parse_qs(urlsplit(url).query)
    assert qs.get("state"), url
    return qs["state"][0]


def _second_user_headers(client) -> dict[str, str]:
    """Register + log in a SECOND ordinary user on the same client."""
    creds = {
        "email": f"upo-other-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup3rSecret",
    }
    register = client.post("/auth/register", json=creds)
    assert register.status_code in (201, 409), register.text
    login = client.post("/auth/login", json=creds)
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deployment_credential_row() -> dict | None:
    """The shared ``ProviderCredential('anthropic')`` row, or None. Reads via
    the repository's masked accessor so no secret enters the test process."""
    from app.repositories.provider_credential import ProviderCredentialRepository

    try:
        return ProviderCredentialRepository().get_masked("anthropic")
    except Exception:  # noqa: BLE001 — a missing table means "no row", not an error
        return None


# ===========================================================================
# 1. start — any authenticated (NON-admin) user, real persisted PKCE state
# ===========================================================================


def test_user_start_returns_authorize_url_for_a_non_admin(
    client, auth_headers, test_user_id, _clean_oauth_tables
):
    """The whole point of UPO-1: an ORDINARY customer can begin the flow.

    The deployment-wide twin 403s here (AdminUser); this route must not.
    """
    resp = client.post(START, headers=auth_headers)
    assert resp.status_code == 200, resp.text

    url = resp.json()["authorizeUrl"]
    qs = parse_qs(urlsplit(url).query)
    assert qs.get("response_type") == ["code"], url
    assert qs.get("code_challenge_method") == ["S256"], url
    assert qs.get("client_id"), url
    assert qs.get("code_challenge"), url
    assert qs.get("state"), url

    # The PKCE verifier is persisted server-side, bound to THIS user, and is
    # never part of the URL handed to the browser.
    from app.db import get_connection, rows_to_dicts

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT "userId", "codeVerifier" FROM "AnthropicOAuthState" '
                'WHERE "stateToken" = %s',
                (qs["state"][0],),
            )
            rows = rows_to_dicts(cur)
    assert rows, "no AnthropicOAuthState row persisted for the returned state"
    assert rows[0]["userId"] == test_user_id
    assert rows[0]["codeVerifier"]
    assert rows[0]["codeVerifier"] not in url


def test_user_start_requires_authentication(client, _clean_oauth_tables):
    assert client.post(START).status_code in (401, 403)


def test_user_start_503_when_vault_key_absent(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """Fail closed and EARLY: without the vault key the Save that follows this
    flow cannot store the token, so the flow must not start at all."""
    monkeypatch.delenv("AETHER_CREDENTIAL_KEY", raising=False)
    resp = client.post(START, headers=auth_headers)
    assert resp.status_code == 503, resp.text


# ===========================================================================
# 2. exchange — returns the minted token so the dialog can populate the field
# ===========================================================================


def test_user_exchange_returns_the_minted_token_and_hint(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """Mint-and-fill: the caller who just authenticated receives their OWN
    subscription token once, so the OAuth-token field can be populated."""
    sent = _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)

    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"authcode-abc#{state}"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["token"] == FAKE_ACCESS
    assert body["authMode"] == "oauth_token"
    assert body["secretHint"] == vault.secret_hint(FAKE_ACCESS)
    assert body["expiresAt"], body
    assert body["scope"] == "user:inference"
    # The refresh token is NOT part of this contract — it is refresh material
    # for the operator flow and has no use in a browser.
    assert "refresh_token" not in body and "refreshToken" not in body

    # The upstream call really carried the authorization-code grant + PKCE.
    assert len(sent) == 1, sent
    assert sent[0]["grant_type"] == "authorization_code"
    assert sent[0]["code"] == "authcode-abc"
    assert sent[0]["state"] == state
    assert sent[0]["code_verifier"]


def test_user_exchange_response_is_not_cacheable(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """The one response in the app that carries a live token must never be
    stored by a browser, proxy or bfcache."""
    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)

    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert resp.status_code == 200, resp.text
    assert "no-store" in resp.headers.get("cache-control", "").lower()


# ===========================================================================
# 3. Privilege-escalation regression guards (the reason this route is separate)
# ===========================================================================


def test_user_exchange_does_not_write_deployment_credential(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """A customer minting their own token must NOT touch the shared row.

    The deployment-wide ``ProviderCredential('anthropic')`` row is what every
    bare ``claude-*`` run — including cron/background, which has no user id —
    resolves. Writing it from a non-admin route would let any customer silently
    re-bill the entire deployment to their own Claude subscription. That is the
    exact attack F-01's admin gate on the operator flow exists to prevent, so
    the per-user twin must be provably free of the same side effect.
    """
    assert _deployment_credential_row() is None, "precondition: no shared row yet"

    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)
    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert resp.status_code == 200, resp.text

    assert _deployment_credential_row() is None, (
        "per-user OAuth mint wrote the DEPLOYMENT-WIDE ProviderCredential row — "
        "this re-bills every bare claude-* run on the deployment to this customer"
    )


def test_user_exchange_does_not_write_anthropic_oauth_token_row(
    client, auth_headers, test_user_id, monkeypatch, _clean_oauth_tables
):
    """It must not populate the operator's auto-refresh token store either.

    ``AnthropicOAuthToken`` backs ``anthropic_oauth.refresh_if_needed``. A mint
    that wrote it would make the refresh hook start rotating — and marking
    needs_reauth on — a session this flow does not own.
    """
    from app.repositories.user_provider_credential import AnthropicOAuthTokenRepository

    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)
    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert resp.status_code == 200, resp.text

    assert AnthropicOAuthTokenRepository().get(test_user_id) is None, (
        "per-user OAuth mint wrote AnthropicOAuthToken — the refresh hook would "
        "then rotate a session this flow never stored"
    )


def test_user_exchange_stores_nothing_until_save(
    client, auth_headers, test_user_id, monkeypatch, _clean_oauth_tables
):
    """Mint does not persist; the EXISTING Save write path owns storage."""
    from app.repositories.user_provider_credential import (
        UserProviderCredentialRepository,
    )

    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)
    client.post(EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"})

    assert (
        UserProviderCredentialRepository().get_masked(test_user_id, "anthropic") is None
    ), "mint persisted a credential; Save must remain the single write path"


# ===========================================================================
# 4. Round trip — the minted token really is storable through Save
# ===========================================================================


def test_minted_token_round_trips_through_the_save_endpoint(
    client, auth_headers, test_user_id, monkeypatch, _clean_oauth_tables
):
    """End-to-end proof the feature works: mint -> Save -> stored + masked.

    Guards the contract seam between the two halves — a minted token whose
    prefix the credential validator rejects would make the whole flow dead on
    arrival at the Save click, which no unit test of either half would catch.
    """
    from app.repositories.user_provider_credential import (
        UserProviderCredentialRepository,
    )

    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)
    minted = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert minted.status_code == 200, minted.text
    body = minted.json()

    saved = client.put(
        "/agents/user/providers/anthropic/credential",
        headers=auth_headers,
        json={"authMode": body["authMode"], "secret": body["token"]},
    )
    assert saved.status_code == 200, saved.text

    stored = UserProviderCredentialRepository().get_masked(test_user_id, "anthropic")
    assert stored is not None, "Save did not persist the minted token"
    assert stored["authMode"] == "oauth_token"
    assert stored["secretHint"] == vault.secret_hint(FAKE_ACCESS)
    # The response never echoes the secret back.
    assert FAKE_ACCESS not in saved.text


def test_user_save_does_not_sync_oauth_token_into_deployment_env(
    client, auth_headers, monkeypatch, tmp_path, _clean_oauth_tables
):
    """A customer's Save must not overwrite CLAUDE_CODE_OAUTH_TOKEN.

    That env var is the operator's restart-survival copy of the shared
    deployment credential. Writing a customer's minted token into it would
    re-bill every bare claude-* run (including cron) to this customer — the
    same F-01 failure the mint-must-not-write-ProviderCredential guard covers
    for the other shared store.
    """
    env_file = tmp_path / ".env"
    env_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-OPERATORkeepme\n")
    monkeypatch.setenv("AETHER_ENV_FILE_PATH", str(env_file))

    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)
    minted = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert minted.status_code == 200, minted.text
    body = minted.json()

    saved = client.put(
        "/agents/user/providers/anthropic/credential",
        headers=auth_headers,
        json={"authMode": body["authMode"], "secret": body["token"]},
    )
    assert saved.status_code == 200, saved.text
    assert env_file.read_text() == "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-OPERATORkeepme\n"
    assert FAKE_ACCESS not in env_file.read_text()


# ===========================================================================
# 5. Honest failures — never a fake success, never another user's session
# ===========================================================================


def test_user_exchange_rejects_a_state_started_by_another_user(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """CSRF/state binding: user B cannot complete user A's authorization."""
    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)

    other = _second_user_headers(client)
    resp = client.post(EXCHANGE, headers=other, json={"pastedCode": f"code#{state}"})
    assert resp.status_code == 403, resp.text
    assert FAKE_ACCESS not in resp.text


def test_user_exchange_cross_user_attempt_does_not_burn_the_owners_state(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """P3-1 (RUN-20260818T0223Z third-party adversarial review): user B's
    rejected cross-user attempt — reproduced against the live prod route this
    finding names first, ``/oauth/mint/exchange`` — must NOT delete user A's
    state. A's own subsequent, legitimate retry with the SAME state must
    still succeed. Before the fix, ``AnthropicOAuthStateRepository.consume``
    deleted the row before the ownership check ran, so any observer of a live
    ``state`` value could permanently burn the real owner's in-flight connect
    attempt with one rejected request."""
    sent = _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)

    other = _second_user_headers(client)
    attack = client.post(EXCHANGE, headers=other, json={"pastedCode": f"code#{state}"})
    assert attack.status_code == 403, attack.text

    retry = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert retry.status_code == 200, (
        "user B's rejected cross-user attempt burned user A's still-pending "
        f"mint state — A's own legitimate retry failed: {retry.text}"
    )
    assert retry.json()["token"] == FAKE_ACCESS
    # Only the owner's own attempt ever reached the upstream token endpoint.
    assert len(sent) == 1, sent

    # Still genuinely single-use: a second legitimate redeem must now fail.
    replay = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert replay.status_code == 400, replay.text


@pytest.mark.parametrize("pasted", ["", "   ", "codeonly", "#stateonly", "code#"])
def test_user_exchange_422_on_malformed_paste(
    client, auth_headers, pasted, _clean_oauth_tables
):
    resp = client.post(EXCHANGE, headers=auth_headers, json={"pastedCode": pasted})
    assert resp.status_code == 422, resp.text


def test_user_exchange_400_on_unknown_or_replayed_state(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """A state token is single-use: the second submission must be refused."""
    _patch_token_endpoint(monkeypatch, _fake_token_response())
    state = _start_and_get_state(client, auth_headers)

    first = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert first.status_code == 200, first.text

    replay = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert replay.status_code == 400, replay.text


def test_user_exchange_422_when_anthropic_rejects_the_code(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """An upstream CODE-REJECTION is the caller's mistake, so it must surface
    as a 4xx whose body survives an intermediary (ML-adv-002) — not a 502."""
    from app.services import anthropic_oauth

    state = _start_and_get_state(client, auth_headers)

    def _reject(body: dict) -> dict:
        raise anthropic_oauth.OAuthExchangeError(
            "Anthropic token endpoint returned HTTP 400.", upstream_status=400
        )

    monkeypatch.setattr(anthropic_oauth, "_post_token", _reject)
    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"stale#{state}"}
    )
    assert resp.status_code == 422, resp.text


def test_user_exchange_502_on_a_genuine_network_failure(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """No response reached us at all — that is a gateway failure, not the
    caller's fault, and must not be reported as a bad code."""
    from app.services import anthropic_oauth

    state = _start_and_get_state(client, auth_headers)

    def _unreachable(body: dict) -> dict:
        raise anthropic_oauth.OAuthExchangeError(
            "Could not reach the Anthropic token endpoint: ConnectError."
        )

    monkeypatch.setattr(anthropic_oauth, "_post_token", _unreachable)
    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert resp.status_code == 502, resp.text


def test_user_exchange_502_on_an_unexpected_upstream_shape(
    client, auth_headers, monkeypatch, _clean_oauth_tables
):
    """A 2xx with no access_token is NEVER a success — defensive parse."""
    _patch_token_endpoint(monkeypatch, {"unexpected": "shape"})
    state = _start_and_get_state(client, auth_headers)

    resp = client.post(
        EXCHANGE, headers=auth_headers, json={"pastedCode": f"code#{state}"}
    )
    assert resp.status_code == 502, resp.text
    assert "token" not in resp.json()


def test_user_exchange_requires_authentication(client, _clean_oauth_tables):
    resp = client.post(EXCHANGE, json={"pastedCode": "code#state"})
    assert resp.status_code in (401, 403)
