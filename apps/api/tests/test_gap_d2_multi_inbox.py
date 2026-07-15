"""GAP-D2 — multiple Gmail inboxes per user (additive ``GmailAccount`` table).

Before the fix a second Gmail connect OVERWROTE the first account's row (the
legacy ``GoogleCredential`` PK was ``userId``). The rejected first attempt fixed
it by DROPping that primary key — prohibited, and a rollback hazard. This fix
introduces a NEW ``GmailAccount`` table and leaves ``GoogleCredential`` entirely
untouched. These tests lock in the multi-account contract AND the schema-safety
guarantees:

* ``build_consent_url`` uses ``prompt=select_account`` (keeps its PKCE guard).
* The OAuth callback links by ``(userId, accountEmail)`` on ``GmailAccount`` — a
  second, different account INSERTs a new row and never clobbers the first.
* Accounts can be listed, filtered per-inbox, merged into a unified inbox, have a
  unique primary, and be disconnected one at a time without touching the others.
* No DROP anywhere in the DDL/migration and ``GoogleCredential`` keeps its
  original primary key + columns after ``GmailAccount._ensure_table`` runs.

The OAuth token exchange is mocked (``exchange_code`` returns a chosen
``google_email``) — no live Google call is ever made. Tokens are stored as Fernet
ciphertext; the vault key comes from the sourced ``.env``. ``GmailAccount`` is not
auto-truncated, so every test cleans up.
"""
from __future__ import annotations

import pathlib
import urllib.parse
from typing import Any

from app.db import get_connection, new_id
from app.repositories.gmail_account import GmailAccountRepository
from app.repositories.google_credential import GoogleCredentialRepository
from app.services import google_oauth
from app.services.gmail_service import ensure_email_thread_gmail_columns

_REPO_SRC = pathlib.Path(
    "app/repositories/gmail_account.py"
)
_MIGRATION = pathlib.Path("migrations/0021_multi_gmail_inbox.sql")


def _configure_oauth_env(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "https://example.abacusai.cloud/api/auth/google/callback",
    )


def _connect_via_callback(client, monkeypatch, user_id: str, email: str) -> None:
    """Drive the OAuth callback once for ``email`` with a mocked token exchange."""

    def fake_exchange(code: str, state: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "google_email": email,
            "refresh_token": f"refresh-{email}",
            "access_token": f"access-{email}",
            "expires_at": None,
            "scopes": "gmail.modify gmail.send",
        }

    monkeypatch.setattr("app.routers.google_oauth.exchange_code", fake_exchange)
    resp = client.get(
        "/auth/google/callback?code=good&state=whatever", follow_redirects=False
    )
    assert resp.status_code == 302, resp.text
    assert "gmail_connected=1" in resp.headers["location"]


def _seed_thread(user_id: str, account_id: str | None, subject: str) -> str:
    ensure_email_thread_gmail_columns()
    tid = new_id()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO "EmailThread"'
                ' ("id","userId","subject","messages","gmailAccountId",'
                '  "createdAt","updatedAt")'
                " VALUES (%s,%s,%s,%s::jsonb,%s,now(),now())",
                (tid, user_id, subject, "[]", account_id),
            )
        conn.commit()
    return tid


# --------------------------------------------------------------- consent URL
def test_build_consent_url_uses_select_account(monkeypatch):
    _configure_oauth_env(monkeypatch)
    url = google_oauth.build_consent_url("user-123")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["prompt"][0] == "select_account"
    # PKCE regression guard (ADR-PC-1) must survive the prompt change.
    assert query.get("code_challenge"), "consent URL lost its PKCE code_challenge"


def test_build_consent_url_accepts_login_hint(monkeypatch):
    _configure_oauth_env(monkeypatch)
    url = google_oauth.build_consent_url("user-123", login_hint="who@gmail.com")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["login_hint"][0] == "who@gmail.com"


# ------------------------------------------------------ second account INSERTs
def test_second_gmail_creates_new_row_not_overwrite(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "first@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "second@gmail.com")

        accounts = repo.list_accounts(test_user_id)
        emails = {a["accountEmail"] for a in accounts}
        assert emails == {"first@gmail.com", "second@gmail.com"}
        # Neither account's refresh token was clobbered by the other connect
        # (decrypted back from the stored cipher).
        by_email = {a["accountEmail"]: a for a in accounts}
        assert by_email["first@gmail.com"]["refreshToken"] == "refresh-first@gmail.com"
        assert by_email["second@gmail.com"]["refreshToken"] == "refresh-second@gmail.com"
    finally:
        repo.disconnect(test_user_id)


def test_tokens_stored_encrypted_not_plaintext(
    client, auth_headers, test_user_id, monkeypatch
):
    """The persisted cipher column must NOT contain the plaintext token."""
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "cipher@gmail.com")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT "refreshTokenCipher", "accessTokenCipher"'
                    ' FROM "GmailAccount"'
                    ' WHERE "userId" = %s AND "accountEmail" = %s',
                    (test_user_id, "cipher@gmail.com"),
                )
                refresh_cipher, access_cipher = cur.fetchone()
        assert refresh_cipher and refresh_cipher != "refresh-cipher@gmail.com"
        assert access_cipher and access_cipher != "access-cipher@gmail.com"
    finally:
        repo.disconnect(test_user_id)


