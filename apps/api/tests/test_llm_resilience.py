"""Post-review hardening — LLM client resilience + router 503 mapping (D-0014).

An independent review found that stale OpenRouter model ids caused live 500s
on the LLM agent endpoints. These tests lock in the fix:
- ``auto`` mode falls back to the recorded fixture when live calls fail;
- the model chain retries once with the fallback model before giving up;
- routers convert :class:`LLMUnavailableError` into HTTP 503 (never 500).
"""
from __future__ import annotations

import json
import time

import pytest

from app.services.llm_client import (
    FALLBACK_MODEL,
    LLMClient,
    LLMUnavailableError,
    get_budget_seconds,
    shared_budget,
)


def _seed_job(client, auth_headers) -> dict:
    run = client.post(
        "/agents/scout/run",
        json={"query": "python engineer", "location": "Sydney"},
        headers=auth_headers,
    )
    assert run.status_code == 202
    return client.get("/jobs", headers=auth_headers).json()[0]


class TestModelChain:
    def test_retries_once_with_fallback_model(self):
        assert LLMClient._model_chain("openai/gpt-oss-120b:free") == [
            "openai/gpt-oss-120b:free",
            FALLBACK_MODEL,
        ]

    def test_no_duplicate_attempt_when_primary_is_fallback(self):
        assert LLMClient._model_chain(FALLBACK_MODEL) == [FALLBACK_MODEL]


class TestAutoModeFallback:
    def test_auto_falls_back_to_fixture_when_live_fails(self, tmp_path, monkeypatch):
        fixture = tmp_path / "demo_prompt" / "default.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"content": "canned answer"}))
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient,
            "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 404")),
        )
        assert llm.complete("demo_prompt", "sys", "usr") == "canned answer"

    def test_auto_raises_unavailable_when_no_fixture(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient,
            "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("HTTP 429")),
        )
        with pytest.raises(LLMUnavailableError):
            llm.complete("no_such_prompt", "sys", "usr")

    def test_auto_records_fixture_on_live_success(self, tmp_path, monkeypatch):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", lambda self, *a, **k: "live answer")
        assert llm.complete("recorded_prompt", "sys", "usr") == "live answer"
        recorded = tmp_path / "recorded_prompt" / "default.json"
        assert json.loads(recorded.read_text())["content"] == "live answer"


class TestTimeBudget:
    """Fix for the >120s cover-letter hang: strict per-call timeouts plus an
    overall wall-clock budget for the whole fallback chain."""

    def test_budget_exhausted_skips_live_and_serves_fixture(self, tmp_path, monkeypatch):
        fixture = tmp_path / "slow_prompt" / "default.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"content": "fixture within budget"}))
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        llm._deadline = time.monotonic() - 1  # budget already spent

        def _never(self, *a, **k):
            raise AssertionError("live call attempted after budget exhausted")

        monkeypatch.setattr(LLMClient, "_call_live", _never)
        assert llm.complete("slow_prompt", "sys", "usr") == "fixture within budget"

    def test_budget_exhausted_raises_typed_error_without_fixture(
        self, tmp_path, monkeypatch
    ):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        llm._deadline = time.monotonic() - 1
        monkeypatch.setattr(
            LLMClient,
            "_call_live",
            lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("no live")),
        )
        with pytest.raises(LLMUnavailableError):
            llm.complete("no_fixture_prompt", "sys", "usr")

    def test_live_call_receives_remaining_budget_cap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "42")
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        seen: dict[str, float] = {}

        def _capture(self, *a, **k):
            seen["max_seconds"] = k["max_seconds"]
            return "ok"

        monkeypatch.setattr(LLMClient, "_call_live", _capture)
        assert llm.complete("budget_prompt", "sys", "usr") == "ok"
        assert 0 < seen["max_seconds"] <= 42

    def test_budget_env_default_and_bad_value(self, monkeypatch):
        monkeypatch.delenv("AETHER_LLM_BUDGET_SECONDS", raising=False)
        assert get_budget_seconds() == 60.0
        monkeypatch.setenv("AETHER_LLM_BUDGET_SECONDS", "not-a-number")
        assert get_budget_seconds() == 60.0


