"""Adapter registry (P2-S02): map a source key to its adapter class.

Allows runtime selection of which job boards the Scout agent queries and keeps
the router decoupled from concrete adapter imports.
"""
from __future__ import annotations

from app.services.discovery.base_adapter import BaseAdapter
from app.services.discovery.indeed_adapter import IndeedAdapter
from app.services.discovery.linkedin_adapter import LinkedInAdapter
from app.services.discovery.seek_adapter import SeekAdapter

#: Source key → adapter class.
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    SeekAdapter.source: SeekAdapter,
    LinkedInAdapter.source: LinkedInAdapter,
    IndeedAdapter.source: IndeedAdapter,
}

#: Sources queried by the Scout agent in production, in priority order.
DEFAULT_SOURCES: tuple[str, ...] = (
    SeekAdapter.source,
    LinkedInAdapter.source,
    IndeedAdapter.source,
)


def build_adapters(sources: tuple[str, ...] = DEFAULT_SOURCES) -> list[BaseAdapter]:
    """Instantiate live (non-fixture) adapters for the given source keys."""
    return [ADAPTER_REGISTRY[name]() for name in sources if name in ADAPTER_REGISTRY]
