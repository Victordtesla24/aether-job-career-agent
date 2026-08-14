"""MON-002 — stop the Gmail-403 hammering with an honest credential state.

EVIDENCE (uat/reports/evidence/orch-exec/MON-RESIDUALS-EVIDENCE-2026-08-14.md,
Probe 1): ``GET /workspaces/emails/inbox`` (``apps/api/app/routers/workspaces.py``
``email_inbox``) does an INLINE Gmail sync whose failure path used to be a bare
``except Exception: pass``. An expired/revoked Google credential (or, as
confirmed by the evidence, a scope mismatch surfacing as a Google 403
"insufficientPermissions") produced ~50 403s/hour because EVERY page poll
past the 120s freshness TTL retried the sync and silently swallowed the
error — no backoff, no log, no honest status.

Seam / mocking pattern mirrors ``test_gm2_email_agents_findings.py``:
monkeypatch ``app.services.gmail_service.GmailService`` with a stand-in whose
``sync_threads_to_db`` raises the real exception the sync path would raise,
then hit ``GET /workspaces/emails/inbox`` through the real ``client`` fixture.
"""
from __future__ import annotations

import time

from app.repositories.gmail_account import GmailAccountRepository
from app.routers import workspaces as workspaces_module


def _seed_gmail_account(user_id: str, email: str = "owner@gmail.com") -> dict:
    repo = GmailAccountRepository()
    return repo.upsert_account(
        user_id,
        account_email=email,
        refresh_token=f"refresh-{email}",
        scopes="gmail.modify",
    )


class _CountingFakeGmailService:
    """Stand-in for ``GmailService`` that counts constructions (a call to
    ``GmailService(...)`` is the thing MON-002's backoff must prevent — the
    ctor is where every real sync attempt begins) and raises a real Google
    403 "insufficientPermissions" ``GmailError`` on every ``sync_threads_to_db``
    call, exactly as ``GmailService.list_threads`` wraps the underlying
    ``googleapiclient.errors.HttpError`` (gmail_service.py:557-558) when the
    stored token has a scope mismatch — this is NOT one of the two types
    (``GmailAuthError``, ``GmailNotConnectedError``) the router used to
    special-case, so it is the exact shape that used to fall into the bare
    ``except Exception: pass``.
    """

    call_count = 0

    def __init__(self, user_id, account_id=None, creds_repo=None):
        type(self).call_count += 1
        self._user_id = user_id
        self._account_id = account_id

    def sync_threads_to_db(self, user_id=None, query=None, max_results=25):
        from app.services.gmail_service import GmailError

        raise GmailError(
            'Gmail thread list failed: <HttpError 403 when requesting '
            'https://gmail.googleapis.com/gmail/v1/users/me/threads?... '
            'returned "Insufficient Permission". Details: "[{\'message\': '
            '\'Insufficient Permission\', \'domain\': \'global\', \'reason\': '
            '\'insufficientPermissions\'}]">'
        )

    @classmethod
    def reset(cls) -> None:
        cls.call_count = 0


class _OkFakeGmailService:
    """A genuinely healthy sync — mirrors the real ``sync_threads_to_db``
    success path (marks the account synced, returns a row count)."""

    call_count = 0

    def __init__(self, user_id, account_id=None, creds_repo=None):
        type(self).call_count += 1
        self._user_id = user_id
        self._account_id = account_id

    def sync_threads_to_db(self, user_id=None, query=None, max_results=25):
        GmailAccountRepository().mark_synced(self._account_id)
        return 0

    @classmethod
    def reset(cls) -> None:
        cls.call_count = 0


def _clear_backoff(user_id: str) -> None:
    workspaces_module._gmail_sync_backoff.pop(user_id, None)


def test_second_call_within_backoff_window_skips_the_sync_attempt(
    client, auth_headers, test_user_id, monkeypatch
):
    """(1) A Google 403 puts the user in backoff: the SECOND ``GET
    /workspaces/emails/inbox`` within the window must not construct
    ``GmailService`` again (call count stays 1) — this is the hammering
    MON-002 exists to stop."""
    _seed_gmail_account(test_user_id)
    _CountingFakeGmailService.reset()
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService", _CountingFakeGmailService
    )
    # TTL is irrelevant here since lastSyncedAt is never stamped on failure —
    # every request would normally re-attempt the sync regardless of TTL.
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp1 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp1.status_code == 200, resp1.text
        assert _CountingFakeGmailService.call_count == 1, (
            "first request should attempt exactly one sync"
        )

        resp2 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp2.status_code == 200, resp2.text
        assert _CountingFakeGmailService.call_count == 1, (
            "second GET within the backoff window constructed GmailService "
            f"again (count={_CountingFakeGmailService.call_count}) — MON-002 "
            "backoff did not skip the inline sync attempt"
        )
    finally:
        _clear_backoff(test_user_id)
        GmailAccountRepository().disconnect(test_user_id)


