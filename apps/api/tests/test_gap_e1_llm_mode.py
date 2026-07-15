"""GAP-E1 (HIGH): production replay-mode guard (§REC-04).

``AETHER_LLM_MODE`` defaults to ``replay`` (see ``app.services.llm_client.get_mode``).
That default is correct for local dev/tests but must never reach production — a
misconfigured deploy would silently serve canned fixture responses instead of
real model output. ``create_app()`` must fail fast when
``AETHER_ENV=production`` and the effective LLM mode is ``replay``, and only
warn (never raise) otherwise.
"""
from __future__ import annotations

import pytest

from app.main import create_app


def test_replay_mode_in_production_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_LLM_MODE", "replay")

    with pytest.raises(RuntimeError, match="REC-04"):
        create_app()


@pytest.mark.parametrize("mode", ["auto", "live", "record"])
def test_non_replay_modes_in_production_do_not_raise(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_LLM_MODE", mode)

    create_app()  # must not raise


def test_replay_mode_in_development_warns_but_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv("AETHER_ENV", "development")
    monkeypatch.setenv("AETHER_LLM_MODE", "replay")

    create_app()  # must not raise

    captured = capsys.readouterr()
    assert "replay" in captured.err.lower()


def test_replay_mode_with_no_aether_env_set_warns_but_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("AETHER_ENV", raising=False)
    monkeypatch.setenv("AETHER_LLM_MODE", "replay")

    create_app()  # default AETHER_ENV is not production; must not raise

    captured = capsys.readouterr()
    assert "replay" in captured.err.lower()
