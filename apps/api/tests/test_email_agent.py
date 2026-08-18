"""P4 — Email Agent tests.

Unit tests (dependency-injected fakes, no DB) cover the send-gate discipline,
fabrication-guarded drafting and honest degradation. Integration tests
(client + auth + DB) cover the /agents/email/run endpoint end-to-end in replay
mode (email_triage fixture).
"""
from __future__ import annotations

import pytest

from app.agents.email_agent import EmailAgent, EmailAgentError


class _FakeApprovals:
    def __init__(self):
        self.created = []

    def create(self, user_id, type_, payload, application_id=None):
        self.created.append((user_id, type_, payload))
        return {"id": "appr-1", "status": "pending"}


class _FakeCreds:
    def __init__(self, connected=False):
        self._connected = connected

    def is_connected(self, user_id):
        return self._connected


class _FakeLLM:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def complete_json(self, prompt_name, system, user, **kwargs):
        self.calls += 1
        return self._payload


# ------------------------------------------------------------------ send mode
def test_send_mode_creates_pending_approval_without_sending():
    approvals = _FakeApprovals()
    agent = EmailAgent(approvals=approvals, credentials=_FakeCreds())
    res = agent.run(
        "u1", mode="send", to="r@x.com", subject="Re: role", body="Thanks!"
    )
    assert res.mode == "send"
    assert res.approval_id == "appr-1"
    assert res.approval_status == "pending"
    # It created an email_send approval and sent nothing.
    assert approvals.created[0][1] == "email_send"
    assert approvals.created[0][2]["to"] == "r@x.com"


def test_send_mode_requires_fields():
    agent = EmailAgent(approvals=_FakeApprovals(), credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="send", to="r@x.com")  # missing subject/body


def test_unknown_mode_raises():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="totally-unknown")


def test_draft_requires_thread_id():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="draft_reply")


# ---------------------------------------------------------- draft_follow_up
def test_draft_follow_up_requires_thread_id():
    agent = EmailAgent(credentials=_FakeCreds())
    with pytest.raises(EmailAgentError):
        agent.run("u1", mode="draft_follow_up")


def test_draft_follow_up_returns_follow_up_mode_and_guards():
    """The subsumed Follow-up capability: a silence-triggered nudge on an
    existing thread, grounded in the same evidence corpus + FabricationGuard."""
    clean = (
        "just following up on my earlier note about the delivery role. "
        "i remain available for a quick call this week whenever it helps."
    )
    fake_llm = _FakeLLM({"body": clean})
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "subject": "Delivery role",
        "messages": [{"body": "Thanks for applying — we'll be in touch."}],
    }
    agent._resume_text = lambda *a, **k: "Experienced delivery lead and program manager."  # type: ignore[assignment]
    res = agent.run("u1", mode="draft_follow_up", thread_id="t9")
    assert res.mode == "draft_follow_up"
    assert res.thread_id == "t9"
    assert res.draft.startswith("just following up")
    # Nothing fabricated → no flags.
    assert res.flagged == []


# ---------------------------------------------------------------- draft guard
def test_draft_flags_fabricated_claims():
    """A drafted reply that invents a metric/entity absent from the resume and
    the incoming email is flagged by the FabricationGuard."""
    fake_llm = _FakeLLM({"body": "I led the GCP migration achieving 99.99% uptime."})
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    # Bypass DB/PDF reads with grounded, GCP-free evidence.
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "subject": "Delivery role",
        "messages": [{"body": "We have an opening for a delivery lead."}],
    }
    agent._resume_text = lambda *a, **k: "Experienced delivery lead and program manager."  # type: ignore[assignment]
    res = agent.run("u1", mode="draft_reply", thread_id="t1")
    assert res.mode == "draft_reply"
    # GCP (acronym) and 99.99 (metric) are not in the evidence corpus.
    assert res.flagged, "expected fabricated tokens to be flagged"


# ------------------------------------------------------------- honest degrade
def test_apply_labels_degrades_when_not_connected():
    agent = EmailAgent(credentials=_FakeCreds(connected=False))
    res = agent.run("u1", mode="apply_labels", thread_id=None)
    assert res.degraded is True
    assert res.connected is False
    assert "Connect Gmail" in res.message