class TestHardWallClockCap:
    """D1 regression (Phase-2 audit): trickling provider responses used to
    outlive the budget by minutes (httpx read timeouts are per-chunk), causing
    edge 524s on /agents/cover-letter/run and /agents/pipeline/run."""

    def test_trickling_live_call_is_abandoned_at_hard_cap(self, monkeypatch):
        import httpx

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        def _slow_post(*a, **k):  # simulates a response trickling past any read timeout
            time.sleep(2.0)
            raise AssertionError("request should have been abandoned")

        monkeypatch.setattr(httpx, "post", _slow_post)
        llm = LLMClient(mode="live")
        start = time.monotonic()
        with pytest.raises(RuntimeError, match="hard budget"):
            llm._call_live("sys", "usr", model="m", temperature=0.0, max_seconds=0.2)
        assert time.monotonic() - start < 1.5  # cut off, not held hostage

    def test_shared_budget_bounds_all_clients_in_scope(self, tmp_path, monkeypatch):
        """The pipeline shares ONE budget across tailor + coverLetter clients."""
        fixture = tmp_path / "shared_prompt" / "default.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"content": "canned"}))

        def _no_live(self, *a, **k):
            raise AssertionError("live call attempted after shared budget expired")

        monkeypatch.setattr(LLMClient, "_call_live", _no_live)
        with shared_budget(0.0):  # already exhausted
            for _ in range(2):  # fresh clients, as the pipeline constructs them
                llm = LLMClient(mode="auto", fixture_dir=tmp_path)
                assert llm.complete("shared_prompt", "sys", "usr") == "canned"

    def test_provider_base_url_is_configurable(self, monkeypatch):
        """AETHER_LLM_BASE_URL/API_KEY allow any OpenAI-compatible provider
        (e.g. Anthropic's compat endpoint) without a code change."""
        import httpx

        monkeypatch.setenv("AETHER_LLM_BASE_URL", "https://api.anthropic.com/v1")
        monkeypatch.setenv("AETHER_LLM_API_KEY", "sk-ant-test")
        seen: dict[str, object] = {}

        class _Resp:
            status_code = 200

            @staticmethod
            def json() -> dict:
                return {"choices": [{"message": {"content": "hello"}}]}

        def _capture(url, **kwargs):
            seen["url"] = url
            seen["auth"] = kwargs["headers"]["Authorization"]
            return _Resp()

        monkeypatch.setattr(httpx, "post", _capture)
        llm = LLMClient(mode="live")
        out = llm._call_live("sys", "usr", model="claude-test", temperature=0.0)
        assert out == "hello"
        assert seen["url"] == "https://api.anthropic.com/v1/chat/completions"
        assert seen["auth"] == "Bearer sk-ant-test"


class TestGracefulDegradation:
    """Malformed live output and missing retry fixtures degrade, never 500."""

    def test_missing_retry_fixture_key_degrades_to_default(self, tmp_path, monkeypatch):
        fixture = tmp_path / "letter_prompt" / "default.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"content": "default letter"}))
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        def _boom(self, *a, **k):
            raise RuntimeError("429")

        monkeypatch.setattr(LLMClient, "_call_live", _boom)
        # "retry2" was never recorded — must serve default, not raise/503.
        assert llm.complete("letter_prompt", "s", "u", fixture_key="retry2") == "default letter"

    def test_malformed_live_json_falls_back_to_fixture(self, tmp_path, monkeypatch):
        fixture = tmp_path / "json_prompt" / "default.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text(json.dumps({"content": '{"stories": []}'}))
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(
            LLMClient, "_call_live", lambda self, *a, **k: '{"stories": [{"title": "trunc'
        )
        assert llm.complete_json("json_prompt", "s", "u") == {"stories": []}

    def test_malformed_live_json_without_fixture_raises_typed_error(
        self, tmp_path, monkeypatch
    ):
        llm = LLMClient(mode="auto", fixture_dir=tmp_path)
        monkeypatch.setattr(LLMClient, "_call_live", lambda self, *a, **k: "not json {")
        with pytest.raises(LLMUnavailableError):
            llm.complete_json("json_prompt_missing", "s", "u")


class TestRouter503Mapping:
    def test_tailor_returns_503_not_500_when_llm_unavailable(
        self, client, auth_headers, monkeypatch
    ):
        job = _seed_job(client, auth_headers)
        from app.agents import tailor_agent as tailor_module

        def _boom(self, user_id, job_id, resume_id=None):
            raise LLMUnavailableError("LLM backend unavailable: simulated outage")

        monkeypatch.setattr(tailor_module.TailoringAgent, "run", _boom)
        resp = client.post(
            "/agents/tailor/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["detail"] == "LLM backend unavailable"

    def test_failed_run_is_audited(self, client, auth_headers, monkeypatch):
        job = _seed_job(client, auth_headers)
        from app.agents import cover_letter_agent as cl_module

        def _boom(self, user_id, job_id, resume_id=None):
            raise LLMUnavailableError("LLM backend unavailable: simulated outage")

        monkeypatch.setattr(cl_module.CoverLetterAgent, "run", _boom)
        resp = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 503
        runs = client.get("/agents/runs", headers=auth_headers).json()
        failed = [r for r in runs if r["agentName"] == "coverLetter"]
        assert failed and failed[0]["status"] == "failed"
