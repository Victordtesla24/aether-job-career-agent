"""GOLD-MASTER-V2 §15 step 2 — failing tests for three confirmed defects:

- GM2-EMAIL-001 (HIGH): the Gmail account-status surface reports "Connected"
  even when the stored OAuth token is actually expired/revoked.
- GM2-EMAIL-002 (MEDIUM-HIGH): AI Draft Reply reverses sender/recipient
  direction when the thread's newest message is the account owner's OWN
  prior reply.
- GM2-AGENTS-001 (HIGH): the Agents-screen catalog contains a user-visible
  entry (Submission Agent) permanently stuck in an unimplemented "planned"
  state, violating §4 ("no planned/coming-soon feature at exit").

Written BEFORE any fix. test-author never implements fixes — a "failing"
test that passes against current code is itself a defect in the test (fixed
here, not silenced). Verbatim failing-run evidence:
uat/reports/evidence/gold-master-v2/waves/EMAIL-AGENTS-failing-tests.md
"""
from __future__ import annotations

from app.repositories.gmail_account import GmailAccountRepository


# ===========================================================================
# GM2-EMAIL-001 — connection status must reflect REAL token validity, not
# merely the presence of a stored credential row.
#
# Seam: GET /workspaces/emails/inbox (app/routers/workspaces.py `email_inbox`)
# builds its `accounts[]` array purely from `GmailAccountRepository
# .list_accounts()` row existence (`"status": "connected"` is a LITERAL,
# unconditional string — see workspaces.py around the `if account_rows:`
# block) even though the very same request already attempted a real sync via
# `GmailService(...).sync_threads_to_db()` a few lines above and silently
# swallowed a `GmailAuthError`/`GmailNotConnectedError` failure
# (`except (GmailAuthError, GmailNotConnectedError): pass`). Production
# evidence (ML-email-002,
# uat/reports/evidence/gold-master-v2/screens/email-screen-test.md):
# `POST /agents/email/run {"mode":"triage"}` returns
# `"connected": false, "degraded": true, "message": "Gmail sync failed —
# reconnect your account. (Gmail authorization expired or was revoked —
# reconnect your account.)"` while `GET /workspaces/emails/inbox`'s
# `accounts[].status` stays "connected" regardless — reproduced twice on
# live production.
# ===========================================================================


def _seed_gmail_account(user_id: str, email: str = "owner@gmail.com") -> dict:
    repo = GmailAccountRepository()
    return repo.upsert_account(
        user_id,
        account_email=email,
        refresh_token=f"refresh-{email}",
        scopes="gmail.modify",
    )


def _fake_gmail_service_factory(outcome: str):
    """A GmailService stand-in.

    ``outcome="auth_error"`` raises the EXACT exception
    (``app.services.gmail_service.GmailAuthError``) a real expired/revoked
    Google grant raises from ``GmailService._credentials`` after a failed
    token refresh — this is not a synthetic error type, it is the real one.
    ``outcome="ok"`` mirrors a genuinely healthy sync (mark_synced, like the
    real ``sync_threads_to_db``).
    """

    class _FakeGmailService:
        def __init__(self, user_id, account_id=None, creds_repo=None):
            self._user_id = user_id
            self._account_id = account_id

        def sync_threads_to_db(self, user_id=None, query=None, max_results=25):
            if outcome == "auth_error":
                from app.services.gmail_service import GmailAuthError

                raise GmailAuthError(
                    "Gmail authorization expired or was revoked — "
                    "reconnect your account."
                )
            GmailAccountRepository().mark_synced(self._account_id)
            return 0

    return _FakeGmailService


def test_inbox_account_status_honestly_reflects_expired_token(
    client, auth_headers, test_user_id, monkeypatch
):
    """GM2-EMAIL-001, VERIFIED TWICE on production: an account whose Gmail
    grant just failed to refresh (real ``GmailAuthError``, the same class a
    revoked/expired token raises) must NOT be reported as
    ``"status": "connected"`` by the account-status surface the Email Center
    reads on load.
    """
    _seed_gmail_account(test_user_id)
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService",
        _fake_gmail_service_factory("auth_error"),
    )
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        accounts = resp.json()["accounts"]
        assert len(accounts) == 1, accounts
        status = accounts[0]["status"]
        assert status != "connected", (
            "the account list reports 'connected' even though THIS SAME "
            "request's own sync attempt just failed with an expired/revoked "
            f"Gmail grant (GM2-EMAIL-001) — got status={status!r}, "
            f"account={accounts[0]!r}"
        )
    finally:
        GmailAccountRepository().disconnect(test_user_id)


