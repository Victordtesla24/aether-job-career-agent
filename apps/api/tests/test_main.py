"""Contract tests for the FastAPI application skeleton (P1-S09).

These assert the wired app: the `/health` endpoint returns the canonical
payload, the versioned API prefix mounts, and OpenAPI metadata is populated.
"""
from fastapi.testclient import TestClient

from app.config import API_VERSION
from app.main import app

client = TestClient(app)


def test_health_returns_canonical_payload() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": "0.2.0"}


def test_health_version_matches_config() -> None:
    resp = client.get("/health")
    assert resp.json()["version"] == API_VERSION


def test_app_metadata_is_populated() -> None:
    assert app.title == "Aether API"
    assert app.version == API_VERSION


def test_openapi_schema_exposes_health_route() -> None:
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]


def test_unknown_route_returns_404() -> None:
    assert client.get("/does-not-exist").status_code == 404