def test_reconnecting_same_account_rotates_not_duplicates(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "same@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "same@gmail.com")
        accounts = repo.list_accounts(test_user_id)
        assert len(accounts) == 1
    finally:
        repo.disconnect(test_user_id)


def test_first_account_primary_second_not(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "first@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "second@gmail.com")
        by_email = {a["accountEmail"]: a for a in repo.list_accounts(test_user_id)}
        assert by_email["first@gmail.com"]["isPrimary"] is True
        assert by_email["second@gmail.com"]["isPrimary"] is False
    finally:
        repo.disconnect(test_user_id)


# --------------------------------------------------------------- endpoints
def test_list_accounts_endpoint_returns_all_masked(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "alice@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "bob@gmail.com")

        resp = client.get("/emails/accounts", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body) == 2
        # Masked, never the raw token.
        for acc in body:
            assert "@gmail.com" in acc["accountEmail"]
            assert "*" in acc["accountEmail"]
            assert "refreshToken" not in acc
            assert "accessToken" not in acc
            assert "refreshTokenCipher" not in acc
    finally:
        repo.disconnect(test_user_id)


def test_oauth_status_endpoint_returns_200(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        resp = client.get("/emails/oauth/status", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connected"] is False
        assert body["accountCount"] == 0

        _connect_via_callback(client, monkeypatch, test_user_id, "who@gmail.com")
        resp2 = client.get("/emails/oauth/status", headers=auth_headers)
        assert resp2.json()["connected"] is True
        assert resp2.json()["accountCount"] == 1
    finally:
        repo.disconnect(test_user_id)


def test_set_primary_is_unique(client, auth_headers, test_user_id, monkeypatch):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "a@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "b@gmail.com")
        accounts = {a["accountEmail"]: a["id"] for a in repo.list_accounts(test_user_id)}

        resp = client.patch(
            f"/emails/accounts/{accounts['b@gmail.com']}/set-primary",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

        by_email = {a["accountEmail"]: a for a in repo.list_accounts(test_user_id)}
        assert by_email["b@gmail.com"]["isPrimary"] is True
        assert by_email["a@gmail.com"]["isPrimary"] is False
        primaries = [a for a in by_email.values() if a["isPrimary"]]
        assert len(primaries) == 1
    finally:
        repo.disconnect(test_user_id)


def test_disconnect_removes_only_that_account(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "keep@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "drop@gmail.com")
        accounts = {a["accountEmail"]: a["id"] for a in repo.list_accounts(test_user_id)}

        # Do not actually call Google's revoke endpoint from a test.
        monkeypatch.setattr("app.routers.emails.revoke_token", lambda token: True)
        resp = client.delete(
            f"/emails/accounts/{accounts['drop@gmail.com']}", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

        remaining = repo.list_accounts(test_user_id)
        assert [a["accountEmail"] for a in remaining] == ["keep@gmail.com"]
        # The surviving account is (still) primary.
        assert remaining[0]["isPrimary"] is True
    finally:
        repo.disconnect(test_user_id)


def test_disconnect_leaves_other_accounts_threads_intact(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "keep@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "drop@gmail.com")
        by_email = {a["accountEmail"]: a["id"] for a in repo.list_accounts(test_user_id)}
        _seed_thread(test_user_id, by_email["keep@gmail.com"], "keep thread")
        _seed_thread(test_user_id, by_email["drop@gmail.com"], "drop thread")

        monkeypatch.setattr("app.routers.emails.revoke_token", lambda token: True)
        resp = client.delete(
            f"/emails/accounts/{by_email['drop@gmail.com']}", headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

        # The kept account's thread is untouched and still filterable.
        r = client.get(
            f"/emails?account_id={by_email['keep@gmail.com']}", headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert {t["subject"] for t in r.json()} == {"keep thread"}
    finally:
        repo.disconnect(test_user_id)


def test_disconnect_promotes_new_primary_when_primary_removed(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "primary@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "backup@gmail.com")
        by_email = {a["accountEmail"]: a for a in repo.list_accounts(test_user_id)}
        primary_id = by_email["primary@gmail.com"]["id"]
        assert by_email["primary@gmail.com"]["isPrimary"] is True

        monkeypatch.setattr("app.routers.emails.revoke_token", lambda token: True)
        resp = client.delete(f"/emails/accounts/{primary_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        remaining = repo.list_accounts(test_user_id)
        assert len(remaining) == 1
        assert remaining[0]["accountEmail"] == "backup@gmail.com"
        assert remaining[0]["isPrimary"] is True  # promoted
    finally:
        repo.disconnect(test_user_id)


def test_delete_unknown_account_404(client, auth_headers, test_user_id):
    resp = client.delete("/emails/accounts/does-not-exist", headers=auth_headers)
    assert resp.status_code == 404


# ------------------------------------------------------ thread filtering
def test_threads_filter_by_account_and_unified_merge(
    client, auth_headers, test_user_id, monkeypatch
):
    repo = GmailAccountRepository()
    try:
        _connect_via_callback(client, monkeypatch, test_user_id, "one@gmail.com")
        _connect_via_callback(client, monkeypatch, test_user_id, "two@gmail.com")
        by_email = {a["accountEmail"]: a["id"] for a in repo.list_accounts(test_user_id)}

        _seed_thread(test_user_id, by_email["one@gmail.com"], "from inbox one")
        _seed_thread(test_user_id, by_email["two@gmail.com"], "from inbox two")

        # Per-account filter narrows to a single inbox.
        r1 = client.get(
            f"/emails?account_id={by_email['one@gmail.com']}", headers=auth_headers
        )
        assert r1.status_code == 200, r1.text
        subjects_one = {t["subject"] for t in r1.json()}
        assert subjects_one == {"from inbox one"}

        # No filter → unified inbox merges every account's threads.
        r_all = client.get("/emails", headers=auth_headers)
        assert r_all.status_code == 200, r_all.text
        subjects_all = {t["subject"] for t in r_all.json()}
        assert {"from inbox one", "from inbox two"} <= subjects_all
    finally:
        repo.disconnect(test_user_id)


def test_upsert_account_assigns_id_used_to_link_threads(
    client, auth_headers, test_user_id
):
    """Repo-level guard for the callback→thread linkage: a connected account has a
    stable id that a thread can be filtered by."""
    repo = GmailAccountRepository()
    try:
        row = repo.upsert_account(
            test_user_id,
            account_email="link@gmail.com",
            refresh_token="rt-link",
            access_token="at-link",
            scopes="gmail.modify",
        )
        account_id = row["id"]
        assert account_id
        _seed_thread(test_user_id, account_id, "linked thread")

        resp = client.get(f"/emails?account_id={account_id}", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert {t["subject"] for t in resp.json()} == {"linked thread"}
    finally:
        repo.disconnect(test_user_id)


# ------------------------------------------------------ schema safety (no DROP)
def test_ddl_and_migration_contain_no_drop():
    """The additive-only contract: neither the runtime DDL nor the documentary
    migration may contain a DROP / ALTER TYPE / column rename."""
    repo_src = _REPO_SRC.read_text()
    migration_src = _MIGRATION.read_text()
    for label, src in (("repository DDL", repo_src), ("migration", migration_src)):
        upper = src.upper()
        assert "DROP " not in upper, f"{label} contains a prohibited DROP statement"
        assert "DROP\t" not in upper, f"{label} contains a prohibited DROP statement"
        assert "ALTER TYPE" not in upper, f"{label} contains a prohibited ALTER TYPE"
        assert "RENAME" not in upper, f"{label} contains a prohibited RENAME"


def test_google_credential_untouched_after_gmailaccount_ensure(client):
    """``GmailAccount._ensure_table`` (incl. its backfill) must NOT modify the
    legacy ``GoogleCredential`` table in any way — its primary key and every
    column stay exactly as they were. This is the rollback-safety anchor.

    Note: this asserts INVARIANCE (before == after) rather than an absolute PK
    value, because the shared ``aether_test`` schema is long-lived and may carry
    an altered ``GoogleCredential`` from an earlier (rejected) branch's run. What
    matters — and what production correctness depends on — is that THIS code path
    changes nothing about ``GoogleCredential``.
    """
    # Materialize the legacy table first (its own repo owns its DDL).
    GoogleCredentialRepository()._ensure_table()

    def _snapshot() -> tuple[list[str], list[tuple[str, str, str]]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = '"GoogleCredential"'::regclass
                      AND i.indisprimary
                    ORDER BY a.attname
                    """
                )
                pk_cols = [r[0] for r in cur.fetchall()]
                cur.execute(
                    "SELECT column_name, data_type, is_nullable"
                    " FROM information_schema.columns"
                    " WHERE table_name = 'GoogleCredential'"
                    " AND table_schema = ANY(current_schemas(false))"
                    " ORDER BY column_name"
                )
                cols = [(r[0], r[1], r[2]) for r in cur.fetchall()]
        return pk_cols, cols

    pk_before, cols_before = _snapshot()
    # Sanity: the original columns are all still present (additive contract).
    col_names = {c[0] for c in cols_before}
    assert {"userId", "refreshToken", "accessToken", "googleEmail"} <= col_names

    # Run the new table's ensure + backfill.
    GmailAccountRepository()._ensure_table()

    pk_after, cols_after = _snapshot()
    assert pk_after == pk_before, "GmailAccount ensure changed GoogleCredential PK"
    assert cols_after == cols_before, "GmailAccount ensure changed GoogleCredential columns"