def test_triage_rate_limit_degrades_with_filter_categories_no_scores(monkeypatch):
    """Prod 2026-08-18: user-chosen Claude HTTP 429 must not 503 the Email Center.

    Sync + career-filter keep/hide already ran. Inventing scores or silently
    swapping models would violate honesty / ADR-ML-3. Persist deterministic
    categories, leave aiScore untouched, bill nothing, return degraded.
    """
    from app.agents import email_agent as email_agent_mod
    from app.services.llm_client import (
        LLM_RATE_LIMITED_USER_MESSAGE,
        LLMUnavailableError,
    )

    class _BoomLLM:
        def complete_json(self, *a, **k):
            raise LLMUnavailableError("LLM provider HTTP 429: rate_limit_error")

    class _Cur:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def __init__(self):
            self.cur = _Cur()

        def cursor(self):
            return self.cur

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    conn = _Conn()
    monkeypatch.setattr(email_agent_mod, "get_connection", lambda: conn)
    monkeypatch.setattr(
        "app.services.interview_ingest.ingest_inbound_for_user",
        lambda *a, **k: None,
    )

    agent = EmailAgent(llm=_BoomLLM(), credentials=_FakeCreds(connected=False))
    agent._threads = lambda uid: [  # type: ignore[method-assign]
        {
            "id": "t-int",
            "subject": "Interview invitation Tuesday 10am",
            "gmailThreadId": "g1",
            "messages": [
                {
                    "from": "Ada Recruiter",
                    "fromEmail": "ada@acme.com",
                    "body": "Please join the interview on Tuesday.",
                }
            ],
        }
    ]
    res = agent.run("u1", mode="triage")
    assert res.degraded is True
    assert res.llm_called is False
    assert res.triaged == 1
    assert res.categories.get("priority") == 1
    assert LLM_RATE_LIMITED_USER_MESSAGE in res.message
    assert "no AI scores" in res.message
    written = [params for _sql, params in conn.cur.calls if params]
    assert any(params[0] == "priority" and params[1] == "t-int" for params in written)


