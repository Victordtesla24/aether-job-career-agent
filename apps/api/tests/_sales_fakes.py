"""Shared fakes for the S1–S4 sales-agent suites.

Extends the proven ``FakeGmail`` seam from ``tests.test_sales_agent`` with:

* :class:`WindowedGmail` — a faithful Gmail simulation for the backlog walk:
  it honours the ``after:``/``before:`` epoch bounds in the query, returns
  results NEWEST-FIRST (as the real API does) and truncates at
  ``max_results``. Without that fidelity a paging test would prove nothing.

  Gmail documents ``after:``/``before:`` by example and never states whether
  either bound is inclusive, so this fake refuses to pick one on the product's
  behalf: ``boundary`` selects any of the four possible readings
  (:data:`BOUNDARY_READINGS`). The default is the CONSERVATIVE standard one
  (``after:`` inclusive, ``before:`` exclusive); the S1 boundary suite runs
  every reading, because production code that only works under one of them is
  code that silently loses mail under the other three.
* :class:`RecordingLLM` — records every ``complete_json`` call so a test can
  assert the automated-sender guard ran BEFORE any LLM call.

These are test doubles only; no network, no real Gmail, no real LLM.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from app.services.llm_client import LLMUnavailableError

_AFTER = re.compile(r"after:(\d+)")
_BEFORE = re.compile(r"before:(\d+)")

#: Every possible reading of Gmail's ``after:``/``before:`` epoch bounds.
#: ``"after_inclusive"`` (``after:`` ⇒ ``>=``, ``before:`` ⇒ ``<``) is the
#: conservative standard interpretation and the fake's default; the other three
#: exist so the backlog walk can be proven correct WITHOUT depending on which
#: one the live API actually implements.
BOUNDARY_READINGS = ("strict", "after_inclusive", "before_inclusive", "inclusive")


def agent_for(
    repo: Any,
    fake: Any,
    monkeypatch: Any,
    *,
    account_id: str,
    llm: Any = None,
    with_linkedin: bool = False,
    with_digest: bool = False,
) -> Any:
    """A ``SalesAgent`` bound to one FRESH fake sending account.

    A unique ``account_id`` per test matters: the watermark lives in
    ``AdminSetting`` keyed by account id, and the test database is shared for
    the whole session — a shared id would leak one test's watermark into the
    next test's "first sight" assertion.
    """
    from app.agents.sales_agent import SalesAgent  # noqa: PLC0415

    agent = SalesAgent(repo=repo, gmail_factory=lambda uid, aid: fake, llm=llm)
    monkeypatch.setattr(
        repo,
        "sales_sending_accounts",
        lambda user_id: [
            {"id": account_id, "accountEmail": f"{account_id}@aether.local",
             "isPrimary": True}
        ],
    )
    monkeypatch.setattr(agent, "_lifecycle_candidates", lambda: [])
    if not with_linkedin:
        monkeypatch.setattr(agent, "_run_linkedin_draft", lambda **kwargs: None)
    if not with_digest:
        monkeypatch.setattr(agent, "_run_digest", lambda *args, **kwargs: None)
    return agent


def make_message(
    *,
    sender: str,
    subject: str,
    text: str,
    epoch: int | None = None,
    name: str = "Pat Prospect",
) -> dict[str, Any]:
    """One canned inbound message in the shape ``FakeGmail`` serves."""
    msg: dict[str, Any] = {
        "id": f"m-{uuid.uuid4().hex[:12]}",
        "threadId": f"t-{uuid.uuid4().hex[:12]}",
        "from": f"{name} <{sender}>",
        "subject": subject,
        "text": text,
    }
    if epoch is not None:
        msg["internalDate"] = str(int(epoch) * 1000)
    return msg


class WindowedGmail:
    """Gmail double that respects the scan window and the result cap."""

    def __init__(
        self,
        messages: list[dict[str, Any]] | None = None,
        *,
        boundary: str = "after_inclusive",
    ) -> None:
        if boundary not in BOUNDARY_READINGS:
            raise ValueError(f"unknown boundary reading: {boundary!r}")
        self.messages = messages or []
        self.boundary = boundary
        self.sent: list[dict[str, Any]] = []
        self.queries: list[str] = []
        self.max_results: list[int] = []
        self.fetched: list[str] = []

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _epoch(msg: dict[str, Any]) -> int:
        return int(int(msg.get("internalDate") or 0) / 1000)

    def _window(self, query: str | None) -> tuple[int, int]:
        after = _AFTER.search(query or "")
        before = _BEFORE.search(query or "")
        return (
            int(after.group(1)) if after else 0,
            int(before.group(1)) if before else 2**31 - 1,
        )

    def _matches(self, epoch: int, lo: int, hi: int) -> bool:
        """Is ``epoch`` inside ``after:lo before:hi`` under this reading?"""
        lo_ok = epoch >= lo if self.boundary in (
            "after_inclusive", "inclusive"
        ) else epoch > lo
        hi_ok = epoch <= hi if self.boundary in (
            "before_inclusive", "inclusive"
        ) else epoch < hi
        return lo_ok and hi_ok

    # -- Gmail surface -----------------------------------------------------
    def list_message_headers(
        self, query: str | None = None, max_results: int = 100
    ) -> list[dict[str, Any]]:
        self.queries.append(query or "")
        self.max_results.append(max_results)
        lo, hi = self._window(query)
        in_window = [
            m for m in self.messages
            if not m.get("internalDate") or self._matches(self._epoch(m), lo, hi)
        ]
        in_window.sort(key=self._epoch, reverse=True)  # newest first, as Gmail
        return [
            {
                "id": m["id"],
                "threadId": m["threadId"],
                "from": m["from"],
                "subject": m["subject"],
                "date": m.get("date", ""),
                "internalDate": m.get("internalDate"),
            }
            for m in in_window[:max_results]
        ]

    def get_message_bodies(self, message_id: str) -> dict[str, Any]:
        self.fetched.append(message_id)
        m = next(m for m in self.messages if m["id"] == message_id)
        return {
            "id": m["id"],
            "threadId": m["threadId"],
            "from": m["from"],
            "subject": m["subject"],
            "date": m.get("date", ""),
            "internalDate": m.get("internalDate"),
            "text": m["text"],
            "html": "",
        }

    def send(
        self, to, subject, body, in_reply_to=None, thread_id=None,
        attachments=None, html_body=None,
    ):  # noqa: ANN001, ANN201
        self.sent.append({"to": to, "subject": subject, "body": body,
                          "threadId": thread_id, "html_body": html_body})
        suffix = uuid.uuid4().hex[:12]
        return {"id": f"sent-{suffix}", "threadId": thread_id or f"t-{suffix}"}


class RecordingLLM:
    """Records ``complete_json`` / ``complete`` calls; returns canned output."""

    def __init__(
        self,
        payload: Any = None,
        *,
        exc: Exception | None = None,
        text: str | None = None,
        text_exc: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.exc = exc
        self.text = text
        self.text_exc = text_exc
        self.calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []

    def complete_json(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> Any:
        self.calls.append(
            {"prompt": prompt_name, "system": system, "user": user, "kwargs": kwargs}
        )
        if self.exc is not None:
            raise self.exc
        return self.payload

    def complete(self, prompt_name: str, system: str, user: str, **kwargs: Any) -> str:
        self.text_calls.append(
            {"prompt": prompt_name, "system": system, "user": user, "kwargs": kwargs}
        )
        if self.text_exc is not None:
            raise self.text_exc
        if self.text is None:
            raise LLMUnavailableError("test stub: no canned text response")
        return self.text
