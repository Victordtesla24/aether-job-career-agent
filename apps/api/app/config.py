"""Application configuration for the Aether API (P1-S09).

Settings are read from the environment (and an optional `.env`) via
pydantic-settings. Secrets such as ``OPENROUTER_API_KEY`` are declared here so
they can be injected where needed, but their values are never logged or echoed.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Semantic version of the API surface. Bumped as the API contract evolves.
API_VERSION = "0.1.0"

#: Human-facing service title (also used as the OpenAPI title).
API_TITLE = "Aether API"


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables.

    Unknown environment variables are ignored so the shared root `.env`
    (which also holds web/db settings) can be reused without validation errors.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_title: str = API_TITLE
    api_version: str = API_VERSION
    # Optional integrations — absent in unit tests / offline runs.
    database_url: str | None = None
    redis_url: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Present only at runtime; never logged. Left optional so the app boots
    # without it (agent calls that need it fail loudly at call time instead).
    openrouter_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