def _light_retry_capture_agent(monkeypatch):
    """Build an EmailAgent whose LLM always 429s and records the model id
    each ``complete_json`` call was made with. Shared by both light-retry
    invariant tests below (RUN-20260818T0223Z BATCH-2 §5)."""
    from app.services.llm_client import LLMUnavailableError

    captured: list[str | None] = []

    class _CaptureLLM:
        def complete_json(self, *a, **k):
            captured.append(k.get("model"))
            raise LLMUnavailableError("LLM provider HTTP 429: rate_limit_error")

    class _Cur:
        def execute(self, sql, params=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("app.agents.email_agent.get_connection", lambda: _Conn())
    monkeypatch.setattr(
        "app.services.interview_ingest.ingest_inbound_for_user",
        lambda *a, **k: None,
    )
    agent = EmailAgent(llm=_CaptureLLM(), credentials=_FakeCreds(connected=False))
    agent._threads = lambda uid: [  # type: ignore[method-assign]
        {
            "id": "t1",
            "subject": "Role at Acme",
            "messages": [{"from": "Ada", "fromEmail": "ada@acme.com", "body": "Intro call?"}],
        }
    ]
    return agent, captured


def test_triage_light_retry_calls_fallback_model_not_user_chosen(monkeypatch):
    """ADR-ML-3 + RUN-20260818T0223Z BATCH-2 §5: with no per-run model
    override the primary attempt runs on the REASONING tier's DEFAULT.
    AUD-ECON-2 retuned that default to the SAME id as ``FALLBACK_MODEL``
    (both ``claude-haiku-4-5``), so light_retry must NOT blindly reach for
    ``get_fallback_model()`` — that would resubmit to the model that just
    429'd, defeating the retry. ``fallback_for`` must step to the designated,
    genuinely-different, still-cheap alternate instead.
    """
    from app.agents.email_agent import gmail_sync_failure_message
    from app.services.llm_client import fallback_for, get_model

    monkeypatch.delenv("AETHER_MODEL_REASONING", raising=False)
    monkeypatch.delenv("AETHER_MODEL_FALLBACK", raising=False)
    agent, captured = _light_retry_capture_agent(monkeypatch)
    agent.run("u1", mode="triage")
    agent.run("u1", mode="triage", light_retry=True)
    assert captured[0] == get_model("REASONING") == "claude-haiku-4-5"
    assert captured[1] == fallback_for(get_model("REASONING")) == "claude-sonnet-4-6"
    assert captured[1] != captured[0]
    # Pin the helper used by the sync-fail path (tested below) so a rename
    # cannot silently drop the accessNotConfigured honesty.
    assert "reconnect" in gmail_sync_failure_message(RuntimeError("token expired")).lower()


def test_triage_light_retry_calls_fallback_model_when_primary_is_user_chosen(monkeypatch):
    """Companion case: a user-PINNED REASONING model (production 429s were
    observed on user-pinned Sonnet/Opus) rate-limits. The retry must land on
    the plain configured fallback (``get_fallback_model()``, Haiku) —
    genuinely different from the user's pinned model — exactly the
    pre-AUD-ECON-2 behaviour, unaffected by the default-tier retune."""
    from app.services.llm_client import get_fallback_model, user_model_context

    monkeypatch.delenv("AETHER_MODEL_FALLBACK", raising=False)
    agent, captured = _light_retry_capture_agent(monkeypatch)
    with user_model_context("claude-opus-4-8"):
        agent.run("u1", mode="triage")
        agent.run("u1", mode="triage", light_retry=True)
    assert captured[0] == "claude-opus-4-8"
    assert captured[1] == get_fallback_model() == "claude-haiku-4-5"
    assert captured[1] != captured[0]


def test_gmail_sync_failure_does_not_blame_oauth_for_api_not_configured():
    from app.agents.email_agent import gmail_sync_failure_message

    msg = gmail_sync_failure_message(
        RuntimeError('403 Forbidden with reason "accessNotConfigured"')
    )
    assert "reconnect" not in msg.lower()
    assert "google api" in msg.lower() or "google cloud" in msg.lower()


def test_insights_rate_limit_degrades_without_invented_score():
    from app.services.llm_client import LLM_RATE_LIMITED_USER_MESSAGE, LLMUnavailableError

    class _BoomLLM:
        def complete_json(self, *a, **k):
            raise LLMUnavailableError("LLM provider HTTP 429: rate_limit_error")

    agent = EmailAgent(llm=_BoomLLM(), credentials=_FakeCreds())
    agent._thread = lambda user_id, thread_id: {  # type: ignore[method-assign]
        "id": thread_id,
        "subject": "Intro call",
        "messages": [{"body": "Are you free Tuesday?"}],
    }
    res = agent.run("u1", mode="insights", thread_id="t1")
    assert res.degraded is True
    assert res.llm_called is False
    assert res.insights is None
    assert LLM_RATE_LIMITED_USER_MESSAGE in res.message


def test_draft_reply_rate_limit_degrades_without_invented_body():
    from app.services.llm_client import LLM_RATE_LIMITED_USER_MESSAGE, LLMUnavailableError

    class _BoomLLM:
        def complete_json(self, *a, **k):
            raise LLMUnavailableError("LLM provider HTTP 429: rate_limit_error")

    agent = EmailAgent(llm=_BoomLLM(), credentials=_FakeCreds())
    agent._thread = lambda user_id, thread_id: {  # type: ignore[method-assign]
        "id": thread_id,
        "subject": "Intro call",
        "messages": [{"body": "Are you free Tuesday?"}],
    }
    agent._resume_text = lambda *a, **k: "Delivery lead, 8 years."  # type: ignore[method-assign]
    res = agent.run("u1", mode="draft_reply", thread_id="t1")
    assert res.degraded is True
    assert res.llm_called is False
    assert res.draft == ""
    assert LLM_RATE_LIMITED_USER_MESSAGE in res.message


def test_email_agent_request_accepts_light_retry_flag():
    from app.routers.agents import EmailAgentRequest

    assert EmailAgentRequest().light_retry is False
    assert EmailAgentRequest(mode="triage", light_retry=True).light_retry is True


def test_email_agent_request_accepts_bulk_label_fields():
    """RUN-20260818T0223Z EC-ADV reconciliation: the bulk mark_read/apply_labels
    UI (page.tsx runInboxAction) posts thread_ids/add/remove/message_id, but
    EmailAgentRequest never declared them — pydantic's default extra='ignore'
    silently dropped every one before it reached the agent, so the landed
    bulk-label/bulk-mark-read buttons would 400 or no-op in production despite
    passing every agent-level unit test (which calls EmailAgent directly and
    never goes through this Pydantic layer). Not one of the review's five
    merge conflicts — a wiring gap in e9d6c890 itself, fixed while landing."""
    from app.routers.agents import EmailAgentRequest

    req = EmailAgentRequest(
        mode="apply_labels",
        thread_ids=["t1", "t2"],
        add=["Interested"],
        remove=["id-old"],
        message_id="m-1",
    )
    assert req.thread_ids == ["t1", "t2"]
    assert req.add == ["Interested"]
    assert req.remove == ["id-old"]
    assert req.message_id == "m-1"
    # Defaults stay None so `params = {k: v for ... if v is not None}` in
    # run_email_agent() omits them entirely for callers that never set them.
    assert EmailAgentRequest().thread_ids is None
    assert EmailAgentRequest().add is None
    assert EmailAgentRequest().remove is None
    assert EmailAgentRequest().message_id is None


# ---------------------------------------------- Email Center controls (EC-ADV)
def test_mark_read_and_trash_and_history_degrade_when_not_connected():
    agent = EmailAgent(credentials=_FakeCreds(connected=False))
    read = agent.run("u1", mode="mark_read")
    trash = agent.run("u1", mode="trash_automated")
    history = agent.run("u1", mode="thread_history", thread_id="t1")
    assert read.degraded is True and read.llm_called is False
    assert trash.degraded is True and trash.llm_called is False
    assert history.degraded is True and history.llm_called is False
    assert "Connect Gmail" in read.message
    assert "Connect Gmail" in trash.message
    assert "Connect Gmail" in history.message


class _FakeGmail:
    def __init__(self) -> None:
        self.trashed: list[str] = []
        self.modified: list[tuple[str, list[str], list[str]]] = []
        self.history_ids: list[str] = []

    def trash(self, message_id: str) -> dict:
        self.trashed.append(message_id)
        return {}

    def modify_labels(self, message_id: str, add=None, remove=None) -> dict:  # noqa: ANN001
        self.modified.append((message_id, list(add or []), list(remove or [])))
        return {}

    def ensure_label(self, name: str) -> str:
        return f"id-{name}"

    def get_thread_messages(self, gmail_thread_id: str) -> list[dict]:
        self.history_ids.append(gmail_thread_id)
        return [
            {
                "from": "Pat Lee",
                "fromEmail": "pat@acme.com",
                "body": "Are you free Thursday?",
                "receivedAt": "Mon, 17 Aug 2026",
                "gmailMessageId": "m-1",
            }
        ]


def test_mark_read_removes_unread_on_career_threads():
    gmail = _FakeGmail()
    agent = EmailAgent(credentials=_FakeCreds(connected=True), gmail=gmail)
    agent._threads = lambda user_id: [  # type: ignore[assignment]
        {
            "id": "t-unread",
            "labels": ["UNREAD", "INBOX"],
            "gmailMessageId": "gm-unread",
            "subject": "Interview with Acme",
            "messages": [{"from": "Pat", "fromEmail": "pat@acme.com", "body": "interview"}],
        }
    ]
    agent._update_thread_fields = lambda *a, **k: None  # type: ignore[assignment]
    res = agent.run("u1", mode="mark_read")
    assert res.llm_called is False
    assert res.marked_read == 1
    assert gmail.modified == [("gm-unread", [], ["UNREAD"])]


def test_trash_automated_spares_recruiter_threads():
    gmail = _FakeGmail()
    agent = EmailAgent(credentials=_FakeCreds(connected=True), gmail=gmail)
    agent._threads = lambda user_id: [  # type: ignore[assignment]
        {
            "id": "t-auto",
            "subject": "New jobs matching your alert",
            "gmailMessageId": "gm-auto",
            "messages": [
                {
                    "from": "LinkedIn Job Alerts",
                    "fromEmail": "jobalerts@linkedin.com",
                    "body": "New jobs this week",
                }
            ],
        },
        {
            "id": "t-rec",
            "subject": "Interview with Acme",
            "gmailMessageId": "gm-rec",
            "messages": [
                {"from": "Pat Lee", "fromEmail": "pat@acme.com", "body": "Can we interview Thursday?"}
            ],
        },
    ]
    agent._update_thread_fields = lambda *a, **k: None  # type: ignore[assignment]
    res = agent.run("u1", mode="trash_automated")
    assert res.llm_called is False
    assert res.trashed == 1
    assert gmail.trashed == ["gm-auto"]


def test_thread_history_returns_gmail_messages():
    gmail = _FakeGmail()
    agent = EmailAgent(credentials=_FakeCreds(connected=True), gmail=gmail)
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "gmailThreadId": "gt-1",
        "gmailAccountId": None,
    }
    res = agent.run("u1", mode="thread_history", thread_id="t1")
    assert res.llm_called is False
    assert gmail.history_ids == ["gt-1"]
    assert res.thread_messages[0]["from"] == "Pat Lee"