def test_backoff_expires_and_sync_is_attempted_again(
    client, auth_headers, test_user_id, monkeypatch
):
    """(2) Once the backoff window has elapsed, the next ``GET
    /workspaces/emails/inbox`` attempts the sync again (call count
    increments) instead of skipping forever."""
    _seed_gmail_account(test_user_id)
    _CountingFakeGmailService.reset()
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService", _CountingFakeGmailService
    )
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp1 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp1.status_code == 200, resp1.text
        assert _CountingFakeGmailService.call_count == 1

        resp2 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp2.status_code == 200, resp2.text
        assert _CountingFakeGmailService.call_count == 1, "still in backoff"

        # Simulate the ~15min window elapsing without a real sleep: rewrite
        # the backoff deadline (monotonic-clock float) to the past. Direct
        # module-state manipulation mirrors this codebase's existing TTL-cache
        # test idiom (see conftest's apply_channel_resolver cache reset).
        deadline, account_ids = workspaces_module._gmail_sync_backoff[test_user_id]
        workspaces_module._gmail_sync_backoff[test_user_id] = (
            time.monotonic() - 1,
            account_ids,
        )

        resp3 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp3.status_code == 200, resp3.text
        assert _CountingFakeGmailService.call_count == 2, (
            "expired backoff should have let the sync attempt run again "
            f"(count={_CountingFakeGmailService.call_count})"
        )
    finally:
        _clear_backoff(test_user_id)
        GmailAccountRepository().disconnect(test_user_id)


def test_response_carries_the_honest_auth_error_state(
    client, auth_headers, test_user_id, monkeypatch
):
    """(3) The response payload the Email Center page already consumes
    (``accounts[].status``, the field ``apps/web/src/app/dashboard/email/page.tsx``
    reads for connection state) must never say "connected" while the account
    is in backoff — neither on the failing request nor on a subsequent
    request that skips the sync because backoff is active."""
    _seed_gmail_account(test_user_id)
    _CountingFakeGmailService.reset()
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService", _CountingFakeGmailService
    )
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp1 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp1.status_code == 200, resp1.text
        accounts1 = resp1.json()["accounts"]
        assert len(accounts1) == 1, accounts1
        assert accounts1[0]["status"] != "connected", accounts1[0]

        # Backoff-skip request: the honest state must persist, not silently
        # revert to "connected" just because no sync was attempted.
        resp2 = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp2.status_code == 200, resp2.text
        accounts2 = resp2.json()["accounts"]
        assert accounts2[0]["status"] != "connected", accounts2[0]
    finally:
        _clear_backoff(test_user_id)
        GmailAccountRepository().disconnect(test_user_id)


def test_successful_sync_clears_and_never_sets_backoff(
    client, auth_headers, test_user_id, monkeypatch
):
    """(4a) A genuinely successful sync never enters backoff at all."""
    _seed_gmail_account(test_user_id)
    _OkFakeGmailService.reset()
    monkeypatch.setattr("app.services.gmail_service.GmailService", _OkFakeGmailService)
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["accounts"][0]["status"] == "connected"
        assert test_user_id not in workspaces_module._gmail_sync_backoff, (
            "a successful sync must never enter backoff"
        )
    finally:
        _clear_backoff(test_user_id)
        GmailAccountRepository().disconnect(test_user_id)


def test_successful_sync_clears_a_previously_entered_backoff(
    client, auth_headers, test_user_id, monkeypatch
):
    """(4b) If backoff was entered earlier and has since expired, a
    subsequent SUCCESSFUL sync clears it (the credential works again — the
    honest state must flip back to "connected", and the stale backoff entry
    must not linger)."""
    _seed_gmail_account(test_user_id)
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        # Pre-seed an already-EXPIRED backoff entry, as if a prior request
        # had failed and the window has since elapsed.
        workspaces_module._gmail_sync_backoff[test_user_id] = (
            time.monotonic() - 1,
            frozenset({"some-account-id"}),
        )

        _OkFakeGmailService.reset()
        monkeypatch.setattr(
            "app.services.gmail_service.GmailService", _OkFakeGmailService
        )
        resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["accounts"][0]["status"] == "connected"
        assert test_user_id not in workspaces_module._gmail_sync_backoff, (
            "a successful sync must clear a previously-entered backoff entry"
        )
    finally:
        _clear_backoff(test_user_id)
        GmailAccountRepository().disconnect(test_user_id)
