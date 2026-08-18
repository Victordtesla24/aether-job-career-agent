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