def test_inbox_account_status_stays_connected_for_a_genuinely_valid_token(
    client, auth_headers, test_user_id, monkeypatch
):
    """Inverse / false-positive guard (required by the brief): a genuinely
    healthy, successfully-synced Gmail account must still read "connected" —
    whatever fixes GM2-EMAIL-001 must not turn every account into a false
    "disconnected". This is expected to PASS both before and after the fix
    (recorded as such in the evidence artifact, not a defect)."""
    _seed_gmail_account(test_user_id)
    monkeypatch.setattr(
        "app.services.gmail_service.GmailService",
        _fake_gmail_service_factory("ok"),
    )
    monkeypatch.setenv("AETHER_EMAIL_SYNC_TTL_SECONDS", "120")
    try:
        resp = client.get("/workspaces/emails/inbox", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        accounts = resp.json()["accounts"]
        assert len(accounts) == 1, accounts
        assert accounts[0]["status"] == "connected", accounts[0]
    finally:
        GmailAccountRepository().disconnect(test_user_id)


# ===========================================================================
# GM2-EMAIL-002 — AI Draft Reply must ground its draft in the COUNTERPARTY's
# last message, never the account owner's own prior reply.
#
# Seam: EmailAgent._compose_draft (app/agents/email_agent.py) builds its
# prompt from ``self._latest_body(thread)``, which is unconditionally
# ``messages[-1]["body"]`` — it never reads each message's ``role`` (already
# present on every stored EmailThread message: "received" for real inbound
# Gmail mail — app/services/gmail_service.py `_normalize_thread` — vs
# "reply"/"draft" for the candidate's own outbound text —
# app/routers/emails.py `reply_to_thread`/`create_draft`). When the thread's
# newest message is the candidate's own prior reply, this feeds the
# candidate's OWN words to the LLM labelled "Incoming email:" — exactly why
# production (ML-email-003 / GM2-EMAIL-002, verified 3x) generated a draft
# written FROM the counterparty TO the candidate, addressed "Hi Vikram" and
# signed "Andrew Woodhouse".
# ===========================================================================

_COUNTERPARTY_MARKER = "please confirm your availability for the interview panel"
_OWN_REPLY_MARKER = "yes tuesday 2pm works for me thanks"


class _FakeCreds:
    def __init__(self, connected: bool = True):
        self._connected = connected

    def is_connected(self, user_id):
        return self._connected


class _CapturingLLM:
    """Records every ``complete_json`` call (prompt_name/system/user) and
    returns a fixed, evidence-safe reply body — the test inspects what was
    SENT to the model, not what a real model would say back."""

    def __init__(self, body: str = "Thank you for reaching out — noted, thanks."):
        self._body = body
        self.calls: list[dict] = []

    def complete_json(self, prompt_name, system, user, **kwargs):
        self.calls.append({"prompt_name": prompt_name, "system": system, "user": user})
        return {"body": self._body}


def _thread_with_own_reply_newest() -> dict:
    """Newest message (index -1) is the CANDIDATE's own prior reply — the
    exact production shape (Vikram's own reply to Andrew is the newest
    message, Andrew's original request is the earlier one)."""
    return {
        "id": "t-own-newest",
        "subject": "Re: Interview invitation",
        "messages": [
            {
                "role": "received",
                "from": "Andrew Woodhouse",
                "fromEmail": "andrew@acme.com",
                "body": f"Hi Vikram, {_COUNTERPARTY_MARKER}. Kind regards, Andrew",
            },
            {
                "role": "reply",
                "body": _OWN_REPLY_MARKER.capitalize() + ".",
            },
        ],
    }


def _thread_with_counterparty_newest() -> dict:
    """Contrast case: the newest message genuinely IS the counterparty's —
    the direction that already works correctly in production and must keep
    working."""
    return {
        "id": "t-counterparty-newest",
        "subject": "Re: Interview invitation",
        "messages": [
            {
                "role": "reply",
                "body": "Could you share a bit more detail on the role?",
            },
            {
                "role": "received",
                "from": "Andrew Woodhouse",
                "fromEmail": "andrew@acme.com",
                "body": f"Hi Vikram, {_COUNTERPARTY_MARKER}. Kind regards, Andrew",
            },
        ],
    }


def test_draft_reply_grounds_on_counterparty_message_when_newest_is_own_reply():
    """GM2-EMAIL-002, VERIFIED 3x on production: when the thread's newest
    message is the account owner's OWN prior reply, `draft_reply` must still
    build its prompt from the COUNTERPARTY's last message — never present the
    candidate's own outbound text as the "Incoming email" being replied to.
    """
    from app.agents.email_agent import EmailAgent

    fake_llm = _CapturingLLM()
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    thread = _thread_with_own_reply_newest()
    agent._thread = lambda user_id, thread_id: thread  # type: ignore[assignment]
    agent._resume_text = lambda *a, **k: (  # type: ignore[assignment]
        "Experienced candidate available Tuesdays for interviews."
    )

    agent.run("u1", mode="draft_reply", thread_id="t-own-newest")

    assert fake_llm.calls, "draft_reply never reached the LLM"
    prompt = fake_llm.calls[0]["user"].lower()
    assert _COUNTERPARTY_MARKER in prompt, (
        "the counterparty's real message must ground the draft prompt as "
        f"the email being replied to, but it is missing. prompt={prompt!r}"
    )
    assert _OWN_REPLY_MARKER not in prompt, (
        "the candidate's OWN prior reply was fed to the LLM as the "
        "'Incoming email' being replied to — this is the exact "
        f"GM2-EMAIL-002 direction-reversal defect. prompt={prompt!r}"
    )


def test_draft_reply_grounds_on_counterparty_message_when_it_is_newest():
    """Contrast case (must keep working): when the thread's newest message
    genuinely is the counterparty's, the draft is already grounded correctly
    — protect that behaviour. Expected to PASS both before and after the fix
    (recorded as such in the evidence artifact, not a defect)."""
    from app.agents.email_agent import EmailAgent

    fake_llm = _CapturingLLM()
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    thread = _thread_with_counterparty_newest()
    agent._thread = lambda user_id, thread_id: thread  # type: ignore[assignment]
    agent._resume_text = lambda *a, **k: (  # type: ignore[assignment]
        "Experienced candidate available Tuesdays for interviews."
    )

    agent.run("u1", mode="draft_reply", thread_id="t-counterparty-newest")

    assert fake_llm.calls, "draft_reply never reached the LLM"
    prompt = fake_llm.calls[0]["user"].lower()
    assert _COUNTERPARTY_MARKER in prompt, prompt


# ===========================================================================
# GM2-AGENTS-001 — no user-visible catalog entry may be left in a
# planned/unimplemented state (§4).
#
# Seam: GET /agents/catalog (app/routers/agents.py `agent_catalog`) derives
# `status="planned"` for every AGENT_CATALOG entry whose `backend` is
# `None`. The Submission Agent card (key "submission") has `backend=None`
# and therefore reports `status="planned"` forever — a real, user-visible
# roadmap card with literally no implementation behind it.
#
# NOTE: this is deliberately NOT about how the planned state is presented —
# test_agents_screen.py::test_catalog_lists_full_roster_with_defaults already
# established the disabled-card / "Not yet available" treatment is honest,
# not deceptive (and test_test_run_model_never_null_for_planned_agent
# tolerates a planned card existing at all, skipping if none remain). The
# defect asserted here is the mere EXISTENCE of a user-visible entry with no
# backend — written generically so it also catches any FUTURE planned entry,
# not only "submission" by name.
# ===========================================================================


def test_agent_catalog_has_no_user_visible_planned_entries(client, auth_headers):
    """GM2-AGENTS-001 (HIGH): §4 forbids any feature remaining in a
    planned/coming-soon state at exit — the catalog a user is SHOWN must
    contain no `status == "planned"` entries."""
    res = client.get("/agents/catalog", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    planned = sorted(a["key"] for a in body["agents"] if a["status"] == "planned")
    assert planned == [], (
        "the agent catalog a user sees must contain no unimplemented "
        f"('planned') entries, but found: {planned} (GM2-AGENTS-001 — "
        "Submission Agent has backend=None and is shown to every user)"
    )
    assert body["counts"]["planned"] == 0, body["counts"]
