"""Post-review hardening — LLM client resilience + router 503 mapping (D-0014).

An independent review found that stale OpenRouter model ids caused live 500s
on the LLM agent endpoints. These tests lock in the fix:
- ``auto`` mode falls back to the recorded fixture when live calls fail;
- the model chain retries once with the fallback model before giving up;
- routers convert :class:`LLMUnavailableError` into HTTP 503 (never 500).
"""
from __future__ import annotations

import json

import pytest

from app.services.llm_client import (
    FALLBACK_MODEL,
    LLMClient,
    LLMUnavailableError,
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


class TestRouter503Mapping:
    def test_tailor_returns_503_not_500_when_llm_unavailable(
        self, client, auth_headers, monkeypatch
    ):
        job = _seed_job(client, auth_headers)
        from app.agents import tailor_agent as tailor_module

        def _boom(self, user_id, job_id):
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

        def _boom(self, user_id, job_id):
            raise LLMUnavailableError("LLM backend unavailable: simulated outage")

        monkeypatch.setattr(cl_module.CoverLetterAgent, "run", _boom)
        resp = client.post(
            "/agents/cover-letter/run", json={"job_id": job["id"]}, headers=auth_headers
        )
        assert resp.status_code == 503
        runs = client.get("/agents/runs", headers=auth_headers).json()
        failed = [r for r in runs if r["agentName"] == "coverLetter"]
        assert failed and failed[0]["status"] == "failed"
