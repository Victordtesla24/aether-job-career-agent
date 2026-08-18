"""AUD-ECON-1 (r2) — the Sales Agent's own runs must disclose which model
actually served them, exactly like every other agent already does.

Verified finding (evidence: docs/delivery/evidence/RUN-20260818T0223Z/AUD-ECON-1/
09-reverify-vs-foreign.md): ``app/agents/sales_agent.py`` never opens
``served_model_capture()`` around its LLM-calling spans, so
``get_last_served_model()`` always reads ``None`` inside it and every
``AgentRunRepository.finish()`` call for ``salesAgent`` records no
``servedModel``/``servedProvider`` — the exact silence CLI-D5 already closed
for every OTHER agent via ``app.routers.agents._record_run``
(agents.py:1604-1606, see ``test_cli_d5_served_model_disclosure.py``).

Contract pinned here (mirrors D5's contract, Track E):

1. A ``salesAgent`` run whose work made a REAL LLM call carries additive
   ``servedModel`` + ``servedProvider`` keys in its output — on BOTH terminal
   paths (``generate_marketing_content`` and ``run``) — gated on the
   provider-published observation itself (``get_last_served_model()``), and
   resolved to a provider with the SAME pure function the billing audit uses
   (``resolve_provider``).
2. The disclosure survives onto the persisted ``AgentRun`` row (the ``output``
   argument passed to ``AgentRunRepository.finish``), on BOTH the completed
   and the failed/degraded terminal path.
3. A run that made NO successful live call — because every LLM span was
   skipped/disabled, or because every attempt failed before any success —
   carries NEITHER key. Nothing is ever fabricated.

The LLM spans are exercised through a REAL ``LLMClient(mode="auto", ...)``
against a mocked ``httpx.post`` transport (the exact seam
``test_cli_d5_served_model_disclosure.py`` uses for coverLetter) so the
observation this file asserts on is the real provider-publish path
(``llm_client._publish_served_model``), never a hand-set attribute. Every
other collaborator (``SalesRepository``, ``AgentRunRepository``, the Stripe
promo gateway) is an in-memory fake — the SAME technique this file's sibling
suite already uses for ``SalesAgent.run()`` control-flow assertions (see
``test_sales_agent.py::test_default_live_scope_skips_lifecycle_but_keeps_inbound_polling``),
so nothing here depends on seeded DB rows.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.agents.sales_agent import SalesAgent
from app.services.llm_client import LLMClient
from app.services.stripe_gateway import StripeNotConfiguredError
from tests.test_cli_d5_served_model_disclosure import (  # noqa: F401 — reused fixture/helpers
    _CHEAP_PRIMARY,
    _Resp,
    _install_transport,
    _ok,
    openrouter_env,
)

#: Grounding-guard-safe (no dollar amounts, no percentages, no invented
#: counts) AND splittable on "===" — the ONE canned body used for every
#: mocked live call in this file. ``_generate_campaigns``/``_run_linkedin_draft``
#: use it whole (a real "===" inside a campaign template is harmless — these
#: tests never assert on template prose); ``_generate_linkedin_drafts`` splits
#: it into exactly three non-empty posts, matching the ``count=3`` the
#: production call always requests.
_SAFE_COPY = (
    "Aether sources roles from licensed job APIs and tailors your resume "
    "against your own story bank.\n"
    "===\n"
    "The agent waits for your yes before anything goes out.\n"
    "===\n"
    "Approval queues keep every claim traceable to your real history."
)


# ---------------------------------------------------------------------------
# In-memory fakes — mirrors tests/test_sales_agent.py's FakeRepo/FakeRuns style.
# ---------------------------------------------------------------------------


class _FakeRuns:
    """Stand-in for ``AgentRunRepository`` — records every start/finish call
    so the test can assert on the EXACT dict persisted, without a DB row."""

    def __init__(self) -> None:
        self.started: list[tuple[Any, ...]] = []
        self.finished: list[dict[str, Any]] = []

    def start(self, admin_id: str, agent_key: str, meta: dict[str, Any]) -> dict[str, Any]:
        self.started.append((admin_id, agent_key, meta))
        return {"id": f"run-{len(self.started)}"}

    def finish(
        self, run_id: str, status: str, output: Any = None, error: str | None = None
    ) -> None:
        self.finished.append(
            {"run_id": run_id, "status": status, "output": output, "error": error}
        )


class _FakeSalesRepo:
    """In-memory stand-in for ``SalesRepository`` — implements only the
    surface ``generate_marketing_content``/``run`` actually call in these
    tests."""

    def __init__(self) -> None:
        self._campaigns: list[dict[str, Any]] = []
        self.outreach: list[dict[str, Any]] = []
        self._linkedin_campaign: dict[str, Any] | None = None
        self._reserve_result: dict[str, Any] = {
            "reserved": True, "reservationId": "r-1", "queuedLast7d": 0,
        }

    # -- generate_marketing_content -----------------------------------
    def list_campaigns(self) -> list[dict[str, Any]]:
        return list(self._campaigns)

    def create_campaign(
        self, *, name: str, ctype: str, template_body: str, active: bool
    ) -> dict[str, Any]:
        row = {
            "id": f"camp-{len(self._campaigns) + 1}", "name": name, "type": ctype,
            "templateBody": template_body, "active": active,
        }
        self._campaigns.append(row)
        return row

    def active_campaign_by_type(self, ctype: str) -> dict[str, Any] | None:
        if ctype == "linkedin_draft":
            return self._linkedin_campaign
        for c in self._campaigns:
            if c["type"] == ctype and c["active"]:
                return c
        return None

    def record_outreach(self, **kwargs: Any) -> dict[str, Any]:
        self.outreach.append(kwargs)
        return {"id": f"out-{len(self.outreach)}"}

    # -- run() ------------------------------------------------------------
    def seed_default_campaigns(self) -> int:
        return 0

    def sales_sending_accounts(self, user_id: str) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def prune_orphan_watermarks(active_account_ids: tuple[str, ...] = ()) -> int:
        return 0

    def reserve_linkedin_draft_slot(self, **kwargs: Any) -> dict[str, Any]:
        return dict(self._reserve_result)

    def release_linkedin_draft_slot(self, reservation_id: str) -> bool:
        return True

    def finalize_linkedin_draft(self, reservation_id: str, **kwargs: Any) -> dict[str, Any]:
        return {"id": "draft-1", **kwargs}


class _NoStripe:
    """Promo gateway stand-in: Stripe genuinely not configured in the test
    environment — the honest, already-handled degrade branch of
    ``_generate_promo``, never a crash."""

    def list_promotion_codes(self) -> list[dict[str, Any]]:
        raise StripeNotConfiguredError("test: stripe not configured")


@pytest.fixture()
def fake_runs(monkeypatch) -> _FakeRuns:
    """ONE ``_FakeRuns`` instance shared by every ``AgentRunRepository()``
    construction the method under test performs — the class is patched to a
    factory that always returns THIS instance, so the test can inspect what
    was actually persisted (``fake_runs.finished``) instead of losing the
    record to a second, freshly-constructed fake."""
    runs = _FakeRuns()
    monkeypatch.setattr("app.agents.sales_agent.AgentRunRepository", lambda: runs)
    return runs


@pytest.fixture()
def sales_wiring(monkeypatch, fake_runs):
    """Everything ``generate_marketing_content``/``run`` need that is NOT the
    LLM call itself: feature gate on, admin resolution, config seeding, model
    resolution and the run-record repository — all faked/env-set so these
    tests exercise ONLY the served-model observation-and-disclosure wiring,
    never DB seeding or Gmail/Stripe integration (those are covered by
    test_sales_agent.py and its siblings)."""
    monkeypatch.setenv("AETHER_SALES_AGENT_ENABLED", "true")
    monkeypatch.setattr(
        "app.agents.sales_agent.resolve_admin_user_id", lambda: "admin-econ1-test"
    )
    monkeypatch.setattr("app.agents.sales_agent.ensure_agent_config", lambda admin_id: None)
    monkeypatch.setattr(
        "app.agents.sales_agent.resolve_model", lambda: (_CHEAP_PRIMARY, "test")
    )
    return fake_runs


def _responder_success_then_failure(n_success: int):
    """Succeed on the first ``n_success`` live calls (publishing
    ``_CHEAP_PRIMARY`` as served), then 500 every call after — the shape
    needed to prove the degrade path discloses the LAST model that actually
    served, not the one that failed."""
    calls = {"n": 0}

    def responder(asked_model: str) -> _Resp:
        calls["n"] += 1
        if calls["n"] <= n_success:
            return _ok(_SAFE_COPY, _CHEAP_PRIMARY)
        return _Resp(500, "upstream failure")

    return responder


# ---------------------------------------------------------------------------
# 1. generate_marketing_content — happy path discloses the served model.
# ---------------------------------------------------------------------------


def test_generate_marketing_content_discloses_served_model_on_completion(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """FAILS on unpatched sales_agent.py: no ``served_model_capture()`` scope
    is ever opened, so ``get_last_served_model()`` reads ``None`` and neither
    key is ever written — even though three real LLM calls just succeeded."""
    _install_transport(monkeypatch, lambda m: _ok(_SAFE_COPY, _CHEAP_PRIMARY))
    agent = SalesAgent(
        repo=_FakeSalesRepo(), promo_gateway=_NoStripe(),
        llm=LLMClient(mode="auto", fixture_dir=tmp_path),
    )

    result = agent.generate_marketing_content(trigger="admin")

    assert result["ran"] is True
    assert len(result["campaignsCreated"]) == 2, "both campaign specs must have generated"
    assert result["linkedinDrafts"] == 3
    assert result["servedModel"] == _CHEAP_PRIMARY, (
        "the run output must name the model that ACTUALLY served every LLM "
        "call this run made"
    )
    assert result["servedProvider"] == "openrouter", (
        "the disclosure must name the billing provider too, resolved with "
        "the same pure function the billing audit uses"
    )


def test_generate_marketing_content_disclosure_is_persisted_on_the_run_row(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """The persisted ``AgentRun.output`` (what ``GET /agents/runs`` and the
    admin UI actually read) must carry the same disclosure as the HTTP-shaped
    return value, not only the in-memory dict."""
    _install_transport(monkeypatch, lambda m: _ok(_SAFE_COPY, _CHEAP_PRIMARY))
    agent = SalesAgent(
        repo=_FakeSalesRepo(), promo_gateway=_NoStripe(),
        llm=LLMClient(mode="auto", fixture_dir=tmp_path),
    )

    agent.generate_marketing_content(trigger="admin")

    assert sales_wiring.finished, "runs.finish() must have been called"
    stored_output = sales_wiring.finished[-1]["output"]
    assert stored_output["servedModel"] == _CHEAP_PRIMARY
    assert stored_output["servedProvider"] == "openrouter"
    assert sales_wiring.finished[-1]["status"] == "completed"


# ---------------------------------------------------------------------------
# 2. generate_marketing_content — degrade path still discloses (the LAST
#    model that actually served, from before the failure that ended the run).
# ---------------------------------------------------------------------------


def test_generate_marketing_content_failure_after_a_successful_call_discloses_it(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """FAILS on unpatched sales_agent.py: the ``except Exception`` branch
    that finishes the run 'failed' never reads ``get_last_served_model()`` —
    even though the FIRST campaign genuinely got served before the SECOND
    campaign's call exhausted its retry chain and raised."""
    _install_transport(monkeypatch, _responder_success_then_failure(1))
    agent = SalesAgent(
        repo=_FakeSalesRepo(), promo_gateway=_NoStripe(),
        llm=LLMClient(mode="auto", fixture_dir=tmp_path),
    )

    result = agent.generate_marketing_content(trigger="admin")

    assert result["errors"], "the second campaign's exhausted retry chain must be recorded"
    assert result["servedModel"] == _CHEAP_PRIMARY, (
        "a degraded run that made one real successful call before failing "
        "must still disclose what served it"
    )
    assert result["servedProvider"] == "openrouter"
    assert sales_wiring.finished[-1]["status"] == "failed"
    assert sales_wiring.finished[-1]["output"]["servedModel"] == _CHEAP_PRIMARY
    assert sales_wiring.finished[-1]["output"]["servedProvider"] == "openrouter"