def test_apply_labels_bulk_thread_ids_dedupes_by_gmail_message_id():
    """The "Label all visible" bulk action (page.tsx bulkLabel) resolves every
    thread_id to its gmailMessageId and writes each UNIQUE message once — a
    re-synced duplicate thread pointing at the same Gmail message must not
    double the write."""
    gmail = _FakeGmail()
    agent = EmailAgent(credentials=_FakeCreds(connected=True), gmail=gmail)
    threads = {
        "t1": {"id": "t1", "gmailMessageId": "gm-1"},
        "t2": {"id": "t2", "gmailMessageId": "gm-2"},
        "t3": {"id": "t3", "gmailMessageId": "gm-1"},  # same message as t1
    }
    agent._thread = lambda user_id, thread_id: threads[thread_id]  # type: ignore[assignment]
    res = agent.run(
        "u1",
        mode="apply_labels",
        thread_ids=["t1", "t2", "t3"],
        add=["Interested"],
    )
    assert res.llm_called is False
    assert res.labels_applied == ["Interested"]
    assert sorted(mid for mid, _add, _rm in gmail.modified) == ["gm-1", "gm-2"]
    assert "2 message(s)" in res.message


def test_draft_parses_tone_when_present():
    clean = (
        "thank you for the note about the delivery role. "
        "i remain available for a call this week."
    )
    fake_llm = _FakeLLM(
        {
            "body": clean,
            "tone": {"enthusiasm": 55, "formality": 80, "detail": 40},
        }
    )
    agent = EmailAgent(llm=fake_llm, credentials=_FakeCreds())
    agent._thread = lambda user_id, thread_id: {  # type: ignore[assignment]
        "id": thread_id,
        "subject": "Delivery role",
        "messages": [{"body": "We have an opening for a delivery lead."}],
    }
    agent._resume_text = lambda *a, **k: "Experienced delivery lead and program manager."  # type: ignore[assignment]
    res = agent.run("u1", mode="draft_reply", thread_id="t1")
    assert res.tone == {"enthusiasm": 55, "formality": 80, "detail": 40}


