"""LOOP-429 — a provider 429 503 must tell the client when to retry.

Production 2026-08-18 (Career Search Operating Loop): Resume Tailoring returned
the honest rate-limit sentence as HTTP 503 with NO ``Retry-After``. The map
batch halted immediately. The LLM client had already spent its one 2–5 s
same-model retry (RT-006). A 15-minute per-model cooldown (RT-005 default 900 s)
still told the subscriber to "wait a minute".

These tests pin the header contract BEFORE the router grows it. Written first.
"""
from __future__ import annotations

import inspect

from app.services.llm_client import (
    LLM_FAILURE_INSUFFICIENT_CREDITS,
    LLMUnavailableError,
    ProviderAuthError,
    llm_retry_after_http_headers,
)


def test_rate_limit_429_advertises_a_one_minute_retry_after() -> None:
    exc = LLMUnavailableError(
        "LLM backend unavailable: live call failed: LLM provider HTTP 429: "
        "rate_limit_error"
    )
    headers = llm_retry_after_http_headers(exc)
    assert headers.get("Retry-After") == "60"


def test_cooling_429_advertises_the_remaining_cooldown() -> None:
    exc = LLMUnavailableError(
        "LLM provider HTTP 429 (cooling): model claude-opus-4-8 is "
        "rate-limited; cooldown ends in 812s"
    )
    headers = llm_retry_after_http_headers(exc)
    assert headers.get("Retry-After") == "812"


def test_insufficient_credits_does_not_advertise_retry_after() -> None:
    exc = LLMUnavailableError(
        "openrouter 402",
        failure_class=LLM_FAILURE_INSUFFICIENT_CREDITS,
    )
    assert llm_retry_after_http_headers(exc) == {}


def test_provider_auth_failure_does_not_advertise_retry_after() -> None:
    exc = ProviderAuthError("401 rejected")
    assert llm_retry_after_http_headers(exc) == {}


def test_generic_retryable_outage_does_not_pretend_a_wait_helps() -> None:
    exc = LLMUnavailableError("boom")
    assert llm_retry_after_http_headers(exc) == {}


def test_record_run_attaches_the_retry_after_headers() -> None:
    from app.routers.agents import _execute_reserved_run, _record_run

    # GAP-P7-ASYNC-001 extracted the LLM 503 from ``_record_run`` into
    # ``_execute_reserved_run`` so the sync HTTP path and the ARQ worker share
    # one raise site. Headers must live on THAT raise, and ``_record_run``
    # must still delegate so it cannot skip them.
    src = inspect.getsource(_execute_reserved_run)
    assert "llm_retry_after_http_headers" in src, (
        "_execute_reserved_run must attach llm_retry_after_http_headers on the "
        "LLMUnavailableError 503 so the operating-loop client can wait"
    )
    assert "headers=" in src
    wrapper = inspect.getsource(_record_run)
    assert "_execute_reserved_run" in wrapper


def test_worker_reads_retry_after_off_the_http_503_the_browser_never_sees() -> None:
    """Production Career Search is async: tailor 429 is raised inside the job.

    The browser polls GET /agents/jobs/{id} and never receives the HTTP 503
    headers. The worker must lift Retry-After off the HTTPException.
    """
    from fastapi import HTTPException
    from starlette import status as http_status

    from app.services.llm_client import LLM_RATE_LIMITED_USER_MESSAGE
    from app.workers.tasks import _honest_message, _retry_after_seconds

    exc = HTTPException(
        http_status.HTTP_503_SERVICE_UNAVAILABLE,
        LLM_RATE_LIMITED_USER_MESSAGE,
        headers={"Retry-After": "812"},
    )
    assert _honest_message(exc) == LLM_RATE_LIMITED_USER_MESSAGE
    assert _retry_after_seconds(exc) == 812


def test_job_status_payload_forwards_retry_after_seconds() -> None:
    from app.routers.agents import _job_status_payload

    payload = _job_status_payload(
        {
            "id": "job-429",
            "status": "failed",
            "agentKey": "tailor",
            "result": None,
            "error": "The AI provider rate-limited this run.",
            "createdAt": None,
            "startedAt": None,
            "finishedAt": None,
            "retryAfterSeconds": 812,
        }
    )
    assert payload["retryAfterSeconds"] == 812
    assert payload["error"] == "The AI provider rate-limited this run."
    assert payload["status"] == "failed"


def test_mark_failed_persists_retry_after_seconds_for_the_poll_client(
    test_user_id: str,
) -> None:
    """The worker's HTTP 503 headers never reach the browser. The seconds must
    round-trip on the job row ``GET /agents/jobs/{id}`` already polls."""
    from app.repositories.background_jobs import (
        BackgroundJobRepository,
        _reset_bg_ready_for_tests,
    )
    from app.routers.agents import _job_status_payload

    _reset_bg_ready_for_tests()
    repo = BackgroundJobRepository()
    job_id = repo.create(test_user_id, "tailor")
    assert repo.mark_processing(job_id) is not None
    assert repo.mark_failed(
        job_id,
        "The AI provider rate-limited this run.",
        retry_after_seconds=812,
    )
    row = repo.get(job_id)
    assert row is not None
    assert row["status"] == "failed"
    assert row["retryAfterSeconds"] == 812
    assert _job_status_payload(row)["retryAfterSeconds"] == 812
