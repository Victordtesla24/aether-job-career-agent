"""RT-005 — sustained ambiguous 429s open a SHORT per-model cooldown.

Live incident (2026-08-16 14:15-14:25Z): the subscription credential returned
HTTP 429 with body ``{"message": "Error"}`` — no quota phrase, no long
retry-after — so the conservative quota classifier (correctly) called every
one transient, and the chain paid a doomed live call + backoff on EVERY
attempt for over ten minutes. The fix: after N consecutive real 429s a model
cools for a SHORT window; while cooling, attempts fail fast through the
IDENTICAL failure-handling path (fallback staging, chain rules, disclosure)
without a network call, and a success clears the streak.
"""
from __future__ import annotations

import pytest

from app.services import llm_client as lc


@pytest.fixture(autouse=True)
def _clean_streaks(monkeypatch):
    lc._RATE_LIMIT_STREAKS.clear()
    monkeypatch.setenv("AETHER_MODEL_429_STREAK", "3")
    monkeypatch.setenv("AETHER_MODEL_429_COOLDOWN_SECONDS", "60")
    yield
    lc._RATE_LIMIT_STREAKS.clear()


def test_streak_below_threshold_never_cools():
    lc._note_model_429("m-x")
    lc._note_model_429("m-x")
    assert lc._model_cooling_seconds_left("m-x") == 0.0


def test_threshold_opens_a_short_cooldown_and_success_clears_it():
    for _ in range(3):
        lc._note_model_429("m-x")
    left = lc._model_cooling_seconds_left("m-x")
    assert 0 < left <= 60.0
    lc._clear_model_429("m-x")
    assert lc._model_cooling_seconds_left("m-x") == 0.0


def test_only_http_429_texts_count():
    assert lc._exc_is_http_429(RuntimeError("LLM provider HTTP 429: {...}"))
    assert not lc._exc_is_http_429(RuntimeError("LLM provider HTTP 503: nope"))


class _FakeTransport:
    """Counts live calls; fails every call with a bare ambiguous 429."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, system, user, *, model, temperature, max_seconds=None, **kw):
        self.calls.append(model)
        raise RuntimeError(
            'LLM provider HTTP 429: {"type":"error","error":'
            '{"type":"rate_limit_error","message":"Error"}}'
        )


def _auto_client(monkeypatch, fake):
    """Production runs AETHER_LLM_MODE=auto — the chain loop under test."""
    client = lc.LLMClient(mode="auto")
    monkeypatch.setattr(client, "_call_live", fake)
    return client


def test_cooling_model_fails_fast_without_a_live_call(monkeypatch):
    """Once cooling, the chain must NOT hit the network for that model."""
    fake = _FakeTransport()
    client = _auto_client(monkeypatch, fake)

    # Burn the streak with real (fake-transport) 429s.
    for _ in range(3):
        with pytest.raises(Exception):
            client.complete("tailor", "sys", "user", model="cool-model")
    assert lc._model_cooling_seconds_left("cool-model") > 0
    calls_before = len(fake.calls)

    # While cooling: attempt still fails honestly, but with ZERO new live calls.
    with pytest.raises(Exception) as excinfo:
        client.complete("tailor", "sys", "user", model="cool-model")
    assert len(fake.calls) == calls_before, "cooling attempt must skip the network"
    assert "429" in str(excinfo.value) or "unavailable" in str(excinfo.value).lower()


def test_synthetic_cooling_skip_does_not_extend_its_own_block(monkeypatch):
    fake = _FakeTransport()
    client = _auto_client(monkeypatch, fake)
    for _ in range(3):
        with pytest.raises(Exception):
            client.complete("tailor", "sys", "user", model="cool-model")
    entry = dict(lc._RATE_LIMIT_STREAKS.get("cool-model") or {})
    with pytest.raises(Exception):
        client.complete("tailor", "sys", "user", model="cool-model")
    after = dict(lc._RATE_LIMIT_STREAKS.get("cool-model") or {})
    assert after.get("count") == entry.get("count"), (
        "a synthetic cooling skip must not increment the real-429 streak"
    )


class _FlakyTransport:
    """429 on the first N calls, then valid JSON — the live boundary pattern."""

    def __init__(self, fail_first: int):
        self.fail_first = fail_first
        self.calls: list[str] = []

    def __call__(self, system, user, *, model, temperature, max_seconds=None, **kw):
        self.calls.append(model)
        if len(self.calls) <= self.fail_first:
            raise RuntimeError(
                'LLM provider HTTP 429: {"type":"error","error":'
                '{"type":"rate_limit_error","message":"Error"}}'
            )
        return '{"ok": true}'


class TestRt006SoleModel429Retry:
    """RT-006: a user's explicit single-model pick gets exactly ONE bounded
    same-model retry on a real 429 (live evidence: identical request 429'd
    then served seconds later at the subscription-window boundary)."""

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        monkeypatch.setattr(lc, "_sleep_for_backoff", lambda *_a, **_k: None)

    def test_429_then_success_serves_the_chosen_model(self, monkeypatch):
        fake = _FlakyTransport(fail_first=1)
        client = _auto_client(monkeypatch, fake)
        out = client.complete("tailor", "sys", "user", model="picked-model")
        assert '"ok"' in out
        assert fake.calls == ["picked-model", "picked-model"], (
            "exactly one same-model retry, no substitution"
        )

    def test_at_most_one_retry_then_honest_failure(self, monkeypatch):
        fake = _FlakyTransport(fail_first=99)
        client = _auto_client(monkeypatch, fake)
        with pytest.raises(Exception):
            client.complete("tailor", "sys", "user", model="picked-model")
        assert fake.calls.count("picked-model") == 2, (
            f"one attempt + one retry for the primary only, got {fake.calls}"
        )
        # The chain then honestly consults its fallback (disclosed elsewhere) —
        # the retry never blocks or replaces the existing fallback semantics.
        assert fake.calls[0] == "picked-model" and fake.calls[1] == "picked-model"

    def test_no_retry_while_the_model_is_cooling(self, monkeypatch):
        for _ in range(3):
            lc._note_model_429("picked-model")
        assert lc._model_cooling_seconds_left("picked-model") > 0
        fake = _FlakyTransport(fail_first=99)
        client = _auto_client(monkeypatch, fake)
        with pytest.raises(Exception):
            client.complete("tailor", "sys", "user", model="picked-model")
        assert "picked-model" not in fake.calls, (
            "the cooling model must make zero live calls (fallback models may)"
        )