# ------------------------------------------------------------- integration
def _make_draft(client, auth_headers, subject):
    resp = client.post(
        "/emails/draft",
        json={"subject": subject, "body": f"Body for {subject}"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_email_run_triage_classifies_local_threads(client, auth_headers):
    _make_draft(client, auth_headers, "Recruiter A")
    _make_draft(client, auth_headers, "Recruiter B")
    resp = client.post(
        "/agents/email/run", json={"mode": "triage"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mode"] == "triage"
    assert data["triaged"] == 2
    # No Gmail connected → honest degraded flag, but local threads still triaged.
    assert data["connected"] is False
    assert data["categories"]


def test_email_run_records_agent_run(client, auth_headers):
    _make_draft(client, auth_headers, "Recruiter C")
    client.post("/agents/email/run", json={"mode": "triage"}, headers=auth_headers)
    runs = client.get("/agents/runs", headers=auth_headers).json()
    assert any(r["agentName"] == "emailAgent" for r in runs)


def test_email_run_send_opens_pending_approval(client, auth_headers):
    resp = client.post(
        "/agents/email/run",
        json={
            "mode": "send",
            "to": "recruiter@acme.com",
            "subject": "Re: role",
            "body": "Thanks, let's talk.",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval_status"] == "pending"
    pending = client.get("/approvals?status=pending", headers=auth_headers).json()
    assert any(a["type"] == "email_send" for a in pending)


def test_email_run_draft_without_thread_is_422(client, auth_headers):
    resp = client.post(
        "/agents/email/run", json={"mode": "draft_reply"}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text
