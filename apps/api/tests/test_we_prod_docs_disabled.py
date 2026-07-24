"""W-E quality sweep — interactive API docs must not ship on production.

The prod hygiene audit (spec §7.3) found `/docs`, `/redoc` and
`/openapi.json` served with 200 on the live deployment. Interactive schema
explorers are debug surfaces: they enumerate every endpoint and request
shape for anonymous visitors. ``create_app()`` must disable them when
``AETHER_ENV=production`` and keep them available in development.
"""
from __future__ import annotations

import pytest

from app.main import create_app


@pytest.fixture(autouse=True)
def _non_replay_llm_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the §REC-04 replay guard out of the way for production app builds.
    monkeypatch.setenv("AETHER_LLM_MODE", "auto")


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_endpoints_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("AETHER_ENV", "production")
    app = create_app()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_docs_endpoints_available_in_development(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("AETHER_ENV", "development")
    app = create_app()
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get(path).status_code == 200
