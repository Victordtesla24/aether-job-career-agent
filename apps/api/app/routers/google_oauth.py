"""Google OAuth router — in-app Gmail connect (login + callback).

Mounted under ``/auth`` (see ``app.main``), so the public routes are
``/api/auth/google/login`` and ``/api/auth/google/callback`` — the callback URL
registered in the Google Cloud console.

``/google/login`` is authenticated (the app user's Bearer JWT), and embeds the
user id into a signed ``state`` token. ``/google/callback`` is unauthenticated
(Google's redirect carries no app JWT); it recovers the user from ``state``,
persists the tokens, and 302-redirects the browser back to the Email Center —
never returning a raw 500 to the user.
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from app.middleware.auth import CurrentUser
from app.repositories.gmail_account import GmailAccountRepository
from app.services.google_oauth import (
    OAuthError,
    build_consent_url,
    exchange_code,
    oauth_configured,
)

router = APIRouter()


def _post_auth_base() -> str:
    """Front-end origin the callback redirects back to. Falls back to a
    relative path (resolved by the browser against the current host)."""
    import os

    return (
        os.environ.get("PRODUCTION_URL")
        or os.environ.get("NEXTAUTH_URL")
        or ""
    ).rstrip("/")


def _redirect(connected: bool, error: str | None = None) -> RedirectResponse:
    target = f"{_post_auth_base()}/dashboard/email?gmail_connected={'1' if connected else '0'}"
    if error:
        target += f"&error={quote(error[:200])}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


@router.get("/google/login")
def google_login(current_user: CurrentUser) -> dict[str, str]:
    """Return the Google consent URL for the authenticated user to visit."""
    if not oauth_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth is not configured on the server",
        )
    try:
        return {"authUrl": build_consent_url(current_user["id"])}
    except OAuthError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/google/callback")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Google's redirect: exchange the code, persist tokens, bounce back
    to the Email Center with an honest success/failure flag."""
    if error:
        return _redirect(False, error)
    if not code or not state:
        return _redirect(False, "missing code or state")
    try:
        data = exchange_code(code, state)
    except OAuthError as exc:
        return _redirect(False, str(exc))
    except Exception as exc:  # noqa: BLE001 — never surface a 500 to the browser
        return _redirect(False, f"unexpected error: {exc}")
    repo = GmailAccountRepository()
    account_email = data["google_email"]
    existing = repo.get_by_email(data["user_id"], account_email)
    # A first-time link needs a refresh token (offline access). Re-connecting a
    # KNOWN account may legitimately return none — the stored token is kept — so
    # only reject when there is nothing to fall back on.
    if not data.get("refresh_token") and not existing:
        return _redirect(
            False,
            "no refresh token returned — revoke prior access at "
            "myaccount.google.com/permissions and reconnect",
        )
    # Link by (userId, accountEmail): rotates tokens on a known account, INSERTs
    # a brand-new row for a different account — never overwrites another inbox
    # (GAP-D2). GoogleCredential is intentionally left untouched (rollback anchor).
    repo.upsert_account(
        data["user_id"],
        account_email=account_email,
        refresh_token=data["refresh_token"],
        access_token=data["access_token"],
        access_token_expires_at=data["expires_at"],
        scopes=data["scopes"],
    )
    return _redirect(True)