def test_generate_marketing_content_failure_before_any_success_discloses_nothing(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """PIN (passes before and after the fix): every attempt fails before any
    successful call — nothing was ever observed, so nothing may be disclosed."""
    _install_transport(monkeypatch, lambda m: _Resp(500, "upstream failure"))
    agent = SalesAgent(
        repo=_FakeSalesRepo(), promo_gateway=_NoStripe(),
        llm=LLMClient(mode="auto", fixture_dir=tmp_path),
    )

    result = agent.generate_marketing_content(trigger="admin")

    assert result["errors"]
    assert "servedModel" not in result
    assert "servedProvider" not in result
    assert sales_wiring.finished[-1]["status"] == "failed"
    assert "servedModel" not in sales_wiring.finished[-1]["output"]
    assert "servedProvider" not in sales_wiring.finished[-1]["output"]


# ---------------------------------------------------------------------------
# 3. run() — happy path (the LinkedIn-drafting span) discloses the served
#    model on the completed terminal path.
# ---------------------------------------------------------------------------


def test_run_discloses_served_model_via_linkedin_draft(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """FAILS on unpatched sales_agent.py: ``run()`` never opens
    ``served_model_capture()`` either, so a manual/timer run that drafted a
    real, LLM-authored LinkedIn post still discloses nothing about what
    served it."""
    _install_transport(monkeypatch, lambda m: _ok(_SAFE_COPY, _CHEAP_PRIMARY))
    repo = _FakeSalesRepo()
    repo._linkedin_campaign = {
        "id": "camp-li-1", "templateBody": "Write about the anti-fabrication guard.",
    }
    agent = SalesAgent(repo=repo, llm=LLMClient(mode="auto", fixture_dir=tmp_path))
    monkeypatch.setattr(agent, "_run_digest", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_run_network_nurture", lambda *a, **k: None)

    result = agent.run(trigger="manual")

    assert result["linkedinDrafts"] == 1
    assert result["servedModel"] == _CHEAP_PRIMARY
    assert result["servedProvider"] == "openrouter"
    assert sales_wiring.finished[-1]["status"] == "completed"
    assert sales_wiring.finished[-1]["output"]["servedModel"] == _CHEAP_PRIMARY
    assert sales_wiring.finished[-1]["output"]["servedProvider"] == "openrouter"


def test_run_discloses_served_model_on_the_failed_terminal_path(
    monkeypatch, openrouter_env, sales_wiring, tmp_path
):
    """FAILS on unpatched sales_agent.py: the ``except Exception`` branch in
    ``run()`` never reads ``get_last_served_model()`` — a run that genuinely
    served a real LinkedIn draft and THEN failed in a later step must still
    disclose the model that served the work it did complete."""
    _install_transport(monkeypatch, lambda m: _ok(_SAFE_COPY, _CHEAP_PRIMARY))
    repo = _FakeSalesRepo()
    repo._linkedin_campaign = {
        "id": "camp-li-1", "templateBody": "Write about the human approval queue.",
    }
    agent = SalesAgent(repo=repo, llm=LLMClient(mode="auto", fixture_dir=tmp_path))

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("digest transport unreachable")

    monkeypatch.setattr(agent, "_run_digest", _boom)
    monkeypatch.setattr(agent, "_run_network_nurture", lambda *a, **k: None)

    result = agent.run(trigger="manual")

    assert result["errors"] and "digest transport unreachable" in result["errors"][-1]
    assert result["servedModel"] == _CHEAP_PRIMARY, (
        "the LinkedIn draft genuinely served before the later digest step "
        "failed — that observation must survive onto the failed run"
    )
    assert result["servedProvider"] == "openrouter"
    assert sales_wiring.finished[-1]["status"] == "failed"
    assert sales_wiring.finished[-1]["output"]["servedModel"] == _CHEAP_PRIMARY
    assert sales_wiring.finished[-1]["output"]["servedProvider"] == "openrouter"


def test_run_with_no_llm_call_discloses_nothing(monkeypatch, openrouter_env, sales_wiring):
    """PIN (passes before and after the fix): drafting switched off
    (``AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK=0``), no sending accounts, no
    lifecycle scope — a fully deterministic run makes zero LLM calls and must
    disclose nothing."""
    monkeypatch.setenv("AETHER_SALES_LINKEDIN_DRAFTS_PER_WEEK", "0")
    agent = SalesAgent(repo=_FakeSalesRepo())
    monkeypatch.setattr(agent, "_run_digest", lambda *a, **k: None)
    monkeypatch.setattr(agent, "_run_network_nurture", lambda *a, **k: None)

    result = agent.run(trigger="manual")

    assert result["linkedinDrafts"] == 0
    assert "servedModel" not in result
    assert "servedProvider" not in result
    assert sales_wiring.finished[-1]["status"] == "completed"
    assert "servedModel" not in sales_wiring.finished[-1]["output"]
    assert "servedProvider" not in sales_wiring.finished[-1]["output"]
